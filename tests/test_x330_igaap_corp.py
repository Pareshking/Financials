"""X330-X334 (work QG): IGAAP_CORP, SME-listed companies' Integrated Filing results on SEBI's non-Ind AS template
(`IntegratedFinance_OtherThanBank`, Schedule III Division I). Characterisation of real, unmodified filings in
tests/fixtures/igaap_corp/ (MANIFEST.md "QG"): profile routing, scope, periods, LevelOfRounding, the Division I profit
chain, attribution and the balance sheet, and rule AMOUNTS_AND_EPS_SCALED."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest
import yaml

from _fixture_helpers import FIXTURES, XBRL_DIR
from financials.money import identity_tolerance
from financials.parsers.igaap_corp import IGAAP_DURATION_TAGS, IGAAP_INSTANT_TAGS, parse_igaap_corp_results
from financials.parsers.indas_corp import detect_instance_profile
from financials.parsers.integrated import parse_integrated_results
from financials.parsers.xbrl import parse_instance

D = FIXTURES / "igaap_corp"
VIVIANA_S_Q1 = D / "INTEGRATED_FILING_NONINDAS_1509526_12082025041915_WEB.xml"
VIVIANA_C_Q1 = D / "INTEGRATED_FILING_NONINDAS_1509532_12082025042000_WEB.xml"
PARIN_C_H2 = D / "INTEGRATED_FILING_NONINDAS_1650266_13042026110130_WEB.xml"
LEMERITE_C_H1 = D / "INTEGRATED_FILING_NONINDAS_1573202_13112025120518_WEB.xml"
GICL_S_Q2_SCALED = D / "INTEGRATED_FILING_NONINDAS_1575526_14112025065604_WEB.xml"
GICL_S_Q2_REFILED = D / "INTEGRATED_FILING_NONINDAS_1601469_15012026024456_WEB.xml"
MRPL_WRONG_TEMPLATE = XBRL_DIR / "INTEGRATED_FILING_INDAS_1487244_18072025075933_WEB.xml"  # X89, Main Board
ALL = sorted(D.glob("*.xml"))

Q1_FY26 = (date(2025, 4, 1), date(2025, 6, 30))
H1_FY26 = (date(2025, 4, 1), date(2025, 9, 30))
Q2_FY26 = (date(2025, 7, 1), date(2025, 9, 30))
H2_FY26 = (date(2025, 10, 1), date(2026, 3, 31))
FY26 = (date(2025, 4, 1), date(2026, 3, 31))


def _parse(path: Path):
    return parse_integrated_results(path.read_bytes(), path.name)


@pytest.mark.parametrize("path", ALL, ids=lambda p: p.name[27:41])
def test_x330_sme_filings_on_the_non_indas_template_are_igaap_corp(path):
    inst = parse_instance(path.read_bytes())
    assert "/IntegratedFinance_OtherThanBank/" in inst.entity_namespace
    assert {f.value_text for f in inst.facts if f.name == "TypeOfCompany"} == {"SME"}
    assert detect_instance_profile(inst) == "IGAAP_CORP"
    assert _parse(path).profile == "IGAAP_CORP"


def test_x330_main_board_filing_on_that_template_stays_unknown_taxonomy():
    """X89's MRPL Q1 FY26 (an Ind AS company on the wrong template) states TypeOfCompany Main Board."""
    inst = parse_instance(MRPL_WRONG_TEMPLATE.read_bytes())
    assert {f.value_text for f in inst.facts if f.name == "TypeOfCompany"} == {"Main Board"}
    assert detect_instance_profile(inst) is None
    r = _parse(MRPL_WRONG_TEMPLATE)
    assert r.profile is None and not r.facts
    # details as before X330 (the finding id derives from them); X89 selects on the namespace
    assert [(i.reason_code, i.details) for i in r.issues] == [
        ("UNKNOWN_TAXONOMY", {"entity_namespace": inst.entity_namespace})
    ]


