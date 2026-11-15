"""Dirty tracking for incremental materialisation (architecture §11.10).

A (day, security) feature row depends only on that security's / entity's own inputs. The single writers
(promoter.py, admin.py) record in `materialize_dirty`, inside the transaction that changes an input, which entity's
rows may be stale from which as_of_date on; `features.materialize_incremental` recomputes exactly those rows.

Two kinds of hooks:
- explicit, where the writer knows the entity and the visibility (results / annual filings, shareholding, Reg. 30
  events, KPIs, delivery attached late, bars loaded by reprocess, overrides, security merges, rebuild-market) and a
  FULL marker (entity '*') from the date of every market day promoted;
- a market-state diff around every batch / admin operation that can change price-side state, because those writes
  are spread over many rules (verification, CA11-CA13, gap auditor, inactivity, merges): the accepted
  corporate-action factors, the open GAP findings (the series freeze), identifier intervals, the security -> entity
  map and Nifty 500 membership are snapshotted before and compared after; every changed row marks its security's
  entity from the earliest date in the row (an action changes bars before its ex-date only for as_of >= ex_date).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime

from financials.corp_actions import ACCEPTED_STATUSES
from financials.db import insert_rows
from financials.fundamentals import in_list
from financials.ids import stable_id
from financials.scope import MIN_TRADE_DATE
from financials.timeutil import utc_now, utc_to_ist_date

FULL = "*"  # entity_id of a marker that covers every entity


def mark(con, from_dates: Mapping[str, date], reason: str, source_id: str = "") -> int:
    """One marker per entity (from its date). Idempotent: the id is deterministic, a replay inserts nothing."""
    now = utc_now()
    rows = [
        {"dirty_id": stable_id("dirty", ent, d, reason, source_id), "entity_id": ent, "from_date": d,
         "reason": reason, "source_id": source_id or "", "created_at": now}
        for ent, d in sorted(from_dates.items()) if ent is not None and d is not None
    ]  # fmt: skip
    insert_rows(con, "materialize_dirty", rows, or_ignore=True)
    return len(rows)


def mark_entities(con, entity_ids: Iterable[str], from_date: date, reason: str, source_id: str = "") -> int:
    return mark(con, dict.fromkeys(entity_ids, from_date), reason, source_id)


def mark_all(con, from_date: date, reason: str, source_id: str = "") -> int:
    return mark(con, {FULL: from_date}, reason, source_id)


def mark_visible(con, entity_id: str, visible_from_ts: datetime, reason: str, source_id: str = "") -> int:
    """A fact visible at `visible_from_ts` (UTC) is first read by the as_of_date of its IST calendar date."""
    return mark(con, {entity_id: utc_to_ist_date(visible_from_ts)}, reason, source_id)


def mark_securities(con, from_dates: Mapping[str, date], reason: str, source_id: str = "") -> int:
    """Securities -> their entities (one query), earliest date per entity."""
    if not from_dates:
        return 0
    out: dict[str, date] = {}
    sql, params = in_list("security_id", from_dates)
    for sec, ent in con.execute("SELECT security_id, entity_id FROM securities WHERE " + sql, params).fetchall():
        out[ent] = min(out.get(ent, date.max), from_dates[sec])
    return mark(con, out, reason, source_id)


# name -> (query, indexes of the date columns). Column 0 is the security_id.
_STATE = {
    "factors": (
        "SELECT security_id, ex_date, action_id, price_factor, coalesce(eps_factor, 1) FROM corp_actions "
        "WHERE price_factor IS NOT NULL AND status IN (" + ", ".join(f"'{s}'" for s in sorted(ACCEPTED_STATUSES)) + ")",
        (1,),
    ),
    "gaps": (
        "SELECT security_id, CAST(json_extract_string(details, '$.trade_date') AS DATE) FROM quarantine_queue "
        "WHERE stage = 'GAP' AND resolved_at IS NULL AND security_id IS NOT NULL",
        (1,),
    ),
    "identifiers": (
        "SELECT security_id, exchange, symbol, series, valid_from, valid_to FROM security_identifier_history",
        (4, 5),
    ),
    "nifty": (
        "SELECT security_id, valid_from, valid_to FROM index_constituents_history WHERE index_name = 'NIFTY 500'",
        (1, 2),
    ),
}


def market_state(con) -> dict[str, set[tuple]]:
    """Snapshot of the price-side inputs of feature rows (small tables; a few queries per batch)."""
    out = {name: set(con.execute(sql).fetchall()) for name, (sql, _) in _STATE.items()}
    out["securities"] = set(con.execute("SELECT security_id, entity_id FROM securities").fetchall())
    return out


def mark_market_changes(con, before: dict[str, set[tuple]], reason: str, source_id: str = "") -> int:
    """Diff `before` against the current state and mark each changed row's entity from the row's earliest date."""
    after = market_state(con)
    secs: dict[str, date] = {}
    for name, (_, date_cols) in _STATE.items():
        for row in before[name] ^ after[name]:
            dates = [row[i] for i in date_cols if row[i] is not None]
            d = min(dates) if dates else MIN_TRADE_DATE
            secs[row[0]] = min(secs.get(row[0], date.max), d)
    n = mark_securities(con, secs, reason, source_id)
    # A security re-pointed to another entity (merge): both entities change on every day. A new security has no
    # earlier rows (its first bar is the promoted day, covered by that day's FULL marker).
    old = dict(before["securities"])
    moved = {e for sec, ent in after["securities"] ^ before["securities"] if sec in old for e in (ent, old[sec])}
    return n + mark_entities(con, moved, MIN_TRADE_DATE, reason, source_id)
