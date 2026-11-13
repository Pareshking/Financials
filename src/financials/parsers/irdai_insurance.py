"""Insurer results: IRDAI life, IRDAI general and Ind AS 117 insurance taxonomies [X62-X66].

Three element sets, one shared machinery (contexts, period gating against declared dates, meta, EPS check).
All identities below are VERIFIED to the rupee on Batch 6 (Q2 FY27) filings:

IRDAI_LIFE (`IntegratedFinance_LI`; HDFC Life, SBI Life, LIC): policyholders' revenue account
  Income = NetPremium + IncomeFromInvestmentsNet + PH other income + transfer from shareholders
  ExpensesOfManagement = NetCommission + OperatingExpensesRelatedToInsuranceBusiness
  Expenses = EoM + provisions + GST on linked charges + PH tax + BenefitsPaidNet + ChangeInActuarialLiability
  NetSurplus = Income - Expenses = transfer to shareholders + funds for future appropriation
  shareholders' account: Income = transfer from PH + investment + other; PBT = income - expenses; PAT = PBT - tax
  balance sheet: Sources of funds = Application of funds; NetCurrentAssets = CurrentAssets - CL & provisions
IRDAI_GENERAL (`IntegratedFinance_GI`; ICICI Lombard, New India, GIC Re):
  OperatingIncome = PremiumEarned + IncomeFromInvestmentsNet + OtherIncome
  OperatingExpenses = NetCommission + OpEx related to insurance + PremiumDeficiency + IncurredClaims
  Underwriting = PremiumEarned - OperatingExpenses; OperatingProfit = OperatingIncome - OperatingExpenses
  (the two provision lines are memo lines outside it: New India 22.85 Cr)
  shareholders' account -> PBT -> PAT; Sources of funds = Application of funds
INDAS_INSURANCE (`IntegratedFinance_InsuranceCompaniesIndAS`, Ind AS 117; Star Health, Go Digit):
  InsuranceRevenue = PAA + non-PAA; InsuranceServiceExpenses = claims + onerous + adjustments to LIC + employee
  + commission + other + acquisition amortisation; ServiceResult = Revenue - ServiceExpenses + net reinsurance
  NetFinanceResult = InvestmentIncome + insurance finance income/expense + investment-contract movement
  PBEIT = ServiceResult + NetFinanceResult + other net; PBT; PAT; TCI; Assets = Equity + Liabilities
"""

from __future__ import annotations

from decimal import Decimal

from financials.parsers.indas_corp import ParsedResults, ProfileSpec, _check, parse_with_spec

INR = "INR"


def _tags(pairs: dict[str, str], unit: str = INR) -> dict[str, tuple[str, str]]:
    return {element: (tag, unit) for element, tag in pairs.items()}


_CASH_FLOW = _tags(
    {
        "CashFlowsFromUsedInOperatingActivities": "cfo",
        "CashFlowsFromUsedInInvestingActivities": "cfi",
        "CashFlowsFromUsedInFinancingActivities": "cff",
        "IncreaseDecreaseInCashAndCashEquivalentsBeforeEffectOfExchangeRateChanges": "net_cash_flow",
        "IncreaseDecreaseInCashAndCashEquivalents": "net_cash_flow_after_fx",
    }
)

