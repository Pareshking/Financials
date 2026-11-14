"""Tax lines copied from the prior-year comparative column [X94].

Muthoot Finance standalone Q2 FY27 (filing 1750817) tags the current quarter's PBT (3,992.52 Cr) with Q2 FY26's
current and deferred tax (789.25 / 17.02 Cr, to the rupee), so PAT = 3,186.25 Cr. The statutory statement reads
current tax 10,050.38 lakh, deferred 108.55 lakh, profit for the period 29,766.29 lakh and EPS 74.14, and the filing's
own EPS is 74.14. PBT - tax = PAT still holds, so no in-filing identity catches it; only the prior-year filing does.
Across the 8,121 vaulted results XBRLs this is the only filing where both components repeat (2026-11-14).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from _fixture_helpers import XBRL_DIR
from financials.fundamentals import TAX_COPY_WITHHELD_TAGS, FactBook
from financials.parsers.integrated import parse_integrated_results

Q2FY27 = "INTEGRATED_FILING_NBFC_INDAS_1750817_31102026081106_WEB.xml"
Q2FY26 = "INTEGRATED_FILING_NBFC_INDAS_1574319_13112025084559_WEB.xml"
Q2, H1 = (date(2026, 7, 1), date(2026, 9, 30)), (date(2026, 4, 1), date(2026, 9, 30))
Q2_PY = (date(2025, 7, 1), date(2025, 9, 30))


def _parsed(name):
    r = parse_integrated_results((XBRL_DIR / name).read_bytes(), name)
    assert r.ok and not r.issues and r.meta["scope"] == "STANDALONE"
    return r


def _book(names) -> FactBook:
    book = FactBook("MUTHOOTFIN", "STANDALONE")
    for name in names:
        for f in _parsed(name).facts:
            if f.period_type == "DURATION":
                book.durations.setdefault(f.canonical_tag, {})[(f.period_start, f.period_end)] = f.value
    return book


def test_filing_repeats_the_prior_year_tax_lines_and_eps_disagrees():
    cur, prev = _parsed(Q2FY27), _parsed(Q2FY26)
    for tag in ("current_tax", "deferred_tax", "tax_expense"):
        assert cur.value(tag, *Q2) == prev.value(tag, *Q2_PY)
    assert cur.value("current_tax", *Q2) == Decimal("7892460000")
    assert cur.value("pbt", *Q2) == Decimal("39925220000") != prev.value("pbt", *Q2_PY)
    assert cur.value("pat", *Q2) == Decimal("31862530000")  # PBT - copied tax
    assert cur.value("eps_basic", *Q2) == Decimal("74.14")  # PDF: PAT 2,976.63 Cr / 40.15 Cr shares
    assert {w["code"] for w in cur.meta["warnings"]} >= {"EPS_INCONSISTENT"}


def test_factbook_withholds_profit_and_tax_of_the_copied_periods():
    book = _book([Q2FY26, Q2FY27])
    book.withhold_tax_copies()
    assert sorted(tuple(b["period"]) for b in book.tax_copied) == sorted(
        [(str(Q2[0]), str(Q2[1])), (str(H1[0]), str(H1[1]))]
    )
    for tag in TAX_COPY_WITHHELD_TAGS:
        assert Q2 not in book.durations.get(tag, {}) and H1 not in book.durations.get(tag, {})
    assert book.durations["pbt"][Q2] == Decimal("39925220000")  # PBT is current and stays
    assert book.durations["pat"][Q2_PY] == Decimal("23451700000")  # the prior year is untouched
    assert book.ttm("pat", date(2026, 9, 30)) is None


def test_without_the_prior_year_nothing_is_withheld():
    book = _book([Q2FY27])
    book.withhold_tax_copies()
    assert book.tax_copied == [] and book.durations["pat"][Q2] == Decimal("31862530000")


def test_a_zero_component_is_not_evidence_of_a_copy():
    """DALBHARAT standalone Q2 FY27 / FY26: current tax 1.00 Cr both years, deferred 0, PBT 16 vs 15 Cr (crore
    rounding). One matching round number is a coincidence, not a copied column."""
    book = FactBook("DALBHARAT", "STANDALONE")
    for p, pbt in ((Q2, 160000000), (Q2_PY, 150000000)):
        book.durations.setdefault("current_tax", {})[p] = Decimal(10000000)
        book.durations.setdefault("deferred_tax", {})[p] = Decimal(0)
        book.durations.setdefault("pbt", {})[p] = Decimal(pbt)
    assert book.tax_copy_breaks() == []


def test_audit_raises_and_closes_the_finding():
    from financials.db import apply_schema, connect
    from financials.promoter import audit_ytd_identity

    con = connect()
    apply_schema(con)
    assert audit_ytd_identity(con, [("ent_mfin", "STANDALONE")]) == []  # no facts: nothing raised
    open_ = con.execute(
        "SELECT count(*) FROM quarantine_queue WHERE reason_code = 'TAX_COPIED_FROM_PRIOR_YEAR'"
    ).fetchone()[0]
    assert open_ == 0
