"""Event-sparse screener_features_history (features_store.py, architecture §4.1).

1. The split: every screener_features column is stored in exactly one of features_daily / features_events, the
   view has screener_features' exact names, order and types, and every column a refresh step UPDATEs or a
   multi-day reader takes from features_daily is a DAILY column.
2. The interval store against a plain dict model: random writes in any order (whole days, single securities,
   incremental-style replacements, rebuild-market deletions) read back exactly through the view, keep the
   invariants, and leave the same intervals as writing the final rows day by day.
3. The fixture market materialised with a shadow wide table written the old way (DELETE + INSERT of the full rows,
   the cross-section UPDATEs run on it): full run, incremental run, an out-of-order day, rebuild-market and the
   one-off migration of a wide table all give identical rows (Decimals with their exponent, floats bit for bit,
   NULLs).
"""

from __future__ import annotations

import io
import random
import shutil
from datetime import date, timedelta
from decimal import Decimal

import pytest
from conftest import build_full_market
from test_materialize_fast_path import identical

from financials import features, features_gems, features_more, features_peers, features_store
from financials.db import apply_schema, connect, declared_columns, fetch_dicts, insert_rows
from financials.features_store import DAILY_COLUMNS, EVENT_COLUMNS

# ── 1. the split ─────────────────────────────────────────────────────────────────────────────────────────────────


def test_every_feature_column_is_stored_in_exactly_one_table():
    decl = declared_columns()
    live = decl["screener_features"]
    daily = decl["features_daily"]
    events = decl["features_events"]
    assert [c for c, _ in events[:3]] == ["security_id", "valid_from_date", "valid_to_date"]
    event_cols = [c for c, _ in events[3:]]
    assert tuple(event_cols) == EVENT_COLUMNS
    assert tuple(c for c, _ in daily) == DAILY_COLUMNS
    names = [c for c, _ in live]
    assert len(set(EVENT_COLUMNS)) == len(EVENT_COLUMNS) and not set(EVENT_COLUMNS) & set(DAILY_COLUMNS)
    assert sorted([*DAILY_COLUMNS, *EVENT_COLUMNS]) == sorted(names)
    # both tables keep screener_features' order and definitions
    assert [c for c in names if c in set(DAILY_COLUMNS)] == list(DAILY_COLUMNS)
    assert [c for c in names if c in set(EVENT_COLUMNS)] == list(EVENT_COLUMNS)
    types = dict(live)
    assert all(types[c] == t for c, t in daily) and all(types[c] == t for c, t in events[3:])
    assert {"as_of_date", "security_id", "entity_id", "symbol", "series"} <= set(DAILY_COLUMNS)


def test_view_has_the_live_tables_columns_and_types():
    con = connect()
    apply_schema(con)
    q = "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = ? ORDER BY ordinal_position"
    assert con.execute(q, ["screener_features_history"]).fetchall() == con.execute(q, ["screener_features"]).fetchall()


def test_updated_and_daily_only_reads_are_daily_columns():
    daily = set(DAILY_COLUMNS)
    for mod in (features_gems, features_peers, features_more):  # UPDATE features_daily in refresh_cross_section
        assert set(mod.CROSS_COLUMNS) <= daily, mod.__name__
    # multi-day history reads that go to features_daily directly (no interval join)
    assert {"pe", "ev_ebitda", *features_more.PERCENTILES.values()} <= daily
    # features_price.refresh_breadth
    breadth = {"in_nifty500", "price_to_dma50", "price_to_dma200", "dist_52w_high", "dist_52w_low", "return_1d"}
    assert breadth <= daily


def test_price_day_and_outside_key_columns_are_daily():
    """Structural review (architecture §4.1): what reads the day's price / shares / EV, a window that moves with the
    as-of date, or an input outside the FundamentalsCache key is never an EVENT column."""
    from financials import features_bs, features_extra, features_pl, features_price

    must_be_daily = {
        "close", "market_cap", "enterprise_value", "shares", "pe", "pb", "ev_ebitda", "eps_ttm", "in_nifty500",
        "promoter_pct", "shp_as_of", "dividend_yield_pct", "pe_percentile", "reverse_dcf_implied_g",
        "persistency_13m", "persistency_61m", "book_value_per_share", "is_trade_to_trade", "graham_number",
        "dilution_1y", "shareholder_yield", "pe_core", "peg", "earnings_yield", "industry", "cyclical_flag",
        "forensic_clean", "altman_z_original", "net_cash_to_market_cap", "pe_numerator", "ev_ebitda_numerator",
        "pead_event_date", "days_to_next_ex_date",
        *features.SHAREHOLDING_COLUMNS, *features.EVENT_COLUMNS, *features.KPI_COLUMNS,
        *features_price.PRICE_COLUMNS, *features_price.RAW_COLUMNS, *features_pl.EPS_COLUMNS,
        *features_bs.COUNT_COLUMNS, *features_extra.VALUATION_COLUMNS, *features_extra.FLOW_COLUMNS,
        *features_gems.OWNERSHIP_COLUMNS, *features_peers.COLUMNS, *features_more.PRICE_COLUMNS,
        *features_more.PEAD_COLUMNS, *features_more.EVENT_COLUMNS, *features_more.PERCENTILES,
    }  # fmt: skip
    assert not must_be_daily & set(EVENT_COLUMNS)
    assert {f"eps_growth_{n}y_pct" for n in features_pl.GROWTH_YEARS} <= set(DAILY_COLUMNS)


