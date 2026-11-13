"""Batch 5: IGAAP_BANK parser on real scheduled-commercial-bank filings [X58-X61]."""

from datetime import date
from decimal import Decimal

import pytest

from _fixture_helpers import XBRL_DIR
from financials.fundamentals import FactBook, bank_blocks
from financials.parsers.igaap_bank import ASSET_LINES, LIABILITY_LINES, parse_igaap_bank_results
from financials.parsers.integrated import parse_integrated_results
from financials.statements.quarterly import bank_quarter, tie_out

Q2 = (date(2026, 7, 1), date(2026, 9, 30))
Q1 = (date(2026, 4, 1), date(2026, 6, 30))
SEP = date(2026, 9, 30)
PNB = XBRL_DIR / "INTEGRATED_FILING_BANKING_1740465_16102026082727_WEB.xml"  # PSU, H1 with balance sheet
INDUSIND_Q1 = XBRL_DIR / "INTEGRATED_FILING_BANKING_1699404_22072026053243_WEB.xml"  # private, Q1, no balance sheet
KOTAK = XBRL_DIR / "INTEGRATED_FILING_BANKING_1745379_24102026050751_WEB.xml"  # face value mis-tagged
HDFC_STANDALONE = XBRL_DIR / "INTEGRATED_FILING_BANKING_1740912_17102026054806_WEB.xml"
HDFC_CONSOLIDATED = XBRL_DIR / "INTEGRATED_FILING_BANKING_1740913_17102026054812_WEB.xml"


@pytest.mark.parametrize(
    "path", [PNB, INDUSIND_Q1, KOTAK, HDFC_STANDALONE, HDFC_CONSOLIDATED], ids=lambda p: p.name[26:33]
)
def test_banks_parse_clean(path):
    r = parse_integrated_results(path.read_bytes())
    assert r.profile == "IGAAP_BANK"
    assert r.ok, r.issues


def test_rbi_format_identities_pnb():
    r = parse_igaap_bank_results(PNB.read_bytes())
    v = lambda t: r.value(t, *Q2)  # noqa: E731
    nii = v("interest_earned") - v("interest_expended")
    assert nii == Decimal("116012900000")
    assert nii + v("other_income") - v("operating_expenses") == v("ppop")  # PPOP = NII + OI - opex
    assert v("ppop") - v("provisions") + v("exceptional_items") == v("pbt")
    i = lambda t: r.value(t, SEP, SEP)  # noqa: E731
    assert sum(i(t) for t in LIABILITY_LINES) == i("total_assets") == sum(i(t) for t in ASSET_LINES)
    assert i("total_equity") == i("equity_share_capital") + i("reserves_and_surplus")


def test_q1_filing_has_no_balance_sheet_and_still_passes():
    r = parse_igaap_bank_results(INDUSIND_Q1.read_bytes())
    assert r.ok
    assert r.value("total_assets", Q1[1], Q1[1]) is None and r.value("advances", Q1[1], Q1[1]) is None
    assert r.value("pat", *Q1) == Decimal("10025000000")
    st = bank_quarter(r, *Q1)
    assert tie_out(st) == 0
    assert st.rows["PCR"].value == (Decimal("108486800000") - Decimal("31005400000")) / Decimal("108486800000")


def test_regulatory_ratios_are_fractions_and_psu_marker():
    r = parse_igaap_bank_results(PNB.read_bytes())
    assert (r.value("gnpa_pct", *Q2), r.value("nnpa_pct", *Q2)) == (Decimal("0.0255"), Decimal("0.0025"))
    assert (r.value("cet1_ratio", *Q2), r.value("at1_ratio", *Q2)) == (Decimal("0.1444"), Decimal("0.0145"))
    assert r.value("govt_holding_pct", *Q2) == Decimal("0.7008")


def test_consolidated_regulatory_zeros_are_dropped_not_read_as_zero():
    """[X60] HDFC Bank consolidated tags GNPA, NNPA, %s, RoA, CET1, AT1 all as 0; standalone has the real values."""
    cons = parse_igaap_bank_results(HDFC_CONSOLIDATED.read_bytes())
    assert cons.meta["rules_applied"][0]["rule"] == "CONSOLIDATED_REGULATORY_PLACEHOLDER"
    assert cons.value("gnpa_pct", *Q2) is None and cons.value("cet1_ratio", *Q2) is None
    stand = parse_igaap_bank_results(HDFC_STANDALONE.read_bytes())
    assert "rules_applied" not in stand.meta
    assert stand.value("gnpa_pct", *Q2) > 0


