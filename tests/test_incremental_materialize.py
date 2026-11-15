"""Incremental materialisation (architecture §11.10): dirty markers written by the single writers, `materialize
--incremental` recomputing only the marked entities' rows, and equivalence with a from-scratch full run.

One base database (six real bhavcopy days, holidays, the Nifty 500 snapshot, one results filing) is built and fully
materialised once; every test works on its own copy. Each scenario then changes one input the way production does
(promote a real fixture filing, a corporate-action batch, a quarantine resolution, an override), runs the
incremental path and compares screener_features_history row for row, column for column, with a full rebuild of the
same database state.
"""

from __future__ import annotations

import hashlib
import io
import shutil
from datetime import date, datetime

import pytest
from conftest import FETCHED_AT, Market

from _fixture_helpers import CORP, FIXTURES, XBRL_DIR
from financials import dirty, features
from financials.cli import main, materialize_dates
from financials.features import FEATURES_VERSION, materialize, materialize_incremental
from financials.promoter import promote
from financials.sources import ROOT
from financials.staging import (
    stage_corp_actions,
    stage_holidays,
    stage_index_snapshot,
    stage_results_xbrl,
    stage_shareholding,
)

ARCHIVE = "https://nsearchives.nseindia.com/corporate/xbrl/"
DAYS = ("20250919", "20250922", "20250923", "20251013")
RESULTS_Q1 = "INTEGRATED_FILING_INDAS_1489565_21072025071304_WEB.xml"  # filed Jul 2025; made visible 20 Sep below
SHP_Q1 = "SHP_1489727_21072025081003_WEB.xml"
CA = FIXTURES / "corp_actions" / "nse_corporateActions_equities_15-09-2025_17-10-2025.json"


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    """Database file of the fully materialised base state (closed, so tests can copy it)."""
    root = tmp_path_factory.mktemp("incr_base")
    m = Market(root)
    for d in DAYS:
        assert promote(m.con, m.stage_day(d)).status == "PROMOTED"
    assert promote(m.con, m.stage_day("20251014", with_delivery=True)).status == "PROMOTED"
    assert promote(m.con, m.stage_day("20261112", with_delivery=True)).status == "PROMOTED"
    hol = FIXTURES / "calendar" / "nse_holiday-master_trading_20261113.json"
    promote(m.con, stage_holidays(m.vault, m.stage_root, data=hol.read_bytes(), source_url="nse-hol",
                                  fetched_at=FETCHED_AT))  # fmt: skip
    idx = FIXTURES / "indices" / "ind_nifty500list_20261113.csv"
    promote(m.con, stage_index_snapshot(m.vault, m.stage_root, data=idx.read_bytes(), source_url="nse-idx",
                                        index_name="NIFTY 500", snapshot_date=date(2026, 11, 12),
                                        fetched_at=FETCHED_AT))  # fmt: skip
    promote(m.con, stage_results_xbrl(m.vault, m.stage_root, data=CORP.read_bytes(), source_url="nse-xbrl-corp",
                                      fetched_at=FETCHED_AT))  # fmt: skip
    out = io.StringIO()
    assert materialize_dates(m.con, None, date(2024, 10, 1), None, out) == 0, out.getvalue()
    # A full run over every materialised day consumes every marker the promotions wrote.
    assert m.con.execute("SELECT count(*) FROM materialize_dirty").fetchone()[0] == 0
    m.con.close()
    return root / "market.duckdb"


@pytest.fixture
def db(base, tmp_path):
    shutil.copy(base, tmp_path / "market.duckdb")
    m = Market(tmp_path)
    yield m
    m.con.close()


def history(con) -> list[tuple]:
    return con.execute("SELECT * FROM screener_features_history ORDER BY as_of_date, security_id").fetchall()


def days(con) -> list[date]:
    return [
        d for (d,) in con.execute("SELECT DISTINCT as_of_date FROM screener_features_history ORDER BY 1").fetchall()
    ]


def full_rebuild(con) -> list[tuple]:
    """From scratch: drop every materialised row, then materialise each day again in order."""
    ds = days(con)
    con.execute("DELETE FROM screener_features_history")
    con.execute("DELETE FROM features_meta")
    for d in ds:
        assert materialize(con, d).status == "PROMOTED", d
    return history(con)


