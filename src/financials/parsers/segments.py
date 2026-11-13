"""Ind AS 108 segment facts from Integrated Filing XBRL [X49]. Pure: bytes -> rows + identity issues.

Segments sit on ReportableSegments*Axis members (`ReportableSegmentsNMember`), one label per member in
`DescriptionOfReportableSegment`. Elements: SegmentRevenue, SegmentProfitLossBeforeTaxAndFinanceCosts
(segment result), SegmentAssets, SegmentLiabilities. Single-segment companies file none (4/10 in Batch 3).
Segment totals are NOT substitutes for P&L lines: Cummins' SegmentRevenueFromOperations differs from
RevenueFromOperations and its SegmentProfitBeforeTax includes associates.
Persistence (a segment table) is not built yet; this parser feeds checks and the registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from financials.parsers.xbrl import Instance, parse_instance

SEGMENT_ELEMENTS = (
    "SegmentRevenue",
    "SegmentProfitLossBeforeTaxAndFinanceCosts",
    "SegmentAssets",
    "SegmentLiabilities",
)


@dataclass(frozen=True)
class SegmentFact:
    member: str
    label: str | None
    element: str
    period_start: date | None
    period_end: date  # instant date for assets/liabilities
    value: Decimal


@dataclass
class SegmentReport:
    facts: list[SegmentFact]
    issues: list[tuple[str, dict]]

    def total(self, element: str, end: date, start: date | None = None) -> Decimal | None:
        vals = [f.value for f in self.facts if f.element == element and f.period_end == end and f.period_start == start]
        return sum(vals, Decimal(0)) if vals else None

    @property
    def segments(self) -> list[str]:
        return sorted({f.label or f.member for f in self.facts})


def _is_segment_axis(axis: str) -> bool:
    return axis.split(":")[-1].startswith("ReportableSegment")


def parse_segments(data: bytes | Instance) -> SegmentReport:
    inst = data if isinstance(data, Instance) else parse_instance(data)
    labels: dict[str, str] = {}
    for f in inst.facts:
        c = inst.contexts[f.context_id]
        if f.name == "DescriptionOfReportableSegment" and c.dimensions and _is_segment_axis(c.dimensions[0][0]):
            labels.setdefault(c.dimensions[0][1], f.value_text.strip())
    facts: list[SegmentFact] = []
    for f in inst.facts:
        c = inst.contexts[f.context_id]
        if f.name not in SEGMENT_ELEMENTS or not c.dimensions or not _is_segment_axis(c.dimensions[0][0]):
            continue
        member = c.dimensions[0][1]
        start, end = (None, c.instant) if c.instant is not None else (c.start, c.end)
        facts.append(SegmentFact(member, labels.get(member), f.name, start, end, Decimal(f.value_text.strip())))
    report = SegmentReport(facts, [])
    _check(inst, report)
    return report


def _nondim(inst: Instance, name: str, start: date | None, end: date) -> Decimal | None:
    for f in inst.facts:
        c = inst.contexts[f.context_id]
        if f.name != name or c.dimensions or not f.is_numeric:
            continue
        if (start is None and c.instant == end) or (start is not None and (c.start, c.end) == (start, end)):
            return Decimal(f.value_text.strip())
    return None


def _check(inst: Instance, report: SegmentReport) -> None:
    """Sum of segments = filed total; segment assets + unallocable = net segment assets = total assets."""
    periods = {(f.element, f.period_start, f.period_end) for f in report.facts}
    for element, start, end in sorted(periods, key=str):
        total, filed = report.total(element, end, start), _nondim(inst, element, start, end)
        if filed is not None and total != filed:
            report.issues.append(("SEGMENT_SUM", {"element": element, "sum": str(total), "filed": str(filed)}))
    for end in sorted({f.period_end for f in report.facts if f.element == "SegmentAssets"}):
        seg, unalloc = report.total("SegmentAssets", end), _nondim(inst, "UnAllocableAssets", None, end)
        net, assets = _nondim(inst, "NetSegmentAssets", None, end), _nondim(inst, "Assets", None, end)
        if None not in (seg, unalloc, net) and seg + unalloc != net:
            report.issues.append(("SEGMENT_ASSETS", {"end": str(end), "lhs": str(seg + unalloc), "rhs": str(net)}))
        if None not in (net, assets) and net != assets:
            report.issues.append(("SEGMENT_ASSETS_TO_BS", {"end": str(end), "net": str(net), "assets": str(assets)}))