LIFE_DURATION = {
    **_CASH_FLOW,
    **_tags(
        {
            "IncomeFirstYearPremium": "first_year_premium",
            "IncomeRenewalPremium": "renewal_premium",
            "IncomeSinglePremium": "single_premium",
            "GrossPremiumIncome": "gross_premium",
            "NetPremiumIncome": "net_premium",
            "IncomeFromInvestmentsNet": "investment_income_policyholders",
            "PolicyholdersAccountOtherIncome": "other_income_policyholders",
            "TransferOfFundsFromShareholdersAccount": "transfer_from_shareholders",
            "Income": "total_income",
            "NetCommission": "net_commission",
            "EmployeesRemunerationAndWelfareExpenses": "employee_benefit_expense",
            "OperatingExpensesRelatedToInsuranceBusiness": "operating_expenses_insurance",
            "ExpensesOfManagement": "expenses_of_management",
            "ProvisionForTax": "tax_policyholders",
            "BenefitsPaidNet": "benefits_paid_net",
            "ChangeInActuarialLiability": "change_in_actuarial_liability",
            "Expenses": "total_expenses",
            "NetSurplusDeficit": "net_surplus",
            "TransferredToShareholdersAccount": "transfer_to_shareholders",
            "FundsForFutureAppropriation": "funds_for_future_appropriation_flow",
            "InvestmentIncome": "investment_income_shareholders",
            "ShareholdersAccountOtherIncome": "other_income",
            "ShareholdersAccountIncome": "shareholders_income",
            "ShareholdersAccountExpenses": "shareholders_expenses",
            "ProfitLossBeforeTax": "pbt",
            "ProvisionsForTaxes": "tax_expense",
            "ProfitLossAfterTaxBeforeExtraordinaryItems": "pat_before_extraordinary",
            "ExtraordinaryItemsNetOfTaxExpenses": "extraordinary_items",
            "ProfitLossAfterTaxAndExtraordinaryItems": "pat",
        }
    ),
    **_tags(
        {
            "BasicAndDilutedEPSAfterExtraordinaryItemsNetOfTaxExpenseForThePeriodNotToBeAnnualized": "eps_basic",
        },
        "INR_PER_SHARE",
    ),
    **_tags(
        {
            "SolvencyRatio": "solvency_ratio",
            "ExpensesOfManagementRatio": "expenses_of_management_ratio",
            "PersistencyRatio13ThMonth": "persistency_13m",
            "PersistencyRatio25ThMonth": "persistency_25m",
            "PersistencyRatio37ThMonth": "persistency_37m",
            "PersistencyRatio49ThMonth": "persistency_49m",
            "PersistencyRatio61ThMonth": "persistency_61m",
            "ConservationRatio": "conservation_ratio",
            "PercentageOfSharesHeldByGovernmentOfIndiaInCaseOfPublicSectorInsuranceCompanies": "govt_holding_pct",
        },
        "RATIO",
    ),
}

_IRDAI_BS = _tags(
    {
        "ShareCapital": "equity_share_capital",
        "ReservesAndSurplus": "reserves_and_surplus",
        "ShareApplicationMoneyReceivedPendingAllotmentOfShares": "share_application_money",
        "Borrowings": "borrowings_insurer",
        "SourcesOfFunds": "total_equity_and_liabilities",
        "ApplicationOfFunds": "total_assets",
        "InvestmentsShareholders": "investments_shareholders",
        "InvestmentsPolicyholders": "investments_policyholders",
        "Loans": "loans",
        "FixedAssets": "fixed_assets",
        "CashAndBankBalances": "cash_and_bank",
        "CurrentAssets": "current_assets",
        "CurrentLiabilitiesAndProvisions": "current_liabilities_and_provisions",
        "NetCurrentAssets": "net_current_assets",
    }
)

LIFE_INSTANT = {
    **_IRDAI_BS,
    **_tags(
        {
            "PolicyholdersFunds": "policyholders_funds",
            "FundsForFutureAppropriations": "funds_for_future_appropriation",
            "AssetsHeldToCoverLinkLiabilities": "assets_held_for_linked_liabilities",
            "ShareholdersFunds": "shareholders_funds",
        }
    ),
}

