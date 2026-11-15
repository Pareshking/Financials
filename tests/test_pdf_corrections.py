"""PDF-verified corrections (owner decision B, 2026-11-15).

Tech Mahindra Q4 FY25 consolidated (1424350) files owners + NCI = OCI and no TCI split, so X86 withholds the split.
Its statutory statement prints owners 1,166.7 Cr and NCI (24.8) Cr (PAT 1,141.9 Cr). A correction recorded with
its evidence is ranked above the filing's own (withheld) values, from the filing's visibility; raw facts are kept.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from _fixture_helpers import XBRL_DIR
from financials.admin import AdminError, correct_from_pdf, revoke_correction
from financials.fundamentals import load_factbook
from financials.promoter import promote
from financials.staging import stage_results_xbrl

TECHM = "INTEGRATED_FILING_INDAS_1424350_24042025113829_WEB.xml"
Q4 = (date(2025, 1, 1), date(2025, 3, 31))
VISIBLE = datetime(2025, 4, 24, 11, 38)
EVIDENCE = dict(evidence_url="https://nsearchives.nseindia.com/corporate/TECHM_example.pdf", evidence_page=3,
                evidence_text="Owners of the Company 1,166.7 / Non-controlling interests (24.8)", reads="TEXT+HAIKU",
                note="test")  # fmt: skip


def _promote(market):
    promote(market.con, market.stage_day("20250228"))
    r = promote(market.con, stage_results_xbrl(
        market.vault, market.stage_root, data=(XBRL_DIR / TECHM).read_bytes(),
        source_url="https://nsearchives.nseindia.com/corporate/xbrl/" + TECHM,
        fetched_at=datetime(2026, 11, 14, 6), broadcast_ts=VISIBLE, broadcast_ts_source="API_FIELD"))  # fmt: skip
    assert r.status == "PROMOTED", r
    fid = r.message
    ent, scope = market.con.execute("SELECT entity_id, scope FROM filing_meta WHERE filing_id = ?", [fid]).fetchone()
    return fid, ent, scope


def test_correction_replaces_a_withheld_split_from_the_filings_visibility(market):
    fid, ent, scope = _promote(market)
    book = load_factbook(market.con, ent, scope, datetime(2026, 1, 1))
    assert Q4 in book.durations["attribution_withheld"] and Q4 not in book.durations.get("pat_owners", {})
    qid = market.con.execute(
        "SELECT quarantine_id FROM quarantine_queue WHERE filing_id = ? AND reason_code = 'ATTRIBUTION_WITHHELD'",
        [fid]).fetchone()[0]  # fmt: skip
    correct_from_pdf(market.con, fid, [
        {"canonical_tag": "pat_owners", "period_start": Q4[0], "period_end": Q4[1], "value_inr": "11667000000"},
        {"canonical_tag": "pat_nci", "period_start": Q4[0], "period_end": Q4[1], "value_inr": "-248000000"},
    ], quarantine_id=qid, **EVIDENCE)  # fmt: skip
    book = load_factbook(market.con, ent, scope, datetime(2026, 1, 1))
    assert book.durations["pat_owners"][Q4] == Decimal("11667000000")
    assert book.durations["pat_nci"][Q4] == Decimal("-248000000")
    assert Q4 not in book.durations.get("attribution_withheld", {})
    assert book.durations["pat"][Q4] == Decimal("11418960000")  # PAT as filed; owners + NCI = 1,141.9 Cr
    from financials.fundamentals import clear_prefetch, prefetch_fundamentals

    ts = datetime(2026, 1, 1)
    prefetch_fundamentals(market.con, ts)  # the batch path used by materialize sees the same correction
    try:
        assert load_factbook(market.con, ent, scope, ts).durations == book.durations
    finally:
        clear_prefetch(market.con, ts)
    before = load_factbook(market.con, ent, scope, datetime(2025, 4, 1))
    assert before.durations == {}  # nothing visible before the filing
    res = market.con.execute("SELECT resolution FROM quarantine_queue WHERE quarantine_id = ?", [qid]).fetchone()[0]
    assert res == "CORRECTED"
    raw = market.con.execute(
        "SELECT count(*) FROM fact_observations WHERE filing_id = ? AND canonical_tag = 'attribution_withheld'", [fid]
    ).fetchone()[0]
    assert raw > 0  # the filed facts are untouched


def test_revoking_restores_the_filed_values_and_corrections_need_two_reads(market):
    fid, ent, scope = _promote(market)
    ids = correct_from_pdf(market.con, fid, [
        {"canonical_tag": "pat_owners", "period_start": Q4[0], "period_end": Q4[1], "value_inr": "11667000000"},
    ], **EVIDENCE)  # fmt: skip
    for cid in ids:
        revoke_correction(market.con, cid, "test")
    book = load_factbook(market.con, ent, scope, datetime(2026, 1, 1))
    assert Q4 in book.durations["attribution_withheld"] and Q4 not in book.durations.get("pat_owners", {})
    with pytest.raises(AdminError):
        correct_from_pdf(market.con, fid, [{"canonical_tag": "pat", "period_start": Q4[0], "period_end": Q4[1],
                                           "value_inr": "1"}], **{**EVIDENCE, "reads": "HAIKU"})  # fmt: skip
