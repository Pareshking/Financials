"""Reg. 31 shareholding: real ELIN filing, NSE master JSON visibility, share-count cross-check."""

import re
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from conftest import FETCHED_AT

from _fixture_helpers import CORP, FIXTURES, XBRL_DIR
from financials.parsers.shareholding import parse_shareholding, parse_shp_master
from financials.promoter import promote
from financials.staging import stage_results_xbrl, stage_shareholding

SHP = XBRL_DIR / "SHP_1739151_15102026054406_WEB.xml"
MASTER = FIXTURES / "shareholding" / "nse_corporate-share-holdings-master_ELIN_20261113.json"
SHP_URL = "https://nsearchives.nseindia.com/corporate/xbrl/SHP_1739151_15102026054406_WEB.xml"


def test_parse_real_filing():
    p = parse_shareholding(SHP.read_bytes())
    assert p.ok, p.issues
    assert p.meta["as_of_date"] == date(2026, 9, 30)
    assert p.meta["stated_isin"] == "INE050401020"
    assert p.meta["has_partly_paid"] is False
    assert p.meta["promoter_pledge_flag"] is False and p.meta["promoter_pledged_shares"] == 0
    c = p.categories
    assert c["TOTAL"]["shares"] == 49709220
    assert c["PROMOTER"]["shares"] + c["PUBLIC"]["shares"] == c["TOTAL"]["shares"]
    assert c["PROMOTER"]["pct"] == Decimal("0.3297")
    assert c["FII"]["shares"] == 298540 and c["DII"]["shares"] == 658724 and c["MUTUAL_FUNDS"]["shares"] == 658724
    assert c["TOTAL"]["holders"] == 51975


def test_master_json_gives_broadcast_time_and_xbrl_url():
    entries = parse_shp_master(MASTER.read_bytes())
    latest = entries[0]
    assert latest.as_of_date == date(2026, 9, 30)
    assert latest.xbrl_url == SHP_URL
    assert latest.broadcast_ts_ist.astimezone(UTC).replace(tzinfo=None) == datetime(2026, 10, 15, 12, 14, 11)
    assert not latest.revised


def test_broken_identity_is_an_issue():
    data = SHP.read_bytes()
    pattern = rb'(<in-bse-shp:NumberOfShares contextRef="PublicShareholding_ContextI"[^>]*>)(\d+)'
    tampered, n = re.subn(pattern, rb"\g<1>33320000", data, count=1)
    assert n == 1
    p = parse_shareholding(tampered)
    assert {(i.stage, i.reason_code) for i in p.issues} == {("IDENTITY", "PROMOTER_PLUS_PUBLIC")}


def test_wrong_taxonomy_is_rejected():
    p = parse_shareholding(CORP.read_bytes())
    assert [i.reason_code for i in p.issues] == ["UNKNOWN_TAXONOMY"]


def _broadcast():
    e = parse_shp_master(MASTER.read_bytes())[0]
    return e.broadcast_ts_ist.astimezone(UTC).replace(tzinfo=None)


def stage_shp(market, data=None, url=SHP_URL, **kw):
    return stage_shareholding(
        market.vault, market.stage_root, data=data or SHP.read_bytes(), source_url=url, fetched_at=FETCHED_AT, **kw
    )


def stage_results(market):
    return stage_results_xbrl(
        market.vault,
        market.stage_root,
        data=CORP.read_bytes(),
        source_url="https://nsearchives.nseindia.com/corporate/xbrl/" + CORP.name,
        fetched_at=FETCHED_AT,
        broadcast_ts=datetime(2026, 11, 5, 10, 0),
        broadcast_ts_source="RSS_PUBDATE",
    )


@pytest.fixture
def known_elin(market):
    promote(market.con, market.stage_day("20251014"))
    return market


def test_promote_shareholding_and_cross_check_passes(known_elin):
    m = known_elin
    r = promote(m.con, stage_shp(m, broadcast_ts=_broadcast(), broadcast_ts_source="API_FIELD"))
    assert r.status == "PROMOTED" and r.quarantined == []
    r2 = promote(m.con, stage_results(m))
    # 49,709,220 (Reg. 31) vs 49,710,000 (paid-up / FV, rounded to 0.01 M): 0.0016% < 0.5%
    assert r2.status == "PROMOTED" and r2.quarantined == []
    rows = dict(
        m.con.execute(
            "SELECT category, shares FROM shareholding_observations WHERE as_of_date = '2026-09-30'"
        ).fetchall()
    )
    assert rows["TOTAL"] == 49709220 and rows["PROMOTER"] == 16388405


def test_cross_check_flags_disagreement(known_elin):
    m = known_elin
    promote(m.con, stage_results(m))
    data = SHP.read_bytes()
    for ctx, value in (("ShareholdingPattern_ContextI", b"52000000"), ("PublicShareholding_ContextI", b"35611595")):
        data = re.sub(
            rb'(<in-bse-shp:NumberOfShares contextRef="' + ctx.encode() + rb'"[^>]*>)(\d+)', rb"\g<1>" + value, data
        )
    r = promote(
        m.con, stage_shp(m, data=data, url=SHP_URL + "?t", broadcast_ts=_broadcast(), broadcast_ts_source="API_FIELD")
    )
    assert r.status == "PROMOTED"
    reasons = m.con.execute("SELECT stage, reason_code FROM quarantine_queue WHERE stage = 'SHARES'").fetchall()
    assert reasons == [("SHARES", "CROSS_CHECK_FAILED")]


def test_shareholding_without_broadcast_is_quarantined(known_elin):
    r = promote(known_elin.con, stage_shp(known_elin))
    assert r.status == "QUARANTINED"
    assert known_elin.con.execute("SELECT reason_code FROM quarantine_queue").fetchall() == [("NO_VISIBILITY",)]
