"""Named label rules [X39, X40] on real Batch 1 filings, and their effect on building blocks."""

from datetime import date
from decimal import Decimal

import pytest

from _fixture_helpers import CORP, XBRL_DIR
from financials.parsers.indas_corp import LABEL_RULES, parse_indas_corp_results

ITC = XBRL_DIR / "INTEGRATED_FILING_INDAS_1751354_02112026065539_WEB.xml"
UNITDSPR = XBRL_DIR / "INTEGRATED_FILING_INDAS_1748218_28102026075349_WEB.xml"
ONGC = XBRL_DIR / "INTEGRATED_FILING_INDAS_1753920_05112026063545_WEB.xml"
Q = (date(2026, 7, 1), date(2026, 9, 30))
H1 = (date(2026, 4, 1), date(2026, 9, 30))
END = date(2026, 9, 30)
CR = Decimal(10) ** 7


@pytest.fixture(scope="module")
def parsed():
    return {p.stem: parse_indas_corp_results(p.read_bytes()) for p in (ITC, UNITDSPR, ONGC, CORP)}


def get(parsed, path):
    return parsed[path.stem]


@pytest.mark.parametrize("path", [ITC, UNITDSPR, ONGC])
def test_batch1_filings_parse_clean(parsed, path):
    r = get(parsed, path)
    assert r.ok, r.issues


def test_excise_duty_label_rule(parsed):
    itc = get(parsed, ITC)
    assert itc.value("excise_duty", *Q) == Decimal("99166500000")
    assert itc.value("excise_duty", *H1) == Decimal("199522800000")
    assert itc.value("revenue_from_operations", *Q) == Decimal("283176700000")
    ex = [f for f in itc.facts if f.canonical_tag == "excise_duty"]
    assert {f.source_element for f in ex} == {"LABEL:EXCISE_DUTY"}
    us = get(parsed, UNITDSPR)
    assert us.value("excise_duty", *Q) / CR == Decimal("3743")
    assert us.value("revenue_from_operations", *Q) / CR == Decimal("7001")


def test_lease_label_rule_tolerates_real_typo(parsed):
    ongc = get(parsed, ONGC)
    assert ongc.value("lease_liabilities_noncurrent", END, END) == Decimal("161261600000")
    assert ongc.value("lease_liabilities_current", END, END) == Decimal("81336000000")  # "Lease Liabilties"
    itc = get(parsed, ITC)
    assert itc.value("lease_liabilities_noncurrent", END, END) == Decimal("1066900000")


def test_no_label_means_no_fact(parsed):
    elin = get(parsed, CORP)
    assert elin.value("excise_duty", *Q) is None
    assert elin.value("lease_liabilities_current", END, END) is None


@pytest.mark.parametrize(
    ("label", "rule", "matches"),
    [
        ("Lease liabilities", "LEASE_LIAB_CURRENT", True),
        ("Lease Liabilties", "LEASE_LIAB_CURRENT", True),
        ("Net investment in lease", "LEASE_LIAB_CURRENT", False),
        ("Liabilities towards lease equalisation", "LEASE_LIAB_CURRENT", False),
        ("Excise Duty", "EXCISE_DUTY", True),
        ("Excise duty on sale of goods", "EXCISE_DUTY", True),
        ("Duties and taxes", "EXCISE_DUTY", False),
    ],
)
def test_label_patterns_are_anchored(label, rule, matches):
    (rx,) = [r[5] for r in LABEL_RULES if r[0] == rule]
    assert bool(rx.match(label)) is matches


def test_building_blocks_use_net_sales_and_leases(parsed):
    """Blocks on a one-quarter book: TTM is NULL, but the net-of-excise logic is visible on the quarter."""
    from financials.fundamentals import FactBook

    itc = get(parsed, ITC)
    book = FactBook("e", "STANDALONE")
    for f in itc.facts:
        if f.period_type == "INSTANT":
            book.instants.setdefault(f.canonical_tag, {})[f.period_end] = f.value
        else:
            book.durations.setdefault(f.canonical_tag, {})[(f.period_start, f.period_end)] = f.value
    gross, excise = book.quarter("revenue_from_operations", END), book.quarter("excise_duty", END)
    assert (gross - excise) / CR == Decimal("18401.02")
    from financials.fundamentals import building_blocks

    b = building_blocks(book, END)
    assert b["lease_liabilities"] == Decimal("1066900000") + Decimal("406000000")
    borrowings = (book.instants.get("borrowings_noncurrent", {}).get(END) or 0) + (
        book.instants.get("borrowings_current", {}).get(END) or 0
    )
    assert b["total_debt"] == borrowings + b["lease_liabilities"]
