"""Backward Nifty 500 reconstruction from real NSE Indices notices (fixtures/index_changes)."""

import csv
import io
import shutil
import subprocess
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pytest

from _fixture_helpers import BHAV_DIR, FIXTURES
from financials.db import apply_schema, connect, insert_rows
from financials.index_changes import (
    IndexEvent,
    IndexInvariantError,
    parse_change_notice,
    read_manifest,
    reconstruct_backward,
    write_manifest,
)
from financials.parsers import ParseError

TEXT = FIXTURES / "index_changes" / "text"
PDF = FIXTURES / "index_changes" / "pdf"
MANIFEST = Path(__file__).parents[1] / "reference" / "nifty500_changes.csv"
NIFTY500 = FIXTURES / "indices" / "ind_nifty500list_20261113.csv"
START, AS_OF = date(2024, 10, 1), date(2026, 11, 13)


def notice(name: str) -> str:
    return (TEXT / f"ind_prs{name}.txt").read_text(encoding="utf-8")


def all_events() -> list[IndexEvent]:
    ev = []
    for p in sorted(TEXT.glob("*.txt")):
        ev += parse_change_notice(
            p.read_text(encoding="utf-8"), "Nifty 500", f"niftyindices.com/Press_Release/{p.stem}.pdf"
        )
    return ev


@pytest.mark.skipif(shutil.which("pdftotext") is None, reason="pdftotext (poppler-utils) not installed")
@pytest.mark.parametrize("pdf", sorted(PDF.glob("*.pdf")), ids=lambda p: p.stem)
def test_derived_text_matches_pdf(pdf, tmp_path):
    out = tmp_path / "x.txt"
    subprocess.run(["pdftotext", "-layout", str(pdf), str(out)], check=True)
    assert out.read_text(encoding="utf-8") == (TEXT / f"{pdf.stem}.txt").read_text(encoding="utf-8")


def test_semi_annual_rebalance():
    ev = parse_change_notice(notice("22082025"), "Nifty 500", "s")
    assert {e.effective_date for e in ev} == {date(2025, 9, 30)}
    removes = [e.symbol for e in ev if e.action == "REMOVE"]
    adds = [e.symbol for e in ev if e.action == "ADD"]
    assert len(removes) == len(adds) == 18
    assert removes[:3] == ["ALIVUS", "GNFC", "GPPL"] and "AKZOINDIA" in adds


def test_lettered_section_and_wrapped_effective_date():
    ev = parse_change_notice(notice("21022025"), "Nifty 500", "s")  # "b) Nifty 500"
    assert ev and {e.effective_date for e in ev} == {date(2025, 3, 28)}
    ev = parse_change_notice(notice("10102024"), "Nifty 500", "s")  # "effective from October\n16, 2024"
    assert [(e.action, e.symbol, e.effective_date) for e in ev] == [
        ("REMOVE", "TV18BRDCST", date(2024, 10, 16)),
        ("ADD", "AKUMS", date(2024, 10, 16)),
    ]


def test_prose_dummy_notice_yields_no_regular_events():
    """[IDX5] DUMMYTATAM: included 2025-10-14, excluded 2025-11-17; prose only -> manual rows."""
    assert parse_change_notice(notice("13112025"), "Nifty 500", "s") == []


def test_unbalanced_or_undated_tables_are_errors():
    text = notice("10102024")
    with pytest.raises(ParseError, match="unbalanced"):
        parse_change_notice(
            text.replace("Akums Drugs and Pharmaceuticals Ltd.                 AKUMS", ""), "Nifty 500", "s"
        )
    with pytest.raises(ParseError, match="effective date"):
        parse_change_notice(text.replace("effective from", "effective on"), "Nifty 500", "s")


def test_committed_manifest_equals_extraction_from_evidence():
    assert MANIFEST.read_text(encoding="utf-8") == write_manifest(all_events())
    assert len(read_manifest(MANIFEST.read_text(encoding="utf-8"))) == 228


# ── real-data walk: today's list back to 2024-10-01 ────────────────────────


