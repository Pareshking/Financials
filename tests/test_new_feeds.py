"""Daily index closes [IDX9] and the NSE equity master [IDX10], from real files."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from conftest import FETCHED_AT

from _fixture_helpers import FIXTURES
from financials.parsers.indices import parse_equity_master, parse_index_closes
from financials.promoter import promote
from financials.staging import stage_equity_master, stage_index_closes

CLOSES = FIXTURES / "indices" / "ind_close_all_13112026.csv"
MASTER = FIXTURES / "indices" / "nse_EQUITY_L_20261114.csv"
ARCH = "https://nsearchives.nseindia.com/content/"


def test_index_closes_parse_with_nifty500_levels_and_no_tri_rows():
    rows = parse_index_closes(CLOSES.read_bytes())
    assert len(rows) == 167 and {r.trade_date for r in rows} == {date(2026, 11, 13)}
    (n500,) = [r for r in rows if r.index_name == "Nifty 500"]
    assert (n500.close, n500.pe, n500.turnover_inr) == (Decimal("23734.2"), 22.19, Decimal("872794300000.00"))
    assert not [r for r in rows if "TOTAL RETURN" in r.index_name.upper() or r.index_name.upper().endswith(" TRI")]


def test_equity_master_parses_spaced_header():
    rows = parse_equity_master(MASTER.read_bytes())
    assert len(rows) == 2635
    (tcs,) = [r for r in rows if r.symbol == "TCS"]
    assert (tcs.isin, tcs.face_value, tcs.listing_date) == ("INE467B01029", Decimal("1"), date(2004, 8, 25))


def test_both_feeds_promote_into_raw_tables(market):
    m = market
    s1 = stage_index_closes(m.vault, m.stage_root, data=CLOSES.read_bytes(),
                            source_url=ARCH + "indices/" + CLOSES.name, fetched_at=FETCHED_AT)  # fmt: skip
    s2 = stage_equity_master(m.vault, m.stage_root, data=MASTER.read_bytes(),
                             source_url=ARCH + "equities/EQUITY_L.csv", fetched_at=FETCHED_AT)  # fmt: skip
    assert promote(m.con, s1).status == promote(m.con, s2).status == "PROMOTED"
    assert m.con.execute("SELECT count(*) FROM index_ohlcv").fetchone()[0] == 167
    assert m.con.execute("SELECT count(*) FROM raw_equity_master").fetchone()[0] == 2635
    assert promote(m.con, s1).status == "PROMOTED"  # replay: append-only, identical rows ignored
    assert m.con.execute("SELECT count(*) FROM index_ohlcv").fetchone()[0] == 167
