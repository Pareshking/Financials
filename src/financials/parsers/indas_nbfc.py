"""INDAS_NBFC: Integrated Filing results of NBFCs / HFCs (Ind AS Schedule III Division III) [X54-X56].

Same contexts, period gating, attribution rules and profit-chain identities as INDAS_CORP (shared machinery
in `indas_corp`). Division III differences, all VERIFIED on 10 Q2 FY27 lender filings (Batch 4):
- revenue is itemised: interest, dividend, rental, fees & commission, fair-value and derecognition gains,
  sale of products / services, other operating revenue; their sum equals RevenueFromOperations to the rupee;
- the balance sheet is liquidity-ordered (financial / non-financial), with Loans, Investments, DebtSecurities,
  Borrowings (other than debt securities), Deposits and SubordinatedLiabilities;
- no NPA, stage-wise ECL or capital-adequacy element exists in the taxonomy, so GNPA / NNPA / PCR / CRAR
  cannot be sourced from this file (they stay NULL; never parsed from text blocks).
Non-lending investment companies (Jindal Poly Investment: Loans = 0) are flagged `is_lending_nbfc = False`
by a deterministic rule (C13), not quarantined: their statements are valid, only lending ratios do not apply.
"""

from __future__ import annotations

import re
from decimal import Decimal

from financials.parsers.indas_corp import (
    DURATION_TAGS,
    INSTANT_TAGS,
    ParsedResults,
    ProfileSpec,
    parse_with_spec,
)

NBFC_DURATION_TAGS: dict[str, tuple[str, str]] = {
    **DURATION_TAGS,  # shared Ind AS elements: OtherIncome, Income, FinanceCosts, profit chain, EPS, cash flow
    "InterestEarned": ("interest_earned", "INR"),
    "DividendIncome": ("dividend_income", "INR"),
    "RentalIncome": ("rental_income", "INR"),
    "FeesAndCommissionIncome": ("fee_commission_income", "INR"),
    "NetGainOnFairValueChanges": ("net_gain_fair_value", "INR"),
    "NetGainOnDerecognitionOfFinancialInstrumentsUnderAmortisedCostCategory": ("net_gain_derecognition", "INR"),
    "RevenueFromSaleOfProduct": ("sale_of_products", "INR"),
    "RevenueFromSaleOfServices": ("sale_of_services", "INR"),
    "OtherRevenueFromOperations": ("other_operating_revenue", "INR"),
    "FeesAndCommissionExpense": ("fee_commission_expense", "INR"),
    "NetLossOnFairValueChanges": ("net_loss_fair_value", "INR"),
    "NetLossOnDerecognitionOfFinancialInstrumentsUnderAmortisedCostCategory": ("net_loss_derecognition", "INR"),
    "ImpairmentOnFinancialInstruments": ("impairment_financial_instruments", "INR"),
}

_SHARED_INSTANTS = (
    "CashAndCashEquivalents", "BankBalanceOtherThanCashAndCashEquivalents", "Inventories", "PropertyPlantAndEquipment",
    "CapitalWorkInProgress", "IntangibleAssetsUnderDevelopment", "InvestmentProperty", "Goodwill",
    "OtherIntangibleAssets", "DeferredTaxAssetsNet", "DeferredTaxLiabilitiesNet", "Assets", "EquityShareCapital",
    "OtherEquity", "EquityAttributableToOwnersOfParent", "NonControllingInterest", "Equity", "Liabilities",
    "EquityAndLiabilities",
)  # fmt: skip

NBFC_INSTANT_TAGS: dict[str, tuple[str, str]] = {
    **{k: INSTANT_TAGS[k] for k in _SHARED_INSTANTS},
    "Loans": ("loans", "INR"),
    "Investments": ("investments_total", "INR"),
    "TradeReceivables": ("trade_receivables", "INR"),
    "OtherReceivables": ("other_receivables", "INR"),
    "DerivativeFinancialInstrumentsFinancialAssets": ("derivative_assets", "INR"),
    "OtherFinancialAssets": ("other_financial_assets", "INR"),
    "FinanicalAssets": ("financial_assets", "INR"),  # sic: the taxonomy element is misspelt [X54]
    "OtherNonFinancialAssets": ("other_non_financial_assets", "INR"),
    "NonFinancialAssets": ("non_financial_assets", "INR"),
    "DerivativeFinancialInstrumentsFinancialLiabilities": ("derivative_liabilities", "INR"),
    "DebtSecurities": ("debt_securities", "INR"),
    "Borrowings": ("borrowings_other_than_debt_securities", "INR"),
    "Deposits": ("deposits", "INR"),
    "SubordinatedLiabilities": ("subordinated_liabilities", "INR"),
    "OtherFinancialLiabilities": ("other_financial_liabilities", "INR"),
    "FinancialLiabilities": ("financial_liabilities", "INR"),
    "Provisions": ("provisions", "INR"),
    "NonFinancialLiabilities": ("non_financial_liabilities", "INR"),
}

