"""IGAAP_CORP: Integrated Filing results on SEBI's non-Ind AS template (`IntegratedFinance_OtherThanBank`,
Schedule III Division I, Accounting Standards) filed by SME-listed companies [X330-X333].

Routing (X330): the namespace is shared with Ind AS companies that used the wrong template (X89), so the profile is
IGAAP_CORP only when the filing states TypeOfCompany = "SME" (`indas_corp.detect_instance_profile`).

Shared machinery (contexts, declared-period gating, meta, scope, LevelOfRounding tolerance, EPS check, zero-drop line
items) comes from `indas_corp`. The template differs from Ind AS (VERIFIED on every vaulted SME filing, X331):
- the face of the P&L has two items below operating profit: exceptional and extraordinary, each filed signed and
  added: PBEEIT + ExceptionalItems = ProfitBeforeExtraordinaryItemsAndTax; + ExtraordinaryItems = ProfitBeforeTax.
  There is no prior-period item element; Indian GAAP has no OCI, so no OCI / TCI facts exist.
- the profit chain ends after minority interest: PBT - TaxExpense = ProfitLossForThePeriodFromContinuingOperations;
  + discontinuing after tax = ProfitLossForPeriodBeforeMinorityInterest; + ShareOfProfitLossOfAssociates +
  ProfitLossOfMinorityInterest = ProfitLossForThePeriod (the owners' profit). The minority line is filed signed as
  its effect on the owners' profit (negative when the subsidiaries' minority holders earn a profit).
- the balance sheet is Division I: ShareholdersFunds (share capital + reserves and surplus + share warrants money),
  share application money, MinorityInterest, long-/short-term borrowings and provisions; Assets.
Derived (X332, rule IGAAP_ATTRIBUTION): pat (owners + minority, as Ind AS ProfitLossForPeriod) = ProfitLossForThePeriod
- ProfitLossOfMinorityInterest; in a consolidated filing pat_owners = ProfitLossForThePeriod and pat_nci =
- ProfitLossOfMinorityInterest; total_equity = ShareholdersFunds + MinorityInterest. Nothing else is derived, and the
filed values stay under their own tags. Half-yearly SME periods (6 months) are stored as filed (period_months 6).
"""

from __future__ import annotations

from decimal import Decimal

from financials.parsers.indas_corp import (
    DURATION_TAGS,
    INSTANT_TAGS,
    CanonicalFact,
    Issue,
    ParsedResults,
    ProfileSpec,
    _check,
    parse_with_spec,
)

# Ind AS element names the template shares with the same meaning (P&L lines, share data, cash flow).
_SHARED_DURATION = (
    "RevenueFromOperations", "OtherIncome", "Income", "CostOfMaterialsConsumed", "PurchasesOfStockInTrade",
    "ChangesInInventoriesOfFinishedGoodsWorkInProgressAndStockInTrade", "EmployeeBenefitExpense", "FinanceCosts",
    "OtherExpenses", "Expenses", "ProfitBeforeTax", "CurrentTax", "DeferredTax", "TaxExpense",
    "PaidUpValueOfEquityShareCapital", "FaceValueOfEquityShareCapital",
    "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
    "DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
    "CashFlowsFromUsedInOperations", "IncomeTaxesPaidRefundClassifiedAsOperatingActivities",
    "CashFlowsFromUsedInOperatingActivities", "CashFlowsFromUsedInInvestingActivities",
    "CashFlowsFromUsedInFinancingActivities", "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
    "PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities",
    "ProceedsFromSalesOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
    "InterestPaidClassifiedAsOperatingActivities", "InterestPaidClassifiedAsFinancingActivities",
    "InterestReceivedClassifiedAsOperatingActivities", "InterestReceivedClassifiedAsInvestingActivities",
    "DividendsPaidClassifiedAsFinancingActivities", "AdjustmentsForSharebasedPayments",
    "AdjustmentsForReconcileProfitLoss", "AdjustmentsForDepreciationAndAmortisationExpense",
    "AdjustmentsForFinanceCosts", "AdjustmentsForDividendIncome", "AdjustmentsForDecreaseIncreaseInInventories",
    "AdjustmentsForDecreaseIncreaseInOtherCurrentAssets", "AdjustmentsForIncreaseDecreaseInOtherCurrentLiabilities",
    "DividendsReceivedClassifiedAsOperatingActivities", "DividendsReceivedClassifiedAsInvestingActivities",
    "ProceedsFromBorrowingsClassifiedAsFinancingActivities", "RepaymentsOfBorrowingsClassifiedAsFinancingActivities",
    "IncreaseDecreaseInCashAndCashEquivalentsBeforeEffectOfExchangeRateChanges",
    "EffectOfExchangeRateChangesOnCashAndCashEquivalents", "IncreaseDecreaseInCashAndCashEquivalents",
)  # fmt: skip

