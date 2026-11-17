"""Attribution with a missing or zero NCI element [X105].

- Premier Energies Q4 FY25 consolidated (1475626): owners element = TCI (277.346 Cr), no NCI element, PAT 277.805 Cr.
  OWNERS_TAGGED_AS_TCI (X56) required a filed NCI of 0; a missing NCI now counts as 0, so owners := PAT (exact).
- Finolex Cables Q4 FY25 consolidated (1456174): owners = NCI = PAT = 191.71 Cr. NCI_TAGGED_AS_PAT (X91) required
  owners != PAT; with owners = PAT the NCI is PAT - owners = 0.
- STL Tech 9M FY26 consolidated (1609091, crore rounding): NCI filed 0, PAT -3 Cr, owners 10 Cr. X91 matched
  "NCI = PAT" within the 3-unit tolerance and produced owners 10 / NCI -13 Cr (PDF: owners (3) Cr). A zero NCI is no
  longer read as PAT. Since X214 (ATTRIBUTION_BY_EPS, 2026-11-18) the filing's own EPS decides the split: owners
  := PAT = (3) Cr with NCI 0, which is the PDF's figure (before X214 the split was withheld, X86).
"""

from __future__ import annotations

from decimal import Decimal

from _fixture_helpers import XBRL_DIR
from financials.parsers.integrated import parse_integrated_results


def _split(name, period):
    r = parse_integrated_results((XBRL_DIR / name).read_bytes(), name)
    assert r.ok and not r.issues
    return {
        f.canonical_tag: (f.value, f.source_element)
        for f in r.facts
        if f.canonical_tag in ("pat", "pat_owners", "pat_nci", "attribution_withheld")
        and (str(f.period_start), str(f.period_end)) == period
    }


def test_missing_nci_with_owners_tagged_as_tci_recovers_owners_as_pat():
    s = _split("INTEGRATED_FILING_INDAS_1475626_01072025025937_WEB.xml", ("2025-01-01", "2025-03-31"))
    assert s["pat_owners"] == (s["pat"][0], "RULE:OWNERS_TAGGED_AS_TCI")
    assert s["pat"][0] == Decimal("2778050000") and "pat_nci" not in s


def test_nci_and_owners_both_tagged_as_pat_gives_zero_nci():
    s = _split("INTEGRATED_FILING_INDAS_1456174_29052025103806_WEB.xml", ("2025-01-01", "2025-03-31"))
    assert s["pat"][0] == s["pat_owners"][0] == Decimal("1917100000")
    assert s["pat_nci"] == (Decimal(0), "RULE:NCI_TAGGED_AS_PAT")


def test_zero_nci_within_tolerance_of_pat_is_not_nci_tagged_as_pat():
    s = _split("INTEGRATED_FILING_INDAS_1609091_23012026034910_WEB.xml", ("2025-04-01", "2025-12-31"))
    assert s["pat"][0] == Decimal("-30000000")
    assert s["pat_owners"] == (Decimal("-30000000"), "RULE:ATTRIBUTION_BY_EPS")  # PDF: owners (3) Cr
    assert s["pat_nci"] == (Decimal(0), "RULE:ATTRIBUTION_BY_EPS") and "attribution_withheld" not in s
