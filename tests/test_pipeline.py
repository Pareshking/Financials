"""End-to-end: vault → staging Parquet → promoter → market.duckdb, on real fixture files."""

import io
import zipfile
from datetime import date, datetime
from decimal import Decimal

import pytest
from conftest import FETCHED_AT, bhav_bytes, bhav_url

from _fixture_helpers import CORP, NBFC
from financials.corp_actions import CorpAction
from financials.promoter import adjusted_closes, pit_fact, promote, record_corp_action, verify_pending_actions
from financials.staging import stage_market_day, stage_results_xbrl

XBRL_URL = "https://nsearchives.nseindia.com/corporate/xbrl/"


def count(m, sql, params=()):
    return m.con.execute(sql, list(params)).fetchone()[0]


def gap_quarantines(m, symbol, trade_date):
    sec = m.security_id(symbol)
    return m.con.execute(
        "SELECT reason_code, resolution FROM quarantine_queue WHERE stage = 'GAP' AND security_id = ? "
        "AND CAST(json_extract_string(details, '$.trade_date') AS DATE) = ?",
        [sec, trade_date],
    ).fetchall()


def promote_day(m, d, **kw):
    return promote(m.con, m.stage_day(d, **kw))


def test_market_day_promotes_and_is_idempotent(market):
    stage = market.stage_day("20251014", with_delivery=True)
    first = promote(market.con, stage)
    assert first.status == "PROMOTED", first
    assert promote(market.con, stage).status == "ALREADY_PROMOTED"
    n = count(market, "SELECT count(*) FROM ohlcv WHERE trade_date = ?", [date(2025, 10, 14)])
    assert n == 2460  # EQ/BE/BZ rows for the day
    assert count(market, "SELECT count(*) FROM raw_cm_bhavcopy") == 3215  # raw keeps every series
    tm = market.con.execute(
        "SELECT close, deliv_qty FROM ohlcv o JOIN security_identifier_history h USING (security_id) "
        "WHERE h.symbol = 'TATAMOTORS'"
    ).fetchone()
    assert tm == (Decimal("395.4500"), 20939394)
    assert count(market, "SELECT count(*) FROM trading_calendar WHERE is_trading") == 1


def test_split_with_recorded_action_verifies_and_is_not_quarantined(market):
    assert promote_day(market, "20250919").status == "PROMOTED"
    adani = market.security_id("ADANIPOWER")
    bhav_filing = market.con.execute("SELECT filing_id FROM filings LIMIT 1").fetchone()[0]
    record_corp_action(
        market.con,
        CorpAction("ca-adani", adani, "SPLIT", date(2025, 9, 22), Decimal(2), Decimal(10)),
        source_filing_id=bhav_filing,
    )
    assert promote_day(market, "20250922").status == "PROMOTED"
    status, factor = market.con.execute(
        "SELECT status, price_factor FROM corp_actions WHERE action_id = 'ca-adani'"
    ).fetchone()
    assert (status, factor) == ("VERIFIED", 0.2)
    assert gap_quarantines(market, "ADANIPOWER", date(2025, 9, 22)) == []
    history = market.con.execute(
        "SELECT isin, valid_from, valid_to FROM security_identifier_history WHERE security_id = ? "
        "ORDER BY valid_from",
        [adani],
    ).fetchall()
    assert history == [
        ("INE814H01011", date(2025, 9, 19), date(2025, 9, 22)),
        ("INE814H01029", date(2025, 9, 22), None),
    ]
    closes = dict(adjusted_closes(market.con, adani))
    assert closes[date(2025, 9, 19)] == Decimal("709.4000") * Decimal("0.2")


