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

from financials import lineage
from financials.calendar import is_trading_day
from financials.db import apply_schema, connect
from financials.dsl import run_screen
from financials.features import materialize_days, materialize_incremental, materialize_run, settle_full_run
from financials.fetch.http import PoliteFetcher, Transport
from financials.fetch.jobs import WARMUP, Jobs
from financials.promoter import (
    close_resolved_annual_share_findings,
    close_resolved_share_findings,
    close_wrong_template_duplicates,
    promote,
)
from financials.scope import MIN_TRADE_DATE
from financials.staging import read_manifest
from financials.timeutil import utc_now, utc_to_ist_date
from financials.vault import Vault

UNIVERSES = ("nifty500", "active", "mcap500", "mcap500-new")

JOB_ORDER = {"holidays": 0, "market_day": 1, "index_close": 2, "index_snapshot": 2, "mcap_day": 2, "corp_actions": 3,
             "results_xbrl": 4, "shareholding": 5, "raw_only": 6, "kpis": 7, "equity_master": 8,
             "classification": 8, "bse_securities": 8}  # fmt: skip


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


def promote_pending(con, stage_root: Path, out=sys.stdout, vault: Vault | None = None) -> int:
    """Returns the number of batches that aborted or wait (left pending for retry).

    Market days are promoted strictly in date order. When one aborts (e.g. G1 on a half-published file), every
    later market day waits instead of promoting: promoting it would put the failed day permanently behind the
    ORDER gate. Batches for the same date are still tried (a complete re-fetch can replace a trimmed one)."""
    pending, results_seen = 0, False
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
        results_seen = results_seen or r.job == "results_xbrl"
    # the X89 rule reads quarantined filings from their vault blobs (decision J); the vault sits next to staging
    if results_seen and (n := close_wrong_template_duplicates(con, vault or Vault(stage_root.parent / "vault"))):
        print(f"{'FIXED_BY_RULE':16s} {'results_xbrl':14s} {n} wrong-template duplicate(s) closed [X89]", file=out)
    if n := close_resolved_share_findings(con):
        print(
            f"{'FIXED_BY_RULE':16s} {'shares':14s} {n} share cross-check finding(s) agree on re-check [X103]", file=out
        )
    if n := close_resolved_annual_share_findings(con):
        print(f"{'FIXED_BY_RULE':16s} {'shares':14s} {n} annual share-count finding(s) agree on re-check [X181]",
              file=out)  # fmt: skip
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
    fm = sub.add_parser("fetch-mcap", help="NSE PRddmmyy.zip market-cap files for promoted trading days [X130]")
    fm.add_argument("start", type=_date)
    fm.add_argument("end", type=_date, nargs="?")
    fm.add_argument("--weekly", action="store_true", help="only the last trading day of each week (universe backfill)")
    uu = sub.add_parser("update-universe", help="sticky Rs 500 Cr market-cap universe, weekly rule U1 [X134] (audited)")
    uu.add_argument("--from", dest="from_date", type=_date, default=MIN_TRADE_DATE)
    uu.add_argument("--to", dest="to_date", type=_date)
    ci = sub.add_parser("check-issue-size", help="NSE Issue Size vs Reg. 31 total shares on a date (cross-check, X133)")
    ci.add_argument("--as-of", type=_date, required=True)
    ci.add_argument("--all", action="store_true", help="list agreeing rows too")
    fc = sub.add_parser("fetch-corp-actions")
    fc.add_argument("start", type=_date)
    fc.add_argument("end", type=_date)
    sub.add_parser("fetch-holidays")
    sub.add_parser("fetch-equity-master", help="NSE equity master EQUITY_L.csv (listing date, face value, ISIN)")
    fi = sub.add_parser("fetch-index")
    fi.add_argument("--as-of", type=_date, default=date.today())
    fs = sub.add_parser("fetch-shareholding")
    fs.add_argument("symbols", nargs="*")
    fs.add_argument("--universe", choices=UNIVERSES)
    fs.add_argument("--all-history", action="store_true")
    fcl = sub.add_parser("fetch-classification", help="NSE 4-level industry classification (quote API, 1 request/s)")
    fcl.add_argument("symbols", nargs="*")
    fcl.add_argument("--universe", choices=UNIVERSES)
    fcl.add_argument("--missing-only", action="store_true",
                     help="only symbols whose entity has no current classification (nightly workflow)")  # fmt: skip
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
    df.add_argument("--symbols-file", type=Path, help="one NSE symbol per line (needs no market database)")
    df.add_argument("--shard", help="K/N: only shard K (0-based) of N of the symbols (runner fan-out, fetch.replay)")
    df.add_argument("--record-responses", action="store_true",
                    help="also ledger listing answers in vault/responses.jsonl (for import-vault)")  # fmt: skip
    iv = sub.add_parser("import-vault", help="merge runner vaults (blobs + url_index/responses ledgers) and stage them")
    iv.add_argument("dirs", type=Path, nargs="+")
    rd = sub.add_parser("run-day", help="holidays, days, corporate actions, discovery, promote, universe, materialize")
    rd.add_argument("--date", type=_date, help="trading date to run (default: today in IST, for schedulers)")
    rd.add_argument("--lookback-days", type=int, default=7)
    bm = sub.add_parser("bse-members", help="Permitted members of rule U1-P (their filings are on BSE) [X166]")
    bm.add_argument("--as-of", type=_date, help="default: today (IST)")
    ib_ = sub.add_parser(
        "import-bse", help="vault + stage a BSE runner ledger (blobs/ + ledger.jsonl) for promote [A17]"
    )
    ib_.add_argument("ledger_dir", type=Path)
    lk = sub.add_parser("load-kpis", help="stage a supplemental KPI file (CSV/JSON: parsers.kpis) for promote")
    lk.add_argument("path", type=Path)
    eb = sub.add_parser(
        "export-bundle", help="zstd Parquet shards of the database (local / private storage, never git)"
    )
    eb.add_argument("--out", type=Path, required=True)
    eb.add_argument("--max-file-mb", type=float, default=50)
    eb.add_argument("--max-total-mb", type=float, default=250)
    ib = sub.add_parser("import-bundle", help="load a bundle into a new database and verify checksums")
    ib.add_argument("src", type=Path)
    ib.add_argument("--db", type=Path, required=True)
    rs = sub.add_parser("restage", help="re-parse vaulted inputs with the current parser (no download)")
    restage_help = "RESULTS_XBRL re-parses only filings with open parse / identity / period findings"
    rs.add_argument(
        "--category", choices=["CORP_ACTIONS", "SHP_XBRL", "RESULTS_XBRL"], required=True, help=restage_help
    )
    rs.add_argument("--visibility", action="store_true",
                    help="RESULTS_XBRL: instead re-parse promoted filings whose visibility rule now gives a later "
                         "time (listing creation / file name) [X83]")  # fmt: skip
    rs.add_argument("--all", action="store_true",
                    help="RESULTS_XBRL: re-parse every results / annual filing (after a parser change that adds "
                         "output to clean filings, e.g. segment rows in 0.10.0)")  # fmt: skip
    rs.add_argument("--open-findings", action="store_true",
                    help="SHP_XBRL / CORP_ACTIONS: re-parse only filings with open parse / identity / period findings "
                         "(RESULTS_XBRL does this by default)")  # fmt: skip
    evidence_help = "stage raw_results_listing rows from vaulted RESULTS_LISTING blobs (then promote) [X83]"
    sub.add_parser("backfill-listing-evidence", help=evidence_help)
    bg = sub.add_parser(
        "backfill-group-structure",
        help="AOC-1 rows for annual filings promoted before batch H, from the vault (audited) [X112]",
    )
    bg.add_argument("--limit", type=int)
    br = sub.add_parser(
        "backfill-rpt",
        help="related-party schedule rows for annual filings promoted before batch J, from the vault (audited) [X113]",
    )
    br.add_argument("--limit", type=int)
    bd = sub.add_parser(
        "backfill-disclosures",
        help="disclosure_facts rows (every element no other clean table holds) for promoted filings, from the vault "
        "(parallel parse to staging Parquet, one insert by the single writer; audited, resumable) [X116]",
    )
    bd.add_argument("--limit", type=int)
    bd.add_argument("--workers", type=int, help="parse processes (default: os.cpu_count())")
    ba = sub.add_parser(
        "backfill-audit-opinions",
        help="audit_opinions rows (audit-opinion flags from the auditor's report text) for promoted results / annual "
        "filings, from the vault (parallel parse to staging Parquet, one insert by the single writer; audited, "
        "resumable) [X121]",
    )
    ba.add_argument("--limit", type=int)
    ba.add_argument("--workers", type=int, help="parse processes (default: os.cpu_count())")
    sub.add_parser("audit-annual", help="re-run the Reg. 34 prior-year and share-count checks on every annual [X180]")
    sub.add_parser("audit-ytd", help="raise YTD_QUARTER_MISMATCH findings for every entity and scope [X80]")
    ls = sub.add_parser("rescale-level-slips", help="X201: rescale filings that declared the wrong LevelOfRounding")
    ls.add_argument("--dry-run", action="store_true", help="list the filings and their proof, write nothing")
    sub.add_parser("promote", help="apply all pending staged batches (single writer)")
    rb = sub.add_parser("rebuild-market", help="roll market-derived state back to a date and replay it (audited)")
    rb.add_argument("--from", dest="from_date", type=_date, required=True)
    rb.add_argument("--note", default="rebuild-market")
    rb.add_argument("--no-compact", action="store_true", help="do not compact the database file afterwards")
    ms = sub.add_parser(
        "migrate-sparse-history",
        help="one-off: convert the wide screener_features_history table to event-sparse storage",
    )
    ms.add_argument("--no-compact", action="store_true", help="do not compact the database file afterwards")
    cp = sub.add_parser("compact", help="rewrite the database file without dead space (verified copy, atomic swap)")
    cp.add_argument("--keep-old", action="store_true", help="keep the previous file as market.duckdb.bak")
    cp.add_argument(
        "--spill",
        type=Path,
        help="low disk: go through verified Parquet in this directory instead "
        "of a second database file (resumes an interrupted run)",
    )
    pv = sub.add_parser(
        "prune-versions", help="archive to Parquet, then delete, superseded parser versions (decision I)"
    )
    pv.add_argument("--archive", type=Path, help="archive directory (default: DATA_DIR/archive)")
    pv.add_argument("--dry-run", action="store_true", help="only report the rows per table and version")
    pv.add_argument("--note", default="")
    pv.add_argument("--no-compact", action="store_true", help="do not compact the database file afterwards")
    dr = sub.add_parser(
        "drop-raw-xbrl",
        help="one-shot (owner decision J): drop raw_xbrl_facts once the coverage check finds 0 uncaptured elements",
    )
    dr.add_argument("--note", default="")
    dr.add_argument("--no-compact", action="store_true", help="do not compact the database file afterwards")
    dr.add_argument("--spill", type=Path, help="compact afterwards through verified Parquet in this directory "
                    "(low disk: needs ~0.5 x the live size instead of 1.1 x)")  # fmt: skip
    mt = sub.add_parser("materialize", help="one date, or every promoted trading day in --from/--to, in order")
    mt.add_argument("as_of", type=_date, nargs="?")
    mt.add_argument("--from", dest="from_date", type=_date)
    mt.add_argument("--to", dest="to_date", type=_date)
    mt.add_argument(
        "--incremental",
        action="store_true",
        help="recompute only rows marked dirty since the last run, on materialised days (<= --to)",
    )
    mt.add_argument("--no-compact", action="store_true", help="after --from/--to: do not compact the database file")
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
    sc.add_argument("query", nargs="?", help="DSL filter; omit with --saved")
    sc.add_argument("--saved", help='run a saved screen (see `screens`), e.g. "hidden compounder"')
    sc.add_argument("--as-of", type=_date)
    sc.add_argument("--columns", help='extra result columns, comma-separated DSL expressions or custom ratios, e.g. '
                    '"Sales latest quarter, OPM last year, Sales / Market cap"')  # fmt: skip
    sc.add_argument("--order-by", help="sort the matches by this DSL expression (NULLs last)")
    sc.add_argument("--desc", action="store_true", help="with --order-by: descending")
    sc.add_argument("--limit", type=int, help="default 500, or the saved screen's own limit")
    sr = sub.add_parser("save-ratio", help="save (or replace) a custom ratio usable in screens and --columns")
    sr.add_argument("name")
    sr.add_argument("expression")
    sub.add_parser("ratios", help="list saved custom ratios")
    sub.add_parser("screens", help="list saved screens (docs/hidden_gems.md section B)")
    lineage.add_cli(sub)
    return p


