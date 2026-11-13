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


# ------------------------------------------------------- second wave of exports (2026-11-13 afternoon) [S16-S19]
# Each Screener export matched to the filing of the same view; the view of every export was established by which
# filing it ties to (S19). Divergence values as above: an element tuple (gap = their sum) or a pinned Decimal residual.
REGDEF = "NetMovementInRegulatoryDeferralAccountBalancesRelatedToProfitOrLossAndTheRelatedDeferredTaxMovement"
DISC = "ProfitLossFromDiscontinuedOperationsAfterTax"

WAVE2 = {  # name: (fixture, kind, quarter end, Screener rows in Rs crore)
    "AIA_ENG": (
        "INTEGRATED_FILING_INDAS_1751861_03112026045154_WEB.xml",
        "corp",
        "2026-09-30",
        {
            "Sales": "1112.78",
            "Expenses": "829.73",
            "Operating Profit": "283.05",
            "Other Income": "78.60",
            "Depreciation": "30.54",
            "Interest": "1.61",
            "Profit before tax": "329.50",
            "Tax": "80.08",
            "Net Profit": "249.73",
        },
    ),
    "APL_APOLLO": (
        "INTEGRATED_FILING_INDAS_1746046_26102026055540_WEB.xml",
        "corp",
        "2026-09-30",
        {
            "Sales": "7001.70",
            "Expenses": "6423.89",
            "Operating Profit": "577.81",
            "Other Income": "40.16",
            "Depreciation": "65.87",
            "Interest": "52.40",
            "Profit before tax": "499.70",
            "Tax": "117.28",
            "Net Profit": "382.42",
        },
    ),
    "BAJFINANCE_STANDALONE": (
        "INTEGRATED_FILING_NBFC_INDAS_1742038_19102026075842_WEB.xml",
        "nbfc",
        "2026-09-30",
        {
            "Revenue": "20890.66",
            "Expenses": "6796.74",
            "Other Income": "28.74",
            "Depreciation": "303.01",
            "Interest": "6398.84",
            "Profit before tax": "7420.81",
            "Tax": "1884.71",
            "Net Profit": "5536.10",
        },
    ),
    "CHOLAFIN": (
        "INTEGRATED_FILING_NBFC_INDAS_1748395_28102026112856_WEB.xml",
        "nbfc",
        "2026-09-30",
        {
            "Revenue": "9270.92",
            "Expenses": "2789.86",
            "Other Income": "124.92",
            "Depreciation": "83.17",
            "Interest": "4334.43",
            "Profit before tax": "2188.38",
            "Tax": "558.04",
            "Net Profit": "1630.34",
        },
    ),
    "CUMMINS": (
        "INTEGRATED_FILING_INDAS_1753292_04112026105837_WEB.xml",
        "corp",
        "2026-09-30",
        {
            "Sales": "3301.21",
            "Expenses": "2794.94",
            "Operating Profit": "506.27",
            "Other Income": "191.89",
            "Depreciation": "53.93",
            "Interest": "3.00",
            "Profit before tax": "641.23",
            "Tax": "134.06",
            "Net Profit": "507.17",
        },
    ),
    "ELIN_STANDALONE": (
        "INTEGRATED_FILING_INDAS_1753867_05112026061857_WEB.xml",
        "corp",
        "2026-09-30",
        {
            "Sales": "289.55",
            "Expenses": "279.87",
            "Operating Profit": "9.68",
            "Other Income": "0.63",
            "Depreciation": "6.31",
            "Interest": "1.92",
            "Profit before tax": "2.08",
            "Tax": "0.67",
            "Net Profit": "1.41",
        },
    ),
    "HDFCBANK_STANDALONE": (
        "INTEGRATED_FILING_BANKING_1740912_17102026054806_WEB.xml",
        "bank",
        "2026-09-30",
        {
            "Revenue": "83426.60",
            "Expenses": "22540.40",
            "Other Income": "13831.02",
            "Interest": "48807.42",
            "Profit before tax": "25909.80",
            "Tax": "6399.84",
            "Net Profit": "19509.96",
        },
    ),
    "INDUSINDBK_Q1": (
        "INTEGRATED_FILING_BANKING_1699401_22072026052845_WEB.xml",
        "bank",
        "2026-06-30",
        {
            "Revenue": "11309.94",
            "Expenses": "5082.10",
            "Other Income": "1786.53",
            "Interest": "6625.22",
            "Profit before tax": "1389.15",
            "Tax": "352.13",
            "Net Profit": "1037.05",
        },
    ),
    "ITC_STANDALONE": (
        "INTEGRATED_FILING_INDAS_1751354_02112026065539_WEB.xml",
        "corp",
        "2026-09-30",
        {
            "Sales": "18401.02",
            "Expenses": "13241.52",
            "Operating Profit": "5159.50",
            "Other Income": "781.86",
            "Depreciation": "427.85",
            "Interest": "31.76",
            "Profit before tax": "5481.75",
            "Tax": "1344.63",
            "Net Profit": "4137.12",
        },
    ),
    "KOTAKBANK": (
        "INTEGRATED_FILING_BANKING_1745380_24102026050818_WEB.xml",
        "bank",
        "2026-09-30",
        {
            "Revenue": "19855.87",
            "Expenses": "13215.98",
            "Other Income": "9571.01",
            "Interest": "8680.60",
            "Profit before tax": "7530.30",
            "Tax": "1896.23",
            "Net Profit": "5645.38",
        },
    ),
    "MUTHOOTFIN": (
        "INTEGRATED_FILING_NBFC_INDAS_1750814_31102026080404_WEB.xml",
        "nbfc",
        "2026-09-30",
        {
            "Revenue": "9997.77",
            "Expenses": "1856.93",
            "Other Income": "13.01",
            "Depreciation": "38.22",
            "Interest": "3716.59",
            "Profit before tax": "4399.04",
            "Tax": "1121.04",
            "Net Profit": "3246.53",
        },
    ),
    "NIACL": (
        "INTEGRATED_FILING_GI_1750334_30102026070831_WEB.xml",
        "general",
        "2026-09-30",
        {
            "Revenue": "13720.93",
            "Expenses": "14990.79",
            "Other Income": "63.93",
            "Profit before tax": "-1205.93",
            "Tax": "54.08",
            "Net Profit": "-1250.75",
        },
    ),
    "PNBHOUSING": (
        "INTEGRATED_FILING_NBFC_INDAS_1748226_28102026075925_WEB.xml",
        "nbfc",
        "2026-09-30",
        {
            "Revenue": "2423.15",
            "Expenses": "195.90",
            "Other Income": "0.80",
            "Depreciation": "16.78",
            "Interest": "1414.66",
            "Profit before tax": "796.61",
            "Tax": "180.06",
            "Net Profit": "616.55",
        },
    ),
    "PNB": (
        "INTEGRATED_FILING_BANKING_1740466_16102026082756_WEB.xml",
        "bank",
        "2026-09-30",
        {
            "Revenue": "35267.24",
            "Expenses": "7838.79",
            "Other Income": "3523.86",
            "Interest": "23464.05",
            "Profit before tax": "7488.26",
            "Tax": "1927.12",
            "Net Profit": "5898.37",
        },
    ),
    "RELIANCE_STANDALONE": (
        "INTEGRATED_FILING_INDAS_1750535_30102026093155_WEB.xml",
        "corp",
        "2026-09-30",
        {
            "Sales": "172408.00",
            "Expenses": "150021.00",
            "Operating Profit": "22387.00",
            "Other Income": "3899.00",
            "Depreciation": "3994.00",
            "Interest": "1953.00",
            "Profit before tax": "20339.00",
            "Tax": "4985.00",
            "Net Profit": "15354.00",
        },
    ),
    "SBILIFE": (
        "INTEGRATED_FILING_LI_1747186_27102026072642_WEB.xml",
        "life",
        "2026-09-30",
        {
            "Revenue": "24619.70",
            "Expenses": "24057.87",
            "Other Income": "28.04",
            "Profit before tax": "589.87",
            "Tax": "40.64",
            "Net Profit": "549.23",
        },
    ),
    "SRF": (
        "INTEGRATED_FILING_INDAS_1743533_21102026080703_WEB.xml",
        "corp",
        "2026-09-30",
        {
            "Sales": "4904.20",
            "Expenses": "3958.32",
            "Operating Profit": "945.88",
            "Other Income": "24.94",
            "Depreciation": "228.84",
            "Interest": "70.94",
            "Profit before tax": "671.04",
            "Tax": "161.92",
            "Net Profit": "509.12",
        },
    ),
    "TATAPOWER": (
        "INTEGRATED_FILING_INDAS_1756234_11112026070341_WEB.xml",
        "corp",
        "2026-09-30",
        {
            "Sales": "19635.94",
            "Expenses": "15969.09",
            "Operating Profit": "3666.85",
            "Other Income": "1184.48",
            "Depreciation": "1286.55",
            "Interest": "1384.93",
            "Profit before tax": "2179.85",
            "Tax": "527.81",
            "Net Profit": "1366.11",
        },
    ),
    "TMPV_Q2FY26": (
        "INTEGRATED_FILING_INDAS_1574923_14112025041850_WEB.xml",
        "corp",
        "2025-09-30",
        {
            "Sales": "72349.00",
            "Expenses": "73753.00",
            "Operating Profit": "-1404.00",
            "Other Income": "81507.00",
            "Depreciation": "4871.00",
            "Interest": "686.00",
            "Profit before tax": "74546.00",
            "Tax": "-1702.00",
            "Net Profit": "76170.00",
        },
    ),
    "TMCV_Q2FY26": (
        "INTEGRATED_FILING_INDAS_1574016_13112025070452_WEB.xml",
        "corp",
        "2025-09-30",
        {
            "Sales": "18585.00",
            "Expenses": "16553.00",
            "Operating Profit": "2032.00",
            "Other Income": "-1865.00",
            "Depreciation": "472.00",
            "Interest": "256.00",
            "Profit before tax": "-561.00",
            "Tax": "306.00",
            "Net Profit": "-867.00",
        },
    ),
    "UNITDSPR": (
        "INTEGRATED_FILING_INDAS_1748218_28102026075349_WEB.xml",
        "corp",
        "2026-09-30",
        {
            "Sales": "3258.00",
            "Expenses": "2615.00",
            "Operating Profit": "643.00",
            "Other Income": "75.00",
            "Depreciation": "74.00",
            "Interest": "24.00",
            "Profit before tax": "620.00",
            "Tax": "158.00",
            "Net Profit": "462.00",
        },
    ),
    # Batch 7 new-gen tech exports [S20]
    "DELHIVERY": (
        "INTEGRATED_FILING_INDAS_1750274_30102026064310_WEB.xml",
        "corp",
        "2026-09-30",
        {
            "Sales": "3066.38",
            "Expenses": "2862.51",
            "Operating Profit": "203.87",
            "Other Income": "66.63",
            "Depreciation": "197.49",
            "Interest": "34.02",
            "Profit before tax": "38.99",
            "Tax": "-1.65",
            "Net Profit": "40.64",
        },
    ),
    "NYKAA": (
        "INTEGRATED_FILING_INDAS_1752762_04112026053637_WEB.xml",
        "corp",
        "2026-09-30",
        {
            "Sales": "3006.04",
            "Expenses": "2743.48",
            "Operating Profit": "262.56",
            "Other Income": "9.52",
            "Depreciation": "93.05",
            "Interest": "30.52",
            "Profit before tax": "148.51",
            "Tax": "47.32",
            "Net Profit": "100.81",
        },
    ),
    "NAUKRI": (
        "INTEGRATED_FILING_INDAS_1747783_28102026044327_WEB.xml",
        "corp",
        "2026-09-30",
        {
            "Sales": "903.88",
            "Expenses": "549.89",
            "Operating Profit": "353.99",
            "Other Income": "432.49",
            "Depreciation": "32.94",
            "Interest": "5.81",
            "Profit before tax": "747.73",
            "Tax": "97.96",
            "Net Profit": "479.72",
        },
    ),
    "NAUKRI_STANDALONE": (
        "INTEGRATED_FILING_INDAS_1747782_28102026044245_WEB.xml",
        "corp",
        "2026-09-30",
        {
            "Sales": "841.66",
            "Expenses": "464.41",
            "Operating Profit": "377.25",
            "Other Income": "84.96",
            "Depreciation": "25.06",
            "Interest": "4.85",
            "Profit before tax": "432.30",
            "Tax": "98.40",
            "Net Profit": "333.90",
        },
    ),
    "OLAELEC": (
        "INTEGRATED_FILING_INDAS_1756932_12112026075230_WEB.xml",
        "corp",
        "2026-09-30",
        {
            "Sales": "421.00",
            "Expenses": "639.00",
            "Operating Profit": "-218.00",
            "Other Income": "27.00",
            "Depreciation": "108.00",
            "Interest": "63.00",
            "Profit before tax": "-362.00",
            "Net Profit": "-362.00",
        },
    ),
    "PAYTM": (
        "INTEGRATED_FILING_INDAS_1746348_26102026105317_WEB.xml",
        "corp",
        "2026-09-30",
        {
            "Sales": "2648.00",
            "Expenses": "2381.00",
            "Operating Profit": "267.00",
            "Other Income": "178.00",
            "Depreciation": "146.00",
            "Interest": "7.00",
            "Profit before tax": "292.00",
            "Tax": "67.00",
            "Net Profit": "226.00",
        },
    ),
    "POLICYBZR": (
        "INTEGRATED_FILING_INDAS_1750589_30102026112529_WEB.xml",
        "corp",
        "2026-09-30",
        {
            "Sales": "2177.71",
            "Expenses": "2016.70",
            "Operating Profit": "161.01",
            "Other Income": "99.85",
            "Depreciation": "43.78",
            "Interest": "11.67",
            "Profit before tax": "205.41",
            "Tax": "13.02",
            "Net Profit": "192.45",
        },
    ),
    "SWIGGY": (
        "INTEGRATED_FILING_INDAS_1744176_22102026064114_WEB.xml",
        "corp",
        "2026-09-30",
        {
            "Sales": "7571.00",
            "Expenses": "8343.00",
            "Operating Profit": "-772.00",
            "Other Income": "212.00",
            "Depreciation": "308.00",
            "Interest": "54.00",
            "Profit before tax": "-922.00",
            "Net Profit": "-922.00",
        },
    ),
}


