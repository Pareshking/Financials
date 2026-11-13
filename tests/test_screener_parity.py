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
from financials.parsers.igaap_bank import parse_igaap_bank_results
from financials.parsers.indas_corp import parse_indas_corp_results
from financials.parsers.indas_nbfc import parse_indas_nbfc_results
from financials.parsers.irdai_insurance import parse_insurer_results
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

PARSED_BUILDERS = {
    "corp": lambda data, period: corp_quarter(parse_indas_corp_results(data), *period),
    "nbfc": lambda data, period: nbfc_quarter(parse_indas_nbfc_results(data), *period),  # Batch 4 parser
    "bank": lambda data, period: bank_quarter(parse_igaap_bank_results(data), *period),  # Batch 5 parser
    "life": lambda data, period: life_quarter(parse_insurer_results(data, "IRDAI_LIFE"), *period),  # Batch 6
    "general": lambda data, period: general_quarter(parse_insurer_results(data, "IRDAI_GENERAL"), *period),
}


def build(name: str):
    fixture, kind, _, _ = GOLDEN[name]
    data = (XBRL_DIR / fixture).read_bytes()
    facts = quarter_facts(parse_instance(data), Q[1])
    st = PARSED_BUILDERS[kind](data, Q)  # every profile is parsed since Batch 6; raw facts only size divergences
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


# ---------------------------------------------------------------- second period and annual statements [S10-S13]
# Q4 FY26 filings: the Jan-Mar 2026 quarter, FY26 P&L (FourD), the 31-Mar-2026 balance sheet and FY26 cash flow.
# Divergence values: an XBRL element (the gap must equal it) or a Decimal (an unexplained residual pinned exactly,
# so any change in Screener's figure or our definition surfaces).
from financials.statements.balance_sheet import balance_sheet  # noqa: E402
from financials.statements.cashflow import cashflow  # noqa: E402

Q4 = (date(2026, 1, 1), date(2026, 3, 31))
FY = (date(2025, 4, 1), date(2026, 3, 31))
MAR = date(2026, 3, 31)
FX = "EffectOfExchangeRateChangesOnCashAndCashEquivalents"
Q4_FILES = {
    "ELIN": "INTEGRATED_FILING_INDAS_1672621_25052026073245_WEB.xml",
    "TCS": "INTEGRATED_FILING_INDAS_1648408_09042026114218_WEB.xml",
    "ITC": "INTEGRATED_FILING_INDAS_1670766_21052026063229_WEB.xml",
    "RELIANCE": "INTEGRATED_FILING_INDAS_1658776_24042026105714_WEB.xml",
    "ETERNAL": "INTEGRATED_FILING_INDAS_1660628_28042026082148_WEB.xml",
    "HDFCBANK": "INTEGRATED_FILING_BANKING_1654391_18042026073048_WEB.xml",
    "BAJFINANCE": "INTEGRATED_FILING_NBFC_INDAS_1661603_29042026104724_WEB.xml",
}
Q4_KIND = {"HDFCBANK": "bank", "BAJFINANCE": "nbfc"}