def restage_rows(con, category: str, mode: str = "OPEN_FINDINGS") -> list[tuple]:
    """Vaulted filings to re-parse: (source_url, fetched_at, storage_path, sha256, broadcast_ts, broadcast_ts_source,
    exchange). RESULTS_XBRL: OPEN_FINDINGS (default) = filings with open parse / identity / period findings;
    VISIBILITY = promoted filings whose visibility rule now gives a later time [X83]; ALL = every results and annual
    filing that has filing_meta (parsed, not OUT_OF_SCOPE) or an open finding. Other categories: every filing, or
    with OPEN_FINDINGS_ONLY (`restage --open-findings`) only those with open findings."""
    from financials.promoter import FILING_FINDING_STAGES

    where, params = "", [category]
    open_findings = (
        "f.filing_id IN (SELECT filing_id FROM quarantine_queue WHERE resolved_at IS NULL "
        f"AND stage IN {FILING_FINDING_STAGES}) "
    )
    if category == "RESULTS_XBRL" and mode == "VISIBILITY":
        from financials.promoter import filings_with_later_visibility

        where, params = "AND f.filing_id IN (SELECT unnest(?)) ", [category, filings_with_later_visibility(con)]
    elif category == "RESULTS_XBRL" and mode == "ALL":
        where = "AND (f.filing_id IN (SELECT filing_id FROM filing_meta) OR " + open_findings + ") "
    elif category == "RESULTS_XBRL" or mode == "OPEN_FINDINGS_ONLY":
        where = "AND " + open_findings
    return con.execute(
        "SELECT f.source_url, f.fetched_at, b.storage_path, b.sha256, f.broadcast_ts, f.broadcast_ts_source, "
        "f.exchange FROM filings f JOIN blobs b USING (sha256) WHERE f.category = ? " + where
        + "ORDER BY f.source_url", params).fetchall()  # fmt: skip


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
                m = export_bundle(con, args.out, max_file_mb=args.max_file_mb,
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
        from financials import PARSER_VERSION
        from financials.staging import stage_results_xbrl, stage_shareholding

        con = connect(db_path, read_only=True)
        try:
            mode = "VISIBILITY" if args.visibility else "ALL" if args.all else "OPEN_FINDINGS"
            if args.open_findings and args.category != "RESULTS_XBRL":
                mode = "OPEN_FINDINGS_ONLY"
            rows = restage_rows(con, args.category, mode)
        finally:
            con.close()
        vault = Vault(vault_dir)
        for url, fetched, path, sha, bts, bsrc, exch in rows:
            data = vault.read_path(path, sha)
            if args.category == "CORP_ACTIONS":
                s = stage_corp_actions(vault, stage_root, data=data, source_url=url, fetched_at=fetched)
            elif args.category == "RESULTS_XBRL":
                s = stage_results_xbrl(vault, stage_root, data=data, source_url=url, fetched_at=fetched,
                                       broadcast_ts=bts, broadcast_ts_source=bsrc, exchange=exch,
                                       run_suffix=PARSER_VERSION)  # fmt: skip
            else:  # same filing (blob, URL, broadcast time); a new parser_version batch
                s = stage_shareholding(vault, stage_root, data=data, source_url=url, fetched_at=fetched,
                                       broadcast_ts=bts, broadcast_ts_source=bsrc, exchange=exch,
                                       run_suffix=PARSER_VERSION)  # fmt: skip
            print(f"staged {s.relative_to(stage_root).as_posix()}", file=out)
        return 0
    if args.cmd == "backfill-listing-evidence":
        from financials.staging import stage_results_listing

        if not db_path.exists():
            print(f"error: no market database at {db_path}", file=out)
            return 2
        con = connect(db_path, read_only=True)
        try:
            rows = con.execute(
                "SELECT f.source_url, f.fetched_at, f.exchange, b.storage_path, b.sha256 FROM filings f "
                "JOIN blobs b USING (sha256) WHERE f.category = 'RESULTS_LISTING' AND NOT EXISTS "
                "(SELECT 1 FROM raw_results_listing r WHERE r.filing_id = f.filing_id) ORDER BY f.fetched_at"
            ).fetchall()
        finally:
            con.close()
        vault = Vault(vault_dir)
        for url, fetched, exch, path, sha in rows:
            stage_results_listing(vault, stage_root, data=vault.read_path(path, sha), source_url=url,
                                  fetched_at=fetched, exchange=exch, run_suffix="evidence")  # fmt: skip
        print(f"staged {len(rows)} results listings (run promote)", file=out)
        return 0
    if args.cmd == "backfill-group-structure":
        from financials.group_structure import backfill_group_structure

        con = connect(db_path)
        try:
            apply_schema(con)
            con.execute("BEGIN")
            r = backfill_group_structure(con, Vault(vault_dir), limit=args.limit)
            con.execute("COMMIT")
        finally:
            con.close()
        print(json.dumps(r, indent=1), file=out)
        return 1 if r["error_count"] else 0
    if args.cmd == "backfill-rpt":
        from financials.related_parties import backfill_rpt

        con = connect(db_path)
        try:
            apply_schema(con)
            con.execute("BEGIN")
            r = backfill_rpt(con, Vault(vault_dir), limit=args.limit)
            con.execute("COMMIT")
        finally:
            con.close()
        print(json.dumps(r, indent=1), file=out)
        return 1 if r["error_count"] else 0
    if args.cmd == "backfill-disclosures":
        from financials.disclosures import backfill_disclosures

        con = connect(db_path)
        try:
            apply_schema(con)
            r = backfill_disclosures(con, Vault(vault_dir), stage_root, limit=args.limit, workers=args.workers)
        finally:
            con.close()
        print(json.dumps(r, indent=1), file=out)
        return 1 if r["error_count"] else 0
    if args.cmd == "backfill-audit-opinions":
        from financials.audit_opinions import backfill_audit_opinions

        con = connect(db_path)
        try:
            apply_schema(con)
            r = backfill_audit_opinions(con, Vault(vault_dir), stage_root, limit=args.limit, workers=args.workers)
        finally:
            con.close()
        print(json.dumps(r, indent=1), file=out)
        return 1 if r["error_count"] else 0
    if args.cmd == "audit-annual":
        from financials.promoter import audit_annual_checks

        con = connect(db_path)
        try:
            con.execute("BEGIN")
            r = audit_annual_checks(con)
            con.execute("COMMIT")
        finally:
            con.close()
        print(json.dumps(r, indent=1), file=out)
        return 0
    if args.cmd == "audit-ytd":
        from financials.promoter import audit_ytd_identity

        con = connect(db_path)
        try:
            pairs = con.execute("SELECT DISTINCT entity_id, scope FROM filing_meta ORDER BY 1, 2").fetchall()
            con.execute("BEGIN")
            ids = audit_ytd_identity(con, pairs)
            closed = close_resolved_share_findings(con)
            con.execute("COMMIT")
        finally:
            con.close()
        print(f"{len(ids)} YTD_QUARTER_MISMATCH findings over {len(pairs)} entity-scopes", file=out)
        print(f"{closed} share cross-check finding(s) closed on re-check [X103]", file=out)
        return 0
    if args.cmd == "rescale-level-slips":
        from financials.admin import rescale_level_slips

        con = connect(db_path, read_only=args.dry_run)
        try:
            slips = rescale_level_slips(con, dry_run=args.dry_run)
        finally:
            con.close()
        for x in slips:
            print(f"{x['filing_id']} {x['scope']} {x['period_end']} {x['source_url'].rsplit('/', 1)[-1]} "
                  f"corrections={x.get('corrections', '-')} {x['verdict'].evidence()}", file=out)  # fmt: skip
        print(f"{len(slips)} filing(s) {'found' if args.dry_run else 'rescaled'} [X201]", file=out)
        return 0
    if args.cmd == "import-vault":
        from financials.fetch.replay import ImportRefused, import_vault

        try:
            staged, errors, stats = import_vault(Vault(vault_dir), stage_root, args.dirs)
        except ImportRefused as exc:
            print(f"error: refused, nothing imported: {exc}", file=out)
            return 1
        for e in errors:
            print(f"error: {e}", file=out)
        print(" ".join(f"{k}={v}" for k, v in stats.items()), file=out)
        print(f"staged {len(staged)} batch(es) from {len(args.dirs)} runner vault(s) (run promote)", file=out)
        return 1 if errors else 0
    if args.cmd == "import-bse":
        from financials.fetch.bse import import_ledger

        staged, errors = import_ledger(Vault(vault_dir), stage_root, args.ledger_dir)
        for e in errors:
            print(f"error: {e}", file=out)
        print(f"staged {len(staged)} BSE file(s) from {args.ledger_dir} (run promote)", file=out)
        return 1 if errors else 0
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

    if args.cmd == "screens":  # curated file, no database needed
        from dataclasses import asdict

        from financials.dsl import load_saved_screens

        print(json.dumps([asdict(v) for v in load_saved_screens().values()], indent=1), file=out)
        return 0
    if args.cmd in ("screen", "ratios", "check-issue-size") or (
        args.cmd == "quarantine" and args.qcmd in ("list", "inspect")
    ):
        return read_command(args, db_path, out)

    if args.cmd == "compact":
        from financials.storage import compact

        if args.spill is not None:
            from financials.storage import compact_via_spill

            r = compact_via_spill(db_path, args.spill)
            print(f"compact: {r.status} {r.message}", file=out)
            return 0 if r.status == "COMPACTED" else 1
        if not db_path.exists():
            print(f"error: no market database at {db_path}", file=out)
            return 2
        r = compact(db_path, keep_old=args.keep_old)
        print(f"compact: {r.status} {r.message}", file=out)
        return 0 if r.status == "COMPACTED" else 1
    rc = write_command(args, db_path, stage_root, out)
    if args.cmd == "drop-raw-xbrl":
        if rc == 0 and not args.no_compact:
            from financials.storage import compact_via_spill, maybe_compact

            if args.spill is not None:
                r = compact_via_spill(db_path, args.spill)
                print(f"compact: {r.status} {r.message}", file=out)
            elif maybe_compact(db_path, out, data_dir_arg=str(args.data_dir)).status == "REFUSED":
                print(f"compact: low disk? `python -m financials --data-dir {args.data_dir} compact --spill DIR` "
                      "needs room for the Parquet only", file=out)  # fmt: skip
        return rc
    full_run = (args.cmd == "materialize" and args.from_date is not None and not args.incremental) or args.cmd in (
        "rebuild-market", "prune-versions", "migrate-sparse-history")  # fmt: skip
    if rc == 0 and full_run and not getattr(args, "no_compact", False) and not getattr(args, "dry_run", False):
        from financials.storage import maybe_compact

        maybe_compact(db_path, out, data_dir_arg=str(args.data_dir))  # dead space of the rewritten history [§4.1]
    return rc


def write_command(args, db_path: Path, stage_root: Path, out) -> int:
    """Every command that opens the market database for writing (the single writer)."""
    args.data_dir.mkdir(parents=True, exist_ok=True)
    con = connect(db_path)
    try:
        if args.cmd == "migrate-sparse-history":  # before apply_schema, which refuses the wide table
            from financials.features_store import migrate_legacy

            print(json.dumps(migrate_legacy(con)), file=out)
            return 0
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
            with materialize_run(con, r["features_dates"]) as prices:
                results = materialize_days(con, r["features_dates"], prices=prices, report=_reporter(out))
            done = [fr.as_of_date for fr in results if fr.status == "PROMOTED"]
            if done == r["features_dates"]:
                settle_full_run(con, done)
            return 1 if waiting else 0
        if args.cmd == "prune-versions":
            from financials.storage import StorageError, prune_versions

            try:
                r = prune_versions(con, args.archive or args.data_dir / "archive", dry_run=args.dry_run,
                                   note=args.note)  # fmt: skip
            except StorageError as exc:
                print(f"error: {exc}", file=out)
                return 1
            for p in r.plan:
                if p["rows"] or args.dry_run:
                    print(f"{p['table']} {p['parser_version']}: {p['rows']} of {p['total_rows']} rows "
                          + ("removable" if args.dry_run else "removed"), file=out)  # fmt: skip
            print(f"prune-versions: {r.status} {r.removed} rows" + (f", manifest {r.manifest}" if r.manifest else ""),
                  file=out)  # fmt: skip
            return 0
        if args.cmd == "drop-raw-xbrl":
            from financials.raw_xbrl import COLUMNS, drop_raw_xbrl

            r = drop_raw_xbrl(con, note=args.note)
            for row in r.coverage:
                print(" | ".join(f"{c} {row[c]}" for c in COLUMNS), file=out)
            print(f"drop-raw-xbrl: {r.status} {r.message}", file=out)
            return 1 if r.status == "REFUSED" else 0
        if args.cmd == "materialize":
            if args.incremental:
                if args.as_of is not None or args.from_date is not None:
                    print("error: --incremental takes only --to", file=out)
                    return 2
                return materialize_incremental_cli(con, args.to_date, out)
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
        if args.cmd == "save-ratio":
            from financials.dsl import DslError, save_custom_ratio

            try:
                save_custom_ratio(con, args.name, args.expression)
            except DslError as exc:
                print(f"error: {exc}", file=out)
                return 2
            print(f"saved custom ratio {args.name!r} = {args.expression}", file=out)
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
        if args.cmd == "lineage":
            return lineage.run_cli(con, args, out)
        if args.cmd == "bse-members":
            from financials.universe import bse_members

            rows = bse_members(con, args.as_of or utc_to_ist_date(utc_now()))
            for r in rows:
                print(json.dumps(r, default=str), file=out)
            codes = [r["bse_scrip_code"] for r in rows if r["bse_scrip_code"]]
            print(f"{len(rows)} Permitted members, {len(codes)} with a BSE scrip code (rule BSE1); scrips: "
                  + ",".join(codes), file=out)  # fmt: skip
            return 0
        if args.cmd == "update-universe":
            from financials.universe import update_universe, weekly_growth

            con.execute("BEGIN")
            r = update_universe(con, args.from_date, args.to_date or utc_to_ist_date(utc_now()))
            con.execute("COMMIT")
            print(json.dumps(r, default=str, indent=1), file=out)
            for d, reason, n in weekly_growth(con):
                if args.from_date <= d:
                    print(f"{d} {reason} {n}", file=out)
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
    `active` = every security with an open identifier interval, `mcap500` = members of the sticky Rs 500 Cr
    universe joined by `as_of` (financials.universe), `mcap500-new` = those of them without financials yet."""
    if not db_path.exists():
        raise SystemExit(f"error: --universe needs a market database at {db_path}")
    con = connect(db_path, read_only=True)
    try:
        if name in ("mcap500", "mcap500-new"):
            from financials.universe import members

            return members(con, as_of, new_only=name == "mcap500-new")
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


def universe_series(db_path: Path) -> dict[str, str]:
    """Current series of every symbol with an open identifier interval (read-only); EQ wins over BE / BZ."""
    con = connect(db_path, read_only=True)
    try:
        rows = con.execute(
            "SELECT symbol, min(CASE series WHEN 'EQ' THEN '0' ELSE series END) FROM security_identifier_history "
            "WHERE valid_to IS NULL GROUP BY 1"
        ).fetchall()
    finally:
        con.close()
    return {sym: "EQ" if s == "0" else s for sym, s in rows}


def classified_symbols(db_path: Path) -> set[str]:
    """Symbols (open identifier interval) whose entity has a current NSE classification (read-only)."""
    if not db_path.exists():
        return set()
    con = connect(db_path, read_only=True)
    try:
        rows = con.execute(
            "SELECT DISTINCT h.symbol FROM security_identifier_history h JOIN securities s USING (security_id) "
            "WHERE h.valid_to IS NULL AND s.entity_id IN "
            "(SELECT entity_id FROM entity_classification_history WHERE valid_to IS NULL)"
        ).fetchall()
    finally:
        con.close()
    return {r[0] for r in rows}


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
    elif args.cmd == "fetch-mcap":
        staged, errors = jobs.mcap_days(mcap_dates(db_path, max(args.start, MIN_TRADE_DATE), args.end or args.start,
                                                   weekly=args.weekly, out=out))  # fmt: skip
    elif args.cmd == "fetch-corp-actions":
        staged += jobs.corp_actions(max(args.start, MIN_TRADE_DATE), args.end)
    elif args.cmd == "fetch-holidays":
        staged += jobs.holidays()
    elif args.cmd == "fetch-equity-master":
        staged += jobs.equity_master()
    elif args.cmd == "fetch-index":
        staged += jobs.index_snapshot(args.as_of)
    elif args.cmd == "fetch-shareholding":
        syms = _symbols(args, db_path, args.symbols)
        if args.all_history:
            for sym in syms:
                staged += jobs.shareholding(sym, latest_only=False)
        else:
            staged, errors = jobs.discover(syms, ["shareholding"], events=False)
    elif args.cmd == "fetch-classification":
        syms = _symbols(args, db_path, args.symbols)
        if args.missing_only:
            done = classified_symbols(db_path)
            syms = [sym for sym in syms if sym not in done]
            print(f"fetch-classification: {len(syms)} symbol(s) without a classification", file=out)
        series = universe_series(db_path) if args.universe else {}
        staged, errors = jobs.classification(syms, series)
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
        from financials.fetch.replay import parse_shard, read_symbols_file, shard

        syms = _symbols(args, db_path, args.symbols)
        if args.symbols_file:
            syms += [s for s in read_symbols_file(args.symbols_file) if s not in syms]
        if args.from_rss:
            syms += [s for s in jobs.symbols_from_rss() if s not in syms]
        if args.shard:
            syms = shard(syms, *parse_shard(args.shard))
            print(f"discover-filings: shard {args.shard}: {len(syms)} symbol(s)", file=out)
        jobs.record_responses = args.record_responses
        jobs.shp_min_as_of = args.shp_from
        staged, errors = jobs.discover(syms, args.kinds, events=not args.no_events, workers=args.workers)
    return staged, errors


def mcap_dates(db_path: Path, start: date, end: date, *, weekly: bool, out) -> list[date]:
    """Promoted trading days in [start, end] (read-only), or only each week's last trading day (`weekly`)."""
    if not db_path.exists():
        raise SystemExit(f"error: fetch-mcap needs a market database at {db_path} (trading days)")
    con = connect(db_path, read_only=True)
    try:
        if weekly:
            from financials.universe import week_end_trading_days

            days, unknown = week_end_trading_days(con, start, end)
            if unknown:
                print(f"note: week end not yet known for {', '.join(map(str, unknown))}", file=out)
        else:
            days = [d for (d,) in con.execute(
                "SELECT cal_date FROM trading_calendar WHERE exchange = 'NSE' AND is_trading AND cal_date BETWEEN ? "
                "AND ? ORDER BY 1", [start, end]).fetchall()]  # fmt: skip
    finally:
        con.close()
    print(f"fetch-mcap: {len(days)} trading day(s)", file=out)
    return days


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
    with materialize_run(con, dates) as prices:  # bars read once for the whole run [§11.11]
        # ascending, so G4 always compares with the previous materialised date; live table once, on the last day
        results = materialize_days(con, dates, prices=prices, report=_reporter(out))
    if any(r.status != "PROMOTED" for r in results):
        return 1
    settle_full_run(con, dates)  # dirty markers this full run made obsolete
    return 0


def _reporter(out):
    def report(r) -> None:
        print(f"{r.status} {r.as_of_date} rows={r.rows} {r.gate or ''} {r.message}", file=out)

    return report


def materialize_incremental_cli(con, to: date | None, out) -> int:
    r = materialize_incremental(con, to)
    for d in r.days:
        print(f"{d.status} {d.as_of_date} rows={d.rows} {d.gate or ''} {d.message}", file=out)
    print(f"incremental: {r.status} {r.message}" + (f", {r.entities} dirty entities" if r.entities else ""), file=out)
    return 0 if r.status in ("DONE", "NOTHING") else 1


def run_day(args, transport: Transport | None, out) -> int:
    """Idempotent daily run for `--date D`: holiday list, market days D-lookback..D (vaulted days are not fetched
    again; each with its PR-zip mcap file), corporate actions D-lookback..D+30 (announced ahead of ex-date),
    discovery for the symbols with results in today's RSS plus Reg. 30 events, then promote, apply universe rule U1
    to the week ends in D-lookback..D (financials.universe) and materialise D. Fetch failures are reported; the rest
    of the run continues, and the next run picks up what failed."""
    vault_dir, stage_root, db_path = _paths(args.data_dir)
    jobs = Jobs(PoliteFetcher(transport, warmup=WARMUP), Vault(vault_dir), stage_root)
    d = args.date or utc_to_ist_date(utc_now())
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
        from financials.universe import update_universe

        con.execute("BEGIN")  # rule U1 for the week ends in the lookback (D itself once its week is known to end)
        u = update_universe(con, max(d - timedelta(days=args.lookback_days), MIN_TRADE_DATE), d)
        con.execute("COMMIT")
        print(f"universe: {u['joined']} joined, {u['members']} members ({u['week_ends']} week end(s))", file=out)
        # Dirty rows of earlier days first (a late filing, a resolved gap), so D's percentile history is current;
        # then D in full. A version mismatch skips the catch-up (it needs a full run) but still publishes D.
        caught_up = materialize_incremental_cli(con, d - timedelta(days=1), out)
        if is_trading_day(con, "NSE", d) is False:  # holiday / weekend per the promoted calendar: no day to publish
            print(f"{d}: not a trading day; nothing to materialise", file=out)
            rc = caught_up
        else:
            rc = materialize_dates(con, d, None, None, out) or caught_up
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
            from financials.dsl import DslError, split_columns

            try:
                if args.saved:
                    from financials.dsl import run_saved_screen

                    if args.query or args.order_by:
                        raise DslError("--saved takes no query and no --order-by (the saved screen has its own)")
                    rows = run_saved_screen(con, args.saved, args.as_of, columns=split_columns(args.columns),
                                            limit=args.limit)  # fmt: skip
                elif not args.query:
                    raise DslError("give a query or --saved NAME")
                else:
                    limit = 500 if args.limit is None else args.limit
                    rows = run_screen(con, args.query, as_of=args.as_of, limit=limit,
                                      columns=split_columns(args.columns), order_by=args.order_by,
                                      descending=args.desc)  # fmt: skip
            except DslError as exc:
                print(f"error: {exc}", file=out)
                return 2
            print(json.dumps(rows, default=str, indent=1), file=out)
            return 0
        if args.cmd == "check-issue-size":
            from financials.universe import issue_size_check

            print(json.dumps(issue_size_check(con, args.as_of, include_agreeing=args.all), default=str, indent=1),
                  file=out)  # fmt: skip
            return 0
        if args.cmd == "ratios":
            from financials.dsl import load_custom_ratios

            print(json.dumps(load_custom_ratios(con), indent=1, sort_keys=True), file=out)
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
