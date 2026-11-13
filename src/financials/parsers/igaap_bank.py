"""IGAAP_BANK: Integrated Filing results of scheduled commercial banks (RBI / Banking Regulation Act format)
[X58-X61].

Shared machinery (contexts, period gating, meta, attribution rule, EPS check) comes from `indas_corp`; banks
have their own element set and identities, all VERIFIED to the rupee on 10 Batch 5 filings + HDFC Bank
consolidated:
  InterestEarned = interest on advances + income on investments + interest on RBI / inter-bank + other interest
  Income = InterestEarned + OtherIncome; OperatingExpenses = EmployeesCost + OtherOperatingExpenses
  ExpenditureExcludingProvisions = InterestExpended + OperatingExpenses; PPOP = Income - that expenditure
  PBT = PPOP - ProvisionsOtherThanTaxAndContingencies + ExceptionalItems (signed)
  PAT(ordinary) = PBT - Tax; ProfitLossForThePeriod = PAT(ordinary) + ExtraordinaryItems
  owners = ProfitLossForThePeriod + associates - minority
  Balance sheet (H1 / FY only): Capital + Reserves + Deposits + Borrowings + Other liabilities = CapitalAndLiabilities
  = Assets = cash with RBI + balances with banks + investments + advances + fixed assets + other assets.
Q1 / Q3 filings carry no balance sheet: P&L facts are stored and the balance-sheet checks are skipped.
"""

from __future__ import annotations

from decimal import Decimal

from financials.parsers.indas_corp import (
    DURATION_TAGS,
    ParsedResults,
    ProfileSpec,
    _check,
    parse_with_spec,
)

_SHARED_FLOWS = {
    k: v
    for k, v in DURATION_TAGS.items()
    if v[0]
    in ("cfo", "cfi", "cff", "net_cash_flow", "fx_effect_on_cash", "net_cash_flow_after_fx", "dividends_paid",
        "interest_paid_operating", "interest_paid_financing", "interest_received_operating",
        "interest_received_investing", "income_taxes_paid", "cash_generated_from_operations",
        "dividends_received_operating", "dividends_received_investing", "rpt_total_amount")
}  # fmt: skip

BANK_DURATION_TAGS: dict[str, tuple[str, str]] = {
    **_SHARED_FLOWS,
    "InterestOrDiscountOnAdvancesOrBills": ("interest_on_advances", "INR"),
    "RevenueOnInvestments": ("income_on_investments", "INR"),
    "InterestOnBalancesWithReserveBankOfIndiaAndOtherInterBankFunds": ("interest_on_rbi_interbank", "INR"),
    "OtherInterest": ("other_interest", "INR"),
    "InterestEarned": ("interest_earned", "INR"),
    "OtherIncome": ("other_income", "INR"),
    "Income": ("total_income", "INR"),
    "InterestExpended": ("interest_expended", "INR"),
    "EmployeesCost": ("employee_benefit_expense", "INR"),
    "OtherOperatingExpenses": ("other_operating_expenses", "INR"),
    "OperatingExpenses": ("operating_expenses", "INR"),
    "ExpenditureExcludingProvisionsAndContingencies": ("expenditure_excl_provisions", "INR"),
    "OperatingProfitBeforeProvisionAndContingencies": ("ppop", "INR"),
    "ProvisionsOtherThanTaxAndContingencies": ("provisions", "INR"),
    "ExceptionalItems": ("exceptional_items", "INR"),
    "ProfitLossFromOrdinaryActivitiesBeforeTax": ("pbt", "INR"),
    "TaxExpense": ("tax_expense", "INR"),
    "ProfitLossFromOrdinaryActivitiesAfterTax": ("pat_ordinary", "INR"),
    "ExtraordinaryItems": ("extraordinary_items", "INR"),
    "ProfitLossForThePeriod": ("pat", "INR"),
    "ShareOfProfitLossOfAssociates": ("share_of_associates_jv", "INR"),
    "ProfitLossOfMinorityInterest": ("pat_nci", "INR"),
    "ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates": ("pat_owners", "INR"),
    "PaidUpValueOfEquityShareCapital": ("paid_up_equity_capital", "INR"),
    "FaceValueOfEquityShareCapital": ("face_value_per_share", "INR_PER_SHARE"),
    "BasicEarningsPerShareAfterExtraordinaryItems": ("eps_basic", "INR_PER_SHARE"),
    "BasicEarningsPerShareBeforeExtraordinaryItems": ("eps_basic_before_extraordinary", "INR_PER_SHARE"),
    # Regulatory disclosures, filed in duration contexts although they are period-end stocks / ratios [X59]
    "GrossNonPerformingAssets": ("gross_npa", "INR"),
    "NonPerformingAssets": ("net_npa", "INR"),
    "PercentageOfGrossNpa": ("gnpa_pct", "RATIO"),
    "PercentageOfNpa": ("nnpa_pct", "RATIO"),
    "ReturnOnAssets": ("roa_filed", "RATIO"),
    "CET1Ratio": ("cet1_ratio", "RATIO"),
    "AdditionalTier1Ratio": ("at1_ratio", "RATIO"),
    "PercentageOfShareHeldByGovernmentOfIndia": ("govt_holding_pct", "RATIO"),
}

