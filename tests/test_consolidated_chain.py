"""Consolidated profit chain on a real regulated-utility filing [X42] (Tata Power Q2 FY27, consolidated).

PBT - tax + regulatory deferral movement = PAT (continuing)
PAT (continuing) + discontinued + share of associates/JVs = PAT
owners + NCI = PAT;  equity attributable to owners + NCI = total equity
"""

from datetime import date
from decimal import Decimal

import pytest

from _fixture_helpers import XBRL_DIR
from financials.parsers.indas_corp import parse_indas_corp_results

TATAPOWER = XBRL_DIR / "INTEGRATED_FILING_INDAS_1756234_11112026070341_WEB.xml"
Q = (date(2026, 7, 1), date(2026, 9, 30))
END = date(2026, 9, 30)


@pytest.fixture(scope="module")
def tp():
    return parse_indas_corp_results(TATAPOWER.read_bytes())


def test_parses_clean_with_regulatory_deferral(tp):
    assert tp.ok, tp.issues
    v = {t: tp.value(t, *Q) for t in ("pbt", "tax_expense", "regulatory_deferral_movement", "pat_continuing")}
    assert v == {
        "pbt": Decimal("14429100000"),
        "tax_expense": Decimal("5278100000"),
        "regulatory_deferral_movement": Decimal("2501400000"),
        "pat_continuing": Decimal("11652400000"),
    }
    assert v["pbt"] - v["tax_expense"] + v["regulatory_deferral_movement"] == v["pat_continuing"]


def test_associates_sit_after_continuing_pat(tp):
    assert tp.value("share_of_associates_jv", *Q) == Decimal("4868000000")
    assert tp.value("pat_continuing", *Q) + tp.value("share_of_associates_jv", *Q) == tp.value("pat", *Q)


def test_owners_nci_split(tp):
    assert tp.value("pat_owners", *Q) == Decimal("13661100000")
    assert tp.value("pat_nci", *Q) == Decimal("2859300000")
    assert tp.value("pat_owners", *Q) + tp.value("pat_nci", *Q) == tp.value("pat", *Q)
    owners, nci = tp.value("equity_attributable_to_owners", END, END), tp.value("non_controlling_interest", END, END)
    assert (owners, nci) == (Decimal("414483800000"), Decimal("78826500000"))
    assert owners + nci == tp.value("total_equity", END, END)


def test_dropping_regulatory_term_would_break_identity():
    """Without the regdef element the old PBT-tax=PATc check must fire: proves the term is load-bearing."""
    data = TATAPOWER.read_bytes().replace(
        b"NetMovementInRegulatoryDeferralAccountBalancesRelatedToProfitOrLossAndTheRelatedDeferredTaxMovement",
        b"NetMovementInRegulatoryDeferralRenamedForTest",
    )
    r = parse_indas_corp_results(data)
    assert ("IDENTITY", "PBT_MINUS_TAX") in {(i.stage, i.reason_code) for i in r.issues}


def test_equity_method_investments_are_separate_from_noncurrent_investments(tp):
    """[X44] Tata Power: associates/JVs 13485.22 Cr sit outside NoncurrentInvestments 2748.69 Cr."""
    from financials.fundamentals import FactBook, building_blocks

    assert tp.value("equity_method_investments", END, END) == Decimal("134852200000")
    book = FactBook("e", "CONSOLIDATED")
    for f in tp.facts:
        if f.period_type == "INSTANT":
            book.instants.setdefault(f.canonical_tag, {})[f.period_end] = f.value
    b = building_blocks(book, END)
    nci, ci = tp.value("noncurrent_investments", END, END), tp.value("current_investments", END, END) or 0
    assert b["investments"] == nci + ci + Decimal("134852200000")
    assert b["invested_capital"] - b["operating_invested_capital"] == Decimal("134852200000")
