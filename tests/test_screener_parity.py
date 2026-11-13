"""Screener parity harness [S1-S7]: our documented row definitions vs golden values (₹ Cr, Q2 FY27).

Goldens are the 30-Sep-2026 quarter column of Screener Excel exports supplied by the user on 2026-11-13
(the exports themselves are not committed). Each golden either matches our row to Screener's display
rounding, or differs by exactly a named, documented divergence whose size is pinned to an XBRL fact.
To add a company: add a fixture plus a GOLDEN entry; to plug in more periods, add another entry.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from _fixture_helpers import XBRL_DIR
from financials.parsers.indas_corp import parse_indas_corp_results
from financials.parsers.xbrl import parse_instance
from financials.statements.quarterly import (
    CR,
    bank_quarter,
    corp_quarter,
    general_quarter,
    life_quarter,
    nbfc_quarter,
    quarter_facts,
    tie_out,
)

Q = (date(2026, 7, 1), date(2026, 9, 30))
TOL = Decimal("0.011")  # Screener displays ₹ Cr to 2 dp; filings in ₹ lakh round differently by 0.01
ASSOC = "ShareOfProfitLossOfAssociatesAndJointVenturesAccountedForUsingEquityMethod"

# name -> (fixture, builder, screener rows, {row: (divergence code, XBRL element whose value is the gap)})
GOLDEN = {
    "RELIANCE": ("INTEGRATED_FILING_INDAS_1750537_30102026093254_WEB.xml", "corp",
                 {"Sales": "330601", "Expenses": "273985", "Operating Profit": "56616", "Other Income": "5793",
                  "Depreciation": "15315", "Interest": "8481", "Profit before tax": "38613", "Tax": "9363",
                  "Net Profit": "25548"}, {}),
    "TCS": ("INTEGRATED_FILING_INDAS_1734607_08102026100810_WEB.xml", "corp",
            {"Sales": "73188", "Expenses": "54373", "Operating Profit": "18815", "Other Income": "1337",
             "Depreciation": "1262", "Interest": "252", "Profit before tax": "18638", "Tax": "4704",
             "Net Profit": "13884"}, {}),
    "ITC": ("INTEGRATED_FILING_INDAS_1751357_02112026065559_WEB.xml", "corp",
            {"Sales": "20268.63", "Expenses": "14623.80", "Operating Profit": "5644.83", "Other Income": "578.66",
             "Depreciation": "490.60", "Interest": "38.27", "Profit before tax": "5694.62", "Tax": "1465.29",
             "Net Profit": "4168.40"},
            {"Other Income": ("ASSOCIATES_PLACEMENT", ASSOC), "Profit before tax": ("ASSOCIATES_PLACEMENT", ASSOC)}),
    "ELIN": ("INTEGRATED_FILING_INDAS_1753872_05112026061939_WEB.xml", "corp",
             {"Sales": "413.36", "Expenses": "399.29", "Operating Profit": "14.07", "Other Income": "0.69",
              "Depreciation": "7.74", "Interest": "2.96", "Profit before tax": "4.06", "Tax": "1.22",
              "Net Profit": "2.85"}, {}),
    "ETERNAL": ("INTEGRATED_FILING_INDAS_1743410_21102026064843_WEB.xml", "corp",
                {"Sales": "24138", "Expenses": "23386", "Operating Profit": "752", "Other Income": "351",
                 "Depreciation": "625", "Interest": "155", "Profit before tax": "323", "Tax": "198",
                 "Net Profit": "125"}, {}),
    "HDFCBANK": ("INTEGRATED_FILING_BANKING_1740913_17102026054812_WEB.xml", "bank",
                 {"Revenue": "95131.63", "Expenses": "50028.72", "Other Income": "34227.06", "Interest": "50667.43",
                  "Profit before tax": "28662.54", "Tax": "7125.45", "Net Profit": "20700.03"},
                 {"Profit before tax": ("BANK_EXCEPTIONAL", "ExceptionalItems")}),
    "BAJFINANCE": ("INTEGRATED_FILING_NBFC_INDAS_1742040_19102026075918_WEB.xml", "nbfc",
                   {"Revenue": "24546.37", "Expenses": "7119.55", "Other Income": "33.18", "Depreciation": "321.07",
                    "Interest": "8601.73", "Profit before tax": "8537.20", "Tax": "2170.63", "Net Profit": "6266.20"},
                   {"Other Income": ("ASSOCIATES_PLACEMENT", ASSOC),
                    "Profit before tax": ("ASSOCIATES_PLACEMENT", ASSOC)}),
    "HDFCLIFE": ("INTEGRATED_FILING_LI_1739360_15102026072721_WEB.xml", "life",
                 {"Revenue": "24436.62", "Expenses": "24104.63", "Other Income": "246.67",
                  "Profit before tax": "578.66", "Tax": "57.06", "Net Profit": "521.60"}, {}),
    "ICICIGI": ("INTEGRATED_FILING_GI_1740432_16102026073544_WEB.xml", "general",
                {"Revenue": "8220.06", "Expenses": "7004.94", "Other Income": "32.29", "Profit before tax": "1247.41",
                 "Tax": "301.01", "Net Profit": "946.40"}, {}),
}  # fmt: skip

RAW_BUILDERS = {"bank": bank_quarter, "nbfc": nbfc_quarter, "life": life_quarter, "general": general_quarter}


def build(name: str):
    fixture, kind, _, _ = GOLDEN[name]
    data = (XBRL_DIR / fixture).read_bytes()
    facts = quarter_facts(parse_instance(data), Q[1])
    st = corp_quarter(parse_indas_corp_results(data), *Q) if kind == "corp" else RAW_BUILDERS[kind](facts)
    return st, facts


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_rows_match_screener_or_documented_divergence(name):
    st, facts = build(name)
    _, _, golden, divergent = GOLDEN[name]
    for row, want in golden.items():
        ours = st.rows[row].value
        assert ours is not None, (name, row)
        gap = Decimal(want) - ours / CR
        if row in divergent:
            code, element = divergent[row]
            assert any(code in d for d in st.divergences), (name, row, st.divergences)
            expected_gap = -facts[element] / CR if code == "BANK_EXCEPTIONAL" else facts[element] / CR
            assert abs(gap - expected_gap) <= TOL, (name, row, gap, expected_gap)
        else:
            assert abs(gap) <= TOL, (name, row, ours / CR, want)


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_statement_ties_out_to_reported_pbt(name):
    """Revenue - Expenses - Interest - Depreciation + Other Income (+ bank exceptional) = our PBT, to the rupee."""
    st, _ = build(name)
    assert tie_out(st) == 0, (name, tie_out(st))


def test_corp_sub_rows_sum_to_their_parent():
    st, _ = build("ITC")
    oi = st.rows["Other Income"]
    assert sum(v for v in oi.parts.values() if v is not None) == oi.value
    sales = st.rows["Sales"]
    assert sum(sales.parts.values()) == sales.value
    np_parts = st.rows["Net Profit"].parts
    assert np_parts["Profit for the period"] + np_parts["Non-controlling interests"] == st.rows["Net Profit"].value


def test_divergences_are_absent_when_nothing_triggers_them():
    for name in ("TCS", "ETERNAL", "ELIN"):
        assert build(name)[0].divergences == [], name


def test_standalone_filing_does_not_match_consolidated_golden():
    """Screener exports are consolidated when a consolidated filing exists [S1]; the standalone ITC filing differs."""
    st = corp_quarter(parse_indas_corp_results((XBRL_DIR / "INTEGRATED_FILING_INDAS_1751354_02112026065539_WEB.xml")
                                              .read_bytes()), *Q)  # fmt: skip
    assert abs(st.rows["Sales"].value / CR - Decimal("20268.63")) > 1000