def entity_of(con, symbol: str) -> str:
    return con.execute(
        "SELECT DISTINCT s.entity_id FROM security_identifier_history h JOIN securities s USING (security_id) "
        "WHERE h.symbol = ?",
        [symbol],
    ).fetchone()[0]


def _results(m: Market) -> set[str]:
    st = stage_results_xbrl(m.vault, m.stage_root, data=(XBRL_DIR / RESULTS_Q1).read_bytes(),
                            source_url=ARCHIVE + RESULTS_Q1, fetched_at=FETCHED_AT,
                            broadcast_ts=datetime(2025, 9, 20, 6, 0), broadcast_ts_source="API_FIELD")  # fmt: skip
    r = promote(m.con, st)
    assert r.status == "PROMOTED", r
    return {m.con.execute("SELECT entity_id FROM filing_meta WHERE filing_id = ?", [r.message]).fetchone()[0]}


def _shareholding(m: Market) -> set[str]:
    st = stage_shareholding(m.vault, m.stage_root, data=(XBRL_DIR / SHP_Q1).read_bytes(), source_url=ARCHIVE + SHP_Q1,
                            fetched_at=FETCHED_AT, broadcast_ts=datetime(2025, 9, 21, 6, 0),
                            broadcast_ts_source="API_FIELD")  # fmt: skip
    r = promote(m.con, st)
    assert r.status == "PROMOTED", r
    return {m.con.execute("SELECT entity_id FROM shareholding_meta WHERE filing_id = ?", [r.message]).fetchone()[0]}


def _corp_actions(m: Market) -> set[str]:
    st = stage_corp_actions(m.vault, m.stage_root, data=CA.read_bytes(), source_url="nse-ca", fetched_at=FETCHED_AT)
    assert promote(m.con, st).status == "PROMOTED"
    return {entity_of(m.con, "ADANIPOWER")}  # 1:5 split ex 2025-09-22, verified once its bars exist [CA2]


def _gap_accepted(m: Market) -> set[str]:
    from financials.admin import resolve_quarantine

    qid, sec = m.con.execute(
        "SELECT quarantine_id, security_id FROM quarantine_queue WHERE stage = 'GAP' AND resolved_at IS NULL "
        "AND reason_code = 'UNEXPLAINED_GAP' AND json_extract_string(details, '$.trade_date') = '2025-09-23' "
        "ORDER BY quarantine_id LIMIT 1"
    ).fetchone()
    resolve_quarantine(m.con, qid, action="ACCEPT", note="test: a real move")
    return {m.con.execute("SELECT entity_id FROM securities WHERE security_id = ?", [sec]).fetchone()[0]}


def _scope_override(m: Market) -> set[str]:
    from financials.admin import set_scope_override

    ent, filed = m.con.execute("SELECT DISTINCT entity_id, scope FROM filing_meta").fetchone()
    other = "STANDALONE" if filed == "CONSOLIDATED" else "CONSOLIDATED"  # pinned to a scope it never filed
    set_scope_override(m.con, ent, quarterly=other, annual=other, reason="test")
    return {ent}


# (change, first dirty date of its entity, whether stored rows change). Price factors and gap freezes reach
# momentum (needs >= 21 bars; the fixtures hold 6 days), the share count of an issuer with a filed count and, since
# features 2026.11.15-3, dividend_yield_pct: the corporate-actions batch brings accepted dividends (0 -> a yield) and
# an accepted gap unfreezes the yield (NULL -> 0), so both scenarios now change stored rows, only in that column.
SCENARIOS = {
    "results": (_results, date(2025, 9, 20), True),
    "shareholding": (_shareholding, date(2025, 9, 21), True),
    "corp_action": (_corp_actions, date(2025, 9, 22), True),
    "gap_resolution": (_gap_accepted, date(2025, 9, 23), True),
    "scope_override": (_scope_override, date(2024, 10, 1), True),
}


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_incremental_equals_full_rebuild(db, name, monkeypatch):
    change, first_dirty, visible = SCENARIOS[name]
    con = db.con
    before = history(con)
    expected_entities = change(db)
    marks = {(e, d) for e, d in con.execute("SELECT entity_id, from_date FROM materialize_dirty").fetchall()}
    assert {e for e, _ in marks} >= expected_entities
    assert min(d for e, d in marks if e in expected_entities) == first_dirty

    seen: list[set[str]] = []
    real_rows = features._rows

    def spy(con_, as_of, as_of_ts, universe, *rest):
        seen.append({u[1] for u in universe})
        return real_rows(con_, as_of, as_of_ts, universe, *rest)

    monkeypatch.setattr(features, "_rows", spy)
    r = materialize_incremental(con)
    monkeypatch.undo()
    assert r.status == "DONE", r
    dirty_entities = {e for e, _ in marks}
    # only marked entities' rows are computed, at most one batched compute per affected materialised day
    assert 1 <= len(seen) <= len([d for d in days(con) if d >= min(d for _, d in marks)])
    assert set().union(*seen) <= dirty_entities and expected_entities <= set().union(*seen)
    assert con.execute("SELECT count(*) FROM materialize_dirty").fetchone()[0] == 0
    assert {m for (m,) in con.execute("SELECT DISTINCT mode FROM features_meta").fetchall()} >= {"INCREMENTAL"}

    incremental = history(con)
    assert (incremental != before) == visible
    assert incremental == full_rebuild(con)


