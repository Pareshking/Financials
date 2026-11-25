"""RULES25 X364: a BOTTOM_LINE_RESTATED prior-year finding settled by the annual XBRL's own reconciliation table.

Shankara Building Products consolidated: the FY26 annual report restates FY25 for the demerger of note 59 and files,
in the text block `DisclosureOfReclassificationsOrChangesInPresentationExplanatory`, a table "As at 31-03-2025 /
Transfer on account of Demerger / Regrouping / Elimination Adjustments / As at March 31, 2025 (Restated)" (Rupees in
Crores) that prints FY25 PAT 77.40 -> 0.79 and total equity 867.80 -> 410.96: the stored Q4 FY25 figures and the
annual XBRL comparatives. Rule RESTATEMENT_RECONCILED_IN_FILING (`audit-annual` with the vault) resolves it ACCEPTED.
"""

from __future__ import annotations

import json
from datetime import datetime

from conftest import FETCHED_AT

from _fixture_helpers import FIXTURES
from financials.filing_checks import PRIOR_YEAR_REASON, restatement_reconciliation
from financials.promoter import audit_annual_checks, promote
from financials.staging import stage_results_xbrl

RESTATED = FIXTURES / "annual_restated"
URL = "https://nsearchives.nseindia.com/corporate/xbrl/"
Q4_FY25 = "INTEGRATED_FILING_INDAS_1441327_16052025054934_WEB.xml"
FY26 = "AR_XBRL_SHANKARA_09082026020807.xml"


def _promote(m, name, ts):
    r = promote(m.con, stage_results_xbrl(m.vault, m.stage_root, data=(RESTATED / name).read_bytes(),
                                          source_url=URL + name, fetched_at=FETCHED_AT, broadcast_ts=ts,
                                          broadcast_ts_source="API_FIELD"))  # fmt: skip
    assert r.status == "PROMOTED", (name, r)


def _findings(con):
    return con.execute(
        "SELECT details, resolution, resolution_note FROM quarantine_queue WHERE reason_code = ? ORDER BY 1",
        [PRIOR_YEAR_REASON],
    ).fetchall()


def test_x364_reconciliation_table_settles_the_finding(market):
    assert promote(market.con, market.stage_day("20250919")).status == "PROMOTED"
    _promote(market, Q4_FY25, datetime(2025, 5, 16, 12, 19, 34))
    _promote(market, FY26, datetime(2026, 8, 8, 20, 38, 13))
    [(det, res, _)] = _findings(market.con)
    d = json.loads(det)
    assert res is None and d["scope"] == "CONSOLIDATED" and d["subclass"] == "BOTTOM_LINE_RESTATED"
    # without the vault the rule does not run: nothing changes
    assert audit_annual_checks(market.con)["accepted_reconciled"] == 0
    assert _findings(market.con)[0][1] is None
    r = audit_annual_checks(market.con, vault=market.vault)
    assert r["accepted_reconciled"] == 1 and r["open_prior_year"] == 0
    [(det2, res2, note)] = _findings(market.con)
    assert json.loads(det2) == d and res2 == "ACCEPTED"  # same finding, still visible
    assert "X364 RESTATEMENT_RECONCILED_IN_FILING" in note
    assert "DisclosureOfReclassificationsOrChangesInPresentationExplanatory" in note
    assert "pat stored 77.40 -> annual 0.79" in note and "total_equity stored 867.80 -> annual 410.96" in note
    # idempotent: resolved findings are kept as they are
    assert audit_annual_checks(market.con, vault=market.vault)["accepted_reconciled"] == 0


def test_x364_needs_both_amounts_of_every_differing_bottom_line():
    xbrl = (RESTATED / FY26).read_bytes()
    fy, ye = ["2024-04-01", "2025-03-31"], ["2025-03-31", "2025-03-31"]
    pat = {"tag": "pat", "period": fy, "annual": "7900000", "stored": "774000000"}
    eq = {"tag": "total_equity", "period": ye, "annual": "4109600000", "stored": "8678000000"}
    both = {"pat", "total_equity"}
    ev = restatement_reconciliation(xbrl, [pat, eq], both)
    assert ev["unit"] == "crore" and ev["lines"] == {"pat": ["77.40", "0.79"], "total_equity": ["867.80", "410.96"]}
    assert restatement_reconciliation(xbrl, [pat], both)["lines"] == {"pat": ["77.40", "0.79"]}
    # a stored amount the table does not print, a bottom line not compared, or no bottom line differing
    assert restatement_reconciliation(xbrl, [pat, {**eq, "stored": "8679000000"}], both) is None
    assert restatement_reconciliation(xbrl, [pat, eq], {"pat"}) is None
    assert restatement_reconciliation(xbrl, [{**pat, "tag": "total_income"}], both) is None
    # a results filing with no restatement wording proves nothing
    assert restatement_reconciliation((RESTATED / Q4_FY25).read_bytes(), [pat, eq], both) is None
