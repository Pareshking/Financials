"""X300 OPERATING_LINES_BRIDGE: in a restated TTM window the EBITDA / OPM / ROCE / interest-coverage inputs bridge
through the YTD like revenue and PAT (X106), never summed from quarters the YTD contradicts.

Polyplex Corporation consolidated (fixtures `operating_bridge/`, NSE Integrated Filing XBRL, FY26 and H1 FY27):
other income per quarter Q1 29.79, Q2 22.77, Q3 27.26, Q4 61.86 Cr (FY26 quarters 141.68 Cr) against YTDs H1 50.08,
9M 70.64, FY 87.57 Cr; Q1 FY27 25.47 + Q2 43.59 = 69.06 Cr against H1 FY27 67.82 Cr. Revenue, PBT and PAT hold the
identity; FY26 total income (a guarded tag) breaks it with other income, so the Q2 FY27 row is restated (X106) and
revenue / total income bridge. Before X300 the TTM other income summed the four quarters (158.18 Cr) beside the
bridged revenue; now it is H1 FY27 + FY26 - H1 FY26 = 67.82 + 87.57 - 50.08 = 105.31 Cr, and OPM follows.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import financials.fundamentals as F
from financials.fundamentals import FactBook, building_blocks, safe_div
from financials.parsers.integrated import parse_integrated_results

DIR = Path(__file__).parent / "fixtures" / "operating_bridge"
FILES = (
    "INTEGRATED_FILING_INDAS_1510629_12082025102624_WEB.xml",  # Q1 FY26
    "INTEGRATED_FILING_INDAS_1574410_13112025092200_WEB.xml",  # Q2 + H1 FY26
    "INTEGRATED_FILING_INDAS_1625677_13022026082321_WEB.xml",  # Q3 + 9M FY26
    "INTEGRATED_FILING_INDAS_1672109_23052026084256_WEB.xml",  # Q4 + FY26
    "INTEGRATED_FILING_INDAS_1712085_11082026071859_WEB.xml",  # Q1 FY27
    "INTEGRATED_FILING_INDAS_1757942_13112026085007_WEB.xml",  # Q2 + H1 FY27
)
CR = Decimal(10) ** 7
END = date(2026, 9, 30)
FY26 = (date(2025, 4, 1), date(2026, 3, 31))
H1_FY26, H1_FY27 = (date(2025, 4, 1), date(2025, 9, 30)), (date(2026, 4, 1), date(2026, 9, 30))


def _book() -> FactBook:
    b = FactBook("polyplex", "CONSOLIDATED", fy_starts=frozenset({date(2025, 4, 1), date(2026, 4, 1)}))
    b.rounding_unit = Decimal(10) ** 6  # LevelOfRounding: millions
    for name in FILES:
        r = parse_integrated_results((DIR / name).read_bytes(), name)
        assert r.ok
        for f in r.facts:
            if f.period_start:
                b.durations.setdefault(f.canonical_tag, {})[(f.period_start, f.period_end)] = f.value
    return b


def _cr(v: Decimal) -> Decimal:
    return (v / CR).quantize(Decimal("0.01"))


def test_fixture_facts():
    b = _book()
    oi = b.durations["other_income"]
    assert [_cr(oi[p]) for p in (H1_FY26, FY26, H1_FY27)] == [Decimal("50.08"), Decimal("87.57"), Decimal("67.82")]
    quarters = [b.quarter("other_income", e) for e in (date(2025, 12, 31), date(2026, 3, 31), date(2026, 6, 30), END)]
    assert [_cr(q) for q in quarters] == [Decimal("27.26"), Decimal("61.86"), Decimal("25.47"), Decimal("43.59")]
    # other income and total income break the YTD identity; revenue, PBT and PAT hold it
    assert {x["ytd_period"][1] for x in b.ytd_breaks("other_income")} == {
        "2025-09-30", "2025-12-31", "2026-03-31", "2026-09-30"}  # fmt: skip
    assert "2026-03-31" in {x["ytd_period"][1] for x in b.ytd_breaks("total_income")}
    for tag in ("revenue_from_operations", "pat", "pbt"):
        assert not b.ytd_breaks(tag)
    assert b.restatement_triggers(END) == ["YTD_IDENTITY"]


def test_other_income_ttm_bridges_in_the_restated_row():
    b = _book()
    assert b.bridged_operating_line("other_income", END)
    assert _cr(b.ttm("other_income", END)) == Decimal("105.31")  # was 158.18 (the four quarters)
    assert b.ttm("other_income", END) == b.ttm_from_ytd("other_income", END)
    # the lines whose own identity holds are unchanged (their bridge equals the quarters)
    for tag, cr in (("depreciation_amortisation", "379.91"), ("finance_costs", "57.44"),
                    ("profit_before_exceptional_and_tax", "499.03"), ("pbt", "499.03")):  # fmt: skip
        assert not b.bridged_operating_line(tag, END)
        assert _cr(b.ttm(tag, END)) == Decimal(cr)


def test_opm_before_and_after(monkeypatch):
    blocks = building_blocks(_book(), END)
    assert _cr(blocks["other_income"]) == Decimal("105.31") and _cr(blocks["rev_ops"]) == Decimal("8130.86")
    assert _cr(blocks["ebitda"]) == Decimal("831.07")
    assert safe_div(blocks["ebitda"], blocks["rev_ops"]).quantize(Decimal("0.0001")) == Decimal("0.1022")
    monkeypatch.setattr(F, "YTD_BRIDGED_TAGS", frozenset())  # the pre-X300 behaviour
    old = building_blocks(_book(), END)
    assert _cr(old["other_income"]) == Decimal("158.18") and _cr(old["ebitda"]) == Decimal("778.20")
    assert safe_div(old["ebitda"], old["rev_ops"]).quantize(Decimal("0.0001")) == Decimal("0.0957")


def test_no_restatement_keeps_the_quarter_sum():
    """Without a guarded break in the window the operating line is not bridged, even if its own identity breaks:
    drop total income (the only guarded tag that breaks) and other income sums the quarters again."""
    b = _book()
    b.durations.pop("total_income")
    assert b.restatement_triggers(END) == []
    assert not b.bridged_operating_line("other_income", END)
    assert _cr(b.ttm("other_income", END)) == Decimal("158.18")


def test_misfiled_guarded_ytd_is_no_restatement():
    """X226 kept: when every guarded break in the window is provably the YTD's mis-filing (here: a later filing
    states FY26 total income equal to the quarters' sum, LATER_FILING_AGREES), the quarters are right and the
    operating line stays summed."""
    b = _book()
    ti = b.durations["total_income"]
    for x in b.ytd_breaks("total_income"):
        p = (date.fromisoformat(x["ytd_period"][0]), date.fromisoformat(x["ytd_period"][1]))
        b.later_filed.setdefault("total_income", {})[p] = [Decimal(x["quarters_sum"])]
        assert b.misfiled_ytd_evidence("total_income", p) == "LATER_FILING_AGREES"
    assert ti  # total income itself stays filed
    assert not b.bridged_operating_line("other_income", END)
    assert _cr(b.ttm("other_income", END)) == Decimal("158.18")


def test_misfiled_own_ytd_withholds_the_line():
    """X226 on the line itself: a bridged operating line whose own YTD is provably mis-filed is NULL."""
    b = _book()
    b.later_filed["other_income"] = {FY26: [b.durations["other_income"][FY26] + Decimal("541100000")]}
    assert b.misfiled_ytd_evidence("other_income", FY26) == "LATER_FILING_AGREES"
    assert b.bridged_operating_line("other_income", END)
    assert b.ttm("other_income", END) is None


def test_ytd_copy_withheld_first():
    """X173 kept: a YTD withheld as a copy of its quarter is gone before X300 looks, so it cannot be bridged on."""
    b = _book()
    b.withhold_ytd_copies()
    assert b.ytd_copies == []  # POLYPLEX files real YTDs
    assert _cr(b.ttm("other_income", END)) == Decimal("105.31")


SWIGGY = (
    "INTEGRATED_FILING_INDAS_1499085_31072025042102_WEB.xml",  # Q1 FY26
    "INTEGRATED_FILING_INDAS_1561841_30102025063455_WEB.xml",  # Q2 + H1 FY26
    "INTEGRATED_FILING_INDAS_1614516_30012026041413_WEB.xml",  # Q3 + 9M FY26
    "INTEGRATED_FILING_INDAS_1665216_09052026120920_WEB.xml",  # Q4 + FY26 (continuing basis)
    "INTEGRATED_FILING_INDAS_1705249_30072026050331_WEB.xml",  # Q1 FY27
    "INTEGRATED_FILING_INDAS_1744174_22102026064058_WEB.xml",  # Q2 + H1 FY27
)


def _swiggy() -> FactBook:
    b = FactBook("swiggy", "STANDALONE", fy_starts=frozenset({date(2025, 4, 1), date(2026, 4, 1)}))
    b.rounding_unit = CR  # LevelOfRounding: crores
    for name in SWIGGY:
        r = parse_integrated_results((DIR / name).read_bytes(), name)
        assert r.ok and r.meta["scope"] == "STANDALONE" and r.meta["stated_symbol"] == "SWIGGY"
        for f in r.facts:
            if f.period_start:
                b.durations.setdefault(f.canonical_tag, {})[(f.period_start, f.period_end)] = f.value
    return b


def test_prior_year_on_two_bases_keeps_the_quarters():
    """Swiggy standalone: FY26 PBT before exceptional items is 436 Cr on the continuing basis (quarters -991 - 881 -
    886 + 279 = -2,479 Cr) while H1 FY26 stays -1,872 Cr = Q1 + Q2 as first filed. FY - H1 is no set of quarters, so
    the line is not bridged (637 + 436 + 1,872 = 2,945 Cr would be meaningless): the quarter sum (30 Cr) stays, as
    before X300. (Revenue still bridges by X106 on its own break: that is X106's behaviour, not changed here.)"""
    b = _swiggy()
    pbeit = "profit_before_exceptional_and_tax"
    assert _cr(b.durations[pbeit][FY26]) == Decimal("436.00")
    assert _cr(b.durations[pbeit][H1_FY26]) == Decimal("-1872.00")
    assert b.restatement_triggers(END) == ["YTD_IDENTITY", "DISCONTINUED_OPERATIONS"]
    assert b.prior_year_mixed_basis(pbeit, b._bridge_periods(pbeit, END))
    assert _cr(b.ttm_from_ytd(pbeit, END)) == Decimal("2945.00")
    assert not b.bridged_operating_line(pbeit, END)
    assert _cr(b.ttm(pbeit, END)) == Decimal("30.00")
    assert building_blocks(b, END)["ebitda"] is not None
    # the lines move together: no operating line of this row is bridged (EBITDA never mixes a bridged line with
    # summed ones); D&A holds the identity in every YTD and keeps its quarters anyway
    assert not any(b.bridged_operating_line(t, END) for t in F.YTD_BRIDGED_TAGS)
    assert not b.bridged_operating_line("depreciation_amortisation", END)
    assert b.ttm("depreciation_amortisation", END) is not None
