"""Phase 1 audit, Batch A (P0): permanent day lockouts, late delivery, unparsed corporate actions, knowledge modes.

Real fixture days only; the "trimmed" bhavcopy and the unparseable purpose text are in-memory modifications of
real files (fixtures on disk are never changed).
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import date, datetime

import pytest
from conftest import ARCHIVE, FETCHED_AT, Market, bhav_bytes, bhav_url

from _fixture_helpers import BHAV_DIR, FIXTURES
from financials.admin import list_quarantine, rebuild_market, resolve_quarantine
from financials.cli import promote_pending
from financials.features import _price_inputs, materialize
from financials.promoter import adjusted_closes, promote
from financials.staging import stage_corp_actions, stage_market_day

CA_JSON = FIXTURES / "corp_actions" / "nse_corporateActions_equities_15-09-2025_17-10-2025.json"
CA_URL = (
    "https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=15-09-2025&to_date=17-10-2025"
)


def trimmed(yyyymmdd: str, keep: float = 0.5) -> bytes:
    """A half-published bhavcopy: the real file with the second half of its rows cut (in memory)."""
    with zipfile.ZipFile(io.BytesIO(bhav_bytes(yyyymmdd))) as zf:
        (name,) = zf.namelist()
        lines = zf.read(name).decode("utf-8-sig").splitlines()
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr(name, "\n".join(lines[: int(len(lines) * keep)]) + "\n")
    return out.getvalue()


def stage(m: Market, data: bytes, yyyymmdd: str, delivery: bytes | None = None, ddmmyyyy: str | None = None):
    return stage_market_day(
        m.vault, m.stage_root, bhavcopy=data, bhavcopy_url=bhav_url(yyyymmdd), delivery=delivery,
        delivery_url=f"{ARCHIVE}/products/content/sec_bhavdata_full_{ddmmyyyy}.csv" if delivery else None,
        fetched_at=FETCHED_AT,
    )  # fmt: skip


def days(m: Market) -> list[date]:
    return [r[0] for r in m.con.execute("SELECT DISTINCT trade_date FROM ohlcv ORDER BY 1").fetchall()]


# ── P0-1 ────────────────────────────────────────────────────────────────────


def test_g1_failure_holds_later_days_until_the_complete_day_promotes(market):
    m = market
    for d in ("20250919", "20250922"):
        m.stage_day(d)
    stage(m, trimmed("20250923"), "20250923")
    m.stage_day("20251013")
    out = io.StringIO()
    assert promote_pending(m.con, m.stage_root, out) == 2
    log = out.getvalue()
    assert "ABORTED" in log and "G1" in log and "WAITING" in log
    assert days(m) == [date(2025, 9, 19), date(2025, 9, 22)]  # 13 Oct waits behind 23 Sep
    m.stage_day("20250923")  # the complete file, fetched later
    promote_pending(m.con, m.stage_root, io.StringIO())
    assert days(m)[-2:] == [date(2025, 9, 23), date(2025, 10, 13)]
    assert promote_pending(m.con, m.stage_root, io.StringIO()) == 0  # the trimmed batch is now ALREADY_PROMOTED


def _snapshot(m: Market):
    bars = m.con.execute("SELECT * FROM ohlcv ORDER BY ALL").fetchall()
    ids = m.con.execute(
        "SELECT * EXCLUDE (evidence_filing_id) FROM security_identifier_history ORDER BY ALL"
    ).fetchall()
    open_q = m.con.execute("SELECT quarantine_id FROM quarantine_queue WHERE resolved_at IS NULL ORDER BY 1").fetchall()
    feats = m.con.execute("SELECT security_id, close, return_1m FROM screener_features_history ORDER BY ALL").fetchall()
    return bars, ids, open_q, feats


def test_rebuild_market_replays_to_the_same_state(market):
    m = market
    for d in ("20250919", "20250922", "20250923", "20251013", "20251014"):
        m.stage_day(d)
    assert promote_pending(m.con, m.stage_root, io.StringIO()) == 0
    assert materialize(m.con, date(2025, 10, 14)).status == "PROMOTED"
    before = _snapshot(m)
    r = rebuild_market(m.con, date(2025, 9, 23), note="test")
    assert r["market_days_to_replay"] == 3 and r["features_dates"] == [date(2025, 10, 14)]
    assert days(m) == [date(2025, 9, 19), date(2025, 9, 22)]
    assert promote_pending(m.con, m.stage_root, io.StringIO()) == 0
    assert materialize(m.con, date(2025, 10, 14)).status == "PROMOTED"
    assert _snapshot(m) == before  # PIDILITIND's 23-Sep gap is found again and reopened, not lost
    assert m.con.execute("SELECT action FROM admin_log").fetchall() == [("REBUILD_MARKET",)]


# ── P0-2 / P1-8 delivery ─────────────────────────────────────────────────────


def test_late_delivery_attaches_to_promoted_bars(market):
    m = market
    assert promote(m.con, m.stage_day("20251014")).status == "PROMOTED"
    assert promote(m.con, m.stage_day("20261112")).status == "PROMOTED"  # a later day: no ORDER trap
    assert m.con.execute("SELECT count(deliv_qty) FROM ohlcv WHERE trade_date = '2025-10-14'").fetchone()[0] == 0
    late = m.stage_day("20251014", with_delivery=True)
    r = promote(m.con, late)
    assert r.status == "PROMOTED" and "delivery attached" in r.message
    mismatched = m.con.execute(
        """SELECT count(*) FROM ohlcv o JOIN security_identifier_history h
             ON h.security_id = o.security_id AND h.valid_from <= o.trade_date
            AND (h.valid_to IS NULL OR h.valid_to > o.trade_date)
           JOIN raw_delivery d ON d.trade_date = o.trade_date AND d.symbol = h.symbol AND d.series = o.series
           WHERE o.trade_date = '2025-10-14' AND o.deliv_qty IS DISTINCT FROM d.deliv_qty"""
    ).fetchone()[0]
    filled = m.con.execute("SELECT count(deliv_qty) FROM ohlcv WHERE trade_date = '2025-10-14'").fetchone()[0]
    assert filled > 2000 and mismatched == 0
    assert promote(m.con, late).status == "ALREADY_PROMOTED"  # replay changes nothing


def test_delivery_for_another_date_is_quarantined_not_raised(market):
    m = market
    other = (BHAV_DIR / "sec_bhavdata_full_12112026.csv").read_bytes()
    s = stage(m, bhav_bytes("20251014"), "20251014", other, "12112026")
    assert promote(m.con, s).status == "PROMOTED"
    (q,) = list_quarantine(m.con, reason_code="DELIVERY_DATE_MISMATCH")
    assert json.loads(q["details"])["delivery_date"] == "2026-11-12"
    assert m.con.execute("SELECT count(deliv_qty) FROM ohlcv").fetchone()[0] == 0


# ── P0-3 ────────────────────────────────────────────────────────────────────


@pytest.fixture
def unparsed_bonus(market):
    """PIDILITIND's real 1:1 bonus record with its purpose text made unreadable (in memory): UNPARSED."""
    m = market
    for d in ("20250922",):
        promote(m.con, m.stage_day(d))
    rows = json.loads(CA_JSON.read_bytes())
    for r in rows:
        if r["symbol"] == "PIDILITIND":
            r["subject"] = "Bonus issue one for one"
    s = stage_corp_actions(m.vault, m.stage_root, data=json.dumps(rows).encode(), source_url=CA_URL,
                           fetched_at=FETCHED_AT)  # fmt: skip
    assert promote(m.con, s).status == "PROMOTED"
    promote(m.con, m.stage_day("20250923"))
    m.pid = m.security_id("PIDILITIND")
    return m


