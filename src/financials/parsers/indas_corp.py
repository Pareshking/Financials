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
import dataclasses
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
    # Pre-Integrated-Filing GI format (out of scope, context dates do not match declared dates [X26]): never parsed
    ("/GeneralInsurance/", "IRDAI_GENERAL_LEGACY"),
    ("/IntegratedFinance_LI/", "IRDAI_LIFE"),
    ("/IntegratedFinance_GI/", "IRDAI_GENERAL"),
    ("/IntegratedFinance_InsuranceCompaniesIndAS/", "INDAS_INSURANCE"),  # Ind AS 117 (Star Health, Go Digit) [X64]
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
    # Consolidated attribution and regulated-utility line [X42]
    "ProfitOrLossAttributableToOwnersOfParent": ("pat_owners", "INR"),
    "ProfitOrLossAttributableToNonControllingInterests": ("pat_nci", "INR"),
    "NetMovementInRegulatoryDeferralAccountBalancesRelatedToProfitOrLossAndTheRelatedDeferredTaxMovement": (
        "regulatory_deferral_movement",
        "INR",
    ),
    "OtherComprehensiveIncomeNetOfTaxes": ("oci_net", "INR"),
    "ComprehensiveIncomeForThePeriod": ("total_comprehensive_income", "INR"),
    "PaidUpValueOfEquityShareCapital": ("paid_up_equity_capital", "INR"),
    "FaceValueOfEquityShareCapital": ("face_value_per_share", "INR_PER_SHARE"),
    "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations": ("eps_basic", "INR_PER_SHARE"),
    "BasicEarningsLossPerShareFromContinuingOperations": ("eps_basic_continuing", "INR_PER_SHARE"),
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
    # Cash-flow reconciliation (indirect method) [X45]. Sign as filed: working-capital lines are positive when
    # they add cash; AdjustmentsForInterestIncome / DividendIncome / UndistributedProfitsOfAssociates are filed
    # as positive amounts that the filer *deducts* (25/25 Sep-2026 filings, unique sign solution).
    "AdjustmentsForReconcileProfitLoss": ("cf_adjustments_total", "INR"),
    "AdjustmentsForDepreciationAndAmortisationExpense": ("cf_adj_depreciation", "INR"),
    "AdjustmentsForFinanceCosts": ("cf_adj_finance_costs", "INR"),
    "AdjustmentsForInterestIncome": ("cf_adj_interest_income_deducted", "INR"),
    "AdjustmentsForDividendIncome": ("cf_adj_dividend_income_deducted", "INR"),
    "AdjustmentsForUndistributedProfitsOfAssociates": ("cf_adj_associates_deducted", "INR"),
    "AdjustmentsForDecreaseIncreaseInTradeReceivablesCurrent": ("cf_wc_trade_receivables_current", "INR"),
    "AdjustmentsForDecreaseIncreaseInTradeReceivablesNoncurrent": ("cf_wc_trade_receivables_noncurrent", "INR"),
    "AdjustmentsForDecreaseIncreaseInInventories": ("cf_wc_inventories", "INR"),
    "AdjustmentsForIncreaseDecreaseInTradePayablesCurrent": ("cf_wc_trade_payables_current", "INR"),
    "AdjustmentsForIncreaseDecreaseInTradePayablesNoncurrent": ("cf_wc_trade_payables_noncurrent", "INR"),
    "AdjustmentsForDecreaseIncreaseInOtherCurrentAssets": ("cf_wc_other_current_assets", "INR"),
    "AdjustmentsForDecreaseIncreaseInOtherNoncurrentAssets": ("cf_wc_other_noncurrent_assets", "INR"),
    "AdjustmentsForOtherFinancialAssetsCurrent": ("cf_wc_other_financial_assets_current", "INR"),
    "AdjustmentsForOtherFinancialAssetsNoncurrent": ("cf_wc_other_financial_assets_noncurrent", "INR"),
    "AdjustmentsForOtherBankBalances": ("cf_wc_other_bank_balances", "INR"),
    "AdjustmentsForIncreaseDecreaseInOtherCurrentLiabilities": ("cf_wc_other_current_liabilities", "INR"),
    "AdjustmentsForIncreaseDecreaseInOtherNoncurrentLiabilities": ("cf_wc_other_noncurrent_liabilities", "INR"),
    "AdjustmentsForProvisionsCurrent": ("cf_wc_provisions_current", "INR"),
    "AdjustmentsForProvisionsNoncurrent": ("cf_wc_provisions_noncurrent", "INR"),
    "AdjustmentsForOtherFinancialLiabilitiesCurrent": ("cf_wc_other_financial_liabilities_current", "INR"),
    "AdjustmentsForOtherFinancialLiabilitiesNoncurrent": ("cf_wc_other_financial_liabilities_noncurrent", "INR"),
    "DividendsReceivedClassifiedAsOperatingActivities": ("dividends_received_operating", "INR"),
    "DividendsReceivedClassifiedAsInvestingActivities": ("dividends_received_investing", "INR"),
    "ProceedsFromBorrowingsClassifiedAsFinancingActivities": ("borrowings_proceeds", "INR"),
    "RepaymentsOfBorrowingsClassifiedAsFinancingActivities": ("borrowings_repayments", "INR"),
    "PaymentsOfLeaseLiabilitiesClassifiedAsFinancingActivities": ("lease_payments", "INR"),
    "ProceedsFromIssuingSharesClassifiedAsFinancingActivities": ("share_issue_proceeds", "INR"),
    "IncreaseDecreaseInCashAndCashEquivalentsBeforeEffectOfExchangeRateChanges": ("net_cash_flow", "INR"),
    "EffectOfExchangeRateChangesOnCashAndCashEquivalents": ("fx_effect_on_cash", "INR"),
    "IncreaseDecreaseInCashAndCashEquivalents": ("net_cash_flow_after_fx", "INR"),
    "AmountOfRelatedPartyTransactionDuringTheReportingPeriod": ("rpt_total_amount", "INR"),
}

