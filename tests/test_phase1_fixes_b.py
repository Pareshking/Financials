"""Phase 1 audit, Batch B (P1): discovery, calendar inference, chunked corporate actions, resumable fetches,
reprocess, range materialisation, run-day, inactive-security closure. Offline: a fake transport serves fixtures."""

from __future__ import annotations

import io
import json
from datetime import date, datetime, timedelta
from itertools import pairwise

import pytest
from conftest import FETCHED_AT, Market
from test_fetch_and_e2e import FakeTransport

from _fixture_helpers import BHAV_DIR, CORP, FIXTURES
from financials.admin import list_quarantine, reprocess
from financials.calendar import is_trading_day, next_trading_day
from financials.cli import main, promote_pending
from financials.fetch.http import PoliteFetcher, Response
from financials.fetch.jobs import (
    ANNOUNCEMENTS_RSS,
    Jobs,
    bhavcopy_url,
    chunks,
    corp_actions_url,
    delivery_url,
    results_listing_url,
)
from financials.parsers.discovery import parse_integrated_filing_listing, symbols_with_results_today
from financials.promoter import promote
from financials.staging import stage_results_xbrl
from financials.vault import Vault

A7 = FIXTURES / "discovery" / "nse_integrated-filing-results_equities_TCS_20261113.json"
A7_PAGE2 = FIXTURES / "discovery" / "nse_integrated-filing-results_equities_TCS_page2_20261114.json"
RSS = FIXTURES / "events" / "nse_Online_announcements_20261113.xml"
XBRL = "https://nsearchives.nseindia.com/corporate/xbrl/"


def bhav(d: str) -> bytes:
    return (BHAV_DIR / f"BhavCopy_NSE_CM_0_0_0_{d}_F_0000.csv.zip").read_bytes()


def jobs_for(tmp_path, routes) -> tuple[Jobs, FakeTransport]:
    t = FakeTransport(routes)
    return Jobs(PoliteFetcher(t, sleep=lambda s: None), Vault(tmp_path / "vault"), tmp_path / "staging"), t


# ── P1-5 discovery ──────────────────────────────────────────────────────────


def test_a7_listing_lists_results_with_scope_period_and_broadcast_time():
    """A7: newest 20 rows; 13 Financials rows (7 consolidated, 6 standalone), 7 Governance rows skipped."""
    rows = parse_integrated_filing_listing(A7.read_bytes())
    assert len(rows) == 13 and {r.scope for r in rows} == {"Consolidated", "Standalone"}
    q2 = rows[0]
    assert (q2.symbol, q2.period_end, q2.scope) == ("TCS", date(2026, 9, 30), "Consolidated")
    assert q2.broadcast_ts_ist == datetime(2026, 10, 8, 22, 7, 33)
    assert q2.xbrl_url == XBRL + "INTEGRATED_FILING_INDAS_1734607_08102026100810_WEB.xml"
    assert len(parse_integrated_filing_listing(A7.read_bytes(), results_only=False)) == 20


def test_rss_results_items_name_symbols_through_the_attachment_file():
    """A9: 'financial results' items link a PDF named <SYMBOL>_<ts>_...: a hint, not a complete list."""
    syms = symbols_with_results_today(RSS.read_bytes())
    assert {"DCAL", "SWELECTES"} <= set(syms) and len(syms) > 150