def test_unparsed_action_is_superseded_by_a_verified_manual_fix(unparsed_bonus):
    m = unparsed_bonus
    (ca_q,) = list_quarantine(m.con, reason_code="UNPARSED_PURPOSE", security_id=m.pid)
    (gap,) = [
        q for q in list_quarantine(m.con, stage="GAP", security_id=m.pid) if q["reason_code"] == "UNEXPLAINED_GAP"
    ]
    assert [d for d, _ in adjusted_closes(m.con, m.pid)] == [date(2025, 9, 22)]  # frozen
    r = resolve_quarantine(m.con, gap["quarantine_id"], action="CORP_ACTION", note="1:1 bonus per NSE",
                           payload={"action_type": "BONUS", "ratio_num": 1, "ratio_den": 1})  # fmt: skip
    assert r["status"] == "VERIFIED_MANUAL" and r["superseded"] == [json.loads(ca_q["details"])["action_id"]]
    statuses = dict(
        m.con.execute("SELECT action_type, status FROM corp_actions WHERE security_id = ?", [m.pid]).fetchall()
    )
    assert statuses == {"UNKNOWN": "SUPERSEDED", "BONUS": "VERIFIED_MANUAL"}
    assert [d for d, _ in adjusted_closes(m.con, m.pid)] == [date(2025, 9, 22), date(2025, 9, 23)]  # unfrozen
    assert list_quarantine(m.con, reason_code="UNPARSED_PURPOSE", security_id=m.pid) == []  # closed by the fix


