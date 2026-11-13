import io
import zipfile
from datetime import date
from decimal import Decimal

import pytest
from conftest import bhav_bytes

from _fixture_helpers import BHAV_DIR
from financials.parsers import ParseError
from financials.parsers.delivery import parse_sec_bhavdata_full
from financials.parsers.udiff import parse_udiff_cm


def _rezip(csv_text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("x.csv", csv_text)
    return buf.getvalue()


def _csv_text(yyyymmdd: str) -> str:
    with zipfile.ZipFile(io.BytesIO(bhav_bytes(yyyymmdd))) as zf:
        return zf.read(zf.namelist()[0]).decode()


def test_udiff_parses_split_day_exactly():
    rows = {(r.symbol, r.series): r for r in parse_udiff_cm(bhav_bytes("20250922"))}
    adani = rows[("ADANIPOWER", "EQ")]
    assert adani.trade_date == date(2025, 9, 22)
    assert adani.isin == "INE814H01029"
    assert adani.fin_instrm_id == "17388"
    assert adani.open == Decimal("148.2000")
    assert adani.prev_close_reported == Decimal("709.4000")  # unadjusted [P2]
    assert isinstance(adani.volume, int)


def test_udiff_keeps_all_series_raw():
    series = {r.series for r in parse_udiff_cm(bhav_bytes("20251014"))}
    assert {"EQ", "BE", "BZ", "SM", "ST"} <= series


def test_udiff_missing_column_is_parse_error():
    text = _csv_text("20251014").replace("FinInstrmId", "Foo", 1)
    with pytest.raises(ParseError, match="missing columns"):
        parse_udiff_cm(_rezip(text))


def test_udiff_mixed_dates_is_parse_error():
    lines = _csv_text("20251014").splitlines()
    lines[2] = lines[2].replace("2025-10-14", "2025-10-13", 2)
    with pytest.raises(ParseError, match="one trade date"):
        parse_udiff_cm(_rezip("\n".join(lines)))


def test_delivery_parser_handles_dash_and_padding():
    rows = parse_sec_bhavdata_full((BHAV_DIR / "sec_bhavdata_full_14102025.csv").read_bytes())
    by_key = {(r.symbol, r.series): r for r in rows}
    tm = by_key[("TATAMOTORS", "EQ")]
    assert (tm.traded_qty, tm.deliv_qty, tm.deliv_pct) == (52267874, 20939394, 40.06)
    assert any(r.deliv_qty is None for r in rows)  # '-' for non-delivery series
    assert {r.trade_date for r in rows} == {date(2025, 10, 14)}
