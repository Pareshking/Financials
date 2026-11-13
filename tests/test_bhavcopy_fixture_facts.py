"""Characterisation tests: verified behaviour of NSE daily price/delivery files."""

from decimal import Decimal

from _fixture_helpers import load_sec_bhavdata_full, load_udiff

UDIFF_REQUIRED = {"TradDt", "FinInstrmId", "ISIN", "TckrSymb", "SctySrs", "OpnPric", "ClsPric", "PrvsClsgPric", "TtlTradgVol"}


def test_udiff_columns_present_and_no_delivery_column():
    row = next(iter(load_udiff("20251014").values()))
    assert UDIFF_REQUIRED <= row.keys()
    assert not any("deliv" in k.lower() for k in row)


def test_udiff_prev_close_is_not_adjusted_on_ex_dates():
    cases = [
        ("20250919", "20250922", "ADANIPOWER"),  # split
        ("20250922", "20250923", "PIDILITIND"),  # bonus
        ("20251013", "20251014", "TATAMOTORS"),  # demerger
    ]
    for before, ex, sym in cases:
        assert load_udiff(ex)[sym]["PrvsClsgPric"] == load_udiff(before)[sym]["ClsPric"]


def test_split_changes_isin_but_keeps_fin_instrm_id_and_symbol():
    before, ex = load_udiff("20250919")["ADANIPOWER"], load_udiff("20250922")["ADANIPOWER"]
    assert (before["ISIN"], ex["ISIN"]) == ("INE814H01011", "INE814H01029")
    assert before["FinInstrmId"] == ex["FinInstrmId"] == "17388"


def test_bonus_keeps_isin():
    assert load_udiff("20250922")["PIDILITIND"]["ISIN"] == load_udiff("20250923")["PIDILITIND"]["ISIN"]


def test_demerger_parent_keeps_isin_and_symbol_on_ex_date():
    before, ex = load_udiff("20251013")["TATAMOTORS"], load_udiff("20251014")["TATAMOTORS"]
    assert before["ISIN"] == ex["ISIN"] == "INE155A01022"
    assert Decimal(ex["OpnPric"]) / Decimal(before["ClsPric"]) < Decimal("0.65")


def test_sec_bhavdata_full_has_delivery_but_no_isin_and_unadjusted_prev_close():
    header, rows = load_sec_bhavdata_full("14102025")
    assert {"DELIV_QTY", "DELIV_PER", "PREV_CLOSE"} <= set(header)
    assert "ISIN" not in header
    assert rows[("TATAMOTORS", "EQ")]["PREV_CLOSE"] == "660.75"
    assert rows[("TATAINVEST", "EQ")]["PREV_CLOSE"] == "9922.00"
