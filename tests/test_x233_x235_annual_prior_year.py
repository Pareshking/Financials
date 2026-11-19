"""QP3 X233-X235: the annual prior-year check (G328, X110 / X182) after the expanded-universe review.

- X235: rule X201 LEVEL_OF_ROUNDING_SLIP extends to Reg. 34 annual filings. TD Power Systems consolidated FY26
  annual (`Rupees`) files every amount in lakhs: FY25 revenue 127,876.17 rupees where the Q4 FY25 results (`Lakhs`)
  file 12,787,617,000; FY26 equity capital 3,124.30 vs 156,214,830 shares (Reg. 31, 31-Mar-2026) x Rs 2. The three
  checks read 100,000; the rescale closes the SCALE finding, and the re-run prior-year check compares the annual at its
  corrected scale (every total agrees; on the live data two expense lines remain, regrouped).
- X233 RECLASSIFIED: Vintage Coffee consolidated FY26 moves FY25 cash flows between activities (CFO -25.7608 ->
  -21.1632 Cr) while PAT, total equity and net cash flow agree.
- X234 DISCONTINUED_REPRESENTED: BASF India consolidated FY26 re-presents FY25 for a discontinued operation (profit
  -4.80 Cr; revenue / expenses / PBT of continuing operations shrink), PAT 479.06 Cr unchanged.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal

from conftest import FETCHED_AT

from _fixture_helpers import FIXTURES
from financials.admin import find_level_slips, rescale_level_slips
from financials.filing_checks import PRIOR_YEAR_REASON, prior_year_class
from financials.fundamentals import load_factbook
from financials.promoter import promote
from financials.staging import stage_results_xbrl, stage_shareholding

SLIP = FIXTURES / "level_slip_annual"
RESTATED = FIXTURES / "annual_restated"
URL = "https://nsearchives.nseindia.com/corporate/xbrl/"
TDPOWER = (  # (dir, file, broadcast UTC)
    (SLIP, "INTEGRATED_FILING_INDAS_1436604_12052025072108_WEB.xml", datetime(2025, 5, 12, 13, 51, 8)),
    (SLIP, "SHP_1649607_13042026124938_WEB.xml", datetime(2026, 4, 13, 7, 19, 44)),
    (SLIP, "INTEGRATED_FILING_INDAS_1667244_14052026070419_WEB.xml", datetime(2026, 5, 14, 13, 34, 14)),
    (SLIP, "AR_XBRL_TDPOWERSYS_28082026104939.xml", datetime(2026, 8, 28, 5, 19, 40)),
)
CR = Decimal(10) ** 7


def _promote(m, d, name, ts):
    stage = stage_shareholding if name.startswith("SHP_") else stage_results_xbrl
    r = promote(m.con, stage(m.vault, m.stage_root, data=(d / name).read_bytes(), source_url=URL + name,
                             fetched_at=FETCHED_AT, broadcast_ts=ts, broadcast_ts_source="API_FIELD"))  # fmt: skip
    assert r.status == "PROMOTED", (name, r)


def _fid(con, name):
    return con.execute("SELECT filing_id FROM filings WHERE source_url = ?", [URL + name]).fetchone()[0]


def _open(con):
    return [(q, f, json.loads(d)) for q, f, d in con.execute(
        "SELECT quarantine_id, filing_id, details FROM quarantine_queue WHERE reason_code = ? AND resolved_at IS NULL "
        "ORDER BY quarantine_id", [PRIOR_YEAR_REASON]).fetchall()]  # fmt: skip


def test_x235_annual_level_slip_is_found_rescaled_and_rechecked(market):
    assert promote(market.con, market.stage_day("20250919")).status == "PROMOTED"
    for d, name, ts in TDPOWER:
        _promote(market, d, name, ts)
    con = market.con
    annual = _fid(con, TDPOWER[3][1])
    [(qid, fid, before)] = _open(con)
    assert fid == annual and before["class"] == "SCALE"
    rev = next(x for x in before["differences"] if x["tag"] == "revenue_from_operations")
    assert (Decimal(rev["annual"]), Decimal(rev["stored"])) == (Decimal("127876.17"), Decimal("12787617000"))

    [slip] = find_level_slips(con)  # the results filings (both `Lakhs`) are right; only the annual is found
    v = slip["verdict"]
    assert slip["filing_id"] == annual and slip["annual"] and v.factor == Decimal(100000)
    assert (v.declared, v.usual) == ("Rupees", "Lakhs") and [c.verdict for c in v.checks] == ["SLIP"] * 3

    [done] = rescale_level_slips(con)
    assert done["corrections"] > 800
    ent, scope = con.execute("SELECT entity_id, scope FROM filing_meta WHERE filing_id = ?", [annual]).fetchone()
    book = load_factbook(con, ent, scope, datetime(2026, 11, 1))
    assert book.instants["total_assets"][date(2026, 3, 31)] == Decimal("18765991000.00")  # 187,659.91 x 10^5
    raw = con.execute("SELECT value_inr FROM fact_observations WHERE filing_id = ? AND canonical_tag = 'total_assets' "
                      "AND period_end = '2026-03-31'", [annual]).fetchone()[0]  # fmt: skip
    assert raw == Decimal("187659.91")  # the filed fact is kept
    closed = con.execute("SELECT resolution FROM quarantine_queue WHERE quarantine_id = ?", [qid]).fetchone()[0]
    assert closed == "FIXED_BY_RULE"
    # compared at the corrected scale: every total agrees, lines regrouped (X312: resolved ACCEPTED by class)
    [(_, fid2, after)] = [
        (q, f, json.loads(d))
        for q, f, d in con.execute(
            "SELECT quarantine_id, filing_id, details FROM quarantine_queue WHERE reason_code = ? AND resolution = "
            "'ACCEPTED' AND resolution_note LIKE 'Rule X312 PRIOR_YEAR_ACCEPTED_CLASS%'",
            [PRIOR_YEAR_REASON],
        ).fetchall()
    ]
    assert not _open(con)
    assert fid2 == annual and after["class"] == "REGROUPED" and after["totals_differ"] == []
    assert after["scale_lines"] == [] and {"employee_benefit_expense", "other_expenses"} <= {
        x["tag"] for x in after["differences"]
    }


def test_x233_cash_flows_moved_between_activities_are_reclassified(market):
    assert promote(market.con, market.stage_day("20250919")).status == "PROMOTED"
    q4 = "INTEGRATED_FILING_INDAS_1433394_07052025082905_WEB.xml"
    _promote(market, RESTATED, q4, datetime(2025, 5, 7, 14, 59, 6))
    _promote(market, RESTATED, "AR_XBRL_VINCOFE_11112026131428.xml", datetime(2026, 11, 11, 7, 44, 29))
    [(_, _, d)] = _open(market.con)
    assert d["class"] == "RESTATED" and d["subclass"] == "RECLASSIFIED"
    assert set(d["totals_differ"]) <= {"cfo", "cfi", "cff"} and "cfo" in d["totals_differ"]
    cfo = next(x for x in d["differences"] if x["tag"] == "cfo")
    assert (Decimal(cfo["stored"]), Decimal(cfo["annual"])) == (Decimal("-257608000"), Decimal("-211632000"))


def test_x234_discontinued_operation_re_presented(market):
    assert promote(market.con, market.stage_day("20250919")).status == "PROMOTED"
    q4 = "INTEGRATED_FILING_INDAS_1439467_15052025103557_WEB.xml"
    _promote(market, RESTATED, q4, datetime(2025, 5, 15, 5, 5, 58))
    _promote(market, RESTATED, "AR_XBRL_BASF_10092026090839.xml", datetime(2026, 9, 10, 3, 38, 39))
    [(_, _, d)] = _open(market.con)
    assert d["class"] == "RESTATED" and d["subclass"] == "DISCONTINUED_REPRESENTED"
    assert {"total_income", "total_expenses", "pbt"} <= set(d["totals_differ"]) and "pat" not in d["totals_differ"]
    disc = next(x for x in d["differences"] if x["tag"] == "pat_discontinued")
    assert (Decimal(disc["stored"]), Decimal(disc["annual"]) / CR) == (Decimal(0), Decimal("-4.80"))


def test_restated_subclass_needs_every_bottom_line_compared():
    diffs = [{"tag": "cfo", "annual": "10", "stored": "5"}, {"tag": "cfi", "annual": "-10", "stored": "-5"}]
    every = {"compared": {"pat", "total_equity", "net_cash_flow", "cfo", "cfi"}, "discontinued_filed": False}
    assert prior_year_class(diffs, every)["subclass"] == "RECLASSIFIED"
    assert prior_year_class(diffs, {**every, "compared": {"pat", "total_equity"}})["subclass"] == "CASH_FLOW_RESTATED"
    assert prior_year_class(diffs)["subclass"] == "BOTTOM_LINE_RESTATED"  # no context: nothing proven
    pat = [*diffs, {"tag": "pat", "annual": "100", "stored": "90"}]
    assert prior_year_class(pat, every)["subclass"] == "BOTTOM_LINE_RESTATED"
    assert "subclass" not in prior_year_class([{"tag": "li_x", "annual": "1", "stored": "2"}], every)  # REGROUPED
