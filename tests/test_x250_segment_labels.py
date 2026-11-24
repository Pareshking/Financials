"""X250: reconciling lines filed as ordinary `ReportableSegmentsNMember`s are not segments in the segment features.

QD audit (2026-11-18): 148 of 909 entities with segment columns (79 NEW) counted an "Unallocated" / "Eliminations" /
"inter-segment" member of their latest segment period as a business segment. Two real, unmodified filings
(tests/fixtures/segments_qd, MANIFEST section QD):
- Suryoday Small Finance Bank Q2 FY27 (Integrated Filing - Banking): ReportableSegments5Member "Unallocated"
  (revenue 0, result (461) lakh) besides Treasury / Retail Banking / Corporate / Other Banking Operations;
- SGLTL (NSE symbol) Q2 FY27: ReportableSegments3Member "Eliminations" revenue -12.899 Cr, so the "largest
  segment share" was 104% of the summed segment revenue.
Storage stays as filed (member_role is derived from the member name, never the label); the reader drops the label.
"""

from datetime import date
from pathlib import Path

import pytest

from financials import features_more as M
from financials.parsers.segments import parse_segments

FIX = Path(__file__).parent / "fixtures" / "segments_qd"
SURYODAY = FIX / "INTEGRATED_FILING_BANKING_1749476_29102026095319_WEB.xml"
SGLTL = FIX / "INTEGRATED_FILING_INDAS_1753986_05112026065300_WEB.xml"


def _rows(path: Path) -> list[tuple]:
    """The rows segment_inputs builds, from the parsed filing (REVENUE / RESULT of SEGMENT-role members)."""
    out = []
    for f in parse_segments(path.read_bytes()).facts:
        if (
            f.axis_kind == "BUSINESS"
            and f.member_role == "SEGMENT"
            and f.canonical_metric in ("REVENUE", "RESULT")
            and f.period_start is not None
        ):
            label = f.label or f.member.split(":")[-1]
            out.append(
                (
                    f.canonical_metric,
                    (f.period_start, f.period_end),
                    f.period_months,
                    label.strip().lower(),
                    label,
                    f.value,
                    (f.axis, f.member),
                )
            )
    return out


def test_filed_reconciling_members_stay_segment_role():
    """The parser keeps the filing as it is: both reconciling lines are SEGMENT-role members with their label."""
    labels = {f.label: f.member_role for f in parse_segments(SURYODAY.read_bytes()).facts}
    assert labels["Unallocated"] == "SEGMENT"
    labels = {f.label: f.member_role for f in parse_segments(SGLTL.read_bytes()).facts}
    assert labels["Eliminations"] == "SEGMENT"


def test_unallocated_is_not_counted():
    out = M.segment_columns(_rows(SURYODAY))
    assert out["segment_period_end"] == date(2026, 9, 30)
    assert out["segment_count"] == 4  # Treasury, Retail Banking, Corporate, Other Banking Operations
    # Q2 FY27 revenue (Rs lakh, results PDF p7): 9,924 / 77,839 / 5,137 / 1,396
    assert out["largest_segment_revenue_share"] == pytest.approx(77839 / (9924 + 77839 + 5137 + 1396))


def test_eliminations_are_not_a_segment():
    out = M.segment_columns(_rows(SGLTL))
    assert out["segment_count"] == 2  # Engineering & Technology, AI Data Center (0)
    assert out["largest_segment_revenue_share"] == pytest.approx(1.0)  # was 3,094,954,000 / 2,965,964,000 = 1.043


@pytest.mark.parametrize(
    ("label", "drop"),
    [("unallocated", True), ("un-allocated", True), ("unallocable finance and other income", True),
     ("less: inter segment revenue", True), ("inter-segment eliminations", True), ("intersegment", True),
     ("eliminations / adjustments", True), ("total", True), ("unallocated (refer note 5)", True),
     ("media", False), ("others", False), ("total gas", False), ("trading in commodities", False)],
)  # fmt: skip
def test_label_rule(label, drop):
    assert bool(M.NON_SEGMENT_LABEL.match(label)) is drop
