"""Share cross-check net of employee-trust shares [X103].

Adani Wilmar (AWL) 30-Sep-2026: paid-up capital / face value = 1,291,800,000 shares (Q2 FY27 results, 1747073);
the Reg. 31 pattern (1734273) totals 1,299,678,605 shares including 7,860,970 held by employee benefit trusts.
Under Ind AS 32 trust-held shares are treasury shares deducted from equity share capital, so the results count is
the total less the trust shares (1,299,660,970; 0.001% off). The old check (0.61% off) failed 101 findings of 19
companies this way (live 2026-11-14).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from _fixture_helpers import XBRL_DIR
from financials.promoter import SHARE_CROSS_CHECK_TOLERANCE, promote, share_disagreement
from financials.staging import stage_results_xbrl, stage_shareholding

SHP = ("SHP_1734273_08102026033216_WEB.xml", datetime(2026, 10, 8, 3, 32))
RESULTS = ("INTEGRATED_FILING_INDAS_1747073_27102026063415_WEB.xml", datetime(2026, 10, 27, 6, 34))
AS_OF = date(2026, 9, 30)
URL = "https://nsearchives.nseindia.com/corporate/xbrl/"


def test_trust_held_shares_reconcile_paid_up_with_the_shareholding_total(market):
    promote(market.con, market.stage_day("20261112"))
    kw = dict(fetched_at=datetime(2026, 11, 14, 6), broadcast_ts_source="API_FIELD")
    s = promote(market.con, stage_shareholding(market.vault, market.stage_root, data=(XBRL_DIR / SHP[0]).read_bytes(),
                                               source_url=URL + SHP[0], broadcast_ts=SHP[1], **kw))  # fmt: skip
    r = promote(market.con, stage_results_xbrl(market.vault, market.stage_root,
                                               data=(XBRL_DIR / RESULTS[0]).read_bytes(),
                                               source_url=URL + RESULTS[0], broadcast_ts=RESULTS[1], **kw))  # fmt: skip
    assert s.status == r.status == "PROMOTED", (s, r)
    ent = market.con.execute("SELECT entity_id FROM filing_meta WHERE filing_id = ?", [r.message]).fetchone()[0]
    total, trust = (Decimal(v) for v in market.con.execute(
        "SELECT max(shares) FILTER (WHERE category = 'TOTAL'), max(shares) FILTER (WHERE category = 'EMPLOYEE_TRUSTS') "
        "FROM shareholding_observations WHERE entity_id = ? AND as_of_date = ?", [ent, AS_OF]).fetchone())  # fmt: skip
    paid = Decimal(market.con.execute(
        "SELECT max(value_other) FROM fact_observations WHERE entity_id = ? AND canonical_tag = 'shares_from_paid_up' "
        "AND period_end = ?", [ent, AS_OF]).fetchone()[0])  # fmt: skip
    assert (total, trust, paid) == (Decimal(1299678605), Decimal(7860970), Decimal(1291800000))
    assert abs(total - paid) / total > SHARE_CROSS_CHECK_TOLERANCE  # fails without the trust shares
    assert share_disagreement(market.con, ent, AS_OF) is None
    assert (
        market.con.execute("SELECT count(*) FROM quarantine_queue WHERE reason_code = 'CROSS_CHECK_FAILED'").fetchone()[
            0
        ]
        == 0
    )