def test_discover_fetches_only_new_in_scope_results(tmp_path):
    q2 = XBRL + "INTEGRATED_FILING_INDAS_1734607_08102026100810_WEB.xml"
    q4 = XBRL + "INTEGRATED_FILING_INDAS_1648408_09042026114218_WEB.xml"
    routes = {results_listing_url("TCS"): Response(200, A7.read_bytes()),
              results_listing_url("TCS", 2): Response(200, A7_PAGE2.read_bytes()),
              q2: Response(200, (FIXTURES / "xbrl" / q2.rsplit("/", 1)[-1]).read_bytes()),
              q4: Response(200, (FIXTURES / "xbrl" / q4.rsplit("/", 1)[-1]).read_bytes())}  # fmt: skip
    jobs, t = jobs_for(tmp_path, routes)
    staged, errors = jobs.discover(["TCS"], ["results"], events=False)
    # two listing pages + two files; the other 12 in-scope Financials rows (11 on page 1, the Mar 2025 standalone on
    # page 2) are not served (404): reported, not fatal
    assert len(staged) == 4
    assert len(errors) == 12 and all(e.startswith("INTEGRATED_FILING_") for e in errors)
    assert results_listing_url("TCS", 2) in [u for u, _ in t.calls]
    before = len(t.calls)
    jobs.discover(["TCS"], ["results"], events=False)
    fetched_again = [u for u, _ in t.calls[before:] if u in (q2, q4)]
    assert fetched_again == []  # vaulted files are never downloaded again
    m = json.loads((tmp_path / "staging").glob("results_xbrl/*/manifest.json").__next__().read_text())
    assert m["job"] == "results_xbrl"


# ── P1-6 calendar inference ─────────────────────────────────────────────────


def test_prev_close_chain_infers_weekend_and_holiday_and_keeps_the_muhurat_session(market):
    """CAL3 on 17-23 Oct 2025: 18-19 (weekend) and 22 (Balipratipada) had no session; 21 Oct (Diwali, Muhurat)
    has a bhavcopy, so it is a trading day [CAL2], and it raises no more gap findings than a normal day."""
    m = market
    for d in ("20251017", "20251020", "20251021", "20251023"):
        assert promote(m.con, m.stage_day(d)).status == "PROMOTED"
    cal = dict(m.con.execute("SELECT cal_date, source FROM trading_calendar WHERE NOT is_trading").fetchall())
    assert cal == dict.fromkeys([date(2025, 10, 18), date(2025, 10, 19), date(2025, 10, 22)], "INFERRED_PREV_CLOSE")
    assert is_trading_day(m.con, "NSE", date(2025, 10, 19)) is False
    assert is_trading_day(m.con, "NSE", date(2025, 10, 21)) is True
    assert next_trading_day(m.con, "NSE", date(2025, 10, 17)) == date(2025, 10, 20)
    assert next_trading_day(m.con, "NSE", date(2025, 10, 21)) == date(2025, 10, 23)
    gaps = dict(m.con.execute(
        "SELECT json_extract_string(details, '$.trade_date'), count(*) FROM quarantine_queue WHERE stage = 'GAP' "
        "GROUP BY 1").fetchall())  # fmt: skip
    assert gaps["2025-10-21"] <= gaps["2025-10-20"]


def test_a_skipped_session_is_flagged_not_inferred(market):
    m = market
    for d in ("20251020", "20251023"):  # 21 Oct (Muhurat) not loaded
        promote(m.con, m.stage_day(d))
    (q,) = list_quarantine(m.con, reason_code="MISSING_SESSION")
    d = json.loads(q["details"])
    assert d["previous_promoted"] == "2025-10-20" and d["matched"] / d["common"] < 0.05
    assert is_trading_day(m.con, "NSE", date(2025, 10, 22)) is None  # unknown, never guessed


# ── P1-7 corporate actions ──────────────────────────────────────────────────


def test_corp_actions_are_fetched_in_30_day_windows(tmp_path):
    windows = chunks(date(2024, 10, 1), date(2026, 11, 13))
    assert windows[0] == (date(2024, 10, 1), date(2024, 10, 30)) and windows[-1][1] == date(2026, 11, 13)
    assert all(b - a == timedelta(days=29) for a, b in windows[:-1])
    assert all(n[0] - p[1] == timedelta(days=1) for p, n in pairwise(windows))
    routes = {corp_actions_url(a, b): Response(200, b"[]") for a, b in windows}
    jobs, t = jobs_for(tmp_path, routes)
    assert len(jobs.corp_actions(date(2024, 10, 1), date(2026, 11, 13))) == len(windows) == 26
    assert [u for u, _ in t.calls] == [corp_actions_url(a, b) for a, b in windows]


