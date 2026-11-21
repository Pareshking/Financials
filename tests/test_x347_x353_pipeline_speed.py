"""Phase 1/2 pipeline speed (work SP1, 2026-11-20): X347 staging connection reuse, X348 URL-index cache, X349
already-promoted answers are not staged again and the annual share check runs as one batch, X350 the announcements
RSS is asked again when it does not parse, X351 run-day step timings, X352 `clean-staging`, X353 bse-fetch window and
shards. Offline; real fixtures only (a cut-short RSS is built in memory from the committed one, never written)."""

from __future__ import annotations

import importlib.util
import io
import json
from datetime import date, datetime, timedelta

import pyarrow.parquet as pq
import pytest
from conftest import FETCHED_AT
from test_bse import RoutedSession, _resp
from test_fetch_and_e2e import FakeTransport
from test_nse_fetch_runners import Q2, Q4, routes, run, runner_fetch, staged_set
from test_phase1_fixes_b import bhav
from test_x180_annual_checks import GREENPLY_AR25, GREENPLY_Q4FY25, QA_DIR, TCS25, _greenply_shp

from _fixture_helpers import FIXTURES, XBRL_DIR
from financials import promoted_ledger
from financials import staging as staging_mod
from financials.cli import main, promote_pending
from financials.fetch import bse
from financials.fetch.http import PoliteFetcher, Response
from financials.fetch.jobs import (
    ANNOUNCEMENTS_RSS,
    RSS_ATTEMPTS,
    RSS_RETRY_WAIT,
    Jobs,
    bhavcopy_url,
    chunks,
    corp_actions_url,
    results_listing_url,
)
from financials.ids import stable_id
from financials.parsers import ParseError
from financials.promoter import promote
from financials.share_capital import annual_share_disagreement, annual_share_disagreements
from financials.sources import ROOT
from financials.staging import stage_results_xbrl
from financials.staging_clean import clean_staging
from financials.vault import Vault

RSS = (FIXTURES / "events" / "nse_Online_announcements_20261113.xml").read_bytes()
CUT = RSS[:430594]  # the length NSE served on 2026-11-20 ("unclosed token: line 1, column 430594"), in memory only
XBRL_URL = "https://nsearchives.nseindia.com/corporate/xbrl/"


def _jobs(tmp_path, routes_, sleeps=None) -> tuple[Jobs, FakeTransport]:
    t = FakeTransport(routes_)
    sleep = (lambda s: sleeps.append(s)) if sleeps is not None else (lambda s: None)
    return Jobs(PoliteFetcher(t, sleep=sleep), Vault(tmp_path / "vault"), tmp_path / "staging"), t


# ── X347 STAGING_CONNECTION_REUSE ─────────────────────────────────────────────────────────────────────────────


def _tables(d):
    return {p.stem: pq.read_table(p).to_pylist() for p in sorted(d.glob("*.parquet"))}


def test_x347_reused_staging_connection_writes_the_same_batches_and_never_leaks_rows(tmp_path):
    files = [QA_DIR / GREENPLY_Q4FY25, QA_DIR / GREENPLY_AR25, XBRL_DIR / TCS25]

    def stage_all(root):
        return [stage_results_xbrl(Vault(root / "vault"), root / "staging", data=p.read_bytes(),
                                   source_url=XBRL_URL + p.name, fetched_at=FETCHED_AT) for p in files]  # fmt: skip

    reused = stage_all(tmp_path / "a")  # one connection for the three batches (same thread)
    fresh = []
    for p in files:  # a new connection for every batch, as before X347
        staging_mod._LOCAL.con = None
        fresh += [stage_results_xbrl(Vault(tmp_path / "b" / "vault"), tmp_path / "b" / "staging", data=p.read_bytes(),
                                     source_url=XBRL_URL + p.name, fetched_at=FETCHED_AT)]  # fmt: skip
    for a, b in zip(reused, fresh, strict=True):
        assert _tables(a) == _tables(b)
        assert (a / "manifest.json").read_text() == (b / "manifest.json").read_text()
        ids = {r["filing_id"] for rows in _tables(a).values() for r in rows if "filing_id" in r}
        assert ids == {a.name}  # each batch holds its own filing's rows only
    con = staging_mod._staging_connection()
    assert con.execute("SELECT count(*) FROM filings").fetchone() == (0,)


