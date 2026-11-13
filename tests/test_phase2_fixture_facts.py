"""Characterisation tests for the Phase 2 evidence fixtures (no Phase 2 parser exists yet).

Each test pins a claim recorded in docs/references.md §1b. If one fails, revisit the claim.
"""

from decimal import Decimal

import pytest

from _fixture_helpers import XBRL_DIR
from financials.parsers.indas_corp import detect_profile
from financials.parsers.xbrl import parse_instance

NBFC = XBRL_DIR / "INTEGRATED_FILING_NBFC_INDAS_1742038_19102026075842_WEB.xml"
LIFE = XBRL_DIR / "INTEGRATED_FILING_LI_1739355_15102026072525_WEB.xml"
CONS = XBRL_DIR / "INTEGRATED_FILING_INDAS_1750537_30102026093254_WEB.xml"
BANK_H1 = XBRL_DIR / "INTEGRATED_FILING_BANKING_1740912_17102026054806_WEB.xml"
ANNUAL = XBRL_DIR / "AR_XBRL_ELIN_30092025131606.xml"
SHP_PLEDGED = XBRL_DIR / "SHP_1742713_21102026021326_WEB.xml"


@pytest.fixture(scope="module")
def inst():
    cache = {}

    def load(path):
        if path not in cache:
            cache[path] = parse_instance(path.read_bytes())
        return cache[path]

    return load


def num(i, name, ctx):
    f = i.get(name, ctx)
    assert f is not None, (name, ctx)
    return f.decimal()


def nondim_periods(i):
    return {(c.start, c.end, c.instant) for c in i.contexts.values() if not c.dimensions}


def test_lending_nbfc_has_non_zero_lending_lines(inst):
    """[X32] Bajaj Finance Q2 FY27 standalone: a lender, unlike the investment-company fixture."""
    i = inst(NBFC)
    assert detect_profile(i.entity_namespace) == "INDAS_NBFC"
    assert (
        i.first_text("Symbol") == "BAJFINANCE" and i.first_text("NatureOfReportStandaloneConsolidated") == "Standalone"
    )
    assert num(i, "InterestEarned", "OneD") == Decimal("185491400000")
    assert num(i, "FinanceCosts", "OneD") == Decimal("63988400000")
    assert num(i, "ImpairmentOnFinancialInstruments", "OneD") == Decimal("21305100000")
    assert num(i, "Loans", "OneI") == Decimal("4222680200000")


def test_life_insurer_integrated_taxonomy(inst):
    """[X33] HDFC Life Q2 FY27: IntegratedFinance_LI namespace (2025-01-31), dates match declared periods."""
    i = inst(LIFE)
    assert "/IntegratedFinance_LI/2025-01-31/" in i.entity_namespace
    # Routing, not a file fact: known profile since Batch 5 (PROFILE_NOT_IMPLEMENTED until Batch 6); was None.
    assert detect_profile(i.entity_namespace) == "IRDAI_LIFE"
    for tag in ("GrossPremiumIncome", "NetPremiumIncome", "ChangeInActuarialLiability", "BenefitsPaidNet"):
        assert num(i, tag, "OneD") > 0, tag
    assert num(i, "InvestmentsPolicyholders", "OneI") > 0
    declared = {f.context_id: [] for f in i.facts if f.name == "DateOfStartOfReportingPeriod"}
    for f in i.facts:
        if f.name in ("DateOfStartOfReportingPeriod", "DateOfEndOfReportingPeriod"):
            declared[f.context_id].append(f.value_text.strip())
    for ctx, (start, end) in declared.items():
        c = i.contexts[ctx]
        assert (str(c.start), str(c.end)) == (start, end), ctx  # unlike the legacy GI fixture [X26]
    # Extra instants at quarter start and FY start (opening balances).
    assert (i.contexts["OcurI"].instant.isoformat(), i.contexts["OprevI"].instant.isoformat()) == (
        "2026-07-01",
        "2026-04-01",
    )


def test_consolidated_corporate_non_controlling_interest(inst):
    """[X34] Reliance Q2 FY27 consolidated: NCI tags in equity, profit and comprehensive income."""
    i = inst(CONS)
    assert detect_profile(i.entity_namespace) == "INDAS_CORP"
    assert i.first_text("NatureOfReportStandaloneConsolidated") == "Consolidated"
    assert num(i, "NonControllingInterest", "OneI") == Decimal("1882440000000")
    assert num(i, "EquityAttributableToOwnersOfParent", "OneI") == Decimal("9444040000000")
    owners = num(i, "ProfitOrLossAttributableToOwnersOfParent", "OneD")
    nci = num(i, "ProfitOrLossAttributableToNonControllingInterests", "OneD")
    assert (owners, nci) == (Decimal("255480000000"), Decimal("40020000000"))
    assert owners + nci == num(i, "ProfitLossForPeriod", "OneD")
    assert num(i, "Equity", "OneI") == num(i, "EquityAttributableToOwnersOfParent", "OneI") + num(
        i, "NonControllingInterest", "OneI"
    )
    assert num(i, "ShareOfProfitLossOfAssociatesAndJointVenturesAccountedForUsingEquityMethod", "OneD") == Decimal(
        "3000000000"
    )