def _bhav(day: str) -> list[dict]:
    with zipfile.ZipFile(BHAV_DIR / f"BhavCopy_NSE_CM_0_0_0_{day}_F_0000.csv.zip") as z:
        return [
            r for r in csv.DictReader(io.TextIOWrapper(z.open(z.namelist()[0]))) if r["SctySrs"] in ("EQ", "BE", "BZ")
        ]


@pytest.fixture(scope="module")
def walk():
    """Keys are 2026 symbols; older symbols map through FinInstrmId (AKZOINDIA -> JSWDULUX) [IDX6]."""
    old = {r["FinInstrmId"]: r["TckrSymb"] for r in _bhav("20251014")}
    new = {r["FinInstrmId"]: r["TckrSymb"] for r in _bhav("20261112")}
    renamed = {old[k]: new[k] for k in old if k in new and old[k] != new[k]}
    current = [r["Symbol"] for r in csv.DictReader(NIFTY500.open()) if r["ISIN Code"].startswith("IN")]
    intervals, steps = reconstruct_backward(
        current, AS_OF, all_events(), START, lambda s, d: renamed.get(s, s), expected_count=500
    )
    return intervals, steps, renamed


def members_on(intervals, d):
    return {iv.key for iv in intervals if iv.valid_from <= d and (iv.valid_to is None or iv.valid_to > d)}


def test_real_walk_keeps_500_on_every_step(walk):
    intervals, steps, renamed = walk
    assert renamed["AKZOINDIA"] == "JSWDULUX"
    assert len(steps) == 12
    assert all(s.members_on_or_after == s.members_before == 500 for s in steps)
    # Membership is constant between event dates, so checking each step checks every trading day.
    boundaries = sorted({START, *(s.effective_date for s in steps)})
    for d in boundaries:
        for probe in (d, d + timedelta(days=1)):
            assert len(members_on(intervals, probe)) == 500, probe
        assert len(members_on(intervals, d - timedelta(days=1))) in (0, 500)


def test_pre_and_post_rebalance_membership(walk):
    intervals, _, _ = walk
    e = date(2025, 9, 30)
    before, after = members_on(intervals, e - timedelta(days=1)), members_on(intervals, e)
    assert "ALIVUS" in before and "ALIVUS" not in after  # excluded w.e.f. 2025-09-30
    assert "ABLBL" not in before and "ABLBL" in after  # included
    assert "JSWDULUX" in after and "JSWDULUX" not in before  # Akzo Nobel added as AKZOINDIA
    e2 = date(2024, 10, 16)
    assert "TV18BRDCST" in members_on(intervals, e2 - timedelta(days=1))
    assert "AKUMS" in members_on(intervals, e2)


def test_missing_event_breaks_consistency():
    current = ["A", "B", "C"]
    events = [IndexEvent(date(2025, 9, 30), "ADD", "D"), IndexEvent(date(2025, 9, 30), "REMOVE", "C")]
    with pytest.raises(IndexInvariantError, match="ADD D is not a member") as e:
        reconstruct_backward(current, AS_OF, events, START, lambda s, d: s, expected_count=3)
    assert e.value.effective_date == date(2025, 9, 30)


def test_unbalanced_step_breaks_count():
    events = [IndexEvent(date(2025, 9, 30), "ADD", "C")]
    with pytest.raises(IndexInvariantError, match="expected 3"):
        reconstruct_backward(["A", "B", "C"], AS_OF, events, START, lambda s, d: s, expected_count=3)


def test_temporary_member_allows_count_above_expected():
    """A listed spin-off held between dummy inclusion and exclusion (e.g. TMCV in Nov 2025)."""
    events = [IndexEvent(date(2025, 11, 17), "REMOVE", "SPIN", "TEMPORARY"),
              IndexEvent(date(2025, 10, 14), "ADD", "SPIN", "TEMPORARY")]  # fmt: skip
    intervals, steps = reconstruct_backward(["A", "B"], AS_OF, events, START, lambda s, d: s, expected_count=2)
    assert [s.members_before for s in steps] == [3, 2]
    (spin,) = [iv for iv in intervals if iv.key == "SPIN"]
    assert (spin.valid_from, spin.valid_to) == (date(2025, 10, 14), date(2025, 11, 17))