GENERAL_DURATION = {
    **_CASH_FLOW,
    **_tags(
        {
            "GrossPremiumsWritten": "gross_premium",
            "NetPremiumWritten": "net_premium_written",
            "PremiumEarned": "net_premium_earned",
            "IncomeFromInvestmentsNet": "investment_income_policyholders",
            "OtherIncome": "other_income_policyholders",
            "OperatingIncome": "operating_income",
            "NetCommission": "net_commission",
            "EmployeesRemunerationAndWelfareExpenses": "employee_benefit_expense",
            "OperatingExpensesRelatedToInsuranceBusiness": "operating_expenses_insurance",
            "PremiumDeficiency": "premium_deficiency",
            "ClaimsPaid": "claims_paid",
            "ChangeInOutstandingClaims": "change_in_outstanding_claims",
            "IncurredClaims": "claims_incurred",
            "OperatingExpenses": "operating_expenses",
            "UnderwritingProfitOrLoss": "underwriting_result",
            "OperatingProfitOrLoss": "operating_profit_insurance",
            "TransferToProfitAndLossAccount": "transfer_to_pl",
            "ShareholdersAccountTransferFromPolicyholdersFund": "transfer_from_policyholders",
            "ShareholdersAccountIncomeFromInvestments": "investment_income_shareholders",
            "ShareholdersAccountOtherIncome": "other_income",
            "IncomeInShareholdersAccount": "shareholders_income",
            "NonOperatingExpense": "shareholders_expenses",
            "ProfitOrLossBeforeExtraordinaryItems": "pat_before_extraordinary_pretax",
            "ExtraordinaryItems": "extraordinary_items",
            "ProfitOrLossBeforeTax": "pbt",
            "ProvisionForTax": "tax_expense",
            "ProfitLossAfterTax": "pat",
        }
    ),
    **_tags(
        {
            "BasicAndDilutedEPSAfterExtraordinaryItemsNetOfTaxExpenseForThePeriodNotToBeAnnualized": "eps_basic",
        },
        "INR_PER_SHARE",
    ),
    **_tags(
        {
            "SolvencyRatio": "solvency_ratio",
            "ExpensesOfManagementRatio": "expenses_of_management_ratio",
            "IncurredClaimRatio": "claims_ratio_filed",
            "NetRetentionRatio": "net_retention_ratio",
            "CombinedRatio": "combined_ratio_filed",
            "PercentageOfGovernmentHolding": "govt_holding_pct",
        },
        "RATIO",
    ),
}

GENERAL_INSTANT = {
    **_IRDAI_BS,
    # In the GI taxonomy these two are the fair-value change accounts, not equity / policyholder funds [X63]
    **_tags(
        {
            "ShareholdersFunds": "fair_value_change_shareholders",
            "PolicyholdersFunds": "fair_value_change_policyholders",
            "MinorityInterest": "non_controlling_interest",
        }
    ),
}

INDAS_DURATION = {
    **_tags(
        {
            "CashFlowsFromUsedInOperatingActivities": "cfo",
            "CashFlowsFromUsedInInvestingActivities": "cfi",
            "CashFlowsFromUsedInFinancingActivities": "cff",
            "InsuranceRevenueContractsNotMeasuredUnderThePAA": "insurance_revenue_non_paa",
            "InsuranceRevenueContractsMeasuredUnderThePAA": "insurance_revenue_paa",
            "InsuranceRevenue": "insurance_revenue",
            "IncurredClaims": "claims_incurred",
            "LossesAndReversalsOnOnerousContracts": "onerous_contract_losses",
            "AdjustmentsToLiabilitiesForIncurredClaims": "adjustments_to_lic",
            "EmployeeBenefitExpenses": "employee_benefit_expense",
            "Commission": "commission",
            "OtherInsuranceServiceExpenses": "other_insurance_service_expenses",
            "AdjustmentForInsuranceAcquisitionCashFlowAmortisation": "acquisition_cash_flow_amortisation",
            "InsuranceServiceExpenses": "insurance_service_expenses",
            "NetIncomeExpensesFromReinsuranceContracts": "net_reinsurance_result",
            "InsuranceServiceResult": "insurance_service_result",
            "InvestmentIncome": "investment_income_total_indas",
            "InsuranceFinanceIncomeExpenses": "insurance_finance_income_expenses",
            "MovementInInvestmentContractLiabilities": "investment_contract_movement",
            "NetFinanceResult": "net_finance_result",
            "OtherIncome": "other_income",
            "OtherRevenueExpensesNet": "other_revenue_expenses_net",
            "ProfitLossBeforeExceptionalItemsAndTax": "profit_before_exceptional_and_tax",
            "ExceptionalItemsBeforeTax": "exceptional_items",
            "ProfitLossBeforeTax": "pbt",
            "CurrentTax": "current_tax",
            "DeferredTax": "deferred_tax",
            "ProfitLossForPeriodFromContinuingOperationsAfterTax": "pat_continuing",
            "ProfitLossFromDiscontinuedOperationsAfterTax": "pat_discontinued",
            "ProfitLossForPeriod": "pat",
            "OtherComprehensiveIncome": "oci_net",
            "ComprehensiveIncomeForThePeriod": "total_comprehensive_income",
        }
    ),
    **_tags(
        {
            "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations": "eps_basic",
            "BasicEarningsLossPerShareFromContinuingOperations": "eps_basic_continuing",
        },
        "INR_PER_SHARE",
    ),
}

