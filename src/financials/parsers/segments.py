"""Ind AS 108 segment and geography facts from results and Reg. 34 annual XBRL [X49, X95-X97]. Pure: bytes -> rows
+ findings.

Business segments
- Integrated Filing (quarterly results, every profile that files them): one `ReportableSegment*Axis` per element
  (`ReportableSegmentsAxis` SegmentRevenue, `ReportableSegmentsFinanceCostsAxis` SegmentProfitLossBeforeTaxAndFinance
  Costs = segment result, `ReportableSegmentAssetsAxis`, `ReportableSegmentLiabilitiesAxis`), members
  `ReportableSegmentsNMember`, one label per (axis, member) in `DescriptionOfReportableSegment(s)`. Unallocable amounts
  and the filed totals are non-dimensional elements (fact_observations line items), never members.
- Reg. 34 annual (ICAI Ind AS taxonomy): one `EntitySReportableSegmentsAxis` for every element, labels in
  `NatureOfReportableSegment`; besides `ReportableSegmentsNMember` the filer may use `UnallocatedAmountsMember`,
  `EliminationOfIntersegmentAmountsMember` and `MaterialReconcilingItemsMember` (= unallocated + eliminations).
Geography (Reg. 34 annual only; the Integrated Filing has no geography axis): `GeographicalAreasAxis` with
`CountryOfDomicileMember`, `ForeignCountriesMember` (= the sum of the `ForeignCountryNMember` children) and labels in
`CountryOfDomicileOrForeignCountry`.

Members, labels, axes and elements are kept exactly as filed; `member_role` is derived from the member name only
(never from the free-text label) and `canonical_metric` from the element only. Elements no committed fixture shows are
not mapped: they stay in raw_xbrl_facts and are listed in `unmapped`.

Segment totals are NOT substitutes for P&L lines (Cummins' SegmentRevenueFromOperations differs from
RevenueFromOperations; its segment PBT includes associates). Nothing here feeds fact_observations or a ratio.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from financials.money import ROUNDING_UNITS
from financials.parsers import ParseError
from financials.parsers.indas_corp import period_months
from financials.parsers.xbrl import Instance, parse_instance

SEGMENT_ELEMENTS = (
    "SegmentRevenue",
    "SegmentProfitLossBeforeTaxAndFinanceCosts",
    "SegmentAssets",
    "SegmentLiabilities",
)

# element -> canonical_metric, per axis family. Only elements seen in a committed fixture (X49, X95-X97).
QUARTERLY_METRICS = {
    "SegmentRevenue": "REVENUE",
    "SegmentProfitLossBeforeTaxAndFinanceCosts": "RESULT",
    "SegmentAssets": "ASSETS",
    "SegmentLiabilities": "LIABILITIES",
}
ANNUAL_METRICS = {
    # total segment revenue, external + inter-segment (Eternal: = RevenuePrimary + inter-segment for every member)
    "RevenuesFromExternalCustomersAndTransactionsWithOtherReportableSegmentsOfSameEnterprise"
    "ReportableSegment": "REVENUE",
    "RevenuePrimaryReportableSegment": "EXTERNAL_REVENUE",
    "RevenuesFromTransactionsWithOtherOperatingSegmentsOfTheSameEntity": "INTERSEGMENT_REVENUE",
    "ProfitLossReportableSegment": "RESULT",
    "ProfitLossBeforeTaxReportableSegment": "PROFIT_BEFORE_TAX",
    "AssetsReportableSegment": "ASSETS",
    "LiabilitiesReportableSegment": "LIABILITIES",
    "DepreciationAndAmortisationExpenseReportableSegment": "DEPRECIATION_AMORTISATION",
    "InterestExpenseReportableSegment": "INTEREST_EXPENSE",
    "InterestRevenueExpenseReportableSegment": "NET_INTEREST",
    "OtherMaterialNoncashItemsReportableSegment": "OTHER_NONCASH_ITEMS",
}
GEOGRAPHY_METRICS = {
    "RevenueFromExternalCustomers": "EXTERNAL_REVENUE",
    "NoncurrentAssetsOtherThanFinancialInstrumentsDeferredTaxAssetsPostemploymentBenefitAssetsAndRightsArisingUnder"
    "InsuranceContracts": "NON_CURRENT_ASSETS",
}
SEGMENT_METRICS = tuple(dict.fromkeys([*QUARTERLY_METRICS.values(), *ANNUAL_METRICS.values(),
                                       *GEOGRAPHY_METRICS.values()]))  # fmt: skip

BUSINESS_LABELS = ("DescriptionOfReportableSegment", "DescriptionOfReportableSegments", "NatureOfReportableSegment")
GEOGRAPHY_LABELS = ("CountryOfDomicileOrForeignCountry",)
ANNUAL_BUSINESS_AXIS = "EntitySReportableSegmentsAxis"
GEOGRAPHY_AXIS = "GeographicalAreasAxis"

BUSINESS_ROLES = {
    "UnallocatedAmountsMember": "UNALLOCATED",
    "EliminationOfIntersegmentAmountsMember": "ELIMINATION",
    "MaterialReconcilingItemsMember": "RECONCILING",
}
GEOGRAPHY_ROLES = {"CountryOfDomicileMember": "DOMICILE", "ForeignCountriesMember": "FOREIGN_TOTAL"}
_FOREIGN_COUNTRY = re.compile(r"^ForeignCountry\d+Member$")


def _local(qname: str) -> str:
    return qname.split(":")[-1]


def axis_kind(axis: str) -> tuple[str, dict[str, str]] | None:
    """(BUSINESS | GEOGRAPHY, element -> metric map) for a segment axis, else None."""
    a = _local(axis)
    if a == GEOGRAPHY_AXIS:
        return "GEOGRAPHY", GEOGRAPHY_METRICS
    if a == ANNUAL_BUSINESS_AXIS:
        return "BUSINESS", ANNUAL_METRICS
    if a.startswith("ReportableSegment"):
        return "BUSINESS", QUARTERLY_METRICS
    return None


def member_role(kind: str, member: str) -> str:
    m = _local(member)
    if kind == "GEOGRAPHY":
        return GEOGRAPHY_ROLES.get(m) or ("FOREIGN" if _FOREIGN_COUNTRY.match(m) else "AREA")
    return BUSINESS_ROLES.get(m, "SEGMENT")


@dataclass(frozen=True)
class SegmentFact:
    member: str
    label: str | None
    element: str
    period_start: date | None  # None for an instant (assets / liabilities)
    period_end: date
    value: Decimal
    axis: str = ""
    axis_kind: str = "BUSINESS"
    member_role: str = "SEGMENT"
    canonical_metric: str = ""

    @property
    def period_type(self) -> str:
        return "INSTANT" if self.period_start is None else "DURATION"

    @property
    def period_months(self) -> int | None:
        return None if self.period_start is None else period_months(self.period_start, self.period_end)


@dataclass
class SegmentReport:
    facts: list[SegmentFact]
    issues: list[tuple[str, dict]]  # non-blocking findings (sum checks, context conflicts)
    warnings: list[dict] = field(default_factory=list)
    unmapped: list[str] = field(default_factory=list)  # elements on a segment axis with no metric (raw only)
    ignored: int = 0  # outside the validated windows: pre-cutoff, opening balances

    def total(self, element: str, end: date, start: date | None = None) -> Decimal | None:
        vals = [f.value for f in self.facts if f.element == element and f.period_end == end and f.period_start == start]
        return sum(vals, Decimal(0)) if vals else None

    @property
    def segments(self) -> list[str]:
        return sorted({f.label or f.member for f in self.facts if f.axis_kind == "BUSINESS"})


@dataclass(frozen=True)
class Windows:
    """The periods the filing's own parser validated: rows outside them are never emitted."""

    durations: frozenset[tuple[date, date]]
    instants: frozenset[date]
    declared: frozenset[tuple[date, date]] = frozenset()  # declared but pre-cutoff (C9): skipped silently
    # Named rule STALE_CONTEXT_DATES [X87], as the filing's own parser applied it: stale period -> declared period
    redate: tuple[tuple[tuple[date, date], tuple[date, date]], ...] = ()

    @classmethod
    def from_meta(cls, meta: dict) -> Windows | None:
        if "in_scope_periods" in meta:  # Reg. 34 annual
            return cls(frozenset(meta["in_scope_periods"]), frozenset(meta["in_scope_instants"]),
                       frozenset(meta.get("declared_periods") or ()))  # fmt: skip
        q, ytd, end = meta.get("quarter_period"), meta.get("ytd_period"), meta.get("period_end")
        if q is None or end is None:
            return None
        declared = {"One": q, "Four": ytd}
        redate = []
        for rule in meta.get("rules_applied") or ():
            if rule.get("rule") == "STALE_CONTEXT_DATES":
                for family, (a, b) in sorted(rule["periods"].items()):
                    if declared.get(family):
                        redate.append(((date.fromisoformat(a), date.fromisoformat(b)), declared[family]))
        return cls(frozenset(p for p in (q, ytd) if p), frozenset({end}), redate=tuple(redate))

    def resolve(self, start: date | None, end: date) -> tuple[date | None, date]:
        """Re-date a stale context [X87]: stale durations, and instants on the stale end, move to the declared ones."""
        if not self.redate:
            return start, end
        if start is None:
            return (None, max(self.instants)) if end == self.redate[0][0][1] else (None, end)
        return dict(self.redate).get((start, end), (start, end))


