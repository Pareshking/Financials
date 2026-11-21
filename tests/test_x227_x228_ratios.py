"""X227 `roe_screener` (Screener's website ROE) and X228 debt / equity of lending NBFCs (work QF3, 2026-11-18).

Fixtures are real, unmodified Integrated Filings already in `tests/fixtures` (MANIFEST.md): Reliance Infrastructure
consolidated Q4 FY25 (1449896) and Q4 FY26 (1672152); AQYLON standalone Q4 FY25 / FY26 (`ratio_rules/`, X194); Bajaj
Finance Q2 FY27 standalone (1742038) and consolidated (1742040), Q4 FY26 consolidated (1661603); Cholamandalam Q2
FY27 consolidated (1748395); HDFC Bank Q4 FY26 consolidated. Values below were computed by hand from the filings.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from _fixture_helpers import FIXTURES, XBRL_DIR
from financials.fundamentals import FactBook, nbfc_blocks, nbfc_gearing, roe_screener
from financials.parsers.integrated import parse_integrated_results

MAR25, MAR26, SEP26 = date(2025, 3, 31), date(2026, 3, 31), date(2026, 9, 30)


def _book(*paths, scope="CONSOLIDATED") -> FactBook:
    b = FactBook("e", scope)
    for p in paths:  # older filing first
        r = parse_integrated_results(p.read_bytes(), p.name)
        assert r.ok and r.meta["scope"] == scope, r.issues
        for f in r.facts:
            if f.period_type == "INSTANT":
                b.instants.setdefault(f.canonical_tag, {})[f.period_end] = f.value
            else:
                b.durations.setdefault(f.canonical_tag, {})[(f.period_start, f.period_end)] = f.value
    return b


# ── X227 roe_screener ──────────────────────────────────────────────────────────────────────────────────────────────
RELINFRA = (XBRL_DIR / "INTEGRATED_FILING_INDAS_1449896_24052025124314_WEB.xml",
            XBRL_DIR / "INTEGRATED_FILING_INDAS_1672152_23052026112720_WEB.xml")  # fmt: skip
AQYLON = (FIXTURES / "ratio_rules" / "INTEGRATED_FILING_INDAS_1454104_28052025103044_WEB.xml",
          FIXTURES / "ratio_rules" / "INTEGRATED_FILING_INDAS_1649412_11042026052716_WEB.xml")  # fmt: skip


def test_roe_screener_is_last_fy_owners_profit_over_average_owners_equity():
    """RELINFRA FY26 consolidated: owners' profit 2,900.228 Cr; owners' equity (equity capital + other equity, NCI
    excluded) 14,430.20 Cr at 31-Mar-2025 and 17,872.52 Cr at 31-Mar-2026: 2 x 2,900.228 / 32,302.72 = 17.96 %. Our
    `roe` (TTM owners' profit / closing owners' equity, C16) is 16.23 % on the same filing."""
    book = _book(*RELINFRA)
    fy = (date(2025, 4, 1), MAR26)
    assert book.durations["pat_owners"][fy] == Decimal("29002280000")
    assert book.instants["equity_attributable_to_owners"][MAR25] == Decimal("144302000000")
    assert book.instants["equity_attributable_to_owners"][MAR26] == Decimal("178725200000")
    assert book.durations["pat"][fy] == Decimal("48383300000")  # total PAT incl. NCI: not Screener's Net Profit
    got = roe_screener(book, SEP26)
    assert got == Decimal("58004560000") / Decimal("323027200000")
    assert round(got, 4) == Decimal("0.1796")


def test_roe_screener_needs_both_balance_sheets_and_positive_equity():
    assert roe_screener(_book(RELINFRA[1]), SEP26) is None  # no 31-Mar-2025 balance sheet in the FY26 filing
    assert roe_screener(_book(*RELINFRA), date(2025, 12, 31)) is None  # FY25: no 31-Mar-2024 balance sheet (C9)
    aq = _book(*AQYLON, scope="STANDALONE")  # owners' equity -11.44 Cr (Mar-25) and -5.68 Cr (Mar-26)
    assert aq.instants["total_equity"][MAR25] < 0 and aq.instants["total_equity"][MAR26] < 0
    assert roe_screener(aq, SEP26) is None


# ── X228 NBFC gearing ──────────────────────────────────────────────────────────────────────────────────────────────
BAF_SA = XBRL_DIR / "INTEGRATED_FILING_NBFC_INDAS_1742038_19102026075842_WEB.xml"
BAF_CONS = XBRL_DIR / "INTEGRATED_FILING_NBFC_INDAS_1742040_19102026075918_WEB.xml"
BAF_FY26 = XBRL_DIR / "INTEGRATED_FILING_NBFC_INDAS_1661603_29042026104724_WEB.xml"
CHOLA = XBRL_DIR / "INTEGRATED_FILING_NBFC_INDAS_1748395_28102026112856_WEB.xml"


def _gearing(path, scope, end):
    book = _book(path, scope=scope)
    assert nbfc_blocks(book, end)["is_lending_nbfc"] is True
    return nbfc_gearing(book, end)


def test_bajaj_finance_gearing_includes_deposits():
    """Bajaj Finance 30-Sep-2026 standalone: debt securities 166,383.07 + borrowings 133,864.42 + deposits 69,671.82
    + subordinated 724.82 = 370,644.13 Cr over equity 110,908.80 Cr = 3.342x. Consolidated: 244,830.95 + 186,672.39
    + 69,753.70 + 724.82 = 501,981.86 Cr over total equity (incl. NCI 3,185.51) 126,365.26 Cr = 3.972x."""
    assert _gearing(BAF_SA, "STANDALONE", SEP26) == Decimal("3706441300000") / Decimal("1109088000000")
    assert round(_gearing(BAF_SA, "STANDALONE", SEP26), 3) == Decimal("3.342")
    assert _gearing(BAF_CONS, "CONSOLIDATED", SEP26) == Decimal("5019818600000") / Decimal("1263652600000")
    assert round(_gearing(BAF_CONS, "CONSOLIDATED", SEP26), 3) == Decimal("3.972")
    # 31-Mar-2026 consolidated: 193,131.90 + 170,642.53 + 68,532.75 + 2,805.31 = 435,112.49 / 116,985.54 = 3.719x
    assert round(_gearing(BAF_FY26, "CONSOLIDATED", MAR26), 3) == Decimal("3.719")


def test_cholamandalam_gearing_with_deposits_filed_nil():
    """Cholamandalam 30-Sep-2026 consolidated: 43,092.19 + 171,059.94 + 0 + 17,758.63 = 231,910.76 Cr over
    34,531.43 Cr = 6.716x."""
    assert _gearing(CHOLA, "CONSOLIDATED", SEP26) == Decimal("2319107600000") / Decimal("345314300000")
    assert round(_gearing(CHOLA, "CONSOLIDATED", SEP26), 3) == Decimal("6.716")


def test_gearing_needs_a_balance_sheet_and_positive_equity():
    book = _book(CHOLA)
    assert nbfc_gearing(book, date(2026, 6, 30)) is None  # no balance sheet on or before the date
    book.instants["total_equity"][SEP26] = Decimal(0)
    assert nbfc_gearing(book, SEP26) is None
