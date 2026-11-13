"""Batch 10, part 1: Reg. 30 structured event XBRL [E1-E7].

Fixtures (tests/fixtures/events): the 13-Nov-2026 announcements RSS and nine real event filings (two byte-identical
Aptech re-sends). Broadcast times come from the RSS pubDate (IST).
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

import pytest
from conftest import FETCHED_AT

from _fixture_helpers import FIXTURES
from financials.features import EVENT_COLUMNS, _event_counts
from financials.parsers.reg30_events import parse_announcements_rss, parse_reg30_event
from financials.promoter import promote
from financials.staging import stage_reg30_event
from financials.timeutil import ist_to_utc

EV = FIXTURES / "events"
RSS = EV / "nse_Online_announcements_20261113.xml"
BEL = EV / "REG30_PARA_B_1254_WebXMLFile_20261113_183420254.xml"
JSWINFRA = EV / "REG30_PARA_B_21978_WebXMLFile_20261113_182712819.xml"
APTECH_1 = EV / "REG30_PARA_B_2010_WebXMLFile_20261113_133459972.xml"
APTECH_2 = EV / "REG30_PARA_B_2010_WebXMLFile_20261113_133619258.xml"
JINDALPOLY = EV / "REG30_PARA_B_490_WebXMLFile_20261113_204423166.xml"
CMSINFO = EV / "CIM_19883_WebXMLFile_20261113_215018364.xml"
SHRIRAMPPS = EV / "CIM_17080_WebXMLFile_20261113_201057828.xml"
ITC = EV / "ALTERATION_OF_CAPITAL_AND_FUND_RAISING_818_WebXMLFile_20261113_152039711.xml"
FRAUD = EV / "ANN_FRAUD_22342_WebXMLFile_20261113_211505185.xml"
ALL = [BEL, JSWINFRA, APTECH_1, APTECH_2, JINDALPOLY, CMSINFO, SHRIRAMPPS, ITC, FRAUD]


@pytest.fixture(scope="module")
def rss():
    return {i.xbrl_url.rsplit("/", 1)[-1]: i for i in parse_announcements_rss(RSS.read_bytes()) if i.xbrl_url}


def test_rss_items_link_event_xbrl_with_ist_broadcast_time(rss):
    """E1: 2,259 items, 305 with an XBRL link; pubDate is IST, mostly to the second, a few to the minute."""
    items = parse_announcements_rss(RSS.read_bytes())
    assert len(items) == 2259 and len(rss) == 305 and all(i.pub_ts_ist for i in items)
    assert rss[BEL.name].pub_ts_ist == datetime(2026, 11, 13, 18, 34, 21)
    minute_only = [i for i in items if i.pub_ts_ist.second == 0 and i.pub_ts_ist.microsecond == 0]
    assert len(minute_only) >= 5
    for p in ALL:
        assert p.name in rss, p.name


def test_order_wins(rss):
    """E3: Para B sub-para 4 'Bagging/Receiving of orders/contracts': amount in INR, counterparty when named."""
    bel = parse_reg30_event(BEL.read_bytes())
    assert bel.family == "PARA_B" and bel.ok and bel.meta["stated_symbol"] == "BEL"
    (e,) = bel.events
    assert (e["event_type"], e["amount_inr"], e["counterparty"]) == ("ORDER_WIN", Decimal("6190000000"), None)
    (j,) = parse_reg30_event(JSWINFRA.read_bytes()).events
    assert j["amount_inr"] == Decimal("600000000") and j["counterparty"].startswith("Dedicated Freight Corridor")
    assert j["details"]["related_party"] == "false"


def test_litigation():
    (e,) = parse_reg30_event(JINDALPOLY.read_bytes()).events
    assert e["event_type"] == "LITIGATION" and e["details"]["stage"] == "Development in relation to proceedings"


def test_kmp_and_auditor_resignations():
    """E5: one record per person on ChangeInManagementAxis; a resignation is TypeOfChange=Cessation with
    CategoryOfCessation=Resignation."""
    (cs,) = parse_reg30_event(CMSINFO.read_bytes()).events
    assert (cs["event_type"], cs["person_category"], cs["change_type"], cs["cessation_category"]) == (
        "MANAGEMENT_CHANGE", "Key Managerial Personnel", "Cessation", "Resignation"
    )  # fmt: skip
    auditors = parse_reg30_event(SHRIRAMPPS.read_bytes()).events
    assert len(auditors) == 2 and {a["event_type"] for a in auditors} == {"AUDITOR_CHANGE"}
    assert {a["cessation_category"] for a in auditors} == {"Resignation"}


def test_allotment_has_share_counts_but_no_amount():
    """E6: ESOP allotment: shares before/after; the taxonomy has no consideration element (amount NULL)."""
    (e,) = parse_reg30_event(ITC.read_bytes()).events
    assert e["event_type"] == "ALLOTMENT" and e["event_subtype"] == "ESOP/ESPS" and e["amount_inr"] is None
    assert int(e["details"]["shares_post"]) - int(e["details"]["shares_pre"]) == 785300


def test_fraud_or_default_has_no_isin_and_a_text_amount():
    """E7: symbol only (no ISIN); amount is free text, never a number."""
    r = parse_reg30_event(FRAUD.read_bytes())
    assert r.ok and r.meta["stated_isin"] is None and r.meta["stated_symbol"] == "SHANTHALA"
    (e,) = r.events
    assert e["event_type"] == "FRAUD_OR_DEFAULT" and e["amount_inr"] is None
    assert "794.36" in e["details"]["amount_text"]


def _promote_all(m, rss):
    results = {}
    for p in ALL:
        pub = rss[p.name].pub_ts_ist
        stage = stage_reg30_event(
            m.vault, m.stage_root, data=p.read_bytes(), source_url="https://nsearchives.nseindia.com/corporate/xbrl/"
            + p.name, fetched_at=FETCHED_AT, broadcast_ts=ist_to_utc(pub.date(), pub.time()),
            broadcast_ts_source="RSS_PUBDATE")  # fmt: skip
        results[p.name] = promote(m.con, stage)
    return results


@pytest.fixture
def events_market(market, rss):
    promote(market.con, market.stage_day("20261112"))
    market.results = _promote_all(market, rss)
    return market


def test_events_promote_and_resends_are_one_event(events_market):
    m = events_market
    expected = dict.fromkeys((p.name for p in ALL), "PROMOTED")
    expected[FRAUD.name] = "QUARANTINED"  # SHANTHALA trades in the SME series (SM): outside the universe
    assert {n: r.status for n, r in m.results.items()} == expected
    reason = m.con.execute("SELECT reason_code FROM quarantine_queue WHERE stage = 'IDENTITY'").fetchone()[0]
    assert reason == "UNKNOWN_SYMBOL"
    rows = m.con.execute("SELECT event_type, count(*) FROM corporate_events GROUP BY 1 ORDER BY 1").fetchall()
    # Aptech's two byte-identical files are one order win (event_id = blob sha256 + record) [E4]
    assert dict(rows) == {"ALLOTMENT": 1, "AUDITOR_CHANGE": 2, "LITIGATION": 1, "MANAGEMENT_CHANGE": 1,
                          "ORDER_WIN": 3}  # fmt: skip
    assert m.con.execute("SELECT count(*) FROM filings WHERE category = 'REG30_EVENT'").fetchone()[0] == 9


def test_event_counts_are_point_in_time(events_market):
    m = events_market
    before = _event_counts(m.con, date(2026, 11, 13), ist_to_utc(date(2026, 11, 13), time(12, 0)))
    assert sum(v["order_wins_90d"] for v in before.values()) == 0
    after = _event_counts(m.con, date(2026, 11, 13), ist_to_utc(date(2026, 11, 14), time(0, 0)))
    by_symbol = dict(
        m.con.execute(
            "SELECT DISTINCT h.symbol, s.entity_id FROM security_identifier_history h "
            "JOIN securities s USING (security_id)"
        ).fetchall()
    )
    bel, cms, srp = after[by_symbol["BEL"]], after[by_symbol["CMSINFO"]], after[by_symbol["SHRIRAMPPS"]]
    assert (bel["order_wins_90d"], bel["order_value_90d"]) == (1, Decimal("6190000000.00"))
    assert cms["kmp_resignations_90d"] == 1 and cms["auditor_resignations_90d"] == 0
    assert srp["auditor_resignations_90d"] == 2 and srp["kmp_resignations_90d"] == 0
    assert all(v["penalties_90d"] is None for v in after.values())  # no verified penalty source [E7]
    later = _event_counts(m.con, date(2027, 3, 1), ist_to_utc(date(2027, 3, 1), time(0, 0)))
    assert later == {}  # 90-day window has passed
    assert set(EVENT_COLUMNS) <= set(bel)


def test_fraud_disclosure_counts_for_an_in_universe_symbol(events_market, rss):
    """The same filing with the symbol of an in-universe company (in memory): one fraud/default event counted."""
    m = events_market
    data = FRAUD.read_bytes().replace(b">SHANTHALA<", b">CMSINFO<")
    pub = rss[FRAUD.name].pub_ts_ist
    stage = stage_reg30_event(m.vault, m.stage_root, data=data, source_url="memory://fraud-cmsinfo",
                              fetched_at=FETCHED_AT, broadcast_ts=ist_to_utc(pub.date(), pub.time()),
                              broadcast_ts_source="RSS_PUBDATE")  # fmt: skip
    assert promote(m.con, stage).status == "PROMOTED"
    ent = m.con.execute(
        "SELECT DISTINCT s.entity_id FROM security_identifier_history h JOIN securities s USING (security_id) "
        "WHERE h.symbol = 'CMSINFO'"
    ).fetchone()[0]
    counts = _event_counts(m.con, date(2026, 11, 13), ist_to_utc(date(2026, 11, 14), time(0, 0)))[ent]
    assert counts["fraud_or_default_90d"] == 1 and counts["kmp_resignations_90d"] == 1
