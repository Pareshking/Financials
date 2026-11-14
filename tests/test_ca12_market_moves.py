"""CA12: an equity gap <= 20% with no corporate action within 7 days, in a feed that covers the date, is a market move.

Real days 13-14 Oct 2025 and the real 15 Sep - 17 Oct 2025 corporate-action window. 14 Oct + 7 days falls outside that
window, so its gaps stay open until the next window (18 Oct - 16 Nov, here an in-memory empty answer) is promoted:
coverage is the union of contiguous windows."""

from __future__ import annotations

import json

from conftest import FETCHED_AT

from _fixture_helpers import FIXTURES
from financials.promoter import promote
from financials.staging import stage_corp_actions

CA = FIXTURES / "corp_actions" / "nse_corporateActions_equities_15-09-2025_17-10-2025.json"
URL = "https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=15-09-2025&to_date=17-10-2025"


def _open_gaps(con):
    return con.execute(
        "SELECT q.security_id, CAST(json_extract_string(q.details, '$.gap') AS DOUBLE), h.isin FROM quarantine_queue q "
        "JOIN security_identifier_history h ON h.security_id = q.security_id AND h.valid_to IS NULL "
        "WHERE q.reason_code = 'UNEXPLAINED_GAP' AND q.resolved_at IS NULL "
        "AND json_extract_string(q.details, '$.trade_date') = '2025-10-14'"
    ).fetchall()


def test_small_equity_gaps_without_nearby_actions_close_once_the_feed_covers_the_date(market):
    m = market
    for d in ("20251013", "20251014"):
        promote(m.con, m.stage_day(d))
    before = _open_gaps(m.con)
    assert any(abs(g) <= 0.2 and isin.startswith("INE") for _, g, isin in before)  # nothing covers the date yet
    s = stage_corp_actions(m.vault, m.stage_root, data=CA.read_bytes(), source_url=URL, fetched_at=FETCHED_AT)
    assert promote(m.con, s).status == "PROMOTED"
    assert (
        m.con.execute("SELECT count(*) FROM quarantine_queue WHERE resolution_note LIKE '%[CA12]'").fetchone()[0] == 0
    )
    nxt = URL.replace("from_date=15-09-2025&to_date=17-10-2025", "from_date=18-10-2025&to_date=16-11-2025")
    s2 = stage_corp_actions(m.vault, m.stage_root, data=b"[]", source_url=nxt, fetched_at=FETCHED_AT)
    assert promote(m.con, s2).status == "PROMOTED"
    after = _open_gaps(m.con)
    acted = {r[0] for r in m.con.execute(
        "SELECT security_id FROM corp_actions WHERE ex_date BETWEEN DATE '2025-10-07' AND DATE '2025-10-21'"
    ).fetchall()}  # fmt: skip
    for sec, gap, isin in after:  # what stays open is exactly what the rule must not touch
        assert abs(gap) > 0.2 or not isin.startswith("INE") or sec in acted, (sec, gap, isin)
    closed = m.con.execute("SELECT count(*) FROM quarantine_queue WHERE resolution_note LIKE '%[CA12]'").fetchone()[0]
    assert closed > 0 and len(after) < len(before)
    notes = {json.loads(d)["trade_date"] for (d,) in m.con.execute(
        "SELECT details FROM quarantine_queue WHERE resolution_note LIKE '%[CA12]'").fetchall()}  # fmt: skip
    assert notes == {"2025-10-14"}
