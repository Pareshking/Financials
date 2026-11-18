"""X301 GUARDED_BRIDGE_ONE_BASIS: X106 bridges a guarded tag (revenue, total income, PAT, PBT incl. JV, owners' PAT)
through the YTD only when the bridge periods are on one basis. When the prior year's FY and YTD disagree (one holding
the YTD identity with the quarters, the other breaking it, `FactBook.prior_year_mixed_basis`), FY - YTD is no set of
quarters: the TTM is the sum of the latest 4 quarters as filed (industry practice), NULL only when a quarter is missing
or is derived from a proven mis-filed YTD (X226). X226 on a bridge YTD still comes first. The row carries
`restatement_suspected`. Owners' profit TTM (`pat_owners|pat`, `pat_owners_continuing`: EPS, P/E, ROE) takes the same
path, following PAT's basis.

Swiggy standalone (fixtures `operating_bridge/`, shared with X300): FY26 revenue 8,258 Cr on the continuing basis after
the Instamart transfer, quarters 2,693 + 3,000 + 3,166 + 2,194 = 11,053 Cr; H1 FY26 5,693 Cr = Q1 + Q2 as first filed.
Before X301 Q2 FY27 TTM revenue was 5,108 + 8,258 - 5,693 = 7,673 Cr; now 3,166 + 2,194 + 2,462 + 2,646 = 10,468 Cr.

Patanjali Foods standalone (fixtures `operating_bridge/`): H1 FY26 revenue 18,564.86 Cr vs Q1 + Q2 18,698.55 Cr breaks
the identity, FY26 40,169.58 Cr holds it (quarters 40,337.81 Cr, within 0.5 %): TTM = the 4 quarters, 44,299.35 Cr
(bridge 44,264.75).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from test_x300_operating_lines_bridge import _swiggy

import financials.fundamentals as F
from financials.fundamentals import FactBook, building_blocks
from financials.parsers.integrated import parse_integrated_results

DIR = Path(__file__).parent / "fixtures" / "operating_bridge"
CR = Decimal(10) ** 7
END = date(2026, 9, 30)
FY26 = (date(2025, 4, 1), date(2026, 3, 31))
H1_FY26, H1_FY27 = (date(2025, 4, 1), date(2025, 9, 30)), (date(2026, 4, 1), date(2026, 9, 30))
NINE_M_FY26 = (date(2025, 4, 1), date(2025, 12, 31))
PATANJALI = (
    "INTEGRATED_FILING_INDAS_1513074_14082025053356_WEB.xml",  # Q1 FY26
    "INTEGRATED_FILING_INDAS_1562673_31102025052557_WEB.xml",  # Q2 + H1 FY26
    "INTEGRATED_FILING_INDAS_1623623_11022026072616_WEB.xml",  # Q3 + 9M FY26
    "INTEGRATED_FILING_INDAS_1678022_30052026094755_WEB.xml",  # Q4 + FY26
    "INTEGRATED_FILING_INDAS_1715092_14082026083859_WEB.xml",  # Q1 FY27
    "INTEGRATED_FILING_INDAS_1758226_14112026020725_WEB.xml",  # H1 FY27
)


def _cr(v: Decimal | None) -> Decimal | None:
    return None if v is None else (v / CR).quantize(Decimal("0.01"))


def _patanjali() -> FactBook:
    b = FactBook("patanjali", "STANDALONE", fy_starts=frozenset({date(2025, 4, 1), date(2026, 4, 1)}))
    b.rounding_unit = Decimal(10) ** 5  # LevelOfRounding: lakhs
    for name in PATANJALI:
        r = parse_integrated_results((DIR / name).read_bytes(), name)
        assert r.ok and r.meta["scope"] == "STANDALONE" and r.meta["stated_symbol"] == "PATANJALI"
        for f in r.facts:
            if f.period_start:
                b.durations.setdefault(f.canonical_tag, {})[(f.period_start, f.period_end)] = f.value
    return b


def _pre_x301(monkeypatch):
    monkeypatch.setattr(FactBook, "mixed_basis_quarter_sum", lambda self, tag, end: self.ttm_from_ytd(tag, end))


def test_swiggy_fixture_facts():
    b = _swiggy()
    rev = b.durations["revenue_from_operations"]
    assert [_cr(rev[p]) for p in (H1_FY26, FY26, H1_FY27)] == [Decimal("5693.00"), Decimal("8258.00"),
                                                              Decimal("5108.00")]  # fmt: skip
    quarters = [b.quarter("revenue_from_operations", e) for e in (date(2025, 12, 31), date(2026, 3, 31))]
    assert [_cr(q) for q in quarters] == [Decimal("3166.00"), Decimal("2194.00")]
    assert {tuple(x["ytd_period"]) for x in b.ytd_breaks("revenue_from_operations")} == {("2025-04-01", "2026-03-31")}
    used = b._bridge_periods("revenue_from_operations", END)
    assert used == [H1_FY27, FY26, H1_FY26] and b.prior_year_mixed_basis("revenue_from_operations", used)
    assert b.misfiled_ytd_evidence("revenue_from_operations", FY26) is None


@pytest.mark.parametrize(("tag", "quarters", "bridge"), [("revenue_from_operations", "10468.00", "7673.00"),
                                                          ("total_income", "11589.00", "8764.00")])  # fmt: skip
def test_swiggy_mixed_prior_year_sums_the_quarters(tag, quarters, bridge, monkeypatch):
    b = _swiggy()
    assert _cr(b.ttm(tag, END)) == Decimal(quarters)
    assert _cr(b.ttm_from_ytd(tag, END)) == Decimal(bridge)  # the mixed-basis bridge X106 used to return
    assert b.restatement_suspected(END)
    _pre_x301(monkeypatch)
    assert _cr(b.ttm(tag, END)) == Decimal(bridge)


def test_swiggy_unbroken_guarded_tag_unchanged():
    """PAT holds the YTD identity in every YTD: summed from the quarters as before (X106 does not apply)."""
    b = _swiggy()
    assert not b.ytd_breaks("pat")
    assert _cr(b.ttm("pat", END)) == Decimal("-910.00")


def test_swiggy_blocks(monkeypatch):
    blocks = building_blocks(_swiggy(), END)
    assert _cr(blocks["rev_ops"]) == Decimal("10468.00")  # sales_ttm
    assert _cr(blocks["pat"]) == Decimal("-910.00")
    _pre_x301(monkeypatch)
    assert _cr(building_blocks(_swiggy(), END)["rev_ops"]) == Decimal("7673.00")


def test_missing_quarter_is_null():
    b = _swiggy()
    del b.durations["revenue_from_operations"][(date(2026, 4, 1), date(2026, 6, 30))]  # Q1 FY27 (H1 FY27 stays)
    assert b.quarter("revenue_from_operations", date(2026, 6, 30)) is None
    assert b.prior_year_mixed_basis("revenue_from_operations", b._bridge_periods("revenue_from_operations", END))
    assert b.ttm("revenue_from_operations", END) is None


def test_quarter_derived_from_a_misfiled_ytd_is_null():
    """A window quarter derived as YTD_k - YTD_k-1 from a proven mis-filed YTD (X226) is no filed quarter: NULL.
    Swiggy Q3 FY26 revenue = 9M - H1 FY26 when Q3 is not filed directly; an H1 FY26 500 Cr off its quarters that a
    later filing contradicts (LATER_FILING_AGREES) makes that Q3 a mis-filing."""
    b = _swiggy()
    rev = b.durations["revenue_from_operations"]
    del rev[(date(2025, 10, 1), date(2025, 12, 31))]
    assert _cr(b.mixed_basis_quarter_sum("revenue_from_operations", END)) == Decimal("10468.00")  # Q3 = 8,859 - 5,693
    b.later_filed["revenue_from_operations"] = {H1_FY26: [rev[H1_FY26]]}
    rev[H1_FY26] += 500 * CR
    assert b.misfiled_ytd_evidence("revenue_from_operations", H1_FY26) == "LATER_FILING_AGREES"
    assert b.mixed_basis_quarter_sum("revenue_from_operations", END) is None


def test_owners_ttm_tags_follow_pat():
    """`pat_owners|pat` is not a guarded tag but its TTM takes the X106 path when PAT breaks in the window."""
    b = _swiggy()
    assert "pat_owners|pat" in F.OWNERS_TTM_TAGS and "pat_owners_continuing" in F.OWNERS_TTM_TAGS
    owners = b.coalesced("pat_owners", "pat")
    assert b._ytd_consistent(owners, END)  # Swiggy's PAT holds the identity: summed as PAT
    assert b.ttm(owners, END) == b.ttm("pat", END)
    pat = b.durations["pat"]
    pat[FY26] += 1000 * CR  # FY26 PAT now breaks (H1 FY26 holds): mixed prior year
    assert not b._ytd_consistent(owners, END)
    assert b.ttm("pat", END) == sum(b.quarter("pat", F._add_months(END, -3 * i)) for i in range(4))


def test_patanjali_fixture_facts():
    b = _patanjali()
    rev = b.durations["revenue_from_operations"]
    assert [_cr(rev[p]) for p in (H1_FY26, NINE_M_FY26, FY26, H1_FY27)] == [
        Decimal("18564.86"), Decimal("29013.98"), Decimal("40169.58"), Decimal("22660.03")]  # fmt: skip
    assert {tuple(x["ytd_period"]) for x in b.ytd_breaks("revenue_from_operations")} == {
        ("2025-04-01", "2025-09-30"), ("2025-04-01", "2025-12-31")}  # fmt: skip
    assert b.misfiled_ytd_evidence("revenue_from_operations", NINE_M_FY26) == "NEXT_YTD_AGREES"
    assert b.misfiled_ytd_evidence("revenue_from_operations", H1_FY26) is None
    used = b._bridge_periods("revenue_from_operations", END)
    assert used == [H1_FY27, FY26, H1_FY26] and b.prior_year_mixed_basis("revenue_from_operations", used)


@pytest.mark.parametrize(("tag", "quarters", "bridge"), [("revenue_from_operations", "44299.35", "44264.75"),
                                                          ("total_income", "44501.68", "44467.08")])  # fmt: skip
def test_patanjali_quarters(tag, quarters, bridge, monkeypatch):
    b = _patanjali()
    qs = [b.quarter(tag, F._add_months(END, -3 * i)) for i in range(4)]
    assert b.ttm(tag, END) == sum(qs, Decimal(0))
    assert _cr(b.ttm(tag, END)) == Decimal(quarters)
    _pre_x301(monkeypatch)
    assert _cr(b.ttm(tag, END)) == Decimal(bridge)


def test_prior_year_on_one_basis_still_bridges():
    """X106 unchanged when the prior FY and YTD agree on the basis: with FY26 broken as well (both the prior FY and
    H1 FY26 break the identity), FY - H1 is taken as one basis and the bridge stays."""
    b = _patanjali()
    b.durations["revenue_from_operations"][FY26] -= 1000 * CR
    used = b._bridge_periods("revenue_from_operations", END)
    assert not b.prior_year_mixed_basis("revenue_from_operations", used)
    assert b.ttm("revenue_from_operations", END) == b.ttm_from_ytd("revenue_from_operations", END)


def test_operating_lines_unchanged_by_x301():
    """X300 already keeps the quarter sums of the operating lines on a mixed prior year; X301 only touches the
    guarded tags (Swiggy PBT before exceptional items: 30 Cr from the quarters, as in X300's test)."""
    b = _swiggy()
    assert _cr(b.ttm("profit_before_exceptional_and_tax", END)) == Decimal("30.00")
