"""Characterisation tests: verified facts about real NSE XBRL files.

Each test pins one claim recorded as VERIFIED in docs/references.md. If a test here
fails, the claim (and any design depending on it) must be revisited — do not "fix" the test.
"""

from decimal import Decimal

import pytest

from _fixture_helpers import BANK, CORP, GEN_INS, NBFC, load_instance

ENT = "in-capmkt-ent"


@pytest.mark.parametrize(
    ("path", "namespace_fragment"),
    [
        (CORP, "/IntegratedFinance_IndAS/"),
        (NBFC, "/IntegratedFinance_NBFC/"),
        (BANK, "/IntegratedFinance_Banking/"),
        (GEN_INS, "bseindia.com/xbrl/GeneralInsurance/"),
    ],
)
def test_accounting_profile_is_routable_from_entity_namespace(path, namespace_fragment):
    assert namespace_fragment in load_instance(path).namespaces[ENT]


@pytest.mark.parametrize("path", [CORP, NBFC, BANK])
def test_no_prior_period_comparative_duration_contexts(path):
    """Quarterly XBRL carries current-quarter and current-YTD durations only."""
    inst = load_instance(path)
    fy_start = inst.text[("DateOfStartOfFinancialYear", "OneD")]
    used = {ctx for (_, ctx) in inst.numeric} | {ctx for (_, ctx) in inst.text}
    for ctx_id in used:
        ctx = inst.contexts[ctx_id]
        if ctx.start is not None:
            assert ctx.start >= fy_start, f"{ctx_id} starts before current FY: {ctx.start}"


@pytest.mark.parametrize("path", [CORP, NBFC])
def test_only_prior_instant_is_opening_cash_for_cash_flow(path):
    inst = load_instance(path)
    prior = [name for (name, ctx) in inst.numeric if ctx == "PY_I"]
    assert prior == ["CashAndCashEquivalentsCashFlowStatement"]


def test_values_are_absolute_rupees_regardless_of_level_of_rounding():
    corp = load_instance(CORP)
    assert corp.text[("LevelOfRounding", "OneD")] == "Millions"
    assert corp.numeric[("RevenueFromOperations", "OneD")] == Decimal("2895440000")
    bank = load_instance(BANK)
    assert bank.text[("LevelOfRounding", "OneD")] == "Lakhs"
    assert bank.numeric[("InterestEarned", "OneD")] == Decimal("12873200000")


def test_scope_is_a_per_filing_fact_not_a_context_dimension():
    for path in (CORP, NBFC, BANK):
        assert load_instance(path).text[("NatureOfReportStandaloneConsolidated", "OneD")] == "Standalone"
    assert load_instance(GEN_INS).text[("NatureOfReportStandaloneConsolidated", "OneI")] == "Standalone"


def test_issuer_identifiers_are_inside_the_filing():
    corp = load_instance(CORP)
    assert corp.text[("Symbol", "OneD")] == "ELIN"
    assert corp.text[("ISIN", "OneD")] == "INE050401020"
    assert corp.text[("ScripCode", "OneD")] == "543725"


@pytest.mark.parametrize("ctx", ["OneD", "FourD"])
def test_corp_pnl_identities_and_exceptional_sign(ctx):
    n = load_instance(CORP).numeric
    assert n[("Income", ctx)] - n[("Expenses", ctx)] == n[("ProfitBeforeExceptionalItemsAndTax", ctx)]
    # Exceptional items are stored so that PBT = pre-exceptional profit + ExceptionalItemsBeforeTax.
    assert (
        n[("ProfitBeforeExceptionalItemsAndTax", ctx)] + n[("ExceptionalItemsBeforeTax", ctx)]
        == n[("ProfitBeforeTax", ctx)]
    )
    assert (
        n[("ProfitBeforeTax", ctx)] - n[("TaxExpense", ctx)]
        == n[("ProfitLossForPeriodFromContinuingOperations", ctx)]
    )


def test_corp_expenses_include_inventory_change_with_expense_sign():
    n = load_instance(CORP).numeric
    parts = [
        "CostOfMaterialsConsumed",
        "PurchasesOfStockInTrade",
        "ChangesInInventoriesOfFinishedGoodsWorkInProgressAndStockInTrade",
        "EmployeeBenefitExpense",
        "FinanceCosts",
        "DepreciationDepletionAndAmortisationExpense",
        "OtherExpenses",
    ]
    assert sum(n[(p, "OneD")] for p in parts) == n[("Expenses", "OneD")]
    # Negative value here = inventory build-up (reduces expenses).
    assert n[("ChangesInInventoriesOfFinishedGoodsWorkInProgressAndStockInTrade", "OneD")] < 0


@pytest.mark.parametrize("path", [CORP, NBFC])
def test_balance_sheet_identity_h1(path):
    n = load_instance(path).numeric
    assert n[("Assets", "OneI")] == n[("EquityAndLiabilities", "OneI")]


def test_corp_interest_paid_classification_is_tagged():
    n = load_instance(CORP).numeric
    assert n[("InterestPaidClassifiedAsOperatingActivities", "FourD")] == 0
    assert n[("InterestPaidClassifiedAsFinancingActivities", "FourD")] > 0


def test_cash_flow_only_in_ytd_context():
    n = load_instance(CORP).numeric
    assert ("CashFlowsFromUsedInOperatingActivities", "FourD") in n
    assert ("CashFlowsFromUsedInOperatingActivities", "OneD") not in n


def test_nbfc_taxonomy_uses_interest_earned_tag():
    n = load_instance(NBFC).numeric
    assert ("InterestEarned", "OneD") in n
    assert ("InterestIncome", "OneD") not in n


def test_bank_identities():
    n = load_instance(BANK).numeric
    assert n[("InterestEarned", "OneD")] + n[("OtherIncome", "OneD")] == n[("Income", "OneD")]
    assert (
        n[("Income", "OneD")] - n[("ExpenditureExcludingProvisionsAndContingencies", "OneD")]
        == n[("OperatingProfitBeforeProvisionAndContingencies", "OneD")]
    )


def test_bank_asset_quality_and_capital_tags():
    n = load_instance(BANK).numeric
    for tag in ("GrossNonPerformingAssets", "NonPerformingAssets"):
        assert (tag, "OneD") in n
    # Ratios are fractions, not percentages.
    assert n[("PercentageOfGrossNpa", "OneD")] == Decimal("0.0175")
    assert ("CET1Ratio", "OneD") in n
    names = {name for (name, _) in n}
    assert not any("casa" in name.lower() for name in names)


def test_bank_q1_filing_has_no_balance_sheet():
    names = {name for (name, ctx) in load_instance(BANK).numeric if ctx == "OneI"}
    assert "Advances" not in names and "Deposits" not in names
    assert "FourD" not in load_instance(BANK).contexts


def test_general_insurer_fourd_context_dates_are_wrong_but_values_are_ytd():
    """Known filer defect: context says Oct–Dec, declared period and values are Apr–Dec."""
    inst = load_instance(GEN_INS)
    one, four = inst.contexts["OneD"], inst.contexts["FourD"]
    assert (four.start, four.end) == (one.start, one.end) == ("2024-10-01", "2024-12-31")
    assert inst.text[("DateOfStartOfReportingPeriod", "FourI")] == "2024-04-01"
    assert (
        inst.numeric[("GrossPremiumsWritten", "FourD")] > 3 * inst.numeric[("GrossPremiumsWritten", "OneD")]
    )
