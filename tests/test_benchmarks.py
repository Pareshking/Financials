"""Performance regression guards (generous margins; real numbers are in docs/benchmarks.md).

These catch order-of-magnitude regressions such as per-row/per-security query loops (N+1), e.g. the
2026-11-12 promotion that took 11.2 s before gap quarantines were bulk-inserted (now < 1 s locally).
"""

import statistics
import time
from datetime import date

import pytest
from conftest import Market

from _fixture_helpers import CORP, XBRL_DIR
from financials.dsl import run_screen
from financials.features import materialize
from financials.parsers.indas_corp import parse_indas_corp_results
from financials.parsers.shareholding import parse_shareholding
from financials.promoter import promote


def timed(fn, repeat=1) -> float:
    xs = []
    for _ in range(repeat):
        t = time.perf_counter()
        fn()
        xs.append(time.perf_counter() - t)
    return statistics.median(xs)


def test_gap_heavy_market_day_promotes_fast(tmp_path):
    m = Market(tmp_path)
    assert promote(m.con, m.stage_day("20251014", with_delivery=True)).status == "PROMOTED"
    stage = m.stage_day("20261112", with_delivery=True)  # ~2,100 gap quarantines vs a bar 13 months earlier
    t = time.perf_counter()
    r = promote(m.con, stage)
    elapsed = time.perf_counter() - t
    assert r.status == "PROMOTED" and len(r.quarantined) > 1500
    assert elapsed < 6.0, f"market-day promotion took {elapsed:.1f}s"
    m.con.close()


@pytest.mark.parametrize(
    ("parse", "path", "limit_s"),
    [
        (parse_indas_corp_results, CORP, 0.25),
        (parse_shareholding, XBRL_DIR / "SHP_1739151_15102026054406_WEB.xml", 0.4),
    ],
    ids=["indas_corp", "reg31"],
)
def test_xbrl_parse_latency(parse, path, limit_s):
    data = path.read_bytes()
    assert timed(lambda: parse(data), repeat=5) < limit_s


def test_materialization_and_dsl_latency(full_market):
    con = full_market.con
    elapsed = timed(lambda: materialize(con, date(2026, 11, 12)))
    assert elapsed < 5.0, f"materialize took {elapsed:.2f}s"
    queries = [
        "Market Cap > 100 AND Promoter holding > 30",
        "(roe > 15 OR roce > 20) AND NOT debt to equity > 1 AND pe < 40",
        "(net profit - 2) / (sales + 1) * 100 > 10 AND In Nifty 500 = 1",
    ]
    for q in queries:
        run_screen(con, q)
        median = timed(lambda q=q: run_screen(con, q), repeat=7)
        assert median < 0.2, f"{q!r} took {median * 1000:.0f} ms"


def test_incremental_materialization_recomputes_a_subset_fast(full_market):
    """`materialize --incremental` for 300 dirty entities on one day: one batched compute restricted to them (no
    per-entity queries), then G5/G4 on the merged day; it must stay well below a full day's materialisation."""
    from financials import dirty
    from financials.features import materialize_incremental

    con = full_market.con
    day = date(2026, 11, 12)
    full = timed(lambda: materialize(con, day))
    ents = [e for (e,) in con.execute(
        "SELECT DISTINCT entity_id FROM screener_features_history WHERE as_of_date = ? ORDER BY 1 LIMIT 300", [day]
    ).fetchall()]  # fmt: skip
    con.execute("DELETE FROM materialize_dirty")
    dirty.mark_entities(con, ents, day, "BENCH")
    t = time.perf_counter()
    r = materialize_incremental(con)
    elapsed = time.perf_counter() - t
    assert r.status == "DONE" and [d.as_of_date for d in r.days] == [day], r
    assert elapsed < 1.5, f"incremental (300 entities, 1 day) took {elapsed:.2f}s (full day {full:.2f}s)"