IGAAP_DURATION_TAGS: dict[str, tuple[str, str]] = {
    **{k: DURATION_TAGS[k] for k in _SHARED_DURATION},
    "DepreciationAndAmortisationExpense": ("depreciation_amortisation", "INR"),
    "ProfitBeforeExceptionalAndExtraordinaryItemsAndTax": ("profit_before_exceptional_and_tax", "INR"),
    "ExceptionalItems": ("exceptional_items", "INR"),
    "ProfitBeforeExtraordinaryItemsAndTax": ("profit_before_extraordinary_and_tax", "INR"),
    "ExtraordinaryItems": ("extraordinary_items", "INR"),
    "ProfitLossForThePeriodFromContinuingOperations": ("pat_continuing", "INR"),
    "ProfitLossFromDiscontinuingOperationsBeforeTax": ("discontinued_pbt", "INR"),
    "TaxExpenseOfDiscontinuingOperations": ("discontinued_tax", "INR"),
    "ProfitLossFromDiscontinuingOperationAfterTax": ("pat_discontinued", "INR"),
    "ProfitLossForPeriodBeforeMinorityInterest": ("pat_before_minority", "INR"),
    "ShareOfProfitLossOfAssociates": ("share_of_associates_jv", "INR"),
    # signed as filed: its effect on the owners' profit [X331]; pat_nci is its negation (IGAAP_ATTRIBUTION)
    "ProfitLossOfMinorityInterest": ("pat_minority_interest_line", "INR"),
    "ProfitLossForThePeriod": ("pat_after_minority", "INR"),
}

_SHARED_INSTANT = (
    "PropertyPlantAndEquipment", "DeferredTaxAssetsNet", "DeferredTaxLiabilitiesNet", "NoncurrentInvestments",
    "NoncurrentAssets", "Inventories", "CurrentInvestments", "CashAndCashEquivalents",
    "BankBalanceOtherThanCashAndCashEquivalents", "CurrentAssets", "Assets", "CashAndCashEquivalentsCashFlowStatement",
    "NoncurrentLiabilities", "CurrentLiabilities", "EquityAndLiabilities",
)  # fmt: skip

IGAAP_INSTANT_TAGS: dict[str, tuple[str, str]] = {
    **{k: INSTANT_TAGS[k] for k in _SHARED_INSTANT},
    "ShareCapital": ("equity_share_capital", "INR"),
    "ReservesAndSurplus": ("other_equity", "INR"),  # Division I reserves and surplus (Ind AS: other equity)
    "ShareholdersFunds": ("equity_attributable_to_owners", "INR"),
    "MinorityInterest": ("non_controlling_interest", "INR"),
    "LongTermBorrowings": ("borrowings_noncurrent", "INR"),
    "ShortTermBorrowings": ("borrowings_current", "INR"),
    "TradePayables": ("trade_payables_current", "INR"),  # Division I trade payables are current liabilities
    "TradeReceivables": ("trade_receivables_current", "INR"),  # ... and trade receivables current assets
    "IntangibleAssets": ("other_intangibles", "INR"),
    "PropertyPlantAndEquipmentCapitalWorkInProgress": ("cwip", "INR"),
    "IntangibleAssetsUnderDevelopmentOrWorkInProgress": ("intangibles_under_development", "INR"),
}

IGAAP_CRITICAL = (
    "revenue_from_operations", "other_income", "total_income", "total_expenses", "finance_costs",
    "depreciation_amortisation", "profit_before_exceptional_and_tax", "pbt", "tax_expense", "pat",
)  # fmt: skip

