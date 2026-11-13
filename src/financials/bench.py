"""Reproducible benchmarks on the committed fixtures.  `python -m financials.bench [--out docs/benchmarks.md]`

Runs the real pipeline offline in a temporary directory: every committed bhavcopy day (+ delivery
where present), corporate actions, holidays, index snapshot, the INDAS_CORP and REG31 filings,
feature materialisation and a set of DSL screens. Numbers depend on the machine; the header records it.
"""

from __future__ import annotations

import argparse
import os
import platform
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb

from financials.db import apply_schema, connect
from financials.dsl import run_screen, save_custom_ratio
from financials.features import materialize
from financials.parsers.indas_corp import parse_indas_corp_results
from financials.parsers.shareholding import parse_shareholding, parse_shp_master
from financials.promoter import promote
from financials.staging import (
    stage_corp_actions,
    stage_holidays,
    stage_index_snapshot,
    stage_market_day,
    stage_results_xbrl,
    stage_shareholding,
)
from financials.vault import Vault

DAYS = ("20250919", "20250922", "20250923", "20251013", "20251014", "20261112")
SCREENS = (
    "Market Cap > 100 AND Promoter holding > 30",
    "(roe > 15 OR roce > 20) AND NOT debt to equity > 1 AND pe < 40",
    "Return 1M > 5 OR price to 200dma > 1.1 OR delivery velocity > 1.5",
    "(net profit - 2) / (sales + 1) * 100 > 10 AND In Nifty 500 = 1",
    "net cash to mcap > 5 AND market cap > 500",
    "In Nifty 500 = 1 AND (fii holding + dii holding) > 20 OR price to book value < 1",
)


def _ms(fn: Callable[[], object], repeat: int = 1) -> list[float]:
    out = []
    for _ in range(repeat):
        t = time.perf_counter()
        fn()
        out.append((time.perf_counter() - t) * 1000)
    return out


def _pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    k = (len(xs) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def _size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) if path.is_dir() else path.stat().st_size


def run(fixtures: Path, work: Path) -> dict:
    bh, ix = fixtures / "bhavcopy", fixtures
    vault, stage_root = Vault(work / "vault"), work / "staging"
    con = connect(work / "market.duckdb")
    apply_schema(con)
    now = datetime(2026, 11, 13, 9, 0)
    res: dict = {"days": []}

    for d in DAYS:
        bhav = (bh / f"BhavCopy_NSE_CM_0_0_0_{d}_F_0000.csv.zip").read_bytes()
        dp = bh / f"sec_bhavdata_full_{d[6:]}{d[4:6]}{d[:4]}.csv"
        deliv = dp.read_bytes() if dp.exists() else None
        t0 = time.perf_counter()
        stage = stage_market_day(vault, stage_root, bhavcopy=bhav, bhavcopy_url=f"bench://{d}", delivery=deliv,
                                 delivery_url=f"bench://d{d}" if deliv else None, fetched_at=now)  # fmt: skip
        t1 = time.perf_counter()
        r = promote(con, stage)
        t2 = time.perf_counter()
        raw = con.execute("SELECT count(*) FROM raw_cm_bhavcopy WHERE trade_date = ?",
                          [date.fromisoformat(f"{d[:4]}-{d[4:6]}-{d[6:]}")]).fetchone()[0]  # fmt: skip
        n_deliv = con.execute("SELECT count(*) FROM raw_delivery WHERE trade_date = ?",
                              [date.fromisoformat(f"{d[:4]}-{d[4:6]}-{d[6:]}")]).fetchone()[0]  # fmt: skip
        res["days"].append({"day": d, "status": r.status, "raw_rows": raw, "delivery_rows": n_deliv,
                            "stage_ms": (t1 - t0) * 1000, "promote_ms": (t2 - t1) * 1000})  # fmt: skip
        if d == "20250919":
            ca = (ix / "corp_actions" / "nse_corporateActions_equities_15-09-2025_17-10-2025.json").read_bytes()
            promote(con, stage_corp_actions(vault, stage_root, data=ca, source_url="bench://ca", fetched_at=now))
    hol = (ix / "calendar" / "nse_holiday-master_trading_20261113.json").read_bytes()
    promote(con, stage_holidays(vault, stage_root, data=hol, source_url="bench://hol", fetched_at=now))
    lst = (ix / "indices" / "ind_nifty500list_20261113.csv").read_bytes()
    promote(con, stage_index_snapshot(vault, stage_root, data=lst, source_url="bench://idx", index_name="NIFTY 500",
                                      snapshot_date=date(2026, 11, 12), fetched_at=now))  # fmt: skip

    corp = (ix / "xbrl" / "INTEGRATED_FILING_INDAS_1753867_05112026061857_WEB.xml").read_bytes()
    shp = (ix / "xbrl" / "SHP_1739151_15102026054406_WEB.xml").read_bytes()
    res["parse_indas_corp_ms"] = _ms(lambda: parse_indas_corp_results(corp), 20)
    res["parse_reg31_ms"] = _ms(lambda: parse_shareholding(shp), 20)
    promote(con, stage_results_xbrl(vault, stage_root, data=corp, source_url="bench://xbrl", fetched_at=now))
    master = parse_shp_master((ix / "shareholding" / "nse_corporate-share-holdings-master_ELIN_20261113.json")
                              .read_bytes())[0]  # fmt: skip
    promote(con, stage_shareholding(vault, stage_root, data=shp, source_url=master.xbrl_url, fetched_at=now,
                                    broadcast_ts=master.broadcast_ts_ist.astimezone(UTC).replace(tzinfo=None),
                                    broadcast_ts_source="API_FIELD"))  # fmt: skip

    materialize(con, date(2025, 10, 14))
    t = time.perf_counter()
    m = materialize(con, date(2026, 11, 12))
    res["materialize_ms"] = (time.perf_counter() - t) * 1000
    res["materialize_rows"] = m.rows
    res["materialize_status"] = m.status

    save_custom_ratio(con, "net cash to mcap", "(0 - net debt) / market cap * 100")
    res["screens"] = {}
    for q in SCREENS:
        run_screen(con, q)  # warm
        res["screens"][q] = _ms(lambda q=q: run_screen(con, q), 50)
    con.execute("CHECKPOINT")
    con.close()
    res["sizes"] = {
        "market.duckdb": _size(work / "market.duckdb"),
        "staging (Parquet)": _size(stage_root),
        "vault (raw files)": _size(work / "vault"),
    }
    return res


