"""X87 STALE_CONTEXT_DATES. Siemens Q3 FY26 (quarter ended 31 Dec 2025, fiscal year 1 Oct 2024 - 31 Mar 2026 after
the change of year end) was filed with every period context still on the previous filing's dates: OneD Apr-Jun 2025
and FourD Oct 2024-Jun 2025, while the declared periods are Oct-Dec 2025 and the fifteen months Oct 2024-Dec 2025.
The results PDF (Rs Mn, "quarter and fifteen months ended 31 December 2025") shows exactly the XBRL values for the
declared periods: standalone revenue 33,985 / 179,167, PAT 2,089 / 22,348. Re-dated, not quarantined."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from _fixture_helpers import XBRL_DIR
from financials.parsers.integrated import parse_integrated_results

STANDALONE = "INTEGRATED_FILING_INDAS_1620148_06022026044508_WEB.xml"
CONSOLIDATED = "INTEGRATED_FILING_INDAS_1620200_06022026050905_WEB.xml"
Q = (date(2025, 10, 1), date(2025, 12, 31))
YTD15 = (date(2024, 10, 1), date(2025, 12, 31))
MN = Decimal(10) ** 6


def test_stale_context_dates_are_re_dated_to_the_declared_periods():
    r = parse_integrated_results((XBRL_DIR / STANDALONE).read_bytes(), STANDALONE)
    assert r.ok and not r.issues
    assert (r.meta["quarter_period"], r.meta["ytd_period"]) == (Q, YTD15)
    rule = {"rule": "STALE_CONTEXT_DATES",
            "periods": {"Four": ["2024-10-01", "2025-06-30"], "One": ["2025-04-01", "2025-06-30"]}}  # fmt: skip
    assert rule in r.meta["rules_applied"]
    assert r.value("revenue_from_operations", *Q) / MN == 33985
    assert r.value("revenue_from_operations", *YTD15) / MN == 179167
    assert (r.value("pat", *Q) / MN, r.value("pat", *YTD15) / MN) == (2089, 22348)
    assert not [f for f in r.facts if f.period_end == date(2025, 6, 30)]  # nothing keeps the stale dates


def test_consolidated_filing_has_the_same_shift():
    r = parse_integrated_results((XBRL_DIR / CONSOLIDATED).read_bytes(), CONSOLIDATED)
    assert r.ok and r.meta["scope"] == "CONSOLIDATED"
    assert r.value("revenue_from_operations", *Q) / MN == 38307


@pytest.mark.parametrize("name", ["INTEGRATED_FILING_INDAS_1753867_05112026061857_WEB.xml"])  # ELIN, correct dates
def test_a_correctly_dated_filing_is_untouched(name):
    r = parse_integrated_results((XBRL_DIR / name).read_bytes(), name)
    assert "STALE_CONTEXT_DATES" not in {x["rule"] for x in r.meta.get("rules_applied", [])}
