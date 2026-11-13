"""Batch 4: INDAS_NBFC (Division III) parser on real Q2 FY27 lender filings [X54-X57, C13]."""

from datetime import date
from decimal import Decimal

import pytest

from _fixture_helpers import NBFC, XBRL_DIR
from financials.fundamentals import FactBook, nbfc_blocks
from financials.parsers.indas_nbfc import parse_indas_nbfc_results
from financials.parsers.integrated import parse_integrated_results
from financials.statements.quarterly import nbfc_quarter, tie_out

Q = (date(2026, 7, 1), date(2026, 9, 30))
H1 = (date(2026, 4, 1), date(2026, 9, 30))
END = date(2026, 9, 30)
BAJAJ = XBRL_DIR / "INTEGRATED_FILING_NBFC_INDAS_1742040_19102026075918_WEB.xml"
MUTHOOT = XBRL_DIR / "INTEGRATED_FILING_NBFC_INDAS_1750814_31102026080404_WEB.xml"
PNBHF = XBRL_DIR / "INTEGRATED_FILING_NBFC_INDAS_1748226_28102026075925_WEB.xml"
CHOLA = XBRL_DIR / "INTEGRATED_FILING_NBFC_INDAS_1748395_28102026112856_WEB.xml"
LENDERS = [BAJAJ, MUTHOOT, PNBHF]


@pytest.fixture(scope="module", params=LENDERS, ids=["BAJFINANCE", "MUTHOOTFIN", "PNBHOUSING"])
def lender(request):
    return parse_indas_nbfc_results(request.param.read_bytes())


def test_lenders_parse_clean_with_all_identities(lender):
    assert lender.ok, lender.issues
    assert lender.profile == "INDAS_NBFC"
    assert lender.meta["is_lending_nbfc"] is True and lender.meta["lending_basis"] == "LOANS_TO_ASSETS"


def test_division_iii_revenue_and_income_identities(lender):
    from financials.parsers.indas_nbfc import NBFC_REVENUE_COMPONENTS as parts

    for p in (Q, H1):
        total = sum((lender.value(t, *p) or Decimal(0)) for t in parts)
        assert total == lender.value("revenue_from_operations", *p)
        assert lender.value("revenue_from_operations", *p) + lender.value("other_income", *p) == lender.value(
            "total_income", *p
        )


def test_division_iii_balance_sheet(lender):
    a = lender.value("total_assets", END, END)
    assert lender.value("total_equity", END, END) + lender.value("total_liabilities", END, END) == a
    assert lender.value("loans", END, END) > 0


def test_ppop_equals_profit_before_exceptional_plus_impairment(lender):
    st = nbfc_quarter(lender, *Q)
    pbeit, imp = (
        lender.value("profit_before_exceptional_and_tax", *Q),
        lender.value("impairment_financial_instruments", *Q),
    )
    assert st.rows["PPOP"].value == pbeit + imp
    assert st.rows["NII"].value == lender.value("interest_earned", *Q) - lender.value("finance_costs", *Q)
    assert tie_out(st) == 0


def test_muthoot_gold_loan_values():
    r = parse_indas_nbfc_results(MUTHOOT.read_bytes())
    st = nbfc_quarter(r, *Q)
    assert st.rows["NII"].value == Decimal("61391770000")
    assert st.rows["PPOP"].value == Decimal("49923740000")
    assert r.value("loans", END, END) == Decimal("2104801550000")
    assert r.value("debt_securities", END, END) == Decimal("561630780000")
    assert st.rows["EPS"].value == Decimal("80.87")


def test_pnb_housing_negative_credit_cost_and_zero_attribution_rule():
    """[X48 recurrence] PNB Housing also tags owners = NCI = 0; impairment is a write-back (-47.56 Cr)."""
    r = parse_indas_nbfc_results(PNBHF.read_bytes())
    assert r.meta["rules_applied"][0]["rule"] == "ZERO_ATTRIBUTION_PLACEHOLDER"
    assert r.value("pat_owners", *Q) is None and r.value("pat", *Q) == Decimal("6165500000")
    assert r.value("impairment_financial_instruments", *Q) == Decimal("-475600000")
    assert nbfc_quarter(r, *Q).rows["Net Profit"].value == Decimal("6165500000")


