"""Work QA2: open ATTRIBUTION_WITHHELD findings of the NEW cohort [X317, X318, X319].

- X317 (X214 amended): owners filed = OCI with the NCI filed 0 and no NCI share of TCI. X214 refused every OCI-shaped
  owners figure (Tech Mahindra Q4 FY25: owners + NCI = OCI with a non-zero NCI, neither line usable); with the NCI 0
  the only other candidate is owners := PAT, which the filing's own EPS must confirm.
  Indo Borax Q1 FY26 consolidated (1509540): owners 10,744,000 = OCI, NCI 0 (and TCI NCI 0), PAT 102,041,000;
  EPS 3.18 x 32,090,000 = 102,046,200. DCX Systems FY26 consolidated (1674219): owners 1,201,580,000 = OCI, NCI 0,
  PAT -77,110,000; EPS -0.69 x 111,390,000 = -76,859,100 (Q4: -0.03 x 111,390,000 vs PAT -3,020,000).
- X318 OWNERS_ZERO_NCI_WITHIN_ROUNDING: owners filed 0 with an NCI within the attribution tolerance (3 rounding
  units, X93): owners := PAT - NCI as filed, within that tolerance of PAT whatever the NCI's sign. Prime Securities
  Q4 FY25 consolidated (1424341): owners 0, NCI 300,000, PAT 8,000,000 (FY 383,000,000), Lakhs.
- Not X318: Goldiam Q4 FY25 consolidated (1451463): owners 0, NCI -780,000 (FY) / -592,000 (Q4) against a tolerance
  of 300,000; its FY25 annual report states NCI +780,000, so the sign as filed is wrong and EPS (10.97 x 106,795,000)
  cannot tell PAT - NCI from PAT + NCI: stays withheld (X86).
"""

from __future__ import annotations

import re
from decimal import Decimal

from _fixture_helpers import FIXTURES
from financials.parsers.integrated import parse_integrated_results

QA2 = FIXTURES / "xbrl_qa2"
INDOBORAX_Q1FY26 = QA2 / "INTEGRATED_FILING_INDAS_1509540_12082025042301_WEB.xml"
DCX_Q4FY26 = QA2 / "INTEGRATED_FILING_INDAS_1674219_27052026063304_WEB.xml"
PRIMESECU_Q4FY25 = QA2 / "INTEGRATED_FILING_NBFC_INDAS_1424341_24042025111452_WEB.xml"
GOLDIAM_Q4FY25 = QA2 / "INTEGRATED_FILING_INDAS_1451463_26052025071700_WEB.xml"


def _split(r, start, end):
    return {
        f.canonical_tag: (f.value, f.source_element)
        for f in r.facts
        if f.canonical_tag in ("pat", "pat_owners", "pat_nci", "attribution_withheld")
        and (str(f.period_start), str(f.period_end)) == (start, end)
    }


def _raw(path, element, context):
    m = re.search(rf'<in-capmkt:{element} contextRef="{context}"[^>]*>([^<]*)<', path.read_text())
    return Decimal(m.group(1))


def _withheld(r):
    return sorted(tuple(i.details["period"]) for i in r.findings if i.reason_code == "ATTRIBUTION_WITHHELD")


def test_x317_owners_tagged_as_oci_with_nci_zero_is_chosen_by_eps():
    assert _raw(INDOBORAX_Q1FY26, "ProfitOrLossAttributableToOwnersOfParent", "OneD") == Decimal("10744000")
    assert _raw(INDOBORAX_Q1FY26, "OtherComprehensiveIncomeNetOfTaxes", "OneD") == Decimal("10744000")
    assert _raw(INDOBORAX_Q1FY26, "ProfitOrLossAttributableToNonControllingInterests", "OneD") == 0
    r = parse_integrated_results(INDOBORAX_Q1FY26.read_bytes())
    assert _withheld(r) == []
    q = _split(r, "2025-04-01", "2025-06-30")
    assert q["pat_owners"] == (Decimal("102041000"), "RULE:ATTRIBUTION_BY_EPS")
    assert q["pat_nci"][0] == 0 and q["pat"][0] == Decimal("102041000") and "attribution_withheld" not in q


def test_x317_also_without_a_tci_split_filed():
    r = parse_integrated_results(DCX_Q4FY26.read_bytes())
    assert _withheld(r) == []
    assert _split(r, "2025-04-01", "2026-03-31")["pat_owners"] == (Decimal("-77110000"), "RULE:ATTRIBUTION_BY_EPS")
    assert _split(r, "2026-01-01", "2026-03-31")["pat_owners"] == (Decimal("-3020000"), "RULE:ATTRIBUTION_BY_EPS")


def test_x318_owners_zero_with_nci_within_rounding():
    r = parse_integrated_results(PRIMESECU_Q4FY25.read_bytes())
    assert _withheld(r) == []
    for period, pat in ((("2025-01-01", "2025-03-31"), Decimal("8000000")),
                        (("2024-04-01", "2025-03-31"), Decimal("383000000"))):  # fmt: skip
        s = _split(r, *period)
        assert s["pat"][0] == pat
        assert s["pat_owners"] == (pat - Decimal("300000"), "RULE:OWNERS_ZERO_NCI_WITHIN_ROUNDING")
        assert s["pat_nci"] == (Decimal("300000"), "RULE:OWNERS_ZERO_NCI_WITHIN_ROUNDING")
    rules = {x["rule"] for x in r.meta["rules_applied"] if isinstance(x, dict)}
    assert "OWNERS_ZERO_NCI_WITHIN_ROUNDING" in rules


def test_owners_zero_with_nci_beyond_rounding_stays_withheld():
    assert _raw(GOLDIAM_Q4FY25, "ProfitOrLossAttributableToNonControllingInterests", "FourD") == Decimal("-780000")
    r = parse_integrated_results(GOLDIAM_Q4FY25.read_bytes())
    assert _withheld(r) == [("2024-04-01", "2025-03-31"), ("2025-01-01", "2025-03-31")]
    fy = _split(r, "2024-04-01", "2025-03-31")
    assert "pat_owners" not in fy and "pat_nci" not in fy and fy["attribution_withheld"][0] == 1
