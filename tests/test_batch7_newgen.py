"""Batch 7: new-gen tech filings (Q2 FY27 consolidated) and the new-gen ratio set [X67-X68, C21]."""

from datetime import date
from decimal import Decimal

import pytest

from _fixture_helpers import XBRL_DIR
from financials.admin import AdminError, set_archetype_override
from financials.db import apply_schema, connect, insert_rows
from financials.features import _curated_archetypes, _newgen_columns, derived_archetype
from financials.fundamentals import FactBook, building_blocks, newgen_inputs
from financials.parsers.indas_corp import LABEL_RULES, parse_indas_corp_results
from financials.parsers.integrated import parse_integrated_results

Q = (date(2026, 7, 1), date(2026, 9, 30))
H1 = (date(2026, 4, 1), date(2026, 9, 30))
END = date(2026, 9, 30)
CR = Decimal(10) ** 7
F = {
    "ETERNAL": "INTEGRATED_FILING_INDAS_1743410_21102026064843_WEB.xml",
    "INDIAMART": "INTEGRATED_FILING_INDAS_1747309_27102026112939_WEB.xml",
    "PAYTM": "INTEGRATED_FILING_INDAS_1746348_26102026105317_WEB.xml",
    "NAUKRI": "INTEGRATED_FILING_INDAS_1747783_28102026044327_WEB.xml",
    "DELHIVERY": "INTEGRATED_FILING_INDAS_1750274_30102026064310_WEB.xml",
    "OLAELEC": "INTEGRATED_FILING_INDAS_1756932_12112026075230_WEB.xml",
}


def parse(name):
    return parse_indas_corp_results((XBRL_DIR / F[name]).read_bytes())


@pytest.mark.parametrize("name", ["ETERNAL", "INDIAMART", "PAYTM", "NAUKRI", "DELHIVERY"])
def test_new_gen_filings_parse_clean(name):
    r = parse(name)
    assert r.ok, r.issues


def test_contract_liabilities_and_advertising_label_rules():
    """[X68] IndiaMART labels contract liabilities (current 1,244.6 / non-current 784.3 Cr); Paytm labels both plus
    'Marketing and promotional expenses'; Eternal labels 'Advertisement and sales promotion' (1,138 Cr)."""
    im, pt, et, nk = parse("INDIAMART"), parse("PAYTM"), parse("ETERNAL"), parse("NAUKRI")
    assert im.value("contract_liabilities_current", END, END) / CR == Decimal("1244.6")
    assert im.value("contract_liabilities_noncurrent", END, END) / CR == Decimal("784.3")
    assert pt.value("contract_liabilities_current", END, END) / CR == Decimal("86")
    assert pt.value("advertising_promotion", *Q) / CR == Decimal("194")
    assert et.value("advertising_promotion", *Q) / CR == Decimal("1138")
    assert (
        nk.value("contract_liabilities_current", END, END) is None
    )  # Info Edge labels only "Other current liabilities"


def test_esop_is_only_a_cash_flow_addback():
    """[X68] Share-based payment cost appears only as AdjustmentsForSharebasedPayments in the H1 context."""
    for name, h1 in (("ETERNAL", "517"), ("PAYTM", "97")):
        r = parse(name)
        assert r.value("share_based_payments_addback", *H1) / CR == Decimal(h1)
        assert r.value("share_based_payments_addback", *Q) is None


@pytest.mark.parametrize(
    ("label", "rule", "matches"),
    [("Contract liabilities", "CONTRACT_LIABILITIES_CURRENT", True),
     ("Advances from customers", "CONTRACT_LIABILITIES_CURRENT", True),
     ("Deferred revenue", "CONTRACT_LIABILITIES_CURRENT", True),
     ("Other current liabilities", "CONTRACT_LIABILITIES_CURRENT", False),
     ("Advertisement and sales promotion", "ADVERTISING", True),
     ("Marketing and promotional expenses", "ADVERTISING", True),
     ("Delivery and related charges", "ADVERTISING", False)],
)  # fmt: skip
def test_new_label_patterns(label, rule, matches):
    (rx,) = [r[5] for r in LABEL_RULES if r[0] == rule]
    assert bool(rx.match(label)) is matches


def test_delhivery_second_owners_tci_observation():
    """[X67] Delhivery: owners' profit = TCI (75.454 Cr H1) vs PAT 72.545, NCI 0: the named rule now applies."""
    r = parse("DELHIVERY")
    assert r.meta["rules_applied"][-1]["rule"] == "OWNERS_TAGGED_AS_TCI"
    assert r.value("pat_owners", *H1) == r.value("pat", *H1)


def test_ola_sign_flip_is_recovered_by_the_named_rule():
    """[X67, X85] Ola Electric H1: owners' profit +698 Cr against PAT -698 Cr, NCI 0. Quarantined while it was a single
    observation (X67); the live backfill showed ~20 more sign flips (Godrej Agrovet H1 FY27, HAL, PVR INOX), so
    ATTRIBUTION_SIGN_FLIP now applies: flipping exactly one sign makes owners + NCI = PAT."""
    r = parse("OLAELEC")
    assert not r.issues
    assert r.value("pat", *H1) / CR == Decimal("-698")
    assert r.value("pat_owners", *H1) == r.value("pat", *H1)
    assert {"rule": "ATTRIBUTION_SIGN_FLIP", "periods": [[str(d) for d in H1]]} in r.meta["rules_applied"]


