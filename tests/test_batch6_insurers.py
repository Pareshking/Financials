"""Batch 6: insurer parsers on real Q2 FY27 filings: IRDAI life, IRDAI general, Ind AS 117 [X62-X66]."""

from datetime import date
from decimal import Decimal

import pytest

from _fixture_helpers import XBRL_DIR
from financials.fundamentals import FactBook, insurer_blocks
from financials.parsers.integrated import parse_integrated_results
from financials.parsers.irdai_insurance import parse_insurer_results
from financials.statements.quarterly import (
    general_quarter,
    indas_insurance_quarter,
    indas_insurance_tie_out,
    life_quarter,
    tie_out,
)

Q = (date(2026, 7, 1), date(2026, 9, 30))
H1 = (date(2026, 4, 1), date(2026, 9, 30))
END = date(2026, 9, 30)
STAR = XBRL_DIR / "IF_INS_COM_IND_AS_19799_WebXMLFile_20261027_212749295.xml"
SBI_LIFE = XBRL_DIR / "INTEGRATED_FILING_LI_1747186_27102026072642_WEB.xml"
NEW_INDIA = XBRL_DIR / "INTEGRATED_FILING_GI_1750325_30102026070447_WEB.xml"
HDFC_LIFE = XBRL_DIR / "INTEGRATED_FILING_LI_1739355_15102026072525_WEB.xml"
HDFC_LIFE_CONS = XBRL_DIR / "INTEGRATED_FILING_LI_1739360_15102026072721_WEB.xml"
ICICI_LOMBARD = XBRL_DIR / "INTEGRATED_FILING_GI_1740432_16102026073544_WEB.xml"
CR = Decimal(10) ** 7


@pytest.mark.parametrize(
    ("path", "profile"),
    [
        (STAR, "INDAS_INSURANCE"),
        (SBI_LIFE, "IRDAI_LIFE"),
        (HDFC_LIFE, "IRDAI_LIFE"),
        (HDFC_LIFE_CONS, "IRDAI_LIFE"),
        (NEW_INDIA, "IRDAI_GENERAL"),
        (ICICI_LOMBARD, "IRDAI_GENERAL"),
    ],
    ids=lambda x: getattr(x, "name", x)[:28],
)
def test_insurers_parse_clean_with_all_identities(path, profile):
    r = parse_integrated_results(path.read_bytes())
    assert r.profile == profile
    assert r.ok, r.issues


def test_ind_as_117_star_health():
    """[X64] Ind AS 117: revenue, service result, PBT, PAT, equity (ShareCapital + AssignedCapital + other)."""
    r = parse_insurer_results(STAR.read_bytes(), "INDAS_INSURANCE")
    v = lambda t: r.value(t, *Q)  # noqa: E731
    assert v("insurance_revenue") == Decimal("50737675000")
    assert v("insurance_revenue") - v("insurance_service_expenses") + v("net_reinsurance_result") == v(
        "insurance_service_result"
    )
    assert (v("pbt"), v("pat")) == (Decimal("3516366000"), Decimal("2648081000"))
    assert r.value("total_equity", END, END) + r.value("total_liabilities", END, END) == r.value(
        "total_assets", END, END
    )
    assert indas_insurance_tie_out(indas_insurance_quarter(r, *Q)) == 0


def test_star_health_files_are_one_blob():
    """[X64] The five Q2 FY27 'files' are byte-identical broadcasts; only one is committed (sha256 in MANIFEST)."""
    import hashlib

    assert hashlib.sha256(STAR.read_bytes()).hexdigest().startswith("903eb868")


def test_life_policyholder_and_shareholder_accounts_sbi_life():
    r = parse_insurer_results(SBI_LIFE.read_bytes(), "IRDAI_LIFE")
    v = lambda t: r.value(t, *Q)  # noqa: E731
    assert v("total_income") - v("total_expenses") == v("net_surplus")
    assert v("shareholders_income") - v("shareholders_expenses") == v("pbt")
    assert v("pat") == Decimal("5492318000")
    assert r.value("total_assets", END, END) == r.value("total_equity_and_liabilities", END, END)
    assert (v("solvency_ratio"), v("persistency_13m")) == (Decimal("1.97"), Decimal("0.8582"))
    assert tie_out(life_quarter(r, *Q)) == 0


def test_general_insurer_operating_profit_excludes_memo_provisions_new_india():
    """[X63] New India: operating profit = operating income - operating expenses; the provision lines are memo."""
    r = parse_insurer_results(NEW_INDIA.read_bytes(), "IRDAI_GENERAL")
    v = lambda t: r.value(t, *Q)  # noqa: E731
    assert v("operating_income") - v("operating_expenses") == v("operating_profit_insurance")
    assert v("net_premium_earned") == Decimal("96321800000") and v("pat") == Decimal("-12670400000")
    assert tie_out(general_quarter(r, *Q)) == 0


