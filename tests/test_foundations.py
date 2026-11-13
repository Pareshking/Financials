import stat
from datetime import date, datetime, time
from decimal import Decimal

import pytest

from financials.ids import stable_id
from financials.money import identity_tolerance, parse_decimal, parse_int, to_inr
from financials.timeutil import ist_to_utc, utc_to_ist_date
from financials.vault import Vault, make_filing

NOW = datetime(2026, 11, 13, 9, 0)


@pytest.mark.parametrize(
    ("text", "expected"),
    [(" 12.50 ", Decimal("12.50")), ("-", None), ("", None), ("1,234", Decimal("1234")), (None, None)],
)
def test_parse_decimal(text, expected):
    assert parse_decimal(text) == expected


def test_parse_rejects_garbage_and_fractional_ints():
    with pytest.raises(ValueError):
        parse_decimal("12a")
    with pytest.raises(ValueError):
        parse_int("1.5")


def test_identity_tolerance_uses_rounding_unit_not_percent():
    assert identity_tolerance("Millions", 3) == Decimal("1500000")
    assert identity_tolerance("Lakhs", 2) == Decimal("100000")
    assert to_inr(Decimal("2895440000")) == Decimal("2895440000.00")


def test_stable_id_is_deterministic_and_separator_safe():
    assert stable_id("x", "a", "b") == stable_id("x", "a", "b")
    assert stable_id("x", "ab", "c") != stable_id("x", "a", "bc")


def test_ist_conversion():
    utc = ist_to_utc(date(2026, 11, 5), time(14, 57))
    assert utc == datetime(2026, 11, 5, 9, 27)
    assert utc_to_ist_date(datetime(2026, 11, 5, 19, 0)) == date(2026, 11, 6)


def test_vault_is_content_addressed_idempotent_and_read_only(tmp_path):
    v = Vault(tmp_path)
    a = v.put(b"hello", ext="txt", media_type="text/plain", fetched_at=NOW)
    b = v.put(b"hello", ext="txt", media_type="text/plain", fetched_at=NOW)
    assert a == b
    assert a.storage_path == f"{a.sha256[:2]}/{a.sha256}.txt"
    assert v.read(a) == b"hello"
    assert not (tmp_path / a.storage_path).stat().st_mode & stat.S_IWUSR


def test_same_blob_on_two_exchanges_is_two_filings(tmp_path):
    blob = Vault(tmp_path).put(b"<xbrl/>", ext="xml", media_type="application/xml", fetched_at=NOW)
    nse = make_filing(
        blob,
        exchange="NSE",
        category="RESULTS_XBRL",
        source_url="https://n/x.xml",
        fetched_at=NOW,
        broadcast_ts=NOW,
        broadcast_ts_source="RSS_PUBDATE",
    )
    bse = make_filing(
        blob, exchange="BSE", category="RESULTS_XBRL", source_url="https://b/x.xml", fetched_at=NOW
    )
    assert nse.sha256 == bse.sha256
    assert nse.filing_id != bse.filing_id


def test_broadcast_source_must_match_timestamp(tmp_path):
    blob = Vault(tmp_path).put(b"x", ext="txt", media_type="text/plain", fetched_at=NOW)
    with pytest.raises(ValueError):
        make_filing(blob, exchange="NSE", category="X", source_url="u", fetched_at=NOW, broadcast_ts=NOW)
    with pytest.raises(ValueError):
        make_filing(
            blob,
            exchange="NSE",
            category="X",
            source_url="u",
            fetched_at=NOW,
            broadcast_ts_source="RSS_PUBDATE",
        )


def test_insert_or_ignore_keeps_all_rows_with_null_optional_columns():
    """Regression: a nullable UNIQUE column made DuckDB's OR IGNORE drop rows with NULLs."""
    from financials.db import apply_schema, connect, insert_rows

    con = connect()
    apply_schema(con)
    rows = [{"entity_id": f"e{i}", "legal_name": f"n{i}"} for i in range(50)]
    insert_rows(con, "entity_master", rows, or_ignore=True)
    insert_rows(con, "entity_master", rows, or_ignore=True)
    assert con.execute("SELECT count(*) FROM entity_master").fetchone()[0] == 50