def test_x331_standalone_quarter_meta_and_profit_chain():
    r = parse_igaap_corp_results(VIVIANA_S_Q1.read_bytes())
    assert r.issues == [] and r.findings == []
    m = r.meta
    assert (m["scope"], m["level_of_rounding"], m["reporting_quarter"], m["audited"]) == (
        "STANDALONE", "Lakhs", "First quarter", False)  # fmt: skip
    assert m["quarter_period"] == m["ytd_period"] == Q1_FY26
    v = lambda t: r.value(t, *Q1_FY26)  # noqa: E731
    assert v("revenue_from_operations") == Decimal("207813000")
    assert v("total_income") == Decimal("214221000")
    assert v("total_expenses") == Decimal("187172000")
    assert v("pbt") == Decimal("27049000") and v("tax_expense") == Decimal("6171000")
    assert v("pat") == v("pat_after_minority") == Decimal("20878000")
    assert v("pat_owners") is None and v("pat_nci") is None  # standalone: no attribution
    assert v("eps_basic") == Decimal("3.33") and v("face_value_per_share") == Decimal("10")
    assert r.value("shares_from_paid_up", Q1_FY26[1], Q1_FY26[1]) == Decimal("6275000")
    assert {f.period_months for f in r.facts if f.period_type == "DURATION"} == {3}
    assert not [f for f in r.facts if f.canonical_tag.startswith(("oci", "total_comprehensive"))]  # no OCI in AS


def test_x331_consolidated_quarter_adds_the_share_of_associates():
    r = parse_igaap_corp_results(VIVIANA_C_Q1.read_bytes())
    assert r.issues == [] and r.meta["scope"] == "CONSOLIDATED"
    v = lambda t: r.value(t, *Q1_FY26)  # noqa: E731
    assert v("pat_before_minority") == Decimal("31607000")
    assert v("share_of_associates_jv") == Decimal("1049000")
    assert v("pat_after_minority") == v("pat") == v("pat_owners") == Decimal("32656000")
    assert v("pat_nci") == 0


def test_x331_x332_half_year_with_extraordinary_items_and_minority():
    """PARIN H2 FY26 (2026-01-31 taxonomy, audited FY): extraordinary items filed signed and added to PBT; the
    minority line filed negative and added to the owners' profit, which the filed EPS confirms."""
    r = parse_igaap_corp_results(PARIN_C_H2.read_bytes())
    assert r.issues == []
    assert "IntegratedFinance_OtherThanBank/2026-01-31" in r.taxonomy_ns
    m = r.meta
    assert (m["quarter_period"], m["ytd_period"], m["reporting_quarter"], m["audited"]) == (
        H2_FY26, FY26, "Yearly", True)  # fmt: skip
    assert {(f.period_start, f.period_end, f.period_months) for f in r.facts if f.period_type == "DURATION"} == {
        (*H2_FY26, 6), (*FY26, 12)}  # fmt: skip
    for per, xo, pbt, minority, owners in ((H2_FY26, "-1800000", "59703000", "-5154000", "37964000"),
                                           (FY26, "-3600000", "101833000", "-10335000", "62915000")):  # fmt: skip
        v = lambda t, per=per: r.value(t, *per)  # noqa: E731
        assert v("exceptional_items") == 0
        assert v("profit_before_extraordinary_and_tax") + Decimal(xo) == v("pbt") == Decimal(pbt)
        assert v("extraordinary_items") == Decimal(xo)
        assert v("pat_minority_interest_line") == Decimal(minority)
        assert v("pat_owners") == v("pat_after_minority") == Decimal(owners)
        assert v("pat_nci") == -Decimal(minority)
        assert v("pat") == v("pat_before_minority") == v("pat_owners") + v("pat_nci")
        shares = r.value("shares_from_paid_up", *(FY26[1],) * 2)
        assert abs(v("eps_basic") * shares - v("pat_owners")) <= Decimal("0.005") * v("pat_owners")
    e = FY26[1]
    b = lambda t: r.value(t, e, e)  # noqa: E731
    assert b("equity_attributable_to_owners") == Decimal("751690000")
    assert b("non_controlling_interest") == Decimal("17342000")
    assert b("total_equity") == Decimal("769032000")  # DERIVED: ShareholdersFunds + MinorityInterest
    assert b("total_liabilities") == b("noncurrent_liabilities") + b("current_liabilities") == Decimal("1176397000")
    assert b("total_assets") == b("total_equity_and_liabilities") == b("total_equity") + b("total_liabilities")
    assert r.value("cfo", *FY26) == Decimal("25577000")
    assert {x["rule"] for x in m["rules_applied"]} == {"IGAAP_ATTRIBUTION"}


def test_x332_positive_minority_line_is_the_minority_share_of_a_loss():
    """LEMERITE H1 FY26: minority line +2.88 lakh; owners 851.61 lakh, EPS 3.50 x 2,43,60,000 shares = 852.60 lakh
    (owners, not PAT 848.73 lakh)."""
    r = parse_igaap_corp_results(LEMERITE_C_H1.read_bytes())
    assert r.issues == [] and r.meta["reporting_quarter"] == "Half yearly"
    v = lambda t: r.value(t, *H1_FY26)  # noqa: E731
    assert v("pat_minority_interest_line") == Decimal("288000")
    assert (v("pat_owners"), v("pat_nci"), v("pat")) == (Decimal("85161000"), Decimal("-288000"), Decimal("84873000"))
    implied = v("eps_basic") * r.value("shares_from_paid_up", H1_FY26[1], H1_FY26[1])
    assert abs(implied - v("pat_owners")) < abs(implied - v("pat"))
    assert r.value("non_controlling_interest", H1_FY26[1], H1_FY26[1]) == Decimal("-11706000")


