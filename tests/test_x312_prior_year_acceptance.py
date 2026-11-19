"""QK X312: `audit-annual` records the owner-accepted prior-year classes as ACCEPTED and carries a case-by-case
acceptance forward only when the totals are the same. Real, unmodified fixtures (MANIFEST.md "QA X180-X182",
"QP3 X233-X235"):

- PRIOR_YEAR_ACCEPTED_CLASS: Vintage Coffee consolidated FY26 (RESTATED / RECLASSIFIED, X233) and TCS FY26 (REGROUPED,
  every statement total compared and agreeing, X182) are written and resolved ACCEPTED in the same run.
- PRIOR_YEAR_ACCEPTANCE_CARRIED: RELINFRA FY26 standalone restates FY25 (BOTTOM_LINE_RESTATED, never accepted by
  class). An earlier ACCEPTED finding of the same filing that differs only in a detail line carries forward; one whose
  PAT moved by 1 Cr does not.
- A re-run changes nothing.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime
from decimal import Decimal

from conftest import FETCHED_AT

from _fixture_helpers import FIXTURES, XBRL_DIR
from financials import filing_checks as fc
from financials.db import insert_rows
from financials.promoter import _quarantine_row, audit_annual_checks, promote
from financials.staging import stage_results_xbrl

URL = "https://nsearchives.nseindia.com/corporate/xbrl/"
RESTATED = FIXTURES / "annual_restated"


def _promote(m, path, ts):
    staged = stage_results_xbrl(m.vault, m.stage_root, data=path.read_bytes(), source_url=URL + path.name,
                                fetched_at=FETCHED_AT, broadcast_ts=ts, broadcast_ts_source="API_FIELD")  # fmt: skip
    r = promote(m.con, staged)
    assert r.status == "PROMOTED", (path.name, r)


def _findings(con):
    return [(q, json.loads(d), res, note) for q, d, res, note in con.execute(
        "SELECT quarantine_id, details, resolution, resolution_note FROM quarantine_queue WHERE reason_code = ? "
        "ORDER BY quarantine_id", [fc.PRIOR_YEAR_REASON]).fetchall()]  # fmt: skip


def test_accepted_classes_are_resolved_when_written_and_rerun_is_idempotent(market):
    con = market.con
    assert promote(con, market.stage_day("20250227")).status == "PROMOTED"  # TCS known
    assert promote(con, market.stage_day("20250919")).status == "PROMOTED"  # Vintage Coffee known
    _promote(
        market, RESTATED / "INTEGRATED_FILING_INDAS_1433394_07052025082905_WEB.xml", datetime(2025, 5, 7, 14, 59, 6)
    )
    _promote(market, RESTATED / "AR_XBRL_VINCOFE_11112026131428.xml", datetime(2026, 11, 11, 7, 44, 29))
    _promote(market, XBRL_DIR / "AR_XBRL_TCS_14082025184751.xml", datetime(2025, 8, 14, 13, 17, 52))
    _promote(market, XBRL_DIR / "AR_XBRL_TCS_09082026012216.xml", datetime(2026, 8, 8, 19, 52, 19))

    r = audit_annual_checks(con)
    assert r["findings"] == 2 and r["accepted_by_class"] == 2 and r["accepted_carried"] == 0
    assert r["open_prior_year"] == 0
    got = {(d["class"], d.get("subclass")): (res, note) for _, d, res, note in _findings(con)}
    assert set(got) == {("RESTATED", "RECLASSIFIED"), ("REGROUPED", None)}  # both written, kept visible
    res, note = got[("RESTATED", "RECLASSIFIED")]
    assert res == "ACCEPTED" and "X312 PRIOR_YEAR_ACCEPTED_CLASS" in note and "X233" in note
    res, note = got[("REGROUPED", None)]
    assert res == "ACCEPTED" and "every PRIOR_YEAR_TOTALS tag was compared" in note

    before = _findings(con)
    again = audit_annual_checks(con)  # same ids, already resolved: nothing changes
    assert again["accepted_by_class"] == 0 and again["closed"] == 0 and _findings(con) == before


def test_regrouped_without_every_total_compared_stays_open():
    d = {"class": "REGROUPED", "scope": "STANDALONE", "differences": []}
    assert fc.accepted_class_note(d, {"compared": set(fc.PRIOR_YEAR_TOTALS)}) is not None
    assert fc.accepted_class_note(d, {"compared": set(fc.PRIOR_YEAR_TOTALS) - {"cfo"}}) is None
    assert fc.accepted_class_note(d, None) is None
    for sub in ("CASH_FLOW_RESTATED", "BOTTOM_LINE_RESTATED"):
        assert (
            fc.accepted_class_note({"class": "RESTATED", "subclass": sub}, {"compared": fc.PRIOR_YEAR_TOTALS}) is None
        )
    for sub in fc.RESTATED_ACCEPTABLE:
        assert fc.accepted_class_note({"class": "RESTATED", "subclass": sub}, None) is not None
    assert fc.accepted_class_note({"class": "SCALE"}, {"compared": fc.PRIOR_YEAR_TOTALS}) is None


def _relinfra(market):
    con = market.con
    promote(con, market.stage_day("20250227"))
    _promote(market, XBRL_DIR / "AR_XBRL_RELINFRA_06092025221939.xml", datetime(2025, 9, 6, 16, 49, 39))
    _promote(market, XBRL_DIR / "AR_XBRL_RELINFRA_18092026172005.xml", datetime(2026, 9, 18, 11, 50, 5))
    [(qid, d, res, _)] = _findings(con)
    assert res is None and d["class"] == "RESTATED" and d["subclass"] == "BOTTOM_LINE_RESTATED"
    fid, ent = con.execute(
        "SELECT filing_id, entity_id FROM quarantine_queue WHERE quarantine_id = ?", [qid]
    ).fetchone()
    return qid, d, fid, ent


def _earlier_accepted(con, details, fid, ent, note):
    """A finding of the same filing as an earlier run wrote it (other ids: its differences were other numbers),
    resolved ACCEPTED case by case."""
    row = _quarantine_row(stage="CONSISTENCY", reason_code=fc.PRIOR_YEAR_REASON, filing_id=fid, entity_id=ent,
                          details=details)  # fmt: skip
    row.update(resolved_at=datetime(2026, 11, 18, 12), resolution="ACCEPTED", resolution_note=note)
    insert_rows(con, "quarantine_queue", [row])
    return row["quarantine_id"]


def test_case_by_case_acceptance_carries_forward_when_the_totals_are_the_same(market):
    con = market.con
    qid, d, fid, ent = _relinfra(market)
    old = copy.deepcopy(d)
    detail = next(x for x in old["differences"] if x["tag"] not in fc.CARRY_TAGS)
    detail["annual"] = str(Decimal(detail["annual"]) + 12345678)  # a detail line moved; every total is the same
    detail["difference"] = str(Decimal(detail["annual"]) - Decimal(detail["stored"]))
    prev = _earlier_accepted(con, old, fid, ent, "case review: Ind AS 8 restatement quoted from the annual")
    assert prev != qid

    r = audit_annual_checks(con)
    assert r["accepted_carried"] == 1 and r["accepted_by_class"] == 0 and r["open_prior_year"] == 0
    res, note = con.execute("SELECT resolution, resolution_note FROM quarantine_queue WHERE quarantine_id = ?",
                            [qid]).fetchone()  # fmt: skip
    assert res == "ACCEPTED" and "X312 PRIOR_YEAR_ACCEPTANCE_CARRIED" in note and prev in note
    before = _findings(con)
    assert audit_annual_checks(con)["accepted_carried"] == 0 and _findings(con) == before


def test_no_carry_forward_when_a_bottom_line_changed(market):
    con = market.con
    qid, d, fid, ent = _relinfra(market)
    old = copy.deepcopy(d)
    pat = next(x for x in old["differences"] if x["tag"] == "pat")
    assert Decimal(pat["tolerance"]) == 10**7  # RELINFRA files in crores: 1 Cr
    pat["annual"] = str(Decimal(pat["annual"]) + 5 * 10**7)  # PAT 5 Cr apart: a different restatement
    _earlier_accepted(con, old, fid, ent, "case review")
    # another scope, or another sub-class, never carries either
    _earlier_accepted(con, {**d, "scope": "CONSOLIDATED"}, fid, ent, "case review")
    _earlier_accepted(con, {**d, "subclass": "CASH_FLOW_RESTATED"}, fid, ent, "case review")

    r = audit_annual_checks(con)
    assert r["accepted_carried"] == 0 and r["open_prior_year"] == 1
    assert con.execute("SELECT resolved_at FROM quarantine_queue WHERE quarantine_id = ?", [qid]).fetchone()[0] is None


def test_same_totals_is_within_each_lines_tolerance():
    line = {"tag": "pat", "period_type": "DURATION", "period": ["2024-04-01", "2025-03-31"], "annual": "100",
            "stored": "90", "tolerance": "5"}  # fmt: skip
    new = {"differences": [line, {"tag": "li_x", "period": ["a", "b"], "annual": "1", "stored": "2"}]}
    assert fc.same_totals(new, {"differences": [{**line, "annual": "104"}]})  # detail lines do not count
    assert not fc.same_totals(new, {"differences": [{**line, "annual": "106"}]})
    assert not fc.same_totals(new, {"differences": [line, {**line, "tag": "total_equity"}]})  # a total more
    assert not fc.same_totals({"differences": []}, {"differences": []})  # nothing to match on: no carry