BANK_INSTANT_TAGS: dict[str, tuple[str, str]] = {
    "Capital": ("equity_share_capital", "INR"),
    "ReservesAndSurplus": ("reserves_and_surplus", "INR"),
    "Deposits": ("deposits", "INR"),
    "Borrowings": ("borrowings_bank", "INR"),
    "OtherLiabilitiesAndProvisions": ("other_liabilities_and_provisions", "INR"),
    "CapitalAndLiabilities": ("total_equity_and_liabilities", "INR"),
    "CashAndBalancesWithReserveBankOfIndia": ("cash_and_rbi_balances", "INR"),
    "BalancesWithBanksAndMoneyAtCallAndShortNotice": ("balances_with_banks", "INR"),
    "Investments": ("investments_total", "INR"),
    "Advances": ("advances", "INR"),
    "FixedAssets": ("fixed_assets", "INR"),
    "OtherAssets": ("other_assets", "INR"),
    "Assets": ("total_assets", "INR"),
}

BANK_CRITICAL = (
    "interest_earned", "other_income", "total_income", "interest_expended", "operating_expenses", "ppop",
    "provisions", "pbt", "tax_expense", "pat",
)  # fmt: skip

LIABILITY_LINES = ("equity_share_capital", "reserves_and_surplus", "deposits", "borrowings_bank",
                   "other_liabilities_and_provisions")  # fmt: skip
ASSET_LINES = ("cash_and_rbi_balances", "balances_with_banks", "investments_total", "advances", "fixed_assets",
               "other_assets")  # fmt: skip
REGULATORY = ("gross_npa", "net_npa", "gnpa_pct", "nnpa_pct", "roa_filed", "cet1_ratio", "at1_ratio")


