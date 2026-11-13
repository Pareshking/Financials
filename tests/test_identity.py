from dataclasses import replace
from datetime import date

from conftest import bhav_bytes

from financials.identity import SecurityRegistry
from financials.parsers.udiff import parse_udiff_cm


def day(yyyymmdd):
    return parse_udiff_cm(bhav_bytes(yyyymmdd))


def test_split_isin_change_keeps_security_and_closes_interval():
    reg = SecurityRegistry("NSE")
    first = reg.observe(day("20250919"))
    adani = first.resolved[("ADANIPOWER", "EQ")]
    second = reg.observe(day("20250922"))
    assert second.resolved[("ADANIPOWER", "EQ")] == adani
    events = [e for e in second.events if e.security_id == adani]
    assert [(e.kind, e.old, e.new) for e in events] == [("ISIN_CHANGE", "INE814H01011", "INE814H01029")]
    (closed,) = [iv for iv in second.closed if iv.security_id == adani]
    assert (closed.valid_from, closed.valid_to) == (date(2025, 9, 19), date(2025, 9, 22))
    assert reg.current(adani).isin == "INE814H01029"
    assert reg.owner_of_fin_instrm_id("17388") == adani


def test_bonus_has_no_identity_event():
    reg = SecurityRegistry("NSE")
    reg.observe(day("20250922"))
    out = reg.observe(day("20250923"))
    pid = out.resolved[("PIDILITIND", "EQ")]
    assert not [e for e in out.events if e.security_id == pid]


def test_only_universe_series_are_registered():
    out = SecurityRegistry("NSE").observe(day("20251014"))
    assert {series for (_, series) in out.resolved} <= {"EQ", "BE", "BZ"}
    assert not out.issues


def test_out_of_order_day_is_rejected():
    reg = SecurityRegistry("NSE")
    reg.observe(day("20250922"))
    out = reg.observe(day("20250919"))
    assert out.issues and {i.reason_code for i in out.issues} == {"OUT_OF_ORDER"}
    assert not out.resolved


def test_fin_instrm_id_and_isin_pointing_at_different_securities_is_a_collision():
    reg = SecurityRegistry("NSE")
    a, b = [r for r in day("20251013") if r.series == "EQ"][:2]
    reg.observe([a, b])
    impostor = replace(a, isin=b.isin, trade_date=date(2025, 10, 14))
    out = reg.observe([impostor])
    assert [i.reason_code for i in out.issues] == ["ISIN_COLLISION"]
    assert not out.resolved


def test_reload_from_intervals_is_equivalent():
    reg = SecurityRegistry("NSE")
    out = reg.observe(day("20250919"))
    reloaded = SecurityRegistry("NSE", out.opened)
    again = reloaded.observe(day("20250922"))
    assert again.resolved[("ADANIPOWER", "EQ")] == out.resolved[("ADANIPOWER", "EQ")]
    assert not again.new_securities or all(s.security_id not in out.resolved.values() for s in again.new_securities)


def test_series_change_with_new_fin_instrm_id_keeps_security():
    reg = SecurityRegistry("NSE")
    first = reg.observe(day("20250923"))
    sec = first.resolved[("AAATECH", "EQ")]
    out = reg.observe(day("20251013"))
    assert out.resolved[("AAATECH", "BE")] == sec
    kinds = {e.kind for e in out.events if e.security_id == sec}
    assert kinds == {"SERIES_CHANGE", "FIN_INSTRM_ID_CHANGE"}
    assert not out.issues
