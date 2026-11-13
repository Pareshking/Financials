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