INDAS_INSTANT = _tags(
    {
        "CashAndCashEquivalents": "cash_and_equivalents",
        "Investments": "investments_total",
        "Loans": "loans",
        "InsuranceContractAssets": "insurance_contract_assets",
        "ReinsuranceContractAssets": "reinsurance_contract_assets",
        "Assets": "total_assets",
        "InsuranceContractLiabilities": "insurance_contract_liabilities",
        "ReinsuranceContractLiabilities": "reinsurance_contract_liabilities",
        "InvestmentContractLiabilities": "investment_contract_liabilities",
        "Borrowings": "borrowings_insurer",
        "Liabilities": "total_liabilities",
        "ShareCapital": "equity_share_capital",
        "AssignedCapital": "assigned_capital",
        "OtherFinancialInstrumentsClassifiedAsEquity": "other_equity_instruments",
        "OtherEquity": "other_equity",
        "Equity": "total_equity",
        "EquityAndLiabilities": "total_equity_and_liabilities",
    }
)


def _z(result: ParsedResults, tag: str, p) -> Decimal:
    return result.value(tag, *p) or Decimal(0)


def _sum_check(result: ParsedResults, name: str, parts: tuple[str, ...], total: str, p, minus: tuple = ()) -> None:
    t = result.value(total, *p)
    if t is None:
        return
    lhs = sum((_z(result, x, p) for x in parts), Decimal(0)) - sum((_z(result, x, p) for x in minus), Decimal(0))
    _check(result, name, lhs, t, len(parts) + len(minus) + 1, p)


def _periods(result: ParsedResults):
    return [p for p in {result.meta["quarter_period"], result.meta["ytd_period"]} if p]


def _bs(result: ParsedResults, checks) -> None:
    end = result.meta["period_end"]
    if result.value("total_assets", end, end) is None:
        return
    for name, parts, total, minus in checks:
        _sum_check(result, name, parts, total, (end, end), minus)


def life_identities(result: ParsedResults) -> None:
    for p in _periods(result):
        _sum_check(
            result, "LI_GROSS_PREMIUM", ("first_year_premium", "renewal_premium", "single_premium"), "gross_premium", p
        )
        _sum_check(
            result,
            "LI_INCOME",
            (
                "net_premium",
                "investment_income_policyholders",
                "other_income_policyholders",
                "transfer_from_shareholders",
            ),
            "total_income",
            p,
        )
        _sum_check(result, "LI_EOM", ("net_commission", "operating_expenses_insurance"), "expenses_of_management", p)
        _sum_check(result, "LI_SURPLUS", ("total_income",), "net_surplus", p, minus=("total_expenses",))
        _sum_check(
            result,
            "LI_APPROPRIATION",
            ("transfer_to_shareholders", "funds_for_future_appropriation_flow"),
            "net_surplus",
            p,
        )
        _sum_check(result, "LI_PBT", ("shareholders_income",), "pbt", p, minus=("shareholders_expenses",))
        _sum_check(result, "LI_PAT", ("pbt", "extraordinary_items"), "pat", p, minus=("tax_expense",))
    _bs(
        result,
        [
            ("BALANCE_SHEET", ("total_equity_and_liabilities",), "total_assets", ()),
            ("NET_CURRENT_ASSETS", ("current_assets",), "net_current_assets", ("current_liabilities_and_provisions",)),
        ],
    )


