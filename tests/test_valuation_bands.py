"""Reverse DCF and historical valuation percentiles [C20]."""

from datetime import date

import pytest

from financials.db import apply_schema, connect
from financials.features import _valuation_history
from financials.fundamentals import percentile_rank, reverse_dcf_implied_growth


def _dcf(fcff, g, wacc=0.12, tg=0.04, n=5):
    pv = sum(fcff * (1 + g) ** t / (1 + wacc) ** t for t in range(1, n + 1))
    return pv + fcff * (1 + g) ** n * (1 + tg) / ((wacc - tg) * (1 + wacc) ** n)


@pytest.mark.parametrize("g", [-0.10, 0.0, 0.08, 0.25, 0.60])
def test_reverse_dcf_round_trip(g):
    assert reverse_dcf_implied_growth(_dcf(100.0, g), 100.0) == pytest.approx(g, abs=1e-5)


def test_reverse_dcf_nulls():
    assert reverse_dcf_implied_growth(1000.0, -5.0) is None  # cash-burning: FCFF <= 0
    assert reverse_dcf_implied_growth(-10.0, 5.0) is None  # EV <= 0
    assert reverse_dcf_implied_growth(None, 5.0) is None
    assert reverse_dcf_implied_growth(1e12, 1.0) is None  # beyond +300% p.a.: no solution in range


def test_percentile_rank():
    assert percentile_rank(20.0, [10.0, 15.0, 25.0, 30.0]) == 0.5
    assert percentile_rank(20.0, [10.0, 15.0, 25.0]) is None  # min_periods_required = 4
    assert percentile_rank(20.0, [10.0, -5.0, 15.0, 25.0, None, 30.0]) == 0.5  # non-positive / NULL ignored
    assert percentile_rank(-3.0, [10.0, 15.0, 25.0, 30.0]) is None


def test_history_is_one_value_per_prior_quarter():
    con = connect()
    apply_schema(con)
    rows = [("2026-04-10", 10.0), ("2026-06-30", 12.0), ("2026-07-15", 14.0), ("2026-09-29", 16.0),
            ("2026-10-05", 99.0)]  # fmt: skip
    for d, pe in rows:
        con.execute(
            "INSERT INTO screener_features_history (as_of_date, security_id, entity_id, symbol, series, pe, ev_ebitda)"
            " VALUES (?, 's', 'e', 'S', 'EQ', ?, ?)",
            [d, pe, pe / 2],
        )
    h = _valuation_history(con, date(2026, 11, 13))
    assert sorted(h["s"]["pe"]) == [12.0, 16.0]  # last value of Q1 FY27 and Q2 FY27; current quarter excluded
    assert sorted(h["s"]["ev_ebitda"]) == [6.0, 8.0]
