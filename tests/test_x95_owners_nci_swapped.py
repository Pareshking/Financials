"""Owners and NCI profit filed in each other's elements [X95].

owners + NCI = PAT still holds, so X84-X86 never fire; the filing's own basic EPS tells them apart: NCI / period-end
shares (paid-up / face value) equals the filed EPS and owners / shares does not. PDFs (2026-11-14 audit):
Glenmark Q4 FY26 owners 3,014.14 / NCI (0.95) Mn; Zydus Q4 FY25 owners 11,709 / NCI 728 Mn; Kirloskar Brothers
Q1 FY26 owners 667 / NCI 8 Mn. Among 8,121 vaulted results XBRLs the rule fires on 6 filings (also Shyam Metalics,
Praj, ITC Hotels FY25).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from _fixture_helpers import XBRL_DIR
from financials.parsers.integrated import parse_integrated_results

SWAPPED = {
    # file: (quarter, owners, nci, eps) after the rule, rupees
    "INTEGRATED_FILING_INDAS_1677062_29052026111208_WEB.xml": (
        ("2026-01-01", "2026-03-31"),
        3014140000,
        -950000,
        "10.68",
    ),
    "INTEGRATED_FILING_INDAS_1444664_20052025064321_WEB.xml": (
        ("2025-01-01", "2025-03-31"),
        11709000000,
        728000000,
        "11.64",
    ),
    "INTEGRATED_FILING_INDAS_1500111_01082025034547_WEB.xml": (("2025-04-01", "2025-06-30"), 667000000, 8000000, "8.4"),
}


def _parse(name):
    return parse_integrated_results((XBRL_DIR / name).read_bytes(), name)


def _at(r, tag, period):
    return next(f for f in r.facts if f.canonical_tag == tag and (str(f.period_start), str(f.period_end)) == period)


@pytest.mark.parametrize("name", sorted(SWAPPED))
def test_swapped_owners_and_nci_are_exchanged_back(name):
    q, owners, nci, eps = SWAPPED[name]
    r = _parse(name)
    assert r.ok and not r.issues
    o, n = _at(r, "pat_owners", q), _at(r, "pat_nci", q)
    assert (o.value, n.value) == (Decimal(owners), Decimal(nci))
    assert o.source_element == n.source_element == "RULE:OWNERS_NCI_SWAPPED"
    assert _at(r, "eps_basic", q).value == Decimal(eps)
    assert o.value + n.value == _at(r, "pat", q).value
    assert not any(w["code"] == "EPS_INCONSISTENT" for w in r.meta.get("warnings", []))
    from financials.parsers.xbrl import parse_instance

    inst = parse_instance((XBRL_DIR / name).read_bytes())
    filed = {
        (x.name, inst.contexts[x.context_id].start, inst.contexts[x.context_id].end): Decimal(x.value_text)
        for x in inst.facts
        if x.name in ("ProfitOrLossAttributableToOwnersOfParent", "ProfitOrLossAttributableToNonControllingInterests")
        and not inst.contexts[x.context_id].dimensions
    }
    key = lambda e: (e, date.fromisoformat(q[0]), date.fromisoformat(q[1]))  # noqa: E731
    assert filed[key("ProfitOrLossAttributableToOwnersOfParent")] == Decimal(nci)  # as filed: the swap
    assert filed[key("ProfitOrLossAttributableToNonControllingInterests")] == Decimal(owners)


def test_rule_fires_on_no_other_committed_fixture():
    hits = []
    for path in sorted(XBRL_DIR.glob("INTEGRATED_FILING_*.xml")):
        try:
            r = _parse(path.name)
        except Exception:
            continue
        if any(x["rule"] == "OWNERS_NCI_SWAPPED" for x in r.meta.get("rules_applied", [])):  # X95 only
            hits.append(path.name)
    assert sorted(hits) == sorted(SWAPPED)


def test_missing_nci_element_counts_as_zero_so_owners_tagged_as_oci_is_recovered():
    """X96: THELEELA Q4 FY26 files no NCI element and owners = OCI (264.09 Mn). X84 used to skip the period (NCI
    None), so the wrong owners' profit passed silently. With NCI as filed = 0, X84 recovers owners = TCI owners - OCI:
    1,717.70 Mn (quarter) and 4,031.34 Mn (FY), as in the PDF."""
    r = _parse("INTEGRATED_FILING_INDAS_1660691_28042026092008_WEB.xml")
    assert r.ok and not r.issues and not r.findings
    for q, owners, nci in ((("2026-01-01", "2026-03-31"), 1717700000, -460000),
                           (("2025-04-01", "2026-03-31"), 4031340000, -1010000)):  # fmt: skip
        o, n = _at(r, "pat_owners", q), _at(r, "pat_nci", q)
        assert (o.value, n.value) == (Decimal(owners), Decimal(nci))
        assert o.source_element == n.source_element == "RULE:ATTRIBUTION_TAGGED_AS_OCI"
