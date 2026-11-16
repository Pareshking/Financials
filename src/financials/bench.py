"""Reproducible benchmarks on the committed fixtures.  `python -m financials.bench [--out docs/benchmarks.md]`

Runs the real pipeline offline in a temporary directory: every committed bhavcopy day (+ delivery
where present), corporate actions, holidays, index snapshot, the INDAS_CORP and REG31 filings,
feature materialisation and a set of DSL screens. Numbers depend on the machine; the header records it.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
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
    # Incremental (§11.10): one filed entity dirty since 2025-10-14 (2 materialised days), then 300 entities on 1 day.
    from financials import dirty
    from financials.features import materialize_incremental

    con.execute("DELETE FROM materialize_dirty")
    ent = con.execute("SELECT DISTINCT entity_id FROM filing_meta ORDER BY 1").fetchone()[0]
    dirty.mark_entities(con, [ent], date(2025, 10, 14), "BENCH")
    t = time.perf_counter()
    inc = materialize_incremental(con)
    res["incremental_1_ms"], res["incremental_1_days"] = (time.perf_counter() - t) * 1000, len(inc.days)
    ents = [e for (e,) in con.execute("SELECT DISTINCT entity_id FROM screener_features_history WHERE as_of_date = ? "
                                       "ORDER BY 1 LIMIT 300", [date(2026, 11, 12)]).fetchall()]  # fmt: skip
    dirty.mark_entities(con, ents, date(2026, 11, 12), "BENCH")
    t = time.perf_counter()
    inc = materialize_incremental(con)
    res["incremental_300_ms"], res["incremental_status"] = (time.perf_counter() - t) * 1000, inc.status

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


def extend_synthetic(path: Path, n_secs: int, start: date, end: date, seed: int = 11) -> list[date]:
    """Synthetic history on every weekday from `start` to `end` without a fixture day, for the first `n_secs`
    securities traded on 2025-09-19 (random walks with holes in high / low / delivery, accepted splits, some two on
    one ex-date), Nifty 500 closes for every day, identifiers valid from `start`. Benchmarks and the fast-path
    equality test (never real data: the database at `path` is a throwaway copy). Returns every bar date."""
    import random

    import pyarrow as pa

    con = connect(path)
    rng = random.Random(seed)
    have = {d for (d,) in con.execute("SELECT DISTINCT trade_date FROM ohlcv").fetchall()}
    days, d = [], start
    while d <= end:
        if d.weekday() < 5 and d not in have:
            days.append(d)
        d += timedelta(days=1)
    base = con.execute(
        "SELECT security_id, exchange, series, close, price_filing_id FROM ohlcv WHERE trade_date = '2025-09-19' "
        "ORDER BY security_id LIMIT ?",
        [n_secs],
    ).fetchall()
    cols: dict[str, list] = {c: [] for c in ("security_id", "exchange", "series", "trade_date", "open", "high", "low",
                                              "close", "volume", "turnover_inr", "deliv_qty", "price_filing_id",
                                              "delivery_filing_id")}  # fmt: skip
    for sec, ex, series, close, fid in base:
        c = float(close)
        for d in days:
            c = max(1.0, c * (1 + rng.gauss(0, 0.02)))
            hole = rng.random() < 0.02
            vol = rng.randint(1000, 1_000_000)
            for k, v in (("security_id", sec), ("exchange", ex), ("series", series), ("trade_date", d),
                         ("open", round(c, 2)), ("high", None if hole else round(c * 1.01, 2)),
                         ("low", None if hole else round(c * 0.99, 2)), ("close", round(c, 2)), ("volume", vol),
                         ("turnover_inr", round(vol * c, 2)),
                         ("deliv_qty", None if rng.random() < 0.05 else int(vol * rng.random())),
                         ("price_filing_id", fid), ("delivery_filing_id", None)):  # fmt: skip
                cols[k].append(v)
    t = pa.table(cols)  # noqa: F841 (read by DuckDB)
    con.execute("INSERT INTO ohlcv SELECT * FROM t")
    fid = base[0][4]
    idx_days = sorted(set(days) | have)
    level, idx = 20000.0, {"index_name": [], "trade_date": [], "close": [], "filing_id": []}
    for d in idx_days:
        level *= 1 + rng.gauss(0, 0.01)
        if rng.random() > 0.002:  # a missing index close now and then (beta / RS / PEAD NULL around it)
            for k, v in (("index_name", "Nifty 500"), ("trade_date", d), ("close", round(level, 2)),
                         ("filing_id", fid)):  # fmt: skip
                idx[k].append(v)
    it = pa.table(idx)  # noqa: F841
    con.execute("DELETE FROM index_ohlcv WHERE upper(index_name) = 'NIFTY 500'")
    con.execute("INSERT INTO index_ohlcv (index_name, trade_date, close, filing_id) SELECT * FROM it")
    ent = dict(con.execute("SELECT security_id, entity_id FROM securities").fetchall())
    for i, (sec, *_rest, fid) in enumerate(base):
        if i % 6 == 0:
            exd = days[rng.randrange(len(days))]
            for j in range(1 + (i % 12 == 0)):  # two actions on the same ex-date for some
                pf = rng.choice((0.5, 0.2, 2 / 3))
                con.execute(
                    "INSERT INTO corp_actions (action_id, entity_id, security_id, action_type, ex_date, price_factor, "
                    "eps_factor, status, source_filing_id, decided_at) VALUES (?, ?, ?, 'SPLIT', ?, ?, ?, 'VERIFIED', "
                    "?, ?)",
                    [f"syn-{sec}-{j}", ent.get(sec), sec, exd, pf, pf, fid, exd],
                )
    con.execute(
        """UPDATE security_identifier_history h SET valid_from = ?
           FROM (SELECT security_id, exchange, min(valid_from) AS v FROM security_identifier_history GROUP BY ALL) m
           WHERE h.security_id = m.security_id AND h.exchange = m.exchange AND h.valid_from = m.v
             AND m.v <= DATE '2025-09-19'""",
        [start],
    )
    out = [d for (d,) in con.execute("SELECT DISTINCT trade_date FROM ohlcv ORDER BY 1").fetchall()]
    con.close()
    return out


def run_synthetic(db: Path, work: Path, n_secs: int, legacy_days: int = 3) -> dict:
    """Materialise every day of the fixture market extended with `n_secs` synthetic histories (2024-10-01 to
    2026-11-11): one full run on the run-level path (per-day timings), then the per-day legacy path
    (FINANCIALS_MATERIALIZE_LEGACY=1) for `legacy_days` days spread over the history on a copy holding the same
    earlier days (each rewrites one day of a copy that holds the run's history)."""
    from financials import features
    from financials.price_history import LEGACY_ENV

    path = work / "synthetic.duckdb"
    shutil.copy(db, path)
    con = connect(path)
    con.execute("DELETE FROM screener_features_history")
    con.execute("DELETE FROM features_meta")
    con.execute("DELETE FROM market_breadth")
    con.close()
    requested = n_secs
    days = extend_synthetic(path, n_secs, date(2024, 10, 1), date(2026, 11, 11))
    con = connect(path, read_only=True)
    n_secs = con.execute("SELECT count(DISTINCT security_id) FROM ohlcv WHERE trade_date = ?", [days[0]]).fetchone()[0]
    con.close()
    shutil.copy(path, work / "synthetic_legacy.duckdb")
    con = connect(path)
    res: dict = {"secs": n_secs, "requested": requested, "days": len(days), "per_day": []}
    t0 = time.perf_counter()
    with features.materialize_run(con, days) as prices:
        res["load_s"] = time.perf_counter() - t0
        for d in days:
            t = time.perf_counter()
            r = features.materialize(con, d, prices=prices)
            res["per_day"].append((d, time.perf_counter() - t, r.rows))
            if r.status != "PROMOTED":
                raise RuntimeError(f"{d}: {r}")
    res["total_s"] = time.perf_counter() - t0
    res["rss_mb"] = _rss_mb()
    con.close()
    # The legacy path on a few days, each on a database holding every earlier materialised day (as in a run).
    sample = [days[int(i * (len(days) - 1) / max(1, legacy_days - 1))] for i in range(legacy_days)]
    res["legacy"] = []
    lcon = connect(work / "synthetic_legacy.duckdb")
    lcon.execute(f"ATTACH '{path}' AS fast (READ_ONLY)")
    lcon.execute("INSERT INTO screener_features_history SELECT * FROM fast.screener_features_history")
    lcon.execute("INSERT INTO features_meta SELECT * FROM fast.features_meta")
    lcon.execute("DETACH fast")
    for d in sample:
        os.environ[LEGACY_ENV] = "1"
        try:
            t = time.perf_counter()
            r = features.materialize(lcon, d)  # rewrites day d; the earlier days are already there
            legacy_s = time.perf_counter() - t
        finally:
            os.environ.pop(LEGACY_ENV, None)
        fast_s = next(s for x, s, _ in res["per_day"] if x == d)
        res["legacy"].append((d, r.rows, legacy_s, fast_s))
    lcon.close()
    return res


def _rss_mb() -> float:
    try:
        import resource

        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    except ImportError:  # not on Windows
        return float("nan")


def render(res: dict) -> str:
    lines = [
        "# Benchmarks",
        "",
        "Generated by `python -m financials.bench "
        + (
            f"--synthetic {res['synthetic']['requested']} --legacy-days {len(res['synthetic']['legacy'])} "
            if res.get("synthetic")
            else ""
        )
        + "--out docs/benchmarks.md` on the committed fixtures (offline).",
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
        f"Incremental (`materialize --incremental`, {res['incremental_status']}): one dirty entity over "
        f"{res['incremental_1_days']} materialised days **{res['incremental_1_ms']:.0f} ms**; 300 dirty entities on "
        f"2026-11-12 **{res['incremental_300_ms']:.0f} ms** (restricted batch reads, then G5/G4 on the merged day).",
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
    syn = res.get("synthetic")
    if syn:
        per = syn["per_day"]
        q = [per[int(i * (len(per) - 1) / 8)] for i in range(9)]
        lines += [
            "",
            "## 6. Full materialisation run over a long synthetic history (`--synthetic N`)",
            "",
            f"The fixture market plus random-walk histories for {syn['secs']:,} securities (every security of the "
            f"2025-09-19 fixture day, up to N) on every weekday from 2024-10-01 (accepted splits, holes, Nifty 500 "
            f"closes; `bench.extend_synthetic`): {syn['days']} days, "
            f"one `materialize --from/--to` run on the run-level path (§11.11). Price history read in "
            f"{syn['load_s']:.1f} s; **whole run {syn['total_s'] / 60:.1f} min** "
            f"({syn['total_s'] / syn['days']:.2f} s a day on average), peak RSS {syn['rss_mb']:,.0f} MB.",
            "",
            "| Day | Rows | Run-level path s (materialize incl. gates and write) |",
            "|---|---|---|",
        ]
        lines += [f"| {d} | {n:,} | {t:.2f} |" for d, t, n in q]
        lines += [
            "",
            "Per-day legacy path (`FINANCIALS_MATERIALIZE_LEGACY=1`: every day re-reads and recomputes the whole "
            "history) on the same days, each rewriting one day of a copy that holds the run's history:",
            "",
            "| Day | Rows | Legacy s | Run-level s | Speed-up |",
            "|---|---|---|---|---|",
        ]
        lines += [f"| {d} | {n:,} | {lt:.2f} | {ft:.2f} | {lt / ft:.1f}x |" for d, n, lt, ft in syn["legacy"]]
    lines += ["", "Regression guards with generous margins live in `tests/test_benchmarks.py`.", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="financials.bench")
    p.add_argument("--fixtures", type=Path, default=Path("tests/fixtures"))
    p.add_argument("--out", type=Path)
    p.add_argument(
        "--synthetic",
        type=int,
        default=0,
        metavar="N",
        help="also time a full run over N synthetic 2-year histories (section 6; N=3000: ~30 min)",
    )
    p.add_argument("--legacy-days", type=int, default=3, help="days timed on the legacy path in section 6")
    args = p.parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        res = run(args.fixtures, Path(tmp))
        if args.synthetic:
            res["synthetic"] = run_synthetic(Path(tmp) / "market.duckdb", Path(tmp), args.synthetic, args.legacy_days)
        text = render(res)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
