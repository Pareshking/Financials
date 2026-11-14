"""One database, every real fixture: all results profiles (Ind AS corporate standalone + consolidated incl. excise FMCG
and new-gen tech, lending NBFC, private + PSU banks, life, general and Ind AS 117 insurers), Reg. 34 annual, Reg. 31
shareholding (pledges, no-promoter bank), Reg. 30 events, ten bhavcopy days (two with delivery), corporate actions,
the holiday master and the Nifty 500 snapshot. Promoted together through `promote`, then materialised and screened.

Broadcast times are set (fixed, before the materialised date) because the fixtures' own listing times are not all
committed; nothing else is synthetic. The expected quarantines are the documented ones, so any new cross-profile
collision or regression shows up as a changed count or reason here.
"""

from __future__ import annotations

import io
from collections import Counter
from datetime import date, datetime

import pytest
from conftest import FETCHED_AT, Market

from _fixture_helpers import FIXTURES, XBRL_DIR
from financials.cli import promote_pending
from financials.dsl import run_screen
from financials.features import materialize
from financials.promoter import index_members, total_return
from financials.staging import (
    stage_corp_actions,
    stage_holidays,
    stage_index_snapshot,
    stage_reg30_event,
    stage_results_xbrl,
    stage_shareholding,
)

ARCHIVE = "https://nsearchives.nseindia.com/corporate/xbrl/"
FILED, EVENTS = datetime(2026, 11, 12, 6, 0), datetime(2026, 11, 13, 8, 0)  # UTC
AS_OF = date(2026, 11, 13)


@pytest.fixture(scope="module")
def unified(tmp_path_factory):
    m = Market(tmp_path_factory.mktemp("unified"))
    for d in ("20250919", "20250922", "20250923", "20251013", "20251017", "20251020", "20251021", "20251023"):
        m.stage_day(d)
    m.stage_day("20251014", with_delivery=True)
    m.stage_day("20261112", with_delivery=True)
    fx = FIXTURES
    stage_corp_actions(
        m.vault,
        m.stage_root,
        fetched_at=FETCHED_AT,
        source_url="nse-ca",
        data=(fx / "corp_actions" / "nse_corporateActions_equities_15-09-2025_17-10-2025.json").read_bytes(),
    )
    stage_holidays(
        m.vault,
        m.stage_root,
        fetched_at=FETCHED_AT,
        source_url="nse-hol",
        data=(fx / "calendar" / "nse_holiday-master_trading_20261113.json").read_bytes(),
    )
    stage_index_snapshot(m.vault, m.stage_root, fetched_at=FETCHED_AT, source_url="nse-idx", index_name="NIFTY 500",
                         snapshot_date=date(2026, 11, 12),
                         data=(fx / "indices" / "ind_nifty500list_20261113.csv").read_bytes())  # fmt: skip
    for p in sorted(XBRL_DIR.glob("*.xml")):
        stage = stage_shareholding if p.name.startswith("SHP_") else stage_results_xbrl
        stage(m.vault, m.stage_root, data=p.read_bytes(), source_url=ARCHIVE + p.name, fetched_at=FETCHED_AT,
              broadcast_ts=FILED, broadcast_ts_source="API_FIELD")  # fmt: skip
    for p in sorted((fx / "events").glob("*.xml")):
        if not p.name.startswith("nse_"):
            stage_reg30_event(
                m.vault,
                m.stage_root,
                data=p.read_bytes(),
                source_url=ARCHIVE + p.name,
                fetched_at=FETCHED_AT,
                broadcast_ts=EVENTS,
                broadcast_ts_source="RSS_PUBDATE",
            )
    out = io.StringIO()
    m.pending = promote_pending(m.con, m.stage_root, out)
    m.log = [ln.split()[:2] for ln in out.getvalue().splitlines()]
    m.materialized = materialize(m.con, AS_OF)
    yield m
    m.con.close()


