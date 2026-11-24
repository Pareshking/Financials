"""A full materialize run publishes many days per transaction (features._materialize_batched, architecture §11.11)
and leaves exactly the tables of the day-by-day run (`materialize_days(..., batch_days=1)`, one transaction a day):
every row of features_daily, features_events (the intervals themselves, not only the view), market_breadth,
screener_features, features_meta (but its timestamp) and materialize_dirty, NULLs included, Decimals with their
exponent, floats bit for bit. On the fixture databases of tests/test_incremental_materialize.py (fixture market with
results, shareholding, a corporate-action batch) and tests/test_materialize_fast_path.py (the full fixture market,
and the same extended with synthetic histories over five quarters), with batches that end inside and at quarter
ends, a gate failure and an error in the middle of a batch, and the X325 dq_flags / dq_suspect columns filled by
open findings.
"""

from __future__ import annotations

import io
import math
import shutil
from datetime import date
from decimal import Decimal

import pytest
from conftest import build_full_market
from test_incremental_materialize import base  # noqa: F401  (module fixture: the materialised fixture market)

from financials import features
from financials.bench import extend_synthetic
from financials.cli import materialize_dates
from financials.db import connect

TABLES = {
    "features_daily": "as_of_date, security_id",
    "features_events": "security_id, valid_from_date",
    "market_breadth": "as_of_date, universe",
    "screener_features": "security_id",
    "features_meta": "as_of_date",
    "materialize_dirty": "dirty_id",
}
EXCLUDED = {"features_meta": {"materialized_at"}}


def identical(a, b) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        return (math.isnan(a) and math.isnan(b)) or (a == b and math.copysign(1, a) == math.copysign(1, b))
    if isinstance(a, Decimal) and isinstance(b, Decimal):
        return a == b and a.as_tuple() == b.as_tuple()
    return type(a) is type(b) and a == b


def tables(con) -> dict[str, tuple[list[str], list[tuple]]]:
    out = {}
    for t, order in TABLES.items():
        cols = [c for (c,) in con.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ? ORDER BY ordinal_position", [t]
        ).fetchall() if c not in EXCLUDED.get(t, ())]  # fmt: skip
        out[t] = (cols, con.execute(f"SELECT {', '.join(cols)} FROM {t} ORDER BY {order}").fetchall())
    return out


def assert_identical(new: dict, old: dict) -> None:
    for t in TABLES:
        (cols, a), (cols_b, b) = new[t], old[t]
        assert cols == cols_b, t
        assert len(a) == len(b), (t, len(a), len(b))
        bad = [(t, ra[:2], c, x, y) for ra, rb in zip(a, b, strict=True)
               for c, x, y in zip(cols, ra, rb, strict=True) if not identical(x, y)]  # fmt: skip
        assert not bad, bad[:20]


def run(path, days, batch_days, monkeypatch=None, fail=None) -> tuple[list, dict]:
    """materialize_days over `days` on `path` (one run), then every compared table."""
    con = connect(path)
    try:
        with features.materialize_run(con, days) as prices:
            res = features.materialize_days(con, days, prices=prices, batch_days=batch_days)
        if all(r.status == "PROMOTED" for r in res) and len(res) == len(days):
            features.settle_full_run(con, days)
        return [(r.status, r.as_of_date, r.rows, r.gate, r.message) for r in res], tables(con)
    finally:
        con.close()


def both(src, tmp_path, days, batch_days=3, **kw) -> tuple[list, dict]:
    out = {}
    for name, n in (("day_by_day", 1), ("batched", batch_days)):
        path = tmp_path / f"{name}.duckdb"
        shutil.copy(src, path)
        out[name] = run(path, days, n, **kw)
    (res_new, new), (res_old, old) = out["batched"], out["day_by_day"]
    assert res_new == res_old
    assert_identical(new, old)
    return res_new, new


def stored_days(path) -> list[date]:
    con = connect(path, read_only=True)
    try:
        return [d for (d,) in con.execute("SELECT DISTINCT trade_date FROM ohlcv ORDER BY 1").fetchall()]
    finally:
        con.close()


def open_finding(path, symbol: str) -> None:
    """An open entity finding (X325 OPEN_FINDING flag) on `symbol`'s entity, for its latest results period."""
    con = connect(path)
    try:
        ent, fid = con.execute(
            "SELECT s.entity_id, arg_max(f.filing_id, (f.period_end, f.filing_id)) FROM security_identifier_history h "
            "JOIN securities s USING (security_id) JOIN filing_meta f ON f.entity_id = s.entity_id "
            "WHERE h.symbol = ? GROUP BY 1",
            [symbol],
        ).fetchone()
        con.execute(
            "INSERT INTO quarantine_queue (quarantine_id, stage, filing_id, entity_id, reason_code, details, "
            "created_at) VALUES ('test-open-finding', 'TEST', ?, ?, 'CROSS_CHECK_FAILED', '{}', "
            "TIMESTAMP '2025-01-01 00:00:00')",
            [fid, ent],
        )
    finally:
        con.close()


@pytest.fixture(scope="module")
def full_market(tmp_path_factory):
    root = tmp_path_factory.mktemp("batched_full_market")
    m = build_full_market(root)
    m.con.close()
    return root / "market.duckdb"


