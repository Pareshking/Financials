"""Reg. 34(1) annual report XBRL (ICAI/MCA Ind AS taxonomy, `…/2017-03-31/ind-as`) -> canonical facts.

Evidence: docs/references.md X36, X37, X69-X76 (Batch 9, 13 filings). What differs from the Integrated Filing:
- no ISIN/Symbol: identity is the NSE file name's symbol plus the filed CIN [X70];
- periods are declared by `DateOfStart/EndOfReportingPeriod` per duration context (current and previous FY);
  instants exist for both year ends and the year before (opening balances) [X36];
- the fixed-asset schedule, borrowings, contingent liabilities, audit fees, R&D, royalty and geographic revenue
  are notes, mostly dimensional [X71-X75];
- lease liabilities exist only as labelled "Others" rows [X37, X72].

Point-in-time and cutoff (C9): only periods ending on or after MIN_PERIOD_END_DATE are emitted. A comparative
year inside a later filing is emitted as that filing's fact, so it becomes visible at that filing's broadcast
and supersedes earlier versions only from then (restatements are preserved, nothing is backdated). Earlier
periods are skipped silently and counted in meta["ignored_pre_cutoff_facts"].

Facts are the same canonical tags as INDAS_CORP (DURATION, period_months 12; INSTANT), so annual figures sit
in fact_observations beside quarterly ones and load_factbook picks the latest visible version per period.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from financials.parsers import ParseError
from financials.parsers.indas_corp import (
    DURATION_TAGS,
    INSTANT_TAGS,
    ROUNDING_UNITS,
    SCOPES,
    CanonicalFact,
    Issue,
    ParsedResults,
    _check,
    _check_eps,
    _check_identities,
    period_months,
)
from financials.parsers.xbrl import Instance, parse_instance
from financials.scope import MIN_PERIOD_END_DATE
from financials.timeutil import IST

PROFILE = "REG34_ANNUAL"
NS_FRAGMENT = "/2017-03-31/ind-as"
FILE_SYMBOL = re.compile(r"AR_XBRL_(?P<symbol>.+)_\d{14}\.xml$")  # NSE file name pattern [A8]

# Annual-only notes, non-dimensional [X73]. Absent = not disclosed (NULL), never 0.
ANNUAL_DURATION_TAGS: dict[str, tuple[str, str]] = {
    "PaymentsToAuditor": ("audit_fees", "INR"),
    "ExpenditureIncurredOnResearchAndDevelopment": ("rnd_expense", "INR"),
    "CostRoyalty": ("royalty_expense", "INR"),
    "IncomeTaxesPaidRefund": ("income_taxes_paid_total", "INR"),
    # A face-of-P&L element in the annual taxonomy (Reliance, ITC); the Integrated Filing only labels it [X40, X74].
    "ExciseDuty": ("excise_duty", "INR"),
    # Face-of-P&L cost lines that the Integrated Filing only labels [X50, X68]; Screener's Power & Fuel and
    # Selling & admin rows.
    "PowerAndFuel": ("power_and_fuel", "INR"),
    "CostFreight": ("freight", "INR"),
    "AdvertisingPromotionalExpenses": ("advertising_promotion", "INR"),
    # Investments bought/sold (CF sub-rows, 8/13 and 6/13 filings) [X74]
    "OtherCashPaymentsToAcquireEquityOrDebtInstrumentsOfOtherEntitiesClassifiedAsInvestingActivities": (
        "investments_purchased",
        "INR",
    ),
    "OtherCashReceiptsFromSalesOfEquityOrDebtInstrumentsOfOtherEntitiesClassifiedAsInvestingActivities": (
        "investments_sold",
        "INR",
    ),
}
ANNUAL_INSTANT_TAGS: dict[str, tuple[str, str]] = {
    "ContingentLiabilities": ("contingent_liabilities", "INR"),
    "ContingentLiabilitiesAndCommitments": ("contingent_liabilities_and_commitments", "INR"),
    "AdvanceReceivedFromCustomers": ("advance_from_customers", "INR"),
}

# Fixed-asset schedule [X71]. Top-level classes only; sub-members (FactoryBuilding ⊂ Buildings, MotorVehicles ⊂
# Vehicles, OtherPlantAndEquipment ⊂ PlantAndEquipment …) are never added. Values are summed over
# SubClassesOfPropertyPlantAndEquipmentAxis (owned / held under lease / given under operating lease) unless a
# class-only fact exists. "Other" = gross block − named classes, so the identity holds by construction; a
# negative remainder is an issue (double counting) and the class breakdown is dropped.
PPE_CLASSES = {
    "LandMember": "ppe_gross_land",
    "BuildingsMember": "ppe_gross_buildings",
    "PlantAndEquipmentMember": "ppe_gross_plant_equipment",
    "OfficeEquipmentMember": "ppe_gross_office_equipment",
    "ComputerEquipmentsMember": "ppe_gross_computers",
    "FurnitureAndFixturesMember": "ppe_gross_furniture",
    "VehiclesMember": "ppe_gross_vehicles",
}
PPE_AXIS, PPE_CLASS_AXIS, PPE_SUBCLASS_AXIS = (
    "CarryingAmountAccumulatedDepreciationAndGrossCarryingAmountAxis",
    "ClassesOfPropertyPlantAndEquipmentAxis",
    "SubClassesOfPropertyPlantAndEquipmentAxis",
)
INTANGIBLE_AXIS = "CarryingAmountAccumulatedAmortizationAndImpairmentAndGrossCarryingAmountAxis"
INTANGIBLE_CLASS_AXIS, INTANGIBLE_SUBCLASS_AXIS = (
    "ClassesOfOtherIntangibleAssetsAxis",
    "SubClassesOfOtherIntangibleAssetsAxis",
)
GEO_AXIS = "GeographicalAreasAxis"

# Label rules on the annual "Others" axes [X37, X72]: (rule, axis, label element, amount element, tag, pattern).
LEASE_LABEL = re.compile(r"^\s*lease\s+liab", re.I)
ANNUAL_LABEL_RULES = (
    ("LEASE_LIAB_NONCURRENT", "OtherNoncurrentFinancialLiabilitiesOthersAxis",
     "DescriptionOtherNoncurrentFinancialLiabilitiesOthers", "OtherNoncurrentFinancialLiabilitiesOthers",
     "lease_liabilities_noncurrent", LEASE_LABEL),
    ("LEASE_LIAB_CURRENT", "OtherCurrentFinancialLiabilitiesOthersAxis",
     "DescriptionOfOtherCurrentFinancialLiabilitiesOthers", "OtherCurrentFinancialLiabilitiesOthers",
     "lease_liabilities_current", LEASE_LABEL),
    ("RIGHT_OF_USE_ASSETS", "OtherNoncurrentAssetsOthersAxis", "DescriptionOfOtherNoncurrentAssetsOthers",
     "OtherNoncurrentAssetsOthers", "right_of_use_assets", re.compile(r"^\s*right[\s-]*of[\s-]*use", re.I)),
)  # fmt: skip

CRITICAL = ("revenue_from_operations", "total_income", "total_expenses", "pbt", "pat", "total_assets", "total_equity")


def is_reg34(inst: Instance) -> bool:
    return any(u.endswith(NS_FRAGMENT) for u in inst.namespaces.values()) and inst.entity_namespace is None


def symbol_from_file_name(name: str) -> str | None:
    m = FILE_SYMBOL.search(name)
    return m["symbol"] if m else None


def _local(x: str) -> str:
    return x.split(":")[-1]


def parse_reg34_annual(data: bytes, file_name: str | None = None) -> ParsedResults:
    inst = parse_instance(data)
    ns = next((u for u in inst.namespaces.values() if u.endswith(NS_FRAGMENT)), None)
    result = ParsedResults(profile=PROFILE, taxonomy_ns=ns)
    if ns is None:
        result.issues.append(Issue("PARSE", "UNKNOWN_TAXONOMY", {"namespaces": sorted(inst.namespaces.values())}))
        return result
    _meta(inst, result, file_name)
    if result.issues:
        return result
    _map(inst, result)
    _ppe_schedule(inst, result)
    _intangibles(inst, result)
    _geographic(inst, result)
    _label_rules(inst, result)
    _apply_contingent_placeholder_rule(result)
    if result.issues:
        return result
    _identities(result)
    return result


def _meta(inst: Instance, result: ParsedResults, file_name: str | None) -> None:
    def text(name: str) -> str | None:
        return inst.first_text(name)

    scope_text, rounding = (
        text("NatureOfReportStandaloneConsolidated"),
        text("LevelOfRoundingUsedInFinancialStatements"),
    )
    scope = SCOPES.get((scope_text or "").strip().lower())
    if scope is None:
        result.issues.append(
            Issue("PARSE", "MISSING_META" if not scope_text else "UNKNOWN_SCOPE", {"scope": scope_text})
        )
    if rounding not in ROUNDING_UNITS:
        result.issues.append(Issue("PARSE", "UNKNOWN_ROUNDING", {"value": rounding}))

    # Declared periods: one per duration context carrying DateOfStart/EndOfReportingPeriod [X36].
    declared: dict[str, dict[str, date]] = defaultdict(dict)
    for f in inst.facts:
        c = inst.contexts[f.context_id]
        if c.dimensions or c.instant is not None:
            continue
        if f.name in ("DateOfStartOfReportingPeriod", "DateOfEndOfReportingPeriod"):
            declared[f.context_id][f.name] = date.fromisoformat(f.value_text.strip())
    periods = set()
    for cid, d in declared.items():
        c = inst.contexts[cid]
        start, end = d.get("DateOfStartOfReportingPeriod"), d.get("DateOfEndOfReportingPeriod")
        if (start, end) != (c.start, c.end):  # never trust context dates blindly (invariant 6)
            result.issues.append(
                Issue(
                    "PERIOD",
                    "CONTEXT_CONFLICT",
                    {"context_id": cid, "context": [str(c.start), str(c.end)], "declared": [str(start), str(end)]},
                )
            )
            continue
        months = period_months(start, end)
        if months is None or not 1 <= months <= 18:
            result.issues.append(Issue("PERIOD", "IRREGULAR_PERIOD", {"dates": [str(start), str(end)]}))
            continue
        periods.add((start, end))
    if not periods:
        result.issues.append(Issue("PERIOD", "NO_DECLARED_PERIOD", {}))
        return
    fy_start, fy_end = max(periods, key=lambda p: p[1])
    in_scope = sorted(p for p in periods if p[1] >= MIN_PERIOD_END_DATE)
    instants = sorted({p[1] for p in in_scope})
    qualified = (
        text("WhetherAuditorsReportHasBeenQualifiedOrHasAnyReservationsOrContainsAdverseRemarks") or ""
    ).lower()
    result.meta.update(
        scope=scope,
        level_of_rounding=rounding,
        fy_start=fy_start,
        fy_end=fy_end,
        period_end=fy_end,
        quarter_period=(fy_start, fy_end),  # used by the shared identity checks
        ytd_period=(fy_start, fy_end),
        declared_periods=sorted(periods),
        in_scope_periods=in_scope,
        in_scope_instants=instants,
        reporting_quarter=None,
        audited=True,  # Reg. 34 statements are audited
        audited_ytd=True,
        auditor_qualified={"true": True, "false": False}.get(qualified),
        board_meeting_end_ts=None,
        stated_isin=None,
        stated_symbol=symbol_from_file_name(file_name) if file_name else None,
        stated_scrip_code=None,
        stated_cin=text("CorporateIdentityNumber"),
        company_name=text("NameOfCompany"),
        interest_paid_cfo_class=None,
        interest_recd_cfo_class=None,
        ignored_pre_cutoff_facts=0,
        warnings=[],
        rules_applied=[],
    )


def _map(inst: Instance, result: ParsedResults) -> None:
    periods = set(result.meta["in_scope_periods"])
    all_periods = set(result.meta["declared_periods"])
    instants = set(result.meta["in_scope_instants"])
    durations = {**DURATION_TAGS, **ANNUAL_DURATION_TAGS}
    instant_tags = {**INSTANT_TAGS, **ANNUAL_INSTANT_TAGS}
    seen: dict[tuple, CanonicalFact] = {}
    for f in inst.facts:
        if not f.is_numeric:
            continue
        c = inst.contexts[f.context_id]
        if c.dimensions:
            continue
        if c.instant is not None:
            mapping = instant_tags.get(f.name)
            if mapping is None:
                continue
            if c.instant not in instants:
                result.meta["ignored_pre_cutoff_facts"] += 1
                continue
            start = end = c.instant
            ptype, months = "INSTANT", None
        else:
            mapping = durations.get(f.name)
            if mapping is None:
                continue
            p = (c.start, c.end)
            if p not in all_periods:
                result.issues.append(
                    Issue(
                        "PERIOD",
                        "CONTEXT_CONFLICT",
                        {"context_id": c.id, "element": f.name, "dates": [str(c.start), str(c.end)]},
                    )
                )
                continue
            if p not in periods:
                result.meta["ignored_pre_cutoff_facts"] += 1
                continue
            start, end = p
            ptype, months = "DURATION", period_months(start, end)
        tag, unit = mapping
        _add(result, seen, CanonicalFact(tag, ptype, start, end, months, unit, f.decimal(), f.name))
    for t in CRITICAL:
        p = result.meta["fy_end"] if t in ("total_assets", "total_equity") else None
        has = any(
            fct.canonical_tag == t and (fct.period_end == result.meta["fy_end"] if p else True) for fct in result.facts
        )
        if not has:
            result.issues.append(Issue("PARSE", "MISSING_CRITICAL", {"tag": t}))


def _add(result: ParsedResults, seen: dict, cf: CanonicalFact) -> None:
    key = (cf.canonical_tag, cf.period_start, cf.period_end)
    if key in seen:
        if seen[key].value != cf.value:
            result.issues.append(
                Issue(
                    "PARSE",
                    "CONFLICTING_DUPLICATE",
                    {
                        "tag": cf.canonical_tag,
                        "end": str(cf.period_end),
                        "values": [str(seen[key].value), str(cf.value)],
                    },
                )
            )
        return
    seen[key] = cf
    result.facts.append(cf)


def _dims(inst: Instance, f) -> dict[str, str]:
    return {_local(a): _local(m) for a, m in inst.contexts[f.context_id].dimensions}


def _ppe_schedule(inst: Instance, result: ParsedResults) -> None:
    """Gross block by top-level class, total gross block and accumulated depreciation, per in-scope year end."""
    instants = set(result.meta["in_scope_instants"])
    total: dict[tuple[date, str], Decimal] = {}  # (end, Gross|Accum) -> value (no class)
    class_only: dict[tuple[date, str], Decimal] = {}
    by_sub: dict[tuple[date, str], Decimal] = defaultdict(Decimal)
    for f in inst.facts:
        if f.name != "PropertyPlantAndEquipment" or not f.is_numeric:
            continue
        c = inst.contexts[f.context_id]
        if c.instant not in instants:
            continue
        d = _dims(inst, f)
        kind = d.get(PPE_AXIS)
        if set(d) - {PPE_AXIS, PPE_CLASS_AXIS, PPE_SUBCLASS_AXIS}:
            continue
        if PPE_CLASS_AXIS not in d:
            if kind and PPE_SUBCLASS_AXIS not in d:
                total[(c.instant, kind)] = f.decimal()
            continue
        if kind != "GrossCarryingAmountMember" or d[PPE_CLASS_AXIS] not in PPE_CLASSES:
            continue
        if PPE_SUBCLASS_AXIS in d:
            by_sub[(c.instant, d[PPE_CLASS_AXIS])] += f.decimal()
        else:
            class_only[(c.instant, d[PPE_CLASS_AXIS])] = f.decimal()
    for end in sorted(instants):
        gross = total.get((end, "GrossCarryingAmountMember"))
        accum = total.get((end, "AccumulatedDepreciationAndImpairmentMember"))
        if gross is None:
            continue
        result.facts.append(CanonicalFact("ppe_gross_block", "INSTANT", end, end, None, "INR", gross, "PPE_SCHEDULE"))
        if accum is not None:
            result.facts.append(
                CanonicalFact("ppe_accumulated_depreciation", "INSTANT", end, end, None, "INR", accum, "PPE_SCHEDULE")
            )
        classes = {}
        for member, tag in PPE_CLASSES.items():
            v = class_only.get((end, member), by_sub.get((end, member)))
            if v is not None:
                classes[tag] = v
        other = gross - sum(classes.values(), Decimal(0))
        if other < 0:
            result.meta["warnings"].append(
                {"code": "PPE_CLASSES_EXCEED_GROSS_BLOCK", "end": str(end), "excess": str(-other)}
            )
            continue
        for tag, v in {**classes, "ppe_gross_other": other}.items():
            result.facts.append(CanonicalFact(tag, "INSTANT", end, end, None, "INR", v, "PPE_SCHEDULE"))


def _intangibles(inst: Instance, result: ParsedResults) -> None:
    """Gross carrying amount and accumulated amortisation of other intangibles (no class axis)."""
    instants = set(result.meta["in_scope_instants"])
    tags = {
        "GrossCarryingAmountMember": "intangibles_gross",
        "AccumulatedAmortizationAndImpairmentMember": "intangibles_accumulated_amortisation",
    }
    for f in inst.facts:
        if f.name != "OtherIntangibleAssets" or not f.is_numeric:
            continue
        c = inst.contexts[f.context_id]
        d = _dims(inst, f)
        if c.instant not in instants or set(d) != {INTANGIBLE_AXIS} or d[INTANGIBLE_AXIS] not in tags:
            continue
        result.facts.append(
            CanonicalFact(
                tags[d[INTANGIBLE_AXIS]],
                "INSTANT",
                c.instant,
                c.instant,
                None,
                "INR",
                f.decimal(),
                "INTANGIBLES_SCHEDULE",
            )
        )


def _geographic(inst: Instance, result: ParsedResults) -> None:
    """Revenue from external customers: country of domicile vs foreign countries (Ind AS 108.33) [X75]."""
    periods = set(result.meta["in_scope_periods"])
    tags = {"CountryOfDomicileMember": "revenue_domestic", "ForeignCountriesMember": "revenue_foreign"}
    for f in inst.facts:
        if f.name != "RevenueFromExternalCustomers" or not f.is_numeric:
            continue
        c = inst.contexts[f.context_id]
        d = _dims(inst, f)
        if set(d) != {GEO_AXIS} or d[GEO_AXIS] not in tags or (c.start, c.end) not in periods:
            continue
        result.facts.append(
            CanonicalFact(
                tags[d[GEO_AXIS]],
                "DURATION",
                c.start,
                c.end,
                period_months(c.start, c.end),
                "INR",
                f.decimal(),
                "GEOGRAPHIC",
            )
        )


def _label_rules(inst: Instance, result: ParsedResults) -> None:
    instants = set(result.meta["in_scope_instants"])
    for rule, axis, label_el, amount_el, tag, pattern in ANNUAL_LABEL_RULES:
        members = set()
        for f in inst.facts:
            if f.name == label_el and pattern.match(f.value_text):
                d = _dims(inst, f)
                if axis in d:
                    members.add(d[axis])
        if not members:
            continue
        totals: dict[date, Decimal] = defaultdict(Decimal)
        for f in inst.facts:
            if f.name != amount_el or not f.is_numeric:
                continue
            c = inst.contexts[f.context_id]
            d = _dims(inst, f)
            if set(d) == {axis} and d[axis] in members and c.instant in instants:
                totals[c.instant] += f.decimal()
        for end, v in sorted(totals.items()):
            result.facts.append(CanonicalFact(tag, "INSTANT", end, end, None, "INR", v, f"LABEL:{rule}"))
        result.meta["rules_applied"].append(rule)


CONTINGENT_RULE = "CONTINGENT_ZERO_PLACEHOLDER"


def _apply_contingent_placeholder_rule(result: ParsedResults) -> None:
    """Rule CONTINGENT_ZERO_PLACEHOLDER [X73]: Maruti Suzuki and Info Edge FY26 file ContingentLiabilities = 0 and
    ContingentLiabilitiesAndCommitments = 0 for both years while their notes disclose claims. Both zero at the
    same date = not disclosed: the facts are withheld (NULL), never read as "no contingent liabilities"."""
    tags = ("contingent_liabilities", "contingent_liabilities_and_commitments")
    for end in result.meta["in_scope_instants"]:
        vals = [result.value(t, end, end) for t in tags]
        if vals == [Decimal(0), Decimal(0)]:
            result.facts = [f for f in result.facts if not (f.canonical_tag in tags and f.period_end == end)]
            if CONTINGENT_RULE not in result.meta["rules_applied"]:
                result.meta["rules_applied"].append(CONTINGENT_RULE)


def _identities(result: ParsedResults) -> None:
    """The INDAS_CORP P&L, cash-flow and balance-sheet identities for every in-scope year, plus the PPE schedule.

    Tolerances come from LevelOfRounding (invariant 7): "to the rupee" is only possible when the filing is in
    rupees; a filing rounded to crores ties to within half a crore per term."""
    original = (result.meta["quarter_period"], result.meta["ytd_period"], result.meta["period_end"])
    try:
        for p in result.meta["in_scope_periods"]:
            result.meta["quarter_period"] = result.meta["ytd_period"] = p
            result.meta["period_end"] = p[1]
            _check_identities(result)
            end = p[1]
            gross, accum, net = (
                result.value(t, end, end) for t in ("ppe_gross_block", "ppe_accumulated_depreciation", "ppe_net")
            )
            if None not in (gross, accum, net):
                _check(result, "PPE_GROSS_MINUS_ACCUMULATED", gross - accum, net, 3, (end,))
    finally:
        result.meta["quarter_period"], result.meta["ytd_period"], result.meta["period_end"] = original
    _check_eps(result)


@dataclass(frozen=True)
class AnnualListingEntry:
    symbol: str
    from_year: int
    to_year: int
    submission_type: str  # Standalone | Consolidated
    broadcast_ts_ist: datetime
    xbrl_url: str


def parse_annual_listing(data: bytes) -> list[AnnualListingEntry]:
    """NSE `annual-reports-xbrl` JSON [A8, X69]: one row per Reg. 34 XBRL with its broadcast time (IST)."""
    try:
        rows = json.loads(data.decode("utf-8"))["data"]
        out = []
        for r in rows:
            name = r["fileName"].rsplit("/", 1)[-1]
            symbol = symbol_from_file_name(name)
            if symbol is None:
                raise ValueError(f"file name {name!r} does not match AR_XBRL_<SYM>_<ts>.xml")
            out.append(
                AnnualListingEntry(
                    symbol=symbol,
                    from_year=int(r["fromYr"]),
                    to_year=int(r["toYr"]),
                    submission_type=r["submission_type"],
                    broadcast_ts_ist=datetime.strptime(r["broadcast_dttm"], "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST),
                    xbrl_url=r["fileName"],
                )
            )
        return out
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ParseError(f"annual reports listing: {exc}") from exc
