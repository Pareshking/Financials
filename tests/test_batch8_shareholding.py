"""Batch 8: Reg. 31 shareholding pattern (in-bse-shp 2025-10-31) across pledged, no-promoter and DR filers.

Evidence SHP8-SHP14 in docs/references.md. All fixtures are real, unmodified NSE files (MANIFEST.md);
tampering happens in memory only.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal

import pytest
from conftest import FETCHED_AT

from _fixture_helpers import XBRL_DIR
from financials.features import _preload, _quarter_before, shareholding_columns
from financials.parsers.shareholding import NO_PROMOTER_RULE, parse_shareholding
from financials.promoter import promote
from financials.staging import stage_shareholding

HDFC_SEP = XBRL_DIR / "SHP_1733480_06102026050037_WEB.xml"
HDFC_JUN = XBRL_DIR / "SHP_1687801_03072026023346_WEB.xml"
ICICI = XBRL_DIR / "SHP_1743956_22102026042725_WEB.xml"
VEDL = XBRL_DIR / "SHP_1740148_16102026052137_WEB.xml"
JSW = XBRL_DIR / "SHP_1743210_21102026055808_WEB.xml"
APOLLO = XBRL_DIR / "SHP_1733654_07102026112959_WEB.xml"
AFCONS = XBRL_DIR / "SHP_1742713_21102026021326_WEB.xml"
ELIN = XBRL_DIR / "SHP_1739151_15102026054406_WEB.xml"

ALL = [HDFC_SEP, HDFC_JUN, ICICI, VEDL, JSW, APOLLO, AFCONS, ELIN]


@pytest.fixture(scope="module")
def parsed():
    return {p.name: parse_shareholding(p.read_bytes()) for p in ALL}


def _cat(r, cat, measure="shares"):
    return r.categories[cat][measure]


@pytest.mark.parametrize("path", ALL, ids=lambda p: p.stem)
def test_every_fixture_parses_and_balances(parsed, path):
    """SHP8: promoter + public + non-promoter non-public = total, exactly, in every filing."""
    r = parsed[path.name]
    assert r.ok, r.issues
    npnp = r.categories.get("NON_PROMOTER_NON_PUBLIC", {}).get("shares", Decimal(0))
    assert _cat(r, "PROMOTER") + _cat(r, "PUBLIC") + npnp == _cat(r, "TOTAL")


def test_npnp_bucket_holds_dr_custodian_and_employee_trusts(parsed):
    """SHP8: HDFC Bank's NPNP = DR custodian 2,051,218,867 + employee trusts 117,978."""
    r = parsed[HDFC_SEP.name]
    assert _cat(r, "DR_CUSTODIAN") == Decimal("2051218867")
    assert _cat(r, "EMPLOYEE_TRUSTS") == Decimal("117978")
    assert _cat(r, "NON_PROMOTER_NON_PUBLIC") == Decimal("2051336845")
    assert _cat(r, "PUBLIC") + _cat(r, "NON_PROMOTER_NON_PUBLIC") == _cat(r, "TOTAL") == Decimal("15418597348")
    v = parsed[VEDL.name]
    assert _cat(v, "NON_PROMOTER_NON_PUBLIC") == _cat(v, "EMPLOYEE_TRUSTS") == Decimal("6232329")


def test_percentage_denominator_excludes_dr_shares_but_includes_employee_trusts(parsed):
    """SHP9: DR-underlying shares carry no percentage and are outside the denominator; EBT shares are inside."""
    r = parsed[HDFC_SEP.name]
    assert "pct" not in r.categories["DR_CUSTODIAN"]
    assert _cat(r, "PUBLIC", "pct") == Decimal("1")
    voting = _cat(r, "TOTAL") - _cat(r, "DR_CUSTODIAN")
    assert round(_cat(r, "FII") / voting, 4) == _cat(r, "FII", "pct") == Decimal("0.394")
    assert round(_cat(r, "FII") / _cat(r, "TOTAL"), 4) != _cat(r, "FII", "pct")
    v = parsed[VEDL.name]  # no DR shares: denominator = total, EBT included
    assert round(_cat(v, "PROMOTER") / _cat(v, "TOTAL"), 4) == _cat(v, "PROMOTER", "pct") == Decimal("0.5472")
    assert _cat(v, "EMPLOYEE_TRUSTS", "pct") == Decimal("0.0016")


def test_vedanta_encumbrance_is_not_pledge(parsed):
    """SHP10: Vedanta files no pledge, but NDU + other encumbrances cover ~100% of promoter shares."""
    r = parsed[VEDL.name]
    assert r.meta["promoter_pledge_flag"] is False
    assert r.meta["promoter_pledged_shares"] == 0
    assert r.meta["promoter_encumbered_shares"] == Decimal("107342705") + Decimal("2032309058") == Decimal("2139651763")
    cols = shareholding_columns(_as_features(r))
    assert cols["promoter_pledge_pct"] == 0.0
    assert cols["promoter_encumbered_pct"] == pytest.approx(2139651763 / 2139758459)


