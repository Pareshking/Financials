"""Batch 10, part 2: financial edge cases [E8-E11].

- Revised filing (ICICI Lombard Q2 FY27: 1738196 original, 1740432 revision, bytes differ in RPT detail only).
- Byte-identical re-send (Go Digit Ind AS 117 Q2 FY27: the 5-Nov and 12-Nov files share one sha256; committed once).
- Audit-opinion declaration on Integrated Filings (ELIN Q4 FY26 audited vs Q2 FY27 limited review).
- Discontinued operations (Tata Motors PV, Q2 FY26 demerger quarter).
- Period-length gating on a Reg. 34 annual filing (15-month and 27-month years, in memory: no real 15-month
  in-scope filing was found [E11]).
"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from conftest import FETCHED_AT

from _fixture_helpers import XBRL_DIR
from financials.fundamentals import annual_ratios
from financials.parsers.indas_corp import parse_indas_corp_results
from financials.parsers.reg34_annual import parse_reg34_annual
from financials.promoter import promote
from financials.staging import stage_results_xbrl

LOMBARD_ORIGINAL = XBRL_DIR / "INTEGRATED_FILING_GI_1738196_14102026103636_WEB.xml"
LOMBARD_REVISION = XBRL_DIR / "INTEGRATED_FILING_GI_1740432_16102026073544_WEB.xml"
DIGIT = XBRL_DIR / "IF_INS_COM_IND_AS_21009_WebXMLFile_20261105_192422730.xml"
ELIN_Q4 = XBRL_DIR / "INTEGRATED_FILING_INDAS_1672621_25052026073245_WEB.xml"
ELIN_Q2 = XBRL_DIR / "INTEGRATED_FILING_INDAS_1753867_05112026061857_WEB.xml"
TMPV_Q2FY26 = XBRL_DIR / "INTEGRATED_FILING_INDAS_1574923_14112025041850_WEB.xml"
TCS26 = XBRL_DIR / "AR_XBRL_TCS_09082026012216.xml"
ARCHIVE = "https://nsearchives.nseindia.com/corporate/xbrl/"


@pytest.fixture
def m(market):
    promote(market.con, market.stage_day("20261112"))
    return market


def _stage(m, data, url, ts):
    return stage_results_xbrl(m.vault, m.stage_root, data=data, source_url=url, fetched_at=FETCHED_AT,
                              broadcast_ts=ts, broadcast_ts_source="API_FIELD")  # fmt: skip


def _latest_filing(con, tag, as_of):
    return con.execute(
        "SELECT filing_id FROM fact_observations WHERE canonical_tag = ? AND visible_from_ts <= ? "
        "ORDER BY period_end DESC, visible_from_ts DESC LIMIT 1",
        [tag, as_of],
    ).fetchone()[0]


def test_revision_chain_and_point_in_time_provenance(m):
    """E9: the later filing for the same entity/profile/scope/period supersedes the earlier (REVISION: bytes
    differ); PIT reads return the original before the revision's broadcast and the revision after it."""
    t0, t1 = datetime(2026, 10, 14, 5, 6, 36), datetime(2026, 10, 16, 2, 5, 44)
    r0 = promote(m.con, _stage(m, LOMBARD_ORIGINAL.read_bytes(), ARCHIVE + LOMBARD_ORIGINAL.name, t0))
    r1 = promote(m.con, _stage(m, LOMBARD_REVISION.read_bytes(), ARCHIVE + LOMBARD_REVISION.name, t1))
    assert r0.status == r1.status == "PROMOTED"
    (link,) = m.con.execute("SELECT filing_id, supersedes_filing_id, relation FROM filing_revisions").fetchall()
    assert (link[0], link[1], link[2]) == (r1.message, r0.message, "REVISION")
    assert _latest_filing(m.con, "pat", datetime(2026, 10, 15)) == r0.message
    assert _latest_filing(m.con, "pat", datetime(2026, 10, 17)) == r1.message


def test_byte_identical_resend_is_linked_as_resend(m):
    """E10: Go Digit's two Q2 FY27 files are byte-identical (one blob, two filings): RESEND, not a revision."""
    data = DIGIT.read_bytes()
    a = promote(m.con, _stage(m, data, ARCHIVE + DIGIT.name, datetime(2026, 11, 5, 14, 0)))
    b = promote(m.con, _stage(m, data, ARCHIVE + "IF_INS_COM_IND_AS_21009_WebXMLFile_20261112_145426721.xml",
                              datetime(2026, 11, 12, 9, 30)))  # fmt: skip
    assert a.status == b.status == "PROMOTED"
    assert m.con.execute(
        "SELECT count(DISTINCT sha256), count(*) FROM filings WHERE category = 'RESULTS_XBRL'"
    ).fetchone() == (1, 2)
    assert m.con.execute("SELECT relation FROM filing_revisions").fetchall() == [("RESEND",)]


def test_audit_opinion_declaration_is_recorded(m):
    """E8: audited Q4 results declare an unmodified opinion; a limited-review quarter says 'Not applicable'.
    A qualified-opinion value has not been observed (it would be stored verbatim)."""
    assert parse_indas_corp_results(ELIN_Q4.read_bytes()).meta["audit_opinion"] == "UNMODIFIED"
    assert parse_indas_corp_results(ELIN_Q2.read_bytes()).meta["audit_opinion"] == "NOT_APPLICABLE"
    r = promote(m.con, _stage(m, ELIN_Q4.read_bytes(), ARCHIVE + ELIN_Q4.name, datetime(2026, 5, 25, 2, 0)))
    assert r.status == "PROMOTED"
    assert m.con.execute("SELECT audit_opinion FROM filing_meta").fetchone()[0] == "UNMODIFIED"


def test_discontinued_operations_chain():
    """E11 / X42: TMPV's demerger quarter: PAT = continuing + discontinued, and the PAT chain identity holds."""
    r = parse_indas_corp_results(TMPV_Q2FY26.read_bytes())
    assert r.ok, r.issues
    q = r.meta["quarter_period"]
    cont, disc, pat = (r.value(t, *q) for t in ("pat_continuing", "pat_discontinued", "pat"))
    assert disc is not None and disc != 0
    assert abs(cont + disc + (r.value("share_of_associates_jv", *q) or 0) - pat) <= 10**7


def test_fifteen_month_year_is_gated_and_never_used_as_a_fiscal_year():
    """E11: a 15-month reporting period (1..18) parses with period_months 15, but annual ratios only use
    12-month years, so they fall back to the prior 12-month year; 27 months is rejected (IRREGULAR_PERIOD)."""
    fifteen = TCS26.read_bytes().replace(b"2025-04-01", b"2025-01-01")
    r = parse_reg34_annual(fifteen, TCS26.name)
    assert r.ok, r.issues
    assert {f.period_months for f in r.facts if f.period_type == "DURATION"} == {12, 15}
    from tests.test_batch9_annual import _book

    out = annual_ratios(_book(r), date(2026, 9, 30))
    assert out["annual_fy_end"] == date(2025, 3, 31) and out["piotroski_f"] is None
    long = TCS26.read_bytes().replace(b"2025-04-01", b"2024-01-01")
    bad = parse_reg34_annual(long, TCS26.name)
    assert not bad.ok and {i.reason_code for i in bad.issues} >= {"IRREGULAR_PERIOD"}