# (statement, company) -> (screener rows, divergences)
ANNUAL_GOLDEN = {
    ("BS", "ELIN"): ({"Equity Capital": "24.38", "Reserves": "532.12", "Borrowings": "16.53",
                      "Other Liabilities": "192.78", "Total Liabilities": "765.81", "Net Block": "252.70",
                      "Capital Work in Progress": "27.74", "Investments": "81.90", "Other Assets": "403.47"},
                     {"Borrowings": ("UNEXPLAINED", Decimal("0.54")),
                      "Other Liabilities": ("UNEXPLAINED", Decimal("-0.53"))}),
    ("BS", "TCS"): ({"Equity Capital": "362", "Reserves": "106878", "Borrowings": "11283", "Other Liabilities": "62644",
                     "Total Liabilities": "181167", "Net Block": "31343", "Capital Work in Progress": "2665",
                     "Investments": "33988", "Other Assets": "113171"}, {}),
    ("BS", "ITC"): ({"Equity Capital": "1252.95", "Reserves": "71254.35", "Borrowings": "2399.06",
                     "Other Liabilities": "18730.84", "Total Liabilities": "93637.20", "Net Block": "22442.53",
                     "Capital Work in Progress": "1601.88", "Investments": "38128.43", "Other Assets": "31464.36"}, {}),
    ("BS", "RELIANCE"): ({"Equity Capital": "13532", "Reserves": "890498", "Borrowings": "402962",
                          "Other Liabilities": "870554", "Total Liabilities": "2177546", "Net Block": "1124795",
                          "Capital Work in Progress": "237686", "Investments": "248332", "Other Assets": "566733"},
                         {"Borrowings": ("UNEXPLAINED", Decimal("4962")),
                          "Other Liabilities": ("UNEXPLAINED", Decimal("-4962"))}),
    ("BS", "ETERNAL"): ({"Equity Capital": "919", "Reserves": "30061", "Borrowings": "4592",
                         "Other Liabilities": "5150",
                         "Total Liabilities": "40722", "Net Block": "12675", "Capital Work in Progress": "136",
                         "Investments": "14833", "Other Assets": "13078"}, {}),
    ("CF", "ELIN"): ({"Cash from Operating Activity": "53.78", "Cash from Investing Activity": "-34.38",
                      "Cash from Financing Activity": "-15.33", "Net Cash Flow": "4.07"}, {}),
    ("CF", "TCS"): ({"Cash from Operating Activity": "52094", "Cash from Investing Activity": "-11886",
                     "Cash from Financing Activity": "-42133", "Net Cash Flow": "-1925"},
                    {"Cash from Investing Activity": ("FX_IN_INVESTING", FX)}),
    ("CF", "ITC"): ({"Cash from Operating Activity": "18464.31", "Cash from Investing Activity": "-2320.74",
                     "Cash from Financing Activity": "-16147.12", "Net Cash Flow": "-3.55"}, {}),
    ("CF", "RELIANCE"): ({"Cash from Operating Activity": "192113", "Cash from Investing Activity": "-101089",
                          "Cash from Financing Activity": "-51549", "Net Cash Flow": "39475"}, {}),
    ("CF", "ETERNAL"): ({"Cash from Operating Activity": "632", "Cash from Investing Activity": "540",
                         "Cash from Financing Activity": "-842", "Net Cash Flow": "330"},
                        {"Cash from Investing Activity": ("FX_IN_INVESTING", FX)}),
    ("FY", "ELIN"): ({"Sales": "1287.73", "Other Income": "6.41", "Depreciation": "24.37", "Interest": "8.19",
                      "Profit before tax": "29.65", "Tax": "7.05", "Net Profit": "22.59"},
                     {"Other Income": ("UNEXPLAINED", Decimal("-0.23"))}),
    ("FY", "TCS"): ({"Sales": "267021", "Other Income": "-124", "Depreciation": "5560", "Interest": "1227",
                     "Profit before tax": "65487", "Tax": "16033", "Net Profit": "49210"}, {}),
    ("FY", "ITC"): ({"Sales": "78868.40", "Other Income": "2523.09", "Depreciation": "1710.53", "Interest": "85.17",
                     "Profit before tax": "28033.39", "Tax": "7015.24", "Net Profit": "20689.47"},
                    {"Other Income": ("UNEXPLAINED", Decimal("388.99")),
                     "Profit before tax": ("ASSOCIATES_PLACEMENT", ASSOC)}),
    ("FY", "RELIANCE"): ({"Sales": "1055780", "Other Income": "28846", "Depreciation": "57688", "Interest": "27061",
                          "Profit before tax": "123162", "Tax": "27552", "Net Profit": "80775"},
                         {"Sales": ("UNEXPLAINED", Decimal("-1439")),
                          "Other Income": ("UNEXPLAINED", Decimal("-116"))}),
    ("FY", "ETERNAL"): ({"Sales": "54364", "Other Income": "1396", "Depreciation": "1597", "Interest": "392",
                         "Profit before tax": "615", "Tax": "249", "Net Profit": "366"}, {}),
}  # fmt: skip

Q4_GOLDEN = {
    "ELIN": {
        "Sales": "324.19",
        "Expenses": "318.23",
        "Other Income": "1.11",
        "Depreciation": "6.48",
        "Interest": "2.30",
        "Profit before tax": "-1.71",
        "Tax": "-0.95",
        "Net Profit": "-0.76",
    },
    "TCS": {
        "Sales": "70698.00",
        "Expenses": "51422.00",
        "Other Income": "757.00",
        "Depreciation": "1406.00",
        "Interest": "265.00",
        "Profit before tax": "18362.00",
        "Tax": "4578.00",
        "Net Profit": "13718.00",
    },
    "ITC": {
        "Sales": "17824.68",
        "Expenses": "10900.45",
        "Other Income": "699.52",
        "Depreciation": "421.95",
        "Interest": "29.18",
        "Profit before tax": "7172.62",
        "Tax": "1702.88",
        "Net Profit": "5387.97",
    },
    "RELIANCE": {
        "Sales": "294059.00",
        "Expenses": "249918.00",
        "Other Income": "4447.00",
        "Depreciation": "14808.00",
        "Interest": "6585.00",
        "Profit before tax": "27195.00",
        "Tax": "6579.00",
        "Net Profit": "16971.00",
    },
    "ETERNAL": {
        "Sales": "17292.00",
        "Expenses": "16806.00",
        "Other Income": "342.00",
        "Depreciation": "468.00",
        "Interest": "132.00",
        "Profit before tax": "228.00",
        "Tax": "54.00",
        "Net Profit": "174.00",
    },
    "HDFCBANK": {
        "Revenue": "87182.50",
        "Expenses": "44027.87",
        "Other Income": "29737.44",
        "Interest": "45220.44",
        "Profit before tax": "27671.63",
        "Tax": "6597.41",
        "Net Profit": "20350.76",
    },
    "BAJFINANCE": {
        "Revenue": "21605.79",
        "Expenses": "6553.07",
        "Other Income": "10.92",
        "Depreciation": "255.52",
        "Interest": "7398.28",
        "Profit before tax": "7409.84",
        "Tax": "1856.54",
        "Net Profit": "5464.57",
    },
}