WAVE2_DIVERGENT = {
    "AIA_ENG": {"Other Income": ("ASSOCIATES_PLACEMENT", (ASSOC,)),
                "Profit before tax": ("ASSOCIATES_PLACEMENT", (ASSOC,))},
    "CUMMINS": {"Other Income": ("ASSOCIATES_PLACEMENT", (ASSOC,)),
                "Profit before tax": ("ASSOCIATES_PLACEMENT", (ASSOC,))},
    "TATAPOWER": {"Other Income": ("REGULATORY_DEFERRAL_PLACEMENT", (ASSOC, REGDEF)),
                  "Profit before tax": ("REGULATORY_DEFERRAL_PLACEMENT", (ASSOC, REGDEF))},
    "TMPV_Q2FY26": {"Other Income": ("DISCONTINUED_PLACEMENT", (DISC, ASSOC)),
                    "Profit before tax": ("DISCONTINUED_PLACEMENT", (DISC, ASSOC))},
    # Screener moves the labelled "Fair value loss on equity investments" (2,027 Cr) from Expenses to Other Income
    # and books associates (-12 Cr) in Expenses [S17]
    "TMCV_Q2FY26": {"Expenses": ("LABEL_RECLASS", Decimal("-2015")),
                    "Other Income": ("LABEL_RECLASS", Decimal("-2027")),
                    "Operating Profit": ("LABEL_RECLASS", Decimal("2015")),
                    "Profit before tax": ("ASSOCIATES_PLACEMENT", (ASSOC,))},
    # Screener moves the labelled "Other Income" member (123.59 Cr) out of revenue and adds associates [S17]; Net
    # Profit now matches (1,630.34) because OWNERS_TAGGED_AS_TCI fixes the mis-tagged owners' profit (X67)
    "CHOLAFIN": {"Revenue": ("LABEL_RECLASS", Decimal("-123.59")), "Other Income": ("LABEL_RECLASS", Decimal("124.92")),
                 "Profit before tax": ("ASSOCIATES_PLACEMENT", (ASSOC,))},
    "NIACL": {"Net Profit": ("UNEXPLAINED", Decimal("9.26"))},  # = ProfitLossCarriedToBalanceSheet - PAT [S18]
    # Associates LOSS: Screener books it in Expenses and PBT, not Other Income [S20]; "-" negates the element
    **{k: {"Expenses": ("ASSOCIATES_PLACEMENT", ("-" + ASSOC,)),
           "Operating Profit": ("ASSOCIATES_PLACEMENT", (ASSOC,)),
           "Profit before tax": ("ASSOCIATES_PLACEMENT", (ASSOC,))}
       for k in ("DELHIVERY", "PAYTM", "POLICYBZR", "SWIGGY")},
    "NAUKRI": {"Other Income": ("ASSOCIATES_PLACEMENT", (ASSOC,)),
               "Profit before tax": ("ASSOCIATES_PLACEMENT", (ASSOC,))},
    "OLAELEC": {"Sales": ("UNEXPLAINED", Decimal("1")), "Expenses": ("UNEXPLAINED", Decimal("1"))},  # Rs-crore filer
}  # fmt: skip