IGAAP_EXPENSE_COMPONENTS = (
    "cost_of_materials_consumed", "purchases_of_stock_in_trade", "changes_in_inventories", "employee_benefit_expense",
    "finance_costs", "depreciation_amortisation", "other_expenses",
)  # fmt: skip

ATTRIBUTION_RULE = "IGAAP_ATTRIBUTION"


def derive_igaap(result: ParsedResults) -> None:
    """IGAAP_ATTRIBUTION [X332]: Ind AS-comparable profit lines from the Division I chain, per validated period.
    pat = ProfitLossForThePeriod - ProfitLossOfMinorityInterest (absent minority = 0); consolidated: pat_owners =
    ProfitLossForThePeriod, pat_nci = -ProfitLossOfMinorityInterest. Period-end: total_equity = ShareholdersFunds +
    MinorityInterest (absent = 0), total_liabilities = non-current + current liabilities."""
    periods = sorted({(f.period_start, f.period_end, f.period_months) for f in result.facts
                      if f.canonical_tag == "pat_after_minority"})  # fmt: skip
    consolidated = result.meta.get("scope") == "CONSOLIDATED"
    for start, end, months in periods:
        after = result.value("pat_after_minority", start, end)
        minority = result.value("pat_minority_interest_line", start, end) or Decimal(0)
        out = [("pat", after - minority, "DERIVED:ProfitLossForThePeriod-ProfitLossOfMinorityInterest")]
        if consolidated:
            out += [("pat_owners", after, "DERIVED:ProfitLossForThePeriod"),
                    ("pat_nci", -minority, "DERIVED:-ProfitLossOfMinorityInterest")]  # fmt: skip
        for tag, value, src in out:
            result.facts.append(CanonicalFact(tag, "DURATION", start, end, months, "INR", value, src))
    end = result.meta["period_end"]
    funds = result.value("equity_attributable_to_owners", end, end)
    if funds is not None:
        nci = result.value("non_controlling_interest", end, end) or Decimal(0)
        result.facts.append(CanonicalFact("total_equity", "INSTANT", end, end, None, "INR", funds + nci,
                                          "DERIVED:ShareholdersFunds+MinorityInterest"))  # fmt: skip
    ncl, cl = result.value("noncurrent_liabilities", end, end), result.value("current_liabilities", end, end)
    if ncl is not None and cl is not None:
        result.facts.append(CanonicalFact("total_liabilities", "INSTANT", end, end, None, "INR", ncl + cl,
                                          "DERIVED:NoncurrentLiabilities+CurrentLiabilities"))  # fmt: skip
    result.meta.setdefault("rules_applied", []).append({"rule": ATTRIBUTION_RULE, "consolidated": consolidated})


SCALED_RULE = "AMOUNTS_AND_EPS_SCALED"
EPS_TO_FACE_MAX = Decimal(1000)  # no listed company earns 1,000x its face value per share in one period
SCALE_FIT = Decimal("0.10")


def _check_scaled_amounts(result: ParsedResults) -> None:
    """Rule AMOUNTS_AND_EPS_SCALED [X333]: every amount of the filing, its EPS included, is a power of ten (>= 1,000)
    too large, so the identities and the EPS check still hold. Read from the filing alone: basic EPS above 1,000x the
    face value, and the share count implied by profit / EPS a power of ten (within 10%) below paid-up / face value.
    GICL Q2 FY26 standalone (14 Nov 2025): EPS 61,000 on face value 10, PAT 1,818,800,000,000, paid-up
    27,988,647,000,000 (Rs 279,886,470 x 1e5); its re-filing of 15 Jan 2026 states EPS 0.61, PAT 18,189,000 and
    paid-up 279,886,000. Blocking: the filing is quarantined whole (raw blob kept), never rescaled here."""
    q = result.meta["quarter_period"]
    eps, face = result.value("eps_basic", *q), result.value("face_value_per_share", *q)
    paid_up = result.value("paid_up_equity_capital", *q)
    profit = result.value("pat_owners", *q)
    profit = result.value("pat", *q) if profit is None else profit
    if not eps or not face or not paid_up or not profit or abs(eps) <= EPS_TO_FACE_MAX * face:
        return
    ratio = (paid_up / face) / abs(profit / eps)
    if ratio < 1000:
        return
    nearest = Decimal(10) ** int(ratio.log10().to_integral_value())
    if abs(ratio / nearest - 1) <= SCALE_FIT:
        result.issues.append(Issue("PARSE", "AMOUNTS_SCALED", {
            "rule": SCALED_RULE, "eps_basic": str(eps), "face_value": str(face), "paid_up": str(paid_up),
            "profit": str(profit), "factor": str(nearest), "ratio": str(ratio.quantize(Decimal("0.01")))}))  # fmt: skip