def test_x331_identities_use_the_level_of_rounding_tolerance():
    """A PBT one Lakh rounding unit off the chain fails IGAAP_EXTRAORDINARY (in-memory copy; the fixture is
    untouched)."""
    data = PARIN_C_H2.read_bytes()
    assert data.count(b">59703000<") == 1
    r = parse_igaap_corp_results(data.replace(b">59703000<", b">59903000<"))
    assert identity_tolerance("Lakhs", 3) < Decimal("200000")
    assert "IGAAP_EXTRAORDINARY" in {i.reason_code for i in r.issues}


def test_x333_amounts_and_eps_scaled_blocks_the_filing():
    """GICL Q2 FY26 standalone of 14 Nov 2025: every amount and the EPS are 1e5x those of its 15 Jan 2026
    re-filing; quarantined whole, never rescaled."""
    bad = parse_igaap_corp_results(GICL_S_Q2_SCALED.read_bytes())
    assert [(i.reason_code, i.details["rule"], i.details["factor"]) for i in bad.issues] == [
        ("AMOUNTS_SCALED", "AMOUNTS_AND_EPS_SCALED", "100000")]  # fmt: skip
    good = parse_igaap_corp_results(GICL_S_Q2_REFILED.read_bytes())
    assert good.issues == [] and good.meta["quarter_period"] == Q2_FY26 and good.meta["ytd_period"] == H1_FY26
    for tag in ("revenue_from_operations", "eps_basic"):
        assert bad.value(tag, *Q2_FY26) == good.value(tag, *Q2_FY26) * 100000, tag
    for tag in ("pat", "paid_up_equity_capital"):  # rounded apart: PAT 181.88 vs 181.89 lakh
        assert abs(bad.value(tag, *Q2_FY26) / 100000 - good.value(tag, *Q2_FY26)) <= 1000, tag
    assert good.value("pat", *Q2_FY26) == Decimal("18189000") and good.value("eps_basic", *Q2_FY26) == Decimal("0.61")
    assert good.value("exceptional_items", *Q2_FY26) == Decimal("-210000")


def test_x331_registry_covers_every_element_of_the_fixtures():
    registry = yaml.safe_load((Path(__file__).parents[1] / "docs" / "tag_registry.yaml").read_text())
    registered = set(registry["profiles"]["IGAAP_CORP"])
    for path in ALL:
        inst = parse_instance(path.read_bytes())
        assert {f.name for f in inst.facts if not inst.contexts[f.context_id].dimensions} <= registered, path.name
        assert path.name in registry["files"]
    mapped = {**IGAAP_DURATION_TAGS, **IGAAP_INSTANT_TAGS}
    assert set(mapped) <= registered  # only elements seen in a committed fixture are mapped


def test_x334_igaap_corp_is_its_own_accounting_basis():
    from financials.fundamentals import _BASIS

    rows = duckdb.connect().execute(
        f"SELECT accounting_profile, {_BASIS} FROM (VALUES ('IGAAP_CORP'), ('INDAS_CORP')) t(accounting_profile) "
        "ORDER BY 1").fetchall()  # fmt: skip
    assert rows == [("IGAAP_CORP", "IGAAP_CORP"), ("INDAS_CORP", "INDAS")]


def test_x331_staging_writes_the_igaap_corp_profile():
    from financials.staging import results_tables

    data = VIVIANA_C_Q1.read_bytes()
    t = results_tables("fil_test", parse_instance(data), data, "https://example.invalid/" + VIVIANA_C_Q1.name)
    assert "stg_issues" not in t
    assert [(r["accounting_profile"], r["scope"], r["period_end"]) for r in t["stg_xbrl_filing"]] == [
        ("IGAAP_CORP", "CONSOLIDATED", Q1_FY26[1])]  # fmt: skip
    pat = [r for r in t["stg_xbrl_facts"] if r["canonical_tag"] == "pat"]
    assert [(r["value_inr"], r["period_months"], r["source_element"]) for r in pat] == [
        (Decimal("32656000.00"), 3, "DERIVED:ProfitLossForThePeriod-ProfitLossOfMinorityInterest")]  # fmt: skip
