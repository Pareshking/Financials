"""Storage maintenance (architecture §4.1): the live table written once per run, `compact`, `prune-versions`.

The fixture market (every real fixture through the real pipeline, plus Cummins' quarterly results and annual
report for segments, related-party and group-structure rows) is built once. `prune-versions` is checked against
superseded versions injected the way a re-parse leaves them (a copy of every row at an older parser version, with
different values so a wrong pick would show), plus the rows no reader may lose: an old anchor period the current
version lacks, an old shareholding version visible earlier (X83) and a version a quarantine finding names.
"""

from __future__ import annotations

import io
import json
import os
import shutil
from datetime import date, datetime

import pyarrow.parquet as pq
import pytest
from conftest import FETCHED_AT, build_full_market

from _fixture_helpers import XBRL_DIR
from financials import features, features_store, storage
from financials.cli import main, materialize_dates
from financials.db import connect
from financials.promoter import promote
from financials.staging import stage_results_xbrl
from financials.statements.segments import segment_facts

ARCHIVE = "https://nsearchives.nseindia.com/corporate/xbrl/"
CUMMINS_AR = "AR_XBRL_CUMMINSIND_04092026113534.xml"
CUMMINS_Q = "INTEGRATED_FILING_INDAS_1753292_04112026105837_WEB.xml"
OLD, EARLY = "0.0.1", "0.0.2"
TABLES = {
    "screener_features_history": "as_of_date, security_id",
    "screener_features": "security_id",
    "market_breadth": "as_of_date, universe",
    "features_meta": "as_of_date",
}


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    root = tmp_path_factory.mktemp("storage_base")
    m = build_full_market(root)
    for name, ts in ((CUMMINS_AR, datetime(2026, 9, 4, 6, 5)), (CUMMINS_Q, datetime(2026, 11, 4, 5, 28))):
        r = promote(m.con, stage_results_xbrl(m.vault, m.stage_root, data=(XBRL_DIR / name).read_bytes(),
                                              source_url=ARCHIVE + name, fetched_at=FETCHED_AT, broadcast_ts=ts,
                                              broadcast_ts_source="API_FIELD"))  # fmt: skip
        assert r.status == "PROMOTED", r
    m.con.close()
    return root


@pytest.fixture(autouse=True)
def _free_disk(tmp_path):
    """Each test copies the database: remove the copies afterwards (the suite runs on small disks too)."""
    yield
    shutil.rmtree(tmp_path, ignore_errors=True)


def _copy(base, tmp_path):
    for p in base.iterdir():
        if p.is_file():
            shutil.copy(p, tmp_path / p.name)
    return tmp_path / "market.duckdb"


def _tables(con) -> dict:
    out = {}
    for t, order in TABLES.items():
        exclude = " EXCLUDE (materialized_at)" if t == "features_meta" else ""
        out[t] = con.execute(f"SELECT *{exclude} FROM {t} ORDER BY {order}").fetchall()
    return out


def _days(con) -> list[date]:
    return [d for (d,) in con.execute("SELECT DISTINCT trade_date FROM ohlcv ORDER BY 1").fetchall()]


# ── 1. the live table once per run ──────────────────────────────────────────


def _count_snapshots(monkeypatch) -> list[int]:
    calls = []
    real = features._write_snapshot

    def spy(con):
        calls.append(1)
        real(con)

    monkeypatch.setattr(features, "_write_snapshot", spy)
    return calls


def test_run_writes_the_live_table_once_with_identical_tables(base, tmp_path, monkeypatch):
    path = _copy(base, tmp_path)
    con = connect(path)
    days = _days(con)
    assert len(days) >= 5
    shutil.copy(path, tmp_path / "day_by_day.duckdb")
    calls = _count_snapshots(monkeypatch)
    assert materialize_dates(con, None, days[0], None, io.StringIO()) == 0
    assert len(calls) == 1  # was one per day
    run = _tables(con)
    con.close()
    old = connect(tmp_path / "day_by_day.duckdb")
    calls.clear()
    for d in days:  # the previous behaviour: every day rewrites the live table
        assert features.materialize(old, d).status == "PROMOTED"
    assert len(calls) == len(days)
    assert _tables(old) == run
    assert run["screener_features"] and run["screener_features"][0][0] == max(days)
    old.close()