def test_incremental_fixture_db_batched_equals_day_by_day(base, tmp_path, monkeypatch):  # noqa: F811
    """Also with the run's slices exercised: the readers of a batch whose entities' inputs become visible in it
    read them from the slices (`_FullRunSlices.reader`)."""
    days = stored_days(base)
    sources = []
    real = features._FullRunSlices.reader

    def reader(self, stale):
        out = real(self, stale)
        sources.append(out is self.cur)
        return out

    monkeypatch.setattr(features._FullRunSlices, "reader", reader)
    res, new = both(base, tmp_path, days, batch_days=2)
    assert [r[0] for r in res] == ["PROMOTED"] * len(days)
    cols, rows = new["features_daily"]
    assert {r[cols.index("as_of_date")] for r in rows} == set(days)
    assert True in sources and False in sources  # slices and the database both read


@pytest.mark.parametrize("batch_days", [2, 20])
def test_full_fixture_market_batched_equals_day_by_day(full_market, tmp_path, batch_days):
    days = stored_days(full_market)
    res, new = both(full_market, tmp_path, days, batch_days=batch_days)
    assert len(res) == len(days)
    cols, rows = new["features_daily"]
    flagged = [r for r in rows if r[cols.index("dq_flags")] is not None]
    assert flagged and all(r[cols.index("dq_suspect")] is True for r in flagged)  # X325 columns compared, not NULL


def test_open_finding_flags_are_identical(full_market, tmp_path):
    src = tmp_path / "flagged.duckdb"
    shutil.copy(full_market, src)
    open_finding(src, "ELIN")
    _, new = both(src, tmp_path, stored_days(src))
    cols, rows = new["features_daily"]
    assert any("OPEN_FINDING:CROSS_CHECK_FAILED" in (r[cols.index("dq_flags")] or "") for r in rows)


def test_long_synthetic_history_batched_equals_day_by_day(full_market, tmp_path, monkeypatch):
    """Every weekday over three quarters, batches of 7 days ending inside quarters and cut at every quarter end: a
    quarter's first day reads the valuation history of the run's earlier quarters (FundamentalsCache.per_quarter),
    which the batched run has committed by then; both runs read the same histories."""
    path = tmp_path / "synthetic.duckdb"
    shutil.copy(full_market, path)
    all_days = extend_synthetic(path, 40, date(2024, 10, 1), date(2025, 12, 31))
    days = [d for d in all_days if d >= date(2025, 6, 2)]
    reads: list[tuple] = []
    real = features._valuation_history

    def history(con, as_of, securities=None):
        out = real(con, as_of, securities)
        reads.append((as_of, sorted((s, tuple(v["pe"]), tuple(v["ev_ebitda"])) for s, v in out.items())))
        return out

    monkeypatch.setattr(features, "_valuation_history", history)
    res, _ = both(path, tmp_path, days, batch_days=7)
    assert len(res) == len(days)
    half = len(reads) // 2
    assert reads[:half] == reads[half:]  # day by day, then batched: the same reads, the same histories
    assert any(d >= date(2025, 7, 1) and h for d, h in reads[:half])  # Q3 and Q4 read the run's earlier quarters


def test_gate_failure_inside_a_batch_publishes_the_days_before_it(full_market, tmp_path, monkeypatch):
    days = stored_days(full_market)
    stop = days[3]
    real = features._g4_spikes

    def g4(con, prev, rows):
        if rows and rows[0]["as_of_date"] == stop:
            return {"close": (0.0, 1.0)}
        return real(con, prev, rows)

    monkeypatch.setattr(features, "_g4_spikes", g4)
    res, new = both(full_market, tmp_path, days, batch_days=10)
    assert [r[0] for r in res] == ["PROMOTED"] * 3 + ["ABORTED"] and res[-1][3] == "G4"
    assert new["screener_features"][1]  # the live table of the last published day


def test_error_inside_a_batch_publishes_the_days_before_it(full_market, tmp_path, monkeypatch):
    days = stored_days(full_market)
    stop = days[4]
    real = features.compute_rows

    def compute(con, as_of, *a, **k):
        if as_of == stop:
            raise RuntimeError("boom")
        return real(con, as_of, *a, **k)

    monkeypatch.setattr(features, "compute_rows", compute)
    out = {}
    for name, n in (("day_by_day", 1), ("batched", 10)):
        path = tmp_path / f"{name}.duckdb"
        shutil.copy(full_market, path)
        with pytest.raises(RuntimeError, match="boom"):
            run(path, days, n)
        con = connect(path, read_only=True)
        out[name] = tables(con)
        con.close()
    assert_identical(out["batched"], out["day_by_day"])


def test_materialize_dates_batches_a_full_run(full_market, tmp_path, monkeypatch):
    """`materialize --from/--to` takes the batched path: one transaction per batch, not per day."""
    path = tmp_path / "m.duckdb"
    shutil.copy(full_market, path)
    calls = []
    real = features._publish_days

    def publish(con, batch, snapshot):
        calls.append(len(batch))
        real(con, batch, snapshot)

    monkeypatch.setattr(features, "_publish_days", publish)
    con = connect(path)
    try:
        assert materialize_dates(con, None, date(2024, 10, 1), None, io.StringIO()) == 0
    finally:
        con.close()
    assert sum(calls) == len(stored_days(path)) and len(calls) < sum(calls)
