"""The run-level price path (price_history.PriceHistory: bars read once per materialize run, series built once per
factor regime, sliced per day) gives exactly the rows of the per-day legacy path (FINANCIALS_MATERIALIZE_LEGACY=1:
every day re-reads and recomputes the whole history), architecture §11.10.

Three levels:
1. randomised series (splits, two factors on one ex-date, holes in high / low / volume / delivery, missing index
   closes, GAP freezes, sparse trading reaching past the 450-day window of features_more): every column of the
   per-day functions, for every prefix;
2. the full fixture market materialised day by day with both paths: screener_features_history, screener_features
   and market_breadth identical row for row, column for column;
3. the fixture market extended with long synthetic histories (random walks, accepted splits, Nifty 500 closes) so
   every 1-year window fills: the same comparison over a sample of days.
Decimal values must be equal (and Decimal), floats equal within 1e-12 relative (they are in fact bit-identical),
NULLs identical.
"""

from __future__ import annotations

import io
import math
import random
import shutil
import statistics
from datetime import date, timedelta
from decimal import Decimal

import pytest
from conftest import Market, build_full_market

from financials import features, features_more, features_price
from financials.bench import extend_synthetic
from financials.cli import materialize_dates
from financials.price_history import LEGACY_ENV, PriceHistory, _ExactSums

REL = 1e-12


def same(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, float) or isinstance(b, float):
        if not (isinstance(a, float) and isinstance(b, float)):
            return False
        if math.isnan(a) or math.isnan(b):
            return math.isnan(a) and math.isnan(b)
        return a == b or abs(a - b) <= REL * max(abs(a), abs(b))
    if isinstance(a, Decimal) or isinstance(b, Decimal):
        return isinstance(a, Decimal) and isinstance(b, Decimal) and a == b
    return type(a) is type(b) and a == b


def identical(a, b) -> bool:
    """Bit-identical floats, equal Decimals of the same exponent, identical NULLs and other values."""
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    if isinstance(a, Decimal) and isinstance(b, Decimal):
        return a == b and a.as_tuple() == b.as_tuple()
    return type(a) is type(b) and a == b


def assert_same_dicts(new: dict, old: dict, where, eq=identical) -> None:
    assert new.keys() == old.keys(), (where, set(new) ^ set(old))
    diff = {k: (new[k], old[k]) for k in new if not eq(new[k], old[k])}
    assert not diff, (where, diff)


# ── 1. randomised series, every prefix ──────────────────────────────────────────────────────────────────────────


def _series(rng: random.Random, n: int, start: date, sparse: bool) -> list[tuple]:
    bars, d, c = [], start, rng.uniform(20, 2000)
    for _ in range(n):
        d += timedelta(days=rng.choice((1, 1, 1, 3, 9)) if sparse else rng.choice((1, 1, 1, 1, 3)))
        c = max(0.5, c * (1 + rng.gauss(0, 0.025)))
        close = Decimal(f"{c:.2f}").quantize(Decimal("0.0001"))
        hole = rng.random() < 0.03
        high = None if hole else Decimal(f"{c * (1 + abs(rng.gauss(0, 0.01))):.2f}").quantize(Decimal("0.0001"))
        low = None if hole else Decimal(f"{c * (1 - abs(rng.gauss(0, 0.01))):.2f}").quantize(Decimal("0.0001"))
        vol = None if rng.random() < 0.02 else rng.randint(0 if rng.random() < 0.01 else 1, 2_000_000)
        turnover = None if vol is None or rng.random() < 0.02 else Decimal(f"{vol * c:.2f}")
        deliv = None if vol is None or rng.random() < 0.05 else rng.randint(0, vol)
        bars.append((d, close, high, low, vol, turnover, deliv))
    return bars


FACTORS = (Decimal("0.5"), Decimal("0.2"), Decimal("0.1"), Decimal(str(2 / 3)), Decimal(str(10 / 11)), Decimal("1"))


