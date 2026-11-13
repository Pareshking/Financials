"""Audit of numeric XBRL elements that the production parsers do not map to a canonical tag (C22).

Every numeric element in docs/tag_registry.yaml is either mapped (``mapped_to``) or ``status: EXCLUDED``
with one reason code below. Rules are ordered, deterministic regexes on the element name; the first match
wins. An unmapped numeric element that matches no rule is ``UNCLASSIFIED`` and fails test_docs_sync, so a
new element can never be silently ignored: it must be mapped or given a rule here.

Excluded elements are not lost: every fact is stored verbatim in ``raw_xbrl_facts`` (invariant 3).
"""

from __future__ import annotations

import re

REASONS = {
    "PER_SHARE_DUPLICATE": "A per-share or per-unit restatement of a mapped amount (EPS variants, per-share equity).",
    "OCI_SUBLINE": "A component or attribution of other comprehensive income; the OCI and TCI totals are mapped.",
    "DERIVED_SUBTOTAL": "A subtotal or presentation duplicate of mapped lines (financial-assets subtotals, "
    "'before extraordinary items' totals, results-format duplicates of balance-sheet lines).",
    "REGULATORY_MEMO": "A regulator-mandated memo or filer-computed ratio (debt-default disclosures, DSCR/ISCR, "
    "filer D/E, fund-wise NPAs, solvency/limit percentages); we compute our own ratios.",
    "NON_FINANCIAL_COUNT": "A count or quantity that is not money (shares, voting rights, complaints).",
    "CASH_FLOW_DETAIL": "A component line of a mapped cash-flow total (CFO/CFI/CFF); the total carries the value.",
    "BALANCE_SHEET_DETAIL": "A component line of mapped balance-sheet totals (provisions, tax assets, other "
    "assets/liabilities, held-for-sale, grants, biological assets).",
    "SEGMENT_DISCLOSURE": "An Ind AS 108 segment line, parsed by parsers/segments.py, not a canonical fact.",
    "DISCONTINUED_DETAIL": "A detail of discontinued operations; pat_discontinued and discontinued_pbt are mapped.",
    "INSURANCE_SCHEDULE_DETAIL": "An IRDAI revenue/appropriation/fund-analysis schedule line under a mapped total.",
}

