"""X359: the PR-zip price-band file (bhddmmyy(yy).csv) and the circuit-day columns read from it."""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

import duckdb
import pytest
from conftest import FETCHED_AT

from _fixture_helpers import FIXTURES
from financials.features_bands import COLUMNS, WINDOW, add_columns
from financials.parsers import ParseError
from financials.parsers.pr_bands import parse_price_band_hits
from financials.promoter import promote
from financials.staging import stage_price_bands
from financials.timeutil import ist_to_utc

ZIPS = {  # zip: (trade date, rows, H, L); headers with INDEX FLAG up to 2025, without after
    "pr_zip/PR011024.zip": (date(2024, 10, 1), 243, 172, 71),
    "pr_zip/PR061224.zip": (date(2024, 12, 6), 202, 157, 45),
    "pr_zip/PR300625.zip": (date(2025, 6, 30), 225, 151, 74),
    "pr_zip/PR250926.zip": (date(2026, 9, 25), 259, 149, 110),
    "pr_zip/PR300926.zip": (date(2026, 9, 30), 305, 182, 123),
    "series_switch/PR301026.zip": (date(2026, 10, 30), 290, 155, 135),
    "pr_zip/PR131126.zip": (date(2026, 11, 13), 251, 133, 118),
}


@pytest.mark.parametrize("name", sorted(ZIPS))
def test_every_real_zip_parses(name):
    rows = parse_price_band_hits((FIXTURES / name).read_bytes())
    day, n, h, low = ZIPS[name]
    assert {r.trade_date for r in rows} == {day} and len(rows) == n
    assert Counter(r.band for r in rows) == {"H": h, "L": low}
    assert {"EQ", "BE"} <= {r.series for r in rows}  # every series is kept as filed (also SM, ST, GS, ...)


def test_a_real_header_only_file_parses_to_no_rows():
    """12-Jan-2026: NSE's bh file holds the header only on a normal trading day; no rows, so the day counts as not
    loaded and every 20-session window containing it is NULL (features_bands)."""
    assert parse_price_band_hits((FIXTURES / "pr_zip/PR120126.zip").read_bytes()) == []


def test_a_real_row_is_kept_as_filed():
    rows = parse_price_band_hits((FIXTURES / "pr_zip/PR131126.zip").read_bytes())
    r = next(r for r in rows if r.symbol == "3IINFOLTD")
    assert (r.series, r.security_name, r.band) == ("BE", "3I INFOTECH LIMITED", "H")


def test_a_zip_without_a_bh_member_fails(tmp_path):
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", "x")
    with pytest.raises(ParseError, match="expected one bh file"):
        parse_price_band_hits(buf.getvalue())


def _mini(days: int, loaded: int):
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE ohlcv (security_id VARCHAR, exchange VARCHAR, series VARCHAR, trade_date DATE, "
        "open DECIMAL(18,4), high DECIMAL(18,4), low DECIMAL(18,4), close DECIMAL(18,4))"
    )
    con.execute(
        "CREATE TABLE raw_price_band_hits (filing_id VARCHAR, exchange VARCHAR, trade_date DATE, "
        "symbol VARCHAR, series VARCHAR, security_name VARCHAR, band VARCHAR)"
    )
    con.execute(
        "CREATE TABLE security_identifier_history (security_id VARCHAR, exchange VARCHAR, symbol VARCHAR, "
        "series VARCHAR, valid_from DATE, valid_to DATE)"
    )
    con.execute(
        "INSERT INTO security_identifier_history VALUES ('s1', 'NSE', 'AAA', 'EQ', DATE '2020-01-01', NULL), "
        "('s2', 'NSE', 'BBB', 'BE', DATE '2020-01-01', NULL)"
    )
    d0 = date(2026, 1, 1)
    for i in range(days):
        d = d0 + timedelta(days=i)
        # s1: upper band touched every day, locked (close = high) on even days; s2 lower band on day 0 only, locked
        con.execute("INSERT INTO ohlcv VALUES ('s1', 'NSE', 'EQ', ?, 10, 11, 9, ?), ('s2', 'NSE', 'BE', ?, 5, 6, 4, 4)",
                    [d, 11 if i % 2 == 0 else 10, d])  # fmt: skip
        if i >= days - loaded:
            con.execute("INSERT INTO raw_price_band_hits VALUES ('f', 'NSE', ?, 'AAA', 'EQ', 'A', 'H')", [d])
            if i == days - 1:
                con.execute("INSERT INTO raw_price_band_hits VALUES ('f', 'NSE', ?, 'BBB', 'BE', 'B', 'L')", [d])
    return con, d0 + timedelta(days=days - 1)


def test_window_counts_hits_and_locks_by_security():
    con, as_of = _mini(WINDOW + 5, WINDOW)
    rows = [{"security_id": "s1"}, {"security_id": "s2"}, {"security_id": "s3"}]
    add_columns(con, rows, as_of)
    assert [tuple(r[c] for c in COLUMNS) for r in rows] == [(20, 10, 0), (1, 0, 1), (0, 0, 0)]


def test_a_window_not_covered_by_band_files_is_null():
    con, as_of = _mini(WINDOW + 5, WINDOW - 1)  # one session of the window has no band file
    rows = [{"security_id": "s1"}]
    add_columns(con, rows, as_of)
    assert all(rows[0][c] is None for c in COLUMNS)


def test_backfill_stages_and_promotes_the_rows(market):
    m = market
    data = (FIXTURES / "pr_zip/PR131126.zip").read_bytes()
    st = stage_price_bands(m.vault, m.stage_root, data=data, source_url="https://example.invalid/PR131126.zip",
                           fetched_at=FETCHED_AT, broadcast_ts=ist_to_utc(date(2026, 11, 13), __import__(
                               "datetime").time(23, 59, 59)))  # fmt: skip
    r = promote(m.con, st)
    assert r.status == "PROMOTED", r
    assert m.con.execute("SELECT count(*), count(DISTINCT band) FROM raw_price_band_hits").fetchone() == (251, 2)
    again = promote(m.con, st)  # a replay adds nothing
    assert (
        again.status in ("PROMOTED", "SKIPPED")
        and m.con.execute("SELECT count(*) FROM raw_price_band_hits").fetchone()[0] == 251
    )
