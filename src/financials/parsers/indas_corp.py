"""INDAS_CORP quarterly results parser (SEBI Integrated Filing, Ind AS Division II).

Rules implemented (docs/architecture.md §6-7; evidence in docs/references.md):
- route by `in-capmkt-ent` namespace [X1]; other profiles are reported, not parsed
- values are absolute rupees [X4]; tolerances from LevelOfRounding, never `decimals` [X5]
- scope is a per-filing fact [X6]
- context dates must agree with the declared reporting period of the same context
  family ("One…", "Four…") [X26]; a conflict is an issue, never silently fixed
- only non-dimensional contexts are mapped; dimensional facts stay raw-only
- P&L, expense and balance-sheet identities are checked [X9-X12]
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, time
from decimal import Decimal
from typing import Any

from financials.money import ROUNDING_UNITS, identity_tolerance
from financials.parsers import ParseError
from financials.parsers.xbrl import Instance, parse_instance
from financials.timeutil import ist_to_utc

PROFILE_BY_NAMESPACE = (
    ("/IntegratedFinance_IndAS/", "INDAS_CORP"),
    ("/IntegratedFinance_NBFC/", "INDAS_NBFC"),
    ("/IntegratedFinance_Banking/", "IGAAP_BANK"),
    ("/GeneralInsurance/", "IRDAI_GENERAL"),
)

# Element → canonical tag. Only elements seen in a committed fixture are mapped.
DURATION_TAGS: dict[str, tuple[str, str]] = {
    "RevenueFromOperations": ("revenue_from_operations", "INR"),
    "OtherIncome": ("other_income", "INR"),
    "Income": ("total_income", "INR"),
    "CostOfMaterialsConsumed": ("cost_of_materials_consumed", "INR"),
    "PurchasesOfStockInTrade": ("purchases_of_stock_in_trade", "INR"),
    "ChangesInInventoriesOfFinishedGoodsWorkInProgressAndStockInTrade": ("changes_in_inventories", "INR"),
    "EmployeeBenefitExpense": ("employee_benefit_expense", "INR"),
    "FinanceCosts": ("finance_costs", "INR"),
    "DepreciationDepletionAndAmortisationExpense": ("depreciation_amortisation", "INR"),
    "OtherExpenses": ("other_expenses", "INR"),
    "Expenses": ("total_expenses", "INR"),
    "ProfitBeforeExceptionalItemsAndTax": ("profit_before_exceptional_and_tax", "INR"),
    "ExceptionalItemsBeforeTax": ("exceptional_items", "INR"),
    "ProfitBeforeTax": ("pbt", "INR"),
    "CurrentTax": ("current_tax", "INR"),
    "DeferredTax": ("deferred_tax", "INR"),
    "TaxExpense": ("tax_expense", "INR"),
    "ProfitLossForPeriodFromContinuingOperations": ("pat_continuing", "INR"),
    "ProfitLossFromDiscontinuedOperationsBeforeTax": ("discontinued_pbt", "INR"),
    "ProfitLossFromDiscontinuedOperationsAfterTax": ("pat_discontinued", "INR"),
    "ShareOfProfitLossOfAssociatesAndJointVenturesAccountedForUsingEquityMethod": (
        "share_of_associates_jv",
        "INR",
    ),
    "ProfitLossForPeriod": ("pat", "INR"),
    "OtherComprehensiveIncomeNetOfTaxes": ("oci_net", "INR"),
    "ComprehensiveIncomeForThePeriod": ("total_comprehensive_income", "INR"),
    "PaidUpValueOfEquityShareCapital": ("paid_up_equity_capital", "INR"),
    "FaceValueOfEquityShareCapital": ("face_value_per_share", "INR_PER_SHARE"),
    "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations": ("eps_basic", "INR_PER_SHARE"),
    "DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations": ("eps_diluted", "INR_PER_SHARE"),
    # Cash flow (H1/FY, YTD context only [X13]); outflow lines are positive magnitudes [X15].
    "CashFlowsFromUsedInOperations": ("cash_generated_from_operations", "INR"),
    "IncomeTaxesPaidRefundClassifiedAsOperatingActivities": ("income_taxes_paid", "INR"),
    "CashFlowsFromUsedInOperatingActivities": ("cfo", "INR"),
    "CashFlowsFromUsedInInvestingActivities": ("cfi", "INR"),
    "CashFlowsFromUsedInFinancingActivities": ("cff", "INR"),
    "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities": ("capex_ppe", "INR"),
    "PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities": ("capex_intangibles", "INR"),
    "ProceedsFromSalesOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities": ("ppe_disposals", "INR"),
    "InterestPaidClassifiedAsOperatingActivities": ("interest_paid_operating", "INR"),
    "InterestPaidClassifiedAsFinancingActivities": ("interest_paid_financing", "INR"),
    "InterestReceivedClassifiedAsOperatingActivities": ("interest_received_operating", "INR"),
    "InterestReceivedClassifiedAsInvestingActivities": ("interest_received_investing", "INR"),
    "DividendsPaidClassifiedAsFinancingActivities": ("dividends_paid", "INR"),
    "AdjustmentsForSharebasedPayments": ("share_based_payments_addback", "INR"),
    "AmountOfRelatedPartyTransactionDuringTheReportingPeriod": ("rpt_total_amount", "INR"),
}

INSTANT_TAGS: dict[str, tuple[str, str]] = {
    "PropertyPlantAndEquipment": ("ppe_net", "INR"),
    "CapitalWorkInProgress": ("cwip", "INR"),
    "Goodwill": ("goodwill", "INR"),
    "OtherIntangibleAssets": ("other_intangibles", "INR"),
    "NoncurrentInvestments": ("noncurrent_investments", "INR"),
    "NoncurrentAssets": ("noncurrent_assets", "INR"),
    "Inventories": ("inventories", "INR"),
    "CurrentInvestments": ("current_investments", "INR"),
    "TradeReceivablesCurrent": ("trade_receivables_current", "INR"),
    "TradeReceivablesNoncurrent": ("trade_receivables_noncurrent", "INR"),
    "CashAndCashEquivalents": ("cash_and_equivalents", "INR"),
    "BankBalanceOtherThanCashAndCashEquivalents": ("bank_balances_other", "INR"),
    "CurrentAssets": ("current_assets", "INR"),
    "Assets": ("total_assets", "INR"),
    "EquityShareCapital": ("equity_share_capital", "INR"),
    "OtherEquity": ("other_equity", "INR"),
    "EquityAttributableToOwnersOfParent": ("equity_attributable_to_owners", "INR"),
    "Equity": ("total_equity", "INR"),
    "BorrowingsNoncurrent": ("borrowings_noncurrent", "INR"),
    "BorrowingsCurrent": ("borrowings_current", "INR"),
    "TradePayablesCurrent": ("trade_payables_current", "INR"),
    "NoncurrentLiabilities": ("noncurrent_liabilities", "INR"),
    "CurrentLiabilities": ("current_liabilities", "INR"),
    "Liabilities": ("total_liabilities", "INR"),
    "EquityAndLiabilities": ("total_equity_and_liabilities", "INR"),
}

# Required in the quarter context of every INDAS_CORP results filing.
CRITICAL_QUARTER_TAGS = (
    "revenue_from_operations",
    "other_income",
    "total_income",
    "total_expenses",
    "finance_costs",
    "depreciation_amortisation",
    "profit_before_exceptional_and_tax",
    "pbt",
    "tax_expense",
    "pat",
)

EXPENSE_COMPONENTS = (
    "cost_of_materials_consumed",
    "purchases_of_stock_in_trade",
    "changes_in_inventories",
    "employee_benefit_expense",
    "finance_costs",
    "depreciation_amortisation",
    "other_expenses",
)

SCOPES = {"standalone": "STANDALONE", "consolidated": "CONSOLIDATED"}

# Named label rules [references X39, X40]: some lines exist only as a free-text label on a dimensional
# "Others"/detail member (Description* fact) paired with an amount in contexts with the same member.
# Each rule fixes the axis, the amount element and an anchored label pattern; nothing is fuzzy-matched.
LABEL_RULES: tuple[tuple[str, str, str, str, str, re.Pattern[str]], ...] = (
    # (rule name, axis local name, amount element, canonical tag, period type, label pattern)
    ("LEASE_LIAB_NONCURRENT", "OtherNoncurrentFinancialLiabilitiesAxis", "OtherNoncurrentFinancialLiabilities",
     "lease_liabilities_noncurrent", "INSTANT", re.compile(r"^\s*lease\s+liab", re.I)),
    ("LEASE_LIAB_CURRENT", "OtherCurrentFinancialLiabilitiesAxis", "OtherCurrentFinancialLiabilities",
     "lease_liabilities_current", "INSTANT", re.compile(r"^\s*lease\s+liab", re.I)),
    ("EXCISE_DUTY", "DetailsOfOtherExpensesAxis", "OtherExpenses", "excise_duty", "DURATION",
     re.compile(r"^\s*excise\s+dut", re.I)),
)  # fmt: skip


@dataclass(frozen=True)
class Issue:
    stage: str  # PARSE | PERIOD | IDENTITY
    reason_code: str
    details: dict[str, Any]


@dataclass(frozen=True)
class CanonicalFact:
    canonical_tag: str
    period_type: str  # DURATION | INSTANT
    period_start: date
    period_end: date
    period_months: int | None
    unit: str
    value: Decimal
    source_element: str


@dataclass
class ParsedResults:
    profile: str | None
    taxonomy_ns: str | None
    meta: dict[str, Any] = field(default_factory=dict)
    facts: list[CanonicalFact] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.profile == "INDAS_CORP" and not self.issues

    def value(self, tag: str, start: date, end: date) -> Decimal | None:
        for f in self.facts:
            if f.canonical_tag == tag and f.period_start == start and f.period_end == end:
                return f.value
        return None


def detect_profile(entity_ns: str | None) -> str | None:
    if not entity_ns:
        return None
    for fragment, profile in PROFILE_BY_NAMESPACE:
        if fragment in entity_ns:
            return profile
    return None


def period_months(start: date, end: date) -> int | None:
    """Whole calendar months for a period starting on the 1st and ending on a month end."""
    if start.day != 1 or end.day != calendar.monthrange(end.year, end.month)[1] or end < start:
        return None
    return (end.year - start.year) * 12 + end.month - start.month + 1


def _parse_date(text: str | None) -> date | None:
    return date.fromisoformat(text) if text else None


def _declared_periods(inst: Instance) -> dict[str, tuple[date, date]]:
    """Declared (start, end) per context family, from DateOf{Start,End}OfReportingPeriod."""
    out: dict[str, tuple[date, date]] = {}
    for family in ("One", "Four"):
        start = end = None
        for suffix in ("D", "I"):
            start = start or _parse_date(inst.text("DateOfStartOfReportingPeriod", family + suffix))
            end = end or _parse_date(inst.text("DateOfEndOfReportingPeriod", family + suffix))
        if start and end:
            out[family] = (start, end)
    return out


def _family(context_id: str) -> str | None:
    for family in ("One", "Four"):
        if context_id in (family + "D", family + "I"):
            return family
    return None


def parse_indas_corp_results(data: bytes) -> ParsedResults:
    inst = parse_instance(data)
    ns = inst.entity_namespace
    profile = detect_profile(ns)
    result = ParsedResults(profile=profile, taxonomy_ns=ns)
    if profile is None:
        result.issues.append(Issue("PARSE", "UNKNOWN_TAXONOMY", {"entity_namespace": ns}))
        return result
    if profile != "INDAS_CORP":
        result.issues.append(Issue("PARSE", "PROFILE_NOT_IMPLEMENTED", {"profile": profile}))
        return result

    _parse_meta(inst, result)
    if result.issues:
        return result
    _map_facts(inst, result)
    if not result.issues:
        _check_critical(result)
        _check_identities(result)
    return result


def _parse_meta(inst: Instance, result: ParsedResults) -> None:
    def required(name: str) -> str | None:
        try:
            value = inst.first_text(name)
        except ParseError as exc:
            result.issues.append(Issue("PARSE", "CONFLICTING_META", {"element": name, "error": str(exc)}))
            return None
        if value is None:
            result.issues.append(Issue("PARSE", "MISSING_META", {"element": name}))
        return value

    scope_text = required("NatureOfReportStandaloneConsolidated")
    rounding = required("LevelOfRounding")
    fy_start = _parse_date(required("DateOfStartOfFinancialYear"))
    fy_end = _parse_date(required("DateOfEndOfFinancialYear"))
    isin = required("ISIN")
    symbol = inst.first_text("Symbol")

    scope = SCOPES.get((scope_text or "").strip().lower())
    if scope_text and scope is None:
        result.issues.append(Issue("PARSE", "UNKNOWN_SCOPE", {"value": scope_text}))
    if rounding and rounding not in ROUNDING_UNITS:
        result.issues.append(Issue("PARSE", "UNKNOWN_ROUNDING", {"value": rounding}))

    declared = _declared_periods(inst)
    if "One" not in declared:
        result.issues.append(Issue("PERIOD", "NO_DECLARED_PERIOD", {}))
        return
    q_start, q_end = declared["One"]
    ytd = declared.get("Four", (fy_start, q_end) if fy_start else None)
    if fy_start and ytd and ytd != (fy_start, q_end):
        result.issues.append(
            Issue(
                "PERIOD",
                "YTD_NOT_FROM_FY_START",
                {"declared_ytd": [str(d) for d in ytd], "fy_start": str(fy_start)},
            )
        )

    board_end = None
    end_date = _parse_date(inst.first_text("DateOfEndOfBoardMeeting"))
    end_time = inst.first_text("EndTimeOfBoardMeeting")
    if end_date and end_time:
        board_end = ist_to_utc(end_date, time.fromisoformat(end_time))

    audited_text = (inst.first_text("WhetherResultsAreAuditedOrUnaudited") or "").strip().lower()
    result.meta.update(
        scope=scope,
        level_of_rounding=rounding,
        fy_start=fy_start,
        fy_end=fy_end,
        quarter_period=(q_start, q_end),
        ytd_period=ytd,
        period_end=q_end,
        reporting_quarter=inst.first_text("ReportingQuarter"),
        audited={"audited": True, "unaudited": False}.get(audited_text),
        board_meeting_end_ts=board_end,
        stated_isin=isin,
        stated_symbol=symbol,
        stated_scrip_code=inst.first_text("ScripCode"),
        company_name=inst.first_text("NameOfTheCompany"),
    )


def _map_facts(inst: Instance, result: ParsedResults) -> None:
    declared = {"One": result.meta["quarter_period"], "Four": result.meta["ytd_period"]}
    period_end: date = result.meta["period_end"]
    seen: dict[tuple[str, date, date], CanonicalFact] = {}

    for fact in inst.facts:
        if not fact.is_numeric:
            continue
        ctx = inst.contexts[fact.context_id]
        if ctx.dimensions:
            continue  # raw-only (RPT detail, segment, OCI breakdowns)
        if ctx.is_instant:
            mapping = INSTANT_TAGS.get(fact.name)
            if mapping is None or ctx.instant != period_end:
                continue  # e.g. PY_I opening cash: raw-only [X2]
            start = end = ctx.instant
            months = None
            ptype = "INSTANT"
        else:
            mapping = DURATION_TAGS.get(fact.name)
            if mapping is None:
                continue
            family = _family(ctx.id)
            expected = declared.get(family) if family else None
            actual = (ctx.start, ctx.end)
            if expected is None or actual != expected:
                result.issues.append(
                    Issue(
                        "PERIOD",
                        "CONTEXT_CONFLICT",
                        {
                            "context_id": ctx.id,
                            "context_dates": [str(d) for d in actual],
                            "declared": [str(d) for d in expected] if expected else None,
                            "element": fact.name,
                        },
                    )
                )
                continue
            start, end = actual
            months = period_months(start, end)
            if months is None or not 1 <= months <= 18:
                result.issues.append(
                    Issue("PERIOD", "IRREGULAR_PERIOD", {"context_id": ctx.id, "dates": [str(start), str(end)]})
                )
                continue
            ptype = "DURATION"
        tag, unit = mapping
        cf = CanonicalFact(tag, ptype, start, end, months, unit, fact.decimal(), fact.name)
        key = (tag, start, end)
        if key in seen:
            if seen[key].value != cf.value:
                result.issues.append(
                    Issue(
                        "PARSE",
                        "DUPLICATE_CONFLICT",
                        {"tag": tag, "values": [str(seen[key].value), str(cf.value)]},
                    )
                )
            continue
        seen[key] = cf
        result.facts.append(cf)

    _apply_label_rules(inst, result, declared, period_end)

    # Derived per-filing facts.
    q_start, q_end = result.meta["quarter_period"]
    paid_up = result.value("paid_up_equity_capital", q_start, q_end)
    face = result.value("face_value_per_share", q_start, q_end)
    if paid_up is not None and face:
        # Wrong for partly-paid share classes [X18]; cross-checked against Reg. 31 later.
        result.facts.append(
            CanonicalFact(
                "shares_from_paid_up",
                "INSTANT",
                q_end,
                q_end,
                None,
                "SHARES",
                paid_up / face,
                "DERIVED:PaidUpValueOfEquityShareCapital/FaceValueOfEquityShareCapital",
            )
        )
    result.meta["interest_paid_cfo_class"] = _classify(
        result, "interest_paid_operating", "interest_paid_financing", "FINANCING"
    )
    result.meta["interest_recd_cfo_class"] = _classify(
        result, "interest_received_operating", "interest_received_investing", "INVESTING"
    )


def _classify(result: ParsedResults, op_tag: str, other_tag: str, other_label: str) -> str | None:
    ytd = result.meta["ytd_period"]
    op = result.value(op_tag, *ytd)
    other = result.value(other_tag, *ytd)
    if op is None and other is None:
        return None  # no cash-flow statement in this filing
    op_nz, other_nz = bool(op), bool(other)
    if op_nz and other_nz:
        return "MIXED"
    if op_nz:
        return "OPERATING"
    if other_nz:
        return other_label
    return "NONE"


def _check_critical(result: ParsedResults) -> None:
    q = result.meta["quarter_period"]
    missing = [t for t in CRITICAL_QUARTER_TAGS if result.value(t, *q) is None]
    if missing:
        result.issues.append(Issue("PARSE", "MISSING_CRITICAL", {"tags": missing}))


def _check(result: ParsedResults, name: str, lhs: Decimal, rhs: Decimal, n_terms: int, period: Any) -> None:
    tol = identity_tolerance(result.meta["level_of_rounding"], n_terms)
    if abs(lhs - rhs) > tol:
        result.issues.append(
            Issue(
                "IDENTITY",
                name,
                {"period": [str(p) for p in period], "lhs": str(lhs), "rhs": str(rhs), "tolerance": str(tol)},
            )
        )


def _check_identities(result: ParsedResults) -> None:
    periods = {result.meta["quarter_period"], result.meta["ytd_period"]}
    for p in periods:
        v = lambda tag, p=p: result.value(tag, *p)  # noqa: E731
        inc, exp, pbeit, pbt = (
            v("total_income"),
            v("total_expenses"),
            v("profit_before_exceptional_and_tax"),
            v("pbt"),
        )
        if None not in (inc, exp, pbeit):
            _check(result, "INCOME_MINUS_EXPENSES", inc - exp, pbeit, 3, p)
        if None not in (pbeit, pbt):
            exc = v("exceptional_items") or Decimal(0)
            _check(result, "PBEIT_PLUS_EXCEPTIONAL", pbeit + exc, pbt, 3, p)
        tax, pat_c = v("tax_expense"), v("pat_continuing")
        if None not in (pbt, tax, pat_c):
            _check(result, "PBT_MINUS_TAX", pbt - tax, pat_c, 3, p)
        comps = [v(t) for t in EXPENSE_COMPONENTS]
        if exp is not None and None not in comps:
            _check(result, "EXPENSE_COMPONENTS", sum(comps, Decimal(0)), exp, len(comps) + 1, p)
    end = result.meta["period_end"]
    assets, eq_liab = (
        result.value("total_assets", end, end),
        result.value("total_equity_and_liabilities", end, end),
    )
    if None not in (assets, eq_liab):
        _check(result, "BALANCE_SHEET", assets, eq_liab, 2, (end,))


def _apply_label_rules(inst: Instance, result: ParsedResults, declared: dict, period_end: date) -> None:
    """Sum amounts of members whose Description* label matches a rule; same period checks as other facts."""
    labelled: dict[str, set[tuple]] = {}  # rule -> set of dimension tuples whose label matched
    for f in inst.facts:
        if f.is_numeric or not f.name.startswith("Description"):
            continue
        dims = inst.contexts[f.context_id].dimensions
        if len(dims) != 1:
            continue
        axis = dims[0][0].split(":")[-1]
        for rule, rule_axis, _, _, _, rx in LABEL_RULES:
            if axis == rule_axis and rx.match(f.value_text):
                labelled.setdefault(rule, set()).add(dims)
    for rule, _, element, tag, ptype, _ in LABEL_RULES:
        dims_set = labelled.get(rule)
        if not dims_set:
            continue
        totals: dict[tuple[date, date], Decimal] = {}
        for f in inst.facts:
            ctx = inst.contexts[f.context_id]
            if f.name != element or not f.is_numeric or ctx.dimensions not in dims_set:
                continue
            if ptype == "INSTANT":
                if ctx.instant != period_end:
                    continue
                key = (period_end, period_end)
            else:
                if ctx.instant is not None or (ctx.start, ctx.end) not in (declared["One"], declared["Four"]):
                    result.issues.append(
                        Issue(
                            "PERIOD",
                            "CONTEXT_CONFLICT",
                            {"rule": rule, "context_id": ctx.id, "context_dates": [str(ctx.start), str(ctx.end)]},
                        )
                    )
                    continue
                key = (ctx.start, ctx.end)
            totals[key] = totals.get(key, Decimal(0)) + f.decimal()
        for (start, end), value in totals.items():
            months = None if ptype == "INSTANT" else period_months(start, end)
            result.facts.append(CanonicalFact(tag, ptype, start, end, months, "INR", value, f"LABEL:{rule}"))
