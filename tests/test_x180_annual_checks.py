"""QA X180-X182: the Reg. 34 annual checks (G328 prior-year columns [X110], G93 year-end share counts [X114]) on the
expanded universe. Real, unmodified fixtures throughout (MANIFEST.md "QA X180-X182"):

- X180: both checks ran only at promotion, so the outcome depended on promotion order (TCS FY26 promoted before its
  FY25 report finds nothing to compare). `audit_annual_checks` re-runs them on the data now stored and gives the
  broadcast-order answer; a second run changes nothing.
- X181: GREENPLY Q4 FY25 results file face value 10 with paid-up 12.49 Cr (12,487,300 shares); the FY25 annual report
  and the Reg. 31 filing of 31-Mar-2025 both state 124,873,295 shares. Reg. 31 decides; the results filing keeps its
  own CROSS_CHECK_FAILED finding.
- X182: triage class of a prior-year finding: TCS FY26 regroups (totals agree), RELINFRA FY26 restates FY25 totals.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

from conftest import FETCHED_AT

from _fixture_helpers import FIXTURES, XBRL_DIR
from financials.filing_checks import PRIOR_YEAR_REASON, prior_year_class
from financials.promoter import audit_annual_checks, close_resolved_annual_share_findings, promote
from financials.share_capital import REASON as SHARE_REASON
from financials.staging import stage_results_xbrl, stage_shareholding

QA_DIR = FIXTURES / "annual_checks"
TCS25 = "AR_XBRL_TCS_14082025184751.xml"
TCS26 = "AR_XBRL_TCS_09082026012216.xml"
RELINFRA25 = "AR_XBRL_RELINFRA_06092025221939.xml"
RELINFRA26 = "AR_XBRL_RELINFRA_18092026172005.xml"
GREENPLY_AR25 = "AR_XBRL_GREENPLY_24092025103040.xml"
GREENPLY_Q4FY25 = "INTEGRATED_FILING_INDAS_1426806_28042025073334_WEB.xml"
GREENPLY_SHP = "SHP_198395_1419898_19042025033622_WEB.xml"
CR = Decimal(10) ** 7


def _promote(m, path, ts: datetime):
    staged = stage_results_xbrl(m.vault, m.stage_root, data=path.read_bytes(),
                                source_url="https://nsearchives.nseindia.com/corporate/xbrl/" + path.name,
                                fetched_at=FETCHED_AT, broadcast_ts=ts, broadcast_ts_source="API_FIELD")  # fmt: skip
    r = promote(m.con, staged)
    assert r.status == "PROMOTED", r
    return r


def _open(m, reason):
    return m.con.execute(
        "SELECT quarantine_id, filing_id, details FROM quarantine_queue WHERE reason_code = ? AND resolved_at IS NULL "
        "ORDER BY quarantine_id",
        [reason],
    ).fetchall()


# ── X180: promotion order ──────────────────────────────────────────────────────────────────────────────────────


def test_prior_year_check_rerun_does_not_depend_on_promotion_order(market):
    promote(market.con, market.stage_day("20250227"))  # TCS known before both reports
    _promote(market, XBRL_DIR / TCS26, datetime(2026, 8, 8, 19, 52, 19))  # the later report first
    assert not _open(market, PRIOR_YEAR_REASON)  # nothing stored for FY25 yet: the check had nothing to compare
    _promote(market, XBRL_DIR / TCS25, datetime(2025, 8, 14, 13, 17, 52))
    assert not _open(market, PRIOR_YEAR_REASON)  # FY25's own report has no in-scope prior year (C9)

    r = audit_annual_checks(market.con)
    assert r["annual_filings"] == 2 and r["findings"] == 1 and r["closed"] == 0 and r["open_prior_year"] == 1
    [(_, fid, details)] = _open(market, PRIOR_YEAR_REASON)
    d = json.loads(details)
    tcs26 = market.con.execute("SELECT filing_id FROM filings WHERE source_url LIKE ?", ["%" + TCS26]).fetchone()[0]
    assert fid == tcs26
    # the same differences as promotion in broadcast order (test_restatement_triggers, X110)
    assert {x["tag"]: (Decimal(x["stored"]) / CR, Decimal(x["annual"]) / CR) for x in d["differences"]} == {
        "li_managerial_remuneration": (Decimal(38), Decimal(45)),
        "li_remuneration_to_directors": (Decimal(38), Decimal(45)),
        "li_salary_to_directors": (Decimal(38), Decimal(45)),
        "li_salaries_and_wages": (Decimal(129997), Decimal(129990)),
    }
    assert d["class"] == "REGROUPED" and d["totals_differ"] == [] and d["scale_lines"] == []  # X182
    again = audit_annual_checks(market.con)  # idempotent: same deterministic id, nothing closed
    assert again["findings"] == 1 and again["closed"] == 0 and len(_open(market, PRIOR_YEAR_REASON)) == 1


# ── X182: triage class ─────────────────────────────────────────────────────────────────────────────────────────


def test_relinfra_fy26_restates_fy25_statement_totals(market):
    promote(market.con, market.stage_day("20250227"))  # RELINFRA known before both reports
    _promote(market, XBRL_DIR / RELINFRA25, datetime(2025, 9, 6, 16, 49, 39))
    r = _promote(market, XBRL_DIR / RELINFRA26, datetime(2026, 9, 18, 11, 50, 5))
    [(qid, _, details)] = _open(market, PRIOR_YEAR_REASON)
    assert qid in r.quarantined
    d = json.loads(details)
    diffs = {x["tag"]: (Decimal(x["stored"]) / CR, Decimal(x["annual"]) / CR) for x in d["differences"]}
    assert diffs["total_assets"] == (Decimal("12046.07"), Decimal("31002.15"))
    assert diffs["pat"] == (Decimal("-1108.05"), Decimal("-609.96"))
    assert d["class"] == "RESTATED" and {"total_assets", "total_equity", "pat"} <= set(d["totals_differ"])


def test_scale_class_is_an_exact_power_of_ten_and_wins():
    # KUANTUM FY26 annual (vault, not committed): FY25 income tax 40,197,100,000 vs its FY25 report's 401,971,000
    d = [
        {"tag": "li_income_tax_expense_continuing_operations", "annual": "40197100000.00", "stored": "401971000.00"},
        {"tag": "pat", "annual": "100.00", "stored": "90.00"},
    ]
    assert prior_year_class(d) == {"class": "SCALE", "scale_lines": ["li_income_tax_expense_continuing_operations"],
                                   "totals_differ": ["pat"]}  # fmt: skip
    near = [{"tag": "li_x", "annual": "1010", "stored": "100"}, {"tag": "li_y", "annual": "-1000", "stored": "100"}]
    assert prior_year_class(near)["class"] == "REGROUPED"  # 10.1x is not a scale error; a sign flip is not either


# ── X181: Reg. 31 decides the annual share count check ────────────────────────────────────────────────────────


def _greenply_shp(m):
    r = promote(m.con, stage_shareholding(m.vault, m.stage_root, data=(QA_DIR / GREENPLY_SHP).read_bytes(),
                                          source_url="https://nsearchives.nseindia.com/corporate/xbrl/" + GREENPLY_SHP,
                                          fetched_at=FETCHED_AT, broadcast_ts=datetime(2025, 4, 19, 10, 6, 23),
                                          broadcast_ts_source="API_FIELD"))  # fmt: skip
    assert r.status == "PROMOTED", r


def test_reg31_agreeing_with_the_annual_decides_over_a_mistyped_face_value(market):
    promote(market.con, market.stage_day("20250227"))  # GREENPLY known
    _greenply_shp(market)
    _promote(market, QA_DIR / GREENPLY_Q4FY25, datetime(2025, 4, 28, 14, 3, 35))
    [(_, _, cc)] = market.con.execute(
        "SELECT quarantine_id, filing_id, details FROM quarantine_queue WHERE reason_code = 'CROSS_CHECK_FAILED'"
    ).fetchall()
    cc = json.loads(cc)  # the results filing's own finding: 12.49 Cr / face 10 vs the Reg. 31 total
    assert Decimal(cc["paid_up_over_face_value"]) == 12487300 and Decimal(cc["reg31_total"]) == 124873295
    _promote(market, QA_DIR / GREENPLY_AR25, datetime(2025, 9, 24, 5, 0, 40))
    assert not _open(market, SHARE_REASON)  # before X181 this raised: paid-up / face value 10x off the annual count


def test_annual_finding_raised_before_reg31_arrived_closes_on_recheck(market):
    promote(market.con, market.stage_day("20250227"))
    _promote(market, QA_DIR / GREENPLY_Q4FY25, datetime(2025, 4, 28, 14, 3, 35))
    _promote(market, QA_DIR / GREENPLY_AR25, datetime(2025, 9, 24, 5, 0, 40))
    [(_, _, details)] = _open(market, SHARE_REASON)  # only paid-up / face value to compare with: it decides
    d = json.loads(details)
    assert d["decided_by"] == "paid_up_over_face_value" and d["annual_counts"]["paid_up"] == "124873295"
    assert d["references"] == {"paid_up_over_face_value": ["12487300"]}
    _greenply_shp(market)  # the FY-end Reg. 31 filing is promoted later
    assert close_resolved_annual_share_findings(market.con) == 1
    assert not _open(market, SHARE_REASON)
    note = market.con.execute(
        "SELECT resolution, resolution_note FROM quarantine_queue WHERE reason_code = ?", [SHARE_REASON]
    ).fetchone()
    assert note[0] == "FIXED_BY_RULE" and "X181" in note[1]
