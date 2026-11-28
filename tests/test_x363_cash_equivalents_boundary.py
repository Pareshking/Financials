"""RULES25 X363: CASH_FLOW_RESTATED prior-year findings whose cash-equivalents boundary moved at both ends of the year.

Welspun Enterprises standalone: the Q4 FY25 results' cash-flow statement closes FY25 at 895.17 Cr of cash although its
own balance sheet states cash and cash equivalents of 433.73 Cr; the FY26 annual report restates the FY25 cash flows to
the balance-sheet figure (opening 704.66 -> 225.34 Cr, closing 895.17 -> 433.73 Cr), so the movement of the balances
moved out of cash is an investing flow: CFI -16.23 -> 1.64 Cr, net change 190.51 -> 208.39 Cr, CFO 274.04 Cr and CFF
-67.30 / -67.29 Cr unchanged, PAT, total equity and total assets unchanged. X306 does not apply (the closing cash moved
by -461.44 Cr, the net change by +17.88 Cr): both ends of the year were redefined.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

from conftest import FETCHED_AT

from _fixture_helpers import FIXTURES
from financials.filing_checks import PRIOR_YEAR_REASON, RESTATED_ACCEPTABLE, prior_year_class
from financials.promoter import audit_annual_checks, promote
from financials.staging import stage_results_xbrl

RESTATED = FIXTURES / "annual_restated"
URL = "https://nsearchives.nseindia.com/corporate/xbrl/"
CR = Decimal(10) ** 7
Q4_FY25 = "INTEGRATED_FILING_INDAS_1440595_15052025094344_WEB.xml"
FY26 = "AR_XBRL_WELENT_18092026113802.xml"


def _promote(m, name, ts):
    r = promote(m.con, stage_results_xbrl(m.vault, m.stage_root, data=(RESTATED / name).read_bytes(),
                                          source_url=URL + name, fetched_at=FETCHED_AT, broadcast_ts=ts,
                                          broadcast_ts_source="API_FIELD"))  # fmt: skip
    assert r.status == "PROMOTED", (name, r)


def _findings(con):
    return con.execute(
        "SELECT details, resolution, resolution_note FROM quarantine_queue WHERE reason_code = ? "
        "ORDER BY created_at, quarantine_id",
        [PRIOR_YEAR_REASON],
    ).fetchall()


def _line(d, tag):
    x = next(x for x in d["differences"] if x["tag"] == tag)
    return (Decimal(x["stored"]) / CR).quantize(Decimal("0.01")), (Decimal(x["annual"]) / CR).quantize(Decimal("0.01"))


def test_x363_boundary_moved_at_both_ends_of_the_year(market):
    assert promote(market.con, market.stage_day("20250919")).status == "PROMOTED"
    _promote(market, Q4_FY25, datetime(2025, 5, 15, 16, 13, 44))
    _promote(market, FY26, datetime(2026, 9, 18, 6, 8, 3))
    [(det, res, _)] = _findings(market.con)
    d = json.loads(det)
    assert res is None and d["scope"] == "STANDALONE"
    assert d["class"] == "RESTATED" and d["subclass"] == "CASH_EQUIVALENTS_BOUNDARY"
    tags = {x["tag"] for x in d["differences"]}
    assert not tags & {"pat", "total_equity", "total_assets", "cfo", "cff", "cash_and_equivalents"}
    assert _line(d, "cfi") == (Decimal("-16.23"), Decimal("1.64"))
    assert _line(d, "net_cash_flow") == (Decimal("190.51"), Decimal("208.39"))
    assert _line(d, "cash_cf_statement") == (Decimal("895.17"), Decimal("433.73"))  # = balance-sheet cash, both
    # X312: accepted when audit-annual writes it, still visible
    audit_annual_checks(market.con)
    [(det2, res2, note)] = [r for r in _findings(market.con) if r[1] is not None]
    assert json.loads(det2) == d and res2 == "ACCEPTED"
    assert "CASH_EQUIVALENTS_BOUNDARY (X363)" in note


def test_x363_needs_its_proof():
    assert "CASH_EQUIVALENTS_BOUNDARY" in RESTATED_ACCEPTABLE
    fy, ye = ["2024-04-01", "2025-03-31"], ["2025-03-31", "2025-03-31"]

    def line(tag, annual, stored, period=fy):
        return {"tag": tag, "period": period, "annual": annual, "stored": stored, "tolerance": "0.5"}

    cfi, net = line("cfi", "2", "-16"), line("net_cash_flow", "208", "190")
    cash = line("cash_cf_statement", "434", "895", ye)
    base = {"pat", "total_equity", "total_assets", "cfo", "cff", "cfi", "net_cash_flow", "cash_cf_statement"}
    ctx = {"compared": base, "discontinued_filed": False}
    assert prior_year_class([cfi, net, cash], ctx)["subclass"] == "CASH_EQUIVALENTS_BOUNDARY"
    # operating or financing cash flow not compared, or differing: cash flows were restated, not only the boundary
    for t in ("cfo", "cff"):
        assert prior_year_class([cfi, net, cash], {**ctx, "compared": base - {t}})["subclass"] == "CASH_FLOW_RESTATED"
        assert prior_year_class([cfi, net, cash, line(t, "1", "5")], ctx)["subclass"] == "CASH_FLOW_RESTATED"
    # investing and net change moved by different amounts, or investing did not move
    assert prior_year_class([line("cfi", "5", "-16"), net, cash], ctx)["subclass"] == "CASH_FLOW_RESTATED"
    assert prior_year_class([net, cash], ctx)["subclass"] == "CASH_FLOW_RESTATED"
    # no year-end cash balance moved: nothing shows a redefinition
    assert prior_year_class([cfi, net], ctx)["subclass"] == "CASH_FLOW_RESTATED"
    # total assets or a bottom line moved
    assert prior_year_class([cfi, net, cash, line("total_assets", "1", "2", ye)], ctx)["subclass"] == (
        "CASH_FLOW_RESTATED"
    )
    assert prior_year_class([cfi, net, cash, line("pat", "1", "2")], ctx)["subclass"] == "BOTTOM_LINE_RESTATED"
    # the net change after the exchange difference compared: it must move by the same amount
    fx = {**ctx, "compared": base | {"net_cash_flow_after_fx"}}
    after = line("net_cash_flow_after_fx", "208", "190")
    assert prior_year_class([cfi, net, after, cash], fx)["subclass"] == "CASH_EQUIVALENTS_BOUNDARY"
    off = line("net_cash_flow_after_fx", "210", "190")
    assert prior_year_class([cfi, net, off, cash], fx)["subclass"] == "CASH_FLOW_RESTATED"
    # X306 still comes first: closing cash moved by the net change
    same = line("cash_cf_statement", "913", "895", ye)
    assert prior_year_class([cfi, net, same], ctx)["subclass"] == "CASH_EQUIVALENTS_RECLASSIFIED"
