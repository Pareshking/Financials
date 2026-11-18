"""QT X273 FIXED_ASSET_ONE_DEFINITION (owner decision T): the fixed-asset lines of one balance-sheet date come from one
filing and carry the definition the entity's other balance-sheet dates use.

- FSN E-Commerce (NYKAA) consolidated FY26: the Q4 results file PPE 299.97 Cr and right-of-use assets 461.47 Cr
  (labelled member, X47); the Reg. 34 annual report files PPE 761.44 Cr = the two together and no right-of-use line.
  Ranked tag by tag, March took the annual's PPE and the results' right-of-use line: net block 1,469.42 Cr, the
  right-of-use assets counted twice. Fixed assets agree in total, so the lines take the definition of the Q2 FY27
  balance sheet (PPE 306.53, right-of-use 496.47 Cr): the results' split.
- MPS Ltd (MPSLTD) consolidated FY26: the annual files other intangibles 494.10 Cr (its "Others" class 439.54 Cr is
  the acquired intangibles and goodwill) and no goodwill; the Q4 results file goodwill 376.32 and other intangibles
  138.86 Cr. The totals differ (494.10 vs 515.18 Cr), so the annual's own lines stand and the results' goodwill is not
  added to them (net block 894.88 -> 518.56 Cr; Q2 FY27: 539.23 Cr).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from conftest import FETCHED_AT

from _fixture_helpers import FIXTURES
from financials.features_bs import bs_lines
from financials.fundamentals import FactBook, clear_prefetch, load_factbook, prefetch_fundamentals
from financials.promoter import promote
from financials.staging import stage_results_xbrl

D = FIXTURES / "fixed_assets"
URL = "https://nsearchives.nseindia.com/corporate/xbrl/"
CR = Decimal(10) ** 7
M26, S26 = date(2026, 3, 31), date(2026, 9, 30)
NYKAA = (  # (file, broadcast UTC) from filings.broadcast_ts
    ("INTEGRATED_FILING_INDAS_1670964_21052026084421_WEB.xml", datetime(2026, 5, 21, 15, 14, 21)),
    ("AR_XBRL_NYKAA_23092026220941.xml", datetime(2026, 9, 23, 16, 39, 42)),
    ("INTEGRATED_FILING_INDAS_1752762_04112026053637_WEB.xml", datetime(2026, 11, 4, 12, 6, 37)),
)
MPSLTD = (
    ("INTEGRATED_FILING_INDAS_1668105_15052026092506_WEB.xml", datetime(2026, 5, 15, 15, 55, 7)),
    ("AR_XBRL_MPSLTD_01102026192529.xml", datetime(2026, 10, 1, 13, 55, 30)),
    ("INTEGRATED_FILING_INDAS_1752323_03112026100325_WEB.xml", datetime(2026, 11, 3, 16, 33, 26)),
)


def _load(market, files):
    assert promote(market.con, market.stage_day("20250919")).status == "PROMOTED"
    for name, ts in files:
        r = promote(market.con, stage_results_xbrl(market.vault, market.stage_root, data=(D / name).read_bytes(),
                                                   source_url=URL + name, fetched_at=FETCHED_AT, broadcast_ts=ts,
                                                   broadcast_ts_source="API_FIELD"))  # fmt: skip
        assert r.status in ("PROMOTED", "QUARANTINED"), (name, r)
    (ent,) = market.con.execute(
        "SELECT DISTINCT entity_id FROM filing_meta WHERE filing_id IN (SELECT filing_id FROM filings "
        "WHERE source_url = ?)", [URL + files[1][0]]).fetchone()  # fmt: skip
    return ent


def _cr(book: FactBook, tag: str, d: date) -> Decimal | None:
    v = book.instants.get(tag, {}).get(d)
    return None if v is None else v / CR


def _nb(book: FactBook, d: date) -> Decimal:
    return bs_lines(book, d)["net_block"] / CR


def test_x273_right_of_use_inside_annual_ppe_is_not_counted_twice(market):
    ent = _load(market, NYKAA)
    con = market.con
    raw = dict(con.execute(
        "SELECT m.accounting_profile, f.value_inr FROM fact_observations f JOIN filing_meta m USING (filing_id) "
        "WHERE f.entity_id = ? AND f.scope = 'CONSOLIDATED' AND f.canonical_tag = 'ppe_net' AND f.period_end = ?",
        [ent, M26]).fetchall())  # fmt: skip
    assert raw == {"INDAS_CORP": Decimal("2999700000.00"), "REG34_ANNUAL": Decimal("7614400000.00")}  # kept as filed

    # Before the annual report: the Q4 results alone.
    q4 = load_factbook(con, ent, "CONSOLIDATED", datetime(2026, 6, 1))
    assert (_cr(q4, "ppe_net", M26), _cr(q4, "right_of_use_assets", M26)) == (Decimal("299.97"), Decimal("461.47"))
    assert M26 not in q4.fixed_asset_rule
    assert _nb(q4, M26) == Decimal("1007.95")

    # Annual visible, no later balance sheet yet: its own lines (PPE includes right-of-use), counted once.
    ar = load_factbook(con, ent, "CONSOLIDATED", datetime(2026, 10, 1))
    assert ar.fixed_asset_rule[M26] == "ANNUAL_DEFINITION"
    assert (_cr(ar, "ppe_net", M26), _cr(ar, "right_of_use_assets", M26)) == (Decimal("761.44"), None)
    assert _nb(ar, M26) == Decimal("1007.95")  # was 1,469.42: 761.44 + 461.47 + 149.01 + 97.50

    # Q2 FY27 visible: it splits right-of-use out of PPE, so March takes the same split.
    h1 = load_factbook(con, ent, "CONSOLIDATED", datetime(2026, 11, 18))
    assert h1.fixed_asset_rule[M26] == "RESULTS_DEFINITION"
    assert (_cr(h1, "ppe_net", M26), _cr(h1, "right_of_use_assets", M26)) == (Decimal("299.97"), Decimal("461.47"))
    assert (_cr(h1, "ppe_net", S26), _cr(h1, "right_of_use_assets", S26)) == (Decimal("306.53"), Decimal("496.47"))
    assert (_nb(h1, M26), _nb(h1, S26)) == (Decimal("1007.95"), Decimal("1060.15"))
    assert _cr(h1, "cwip", M26) == Decimal("9.25")  # lines that agree are unchanged


def test_x273_annual_lines_are_not_mixed_with_results_lines_when_totals_differ(market):
    ent = _load(market, MPSLTD)
    book = load_factbook(market.con, ent, "CONSOLIDATED", datetime(2026, 11, 18))
    assert book.fixed_asset_rule[M26] == "ANNUAL_ONE_SOURCE"
    assert _cr(book, "other_intangibles", M26) == Decimal("494.1015")
    assert _cr(book, "goodwill", M26) is None  # the results' 376.32 Cr is inside the annual's other intangibles
    assert _nb(book, M26) == Decimal("518.565")  # was 894.88
    assert (_cr(book, "goodwill", S26), _nb(book, S26)) == (Decimal("381.68"), Decimal("539.23"))


@pytest.mark.parametrize("files", [NYKAA, MPSLTD])
def test_x273_batch_prefetch_equals_per_entity_book(market, files):
    ent = _load(market, files)
    as_of = datetime(2026, 11, 18)
    single = load_factbook(market.con, ent, "CONSOLIDATED", as_of)
    prefetch_fundamentals(market.con, as_of)
    try:
        batch = load_factbook(market.con, ent, "CONSOLIDATED", as_of)
    finally:
        clear_prefetch(market.con, as_of)
    assert batch.instants == single.instants and batch.fixed_asset_rule == single.fixed_asset_rule


def test_x273_rule_unit():
    b = FactBook("e", "CONSOLIDATED", rounding_unit=Decimal(100000))
    m, s = M26, S26
    b.instants = {"ppe_net": {m: 761 * CR, s: 306 * CR}, "right_of_use_assets": {m: 461 * CR, s: 496 * CR}}
    vis_q4, vis_ar = datetime(2026, 5, 21), datetime(2026, 9, 23)
    rows = [  # (rank, filing, annual?, visible, tag, value)
        (1, "AR", True, vis_ar, "ppe_net", 761 * CR),
        (2, "Q4", False, vis_q4, "ppe_net", 300 * CR),
        (1, "Q4", False, vis_q4, "right_of_use_assets", 461 * CR),
    ]
    b.align_fixed_assets({m: rows})
    assert b.fixed_asset_rule[m] == "RESULTS_DEFINITION" and b.instants["ppe_net"][m] == 300 * CR
    # Without a neighbouring balance sheet the annual's own split stands, still counted once.
    a = FactBook("e", "CONSOLIDATED", rounding_unit=Decimal(100000))
    a.instants = {"ppe_net": {m: 761 * CR}, "right_of_use_assets": {m: 461 * CR}}
    a.align_fixed_assets({m: rows})
    assert a.fixed_asset_rule[m] == "ANNUAL_DEFINITION"
    assert a.instants["ppe_net"][m] == 761 * CR and m not in a.instants["right_of_use_assets"]
    # Every line agrees within rounding: nothing changes, no rule recorded.
    c = FactBook("e", "CONSOLIDATED", rounding_unit=Decimal(100000))
    c.instants = {"ppe_net": {m: Decimal("1000000")}}
    c.align_fixed_assets({m: [(1, "AR", True, vis_ar, "ppe_net", Decimal("1000000")),
                              (2, "Q4", False, vis_q4, "ppe_net", Decimal("1050000"))]})  # fmt: skip
    assert c.fixed_asset_rule == {} and c.instants["ppe_net"][m] == Decimal("1000000")
    # Results ranked first on every line (no annual report): untouched.
    e = FactBook("e", "CONSOLIDATED")
    e.instants = {"ppe_net": {m: Decimal(5)}}
    e.align_fixed_assets({m: [(1, "Q4", False, vis_q4, "ppe_net", Decimal(5))]})
    assert e.fixed_asset_rule == {}