def test_cli_warms_up_the_api_host_once(tmp_path):
    t = FakeTransport({corp_actions_url(date(2025, 9, 15), date(2025, 10, 14)): Response(200, b"[]")})
    import financials.cli as cli_mod

    orig = cli_mod.PoliteFetcher
    cli_mod.PoliteFetcher = lambda transport, **kw: orig(transport, sleep=lambda s: None, **kw)
    try:
        main(["--data-dir", str(tmp_path), "fetch-corp-actions", "2025-09-15", "2025-10-14"], transport=t,
             out=io.StringIO())  # fmt: skip
    finally:
        cli_mod.PoliteFetcher = orig
    assert t.calls[0][0] == "https://www.nseindia.com/"


# ── P1-8 resumable, vault-aware fetch-days ──────────────────────────────────


def test_fetch_days_skips_vaulted_days_continues_after_errors_and_warns_on_tradedt(tmp_path):
    d17, d18, d19, d20 = (date(2025, 10, x) for x in (17, 18, 19, 20))
    routes = {bhavcopy_url(d17): Response(200, bhav("20251017")),
              bhavcopy_url(d19): Response(200, bhav("20251017")),  # Sunday answered with Friday's file
              bhavcopy_url(d20): [Response(503, b""), Response(503, b""), Response(503, b""), Response(503, b""),
                                  Response(200, bhav("20251020"))]}  # fmt: skip
    jobs, t = jobs_for(tmp_path, routes)
    staged, errors = jobs.market_days(d17, d20)
    assert len(errors) == 1 and errors[0].startswith("2025-10-20")  # four 503s: reported, the range went on
    assert jobs.warnings == ["2025-10-19: file holds TradDt 2025-10-17; staged under 2025-10-17"]
    assert len(staged) == 2 and staged[0] == staged[1]  # the Sunday answer is the same batch as Friday's
    calls = len(t.calls)
    staged, errors = jobs.market_days(d17, d20)  # resume
    assert errors == [] and {p.name[:8] for p in staged} == {"20251017", "20251020"}
    new = [u for u, _ in t.calls[calls:]]
    assert bhavcopy_url(d17) not in new and bhavcopy_url(d20) in new  # vaulted day not fetched again
    assert bhavcopy_url(d18) not in new  # its 404 was observed (today) long after 18 Oct: settled, not asked again
    fresh = date(2026, 11, 13)
    jobs.vault.record_fetch(bhavcopy_url(fresh), 404, datetime(2026, 11, 13, 10, 0))  # same day: may still appear
    before = len(t.calls)
    jobs.market_day(fresh)
    assert bhavcopy_url(fresh) in [u for u, _ in t.calls[before:]]


# ── P1-9 reprocess ─────────────────────────────────────────────────────────


def test_reprocess_promotes_a_filing_once_its_visibility_is_derivable(tmp_path):
    """ELIN's Q2 FY27 filing without a broadcast time needs the next trading day after the board meeting
    (2026-11-05 IST); with no calendar it is NO_VISIBILITY. Once the calendar knows 6 Nov, reprocess promotes it."""
    m = Market(tmp_path)
    promote(m.con, m.stage_day("20251014"))
    s = stage_results_xbrl(m.vault, m.stage_root, data=CORP.read_bytes(), source_url=XBRL + CORP.name,
                           fetched_at=FETCHED_AT)  # fmt: skip
    promote_pending(m.con, m.stage_root, io.StringIO())
    assert m.con.execute("SELECT status FROM promotion_log WHERE job = 'results_xbrl'").fetchone()[0] == "QUARANTINED"
    (q,) = list_quarantine(m.con, reason_code="NO_VISIBILITY")
    assert reprocess(m.con, m.stage_root)["cleared"] == []  # still not derivable: reopened, not lost
    assert list_quarantine(m.con, reason_code="NO_VISIBILITY")[0]["quarantine_id"] == q["quarantine_id"]
    m.con.execute("INSERT INTO trading_calendar (exchange, cal_date, is_trading, note) "
                  "VALUES ('NSE', DATE '2026-11-06', TRUE, 'test')")  # fmt: skip
    r = reprocess(m.con, m.stage_root)
    assert r["cleared"] == [q["quarantine_id"]] and r["batches"][0]["status"] == "PROMOTED"
    assert m.con.execute("SELECT visible_from_source FROM filing_meta").fetchone()[0] == "BOARD_MEETING_RULE"
    assert s.name in r["batches"][0]["stage"]