def test_x347_a_failed_batch_leaves_nothing_behind_and_the_next_batch_works(tmp_path):
    row = {"filing_id": "f", "stage": "PARSE", "reason_code": "X", "details": "{}"}
    with pytest.raises(Exception):  # noqa: B017 - DuckDB's own error for a NOT NULL column
        staging_mod.write_stage(tmp_path, "results_xbrl", "bad", {"stg_issues": [row, {**row, "stage": None}]})
    assert not (tmp_path / "results_xbrl" / "bad").exists()
    assert not [p for p in (tmp_path / "results_xbrl").iterdir()]  # the temp directory is gone too
    ok = staging_mod.write_stage(tmp_path, "results_xbrl", "good", {"stg_issues": [row]})
    assert pq.read_table(ok / "stg_issues.parquet").to_pylist() == [row]


# ── X348 URL_INDEX_CACHE ─────────────────────────────────────────────────────────────────────────────────────


def test_x348_a_recorded_fetch_updates_the_loaded_index_without_reading_the_file_again(tmp_path, monkeypatch):
    v = Vault(tmp_path)
    v.record_fetch("u1", 404, FETCHED_AT)
    assert v.last_fetch("u1")["status"] == 404  # loads the index once
    reads = []
    real = type(v.index_path).read_text
    monkeypatch.setattr(
        type(v.index_path), "read_text", lambda self, *a, **k: reads.append(self) or real(self, *a, **k)
    )
    v.record_fetch("u1", 200, FETCHED_AT, b"x", "xml")
    v.record_fetch("u2", 200, FETCHED_AT, b"y", "xml")
    assert v.last_fetch("u1")["status"] == 200 and v.last_fetch("u2")["sha256"] and reads == []
    assert Vault(tmp_path).last_fetch("u1") == v.last_fetch("u1")  # what a fresh read of the file gives


# ── X349 PROMOTED_ANSWER_SKIP ────────────────────────────────────────────────────────────────────────────────


def test_x349_reimport_of_a_promoted_runner_vault_stages_nothing(tmp_path):
    nse_fetch = runner_fetch(tmp_path)
    local = tmp_path / "local"
    rc, text = run(["--data-dir", str(local), "import-vault", str(nse_fetch)])
    first = staged_set(local / "staging")
    assert rc == 0 and any(s.startswith("raw_only/") for s in first), text
    assert run(["--data-dir", str(local), "init-db"])[0] == 0
    rc, text = run(["--data-dir", str(local), "promote"])
    assert "PROMOTED" in text, text
    for d in (local / "staging").glob("*/*"):  # disk clean-up: staging is disposable once promoted (X345)
        if d.is_dir():
            import shutil

            shutil.rmtree(d)
    rc, text = run(["--data-dir", str(local), "import-vault", str(nse_fetch)])
    assert rc == 0, text
    again = staged_set(local / "staging")
    assert not [s for s in again if s.startswith("raw_only/")]  # listings byte-identical to promoted ones
    import duckdb

    con = duckdb.connect(str(local / "market.duckdb"), read_only=True)
    retry = {r[0] for r in con.execute(
        "SELECT filing_id FROM quarantine_queue WHERE resolved_at IS NULL AND stage IN ('PARSE', 'IDENTITY', 'PERIOD')"
    ).fetchall()}  # fmt: skip
    con.close()
    # no market day here, so the files fail identity: those (and only those) are retried, as X345 intends
    assert {s.split("/", 1)[1] for s in again} == retry and again <= first


def test_x349_a_changed_listing_is_staged_and_an_identical_one_is_only_read(tmp_path):
    jobs, t = _jobs(tmp_path, routes())
    listing = routes()[results_listing_url("TCS")].body
    fid = stable_id("fil", "NSE", results_listing_url("TCS"), __import__("hashlib").sha256(listing).hexdigest())
    (tmp_path / "staging").mkdir()
    (tmp_path / "staging" / promoted_ledger.FILE).write_text(fid + "\n")
    staged = jobs.results("TCS")
    names = {p.name for p in staged}
    assert fid not in names  # page 1 is already promoted: not staged again
    assert {Q2, Q4} <= {u for u, _ in t.calls}  # but still read: its rows were followed to the files
    assert any(p.parent.name == "raw_only" for p in staged)  # page 2 is not in the ledger: staged


