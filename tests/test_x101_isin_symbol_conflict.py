"""ISIN of another issuer [X101].

Gillette India Q1 FY26 standalone (1498822, 31-Jul-2025) states Symbol GILLETTE and company "Gillette India Limited"
but ISIN INE179A01014, which is P&G Hygiene and Health Care's. Resolution by ISIN alone promoted it under PGHH,
whose own Q1 then lost to it and 12 YTD_QUARTER_MISMATCH items opened (live 2026-11-14). Invariant 3: identifiers
that disagree quarantine, except under the named rule ISIN_OF_OTHER_ISSUER (the symbol names one entity whose name
agrees with the filed company name, the ISIN entity's does not).
"""

from __future__ import annotations

import json
from datetime import datetime

from _fixture_helpers import XBRL_DIR
from financials.promoter import promote, resolve_isin_symbol_conflict
from financials.staging import stage_results_xbrl

GILLETTE_Q1 = "INTEGRATED_FILING_INDAS_1498822_31072025011108_WEB.xml"


def _entity(con, symbol):
    return con.execute(
        "SELECT DISTINCT s.entity_id FROM security_identifier_history h JOIN securities s USING (security_id) "
        "WHERE h.symbol = ?", [symbol]).fetchone()[0]  # fmt: skip


def test_filing_with_another_issuers_isin_is_promoted_under_its_symbol(market):
    from _fixture_helpers import XBRL_DIR as X

    promote(market.con, market.stage_day("20251023"))
    raw = (X / GILLETTE_Q1).read_text()
    assert ">INE179A01014<" in raw and ">GILLETTE<" in raw  # as filed
    data = (XBRL_DIR / GILLETTE_Q1).read_bytes()
    r = promote(market.con, stage_results_xbrl(market.vault, market.stage_root, data=data,
                source_url="https://nsearchives.nseindia.com/corporate/xbrl/" + GILLETTE_Q1,
                fetched_at=datetime(2026, 11, 14, 6), broadcast_ts=datetime(2025, 7, 31, 7, 41),
                broadcast_ts_source="API_FIELD"))  # fmt: skip
    assert r.status == "PROMOTED", r
    ent = market.con.execute("SELECT entity_id FROM filing_meta WHERE filing_id = ?", [r.message]).fetchone()[0]
    assert ent == _entity(market.con, "GILLETTE") != _entity(market.con, "PGHH")
    log = market.con.execute("SELECT params FROM admin_log WHERE action = 'RULE:ISIN_OF_OTHER_ISSUER'").fetchall()
    assert [json.loads(p)["symbol"] for (p,) in log] == ["GILLETTE"]


def test_disagreeing_identifiers_without_a_name_match_are_not_resolved(market):
    from datetime import date

    promote(market.con, market.stage_day("20251023"))
    pghh, gillette = _entity(market.con, "PGHH"), _entity(market.con, "GILLETTE")
    on = date(2025, 6, 30)
    assert resolve_isin_symbol_conflict(market.con, "NSE", pghh, "PGHH", "Any name", on, "f") == (pghh, None)
    assert resolve_isin_symbol_conflict(market.con, "NSE", pghh, "NOSUCHSYMBOL", "x", on, "f") == (pghh, None)
    ent, details = resolve_isin_symbol_conflict(market.con, "NSE", pghh, "GILLETTE", "Unrelated Ltd", on, "f")
    assert ent is None and details["symbol_entities"] == [gillette]
