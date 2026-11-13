"""INDAS_CORP parser against the real ELIN fixture, plus in-memory mutations of it.

Mutations are applied to bytes in memory; fixture files themselves are never modified.
"""

import re
from datetime import date, datetime
from decimal import Decimal

import pytest

from _fixture_helpers import BANK, CORP, GEN_INS, NBFC
from financials.parsers.indas_corp import parse_indas_corp_results, period_months

Q = (date(2026, 7, 1), date(2026, 9, 30))
H1 = (date(2026, 4, 1), date(2026, 9, 30))
END = date(2026, 9, 30)


@pytest.fixture(scope="module")
def corp_bytes() -> bytes:
    return CORP.read_bytes()


@pytest.fixture(scope="module")
def parsed(corp_bytes):
    return parse_indas_corp_results(corp_bytes)


def reasons(result) -> set[tuple[str, str]]:
    return {(i.stage, i.reason_code) for i in result.issues}


def test_real_filing_parses_clean(parsed):
    assert parsed.ok, parsed.issues
    assert parsed.profile == "INDAS_CORP"


def test_meta(parsed):
    m = parsed.meta
    assert m["scope"] == "STANDALONE"
    assert m["level_of_rounding"] == "Millions"
    assert (m["fy_start"], m["fy_end"]) == (date(2026, 4, 1), date(2027, 3, 31))
    assert m["quarter_period"] == Q and m["ytd_period"] == H1
    assert m["stated_isin"] == "INE050401020" and m["stated_symbol"] == "ELIN"
    assert m["board_meeting_end_ts"] == datetime(2026, 11, 5, 9, 27)  # 14:57 IST
    assert m["audited"] is False
    assert m["interest_paid_cfo_class"] == "FINANCING"
    assert m["interest_recd_cfo_class"] == "INVESTING"


def test_values_quarter_and_ytd_are_absolute_rupees(parsed):
    assert parsed.value("revenue_from_operations", *Q) == Decimal("2895440000")
    assert parsed.value("revenue_from_operations", *H1) == Decimal("5647590000")
    assert parsed.value("pat", *Q) == Decimal("14050000")
    assert parsed.value("pat", *H1) == Decimal("-184890000")


def test_cash_flow_only_for_ytd(parsed):
    assert parsed.value("cfo", *H1) == Decimal("-284140000")
    assert parsed.value("cfo", *Q) is None
    assert parsed.value("capex_ppe", *H1) == Decimal("344620000")  # positive magnitude [X15]


def test_balance_sheet_and_derived_shares(parsed):
    assert parsed.value("total_assets", END, END) == Decimal("6789940000")
    assert parsed.value("borrowings_current", END, END) == Decimal("202640000")
    assert parsed.value("shares_from_paid_up", END, END) == Decimal("49710000")


def test_period_months_and_types(parsed):
    months = {(f.canonical_tag, f.period_start): f.period_months for f in parsed.facts}
    assert months[("revenue_from_operations", Q[0])] == 3
    assert months[("revenue_from_operations", H1[0])] == 6
    assert all(f.period_months is None for f in parsed.facts if f.period_type == "INSTANT")


def test_prior_year_instant_is_not_mapped(parsed):
    assert all(f.period_end == END for f in parsed.facts if f.period_type == "INSTANT")


def test_dimensional_facts_are_not_mapped(parsed):
    # RPT detail rows live in dimensional contexts; only the non-dimensional total maps.
    rpt = [f for f in parsed.facts if f.canonical_tag == "rpt_total_amount"]
    assert len(rpt) == 1 and rpt[0].value == Decimal("891230000")


@pytest.mark.parametrize(("path", "profile"), [(NBFC, "INDAS_NBFC"), (BANK, "IGAAP_BANK"), (GEN_INS, "IRDAI_GENERAL")])
def test_other_profiles_are_routed_not_parsed(path, profile):
    r = parse_indas_corp_results(path.read_bytes())
    assert r.profile == profile
    assert reasons(r) == {("PARSE", "PROFILE_NOT_IMPLEMENTED")}
    assert not r.facts


def test_unknown_namespace(corp_bytes):
    r = parse_indas_corp_results(corp_bytes.replace(b"IntegratedFinance_IndAS", b"SomethingNew"))
    assert reasons(r) == {("PARSE", "UNKNOWN_TAXONOMY")}


def _set_context_start(data: bytes, context_id: str, new_start: str) -> bytes:
    pattern = rb'(id="' + context_id.encode() + rb'">.*?<xbrli:startDate>)([0-9-]+)(</xbrli:startDate>)'
    out, n = re.subn(pattern, rb"\g<1>" + new_start.encode() + rb"\g<3>", data, count=1, flags=re.S)
    assert n == 1
    return out


def test_star_health_style_context_defect_is_quarantined(corp_bytes):
    """FourD carrying the quarter's dates while declared period says H1 [X26]."""
    r = parse_indas_corp_results(_set_context_start(corp_bytes, "FourD", "2026-07-01"))
    assert ("PERIOD", "CONTEXT_CONFLICT") in reasons(r)
    assert not r.ok


def _set_value(data: bytes, element: str, context: str, value: str) -> bytes:
    pattern = rb"(<in-capmkt:" + element.encode() + rb' contextRef="' + context.encode() + rb'"[^>]*>)([^<]*)'
    out, n = re.subn(pattern, rb"\g<1>" + value.encode(), data, count=1)
    assert n == 1
    return out


def test_broken_expense_total_fails_identity(corp_bytes):
    r = parse_indas_corp_results(_set_value(corp_bytes, "Expenses", "OneD", "2881020000000"))
    codes = reasons(r)
    assert ("IDENTITY", "INCOME_MINUS_EXPENSES") in codes
    assert ("IDENTITY", "EXPENSE_COMPONENTS") in codes


def test_mismatch_within_rounding_tolerance_passes(corp_bytes):
    # Millions rounding, 3 terms: tolerance 1.5M rupees.
    r = parse_indas_corp_results(_set_value(corp_bytes, "ProfitBeforeTax", "OneD", "21750000"))
    assert r.ok, r.issues


def test_balance_sheet_mismatch(corp_bytes):
    r = parse_indas_corp_results(_set_value(corp_bytes, "Assets", "OneI", "7789940000"))
    assert ("IDENTITY", "BALANCE_SHEET") in reasons(r)


def test_missing_critical_tag(corp_bytes):
    data = re.sub(
        rb'<in-capmkt:ProfitBeforeTax contextRef="OneD"[^>]*>[^<]*</in-capmkt:ProfitBeforeTax>',
        b"",
        corp_bytes,
        count=1,
    )
    r = parse_indas_corp_results(data)
    assert ("PARSE", "MISSING_CRITICAL") in reasons(r)


def test_unknown_scope(corp_bytes):
    r = parse_indas_corp_results(corp_bytes.replace(b">Standalone<", b">Combined<"))
    assert ("PARSE", "UNKNOWN_SCOPE") in reasons(r)


@pytest.mark.parametrize(
    ("start", "end", "months"),
    [
        (date(2026, 7, 1), date(2026, 9, 30), 3),
        (date(2023, 1, 1), date(2024, 3, 31), 15),  # 15-month transition year [R6]
        (date(2026, 7, 2), date(2026, 9, 30), None),
        (date(2026, 7, 1), date(2026, 9, 29), None),
    ],
)
def test_period_months(start, end, months):
    assert period_months(start, end) == months
