"""Price history of one materialize run (architecture §11.11): bars, accepted price factors, GAP freezes and Nifty
500 closes read once, per-security series built once per factor regime, every day's price columns sliced from them.

Before this module every materialised day re-read every security's whole bar history (~450 days by the end of the
data) and recomputed every indicator from the first bar: quadratic in the length of the history. A `PriceHistory`
reads the bars of the run once (up to its last day); a day `d` sees each security's prefix of bars dated <= d.

Factor regimes. A back-adjusted series depends on the as-of date only through the set of accepted actions with
ex-date <= as_of ("valid" knowledge, the only mode materialised history uses): the factor of a bar is the product of
those actions' price factors with ex-date after the bar. Between two ex-dates of a security that set is fixed, so
its adjusted series (and every causal indicator over it: RSI, MACD / signal EMAs, ATR) is computed once per set of
active factors (a "regime") over all its bars, and the value of day d is the element at d's last bar. Causal means
the value at bar i depends only on bars 0..i; the recursions of features_price (seeded by the first n values) are.
Bars after d never change the factor of an earlier bar, and a GAP freeze only cuts the series at its first frozen
bar (every column that needs the adjusted series is NULL from that bar on), so the slice is the exact series the
per-day code would have built. Windowed values (sums, max / min, returns, beta, volatility, drawdown, PEAD) are
recomputed per day from the slices with the same expressions, in the same order, so Decimal results are equal and
float results bit-identical; the only shortcuts are prefix sums that give provably the same value (`_DecimalSums`
when every partial sum is exact, `_ExactSums` for the volatility). tests/test_materialize_fast_path.py pins this
against the per-day code
(FINANCIALS_MATERIALIZE_LEGACY=1 selects it) on the fixture market and on randomised series with splits, holes and
gaps for every prefix.

A run must not change ohlcv, corp_actions or GAP quarantines while it holds a PriceHistory: materialize only writes
the feature tables, so a `materialize --from/--to` or `--incremental` run cannot.
"""

from __future__ import annotations

import bisect
import decimal
import gc
import math
import os
import statistics
from array import array
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal
from fractions import Fraction
from itertools import pairwise

from financials import features_more as fm
from financials import features_price as fp
from financials.corp_actions import ACCEPTED_STATUSES

LEGACY_ENV = "FINANCIALS_MATERIALIZE_LEGACY"
DELIVERY_TAIL = 20  # bars `features._rows` / `_delivery` / dividends / features_pl read (the last one, or 5 and 20)
_ONE = Decimal(1)


def legacy() -> bool:
    """FINANCIALS_MATERIALIZE_LEGACY=1: the per-day path (every day re-reads and recomputes the whole history)."""
    return os.environ.get(LEGACY_ENV, "") not in ("", "0")