# ── 2. the interval store against a model ────────────────────────────────────────────────────────────────────────

SECS = ("S1", "S2", "S3", "S4")
DAYS = tuple(date(2025, 1, 1) + timedelta(days=i) for i in range(0, 40, 2))


def _row(rng: random.Random, d: date, sec: str, regime: int) -> dict:
    """A row whose EVENT values depend only on `regime` (so they repeat), DAILY values change every day."""
    r = {c: None for c in features_store.COLUMNS}
    r.update(as_of_date=d, security_id=sec, entity_id="E" + sec, symbol=sec, series="EQ",
             close=Decimal(rng.randint(100, 99999)) / 100, pe=rng.random())  # fmt: skip
    r.update(sales_ttm=Decimal(1000 + regime) if regime % 3 else None, roe=0.1 * regime,
             scope_used="CONSOLIDATED" if regime % 2 else "STANDALONE", piotroski_f=regime,
             fundamentals_end=date(2025, 3, 31) + timedelta(days=regime))  # fmt: skip
    return r


def _view(con) -> dict[tuple, dict]:
    return {(r["as_of_date"], r["security_id"]): r for r in fetch_dicts(con, "SELECT * FROM screener_features_history")}


def _norm(r: dict) -> dict:
    return {c: r.get(c) for c in features_store.COLUMNS}


def _same_rows(con, model: dict[tuple, dict]) -> None:
    got = _view(con)
    assert got.keys() == model.keys()
    for k, r in model.items():
        want = _norm(r)
        bad = {c: (got[k][c], want[c]) for c in want if not (got[k][c] == want[c] and (got[k][c] is None) ==
                                                             (want[c] is None))}  # fmt: skip
        assert not bad, (k, bad)
    assert features_store.check_invariants(con) == dict.fromkeys(
        ("overlaps", "identical_neighbours", "uncovered", "multiply_covered"), 0
    )


def _intervals(con) -> list[tuple]:
    return con.execute("SELECT * FROM features_events ORDER BY security_id, valid_from_date").fetchall()


@pytest.mark.parametrize("seed", range(6))
def test_random_writes_read_back_exactly_and_canonically(seed):
    rng = random.Random(seed)
    con = connect()
    apply_schema(con)
    model: dict[tuple, dict] = {}
    regime = {s: 0 for s in SECS}
    for _ in range(60):
        op = rng.random()
        if op < 0.5:  # a whole day (any order), regimes moving now and then
            d = rng.choice(DAYS)
            rows = []
            for s in SECS:
                if rng.random() < 0.25:
                    regime[s] = rng.randint(0, 5)
                rows.append(_row(rng, d, s, regime[s]))
            con.execute("BEGIN")
            features_store.write_day(con, d, rows)
            con.execute("COMMIT")
            for k in [k for k in model if k[0] == d]:
                del model[k]
            model.update({(d, r["security_id"]): r for r in rows})
        elif op < 0.85:  # incremental-style: one entity's rows of one day replaced
            d, s = rng.choice(DAYS), rng.choice(SECS)
            r = _row(rng, d, s, rng.randint(0, 5))
            features_store.write_day(con, d, [r], entities=frozenset({"E" + s}))
            model[(d, s)] = r
        elif op < 0.95:  # rebuild-market
            cut = rng.choice(DAYS)
            features_store.delete_from(con, cut)
            model = {k: v for k, v in model.items() if k[0] < cut}
        else:
            features_store.truncate(con)
            model = {}
        _same_rows(con, model)
    # canonical: the same final rows written day by day from scratch give the same intervals
    other = connect()
    apply_schema(other)
    for d in sorted({k[0] for k in model}):
        features_store.write_day(other, d, [_norm(v) for k, v in sorted(model.items()) if k[0] == d])
    assert _intervals(con) == _intervals(other)