def test_chola_owners_tagged_as_total_comprehensive_income_is_quarantined():
    """[X56] Cholamandalam tags TCI (1,763.61 Cr) as owners' profit; PAT is 1,630.34 Cr. One observation: quarantine,
    no rule (CLAUDE.md data invariant 9)."""
    r = parse_indas_nbfc_results(CHOLA.read_bytes())
    assert not r.ok
    assert {i.reason_code for i in r.issues} == {"OWNERS_PLUS_NCI"}
    q = next(i for i in r.issues if i.details["period"] == [str(Q[0]), str(Q[1])])
    assert (Decimal(q.details["lhs"]), Decimal(q.details["rhs"])) == (Decimal("17636100000"), Decimal("16303400000"))


def test_investment_holding_company_is_not_a_lender():
    """[C13] Jindal Poly Investment: InterestEarned 0.06 Cr (not 0) and Loans 0, so a rule on InterestEarned == 0
    alone would misclassify it."""
    r = parse_indas_nbfc_results(NBFC.read_bytes())
    assert r.ok, r.issues
    assert r.value("interest_earned", *Q) == Decimal("600000")
    assert r.meta["is_lending_nbfc"] is False


def test_dispatcher_routes_nbfc_and_keeps_other_profiles_unimplemented():
    """Banks became implemented in Batch 5; insurers remain unimplemented until Batch 6."""
    from _fixture_helpers import GEN_INS

    assert parse_integrated_results(BAJAJ.read_bytes()).profile == "INDAS_NBFC"
    ins = parse_integrated_results(GEN_INS.read_bytes())
    assert {i.reason_code for i in ins.issues} == {"PROFILE_NOT_IMPLEMENTED"}


def test_no_npa_elements_in_nbfc_taxonomy():
    """[X54] GNPA / NNPA / PCR are not in the NBFC taxonomy, so they stay NULL (never parsed from text)."""
    r = parse_indas_nbfc_results(BAJAJ.read_bytes())
    tags = {f.canonical_tag for f in r.facts}
    assert not {t for t in tags if "npa" in t or "non_performing" in t}


def _synthetic_lender() -> FactBook:
    b = FactBook("e", "CONSOLIDATED")
    qs = [(date(2025, 10, 1), date(2025, 12, 31)), (date(2026, 1, 1), date(2026, 3, 31)),
          (date(2026, 4, 1), date(2026, 6, 30)), (date(2026, 7, 1), date(2026, 9, 30))]  # fmt: skip
    for tag, v in {"interest_earned": 100, "finance_costs": 40, "revenue_from_operations": 120, "other_income": 2,
                   "total_expenses": 90, "impairment_financial_instruments": 10, "pat": 24}.items():  # fmt: skip
        b.durations[tag] = {p: Decimal(v) for p in qs}
    b.instants["loans"] = {date(2025, 9, 30): Decimal(1800), END: Decimal(2200)}
    b.instants["total_assets"] = {date(2025, 9, 30): Decimal(2400), END: Decimal(2600)}
    return b


def test_lending_ratios_on_a_synthetic_book():
    nb = nbfc_blocks(_synthetic_lender(), END)
    assert nb["is_lending_nbfc"] is True
    assert nb["nii_ttm"] == Decimal(240)  # 4 x (100 - 40)
    assert nb["ppop_ttm"] == Decimal(168)  # net total income 4 x (120 + 2 - 40) = 328, less opex 4 x (90-40-10) = 160
    assert nb["cost_to_income"] == Decimal(160) / Decimal(328)
    assert nb["credit_cost"] == Decimal(40) / Decimal(2000)  # avg loans (1800 + 2200) / 2
    assert nb["nim_asset_proxy"] == Decimal(240) / Decimal(2500)
    assert nb["roa"] == Decimal(96) / Decimal(2500)
    assert (nb["loans_avg_from"], nb["loans_as_of"]) == (date(2025, 9, 30), END)
    assert nb["gnpa_pct"] is None and nb["pcr"] is None


def test_averages_need_the_opening_balance_sheet():
    b = _synthetic_lender()
    del b.instants["loans"][date(2025, 9, 30)]
    nb = nbfc_blocks(b, END)
    assert nb["credit_cost"] is None and nb["loans_avg_from"] is None and nb["loans_as_of"] == END
    assert nb["nii_ttm"] == Decimal(240)


def test_nbfc_lease_and_rou_label_rules():
    """[X57] Muthoot labels 'Lease Liability' on OtherFinancialLiabilitiesAxis; Bajaj labels none (absent = none)."""
    m = parse_indas_nbfc_results(MUTHOOT.read_bytes())
    assert m.value("lease_liabilities", END, END) is not None and m.value("lease_liabilities", END, END) > 0
    b = parse_indas_nbfc_results(BAJAJ.read_bytes())
    assert b.value("lease_liabilities", END, END) is None