def test_rows_of_untouched_entities_and_days_are_not_rewritten(db):
    """Rows of other entities, and every day before the first dirty date, are left exactly as stored."""
    con = db.con
    for t in ("screener_features_history", "screener_features"):
        con.execute(f"ALTER TABLE {t} ADD COLUMN probe INTEGER DEFAULT 1")
    ent = _results(db)
    assert materialize_incremental(con).status == "DONE"
    rewritten = con.execute(
        "SELECT DISTINCT entity_id, as_of_date FROM screener_features_history WHERE probe IS NULL"
    ).fetchall()
    assert {e for e, _ in rewritten} == ent
    assert min(d for _, d in rewritten) == date(2025, 9, 22)  # first materialised day >= 20 Sep


def test_writers_mark_what_they_change(db, tmp_path):
    con = db.con
    _results(db)
    _shareholding(db)
    reasons = dict(con.execute("SELECT reason, count(*) FROM materialize_dirty GROUP BY 1").fetchall())
    assert reasons == {"RESULTS": 1, "SHAREHOLDING": 1}
    # a replayed promotion inserts no marker twice (deterministic ids)
    _corp_actions(db)
    n = con.execute("SELECT count(*) FROM materialize_dirty").fetchone()[0]
    st = stage_corp_actions(db.vault, db.stage_root, data=CA.read_bytes(), source_url="nse-ca", fetched_at=FETCHED_AT)
    promote(con, st)
    assert con.execute("SELECT count(*) FROM materialize_dirty").fetchone()[0] == n
    # a promoted market day marks every entity from its date (FULL); a late delivery file marks its bars' entities
    (tmp_path / "fresh").mkdir()
    fresh = Market(tmp_path / "fresh")
    try:
        promote(fresh.con, fresh.stage_day("20251014"))
        assert (
            fresh.con.execute(
                "SELECT count(*) FROM materialize_dirty WHERE entity_id = ? AND from_date = '2025-10-14'", [dirty.FULL]
            ).fetchone()[0]
            == 1
        )
        fresh.con.execute("DELETE FROM materialize_dirty")
        assert promote(fresh.con, fresh.stage_day("20251014", with_delivery=True)).status == "PROMOTED"
        assert fresh.con.execute(
            "SELECT reason, min(from_date), count(*) > 1000 FROM materialize_dirty GROUP BY 1"
        ).fetchall() == [("DELIVERY", date(2025, 10, 14), True)]
    finally:
        fresh.con.close()


def test_to_bound_moves_markers_forward(db):
    con = db.con
    (ent,) = _results(db)
    r = materialize_incremental(con, to=date(2025, 9, 23))
    assert r.status == "DONE" and [d.as_of_date for d in r.days] == [date(2025, 9, 22), date(2025, 9, 23)]
    assert con.execute("SELECT entity_id, from_date FROM materialize_dirty").fetchall() == [(ent, date(2025, 9, 24))]
    assert materialize_incremental(con).status == "DONE"
    assert con.execute("SELECT count(*) FROM materialize_dirty").fetchone()[0] == 0
    assert history(con) == full_rebuild(con)


