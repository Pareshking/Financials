"""Compare the run-level materialize path with the per-day legacy path on a real database (architecture §11.10).

    python scripts/compare_materialize.py data/market.duckdb --from 2024-10-01 --to 2026-11-13 [--every 5]

Never writes the source: the database is copied to a temporary directory first (or, with --no-copy, opened
read-only in place, which DuckDB refuses while a writer holds it); the copy is opened read-only too, unless
--store asks for the rows to be kept in it. For every chosen day it computes the feature rows twice through
`features.compute_rows`: once with one `PriceHistory` for the whole run (the default path) and once with
FINANCIALS_MATERIALIZE_LEGACY=1 (every day re-reads and recomputes the whole history); the fast path keeps the
run's per-entity fundamentals cache across the chosen days, as a materialize run does. Both read the same stored
history (PE / EV-EBITDA percentile bands) of the copy, so any difference is the price path. --store --keep also
writes both row sets into the tables `cmp_fast` and `cmp_legacy` of the kept copy for inspection in SQL (never the
source). It reports, per column, rows that differ:
Decimal values must be equal, floats equal within --rel (default 1e-12; bit-identical is expected), NULLs identical.
Exit 0 when nothing differs, 1 otherwise. The legacy path is slow on a long history (~25-35 s a day at the end of
the data); --every N compares every Nth day (plus the last) to bound the run.
"""

from __future__ import annotations

import argparse
import math
import os
import shutil
import sys
import tempfile
import time
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path


def same(a, b, rel: float) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, float) or isinstance(b, float):
        if not (isinstance(a, float) and isinstance(b, float)):
            return False
        if math.isnan(a) or math.isnan(b):
            return math.isnan(a) and math.isnan(b)
        return a == b or abs(a - b) <= rel * max(abs(a), abs(b))
    if isinstance(a, Decimal) or isinstance(b, Decimal):
        return isinstance(a, Decimal) and isinstance(b, Decimal) and a == b
    return type(a) is type(b) and a == b


def _store(con, table: str, columns: list[str], rows: list[dict]) -> None:
    import pyarrow as pa

    con.execute(f"CREATE TABLE IF NOT EXISTS {table} AS SELECT * FROM screener_features_history LIMIT 0")
    t = pa.Table.from_pylist([{c: r.get(c) for c in columns} for r in rows])  # noqa: F841 (read by DuckDB)
    con.execute(f"INSERT INTO {table} SELECT * FROM t")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="compare_materialize", description=__doc__.split("\n\n")[0])
    p.add_argument("db", type=Path)
    p.add_argument("--from", dest="start", type=date.fromisoformat, required=True)
    p.add_argument("--to", dest="end", type=date.fromisoformat, required=True)
    p.add_argument("--every", type=int, default=1, help="compare every Nth trading day (and the last)")
    p.add_argument("--rel", type=float, default=1e-12, help="relative float tolerance")
    p.add_argument("--exchange", default="NSE")
    p.add_argument("--no-copy", action="store_true", help="open the database read-only in place (no copy)")
    p.add_argument("--keep", action="store_true", help="keep the temporary copy (its path is printed)")
    p.add_argument("--store", action="store_true", help="write both row sets into cmp_fast / cmp_legacy of the copy")
    p.add_argument("--show", type=int, default=30, help="differences printed in full")
    args = p.parse_args(argv)

    from financials import features
    from financials.db import connect, table_columns
    from financials.price_history import LEGACY_ENV, PriceHistory

    if args.store and args.no_copy:
        p.error("--store writes into the copy: it cannot be combined with --no-copy")
    tmp = None
    path = args.db
    if not args.no_copy:
        tmp = Path(tempfile.mkdtemp(prefix="compare_materialize_"))
        path = tmp / args.db.name
        shutil.copy(args.db, path)
        wal = args.db.with_name(args.db.name + ".wal")
        if wal.exists():
            shutil.copy(wal, path.with_name(path.name + ".wal"))
        print(f"copied {args.db} -> {path}", flush=True)
    con = connect(path, read_only=not args.store)
    try:
        days = [d for (d,) in con.execute(
            "SELECT DISTINCT trade_date FROM ohlcv WHERE exchange = ? AND trade_date BETWEEN ? AND ? ORDER BY 1",
            [args.exchange, args.start, args.end]).fetchall()]  # fmt: skip
        if not days:
            print("no trading days in range")
            return 2
        chosen = sorted(set(days[:: max(1, args.every)]) | {days[-1]})
        columns = table_columns(con, "screener_features_history")
        os.environ.pop(LEGACY_ENV, None)
        t = time.perf_counter()
        prices = PriceHistory(con, args.exchange, chosen[-1])
        prices.fundamentals = features.FundamentalsCache(con, chosen[-1])  # as features.materialize_run
        print(f"{len(chosen)} day(s) {chosen[0]}..{chosen[-1]}; price history read in {time.perf_counter() - t:.1f}s",
              flush=True)  # fmt: skip
        per_col: Counter[str] = Counter()
        shown, total_rows, t_fast, t_legacy = 0, 0, 0.0, 0.0
        for d in chosen:
            t = time.perf_counter()
            fast = features.compute_rows(con, d, args.exchange, prices=prices)
            t_fast += (dt_fast := time.perf_counter() - t)
            os.environ[LEGACY_ENV] = "1"
            try:
                t = time.perf_counter()
                legacy = features.compute_rows(con, d, args.exchange)
                t_legacy += (dt_legacy := time.perf_counter() - t)
            finally:
                os.environ.pop(LEGACY_ENV, None)
            if args.store:
                _store(con, "cmp_fast", columns, fast)
                _store(con, "cmp_legacy", columns, legacy)
            day_diffs = 0
            a = {r["security_id"]: r for r in fast}
            b = {r["security_id"]: r for r in legacy}
            if a.keys() != b.keys():
                per_col["<row set>"] += len(a.keys() ^ b.keys())
                day_diffs += len(a.keys() ^ b.keys())
            for sec in sorted(a.keys() & b.keys()):
                for c in columns:
                    x, y = a[sec].get(c), b[sec].get(c)
                    if not same(x, y, args.rel):
                        per_col[c] += 1
                        day_diffs += 1
                        if shown < args.show:
                            print(f"DIFF {d} {sec} {c}: fast={x!r} legacy={y!r}")
                            shown += 1
            total_rows += len(a)
            print(f"{d}: {len(a)} rows, fast {dt_fast:.2f}s, legacy {dt_legacy:.2f}s, {day_diffs} difference(s)",
                  flush=True)  # fmt: skip
        print(f"\n{total_rows} rows x {len(columns)} columns over {len(chosen)} day(s); "
              f"fast {t_fast:.1f}s, legacy {t_legacy:.1f}s")  # fmt: skip
        if per_col:
            print("DIFFERENCES by column:")
            for c, n in per_col.most_common():
                print(f"  {c}: {n}")
            return 1
        print("IDENTICAL")
        return 0
    finally:
        con.close()
        if tmp is not None:
            if args.keep:
                print(f"kept {path}")
            else:
                shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