def test_every_batch_promotes_with_only_the_documented_exceptions(unified):
    m = unified
    assert m.pending == 0
    assert Counter(tuple(x) for x in m.log) == {
        ("PROMOTED", "market_day"): 10, ("PROMOTED", "holidays"): 1, ("PROMOTED", "index_snapshot"): 1,
        ("PROMOTED", "corp_actions"): 1, ("PROMOTED", "results_xbrl"): 72, ("PROMOTED", "shareholding"): 13,
        ("PROMOTED", "reg30_event"): 8,
        ("QUARANTINED", "results_xbrl"): 1,  # OLAELEC: owners + NCI identity fails in the filing itself
        ("OUT_OF_SCOPE", "results_xbrl"): 1,  # Star Health Q3 FY25 legacy GI file (period end before C9)
        ("QUARANTINED", "reg30_event"): 1,  # SHANTHALA fraud disclosure: SME series, outside the universe
    }  # fmt: skip


def test_quarantine_reasons_are_the_documented_ones(unified):
    reasons = {
        r
        for (r,) in unified.con.execute(
            "SELECT DISTINCT stage || '/' || reason_code FROM quarantine_queue WHERE resolved_at IS NULL"
        ).fetchall()
    }
    assert reasons == {
        "CALENDAR/MISSING_SESSION",  # sparse fixture days (CAL3): 23 Sep -> 13 Oct, 14 -> 17 Oct, 23 Oct -> 12 Nov
        "GAP/UNEXPLAINED_GAP",
        "GAP/ISIN_CHANGE_WITHOUT_ACTION",  # mostly across those missing sessions
        "CORP_ACTION/STALE_ISIN_OTHER_ISSUER",  # PREMIERPOL changed issuer code [CA7]
        "IDENTIFIER/ISIN_COLLISION",  # SIGMA split + series change [P14]
        "IDENTITY/OWNERS_PLUS_NCI",
        "IDENTITY/UNKNOWN_SYMBOL",  # OLAELEC, SHANTHALA
        "INDEX/PLACEHOLDER_ISIN",
        "INDEX/UNKNOWN_ISIN",  # IDX2, IDX3
        "SHARES/CROSS_CHECK_FAILED",  # Reg. 31 vs paid-up 1.9% apart for one issuer (owner tolerance 0.5%)
        "CONSISTENCY/YTD_QUARTER_MISMATCH",  # Tata Motors FY26 standalone: Q1 re-presented after the demerger [X80]
    }
    ytd = unified.con.execute(
        "SELECT DISTINCT h.symbol, json_extract_string(q.details, '$.tag') FROM quarantine_queue q "
        "JOIN securities s USING (entity_id) JOIN security_identifier_history h ON h.security_id = s.security_id "
        "WHERE q.reason_code = 'YTD_QUARTER_MISMATCH'").fetchall()  # fmt: skip
    assert {t for _, t in ytd} == {"revenue_from_operations", "total_income", "pbt"}
    assert {s for s, _ in ytd} >= {"TATAMOTORS"}


def test_all_profiles_and_scopes_land_without_collisions(unified):
    con = unified.con
    assert dict(((p, s), n) for p, s, n in con.execute(
        "SELECT accounting_profile, scope, count(*) FROM filing_meta GROUP BY ALL").fetchall()) == {
        ("INDAS_CORP", "CONSOLIDATED"): 24, ("INDAS_CORP", "STANDALONE"): 15, ("INDAS_NBFC", "CONSOLIDATED"): 5,
        ("INDAS_NBFC", "STANDALONE"): 2, ("IGAAP_BANK", "CONSOLIDATED"): 5, ("IGAAP_BANK", "STANDALONE"): 5,
        ("IRDAI_LIFE", "CONSOLIDATED"): 1, ("IRDAI_LIFE", "STANDALONE"): 3, ("IRDAI_GENERAL", "CONSOLIDATED"): 1,
        ("IRDAI_GENERAL", "STANDALONE"): 3, ("INDAS_INSURANCE", "STANDALONE"): 2,
        ("REG34_ANNUAL", "CONSOLIDATED"): 4, ("REG34_ANNUAL", "STANDALONE"): 2,
    }  # fmt: skip
    # one results profile per entity (Reg. 34 annual sits beside its company's quarterly profile)
    assert (
        con.execute(
            "SELECT count(*) FROM (SELECT entity_id FROM filing_meta WHERE accounting_profile <> 'REG34_ANNUAL' "
            "GROUP BY 1 HAVING count(DISTINCT accounting_profile) > 1)"
        ).fetchone()[0]
        == 0
    )
    # every filing's facts belong to the entity of that filing
    assert (
        con.execute(
            "SELECT count(*) FROM fact_observations f JOIN filing_meta m USING (filing_id) "
            "WHERE f.entity_id <> m.entity_id"
        ).fetchone()[0]
        == 0
    )