def test_version_mismatch_refuses_and_changes_nothing(db):
    con = db.con
    _results(db)
    con.execute("UPDATE features_meta SET features_version = 'old' WHERE as_of_date = '2025-09-19'")
    before = history(con)
    r = materialize_incremental(con)
    assert r.status == "REFUSED" and "full" in r.message and FEATURES_VERSION in r.message
    assert history(con) == before
    assert con.execute("SELECT count(*) FROM materialize_dirty").fetchone()[0] == 1
    db.con.close()
    out = io.StringIO()
    assert main(["--data-dir", str(db.stage_root.parent), "materialize", "--incremental"], out=out) == 1
    assert "REFUSED" in out.getvalue()
    db.con = Market(db.stage_root.parent).con
    # a day built before features_meta existed counts as another version too
    db.con.execute("DELETE FROM features_meta WHERE as_of_date = '2025-09-19'")
    db.con.execute("UPDATE features_meta SET features_version = ?", [FEATURES_VERSION])
    assert materialize_incremental(db.con).status == "REFUSED"


def test_gate_failure_leaves_the_day_unchanged_and_keeps_markers(db, monkeypatch):
    con = db.con
    q = "SELECT DISTINCT entity_id FROM screener_features_history WHERE as_of_date = '2025-10-13'"
    ents = {e for (e,) in con.execute(q).fetchall()}
    dirty.mark_entities(con, ents, date(2025, 10, 13), "TEST")
    before = history(con)
    real_rows = features._rows

    def no_close(*args):
        return [{**r, "close": None} for r in real_rows(*args)]

    monkeypatch.setattr(features, "_rows", no_close)  # every recomputed close turns NULL: a G4 null spike
    r = materialize_incremental(con)
    assert r.status == "ABORTED" and r.days[-1].gate == "G4" and r.days[-1].as_of_date == date(2025, 10, 13)
    assert history(con) == before
    assert con.execute("SELECT count(*) FROM materialize_dirty").fetchone()[0] == len(ents)

    monkeypatch.setattr(features, "_rows", lambda *args: real_rows(*args)[1:])  # one row short: G5
    r = materialize_incremental(con)
    assert r.status == "ABORTED" and r.days[-1].gate == "G5"
    assert history(con) == before
    monkeypatch.undo()
    assert materialize_incremental(con).status == "DONE"  # the rerun resumes from the kept markers
    assert history(con) == before  # nothing actually changed for these entities


def test_full_range_run_consumes_markers_it_covers(db):
    con = db.con
    (ent,) = _results(db)
    out = io.StringIO()
    assert materialize_dates(con, None, date(2025, 10, 13), None, out) == 0  # does not cover 22-23 Sep
    assert con.execute("SELECT entity_id, from_date FROM materialize_dirty").fetchall() == [(ent, date(2025, 9, 20))]
    # from 22 Sep: the marker (Saturday 20 Sep) has no stale day before it (last earlier materialised day: 19 Sep)
    assert materialize_dates(con, None, date(2025, 9, 22), None, out) == 0
    assert con.execute("SELECT count(*) FROM materialize_dirty").fetchone()[0] == 0
    assert history(con) == full_rebuild(con)


# ── reader version pin ───────────────────────────────────────────────────────

# Files whose text decides feature values. Changing any of them changes this hash: bump features.FEATURES_VERSION
# (so `materialize --incremental` refuses days built by the old rules) and update both values here together.
PINNED_SOURCES = (
    "src/financials/features.py",
    "src/financials/features_price.py",
    "src/financials/fundamentals.py",
    "src/financials/scope.py",
    "src/financials/money.py",
    "reference/valuation_archetypes.csv",
)
PINNED = ("2026.11.15-4B", "32496d936338dbd6bab5ad4e1ceb6bc83f22d68062436dd9b64850bfd117917e")


def sources_sha256() -> str:
    h = hashlib.sha256()
    for rel in PINNED_SOURCES:
        h.update(rel.encode() + b"\0" + (ROOT / rel).read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return h.hexdigest()


def test_reader_sources_change_only_with_a_version_bump():
    assert (FEATURES_VERSION, sources_sha256()) == PINNED, (
        "features.py / fundamentals.py / a pinned reader file changed: bump FEATURES_VERSION in features.py and "
        f"set PINNED = ({FEATURES_VERSION!r}, {sources_sha256()!r}) in this test"
    )
