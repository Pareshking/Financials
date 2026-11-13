"""Audited quarantine resolution (D-6) on real fixture days."""

import io
import json
from datetime import date

import pytest
from conftest import Market

from financials.admin import AdminError, list_quarantine, resolve_quarantine
from financials.cli import main
from financials.promoter import adjusted_closes, promote


@pytest.fixture
def mkt(tmp_path):
    """22-23 Sep 2025 (PIDILITIND bonus, unrecorded), 13 Oct 2025 and 12 Nov 2026 (SIGMA collision)."""
    m = Market(tmp_path)
    for d in ("20250922", "20250923", "20251013", "20261112"):
        assert promote(m.con, m.stage_day(d)).status == "PROMOTED"
    yield m
    m.con.close()


def sec(m, symbol):
    rows = m.con.execute(
        "SELECT DISTINCT security_id FROM security_identifier_history WHERE symbol = ?", [symbol]
    ).fetchall()
    return [r[0] for r in rows]


def gap_q(m, symbol, d):
    (s,) = sec(m, symbol)
    rows = list_quarantine(m.con, stage="GAP", security_id=s, include_resolved=True)
    return [r for r in rows if json.loads(r["details"])["trade_date"] == str(d)]


def test_list_filters(mkt):
    collisions = list_quarantine(mkt.con, reason_code="ISIN_COLLISION")
    assert len(collisions) == 1 and json.loads(collisions[0]["details"])["isin"] == "INE0A0S01028"
    assert all(r["stage"] == "GAP" for r in list_quarantine(mkt.con, stage="GAP", limit=50))
    assert list_quarantine(mkt.con, reason_code="NOPE") == []


def test_merge_resolves_sigma_split_plus_series_collision(mkt):
    """[P14] SIGMA: EQ INE0A0S01010 (16658) -> BE INE0A0S01028 (16664) -> EQ INE0A0S01028 (16658)."""
    m = mkt
    assert len(sec(m, "SIGMA")) == 2
    (q,) = list_quarantine(m.con, reason_code="ISIN_COLLISION")
    r = resolve_quarantine(m.con, q["quarantine_id"], action="MERGE_SECURITIES", note="SIGMA split 2025-10-06 + BE")
    assert r["bars_loaded"] == 1
    (keep,) = sec(m, "SIGMA")
    hist = m.con.execute(
        "SELECT series, isin, fin_instrm_id, valid_from, valid_to FROM security_identifier_history "
        "WHERE security_id = ? ORDER BY valid_from",
        [keep],
    ).fetchall()
    assert hist == [
        ("EQ", "INE0A0S01010", "16658", date(2025, 9, 22), date(2025, 10, 13)),
        ("BE", "INE0A0S01028", "16664", date(2025, 10, 13), date(2026, 11, 12)),
        ("EQ", "INE0A0S01028", "16658", date(2026, 11, 12), None),
    ]
    bars = m.con.execute("SELECT trade_date FROM ohlcv WHERE security_id = ? ORDER BY 1", [keep]).fetchall()
    assert [b[0] for b in bars] == [date(2025, 9, 22), date(2025, 9, 23), date(2025, 10, 13), date(2026, 11, 12)]
    row = m.con.execute("SELECT resolved_at, resolution, resolution_note FROM quarantine_queue WHERE quarantine_id = ?",
                        [q["quarantine_id"]]).fetchone()  # fmt: skip
    assert row[0] is not None and row[1:] == ("OVERRIDDEN", "SIGMA split 2025-10-06 + BE")
    ovr = m.con.execute("SELECT field, value FROM company_overrides").fetchall()
    assert [o[0] for o in ovr] == ["merged_security"]
    with pytest.raises(AdminError, match="already resolved"):
        resolve_quarantine(m.con, q["quarantine_id"], action="ACCEPT", note="again")


def test_corp_action_resolution_verifies_and_unfreezes(mkt):
    m = mkt
    (q,) = [r for r in gap_q(m, "PIDILITIND", date(2025, 9, 23)) if r["reason_code"] == "UNEXPLAINED_GAP"]
    (pid,) = sec(m, "PIDILITIND")
    assert [d for d, _ in adjusted_closes(m.con, pid)] == [date(2025, 9, 22)]  # frozen
    with pytest.raises(AdminError, match="does not explain the gap"):
        resolve_quarantine(m.con, q["quarantine_id"], action="CORP_ACTION", note="wrong ratio",
                           payload={"action_type": "BONUS", "ratio_num": 1, "ratio_den": 2})  # fmt: skip
    assert m.con.execute("SELECT count(*) FROM corp_actions").fetchone()[0] == 0  # rolled back
    r = resolve_quarantine(m.con, q["quarantine_id"], action="CORP_ACTION", note="1:1 bonus per NSE",
                           payload={"action_type": "BONUS", "ratio_num": 1, "ratio_den": 1})  # fmt: skip
    assert r["status"] == "VERIFIED"
    closes = dict(adjusted_closes(m.con, pid))
    assert closes[date(2025, 9, 22)] == closes[date(2025, 9, 22)].__class__("1519.0000")
    assert date(2025, 9, 23) in closes


def test_accept_and_validation(mkt):
    m = mkt
    q = list_quarantine(m.con, stage="GAP", limit=1)[0]
    with pytest.raises(AdminError, match="note is required"):
        resolve_quarantine(m.con, q["quarantine_id"], action="ACCEPT", note=" ")
    with pytest.raises(AdminError, match="action must be"):
        resolve_quarantine(m.con, q["quarantine_id"], action="DELETE", note="x")
    with pytest.raises(AdminError, match="ISIN_COLLISION"):
        resolve_quarantine(m.con, q["quarantine_id"], action="MERGE_SECURITIES", note="x")
    resolve_quarantine(m.con, q["quarantine_id"], action="ACCEPT", note="genuine news-driven move")
    assert q["quarantine_id"] not in {r["quarantine_id"] for r in list_quarantine(m.con, limit=10_000)}
    assert q["quarantine_id"] in {r["quarantine_id"] for r in list_quarantine(m.con, include_resolved=True,
                                                                               limit=10_000)}  # fmt: skip


def test_cli_list_and_resolve(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    m = Market(data)  # same layout the CLI uses: data/vault, data/staging, data/market.duckdb
    for d in ("20250923", "20251013", "20261112"):
        promote(m.con, m.stage_day(d))
    m.con.close()

    out = io.StringIO()
    assert main(["--data-dir", str(data), "quarantine", "list", "--reason", "ISIN_COLLISION"], out=out) == 0
    (row,) = json.loads(out.getvalue())
    out = io.StringIO()
    code = main(["--data-dir", str(data), "quarantine", "resolve", "--id", row["quarantine_id"], "--action",
                 "MERGE_SECURITIES", "--note", "SIGMA merge"], out=out)  # fmt: skip
    assert code == 0 and json.loads(out.getvalue())["bars_loaded"] == 1
    out = io.StringIO()
    code = main(["--data-dir", str(data), "quarantine", "resolve", "--id", "nope", "--action", "ACCEPT", "--note",
                 "x"], out=out)  # fmt: skip
    assert code == 1 and "unknown quarantine id" in out.getvalue()