def test_reprocess_loads_a_bar_that_arrived_without_fin_instrm_id(market):
    import io as _io
    import zipfile

    m = market
    promote(m.con, m.stage_day("20251013"))
    with zipfile.ZipFile(_io.BytesIO(bhav("20251014"))) as zf:
        (name,) = zf.namelist()
        lines = zf.read(name).decode("utf-8-sig").splitlines()
    header = lines[0].split(",")
    fid, sym = header.index("FinInstrmId"), header.index("TckrSymb")
    rows = [ln.split(",") for ln in lines[1:]]
    for r in rows:
        if r[sym] == "PIDILITIND":
            r[fid] = ""  # in memory: the identifier missing from one row
    buf = _io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, "\n".join([lines[0], *(",".join(r) for r in rows)]) + "\n")
    from test_phase1_fixes_a import stage

    assert promote(m.con, stage(m, buf.getvalue(), "20251014")).status == "PROMOTED"
    assert len(list_quarantine(m.con, reason_code="MISSING_FIN_INSTRM_ID")) == 1
    pid = m.security_id("PIDILITIND")
    assert m.con.execute("SELECT count(*) FROM ohlcv WHERE security_id = ? AND trade_date = '2025-10-14'",
                         [pid]).fetchone()[0] == 0  # fmt: skip
    assert reprocess(m.con, m.stage_root)["bars_loaded"] == 1
    assert m.con.execute("SELECT count(*) FROM ohlcv WHERE security_id = ? AND trade_date = '2025-10-14'",
                         [pid]).fetchone()[0] == 1  # fmt: skip
    assert list_quarantine(m.con, reason_code="MISSING_FIN_INSTRM_ID") == []


# ── P1-10 range materialisation and run-day ─────────────────────────────────


def test_materialize_range_runs_every_promoted_day_in_order(tmp_path):
    m = Market(tmp_path)
    for d in ("20251013", "20251014", "20251017"):
        m.stage_day(d)
    m.con.close()
    out = io.StringIO()
    assert main(["--data-dir", str(tmp_path), "promote"], out=io.StringIO()) == 0
    assert (
        main(["--data-dir", str(tmp_path), "materialize", "--from", "2025-10-01", "--to", "2025-10-31"], out=out) == 0
    )
    assert [ln.split()[1] for ln in out.getvalue().splitlines()] == ["2025-10-13", "2025-10-14", "2025-10-17"]


def test_run_day_fetches_promotes_and_materialises(tmp_path):
    d = date(2025, 10, 17)
    routes = {bhavcopy_url(d): Response(200, bhav("20251017")), ANNOUNCEMENTS_RSS: Response(200, b"<rss></rss>")}
    routes |= {corp_actions_url(a, b): Response(200, b"[]") for a, b in chunks(d - timedelta(days=7),
                                                                                  d + timedelta(days=30))}  # fmt: skip
    t = FakeTransport(routes)
    import financials.cli as cli_mod

    orig = cli_mod.PoliteFetcher
    cli_mod.PoliteFetcher = lambda transport, **kw: orig(transport, sleep=lambda s: None, **kw)
    out = io.StringIO()
    try:
        code = main(["--data-dir", str(tmp_path), "run-day", "--date", "2025-10-17"], transport=t, out=out)
    finally:
        cli_mod.PoliteFetcher = orig
    log = out.getvalue()
    assert "PROMOTED         market_day" in log and "PROMOTED 2025-10-17" in log
    assert code == 1 and "error: holidays" in log  # the holiday master was not served: reported, run went on
    assert delivery_url(d) in [u for u, _ in t.calls]