def test_icici_prudential_parses_under_its_new_symbol():
    """ICICILIFE (formerly ICICIPRULI) Q2 FY27: IRDAI_LIFE, all identities; the XBRL still carries ICICIPRULI."""
    r = parse_integrated_results((XBRL_DIR / "INTEGRATED_FILING_LI_1736933_13102026040430_WEB.xml").read_bytes())
    assert (r.profile, r.ok) == ("IRDAI_LIFE", True)
    assert r.meta["stated_symbol"] == "ICICIPRULI"


def test_archetypes():
    curated = _curated_archetypes()
    assert curated["ETERNAL"] == curated["PAYTM"] == "NEW_GEN_TECH" and len(curated) == 10
    corp, bank, ins = FactBook("e", "C"), FactBook("e", "C"), FactBook("e", "C")
    corp.durations["revenue_from_operations"] = {Q: Decimal(1)}
    bank.durations["interest_expended"] = {Q: Decimal(1)}
    ins.durations["net_premium_earned"] = {Q: Decimal(1)}
    assert [derived_archetype(b) for b in (corp, bank, ins)] == [
        "INDUSTRIAL_SERVICES",
        "FINANCIAL_LENDING",
        "INSURANCE",
    ]


def test_archetype_override_is_audited():
    con = connect()
    apply_schema(con)
    insert_rows(con, "entity_master", [{"entity_id": "e", "legal_name": "X"}])
    set_archetype_override(con, "e", archetype="NEW_GEN_TECH", reason="platform")
    assert con.execute("SELECT valuation_archetype FROM entity_archetype_override").fetchall() == [("NEW_GEN_TECH",)]
    set_archetype_override(con, "e", archetype=None, reason="clear")
    assert con.execute("SELECT count(*) FROM entity_archetype_override").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM company_overrides WHERE field = 'valuation_archetype'").fetchone()[0] == 2
    with pytest.raises(AdminError):
        set_archetype_override(con, "e", archetype="FINTECH", reason="x")


def _newgen_book(fcf_negative=False) -> FactBook:
    b = FactBook("e", "CONSOLIDATED")
    qs = [(date(2025, 10, 1), date(2025, 12, 31)), (date(2026, 1, 1), date(2026, 3, 31)),
          (date(2026, 4, 1), date(2026, 6, 30)), Q]  # fmt: skip
    flows = {"revenue_from_operations": 1000, "pat": 50, "pbt": 60, "tax_expense": 10, "other_income": 20,
             "profit_before_exceptional_and_tax": 60, "finance_costs": 5, "depreciation_amortisation": 15,
             "cost_of_materials_consumed": 0, "purchases_of_stock_in_trade": 0,
             "changes_in_inventories": 0}  # fmt: skip
    for tag, v in flows.items():
        b.durations[tag] = {p: Decimal(v) for p in qs}
    fy0, h10 = (date(2025, 4, 1), date(2026, 3, 31)), (date(2025, 4, 1), date(2025, 9, 30))
    cfo = (-400, -900, -350) if fcf_negative else (200, 450, 180)
    for tag, (a, c, e) in {"cfo": cfo, "capex_ppe": (40, 80, 30), "share_based_payments_addback": (30, 70, 25)}.items():
        b.durations[tag] = {H1: Decimal(a), fy0: Decimal(c), h10: Decimal(e)}
    for d in (END, date(2025, 9, 30)):
        for tag, v in {"total_assets": 5000, "cash_and_equivalents": 300, "bank_balances_other": 100,
                       "current_investments": 600, "noncurrent_investments": 9000, "trade_payables_current": 400,
                       "trade_receivables_current": 150, "inventories": 50,
                       "contract_liabilities_current": 200 if d == END else 120}.items():  # fmt: skip
            b.instants.setdefault(tag, {})[d] = Decimal(v)
    return b


def test_new_gen_inputs_and_ratios():
    book = _newgen_book()
    b = building_blocks(book, END)
    ng = newgen_inputs(book, END, b)
    assert ng["liquid_cash"] == Decimal(1000)  # non-current investments (9,000) excluded
    assert ng["billings_ttm"] == Decimal(4000) + (Decimal(200) - Decimal(120))
    assert ng["esop_ttm"] == Decimal(30 + 70 - 25)
    assert ng["esop_adj_fcf"] == b["fcf"] - Decimal(75)
    assert ng["neg_working_capital_float_pct"] == ((Decimal(400) + 200) - (Decimal(150) + 50)) / Decimal(4000)
    assert ng["ex_cash_earnings"] == b["pat_owners_continuing"] - Decimal(80) * (1 - b["etr"])
    assert ng["cash_runway_months"] is None and ng["rule_of_40"] is None  # FCF > 0; YoY needs 8 quarters
    fund = {"_cfo": b["cfo"], "_gross_profit": None, "_lender": False}
    cols = _newgen_columns(ng, Decimal(20000), Decimal(19500), fund)
    assert cols["ev_to_billings"] == pytest.approx(19500 / 4080)
    assert cols["ex_cash_pe"] == pytest.approx(19000 / float(ng["ex_cash_earnings"]))
    assert cols["price_to_cfo"] == pytest.approx(20000 / float(b["cfo"]))
    assert cols["ev_to_gross_profit"] is None  # services company: no gross profit (COGS guard)


def test_cash_runway_for_a_cash_burner():
    book = _newgen_book(fcf_negative=True)
    b = building_blocks(book, END)
    ng = newgen_inputs(book, END, b)
    assert b["fcf"] < 0
    assert ng["cash_runway_months"] == Decimal(1000) / (-b["fcf"] / 12)
    lender = _newgen_columns(ng, Decimal(1), Decimal(1), {"_lender": True, "_cfo": None, "_gross_profit": None})
    assert all(v is None for v in lender.values())  # new-gen ratios are NULL for lenders / insurers
