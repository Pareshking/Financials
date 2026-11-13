"""Trading calendar (bhavcopy + holiday master) and index membership history."""

import json
from datetime import date, datetime

import pytest
from conftest import FETCHED_AT

from _fixture_helpers import CORP, FIXTURES
from financials.calendar import is_trading_day, next_trading_day, parse_holiday_master
from financials.parsers.indices import parse_index_list
from financials.promoter import SurvivorshipBiasError, index_members, promote
from financials.staging import stage_holidays, stage_index_snapshot, stage_results_xbrl

HOLIDAYS = FIXTURES / "calendar" / "nse_holiday-master_trading_20261113.json"
NIFTY500 = FIXTURES / "indices" / "ind_nifty500list_20261113.csv"
H_URL = "https://www.nseindia.com/api/holiday-master?type=trading"
I_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"


def load_holidays(market, data=None, url=H_URL):
    stage = stage_holidays(
        market.vault, market.stage_root, data=data or HOLIDAYS.read_bytes(), source_url=url, fetched_at=FETCHED_AT
    )
    return promote(market.con, stage)


def test_holiday_master_parses_cash_segment():
    h = dict(parse_holiday_master(HOLIDAYS.read_bytes()))
    assert len(h) == 20
    assert h[date(2026, 1, 26)] == "Republic Day"
    assert h[date(2026, 11, 8)] == "Diwali Laxmi Pujan*"  # Sunday; '*' marks the special session


def test_next_trading_day_skips_weekends_and_holidays(market):
    assert load_holidays(market).status == "PROMOTED"
    assert next_trading_day(market.con, "NSE", date(2026, 1, 23)) == date(2026, 1, 27)  # Fri -> Mon holiday -> Tue
    assert next_trading_day(market.con, "NSE", date(2026, 11, 9)) == date(2026, 11, 11)  # 10 Nov Balipratipada
    assert is_trading_day(market.con, "NSE", date(2026, 11, 7)) is False  # Saturday
    assert next_trading_day(market.con, "NSE", date(2026, 12, 31)) is None  # 2027 not covered: unknown


def test_uncovered_year_without_bhavcopy_is_unknown(market):
    promote(market.con, market.stage_day("20251013"))
    promote(market.con, market.stage_day("20251014"))
    assert next_trading_day(market.con, "NSE", date(2025, 10, 13)) == date(2025, 10, 14)
    assert next_trading_day(market.con, "NSE", date(2025, 10, 14)) is None


def test_bhavcopy_beats_holiday_in_both_orders(market):
    promote(market.con, market.stage_day("20251014"))
    fake = json.dumps({"CM": [{"tradingDate": "14-Oct-2025", "description": "test holiday"}]}).encode()
    load_holidays(market, data=fake, url=H_URL + "&fake")
    assert is_trading_day(market.con, "NSE", date(2025, 10, 14)) is True


def test_board_meeting_visibility_uses_holiday_calendar(market):
    promote(market.con, market.stage_day("20251014"))  # makes ELIN a known security
    load_holidays(market)
    stage = stage_results_xbrl(
        market.vault, market.stage_root, data=CORP.read_bytes(), source_url="u", fetched_at=FETCHED_AT
    )
    assert promote(market.con, stage).status == "PROMOTED"
    visible = market.con.execute("SELECT visible_from_ts FROM filing_meta").fetchone()[0]
    assert visible == datetime(2026, 11, 5, 18, 30)  # board ended Thu 5 Nov -> Fri 6 Nov 00:00 IST


# ── index membership ─────────────────────────────────────────────────────


def snapshot(market, data, snap, run=""):
    stage = stage_index_snapshot(
        market.vault,
        market.stage_root / run,
        data=data,
        source_url=I_URL,
        index_name="NIFTY 500",
        snapshot_date=snap,
        fetched_at=FETCHED_AT,
    )
    return promote(market.con, stage)


def test_index_list_parses():
    members = parse_index_list(NIFTY500.read_bytes())
    assert len(members) == 501
    assert any(m.isin.startswith("DUM") for m in members)  # placeholder row [IDX2]


def test_stale_universe_trips_g2(market):
    """2026 constituents against 2025 prices: IPOs since then are unresolvable, so the gate aborts."""
    promote(market.con, market.stage_day("20251014"))
    result = snapshot(market, NIFTY500.read_bytes(), date(2026, 11, 13))
    assert (result.status, result.gate) == ("ABORTED", "G2")
    assert market.con.execute("SELECT count(*) FROM index_constituents_history").fetchone()[0] == 0


def _resolvable_list(market) -> bytes:
    lines = NIFTY500.read_text().splitlines()
    known = {i for (i,) in market.con.execute("SELECT isin FROM security_identifier_history").fetchall()}
    keep = [lines[0]] + [ln for ln in lines[1:] if ln.split(",")[-1].strip() in known]
    return ("\n".join(keep) + "\n").encode()


def test_membership_intervals_and_point_in_time(market):
    promote(market.con, market.stage_day("20251014"))
    first = _resolvable_list(market)
    assert snapshot(market, first, date(2025, 10, 14)).status == "PROMOTED"
    n = len(first.splitlines()) - 1
    assert len(index_members(market.con, "NIFTY 500", date(2025, 10, 14))) == n

    lines = first.decode().splitlines()
    dropped = lines[1].split(",")[2]  # symbol of the first member
    second = ("\n".join([lines[0], *lines[2:]]) + "\n").encode()
    assert snapshot(market, second, date(2025, 10, 20), run="b").status == "PROMOTED"
    sec = market.security_id(dropped)
    assert sec in index_members(market.con, "NIFTY 500", date(2025, 10, 19))
    assert sec not in index_members(market.con, "NIFTY 500", date(2025, 10, 20))
    (valid_to,) = market.con.execute(
        "SELECT valid_to FROM index_constituents_history WHERE security_id = ?", [sec]
    ).fetchone()
    assert valid_to == date(2025, 10, 20)


def test_query_before_history_starts_is_refused(market):
    promote(market.con, market.stage_day("20251014"))
    snapshot(market, _resolvable_list(market), date(2025, 10, 14))
    with pytest.raises(SurvivorshipBiasError):
        index_members(market.con, "NIFTY 500", date(2024, 1, 1))
    assert index_members(market.con, "NIFTY 500", date(2024, 1, 1), allow_survivorship_bias=True)


def test_older_snapshot_is_rejected(market):
    promote(market.con, market.stage_day("20251014"))
    snapshot(market, _resolvable_list(market), date(2025, 10, 14))
    result = snapshot(market, _resolvable_list(market), date(2025, 10, 1), run="old")
    assert (result.status, result.gate) == ("ABORTED", "ORDER")
