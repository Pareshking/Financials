"""v1 scope cutoff [C9]: MIN_TRADE_DATE = 2024-10-01, MIN_PERIOD_END_DATE = 2024-12-31."""

import io
import zipfile
from datetime import date, datetime
from decimal import Decimal

from conftest import FETCHED_AT, bhav_bytes, bhav_url
from test_fundamentals import con, insert_rows, quarterly_revenue  # noqa: F401  (fixture + helpers)

from _fixture_helpers import CORP
from financials.fundamentals import cagr, load_factbook, quarters_available_since, yoy_growth
from financials.promoter import promote
from financials.scope import MIN_PERIOD_END_DATE, MIN_TRADE_DATE
from financials.staging import stage_market_day, stage_results_xbrl


def _redate_bhavcopy(src: str, new_iso: str) -> bytes:
    with zipfile.ZipFile(io.BytesIO(bhav_bytes(src))) as zf:
        text = zf.read(zf.namelist()[0]).decode()
    old_iso = f"{src[:4]}-{src[4:6]}-{src[6:]}"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("x.csv", text.replace(old_iso, new_iso))
    return buf.getvalue()


def test_constants():
    assert (date(2024, 10, 1), date(2024, 12, 31)) == (MIN_TRADE_DATE, MIN_PERIOD_END_DATE)


def test_pre_cutoff_market_day_is_vaulted_but_not_loaded(market):
    stage = stage_market_day(
        market.vault, market.stage_root, bhavcopy=_redate_bhavcopy("20251014", "2024-09-30"),
        bhavcopy_url=bhav_url("20240930"), delivery=None, delivery_url=None, fetched_at=FETCHED_AT,
    )  # fmt: skip
    r = promote(market.con, stage)
    assert r.status == "OUT_OF_SCOPE"
    assert market.con.execute("SELECT count(*) FROM filings").fetchone()[0] == 1  # evidence kept
    for t in ("raw_cm_bhavcopy", "ohlcv", "security_identifier_history", "trading_calendar"):
        assert market.con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] == 0, t


def test_first_in_scope_day_loads(market):
    stage = stage_market_day(
        market.vault, market.stage_root, bhavcopy=_redate_bhavcopy("20251014", "2024-10-01"),
        bhavcopy_url=bhav_url("20241001"), delivery=None, delivery_url=None, fetched_at=FETCHED_AT,
    )  # fmt: skip
    assert promote(market.con, stage).status == "PROMOTED"


def _redate_results(data: bytes) -> bytes:
    """ELIN's Q2 FY27 filing shifted to Q2 FY25 (period end 2024-09-30): before the cutoff."""
    for a, b in (
        (b"2027-03-31", b"2025-03-31"),
        (b"2026-09-30", b"2024-09-30"),
        (b"2026-07-01", b"2024-07-01"),
        (b"2026-04-01", b"2024-04-01"),
        (b"2026-03-31", b"2024-03-31"),
        (b"2026-06-30", b"2024-06-30"),
    ):
        data = data.replace(a, b)  # fmt: skip
    return data


def test_pre_cutoff_results_filing_is_out_of_scope(market):
    promote(market.con, market.stage_day("20251014"))
    stage = stage_results_xbrl(
        market.vault, market.stage_root, data=_redate_results(CORP.read_bytes()), source_url="old",
        fetched_at=FETCHED_AT, broadcast_ts=datetime(2024, 11, 5), broadcast_ts_source="RSS_PUBDATE",
    )  # fmt: skip
    r = promote(market.con, stage)
    assert r.status == "OUT_OF_SCOPE" and "2024-09-30" in r.message
    for t in ("raw_xbrl_facts", "filing_meta", "fact_observations", "quarantine_queue"):
        assert market.con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] == 0, t


def test_q3_fy25_ytd_starting_before_cutoff_is_kept():
    """Filter is on period END: the Apr-Dec 2024 YTD of a Q3 FY25 filing is in scope."""
    assert quarters_available_since(date(2024, 12, 31), 1)
    assert not quarters_available_since(date(2024, 9, 30), 1)


def test_multi_year_windows_are_null_until_history_exists(con):  # noqa: F811
    insert_rows(con, "fact_observations", quarterly_revenue())
    book = load_factbook(con, "ent_test", "STANDALONE", datetime(2030, 1, 1))
    end = date(2026, 9, 30)
    # 8 quarters Q3 FY25..Q2 FY27 exist on/after the cutoff: YoY TTM and 1Y CAGR are defined.
    assert yoy_growth(book, "revenue_from_operations", end) is not None
    assert cagr(book, "revenue_from_operations", end, 1) == yoy_growth(book, "revenue_from_operations", end)
    # 3Y / 5Y windows would need quarters before 2024-12-31: NULL, not a partial number.
    assert cagr(book, "revenue_from_operations", end, 3) is None
    assert cagr(book, "revenue_from_operations", end, 5) is None
    # Even though the synthetic book holds Jun/Sep 2024 quarters, a window needing them is NULL.
    assert yoy_growth(book, "revenue_from_operations", date(2025, 9, 30)) is None
    assert cagr(book, "revenue_from_operations", end, 2, min_periods_required=12) is None
    assert isinstance(cagr(book, "revenue_from_operations", end, 1), Decimal)