def test_unchanged_event_values_write_no_interval():
    con = connect()
    apply_schema(con)
    rng = random.Random(1)
    for d in DAYS:
        features_store.write_day(con, d, [_row(rng, d, s, 1) for s in SECS])
    assert con.execute("SELECT count(*) FROM features_daily").fetchone()[0] == len(DAYS) * len(SECS)
    assert con.execute("SELECT count(*), count(valid_to_date) FROM features_events").fetchone() == (len(SECS), 0)
    features_store.write_day(con, DAYS[-1], [_row(rng, DAYS[-1], "S1", 2)], entities=frozenset({"ES1"}))
    assert con.execute("SELECT valid_from_date, valid_to_date FROM features_events WHERE security_id = 'S1' "
                       "ORDER BY 1").fetchall() == [(DAYS[0], DAYS[-1]), (DAYS[-1], None)]  # fmt: skip


def test_write_rows_refuses_unknown_columns():
    con = connect()
    apply_schema(con)
    with pytest.raises(KeyError):
        features_store.write_rows(con, [{"as_of_date": DAYS[0], "security_id": "S", "nope": 1}])


# ── 3. the fixture market: shadow wide table vs the view ─────────────────────────────────────────────────────────


class _Rewrite:
    """A connection whose SQL reads and writes the shadow wide table instead of the history view / features_daily
    (to run the unchanged refresh steps on the shadow)."""

    def __init__(self, con) -> None:
        self._con = con

    def execute(self, sql, *args):
        return self._con.execute(sql.replace("screener_features_history", "wide").replace("features_daily", "wide"),
                                 *args)  # fmt: skip

    def __getattr__(self, name):
        return getattr(self._con, name)


def _shadow(monkeypatch, con) -> None:
    """Write every history change also into `wide` exactly as the code before event-sparse storage did."""
    con.execute("CREATE TABLE wide AS SELECT * FROM screener_features_history")
    real_write, real_delete = features_store.write_day, features_store.delete_from

    def write_day(con_, as_of, rows, *, entities=None):
        real_write(con_, as_of, rows, entities=entities)
        if entities is None:
            con_.execute("DELETE FROM wide WHERE as_of_date = ?", [as_of])
        else:
            from financials.fundamentals import in_list

            by_ent, by_sec = in_list("entity_id", entities), in_list("security_id", {r["security_id"] for r in rows})
            con_.execute(f"DELETE FROM wide WHERE as_of_date = ? AND ({by_ent[0]} OR {by_sec[0]})",
                         [as_of, *by_ent[1], *by_sec[1]])  # fmt: skip
        insert_rows(con_, "wide", rows)

    def delete_from(con_, from_date):
        con_.execute("DELETE FROM wide WHERE as_of_date >= ?", [from_date])
        return real_delete(con_, from_date)

    monkeypatch.setattr(features_store, "write_day", write_day)
    monkeypatch.setattr(features_store, "delete_from", delete_from)
    for mod in (features_gems, features_peers, features_more):
        real = mod.refresh_cross_section

        def refresh(con_, as_of, _real=real):
            _real(con_, as_of)
            _real(_Rewrite(con_), as_of)

        monkeypatch.setattr(mod, "refresh_cross_section", refresh)


def assert_view_equals_wide(con) -> int:
    cur = con.execute("SELECT * FROM screener_features_history ORDER BY as_of_date, security_id")
    cols = [d[0] for d in cur.description]
    a = cur.fetchall()
    cur = con.execute("SELECT * FROM wide ORDER BY as_of_date, security_id")
    assert [d[0] for d in cur.description] == cols
    b = cur.fetchall()
    assert len(a) == len(b) and a
    bad = [(ra[:2], c, x, y) for ra, rb in zip(a, b, strict=True)
           for c, x, y in zip(cols, ra, rb, strict=True) if not identical(x, y)]  # fmt: skip
    assert not bad, bad[:20]
    assert features_store.check_invariants(con) == dict.fromkeys(
        ("overlaps", "identical_neighbours", "uncovered", "multiply_covered"), 0
    )
    return len(a)


@pytest.fixture(scope="module")
def fixture_db(tmp_path_factory):
    root = tmp_path_factory.mktemp("store_base")
    m = build_full_market(root)
    m.con.close()
    return root / "market.duckdb"