def test_reject_retires_a_quarantined_action(unparsed_bonus):
    m = unparsed_bonus
    (ca_q,) = list_quarantine(m.con, reason_code="UNPARSED_PURPOSE", security_id=m.pid)
    r = resolve_quarantine(m.con, ca_q["quarantine_id"], action="REJECT", note="not an action")
    assert r["rejected_action"] == json.loads(ca_q["details"])["action_id"]
    assert m.con.execute("SELECT status FROM corp_actions WHERE security_id = ?", [m.pid]).fetchone()[0] == "REJECTED"


# ── P0-4 ────────────────────────────────────────────────────────────────────


def test_system_knowledge_keeps_a_gap_frozen_until_it_was_resolved(market):
    """A gap on 23 Sep resolved (manually) on 1 Oct: in system knowledge, 23 Sep stays frozen and unadjusted;
    from 1 Oct it is explained. Valid knowledge (backtests) uses the correction for every date."""
    m = market
    for d in ("20250922", "20250923", "20251013"):
        promote(m.con, m.stage_day(d))
    pid = m.security_id("PIDILITIND")
    (gap,) = [q for q in list_quarantine(m.con, stage="GAP", security_id=pid) if q["reason_code"] == "UNEXPLAINED_GAP"]
    resolve_quarantine(m.con, gap["quarantine_id"], action="CORP_ACTION", note="1:1 bonus",
                       payload={"action_type": "BONUS", "ratio_num": 1, "ratio_den": 1})  # fmt: skip
    found, fixed = datetime(2025, 9, 23, 12, 0), datetime(2025, 10, 1, 6, 0)  # system times (UTC), set for the test
    m.con.execute("UPDATE quarantine_queue SET created_at = ? WHERE stage = 'GAP' AND security_id = ?", [found, pid])
    m.con.execute("UPDATE quarantine_queue SET resolved_at = ? WHERE quarantine_id = ?", [fixed, gap["quarantine_id"]])
    m.con.execute("UPDATE corp_actions SET decided_at = ? WHERE security_id = ?", [fixed, pid])

    def inputs(as_of, ts, knowledge):
        _, factors, frozen = _price_inputs(m.con, "NSE", as_of, knowledge, ts)
        return frozen.get(pid), [f[0] for f in factors.get(pid, [])]

    assert inputs(date(2025, 9, 23), datetime(2025, 9, 23, 18, 30), "system") == (date(2025, 9, 23), [])
    assert inputs(date(2025, 10, 13), datetime(2025, 10, 13, 18, 30), "system") == (None, [date(2025, 9, 23)])
    assert inputs(date(2025, 9, 23), datetime(2025, 9, 23, 18, 30), "valid") == (None, [date(2025, 9, 23)])
    with pytest.raises(ValueError, match="as_of_ts"):
        _price_inputs(m.con, "NSE", date(2025, 9, 23), "system")


def test_cli_rebuild_market_command(tmp_path):
    from financials.cli import main

    m = Market(tmp_path)
    for d in ("20250922", "20250923"):
        m.stage_day(d)
    m.con.close()
    assert main(["--data-dir", str(tmp_path), "promote"], out=io.StringIO()) == 0
    out = io.StringIO()
    assert main(["--data-dir", str(tmp_path), "rebuild-market", "--from", "2025-09-23"], out=out) == 0
    assert '"market_days_to_replay": 1' in out.getvalue() and "PROMOTED" in out.getvalue()
