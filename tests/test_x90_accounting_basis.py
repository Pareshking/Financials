"""X90: a FactBook never combines accounting bases (invariant 6). Go Digit filed Q1 FY27 as an IRDAI Indian-GAAP
general insurer (PBT 115.45 Cr) and Q2 FY27 under Ind AS 117 (H1 PBT 696.14 Cr, whose Q1 is 505.96 Cr in the
Ind AS PDF). Mixing them made Q2 = H1 - Q1 = 580.69 Cr and broke the YTD identity. After the change of basis
only the Ind AS facts are used: Q2 is the filed quarter and no cross-basis quarter is derived."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from _fixture_helpers import XBRL_DIR
from financials.fundamentals import load_factbook
from financials.promoter import promote
from financials.staging import stage_results_xbrl

Q1_IRDAI = "INTEGRATED_FILING_GI_1700274_23072026063349_WEB.xml"
Q2_INDAS = "IF_INS_COM_IND_AS_21009_WebXMLFile_20261105_192422730.xml"
H1 = (date(2026, 4, 1), date(2026, 9, 30))
Q1 = (date(2026, 4, 1), date(2026, 6, 30))


def _promote(m, name, ts):
    r = promote(m.con, stage_results_xbrl(m.vault, m.stage_root, data=(XBRL_DIR / name).read_bytes(),
                                          source_url="https://nsearchives.nseindia.com/corporate/xbrl/" + name,
                                          fetched_at=datetime(2026, 11, 14, 6), broadcast_ts=ts,
                                          broadcast_ts_source="API_FIELD"))  # fmt: skip
    assert r.status == "PROMOTED", r
    return r.message


def test_change_of_accounting_basis_drops_the_older_basis(market):
    promote(market.con, market.stage_day("20261112"))
    _promote(market, Q1_IRDAI, datetime(2026, 7, 23, 13, 4))
    fid = _promote(market, Q2_INDAS, datetime(2026, 11, 5, 14, 0))
    profiles = dict(market.con.execute("SELECT filing_id, accounting_profile FROM filing_meta").fetchall())
    assert sorted(profiles.values()) == ["INDAS_INSURANCE", "IRDAI_GENERAL"]
    ent = market.con.execute("SELECT entity_id FROM filing_meta WHERE filing_id = ?", [fid]).fetchone()[0]

    before = load_factbook(market.con, ent, "STANDALONE", datetime(2026, 8, 1))  # only the IRDAI Q1 is visible
    assert before.durations["pbt"][Q1] == Decimal("1154500000")

    after = load_factbook(market.con, ent, "STANDALONE", datetime(2026, 11, 13))
    assert Q1 not in after.durations["pbt"]  # the IRDAI Q1 is not combined with Ind AS figures
    assert after.durations["pbt"][H1] == Decimal("6961400000")
    assert after.quarter("pbt", date(2026, 9, 30)) == Decimal("1901800000")  # the filed Ind AS quarter
    assert after.ytd_breaks("pbt") == []