def test_fixture_market_view_equals_the_wide_table(fixture_db, tmp_path, monkeypatch):
    from financials import dirty
    from financials.admin import rebuild_market
    from financials.cli import materialize_dates

    path = tmp_path / "m.duckdb"
    shutil.copy(fixture_db, path)
    con = connect(path)
    try:
        apply_schema(con)
        features_store.truncate(con)
        con.execute("DELETE FROM features_meta")
        con.execute("DELETE FROM market_breadth")
        _shadow(monkeypatch, con)
        out = io.StringIO()
        assert materialize_dates(con, None, date(2024, 10, 1), None, out) == 0, out.getvalue()  # full run
        n = assert_view_equals_wide(con)
        days = [d for (d,) in con.execute("SELECT DISTINCT as_of_date FROM features_daily ORDER BY 1").fetchall()]
        intervals = con.execute("SELECT count(*) FROM features_events").fetchone()[0]
        assert len(days) >= 3 and intervals < n  # sparse: fewer intervals than rows

        # an incremental run (dirty entities from a middle day), then one past day again, out of order
        ents = [
            e for (e,) in con.execute("SELECT DISTINCT entity_id FROM features_daily ORDER BY 1 LIMIT 40").fetchall()
        ]
        dirty.mark_entities(con, ents, days[len(days) // 2], "TEST")
        assert features.materialize_incremental(con).status == "DONE"
        assert_view_equals_wide(con)
        assert features.materialize(con, days[1]).status == "PROMOTED"
        assert_view_equals_wide(con)

        # the history removed from a middle day (as rebuild-market does), then those days again
        later = days[len(days) // 2 :]
        assert features_store.delete_from(con, later[0]) > 0
        assert_view_equals_wide(con)
        with features.materialize_run(con, later) as prices:
            res = features.materialize_days(con, later, prices=prices)
        assert all(x.status == "PROMOTED" for x in res)
        assert assert_view_equals_wide(con) == n
        # the live table is the latest day of the view
        live = con.execute("SELECT * FROM screener_features ORDER BY security_id").fetchall()
        last = con.execute("SELECT * FROM screener_features_history WHERE as_of_date = ? ORDER BY security_id",
                           [days[-1]]).fetchall()  # fmt: skip
        assert live == last
        # rebuild-market itself (market state rolled back; the replay needs the staged days, not here)
        r = rebuild_market(con, days[-2], note="test")
        assert r["features"] > 0 and r["features_dates"] == days[-2:]
        n = assert_view_equals_wide(con)
        assert n < len(days) * len(live)

        # the one-off migration of a wide table gives the same view
        monkeypatch.undo()
        wide = con.execute("SELECT * FROM wide ORDER BY as_of_date, security_id").fetchall()
        con.execute("DROP VIEW screener_features_history")
        features_store.truncate(con)
        con.execute("ALTER TABLE wide RENAME TO screener_features_history")
        with pytest.raises(Exception, match="migrate-sparse-history"):
            apply_schema(con)
        m = features_store.migrate_legacy(con)
        assert m["status"] == "MIGRATED" and m["rows"] == n and m["event_intervals"] < n, m
        assert features_store.migrate_legacy(con)["status"] == "NOTHING"
        apply_schema(con)
        got = con.execute("SELECT * FROM screener_features_history ORDER BY as_of_date, security_id").fetchall()
        assert len(got) == len(wide)
        assert all(identical(x, y) for ra, rb in zip(got, wide, strict=True) for x, y in zip(ra, rb, strict=True))
        assert features_store.check_invariants(con)["identical_neighbours"] == 0
    finally:
        con.close()


def test_migration_rolls_back_when_the_view_would_differ(tmp_path, monkeypatch):
    con = connect(tmp_path / "m.duckdb")
    apply_schema(con)
    rng = random.Random(3)
    features_store.write_rows(con, [_row(rng, d, s, i // 5) for i, d in enumerate(DAYS) for s in SECS])
    con.execute("CREATE TABLE wide AS SELECT * FROM screener_features_history")
    con.execute("DROP VIEW screener_features_history")
    features_store.truncate(con)
    con.execute("ALTER TABLE wide RENAME TO screener_features_history")
    monkeypatch.setattr(features_store, "EVENT_COLUMNS", EVENT_COLUMNS[1:])  # sales_ttm would be lost
    with pytest.raises(RuntimeError, match="rolled back"):
        features_store.migrate_legacy(con)
    assert features_store.is_legacy(con)
    assert con.execute("SELECT count(*) FROM screener_features_history").fetchone()[0] == len(DAYS) * len(SECS)