def test_standalone_zero_at1_is_kept():
    """A real 0 (IndusInd has no AT1 capital) is not a placeholder: the rule applies only to consolidated filings."""
    r = parse_igaap_bank_results(INDUSIND_Q1.read_bytes())
    assert r.value("at1_ratio", *Q1) == Decimal(0) and r.value("cet1_ratio", *Q1) == Decimal("0.161")


def test_kotak_face_value_mistag_withholds_derived_shares():
    """[X61] Kotak tags FaceValueOfEquityShareCapital = 994.79 (paid-up in crore): paid-up / face = 1 crore shares
    against ~996 crore implied by EPS 4.23. The derived share count is withheld; raw facts stay."""
    r = parse_igaap_bank_results(KOTAK.read_bytes())
    assert r.ok
    assert r.value("shares_from_paid_up", SEP, SEP) is None
    assert [w["code"] for w in r.meta["warnings"]] == ["EPS_INCONSISTENT", "SHARES_FROM_PAID_UP_WITHHELD"]
    assert r.value("face_value_per_share", *Q2) == Decimal("994.79")


def test_exceptional_item_divergence_on_hdfc_consolidated():
    st = bank_quarter(parse_igaap_bank_results(HDFC_CONSOLIDATED.read_bytes()), *Q2)
    assert any(d.startswith("BANK_EXCEPTIONAL") for d in st.divergences)
    assert tie_out(st) == 0


def _synthetic_bank() -> tuple[FactBook, FactBook]:
    b = FactBook("e", "CONSOLIDATED")
    qs = [(date(2025, 10, 1), date(2025, 12, 31)), (date(2026, 1, 1), date(2026, 3, 31)), Q1, Q2]
    for tag, v in {"interest_earned": 100, "interest_expended": 60, "other_income": 20, "operating_expenses": 30,
                   "ppop": 30, "provisions": 5, "pat": 20}.items():  # fmt: skip
        b.durations[tag] = {p: Decimal(v) for p in qs}
    b.instants["advances"] = {date(2025, 9, 30): Decimal(900), SEP: Decimal(1100)}
    b.instants["deposits"] = {SEP: Decimal(1400)}
    b.instants["total_assets"] = {date(2025, 9, 30): Decimal(1900), SEP: Decimal(2100)}
    reg = FactBook("e", "STANDALONE")
    reg.durations["gross_npa"] = {Q2: Decimal(30)}
    reg.durations["net_npa"] = {Q2: Decimal(9)}
    reg.durations["gnpa_pct"] = {Q2: Decimal("0.027")}
    reg.durations["cet1_ratio"] = {Q2: Decimal("0.15"), (date(2026, 4, 1), SEP): Decimal("0.149")}
    return b, reg


def test_bank_ratios_on_a_synthetic_book():
    b, reg = _synthetic_bank()
    nb = bank_blocks(b, SEP, reg)
    assert nb["nii_ttm"] == Decimal(160) and nb["ppop_ttm"] == Decimal(120)
    assert nb["cost_to_income"] == Decimal(120) / Decimal(160 + 80)  # opex / (NII + other income)
    assert nb["credit_cost"] == Decimal(20) / Decimal(1000)
    assert nb["nim_asset_proxy"] == Decimal(160) / Decimal(2000) and nb["roa"] == Decimal(80) / Decimal(2000)
    assert nb["credit_to_deposit"] == Decimal(1100) / Decimal(1400)
    assert nb["pcr"] == Decimal(21) / Decimal(30) and nb["gnpa_pct"] == Decimal("0.027")
    assert nb["cet1_pct"] == Decimal("0.15")  # the quarter context wins over the YTD one
    assert (nb["loans"], nb["loans_as_of"], nb["loans_avg_from"]) == (Decimal(1100), SEP, date(2025, 9, 30))


def test_bank_ratios_without_regulatory_book_stay_null():
    b, _ = _synthetic_bank()
    nb = bank_blocks(b, SEP)
    assert nb["gnpa_pct"] is None and nb["pcr"] is None and nb["cet1_pct"] is None