class _Regime:
    """Series of one security under one set of active price factors (bars before the GAP freeze only)."""

    __slots__ = ("adj", "atr", "csum", "fl", "fpp", "lr", "macd", "mom", "msum", "rmax", "rmin", "rsi", "sig", "vol",
                 "volsum", "vsum")  # fmt: skip

    def __init__(self, bars: list[tuple], factors: list[tuple], frozen_from: date | None) -> None:
        kept = [b for b in bars if frozen_from is None or b[0] < frozen_from]
        # features_price.adjust / features_more.adjust: factors sorted by (ex, pf) descending, multiplied in that
        # order while walking back from the last bar; an untouched factor (Decimal(1)) leaves the close as it is.
        pending = sorted(((ex, pf) for ex, pf, _ in factors), reverse=True)
        n = len(kept)
        fpp: list[Decimal] = [_ONE] * n
        f, i = _ONE, 0
        for k in range(n - 1, -1, -1):
            d = kept[k][0]
            while i < len(pending) and pending[i][0] > d:
                f *= pending[i][1]
                i += 1
            fpp[k] = f
        self.fpp = fpp
        # close x Decimal(1) is the close itself (same coefficient and exponent): share the object
        adj = [b[1] if f is _ONE else b[1] * f for b, f in zip(kept, fpp, strict=True)]
        self.adj = adj
        self.vol = [None if b[4] is None else Decimal(b[4]) / f for b, f in zip(kept, fpp, strict=True)]
        # features._momentum multiplies the factors in list (query) order: a different rounding order when two or
        # more apply to a bar, so its series is built the same way (the same objects when at most one applies).
        if len(factors) < 2:
            self.mom = adj
        else:
            mom = []
            for b in kept:
                g = _ONE
                for ex, pf, _ in factors:
                    if ex > b[0]:
                        g *= pf
                mom.append(b[1] * g)
            self.mom = mom
        # Float series are stored as array('d') (8 bytes a value) with NaN for None: none of them holds a NaN
        # otherwise (finite closes give finite RSI / EMA / ATR values and log returns).
        fl = [float(c) for c in adj]
        self.fl = array("d", fl)
        self.rsi = _floats(fp.rsi_series(fl))
        macd, sig = fp.macd_series(fl)
        self.macd, self.sig = _floats(macd), _floats(sig)
        # ATR restarts after every bar without a high or low (adjusted_columns: the tail after the last such bar).
        atr: list[float | None] = [None] * n
        start = 0
        for k in range(n + 1):
            if k == n or kept[k][2] is None or kept[k][3] is None:
                if k > start:
                    seg = range(start, k)
                    atr[start:k] = fp.atr_series(
                        [float(kept[j][2] * fpp[j]) for j in seg],
                        [float(kept[j][3] * fpp[j]) for j in seg],
                        [fl[j] for j in seg],
                    )
                start = k + 1  # fmt: skip
        self.atr = _floats(atr)
        rmax, rmin = [], []
        hi = lo = None
        for c in adj:
            if hi is None or c > hi:
                hi = c
            if lo is None or c < lo:
                lo = c
            rmax.append(hi)
            rmin.append(lo)
        self.rmax, self.rmin = rmax, rmin
        # Daily log returns (lr[k] = log(fl[k] / fl[k-1]), the beta / volatility inputs; None where undefined, and
        # then the per-day functions run on that window as before) and their exact prefix sums for the volatility.
        lr: list[float | None] = [None] * n
        for k in range(1, n):
            a, b = fl[k - 1], fl[k]
            lr[k] = math.log(b / a) if a > 0 and b > 0 else None
        self.lr = _floats(lr)
        self.vsum = _ExactSums(lr)
        self.csum = _DecimalSums(adj)
        self.msum = self.csum if self.mom is adj else _DecimalSums(self.mom)
        self.volsum = _DecimalSums(self.vol)


def _floats(xs: list[float | None]) -> array:
    return array("d", [_NAN if x is None else x for x in xs])


def _opt(x: float) -> float | None:
    return None if x != x else x


_NAN = float("nan")


class _DecimalSums:
    """Prefix sums of Decimals (None counted apart), kept only when every partial sum is exact in the default
    28-digit context: then a window's sum is two prefix sums apart, the same value as summing the window (the
    per-day expressions are compared and rounded by value: quotients, floats, quantize). Otherwise `window` returns
    None and the caller sums the window as before (adjusted series with long factors)."""

    __slots__ = ("nones", "sums")

    _CTX = decimal.Context(prec=decimal.getcontext().prec, traps=[decimal.Inexact, decimal.InvalidOperation])

    def __init__(self, xs: list) -> None:
        sums: list[Decimal] | None = [Decimal(0)]
        nones, acc, nn = [0], Decimal(0), 0
        try:
            for x in xs:
                if x is None:
                    nn += 1
                else:
                    acc = self._CTX.add(acc, x)
                sums.append(acc)
                nones.append(nn)
        except (decimal.Inexact, decimal.InvalidOperation):
            sums = None
        self.sums, self.nones = sums, nones

    def window(self, lo: int, hi: int) -> Decimal | None:
        """sum(xs[lo:hi]) when exact and the window holds no None; None otherwise (use the per-day sum)."""
        if self.sums is None or len(self.nones) <= hi or self.nones[hi] != self.nones[lo]:
            return None
        try:
            return self._CTX.subtract(self.sums[hi], self.sums[lo])
        except (decimal.Inexact, decimal.InvalidOperation):
            return None


