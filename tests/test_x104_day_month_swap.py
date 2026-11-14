"""Declared period dates with day and month swapped [X104].

ICICI Prudential Life (1600999) and HDFC Life (1601820) Q3 FY26 declare DateOfStartOfReportingPeriod 2025-01-10
(quarter) and 2025-01-04 (YTD) for contexts that start 2025-10-01 and 2025-04-01. The YTD then did not start at
the declared FY start and the whole filing was quarantined (YTD_NOT_FROM_FY_START, 4 filings, live 2026-11-14).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from _fixture_helpers import XBRL_DIR
from financials.parsers.integrated import parse_integrated_results

CASES = {
    "INTEGRATED_FILING_LI_1600999_14012026055812_WEB.xml": Decimal("3902000000"),
    "INTEGRATED_FILING_LI_1601820_15012026075716_WEB.xml": Decimal("4181900000"),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_swapped_declared_dates_are_read_from_the_contexts(name):
    raw = (XBRL_DIR / name).read_text()
    assert 'DateOfStartOfReportingPeriod contextRef="FourD">2025-01-04<' in raw  # as filed
    r = parse_integrated_results((XBRL_DIR / name).read_bytes(), name)
    assert r.ok and not r.issues
    assert r.meta["quarter_period"] == (date(2025, 10, 1), date(2025, 12, 31))
    assert r.meta["ytd_period"] == (date(2025, 4, 1), date(2025, 12, 31))
    swap = next(x for x in r.meta["rules_applied"] if x["rule"] == "DECLARED_DATE_DAY_MONTH_SWAP")
    assert {f["family"]: f["context"] for f in swap["fixed"]} == {"One": "2025-10-01", "Four": "2025-04-01"}
    assert r.value("pat", *r.meta["quarter_period"]) == CASES[name]


def test_rule_fires_on_no_other_committed_fixture():
    hits = set()
    for path in sorted(XBRL_DIR.glob("INTEGRATED_FILING_*.xml")):
        try:
            r = parse_integrated_results(path.read_bytes(), path.name)
        except Exception:
            continue
        if any(x["rule"] == "DECLARED_DATE_DAY_MONTH_SWAP" for x in r.meta.get("rules_applied", [])):
            hits.add(path.name)
    assert hits == set(CASES)