@pytest.mark.parametrize(
    ("path", "pledged", "promoter", "stated_ratio"),
    [
        (JSW, "132730505", "1083214750", "0.1225"),
        (APOLLO, "1171054", "40287130", "0.0291"),
        (AFCONS, "184500996", "184506596", "1"),
    ],
    ids=["JSWSTEEL", "APOLLOHOSP", "AFCONS"],
)
def test_pledge_pct_is_of_promoter_shares_and_matches_filed_ratio(parsed, path, pledged, promoter, stated_ratio):
    """SHP10: on the promoter member the filed pledge percentage is relative to promoter shares; ours agrees
    to the filing's 4 dp."""
    r = parsed[path.name]
    assert r.meta["promoter_pledged_shares"] == Decimal(pledged)
    assert _cat(r, "PROMOTER") == Decimal(promoter)
    pct = shareholding_columns(_as_features(r))["promoter_pledge_pct"]
    assert round(Decimal(str(pct)), 4) == Decimal(stated_ratio)


@pytest.mark.parametrize("path", [HDFC_SEP, HDFC_JUN, ICICI], ids=lambda p: p.stem)
def test_no_promoter_rule(parsed, path):
    """SHP11: no promoter category filed; public + NPNP = total; no encumbrance declared -> promoter 0."""
    r = parsed[path.name]
    assert NO_PROMOTER_RULE in r.meta["rules_applied"]
    assert _cat(r, "PROMOTER") == 0 and _cat(r, "PROMOTER", "pct") == 0


def test_no_promoter_rule_needs_the_identity():
    """Tampered public count: the rule must not paper over a gap, so the filing is MISSING_CRITICAL."""
    data = HDFC_SEP.read_bytes()
    pattern = rb'(<in-bse-shp:NumberOfShares contextRef="PublicShareholding_ContextI"[^>]*>)(\d+)'
    tampered, n = re.subn(pattern, rb"\g<1>13367260000", data, count=1)
    assert n == 1
    r = parse_shareholding(tampered)
    assert NO_PROMOTER_RULE not in r.meta["rules_applied"]
    assert ("PARSE", "MISSING_CRITICAL") in {(i.stage, i.reason_code) for i in r.issues}


def test_no_promoter_rule_needs_no_declared_encumbrance():
    data = HDFC_SEP.read_bytes()
    tag = rb"WhetherAnySharesHeldByPromotersAreEncumberedUnderPledged"
    tampered, n = re.subn(rb"(<in-bse-shp:" + tag + rb" [^>]*>)false", rb"\g<1>true", data, count=1)
    assert n == 1
    r = parse_shareholding(tampered)
    assert NO_PROMOTER_RULE not in r.meta["rules_applied"] and not r.ok


def test_fii_category_holds_fdi_and_overseas_depositories(parsed):
    """SHP13: Institutions (Foreign) = FPI I + FPI II + FDI + overseas depositories + others."""
    j = parsed[JSW.name]
    assert _cat(j, "FDI", "pct") == Decimal("0.15") and _cat(j, "FII", "pct") == Decimal("0.2623")
    i = parsed[ICICI.name]
    assert _cat(i, "OVERSEAS_DEPOSITORIES", "pct") == Decimal("0.1576")
    cols = shareholding_columns(_as_features(i))
    assert cols["fii_holding_pct"] == 0.5044
    assert cols["fpi_holding_pct"] == pytest.approx(0.3331 + 0.0137)
    # HDFC Bank's ADR shares sit in NPNP instead: same instrument, different bucket (named divergence).
    h = parsed[HDFC_SEP.name]
    assert "OVERSEAS_DEPOSITORIES" not in h.categories and _cat(h, "DR_CUSTODIAN") > 0


def test_major_public_holders(parsed):
    """SHP12: named public holders from the per-category detail tables; all above 1%; no promoter rows."""
    j = {(h["holder_category"], h["holder_name"]): h for h in parsed[JSW.name].major_holders}
    jfe = j[("FDI", "JFE STEEL INTERNATIONAL EUROPE B.V.")]
    assert jfe["shares"] == Decimal("366818095") and jfe["pct"] == Decimal("0.15")
    assert j[("INSURANCE", "LIFE INSURANCE CORPORATION OF INDIA")]["pct"] == Decimal("0.0465")
    for r in parsed.values():
        for h in r.major_holders:
            assert h["pct"] is not None and h["pct"] > Decimal("0.01"), h
    hdfc = parsed[HDFC_SEP.name].major_holders
    assert len(hdfc) == 14 and {h["holder_category"] for h in hdfc} == {
        "FPI_CAT1",
        "INSURANCE",
        "MUTUAL_FUNDS",
        "PENSION_FUNDS",
    }
    icici = {(h["holder_category"], h["holder_name"]): h for h in parsed[ICICI.name].major_holders}
    adr = icici[("OVERSEAS_DEPOSITORIES", "DEUTSCHE BANK TRUST COMPANY AMERICAS")]
    assert adr["shares"] == Decimal("1131013715") and adr["pct"] == Decimal("0.1576")
    # Promoter detail rows (e.g. Mukesh D Ambani-style individual promoters) are on other axes: none here.
    jsw_names = {h["holder_name"] for h in parsed[JSW.name].major_holders}
    assert not any("JINDAL" in n.upper() for n in jsw_names)