def test_solvency_percent_scaling_rule():
    """[X65] New India files 0.0161 (= 1.61x / 100); SBI Life files 1.97 (times): only the former is scaled."""
    ni = parse_insurer_results(NEW_INDIA.read_bytes(), "IRDAI_GENERAL")
    assert ni.value("solvency_ratio", *Q) == Decimal("0.0161")  # filed value kept
    assert ni.value("solvency_ratio_times", *Q) == Decimal("1.61")
    assert ni.meta["rules_applied"][0]["rule"] == "SOLVENCY_PERCENT_SCALING"
    sbi = parse_insurer_results(SBI_LIFE.read_bytes(), "IRDAI_LIFE")
    assert sbi.value("solvency_ratio_times", *Q) == Decimal("1.97") and "rules_applied" not in sbi.meta


@pytest.mark.parametrize("path", [NEW_INDIA, ICICI_LOMBARD], ids=["NIACL", "ICICIGI"])
def test_irdai_combined_ratio_matches_the_filed_ratio(path):
    """[X66] claims / NPE + (net commission + opex) / NPW reproduces the filed CombinedRatio (4 dp), Q and H1."""
    r = parse_insurer_results(path.read_bytes(), "IRDAI_GENERAL")
    for p in (Q, H1):
        v = lambda t, p=p: r.value(t, *p)  # noqa: E731
        claims = v("claims_incurred") / v("net_premium_earned")
        expense = (v("net_commission") + v("operating_expenses_insurance")) / v("net_premium_written")
        assert round(claims + expense, 4) == v("combined_ratio_filed")
        assert round(claims, 4) == v("claims_ratio_filed")


def test_gi_shareholders_funds_element_is_not_equity():
    """[X63] In the GI taxonomy ShareholdersFunds is the fair-value change account; equity is derived."""
    r = parse_insurer_results(NEW_INDIA.read_bytes(), "IRDAI_GENERAL")
    eq = r.value("equity_share_capital", END, END) + r.value("reserves_and_surplus", END, END)
    assert r.value("total_equity", END, END) == eq + (r.value("share_application_money", END, END) or 0)
    assert r.value("fair_value_change_shareholders", END, END) != r.value("total_equity", END, END)


def test_insurer_blocks_on_synthetic_books():
    qs = [(date(2025, 10, 1), date(2025, 12, 31)), (date(2026, 1, 1), date(2026, 3, 31)),
          (date(2026, 4, 1), date(2026, 6, 30)), Q]  # fmt: skip
    gi = FactBook("e", "STANDALONE")
    for tag, val in {"net_premium_earned": 100, "net_premium_written": 110, "claims_incurred": 70,
                     "net_commission": 11, "operating_expenses_insurance": 22,
                     "investment_income_policyholders": 8, "investment_income_shareholders": 2}.items():  # fmt: skip
        gi.durations[tag] = {p: Decimal(val) for p in qs}
    gi.durations["solvency_ratio_times"] = {Q: Decimal("1.61")}
    b = insurer_blocks(gi, END)
    assert b["insurer_basis"] == "IRDAI_GENERAL"
    assert b["claims_ratio"] == Decimal("0.7") and b["expense_ratio"] == Decimal(132) / Decimal(440)
    assert b["combined_ratio"] == Decimal("0.7") + Decimal(132) / Decimal(440)
    assert b["investment_income_ttm"] == Decimal(40) and b["solvency_ratio"] == Decimal("1.61")
    ind = FactBook("e", "STANDALONE")
    for tag, val in {"insurance_revenue": 100, "claims_incurred": 60, "insurance_service_expenses": 90,
                     "net_reinsurance_result": -4, "investment_income_total_indas": 5}.items():  # fmt: skip
        ind.durations[tag] = {p: Decimal(val) for p in qs}
    b = insurer_blocks(ind, END)
    assert b["insurer_basis"] == "INDAS117" and b["net_premium_earned_ttm"] is None
    assert b["claims_ratio"] == Decimal("0.6") and b["combined_ratio"] == Decimal(376) / Decimal(400)
    assert b["solvency_ratio"] is None


def test_legacy_gi_format_stays_unparsed():
    from _fixture_helpers import GEN_INS

    r = parse_integrated_results(GEN_INS.read_bytes())
    assert r.profile == "IRDAI_GENERAL_LEGACY"
    assert {i.reason_code for i in r.issues} == {"PROFILE_NOT_IMPLEMENTED"}


def test_supplemental_kpis_table_exists_with_point_in_time_key():
    from financials.db import apply_schema, connect, table_columns

    con = connect()
    apply_schema(con)
    cols = table_columns(con, "supplemental_kpis")
    assert {"entity_id", "kpi", "period_end", "value", "source_kind", "source_sha256", "visible_from_ts"} <= set(cols)
