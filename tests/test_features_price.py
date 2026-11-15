"""Batch B price / volume / technical columns (features_price.py; ratio catalogue A8, B6; G94, G95, G156-G158,
G183, G207, G208).

Fixture tests: nine real bhavcopy days (2025-09-19 .. 2025-10-23) with the ADANIPOWER 1:5 split, the PIDILITIND 1:1
bonus and the TATAMOTORS demerger, plus the 2025-10-14 delivery file. Every expected value is computed here from the
files themselves (the stdlib readers in _fixture_helpers), never from our parsers. Indicators whose windows need more
bars than the fixtures hold are NULL end to end and are pinned on fixture closes with shorter periods, and at their
real periods on synthetic series with closed-form answers.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest
from conftest import FETCHED_AT, Market

from _fixture_helpers import FIXTURES, load_sec_bhavdata_full, load_udiff
from financials.db import apply_schema, connect, insert_rows
from financials.features import compute_rows
from financials.features_price import (
    PRICE_COLUMNS,
    adjust,
    atr_series,
    beta,
    ema_series,
    index_closes,
    macd_series,
    price_columns,
    refresh_breadth,
    rsi_series,
    sma,
)
from financials.promoter import promote
from financials.staging import stage_corp_actions, stage_index_closes

DAYS = ("20250919", "20250922", "20250923", "20251013", "20251014", "20251017", "20251020", "20251021", "20251023")
OCT14, OCT23 = date(2025, 10, 14), date(2025, 10, 23)
D = Decimal


@pytest.fixture(scope="module")
def mkt(tmp_path_factory):
    m = Market(tmp_path_factory.mktemp("price_market"))

    def ok(stage):
        assert promote(m.con, stage).status in ("PROMOTED", "QUARANTINED")

    ok(m.stage_day(DAYS[0]))
    ca = FIXTURES / "corp_actions" / "nse_corporateActions_equities_15-09-2025_17-10-2025.json"
    ok(stage_corp_actions(m.vault, m.stage_root, data=ca.read_bytes(), source_url="nse-ca", fetched_at=FETCHED_AT))
    for d in DAYS[1:]:
        ok(m.stage_day(d, with_delivery=d == "20251014"))
    m.rows = {d: {r["symbol"]: r for r in compute_rows(m.con, d)} for d in (OCT14, OCT23)}
    yield m
    m.con.close()


def udiff(symbol: str, days=DAYS) -> list[dict]:
    return [load_udiff(d)[symbol] for d in days]


def closes(symbol: str, days=DAYS) -> list[Decimal]:
    return [D(r["ClsPric"]) for r in udiff(symbol, days)]


# ── P16: AVG_PRICE is turnover / volume ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("ud", "full"), [("20261112", "12112026"), ("20251014", "14102025")])
def test_avg_price_is_udiff_turnover_over_volume(ud, full):
    u = load_udiff(ud)
    _, rows = load_sec_bhavdata_full(full)
    n = 0
    for (sym, series), r in rows.items():
        x = u.get(sym)
        if x is None or x["SctySrs"] != series or D(x["TtlTradgVol"]) == 0:
            continue
        n += 1
        assert int(r["TTL_TRD_QNTY"]) == int(x["TtlTradgVol"]), sym
        vwap = D(x["TtlTrfVal"]) / D(x["TtlTradgVol"])
        assert vwap.quantize(D("0.01"), ROUND_HALF_UP) == D(r["AVG_PRICE"]), sym  # WHBRADY 467.125 -> 467.13
    assert n == {"20261112": 2982, "20251014": 2460}[ud]


def test_vwap_and_delivery_pct_match_the_delivery_file(mkt):
    _, full = load_sec_bhavdata_full("14102025")
    for sym in ("RELIANCE", "PIDILITIND", "ADANIPOWER"):
        r, f = mkt.rows[OCT14][sym], full[(sym, "EQ")]
        assert r["vwap"].quantize(D("0.01"), ROUND_HALF_UP) == D(f["AVG_PRICE"])
        assert r["deliv_pct"] == pytest.approx(int(f["DELIV_QTY"]) / int(f["TTL_TRD_QNTY"]))
        assert round(r["deliv_pct"] * 100, 2) == float(f["DELIV_PER"])
        assert r["volume"] == int(f["TTL_TRD_QNTY"])
    assert mkt.rows[OCT23]["RELIANCE"]["deliv_pct"] is None  # no delivery file for 23 Oct in this market
    x = load_udiff("20251023")["RELIANCE"]
    assert mkt.rows[OCT23]["RELIANCE"]["vwap"] == (D(x["TtlTrfVal"]) / D(x["TtlTradgVol"])).quantize(D("0.0001"))


# ── fixture values, end to end ──────────────────────────────────────────────────────────────────────────────────────


def test_returns_volume_and_range_on_reliance(mkt):
    r, c, rows = mkt.rows[OCT23]["RELIANCE"], closes("RELIANCE"), udiff("RELIANCE")
    assert r["return_1d"] == pytest.approx(float(c[-1] / c[-2] - 1))
    assert r["return_1w"] == pytest.approx(float(c[-1] / c[-6] - 1))  # 5 bars back: 2025-10-13
    assert r["volume"] == int(rows[-1]["TtlTradgVol"])
    assert r["volume_1w_avg"] == pytest.approx(sum(int(x["TtlTradgVol"]) for x in rows[-5:]) / 5)
    assert r["high_since_data_start"] == max(c) and r["low_since_data_start"] == min(c)


def test_bonus_and_split_adjust_levels_and_volumes(mkt):
    # PIDILITIND 1:1 bonus ex 2025-09-23: earlier closes x 1/2.
    pid = closes("PIDILITIND")
    adj = [pid[0] / 2, pid[1] / 2, *pid[2:]]
    r = mkt.rows[OCT23]["PIDILITIND"]
    assert r["return_1w"] == pytest.approx(float(adj[-1] / adj[-6] - 1))
    assert r["high_since_data_start"] == max(adj).quantize(D("0.0001"))
    r14 = mkt.rows[OCT14]["PIDILITIND"]
    assert r14["return_1w"] is None  # 5 bars held, return_1w needs 6
    # ADANIPOWER split Rs 10 -> Rs 2 ex 2025-09-22: the 19 Sep volume x 5 on today's share basis, price / 5.
    vol = [int(x["TtlTradgVol"]) for x in udiff("ADANIPOWER", DAYS[:5])]
    ap = mkt.rows[OCT14]["ADANIPOWER"]
    assert ap["volume_1w_avg"] == pytest.approx((vol[0] * 5 + sum(vol[1:])) / 5)
    adp = closes("ADANIPOWER", DAYS[:5])
    assert ap["high_since_data_start"] == max([adp[0] / 5, *adp[1:]]).quantize(D("0.0001"))


def test_demerger_factor_adjusts_the_high(mkt):
    # TATAMOTORS demerger ex 2025-10-14: factor = open on the ex-date / previous close [C3].
    pre, ex = load_udiff("20251013")["TATAMOTORS"], load_udiff("20251014")["TATAMOTORS"]
    f = D(ex["OpnPric"]) / D(pre["ClsPric"])
    c = closes("TATAMOTORS")
    adj = [x * f for x in c[:4]] + c[4:]
    r = mkt.rows[OCT23]["TATAMOTORS"]
    assert r["high_since_data_start"] == max(adj).quantize(D("0.0001"))
    assert r["return_1w"] == pytest.approx(float(adj[-1] / adj[-6] - 1))


def test_long_windows_are_null_on_nine_bars(mkt):
    r = mkt.rows[OCT23]["RELIANCE"]
    for col in ("return_3y", "return_5y", "return_7y", "return_10y", "volume_1m_avg", "volume_1y_avg", "high_52w",
                "low_52w", "dist_52w_low", "dma50", "dma200", "dma50_prev", "dma200_prev", "rsi_14", "rsi_14_prev",
                "macd", "macd_signal", "macd_prev", "macd_signal_prev", "atr_14_pct", "rs_nifty500_3m",
                "rs_nifty500_6m", "rs_nifty500_12m", "beta_1y_nifty500", "turnover_median_20d",
                "deliv_pct_avg_20d", "vwap_20d"):  # fmt: skip
        assert r[col] is None, col
    assert set(PRICE_COLUMNS) <= set(r)


# ── indicators on fixture closes (shorter periods), checked by hand ─────────────────────────────────────────────────


def test_rsi_wilder_on_reliance_closes():
    c = [float(x) for x in closes("RELIANCE")]
    ch = [c[i] - c[i - 1] for i in range(1, 9)]
    gain = [max(x, 0) for x in ch]
    loss = [max(-x, 0) for x in ch]
    ag, al = sum(gain[:5]) / 5, sum(loss[:5]) / 5
    want = [100 - 100 / (1 + ag / al)]
    for i in (5, 6, 7):
        ag, al = (ag * 4 + gain[i]) / 5, (al * 4 + loss[i]) / 5
        want.append(100 - 100 / (1 + ag / al))
    got = rsi_series(c, 5)
    assert got[:5] == [None] * 5
    assert got[5:] == pytest.approx(want)


def test_ema_macd_on_reliance_closes():
    c = [float(x) for x in closes("RELIANCE")]
    e3 = [None, None, sum(c[:3]) / 3]
    for x in c[3:]:
        e3.append(x * 0.5 + e3[-1] * 0.5)  # alpha = 2 / (3 + 1)
    got = ema_series(c, 3)
    assert got[:2] == [None, None] and got[2:] == pytest.approx(e3[2:])
    e5 = [sum(c[:5]) / 5]
    for x in c[5:]:
        e5.append(x / 3 + e5[-1] * 2 / 3)  # alpha = 2 / 6
    macd, sig = macd_series(c, 3, 5, 2)
    want_macd = [a - b for a, b in zip(e3[4:], e5, strict=True)]
    assert macd[:4] == [None] * 4 and macd[4:] == pytest.approx(want_macd)
    s = [(want_macd[0] + want_macd[1]) / 2]
    for x in want_macd[2:]:
        s.append(x * 2 / 3 + s[-1] / 3)  # alpha = 2 / 3
    assert sig[:5] == [None] * 5 and sig[5:] == pytest.approx(s)


def test_atr_and_sma_on_adanipower_adjusted_bars(mkt):
    rows = udiff("ADANIPOWER")
    f = [D("0.2")] + [D(1)] * 8  # 1:5 split ex 2025-09-22
    h = [float(D(r["HghPric"]) * k) for r, k in zip(rows, f, strict=True)]
    lo = [float(D(r["LwPric"]) * k) for r, k in zip(rows, f, strict=True)]
    c = [float(D(r["ClsPric"]) * k) for r, k in zip(rows, f, strict=True)]
    tr = [max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1])) for i in range(1, 9)]
    atr = sum(tr[:4]) / 4
    want = [atr]
    for x in tr[4:]:
        atr = (atr * 3 + x) / 4
        want.append(atr)
    assert atr_series(h, lo, c, 4)[4:] == pytest.approx(want)
    # the production adjustment reproduces these bars
    sec = mkt.security_id("ADANIPOWER")
    bars = mkt.con.execute(
        "SELECT trade_date, close, high, low, volume FROM ohlcv WHERE security_id = ? ORDER BY trade_date", [sec]
    ).fetchall()
    factors = [(ex, D(str(pf)), D(1)) for ex, pf in mkt.con.execute(
        "SELECT ex_date, price_factor FROM corp_actions WHERE security_id = ? AND price_factor IS NOT NULL", [sec]
    ).fetchall()]  # fmt: skip
    assert [(ex, pf) for ex, pf, _ in factors] == [(date(2025, 9, 22), D("0.2"))]
    adj = adjust(bars, factors, None)
    assert [float(b[2]) for b in adj] == pytest.approx(h) and [float(b[1]) for b in adj] == pytest.approx(c)
    assert sma([D(str(x)) for x in c], 3) == pytest.approx(sum(D(str(x)) for x in c[-3:]) / 3)
    assert sma([D(str(x)) for x in c], 3, lag=1) == pytest.approx(sum(D(str(x)) for x in c[-4:-1]) / 3)


# ── Nifty 500 closes from the real IDX9 file ────────────────────────────────────────────────────────────────────────


def test_index_closes_read_nifty500_from_index_ohlcv(market):
    path = FIXTURES / "indices" / "ind_close_all_13112026.csv"
    stage = stage_index_closes(market.vault, market.stage_root, data=path.read_bytes(),
                               source_url="https://nsearchives.nseindia.com/content/indices/" + path.name,
                               fetched_at=FETCHED_AT)  # fmt: skip
    assert promote(market.con, stage).status == "PROMOTED"
    assert index_closes(market.con, date(2026, 11, 13)) == {date(2026, 11, 13): 23734.2}
    assert index_closes(market.con, date(2026, 11, 12)) == {}


# ── synthetic series at the real periods ────────────────────────────────────────────────────────────────────────────


def _bars(closes_, start=date(2024, 10, 1), volume=1000, spread=1):
    out = []
    for i, c in enumerate(closes_):
        c = D(str(c))
        out.append((start + timedelta(days=i), c, c + D(spread), c - D(spread), volume, c * volume, volume // 2))
    return out


def test_history_gated_returns_switch_on_with_enough_bars():
    growth = 1.0004
    series = [round(100 * growth**i, 4) for i in range(2521)]
    out = price_columns(_bars(series), [], None, {})
    for name, n in (("return_1d", 1), ("return_1w", 5), ("return_3y", 756), ("return_5y", 1260), ("return_7y", 1764),
                    ("return_10y", 2520)):  # fmt: skip
        assert out[name] == pytest.approx(series[-1] / series[-1 - n] - 1), name
    short = price_columns(_bars(series[:2520]), [], None, {})  # one bar short of 10 years
    assert short["return_10y"] is None and short["return_7y"] is not None


def test_dma_highs_lows_and_volume_on_a_linear_series():
    series = list(range(1, 301))  # close t = t
    out = price_columns(_bars(series), [], None, {})
    assert out["dma50"] == D("275.5") and out["dma50_prev"] == D("274.5")
    assert out["dma200"] == D("200.5") and out["dma200_prev"] == D("199.5")
    assert (out["high_52w"], out["low_52w"]) == (D(300), D(49))
    assert out["dist_52w_low"] == pytest.approx(300 / 49 - 1)
    assert (out["high_since_data_start"], out["low_since_data_start"]) == (D(300), D(1))
    assert out["volume_1w_avg"] == out["volume_1m_avg"] == out["volume_1y_avg"] == 1000
    assert out["turnover_median_20d"] == D("290500.00")  # median of 281..300 x 1000
    assert out["deliv_pct_avg_20d"] == 0.5 and out["deliv_pct"] == 0.5
    assert out["vwap"] == D(300) and out["vwap_20d"] == D("290.5")
    assert out["atr_14_pct"] == pytest.approx(2 / 300)  # every true range = high - low = 2
    # linear closes: an SMA-seeded EMA(n) lags by exactly (n - 1) / 2, so MACD = 12.5 - 5.5 = 7 = its signal
    assert out["macd"] == pytest.approx(7) and out["macd_signal"] == pytest.approx(7)
    assert out["macd_prev"] == pytest.approx(7) and out["macd_signal_prev"] == pytest.approx(7)
    assert out["rsi_14"] == 100.0  # gains only
    too_short = price_columns(_bars(series[:251]), [], None, {})
    assert too_short["high_52w"] is None and too_short["dist_52w_low"] is None and too_short["volume_1y_avg"] is None


def test_macd_warm_up_and_rsi_wilder_step():
    c = [float(x) for x in range(1, 35)]
    macd, sig = macd_series(c)
    assert macd[24] is None and macd[25] == pytest.approx(7)
    assert sig[32] is None and sig[33] == pytest.approx(7)  # 34 bars
    # 7 gains of +1 and 7 losses of -1 -> RSI 50; then +2: avg gain (0.5 x 13 + 2) / 14, avg loss 0.5 x 13 / 14
    closes_ = [100.0]
    for i in range(14):
        closes_.append(closes_[-1] + (1 if i % 2 == 0 else -1))
    closes_.append(closes_[-1] + 2)
    r = rsi_series(closes_)
    assert r[13] is None and r[14] == pytest.approx(50)
    assert r[15] == pytest.approx(100 - 100 / (1 + 8.5 / 6.5))
    out = price_columns(_bars(closes_), [], None, {})
    assert (out["rsi_14"], out["rsi_14_prev"]) == (pytest.approx(r[15]), pytest.approx(50))


def test_relative_strength_and_beta_vs_nifty500():
    n = 260
    rm = [0.01 * math.sin(i) for i in range(n)]
    idx, stock = [20000.0], [500.0]
    for x in rm:
        idx.append(idx[-1] * math.exp(x))
        stock.append(stock[-1] * math.exp(1.5 * x + 0.0002))
    bars = _bars([round(s, 4) for s in stock])
    index = {b[0]: v for b, v in zip(bars, idx, strict=True)}
    out = price_columns(bars, [], None, index)
    s = [float(b[1]) for b in bars]
    for name, k in (("rs_nifty500_3m", 63), ("rs_nifty500_6m", 126), ("rs_nifty500_12m", 252)):
        assert out[name] == pytest.approx(s[-1] / s[-1 - k] - idx[-1] / idx[-1 - k]), name
    assert out["beta_1y_nifty500"] == pytest.approx(1.5, abs=1e-3)  # closes rounded to 4 dp
    assert beta([1.0, 2.0, 4.0], [10.0, 20.0, 40.0]) is None  # flat market returns: no variance
    del index[bars[-100][0]]  # a missing index day inside the 1-year window
    out = price_columns(bars, [], None, index)
    assert out["beta_1y_nifty500"] is None and out["rs_nifty500_3m"] is not None


def test_split_inside_the_window_and_gap_freeze():
    bars = _bars([500] * 10 + [100] * 15)  # 1:5 split ex the 11th bar
    ex = bars[10][0]
    out = price_columns(bars, [(ex, D("0.2"), D("0.2"))], None, {})
    assert out["return_1w"] == 0.0 and out["high_since_data_start"] == D(100)
    assert out["volume_1y_avg"] is None  # 25 bars
    assert out["volume_1m_avg"] == pytest.approx((6 * 5000 + 15 * 1000) / 21)  # pre-split volume x 5
    assert out["vwap_20d"] == D(100)  # traded value / adjusted volume stays on today's basis
    frozen = price_columns(bars, [], ex, {})  # unresolved gap on the ex-date: adjusted columns withheld
    assert frozen["return_1d"] is None and frozen["high_since_data_start"] is None and frozen["vwap_20d"] is None
    assert frozen["volume"] == 1000 and frozen["vwap"] == D(100)  # raw same-day values stay


# ── market breadth (G208) ───────────────────────────────────────────────────────────────────────────────────────────


def test_market_breadth_counts_nifty500_rows(tmp_path: Path):
    con = connect(tmp_path / "m.duckdb")
    apply_schema(con)
    d = date(2026, 11, 12)
    spec = [  # (in_nifty500, price_to_dma50, price_to_dma200, dist_52w_high, dist_52w_low, return_1d)
        (True, 1.1, 1.2, 0.0, 0.4, 0.01),
        (True, 0.9, 1.1, -0.1, 0.0, -0.02),
        (True, 1.05, None, 0.0, 0.2, 0.0),
        (True, None, None, None, None, 0.03),
        (False, 2.0, 2.0, 0.0, 0.0, 0.05),  # not a member
    ]
    rows = [{"as_of_date": d, "security_id": f"s{i}", "entity_id": f"e{i}", "symbol": f"S{i}", "series": "EQ",
             "in_nifty500": m, "price_to_dma50": a, "price_to_dma200": b, "dist_52w_high": h, "dist_52w_low": lo,
             "return_1d": r} for i, (m, a, b, h, lo, r) in enumerate(spec)]  # fmt: skip
    insert_rows(con, "screener_features_history", rows)
    refresh_breadth(con, d)
    refresh_breadth(con, d)  # idempotent
    got = con.execute("SELECT * EXCLUDE (as_of_date) FROM market_breadth").fetchall()
    assert got == [("NIFTY 500", 4, pytest.approx(2 / 3), 1.0, 2, 1, 2.0, 2, 1, 1, 2.0)]
    con.close()


def test_materialize_publishes_breadth_with_the_day(full_market):
    from financials.features import materialize

    con, nov = full_market.con, date(2026, 11, 12)
    assert materialize(con, nov).status == "PROMOTED"
    members = con.execute(
        "SELECT count(*), count(*) FILTER (WHERE return_1d > 0), count(*) FILTER (WHERE return_1d < 0) "
        "FROM screener_features_history WHERE as_of_date = ? AND in_nifty500",
        [nov],
    ).fetchone()
    got = con.execute("SELECT members, advances, declines FROM market_breadth WHERE as_of_date = ?", [nov]).fetchone()
    assert got == members and members[0] > 400