class _ExactSums:
    """Exact prefix sums of x and x² over finite floats (None breaks the run): every float is an integer multiple of
    2^-scale, so the sums are integers and a window's sums are two subtractions. `stdev` reproduces
    statistics.stdev (Python >= 3.12: the exact sample variance from Fractions, then a correctly rounded square
    root) from them; without that implementation detail it falls back to statistics.stdev on the window."""

    __slots__ = ("bad", "scale", "sx", "sxx")

    def __init__(self, xs: list[float | None]) -> None:
        ratios = [None if x is None else x.as_integer_ratio() for x in xs]
        self.scale = max((d.bit_length() - 1 for r in ratios if r is not None for d in (r[1],)), default=0)
        sx, sxx, bad = [0], [0], [0]
        a = aa = nb = 0
        for r in ratios:
            if r is None:
                nb += 1
            else:
                v = r[0] << (self.scale - (r[1].bit_length() - 1))
                a += v
                aa += v * v
            sx.append(a)
            sxx.append(aa)
            bad.append(nb)
        self.sx, self.sxx, self.bad = sx, sxx, bad

    def stdev(self, xs: list[float | None], lo: int, hi: int) -> float:
        """statistics.stdev(xs[lo:hi])."""
        c = hi - lo
        if _FLOAT_SQRT_OF_FRAC is None or self.bad[hi] != self.bad[lo] or c < 2:
            return statistics.stdev(list(xs[lo:hi]))
        sx = self.sx[hi] - self.sx[lo]
        sxx = self.sxx[hi] - self.sxx[lo]
        num = c * sxx - sx * sx
        q = Fraction(num, c * (c - 1) << (2 * self.scale))
        return _FLOAT_SQRT_OF_FRAC(q.numerator, q.denominator)


_FLOAT_SQRT_OF_FRAC = getattr(statistics, "_float_sqrt_of_frac", None)


class _Security:
    __slots__ = ("bars", "dates", "factors", "frozen", "in_index", "index_lr", "regimes")

    def __init__(self, bars: list[tuple], factors: list[tuple], frozen: date | None, index: dict) -> None:
        self.bars = bars
        self.dates = [b[0] for b in bars]
        self.factors = factors  # accepted (ex, price_factor, eps_factor), query order
        self.frozen = frozen
        self.regimes: dict[int, _Regime] = {}
        acc, ins = 0, [0]
        for d in self.dates:
            acc += d in index
            ins.append(acc)
        self.in_index = ins  # in_index[k] = bars among the first k whose date has an index close
        ilr: list[float | None] = [None]
        for a, b in pairwise(self.dates):
            ia, ib = index.get(a), index.get(b)
            ilr.append(math.log(ib / ia) if ia and ib and ia > 0 and ib > 0 else None)
        self.index_lr = ilr  # Nifty 500 log return between this security's consecutive bars

    def active(self, as_of: date) -> tuple[list[tuple], int]:
        """Factors with ex-date <= as_of (query order) and a regime key (bit set of their positions)."""
        out, key = [], 0
        for i, fac in enumerate(self.factors):
            if fac[0] <= as_of:
                out.append(fac)
                key |= 1 << i
        return out, key

    def regime(self, as_of: date) -> _Regime:
        active, key = self.active(as_of)
        r = self.regimes.get(key)
        if r is None:  # days run in ascending order: an earlier regime is not needed again (rebuilt if it is)
            r = _Regime(self.bars, active, self.frozen)
            self.regimes = {key: r}
        return r