WAVE2_PARSERS = {
    "corp": parse_indas_corp_results, "nbfc": parse_indas_nbfc_results, "bank": parse_igaap_bank_results,
    "life": lambda d: parse_insurer_results(d, "IRDAI_LIFE"),
    "general": lambda d: parse_insurer_results(d, "IRDAI_GENERAL"),
}  # fmt: skip
WAVE2_BUILDERS = {"corp": corp_quarter, "nbfc": nbfc_quarter, "bank": bank_quarter, "life": life_quarter,
                  "general": general_quarter}  # fmt: skip


def _period(qe: str) -> tuple[date, date]:
    end = date.fromisoformat(qe)
    return date(end.year if end.month > 2 else end.year - 1, (end.month - 3) % 12 + 1, 1), end


@pytest.mark.parametrize("name", sorted(WAVE2))
def test_second_wave_exports_match_or_documented_divergence(name):
    fixture, kind, qe, golden = WAVE2[name]
    data = (XBRL_DIR / fixture).read_bytes()
    start, end = _period(qe)
    r = WAVE2_PARSERS[kind](data)
    st = WAVE2_BUILDERS[kind](r, start, end)
    facts = quarter_facts(parse_instance(data), end)
    divergent = WAVE2_DIVERGENT.get(name, {})
    for row, want in golden.items():
        ours = st.rows[row].value
        assert ours is not None, (name, row)
        gap = Decimal(want) - ours / CR
        if row not in divergent:
            assert abs(gap) <= TOL, (name, row, ours / CR, want)
            continue
        code, ref = divergent[row]
        if isinstance(ref, Decimal):
            assert abs(gap - ref) <= TOL, (name, row, gap, ref)
        else:
            assert any(d.startswith(code) for d in st.divergences), (name, code, st.divergences)
            expected = (
                sum(
                    (-facts.get(e[1:], Decimal(0)) if e.startswith("-") else facts.get(e, Decimal(0)) for e in ref),
                    Decimal(0),
                )
                / CR
            )
            assert abs(gap - expected) <= TOL, (name, row, gap, expected)


