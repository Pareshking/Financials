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
  corporate-action factors, MERGER / DEMERGER rows (restatement flag, X109), the open GAP findings (the series
  freeze), identifier intervals, the security -> entity map and Nifty 500 membership are snapshotted before and
  compared after; every changed row marks its security's entity from the earliest date in the row (an action
  changes bars before its ex-date only for as_of >= ex_date).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime, timedelta

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
    # X109: a MERGER / DEMERGER (any status) sets restatement_suspected from its ex-date; a status change can clear it.
    # The related entity (other party) is not marked here: rows of that entity rebuild on their next full run.
    "structural": (
        "SELECT security_id, ex_date, action_id, action_type, status FROM corp_actions "
        "WHERE action_type IN ('MERGER', 'DEMERGER')",
        (1,),
    ),
    # Batch I (features_more): an announced action's listing makes `days_to_next_ex_date` visible from its fetch /
    # broadcast (UTC date: never later than the IST date that first reads it); a retirement clears it.
    "announced": (
        "SELECT a.security_id, CAST(coalesce(f.broadcast_ts, f.fetched_at) AS DATE), a.ex_date, a.action_id, "
        "a.status IN ('SUPERSEDED', 'REJECTED') FROM corp_actions a JOIN filings f ON f.filing_id = a.source_filing_id",
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


# Interval states (the last two columns are [valid_from, valid_to), NULL = open): a feature row of as-of D reads
# them only as "does the row cover D" (the universe, symbol / series, Issue Size and industry lookups at a date,
# Nifty 500 membership at D and its inclusion / exclusion dates, which are interval ends that coverage moves). So a
# change marks its security from the first date whose coverage differs, not from the interval's start: closing an
# identifier interval on 2026-11-13 (a symbol change) used to mark the entity from its first listing day
# (2024-10-01) and walk every materialised day.
_INTERVALS = frozenset({"identifiers", "nifty"})
_OPEN = date.max


def _interval_changes(before: set[tuple], after: set[tuple]) -> dict[str, date]:
    """Security -> the earliest date covered differently by `before` and `after` (rows of one interval state, key =
    the columns before the interval). A change that keeps every date's coverage (an interval split in two at b, or
    two adjacent ones merged) marks from the first moved end (b), which a reader of interval ends could see."""
    changed = before ^ after
    keys = {row[:-2] for row in changed}
    old: dict[tuple, list[tuple[date, date]]] = {k: [] for k in keys}
    new: dict[tuple, list[tuple[date, date]]] = {k: [] for k in keys}
    for rows, out in ((before, old), (after, new)):
        for row in rows:
            if row[:-2] in out and row[-2] is not None:
                out[row[:-2]].append((row[-2], row[-1] or _OPEN))
    marks: dict[str, date] = {}
    for k in keys:
        ends = sorted({d for iv in old[k] + new[k] for d in iv if d != _OPEN})
        first = next((d for d in ends if any(f <= d < t for f, t in old[k]) != any(f <= d < t for f, t in new[k])),
                     None)  # fmt: skip
        if first is None:  # same coverage on every date: the earliest end present in only one of the two
            moved = {d for iv in old[k] for d in iv} ^ {d for iv in new[k] for d in iv}
            first = min(moved - {_OPEN}, default=None)
        if first is None:
            starts = [row[-2] for row in changed if row[:-2] == k and row[-2] is not None]
            first = min(starts, default=MIN_TRADE_DATE)
        marks[k[0]] = min(marks.get(k[0], date.max), first)
    return marks


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
        if name in _INTERVALS:
            changed = _interval_changes(before[name], after[name])
        else:
            changed = {}
            for row in before[name] ^ after[name]:
                dates = [row[i] for i in date_cols if row[i] is not None]
                d = min(dates) if dates else MIN_TRADE_DATE
                changed[row[0]] = min(changed.get(row[0], date.max), d)
        for sec, d in changed.items():
            secs[sec] = min(secs.get(sec, date.max), d)
    n = mark_securities(con, secs, reason, source_id)
    # A security re-pointed to another entity (merge): both entities change on every day. A new security has no
    # earlier rows (its first bar is the promoted day, covered by that day's FULL marker).
    old = dict(before["securities"])
    moved = {e for sec, ent in after["securities"] ^ before["securities"] if sec in old for e in (ent, old[sec])}
    return n + mark_entities(con, moved, MIN_TRADE_DATE, reason, source_id)


# X325 (rule SHOW_AND_FLAG): open findings carrying an entity flag that entity's rows whose window holds the
# finding's period end (features.dq_columns). Findings are opened and resolved by many writers (promotion, audits,
# admin resolutions), so instead of a hook in each, `materialize --incremental` diffs the open set against the set
# the stored rows reflect (features_dq_findings) and marks every changed finding's entity from its period end: a
# row can carry the flag only on an as-of date on or after that end.
FINDING_PERIOD_END_SQL = (
    "coalesce(TRY_CAST(json_extract_string(q.details, '$.ytd_period[1]') AS DATE), "
    "TRY_CAST(json_extract_string(q.details, '$.period[1]') AS DATE), "
    "TRY_CAST(json_extract_string(q.details, '$.as_of') AS DATE), fm.period_end)"
)
FINDING_FILING_JOIN = (
    "LEFT JOIN (SELECT filing_id, any_value(scope) AS scope, max(period_end) AS period_end, "
    "min(visible_from_ts) AS vis FROM filing_meta WHERE filing_id IN (SELECT filing_id FROM quarantine_queue "
    "WHERE resolved_at IS NULL) GROUP BY filing_id) fm USING (filing_id)"
)
OPEN_ENTITY_FINDING = "q.resolved_at IS NULL AND q.entity_id IS NOT NULL AND q.stage <> 'GAP'"


def _open_findings(con) -> set[tuple[str, str, date | None]]:
    return set(con.execute(
        f"SELECT q.quarantine_id, q.entity_id, {FINDING_PERIOD_END_SQL} FROM quarantine_queue q "
        f"{FINDING_FILING_JOIN} WHERE {OPEN_ENTITY_FINDING}"
    ).fetchall())  # fmt: skip


def mark_finding_changes(con) -> int:
    """Mark the entity of every open finding the stored rows do not reflect, and of every reflected one that is no
    longer open, from the finding's period end (MIN_TRADE_DATE when it names none or an earlier one)."""
    stored = set(con.execute("SELECT quarantine_id, entity_id, period_end FROM features_dq_findings").fetchall())
    changed = stored ^ _open_findings(con)
    # features.open_findings flags a row only from the IST date its filing becomes visible, and only when the period
    # end is known (features.dq_columns skips a finding without one): the first as-of a change can reach is the
    # later of the two. Marking from MIN_TRADE_DATE sent `--incremental` over every materialised day.
    vis: dict[str, datetime] = {}
    if changed:
        sql, params = in_list("q.quarantine_id", {r[0] for r in changed})
        vis = {q: ts for q, ts in con.execute(
            "SELECT q.quarantine_id, min(fm.visible_from_ts) FROM quarantine_queue q JOIN filing_meta fm "
            "USING (filing_id) WHERE " + sql + " GROUP BY 1", params).fetchall() if ts is not None}  # fmt: skip
    out: dict[str, date] = {}
    for qid, ent, end in changed:
        if end is None:  # flags no row, now or before
            continue
        # (one day earlier: a timestamp at exactly IST midnight is visible to the as-of of the day before)
        d = max(end, MIN_TRADE_DATE, utc_to_ist_date(vis[qid]) - timedelta(days=1) if qid in vis else end)
        out[ent] = min(out.get(ent, date.max), d)
    return mark(con, out, "DQ_FINDINGS")


def store_finding_state(con) -> None:
    """The open findings the materialised rows now reflect (after a successful run over every stale row)."""
    rows = sorted(_open_findings(con), key=lambda r: r[0])
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute("DELETE FROM features_dq_findings")
        insert_rows(con, "features_dq_findings",
                    [{"quarantine_id": q, "entity_id": e, "period_end": d} for q, e, d in rows])  # fmt: skip
    except BaseException:
        con.execute("ROLLBACK")
        raise
    con.execute("COMMIT")
