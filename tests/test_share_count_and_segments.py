"""Market-cap share-count hierarchy (Reg. 31 -> paid-up / face value, then corporate-action factors) and the
point-in-time segment helper over raw facts."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from conftest import FETCHED_AT

from _fixture_helpers import XBRL_DIR
from financials.features import market_cap_shares
from financials.parsers.segments import parse_segments
from financials.promoter import promote
from financials.staging import stage_results_xbrl
from financials.statements.segments import segment_facts, segment_totals

D = Decimal
REG31, PAID = (D(49709220), date(2026, 9, 30)), (D(48754000), date(2026, 9, 30))
SPLIT_1_5 = (date(2026, 10, 15), D("0.2"), D("0.2"))  # (ex_date, price factor, eps factor): 10 -> 2 face value


def test_reg31_total_wins_over_paid_up():
    assert market_cap_shares(REG31, PAID, [], date(2026, 11, 12)) == (REG31[0], REG31[1], "REG31")


def test_paid_up_is_the_fallback_and_nothing_means_null():
    assert market_cap_shares(None, PAID, [], date(2026, 11, 12)) == (PAID[0], PAID[1], "PAID_UP")
    assert market_cap_shares(None, None, [SPLIT_1_5], date(2026, 11, 12)) == (None, None, None)


def test_share_count_actions_after_the_count_date_scale_the_count():
    shares, counted, _ = market_cap_shares(REG31, None, [SPLIT_1_5], date(2026, 11, 12))
    assert (shares, counted) == (REG31[0] * 5, date(2026, 9, 30))
    # before the ex-date (point in time) and for an action before the count date: unchanged
    assert market_cap_shares(REG31, None, [SPLIT_1_5], date(2026, 10, 14))[0] == REG31[0]
    early = (date(2026, 9, 1), D("0.5"), D("0.5"))
    assert market_cap_shares(REG31, None, [early], date(2026, 11, 12))[0] == REG31[0]


SRF = XBRL_DIR / "INTEGRATED_FILING_INDAS_1743533_21102026080703_WEB.xml"


def test_segment_facts_are_queryable_per_entity_and_match_the_file(market):
    """[X49] SRF Q2 FY27 consolidated: the helper returns from the database exactly what parse_segments reads."""
    m = market
    promote(m.con, m.stage_day("20261112"))
    seen = datetime(2026, 10, 21, 8, 0)
    s = stage_results_xbrl(m.vault, m.stage_root, data=SRF.read_bytes(),
                           source_url="https://nsearchives.nseindia.com/corporate/xbrl/" + SRF.name,
                           fetched_at=FETCHED_AT, broadcast_ts=seen, broadcast_ts_source="API_FIELD")  # fmt: skip
    assert promote(m.con, s).status == "PROMOTED"
    ent = m.con.execute("SELECT entity_id FROM filing_meta").fetchone()[0]
    assert segment_facts(m.con, ent, datetime(2026, 10, 21, 7, 59)) == []  # not yet visible
    rows = segment_facts(m.con, ent, seen)
    report = parse_segments(SRF.read_bytes())
    assert len(rows) == len(report.facts) > 0
    assert {r["segment"] for r in rows} == set(report.segments)
    q = (date(2026, 7, 1), date(2026, 9, 30))
    by_segment = segment_totals(rows, "SegmentRevenue", q)
    assert sum(by_segment.values()) == report.total("SegmentRevenue", q[1], q[0])
    assert segment_facts(m.con, ent, seen, scope="STANDALONE") == []