def render(res: dict) -> str:
    lines = [
        "# Benchmarks",
        "",
        "Generated by `python -m financials.bench --out docs/benchmarks.md` on the committed fixtures (offline).",
        f"Machine: {platform.platform()}, {os.cpu_count()} CPUs, Python {platform.python_version()}, "
        f"DuckDB {duckdb.__version__}. Single run; expect ±30% between runs and slower CI runners.",
        "",
        "## 1. Market-day ingestion (UDiFF bhavcopy + sec_bhavdata_full)",
        "",
        "| Day | Raw rows | Delivery rows | Stage (parse + Parquet) ms | Promote ms | Total ms | Rows/s |",
        "|---|---|---|---|---|---|---|",
    ]
    for d in res["days"]:
        total = d["stage_ms"] + d["promote_ms"]
        rows = d["raw_rows"] + d["delivery_rows"]
        lines.append(f"| {d['day']} | {d['raw_rows']:,} | {d['delivery_rows']:,} | {d['stage_ms']:.0f} | "
                     f"{d['promote_ms']:.0f} | {total:.0f} | {rows / total * 1000:,.0f} |")  # fmt: skip
    pc, ps = res["parse_indas_corp_ms"], res["parse_reg31_ms"]
    lines += [
        "",
        "Promote includes identity resolution, G1/G2, `ohlcv`, corporate-action verification and the gap auditor.",
        "",
        "## 2. XBRL parsing (20 runs)",
        "",
        "| Filing | p50 ms | p95 ms |",
        "|---|---|---|",
        f"| INDAS_CORP results (ELIN, 620 facts) | {_pct(pc, 0.5):.1f} | {_pct(pc, 0.95):.1f} |",
        f"| REG31 shareholding (ELIN, 1,436 facts) | {_pct(ps, 0.5):.1f} | {_pct(ps, 0.95):.1f} |",
        "",
        "## 3. Feature materialisation",
        "",
        f"Full universe for 2026-11-12: **{res['materialize_rows']:,} rows in {res['materialize_ms']:.0f} ms** "
        f"({res['materialize_status']}), including G4 (null-spike vs 2025-10-14) and G5 (atomic swap).",
        "",
        "## 4. DSL screen latency (50 runs each, warm)",
        "",
        "| Screen | p50 ms | p95 ms |",
        "|---|---|---|",
    ]
    for q, xs in res["screens"].items():
        lines.append(f"| `{q}` | {_pct(xs, 0.5):.2f} | {_pct(xs, 0.95):.2f} |")
    allq = [x for xs in res["screens"].values() for x in xs]
    lines += [
        f"| **all screens** | **{_pct(allq, 0.5):.2f}** | **{_pct(allq, 0.95):.2f}** |",
        "",
        "## 5. Storage footprint (after all promotions, `CHECKPOINT`)",
        "",
        "| Store | Bytes | MB |",
        "|---|---|---|",
    ]
    for k, v in res["sizes"].items():
        lines.append(f"| {k} | {v:,} | {v / 1e6:.1f} |")
    lines += ["", "Regression guards with generous margins live in `tests/test_benchmarks.py`.", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="financials.bench")
    p.add_argument("--fixtures", type=Path, default=Path("tests/fixtures"))
    p.add_argument("--out", type=Path)
    args = p.parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        text = render(run(args.fixtures, Path(tmp)))
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