def test_materialised_universe_spans_every_archetype_and_screens_run(unified):
    m = unified
    assert m.materialized.status == "PROMOTED" and m.materialized.rows > 2900
    arche = dict(m.con.execute(
        "SELECT valuation_archetype, count(*) FROM screener_features WHERE valuation_archetype IS NOT NULL "
        "GROUP BY 1").fetchall())  # fmt: skip
    assert set(arche) == {"INDUSTRIAL_SERVICES", "FINANCIAL_LENDING", "INSURANCE", "NEW_GEN_TECH"}

    def syms(q):
        return {r["symbol"] for r in run_screen(m.con, q)}

    # Reg. 34 annual; SPARC FY26 as filed: PBT 15,530,099,000 on revenue 18,791,683,000 (FY25 PBT -3,427,812,000)
    assert syms("Piotroski F score >= 0 AND ROCE screener > 0") == {"TCS", "ETERNAL", "SPARC"}
    assert syms("Debtor days > 0") >= {"TCS", "ITC", "RELIANCE"}  # industrial, incl. excise FMCG
    assert syms("GNPA > 0") >= {"HDFCBANK", "PNB"}  # private + PSU banks
    assert syms("Solvency ratio > 0") >= {"HDFCLIFE", "SBILIFE", "ICICIGI"}  # life + general insurers
    assert syms("Promoter holding > 0 AND Market Cap > 0") >= {"ELIN", "JSWSTEEL"}  # Reg. 31
    assert syms("Order wins 90d > 0") == {"BEL", "JSWINFRA", "APTECHT"}  # Reg. 30, visible 13 Nov
    assert len(index_members(m.con, "NIFTY 500", date(2026, 11, 12))) >= 495  # PIT membership from the snapshot


def test_market_data_layers_coexist(unified):
    con = unified.con
    assert con.execute("SELECT count(deliv_qty) FROM ohlcv WHERE trade_date = '2026-11-12'").fetchone()[0] > 2000
    cal = dict(con.execute("SELECT source, count(*) FROM trading_calendar GROUP BY 1").fetchall())
    # CAL3: 20-21 Sep, 18-19 Oct (weekends) and 22 Oct (Balipratipada)
    assert cal["BHAVCOPY"] == 10 and cal["HOLIDAY_MASTER"] >= 15 and cal["INFERRED_PREV_CLOSE"] == 5
    adani = con.execute("SELECT DISTINCT security_id FROM security_identifier_history WHERE symbol = 'ADANIPOWER'"
                        ).fetchone()[0]  # fmt: skip
    tri = dict(total_return(con, adani))
    assert date(2025, 9, 22) in tri and tri[date(2025, 9, 19)] == 100  # through its 1:5 split [CA2]
    assert con.execute("SELECT status FROM corp_actions WHERE security_id = ? AND action_type = 'SPLIT'",
                       [adani]).fetchone()[0] == "VERIFIED"  # fmt: skip


def test_bundle_round_trip_reproduces_every_table(unified, tmp_path):
    """export-bundle -> import-bundle into a new database: identical row counts and checksums for every table;
    a tiny per-file cap forces sharding; the total budget is enforced."""
    from financials.bundle import BundleError, export_bundle, import_bundle, table_checksum

    m = export_bundle(unified.con, tmp_path / "b", max_file_mb=0.5)
    assert "raw_xbrl_facts" not in m["tables"] and m["tables"]["ohlcv"]["files"] > 1
    assert all(v["max_file_bytes"] < 0.5 * 2**20 for v in m["tables"].values())
    rows = import_bundle(tmp_path / "b", tmp_path / "copy.duckdb")
    assert rows["fact_observations"] == unified.con.execute("SELECT count(*) FROM fact_observations").fetchone()[0]
    from financials.db import connect

    copy = connect(tmp_path / "copy.duckdb", read_only=True)
    try:
        for t in ("ohlcv", "fact_observations", "screener_features_history", "quarantine_queue", "corp_actions"):
            assert table_checksum(copy, t) == table_checksum(unified.con, t), t
    finally:
        copy.close()
    with pytest.raises(BundleError, match="budget"):
        export_bundle(unified.con, tmp_path / "small", max_total_mb=0.1)
