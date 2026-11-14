"""Mis-tagged profit attribution (owners / NCI) in consolidated Integrated Filings [X84, X85, X86].

Live backfill: 153 results filings (141 Nifty 500, 63 companies) failed OWNERS_PLUS_NCI and were quarantined whole,
although revenue, PAT and the balance sheet reconcile. Every one checked was a company tagging error, not a parse
error (NSE's own iXBRL rendering shows the same numbers). Two patterns are recovered exactly; the rest is withheld.
"""

from __future__ import annotations

from decimal import Decimal

from _fixture_helpers import XBRL_DIR
from financials.parsers.indas_corp import parse_indas_corp_results

ADANIPORTS_Q4FY26 = XBRL_DIR / "INTEGRATED_FILING_INDAS_1662399_30042026063302_WEB.xml"
GODREJAGRO_Q2FY27 = XBRL_DIR / "INTEGRATED_FILING_INDAS_1754829_06112026051018_WEB.xml"
COFORGE_Q4FY26 = XBRL_DIR / "INTEGRATED_FILING_INDAS_1663900_05052026095708_WEB.xml"

Q4FY26, FY26 = ("2026-01-01", "2026-03-31"), ("2025-04-01", "2026-03-31")


def _split(r, start, end):
    return {
        f.canonical_tag: (f.value, f.source_element)
        for f in r.facts
        if f.canonical_tag in ("pat", "pat_owners", "pat_nci", "attribution_withheld")
        and (str(f.period_start), str(f.period_end)) == (start, end)
    }


def _raw(path, element, context):
    import re

    m = re.search(rf'<in-capmkt:{element} contextRef="{context}"[^>]*>([^<]*)<', path.read_text())
    return Decimal(m.group(1))


def test_adani_ports_owners_and_nci_elements_carry_the_oci_attribution():
    """As filed (rupees): owners 12,386,700,000 + NCI 1,791,400,000 = OCI 14,178,100,000, not PAT 33,083,000,000.
    The results PDF reads owners 3,328.96 cr and NCI (20.66) cr = TCI attribution minus OCI attribution."""
    assert _raw(ADANIPORTS_Q4FY26, "ProfitOrLossAttributableToOwnersOfParent", "OneD") == Decimal("12386700000")
    assert _raw(ADANIPORTS_Q4FY26, "OtherComprehensiveIncomeNetOfTaxes", "OneD") == Decimal("14178100000")
    r = parse_indas_corp_results(ADANIPORTS_Q4FY26.read_bytes())
    assert not r.issues and not r.findings
    q = _split(r, *Q4FY26)
    assert q["pat"][0] == Decimal("33083000000")
    assert q["pat_owners"] == (Decimal("33289600000"), "RULE:ATTRIBUTION_TAGGED_AS_OCI")
    assert q["pat_nci"] == (Decimal("-206600000"), "RULE:ATTRIBUTION_TAGGED_AS_OCI")
    fy = _split(r, *FY26)
    assert fy["pat_owners"][0] + fy["pat_nci"][0] == fy["pat"][0] == Decimal("127820300000")
    rules = {x["rule"]: x["periods"] for x in r.meta["rules_applied"]}
    assert sorted(rules["ATTRIBUTION_TAGGED_AS_OCI"]) == sorted([list(Q4FY26), list(FY26)])
    asfiled = {f.canonical_tag for f in r.facts if f.source_element == "ProfitOrLossAttributableToOwnersOfParent"}
    assert asfiled == {"asfiled_profit_or_loss_attributable_to_owners_of_parent"}  # zero-drop (C24)


def test_godrej_agrovet_nci_filed_with_the_wrong_sign():
    """H1 FY27 as filed: owners 2,497,100,000 and NCI +186,500,000 against PAT 2,310,600,000 (= owners - NCI).
    Q2 as filed reconciles (NCI -124,600,000) and is left untouched."""
    r = parse_indas_corp_results(GODREJAGRO_Q2FY27.read_bytes())
    assert not r.issues and not r.findings
    h1 = _split(r, "2026-04-01", "2026-09-30")
    assert h1["pat_owners"] == (Decimal("2497100000"), "RULE:ATTRIBUTION_SIGN_FLIP")
    assert h1["pat_nci"] == (Decimal("-186500000"), "RULE:ATTRIBUTION_SIGN_FLIP")
    q2 = _split(r, "2026-07-01", "2026-09-30")
    assert q2["pat_owners"][1] == "ProfitOrLossAttributableToOwnersOfParent"
    assert q2["pat_owners"][0] + q2["pat_nci"][0] == q2["pat"][0]


def test_coforge_unrecoverable_split_is_withheld_and_the_filing_still_parses():
    """Q4 FY26: owners 5,722,000,000 + NCI 608,000,000 = TCI 6,330,000,000, not PAT 6,662,000,000; the OCI split is
    not tagged, so no exact recovery exists. Owners / NCI are withheld (no fallback to PAT); PAT stays."""
    r = parse_indas_corp_results(COFORGE_Q4FY26.read_bytes())
    assert r.ok and not r.issues
    for period in (Q4FY26, FY26):
        s = _split(r, *period)
        assert set(s) == {"pat", "attribution_withheld"}
        assert s["attribution_withheld"] == (Decimal(1), "RULE:ATTRIBUTION_WITHHELD")
    assert sorted(f.details["period"] for f in r.findings) == sorted([list(Q4FY26), list(FY26)])
    assert {(f.stage, f.reason_code) for f in r.findings} == {("IDENTITY", "ATTRIBUTION_WITHHELD")}
    assert _split(r, *Q4FY26)["pat"][0] == Decimal("6662000000")


def test_withheld_split_does_not_fall_back_to_pat_in_readers():
    """X86: owners' profit for a withheld period is absent (no COALESCE to PAT), so quarterly sums / TTM of owners'
    profit cannot silently use total PAT; other periods still coalesce as before."""
    from datetime import date

    from financials.fundamentals import FactBook

    q3, q4 = (date(2025, 10, 1), date(2025, 12, 31)), (date(2026, 1, 1), date(2026, 3, 31))
    b = FactBook("e", "CONSOLIDATED")
    b.durations["pat"] = {q3: Decimal(100), q4: Decimal(120)}
    b.durations["pat_owners"] = {q3: Decimal(90)}
    b.durations["attribution_withheld"] = {q4: Decimal(1)}
    owners = b.durations[b.coalesced("pat_owners", "pat")]
    assert owners == {q3: Decimal(90)}
    b.durations.pop("attribution_withheld")
    b.durations.pop("pat_owners|pat")
    assert b.durations[b.coalesced("pat_owners", "pat")] == {q3: Decimal(90), q4: Decimal(120)}