def general_identities(result: ParsedResults) -> None:
    for p in _periods(result):
        _sum_check(
            result,
            "GI_OPERATING_INCOME",
            ("net_premium_earned", "investment_income_policyholders", "other_income_policyholders"),
            "operating_income",
            p,
        )
        _sum_check(result, "GI_CLAIMS", ("claims_paid", "change_in_outstanding_claims"), "claims_incurred", p)
        _sum_check(
            result,
            "GI_OPERATING_EXPENSES",
            ("net_commission", "operating_expenses_insurance", "premium_deficiency", "claims_incurred"),
            "operating_expenses",
            p,
        )
        _sum_check(
            result, "GI_UNDERWRITING", ("net_premium_earned",), "underwriting_result", p, minus=("operating_expenses",)
        )
        _sum_check(
            result,
            "GI_OPERATING_PROFIT",
            ("operating_income",),
            "operating_profit_insurance",
            p,
            minus=("operating_expenses",),
        )
        _sum_check(
            result,
            "GI_SH_INCOME",
            ("transfer_from_policyholders", "investment_income_shareholders", "other_income"),
            "shareholders_income",
            p,
        )
        _sum_check(
            result, "GI_PBT", ("shareholders_income", "extraordinary_items"), "pbt", p, minus=("shareholders_expenses",)
        )
        _sum_check(result, "GI_PAT", ("pbt",), "pat", p, minus=("tax_expense",))
    _bs(
        result,
        [
            ("BALANCE_SHEET", ("total_equity_and_liabilities",), "total_assets", ()),
            ("NET_CURRENT_ASSETS", ("current_assets",), "net_current_assets", ("current_liabilities_and_provisions",)),
        ],
    )


def indas_identities(result: ParsedResults) -> None:
    for p in _periods(result):
        _sum_check(
            result, "INS_REVENUE", ("insurance_revenue_paa", "insurance_revenue_non_paa"), "insurance_revenue", p
        )
        _sum_check(
            result,
            "INS_SERVICE_EXPENSES",
            (
                "claims_incurred",
                "onerous_contract_losses",
                "adjustments_to_lic",
                "employee_benefit_expense",
                "commission",
                "other_insurance_service_expenses",
                "acquisition_cash_flow_amortisation",
            ),
            "insurance_service_expenses",
            p,
        )
        _sum_check(
            result,
            "INS_SERVICE_RESULT",
            ("insurance_revenue", "net_reinsurance_result"),
            "insurance_service_result",
            p,
            minus=("insurance_service_expenses",),
        )
        _sum_check(
            result,
            "INS_FINANCE_RESULT",
            ("investment_income_total_indas", "insurance_finance_income_expenses", "investment_contract_movement"),
            "net_finance_result",
            p,
        )
        _sum_check(
            result,
            "INS_PBEIT",
            ("insurance_service_result", "net_finance_result", "other_revenue_expenses_net"),
            "profit_before_exceptional_and_tax",
            p,
        )
        _sum_check(result, "INS_PBT", ("profit_before_exceptional_and_tax", "exceptional_items"), "pbt", p)
        _sum_check(result, "INS_PAT_CONTINUING", ("pbt",), "pat_continuing", p, minus=("current_tax", "deferred_tax"))
        _sum_check(result, "INS_PAT", ("pat_continuing", "pat_discontinued"), "pat", p)
        _sum_check(result, "INS_TCI", ("pat", "oci_net"), "total_comprehensive_income", p)
    _bs(
        result,
        [
            ("ASSETS_EQ_EQUITY_PLUS_LIABILITIES", ("total_equity", "total_liabilities"), "total_assets", ()),
            (
                "INS_EQUITY",
                ("equity_share_capital", "assigned_capital", "other_equity_instruments", "other_equity"),
                "total_equity",
                (),
            ),
        ],
    )


SOLVENCY_PERCENT_THRESHOLD = Decimal("0.5")


def _solvency_times(result: ParsedResults) -> None:
    """Named rule SOLVENCY_PERCENT_SCALING [X65]: filers enter SolvencyRatio either as times (HDFC Life 1.8, SBI Life
    1.97) or as times / 100 (ICICI Lombard 0.0275, New India 0.0161, GIC Re 0.0418, LIC 0.0235). A solvency below
    0.5x is impossible for an operating insurer (IRDAI minimum 1.5x), so a filed value below 0.5 is read as
    percent-scaled and multiplied by 100. The filed fact is kept; the normalised one is a derived fact."""
    from financials.parsers.indas_corp import CanonicalFact

    added, scaled = [], []
    for f in [f for f in result.facts if f.canonical_tag == "solvency_ratio"]:
        times = f.value * 100 if 0 < f.value < SOLVENCY_PERCENT_THRESHOLD else f.value
        if times != f.value:
            scaled.append([str(f.period_start), str(f.period_end)])
        added.append(CanonicalFact("solvency_ratio_times", f.period_type, f.period_start, f.period_end, f.period_months,
                                   "RATIO", times, "DERIVED:SolvencyRatio"))  # fmt: skip
    result.facts.extend(added)
    if scaled:
        result.meta.setdefault("rules_applied", []).append({"rule": "SOLVENCY_PERCENT_SCALING", "periods": scaled})


