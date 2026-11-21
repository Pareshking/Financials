"""Ratio rules found by the NEW-member Screener comparison (work QR, X194-X199).

Fixtures (MANIFEST.md "Ratio rules, NEW members (QR)"): AQYLON (formerly SABTNL) standalone Q4 FY26 and Q4 FY25
integrated filings, real and unmodified. Screener's figures are compare-only and are not stored here.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from _fixture_helpers import FIXTURES
from financials.fundamentals import FactBook, screener_convention_ratios
from financials.parsers.integrated import parse_integrated_results

RULES = FIXTURES / "ratio_rules"
AQYLON_FY26 = RULES / "INTEGRATED_FILING_INDAS_1649412_11042026052716_WEB.xml"
AQYLON_FY25 = RULES / "INTEGRATED_FILING_INDAS_1454104_28052025103044_WEB.xml"
CR = Decimal(10) ** 7
MAR26, MAR25 = date(2026, 3, 31), date(2025, 3, 31)


def _book(*paths) -> FactBook:
    b = FactBook("e", "STANDALONE")
    for p in paths:  # older filing first, so the newer one's values win where both carry a period
        r = parse_integrated_results(p.read_bytes(), p.name)
        assert r.ok and r.meta["scope"] == "STANDALONE", r.issues
        for f in r.facts:
            if f.period_type == "INSTANT":
                b.instants.setdefault(f.canonical_tag, {})[f.period_end] = f.value
            else:
                b.durations.setdefault(f.canonical_tag, {})[(f.period_start, f.period_end)] = f.value
    return b


def _capital(book: FactBook, on: date) -> Decimal:
    i = book.instants
    return (
        i["equity_share_capital"][on]
        + i["other_equity"][on]
        + sum((i.get(t, {}).get(on, Decimal(0)) for t in ("borrowings_noncurrent", "borrowings_current")), Decimal(0))
    )


def test_fixture_facts_capital_employed_straddles_zero():
    """X194 evidence: AQYLON's filed capital employed (equity capital + other equity + borrowings) is negative at
    31-Mar-2025 (borrowings filed as nil) and positive at 31-Mar-2026, while FY26 PBT + finance costs is positive."""
    book = _book(AQYLON_FY25, AQYLON_FY26)
    assert _capital(book, MAR25) == Decimal("-114358000")  # -11.44 Cr: 25.37 - 36.81 + 0 + 0
    assert _capital(book, MAR26) == Decimal("123712000")  # 12.37 Cr: 25.37 - 31.05 + 4.24 + 13.81
    fy = (date(2025, 4, 1), MAR26)
    assert book.durations["pbt"][fy] + book.durations["finance_costs"][fy] > 0


def test_roce_screener_is_null_when_opening_or_closing_capital_is_not_positive():
    """X194 ROCE_SCREENER_POSITIVE_CAPITAL: the average-capital ROCE is defined only when capital employed is
    positive at both ends of the year. AQYLON's average (−11.44 + 12.37) / 2 = 0.47 Cr turned 10.2 Cr of EBIT into a
    ROCE of ~2,185 %; it is now NULL (ours `roce`, on closing capital, is unaffected by this rule)."""
    out = screener_convention_ratios(_book(AQYLON_FY25, AQYLON_FY26), date(2026, 9, 30))
    assert out["roce_screener"] is None
    assert out["working_capital"] is not None  # the other Screener-convention ratios are still computed