def test_unrecorded_bonus_is_quarantined_then_resolved_when_action_arrives(market):
    promote_day(market, "20250922")
    promote_day(market, "20250923")
    assert gap_quarantines(market, "PIDILITIND", date(2025, 9, 23)) == [("UNEXPLAINED_GAP", None)]
    pid = market.security_id("PIDILITIND")
    assert [d for d, _ in adjusted_closes(market.con, pid)] == [date(2025, 9, 22)]  # frozen

    filing = market.con.execute("SELECT filing_id FROM filings LIMIT 1").fetchone()[0]
    record_corp_action(
        market.con,
        CorpAction("ca-pid", pid, "BONUS", date(2025, 9, 23), Decimal(1), Decimal(1)),
        source_filing_id=filing,
    )
    assert verify_pending_actions(market.con, "NSE") == 1
    assert gap_quarantines(market, "PIDILITIND", date(2025, 9, 23)) == [("UNEXPLAINED_GAP", "FIXED_BY_RULE")]
    closes = dict(adjusted_closes(market.con, pid))
    assert closes[date(2025, 9, 22)] == Decimal("3038.0000") * Decimal("0.5")
    assert closes[date(2025, 9, 23)] == Decimal("1489.3000")


def test_isin_change_without_split_record_is_quarantined(market):
    promote_day(market, "20250919")
    promote_day(market, "20250922")
    reasons = {r for r, _ in gap_quarantines(market, "ADANIPOWER", date(2025, 9, 22))}
    assert reasons == {"UNEXPLAINED_GAP", "ISIN_CHANGE_WITHOUT_ACTION"}


def test_wrong_ratio_is_quarantined(market):
    promote_day(market, "20250922")
    pid = market.security_id("PIDILITIND")
    filing = market.con.execute("SELECT filing_id FROM filings LIMIT 1").fetchone()[0]
    record_corp_action(
        market.con,
        CorpAction("ca-bad", pid, "BONUS", date(2025, 9, 23), Decimal(1), Decimal(2)),
        source_filing_id=filing,
    )
    promote_day(market, "20250923")
    assert market.con.execute("SELECT status FROM corp_actions").fetchone()[0] == "QUARANTINED"
    assert count(market, "SELECT count(*) FROM quarantine_queue WHERE stage = 'CORP_ACTION'") == 1
    assert gap_quarantines(market, "PIDILITIND", date(2025, 9, 23)) == [("UNEXPLAINED_GAP", None)]


def test_demerger_ex_date(market):
    promote_day(market, "20251013")
    tm = market.security_id("TATAMOTORS")
    filing = market.con.execute("SELECT filing_id FROM filings LIMIT 1").fetchone()[0]
    record_corp_action(
        market.con, CorpAction("ca-tm", tm, "DEMERGER", date(2025, 10, 14)), source_filing_id=filing
    )
    promote_day(market, "20251014")
    status, pf, ef = market.con.execute(
        "SELECT status, price_factor, eps_factor FROM corp_actions"
    ).fetchone()
    assert status == "VERIFIED" and ef == 1.0
    assert pf == pytest.approx(400 / 660.75)
    assert gap_quarantines(market, "TATAMOTORS", date(2025, 10, 14)) == []


def test_series_change_across_promotions_keeps_one_security(market):
    promote_day(market, "20250923")
    promote_day(market, "20251013")
    rows = market.con.execute(
        "SELECT DISTINCT security_id FROM security_identifier_history WHERE symbol = 'AAATECH'"
    ).fetchall()
    assert len(rows) == 1
    assert count(market, "SELECT count(*) FROM quarantine_queue WHERE stage = 'IDENTIFIER'") == 0


def _truncated_bhav(yyyymmdd: str, keep: int) -> bytes:
    with zipfile.ZipFile(io.BytesIO(bhav_bytes(yyyymmdd))) as zf:
        lines = zf.read(zf.namelist()[0]).decode().splitlines()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("x.csv", "\n".join(lines[: keep + 1]))
    return buf.getvalue()


def test_g1_aborts_truncated_day_without_writing(market):
    promote_day(market, "20251013")
    before = count(market, "SELECT count(*) FROM raw_cm_bhavcopy")
    stage = stage_market_day(
        market.vault,
        market.stage_root,
        bhavcopy=_truncated_bhav("20251014", 500),
        bhavcopy_url=bhav_url("20251014"),
        delivery=None,
        delivery_url=None,
        fetched_at=FETCHED_AT,
    )
    result = promote(market.con, stage)
    assert (result.status, result.gate) == ("ABORTED", "G1")
    assert count(market, "SELECT count(*) FROM raw_cm_bhavcopy") == before
    assert count(market, "SELECT count(*) FROM filings") == 1