def test_a_run_that_stops_early_leaves_the_live_table_of_the_last_published_day(base, tmp_path, monkeypatch):
    path = _copy(base, tmp_path)
    con = connect(path)
    days = _days(con)
    real = features.compute_rows

    def no_close_on_last(con_, as_of, *a, **k):
        rows = real(con_, as_of, *a, **k)
        if as_of == days[-1]:
            for r in rows:
                r["close"] = None  # G4 fails on the last day
        return rows

    monkeypatch.setattr(features, "compute_rows", no_close_on_last)
    out = io.StringIO()
    assert materialize_dates(con, None, days[0], None, out) == 1
    assert "ABORTED" in out.getvalue() and "G4" in out.getvalue()
    live = {d for (d,) in con.execute("SELECT DISTINCT as_of_date FROM screener_features").fetchall()}
    assert live == {days[-2]}
    assert con.execute("SELECT count(*) FROM screener_features").fetchone()[0] == con.execute(
        "SELECT count(*) FROM screener_features_history WHERE as_of_date = ?", [days[-2]]).fetchone()[0]  # fmt: skip
    con.close()


# ── 2. compact ───────────────────────────────────────────────────────────────


def _everything(con) -> dict:
    out = {}
    for t in storage.user_tables(con):
        cols = [c for (c,) in con.execute(
            "SELECT column_name FROM duckdb_columns() WHERE table_name = ? AND database_name = current_database() "
            "ORDER BY column_name", [t]).fetchall()]  # fmt: skip
        out[t] = sorted(map(repr, con.execute(f"SELECT {', '.join(cols)} FROM {t}").fetchall()))
    return out


@pytest.mark.parametrize("keep_old", [False, True])
def test_compact_shrinks_the_file_and_keeps_every_row(base, tmp_path, keep_old):
    path = _copy(base, tmp_path)
    con = connect(path)
    days = _days(con)
    for _ in range(3):  # every re-materialisation leaves the previous copies behind as dead blocks
        assert materialize_dates(con, None, days[0], None, io.StringIO()) == 0
    con.execute("CHECKPOINT")
    before = _everything(con)
    views = storage.user_views(con)
    con.close()
    size = os.path.getsize(path)
    args = ["--data-dir", str(tmp_path), "compact"] + (["--keep-old"] if keep_old else [])
    out = io.StringIO()
    assert main(args, out=out) == 0, out.getvalue()
    assert "COMPACTED" in out.getvalue()
    assert os.path.getsize(path) < size
    assert (tmp_path / "market.duckdb.bak").exists() == keep_old
    assert not (tmp_path / "market.duckdb.compact").exists()
    con = connect(path, read_only=True)
    assert _everything(con) == before
    assert storage.user_views(con) == views and "capital_allocation_scorecard" in views
    assert (
        con.execute(
            "SELECT count(*) FROM duckdb_constraints() WHERE constraint_type = 'FOREIGN KEY' AND "
            "database_name = current_database()"
        ).fetchone()[0]
        > 0
    )  # constraints from schema.sql
    con.close()


def test_compact_refuses_without_free_disk_and_changes_nothing(base, tmp_path):
    path = _copy(base, tmp_path)
    data = path.read_bytes()
    r = storage.compact(path, free_bytes=1024)
    assert r.status == "REFUSED" and "free disk" in r.message and "1.1 x live size" in r.message
    assert path.read_bytes() == data and not (tmp_path / "market.duckdb.compact").exists()


def test_compact_refuses_while_another_process_holds_the_file(base, tmp_path):
    import subprocess
    import sys

    path = _copy(base, tmp_path)
    holder = connect(path)  # this process is the writer
    try:
        code = "import sys; from financials.storage import compact; print(compact(sys.argv[1]).status)"
        env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
        got = subprocess.run([sys.executable, "-c", code, str(path)], env=env, capture_output=True, text=True)
        assert got.stdout.strip() == "REFUSED", got.stderr
    finally:
        holder.close()
    assert not (tmp_path / "market.duckdb.compact").exists() and not (tmp_path / "market.duckdb.bak").exists()


def test_full_runs_compact_automatically_when_there_is_dead_space(base, tmp_path, monkeypatch):
    path = _copy(base, tmp_path)
    con = connect(path)
    days = _days(con)
    con.close()
    monkeypatch.setattr(storage, "AUTO_COMPACT_MIN_BYTES", 0)
    out = io.StringIO()
    assert main(["--data-dir", str(tmp_path), "materialize", "--from", str(days[0])], out=out) == 0
    assert "compact: COMPACTED" in out.getvalue()
    monkeypatch.setattr(storage, "FREE_DISK_FACTOR", 1e9)
    out = io.StringIO()
    assert main(["--data-dir", str(tmp_path), "materialize", "--from", str(days[0])], out=out) == 0
    assert "compact: REFUSED" in out.getvalue() and f"--data-dir {tmp_path} compact" in out.getvalue()
    out = io.StringIO()
    assert main(["--data-dir", str(tmp_path), "materialize", "--from", str(days[0]), "--no-compact"], out=out) == 0
    assert "compact:" not in out.getvalue()


# ── 3. prune-versions ───────────────────────────────────────────────────────


