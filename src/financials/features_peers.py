"""Industry and peer columns (G96, G112, G199, G334) for `features.py`: batch H.

Two stages, both batched (never a query per security):
1. `add_columns(con, rows, as_of, as_of_ts, entities)` (the `features.compute_rows` hook): the NSE 4-level
   classification [IC1] of each row's entity, read point in time from `entity_classification_history`
   (interval covering the as-of and visible by the as-of's end). NSE gives no effective date [IC3], so a company is
   classified only from the day its classification was first fetched: earlier days stay NULL, never backdated.
2. `cross_section(rows)` over all rows of one as-of date, recomputed from the stored day by
   `refresh_cross_section(con, as_of)` inside the materialize transaction (like features_gems), so an incremental
   run ranks every row against the same universe as a full run.

Peer groups are the day's materialised companies sharing `nse_industry` or `nse_basic_industry`. One value per
company (its largest-market-cap security), so a second share class never counts twice. Medians need at least
MIN_PEERS company values, else NULL; PE and PB medians use positive values only (a loss-maker has no PE). Premiums
are `x / median - 1` (negative = discount) for a positive own value. Ranks are competition ranks among the
companies of the basic industry with a value (1 = largest market cap, lowest positive PE, highest ROCE, highest
quarterly profit growth); NULL without an own value or classification.

`industry_group_*` is the fallback over the Nifty 500 file's `industry` column (features_gems, 20 sector groups,
Nifty 500 members only). It is a different taxonomy and is never mixed into the NSE columns.
"""

from __future__ import annotations

import statistics
from datetime import date, datetime

from financials.fundamentals import entity_filter

MIN_PEERS = 3  # company values needed for a median

CLASS_COLUMNS = ("nse_macro_sector", "nse_sector", "nse_industry", "nse_basic_industry")
METRICS = {"pe": "pe", "pb": "pb", "roce": "roce", "sales_growth": "sales_growth_yoy"}
POSITIVE_ONLY = frozenset({"pe", "pb"})
LEVELS = {"industry": "nse_industry", "basic_industry": "nse_basic_industry", "industry_group": "industry"}
RANKS = {  # column -> (input, descending: 1 = highest)
    "peer_rank_market_cap": ("market_cap", True),
    "peer_rank_pe": ("pe", False),
    "peer_rank_roce": ("roce", True),
    "peer_rank_profit_growth": ("profit_growth_yoy_quarter_pct", True),
}
MEDIAN_COLUMNS = tuple(f"{lvl}_{m}_median" for lvl in LEVELS for m in METRICS)
PREMIUM_COLUMNS = tuple(f"{m}_premium_to_{lvl}" for lvl in LEVELS for m in ("pe", "pb"))
CROSS_COLUMNS = (*MEDIAN_COLUMNS, *PREMIUM_COLUMNS, "peer_count", *RANKS)
COLUMNS = (*CLASS_COLUMNS, *CROSS_COLUMNS)

# Every column the cross-section reads (refresh_cross_section selects exactly these from the stored day).
CROSS_INPUTS = ("security_id", "entity_id", "nse_industry", "nse_basic_industry", "industry", "market_cap", "pe", "pb",
                "roce", "sales_growth_yoy", "profit_growth_yoy_quarter_pct")  # fmt: skip


def classifications(con, as_of: date, as_of_ts: datetime, entities=None) -> dict[str, tuple]:
    """entity_id -> (macro, sector, industry, basic_industry) in force and visible on `as_of`."""
    only, params = entity_filter("entity_id", entities)
    rows = con.execute(
        "SELECT entity_id, macro, sector, industry, basic_industry FROM entity_classification_history "
        "WHERE source = 'NSE_QUOTE' AND valid_from <= ? AND (valid_to IS NULL OR valid_to > ?) "
        "AND visible_from_ts <= ?" + only,
        [as_of, as_of, as_of_ts, *params],
    ).fetchall()
    return {r[0]: tuple(r[1:]) for r in rows}


def add_columns(con, rows: list[dict], as_of: date, as_of_ts: datetime, entities=None) -> None:
    """The features.compute_rows hook: classification columns, then the day's cross-section, in place."""
    cls = classifications(con, as_of, as_of_ts, entities)
    for row in rows:
        row.update(dict(zip(CLASS_COLUMNS, cls.get(row["entity_id"], (None,) * 4), strict=True)))
    cross_section(rows)


