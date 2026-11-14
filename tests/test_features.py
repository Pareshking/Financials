"""Feature materialisation on the full real-data market (prices, results, shareholding, index)."""

from datetime import date
from decimal import Decimal

import pytest

from financials.features import compute_rows, materialize

NOV = date(2026, 11, 12)
OCT = date(2025, 10, 14)


@pytest.fixture(scope="module")
def published(full_market):
    r1 = materialize(full_market.con, OCT)
    assert r1.status == "PROMOTED", r1
    r2 = materialize(full_market.con, NOV)
    assert r2.status == "PROMOTED", r2
    return full_market


def row(m, symbol, as_of=NOV, table="screener_features_history"):
    cur = m.con.execute(f"SELECT * FROM {table} WHERE symbol = ? AND as_of_date = ?", [symbol, as_of])
    names = [d[0] for d in cur.description]
    rows = cur.fetchall()
    assert len(rows) == 1, (symbol, rows)
    return dict(zip(names, rows[0], strict=True))


def test_elin_point_in_time_features(published):
    r = row(published, "ELIN")
    assert r["close"] == Decimal("83.8300")
    assert (r["shares"], r["shares_source"]) == (49709220, "REG31")
    assert r["market_cap"] == (Decimal("83.83") * 49709220).quantize(Decimal("0.01"))
    assert r["total_equity"] == Decimal("4528730000.00")
    assert r["pb"] == pytest.approx(float(r["market_cap"] / r["total_equity"]))
    assert r["pe"] is None and r["sales_ttm"] is None  # only Q2 + H1 known: no TTM window
    assert r["promoter_pct"] == pytest.approx(0.3297)
    # Batch 8 columns, materialised end to end [SHP8-SHP10]. ELIN: no pledge, no NPNP, one quarter only.
    assert r["promoter_holding_pct"] == pytest.approx(0.3297)
    assert r["promoter_holding_pct"] + r["public_holding_pct"] == pytest.approx(1.0)
    assert r["promoter_pledge_pct"] == 0.0 and r["promoter_encumbered_pct"] == 0.0
    assert r["non_promoter_non_public_pct"] == 0.0
    assert r["fii_holding_pct"] is not None and r["dii_holding_pct"] is not None
    assert r["fii_dii_qoq_change_pct"] is None  # no 2026-06-30 filing in this market
    assert (r["scope_used"], r["fundamentals_end"], r["bs_as_of"]) == (
        "STANDALONE",
        date(2026, 9, 30),
        date(2026, 9, 30),
    )
    assert r["shp_as_of"] == date(2026, 9, 30)
    assert r["piotroski_f"] is None and r["beneish_m"] is None


def test_results_are_invisible_before_broadcast(published):
    r = row(published, "ELIN", OCT)
    assert r["total_equity"] is None and r["shares"] is None and r["promoter_pct"] is None


def test_symbol_change_keeps_security_and_index_membership(published):
    tm_2025 = row(published, "TATAMOTORS", OCT)
    tm_2026 = row(published, "TMPV", NOV)
    assert tm_2025["security_id"] == tm_2026["security_id"]
    assert tm_2026["in_nifty500"] is True
    assert tm_2025["in_nifty500"] is False  # membership history starts 2026-11-12 [L1]


def test_delivery_and_momentum_need_history(published):
    r = row(published, "TATAMOTORS", OCT)
    assert r["deliv_avg_5d"] is None and r["delivery_velocity"] is None  # only one delivery day
    assert r["return_1m"] is None and r["price_to_dma50"] is None  # five bars only


def test_live_table_holds_only_latest_date(published):
    dates = published.con.execute("SELECT DISTINCT as_of_date FROM screener_features").fetchall()
    assert dates == [(NOV,)]
    q = "SELECT count(*) FROM screener_features_history WHERE as_of_date = ?"
    n_hist = published.con.execute(q, [NOV]).fetchone()[0]
    n_live = published.con.execute("SELECT count(*) FROM screener_features").fetchone()[0]
    assert n_hist == n_live > 2000


def test_rematerialising_is_idempotent(published):
    before = published.con.execute("SELECT count(*), sum(hash(security_id)) FROM screener_features_history").fetchone()
    assert materialize(published.con, NOV).status == "PROMOTED"
    after = published.con.execute("SELECT count(*), sum(hash(security_id)) FROM screener_features_history").fetchone()
    assert before == after


def test_g4_aborts_on_null_spike(published):
    # Pretend the previous run had full sales coverage; today's ~100% nulls is then a spike.
    con = published.con
    con.execute("CREATE TEMP TABLE keep AS SELECT * FROM screener_features_history WHERE as_of_date = ?", [OCT])
    try:
        con.execute("UPDATE screener_features_history SET sales_ttm = 1 WHERE as_of_date = ?", [OCT])
        result = materialize(con, NOV)
        assert (result.status, result.gate) == ("ABORTED", "G4")
        assert "sales_ttm" in result.message
    finally:
        con.execute("DELETE FROM screener_features_history WHERE as_of_date = ?", [OCT])
        con.execute("INSERT INTO screener_features_history SELECT * FROM keep")
        con.execute("DROP TABLE keep")


def test_g5_aborts_when_universe_is_empty(published):
    result = materialize(published.con, date(2030, 1, 1))
    assert (result.status, result.gate) == ("ABORTED", "G5")
    assert compute_rows(published.con, date(2030, 1, 1)) == []


def test_g4_forgives_only_ttm_nulls_caused_by_the_c9_window():
    """Live backfill 2025-07-28: companies filing Q1 FY26 lose TTM because the window to Jun 2025 needs the Sep and
    Dec 2024 quarters, before the cutoff (C9). That is expected (rule G4_C9_WINDOW); any other new NULL still counts."""
    from datetime import date as d

    from financials.db import apply_schema, connect, insert_rows
    from financials.features import _c9_expected_nulls, _null_rates

    con = connect()
    apply_schema(con)
    base = {"as_of_date": d(2025, 7, 25), "entity_id": "e", "symbol": "S", "series": "EQ", "sales_ttm": 1, "pat_ttm": 1,
            "fundamentals_end": d(2025, 3, 31)}  # fmt: skip
    insert_rows(con, "screener_features_history", [{**base, "security_id": s} for s in ("A", "B", "C", "D")])
    now = [
        {"security_id": "A", "fundamentals_end": d(2025, 6, 30), "sales_ttm": None, "pat_ttm": None},  # C9 window
        {"security_id": "B", "fundamentals_end": d(2025, 3, 31), "sales_ttm": None, "pat_ttm": 1},  # same end: defect
        {"security_id": "C", "fundamentals_end": d(2025, 12, 31), "sales_ttm": None, "pat_ttm": 1},  # window in scope
        {"security_id": "D", "fundamentals_end": d(2025, 6, 30), "sales_ttm": 1, "pat_ttm": 1},
    ]
    forgiven = _c9_expected_nulls(con, d(2025, 7, 25), now)
    assert forgiven == {("A", "sales_ttm"), ("A", "pat_ttm")}
    rates = _null_rates([{**r, "close": 1, "market_cap": 1, "total_equity": 1} for r in now], forgiven)
    assert rates["sales_ttm"] == 0.5 and rates["pat_ttm"] == 0.0