def test_x349_batched_annual_share_check_equals_the_single_filing_check(market):
    promote(market.con, market.stage_day("20250227"))
    for name, ts in ((GREENPLY_Q4FY25, datetime(2025, 4, 28, 14, 3, 35)), (GREENPLY_AR25, datetime(2025, 9, 24, 5)),
                     (TCS25, datetime(2025, 8, 14, 13, 17, 52))):  # fmt: skip
        src = XBRL_DIR if name == TCS25 else QA_DIR
        r = promote(market.con, stage_results_xbrl(market.vault, market.stage_root, data=(src / name).read_bytes(),
                                                   source_url=XBRL_URL + name, fetched_at=FETCHED_AT, broadcast_ts=ts,
                                                   broadcast_ts_source="API_FIELD"))  # fmt: skip
        assert r.status == "PROMOTED", r
    items = market.con.execute(
        "SELECT DISTINCT filing_id, entity_id, fy_end FROM filing_meta WHERE accounting_profile = 'REG34_ANNUAL' "
        "ORDER BY 1"
    ).fetchall()
    assert len(items) == 2
    for stage in ("before Reg. 31", "after Reg. 31"):
        batch = annual_share_disagreements(market.con, items)
        assert batch == {f: annual_share_disagreement(market.con, f, e, d) for f, e, d in items}, stage
        assert sum(v is not None for v in batch.values()) == (1 if stage == "before Reg. 31" else 0), (stage, batch)
        if stage == "before Reg. 31":
            _greenply_shp(market)  # GREENPLY's FY-end Reg. 31 total decides from now on (X181)
    with pytest.raises(ValueError):
        annual_share_disagreements(market.con, [(items[0][0], items[0][1], items[0][2]),
                                                (items[0][0], items[0][1], date(2024, 3, 31))])  # fmt: skip


# ── X350 RSS_PARSE_RETRY / X351 RUN_DAY_TIMINGS ──────────────────────────────────────────────────────────────


def test_x350_a_cut_short_rss_is_asked_again_and_never_vaulted(tmp_path):
    with pytest.raises(ParseError):
        Jobs(PoliteFetcher(FakeTransport({})), Vault(tmp_path / "x"), tmp_path / "y").reg30_events(rss=CUT)
    sleeps: list[float] = []
    jobs, t = _jobs(tmp_path, {ANNOUNCEMENTS_RSS: [Response(200, CUT), Response(200, RSS)]}, sleeps)
    assert jobs.symbols_from_rss() and jobs.announcements_rss() == RSS
    assert [u for u, _ in t.calls].count(ANNOUNCEMENTS_RSS) == 2  # once cut short, once whole; then reused
    assert RSS_RETRY_WAIT in sleeps and any("X350" in w for w in jobs.warnings)
    staged = jobs.reg30_events(limit=0)
    raw = [p for p in staged if p.parent.name == "raw_only"]
    assert len(raw) == 1 and [u for u, _ in t.calls].count(ANNOUNCEMENTS_RSS) == 2
    vaulted = {p.name for p in (tmp_path / "vault").rglob("*.gz")}
    sha = __import__("hashlib").sha256
    assert f"{sha(RSS).hexdigest()}.xml.gz" in vaulted and f"{sha(CUT).hexdigest()}.xml.gz" not in vaulted

    jobs, t = _jobs(tmp_path / "all_bad", {ANNOUNCEMENTS_RSS: Response(200, CUT)})
    with pytest.raises(ParseError, match=f"{RSS_ATTEMPTS} attempts"):
        jobs.reg30_events()
    assert [u for u, _ in t.calls].count(ANNOUNCEMENTS_RSS) == RSS_ATTEMPTS
    assert not (tmp_path / "all_bad" / "vault").exists() and not (tmp_path / "all_bad" / "staging").exists()


def test_x351_run_day_times_every_step_and_reads_the_rss_once(tmp_path):
    d = date(2025, 10, 17)
    rts = {bhavcopy_url(d): Response(200, bhav("20251017")),
           ANNOUNCEMENTS_RSS: [Response(200, CUT), Response(200, RSS)]}  # fmt: skip
    rts |= {corp_actions_url(a, b): Response(200, b"[]") for a, b in chunks(d - timedelta(days=7),
                                                                             d + timedelta(days=30))}  # fmt: skip
    t = FakeTransport(rts)
    import financials.cli as cli_mod

    orig = cli_mod.PoliteFetcher
    cli_mod.PoliteFetcher = lambda transport, **kw: orig(transport, sleep=lambda s: None, **kw)
    out = io.StringIO()
    try:
        main(["--data-dir", str(tmp_path), "run-day", "--date", "2025-10-17"], transport=t, out=out)
    finally:
        cli_mod.PoliteFetcher = orig
    log = out.getvalue()
    steps = ["holidays", "days", "corp-actions", "discovery", "events", "open-db", "schema", "promote", "universe",
             "materialize-catch-up", "materialize", "total"]  # fmt: skip
    timed = [ln.split()[1].rstrip(":") for ln in log.splitlines() if ln.startswith("time ")]
    assert timed == steps, log
    assert not [ln for ln in log.splitlines() if ln.startswith("error:") and "announcements RSS" in ln]  # asked again
    assert "X350" in log  # the retry is reported as a warning
    assert "PROMOTED 2025-10-17" in log and "raw_only" in log  # the day's RSS is vaulted, promoted once
    assert [u for u, _ in t.calls].count(ANNOUNCEMENTS_RSS) == 2


