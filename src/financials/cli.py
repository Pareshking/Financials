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

    args.data_dir.mkdir(parents=True, exist_ok=True)
    con = connect(db_path)
    try:
        apply_schema(con)
        if args.cmd == "init-db":
            print(f"schema applied to {db_path}", file=out)
            return 0
        if args.cmd == "promote":
            return 1 if promote_pending(con, stage_root, out) else 0
        if args.cmd == "materialize":
            r = materialize(con, args.as_of)
            print(f"{r.status} {r.as_of_date} rows={r.rows} {r.gate or ''} {r.message}", file=out)
            return 0 if r.status == "PROMOTED" else 1
        if args.cmd == "screen":
            rows = run_screen(con, args.query, as_of=args.as_of)
            print(json.dumps(rows, default=str, indent=1), file=out)
            return 0
    finally:
        con.close()
    return 2
