"""X293 OWNERS_FROM_YTD: an owners' period without the attribution takes what the owners' own figures imply.

Lumax Auto Technologies consolidated (fixtures `owners_ytd/`, NSE Integrated Filing XBRL):
- Q1 FY27 (1711189, 10-Aug-2026) files PAT 98.6365 Cr but no ProfitOrLossAttributableToOwnersOfParent (only the
  comprehensive-income split): per-filing COALESCE(owners, PAT) read 98.64 Cr, NCI share included;
- Q2 FY27 (1745364, 24-Oct-2026) files owners' profit for Q2 (105.50894 Cr) and H1 (192.14884 Cr), so the owners'
  Q1 is H1 - Q2 = 86.6399 Cr (not PAT), and the owners' TTM equals the YTD bridge H1 FY27 + FY26 - H1 FY26.
The Q2 FY27 PDF (Rs lakh) prints net profit attributable to owners 10,550.89 (Q2) and 19,214.88 (H1).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from financials.fundamentals import FactBook, building_blocks
from financials.parsers.integrated import parse_integrated_results

DIR = Path(__file__).parent / "fixtures" / "owners_ytd"
Q1 = (date(2026, 4, 1), date(2026, 6, 30))
Q2 = (date(2026, 7, 1), date(2026, 9, 30))
H1 = (date(2026, 4, 1), date(2026, 9, 30))
LAKH = Decimal(100000)


def _facts(name):
    r = parse_integrated_results((DIR / name).read_bytes(), name)
    assert r.ok
    return {(f.canonical_tag, f.period_start, f.period_end): f.value for f in r.facts if f.period_start}


def _book():
    b = FactBook("e", "CONSOLIDATED", fy_starts=frozenset({date(2026, 4, 1), date(2025, 4, 1)}))
    for name in ("INTEGRATED_FILING_INDAS_1711189_10082026062233_WEB.xml",
                 "INTEGRATED_FILING_INDAS_1745364_24102026044213_WEB.xml"):  # fmt: skip
        for (tag, s, e), v in _facts(name).items():
            if tag in ("pat", "pat_owners", "revenue_from_operations"):
                b.durations.setdefault(tag, {})[(s, e)] = v
    return b


def test_fixture_facts():
    q1 = _facts("INTEGRATED_FILING_INDAS_1711189_10082026062233_WEB.xml")
    assert ("pat_owners", *Q1) not in q1 and q1[("pat", *Q1)] == Decimal("986365000")
    q2 = _facts("INTEGRATED_FILING_INDAS_1745364_24102026044213_WEB.xml")
    assert (q2[("pat_owners", *Q2)] / LAKH).quantize(Decimal("0.01")) == Decimal("10550.89")
    assert (q2[("pat_owners", *H1)] / LAKH).quantize(Decimal("0.01")) == Decimal("19214.88")


def test_owners_quarter_is_owners_ytd_minus_the_later_quarter():
    b = _book()
    coalesced = b.durations[b.coalesced("pat_owners", "pat")]
    assert coalesced[Q1] == Decimal("866399000")  # H1 - Q2; was: PAT 98.6365 Cr (NCI included)
    assert coalesced[H1] == Decimal("1921488400") and coalesced[Q2] == Decimal("1055089400")
    assert b.quarter(b.coalesced("pat_owners", "pat"), Q1[1]) == Decimal("866399000")


def test_owners_ttm_uses_the_derived_owners_quarter():
    """Synthetic prior-year owners' figures (FY26 278.8568 Cr, H1 FY26 108.2736 Cr, quarters Q3 / Q4 FY26 82.4681 /
    88.1151 Cr, PAT for the PAT-only quarters) complete the window: owners' TTM = H1 + FY - H1PY = 362.73204 Cr; the
    old per-filing coalesce summed Q2 owners + Q1 PAT + Q4 + Q3 = 374.7286 Cr."""
    b = _book()
    fy, h1py = (date(2025, 4, 1), date(2026, 3, 31)), (date(2025, 4, 1), date(2025, 9, 30))
    q3, q4 = (date(2025, 10, 1), date(2025, 12, 31)), (date(2026, 1, 1), date(2026, 3, 31))
    own = {fy: "2788568000", h1py: "1082736000", q3: "824681000", q4: "881151000"}
    for p, v in own.items():
        b.durations["pat_owners"][p] = Decimal(v)
        b.durations["pat"][p] = Decimal(v) + Decimal(100000000)
    blocks = building_blocks(b, Q2[1])
    assert blocks["pat_owners"] == Decimal("3627320400")
    assert blocks["pat_owners_continuing"] == Decimal("3627320400")


def test_no_owners_ytd_keeps_the_pat_fallback():
    """Without the Q2 filing (point in time before 24-Oct-2026) the Q1 PAT fallback stays (X42)."""
    b = FactBook("e", "CONSOLIDATED", fy_starts=frozenset({date(2026, 4, 1)}))
    for (tag, s, e), v in _facts("INTEGRATED_FILING_INDAS_1711189_10082026062233_WEB.xml").items():
        if tag in ("pat", "pat_owners"):
            b.durations.setdefault(tag, {})[(s, e)] = v
    b.durations.setdefault("pat_owners", {})
    assert b.durations[b.coalesced("pat_owners", "pat")][Q1] == Decimal("986365000")