def parse_segments(
    data: bytes | Instance, windows: Windows | None = None, *, level_of_rounding: str | None = None
) -> SegmentReport:
    """Every mapped segment / geography fact on a single-dimension context. With `windows`, only facts in the
    filing's validated periods are kept (a duration outside the declared periods is a finding; a declared pre-cutoff
    period is skipped). `level_of_rounding` sets the sum-check tolerance (exact when None)."""
    inst = data if isinstance(data, Instance) else parse_instance(data)
    report = SegmentReport([], [])
    labels: dict[tuple[str, str], tuple[date, str]] = {}
    for f in inst.facts:
        c = inst.contexts[f.context_id]
        if len(c.dimensions) != 1 or f.is_numeric or not f.value_text.strip():
            continue
        axis, member = c.dimensions[0]
        k = axis_kind(axis)
        if k is None or f.name not in (BUSINESS_LABELS if k[0] == "BUSINESS" else GEOGRAPHY_LABELS):
            continue
        # One label per (axis, member): the one filed for the latest period (the current year's presentation).
        when = c.end or c.instant or date.min
        prev = labels.get((axis, member))
        if prev is None or when > prev[0]:
            if prev is not None and prev[1] != f.value_text.strip():
                report.warnings.append({"code": "SEGMENT_LABEL_CHANGED", "member": member,
                                        "labels": [prev[1], f.value_text.strip()]})  # fmt: skip
            labels[(axis, member)] = (when, f.value_text.strip())
    seen: dict[tuple, SegmentFact] = {}
    conflicts: set[tuple] = set()
    unmapped: set[str] = set()
    outside: list[dict] = []
    for f in inst.facts:
        c = inst.contexts[f.context_id]
        if len(c.dimensions) != 1 or not f.is_numeric:
            continue
        axis, member = c.dimensions[0]
        k = axis_kind(axis)
        if k is None:
            continue
        kind, metrics = k
        metric = metrics.get(f.name)
        if metric is None:
            if inst.unit_kind(f.unit_ref) == "INR":
                unmapped.add(f.name)
            continue
        if inst.unit_kind(f.unit_ref) != "INR":
            report.warnings.append({"code": "SEGMENT_NON_INR_UNIT", "element": f.name, "unit": f.unit_ref})
            continue
        start, end = (None, c.instant) if c.instant is not None else (c.start, c.end)
        if windows is not None:
            start, end = windows.resolve(start, end)
            if start is None and end not in windows.instants:
                if end < max(windows.instants, default=end):
                    report.ignored += 1  # opening balance or pre-cutoff year end
                else:
                    outside.append({"element": f.name, "context_id": c.id, "instant": str(end)})
                continue
            if start is not None and (start, end) not in windows.durations:
                if (start, end) in windows.declared:
                    report.ignored += 1
                else:
                    outside.append({"element": f.name, "context_id": c.id, "dates": [str(start), str(end)]})
                continue
        try:
            value = f.decimal()
        except ParseError:
            report.warnings.append({"code": "SEGMENT_NOT_NUMERIC", "element": f.name, "context_id": c.id})
            continue
        if value != value.quantize(Decimal("0.01")):
            report.warnings.append({"code": "SEGMENT_SUBPAISE", "element": f.name, "value": str(value)})
            continue
        if start is not None:
            months = period_months(start, end)
            if months is None or not 1 <= months <= 18:
                outside.append({"element": f.name, "context_id": c.id, "dates": [str(start), str(end)]})
                continue
        label = labels.get((axis, member))
        sf = SegmentFact(member, label[1] if label else None, f.name, start, end, value, axis, kind,
                         member_role(kind, member), metric)  # fmt: skip
        key = (axis, member, f.name, start, end)
        if key in seen:
            if seen[key].value != value:
                conflicts.add(key)
            continue
        seen[key] = sf
    for key in sorted(conflicts, key=str):
        report.warnings.append({"code": "SEGMENT_DUPLICATE_CONFLICT", "member": key[1], "element": key[2],
                                "period": [str(key[3]), str(key[4])]})  # fmt: skip
    report.facts = [sf for key, sf in seen.items() if key not in conflicts]
    report.unmapped = sorted(unmapped)
    if outside:
        report.issues.append(("SEGMENT_CONTEXT_OUTSIDE_DECLARED", {"count": len(outside), "facts": outside[:10]}))
    _check(inst, report, level_of_rounding)
    return report


