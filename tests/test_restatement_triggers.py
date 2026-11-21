"""Restatement triggers beyond the YTD identity (architecture §7.6, G67 / G68 / G328) and in-filing BSE scrip codes
(G79). Every case runs on committed, unmodified fixtures:

- X108 (G67): Reliance Power Q4 FY25 consolidated files `ProfitLossFromDiscontinuedOperationsAfterTax` 4,300,000
  for FY25 (0 for the quarter); the YTD identity cannot break on one filing, so only the new trigger flags it.
- X109 (G68): the Tata Motors CV demerger (ex-date 14-Oct-2025, the 20251013 / 20251014 bhavcopies) logged in the
  corporate-action ledger reaches the factbook of the entity, in the per-entity and the batch (prefetch) reader.
- X110 (G328): TCS FY26 annual report (Reg. 34) restates FY25 directors' remuneration 38 -> 45 Cr and salaries
  129,997 -> 129,990 Cr against the FY25 annual report already stored; face-of-statement lines agree.
- X111 (G79): `ScripCode` inside a corporate (TCS 532540) and a bank (HDFC Bank 500180) Integrated Filing.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from conftest import FETCHED_AT

from _fixture_helpers import XBRL_DIR
from financials.corp_actions import CorpAction
from financials.fundamentals import FactBook, clear_prefetch, load_factbook, prefetch_fundamentals
from financials.parsers.integrated import parse_integrated_results
from financials.promoter import promote, record_corp_action
from financials.staging import stage_results_xbrl

RPOWER_Q4FY25 = "INTEGRATED_FILING_INDAS_1435405_09052025091610_WEB.xml"
TCS25 = "AR_XBRL_TCS_14082025184751.xml"
TCS26 = "AR_XBRL_TCS_09082026012216.xml"
TCS_Q2FY27 = "INTEGRATED_FILING_INDAS_1734607_08102026100810_WEB.xml"
HDFCBANK_Q4FY26 = "INTEGRATED_FILING_BANKING_1654391_18042026073048_WEB.xml"
MAR25 = date(2025, 3, 31)


def _book(name: str, *, keep=lambda f: True) -> FactBook:
    r = parse_integrated_results((XBRL_DIR / name).read_bytes(), name)
    assert not r.issues
    book = FactBook("E", r.meta["scope"])
    for f in r.facts:
        if f.period_type == "DURATION" and keep(f):
            book.durations.setdefault(f.canonical_tag, {})[(f.period_start, f.period_end)] = f.value
    return book


# ── G67: discontinued operations != 0 ──────────────────────────────────────────────────────────────────────


def test_discontinued_operations_flag_the_last_five_quarters():
    book = _book(RPOWER_Q4FY25)
    assert book.durations["pat_discontinued"] == {(date(2024, 4, 1), MAR25): Decimal("4300000"),
                                                  (date(2025, 1, 1), MAR25): Decimal("0")}  # fmt: skip
    assert book.ytd_breaks("pat") == []  # the YTD trigger alone would not flag this filing
    assert book.restatement_triggers(MAR25) == ["DISCONTINUED_OPERATIONS"]
    assert book.restatement_suspected(MAR25)
    # FY25 is the year-ago comparison of Mar-2026 (5th quarter end back); one quarter later it has left the window.
    assert book.restatement_suspected(date(2026, 3, 31))
    assert not book.restatement_suspected(date(2026, 6, 30))


def test_a_zero_discontinued_line_is_not_a_trigger():
    book = _book(RPOWER_Q4FY25, keep=lambda f: f.period_months == 3)  # the quarter alone files 0
    assert book.restatement_triggers(MAR25) == []


# ── G68: a logged merger / demerger ──────────────────────────────────────────────────────────────────────


def _tm_market(market):
    promote(market.con, market.stage_day("20251013"))
    tm = market.security_id("TATAMOTORS")
    filing = market.con.execute("SELECT filing_id FROM filings LIMIT 1").fetchone()[0]
    record_corp_action(market.con, CorpAction("ca-tm", tm, "DEMERGER", date(2025, 10, 14)), source_filing_id=filing)
    promote(market.con, market.stage_day("20251014"))
    ent = market.con.execute("SELECT entity_id FROM securities WHERE security_id = ?", [tm]).fetchone()[0]
    return ent


def test_demerger_in_the_ledger_reaches_the_factbook_in_both_readers(market):
    ent = _tm_market(market)
    as_of = datetime(2026, 11, 13)
    book = load_factbook(market.con, ent, "CONSOLIDATED", as_of)
    assert book.structural_actions == ((date(2025, 10, 14), "DEMERGER"),)
    prefetch_fundamentals(market.con, as_of)
    try:
        assert load_factbook(market.con, ent, "CONSOLIDATED", as_of).structural_actions == book.structural_actions
    finally:
        clear_prefetch(market.con, as_of)
    assert load_factbook(market.con, ent, "CONSOLIDATED", datetime(2025, 10, 13)).structural_actions == ()
    # Window (end - 5 quarters, end]: Q3 FY26 through Q3 FY27; Q2 FY26 ends before the ex-date.
    assert book.restatement_triggers(date(2025, 9, 30)) == []
    assert book.restatement_triggers(date(2025, 12, 31)) == ["DEMERGER"]
    assert book.restatement_suspected(date(2026, 12, 31))
    assert not book.restatement_suspected(date(2027, 3, 31))


def test_recording_a_demerger_marks_the_entity_dirty_from_its_ex_date(market):
    from financials import dirty

    promote(market.con, market.stage_day("20251013"))
    tm = market.security_id("TATAMOTORS")
    ent = market.con.execute("SELECT entity_id FROM securities WHERE security_id = ?", [tm]).fetchone()[0]
    filing = market.con.execute("SELECT filing_id FROM filings LIMIT 1").fetchone()[0]
    before = dirty.market_state(market.con)
    record_corp_action(market.con, CorpAction("ca-tm", tm, "DEMERGER", date(2025, 10, 14)), source_filing_id=filing)
    dirty.mark_market_changes(market.con, before, "TEST")
    rows = market.con.execute("SELECT entity_id, from_date FROM materialize_dirty WHERE reason = 'TEST'").fetchall()
    # From the ex-date for the restatement flag (X109); batch I adds the day its source listing became visible
    # (here the 2025-10-13 bhavcopy, EOD rule), because `days_to_next_ex_date` reads announced actions from then.
    assert rows == [(ent, date(2025, 10, 13))]
    structural = {r for r in dirty.market_state(market.con)["structural"] if r[2] == "ca-tm"}
    assert {r[1] for r in structural} == {date(2025, 10, 14)}


def test_retired_actions_do_not_flag(market):
    ent = _tm_market(market)
    market.con.execute("UPDATE corp_actions SET status = 'REJECTED' WHERE action_id = 'ca-tm'")
    assert load_factbook(market.con, ent, "CONSOLIDATED", datetime(2026, 11, 13)).structural_actions == ()


# ── G328: Reg. 34 prior-year columns vs stored FY figures ───────────────────────────────────────────────


def _stage(m, name: str, ts: datetime):
    return stage_results_xbrl(m.vault, m.stage_root, data=(XBRL_DIR / name).read_bytes(),
                              source_url="https://nsearchives.nseindia.com/corporate/xbrl/" + name,
                              fetched_at=FETCHED_AT, broadcast_ts=ts, broadcast_ts_source="API_FIELD")  # fmt: skip


def test_annual_prior_year_columns_that_differ_are_a_non_blocking_finding(market):
    promote(market.con, market.stage_day("20250227"))  # TCS identity before its FY25 annual report
    r25 = promote(market.con, _stage(market, TCS25, datetime(2025, 8, 14, 13, 17, 52)))
    assert r25.status == "PROMOTED", r25
    assert not market.con.execute(
        "SELECT count(*) FROM quarantine_queue WHERE reason_code = 'ANNUAL_PRIOR_YEAR_DIFFERS'"
    ).fetchone()[0]  # FY25's own report has no in-scope prior year (FY24 is cut off, C9)
    r26 = promote(market.con, _stage(market, TCS26, datetime(2026, 8, 8, 19, 52, 19)))
    assert r26.status == "PROMOTED", r26
    rows = market.con.execute(
        "SELECT stage, details, resolved_at FROM quarantine_queue WHERE reason_code = 'ANNUAL_PRIOR_YEAR_DIFFERS'"
    ).fetchall()
    assert len(rows) == 1 and rows[0][0] == "CONSISTENCY" and rows[0][2] is None
    import json

    diffs = {d["tag"]: (Decimal(d["stored"]), Decimal(d["annual"])) for d in json.loads(rows[0][1])["differences"]}
    cr = Decimal(10) ** 7
    assert {t: (a / cr, b / cr) for t, (a, b) in diffs.items()} == {
        "li_managerial_remuneration": (Decimal(38), Decimal(45)),
        "li_remuneration_to_directors": (Decimal(38), Decimal(45)),
        "li_salary_to_directors": (Decimal(38), Decimal(45)),
        "li_salaries_and_wages": (Decimal(129997), Decimal(129990)),
    }  # authorised capital 565.00 vs 565.075 Cr is inside the rounding of two crore-rounded filings
    # The finding never blocks: FY25 now reads as restated by the later report, visible from its broadcast.
    assert r26.quarantined and set(r26.quarantined) >= {
        market.con.execute(
            "SELECT quarantine_id FROM quarantine_queue WHERE reason_code = 'ANNUAL_PRIOR_YEAR_DIFFERS'"
        ).fetchone()[0]
    }


# ── G79: BSE scrip code from the filing ──────────────────────────────────────────────────────────────────


def _codes(m, symbol: str) -> set:
    return {
        c
        for (c,) in m.con.execute(
            "SELECT bse_scrip_code FROM security_identifier_history WHERE symbol = ?", [symbol]
        ).fetchall()
    }


@pytest.mark.parametrize(
    ("name", "symbol", "code"),
    [(TCS_Q2FY27, "TCS", "532540"), (HDFCBANK_Q4FY26, "HDFCBANK", "500180")],
    ids=["corporate", "bank"],
)
def test_scrip_code_fills_the_matching_identifier_rows(market, name, symbol, code):
    promote(market.con, market.stage_day("20261112"))
    assert _codes(market, symbol) == {None}
    r = promote(market.con, _stage(market, name, datetime(2026, 10, 8, 4, 38)))
    assert r.status == "PROMOTED", r
    assert _codes(market, symbol) == {code}
    assert _codes(market, "INFY") == {None}  # only the filer's rows


def test_a_different_stored_scrip_code_is_kept_and_quarantined(market):
    promote(market.con, market.stage_day("20261112"))
    market.con.execute("UPDATE security_identifier_history SET bse_scrip_code = '999999' WHERE symbol = 'TCS'")
    r = promote(market.con, _stage(market, TCS_Q2FY27, datetime(2026, 10, 8, 4, 38)))
    assert r.status == "PROMOTED", r
    assert _codes(market, "TCS") == {"999999"}
    q = market.con.execute(
        "SELECT stage, json_extract_string(details, '$.filed'), json_extract_string(details, '$.stored') "
        "FROM quarantine_queue WHERE reason_code = 'BSE_SCRIP_CODE_CONFLICT'"
    ).fetchall()
    assert q == [("IDENTIFIER", "532540", "999999")]


# ── SC0: an all-zero scrip code is a placeholder (X171) ──────────────────────────────────────────────────────────
UNITEDPOLY_ZERO = "INTEGRATED_FILING_INDAS_1502813_05082025045022_WEB.xml"


def test_a_real_filing_states_an_all_zero_scrip_code_and_sc0_reads_it_as_none():
    from financials.filing_checks import scrip_code
    from financials.parsers.xbrl import parse_instance

    inst = parse_instance((XBRL_DIR / UNITEDPOLY_ZERO).read_bytes())
    stated = {f.name: f.value_text.strip() for f in inst.facts if f.name in ("ScripCode", "Symbol")}
    assert stated == {"ScripCode": "000000", "Symbol": "UNITEDPOLY"}
    assert scrip_code("000000") is None and scrip_code(" 0 ") is None and scrip_code("") is None
    assert scrip_code(None) is None and scrip_code("53254O") is None
    assert scrip_code(" 532540 ") == "532540" and scrip_code("500180") == "500180"


def test_a_stored_all_zero_scrip_code_is_filled_by_the_real_one_without_a_conflict(market):
    promote(market.con, market.stage_day("20261112"))
    market.con.execute("UPDATE security_identifier_history SET bse_scrip_code = '000000' WHERE symbol = 'TCS'")
    r = promote(market.con, _stage(market, TCS_Q2FY27, datetime(2026, 10, 8, 4, 38)))
    assert r.status == "PROMOTED", r
    assert _codes(market, "TCS") == {"532540"}
    assert (
        market.con.execute(
            "SELECT count(*) FROM quarantine_queue WHERE reason_code = 'BSE_SCRIP_CODE_CONFLICT'"
        ).fetchone()[0]
        == 0
    )
