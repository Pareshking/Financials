"""scripts/open_findings_report.py (work QZ, owner decision 2026-11-19): every open finding gets exactly one cause from
a closed, documented taxonomy; the script only reads."""

import importlib.util
import json
from datetime import datetime
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "open_findings_report.py"


@pytest.fixture(scope="module")
def ofr():
    spec = importlib.util.spec_from_file_location("open_findings_report", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_taxonomy_is_closed_and_documented(ofr):
    assert "UNCLASSIFIED" in ofr.CAUSES
    for cause, (reason, action, desc) in ofr.CAUSES.items():
        assert action in ofr.ACTIONS, cause
        assert reason and desc.strip(), cause


def test_every_open_finding_of_the_fixture_db_gets_one_cause(ofr, full_market):
    con = full_market.con
    before = con.execute("SELECT count(*), count(resolved_at) FROM quarantine_queue").fetchone()
    n_open = con.execute("SELECT count(*) FROM quarantine_queue WHERE resolved_at IS NULL").fetchone()[0]
    rows = ofr.classify(con)
    assert len(rows) == n_open and len({r["quarantine_id"] for r in rows}) == n_open
    assert all(r["cause"] in ofr.CAUSES and r["action"] == ofr.CAUSES[r["cause"]][1] for r in rows)
    assert [r for r in rows if r["cause"] == "UNCLASSIFIED"] == []
    assert all(r["cohort"] in ofr.COHORTS for r in rows)
    assert con.execute("SELECT count(*), count(resolved_at) FROM quarantine_queue").fetchone() == before
    md = ofr.to_markdown(rows, "fixture", "open_findings.csv")
    assert "| all | UNCLASSIFIED | - | 0 | 0 | 0 | 0 | 0 |" in md
    assert ofr.to_csv(rows).count("\n") == n_open + 1


def _q(con, qid, stage, reason, details, entity_id=None):
    con.execute(
        "INSERT INTO quarantine_queue (quarantine_id, stage, reason_code, entity_id, details, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [qid, stage, reason, entity_id, json.dumps(details), datetime(2026, 11, 19)],
    )


def test_causes_from_details_and_unknown_reason_is_unclassified(ofr, market, tmp_path):
    con = market.con
    con.execute("INSERT INTO entity_master (entity_id, legal_name) VALUES ('ent_x', 'X LIMITED')")
    ytd = {"quarters": 2, "quarters_sum": "1000.00", "scope": "STANDALONE", "tag": "pat", "tolerance": "1.00",
           "ytd": "1500.00", "ytd_period": ["2026-04-01", "2026-09-30"]}  # fmt: skip
    _q(con, "q1", "CONSISTENCY", "YTD_QUARTER_MISMATCH", ytd, "ent_x")
    _q(con, "q2", "CONSISTENCY", "YTD_QUARTER_MISMATCH", {**ytd, "ytd": "1005.00"}, "ent_x")
    attr = {"nci": "50000", "owners": "0", "pat": "900000", "period": ["2026-01-01", "2026-03-31"], "tolerance": "3000"}
    _q(con, "q3", "IDENTITY", "ATTRIBUTION_WITHHELD", attr, "ent_x")
    _q(con, "q4", "IDENTITY", "ATTRIBUTION_WITHHELD", {**attr, "owners": "849000"}, "ent_x")
    py = {"class": "RESTATED", "subclass": "BOTTOM_LINE_RESTATED", "differences": [], "scale_lines": [],
          "scope": "CONSOLIDATED", "totals_differ": ["pat"]}  # fmt: skip
    _q(con, "q5", "CONSISTENCY", "ANNUAL_PRIOR_YEAR_DIFFERS", py, "ent_x")
    _q(con, "q6", "SOMETHING", "A_NEW_REASON", {}, "ent_x")
    cc = {"as_of": "2026-09-30", "employee_trust_shares": "0", "paid_up_over_face_value": "1000000",
          "reg31_total": "1100000", "relative_diff": "0.1"}  # fmt: skip
    _q(con, "q7", "SHARES", "CROSS_CHECK_FAILED", cc, "ent_x")
    _q(con, "q8", "IDENTITY", "UNKNOWN_ISIN", {"isin": "INE000X01010", "symbol": "NOSUCH"})
    causes = {r["quarantine_id"]: r["cause"] for r in ofr.classify(con)}
    assert causes == {"q1": "YTD_INTERIM_NOT_SUM_OF_QUARTERS", "q2": "YTD_GAP_UNDER_1PCT",
                      "q3": "AW_OWNERS_ZERO_NCI_BEYOND_ROUNDING", "q4": "AW_GAP_UNDER_HALF_PCT",
                      "q5": "PY_BOTTOM_LINE_RESTATED", "q6": "UNCLASSIFIED", "q7": "CC_NO_ISSUE_SIZE",
                      "q8": "ID_NOT_IN_UNIVERSE"}  # fmt: skip
    con.execute("CHECKPOINT")
    market.con.close()
    out = tmp_path / "report.md"
    assert ofr.main([str(tmp_path / "market.duckdb"), "--out", str(out)]) == 1  # UNCLASSIFIED > 0 fails
    assert "| all | UNCLASSIFIED | - | 1 | 0 | 0 | 0 | 1 |" not in out.read_text()  # q6 has no member: NONE
    assert "| all | UNCLASSIFIED | - | 0 | 0 | 0 | 1 | 1 |" in out.read_text()
    assert not (tmp_path / "report.csv").exists()  # the CSV is never written next to the committed report
    assert (tmp_path / "open_findings.csv").read_text().count("\n") == 9  # next to the database (gitignored)
    market.con = ofr.duckdb.connect(str(tmp_path / "market.duckdb"))  # the fixture closes it at teardown
