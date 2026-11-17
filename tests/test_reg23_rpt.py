"""Reg. 23(9) related-party transactions per counterparty in the Integrated Filing [X19, X115]: parser
characterisation on the 27 committed filings that carry the section, promotion with the results filing, and
`backfill-rpt` for results filings. Every value is read straight from the XML."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal

import pytest

from _fixture_helpers import XBRL_DIR
from financials.parsers.integrated import parse_integrated_results
from financials.parsers.reg23_rpt import REG23_PARSER_VERSION, TYPE_MAP, parse_reg23_rpt
from financials.parsers.xbrl import parse_instance
from financials.promoter import promote
from financials.related_parties import backfill_rpt, pending_results_filings
from financials.staging import stage_results_xbrl

NETWEB = "INTEGRATED_FILING_INDAS_1668217_16052026103806_WEB.xml"  # Q4 FY26 standalone, Jan-Mar context
NETWEB_OCT_MAR = "INTEGRATED_FILING_INDAS_1663034_02052026072054_WEB.xml"  # first filing, Oct-Mar context (X82)
TMPV = "INTEGRATED_FILING_INDAS_1574914_14112025041626_WEB.xml"  # Q2 FY26 standalone
RELIANCE = "INTEGRATED_FILING_INDAS_1750535_30102026093155_WEB.xml"  # Q2 FY27 standalone
WITH_SECTION = sorted(p.name for p in XBRL_DIR.glob("*.xml") if b"NameOfCounterParty" in p.read_bytes())


def _parse(name: str):
    data = (XBRL_DIR / name).read_bytes()
    parsed = parse_integrated_results(data, name)
    return parsed, parse_instance(data), parse_reg23_rpt(parse_instance(data), parsed.meta["period_end"])


def _one(rows, name, member=None):
    hits = [r for r in rows if r.counterparty_name == name and (member is None or r.row_member == member)]
    assert len(hits) == 1, hits
    return hits[0]


def test_netweb_rows_and_balances():
    _, _, rows = _parse(NETWEB)
    assert len(rows) == 6
    sanjay = _one(rows, "Sanjay Lodha")
    assert (sanjay.row_member, sanjay.period_start, sanjay.period_end, sanjay.period_months) == (
        "RelatedPartyTransactionDomain1", date(2026, 1, 1), date(2026, 3, 31), 3)  # fmt: skip
    assert (sanjay.listed_party_name, sanjay.relationship, sanjay.type_as_filed, sanjay.txn_type) == (
        "Netweb Technologies India Limited", "Managing Director", "Remuneration", "remuneration")  # fmt: skip
    assert (sanjay.amount, sanjay.approved_value, sanjay.opening_balance, sanjay.closing_balance) == (
        Decimal("31270000"), Decimal("50000000"), Decimal("0"), Decimal("630000"))  # fmt: skip
    assert sanjay.counterparty_pan is None  # filed as "******"
    assert sanjay.approval_remarks == "Within the omnibus approval limit"
    navin = _one(rows, "Navin Lodha")
    assert (navin.relationship, navin.amount, navin.closing_balance) == (
        "Whole Time Director", Decimal("21840000"), Decimal("760000"))  # fmt: skip


def test_context_dates_do_not_prove_the_disclosure_period():
    """NETWEB filed the same six rows with the same amounts in an Oct-Mar and, re-filed, in a Jan-Mar context: the
    tagged period is the filing's reporting-period context; the disclosure period is the half-year by HALF_YEAR_RULE
    (X160, tests/test_reg23_period.py), the same for both."""
    _, _, first = _parse(NETWEB_OCT_MAR)
    _, _, refiled = _parse(NETWEB)
    assert {(r.period_start, r.period_months) for r in first} == {(date(2025, 10, 1), 6)}
    assert {(r.period_start, r.period_months) for r in refiled} == {(date(2026, 1, 1), 3)}

    def key(r):
        return (r.row_member, r.counterparty_name, r.txn_type, r.amount, r.opening_balance, r.closing_balance)

    assert [key(r) for r in first] == [key(r) for r in refiled]
    assert {(r.disclosure_start, r.disclosure_months) for r in first + refiled} == {(date(2025, 10, 1), 6)}


def test_tmpv_subsidiary_transactions_on_the_consolidated_basis():
    _, _, rows = _parse(TMPV)
    assert len(rows) == 821
    gmbh = _one(rows, "Tata Technologies GmbH", "RelatedPartyTransactionDomain1")
    assert (gmbh.listed_party_name, gmbh.relationship, gmbh.type_as_filed, gmbh.txn_type) == (
        "Tata Technologies Limited", "Subsidiary", "Purchase of goods or services", "purchases")  # fmt: skip
    assert (gmbh.period_start, gmbh.period_end) == (date(2025, 7, 1), date(2025, 9, 30))
    assert (gmbh.amount, gmbh.approved_value, gmbh.opening_balance, gmbh.closing_balance) == (
        Decimal("28600000"), Decimal("0"), Decimal("27100000"), Decimal("62900000"))  # fmt: skip
    assert gmbh.approval_remarks == "Not applicable as per regulation 23(2)(c) of SEBI LODR"


def test_reliance_investment_terms_kept_as_filed():
    _, _, rows = _parse(RELIANCE)
    bam = _one(rows, "BAM DLR Network Services Private Limited", "RelatedPartyTransactionDomain27")
    assert (bam.relationship, bam.txn_type, bam.amount, bam.approved_value) == (
        "Joint Venture", "investment", Decimal("880000000"), Decimal("5820000000"))  # fmt: skip
    assert (bam.opening_balance, bam.closing_balance) == (Decimal("20000000"), Decimal("900000000"))
    assert json.loads(bam.terms) == {
        "InterestRateOfLoansOrInterCorporateDepositsOrAdvancesOrInvestments": "11.5",
        "NatureOfTheLoansOrInterCorporateDepositsOrAdvancesOrInvestments": "Investment",
        "PurposeForWhichTheFundsWillBeUtilisedByTheUltimateRecipientOfFundsForEndusage": "Business Purpose",
        "TenureOfLoansOrInterCorporateDepositsOrAdvancesOrInvestments": "10 years",
        "TypeOfLoansOrInterCorporateDepositsOrAdvancesOrInvestmentsSecuredOrUnsecured": "Unsecured",
    }


def test_only_standalone_q2_q4_filings_carry_the_section():
    assert len(WITH_SECTION) == 27
    for name in WITH_SECTION:
        m = parse_integrated_results((XBRL_DIR / name).read_bytes(), name).meta
        assert m["scope"] == "STANDALONE" and m["period_end"].month in (3, 9), name


@pytest.mark.parametrize("name", WITH_SECTION)
def test_rows_sum_to_the_filed_total_and_every_type_is_mapped(name):
    """Every typed member becomes one row; the rows add up exactly to the undimensioned
    AmountOfRelatedPartyTransactionDuringTheReportingPeriod (the existing `rpt_total_amount`)."""
    parsed, inst, rows = _parse(name)
    members = {dict((a.split(":")[-1], v) for a, v in c.dimensions).get("RelatedPartyTransactionAxis")
               for c in inst.contexts.values()} - {None}  # fmt: skip
    assert len(rows) == len(members) > 0
    total = [f for f in parsed.facts if f.canonical_tag == "rpt_total_amount"]
    assert len(total) == 1 and sum(r.amount for r in rows) == total[0].value
    assert {r.period_end for r in rows} == {parsed.meta["period_end"]}
    assert {r.txn_type for r in rows} <= set(TYPE_MAP.values())


def test_a_filing_without_the_section_or_another_period_end_gives_no_rows():
    _, inst, _ = _parse(NETWEB)
    assert parse_reg23_rpt(inst, date(2025, 12, 31)) == []  # contexts end elsewhere: not read
    assert parse_reg23_rpt(inst, None) == []
    q3 = "INTEGRATED_FILING_INDAS_1603408_17012026050918_WEB.xml"
    data = (XBRL_DIR / q3).read_bytes()
    assert parse_reg23_rpt(parse_instance(data), parse_integrated_results(data, q3).meta["period_end"]) == []


# ── promotion and backfill ────────────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def netweb(market):
    for day in ("20251023", "20261112"):
        promote(market.con, market.stage_day(day))
    r = promote(market.con, stage_results_xbrl(
        market.vault, market.stage_root, data=(XBRL_DIR / NETWEB).read_bytes(),
        source_url="https://nsearchives.nseindia.com/corporate/xbrl/" + NETWEB, fetched_at=datetime(2026, 11, 14, 6),
        broadcast_ts=datetime(2026, 5, 16, 5, 8), broadcast_ts_source="API_FIELD"))  # fmt: skip
    assert r.status == "PROMOTED", r
    return market


def test_rows_are_promoted_with_the_results_filing_and_backfilled(netweb):
    con = netweb.con
    got = con.execute(
        "SELECT count(*), sum(r.amount_inr), bool_and(r.visible_from_ts = m.visible_from_ts AND r.scope = m.scope), "
        "any_value(r.parser_version) FROM reg23_related_party_transactions r "
        "JOIN filing_meta m USING (filing_id, entity_id)").fetchone()  # fmt: skip
    assert got == (6, Decimal("97350000.00"), True, REG23_PARSER_VERSION)
    assert con.execute(
        "SELECT closing_balance_inr, approved_value_inr FROM reg23_related_party_transactions "
        "WHERE counterparty_name = 'Sanjay Lodha'"
    ).fetchone() == (Decimal("630000.00"), Decimal("50000000.00"))
    assert con.execute("SELECT count(*) FROM related_party_transactions").fetchone()[0] == 0  # annual table untouched
    assert pending_results_filings(con) == []
    # as if parsed by an earlier Reg. 23 parser version: the filing is known to carry the section from its clean rows
    # (decision J: no raw table), so the backfill re-reads its blob
    con.execute("UPDATE reg23_related_party_transactions SET parser_version = '0.0.1'")
    fid = con.execute("SELECT filing_id FROM filing_meta").fetchone()[0]
    assert [r[0] for r in pending_results_filings(con)] == [fid]
    result = backfill_rpt(con, netweb.vault)
    assert (result["filings"], result["reg23_filings"], result["reg23_rows"], result["error_count"]) == (0, 1, 6, 0)
    assert backfill_rpt(con, netweb.vault)["reg23_filings"] == 0  # idempotent
    assert con.execute("SELECT count(*) FROM reg23_related_party_transactions WHERE parser_version = ?",
                       [REG23_PARSER_VERSION]).fetchone()[0] == 6  # fmt: skip
    # a section the parser does not take (another period end) is kept in disclosure_facts: still selected
    con.execute("DELETE FROM reg23_related_party_transactions")
    assert pending_results_filings(con) == []
    con.execute("INSERT INTO disclosure_facts SELECT * REPLACE ('NameOfCounterParty' AS element, -1 AS seq) "
                "FROM disclosure_facts WHERE filing_id = ? LIMIT 1", [fid])  # fmt: skip
    assert [r[0] for r in pending_results_filings(con)] == [fid]
