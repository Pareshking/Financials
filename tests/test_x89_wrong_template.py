"""X89, rule WRONG_TEMPLATE_DUPLICATE. MRPL Q1 FY26 was filed on 18 Jul 2025 on the non-Ind AS template (SEBI
`IntegratedFinance_OtherThanBank` taxonomy: ExtraordinaryItems, ProfitLossForPeriodBeforeMinorityInterest) and
re-filed on 19 Jul on the Ind AS template, per scope. The wrong-template filing stays UNKNOWN_TAXONOMY until an
Ind AS filing of the same entity, scope and period end is promoted; then the finding closes, in either order."""

from __future__ import annotations

from datetime import datetime

import pytest

from _fixture_helpers import XBRL_DIR
from financials.promoter import close_wrong_template_duplicates, promote
from financials.staging import stage_results_xbrl

WRONG = {"STANDALONE": "INTEGRATED_FILING_INDAS_1487244_18072025075933_WEB.xml",
         "CONSOLIDATED": "INTEGRATED_FILING_INDAS_1487257_18072025080410_WEB.xml"}  # fmt: skip
RIGHT = {"STANDALONE": "INTEGRATED_FILING_INDAS_1487538_19072025125012_WEB.xml",
         "CONSOLIDATED": "INTEGRATED_FILING_INDAS_1487540_19072025125103_WEB.xml"}  # fmt: skip


def _promote(market, name, ts):
    stage = stage_results_xbrl(market.vault, market.stage_root, data=(XBRL_DIR / name).read_bytes(),
                               source_url="https://nsearchives.nseindia.com/corporate/xbrl/" + name,
                               fetched_at=datetime(2026, 11, 14, 6), broadcast_ts=ts,
                               broadcast_ts_source="API_FIELD")  # fmt: skip
    return promote(market.con, stage)


def _open(market, name):
    return market.con.execute(
        "SELECT count(*) FROM quarantine_queue q JOIN filings f USING (filing_id) WHERE q.reason_code = "
        "'UNKNOWN_TAXONOMY' AND q.resolved_at IS NULL AND f.source_url LIKE ?",
        ["%" + name],
    ).fetchone()[0]


@pytest.mark.parametrize("right_first", [False, True])
def test_wrong_template_finding_closes_once_the_ind_as_filing_exists(market, right_first):
    promote(market.con, market.stage_day("20250228"))
    wrong_ts, right_ts = datetime(2025, 7, 18, 14, 29), datetime(2025, 7, 19, 7, 20)
    if right_first:
        assert _promote(market, RIGHT["STANDALONE"], right_ts).status == "PROMOTED"
    r = _promote(market, WRONG["STANDALONE"], wrong_ts)
    assert r.status == "QUARANTINED"
    assert _promote(market, WRONG["CONSOLIDATED"], wrong_ts).status == "QUARANTINED"
    if not right_first:
        assert close_wrong_template_duplicates(market.con) == 0
        assert _promote(market, RIGHT["STANDALONE"], right_ts).status == "PROMOTED"
    assert close_wrong_template_duplicates(market.con) == 1  # standalone only: no consolidated Ind AS filing yet
    assert (_open(market, WRONG["STANDALONE"]), _open(market, WRONG["CONSOLIDATED"])) == (0, 1)
    note = market.con.execute("SELECT resolution_note FROM quarantine_queue WHERE filing_id = ?",
                              [r.message]).fetchone()[0]  # fmt: skip
    assert note.startswith("X89 WRONG_TEMPLATE_DUPLICATE")
    assert _promote(market, RIGHT["CONSOLIDATED"], right_ts).status == "PROMOTED"
    assert close_wrong_template_duplicates(market.con) == 1
    assert _open(market, WRONG["CONSOLIDATED"]) == 0
