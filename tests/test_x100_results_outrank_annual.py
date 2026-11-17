"""Quarterly results outrank the Reg. 34 annual report on income-statement lines [X100].

Cummins India FY26 consolidated: the Q4 results filing (1674519, 27-May-2026) states FY PBT 2,819.67 Cr, excluding
the JV share as Integrated Filing XBRL does; the annual report (04-Sep-2026) books the JV share inside PBT,
3,085.95 Cr (= + 266.28). Latest-visible-wins let the annual value replace the results' FY and broke the YTD
identity of the quarters (36 of 537 open YTD_QUARTER_MISMATCH items, live 2026-11-14). The annual still fills
everything the results filing does not state, and keeps winning on cash-flow and line-item detail.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from _fixture_helpers import XBRL_DIR
from financials.fundamentals import load_factbook
from financials.promoter import promote
from financials.staging import stage_results_xbrl

Q4 = "INTEGRATED_FILING_INDAS_1674519_27052026092425_WEB.xml"
ANNUAL = "AR_XBRL_CUMMINSIND_04092026113534.xml"
FY = (date(2025, 4, 1), date(2026, 3, 31))


def _promote(m, name, ts):
    r = promote(m.con, stage_results_xbrl(m.vault, m.stage_root, data=(XBRL_DIR / name).read_bytes(),
                                          source_url="https://nsearchives.nseindia.com/corporate/xbrl/" + name,
                                          fetched_at=datetime(2026, 11, 14, 6), broadcast_ts=ts,
                                          broadcast_ts_source="API_FIELD"))  # fmt: skip
    assert r.status == "PROMOTED", m.con.execute("SELECT stage, reason_code, details FROM quarantine_queue").fetchall()
    return r.message


def test_results_fy_pbt_is_not_replaced_by_the_annual_report(market):
    for day in ("20251023", "20261112"):  # the annual report has no ISIN: CUMMINSIND must be known on 2026-03-31
        promote(market.con, market.stage_day(day))
    _promote(market, Q4, datetime(2026, 5, 27, 10, 24))
    fid = _promote(market, ANNUAL, datetime(2026, 9, 4, 6, 5))
    ent = market.con.execute("SELECT entity_id FROM filing_meta WHERE filing_id = ?", [fid]).fetchone()[0]
    filed = dict(market.con.execute(
        "SELECT m.accounting_profile, o.value_inr FROM fact_observations o JOIN filing_meta m USING (filing_id) "
        "WHERE o.entity_id = ? AND o.scope = 'CONSOLIDATED' AND o.canonical_tag = 'pbt' AND o.period_start = ? "
        "AND o.period_end = ?", [ent, *FY]).fetchall())  # fmt: skip
    assert filed["REG34_ANNUAL"] - filed["INDAS_CORP"] == Decimal("2662800000")  # the JV share, 266.28 Cr
    book = load_factbook(market.con, ent, "CONSOLIDATED", datetime(2026, 11, 13))
    assert book.durations["pbt"][FY] == filed["INDAS_CORP"] == Decimal("28196700000")
    annual_only = {t for t, d in book.durations.items() if FY in d} - {
        t for (t,) in market.con.execute(
            "SELECT DISTINCT canonical_tag FROM fact_observations o JOIN filing_meta m USING (filing_id) "
            "WHERE o.entity_id = ? AND m.accounting_profile = 'INDAS_CORP' AND o.period_start = ? AND o.period_end = ?",
            [ent, *FY]).fetchall()
    }  # fmt: skip
    assert annual_only  # the annual report still fills what the results filing does not state
