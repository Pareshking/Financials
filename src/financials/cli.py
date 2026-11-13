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

from financials.db import apply_schema, connect
from financials.dsl import run_screen
from financials.features import materialize
from financials.fetch.http import PoliteFetcher, Transport
from financials.fetch.jobs import Jobs
from financials.promoter import promote
from financials.scope import MIN_TRADE_DATE
from financials.staging import read_manifest
from financials.timeutil import utc_now
from financials.vault import Vault

JOB_ORDER = {"holidays": 0, "market_day": 1, "index_snapshot": 2, "corp_actions": 3, "results_xbrl": 4,
             "shareholding": 5, "raw_only": 6}  # fmt: skip


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
    """Returns the number of batches that aborted (left pending for retry)."""
    aborted = 0
    for d in pending_stages(con, stage_root):
        r = promote(con, d)
        rel = d.relative_to(stage_root).as_posix()
        print(f"{r.status:16s} {r.job:14s} {rel} {r.gate or ''} {r.message}", file=out)
        if r.status == "ABORTED":
            aborted += 1
            continue
        con.execute("INSERT OR REPLACE INTO promotion_log VALUES (?, ?, ?, ?, ?)",
                    [rel, r.job, r.status, r.message, utc_now()])  # fmt: skip
    return aborted


def _date(s: str) -> date:
    return date.fromisoformat(s)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="financials", description=__doc__.splitlines()[0])
    p.add_argument("--data-dir", type=Path, default=Path("data"))
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db")
    fd = sub.add_parser("fetch-days", help="bhavcopy + delivery for a date range (holidays are skipped)")
    fd.add_argument("start", type=_date)
    fd.add_argument("end", type=_date, nargs="?")
    fc = sub.add_parser("fetch-corp-actions")
    fc.add_argument("start", type=_date)
    fc.add_argument("end", type=_date)
    sub.add_parser("fetch-holidays")
    fi = sub.add_parser("fetch-index")
    fi.add_argument("--as-of", type=_date, default=date.today())
    fs = sub.add_parser("fetch-shareholding")
    fs.add_argument("symbols", nargs="+")
    fs.add_argument("--all-history", action="store_true")
    fr = sub.add_parser("fetch-results", help="results XBRL by URL")
    fr.add_argument("url")
    fr.add_argument("--broadcast-utc", type=datetime.fromisoformat)
    sub.add_parser("promote", help="apply all pending staged batches (single writer)")
    mt = sub.add_parser("materialize")
    mt.add_argument("as_of", type=_date)
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
    if args.cmd.startswith("fetch"):
        jobs = Jobs(PoliteFetcher(transport), Vault(vault_dir), stage_root)
        staged: list[Path] = []
        if args.cmd == "fetch-days":
            d, end = max(args.start, MIN_TRADE_DATE), args.end or args.start
            if args.start < MIN_TRADE_DATE:
                print(f"note: v1 scope starts {MIN_TRADE_DATE}; earlier dates are not fetched", file=out)
            while d <= end:
                staged += jobs.market_day(d) or []
                d += timedelta(days=1)
        elif args.cmd == "fetch-corp-actions":
            staged += jobs.corp_actions(max(args.start, MIN_TRADE_DATE), args.end)
        elif args.cmd == "fetch-holidays":
            staged += jobs.holidays()
        elif args.cmd == "fetch-index":
            staged += jobs.index_snapshot(args.as_of)
        elif args.cmd == "fetch-shareholding":
            for sym in args.symbols:
                staged += jobs.shareholding(sym, latest_only=not args.all_history)
        elif args.cmd == "fetch-results":
            src = "API_FIELD" if args.broadcast_utc else "UNKNOWN"
            staged += jobs.results_xbrl(args.url, args.broadcast_utc, src)
        for s in staged:
            print(f"staged {s.relative_to(stage_root).as_posix()}", file=out)
        return 0

    if args.cmd == "extract-index-changes":
        from financials.index_changes import parse_change_notice, write_manifest

        events = []
        for p in sorted(args.text_dir.glob("*.txt")):
            events += parse_change_notice(p.read_text(encoding="utf-8"), args.index, p.name)
        args.out.write_text(write_manifest(events), encoding="utf-8")
        print(f"{len(events)} events from {len(sorted(args.text_dir.glob('*.txt')))} notices -> {args.out}", file=out)
        return 0

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
        if args.cmd == "materialize":
            r = materialize(con, args.as_of)
            print(f"{r.status} {r.as_of_date} rows={r.rows} {r.gate or ''} {r.message}", file=out)
            return 0 if r.status == "PROMOTED" else 1
        if args.cmd == "quarantine":
            from financials.admin import AdminError, list_quarantine, resolve_quarantine

            if args.qcmd == "list":
                rows = list_quarantine(
                    con,
                    stage=args.stage,
                    reason_code=args.reason,
                    entity_id=args.entity,
                    security_id=args.security,
                    include_resolved=args.all,
                    limit=args.limit,
                )
                print(json.dumps(rows, default=str, indent=1), file=out)
                return 0
            try:
                result = resolve_quarantine(con, args.id, action=args.action, note=args.note,
                                            payload=json.loads(args.payload_json))  # fmt: skip
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
        if args.cmd == "screen":
            rows = run_screen(con, args.query, as_of=args.as_of)
            print(json.dumps(rows, default=str, indent=1), file=out)
            return 0
    finally:
        con.close()
    return 2