def check_bank_identities(result: ParsedResults) -> None:
    periods = {result.meta["quarter_period"], result.meta["ytd_period"]}
    for p in periods:
        v = lambda tag, p=p: result.value(tag, *p)  # noqa: E731
        z = lambda tag, p=p: result.value(tag, *p) or Decimal(0)  # noqa: E731
        if v("interest_earned") is None:
            continue  # e.g. a Q1 filing has no separate YTD context
        parts = ("interest_on_advances", "income_on_investments", "interest_on_rbi_interbank", "other_interest")
        _check(result, "BANK_INTEREST_COMPONENTS", sum(z(t) for t in parts), v("interest_earned"), 5, p)
        _check(result, "BANK_TOTAL_INCOME", z("interest_earned") + z("other_income"), v("total_income"), 3, p)
        opex = z("employee_benefit_expense") + z("other_operating_expenses")
        _check(result, "BANK_OPEX", opex, v("operating_expenses"), 3, p)
        exp = z("interest_expended") + z("operating_expenses")
        _check(result, "BANK_EXPENDITURE", exp, v("expenditure_excl_provisions"), 3, p)
        _check(result, "BANK_PPOP", z("total_income") - z("expenditure_excl_provisions"), v("ppop"), 3, p)
        pbt = z("ppop") - z("provisions") + z("exceptional_items")
        _check(result, "BANK_PBT", pbt, v("pbt"), 4, p)
        _check(result, "BANK_PAT_ORDINARY", z("pbt") - z("tax_expense"), v("pat_ordinary"), 3, p)
        _check(result, "BANK_PAT", z("pat_ordinary") + z("extraordinary_items"), v("pat"), 3, p)
        if v("pat_owners") is not None:
            owners = z("pat") + z("share_of_associates_jv") - z("pat_nci")
            _check(result, "BANK_OWNERS", owners, v("pat_owners"), 4, p)
        cfo, cfi, cff, net = v("cfo"), v("cfi"), v("cff"), v("net_cash_flow")
        if None not in (cfo, cfi, cff, net):
            _check(result, "CF_NET", cfo + cfi + cff, net, 4, p)
    end = result.meta["period_end"]
    total = result.value("total_assets", end, end)
    if total is None:
        return  # Q1 / Q3: no balance sheet
    i = lambda tag: result.value(tag, end, end) or Decimal(0)  # noqa: E731
    _check(result, "BANK_LIABILITIES", sum(i(t) for t in LIABILITY_LINES), i("total_equity_and_liabilities"), 6,
           (end,))  # fmt: skip
    _check(result, "BANK_ASSETS", sum(i(t) for t in ASSET_LINES), total, 7, (end,))
    _check(result, "BALANCE_SHEET", total, i("total_equity_and_liabilities"), 2, (end,))


def post_process(result: ParsedResults) -> None:
    """Named rule CONSOLIDATED_REGULATORY_PLACEHOLDER [X60]: consolidated bank filings tag every regulatory
    disclosure (GNPA, NNPA, their %, RoA, CET1, AT1) as exactly 0 (SBI, HDFC Bank Q2 FY27). These are standalone
    disclosures, so in a CONSOLIDATED filing where all are 0 they are dropped (NULL), never read as 0%.
    Then derive owners' equity = Capital + Reserves and surplus (the RBI format has no total-equity line)."""
    if result.meta["scope"] == "CONSOLIDATED":
        periods = {(f.period_start, f.period_end) for f in result.facts if f.canonical_tag in REGULATORY}
        dropped = []
        for p in periods:
            vals = [result.value(t, *p) for t in REGULATORY]
            if all(v == 0 for v in vals if v is not None) and any(v is not None for v in vals):
                dropped.append(p)
        if dropped:
            result.facts = [
                f for f in result.facts
                if not (f.canonical_tag in REGULATORY and (f.period_start, f.period_end) in dropped)
            ]  # fmt: skip
            result.meta.setdefault("rules_applied", []).append(
                {
                    "rule": "CONSOLIDATED_REGULATORY_PLACEHOLDER",
                    "periods": [[str(a), str(b)] for a, b in sorted(dropped)],
                }
            )
    end = result.meta["period_end"]
    cap, res = result.value("equity_share_capital", end, end), result.value("reserves_and_surplus", end, end)
    if cap is not None and res is not None:
        from financials.parsers.indas_corp import CanonicalFact

        result.facts.append(
            CanonicalFact(
                "total_equity", "INSTANT", end, end, None, "INR", cap + res, "DERIVED:Capital+ReservesAndSurplus"
            )
        )


BANK_SPEC = ProfileSpec(
    "IGAAP_BANK",
    BANK_DURATION_TAGS,
    BANK_INSTANT_TAGS,
    BANK_CRITICAL,
    expense_components=(),
    post_process=post_process,
    identities=check_bank_identities,
)


def parse_igaap_bank_results(data: bytes) -> ParsedResults:
    return parse_with_spec(data, BANK_SPEC)