class PriceHistory:
    """See the module docstring. `securities` restricts every read to those securities (incremental runs)."""

    def __init__(self, con, exchange: str, through: date, securities=None) -> None:
        enabled = gc.isenabled()
        gc.disable()  # millions of new long-lived objects: no point in collecting while they are created
        try:
            self._load(con, exchange, through, securities)
        finally:
            if enabled:
                gc.enable()

    def _load(self, con, exchange: str, through: date, securities) -> None:
        from financials.fundamentals import entity_filter

        self.exchange, self.through = exchange, through
        self._settle = False
        self.fundamentals = None  # the run's features.FundamentalsCache (set by features.materialize_run)
        only, only_p = entity_filter("security_id", securities)
        interned: dict[date, date] = {}
        bars: dict[str, list[tuple]] = defaultdict(list)
        for sec, d, *rest in con.execute(
            "SELECT security_id, trade_date, close, high, low, volume, turnover_inr, deliv_qty FROM ohlcv "
            "WHERE exchange = ? AND trade_date <= ?" + only + " ORDER BY security_id, trade_date",
            [exchange, through, *only_p],
        ).fetchall():
            bars[sec].append((interned.setdefault(d, d), *rest))
        # features._price_inputs (knowledge="valid"): every accepted action with a price factor, in query order;
        # a day keeps those with ex-date <= as_of.
        factors: dict[str, list[tuple]] = defaultdict(list)
        for sec, ex, pf, ef, status in con.execute(
            "SELECT security_id, ex_date, price_factor, eps_factor, status FROM corp_actions WHERE ex_date <= ?" + only,
            [through, *only_p],
        ).fetchall():
            if status in ACCEPTED_STATUSES and pf is not None:
                factors[sec].append((ex, Decimal(str(pf)), Decimal(str(ef if ef is not None else 1))))
        frozen = dict(
            con.execute(
                "SELECT security_id, min(CAST(json_extract_string(details, '$.trade_date') AS DATE)) "
                "FROM quarantine_queue WHERE stage = 'GAP' AND resolved_at IS NULL" + only + " GROUP BY security_id",
                only_p,
            ).fetchall()
        )
        self._build(bars, factors, frozen, fp.index_closes(con, through))

    @classmethod
    def from_data(cls, exchange: str, through: date, bars: dict, factors: dict, frozen: dict, index: dict):
        """From in-memory inputs in the shapes the queries return: bars (date, close, high, low, volume,
        turnover_inr, deliv_qty) ascending per security, accepted (ex, price_factor, eps_factor) per security,
        GAP freeze date per security, index closes by date (tests)."""
        self = cls.__new__(cls)
        self.exchange, self.through, self._settle, self.fundamentals = exchange, through, False, None
        self._build({k: list(v) for k, v in bars.items()}, factors, frozen, index)
        return self

    def _build(self, bars: dict, factors: dict, frozen: dict, index: dict) -> None:
        self.frozen, self.index, self._factors = frozen, index, factors
        self._securities = {
            sec: _Security(b, factors.get(sec, []), frozen.get(sec), index) for sec, b in bars.items() if b
        }

    @contextmanager
    def frozen_heap(self) -> Iterator[PriceHistory]:
        """A run holds millions of long-lived objects (bars, series): the cyclic garbage collector would traverse
        them all on every full collection, more than half of a day's time. They are frozen (gc.freeze) for the run
        and after every day (`settle`, after collecting that day's garbage); unfrozen when the run ends. Reference
        counting still frees them as usual (the series hold no reference cycles). Automatic collection is off for
        the run: `settle` collects once per day."""
        enabled = gc.isenabled()
        gc.disable()
        gc.collect()
        gc.freeze()
        self._settle = True
        try:
            yield self
        finally:
            self._settle = False
            gc.unfreeze()
            if enabled:
                gc.enable()

    def settle(self) -> None:
        """End of a materialised day inside `frozen_heap`: collect the day's garbage, freeze what survives."""
        if self._settle:
            gc.collect()
            gc.freeze()

    def covers(self, exchange: str, as_of: date) -> bool:
        return exchange == self.exchange and as_of <= self.through

    # ── the per-day inputs of features.compute_rows ──────────────────────────────────────────────────────────

    def inputs(self, as_of: date, securities=None):
        """(bars, factors, frozen) as features._price_inputs returns them for `as_of` (knowledge="valid"), except
        that each security's bars are only its last DELIVERY_TAIL (date, close, deliv_qty): the rest of the history
        is read through `momentum` / `price_columns` / `more_price_columns`."""
        bars: dict[str, list[tuple]] = {}
        factors: dict[str, list[tuple]] = {}
        frozen: dict[str, date] = {}
        for sec, s in self._securities.items():
            if securities is not None and sec not in securities:
                continue
            n = bisect.bisect_right(s.dates, as_of)
            if n:
                bars[sec] = [(b[0], b[1], b[6]) for b in s.bars[max(0, n - DELIVERY_TAIL) : n]]
            active, _ = s.active(as_of)
            if active:
                factors[sec] = active
            if s.frozen is not None:
                frozen[sec] = s.frozen
        for sec in self._factors.keys() - self._securities.keys():  # actions of securities without bars
            if securities is None or sec in securities:
                active = [f for f in self._factors[sec] if f[0] <= as_of]
                if active:
                    factors[sec] = active
        for sec, fz in self.frozen.items():
            if sec not in self._securities and (securities is None or sec in securities):
                frozen[sec] = fz
        return bars, factors, frozen

    def _at(self, sec: str, as_of: date) -> tuple[_Security | None, int]:
        s = self._securities.get(sec)
        if s is None:
            return None, 0
        return s, bisect.bisect_right(s.dates, as_of)

    def _frozen_today(self, s: _Security, n: int) -> bool:
        return s.frozen is not None and s.dates[n - 1] >= s.frozen

    # ── features._momentum ───────────────────────────────────────────────────────────────────────────────────

    def momentum(self, sec: str, as_of: date) -> dict:
        s, n = self._at(sec, as_of)
        if not n:
            return _momentum_empty()
        if self._frozen_today(s, n):
            return _momentum_empty()
        r = s.regime(as_of)
        adj = r.mom
        last = adj[n - 1]
        out: dict = {}
        for name, k in (("return_1m", 21), ("return_3m", 63), ("return_6m", 126), ("return_12m", 252)):
            out[name] = _f(last / adj[n - 1 - k] - 1) if n > k and adj[n - 1 - k] else None
        for name, k in (("price_to_dma50", 50), ("price_to_dma200", 200)):
            if n >= k:
                total = r.msum.window(n - k, n)
                out[name] = _f(last / ((sum(adj[n - k : n]) if total is None else total) / k))
            else:
                out[name] = None
        out["dist_52w_high"] = _f(last / max(adj[n - 252 : n]) - 1) if n >= 252 else None
        return out

    # ── features_price.price_columns ─────────────────────────────────────────────────────────────────────────

    def price_columns(self, sec: str, as_of: date) -> dict:
        s, n = self._at(sec, as_of)
        if not n:
            return fp.price_columns([], [], None, self.index)
        raw = s.bars[max(0, n - fp.LIQUIDITY_BARS) : n]
        out = fp.raw_columns(raw)
        if self._frozen_today(s, n):
            return {**dict.fromkeys(fp.PRICE_COLUMNS), **out}
        r = s.regime(as_of)
        out |= self._adjusted_columns(s, r, n)
        if n >= fp.LIQUIDITY_BARS:
            vols = r.vol[n - fp.LIQUIDITY_BARS : n]
            if None not in vols and None not in [b[5] for b in raw]:
                vol = sum(vols, Decimal(0))
                out["vwap_20d"] = fp._q(sum((Decimal(b[5]) for b in raw), Decimal(0)) / vol) if vol else None
        return out

    def _adjusted_columns(self, s: _Security, r: _Regime, n: int) -> dict:
        """features_price.adjusted_columns on the first n bars of regime `r` (n >= 1)."""
        index = self.index
        out = dict.fromkeys(c for c in fp.PRICE_COLUMNS if c not in fp.RAW_COLUMNS)
        c = r.adj
        last = c[n - 1]
        for name, k in fp.RETURN_BARS.items():
            out[name] = float(last / c[n - 1 - k] - 1) if n > k and c[n - 1 - k] else None
        for name, k in fp.VOLUME_BARS.items():
            if n >= k:
                total = r.volsum.window(n - k, n)
                if total is not None:
                    out[name] = float(total / k)
                else:
                    tail = r.vol[n - k : n]
                    out[name] = float(sum(tail) / k) if None not in tail else None
        y = fp.YEAR_BARS
        if n >= y:
            window = c[n - y : n]
            hi, lo = max(window), min(window)
            out["high_52w"], out["low_52w"] = fp._q(hi), fp._q(lo)
            out["dist_52w_low"] = float(last / lo - 1) if lo else None
        out["high_since_data_start"], out["low_since_data_start"] = fp._q(r.rmax[n - 1]), fp._q(r.rmin[n - 1])
        for k in (50, 200):
            for col, lag in ((f"dma{k}", 0), (f"dma{k}_prev", 1)):
                if n < k + lag:
                    continue  # features_price.sma: NULL without k values
                total = r.csum.window(n - lag - k, n - lag)
                out[col] = fp._q(fp.sma(c[n - lag - k : n - lag], k) if total is None else total / k)
        out["rsi_14"], out["rsi_14_prev"] = _opt(r.rsi[n - 1]), _opt(r.rsi[n - 2]) if n >= 2 else None
        out["macd"], out["macd_prev"] = _opt(r.macd[n - 1]), _opt(r.macd[n - 2]) if n >= 2 else None
        out["macd_signal"], out["macd_signal_prev"] = _opt(r.sig[n - 1]), _opt(r.sig[n - 2]) if n >= 2 else None
        atr, fl = _opt(r.atr[n - 1]), r.fl
        out["atr_14_pct"] = atr / fl[n - 1] if atr is not None and fl[n - 1] else None
        dates = s.dates
        for name, k in fp.RS_BARS.items():
            if n > k and dates[n - 1] in index and dates[n - 1 - k] in index and c[n - 1 - k]:
                out[name] = float(last / c[n - 1 - k]) - index[dates[n - 1]] / index[dates[n - 1 - k]]
        if n >= y + 1 and s.in_index[n] - s.in_index[n - y - 1] == y + 1:
            rs, rm = r.lr[n - y : n], s.index_lr[n - y : n]
            if r.vsum.bad[n] != r.vsum.bad[n - y] or None in rm:  # an undefined log return: the per-day function
                out["beta_1y_nifty500"] = fp.beta(list(fl[n - y - 1 : n]), [index[d] for d in dates[n - y - 1 : n]])
            else:
                out["beta_1y_nifty500"] = _beta(rs, rm)
        return out

    # ── features_more.price_columns ──────────────────────────────────────────────────────────────────────────

    def more_price_columns(self, row: dict, as_of: date) -> dict:
        out = dict.fromkeys((*fm.PRICE_COLUMNS, *fm.PEAD_COLUMNS))
        r12, r1 = row.get("return_12m"), row.get("return_1m")
        if r12 is not None and r1 is not None and r1 > -1:
            out["momentum_12m_1m"] = (1 + r12) / (1 + r1) - 1
        s, n = self._at(row["security_id"], as_of)
        # features_more.load_bars: the bars of the last BAR_LOOKBACK_DAYS calendar days only
        w = bisect.bisect_right(s.dates, as_of - timedelta(days=fm.BAR_LOOKBACK_DAYS), 0, n) if n else 0
        if n <= w or self._frozen_today(s, n):
            return out
        r = s.regime(as_of)
        fl, y = r.fl, fm.YEAR_BARS
        m = n - w  # bars in the window
        if m >= y + 1:  # features_more.volatility on the last y + 1 closes: the y log returns ending at bar n - 1
            if r.vsum.bad[n] != r.vsum.bad[n - y]:  # an undefined log return: the per-day function, as before
                out["volatility_1y"] = fm.volatility(list(fl[n - y - 1 : n]))
            else:
                out["volatility_1y"] = r.vsum.stdev(r.lr, n - y, n) * math.sqrt(y)
        out["max_drawdown_1y"] = fm.max_drawdown(list(fl[n - y : n])) if m >= y else None
        out["high_52w_on_delivery_spike"] = self._delivery_spike(s, r, n) if m >= y else None
        out |= self._pead(s, r, w, n, row.get("last_result_date"))
        return out

    @staticmethod
    def _delivery_spike(s: _Security, r: _Regime, n: int) -> bool | None:
        fl = r.fl
        if fl[n - 1] < max(fl[n - fm.YEAR_BARS : n]):
            return False
        lo = n - fm.SPIKE_BARS - 1
        deliv = [None if s.bars[j][6] is None else float(s.bars[j][6] / r.fpp[j]) for j in range(lo, n)]
        if None in deliv:
            return None
        return deliv[-1] > fm.SPIKE_MULTIPLE * statistics.median(deliv[:-1])

    def _pead(self, s: _Security, r: _Regime, w: int, n: int, event: date | None) -> dict:
        out = dict.fromkeys(fm.PEAD_COLUMNS)
        if event is None:
            return out
        i0 = bisect.bisect_left(s.dates, event, w, n)
        if i0 >= n or i0 == w:
            return out
        index = self.index
        out["pead_event_date"] = event
        base_d, base_c = s.dates[i0 - 1], r.fl[i0 - 1]
        vols = [None if v is None else float(v) for v in r.vol[max(w, i0 - fm.PEAD_BASE_BARS) : i0]]
        base_vol = statistics.fmean(vols) if len(vols) == fm.PEAD_BASE_BARS and None not in vols else None
        for k in fm.PEAD_DAYS:
            if i0 + k >= n:
                continue
            d, c, v = s.dates[i0 + k], r.fl[i0 + k], r.vol[i0 + k]
            if base_d in index and d in index and base_c:
                out[f"pead_ar_t{k}"] = c / base_c - index[d] / index[base_d]
            if base_vol and v is not None:
                out[f"pead_relvol_t{k}"] = float(v) / base_vol
        return out


def _beta(rs: list[float], rm: list[float]) -> float | None:
    """features_price.beta from the two log-return series (the same expressions, in the same order)."""
    if len(rs) < 2:
        return None
    ms, mm = statistics.fmean(rs), statistics.fmean(rm)
    var = sum((x - mm) ** 2 for x in rm)
    if var == 0:
        return None
    return sum((x - ms) * (y - mm) for x, y in zip(rs, rm, strict=True)) / var


def _f(x) -> float | None:
    return None if x is None else float(x)


def _momentum_empty() -> dict:
    return dict.fromkeys(("return_1m", "return_3m", "return_6m", "return_12m", "price_to_dma50", "price_to_dma200",
                          "dist_52w_high"))  # fmt: skip