def _market(seed: int):
    rng = random.Random(seed)
    bars, factors, frozen = {}, {}, {}
    for i in range(5):
        sec = f"S{i}"
        b = _series(rng, rng.randint(270, 330), date(2024, 10, 1), sparse=i == 4)
        bars[sec] = b
        dates = [x[0] for x in b]
        acts = []
        for _ in range(rng.randint(0, 3)):
            ex = rng.choice(dates[1:])
            pf = rng.choice(FACTORS)
            acts.append((ex, pf, rng.choice((pf, Decimal(1)))))
            if rng.random() < 0.3:  # a second action on the same ex-date (split + bonus)
                acts.append((ex, rng.choice(FACTORS), Decimal(1)))
        if rng.random() < 0.3:
            acts.append((dates[0] - timedelta(days=5), Decimal("0.5"), Decimal("0.5")))  # before the first bar
        if i == 2:  # three or more inexact factors on one bar: the product depends on the multiplication order
            acts += [(rng.choice(dates[200:]), Decimal(str(x)), Decimal(1)) for x in (2 / 3, 10 / 11, 3 / 7, 7 / 9)]
        rng.shuffle(acts)  # query order is not ex-date order
        factors[sec] = acts
        if i == 3:
            frozen[sec] = dates[len(dates) * 3 // 4]
    all_dates = sorted({x[0] for b in bars.values() for x in b})
    index, level = {}, 20000.0
    for d in all_dates:
        level *= 1 + rng.gauss(0, 0.01)
        if rng.random() > 0.01:
            index[d] = level
    return bars, factors, frozen, index


@pytest.mark.parametrize("seed", [1, 2])
def test_price_columns_equal_the_per_day_functions_for_every_prefix(seed):
    bars, factors, frozen, index = _market(seed)
    last = max(x[0] for b in bars.values() for x in b)
    ph = PriceHistory.from_data("NSE", last, bars, factors, frozen, index)
    rng = random.Random(seed)
    checked = 0
    for sec, b in bars.items():
        dates = [x[0] for x in b]
        events = [rng.choice(dates) for _ in range(3)] + [None, dates[0] - timedelta(days=1)]
        for k, as_of in enumerate(dates):
            as_of = as_of + timedelta(days=1) if k % 7 == 3 else as_of  # also a day without a bar
            prefix = [x for x in b if x[0] <= as_of]
            active = [f for f in factors[sec] if f[0] <= as_of]
            idx = {d: v for d, v in index.items() if d <= as_of}
            fz = frozen.get(sec)
            day_bars, day_factors, day_frozen = ph.inputs(as_of)
            assert day_factors.get(sec, []) == active and day_frozen.get(sec) == fz
            tail3 = [(x[0], x[1], x[6]) for x in prefix]
            assert day_bars[sec] == tail3[-20:]
            assert_same_dicts(features._delivery(day_bars[sec]), features._delivery(tail3), (sec, as_of))
            old_mom = features._momentum(tail3, active, fz)
            assert_same_dicts(ph.momentum(sec, as_of), old_mom, (sec, as_of, "momentum"))
            assert_same_dicts(ph.price_columns(sec, as_of), features_price.price_columns(prefix, active, fz, idx),
                              (sec, as_of, "features_price"))  # fmt: skip
            window = [(x[0], x[1], x[4], x[6]) for x in prefix
                      if x[0] > as_of - timedelta(days=features_more.BAR_LOOKBACK_DAYS)]  # fmt: skip
            row = {"security_id": sec, "as_of_date": as_of, "return_12m": old_mom["return_12m"],
                   "return_1m": old_mom["return_1m"], "last_result_date": events[k % len(events)]}  # fmt: skip
            old_more = features_more.price_columns(row, window, active, fz, idx)
            assert_same_dicts(ph.more_price_columns(row, as_of), old_more, (sec, as_of, "more"))
            checked += 1
    assert checked >= 5 * 270


def test_exact_window_stdev_is_statistics_stdev():
    rng = random.Random(7)
    xs = [rng.gauss(0, 0.02) for _ in range(600)] + [0.0, -0.0, 1e-300, 5e-324, 1e10] + [0.01] * 300
    sums = _ExactSums(xs)
    for lo, hi in [(0, 2), (0, 252), (100, 352), (348, 600), (590, 610), (600, 905), (650, 902), (0, 905)]:
        assert sums.stdev(xs, lo, hi) == statistics.stdev(xs[lo:hi]), (lo, hi)
    holes = [None if i == 10 else x for i, x in enumerate(xs[:300])]
    assert _ExactSums(holes).stdev(holes, 20, 280) == statistics.stdev(holes[20:280])


# ── 2. / 3. the materialised tables, legacy vs run-level path ──────────────────────────────────────────────────

TABLES = {
    "screener_features_history": "as_of_date, security_id",
    "screener_features": "security_id",
    "market_breadth": "as_of_date, universe",
}


def _tables(con) -> dict[str, tuple[list[str], list[tuple]]]:
    out = {}
    for t, order in TABLES.items():
        cur = con.execute(f"SELECT * FROM {t} ORDER BY {order}")
        out[t] = ([d[0] for d in cur.description], cur.fetchall())
    return out


def assert_same_tables(new: dict, old: dict) -> None:
    for t in TABLES:
        (cols, a), (cols_b, b) = new[t], old[t]
        assert cols == cols_b and len(a) == len(b), t
        assert a, t
        bad = [(t, ra[:3], c, x, y) for ra, rb in zip(a, b, strict=True)
               for c, x, y in zip(cols, ra, rb, strict=True) if not same(x, y)]  # fmt: skip
        assert not bad, bad[:20]


def _materialize_both(db_path, tmp_path, days, monkeypatch) -> tuple[dict, dict]:
    out = {}
    for name, legacy in (("fast", False), ("legacy", True)):
        path = tmp_path / f"{name}.duckdb"
        shutil.copy(db_path, path)
        if legacy:
            monkeypatch.setenv(LEGACY_ENV, "1")
        else:
            monkeypatch.delenv(LEGACY_ENV, raising=False)
        from financials.db import connect

        con = connect(path)
        try:
            buf = io.StringIO()
            assert _run(con, days, buf) == 0, buf.getvalue()
            out[name] = _tables(con)
        finally:
            con.close()
    monkeypatch.delenv(LEGACY_ENV, raising=False)
    return out["fast"], out["legacy"]


def _run(con, days, buf) -> int:
    """materialize_dates over exactly `days` (one PriceHistory for the run on the fast path)."""
    with features.materialize_run(con, days) as prices:  # None on the legacy path
        for d in days:
            r = features.materialize(con, d, prices=prices)
            print(r, file=buf)
            if r.status != "PROMOTED":
                return 1
    return 0


@pytest.fixture(scope="module")
def fixture_db(tmp_path_factory):
    root = tmp_path_factory.mktemp("fast_path_base")
    m = build_full_market(root)
    m.con.close()
    return root / "market.duckdb"


def test_full_fixture_market_legacy_and_fast_paths_are_identical(fixture_db, tmp_path, monkeypatch):
    from financials.db import connect

    con = connect(fixture_db, read_only=True)
    days = [d for (d,) in con.execute("SELECT DISTINCT trade_date FROM ohlcv ORDER BY 1").fetchall()]
    con.close()
    new, old = _materialize_both(fixture_db, tmp_path, days, monkeypatch)
    assert_same_tables(new, old)


def test_long_synthetic_history_legacy_and_fast_paths_are_identical(fixture_db, tmp_path, monkeypatch):
    path = tmp_path / "synthetic.duckdb"
    shutil.copy(fixture_db, path)
    all_days = extend_synthetic(path, 60, date(2024, 10, 1), date(2025, 12, 31))
    later = [d for d in all_days if d >= date(2025, 9, 1)]
    days = sorted(set(all_days[::25] + later[:: max(1, len(later) // 8)] + all_days[-3:]))
    new, old = _materialize_both(path, tmp_path, days, monkeypatch)
    rows = new["screener_features_history"][1]
    cols = new["screener_features_history"][0]
    filled = {c: sum(r[cols.index(c)] is not None for r in rows) for c in
              ("beta_1y_nifty500", "volatility_1y", "high_52w", "dma200", "return_12m", "atr_14_pct")}  # fmt: skip
    assert all(filled.values()), filled  # the 1-year windows are exercised
    assert_same_tables(new, old)


def test_materialize_dates_uses_one_price_history_per_run(fixture_db, tmp_path, monkeypatch):
    """`materialize --from/--to` reads the bars once for the run, not once per day."""
    from financials import price_history

    path = tmp_path / "m.duckdb"
    shutil.copy(fixture_db, path)
    m = Market.__new__(Market)
    from financials.db import connect

    m.con = connect(path)
    built = []
    real = price_history.PriceHistory._build

    def spy(self, *a, **k):
        built.append(1)
        return real(self, *a, **k)

    monkeypatch.setattr(price_history.PriceHistory, "_build", spy)
    monkeypatch.delenv(LEGACY_ENV, raising=False)
    assert materialize_dates(m.con, None, date(2024, 10, 1), None, io.StringIO()) == 0
    assert len(built) == 1
    m.con.close()