def test_h1_bank_has_balance_sheet_but_no_casa_or_crar(inst):
    """[X35] HDFC Bank H1 FY27 standalone: OneI balance sheet present; CASA and total CRAR still untagged."""
    i = inst(BANK_H1)
    assert detect_profile(i.entity_namespace) == "IGAAP_BANK"
    bs = {t: num(i, t, "OneI") for t in ("Advances", "Deposits", "Borrowings", "Capital", "ReservesAndSurplus",
                                        "Investments", "Assets", "CapitalAndLiabilities")}  # fmt: skip
    assert bs["Assets"] == bs["CapitalAndLiabilities"] == Decimal("45777597700000")
    assert bs["Advances"] == Decimal("31955660600000") and bs["Deposits"] == Decimal("33274489300000")
    pure = {f.name for f in i.facts if f.unit_ref == "pure"}
    assert "CET1Ratio" in pure
    assert not any("casa" in n.lower() or "crar" in n.lower() or "capitaladequacy" in n.lower() for n in pure)
    assert i.first_text("LevelOfRounding") == "Crores"


def test_annual_report_xbrl_has_two_years_and_notes(inst):
    """[X36] ELIN FY2024-25 Reg. 34 XBRL: ICAI Ind AS taxonomy 2017-03-31, current + previous FY contexts."""
    i = inst(ANNUAL)
    assert any(u.endswith("/2017-03-31/ind-as") for u in i.namespaces.values())
    from datetime import date

    periods = nondim_periods(i)
    assert (date(2024, 4, 1), date(2025, 3, 31), None) in periods
    assert (date(2023, 4, 1), date(2024, 3, 31), None) in periods
    assert {(None, None, date(2025, 3, 31)), (None, None, date(2024, 3, 31))} <= periods

    def by_year(name):
        out = {}
        for f in i.facts:
            c = i.contexts[f.context_id]
            if f.name == name and f.is_numeric and not c.dimensions:
                out[(c.end or c.instant).isoformat()] = f.decimal()
        return out

    assert by_year("CostOfMaterialsConsumed") == {"2025-03-31": Decimal("6584870000"),
                                                  "2024-03-31": Decimal("5806510000")}  # fmt: skip
    assert by_year("CapitalWorkInProgress") == {"2025-03-31": Decimal("33200000"), "2024-03-31": Decimal("119390000")}
    assert by_year("ContingentLiabilities") == {"2025-03-31": Decimal("88050000"), "2024-03-31": Decimal("120370000")}
    assert by_year("RevenueFromOperations")["2025-03-31"] == Decimal("9449470000")


def test_annual_lease_liabilities_are_labelled_others_lines(inst):
    """[X37] No LeaseLiabilities element: a free-text 'Lease Liabilities' label on an 'Others' member
    (duration context) names the amount held in the instant context of the same member."""
    i = inst(ANNUAL)
    assert not any(f.name == "LeaseLiabilities" for f in i.facts)
    labels = [f for f in i.facts if not f.is_numeric and f.value_text.strip() == "Lease Liabilities"]
    assert labels
    dims = i.contexts[labels[0].context_id].dimensions
    amounts = {
        i.contexts[f.context_id].instant.isoformat(): f.decimal()
        for f in i.facts
        if f.is_numeric and i.contexts[f.context_id].dimensions == dims and i.contexts[f.context_id].instant
    }
    assert amounts == {"2025-03-31": Decimal("60000"), "2024-03-31": Decimal("60000")}
    assert dims[0][0] == "ind-as:OtherCurrentFinancialLiabilitiesOthersAxis"


def test_shareholding_pledge_quantity_tags(inst):
    """[SHP7] Afcons 2026-09-30: pledged quantity and a percentage relative to the row's own shares."""
    i = inst(SHP_PLEDGED)
    assert i.first_text("Symbol") == "AFCONS"
    assert i.first_text("WhetherAnySharesHeldByPromotersAreEncumberedUnderPledged") == "true"
    rows = {}
    for f in i.facts:
        c = i.contexts[f.context_id]
        if len(c.dimensions) == 1 and f.is_numeric:
            rows.setdefault(c.dimensions[0][1].split(":")[-1], {})[f.name] = f.decimal()
    promoter, total = rows["ShareholdingOfPromoterAndPromoterGroupMember"], rows["ShareholdingPatternMember"]
    assert promoter["NumberOfShares"] == Decimal("184506596")
    assert promoter["NumberOfSharesEncumberedUnderPledged"] == Decimal("184500996")
    assert total["NumberOfSharesEncumberedUnderPledged"] == Decimal("184500996")
    assert total["NumberOfShares"] == Decimal("367784631")
    # "...AsPercentageOfTotalNumberOfShares" is relative to the row: 1 for promoters, 0.5017 overall.
    assert promoter["EncumberedShareUnderPledgedAsPercentageOfTotalNumberOfShares"] == Decimal("1")
    assert total["EncumberedShareUnderPledgedAsPercentageOfTotalNumberOfShares"] == Decimal("0.5017")