def _q4(name):
    data = (XBRL_DIR / Q4_FILES[name]).read_bytes()
    facts = {**quarter_facts(parse_instance(data), MAR)}
    fy_facts = {}
    inst = parse_instance(data)
    for f in inst.facts:
        c = inst.contexts[f.context_id]
        if c.dimensions or c.instant is not None or not f.is_numeric or (c.start, c.end) != FY or f.name in fy_facts:
            continue
        fy_facts[f.name] = Decimal(f.value_text.strip())
    return data, facts, fy_facts


def _check_rows(name, st, golden, divergent, facts):
    for row, want in golden.items():
        ours = st.rows[row].value
        assert ours is not None, (name, row)
        gap = Decimal(want) - ours / CR
        if row in divergent:
            code, ref = divergent[row]
            if isinstance(ref, Decimal):
                assert abs(gap - ref) <= TOL, (name, row, gap, ref)
                continue
            assert any(code in d for d in st.divergences), (name, row, st.divergences)
            expected = -facts[ref] / CR if code == "BANK_EXCEPTIONAL" else facts[ref] / CR
            assert abs(gap - expected) <= TOL, (name, row, gap, expected)
        else:
            assert abs(gap) <= TOL, (name, row, ours / CR, want)


@pytest.mark.parametrize("key", sorted(ANNUAL_GOLDEN))
def test_annual_statements_match_screener(key):
    kind, name = key
    data, _, fy_facts = _q4(name)
    r = parse_indas_corp_results(data)
    assert r.ok, r.issues
    st = {"BS": lambda: balance_sheet(r, MAR), "CF": lambda: cashflow(r, *FY), "FY": lambda: corp_quarter(r, *FY)}[
        kind
    ]()
    golden, divergent = ANNUAL_GOLDEN[key]
    _check_rows(name, st, golden, divergent, fy_facts)


@pytest.mark.parametrize("name", sorted(Q4_FILES))
def test_second_quarter_ties_out_and_keeps_the_same_divergences(name):
    """Jan-Mar 2026: every statement reconciles to PBT; the divergence set is the same as in Jul-Sep 2026."""
    data, facts, _ = _q4(name)
    kind = Q4_KIND.get(name, "corp")
    st = PARSED_BUILDERS[kind](data, Q4)
    assert tie_out(st) == 0
    codes = {d.split(":")[0].split(" ")[0] for d in st.divergences}
    expected = {d.split(":")[0].split(" ")[0] for d in build(name)[0].divergences}
    assert codes == expected, (name, codes, expected)
    divergent = {
        "ITC": {"Other Income": ("ASSOCIATES_PLACEMENT", ASSOC), "Profit before tax": ("ASSOCIATES_PLACEMENT", ASSOC)},
        "BAJFINANCE": {"Other Income": ("ASSOCIATES_PLACEMENT", ASSOC),
                       "Profit before tax": ("ASSOCIATES_PLACEMENT", ASSOC)},
        "HDFCBANK": {"Profit before tax": ("BANK_EXCEPTIONAL", "ExceptionalItems")},
    }.get(name, {})  # fmt: skip
    _check_rows(name, st, Q4_GOLDEN[name], divergent, facts)


def test_balance_sheet_nets_deferred_tax_like_screener():
    """[S10] Total = Assets - min(DTA, DTL): TCS 182372 - 1205 = 181167 (DTL < DTA)."""
    r = parse_indas_corp_results((XBRL_DIR / Q4_FILES["TCS"]).read_bytes())
    st = balance_sheet(r, MAR)
    assert st.rows["Total Assets"].parts["Deferred tax netted"] / CR == Decimal("-1205")
    for side in ("Total Assets", "Total Liabilities"):
        assert st.rows[side].value / CR == Decimal("181167")


def test_audit_status_is_per_context():
    """[X46] Eternal Q4 FY26 marks the quarter Unaudited and the FY Audited; this used to raise ParseError."""
    r = parse_indas_corp_results((XBRL_DIR / Q4_FILES["ETERNAL"]).read_bytes())
    assert (r.meta["audited"], r.meta["audited_ytd"]) == (False, True)