# ── P1-11 inactive securities ───────────────────────────────────────────────


def test_a_security_that_stops_trading_is_closed_and_reopens_when_it_trades_again(market, monkeypatch):
    """Real days: IVZINNIFTY (ETF) has no bar on 14 Oct 2025 and trades again on 17 Oct. With a 1-session
    threshold its interval closes after 14 Oct and reopens on 17 Oct under the same security id."""
    import financials.promoter as promoter_mod

    monkeypatch.setattr(promoter_mod, "INACTIVITY_TRADING_DAYS", 1)
    m = market
    for d in ("20251013", "20251014"):
        promote(m.con, m.stage_day(d))
    sec = m.security_id("IVZINNIFTY")
    assert m.con.execute("SELECT valid_to FROM security_identifier_history WHERE security_id = ?",
                         [sec]).fetchall() == [(date(2025, 10, 14),)]  # fmt: skip
    promote(m.con, m.stage_day("20251017"))
    assert m.con.execute("SELECT valid_from, valid_to FROM security_identifier_history WHERE security_id = ? "
                         "ORDER BY 1", [sec]).fetchall() == [(date(2025, 10, 13), date(2025, 10, 14)),
                                                             (date(2025, 10, 17), None)]  # fmt: skip


def test_default_threshold_leaves_sparse_fixture_days_open(market):
    m = market
    for d in ("20251013", "20251014"):
        r = promote(m.con, m.stage_day(d))
    assert "inactive" not in r.message
    assert (
        m.con.execute("SELECT count(*) FROM security_identifier_history WHERE valid_to IS NOT NULL").fetchone()[0] < 50
    )  # only real identifier changes; nobody closed for inactivity with 2 sessions loaded


@pytest.mark.parametrize("n", [1])
def test_inactive_closure_on_a_year_gap(market, monkeypatch, n):
    """14 Oct 2025 -> 12 Nov 2026: 38 securities that no longer trade (e.g. GSPL, CIGNITITEC; reasons not
    established offline) are closed the day after their last bar."""
    import financials.promoter as promoter_mod

    monkeypatch.setattr(promoter_mod, "INACTIVITY_TRADING_DAYS", n)
    m = market
    promote(m.con, m.stage_day("20251014"))
    r = promote(m.con, m.stage_day("20261112"))
    assert "38 inactive securities closed" in r.message
    assert m.con.execute("SELECT valid_to FROM security_identifier_history WHERE symbol = 'GSPL'").fetchone()[
        0
    ] == date(2025, 10, 15)


# ── Step 1: parallel workers never break per-host spacing ───────────────────


def test_parallel_workers_keep_one_request_per_host_interval(tmp_path):
    """Threads overlap hosts but never two requests to one host closer than min_interval."""
    import threading
    import time

    calls: list[tuple[str, float]] = []
    lock = threading.Lock()

    class SlowTransport:
        def get(self, url, headers, timeout):
            with lock:
                calls.append((url.split("/")[2], time.monotonic()))
            time.sleep(0.02)
            return Response(404, b"")

    f = PoliteFetcher(SlowTransport(), min_interval=0.05, max_attempts=1)
    jobs = Jobs(f, Vault(tmp_path / "vault"), tmp_path / "staging")
    staged, errors = jobs.discover(["AAA", "BBB", "CCC", "DDD"], ["results", "annual"], events=False, workers=4)
    assert staged == [] and len(errors) == 8  # every listing 404s: reported per symbol and kind
    per_host: dict[str, list[float]] = {}
    for host, t in calls:
        per_host.setdefault(host, []).append(t)
    assert set(per_host) == {"www.nseindia.com"}
    ts = sorted(per_host["www.nseindia.com"])
    assert len(ts) == 8 and all(b - a >= 0.049 for a, b in pairwise(ts))
