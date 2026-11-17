"""X83 VISIBILITY_FROM_LISTING_CREATION and order-independent revision links (E9).

ADANIGREEN re-filed its Q2 FY26 financials XBRL on 27 Jan 2026 (listing `broadcast_Date` null, `creation_Date`
27-Jan-2026 15:16:52, `revision_Remark` "Revised Integrated Filing ..."). The board-meeting rule alone would make that
file visible from the day after the October 2025 board meeting, three months before it existed."""

from __future__ import annotations

import json
from datetime import date, datetime

from _fixture_helpers import FIXTURES
from financials.db import apply_schema, connect, insert_rows
from financials.fundamentals import load_factbook
from financials.parsers.discovery import filename_ts_bounds, parse_integrated_filing_listing
from financials.promoter import _link_revision, _visible_from
from financials.staging import results_listing_rows
from financials.timeutil import ist_to_utc

DISC = FIXTURES / "discovery"
ADANI = DISC / "nse_integrated-filing-results_equities_ADANIGREEN_20261114.json"
TCS = DISC / "nse_integrated-filing-results_equities_TCS_20261113.json"
REVISED_URL = "https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1610360_27012026031651_WEB.xml"


def _utc(s: str) -> datetime:
    d = datetime.fromisoformat(s)
    return ist_to_utc(d.date(), d.time())


def test_broadcast_is_null_exactly_on_revised_rows_and_creation_is_always_there():
    rows = json.loads(ADANI.read_bytes())["data"]
    assert rows and all(r["creation_Date"] for r in rows)
    assert {bool(r["broadcast_Date"]) for r in rows} == {True, False}
    for r in rows:
        assert (r["broadcast_Date"] is None) == (r["revised_Date"] is not None), r["xbrl"]
    entries = {e.xbrl_url: e for e in parse_integrated_filing_listing(ADANI.read_bytes(), results_only=False)}
    e = entries[REVISED_URL]
    assert e.broadcast_ts_ist is None and e.visible_ts_ist == datetime(2026, 1, 27, 15, 16, 52)
    assert e.revision_remark.startswith("Revised Integrated Filing")


def test_file_name_is_a_twelve_hour_clock():
    for path in (TCS, ADANI):
        for e in parse_integrated_filing_listing(path.read_bytes(), results_only=False):
            lo, hi = filename_ts_bounds(e.xbrl_url)
            assert (hi - lo).total_seconds() == 12 * 3600
            # the creation time is one of the two readings, to the minute
            assert min(abs((t - e.creation_ts_ist).total_seconds()) for t in (lo, hi)) < 120, e.xbrl_url


def _db():
    con = connect()
    apply_schema(con)
    insert_rows(con, "blobs", [{"sha256": "lst", "byte_size": 1, "media_type": "application/json",
                                "storage_path": "p", "first_fetched_at": datetime(2026, 11, 14)}])  # fmt: skip
    insert_rows(con, "filings", [{"filing_id": "lst", "sha256": "lst", "exchange": "NSE",
                                  "category": "RESULTS_LISTING", "source_url": "u", "broadcast_ts_source": "UNKNOWN",
                                  "fetched_at": datetime(2026, 11, 14)}])  # fmt: skip
    insert_rows(con, "trading_calendar", [{"exchange": "NSE", "cal_date": date(2025, 10, 29), "is_trading": True}])
    return con


BOARD_END = ist_to_utc(date(2025, 10, 28), datetime(2025, 1, 1, 17, 0).time())


def test_revised_filing_is_visible_from_its_creation_not_the_board_meeting():
    con = _db()
    board_only, src = _visible_from(con, "NSE", None, BOARD_END, date(2025, 10, 28))
    assert (board_only, src) == (ist_to_utc(date(2025, 10, 29), datetime.min.time()), "BOARD_MEETING_RULE")
    # without listing evidence: the file name (read as PM) lifts the board-meeting rule
    v, src = _visible_from(con, "NSE", None, BOARD_END, date(2025, 10, 28), REVISED_URL)
    assert (v, src) == (_utc("2026-01-27T15:16:51"), "FILENAME_TS")
    # with the vaulted listing: its creation time
    insert_rows(con, "raw_results_listing", results_listing_rows("lst", ADANI.read_bytes()))
    v, src = _visible_from(con, "NSE", None, BOARD_END, date(2025, 10, 28), REVISED_URL)
    assert (v, src) == (_utc("2026-01-27T15:16:52"), "LISTING_CREATION")