def _inject_versions(con, edges: bool = True) -> dict[str, str]:
    """Superseded versions as re-parses leave them, plus (`edges`) rows a reader can still select. Returns the
    filing ids of those."""
    for t in ("filing_meta", "shareholding_meta", *[r.table for r in storage.PRUNE_RULES]):
        cols = [c for (c,) in con.execute(
            "SELECT column_name FROM duckdb_columns() WHERE table_name = ? AND database_name = current_database() "
            "ORDER BY column_index", [t]).fetchall()]  # fmt: skip
        changed = {"parser_version": f"'{OLD}'", "value_inr": "value_inr * 2", "pct": "pct * 2",
                   "shares": "shares * 2", "amount_inr": "amount_inr * 2", "value": "value"}  # fmt: skip
        select = ", ".join(changed.get(c, c) if t not in ("filing_meta", "shareholding_meta") or c == "parser_version"
                           else c for c in cols)  # fmt: skip
        n = con.execute(f"INSERT INTO {t} SELECT {select} FROM {t} RETURNING 1").fetchall()
        assert n, t
    if not edges:
        return {}
    return _inject_edges(con)


def _inject_edges(con) -> dict[str, str]:
    # An old anchor period ('pat', 3 months) the current version does not file: the scope decision groups every
    # version, so it must stay.
    anchor = con.execute("SELECT filing_id FROM fact_observations WHERE parser_version = ? AND canonical_tag = 'pat' "
                         "AND period_type = 'DURATION' AND period_months = 3 ORDER BY filing_id LIMIT 1",
                         [OLD]).fetchone()[0]  # fmt: skip
    con.execute("INSERT INTO fact_observations SELECT * REPLACE (DATE '2023-12-31' AS period_end) "
                "FROM fact_observations WHERE filing_id = ? AND parser_version = ? AND canonical_tag = 'pat' "
                "AND period_type = 'DURATION' AND period_months = 3 LIMIT 1", [anchor, OLD])  # fmt: skip
    # A shareholding version visible a day earlier than the current one (X83): selectable in between.
    shp = con.execute("SELECT filing_id FROM shareholding_meta ORDER BY filing_id LIMIT 1").fetchone()[0]
    for t in ("shareholding_meta", "shareholding_observations", "shareholding_line_items",
              "shareholding_major_holders"):  # fmt: skip
        cols = [c for (c,) in con.execute(
            "SELECT column_name FROM duckdb_columns() WHERE table_name = ? AND database_name = current_database() "
            "ORDER BY column_index", [t]).fetchall()]  # fmt: skip
        sel = ", ".join(f"'{EARLY}'" if c == "parser_version" else
                        "visible_from_ts - INTERVAL 1 DAY" if c == "visible_from_ts" else c for c in cols)  # fmt: skip
        con.execute(f"INSERT INTO {t} SELECT {sel} FROM {t} WHERE filing_id = ? AND parser_version = ?", [shp, OLD])
    # A quarantine finding naming the old version of the results filing.
    named = con.execute("SELECT filing_id FROM filing_meta WHERE accounting_profile <> 'REG34_ANNUAL' "
                        "ORDER BY filing_id LIMIT 1").fetchone()[0]  # fmt: skip
    con.execute("INSERT INTO quarantine_queue VALUES ('q-test', 'PARSE', 'TEST', NULL, NULL, ?, ?, ?, ?, 'X', 'n')",
                [named, json.dumps({"parser_version": OLD}), FETCHED_AT, FETCHED_AT])  # fmt: skip
    return {"anchor": anchor, "shp": shp, "named": named}


def _materialise_all(con) -> dict:
    features_store.truncate(con)
    con.execute("DELETE FROM features_meta")
    con.execute("DELETE FROM market_breadth")
    assert materialize_dates(con, None, date(2024, 10, 1), None, io.StringIO()) == 0
    return _tables(con)


def _segments(con) -> list:
    ent = con.execute("SELECT DISTINCT entity_id FROM segment_observations ORDER BY 1").fetchall()
    return [segment_facts(con, e, datetime(2026, 11, 13)) for (e,) in ent]