def _nondim_index(inst: Instance) -> dict[tuple, Decimal]:
    """{(element, start | None, end): value} for every non-dimensional numeric fact (first one wins)."""
    out: dict[tuple, Decimal] = {}
    for f in inst.facts:
        c = inst.contexts[f.context_id]
        if c.dimensions or not f.is_numeric:
            continue
        key = (f.name, None, c.instant) if c.instant is not None else (f.name, c.start, c.end)
        if key not in out:
            try:
                out[key] = f.decimal()
            except ParseError:
                continue
    return out


def _tolerance(level_of_rounding: str | None, n_terms: int) -> Decimal:
    if level_of_rounding not in ROUNDING_UNITS:
        return Decimal(0)
    return ROUNDING_UNITS[level_of_rounding] * Decimal("0.5") * n_terms


def _check(inst: Instance, report: SegmentReport, level_of_rounding: str | None) -> None:
    """Non-blocking checks against what the filing itself states [X49, X96]:
    - SEGMENT_SUM: the segment members of an element sum to its filed non-dimensional total (when the filing
      separates unallocated / elimination members, the sum with them is accepted too);
    - SEGMENT_RECONCILING: MaterialReconcilingItemsMember = unallocated + eliminations (Reg. 34);
    - GEOGRAPHY_FOREIGN_SUM: ForeignCountriesMember = the sum of the ForeignCountryN members (Reg. 34);
    - SEGMENT_ASSETS: SegmentAssets + UnAllocableAssets = NetSegmentAssets (NetSegmentAssets = Assets is only a
      warning)."""
    nd = _nondim_index(inst)
    groups: dict[tuple, list[SegmentFact]] = {}
    for f in report.facts:
        groups.setdefault((f.axis, f.element, f.period_start, f.period_end), []).append(f)

    def total(fs, roles):
        vals = [f.value for f in fs if f.member_role in roles]
        return (sum(vals, Decimal(0)), len(vals)) if vals else (None, 0)

    for (_axis, element, start, end), fs in sorted(groups.items(), key=str):
        period = [str(start), str(end)] if start else [str(end)]
        if fs[0].axis_kind == "BUSINESS":
            filed = nd.get((element, start, end))
            seg, n = total(fs, {"SEGMENT"})
            if filed is not None and seg is not None and abs(seg - filed) > _tolerance(level_of_rounding, n + 1):
                with_rec, m = total(fs, {"SEGMENT", "UNALLOCATED", "ELIMINATION"})
                if m == n or abs(with_rec - filed) > _tolerance(level_of_rounding, m + 1):
                    report.issues.append(("SEGMENT_SUM", {"element": element, "period": period, "sum": str(seg),
                                                          "filed": str(filed)}))  # fmt: skip
            rec, _ = total(fs, {"RECONCILING"})
            parts, k = total(fs, {"UNALLOCATED", "ELIMINATION"})
            if rec is not None and parts is not None and abs(rec - parts) > _tolerance(level_of_rounding, k + 1):
                details = {"element": element, "period": period, "reconciling": str(rec), "parts": str(parts)}
                report.issues.append(("SEGMENT_RECONCILING", details))
        else:
            parent, _ = total(fs, {"FOREIGN_TOTAL"})
            kids, k = total(fs, {"FOREIGN"})
            if parent is not None and kids is not None and abs(parent - kids) > _tolerance(level_of_rounding, k + 1):
                report.issues.append(("GEOGRAPHY_FOREIGN_SUM", {"element": element, "period": period,
                                                                "foreign": str(parent), "sum": str(kids)}))  # fmt: skip
    for end in sorted({f.period_end for f in report.facts if f.element == "SegmentAssets"}):
        seg, unalloc = report.total("SegmentAssets", end), nd.get(("UnAllocableAssets", None, end))
        net, assets = nd.get(("NetSegmentAssets", None, end)), nd.get(("Assets", None, end))
        if None not in (seg, unalloc, net) and seg + unalloc != net:
            report.issues.append(("SEGMENT_ASSETS", {"end": str(end), "lhs": str(seg + unalloc), "rhs": str(net)}))
        if None not in (net, assets) and net != assets:
            # A warning, not a finding: 388 of 3,352 vaulted quarterly filings with segments (2026-11-14) leave
            # NetSegmentAssets 0 or exclude tax / treasury assets, so it is not an identity the filer promises [X95].
            report.warnings.append({"code": "SEGMENT_ASSETS_TO_BS", "end": str(end), "net": str(net),
                                    "assets": str(assets)})  # fmt: skip