NBFC_REVENUE_COMPONENTS = (
    "interest_earned", "dividend_income", "rental_income", "fee_commission_income", "net_gain_fair_value",
    "net_gain_derecognition", "sale_of_products", "sale_of_services", "other_operating_revenue",
)  # fmt: skip

NBFC_EXPENSE_COMPONENTS = (
    "finance_costs", "fee_commission_expense", "net_loss_fair_value", "net_loss_derecognition",
    "impairment_financial_instruments", "cost_of_materials_consumed", "purchases_of_stock_in_trade",
    "changes_in_inventories", "employee_benefit_expense", "depreciation_amortisation", "other_expenses",
)  # fmt: skip

NBFC_CRITICAL = (
    "revenue_from_operations", "interest_earned", "other_income", "total_income", "total_expenses", "finance_costs",
    "impairment_financial_instruments", "pbt", "tax_expense", "pat",
)  # fmt: skip

# C13: a lender holds loans. With a balance sheet (H1 / FY): Loans >= 10% of total assets. Without one (Q1 / Q3):
# interest earned >= 25% of revenue from operations. Lowest observed among the 10 Batch 4 lenders: 70% / 84%;
# Jindal Poly Investment: 0% / 0.2%.
LOANS_TO_ASSETS_MIN = Decimal("0.10")
INTEREST_TO_REVENUE_MIN = Decimal("0.25")


def classify_lender(result: ParsedResults) -> None:
    q = result.meta["quarter_period"]
    end = q[1]
    loans, assets = result.value("loans", end, end), result.value("total_assets", end, end)
    interest, revenue = result.value("interest_earned", *q), result.value("revenue_from_operations", *q)
    if loans is not None and assets:
        lending, basis = loans / assets >= LOANS_TO_ASSETS_MIN, "LOANS_TO_ASSETS"
    elif interest is not None and revenue:
        lending, basis = interest / revenue >= INTEREST_TO_REVENUE_MIN, "INTEREST_TO_REVENUE"
    else:
        lending, basis = None, None
    result.meta["is_lending_nbfc"] = lending
    result.meta["lending_basis"] = basis


# Division III label rules [X57]: leases and right-of-use assets are labelled members of the liquidity-ordered
# "other" lines (L&T Finance, Muthoot, Poonawalla, Manappuram). Same anchored patterns as X39 / X47.
NBFC_LABEL_RULES = (
    ("NBFC_LEASE_LIABILITIES", "OtherFinancialLiabilitiesAxis", "OtherFinancialLiabilities", "lease_liabilities",
     "INSTANT", re.compile(r"^\s*lease\s+liab", re.I)),
    ("NBFC_RIGHT_OF_USE_ASSETS", "OtherNonFinancialAssetsAxis", "OtherNonFinancialAssets", "right_of_use_assets",
     "INSTANT", re.compile(r"^\s*right[\s-]*of[\s-]*use", re.I)),
)  # fmt: skip

NBFC_SPEC = ProfileSpec(
    "INDAS_NBFC",
    NBFC_DURATION_TAGS,
    NBFC_INSTANT_TAGS,
    NBFC_CRITICAL,
    NBFC_EXPENSE_COMPONENTS,
    revenue_components=NBFC_REVENUE_COMPONENTS,
    label_rules=NBFC_LABEL_RULES,
    missing_component_is_zero=True,
    post_process=classify_lender,
)


def parse_indas_nbfc_results(data: bytes) -> ParsedResults:
    return parse_with_spec(data, NBFC_SPEC)