def test_screener_export_follows_the_view_switch():
    """[S19] ITC and Reliance standalone exports tie to the standalone filings and not to the consolidated ones."""
    for name, other in (("ITC_STANDALONE", "INTEGRATED_FILING_INDAS_1751357_02112026065559_WEB.xml"),
                        ("RELIANCE_STANDALONE", "INTEGRATED_FILING_INDAS_1750537_30102026093254_WEB.xml")):  # fmt: skip
        golden = WAVE2[name][3]
        cons = corp_quarter(parse_indas_corp_results((XBRL_DIR / other).read_bytes()), *Q)
        assert abs(Decimal(golden["Sales"]) - cons.rows["Sales"].value / CR) > 1000


def test_star_health_ind_as_117_presentation_on_screener():
    """[S18] Screener: Sales = insurance revenue + investment income (5,341.34); Tax = current + deferred; PBT and net
    profit as filed; Other Income shown as -6.16 against a filed +6.16 (sign flipped, compensated in Expenses)."""
    r = parse_insurer_results((XBRL_DIR / "IF_INS_COM_IND_AS_19799_WebXMLFile_20261027_212749295.xml").read_bytes(),
                              "INDAS_INSURANCE")  # fmt: skip

    def v(t: str) -> Decimal:  # Star Health files in Rs thousand: compare at Screener's 2 dp
        return (r.value(t, *Q) / CR).quantize(Decimal("0.01"))

    assert v("insurance_revenue") + v("investment_income_total_indas") == Decimal("5341.34")
    assert v("current_tax") + v("deferred_tax") == Decimal("86.83")
    assert (v("pbt"), v("pat")) == (Decimal("351.64"), Decimal("264.81"))
    assert v("other_income") == Decimal("6.16")  # Screener: -6.16
    expenses = Decimal("5341.34") - Decimal("6.16") - Decimal("351.64")  # Screener's 4,983.54 = Sales + OI - PBT
    assert expenses == Decimal("4983.54")