INSTANT_TAGS: dict[str, tuple[str, str]] = {
    "PropertyPlantAndEquipment": ("ppe_net", "INR"),
    "CapitalWorkInProgress": ("cwip", "INR"),
    "IntangibleAssetsUnderDevelopment": ("intangibles_under_development", "INR"),
    "InvestmentProperty": ("investment_property", "INR"),
    "DeferredTaxAssetsNet": ("deferred_tax_assets", "INR"),
    "DeferredTaxLiabilitiesNet": ("deferred_tax_liabilities", "INR"),
    "Goodwill": ("goodwill", "INR"),
    "OtherIntangibleAssets": ("other_intangibles", "INR"),
    "NoncurrentInvestments": ("noncurrent_investments", "INR"),
    # Associates / JVs: a separate Schedule III line, not inside NoncurrentInvestments [X44]
    "InvestmentsAccountedForUsingEquityMethod": ("equity_method_investments", "INR"),
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
    "NonControllingInterest": ("non_controlling_interest", "INR"),
    "BorrowingsNoncurrent": ("borrowings_noncurrent", "INR"),
    "BorrowingsCurrent": ("borrowings_current", "INR"),
    "TradePayablesCurrent": ("trade_payables_current", "INR"),
    # Mapped in the unmapped-element audit (C22): Screener balance-sheet sub-rows and Piotroski/Beneish inputs.
    "TradePayablesNoncurrent": ("trade_payables_noncurrent", "INR"),
    "LoansCurrent": ("loans_current", "INR"),
    "LoansNoncurrent": ("loans_noncurrent", "INR"),
    "CashAndCashEquivalentsCashFlowStatement": ("cash_cf_statement", "INR"),
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

IMPLEMENTED_PROFILES = (
    "INDAS_CORP", "INDAS_NBFC", "IGAAP_BANK", "IRDAI_LIFE", "IRDAI_GENERAL", "INDAS_INSURANCE", "REG34_ANNUAL",
)  # fmt: skip

# Named label rules [references X39, X40]: some lines exist only as a free-text label on a dimensional
# "Others"/detail member (Description* fact) paired with an amount in contexts with the same member.
# Each rule fixes the axis, the amount element and an anchored label pattern; nothing is fuzzy-matched.
LABEL_RULES: tuple[tuple[str, str, str, str, str, re.Pattern[str]], ...] = (
    # (rule name, axis local name, amount element, canonical tag, period type, label pattern)
    ("LEASE_LIAB_NONCURRENT", "OtherNoncurrentFinancialLiabilitiesAxis", "OtherNoncurrentFinancialLiabilities",
     "lease_liabilities_noncurrent", "INSTANT", re.compile(r"^\s*lease\s+liab", re.I)),
    ("LEASE_LIAB_CURRENT", "OtherCurrentFinancialLiabilitiesAxis", "OtherCurrentFinancialLiabilities",
     "lease_liabilities_current", "INSTANT", re.compile(r"^\s*lease\s+liab", re.I)),
    # Right-of-use assets: only a labelled OtherNoncurrentAssets member (Eternal, ITC) [X47]
    ("RIGHT_OF_USE_ASSETS", "OtherNoncurrentAssetsAxis", "OtherNoncurrentAssets", "right_of_use_assets", "INSTANT",
     re.compile(r"^\s*right[\s-]*of[\s-]*use", re.I)),
    # Manufacturing cost lines, labelled only by some filers (4/10 and 1/10 in Batch 3) [X50].
    # Absent label = not disclosed (NULL), never 0: unlike excise, nothing is netted against them.
    ("POWER_AND_FUEL", "DetailsOfOtherExpensesAxis", "OtherExpenses", "power_and_fuel", "DURATION",
     re.compile(r"^\s*power\s*(?:and|&|,)\s*fuel", re.I)),
    ("FREIGHT", "DetailsOfOtherExpensesAxis", "OtherExpenses", "freight", "DURATION",
     re.compile(r"^\s*freight", re.I)),
    # New-gen tech [X68]: contract liabilities only as labelled "other liabilities" members (Swiggy, Paytm, IndiaMART,
    # Nykaa, RateGain); advertising only as a labelled other-expenses line (7/10 of Batch 7). Absent = NULL.
    ("CONTRACT_LIABILITIES_CURRENT", "OtherCurrentLiabilitiesAxis", "OtherCurrentLiabilities",
     "contract_liabilities_current", "INSTANT",
     re.compile(r"^\s*(?:contract\s+liabilit|advances?\s+(?:received\s+)?from\s+customers|deferred\s+revenue|"
                r"unearned\s+revenue|income\s+received\s+in\s+advance)", re.I)),
    ("CONTRACT_LIABILITIES_NONCURRENT", "OtherNoncurrentLiabilitiesAxis", "OtherNoncurrentLiabilities",
     "contract_liabilities_noncurrent", "INSTANT",
     re.compile(r"^\s*(?:contract\s+liabilit|advances?\s+(?:received\s+)?from\s+customers|deferred\s+revenue|"
                r"unearned\s+revenue|income\s+received\s+in\s+advance)", re.I)),
    ("ADVERTISING", "DetailsOfOtherExpensesAxis", "OtherExpenses", "advertising_promotion", "DURATION",
     re.compile(r"^\s*(?:advertis|marketing\s+and\s+(?:advertis|promotion)|sales\s+promotion)", re.I)),
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
    line_item_category: str | None = None  # C24
    parent_subtotal: str | None = None


@dataclass
class ParsedResults:
    profile: str | None
    taxonomy_ns: str | None
    meta: dict[str, Any] = field(default_factory=dict)
    facts: list[CanonicalFact] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    # Non-blocking findings: the filing is promoted and each finding opens a quarantine row [X86].
    findings: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.profile in IMPLEMENTED_PROFILES and not self.issues

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


def _stale_context_dates(inst: Instance, declared: dict, period_end: date) -> tuple[dict, date | None]:
    """Named rule STALE_CONTEXT_DATES [X87]: every period context of the filing still carries an earlier filing's
    dates (Siemens Q3 FY26: OneD Apr-Jun 2025 and FourD Oct 2024-Jun 2025, declared Oct-Dec 2025 and the 15-month
    Oct 2024-Dec 2025; the results PDF shows the XBRL values, 33,985 / 179,167 Mn revenue, for the declared periods).
    Applies only when each period family has one context period, none equals its declared period, all share one end
    date before the declared period end, and every declared period ends on it. Returns (family -> stale period,
    stale end) or ({}, None)."""
    periods: dict[str, set] = {}
    for fact in inst.facts:
        ctx = inst.contexts[fact.context_id]
        if fact.is_numeric and not ctx.dimensions and not ctx.is_instant and (family := _family(ctx.id)):
            periods.setdefault(family, set()).add((ctx.start, ctx.end))
    if not periods or any(len(v) != 1 for v in periods.values()):
        return {}, None
    stale = {f: next(iter(v)) for f, v in periods.items()}
    ends = {p[1] for p in stale.values()}
    if (
        len(ends) != 1
        or any(declared.get(f) is None or declared[f] == p or declared[f][1] != period_end for f, p in stale.items())
        or not next(iter(ends)) < period_end
    ):
        return {}, None
    return stale, next(iter(ends))


def parse_indas_corp_results(data: bytes) -> ParsedResults:
    """Corporate (Schedule III Division II) filings only; other profiles are routed, not parsed."""
    return parse_with_spec(data, CORP_SPEC)


def parse_with_spec(data: bytes, spec: ProfileSpec) -> ParsedResults:
    inst = parse_instance(data)
    ns = inst.entity_namespace
    profile = detect_profile(ns)
    result = ParsedResults(profile=profile, taxonomy_ns=ns)
    if profile is None:
        result.issues.append(Issue("PARSE", "UNKNOWN_TAXONOMY", {"entity_namespace": ns}))
        return result
    if profile != spec.profile:
        result.issues.append(Issue("PARSE", "PROFILE_NOT_IMPLEMENTED", {"profile": profile}))
        return result

    _parse_meta(inst, result)
    if result.issues:
        return result
    _map_facts(inst, result, spec)
    if not result.issues:
        _check_critical(result, spec)
        if spec.identities is not None:
            spec.identities(result)
        else:
            _check_identities(result, spec)
        _check_eps(result)
        if spec.post_process is not None:
            spec.post_process(result)
            preserve_withheld(inst, result, durations={result.meta["quarter_period"], result.meta["ytd_period"]},
                              instants={result.meta["period_end"]})  # fmt: skip
    enrich_line_items(result)
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

    # Audit status is per context: a Q4 filing may mark the quarter Unaudited and the FY Audited [X46].
    audit_by_period: dict[tuple, bool | None] = {}
    for f in inst.facts:
        c = inst.contexts[f.context_id]
        if f.name == "WhetherResultsAreAuditedOrUnaudited" and not c.dimensions and c.instant is None:
            audit_by_period[(c.start, c.end)] = {"audited": True, "unaudited": False}.get(f.value_text.strip().lower())
    # Audit opinion declaration [E8]: only the two values below are observed; anything else is kept verbatim.
    opinions = {
        f.value_text.strip()
        for f in inst.facts
        if f.name == "DeclarationOfUnmodifiedOpinionOrStatementOnImpactOfAuditQualification"
        and not inst.contexts[f.context_id].dimensions
    }
    known = {"declaration of unmodified opinion": "UNMODIFIED", "not applicable": "NOT_APPLICABLE"}
    audit_opinion = ",".join(sorted(known.get(o.lower(), o) for o in opinions)) or None
    result.meta.update(
        audit_opinion=audit_opinion,
        scope=scope,
        level_of_rounding=rounding,
        fy_start=fy_start,
        fy_end=fy_end,
        quarter_period=(q_start, q_end),
        ytd_period=ytd,
        period_end=q_end,
        reporting_quarter=inst.first_text("ReportingQuarter"),
        audited=audit_by_period.get((q_start, q_end)),  # the quarter's own status (filings.audited)
        audited_ytd=audit_by_period.get(ytd) if ytd else None,
        board_meeting_end_ts=board_end,
        stated_isin=isin,
        stated_symbol=symbol,
        stated_scrip_code=inst.first_text("ScripCode"),
        company_name=inst.first_text("NameOfTheCompany"),
    )


def _map_facts(inst: Instance, result: ParsedResults, spec: ProfileSpec | None = None) -> None:
    spec = spec or CORP_SPEC
    declared = {"One": result.meta["quarter_period"], "Four": result.meta["ytd_period"]}
    period_end: date = result.meta["period_end"]
    seen: dict[tuple[str, date, date], CanonicalFact] = {}
    stale, stale_end = _stale_context_dates(inst, declared, period_end)
    if stale:
        result.meta.setdefault("rules_applied", []).append(
            {"rule": "STALE_CONTEXT_DATES", "periods": {f: [str(d) for d in p] for f, p in sorted(stale.items())}}
        )

    for fact in inst.facts:
        if not fact.is_numeric:
            continue
        ctx = inst.contexts[fact.context_id]
        if ctx.dimensions:
            continue  # raw-only (RPT detail, segment, OCI breakdowns)
        if ctx.is_instant:
            mapping = spec.instant_tags.get(fact.name)
            instant = period_end if stale and ctx.instant == stale_end else ctx.instant  # X87
            if mapping is None or instant != period_end:
                continue  # e.g. PY_I opening cash: raw-only [X2]
            start = end = instant
            months = None
            ptype = "INSTANT"
        else:
            mapping = spec.duration_tags.get(fact.name)
            if mapping is None:
                continue
            family = _family(ctx.id)
            expected = declared.get(family) if family else None
            actual = (ctx.start, ctx.end)
            if family in stale and actual == stale[family]:
                actual = expected  # X87: re-dated to the declared period
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

    _apply_label_rules(inst, result, declared, period_end, spec.label_rules)
    map_line_items(inst, result, {**spec.duration_tags, **spec.instant_tags},
                   durations=set(declared.values()), instants={period_end})  # fmt: skip

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
    _apply_zero_attribution_rule(result)
    _apply_owners_tci_rule(result)
    if spec is None or spec.identities is None:
        # Only where owners + NCI = PAT is the profile's identity (corporate, NBFC, annual). Not banks: their
        # PAT precedes the share of associates (PNB Q2 FY27: owners 5,898 Cr = PAT 5,561 - NCI + associates).
        _apply_attribution_recovery_rules(result)
    preserve_withheld(inst, result, durations=set(declared.values()), instants={period_end})
    result.meta["interest_paid_cfo_class"] = _classify(
        result, "interest_paid_operating", "interest_paid_financing", "FINANCING"
    )
    result.meta["interest_recd_cfo_class"] = _classify(
        result, "interest_received_operating", "interest_received_investing", "INVESTING"
    )


UNIT_OF_KIND = {"INR": "INR", "INR_PER_SHARE": "INR_PER_SHARE", "PURE": "PURE", "SHARES": "SHARES"}


def map_line_items(inst: Instance, result: ParsedResults, curated: dict, *, durations: set, instants: set) -> None:
    """Zero-drop pass (C24): every numeric line item not already mapped, in the periods the curated pass validated,
    becomes a fact under its deterministic key; amounts on text-labelled members become `oth_` facts. Curated
    facts get their category/parent metadata too. A conflicting duplicate key is skipped with a warning (never a
    guess); the raw fact stays in raw_xbrl_facts."""
    from financials.line_items import describe, describe_key, line_item_key, slug

    profile = result.profile or ""
    cache: dict[str, dict] = {}

    def meta(element: str) -> dict:
        if element not in cache:
            cache[element] = describe(profile, element, curated)
        return cache[element]

    # metadata on curated / label-rule facts already emitted
    enriched = []
    for f in result.facts:
        if f.line_item_category is None:
            m = describe_key(f.canonical_tag)
            f = dataclasses.replace(f, line_item_category=m["line_item_category"], parent_subtotal=m["parent_subtotal"])
        enriched.append(f)
    result.facts[:] = enriched
    seen = {(f.canonical_tag, f.period_start, f.period_end) for f in result.facts}
    conflicts: dict[tuple, set] = {}
    subpaise: list[str] = []
    pending: dict[tuple, CanonicalFact] = {}

    def period_of(ctx):
        if ctx.instant is not None:
            return ("INSTANT", ctx.instant, ctx.instant, None) if ctx.instant in instants else None
        p = (ctx.start, ctx.end)
        return ("DURATION", ctx.start, ctx.end, period_months(*p)) if p in durations else None

    labels: dict[tuple, str] = {}
    for f in inst.facts:
        dims = inst.contexts[f.context_id].dimensions
        if not f.is_numeric and len(dims) == 1 and f.name.startswith("Description") and f.value_text.strip():
            labels.setdefault(dims, f.value_text.strip())
    # A label shared by several members (subsidiary schedules: "Foreign subsidiary"; segments on two axes) gets the
    # member, then the axis, appended so every key stays unique and deterministic.
    by_label: dict[str, set] = {}
    for dims, label in labels.items():
        by_label.setdefault(slug(label), set()).add(dims)

    def label_key(dims: tuple) -> str:
        base = slug(labels[dims])
        same = by_label[base]
        if len(same) == 1:
            return base
        axis, member = (x.split(":")[-1] for x in dims[0])
        with_member = f"{base}__{slug(member)}"
        if sum(1 for d in same if slug(d[0][1].split(":")[-1]) == slug(member)) == 1:
            return with_member
        return f"{with_member}__{slug(axis)}"

    for f in inst.facts:
        if not f.is_numeric:
            continue
        ctx = inst.contexts[f.context_id]
        per = period_of(ctx)
        if per is None:
            continue
        ptype, start, end, months = per
        kind = inst.unit_kind(f.unit_ref)
        unit = UNIT_OF_KIND.get(kind, kind or "UNKNOWN")
        if ctx.dimensions:
            label = labels.get(ctx.dimensions)
            if label is None or len(ctx.dimensions) != 1:
                continue  # a record row, not a line item
            base = line_item_key(f.name, curated)
            key = f"oth_{base}__{label_key(ctx.dimensions)}"
            m = meta(f.name)
            cat, parent = m["line_item_category"], base
        else:
            if f.name in curated:
                continue  # curated pass owns it
            m = meta(f.name)
            key, cat, parent = m["canonical_key"], m["line_item_category"], m["parent_subtotal"]
        k = (key, start, end)
        if k in seen:
            continue
        try:
            value = f.decimal()
        except ParseError:
            continue
        if unit == "INR" and value != value.quantize(Decimal("0.01")):
            # X77: XBRL rupees are absolute, so a value with sub-paise digits under an INR unit is a mis-tagged count
            # or quantity (BBTC NumberOfMeetingsOfBoard, ELECON product quantity): kept exactly, never as money.
            unit = "INR_SUBPAISE"
            subpaise.append(f.name)
        cf = CanonicalFact(key, ptype, start, end, months, unit, value, f.name, cat, parent)
        if k in pending and pending[k].value != value:
            conflicts.setdefault(k, set()).update({str(pending[k].value), str(value)})
            continue
        pending.setdefault(k, cf)
    for k, cf in pending.items():
        if k not in conflicts:
            result.facts.append(cf)
    if conflicts:
        result.meta.setdefault("warnings", []).append(
            {"code": "LINE_ITEM_CONFLICT", "keys": sorted(f"{k[0]}@{k[2]}" for k in conflicts)}
        )
    if subpaise:
        result.meta.setdefault("warnings", []).append({"code": "INR_UNIT_SUBPAISE", "elements": sorted(set(subpaise))})


def enrich_line_items(result: ParsedResults) -> None:
    """Category / parent metadata for facts created after the line-item pass (derived, rule and schedule facts)."""
    from financials.line_items import describe_key

    result.facts[:] = [
        f if f.line_item_category else dataclasses.replace(
            f, **{k: v for k, v in describe_key(f.canonical_tag).items() if k != "canonical_key"})
        for f in result.facts
    ]  # fmt: skip


def preserve_withheld(inst: Instance, result: ParsedResults, *, durations: set, instants: set) -> None:
    """Zero-drop (C24): a value a named rule withheld or replaced (placeholder owners/NCI [X48], owners tagged as
    TCI, contingent-liability placeholders [X73]) is kept as filed under `asfiled_<element>`; the canonical tag
    keeps the corrected value."""
    from financials.line_items import snake

    have = {f.source_element for f in result.facts}
    seen = set()
    for f in inst.facts:
        c = inst.contexts[f.context_id]
        if not f.is_numeric or c.dimensions or f.name in have:
            continue
        inside = c.instant in instants if c.instant is not None else (c.start, c.end) in durations
        if not inside:
            continue
        start, end = (c.instant, c.instant) if c.instant is not None else (c.start, c.end)
        key = ("asfiled_" + snake(f.name), start, end)
        if key in seen:
            continue
        seen.add(key)
        ptype = "INSTANT" if c.instant is not None else "DURATION"
        months = None if ptype == "INSTANT" else period_months(start, end)
        kind = inst.unit_kind(f.unit_ref)
        result.facts.append(CanonicalFact(key[0], ptype, start, end, months, UNIT_OF_KIND.get(kind, kind or "UNKNOWN"),
                                          f.decimal(), f.name, "AS_FILED_WITHHELD", None))  # fmt: skip


def _apply_zero_attribution_rule(result: ParsedResults) -> None:
    """Named rule ZERO_ATTRIBUTION_PLACEHOLDER [X48].

    Owners' share = 0 AND NCI share = 0 while profit for the period != 0 cannot be a real attribution
    (owners + NCI must equal PAT); it is an unfilled placeholder (APL Apollo Q2 FY27, decimals -7 vs -5).
    Drop both canonical facts for that period, so owners' profit falls back to total PAT per filing
    (COALESCE). Raw facts stay in the vault untouched. Any other mismatch still fails OWNERS_PLUS_NCI.
    """
    by_period: dict[tuple[date, date], dict[str, Decimal]] = {}
    for f in result.facts:
        if f.canonical_tag in ("pat", "pat_owners", "pat_nci"):
            by_period.setdefault((f.period_start, f.period_end), {})[f.canonical_tag] = f.value
    dropped = [p for p, v in by_period.items() if v.get("pat_owners") == 0 and v.get("pat_nci") == 0 and v.get("pat")]
    if not dropped:
        return
    result.facts = [
        f
        for f in result.facts
        if not (f.canonical_tag in ("pat_owners", "pat_nci") and (f.period_start, f.period_end) in dropped)
    ]
    result.meta.setdefault("rules_applied", []).append(
        {"rule": "ZERO_ATTRIBUTION_PLACEHOLDER", "periods": [[str(a), str(b)] for a, b in sorted(dropped)]}
    )


def _apply_owners_tci_rule(result: ParsedResults) -> None:
    """Named rule OWNERS_TAGGED_AS_TCI [X56, X67]: the owners' profit element carries total comprehensive income
    (Cholamandalam Q2 FY27, Delhivery Q2 FY27). Applied only when the NCI share is exactly 0, because then owners'
    profit must equal PAT and the replacement is exact; with a non-zero NCI the filing still fails OWNERS_PLUS_NCI
    and is quarantined (decision 2026-11-13). Raw facts stay; the canonical owners fact becomes PAT."""
    tol = identity_tolerance(result.meta["level_of_rounding"], 3)
    fixed = []
    for f in [f for f in result.facts if f.canonical_tag == "pat_owners"]:
        p = (f.period_start, f.period_end)
        pat, nci, tci = (result.value(t, *p) for t in ("pat", "pat_nci", "total_comprehensive_income"))
        if None in (pat, nci, tci) or nci != 0:
            continue
        if abs(f.value - tci) <= tol and abs(f.value - pat) > tol:
            fixed.append((f, pat))
    if not fixed:
        return
    for f, pat in fixed:
        result.facts.remove(f)
        result.facts.append(CanonicalFact("pat_owners", f.period_type, f.period_start, f.period_end, f.period_months,
                                          f.unit, pat, "RULE:OWNERS_TAGGED_AS_TCI"))  # fmt: skip
    result.meta.setdefault("rules_applied", []).append(
        {"rule": "OWNERS_TAGGED_AS_TCI", "periods": [[str(f.period_start), str(f.period_end)] for f, _ in fixed]}
    )


# X93: owners + NCI = PAT holds to 3 rounding units, not the 1.5 of a three-term sum: companies round each line from
# unrounded books and file a 2-3 unit gap that their own PDF shows too (SPARC Q1 FY27 -20.76 vs PAT -20.78 Lakhs ->
# 2 lakh; RPower Q4 FY25 125.60 vs 125.57 Cr in Lakhs -> 3 lakh).
ATTRIBUTION_TERMS = 6
TCI_OWNERS_KEY = "li_comprehensive_income_for_the_period_attributable_to_owners_of_parent"
TCI_NCI_KEY = "li_comprehensive_income_for_the_period_attributable_to_owners_of_parent_non_controlling_interests"
ATTRIBUTION_WITHHELD_TAG = "attribution_withheld"  # marker (PURE 1): owners/NCI for the period are not usable [X86]


def _replace_attribution(result: ParsedResults, p: tuple, owners: Decimal, nci: Decimal, rule: str) -> None:
    for tag, value in (("pat_owners", owners), ("pat_nci", nci)):
        old = next(f for f in result.facts if f.canonical_tag == tag and (f.period_start, f.period_end) == p)
        result.facts.remove(old)
        result.facts.append(dataclasses.replace(old, value=value, source_element=f"RULE:{rule}"))


def _apply_attribution_recovery_rules(result: ParsedResults) -> None:
    """Exact recovery of a mis-tagged profit attribution, then withholding of what cannot be recovered.

    Run after X48 / X56. For each period whose owners + NCI differs from PAT:
    - ATTRIBUTION_TAGGED_AS_OCI [X84]: the owners/NCI profit elements carry the OCI attribution (owners + NCI =
      OCI). Profit attribution = TCI attribution - OCI attribution, accepted only when that sums to PAT
      (Adani Ports Q4 FY26: 4,567.63 - 1,238.67 = 3,328.96 cr owners; 158.48 - 179.14 = -20.66 cr NCI, as in the PDF).
    - ATTRIBUTION_SIGN_FLIP [X85]: flipping the sign of exactly one of owners / NCI makes owners + NCI = PAT
      (Godrej Agrovet H1 FY27: 249.71 - 18.65 = 231.06 cr). Ambiguous or zero flips are not applied.
    - ATTRIBUTION_WITHHELD [X86]: otherwise drop owners and NCI for the period and add the marker fact, so readers
      neither use the split nor fall back to PAT; the rest of the filing is promoted and the finding stays open
      (owner decision 2026-11-14, superseding 2026-11-13 for the non-zero NCI case). Raw facts stay as filed.
    """
    tol = identity_tolerance(result.meta["level_of_rounding"], ATTRIBUTION_TERMS)
    periods = sorted({(f.period_start, f.period_end) for f in result.facts if f.canonical_tag == "pat_owners"})
    applied: dict[str, list] = {}
    withheld = []
    for p in periods:
        pat, owners, nci = (result.value(t, *p) for t in ("pat", "pat_owners", "pat_nci"))
        if None in (pat, owners, nci) or abs(owners + nci - pat) <= tol:
            continue
        oci, t_own, t_nci = (result.value(t, *p) for t in ("oci_net", TCI_OWNERS_KEY, TCI_NCI_KEY))
        if (
            None not in (oci, t_own, t_nci)
            and abs(owners + nci - oci) <= tol
            and abs((t_own - owners) + (t_nci - nci) - pat) <= tol
        ):
            _replace_attribution(result, p, t_own - owners, t_nci - nci, "ATTRIBUTION_TAGGED_AS_OCI")
            applied.setdefault("ATTRIBUTION_TAGGED_AS_OCI", []).append([str(p[0]), str(p[1])])
            continue
        flips = [
            (o, n)
            for o, n, flipped in ((owners, -nci, nci), (-owners, nci, owners))
            if abs(flipped) > tol and abs(o + n - pat) <= tol
        ]
        if len(flips) == 1:
            _replace_attribution(result, p, *flips[0], "ATTRIBUTION_SIGN_FLIP")
            applied.setdefault("ATTRIBUTION_SIGN_FLIP", []).append([str(p[0]), str(p[1])])
            continue
        if abs(nci - pat) <= tol and abs(owners - pat) > tol:  # X91: NCI filed = PAT
            _replace_attribution(result, p, owners, pat - owners, "NCI_TAGGED_AS_PAT")
            applied.setdefault("NCI_TAGGED_AS_PAT", []).append([str(p[0]), str(p[1])])
            continue
        tci = result.value("total_comprehensive_income", *p)
        if nci != 0 and tci is not None and abs(owners + nci - tci) <= tol and abs(tci - pat) > tol:
            # X92: owners + NCI = TCI with NCI != 0. Owners := PAT - NCI as filed; exact when the NCI's share of OCI
            # is 0 (ATUL, ACC, L&T Finance), off by that share otherwise (Brigade Q2 FY27: 193.62 vs PDF 193.60 Cr).
            _replace_attribution(result, p, pat - nci, nci, "OWNERS_AND_NCI_TAGGED_AS_TCI")
            applied.setdefault("OWNERS_AND_NCI_TAGGED_AS_TCI", []).append([str(p[0]), str(p[1])])
            continue
        withheld.append((p, owners, nci, pat))
    for p, owners, nci, pat in withheld:
        kept = [
            f
            for f in result.facts
            if f.canonical_tag in ("pat_owners", "pat_nci") and (f.period_start, f.period_end) == p
        ]
        for f in kept:
            result.facts.remove(f)
        f = kept[0]
        marker = CanonicalFact(ATTRIBUTION_WITHHELD_TAG, f.period_type, f.period_start, f.period_end,
                               f.period_months, "PURE", Decimal(1), "RULE:ATTRIBUTION_WITHHELD")  # fmt: skip
        result.facts.append(marker)
        result.findings.append(
            Issue("IDENTITY", "ATTRIBUTION_WITHHELD",
                  {"period": [str(p[0]), str(p[1])], "owners": str(owners), "nci": str(nci), "pat": str(pat),
                   "tolerance": str(tol)})
        )  # fmt: skip
        applied.setdefault("ATTRIBUTION_WITHHELD", []).append([str(p[0]), str(p[1])])
    for rule, ps in applied.items():
        result.meta.setdefault("rules_applied", []).append({"rule": rule, "periods": ps})


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


def _check_critical(result: ParsedResults, spec: ProfileSpec | None = None) -> None:
    q = result.meta["quarter_period"]
    missing = [t for t in (spec or CORP_SPEC).critical if result.value(t, *q) is None]
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


def _check_identities(result: ParsedResults, spec: ProfileSpec | None = None) -> None:
    spec = spec or CORP_SPEC
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
            # Regulated utilities: PAT(continuing) = PBT - tax + regulatory deferral movement [X42]
            regdef = v("regulatory_deferral_movement") or Decimal(0)
            _check(result, "PBT_MINUS_TAX", pbt - tax + regdef, pat_c, 4, p)
        pat = v("pat")
        if None not in (pat_c, pat):
            # PAT = continuing + discontinued + share of associates/JVs (after PBT) [X42]
            rest = (v("pat_discontinued") or Decimal(0)) + (v("share_of_associates_jv") or Decimal(0))
            _check(result, "PAT_CHAIN", pat_c + rest, pat, 4, p)
        owners, nci = v("pat_owners"), v("pat_nci")
        if None not in (owners, nci, pat):
            _check(result, "OWNERS_PLUS_NCI", owners + nci, pat, ATTRIBUTION_TERMS, p)
        adj, cgo = v("cf_adjustments_total"), v("cash_generated_from_operations")
        if None not in (pbt, adj, cgo):
            # Indirect method starts from PBT (before associates) [X45]
            _check(result, "CF_RECONCILE", pbt + adj, cgo, 3, p)
        cfo, cfi, cff, net = v("cfo"), v("cfi"), v("cff"), v("net_cash_flow")
        if None not in (cfo, cfi, cff, net):
            _check(result, "CF_NET", cfo + cfi + cff, net, 4, p)
        comps = [v(t) for t in spec.expense_components]
        if spec.missing_component_is_zero:  # Division III: every component is filed, absent = not applicable
            comps = [c or Decimal(0) for c in comps]
        if exp is not None and None not in comps:
            _check(result, "EXPENSE_COMPONENTS", sum(comps, Decimal(0)), exp, len(comps) + 1, p)
        if spec.revenue_components:
            rev = v("revenue_from_operations")
            parts = [v(t) or Decimal(0) for t in spec.revenue_components]
            if rev is not None:
                _check(result, "REVENUE_COMPONENTS", sum(parts, Decimal(0)), rev, len(parts) + 1, p)
            oth, inc = v("other_income"), v("total_income")
            if None not in (rev, oth, inc):
                _check(result, "TOTAL_INCOME", rev + oth, inc, 3, p)
    end = result.meta["period_end"]
    assets, eq_liab = (
        result.value("total_assets", end, end),
        result.value("total_equity_and_liabilities", end, end),
    )
    if None not in (assets, eq_liab):
        _check(result, "BALANCE_SHEET", assets, eq_liab, 2, (end,))
    equity, liab = result.value("total_equity", end, end), result.value("total_liabilities", end, end)
    if None not in (assets, equity, liab):
        _check(result, "ASSETS_EQ_EQUITY_PLUS_LIABILITIES", equity + liab, assets, 3, (end,))


def _apply_label_rules(
    inst: Instance, result: ParsedResults, declared: dict, period_end: date, rules: tuple | None = None
) -> None:
    rules = LABEL_RULES if rules is None else rules
    """Sum amounts of members whose Description* label matches a rule; same period checks as other facts."""
    labelled: dict[str, set[tuple]] = {}  # rule -> set of dimension tuples whose label matched
    for f in inst.facts:
        if f.is_numeric or not f.name.startswith("Description"):
            continue
        dims = inst.contexts[f.context_id].dimensions
        if len(dims) != 1:
            continue
        axis = dims[0][0].split(":")[-1]
        for rule, rule_axis, _, _, _, rx in rules:
            if axis == rule_axis and rx.match(f.value_text):
                labelled.setdefault(rule, set()).add(dims)
    for rule, _, element, tag, ptype, _ in rules:
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


@dataclass(frozen=True)
class ProfileSpec:
    """What one accounting profile maps and checks. Machinery (contexts, periods, rules) is shared."""

    profile: str
    duration_tags: dict[str, tuple[str, str]]
    instant_tags: dict[str, tuple[str, str]]
    critical: tuple[str, ...]
    expense_components: tuple[str, ...]
    revenue_components: tuple[str, ...] = ()
    label_rules: tuple = ()
    missing_component_is_zero: bool = False
    post_process: Any = None
    identities: Any = None  # replaces the Ind AS identity set (banks: RBI format)


CORP_SPEC = ProfileSpec(
    "INDAS_CORP", DURATION_TAGS, INSTANT_TAGS, CRITICAL_QUARTER_TAGS, EXPENSE_COMPONENTS, label_rules=LABEL_RULES
)

EPS_TOLERANCE = Decimal("0.05")


def _check_eps(result: ParsedResults) -> None:
    """Filed EPS vs owners' profit / period-end shares [X53]. A warning, not an issue: weighted-average shares
    legitimately differ from period-end shares, so only a gross mismatch (> 5% and > Rs 0.50) is recorded."""
    q = result.meta["quarter_period"]
    filed = result.value("eps_basic", *q)
    profit = result.value("pat_owners", *q)
    if profit is None:
        profit = result.value("pat", *q)
    shares = result.value("shares_from_paid_up", q[1], q[1])
    if None in (filed, profit, shares) or not shares:
        return
    computed = profit / shares
    gap = abs(filed - computed)
    if gap > Decimal("0.50") and gap > EPS_TOLERANCE * abs(computed):
        result.meta.setdefault("warnings", []).append(
            {"code": "EPS_INCONSISTENT", "filed": str(filed), "computed": str(computed.quantize(Decimal("0.01")))}
        )
        # A >10x gap cannot come from weighted-average vs period-end shares: the derived share count itself is
        # wrong (Kotak Q2 FY27 tags FaceValue = 994.79, i.e. paid-up capital in crore) [X61]. Withhold the derived
        # fact so it never feeds market cap or the Reg. 31 cross-check; raw facts stay untouched.
        if not _shares_plausible(result, q, profit, shares):
            result.facts = [f for f in result.facts if f.canonical_tag != "shares_from_paid_up"]
            result.meta["warnings"].append({"code": "SHARES_FROM_PAID_UP_WITHHELD", "shares": str(shares)})


def _shares_plausible(result: ParsedResults, q: tuple, profit: Decimal, shares: Decimal) -> bool:
    """True if any filed EPS implies a share count within 10x of paid-up / face value. TMPV's wrong total EPS still
    agrees via continuing EPS (368 Cr shares both ways); Kotak's mis-tagged face value agrees with nothing."""
    disc = result.value("pat_discontinued", *q) or Decimal(0)
    bases = [(profit, result.value("eps_basic", *q)), (profit - disc, result.value("eps_basic_continuing", *q))]
    for basis, eps in bases:
        if eps and basis:
            implied = basis / eps
            if implied > 0 and Decimal("0.1") <= implied / shares <= 10:
                return True
    return False
