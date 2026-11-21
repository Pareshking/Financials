"""QT X274 (owner decision U): restated comparatives. The point-in-time history keeps every figure as first filed (a
backtest sees only what was published then); a later filing's restated comparative is stored as that filing's own
fact, visible from its broadcast, and is what readers after that date use. Pinned on real pairs already in
tests/fixtures/annual_restated (X233 / X234):

- Vintage Coffee (VINCOFE) consolidated: Q4 FY25 results (7-May-2025) CFO -25.7608 Cr; the FY26 annual report
  (11-Nov-2026) restates FY25 CFO to -21.1632 Cr (moved between activities).
- BASF India consolidated: Q4 FY25 results (15-May-2025) total income 15,339.45 Cr; the FY26 annual report
  (10-Sep-2026) re-presents FY25 for a discontinued operation (14,859.16 Cr). Income-statement lines are the X100
  exception: for a period both cover, a results filing outranks the annual report, so the re-presented annual
  comparative is stored and visible (and reported by the X182 / X234 prior-year finding) but does not replace the
  results' figure; a restated comparative in a later results filing would (visibility order).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from conftest import FETCHED_AT

from _fixture_helpers import FIXTURES
from financials.fundamentals import load_factbook
from financials.promoter import promote
from financials.staging import stage_results_xbrl

D = FIXTURES / "annual_restated"
URL = "https://nsearchives.nseindia.com/corporate/xbrl/"
CR = Decimal(10) ** 7
FY25 = (date(2024, 4, 1), date(2025, 3, 31))


def _load(market, files):
    assert promote(market.con, market.stage_day("20250919")).status == "PROMOTED"
    for name, ts in files:
        r = promote(market.con, stage_results_xbrl(market.vault, market.stage_root, data=(D / name).read_bytes(),
                                                   source_url=URL + name, fetched_at=FETCHED_AT, broadcast_ts=ts,
                                                   broadcast_ts_source="API_FIELD"))  # fmt: skip
        assert r.status in ("PROMOTED", "QUARANTINED"), (name, r)
    return market.con.execute(
        "SELECT DISTINCT entity_id FROM filing_meta WHERE filing_id IN (SELECT filing_id FROM filings "
        "WHERE source_url = ?)", [URL + files[1][0]]).fetchone()[0]  # fmt: skip


def _stored(con, ent, tag):
    return con.execute(
        "SELECT m.accounting_profile, f.value_inr, f.visible_from_ts FROM fact_observations f JOIN filing_meta m "
        "USING (filing_id, parser_version) WHERE f.entity_id = ? AND f.scope = 'CONSOLIDATED' AND f.canonical_tag = ? "
        "AND f.period_start = ? AND f.period_end = ? ORDER BY f.visible_from_ts",
        [ent, tag, *FY25]).fetchall()  # fmt: skip


def test_x274_restated_comparative_is_visible_from_the_later_filing_only(market):
    files = (("INTEGRATED_FILING_INDAS_1433394_07052025082905_WEB.xml", datetime(2025, 5, 7, 14, 59, 6)),
             ("AR_XBRL_VINCOFE_11112026131428.xml", datetime(2026, 11, 11, 7, 44, 29)))  # fmt: skip
    ent = _load(market, files)
    con = market.con
    first, restated = _stored(con, ent, "cfo")  # both kept, each with its own filing's visibility
    assert (first[0], first[1], first[2] < datetime(2025, 6, 1)) == ("INDAS_CORP", Decimal("-257608000.00"), True)
    assert (restated[0], restated[1]) == ("REG34_ANNUAL", Decimal("-211632000.00"))
    assert restated[2] >= datetime(2026, 11, 11, 7, 44, 29)

    # A backtest dated before the annual report sees the figure as first filed ...
    assert load_factbook(con, ent, "CONSOLIDATED", datetime(2026, 11, 1)).durations["cfo"][FY25] == first[1]
    # ... and a reader after its broadcast the restated comparative.
    assert load_factbook(con, ent, "CONSOLIDATED", datetime(2026, 11, 18)).durations["cfo"][FY25] == restated[1]


def test_x274_income_statement_restatement_in_an_annual_report_is_the_x100_exception(market):
    files = (("INTEGRATED_FILING_INDAS_1439467_15052025103557_WEB.xml", datetime(2025, 5, 15, 5, 5, 58)),
             ("AR_XBRL_BASF_10092026090839.xml", datetime(2026, 9, 10, 3, 38, 39)))  # fmt: skip
    ent = _load(market, files)
    con = market.con
    first, re_presented = _stored(con, ent, "total_income")
    assert (first[0], first[1] / CR) == ("INDAS_CORP", Decimal("15339.45"))
    assert (re_presented[0], re_presented[1] / CR) == ("REG34_ANNUAL", Decimal("14859.16"))
    book = load_factbook(con, ent, "CONSOLIDATED", datetime(2026, 11, 18))
    assert book.durations["total_income"][FY25] == first[1]  # X100: results outrank the annual on P&L lines
    assert book.durations["pat_discontinued"][FY25] == 0  # the results line too: one presentation, not a mix