def _f(v) -> float | None:
    return None if v is None else float(v)


def _value(r: dict, col: str) -> float | None:
    v = _f(r.get(col))
    if v is not None and col in POSITIVE_ONLY and v <= 0:
        return None
    return v


def _representatives(rows: list[dict]) -> list[dict]:
    """One row per company: the security with the largest market cap (then security_id)."""
    best: dict[str, dict] = {}
    for r in sorted(rows, key=lambda r: (-(_f(r.get("market_cap")) or -1.0), r["security_id"])):
        best.setdefault(r["entity_id"], r)
    return list(best.values())


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if len(values) >= MIN_PEERS else None


def _premium(own: float | None, median: float | None) -> float | None:
    return None if own is None or own <= 0 or median is None or median <= 0 else own / median - 1


def cross_section(rows: list[dict]) -> None:
    """Medians, premiums, peer count and peer ranks over every row of one as-of date, in place."""
    reps = _representatives(rows)
    groups: dict[str, dict[str, list[dict]]] = {lvl: {} for lvl in LEVELS}
    for r in reps:
        for lvl, col in LEVELS.items():
            if r.get(col) is not None:
                groups[lvl].setdefault(r[col], []).append(r)
    medians: dict[tuple[str, str], dict[str, float | None]] = {}
    for lvl, by_key in groups.items():
        for key, members in by_key.items():
            medians[(lvl, key)] = {
                m: _median([v for x in members if (v := _value(x, col)) is not None]) for m, col in METRICS.items()
            }
    basic = groups["basic_industry"]
    for r in rows:
        for lvl, col in LEVELS.items():
            med = medians.get((lvl, r.get(col))) if r.get(col) is not None else None
            for m in METRICS:
                r[f"{lvl}_{m}_median"] = None if med is None else med[m]
            for m in ("pe", "pb"):
                r[f"{m}_premium_to_{lvl}"] = _premium(_value(r, m), None if med is None else med[m])
        peers = basic.get(r.get("nse_basic_industry")) if r.get("nse_basic_industry") is not None else None
        r["peer_count"] = None if peers is None else len(peers)
        for out, (col, desc) in RANKS.items():
            own = _value(r, col)
            if peers is None or own is None:
                r[out] = None
                continue
            others = [v for x in peers if x["entity_id"] != r["entity_id"] and (v := _value(x, col)) is not None]
            r[out] = 1 + sum(1 for v in others if (v > own if desc else v < own))


_ARROW_TYPES = {"peer_count": "int32", **dict.fromkeys(RANKS, "int32")}


def refresh_cross_section(con, as_of: date) -> None:
    """Recompute CROSS_COLUMNS for every stored row of `as_of` (inside the materialize transaction, after the day's
    rows are written): one read of the history view, one UPDATE of features_daily (CROSS_COLUMNS are DAILY columns,
    tests/test_features_store.py) through Arrow."""
    import pyarrow as pa

    from financials.db import fetch_dicts

    rows = fetch_dicts(con, f"SELECT {', '.join(CROSS_INPUTS)} FROM screener_features_history WHERE as_of_date = ? "
                       "ORDER BY security_id",
                       [as_of])  # fmt: skip
    if not rows:
        return
    cross_section(rows)
    types = {"int32": pa.int32()}
    fields = [pa.field("security_id", pa.string())] + [
        pa.field(c, types[_ARROW_TYPES[c]] if c in _ARROW_TYPES else pa.float64()) for c in CROSS_COLUMNS
    ]
    table = pa.Table.from_pylist([{c: r[c] for c in ("security_id", *CROSS_COLUMNS)} for r in rows],
                                 schema=pa.schema(fields))  # fmt: skip
    con.register("_peers_cross", table)
    try:
        sets = ", ".join(f"{c} = s.{c}" for c in CROSS_COLUMNS)
        con.execute(
            f"UPDATE features_daily h SET {sets} FROM _peers_cross s "  # DAILY columns (features_store)
            "WHERE h.as_of_date = ? AND h.security_id = s.security_id",
            [as_of],
        )
    finally:
        con.unregister("_peers_cross")
