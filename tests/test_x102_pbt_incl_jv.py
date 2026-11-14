"""PBT including the JV share, placement-independent [X102].

Finolex Cables FY26 consolidated: Q1 (1510705) files PBT 176.37 Cr before its JV share 26.18 (tagged after PBT);
Q2 (1571804) books the JV share inside PBT as an exceptional item 38.11 and tags the JV element 0, PBT 206.20; its H1
PBT 408.75 = 202.55 + 206.20. Filed PBT changes definition between quarters, so the YTD identity broke on PBT
(18 of 537 open items, live 2026-11-14); PBT + JV share holds in both placements.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from _fixture_helpers import XBRL_DIR
from financials.fundamentals import load_factbook
from financials.promoter import promote
from financials.staging import stage_results_xbrl

Q1 = ("INTEGRATED_FILING_INDAS_1510705_13082025092940_WEB.xml", datetime(2025, 8, 13, 9, 29))
Q2 = ("INTEGRATED_FILING_INDAS_1571804_11112025093544_WEB.xml", datetime(2025, 11, 11, 9, 35))
P1, P2, H1 = (
    (date(2025, 4, 1), date(2025, 6, 30)),
    (date(2025, 7, 1), date(2025, 9, 30)),
    (date(2025, 4, 1), date(2025, 9, 30)),
)


def test_pbt_including_jv_share_keeps_the_ytd_identity(market):
    promote(market.con, market.stage_day("20251023"))
    fid = None
    for name, ts in (Q1, Q2):
        data = (XBRL_DIR / name).read_bytes()
        r = promote(market.con, stage_results_xbrl(market.vault, market.stage_root, data=data,
                    source_url="https://nsearchives.nseindia.com/corporate/xbrl/" + name,
                    fetched_at=datetime(2026, 11, 14, 6), broadcast_ts=ts,
                    broadcast_ts_source="API_FIELD"))  # fmt: skip
        assert r.status == "PROMOTED", r
        fid = r.message
    ent = market.con.execute("SELECT entity_id FROM filing_meta WHERE filing_id = ?", [fid]).fetchone()[0]
    book = load_factbook(market.con, ent, "CONSOLIDATED", datetime(2026, 11, 13))
    pbt, jv, incl = (book.durations[t] for t in ("pbt", "share_of_associates_jv", "pbt_incl_jv"))
    assert (pbt[P1], jv[P1]) == (Decimal("1763700000"), Decimal("261800000"))  # JV after PBT
    assert (pbt[P2], jv[P2]) == (Decimal("2062000000"), Decimal(0))  # JV inside PBT (exceptional 38.11 Cr)
    assert incl[P1] + incl[P2] == incl[H1] == Decimal("4087500000")
    assert [b["ytd_period"] for b in book.ytd_breaks("pbt")] == [[str(H1[0]), str(H1[1])]]  # filed PBT breaks
    assert book.ytd_breaks("pbt_incl_jv") == []
