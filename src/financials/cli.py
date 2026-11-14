"""Command line for the local machine.  `python -m financials --help`

Fetch commands only write the vault and staging. `promote` is the single writer: it applies every
pending stage batch in a deterministic order and records the outcome in `promotion_log`.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb

from financials.db import apply_schema, connect
from financials.dsl import run_screen
from financials.features import materialize
from financials.fetch.http import PoliteFetcher, Transport
from financials.fetch.jobs import WARMUP, Jobs
from financials.promoter import promote
from financials.scope import MIN_TRADE_DATE
from financials.staging import read_manifest
from financials.timeutil import utc_now
from financials.vault import Vault

UNIVERSES = ("nifty500", "active")

JOB_ORDER = {"holidays": 0, "market_day": 1, "index_snapshot": 2, "corp_actions": 3, "results_xbrl": 4,
             "shareholding": 5, "raw_only": 6, "kpis": 7}  # fmt: skip


def _paths(data_dir: Path) -> tuple[Path, Path, Path]:
    return data_dir / "vault", data_dir / "staging", data_dir / "market.duckdb"


def pending_stages(con, stage_root: Path) -> list[Path]:
    done = {p for (p,) in con.execute("SELECT stage_path FROM promotion_log").fetchall()}
    stages = []
    for manifest in stage_root.glob("*/**/manifest.json"):
        d = manifest.parent
        rel = d.relative_to(stage_root).as_posix()
        if rel in done:
            continue
        m = read_manifest(d)
        key = m.get("trade_date") or m.get("snapshot_date") or ""
        stages.append((JOB_ORDER.get(m["job"], 9), key, rel, d))
    return [d for *_, d in sorted(stages)]


def promote_pending(con, stage_root: Path, out=sys.stdout) -> int:
    """Returns the number of batches that aborted or wait (left pending for retry).

    Market days are promoted strictly in date order. When one aborts (e.g. G1 on a half-published file), every
    later market day waits instead of promoting: promoting it would put the failed day permanently behind the
    ORDER gate. Batches for the same date are still tried (a complete re-fetch can replace a trimmed one)."""
    pending = 0
    blocked_after: str | None = None
    for d in pending_stages(con, stage_root):
        rel = d.relative_to(stage_root).as_posix()
        m = read_manifest(d)
        if m["job"] == "market_day" and blocked_after is not None and m["trade_date"] > blocked_after:
            print(f"{'WAITING':16s} {'market_day':14s} {rel} behind aborted {blocked_after}", file=out)
            pending += 1
            continue
        r = promote(con, d)
        print(f"{r.status:16s} {r.job:14s} {rel} {r.gate or ''} {r.message}", file=out)
        if r.status == "ABORTED":
            pending += 1
            if m["job"] == "market_day" and blocked_after is None:
                blocked_after = m["trade_date"]
            continue
        if m["job"] == "market_day" and m["trade_date"] == blocked_after:
            blocked_after = None  # a complete batch for the blocked date went through
        con.execute("INSERT OR REPLACE INTO promotion_log VALUES (?, ?, ?, ?, ?)",
                    [rel, r.job, r.status, r.message, utc_now()])  # fmt: skip
    return pending


def _date(s: str) -> date:
    return date.fromisoformat(s)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="financials", description=__doc__.splitlines()[0])
    p.add_argument("--data-dir", type=Path, default=Path("data"))
    archive_help = "archive host requests/s and connections (owner decision); the API host stays at 1/s"
    p.add_argument("--archive-rps", type=float, default=1.0, help=archive_help)

    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db")
    fd = sub.add_parser("fetch-days", help="bhavcopy + delivery for a date range (holidays are skipped)")
    fd.add_argument("start", type=_date)
    fd.add_argument("end", type=_date, nargs="?")
    fd.add_argument("--workers", type=int, default=1, help="threads (with --archive-rps above 1)")
    fc = sub.add_parser("fetch-corp-actions")
    fc.add_argument("start", type=_date)
    fc.add_argument("end", type=_date)
    sub.add_parser("fetch-holidays")
    fi = sub.add_parser("fetch-index")
    fi.add_argument("--as-of", type=_date, default=date.today())
    fs = sub.add_parser("fetch-shareholding")
    fs.add_argument("symbols", nargs="*")
    fs.add_argument("--universe", choices=UNIVERSES)
    fs.add_argument("--all-history", action="store_true")
    fe = sub.add_parser("fetch-events", help="Reg. 30 structured event XBRL from the announcements RSS")
    fe.add_argument("--limit", type=int)
    fa = sub.add_parser("fetch-annual", help="Reg. 34 annual report XBRL (FY ending 2025 onwards)")
    fa.add_argument("symbols", nargs="*")
    fa.add_argument("--universe", choices=UNIVERSES)
    fr = sub.add_parser("fetch-results", help="results XBRL by URL, or by symbol through the A7 listing")
    fr.add_argument("url", nargs="?")
    fr.add_argument("--symbols", nargs="+", default=[])
    fr.add_argument("--universe", choices=UNIVERSES)
    fr.add_argument("--broadcast-utc", type=datetime.fromisoformat)
    df = sub.add_parser("discover-filings", help="results, annual, shareholding listings + Reg. 30 RSS; new files only")
    df.add_argument("--symbols", nargs="+", default=[])
    df.add_argument("--universe", choices=UNIVERSES)
    df.add_argument("--from-rss", action="store_true", help="symbols with results announcements in today's RSS")
    df.add_argument("--kinds", nargs="+", default=["results", "annual", "shareholding"],
                    choices=["results", "annual", "shareholding"])  # fmt: skip
    df.add_argument("--no-events", action="store_true")
    df.add_argument("--workers", type=int, default=1, help="threads (per-host limits still apply)")
    df.add_argument("--shp-from", type=_date, help="shareholding quarters from this date (default: latest only)")
    rd = sub.add_parser("run-day", help="holidays, days, corporate actions, discovery, promote, materialize")
    rd.add_argument("--date", type=_date, required=True)
    rd.add_argument("--lookback-days", type=int, default=7)
    lk = sub.add_parser("load-kpis", help="stage a supplemental KPI file (CSV/JSON: parsers.kpis) for promote")
    lk.add_argument("path", type=Path)
    eb = sub.add_parser(
        "export-bundle", help="zstd Parquet shards of the database (local / private storage, never git)"
    )
    eb.add_argument("--out", type=Path, required=True)
    eb.add_argument("--include-raw", action="store_true")
    eb.add_argument("--max-file-mb", type=float, default=50)
    eb.add_argument("--max-total-mb", type=float, default=250)
    ib = sub.add_parser("import-bundle", help="load a bundle into a new database and verify checksums")
    ib.add_argument("src", type=Path)
    ib.add_argument("--db", type=Path, required=True)
    rs = sub.add_parser("restage", help="re-parse vaulted inputs with the current parser (no download)")
    rs.add_argument("--category", choices=["CORP_ACTIONS"], required=True)
    sub.add_parser("promote", help="apply all pending staged batches (single writer)")
    rb = sub.add_parser("rebuild-market", help="roll market-derived state back to a date and replay it (audited)")
    rb.add_argument("--from", dest="from_date", type=_date, required=True)
    rb.add_argument("--note", default="rebuild-market")
    mt = sub.add_parser("materialize", help="one date, or every promoted trading day in --from/--to, in order")
    mt.add_argument("as_of", type=_date, nargs="?")
    mt.add_argument("--from", dest="from_date", type=_date)
    mt.add_argument("--to", dest="to_date", type=_date)
    q = sub.add_parser("quarantine", help="list or resolve quarantined items (audited)")
    qs = q.add_subparsers(dest="qcmd", required=True)
    ql = qs.add_parser("list")
    ql.add_argument("--stage")
    ql.add_argument("--reason")
    ql.add_argument("--entity")
    ql.add_argument("--security")
    ql.add_argument("--all", action="store_true", help="include resolved rows")
    ql.add_argument("--limit", type=int, default=200)
    qr = qs.add_parser("resolve")
    qr.add_argument("--id", required=True)
    qr.add_argument("--action", required=True, choices=["ACCEPT", "REJECT", "OVERRIDE", "CORP_ACTION",
                                                         "MERGE_SECURITIES"])  # fmt: skip
    qr.add_argument("--note", required=True)
    qr.add_argument("--payload-json", default="{}")
    qs.add_parser("reprocess", help="re-promote batches whose identity / visibility blockers may be cleared")
    qi = qs.add_parser("inspect", help="one finding with its context and the commands that resolve it")
    qi.add_argument("id")
    ex = sub.add_parser("extract-index-changes", help="NSE Indices notices (pdftotext -layout .txt) -> manifest CSV")
    ex.add_argument("text_dir", type=Path)
    ex.add_argument("--index", default="Nifty 500")
    ex.add_argument("--out", type=Path, required=True)
    bf = sub.add_parser("backfill-index", help="rebuild membership before the first snapshot from a manifest")
    bf.add_argument("--manifest", type=Path, required=True)
    bf.add_argument("--index", default="NIFTY 500")
    bf.add_argument("--expected-count", type=int, default=500)
    so = sub.add_parser("scope-override", help="pin (or --clear) a company's default scopes (audited)")
    so.add_argument("--entity", required=True)
    so.add_argument("--quarterly", choices=("CONSOLIDATED", "STANDALONE"))
    so.add_argument("--annual", choices=("CONSOLIDATED", "STANDALONE"))
    so.add_argument("--clear", action="store_true")
    so.add_argument("--reason", required=True)
    ao = sub.add_parser("archetype-override", help="pin (or --clear) a company's valuation archetype (audited)")
    ao.add_argument("--entity", required=True)
    ao.add_argument("--archetype", choices=("INDUSTRIAL_SERVICES", "FINANCIAL_LENDING", "INSURANCE", "NEW_GEN_TECH"))
    ao.add_argument("--clear", action="store_true")
    ao.add_argument("--reason", required=True)
    sc = sub.add_parser("screen")
    sc.add_argument("query")
    sc.add_argument("--as-of", type=_date)
    return p


def main(argv: Sequence[str] | None = None, *, transport: Transport | None = None, out=sys.stdout) -> int:
    args = build_parser().parse_args(argv)
    vault_dir, stage_root, db_path = _paths(args.data_dir)
    if args.cmd.startswith(("fetch", "discover")):
        jobs = Jobs(
            PoliteFetcher(transport, warmup=WARMUP, host_limits=archive_limits(args)), Vault(vault_dir), stage_root
        )
        jobs.workers = getattr(args, "workers", 1)
        staged, errors = run_fetch(args, jobs, db_path, out)
        for s in staged:
            print(f"staged {s.relative_to(stage_root).as_posix()}", file=out)
        for w in jobs.warnings:
            print(f"warning: {w}", file=out)
        for e in errors:
            print(f"error: {e}", file=out)
        return 1 if errors else 0
    if args.cmd in ("export-bundle", "import-bundle"):
        from financials.bundle import BundleError, export_bundle, import_bundle

        try:
            if args.cmd == "import-bundle":
                print(json.dumps(import_bundle(args.src, args.db)), file=out)
                return 0
            if not db_path.exists():
                print(f"error: no market database at {db_path}", file=out)
                return 2
            con = connect(db_path, read_only=True)
            try:
                m = export_bundle(con, args.out, include_raw=args.include_raw, max_file_mb=args.max_file_mb,
                                  max_total_mb=args.max_total_mb)  # fmt: skip
            finally:
                con.close()
        except BundleError as exc:
            print(f"error: {exc}", file=out)
            return 1
        for t, v in m["tables"].items():
            print(f"{t:36s} rows={v['rows']:>10} files={v['files']:>3} {v['bytes'] / 2**20:8.2f} MB", file=out)
        print(f"total {m['total_bytes'] / 2**20:.2f} MB", file=out)
        return 0
    if args.cmd == "restage":
        from financials.staging import stage_corp_actions

        if not db_path.exists():
            print(f"error: no market database at {db_path}", file=out)
            return 2
        con = connect(db_path, read_only=True)
        try:
            rows = con.execute(
                "SELECT f.source_url, f.fetched_at, b.storage_path, b.sha256 FROM filings f "
                "JOIN blobs b USING (sha256) WHERE f.category = ? ORDER BY f.source_url",
                [args.category]).fetchall()  # fmt: skip
        finally:
            con.close()
        vault = Vault(vault_dir)
        for url, fetched, path, sha in rows:
            s = stage_corp_actions(
                vault, stage_root, data=vault.read_path(path, sha), source_url=url, fetched_at=fetched
            )
            print(f"staged {s.relative_to(stage_root).as_posix()}", file=out)
        return 0
    if args.cmd == "load-kpis":
        from financials.staging import stage_kpis

        s = stage_kpis(Vault(vault_dir), stage_root, data=args.path.read_bytes(),
                       source_url=args.path.resolve().as_uri(), fetched_at=utc_now())  # fmt: skip
        print(f"staged {s.relative_to(stage_root).as_posix()} (run promote)", file=out)
        return 0
    if args.cmd == "run-day":
        return run_day(args, transport, out)

    if args.cmd == "extract-index-changes":
        from financials.index_changes import parse_change_notice, write_manifest

        events = []
        for p in sorted(args.text_dir.glob("*.txt")):
            events += parse_change_notice(p.read_text(encoding="utf-8"), args.index, p.name)
        args.out.write_text(write_manifest(events), encoding="utf-8")
        print(f"{len(events)} events from {len(sorted(args.text_dir.glob('*.txt')))} notices -> {args.out}", file=out)
        return 0

    if args.cmd == "screen" or (args.cmd == "quarantine" and args.qcmd in ("list", "inspect")):
        return read_command(args, db_path, out)

    args.data_dir.mkdir(parents=True, exist_ok=True)
    con = connect(db_path)
    try:
        upgraded = apply_schema(con)
        if args.cmd == "init-db":
            for stmt in upgraded:
                print(f"upgraded: {stmt}", file=out)
            print(f"schema applied to {db_path} ({len(upgraded)} column(s) added)", file=out)
            return 0
        if args.cmd == "promote":
            return 1 if promote_pending(con, stage_root, out) else 0
        if args.cmd == "rebuild-market":
            from financials.admin import rebuild_market

            r = rebuild_market(con, args.from_date, note=args.note)
            print(json.dumps(r, default=str), file=out)
            waiting = promote_pending(con, stage_root, out)
            for d in r["features_dates"]:
                fr = materialize(con, d)
                print(f"{fr.status} {fr.as_of_date} rows={fr.rows} {fr.gate or ''} {fr.message}", file=out)
            return 1 if waiting else 0
        if args.cmd == "materialize":
            return materialize_dates(con, args.as_of, args.from_date, args.to_date, out)
        if args.cmd == "quarantine":
            from financials.admin import AdminError, resolve_quarantine

            if args.qcmd == "reprocess":
                from financials.admin import reprocess

                print(json.dumps(reprocess(con, stage_root), default=str, indent=1), file=out)
                return 0
            try:
                result = resolve_quarantine(con, args.id, action=args.action, note=args.note,
                                            payload=json.loads(args.payload_json), stage_root=stage_root)  # fmt: skip
            except AdminError as exc:
                print(f"error: {exc}", file=out)
                return 1
            print(json.dumps(result, default=str, indent=1), file=out)
            return 0
        if args.cmd == "scope-override":
            from financials.admin import AdminError, set_scope_override

            q, an = (None, None) if args.clear else (args.quarterly, args.annual)
            try:
                print(json.dumps(set_scope_override(con, args.entity, quarterly=q, annual=an, reason=args.reason)),
                      file=out)  # fmt: skip
            except AdminError as exc:
                print(f"error: {exc}", file=out)
                return 2
            return 0
        if args.cmd == "archetype-override":
            from financials.admin import AdminError, set_archetype_override

            try:
                result = set_archetype_override(
                    con, args.entity, archetype=None if args.clear else args.archetype, reason=args.reason
                )
                print(json.dumps(result), file=out)
            except AdminError as exc:
                print(f"error: {exc}", file=out)
                return 2
            return 0
        if args.cmd == "backfill-index":
            from financials.admin import AdminError, backfill_index
            from financials.index_changes import IndexInvariantError, read_manifest

            try:
                r = backfill_index(con, args.index, read_manifest(args.manifest.read_text(encoding="utf-8")),
                                   expected_count=args.expected_count)  # fmt: skip
            except (AdminError, IndexInvariantError) as exc:
                print(f"error: {exc}", file=out)
                return 1
            print(f"backfilled {r['rows']} intervals before {r['first_snapshot']} across {len(r['steps'])} "
                  f"event dates", file=out)  # fmt: skip
            return 0
    finally:
        con.close()
    return 2


def archive_limits(args) -> dict[str, tuple[float, int]] | None:
    if args.archive_rps <= 1:
        return None
    return {"nsearchives.nseindia.com": (args.archive_rps, max(1, int(args.archive_rps)))}


def universe_symbols(db_path: Path, name: str, as_of: date) -> list[str]:
    """Symbols of a universe from the market database (read-only): `nifty500` = index members on `as_of`,
    `active` = every security with an open identifier interval."""
    if not db_path.exists():
        raise SystemExit(f"error: --universe needs a market database at {db_path}")
    con = connect(db_path, read_only=True)
    try:
        if name == "nifty500":
            sql = """SELECT DISTINCT h.symbol FROM index_constituents_history i
                     JOIN security_identifier_history h ON h.security_id = i.security_id AND h.valid_to IS NULL
                     WHERE i.index_name = 'NIFTY 500' AND i.valid_from <= ? AND (i.valid_to IS NULL OR i.valid_to > ?)
                     ORDER BY 1"""
            rows = con.execute(sql, [as_of, as_of]).fetchall()
        else:
            rows = con.execute(
                "SELECT DISTINCT symbol FROM security_identifier_history WHERE valid_to IS NULL ORDER BY 1"
            ).fetchall()
    finally:
        con.close()
    return [r[0] for r in rows]


def _symbols(args, db_path: Path, explicit: list[str]) -> list[str]:
    syms = list(explicit)
    if getattr(args, "universe", None):
        syms += [s for s in universe_symbols(db_path, args.universe, date.today()) if s not in syms]
    return syms


def run_fetch(args, jobs: Jobs, db_path: Path, out) -> tuple[list[Path], list[str]]:
    staged: list[Path] = []
    errors: list[str] = []
    if args.cmd == "fetch-days":
        start, end = max(args.start, MIN_TRADE_DATE), args.end or args.start
        if args.start < MIN_TRADE_DATE:
            print(f"note: v1 scope starts {MIN_TRADE_DATE}; earlier dates are not fetched", file=out)
        staged, errors = jobs.market_days(start, end)
    elif args.cmd == "fetch-corp-actions":
        staged += jobs.corp_actions(max(args.start, MIN_TRADE_DATE), args.end)
    elif args.cmd == "fetch-holidays":
        staged += jobs.holidays()
    elif args.cmd == "fetch-index":
        staged += jobs.index_snapshot(args.as_of)
    elif args.cmd == "fetch-shareholding":
        syms = _symbols(args, db_path, args.symbols)
        if args.all_history:
            for sym in syms:
                staged += jobs.shareholding(sym, latest_only=False)
        else:
            staged, errors = jobs.discover(syms, ["shareholding"], events=False)
    elif args.cmd == "fetch-events":
        staged += jobs.reg30_events(limit=args.limit)
    elif args.cmd == "fetch-annual":
        staged, errors = jobs.discover(_symbols(args, db_path, args.symbols), ["annual"], events=False)
    elif args.cmd == "fetch-results":
        if args.url:
            src = "API_FIELD" if args.broadcast_utc else "UNKNOWN"
            staged += jobs.results_xbrl(args.url, args.broadcast_utc, src)
        staged_r, errors = jobs.discover(_symbols(args, db_path, args.symbols), ["results"], events=False)
        staged += staged_r
    elif args.cmd == "discover-filings":
        syms = _symbols(args, db_path, args.symbols)
        if args.from_rss:
            syms += [s for s in jobs.symbols_from_rss() if s not in syms]
        jobs.shp_min_as_of = args.shp_from
        staged, errors = jobs.discover(syms, args.kinds, events=not args.no_events, workers=args.workers)
    return staged, errors


def materialize_dates(con, as_of: date | None, start: date | None, end: date | None, out) -> int:
    if as_of is not None:
        dates = [as_of]
    elif start is not None:
        dates = [r[0] for r in con.execute(
            "SELECT DISTINCT trade_date FROM ohlcv WHERE trade_date >= ? AND trade_date <= ? ORDER BY 1",
            [start, end or date.max],
        ).fetchall()]  # fmt: skip
    else:
        print("error: give a date or --from [--to]", file=out)
        return 2
    for d in dates:  # ascending, so G4 always compares with the previous materialised date
        r = materialize(con, d)
        print(f"{r.status} {r.as_of_date} rows={r.rows} {r.gate or ''} {r.message}", file=out)
        if r.status != "PROMOTED":
            return 1
    return 0


def run_day(args, transport: Transport | None, out) -> int:
    """Idempotent daily run for `--date D`: holiday list, market days D-lookback..D (vaulted days are not fetched
    again), corporate actions D-lookback..D+30 (announced ahead of ex-date), discovery for the symbols with results
    in today's RSS plus Reg. 30 events, then promote and materialise D. Fetch failures are reported; the rest of the
    run continues, and the next run picks up what failed."""
    vault_dir, stage_root, db_path = _paths(args.data_dir)
    jobs = Jobs(PoliteFetcher(transport, warmup=WARMUP), Vault(vault_dir), stage_root)
    d = args.date
    errors: list[str] = []
    steps = (
        ("holidays", jobs.holidays),
        ("days", lambda: jobs.market_days(max(d - timedelta(days=args.lookback_days), MIN_TRADE_DATE), d)),
        ("corp-actions", lambda: jobs.corp_actions(max(d - timedelta(days=args.lookback_days), MIN_TRADE_DATE),
                                                   d + timedelta(days=30))),
        ("discovery", lambda: jobs.discover(jobs.symbols_from_rss(), ["results", "shareholding"])),
    )  # fmt: skip
    for name, step in steps:
        try:
            r = step()
            staged, errs = r if isinstance(r, tuple) else (r, [])
            errors += [f"{name}: {e}" for e in errs]
            print(f"{name}: {len(staged)} staged", file=out)
        except Exception as exc:  # a failed step must not stop the promote of what was fetched
            errors.append(f"{name}: {exc}")
    for w in jobs.warnings:
        print(f"warning: {w}", file=out)
    args.data_dir.mkdir(parents=True, exist_ok=True)
    con = connect(db_path)
    try:
        apply_schema(con)
        waiting = promote_pending(con, stage_root, out)
        rc = materialize_dates(con, d, None, None, out)
    finally:
        con.close()
    for e in errors:
        print(f"error: {e}", file=out)
    return 1 if errors or waiting or rc else 0


def read_command(args, db_path: Path, out) -> int:
    """screen / quarantine list / quarantine inspect: read-only connection, no schema upgrade [P2-12]. DuckDB
    refuses any other process while a writer (promote, materialize, ...) holds the file: reported, not retried."""
    if not db_path.exists():
        print(f"error: no market database at {db_path} (run init-db)", file=out)
        return 2
    try:
        con = connect(db_path, read_only=True)
    except duckdb.IOException as exc:
        print(f"error: database busy (a writer holds {db_path.name}); retry when it finishes: {exc}", file=out)
        return 3
    try:
        if args.cmd == "screen":
            print(json.dumps(run_screen(con, args.query, as_of=args.as_of), default=str, indent=1), file=out)
            return 0
        from financials.admin import AdminError, inspect_quarantine, list_quarantine

        if args.qcmd == "list":
            rows = list_quarantine(con, stage=args.stage, reason_code=args.reason, entity_id=args.entity,
                                   security_id=args.security, include_resolved=args.all, limit=args.limit)  # fmt: skip
            print(json.dumps(rows, default=str, indent=1), file=out)
            return 0
        try:
            print(json.dumps(inspect_quarantine(con, args.id), default=str, indent=1), file=out)
        except AdminError as exc:
            print(f"error: {exc}", file=out)
            return 1
        return 0
    finally:
        con.close()
