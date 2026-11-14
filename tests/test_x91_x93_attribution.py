"""Attribution patterns found by checking withheld filings against the companies' results PDFs (X91-X93).

X91 NCI_TAGGED_AS_PAT: the NCI element carries PAT; NCI := PAT - owners (Intellect H1 FY26: PDF NCI (1.147) Mn x10).
X92 OWNERS_AND_NCI_TAGGED_AS_TCI: owners + NCI = TCI with NCI != 0; owners := PAT - NCI (ACC Q1 FY26 375.38 Cr, ATUL
Q2 FY26 179.24 Cr = the PDFs); off by the NCI's share of OCI when that is not 0 (Brigade Q2 FY27 193.62 vs 193.60).
X93: owners + NCI = PAT to 3 rounding units (SPARC Q1 FY27, RPower Q4 FY25: the PDFs show the same 2-3 lakh gap).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from _fixture_helpers import XBRL_DIR
from financials.parsers.integrated import parse_integrated_results

CR = Decimal(10) ** 7


def _parse(name):
    r = parse_integrated_results((XBRL_DIR / name).read_bytes(), name)
    assert r.ok and not r.issues and not r.findings, (r.issues, r.findings)
    return r


def _split(r, end_month_day, months):
    for f in r.facts:
        if f.canonical_tag == "pat" and f.period_months == months and str(f.period_end)[5:] == end_month_day:
            p = (f.period_start, f.period_end)
            return tuple(r.value(t, *p) / CR for t in ("pat", "pat_owners", "pat_nci"))
    raise AssertionError("period not found")


@pytest.mark.parametrize(
    ("name", "end", "months", "pdf_owners", "pdf_nci", "rule"),
    [
        ("INTEGRATED_FILING_INDAS_1562886_31102025071826_WEB.xml", "09-30", 6, "196.76", "-1.147", "NCI_TAGGED_AS_PAT"),
        ("INTEGRATED_FILING_INDAS_1492889_24072025091201_WEB.xml", "06-30", 3, "375.38", "0.04",
         "OWNERS_AND_NCI_TAGGED_AS_TCI"),
        ("INTEGRATED_FILING_INDAS_1551863_17102025035733_WEB.xml", "09-30", 3, "179.24", "3.13",
         "OWNERS_AND_NCI_TAGGED_AS_TCI"),
        ("INTEGRATED_FILING_INDAS_1551863_17102025035733_WEB.xml", "09-30", 6, "307.01", "7.72",
         "OWNERS_AND_NCI_TAGGED_AS_TCI"),
    ],
)  # fmt: skip
def test_recovered_split_equals_the_results_pdf(name, end, months, pdf_owners, pdf_nci, rule):
    r = _parse(name)
    _, owners, nci = _split(r, end, months)
    assert (owners, nci) == (Decimal(pdf_owners), Decimal(pdf_nci))
    assert rule in {x["rule"] for x in r.meta["rules_applied"]}


def test_tci_rule_is_off_by_the_ncis_share_of_oci():
    r = _parse("INTEGRATED_FILING_INDAS_1749418_29102026084017_WEB.xml")  # Brigade Q2 FY27, Lakhs
    pat, owners, nci = _split(r, "09-30", 3)
    assert owners + nci == pat
    assert owners == Decimal("193.62") and abs(owners - Decimal("193.60")) == Decimal("0.02")  # PDF 193.60


@pytest.mark.parametrize(
    ("name", "end", "pat", "owners"),
    [
        ("INTEGRATED_FILING_INDAS_1710906_10082026025320_WEB.xml", "06-30", "-20.78", "-20.76"),  # SPARC Q1 FY27
        ("INTEGRATED_FILING_INDAS_1435405_09052025091610_WEB.xml", "03-31", "125.57", "125.6"),  # RPower Q4 FY25
    ],
)
def test_a_three_unit_rounding_gap_is_accepted_as_filed(name, end, pat, owners):
    r = _parse(name)
    got = _split(r, end, 3)
    assert (got[0], got[1]) == (Decimal(pat), Decimal(owners))
    assert not r.meta.get("rules_applied")