def check_igaap_identities(result: ParsedResults) -> None:
    """The Division I profit chain and statement identities [X331], each to the LevelOfRounding tolerance, then
    rule AMOUNTS_AND_EPS_SCALED [X333]."""
    _check_scaled_amounts(result)
    for p in {result.meta["quarter_period"], result.meta["ytd_period"]}:
        v = lambda tag, p=p: result.value(tag, *p)  # noqa: E731
        z = lambda tag, p=p: result.value(tag, *p) or Decimal(0)  # noqa: E731
        if v("pbt") is None:
            continue
        inc, exp, pbeeit = v("total_income"), v("total_expenses"), v("profit_before_exceptional_and_tax")
        if None not in (v("revenue_from_operations"), v("other_income"), inc):
            _check(result, "TOTAL_INCOME", z("revenue_from_operations") + z("other_income"), inc, 3, p)
        if None not in (inc, exp, pbeeit):
            _check(result, "INCOME_MINUS_EXPENSES", inc - exp, pbeeit, 3, p)
        pbxo = v("profit_before_extraordinary_and_tax")
        if pbeeit is not None and pbxo is not None:
            _check(result, "IGAAP_EXCEPTIONAL", pbeeit + z("exceptional_items"), pbxo, 3, p)
            _check(result, "IGAAP_EXTRAORDINARY", pbxo + z("extraordinary_items"), v("pbt"), 3, p)
        if None not in (v("tax_expense"), v("pat_continuing")):
            _check(result, "PBT_MINUS_TAX", z("pbt") - z("tax_expense"), v("pat_continuing"), 3, p)
        if None not in (v("pat_continuing"), v("pat_before_minority")):
            _check(result, "IGAAP_BEFORE_MINORITY", z("pat_continuing") + z("pat_discontinued"),
                   v("pat_before_minority"), 3, p)  # fmt: skip
        if None not in (v("pat_before_minority"), v("pat_after_minority")):
            rest = z("share_of_associates_jv") + z("pat_minority_interest_line")
            _check(result, "IGAAP_AFTER_MINORITY", z("pat_before_minority") + rest, v("pat_after_minority"), 4, p)
        comps = [v(t) for t in IGAAP_EXPENSE_COMPONENTS]
        if exp is not None and None not in comps:
            _check(result, "EXPENSE_COMPONENTS", sum(comps, Decimal(0)), exp, len(comps) + 1, p)
        cfo, cfi, cff, net = v("cfo"), v("cfi"), v("cff"), v("net_cash_flow")
        if None not in (cfo, cfi, cff, net):
            _check(result, "CF_NET", cfo + cfi + cff, net, 4, p)
    end = result.meta["period_end"]
    assets, eq_liab = (result.value(t, end, end) for t in ("total_assets", "total_equity_and_liabilities"))
    if None not in (assets, eq_liab):
        _check(result, "BALANCE_SHEET", assets, eq_liab, 2, (end,))


IGAAP_SPEC = ProfileSpec(
    "IGAAP_CORP",
    IGAAP_DURATION_TAGS,
    IGAAP_INSTANT_TAGS,
    IGAAP_CRITICAL,
    IGAAP_EXPENSE_COMPONENTS,
    identities=check_igaap_identities,
    derive=derive_igaap,
)


def parse_igaap_corp_results(data: bytes) -> ParsedResults:
    return parse_with_spec(data, IGAAP_SPEC)
