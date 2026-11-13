"""Phase 1 audit, Batch C (P2): read-only read commands, quarantine inspect, wired OVERRIDE, buyback purpose,
feature-snapshot semantics."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from datetime import date, datetime

import pytest
from conftest import FETCHED_AT, Market

from _fixture_helpers import CORP, FIXTURES
from financials.admin import AdminError, list_quarantine, resolve_quarantine
from financials.cli import main, promote_pending
from financials.corp_actions import CorpAction, theoretical_factors
from financials.features import materialize
from financials.parsers.nse_corp_actions import parse_corp_action_rss, parse_purpose
from financials.promoter import promote
from financials.staging import stage_results_xbrl

XBRL = "https://nsearchives.nseindia.com/corporate/xbrl/"


def cli(data_dir, *args):
    out = io.StringIO()
    return main(["--data-dir", str(data_dir), *args], out=out), out.getvalue()


@pytest.fixture
def gap_db(tmp_path):
    m = Market(tmp_path)
    for d in ("20250922", "20250923"):
        promote(m.con, m.stage_day(d))
    pid = m.security_id("PIDILITIND")
    (q,) = [r for r in list_quarantine(m.con, stage="GAP", security_id=pid) if r["reason_code"] == "UNEXPLAINED_GAP"]
    m.con.close()
    return tmp_path, q["quarantine_id"]


# ── P2-12 ──────────────────────────────────────────────────────────────────


def test_read_commands_use_a_read_only_connection_and_report_a_busy_database(gap_db):
    data, qid = gap_db
    db = data / "market.duckdb"
    holder = subprocess.Popen(
        [sys.executable, "-c", f"import duckdb, sys; c = duckdb.connect({str(db)!r}); print('ok', flush=True); "
         "sys.stdin.readline()"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
    )  # fmt: skip
    try:
        assert holder.stdout.readline().strip() == "ok"  # another process now holds the write lock
        code, out = cli(data, "quarantine", "list")
        assert code == 3 and "database busy" in out
    finally:
        holder.communicate("\n", timeout=30)
    code, out = cli(data, "quarantine", "list", "--reason", "UNEXPLAINED_GAP")
    assert code == 0 and qid in out
    code, out = cli(data, "screen", "Market Cap > 0")
    assert code == 0 and json.loads(out) == []  # nothing materialised yet: the live table is empty


def test_quarantine_inspect_shows_context_and_the_resolving_commands(gap_db):
    data, qid = gap_db
    code, out = cli(data, "quarantine", "inspect", qid)
    assert code == 0
    doc = json.loads(out)
    assert doc["quarantine"]["reason_code"] == "UNEXPLAINED_GAP"
    assert [b["trade_date"] for b in doc["context"]["bars"]] == ["2025-09-22", "2025-09-23"]
    assert any("--action CORP_ACTION" in c for c in doc["resolve_with"])
    assert cli(data, "quarantine", "inspect", "q_nope")[0] == 1


# ── P2-13 ──────────────────────────────────────────────────────────────────


def _no_visibility(m: Market) -> str:
    promote(m.con, m.stage_day("20251014"))
    stage_results_xbrl(m.vault, m.stage_root, data=CORP.read_bytes(), source_url=XBRL + CORP.name,
                       fetched_at=FETCHED_AT)  # fmt: skip
    promote_pending(m.con, m.stage_root, io.StringIO())
    (q,) = list_quarantine(m.con, reason_code="NO_VISIBILITY")
    return q["quarantine_id"]


def test_override_broadcast_ts_is_applied_by_promoting_the_filing_again(tmp_path):
    m = Market(tmp_path)
    qid = _no_visibility(m)
    r = resolve_quarantine(m.con, qid, action="OVERRIDE", note="NSE page shows 05-Nov-2026 18:06 IST",
                           payload={"field": "broadcast_ts", "value": "2026-11-05T12:36:00"},
                           stage_root=m.stage_root)  # fmt: skip
    assert r["repromoted"]["status"] == "PROMOTED"
    assert m.con.execute("SELECT visible_from_ts, visible_from_source FROM filing_meta").fetchone() == (
        datetime(2026, 11, 5, 12, 36),
        "MANUAL_OVERRIDE",
    )
    assert m.con.execute("SELECT resolution FROM quarantine_queue WHERE quarantine_id = ?", [qid]).fetchone() == (
        "OVERRIDDEN",
    )
    assert m.con.execute("SELECT field FROM filing_overrides").fetchall() == [("broadcast_ts",)]


def test_override_security_id_maps_a_filing_whose_isin_is_unknown(tmp_path):
    m = Market(tmp_path)
    promote(m.con, m.stage_day("20251014"))
    data = CORP.read_bytes().replace(b"INE050401020", b"INE999Z01019")  # in memory: an ISIN not on record
    stage_results_xbrl(m.vault, m.stage_root, data=data, source_url="memory://elin-unknown-isin", fetched_at=FETCHED_AT,
                       broadcast_ts=datetime(2026, 11, 5, 12, 36), broadcast_ts_source="API_FIELD")  # fmt: skip
    promote_pending(m.con, m.stage_root, io.StringIO())
    (q,) = list_quarantine(m.con, reason_code="UNKNOWN_ISIN")
    elin = m.security_id("ELIN")
    r = resolve_quarantine(m.con, q["quarantine_id"], action="OVERRIDE", note="ELIN filing, ISIN typo",
                           payload={"field": "security_id", "value": elin}, stage_root=m.stage_root)  # fmt: skip
    assert r["repromoted"]["status"] == "PROMOTED"
    ent = m.con.execute("SELECT entity_id FROM securities WHERE security_id = ?", [elin]).fetchone()[0]
    assert m.con.execute("SELECT entity_id FROM filing_meta").fetchone()[0] == ent


def test_override_only_takes_fields_the_promoter_reads(tmp_path):
    m = Market(tmp_path)
    qid = _no_visibility(m)
    with pytest.raises(AdminError, match=r"payload\.field in"):
        resolve_quarantine(m.con, qid, action="OVERRIDE", note="x", payload={"field": "pat", "value": 1})
    with pytest.raises(AdminError, match="resolve"):
        resolve_quarantine(m.con, qid, action="OVERRIDE", note="x", payload={"field": "security_id", "value": "s"})


# ── P2-15 ──────────────────────────────────────────────────────────────────


def test_feature_history_is_one_full_snapshot_per_materialised_date(market):
    m = market
    for d in ("20251013", "20251014"):
        promote(m.con, m.stage_day(d))
    assert materialize(m.con, date(2025, 10, 14)).status == "PROMOTED"
    n = m.con.execute("SELECT count(*) FROM screener_features_history").fetchone()[0]
    assert materialize(m.con, date(2025, 10, 14)).status == "PROMOTED"  # re-materialising replaces the date
    assert m.con.execute("SELECT count(*) FROM screener_features_history").fetchone()[0] == n > 2000
    from financials.dsl import run_screen

    assert run_screen(m.con, "Market Cap > 0", as_of=date(2025, 10, 13)) == []  # never materialised


# ── P2-16 ──────────────────────────────────────────────────────────────────


def test_buyback_purpose_from_the_rss_is_parsed_with_no_price_factor():
    items = parse_corp_action_rss((FIXTURES / "corp_actions" / "RSS_Corporate_action_20261113.xml").read_bytes())
    buybacks = [i for i in items if i.purpose == "BUY BACK"]
    assert len(buybacks) == 2
    status, _, comps = parse_purpose(buybacks[0].purpose, None)
    assert status == "PARSED" and [c.action_type for c in comps] == ["BUYBACK"]
    a = CorpAction("ca_bb", "sec", "BUYBACK", date(2026, 11, 13))
    assert theoretical_factors(a, None) == (1, 1)
    assert all(parse_purpose(i.purpose or "", None)[0] == "PARSED" for i in items)  # the whole RSS now parses