def test_quarter_before():
    assert _quarter_before(date(2026, 9, 30)) == date(2026, 6, 30)
    assert _quarter_before(date(2026, 3, 31)) == date(2025, 12, 31)


def _as_features(r):
    """The `shp` dict shape `_preload` builds, from one parsed filing."""
    d = {cat: (v.get("pct"), v.get("shares")) for cat, v in r.categories.items()}
    d.update(
        _as_of=r.meta["as_of_date"],
        _pledged=r.meta["promoter_pledged_shares"],
        _encumbered=r.meta["promoter_encumbered_shares"],
    )
    return d


# ── end to end: promote both HDFC Bank filings, read point-in-time ─────────────────────────────────

JUN_BROADCAST = datetime(2026, 7, 3, 9, 3, 54)  # 14:33:54 IST [master JSON]
SEP_BROADCAST = datetime(2026, 10, 6, 11, 30, 45)  # 17:00:45 IST


@pytest.fixture
def hdfc(market):
    promote(market.con, market.stage_day("20251014"))
    for path, ts in ((HDFC_JUN, JUN_BROADCAST), (HDFC_SEP, SEP_BROADCAST)):
        r = promote(
            market.con,
            stage_shareholding(
                market.vault,
                market.stage_root,
                data=path.read_bytes(),
                source_url="https://nsearchives.nseindia.com/corporate/xbrl/" + path.name,
                fetched_at=FETCHED_AT,
                broadcast_ts=ts,
                broadcast_ts_source="API_FIELD",
            ),
        )
        assert r.status == "PROMOTED", r
    return market


def _hdfc_shp(con, as_of_ts):
    shp, _, _ = _preload(con, as_of_ts)
    (ent,) = [e for e, v in shp.items() if v.get("_as_of")]
    return shp[ent]


def test_promoted_meta_and_major_holders(hdfc):
    con = hdfc.con
    rules = con.execute("SELECT DISTINCT rules_applied FROM shareholding_meta").fetchall()
    assert rules == [(NO_PROMOTER_RULE,)]
    n = con.execute(
        "SELECT count(*) FROM shareholding_major_holders WHERE as_of_date = '2026-09-30' AND pct > 0.01"
    ).fetchone()[0]
    assert n == 14


def test_fii_dii_qoq_change_is_point_in_time(hdfc):
    # After the September broadcast: (0.394 + 0.4363) - (0.4183 + 0.4192) = -0.0072
    cols = shareholding_columns(_hdfc_shp(hdfc.con, datetime(2026, 11, 13)))
    assert cols["fii_dii_qoq_change_pct"] == pytest.approx(-0.0072)
    assert cols["promoter_holding_pct"] == 0.0 and cols["promoter_pledge_pct"] is None
    assert cols["public_holding_pct"] == 1.0
    assert cols["non_promoter_non_public_pct"] == pytest.approx(2051336845 / 15418597348)
    # Before it: only June is visible, so there is no previous quarter and no change.
    before = _hdfc_shp(hdfc.con, datetime(2026, 10, 1))
    assert before["_as_of"] == date(2026, 6, 30)
    assert shareholding_columns(before)["fii_dii_qoq_change_pct"] is None


def test_qoq_change_needs_adjacent_quarter():
    r = parse_shareholding(HDFC_SEP.read_bytes())
    shp = _as_features(r)
    shp["_prev"] = {"FII": (0.4, None), "DII": (0.4, None)}
    shp["_prev_as_of"] = date(2026, 3, 31)  # two quarters back
    assert shareholding_columns(shp)["fii_dii_qoq_change_pct"] is None
    shp["_prev_as_of"] = date(2026, 6, 30)
    assert shareholding_columns(shp)["fii_dii_qoq_change_pct"] == pytest.approx(0.8303 - 0.8)


def test_dsl_aliases_compile_to_the_new_columns():
    from financials.dsl import compile_screen

    sql = compile_screen(
        "Promoter holding > 50 AND Promoter pledge < 5 AND Promoter encumbered < 10 AND FII holding > 10 "
        "AND FPI holding > 5 AND DII holding > 10 AND Public holding < 50 AND Change in FII DII holding > 1"
    ).where_sql
    for col in (
        "promoter_holding_pct",
        "promoter_pledge_pct",
        "promoter_encumbered_pct",
        "fii_holding_pct",
        "fpi_holding_pct",
        "dii_holding_pct",
        "public_holding_pct",
        "fii_dii_qoq_change_pct",
    ):
        assert col in sql