def test_broadcast_older_than_the_file_is_lifted_to_the_file_time():
    con = _db()
    url = "https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1613354_29012026060934_WEB.xml"
    bcast = datetime(2026, 1, 27, 14, 39, 13)  # live: API broadcast_Date two days before the file was made
    v, src = _visible_from(con, "NSE", bcast, None, None, url)
    assert (v, src) == (_utc("2026-01-29T06:09:34"), "FILENAME_TS")
    on_time = "https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1743133_21102026051244_WEB.xml"
    b = _utc("2026-10-21T17:12:44")
    assert _visible_from(con, "NSE", b, None, None, on_time) == (b, "BROADCAST")


def _meta_db():
    con = _db()
    insert_rows(con, "entity_master", [{"entity_id": "e", "legal_name": "E"}])
    return con


def _filing(con, fid: str, sha: str, versions: list[tuple[str, datetime]], value: str):
    insert_rows(con, "blobs", [{"sha256": sha, "byte_size": 1, "media_type": "x", "storage_path": sha,
                                "first_fetched_at": datetime(2026, 11, 14)}], or_ignore=True)  # fmt: skip
    insert_rows(con, "filings", [{"filing_id": fid, "sha256": sha, "exchange": "NSE", "category": "RESULTS_XBRL",
                                  "source_url": fid, "broadcast_ts_source": "UNKNOWN",
                                  "fetched_at": datetime(2026, 11, 14)}])  # fmt: skip
    for pv, vis in versions:
        insert_rows(con, "filing_meta", [{"filing_id": fid, "parser_version": pv, "entity_id": "e",
                                          "accounting_profile": "INDAS_CORP", "taxonomy_ns": "t",
                                          "scope": "STANDALONE", "level_of_rounding": "Actual",
                                          "fy_start": date(2025, 4, 1), "fy_end": date(2026, 3, 31),
                                          "period_end": date(2025, 9, 30), "visible_from_ts": vis,
                                          "visible_from_source": "BROADCAST"}])  # fmt: skip
        insert_rows(con, "fact_observations", [{"filing_id": fid, "parser_version": pv, "entity_id": "e",
                                                "scope": "STANDALONE", "canonical_tag": "pat",
                                                "period_type": "DURATION", "period_start": date(2025, 7, 1),
                                                "period_end": date(2025, 9, 30), "period_months": 3, "unit": "INR",
                                                "value_inr": value, "source_element": "ProfitLossForPeriod",
                                                "visible_from_ts": vis}])  # fmt: skip


def test_reparse_with_later_visibility_leaves_no_early_row():
    con = _meta_db()
    early, late = datetime(2025, 10, 29), datetime(2026, 1, 27, 9, 46)
    _filing(con, "f", "s", [("0.7.0", early), ("0.8.0", late)], "100")
    q = (date(2025, 7, 1), date(2025, 9, 30))
    assert q not in load_factbook(con, "e", "STANDALONE", datetime(2025, 12, 1)).durations.get("pat", {})
    assert load_factbook(con, "e", "STANDALONE", late).durations["pat"][q] == 100


def _links(con):
    return set(con.execute("SELECT filing_id, supersedes_filing_id, relation FROM filing_revisions").fetchall())


def _promote_order(order: list[str]) -> set:
    con = _meta_db()
    vis = {"a": datetime(2025, 10, 29), "b": datetime(2025, 11, 5), "c": datetime(2026, 1, 27)}
    sha = {"a": "s1", "b": "s2", "c": "s2"}
    meta = {"accounting_profile": "INDAS_CORP", "scope": "STANDALONE", "period_end": date(2025, 9, 30)}
    for f in order:
        _filing(con, f, sha[f], [("0.8.0", vis[f])], "1")
        _link_revision(con, f, "e", meta, vis[f])
        _link_revision(con, f, "e", meta, vis[f])  # idempotent
    return _links(con)


def test_revision_links_do_not_depend_on_promotion_order():
    forward = _promote_order(["a", "b", "c"])
    assert forward == {("b", "a", "REVISION"), ("c", "b", "RESEND")}
    assert _promote_order(["c", "b", "a"]) == forward
    assert _promote_order(["b", "a", "c"]) == forward
    # the middle filing promoted last also links the outer pair (transitive "supersedes")
    assert _promote_order(["a", "c", "b"]) == forward | {("c", "a", "REVISION")}