def test_older_day_after_newer_is_rejected(market):
    promote_day(market, "20251014")
    result = promote_day(market, "20251013")
    assert (result.status, result.gate) == ("ABORTED", "ORDER")


# ── results XBRL ──────────────────────────────────────────────────────────


def stage_corp(market, **kw):
    return stage_results_xbrl(
        market.vault,
        market.stage_root,
        data=CORP.read_bytes(),
        source_url=XBRL_URL + CORP.name,
        fetched_at=FETCHED_AT,
        **kw,
    )


def test_results_filing_with_broadcast_is_point_in_time(market):
    promote_day(market, "20251014")
    broadcast = datetime(2026, 11, 5, 10, 0)  # UTC
    result = promote(
        market.con, stage_corp(market, broadcast_ts=broadcast, broadcast_ts_source="RSS_PUBDATE")
    )
    assert result.status == "PROMOTED", result
    entity = market.con.execute("SELECT entity_id FROM filing_meta").fetchone()[0]
    args = (entity, "STANDALONE", "revenue_from_operations", date(2026, 7, 1), date(2026, 9, 30))
    assert pit_fact(market.con, *args, as_of=datetime(2026, 11, 5, 9, 59)) is None
    assert pit_fact(market.con, *args, as_of=broadcast) == Decimal("2895440000.00")
    assert count(market, "SELECT count(*) FROM raw_xbrl_facts") == 620
    assert count(market, "SELECT count(*) FROM fact_observations") > 90
    meta = market.con.execute(
        "SELECT visible_from_source, interest_paid_cfo_class FROM filing_meta"
    ).fetchone()
    assert meta == ("BROADCAST", "FINANCING")


def test_results_filing_without_broadcast_or_calendar_is_quarantined(market):
    promote_day(market, "20251014")  # calendar has no trading day after the 2026 board meeting
    result = promote(market.con, stage_corp(market))
    assert result.status == "QUARANTINED"
    assert market.con.execute("SELECT reason_code FROM quarantine_queue").fetchall() == [("NO_VISIBILITY",)]
    assert count(market, "SELECT count(*) FROM fact_observations") == 0
    assert count(market, "SELECT count(*) FROM raw_xbrl_facts") == 620  # raw evidence is kept


def test_results_filing_board_meeting_rule(market):
    promote_day(market, "20251014")
    market.con.execute(
        "INSERT INTO trading_calendar VALUES ('NSE', DATE '2026-11-06', TRUE, 'test'), "
        "('NSE', DATE '2026-11-09', TRUE, 'test')"
    )
    result = promote(market.con, stage_corp(market))
    assert result.status == "PROMOTED", result
    visible, source = market.con.execute(
        "SELECT visible_from_ts, visible_from_source FROM filing_meta"
    ).fetchone()
    assert source == "BOARD_MEETING_RULE"
    assert visible == datetime(2026, 11, 5, 18, 30)  # 2026-11-06 00:00 IST


def test_results_filing_for_unknown_issuer_is_quarantined(market):
    result = promote(
        market.con,
        stage_corp(market, broadcast_ts=datetime(2026, 11, 5, 10), broadcast_ts_source="RSS_PUBDATE"),
    )
    assert result.status == "QUARANTINED"
    assert market.con.execute("SELECT stage, reason_code FROM quarantine_queue").fetchall() == [
        ("IDENTITY", "UNKNOWN_ISIN")
    ]


def test_unimplemented_profile_is_quarantined_with_raw_kept(market):
    stage = stage_results_xbrl(
        market.vault,
        market.stage_root,
        data=NBFC.read_bytes(),
        source_url=XBRL_URL + NBFC.name,
        fetched_at=FETCHED_AT,
    )
    result = promote(market.con, stage)
    assert result.status == "QUARANTINED"
    assert market.con.execute("SELECT reason_code FROM quarantine_queue").fetchall() == [
        ("PROFILE_NOT_IMPLEMENTED",)
    ]
    assert count(market, "SELECT count(*) FROM raw_xbrl_facts") == 359
