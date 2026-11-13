"""Batch 3 (mid/small-cap industrials and chemicals, Q2 FY27 consolidated) [X48-X51]."""

from datetime import date
from decimal import Decimal

import pytest

from _fixture_helpers import XBRL_DIR
from financials.fundamentals import FactBook, building_blocks
from financials.parsers.indas_corp import LABEL_RULES, parse_indas_corp_results
from financials.parsers.segments import parse_segments

Q = (date(2026, 7, 1), date(2026, 9, 30))
END = date(2026, 9, 30)
SRF = XBRL_DIR / "INTEGRATED_FILING_INDAS_1743533_21102026080703_WEB.xml"
CUMMINS = XBRL_DIR / "INTEGRATED_FILING_INDAS_1753292_04112026105837_WEB.xml"
APL = XBRL_DIR / "INTEGRATED_FILING_INDAS_1746046_26102026055540_WEB.xml"
AIA = XBRL_DIR / "INTEGRATED_FILING_INDAS_1751861_03112026045154_WEB.xml"


@pytest.mark.parametrize("path", [SRF, CUMMINS, APL, AIA], ids=lambda p: p.name[25:32])
def test_parse_clean(path):
    r = parse_indas_corp_results(path.read_bytes())
    assert r.ok, r.issues


def test_zero_attribution_placeholder_rule():
    """[X48] APL Apollo tags owners = NCI = 0 with PAT 382.42 Cr: both dropped, owners' profit falls back to PAT."""
    r = parse_indas_corp_results(APL.read_bytes())
    assert r.value("pat", *Q) == Decimal("3824200000")
    assert r.value("pat_owners", *Q) is None and r.value("pat_nci", *Q) is None
    assert r.meta["rules_applied"][0]["rule"] == "ZERO_ATTRIBUTION_PLACEHOLDER"
    book = FactBook("e", "CONSOLIDATED")
    for f in r.facts:
        if f.period_type == "DURATION":
            book.durations.setdefault(f.canonical_tag, {})[(f.period_start, f.period_end)] = f.value
    assert book.quarter(book.coalesced("pat_owners", "pat"), END) == Decimal("3824200000")


def test_zero_attribution_rule_does_not_fire_on_real_attribution():
    r = parse_indas_corp_results((XBRL_DIR / "INTEGRATED_FILING_INDAS_1756234_11112026070341_WEB.xml").read_bytes())
    assert "rules_applied" not in r.meta
    assert r.value("pat_owners", *Q) == Decimal("13661100000")


def test_segments_sum_to_filed_totals_srf():
    """[X49] SRF: 4 labelled segments; sums equal the non-dimensional totals; assets tie to the balance sheet."""
    s = parse_segments(SRF.read_bytes())
    assert s.issues == []
    assert s.segments == [
        "Chemicals Business (CB)", "Others", "Performance Films & Foil Business (PFB)",
        "Technical Textiles Business (TTB)",
    ]  # fmt: skip
    assert s.total("SegmentRevenue", Q[1], Q[0]) == Decimal(5951100000 + 20794600000 + 21223900000 + 1072400000)
    assert s.total("SegmentAssets", END) == Decimal(22928300000 + 129054600000 + 90429600000 + 2300200000)


def test_segment_totals_are_not_pnl_substitutes_cummins():
    """[X49] Cummins: segment revenue from ops 3,247.47 Cr vs P&L 3,301.21 Cr; segment PBT includes associates."""
    s = parse_segments(CUMMINS.read_bytes())
    assert s.issues == [] and s.segments == ["Engines", "Lubes"]
    r = parse_indas_corp_results(CUMMINS.read_bytes())
    assert r.value("revenue_from_operations", *Q) == Decimal("33012100000")
    assert s.total("SegmentRevenue", Q[1], Q[0]) == Decimal("42620300000")  # before inter-segment elimination
    assert r.value("pbt", *Q) + r.value("share_of_associates_jv", *Q) == Decimal("6412300000")  # SegmentProfitBeforeTax


def test_single_segment_filers_have_no_segment_facts():
    assert parse_segments(APL.read_bytes()).facts == []


def test_power_fuel_and_freight_label_rules_aia():
    """[X50] AIA Engineering labels 'Power and fuel' and 'Freight outward expenses' inside OtherExpenses."""
    r = parse_indas_corp_results(AIA.read_bytes())
    assert r.value("power_and_fuel", *Q) == Decimal("825033000")
    assert r.value("freight", *Q) == Decimal("1201982000")
    assert r.value("power_and_fuel", *Q) + r.value("freight", *Q) < r.value("other_expenses", *Q)


def test_power_and_fuel_absent_means_null_not_zero():
    r = parse_indas_corp_results(CUMMINS.read_bytes())
    assert r.value("power_and_fuel", *Q) is None


@pytest.mark.parametrize(
    ("label", "rule", "matches"),
    [
        ("Power and fuel", "POWER_AND_FUEL", True),
        ("Power, fuel and water", "POWER_AND_FUEL", True),
        ("Power & fuel expenses", "POWER_AND_FUEL", True),
        ("Fuel and power", "POWER_AND_FUEL", False),
        ("Freight outward expenses", "FREIGHT", True),
        ("Packing and freight", "FREIGHT", False),
        ("Right of use assets", "RIGHT_OF_USE_ASSETS", True),
        ("Right-of-use assets", "RIGHT_OF_USE_ASSETS", True),
    ],
)
def test_new_label_patterns(label, rule, matches):
    (rx,) = [r[5] for r in LABEL_RULES if r[0] == rule]
    assert bool(rx.match(label)) is matches


def test_cwip_and_intangibles_under_development_feed_screener_cwip():
    r = parse_indas_corp_results(CUMMINS.read_bytes())
    from financials.statements.balance_sheet import balance_sheet

    st = balance_sheet(r, END)
    assert st.rows["Capital Work in Progress"].value == Decimal("787900000") + Decimal("346700000")
    book = FactBook("e", "CONSOLIDATED")
    for f in r.facts:
        if f.period_type == "INSTANT":
            book.instants.setdefault(f.canonical_tag, {})[f.period_end] = f.value
    assert building_blocks(book, END)["bs_as_of"] == END


def test_expense_sub_rows_split_power_and_freight_and_still_sum():
    from financials.statements.quarterly import corp_quarter

    st = corp_quarter(parse_indas_corp_results(AIA.read_bytes()), *Q)
    parts = st.rows["Expenses"].parts
    assert parts["Power and fuel"] == Decimal("825033000") and parts["Freight"] == Decimal("1201982000")
    assert sum(v for v in parts.values() if v is not None) == st.rows["Expenses"].value