# ── X352 STAGING_CLEAN ───────────────────────────────────────────────────────────────────────────────────────


def test_x352_clean_staging_removes_only_promoted_batches_no_reader_needs(market, tmp_path):
    day = market.stage_day("20250227")
    assert promote_pending(market.con, market.stage_root, io.StringIO()) == 0
    q4 = stage_results_xbrl(market.vault, market.stage_root, data=(QA_DIR / GREENPLY_Q4FY25).read_bytes(),
                            source_url=XBRL_URL + GREENPLY_Q4FY25, fetched_at=FETCHED_AT,
                            broadcast_ts=datetime(2025, 4, 28, 14, 3, 35), broadcast_ts_source="API_FIELD")  # fmt: skip
    assert promote_pending(market.con, market.stage_root, io.StringIO()) == 0
    ar = stage_results_xbrl(market.vault, market.stage_root, data=(QA_DIR / GREENPLY_AR25).read_bytes(),
                            source_url=XBRL_URL + GREENPLY_AR25, fetched_at=FETCHED_AT,
                            broadcast_ts=datetime(2025, 9, 24, 5), broadcast_ts_source="API_FIELD")  # fmt: skip
    assert promote_pending(market.con, market.stage_root, io.StringIO()) == 0
    open_ = {r[0] for r in market.con.execute(
        "SELECT filing_id FROM quarantine_queue WHERE resolved_at IS NULL").fetchall()}  # fmt: skip
    assert ar.name in open_ and q4.name not in open_  # the annual's share count waits for the Reg. 31 filing

    dry = clean_staging(market.con, market.stage_root, dry_run=True)
    assert dry["removed"] == 1 and dry["kept_open_finding"] == 1 and dry["by_job"]["results_xbrl"]["dirs"] == 1
    assert dry["bytes"] > 0 and q4.exists()  # a dry run deletes nothing
    r = clean_staging(market.con, market.stage_root)
    assert {k: r[k] for k in ("removed", "bytes")} == {k: dry[k] for k in ("removed", "bytes")}
    assert not q4.exists() and ar.exists() and day.exists()  # market days stay: rebuild-market replays them
    assert clean_staging(market.con, market.stage_root)["removed"] == 0  # idempotent

    # the removed filing stays done for discovery (X345), and a re-promote of the batches left changes nothing
    assert q4.name in promoted_ledger.read(market.stage_root)
    assert promote_pending(market.con, market.stage_root, io.StringIO()) == 0


def test_x352_cli_dry_run_is_read_only_and_promote_cleans_on_request(tmp_path):
    from conftest import Market

    m = Market(tmp_path)  # the data dir layout: vault/, staging/, market.duckdb
    day = m.stage_day("20250227")
    q4 = stage_results_xbrl(m.vault, m.stage_root, data=(QA_DIR / GREENPLY_Q4FY25).read_bytes(),
                            source_url=XBRL_URL + GREENPLY_Q4FY25, fetched_at=FETCHED_AT,
                            broadcast_ts=datetime(2025, 4, 28, 14, 3, 35), broadcast_ts_source="API_FIELD")  # fmt: skip
    m.con.close()
    assert main(["--data-dir", str(tmp_path), "promote"], out=io.StringIO()) == 0
    out = io.StringIO()
    assert main(["--data-dir", str(tmp_path), "clean-staging", "--dry-run"], out=out) == 0
    assert "would remove 1 director(ies)" in out.getvalue() and q4.exists(), out.getvalue()
    out = io.StringIO()
    assert main(["--data-dir", str(tmp_path), "promote", "--clean-staging"], out=out) == 0
    assert "clean-staging: removed 1 director(ies)" in out.getvalue(), out.getvalue()
    assert not q4.exists() and day.exists()


# ── X353 BSE_SINCE_WINDOW / shards ───────────────────────────────────────────────────────────────────────────