def _irdai_post(result: ParsedResults) -> None:
    _irdai_equity(result)
    _solvency_times(result)


def _irdai_equity(result: ParsedResults) -> None:
    """Owners' equity for IRDAI formats = share capital + reserves and surplus + share application money (the formats
    have no total-equity line; GI 'ShareholdersFunds' is a fair-value change account, X63)."""
    from financials.parsers.indas_corp import CanonicalFact

    end = result.meta["period_end"]
    cap, res = result.value("equity_share_capital", end, end), result.value("reserves_and_surplus", end, end)
    if cap is None or res is None:
        return
    total = cap + res + (result.value("share_application_money", end, end) or Decimal(0))
    result.facts.append(
        CanonicalFact(
            "total_equity",
            "INSTANT",
            end,
            end,
            None,
            INR,
            total,
            "DERIVED:ShareCapital+ReservesAndSurplus+ShareApplicationMoney",
        )
    )


# Mapped in the unmapped-element audit (C22). IRDAI `Assets`/`Investments`/`CurrentLiabilities` are deliberately
# NOT mapped: `Assets` equals ApplicationOfFunds (net of current liabilities) and `Investments` exceeds it [C22].
_AUDIT_DURATION = {
    "AmountOfRelatedPartyTransactionDuringTheReportingPeriod": "rpt_total_amount",
    "EffectOfExchangeRateChangesOnCashAndCashEquivalents": "fx_effect_on_cash",
}
LIFE_DURATION.update(_tags({**_AUDIT_DURATION, "CurrentTax": "current_tax"}))
GENERAL_DURATION.update(_tags(_AUDIT_DURATION))
INDAS_DURATION.update(
    _tags(
        {
            "AmountOfRelatedPartyTransactionDuringTheReportingPeriod": "rpt_total_amount",
            "OtherExpenses": "other_expenses",
            "IncreaseDecreaseInCashAndCashEquivalents": "net_cash_flow_after_fx",
            "ProfitLossFromDiscontinuedOperationsBeforeTax": "discontinued_pbt",
        }
    )
)
INDAS_INSTANT.update(
    _tags(
        {
            "PropertyPlantAndEquipment": "ppe_net",
            "Goodwill": "goodwill",
            "OtherIntangibleAssets": "other_intangibles",
            "InvestmentProperty": "investment_property",
        }
    )
)


LIFE_SPEC = ProfileSpec(
    "IRDAI_LIFE",
    LIFE_DURATION,
    LIFE_INSTANT,
    ("net_premium", "total_income", "total_expenses", "net_surplus", "pbt", "pat"),
    (),
    post_process=_irdai_post,
    identities=life_identities,
)
GENERAL_SPEC = ProfileSpec(
    "IRDAI_GENERAL",
    GENERAL_DURATION,
    GENERAL_INSTANT,
    ("net_premium_earned", "claims_incurred", "operating_expenses", "pbt", "pat"),
    (),
    post_process=_irdai_post,
    identities=general_identities,
)
INDAS_SPEC = ProfileSpec(
    "INDAS_INSURANCE",
    INDAS_DURATION,
    INDAS_INSTANT,
    ("insurance_revenue", "insurance_service_expenses", "insurance_service_result", "pbt", "pat"),
    (),
    identities=indas_identities,
)

SPECS = {"IRDAI_LIFE": LIFE_SPEC, "IRDAI_GENERAL": GENERAL_SPEC, "INDAS_INSURANCE": INDAS_SPEC}


def parse_insurer_results(data: bytes, profile: str) -> ParsedResults:
    return parse_with_spec(data, SPECS[profile])
