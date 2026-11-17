"""A YTD context that repeats its own quarter's values [X173, rule YTD_COPIES_QUARTER].

Ajax Engineering standalone Q3 FY26 (filing 1624500) files the Apr-Dec 2025 context (`FourD`) with exactly the
Oct-Dec values: revenue 4,335,480,000, total income 4,468,090,000, PBT 517,110,000, PAT 382,410,000, while its Q1 and
Q2 FY26 filings (1501178, 1573866) report revenue of 4,665.2 and 4,448.1 Mn. A nine-month total income below the
first two quarters' would need a negative quarter, so the nine-month context is a copy. Before the rule this one
filing opened four YTD_QUARTER_MISMATCH findings and the X106 bridge used the copied 9M as the year's YTD. Vault scan
2026-11-17: 8 entity-scope periods fire (AJAXENGG, CONFIPET, HILINFRA, OSWALPUMPS, PACEDIGITK, PANSARI x2,
TARACHAND), none in the Nifty 500 seed; 33 open findings close, no break is raised anew.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from _fixture_helpers import FIXTURES
from financials.fundamentals import FactBook
from financials.parsers.integrated import parse_integrated_results

DIR = FIXTURES / "ytd_copy"
Q1 = "INTEGRATED_FILING_INDAS_1501178_02082025064022_WEB.xml"
Q2 = "INTEGRATED_FILING_INDAS_1573866_13112025063241_WEB.xml"
Q3 = "INTEGRATED_FILING_INDAS_1624500_12022026071533_WEB.xml"
FY = date(2025, 4, 1)
Q3P, M9, H1 = (date(2025, 10, 1), date(2025, 12, 31)), (FY, date(2025, 12, 31)), (FY, date(2025, 9, 30))


def _parsed(name):
    r = parse_integrated_results((DIR / name).read_bytes(), name)
    assert r.ok and r.meta["scope"] == "STANDALONE"
    return r


def _book(names=(Q1, Q2, Q3)) -> FactBook:
    book = FactBook("AJAXENGG", "STANDALONE", fy_starts=frozenset({FY}))
    for name in names:
        for f in _parsed(name).facts:
            if f.period_type == "DURATION":
                book.durations.setdefault(f.canonical_tag, {})[(f.period_start, f.period_end)] = f.value
    return book


def test_the_nine_month_context_repeats_the_quarter():
    r = _parsed(Q3)
    for tag, v in (("revenue_from_operations", 4335480000), ("total_income", 4468090000), ("pbt", 517110000),
                   ("pat", 382410000)):  # fmt: skip
        assert r.value(tag, *Q3P) == r.value(tag, *M9) == Decimal(v)
    book = _book()
    assert book.ytd_breaks("revenue_from_operations")  # 9M 4,335.5 Mn vs quarters 13,448.7 Mn


def test_rule_withholds_the_copied_ytd_and_keeps_the_quarters():
    book = _book()
    book.withhold_ytd_copies()
    assert [b["ytd_period"] for b in book.ytd_copies] == [[str(M9[0]), str(M9[1])]]
    for tag in ("revenue_from_operations", "total_income", "pbt", "pat"):
        assert M9 not in book.durations[tag]
        assert book.durations[tag][Q3P] is not None and not book.ytd_breaks(tag)
        assert H1 in book.durations[tag]  # Q2's genuine half-year YTD is untouched
    q = [book.durations["revenue_from_operations"][p] for p in (
        (FY, date(2025, 6, 30)), (date(2025, 7, 1), date(2025, 9, 30)), Q3P)]  # fmt: skip
    assert sum(q) == Decimal("13448730000")


def test_without_the_earlier_quarters_nothing_is_withheld():
    book = _book((Q3,))
    book.withhold_ytd_copies()
    assert book.ytd_copies == [] and M9 in book.durations["pat"]


def test_a_ytd_above_the_earlier_quarters_is_not_called_a_copy():
    """DHANBANK standalone H1 FY26 repeats Q2 (total income 418.16 Cr) but Q1 was 407.06 Cr: equal values alone do
    not say which context is wrong, so the finding stays."""
    book = FactBook("DHANBANK", "STANDALONE", fy_starts=frozenset({FY}))
    q1, q2 = (FY, date(2025, 6, 30)), (date(2025, 7, 1), date(2025, 9, 30))
    for tag, a, b in (("total_income", 4070600000, 4181600000), ("pbt", 121800000, 232000000),
                      ("pat", 121800000, 232000000)):  # fmt: skip
        book.durations[tag] = {q1: Decimal(a), q2: Decimal(b), H1: Decimal(b)}
    assert book.ytd_copy_periods() == []