# ── database backfill ─────────────────────────────────────────────────────


@pytest.fixture
def toy_db():
    """Three-member toy index with identifier history covering the event dates."""
    con = connect()
    apply_schema(con)
    insert_rows(con, "entity_master", [{"entity_id": f"e{x}", "legal_name": x} for x in "ABCD"])
    insert_rows(con, "securities", [{"security_id": f"s{x}", "entity_id": f"e{x}", "share_class": "COMMON"}
                                    for x in "ABCD"])  # fmt: skip
    rows = [{"security_id": f"s{x}", "exchange": "NSE", "fin_instrm_id": x, "symbol": x, "series": "EQ",
             "isin": f"INE{x}", "valid_from": date(2024, 1, 1), "valid_to": None} for x in "ABD"]  # fmt: skip
    rows += [  # C was called OLDC until 2025-06-01
        {"security_id": "sC", "exchange": "NSE", "fin_instrm_id": "C", "symbol": "OLDC", "series": "EQ",
         "isin": "INEC", "valid_from": date(2024, 1, 1), "valid_to": date(2025, 6, 1)},
        {"security_id": "sC", "exchange": "NSE", "fin_instrm_id": "C", "symbol": "C", "series": "EQ",
         "isin": "INEC", "valid_from": date(2025, 6, 1), "valid_to": None},
    ]  # fmt: skip
    insert_rows(con, "security_identifier_history", rows)
    insert_rows(con, "index_constituents_history", [
        {"index_name": "TOY", "security_id": s, "valid_from": date(2026, 11, 12), "valid_to": None,
         "source": "SNAPSHOT"}
        for s in ("sA", "sB", "sC")
    ])  # fmt: skip
    return con


def test_backfill_writes_intervals_and_pit_queries(toy_db):
    from financials.admin import backfill_index
    from financials.promoter import index_members

    events = [IndexEvent(date(2025, 3, 28), "ADD", "OLDC"), IndexEvent(date(2025, 3, 28), "REMOVE", "D")]
    r = backfill_index(toy_db, "TOY", events, expected_count=3)
    assert r["first_snapshot"] == date(2026, 11, 12)
    assert index_members(toy_db, "TOY", date(2025, 3, 27)) == ["sA", "sB", "sD"]
    assert index_members(toy_db, "TOY", date(2025, 3, 28)) == ["sA", "sB", "sC"]
    assert index_members(toy_db, "TOY", date(2024, 10, 1)) == ["sA", "sB", "sD"]  # no survivorship error now
    assert index_members(toy_db, "TOY", date(2026, 11, 12)) == ["sA", "sB", "sC"]
    again = backfill_index(toy_db, "TOY", events, expected_count=3)  # idempotent rebuild
    assert again["rows"] == r["rows"]


def test_backfill_aborts_atomically_on_unresolvable_symbol(toy_db):
    from financials.admin import backfill_index

    events = [IndexEvent(date(2025, 3, 28), "ADD", "C"), IndexEvent(date(2025, 3, 28), "REMOVE", "NOSUCH")]
    with pytest.raises(IndexInvariantError, match="cannot resolve"):
        backfill_index(toy_db, "TOY", events, expected_count=3)
    n = toy_db.execute("SELECT count(*) FROM index_constituents_history WHERE source = 'MANUAL_BACKFILL'")
    assert n.fetchone()[0] == 0


def test_backfill_on_fixture_market_needs_price_history(full_market):
    """[IDX8] The snapshot resolves 497 equity constituents; the other 3 are REITs (series RR: BAGMANE, BIRET,
    EMBASSY), counted as members outside the equity universe, so the walk starts at 500. On the six fixture days it
    then stops at the first symbol with no price history in the database (the live backfill resolves them all)."""
    from financials.admin import backfill_index

    with pytest.raises(IndexInvariantError, match="2026-09-30: cannot resolve BHARATCOAL"):
        backfill_index(full_market.con, "NIFTY 500", read_manifest(MANIFEST.read_text(encoding="utf-8")))
    n = full_market.con.execute("SELECT count(*) FROM index_constituents_history WHERE source = 'MANUAL_BACKFILL'")
    assert n.fetchone()[0] == 0
