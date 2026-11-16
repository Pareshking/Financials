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


def test_correction_marks_the_entity_for_incremental_materialisation(market):
    fid, ent, _scope = _promote(market)
    market.con.execute("DELETE FROM materialize_dirty")
    correct_from_pdf(market.con, fid, [
        {"canonical_tag": "pat_owners", "period_start": Q4[0], "period_end": Q4[1], "value_inr": "11667000000"},
    ], **EVIDENCE)  # fmt: skip
    rows = market.con.execute("SELECT entity_id, from_date FROM materialize_dirty").fetchall()
    assert rows and {e for e, _ in rows} == {ent} and min(d for _, d in rows) <= VISIBLE.date()


# ── batch K: per-share corrections (EPS, face value) carry value_other ──
# The fixture files basic EPS 13.17 / diluted 13.15 for Q4. 13.20 below is a test value, not a claim about the PDF.


def test_per_share_correction_ranks_above_the_filed_eps_and_revoking_restores_it(market):
    from financials import features_pl
    from financials.fundamentals import clear_prefetch, prefetch_fundamentals

    fid, ent, scope = _promote(market)
    ts = datetime(2026, 1, 1)
    filed = load_factbook(market.con, ent, scope, ts)
    assert filed.durations["eps_basic"][Q4] == Decimal("13.17")
    assert filed.durations["eps_diluted"][Q4] == Decimal("13.15")
    ids = correct_from_pdf(market.con, fid, [
        {"canonical_tag": "eps_basic", "period_start": Q4[0], "period_end": Q4[1], "value_other": "13.20"},
        {"canonical_tag": "eps_diluted", "period_start": Q4[0], "period_end": Q4[1], "value_other": "13.1825"},
    ], **EVIDENCE)  # fmt: skip
    stored = market.con.execute(
        "SELECT canonical_tag, value_inr, value_other FROM fact_corrections ORDER BY canonical_tag"
    ).fetchall()
    assert stored == [("eps_basic", None, Decimal("13.2000")), ("eps_diluted", None, Decimal("13.1825"))]
    book = load_factbook(market.con, ent, scope, ts)
    assert book.durations["eps_basic"][Q4] == Decimal("13.20")
    assert book.durations["eps_diluted"][Q4] == Decimal("13.1825")
    assert book.durations["pat"] == filed.durations["pat"]  # nothing else moves
    prefetch_fundamentals(market.con, ts)  # the batch path used by materialize ranks it the same way
    try:
        assert load_factbook(market.con, ent, scope, ts).durations == book.durations
    finally:
        clear_prefetch(market.con, ts)
    pl = features_pl.period_values(market.con, book, Q4[1], ts)
    assert pl["eps"]["eps_latest_quarter"] == (Decimal("13.20"), date(2025, 4, 24))  # filing's result date
    assert load_factbook(market.con, ent, scope, datetime(2025, 4, 1)).durations == {}  # PIT: not before the filing
    raw = market.con.execute(
        "SELECT value_other FROM fact_observations WHERE filing_id = ? AND canonical_tag = 'eps_basic' "
        "AND period_start = ? AND period_end = ?", [fid, *Q4]).fetchall()  # fmt: skip
    assert raw and {v for (v,) in raw} == {Decimal("13.17")}  # the filed fact is untouched
    for cid in ids:
        revoke_correction(market.con, cid, "test")
    assert load_factbook(market.con, ent, scope, ts).durations == filed.durations


def test_per_share_correction_without_filed_value_gets_the_filings_result_date(market):
    from financials import features_pl

    fid, ent, scope = _promote(market)
    ts = datetime(2026, 1, 1)
    # Simulate a filing that never tagged basic EPS (test-only delete; the code itself never deletes facts).
    market.con.execute("DELETE FROM fact_observations WHERE filing_id = ? AND canonical_tag = 'eps_basic'", [fid])
    assert Q4 not in load_factbook(market.con, ent, scope, ts).durations.get("eps_basic", {})
    correct_from_pdf(market.con, fid, [
        {"canonical_tag": "eps_basic", "period_start": Q4[0], "period_end": Q4[1], "value_other": "13.17"},
    ], **EVIDENCE)  # fmt: skip
    book = load_factbook(market.con, ent, scope, ts)
    assert book.durations["eps_basic"][Q4] == Decimal("13.17")
    features_pl.prefetch(market.con, ts)  # batch path of the visibility rows
    try:
        pl = features_pl.period_values(market.con, book, Q4[1], ts)
    finally:
        features_pl.clear(market.con, ts)
    assert pl["eps"]["eps_latest_quarter"] == (Decimal("13.17"), date(2025, 4, 24))


@pytest.mark.parametrize(
    "correction",
    [
        {"canonical_tag": "eps_basic", "value_inr": "13.20"},  # per-share tag in rupees
        {"canonical_tag": "eps_basic", "value_other": "13.20", "value_inr": "1"},  # both
        {"canonical_tag": "pat", "value_other": "1"},  # rupee tag per share
        {"canonical_tag": "eps_basic", "value_other": "13.12345"},  # beyond DECIMAL(18,4)
        {"canonical_tag": "pat", "value_inr": "1.005"},  # beyond DECIMAL(20,2)
    ],
)
def test_corrections_take_the_value_column_of_their_unit(market, correction):
    fid, _ent, _scope = _promote(market)
    with pytest.raises(AdminError):
        correct_from_pdf(market.con, fid, [{"period_start": Q4[0], "period_end": Q4[1], **correction}], **EVIDENCE)
    assert market.con.execute("SELECT count(*) FROM fact_corrections").fetchone()[0] == 0


def test_schema_upgrade_adds_value_other_to_an_existing_fact_corrections(tmp_path):
    import duckdb

    from financials.db import apply_schema, table_columns

    con = duckdb.connect(str(tmp_path / "old.duckdb"))
    apply_schema(con)
    con.execute("ALTER TABLE fact_corrections DROP COLUMN value_other")  # a database from before batch K
    assert "value_other" not in table_columns(con, "fact_corrections")
    executed = apply_schema(con)
    assert any("fact_corrections ADD COLUMN IF NOT EXISTS value_other DECIMAL(18,4)" in s for s in executed)
    assert "value_other" in table_columns(con, "fact_corrections")