# (regex, reason). Order matters: more specific first.
RULES: tuple[tuple[str, str], ...] = (
    # per share
    (r"(EarningsLossPerShare|EarningsPerShare|EPS|PerShare)", "PER_SHARE_DUPLICATE"),
    # OCI
    (r"(ComprehensiveIncome|ItemThatWillBeReclassified|ItemThatWillNotBeReclassified|ItemsThatWill)", "OCI_SUBLINE"),
    # segments (Ind AS 108 and Ind AS 117 segment tables)
    (r"^(Segment|NetSegment|InterSegment|UnAllocable|Unallocated|OtherUnallocable)", "SEGMENT_DISCLOSURE"),
    # discontinued operations
    (r"DiscontinuedOperations$|OfDiscontinuedOperations", "DISCONTINUED_DETAIL"),
    # regulator memos and filer ratios
    (
        r"(AmountOfDefault|TotalOutstandingAmountOf|TotalFinancialIndebtedness|DebtEquityRatio|DebtServiceCoverage"
        r"|InterestServiceCoverage|NPAs|PercentageOfBoardApprovedLimits|PercentageOfLimitsUtilized|ContigentLiabilities"
        r"|ReserveExcludingRevaluationReserves|ReservesAndSurplusExcludingRevaluationReserve|SBO)",
        "REGULATORY_MEMO",
    ),
    # counts
    (
        r"(^NumberOf|^NoOf|NumberOfShares$|VotingRights|LockedIn|^PercentageOfShareholding|^PercentageOfTotalVoting"
        r"|SharesHeldInDematOrUnclaimed|ShareholdingAsAPercentage|^EncumberedShare|^PercentageOfShareholdingByPAC)",
        "NON_FINANCIAL_COUNT",
    ),
    # subtotals / presentation duplicates
    (
        r"(BeforeExtraordinaryItems|^AdjustmentsForWorkingCapital$|^AdjustmentsToProfitLoss$|FinancialResults$"
        r"|^CurrentFinancialAssets$|^CurrentFinancialLiabilities$|^NoncurrentFinancialAssets$"
        r"|^NoncurrentFinancialLiabilities$|^ProfitBeforeExtraordinaryItemsAndTax$|^PaidUpEquity(Share)?Capital$"
        r"|^OtherAssetsNetOfCurrentLiabilitiesAndProvisions$|^ProfitLossCarriedToBalanceSheet$|^SurplusDeficit$"
        r"|^SurplusShownInTheRevenueAccount$)",
        "DERIVED_SUBTOTAL",
    ),
    # insurance schedules (before generic CF/BS rules: many insurer lines start with Payments/Receipts/Provisions)
    (
        r"(Policyholder|Shareholders?(Account|Fund)|LinkedLiabilities|Bonus|Commission|Premium|Reinsurance"
        r"|InsuranceContract|InsuranceReserve|PolicyLiabilities|FairValueChangeAccount|FairvalueAccount"
        r"|TransferToReserves|TransferredToRetainedEarning|TransferFrom|TransferOf|OpeningBalanceAndApproproations"
        r"|InvestmentContractLiabilities|WithUnrealisedGains|WithoutUnrealisedGains|WithoutUnrealizedGains"
        r"|Discontinuance|DiscontinuedOnAccountOfNonPayment|GoodsAndServiceTaxChargeOnLinkedCharges|AssetsHeldToCover"
        r"|NonDistributableRetainedEarning|RevaluationReserveInvestmentProperty|DebitBalanceInProfitAndLoss"
        r"|IncomeUnderShareholdersAccount|InvestmentsShareholderFund|PaymentsOfClaims|CoInsurers|ReInsurers"
        r"|FinanceIncomeExpensesFrom|InvestmentRevenueOnFinancialAssets|OtherInvestmentRevenue"
        r"|RevenueFromInvestmentManagementServices|ExpensesOtherThanThoseRelatedToInsurance"
        r"|NonOperating|ProvisionsForDiminution|ProvisionsForDoubtfulDebts|ImpairmentLossOnFinancialAssets"
        r"|MiscellaneousExpenditureToTheExtent|PreliminaryAndPreOperative|AdministrationExpenses"
        r"|AdvertisementAndPublicity|OtherFinanceCosts|^FinalDividend$|^InterimDividend$|GoodAndServiceTaxPaid)",
        "INSURANCE_SCHEDULE_DETAIL",
    ),
    # cash-flow components
    (
        r"(^Adjustments|ClassifiedAs(Operating|Investing|Financing)Activities|^ProceedsFrom|^PaymentsFor|^PaymentsOf"
        r"|^PaymentsTo|^PaymentsFrom|^Purchase|^CashReceipts|^CashPayments?|^CashAdvances|^CashFlows(From|Used)"
        r"|^CashFlowFromExtraordinary|^OtherCash|^Receipts|^OtherInflowsOutflows|^IncomeTaxesPaid$|^RepaymentsOf"
        r"|^OtherAdjustments|^EffectOfForeignExchange|^LoansDisbursed|^RepaymentsReceived|^SalesOfInvestments"
        r"|^ExpensesRelatedToInvestments|^InvestmentsInMoneyMarket|^CashAndCashEquivalentsCashFlowStatement$"
        r"|^ShareOfProfitAndLossFromPartnership|^PaymentForExtraordinary|^ProceedsFromExtraordinary)",
        "CASH_FLOW_DETAIL",
    ),
    # balance-sheet components
    (
        r"(^Other(Current|Noncurrent|NonFinancial)?(Financial)?(Assets|Liabilities)$|^Provisions(Current|Noncurrent)?$"
        r"|TaxAssets|TaxLiabilities|^Current?Taxes?$|^DeferredTax(Asset|Assets|Liabilities)$|^Deffered|HeldForSale"
        r"|GovernmentGrants|BiologicalAssets|RegulatoryDeferralAccount|^TotalOutstandingDues|^TradePayablesNoncurrent$"
        r"|^Loans(Current|Noncurrent)$|^Payables$|^AdvancesAndOtherAssets$|^DepositsAdvancesAndStaffLoans$"
        r"|^InvestmentsPolicyholders|^InvestmentsShareholders|^ChangeInFairvalue)",
        "BALANCE_SHEET_DETAIL",
    ),
)
_COMPILED = tuple((re.compile(rx), reason) for rx, reason in RULES)

# Profile-specific decisions where the generic name means something else (checked against fixtures, C22).
OVERRIDES: dict[tuple[str, str], str] = {
    # IRDAI format: `Assets` = ApplicationOfFunds (net of current liabilities), already mapped as total_assets.
    ("IRDAI_LIFE", "Assets"): "DERIVED_SUBTOTAL",
    ("IRDAI_GENERAL", "Assets"): "DERIVED_SUBTOTAL",
    # = InvestmentsShareholders + InvestmentsPolicyholders (both mapped); exceeds the net total for GI.
    ("IRDAI_LIFE", "Investments"): "DERIVED_SUBTOTAL",
    ("IRDAI_GENERAL", "Investments"): "DERIVED_SUBTOTAL",
    # Component of the mapped CurrentLiabilitiesAndProvisions.
    ("IRDAI_LIFE", "CurrentLiabilities"): "BALANCE_SHEET_DETAIL",
    ("IRDAI_GENERAL", "CurrentLiabilities"): "BALANCE_SHEET_DETAIL",
    # Component of mapped operating expenses in the revenue account.
    ("IRDAI_LIFE", "OtherOperatingExpenses"): "INSURANCE_SCHEDULE_DETAIL",
    ("IRDAI_GENERAL", "OtherOperatingExpenses"): "INSURANCE_SCHEDULE_DETAIL",
    # Filed as 0 beside the mapped ShareCapital (Star Health); a presentation duplicate.
    ("INDAS_INSURANCE", "EquityShareCapital"): "DERIVED_SUBTOTAL",
}


def classify(name: str, profile: str | None = None) -> str | None:
    """Reason code for an unmapped numeric element, or None if no rule matches (UNCLASSIFIED)."""
    if (profile, name) in OVERRIDES:
        return OVERRIDES[(profile, name)]
    for rx, reason in _COMPILED:
        if rx.search(name):
            return reason
    return None