def test_prune_keeps_every_reader_identical_and_the_archive_round_trips(base, tmp_path):
    path = _copy(base, tmp_path)
    con = connect(path)
    clean = _materialise_all(con)
    clean_segments = _segments(con)
    _inject_versions(con, edges=False)
    assert _materialise_all(con) == clean  # superseded versions are invisible to every reader already
    segs = _segments(con)
    assert segs == clean_segments and segs and segs[0]  # one version read: no duplicate raw rows
    ids = _inject_edges(con)
    before = _materialise_all(con)
    plan = storage.prune_plan(con)
    removable = {r.table: [] for r in storage.PRUNE_RULES}
    for rule in storage.PRUNE_RULES:
        removable[rule.table] = sorted(map(repr, con.execute(
            f"SELECT t.* {storage._removable_sql(rule)}").fetchall()))  # fmt: skip
    counts = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in removable}
    assert all(removable[t] for t in removable), {t: len(v) for t, v in removable.items()}

    dry = storage.prune_versions(con, tmp_path / "archive", dry_run=True)
    assert dry.status == "DRY_RUN" and dry.plan == plan and not (tmp_path / "archive").exists()
    r = storage.prune_versions(con, tmp_path / "archive", now=datetime(2026, 11, 16, 12))
    assert r.status == "PRUNED" and r.removed == sum(len(v) for v in removable.values())

    # every current version and every row a reader can select is still there
    for t, n in counts.items():
        assert con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] == n - len(removable[t]), t
    assert con.execute("SELECT count(*) FROM fact_observations WHERE parser_version = ? AND filing_id = ? AND "
                       "period_end = DATE '2023-12-31'", [OLD, ids["anchor"]]).fetchone()[0] == 1  # fmt: skip
    assert con.execute("SELECT count(*) FROM shareholding_observations WHERE parser_version = ?",
                       [EARLY]).fetchone()[0] > 0  # fmt: skip
    assert (
        con.execute(
            "SELECT count(*) FROM shareholding_observations WHERE parser_version = ? AND filing_id = ?",
            [OLD, ids["shp"]],
        ).fetchone()[0]
        == 0
    )  # same instant as the current version: superseded
    assert con.execute("SELECT count(*) FROM raw_xbrl_facts WHERE parser_version = ? AND filing_id = ?",
                       [OLD, ids["named"]]).fetchone()[0] > 0  # named by a quarantine finding  # fmt: skip
    assert con.execute("SELECT count(*) FROM filing_meta WHERE parser_version = ?", [OLD]).fetchone()[0] > 0

    assert _materialise_all(con) == before
    assert _segments(con) == segs

    # archive: one zstd Parquet per table and version, manifest with rows and sha256, admin_log entry
    manifest = json.loads(r.manifest.read_text(encoding="utf-8"))
    run = r.manifest.parent
    for t, rows in removable.items():
        files = [f for f in manifest["files"] if f["table"] == t]
        got = []
        for f in files:
            p = run / f["path"]
            assert storage._sha256(p) == f["sha256"]
            assert pq.ParquetFile(p).metadata.row_group(0).column(0).compression == "ZSTD"
            got += con.execute(f"SELECT * FROM read_parquet('{p}')").fetchall()
            assert len(con.execute(f"SELECT 1 FROM read_parquet('{p}')").fetchall()) == f["rows"]
        assert sorted(map(repr, got)) == rows, t
    log = con.execute("SELECT result FROM admin_log WHERE action = 'PRUNE_VERSIONS'").fetchall()
    assert len(log) == 1 and json.loads(log[0][0])["removed"] == r.removed
    assert storage.prune_versions(con, tmp_path / "archive").status == "NOTHING"
    con.close()


def test_prune_refuses_when_the_archive_cannot_be_written(base, tmp_path):
    path = _copy(base, tmp_path)
    con = connect(path)
    _inject_versions(con)
    blocker = tmp_path / "archive"
    blocker.write_text("not a directory", encoding="utf-8")
    counts = {r.table: con.execute(f"SELECT count(*) FROM {r.table}").fetchone()[0] for r in storage.PRUNE_RULES}
    with pytest.raises(storage.StorageError, match="nothing deleted"):
        storage.prune_versions(con, blocker)
    assert {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in counts} == counts
    assert con.execute("SELECT count(*) FROM admin_log WHERE action = 'PRUNE_VERSIONS'").fetchone()[0] == 0
    con.close()


def test_prune_cli_dry_run_reports_and_changes_nothing(base, tmp_path):
    path = _copy(base, tmp_path)
    con = connect(path)
    _inject_versions(con)
    n = con.execute("SELECT count(*) FROM fact_observations").fetchone()[0]
    con.close()
    out = io.StringIO()
    assert main(["--data-dir", str(tmp_path), "prune-versions", "--dry-run"], out=out) == 0, out.getvalue()
    assert f"fact_observations {OLD}:" in out.getvalue() and "removable" in out.getvalue()
    assert "DRY_RUN" in out.getvalue() and "compact:" not in out.getvalue()
    con = connect(path, read_only=True)
    assert con.execute("SELECT count(*) FROM fact_observations").fetchone()[0] == n
    con.close()
    out = io.StringIO()
    assert main(["--data-dir", str(tmp_path), "prune-versions", "--no-compact"], out=out) == 0, out.getvalue()
    assert "PRUNED" in out.getvalue() and (tmp_path / "archive").is_dir()
