"""Classification of numeric XBRL elements outside the curated canonical tags (C22; since C24 every one of them is
mapped as a line item: the reason code below becomes its `line_item_category`, see financials/line_items.py).

Every numeric element in docs/tag_registry.yaml is either mapped (``mapped_to``) or ``status: EXCLUDED``
with one reason code below. Rules are ordered, deterministic regexes on the element name, optionally scoped
to profiles ("Premium" is insurer revenue but a share-premium reserve in a corporate annual report); the first
match wins. An unmapped numeric element that matches no rule is ``UNCLASSIFIED`` and fails test_docs_sync, so a
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
    # Reg. 34 annual-report notes (REG34_ANNUAL only) [X76]
    "ANNUAL_ASSET_MOVEMENT": "A roll-forward line (additions, disposals, impairment, transfers) of a fixed-asset or "
    "provision schedule whose closing balances are mapped.",
    "ANNUAL_TAX_NOTE": "An income-tax note line (rate reconciliation, current/deferred split) under mapped tax totals.",
    "ANNUAL_SHARE_CAPITAL_NOTE": "A share-capital note line (authorised/issued/called values, issues, holders).",
    "ANNUAL_SHARE_BASED_PAYMENT_NOTE": "An ESOP note line (options, exercise prices, fair values).",
    "ANNUAL_REMUNERATION_NOTE": "A managerial / KMP remuneration disclosure.",
    "ANNUAL_EXPENSE_DETAIL": "A note breakdown of a mapped expense total (employee, other expenses, finance cost).",
    "ANNUAL_INCOME_DETAIL": "A note breakdown of mapped revenue or other income (interest, dividends, gains, splits).",
    "ANNUAL_EQUITY_NOTE": "A statement-of-changes-in-equity or dividend appropriation line.",
}
INSURERS = frozenset({"IRDAI_LIFE", "IRDAI_GENERAL", "INDAS_INSURANCE"})
ANNUAL = frozenset({"REG34_ANNUAL"})
EVENTS = frozenset({"REG30_EVENT"})

# (regex, reason, profiles or None = every profile). Order matters: more specific first.
RULES: tuple[tuple[str, str, frozenset | None], ...] = (
    # per share
    (
        r"(EarningsLossPerShare|EarningsPerShare|EPS|PerShare|AttributableToOrdinaryEquityHolders|WeightedAverageShares"
        r"|DilutiveEffectOfShareOptions)",
        "PER_SHARE_DUPLICATE",
        None,
    ),
    # OCI
    (
        r"(ComprehensiveIncome|ItemThatWillBeReclassified|ItemThatWillNotBeReclassified|ItemsThatWill)",
        "OCI_SUBLINE",
        None,
    ),
    # segments (Ind AS 108 and Ind AS 117 segment tables)
    (
        r"(^(Segment|NetSegment|InterSegment|UnAllocable|Unallocated|OtherUnallocable)|ReportableSegment$"
        r"|RevenuesFromTransactionsWithOtherOperatingSegments|^RevenuePrimaryReportableSegment)",
        "SEGMENT_DISCLOSURE",
        None,
    ),
    # discontinued operations
    (r"DiscontinuedOperations$|OfDiscontinuedOperations", "DISCONTINUED_DETAIL", None),
    # regulator memos and filer ratios
    (
        r"(AmountOfDefault|TotalOutstandingAmountOf|TotalFinancialIndebtedness|DebtEquityRatio|DebtServiceCoverage"
        r"|InterestServiceCoverage|NPAs|PercentageOfBoardApprovedLimits|PercentageOfLimitsUtilized|ContigentLiabilities"
        r"|ReserveExcludingRevaluationReserves|ReservesAndSurplusExcludingRevaluationReserve|SBO)",
        "REGULATORY_MEMO",
        None,
    ),
    # counts
    (
        r"(^NumberOf|^NoOf|NumberOfShares$|VotingRights|LockedIn|^PercentageOfShareholding|^PercentageOfTotalVoting"
        r"|SharesHeldInDematOrUnclaimed|ShareholdingAsAPercentage|^EncumberedShare|^PercentageOfShareholdingByPAC)",
        "NON_FINANCIAL_COUNT",
        None,
    ),
    # subtotals / presentation duplicates
    (
        r"(BeforeExtraordinaryItems|^AdjustmentsForWorkingCapital$|^AdjustmentsToProfitLoss$|FinancialResults$"
        r"|^CurrentFinancialAssets$|^CurrentFinancialLiabilities$|^NoncurrentFinancialAssets$"
        r"|^NoncurrentFinancialLiabilities$|^ProfitBeforeExtraordinaryItemsAndTax$|^PaidUpEquity(Share)?Capital$"
        r"|^OtherAssetsNetOfCurrentLiabilitiesAndProvisions$|^ProfitLossCarriedToBalanceSheet$|^SurplusDeficit$"
        r"|^SurplusShownInTheRevenueAccount$)",
        "DERIVED_SUBTOTAL",
        None,
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
        INSURERS,
    ),
    # Reg. 34 annual notes (scoped: these words mean other things in quarterly/insurer profiles) [X76]
    (
        r"(^Additions|^Acquisitions|Disposals|^Retirements|^Revaluation|^IncreaseDecreaseThrough(?!Transfers"
        r"AndOtherChangesEquity|ChangesInOwnership)|^ChangesIn(PropertyPlant|Goodwill|OtherIntangible|OtherProvisions)"
        r"|DecreaseThrough|^Writedowns|^ImpairmentLoss(?!Reversal.*TradeReceivables|OnNonFinancial|RecognisedInProfitOrLoss$)"
        r"|^ReversalOfImpairment|^Depreciation(PropertyPlant|RecognisedAs|RecognisedIn)|^AmortisationOtherIntangible"
        r"|^ProvisionUsed|^OtherProvisionsCreated|^NewProvisions|^UnusedProvisionReversed|^AdditionalProvisions"
        r"|^IncreaseDecreaseInExistingProvisions|^DeductionsInEquityShareWarrants)",
        "ANNUAL_ASSET_MOVEMENT",
        ANNUAL,
    ),
    (
        r"(Tax(Effect|RateEffect|ExpenseIncomeAt)|^ApplicableTaxRate|^AverageEffectiveTaxRate|^AccountingProfit"
        r"|^CurrentTax|^DeferredTax(?!Assets|Liabilities)|^IncomeTaxExpense|^OtherTax|^OtherComponentsOfDeferredTax"
        r"|ProvisionFor(Corporate|Other)Tax|TaxesPayable|^VATPayable|WithholdingTaxes|^OtherCessTaxes"
        r"|^IncreaseDecreaseInDeferredTax|DeferredTaxLiabilityAssets)",
        "ANNUAL_TAX_NOTE",
        ANNUAL,
    ),
    (
        r"(ShareOptions|SharebasedPayment|ShareBasedPayment|ExercisePrice|WeightedAverageSharePrice"
        r"|WeightedAverageFairValue|OtherEquityInstruments(Outstanding|Expired|Granted))",
        "ANNUAL_SHARE_BASED_PAYMENT_NOTE",
        ANNUAL,
    ),
    (
        r"(^ValueOfShares|Shares(BoughtBack|InCompany|Reserved|IssuedDuring|IssuedPursuant|IssuedByWay)"
        r"|^AmountOf.*(Issue|ShareApplication|SharesIssued)|^CallsUnpaid|EquityShareWarrants|^ForfeitedShares"
        r"|ShareApplication|ApplicationMoneyReceived|^DecreaseIn(AmountOfTreasury|EquityShareCapital|NumberOfShares)"
        r"|^IncreaseDecreaseIn(EquityShareCapital|NumberOf)|^OtherDecreaseInAmountOfShares|^AggregateAmountOfIncrease"
        r"|PercentageOfCapitalReduction|UncalledLiability|(PaidUp|Share)CapitalHeldByForeign|PercentageOf(PaidUp|Share)"
        r"Capital|^AmountRaisedFrom|^AmountRemainingUnutilised|^AmountUtilisedTowards|SharePremium|BonusShares"
        r"|BonusIssue|^AggregateNumberOf)",
        "ANNUAL_SHARE_CAPITAL_NOTE",
        ANNUAL,
    ),
    (
        r"(KeyManagementPersonnel|Remuneration|DirectorsSittingFees|SalaryToDirectors|OtherBenefitsTo(Directors|Manager)"
        r"|CommissionToDirectors|PercentageIncreaseInMedian|AveragePercentileIncrease)",
        "ANNUAL_REMUNERATION_NOTE",
        ANNUAL,
    ),
    (
        r"(Dividend(Appropriation|TaxAppropriation)|^ProposedDividend|^Proposed(Equity|Preference)Dividend"
        r"|Appropriation|^AmountOfDividendsProposed|^PercentageOfProposedDividend|^DividendsProposed"
        r"|^TransferToRetainedEarnings|AdditionsToReserves|DeductionsToReserves|^OtherChangesInEquity"
        r"|^OtherEquityBalances|^IncreaseDecreaseThroughTransfersAndOtherChangesEquity"
        r"|^IncreaseDecreaseThroughChangesInOwnershipInterests|^ChangesInEquity$|RelatingToItemsChargedOrCredited)",
        "ANNUAL_EQUITY_NOTE",
        ANNUAL,
    ),
    (
        r"(CSR|AverageNetProfitForLastThree|^AmountSpent|CorporateSocialResponsibility|^Deposits(Accepted|Matured)"
        r"|Unclaimed|^Unpaid|InvestorEducation|DebenturesClaimed|AsPerIndianGaap|AsPerIndAs|^IndAsAdjustment"
        r"|^NetWorthOfCompany|CapitalInvestmentOnEnergyConservation|EstimatedFinancialEffectOfContingent"
        r"|ClaimsAgainstCompanyNotAcknowledged|^Guarantees$|OtherMoneyForWhichCompanyIsContingentlyLiable|^Commitments$"
        r"|^OtherCommitments$|EstimatedAmountOfContracts|^OtherClaimsContracts$|MarketValueOfQuoted|^AggregateAmountOf"
        r"(Quoted|Unquoted)|^AggregateProvisionForDiminution|^InvestmentIn(Government|Subsidiary)Companies"
        r"|GrossValueOfTransactions?WithRelatedParties|BadDebtsOfRelatedParties|^PublicDepositPayable"
        r"|InterestOnDepositsAccruedAndDueButNotPaid|^InterestUnclaimedAmount)",
        "REGULATORY_MEMO",
        ANNUAL,
    ),
    (
        r"(^Salaries|^Contribution|^Gratuity$|^PensionSchemes$|^LeaveEncashment|StaffWelfare|EmployeeMedical"
        r"|OtherEmployeeRelated|OtherRetirementBenefits|^Rent$|^Repairs|^Insurance$|RatesAndTaxes|Travelling"
        r"|^Cost[A-Z]|BankCharges|LegalProfessional|PrintingStationery|TelephonePostage|^MiscellaneousExpenses$"
        r"|Donations|Warranty|VehicleRunning|TrainingRecruitment|SafetySecurity|Electricity|InformationTechnology"
        r"|ConsumptionOfStores|^Commission|SecondaryPacking|TransportationDistribution|^InterestExpense"
        r"|^InterestCostsIncurred|^BorrowingCosts(Incurred|Recognised)|^OtherBorrowingCosts|^OtherInterestCharges"
        r"|InterestLeaseFinancing|^DepreciationExpense$|^AmortisationExpense$|^DepletionExpense$|InventoryWritedown"
        r"|^PaymentFor|ContingentRentsRecognisedAsExpense|LeaseAndSubleasePayments|DirectOperatingExpense"
        r"|ExpenseArisingFromExploration|ChangesInInventoriesOf|^ChangesInOtherInventories$|MaterialCostContract"
        r"|OverheadCosts|^ContractCost$|^NetProvisionsCharged$|DiscountIssueShares|OtherUnamortisedExpenses"
        r"|^EmployeeShareBased|ImpairmentLossOnNonFinancialAssets|^ImpairmentLossRecognisedInProfitOrLoss$"
        r"|TreatedAsFinanceCosts)",
        "ANNUAL_EXPENSE_DETAIL",
        ANNUAL,
    ),
    (
        r"(^InterestIncome|^Interest(On|From)|^DividendIncome|^IncomeOnBrokerage|^Gains|^GainLoss|^GainOn|^LossOn"
        r"|^NetGainLoss|^Rental|^RevenueFrom(SaleOf|Construction|OtherFinancial|Operations(Finance|Other))"
        r"|^Domestic|^Export|^MiscellaneousOther|^OtherNonoperatingIncome|^OtherOperatingRevenues|ExcessProvisions"
        r"|^LiabilitiesWrittenOff|^Income(From|Insurance|Arising)|RevenueArisingFromExchanges"
        r"|ContingentRentsRecognisedAsIncome|OtherAllowancesDeductionOtherIncome|SurplusOnDisposal"
        r"|RevenueSubsidies)",
        "ANNUAL_INCOME_DETAIL",
        ANNUAL,
    ),
    (
        r"(Balances?(With|Held)|BankDeposits|CashOnHand|ChequesDrafts|^CashAndBankBalances$|FixedDeposits"
        r"|Earmarked|^OtherDepositsWithBanks$|BankOverdrafts|^Accrued|Payable|Advances?(?!ReceivedFromCustomers)"
        r"|SecurityDeposits|DepositsRefundable|^Derivative|^Provision|^OtherProvisions$|Others$|^GoodsInTransit$"
        r"|^TradeReceivables(Gross)?$|AllowanceForBad|TradeReceivables$|GrossAmountDue|ProgressBillings|Retention"
        r"|RevenueReceivedInAdvance|FinanceLease|UnearnedFinanceIncome|^InterestAccrued|DividendReceivable"
        r"|UnbilledRevenue|CostsIncurredAndRecognisedProfits|MineralResources|CapitalSubsidies"
        r"|OtherDifferencesToCashAndCashEquivalents|Capitalised$|CapitalisationRate"
        r"|DeferredAcquisitionCostsArisingFromInsurance|InsuranceContracts|ReinsuranceAssets"
        r"|NoncurrentAssetsOtherThanFinancialInstruments)",
        "BALANCE_SHEET_DETAIL",
        ANNUAL,
    ),
    # Reg. 30 event filings: counts, terms and capital figures that the event rows do not need [E6]
    (r"(^NumberOf|TermOfAppointment|^PaidUpShareCapital(Pre|Post))", "NON_FINANCIAL_COUNT", EVENTS),
    # cash-flow components
    (
        r"(^Adjustments|ClassifiedAs(Operating|Investing|Financing)Activities|^ProceedsFrom|^PaymentsFor|^PaymentsOf"
        r"|^PaymentsTo|^PaymentsFrom|^Purchase|^CashReceipts|^CashPayments?|^CashAdvances|^CashFlows(From|Used)"
        r"|^CashFlowFromExtraordinary|^OtherCash|^Receipts|^OtherInflowsOutflows|^IncomeTaxesPaid$|^RepaymentsOf"
        r"|^OtherAdjustments|^EffectOfForeignExchange|^LoansDisbursed|^RepaymentsReceived|^SalesOfInvestments"
        r"|^ExpensesRelatedToInvestments|^InvestmentsInMoneyMarket|^CashAndCashEquivalentsCashFlowStatement$"
        r"|^ShareOfProfitAndLossFromPartnership|^PaymentForExtraordinary|^ProceedsFromExtraordinary)",
        "CASH_FLOW_DETAIL",
        None,
    ),
    # balance-sheet components
    (
        r"(^Other(Current|Noncurrent|NonFinancial)?(Financial)?(Assets|Liabilities)$|^Provisions(Current|Noncurrent)?$"
        r"|TaxAssets|TaxLiabilities|^Current?Taxes?$|^DeferredTax(Asset|Assets|Liabilities)$|^Deffered|HeldForSale"
        r"|GovernmentGrants|BiologicalAssets|RegulatoryDeferralAccount|^TotalOutstandingDues|^TradePayablesNoncurrent$"
        r"|^Loans(Current|Noncurrent)$|^Payables$|^AdvancesAndOtherAssets$|^DepositsAdvancesAndStaffLoans$"
        r"|^InvestmentsPolicyholders|^InvestmentsShareholders|^ChangeInFairvalue)",
        "BALANCE_SHEET_DETAIL",
        None,
    ),
)
_COMPILED = tuple((re.compile(rx), reason, profiles) for rx, reason, profiles in RULES)

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
    # Equals ExceptionalItemsBeforeTax (mapped) in every annual filing that files both [X76].
    ("REG34_ANNUAL", "ExceptionalItems"): "DERIVED_SUBTOTAL",
    ("REG34_ANNUAL", "TradeReceivables"): "BALANCE_SHEET_DETAIL",
    # Geographic / product split of external revenue (Ind AS 108.33) [X75]
    ("REG34_ANNUAL", "RevenueFromExternalCustomers"): "SEGMENT_DISCLOSURE",
    ("REG34_ANNUAL", "ReclassificationAdjustmentsOnExchangeDifferencesOnTranslationBeforeTax"): "OCI_SUBLINE",
    # Split of the mapped ShareOfProfitLossOfAssociatesAndJointVentures... line.
    ("REG34_ANNUAL", "ShareOfProfitLossOfAssociatesAccountedForUsingEquityMethod"): "DERIVED_SUBTOTAL",
    ("REG34_ANNUAL", "ShareOfProfitLossOfJointVenturesAccountedForUsingEquityMethod"): "DERIVED_SUBTOTAL",
}


def classify(name: str, profile: str | None = None) -> str | None:
    """Reason code for an unmapped numeric element, or None if no rule matches (UNCLASSIFIED)."""
    if (profile, name) in OVERRIDES:
        return OVERRIDES[(profile, name)]
    for rx, reason, profiles in _COMPILED:
        if (profiles is None or profile in profiles) and rx.search(name):
            return reason
    return None
