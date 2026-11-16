"""Batch J: related-party schedule per counterparty (G99, G236) [X113] and the annual share-capital cross-check (G93
stand-in for Reg. 76) [X114]. Every value is read straight from the committed Reg. 34 annual fixtures."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal

import pytest

from _fixture_helpers import XBRL_DIR
from financials import features_rpt as R
from financials.cli import build_parser
from financials.db import declared_columns
from financials.dsl import ALIASES, compile_screen
from financials.features_disclosures import COLUMNS as DISCLOSURE_COLUMNS
from financials.parsers.reg34_annual import parse_reg34_annual
from financials.parsers.rpt import CATEGORY_VALUES, TXN_TYPES, nature_type, parse_related_parties
from financials.parsers.xbrl import parse_instance
from financials.promoter import promote
from financials.related_parties import backfill_rpt, pending_filings
from financials.share_capital import REASON, annual_share_counts, annual_share_disagreement
from financials.staging import stage_results_xbrl

CUMMINS = "AR_XBRL_CUMMINSIND_04092026113534.xml"
ELIN = "AR_XBRL_ELIN_30092025131606.xml"
TCS_FY26 = "AR_XBRL_TCS_09082026012216.xml"
SRF = "AR_XBRL_SRF_09082026022508.xml"
FY25, FY26 = date(2025, 3, 31), date(2026, 3, 31)


def _rows(name: str):
    data = (XBRL_DIR / name).read_bytes()
    m = parse_reg34_annual(data, name).meta
    return parse_related_parties(parse_instance(data), set(m["in_scope_periods"]), set(m["in_scope_instants"]))


def _one(rows, name, element, end):
    hits = [r for r in rows if r.counterparty_name == name and r.source_element == element and r.period_end == end]
    assert len(hits) == 1, hits
    return hits[0]


# ── parser [X113] ─────────────────────────────────────────────────────────────────────────────────────────────────


def test_cummins_counterparties_categories_and_amounts():
    rows = _rows(CUMMINS)
    tata = _one(rows, "TATA CUMMINS PRIVATE LIMITED", "PurchasesOfGoodsRelatedPartyTransactions", FY26)
    assert (tata.category, tata.category_member, tata.cin, tata.txn_type, tata.amount, tata.period_start) == (
        "PROMOTER_GROUP", "JointControlOrSignificantInfluenceMember", "U34101PN1993PTC190262", "purchases",
        Decimal("13990100000"), date(2025, 4, 1))  # fmt: skip
    parent = _one(rows, "Cummins Inc.", "OtherRelatedPartyTransactionsExpense", FY26)
    assert (parent.category_member, parent.category, parent.relationship, parent.nature, parent.txn_type) == (
        "ParentMember", "PROMOTER_GROUP", "Holding company", "As stated below", "other")  # fmt: skip
    assert parent.amount == Decimal("10616700000")
    payable = _one(rows, "Cummins Inc.", "AmountsPayableRelatedPartyTransactions", FY26)
    assert (payable.period_type, payable.period_start, payable.txn_type, payable.amount) == (
        "INSTANT", FY26, "balance_payable", Decimal("3301700000"))  # fmt: skip
    kmp = _one(rows, "SHVETA ARYA", "OtherRelatedPartyTransactionsExpense", FY26)
    assert (kmp.category, kmp.pan, kmp.relationship, kmp.amount) == ("KMP", "ADAPG3296A", "Managing Director",
                                                                      Decimal("69200000"))  # fmt: skip
    purchases = sum(r.amount for r in rows if r.period_end == FY26 and r.txn_type == "purchases"
                    and r.category != "SUBSIDIARY")  # fmt: skip
    assert purchases == Decimal("40004500000")
    assert {r.period_end for r in rows} == {FY25, FY26}
    assert {r.category for r in rows} <= set(CATEGORY_VALUES) and {r.txn_type for r in rows} <= {
        *TXN_TYPES, "balance_payable", "balance_receivable"}  # fmt: skip


def test_elin_nature_rule_subsidiaries_and_cutoff():
    rows = _rows(ELIN)
    assert {r.period_end for r in rows} == {FY25}  # FY24 comparatives are out of scope (C9)
    sethia = _one(rows, "Sh. Kishor Sethia", "OtherRelatedPartyTransactionsExpense", FY25)
    assert (sethia.category, sethia.pan, sethia.nature, sethia.amount) == (
        "KMP", "AKLPS0412M", "Remuneration, Dividend paid", Decimal("8740000"))  # fmt: skip
    assert sethia.txn_type == "other"  # two natures named: NATURE_RULE does not guess
    kanchan = _one(rows, "KANCHAN COMMERCIAL CO PVT LTD", "ServicesReceivedRelatedPartyTransactions", FY25)
    assert (kanchan.row_member, kanchan.category, kanchan.cin, kanchan.amount) == (
        "C1", "PROMOTER_GROUP", "U01122DL1950PTC384878", Decimal("600000"))  # fmt: skip
    assert {r.txn_type for r in rows if r.source_element == "OtherRelatedPartyTransactionsExpense"} == {
        "other", "remuneration", "dividend"}  # fmt: skip
    assert any(r.category == "SUBSIDIARY" for r in rows)


def test_tcs_finance_and_lease_elements():
    rows = _rows(TCS_FY26)
    by = {(r.source_element, r.period_end) for r in rows if r.amount}
    types = {r.source_element: r.txn_type for r in rows}
    assert types["TransfersUnderFinanceAgreementsToEntityRelatedPartyTransactions"] == "loans_taken"
    assert types["LeasesAsLessorRelatedPartyTransactions"] == "rent_received"
    assert types["LeasesAsLesseeRelatedPartyTransactions"] == "rent"
    assert types["ProvisionOfGuaranteesOrCollateralToEntityRelatedPartyTransactions"] == "guarantees"
    assert ("PurchasesOfPropertyAndOtherAssetsRelatedPartyTransactions", FY26) in by
    assert {r.category for r in rows} == {"PROMOTER_GROUP", "OTHER"}  # Tata Sons (parent) and other Tata companies


@pytest.mark.parametrize(
    ("text", "expected"),
    [("Remuneration", "remuneration"), ("Sitting fees and commission", "remuneration"), ("Dividend paid", "dividend"),
     ("Royalty", "royalty"), ("Rent paid", "rent"), ("Remuneration, Dividend paid", None), ("As stated below", None),
     (None, None)],
)  # fmt: skip
def test_nature_rule_names_exactly_one_type(text, expected):
    assert nature_type(text) == expected


# ── promotion, backfill, features ─────────────────────────────────────────────────────────────────────────────────


def _promote_annual(market, name, broadcast):
    return promote(market.con, stage_results_xbrl(
        market.vault, market.stage_root, data=(XBRL_DIR / name).read_bytes(),
        source_url="https://nsearchives.nseindia.com/corporate/xbrl/" + name, fetched_at=datetime(2026, 11, 14, 6),
        broadcast_ts=broadcast, broadcast_ts_source="API_FIELD"))  # fmt: skip


@pytest.fixture
def cummins(market):
    for day in ("20251023", "20261112"):  # CUMMINSIND must be known on the broadcast date
        promote(market.con, market.stage_day(day))
    assert _promote_annual(market, CUMMINS, datetime(2026, 9, 4, 6, 5)).status == "PROMOTED"
    return market


def test_rows_are_promoted_with_the_annual_filing_and_backfilled(cummins):
    con = cummins.con
    n = len(_rows(CUMMINS))
    got = con.execute(
        "SELECT count(*), bool_and(r.visible_from_ts = m.visible_from_ts AND r.scope = m.scope), any_value(r.scope) "
        "FROM related_party_transactions r JOIN filing_meta m USING (filing_id, entity_id)").fetchone()  # fmt: skip
    assert got == (n, True, "CONSOLIDATED")
    assert pending_filings(con) == []
    con.execute("DELETE FROM related_party_transactions")  # as if promoted before batch J
    result = backfill_rpt(con, cummins.vault)
    assert (result["filings"], result["rows"], result["error_count"]) == (1, n, 0)
    assert con.execute("SELECT from_date FROM materialize_dirty WHERE reason = 'RPT_BACKFILL'").fetchall() == [
        (date(2026, 9, 4),)
    ]  # visible from the broadcast (IST date)
    assert backfill_rpt(con, cummins.vault)["filings"] == 0  # idempotent
    assert con.execute("SELECT count(*) FROM admin_log WHERE action = 'BACKFILL_RPT'").fetchone()[0] == 2
    assert "backfill-rpt" in build_parser()._subparsers._group_actions[0].choices


def test_leak_columns_from_the_same_filing_point_in_time(cummins):
    con = cummins.con
    ent = con.execute("SELECT DISTINCT entity_id FROM related_party_transactions").fetchone()[0]
    assert R.rpt_inputs(con, datetime(2026, 9, 4, 6, 0)) == {}  # before the broadcast
    inputs = R.rpt_inputs(con, datetime(2026, 11, 13))
    assert set(inputs) == {(ent, "CONSOLIDATED")}
    i = inputs[(ent, "CONSOLIDATED")]
    assert (i["fy_end"], i["revenue"], i["equity"]) == (FY26, Decimal("121431900000"), Decimal("84751600000"))
    row = {"entity_id": ent, "scope_used": "STANDALONE"}  # no standalone schedule: falls back to consolidated
    R.add_columns(con, [row], datetime(2026, 11, 13))
    assert row["rpt_fy_end"] == FY26
    assert row["rpt_leak_pct"] == pytest.approx(40004500000 / 121431900000)
    assert row["rpt_purchases_to_sales"] == row["rpt_leak_pct"]
    assert (row["rpt_royalty_to_sales"], row["rpt_loans_given_to_net_worth"]) == (0.0, 0.0)
    # names outside the group with a non-zero FY26 transaction (balances and subsidiaries do not count)
    expected = {r.counterparty_name for r in _rows(CUMMINS) if r.period_end == FY26 and r.period_type == "DURATION"
                and r.amount and r.category != "SUBSIDIARY"}  # fmt: skip
    assert row["rpt_counterparties"] == len(expected) > 10


def test_columns_without_a_schedule_or_with_a_non_positive_denominator():
    assert R.rpt_columns(None) == dict.fromkeys(R.RPT_COLUMNS)
    out = R.rpt_columns({"fy_end": FY25, "by_type": {"loans_given": Decimal(5)}, "names": {"x"},
                         "revenue": Decimal(0), "equity": Decimal(-1)})  # fmt: skip
    assert (out["rpt_leak_pct"], out["rpt_loans_given_to_net_worth"], out["rpt_counterparties"]) == (None, None, 1)
    out = R.rpt_columns({"fy_end": FY25, "by_type": {"loans_given": Decimal(5), "royalty": Decimal(10),
                         "purchases": Decimal(10), "sales": Decimal(99)}, "names": set(),
                         "revenue": Decimal(100), "equity": Decimal(50)})  # fmt: skip
    assert out["rpt_leak_pct"] == pytest.approx(0.25) and out["rpt_royalty_to_sales"] == pytest.approx(0.1)
    assert out["rpt_loans_given_to_net_worth"] == pytest.approx(0.1)


def test_every_column_is_appended_in_both_tables_and_has_an_alias():
    for t in ("screener_features",):  # the history view has its columns (test_features_store)
        names = [c for c, _ in declared_columns()[t]]
        tail = len(DISCLOSURE_COLUMNS)  # batch J, then only the 18D block (features_disclosures)
        assert names[-len(R.RPT_COLUMNS) - tail : -tail] == list(R.RPT_COLUMNS), t
    used = " ".join(sql for sql, _ in ALIASES.values())
    assert [c for c in R.RPT_COLUMNS if c not in used] == ["rpt_fy_end"]  # a date, shown with `screen --columns`
    sql = compile_screen("RPT leak > 10 AND RPT loans given to net worth > 5 AND RPT royalty to sales > 1").where_sql
    for col in ("rpt_leak_pct", "rpt_loans_given_to_net_worth", "rpt_royalty_to_sales"):
        assert col in sql, col


# ── annual share capital (G93) [X114] ────────────────────────────────────────────────────────────────────────────


def test_annual_share_counts_are_facts_of_the_annual_filing():
    def counts(name):
        facts = parse_reg34_annual((XBRL_DIR / name).read_bytes(), name).facts
        return {
            (f.canonical_tag, f.period_end): f.value for f in facts if f.canonical_tag.startswith("li_number_of_sh")
        }

    elin = counts(ELIN)
    for tag in ("issued", "subscribed_and_fully_paid", "paid_up"):
        assert elin[(f"li_number_of_shares_{tag}", FY25)] == Decimal("49659220")
    srf = counts(SRF)  # issued includes shares the subscribed / paid-up counts exclude
    assert srf[("li_number_of_shares_issued", FY26)] == Decimal("300481580")
    assert srf[("li_number_of_shares_subscribed_and_fully_paid", FY26)] == Decimal("296424825")


def _shp_total(con, shares: int, *, as_of=FY25) -> None:
    """A synthetic Reg. 31 TOTAL row (no Reg. 31 fixture of an annual-fixture company on a FY end exists)."""
    ent = con.execute("SELECT entity_id FROM entity_master WHERE entity_id IN "
                      "(SELECT entity_id FROM security_identifier_history s JOIN securities USING (security_id) "
                      "WHERE s.symbol = 'ELIN')").fetchone()  # fmt: skip
    con.execute("INSERT OR IGNORE INTO blobs VALUES ('synthetic', 1, 'application/xml', 'x', TIMESTAMP '2025-04-20')")
    con.execute("INSERT OR IGNORE INTO filings VALUES ('shp-synth', 'synthetic', 'NSE', 'SHAREHOLDING', 'synthetic', "
                "NULL, 'ELIN', NULL, TIMESTAMP '2025-04-20', 'API_FIELD', TIMESTAMP '2025-04-20', NULL)")  # fmt: skip
    con.execute("DELETE FROM shareholding_observations WHERE filing_id = 'shp-synth'")
    con.execute("INSERT INTO shareholding_observations VALUES ('shp-synth', 'synthetic', ?, ?, 'TOTAL', ?, NULL, 1.0, "
                "NULL, NULL, TIMESTAMP '2025-04-20')", [ent[0], as_of, shares])  # fmt: skip


@pytest.fixture
def elin(market):
    promote(market.con, market.stage_day("20250919"))  # ELIN known before the annual broadcast
    return market


def test_annual_counts_agree_with_reg31_and_no_finding(elin):
    _shp_total(elin.con, 49659220)
    assert _promote_annual(elin, ELIN, datetime(2025, 9, 30, 7, 46)).status == "PROMOTED"
    fid, ent = elin.con.execute("SELECT filing_id, entity_id FROM filing_meta").fetchone()
    assert annual_share_counts(elin.con, fid, FY25) == dict.fromkeys(("issued", "subscribed", "paid_up"),
                                                                     Decimal("49659220"))  # fmt: skip
    assert elin.con.execute("SELECT count(*) FROM quarantine_queue WHERE reason_code = ?", [REASON]).fetchone()[0] == 0
    _shp_total(elin.con, 49659220 + 1000)  # inside the 0.5% tolerance
    assert annual_share_disagreement(elin.con, fid, ent, FY25) is None


def test_annual_counts_that_differ_raise_a_non_blocking_finding(elin):
    _shp_total(elin.con, 51000000)
    r = _promote_annual(elin, ELIN, datetime(2025, 9, 30, 7, 46))
    assert r.status == "PROMOTED"
    q = elin.con.execute("SELECT quarantine_id, stage, filing_id, details FROM quarantine_queue WHERE reason_code = ? "
                         "AND resolved_at IS NULL", [REASON]).fetchall()  # fmt: skip
    fid = elin.con.execute("SELECT filing_id FROM filing_meta").fetchone()[0]
    assert len(q) == 1 and q[0][0] in r.quarantined and q[0][1:3] == ("SHARES", fid)
    d = json.loads(q[0][3])
    assert d["annual_counts"]["subscribed"] == "49659220" and d["references"]["reg31_total"] == ["51000000"]
    assert Decimal(d["relative_diff"]["reg31_total"]) > Decimal("0.02")
    assert elin.con.execute("SELECT count(*) FROM fact_observations WHERE canonical_tag = 'pat'").fetchone()[0] > 0