def _bse_fetch():
    spec = importlib.util.spec_from_file_location("bse_fetch", ROOT / "scripts" / "bse_fetch.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


LIST_500488 = FIXTURES / "bse" / "bse_Corp_FinanceResult_ng_new_500488_flagdur6_20261118.json"
SHP_500488 = FIXTURES / "bse" / "bse_Corp_Shareholding_ng_500488_flag6_20261117.json"


def test_x353_created_since_keeps_rows_on_or_after_the_date_and_unreadable_ones():
    rows = json.loads(LIST_500488.read_bytes())["Table"]
    created = sorted(r["Fld_CreateDate"][:10] for r in rows)
    since = date.fromisoformat(created[-1])
    kept, dropped = bse.created_since([*rows, {"Fld_CreateDate": None}], since)
    assert dropped == sum(c < created[-1] for c in created) and len(kept) == len(rows) + 1 - dropped
    assert bse.created_since(rows, None) == (rows, 0)
    shp = json.loads(SHP_500488.read_bytes())
    shp = shp["Table"] if isinstance(shp, dict) else shp
    assert bse.created_since(shp, date(2026, 10, 15), "D")[1] == sum(r["D"][:10] < "2026-10-15" for r in shp)


def test_x353_window_fetches_only_new_results_files_and_skips_flagdur_7(tmp_path):
    m = _bse_fetch()
    listing = LIST_500488.read_bytes()
    rows = json.loads(listing)["Table"]
    newest = max(r["Fld_CreateDate"] for r in rows)
    want = {
        n for r in rows if r["Fld_CreateDate"][:10] >= newest[:10] for n in (r["XMLName"], r["Consol_XMLName"]) if n
    }
    s = RoutedSession([
        ("SCRIP_CD=500488&FlagDur=6", _resp(200, listing, "application/json")),
        ("XBRLFILES/", _resp(200, b"<html/>", "text/html")),
    ])  # fmt: skip
    c = bse.BseClient(s, sleep=lambda _: None, ledger=bse.Ledger(tmp_path / "led"), allow_in_page=False)
    lines: list[str] = []
    since = date.fromisoformat(newest[:10])
    m.results_xbrl(c, ["500488"], lines.append, since=since, today=since + timedelta(days=3))
    asked = [(p.get("FlagDur"), u) for _, u, p, _ in s.calls]
    assert [f for f, u in asked if "FinanceResult" in u] == ["6"]  # no FlagDur 7 inside the last year
    files = {u.rsplit("XBRLFILES/", 1)[-1] for _, u in asked if "XBRLFILES" in u}
    assert files == want and 0 < len(files) < len(rows)
    assert any("created before --since" in ln for ln in lines)


def test_x353_shards_split_the_scrips_and_only_shard_0_lists_groups(tmp_path):
    m = _bse_fetch()
    scrips = ["500488", "534091", "505036@2026-11-05", "590041"]
    from financials.fetch.replay import shard

    parts = [shard(scrips, k, 3) for k in range(3)]
    assert sorted(s for p in parts for s in p) == sorted(scrips)
    for groups in (True, False):
        s = RoutedSession([("AnnSubCategoryGetData", _resp(200, b'{"Table": [], "Table1": [{"ROWCNT": 0}]}',
                                                           "application/json")),
                           ("Corp_Shareholding_ng", _resp(200, b'{"Table": []}', "application/json")),
                           ("Corp_FinanceResult_ng_new", _resp(200, b'{"Table": []}', "application/json")),
                           ("ListofScripData", _resp(200, b'{"Table": []}', "application/json"))])  # fmt: skip
        c = bse.BseClient(s, sleep=lambda _: None, ledger=bse.Ledger(tmp_path / str(groups)), allow_in_page=False)
        m.run(c, ["500488"], date(2026, 11, 12), date(2026, 11, 20), lambda _: None, window=True, groups=groups)
        lists = [u for _, u, _, _ in s.calls if "ListofScripData" in u]
        assert len(lists) == (len(m.GROUPS) if groups else 0)
        assert [p["FlagDur"] for _, u, p, _ in s.calls if "FinanceResult" in u] == ["6"]


def test_x353_bse_fetch_workflow_runs_shards_with_window_and_one_artifact_each():
    import yaml

    doc = yaml.safe_load((ROOT / ".github" / "workflows" / "bse-fetch.yml").read_text(encoding="utf-8"))
    inputs = doc[True]["workflow_dispatch"]["inputs"]
    assert {"shards", "window", "since", "scrips", "only"} <= set(inputs)
    fetch = doc["jobs"]["fetch"]
    assert fetch["strategy"]["matrix"]["shard"] == "${{ fromJSON(needs.plan.outputs.shards) }}"
    text = (ROOT / ".github" / "workflows" / "bse-fetch.yml").read_text(encoding="utf-8")
    assert '--shard "$SHARD/$N"' in text and "--window" in text and "bse-fetch-${{ matrix.shard }}" in text
