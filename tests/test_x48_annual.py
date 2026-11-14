"""X48 / X56 apply to Reg. 34 annual years too (live backfill: 25 annual filings quarantined OWNERS_PLUS_NCI
because the annual parser never ran the attribution rules). ACUTAAS FY25 standalone files owners' share = 0 and
NCI share = 0 against a profit of 1,595,462,000: the ZERO_ATTRIBUTION_PLACEHOLDER pattern, not a real split."""

from __future__ import annotations

from decimal import Decimal

from _fixture_helpers import XBRL_DIR
from financials.parsers.reg34_annual import parse_reg34_annual

ACUTAAS = XBRL_DIR / "AR_XBRL_ACUTAAS_30102025113233.xml"


def test_zero_attribution_placeholder_in_an_annual_filing():
    r = parse_reg34_annual(ACUTAAS.read_bytes(), ACUTAAS.name)
    assert not r.issues
    rule = {"rule": "ZERO_ATTRIBUTION_PLACEHOLDER", "periods": [["2024-04-01", "2025-03-31"]]}
    assert r.meta["rules_applied"] == [rule]
    tags = {f.canonical_tag: f.value for f in r.facts if f.canonical_tag in ("pat", "pat_owners", "pat_nci")}
    assert tags == {"pat": Decimal("1595462000")}  # placeholders dropped; owners' profit falls back to PAT
