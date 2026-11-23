"""Audited write operations run by the single writer (same process role as `promote`).

- `backfill_index`: backward point-in-time index membership before the first snapshot.
- `list_quarantine` / `resolve_quarantine`: the D-6 resolution path. Quarantine rows are never
  deleted; every resolution sets `resolved_at`, `resolution`, `resolution_note`, and any change it
  makes (override, corporate action, security merge) is recorded in `company_overrides` and applied
  in the same transaction.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from typing import Any

from financials import dirty
from financials.corp_actions import CorpAction, audit_day
from financials.db import fetch_dicts, insert_rows, version_key
from financials.ids import stable_id
from financials.index_changes import IndexEvent, reconstruct_backward
from financials.level_slip import level_slip, rescaled, usual_level
from financials.promoter import (
    RESULTS_CATEGORY_SQL,
    _actions,
    _prev_closes,
    _quarantine,
    index_members,
    record_corp_action,
    verify_pending_actions,
)
from financials.scope import MIN_TRADE_DATE
from financials.timeutil import utc_now


class AdminError(ValueError):
    pass


def _transaction(con, fn, *args, **kwargs):
    """Run `fn` atomically. Every admin operation can change price-side feature inputs (a manual action, a resolved
    gap, a merge, index membership), so the market state is diffed around it into materialize_dirty (dirty.py)."""
    con.execute("BEGIN TRANSACTION")
    try:
        before = dirty.market_state(con)
        out = fn(con, *args, **kwargs)
        dirty.mark_market_changes(con, before, "ADMIN" + fn.__name__.upper(), str(args[0]) if args else "")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    con.execute("COMMIT")
    return out


# ── index backfill ─────────────────────────────────────────────────────────


def resolve_symbol(con, symbol: str, on_date: date, exchange: str = "NSE") -> str | None:
    rows = con.execute(
        "SELECT DISTINCT security_id FROM security_identifier_history WHERE exchange = ? AND symbol = ? "
        "AND valid_from <= ? AND (valid_to IS NULL OR valid_to > ?)",
        [exchange, symbol, on_date, on_date],
    ).fetchall()
    return rows[0][0] if len(rows) == 1 else None


def backfill_index(
    con, index_name: str, events: Iterable[IndexEvent], *, start: date = MIN_TRADE_DATE, expected_count: int = 500
) -> dict[str, Any]:
    """Rebuild MANUAL_BACKFILL rows for [start, first snapshot). Atomic; aborts on any invariant error."""

    def run(con):
        first = con.execute(
            "SELECT min(valid_from) FROM index_constituents_history WHERE index_name = ? AND source = 'SNAPSHOT'",
            [index_name],
        ).fetchone()[0]
        if first is None:
            raise AdminError(f"no snapshot for {index_name}: promote a constituents snapshot first")
        # Members outside the equity universe (REITs, series RR, in the Nifty 500 since 2026-09-30 [IDX8]) count
        # towards the index size but have no security in this database: virtual keys, never written as rows.
        outside = {sym for (sym,) in con.execute(
            "SELECT DISTINCT symbol FROM raw_index_snapshot WHERE index_name = ? AND isin LIKE 'IN%' "
            "AND series NOT IN ('EQ', 'BE', 'BZ') AND snapshot_date = (SELECT max(snapshot_date) FROM "
            "raw_index_snapshot WHERE index_name = ?)", [index_name, index_name]).fetchall()}  # fmt: skip
        current = [*index_members(con, index_name, first), *(f"OUTSIDE:{s}" for s in sorted(outside))]
        intervals, steps = reconstruct_backward(
            current, first, events, start,
            lambda s, d: f"OUTSIDE:{s}" if s in outside else resolve_symbol(con, s, d), expected_count=expected_count,
        )  # fmt: skip
        intervals = [iv for iv in intervals if not str(iv.key).startswith("OUTSIDE:")]
        con.execute(
            "DELETE FROM index_constituents_history WHERE index_name = ? AND source = 'MANUAL_BACKFILL'", [index_name]
        )
        rows = []
        for iv in intervals:
            to = first if iv.valid_to is None else min(iv.valid_to, first)
            if iv.valid_from < to:
                rows.append({"index_name": index_name, "security_id": iv.key, "valid_from": iv.valid_from,
                             "valid_to": to, "source": "MANUAL_BACKFILL"})  # fmt: skip
        insert_rows(con, "index_constituents_history", rows)
        return {"first_snapshot": first, "rows": len(rows), "steps": steps}

    return _transaction(con, run)


# ── rebuild-market [P0-1] ──────────────────────────────────────────────────

AUTO_DECIDED = ("VERIFIED", "UNOBSERVABLE", "QUARANTINED")  # verification outcomes recomputed on replay


def rebuild_market(con, from_date: date, *, note: str = "rebuild-market") -> dict[str, Any]:
    """Roll market-derived state back to `from_date` so the staged market days from that date replay in order.

    Raw tables, vault rows and filings are append-only and untouched. Removed: bars, bhavcopy/inferred calendar
    rows, identifier intervals opened on/after the date (intervals closed on/after it reopen), feature history.
    Reset: automatically decided corporate actions with ex-date on/after it go back to PENDING (manual decisions
    VERIFIED_MANUAL / REJECTED / SUPERSEDED stand). Open GAP / IDENTIFIER / CALENDAR findings on/after it are
    marked SUPERSEDED_BY_REBUILD; a replay that finds the same problem reopens the same row. Market-day entries
    of `promotion_log` on/after the date are removed so `promote` replays them. Audited in `admin_log`."""

    def run(con):
        from financials import features_store
        from financials.promoter import REBUILD_SUPERSEDED

        now = utc_now()
        counts: dict[str, int] = {}

        def n(key: str, sql: str, params: list) -> None:
            counts[key] = len(con.execute(sql + " RETURNING 1", params).fetchall())

        features_dates = [r[0] for r in con.execute(
            "SELECT DISTINCT as_of_date FROM features_daily WHERE as_of_date >= ? ORDER BY 1", [from_date]
        ).fetchall()]  # fmt: skip
        n("ohlcv", "DELETE FROM ohlcv WHERE trade_date >= ?", [from_date])
        n("calendar", "DELETE FROM trading_calendar WHERE cal_date >= ? "
          "AND source IN ('BHAVCOPY', 'INFERRED_PREV_CLOSE')", [from_date])  # fmt: skip
        n("intervals_removed", "DELETE FROM security_identifier_history WHERE valid_from >= ?", [from_date])
        n(
            "intervals_reopened",
            "UPDATE security_identifier_history SET valid_to = NULL WHERE valid_to >= ?",
            [from_date],
        )
        n("corp_actions_reset", "UPDATE corp_actions SET status = 'PENDING', price_factor = NULL, eps_factor = NULL, "
          "observed_gap = NULL, decided_at = NULL WHERE ex_date >= ? AND status IN ('VERIFIED', 'UNOBSERVABLE') "
          "OR (ex_date >= ? AND status = 'QUARANTINED' AND action_type <> 'UNKNOWN')",
          [from_date, from_date])  # fmt: skip
        n("quarantines_superseded",
          "UPDATE quarantine_queue SET resolved_at = ?, resolution = ?, resolution_note = ? "
          "WHERE (resolved_at IS NULL OR resolution = 'FIXED_BY_RULE') AND stage IN ('GAP', 'IDENTIFIER', 'CALENDAR') "
          "AND CAST(json_extract_string(details, '$.trade_date') AS DATE) >= ?",
          [now, REBUILD_SUPERSEDED, f"rebuild-market --from {from_date}: {note}", from_date])  # fmt: skip
        counts["features"] = features_store.delete_from(con, from_date)  # daily rows and intervals (§4.1)
        con.execute("DELETE FROM features_meta WHERE as_of_date >= ?", [from_date])
        con.execute("DELETE FROM market_breadth WHERE as_of_date >= ?", [from_date])
        dirty.mark_all(con, from_date, "REBUILD_MARKET", str(from_date))
        con.execute("DELETE FROM screener_features")
        con.execute("INSERT INTO screener_features BY NAME SELECT * FROM screener_features_history WHERE as_of_date = "
                    "(SELECT max(as_of_date) FROM features_daily)")  # fmt: skip
        logged = [r[0] for r in con.execute("SELECT stage_path FROM promotion_log WHERE job = 'market_day'").fetchall()]
        replay = [p for p in logged if p.split("/", 1)[-1][:8] >= f"{from_date:%Y%m%d}"]  # run id = YYYYMMDD-...
        if replay:
            con.execute("DELETE FROM promotion_log WHERE stage_path IN (SELECT unnest(?))", [replay])
        counts["market_days_to_replay"] = len(replay)
        result = {"from": from_date, **counts, "features_dates": features_dates}
        con.execute(
            "INSERT INTO admin_log VALUES (?, 'REBUILD_MARKET', ?, ?, ?, ?)",
            [stable_id("adm", "rebuild", from_date, now), json.dumps({"from": str(from_date)}),
             json.dumps(result, default=str), note, now],
        )  # fmt: skip
        return result

    return _transaction(con, run)


# ── reprocess [P1-9] ───────────────────────────────────────────────────────

RETRYABLE = ("UNKNOWN_ISIN", "UNKNOWN_SYMBOL", "AMBIGUOUS_ISIN", "AMBIGUOUS_SYMBOL", "AMBIGUOUS_SECURITY",
             "STALE_ISIN_OTHER_ISSUER", "NO_VISIBILITY", "UNPARSED_PURPOSE")  # fmt: skip


def reprocess(con, stage_root) -> dict[str, Any]:
    """Promote again every batch with an open, retryable finding (identity not yet known, visibility not yet
    derivable, a filing override recorded since). Each open finding whose batch is still staged is marked
    REPROCESSING first; promoting the batch again reopens it if the problem is still there (same deterministic id),
    otherwise it is closed as REPROCESSED. A finding whose batch is no longer staged is left open and listed under
    `batch_not_staged` (restage it first) [X141]. The named market rules (CA12, CA13, X140) then re-run over every
    open GAP finding. MISSING_FIN_INSTRM_ID bars are loaded when their ISIN belongs to exactly one security that day
    with the same symbol and series."""
    from pathlib import Path

    from financials.promoter import REPROCESSING, promote

    stage_root = Path(stage_root)
    now = utc_now()
    con.execute(
        "UPDATE quarantine_queue SET resolved_at = NULL, resolution = NULL WHERE resolution = ?", [REPROCESSING]
    )
    open_q = fetch_dicts(
        con,
        "SELECT quarantine_id, filing_id FROM quarantine_queue WHERE resolved_at IS NULL AND filing_id IS NOT NULL "
        "AND reason_code IN (SELECT unnest(?))",
        [list(RETRYABLE)],
    )
    filing_ids = sorted({q["filing_id"] for q in open_q})
    stages: list[str] = []
    staged: set[str] = set()
    if filing_ids:
        logged = [r[0] for r in con.execute("SELECT stage_path FROM promotion_log").fetchall()]
        files = [
            (stage_root / p / "filings.parquet").as_posix()
            for p in logged
            if (stage_root / p / "filings.parquet").exists()
        ]
        if files:
            rows = con.execute(
                "SELECT DISTINCT filename, filing_id FROM read_parquet(?, filename = true) "
                "WHERE filing_id IN (SELECT unnest(?))",
                [files, filing_ids],
            ).fetchall()
            stages = sorted({Path(f).parent.relative_to(stage_root).as_posix() for f, _ in rows})
            staged = {fid for _, fid in rows}
    # Only a finding whose batch is promoted again can be re-checked. A finding whose staged batch is gone (staging
    # pruned after promotion) stays open: closing it as REPROCESSED would claim a re-check that never ran [X141].
    not_found = sorted(q["quarantine_id"] for q in open_q if q["filing_id"] not in staged)
    ids = [q["quarantine_id"] for q in open_q if q["filing_id"] in staged]
    if ids:
        con.execute(
            "UPDATE quarantine_queue SET resolved_at = ?, resolution = ? WHERE quarantine_id IN (SELECT unnest(?))",
            [now, REPROCESSING, ids],
        )
    results = []
    for rel in stages:
        con.execute("DELETE FROM promotion_log WHERE stage_path = ?", [rel])
        r = promote(con, stage_root / rel)
        con.execute(
            "INSERT OR REPLACE INTO promotion_log VALUES (?, ?, ?, ?, ?)", [rel, r.job, r.status, r.message, utc_now()]
        )
        results.append({"stage": rel, "status": r.status, "message": r.message})
    fixed = con.execute(
        "UPDATE quarantine_queue SET resolution = 'REPROCESSED', resolution_note = 'cleared on reprocess' "
        "WHERE resolution = ? RETURNING quarantine_id",
        [REPROCESSING],
    ).fetchall()
    loaded = _load_missing_fin_instrm_id_bars(con)
    rules = _transaction(con, _market_rules)
    out = {"batches": results, "cleared": [r[0] for r in fixed], "bars_loaded": loaded,
           "batch_not_staged": not_found, "market_rules": rules}  # fmt: skip
    con.execute("INSERT INTO admin_log VALUES (?, 'REPROCESS', '{}', ?, NULL, ?)",
                [stable_id("adm", "reprocess", now), json.dumps(out, default=str), now])  # fmt: skip
    return out


def _market_rules(con) -> dict[str, int]:
    """The named market-side rules that close open GAP findings (CA12, CA13, X140), re-run over every open finding:
    the same statements market-day promotion runs, so a rule added later also reaches older findings."""
    from financials.promoter import resolve_isin_changes, resolve_market_moves, resolve_rights_entitlement_gaps

    return {"CA12": resolve_market_moves(con), "CA13": resolve_isin_changes(con, "NSE"),
            "X140": resolve_rights_entitlement_gaps(con)}  # fmt: skip


def _load_missing_fin_instrm_id_bars(con) -> int:
    rows = fetch_dicts(
        con,
        "SELECT quarantine_id, filing_id, details FROM quarantine_queue WHERE resolved_at IS NULL "
        "AND reason_code = 'MISSING_FIN_INSTRM_ID'",
    )
    loaded = 0
    for q in rows:
        d = json.loads(q["details"])
        day = date.fromisoformat(str(d["trade_date"])[:10])
        raw = fetch_dicts(
            con,
            "SELECT * FROM raw_cm_bhavcopy WHERE filing_id = ? AND symbol = ? AND isin = ? AND trade_date = ?",
            [q["filing_id"], d["symbol"], d["isin"], day],
        )
        if len(raw) != 1:
            continue
        r = raw[0]
        secs = con.execute(
            "SELECT DISTINCT security_id FROM security_identifier_history WHERE isin = ? AND symbol = ? AND series = ? "
            "AND valid_from <= ? AND (valid_to IS NULL OR valid_to > ?)",
            [r["isin"], r["symbol"], r["series"], day, day],
        ).fetchall()
        if len(secs) != 1:
            continue
        sec = secs[0][0]
        insert_rows(con, "ohlcv", [{
            "security_id": sec, "exchange": r["exchange"], "series": r["series"], "trade_date": day, "open": r["open"],
            "high": r["high"], "low": r["low"], "close": r["close"], "volume": r["volume"],
            "turnover_inr": r["turnover_inr"], "deliv_qty": None, "price_filing_id": r["filing_id"],
            "delivery_filing_id": None,
        }], or_ignore=True)  # fmt: skip
        dirty.mark_securities(con, {sec: day}, "BAR_LOADED", q["quarantine_id"])  # bar and its gap findings
        prev = _prev_closes(con, r["exchange"], day).get(sec)
        for f in audit_day(
            sec, day, r["open"], prev, _actions(con, "security_id = ? AND ex_date = ?", [sec, day]), False
        ):
            _quarantine(con, stage="GAP", reason_code=f.reason_code, security_id=sec,
                        details={"trade_date": day, "gap": f.gap, "prev_close": prev, "open": r["open"]})  # fmt: skip
        con.execute(
            "UPDATE quarantine_queue SET resolved_at = ?, resolution = 'REPROCESSED', resolution_note = ? "
            "WHERE quarantine_id = ?",
            [utc_now(), f"bar loaded by ISIN for {sec}", q["quarantine_id"]],
        )
        loaded += 1
    return loaded


# ── quarantine ─────────────────────────────────────────────────────────────

RESOLUTIONS = {"ACCEPT": "ACCEPTED", "REJECT": "REJECTED", "OVERRIDE": "OVERRIDDEN", "CORP_ACTION": "OVERRIDDEN",
               "MERGE_SECURITIES": "OVERRIDDEN", "CORRECT": "CORRECTED"}  # fmt: skip
ATTRIBUTION_TAGS = ("pat_owners", "pat_nci")


def list_quarantine(
    con,
    *,
    stage: str | None = None,
    reason_code: str | None = None,
    entity_id: str | None = None,
    security_id: str | None = None,
    include_resolved: bool = False,
    limit: int = 200,
) -> list[dict[str, Any]]:
    where, params = ["1 = 1"], []
    for col, val in (("stage", stage), ("reason_code", reason_code), ("entity_id", entity_id),
                     ("security_id", security_id)):  # fmt: skip
        if val is not None:
            where.append(f"{col} = ?")
            params.append(val)
    if not include_resolved:
        where.append("resolved_at IS NULL")
    return fetch_dicts(
        con,
        f"SELECT * FROM quarantine_queue WHERE {' AND '.join(where)} ORDER BY created_at, quarantine_id "
        f"LIMIT {int(limit)}",
        params,
    )


def inspect_quarantine(con, quarantine_id: str) -> dict[str, Any]:
    """One finding with its context (bars around the date, corporate actions, raw rows, filing) and the exact
    commands that resolve it [P2-12]. Read-only."""
    rows = fetch_dicts(con, "SELECT * FROM quarantine_queue WHERE quarantine_id = ?", [quarantine_id])
    if not rows:
        raise AdminError(f"unknown quarantine id {quarantine_id}")
    q = rows[0]
    d = json.loads(q["details"])
    ctx: dict[str, Any] = {}
    sec, day = q["security_id"], d.get("trade_date") or d.get("ex_date")
    if sec:
        ctx["identifiers"] = fetch_dicts(
            con, "SELECT symbol, series, isin, fin_instrm_id, valid_from, valid_to FROM security_identifier_history "
            "WHERE security_id = ? ORDER BY valid_from", [sec])  # fmt: skip
    if sec and day:
        ctx["bars"] = fetch_dicts(
            con, "SELECT trade_date, open, close, volume FROM ohlcv WHERE security_id = ? AND trade_date BETWEEN "
            "CAST(? AS DATE) - INTERVAL 10 DAY AND CAST(? AS DATE) + INTERVAL 10 DAY ORDER BY 1",
            [sec, day, day])  # fmt: skip
        ctx["corp_actions"] = fetch_dicts(
            con, "SELECT action_id, action_type, ratio_num, ratio_den, status, price_factor, observed_gap "
            "FROM corp_actions WHERE security_id = ? AND ex_date = CAST(? AS DATE)", [sec, day])  # fmt: skip
    if q["filing_id"]:
        ctx["filing"] = (fetch_dicts(con, "SELECT category, source_url, broadcast_ts, broadcast_ts_source FROM filings "
                                     "WHERE filing_id = ?", [q["filing_id"]]) or [None])[0]  # fmt: skip
    if q["reason_code"] in ("MISSING_FIN_INSTRM_ID", "ISIN_COLLISION") and day:
        ctx["raw_rows"] = fetch_dicts(
            con, "SELECT symbol, series, isin, fin_instrm_id, open, close FROM raw_cm_bhavcopy WHERE trade_date = ? "
            "AND (isin = ? OR symbol = ?)", [day, d.get("isin"), d.get("symbol")])  # fmt: skip
    base = f"python -m financials quarantine resolve --id {quarantine_id}"
    suggest = {
        "UNEXPLAINED_GAP": [f"{base} --action CORP_ACTION --note '<source>' --payload-json "
                            "'{\"action_type\": \"BONUS\", \"ratio_num\": 1, \"ratio_den\": 1}'",
                            f"{base} --action ACCEPT --note '<why the gap is genuine>'"],
        "ISIN_CHANGE_WITHOUT_ACTION": [f"{base} --action CORP_ACTION --note '<source>' --payload-json "
                                       "'{\"action_type\": \"SPLIT\", \"ratio_num\": 2, \"ratio_den\": 10}'"],
        "ISIN_COLLISION": [f"{base} --action MERGE_SECURITIES --note '<evidence>'"],
        "UNPARSED_PURPOSE": [f"{base} --action REJECT --note '<not a price action>'",
                             f"{base} --action ACCEPT --note '<source>' --payload-json "
                             "'{\"action_type\": \"DIVIDEND\", \"cash_per_share\": \"0.50\"}'",
                             "resolve the day's GAP finding with --action CORP_ACTION (supersedes this record)"],
        "VERIFY_FAILED": [f"{base} --action REJECT --note '<wrong record>'",
                          f"{base} --action ACCEPT --note '<evidence for the ratio>' --payload-json "
                          "'{\"accept_recorded_factor\": true}'",
                          "resolve the day's GAP finding with --action CORP_ACTION (supersedes this record)"],
        "NO_VISIBILITY": [f"{base} --action OVERRIDE --note '<source>' --payload-json "
                          "'{\"field\": \"broadcast_ts\", \"value\": \"YYYY-MM-DDTHH:MM:SS (UTC)\"}'",
                          "python -m financials quarantine reprocess  (after the calendar covers the date)"],
        "MISSING_SESSION": ["fetch the missing day(s), then python -m financials rebuild-market --from <date>"],
    }  # fmt: skip
    for r in FILING_OVERRIDE_FIELDS["security_id"]:
        suggest[r] = [f"{base} --action OVERRIDE --note '<evidence>' --payload-json "
                      "'{\"field\": \"security_id\", \"value\": \"<sec_...>\"}'",
                      "python -m financials quarantine reprocess  (once the security is known)"]  # fmt: skip
    for r in CA_IDENTITY_REASONS if q["stage"] == "CORP_ACTION" else ():
        suggest[r] = [f"{base} --action ACCEPT --note '<evidence>' --payload-json '{{\"security_id\": \"<sec_...>\"}}'",
                      f"{base} --action ACCEPT --note '<no action to record>'"]  # fmt: skip
    suggest.setdefault("MISSING_FIN_INSTRM_ID", ["python -m financials quarantine reprocess"])
    fallback = [f"{base} --action ACCEPT|REJECT --note '<why>'"]
    return {"quarantine": {**q, "details": d}, "context": ctx, "resolve_with": suggest.get(q["reason_code"], fallback)}


def _override(con, entity_id: str | None, field: str, value: Any, valid_from: date, reason: str) -> None:
    if entity_id is None:
        raise AdminError("this resolution needs an entity")
    body = value if isinstance(value, str) else json.dumps(value, default=str, sort_keys=True)
    insert_rows(con, "company_overrides", [{
        "override_id": stable_id("ovr", entity_id, field, body, valid_from), "entity_id": entity_id, "field": field,
        "value": body, "valid_from": valid_from, "valid_to": None, "reason": reason, "created_at": utc_now(),
    }], or_ignore=True)  # fmt: skip


def resolve_quarantine(
    con, quarantine_id: str, *, action: str, note: str, payload: dict | None = None, stage_root=None
) -> dict:
    """Resolve one finding (audited). A filing-level OVERRIDE is applied at once when `stage_root` is given: the
    filing's batch is promoted again with the override (the finding reopens if that still fails)."""
    if action not in RESOLUTIONS:
        raise AdminError(f"action must be one of {sorted(RESOLUTIONS)}")
    if not note.strip():
        raise AdminError("a resolution note is required")
    result = _transaction(con, _resolve, quarantine_id, action, note.strip(), payload or {})
    if result.get("repromote") and stage_root is not None:
        result["repromoted"] = _repromote_filing(con, stage_root, result["filing_id"], quarantine_id)
    return result


def _repromote_filing(con, stage_root, filing_id: str, qid: str) -> dict | None:
    from pathlib import Path

    from financials.promoter import REPROCESSING, promote

    stage_root = Path(stage_root)
    logged = [r[0] for r in con.execute("SELECT stage_path FROM promotion_log").fetchall()]
    files = [
        (stage_root / p / "filings.parquet").as_posix() for p in logged if (stage_root / p / "filings.parquet").exists()
    ]
    if not files:
        return None
    hit = con.execute("SELECT DISTINCT filename FROM read_parquet(?, filename = true) WHERE filing_id = ?",
                      [files, filing_id]).fetchall()  # fmt: skip
    if not hit:
        return None
    rel = Path(hit[0][0]).parent.relative_to(stage_root).as_posix()
    con.execute("UPDATE quarantine_queue SET resolution = ? WHERE quarantine_id = ?", [REPROCESSING, qid])
    con.execute("DELETE FROM promotion_log WHERE stage_path = ?", [rel])
    r = promote(con, stage_root / rel)
    con.execute(
        "INSERT OR REPLACE INTO promotion_log VALUES (?, ?, ?, ?, ?)", [rel, r.job, r.status, r.message, utc_now()]
    )
    con.execute("UPDATE quarantine_queue SET resolution = 'OVERRIDDEN' WHERE quarantine_id = ? AND resolution = ?",
                [qid, REPROCESSING])  # fmt: skip
    return {"stage": rel, "status": r.status}


def _resolve(con, qid: str, action: str, note: str, payload: dict) -> dict:
    rows = fetch_dicts(con, "SELECT * FROM quarantine_queue WHERE quarantine_id = ?", [qid])
    if not rows:
        raise AdminError(f"unknown quarantine id {qid}")
    q = rows[0]
    if q["resolved_at"] is not None:
        raise AdminError(f"{qid} already resolved ({q['resolution']})")
    details = json.loads(q["details"])
    entity = q["entity_id"]
    if entity is None and q["security_id"]:
        entity = con.execute("SELECT entity_id FROM securities WHERE security_id = ?", [q["security_id"]]).fetchone()[0]
    effects: dict[str, Any] = {}

    if action == "OVERRIDE":
        effects.update(_filing_override(con, q, payload, entity, note))

    elif action == "CORP_ACTION":
        if q["stage"] != "GAP" or not q["security_id"]:
            raise AdminError("CORP_ACTION resolves GAP quarantines")
        effects.update(_add_corp_action(con, q, details, payload, entity, note))

    elif action == "ACCEPT" and q["stage"] == "CORP_ACTION" and payload:
        effects.update(_accept_corp_action(con, q, details, payload, entity, note))

    elif action == "REJECT" and q["stage"] == "CORP_ACTION" and details.get("action_id"):
        n = con.execute(
            "UPDATE corp_actions SET status = 'REJECTED', decided_at = ? WHERE action_id = ? "
            "AND status IN ('PENDING', 'QUARANTINED') RETURNING action_id",
            [utc_now(), details["action_id"]],
        ).fetchall()
        effects["rejected_action"] = details["action_id"] if n else None

    elif action == "MERGE_SECURITIES":
        if q["reason_code"] != "ISIN_COLLISION":
            raise AdminError("MERGE_SECURITIES resolves IDENTIFIER/ISIN_COLLISION quarantines")
        effects.update(_merge_securities(con, q, details, note))

    con.execute(
        "UPDATE quarantine_queue SET resolved_at = ?, resolution = ?, resolution_note = ? WHERE quarantine_id = ?",
        [utc_now(), RESOLUTIONS[action], note, qid],
    )
    return {"quarantine_id": qid, "resolution": RESOLUTIONS[action], **effects}


# OVERRIDE writes only fields the promoter reads, per quarantine reason [P2-13].
FILING_OVERRIDE_FIELDS = {
    "broadcast_ts": ("NO_VISIBILITY",),
    # ISIN_SYMBOL_CONFLICT [X288]: identifiers that disagree and no named rule settles (X101) are decided by hand,
    # on evidence the filing carries (e.g. a BSE filing's ScripCode and company name).
    "security_id": (
        "UNKNOWN_ISIN",
        "UNKNOWN_SYMBOL",
        "AMBIGUOUS_ISIN",
        "AMBIGUOUS_SYMBOL",
        "CIN_MISMATCH",
        "ISIN_SYMBOL_CONFLICT",
    ),
}


def _filing_override(con, q: dict, payload: dict, entity: str | None, note: str) -> dict:
    from datetime import datetime

    field, value = payload.get("field"), payload.get("value")
    if field not in FILING_OVERRIDE_FIELDS or value is None:
        raise AdminError(f"OVERRIDE needs payload.field in {sorted(FILING_OVERRIDE_FIELDS)} and payload.value")
    if q["reason_code"] not in FILING_OVERRIDE_FIELDS[field] or not q["filing_id"]:
        raise AdminError(f"{field} overrides resolve {FILING_OVERRIDE_FIELDS[field]} findings on a filing")
    if field == "broadcast_ts":
        value = datetime.fromisoformat(str(value)).isoformat()  # UTC, naive (invariant 11)
    else:
        row = con.execute("SELECT entity_id FROM securities WHERE security_id = ?", [value]).fetchone()
        if row is None:
            raise AdminError(f"unknown security {value}")
        entity = row[0]
    now = utc_now()
    insert_rows(con, "filing_overrides", [{
        "override_id": stable_id("fov", q["filing_id"], field, value, now), "filing_id": q["filing_id"], "field": field,
        "value": str(value), "quarantine_id": q["quarantine_id"], "reason": note, "created_at": now,
    }])  # fmt: skip
    if entity is not None:
        _override(con, entity, f"filing_{field}", {"filing_id": q["filing_id"], "value": str(value)}, now.date(), note)
    return {"override": field, "filing_id": q["filing_id"], "repromote": True}


def _add_corp_action(con, q: dict, details: dict, payload: dict, entity: str, note: str) -> dict:
    """Record a corporate action that explains a gap; it must verify against the observed gap."""
    sec, ex = q["security_id"], date.fromisoformat(details["trade_date"])
    if "action_type" not in payload:
        raise AdminError("CORP_ACTION needs payload.action_type (and ratio_num/ratio_den/issue_price as needed)")
    filing = con.execute(
        "SELECT price_filing_id FROM ohlcv WHERE security_id = ? AND trade_date = ?", [sec, ex]
    ).fetchone()
    if filing is None:
        raise AdminError(f"no bar for {sec} on {ex}")
    dec = lambda k: None if payload.get(k) is None else Decimal(str(payload[k]))  # noqa: E731
    action = CorpAction(
        action_id=stable_id("ca", "MANUAL", sec, ex, json.dumps(payload, sort_keys=True)), security_id=sec,
        action_type=payload["action_type"], ex_date=ex, ratio_num=dec("ratio_num"), ratio_den=dec("ratio_den"),
        issue_price=dec("issue_price"), cash_per_share=dec("cash_per_share"),
    )  # fmt: skip
    # Records the parser could not factor (UNKNOWN purpose) or that failed verification would poison the
    # verification group of this date [P0-3]: they are retired as SUPERSEDED by the manual action (audit kept).
    superseded = [r[0] for r in con.execute(
        "SELECT action_id FROM corp_actions WHERE security_id = ? AND ex_date = ? AND status = 'QUARANTINED'",
        [sec, ex]).fetchall()]  # fmt: skip
    now = utc_now()
    if superseded:
        con.execute(
            "UPDATE corp_actions SET status = 'SUPERSEDED', decided_at = ? WHERE security_id = ? AND ex_date = ? "
            "AND status = 'QUARANTINED'",
            [now, sec, ex],
        )
    record_corp_action(con, action, source_filing_id=filing[0], entity_id=entity)
    verify_pending_actions(con, "NSE")
    status = con.execute("SELECT status FROM corp_actions WHERE action_id = ?", [action.action_id]).fetchone()[0]
    if status not in ("VERIFIED", "UNOBSERVABLE"):
        raise AdminError(f"recorded {payload['action_type']} does not explain the gap (status {status}); not applied")
    con.execute("UPDATE corp_actions SET status = 'VERIFIED_MANUAL', decided_at = ? WHERE action_id = ?",
                [now, action.action_id])  # fmt: skip
    # The corporate-action quarantines of the retired records are closed by this resolution.
    if superseded:
        con.execute(
            "UPDATE quarantine_queue SET resolved_at = ?, resolution = 'OVERRIDDEN', resolution_note = ? "
            "WHERE stage = 'CORP_ACTION' AND resolved_at IS NULL AND security_id = ? "
            "AND (json_extract_string(details, '$.action_id') IN (SELECT unnest(?)) "
            "OR CAST(json_extract_string(details, '$.ex_date') AS DATE) = ?)",
            [now, f"superseded by {action.action_id}: {note}", sec, superseded, ex],
        )
    _override(con, entity, "manual_corp_action", {"action_id": action.action_id, **payload}, ex, note)
    still_open = con.execute(
        "SELECT count(*) FROM quarantine_queue WHERE stage = 'GAP' AND security_id = ? AND resolved_at IS NULL "
        "AND CAST(json_extract_string(details, '$.trade_date') AS DATE) = ? AND quarantine_id <> ?",
        [sec, ex, q["quarantine_id"]],
    ).fetchone()[0]
    return {"corp_action": action.action_id, "status": "VERIFIED_MANUAL", "superseded": superseded,
            "other_gaps_open_same_day": still_open}  # fmt: skip


CA_IDENTITY_REASONS = ("STALE_ISIN_OTHER_ISSUER", "UNKNOWN_ISIN", "AMBIGUOUS_SECURITY")


def _accept_corp_action(con, q: dict, details: dict, payload: dict, entity: str | None, note: str) -> dict:
    """ACCEPT with a payload on a CORP_ACTION finding: the admin decides what the feed record means [X142].

    - VERIFY_FAILED + {"accept_recorded_factor": true}: the recorded action (ratio proven by other evidence, e.g. the
      Issue Size in NSE's PR mcap file) is accepted with its theoretical factor although the ex-date open is outside
      the verification tolerance; the day is re-audited: a gap the accepted factors explain closes, a residual above
      the threshold is (re)raised as UNEXPLAINED_GAP for its own decision.
    - STALE_ISIN_OTHER_ISSUER / UNKNOWN_ISIN / AMBIGUOUS_SECURITY + {"security_id": ..., "face_value": optional}: the
      record's purpose is parsed by the same rules and recorded for that security (same action id the promoter would
      give it), then verified like any action. The security must have held the record's symbol.
    - UNPARSED_PURPOSE + {"action_type": ..., ratio_num / ratio_den / issue_price / cash_per_share}: the UNKNOWN
      record takes the stated parse (same action id) and is verified like any action.
    """
    from financials.corp_actions import ACTION_TYPES
    from financials.parsers.nse_corp_actions import parse_purpose

    reason, now = q["reason_code"], utc_now()
    if reason == "VERIFY_FAILED":
        if payload.get("accept_recorded_factor") is not True:
            raise AdminError('VERIFY_FAILED: ACCEPT payload must be {"accept_recorded_factor": true}')
        row = con.execute(
            "SELECT security_id, ex_date, price_factor, status FROM corp_actions WHERE action_id = ?",
            [details["action_id"]],
        ).fetchone()
        if row is None or row[3] != "QUARANTINED" or row[2] is None:
            raise AdminError(f"{details['action_id']} is not a factorable QUARANTINED action")
        sec, ex = row[0], row[1]
        con.execute("UPDATE corp_actions SET status = 'VERIFIED_MANUAL', decided_at = ? WHERE action_id = ?",
                    [now, details["action_id"]])  # fmt: skip
        _override(con, entity, "accepted_corp_action", {"action_id": details["action_id"]}, ex, note)
        return {"accepted_action": details["action_id"], **_reaudit_day(con, sec, ex, q["quarantine_id"])}
    if reason == "UNPARSED_PURPOSE":
        if "action_type" not in payload or not details.get("action_id"):
            raise AdminError("UNPARSED_PURPOSE: ACCEPT payload needs action_type (and its ratios / amounts)")
        dec = lambda k: None if payload.get(k) is None else Decimal(str(payload[k]))  # noqa: E731
        if payload["action_type"] not in ACTION_TYPES or payload["action_type"] == "UNKNOWN":
            raise AdminError(f"action_type must be one of {sorted(ACTION_TYPES - {'UNKNOWN'})}")
        n = con.execute(
            "UPDATE corp_actions SET action_type = ?, ratio_num = ?, ratio_den = ?, issue_price = ?, "
            "cash_per_share = ?, status = 'PENDING', decided_at = NULL WHERE action_id = ? AND action_type = 'UNKNOWN' "
            "AND status = 'QUARANTINED' RETURNING security_id, ex_date",
            [payload["action_type"], dec("ratio_num"), dec("ratio_den"), dec("issue_price"), dec("cash_per_share"),
             details["action_id"]],
        ).fetchall()  # fmt: skip
        if not n:
            raise AdminError(f"{details['action_id']} is not a QUARANTINED UNKNOWN record")
        verify_pending_actions(con, "NSE")
        status = con.execute("SELECT status FROM corp_actions WHERE action_id = ?", [details["action_id"]]).fetchone()
        _override(con, entity, "parsed_corp_action", {"action_id": details["action_id"], **payload}, n[0][1], note)
        return {"parsed_action": details["action_id"], "status": status[0]}
    if reason not in CA_IDENTITY_REASONS or "security_id" not in payload:
        raise AdminError(f"ACCEPT with a payload resolves VERIFY_FAILED, UNPARSED_PURPOSE or {CA_IDENTITY_REASONS}")
    sec, ex = payload["security_id"], date.fromisoformat(str(details["ex_date"])[:10])
    held = con.execute(
        "SELECT count(*) FROM security_identifier_history WHERE security_id = ? AND symbol = ?",
        [sec, details["symbol"]],
    ).fetchone()[0]
    if not held:
        raise AdminError(f"{sec} has never held the record's symbol {details['symbol']}")
    fv = None if payload.get("face_value") is None else Decimal(str(payload["face_value"]))
    status, why, comps = parse_purpose(details["subject"], fv)
    if status != "PARSED" or not comps:
        raise AdminError(f"purpose {details['subject']!r} is {status} ({why}): nothing to record; ACCEPT without "
                         "a payload to close the finding")  # fmt: skip
    entity = con.execute("SELECT entity_id FROM securities WHERE security_id = ?", [sec]).fetchone()[0]
    ids = []
    for i, c in enumerate(comps):
        action = CorpAction(
            action_id=stable_id("ca", "NSE", details["isin"], ex, details["subject"], i), security_id=sec,
            action_type=c.action_type, ex_date=ex, ratio_num=c.ratio_num, ratio_den=c.ratio_den,
            issue_price=c.issue_price, cash_per_share=c.cash_per_share, issue_price_floor=c.issue_price_floor,
        )  # fmt: skip
        record_corp_action(con, action, source_filing_id=q["filing_id"], entity_id=entity)
        ids.append(action.action_id)
    verify_pending_actions(con, "NSE")
    statuses = dict(con.execute("SELECT action_id, status FROM corp_actions WHERE action_id IN (SELECT unnest(?))",
                                [ids]).fetchall())  # fmt: skip
    _override(con, entity, "corp_action_security", {"actions": ids, "security_id": sec, "isin": details["isin"]}, ex,
              note)  # fmt: skip
    return {"recorded_actions": statuses}


def _reaudit_day(con, sec: str, ex: date, qid: str) -> dict:
    """Gap audit of one security-day with its currently accepted actions (as verify_pending_actions does)."""
    from financials.corp_actions import ACCEPTED_STATUSES

    bar = con.execute("SELECT open, exchange FROM ohlcv WHERE security_id = ? AND trade_date = ?", [sec, ex]).fetchone()
    if bar is None:
        return {"reaudit": "no bar on the ex-date"}
    prev = _prev_closes(con, bar[1], ex).get(sec)
    accepted = [a for a in _actions(con, "security_id = ? AND ex_date = ?", [sec, ex]) if a.status in ACCEPTED_STATUSES]
    gaps = [f for f in audit_day(sec, ex, bar[0], prev, accepted, False) if f.reason_code == "UNEXPLAINED_GAP"]
    now = utc_now()
    if any(a.action_type in ("SPLIT", "CONSOLIDATION") for a in accepted):
        con.execute(
            "UPDATE quarantine_queue SET resolved_at = ?, resolution = 'FIXED_BY_RULE', resolution_note = ? "
            "WHERE stage = 'GAP' AND reason_code = 'ISIN_CHANGE_WITHOUT_ACTION' AND security_id = ? "
            "AND resolved_at IS NULL AND CAST(json_extract_string(details, '$.trade_date') AS DATE) = ?",
            [now, "explained by recorded split/consolidation", sec, ex],
        )
    if not gaps:
        con.execute(
            "UPDATE quarantine_queue SET resolved_at = ?, resolution = 'FIXED_BY_RULE', resolution_note = ? "
            "WHERE stage = 'GAP' AND reason_code = 'UNEXPLAINED_GAP' AND security_id = ? AND resolved_at IS NULL "
            "AND CAST(json_extract_string(details, '$.trade_date') AS DATE) = ?",
            [now, "explained by " + ", ".join(f"{a.action_type} {a.action_id}" for a in accepted), sec, ex],
        )
        return {"residual_gap": None}
    f = gaps[0]
    gid = _quarantine(con, stage="GAP", reason_code=f.reason_code, security_id=sec,
                      details={"trade_date": ex, "gap": f.gap, "prev_close": prev, "open": bar[0]})  # fmt: skip
    combined = Decimal(1)
    for a in accepted:
        combined *= a.price_factor
    return {"residual_gap": str(bar[0] / (prev * combined) - 1), "gap_finding": gid}


def _merge_securities(con, q: dict, details: dict, note: str) -> dict:
    """Merge the security that owns the ISIN into the one that owns the FinInstrmId (or payload choice).

    Used when a split and a series change between two promoted days created a second security
    (SIGMA, references P14). Identity, prices, actions, index rows and quarantine links move to the
    kept security; the colliding bar is then loaded from raw and audited.
    """
    keep, drop = details["fid_owner"], details["isin_owner"]
    trade_date = date.fromisoformat(details["trade_date"])
    hist = {s: fetch_dicts(con, "SELECT * FROM security_identifier_history WHERE security_id = ? ORDER BY valid_from",
                           [s]) for s in (keep, drop)}  # fmt: skip
    if not hist[keep] or not hist[drop]:
        raise AdminError("both securities must exist")
    drop_start = hist[drop][0]["valid_from"]
    if any(r["valid_from"] >= drop_start for r in hist[keep]):
        raise AdminError("kept security has history after the merged one starts: manual surgery needed")
    overlap = con.execute(
        "SELECT count(*) FROM ohlcv a JOIN ohlcv b USING (exchange, trade_date) WHERE a.security_id = ? "
        "AND b.security_id = ?",
        [keep, drop],
    ).fetchone()[0]
    if overlap:
        raise AdminError(f"{overlap} trading days have bars for both securities: not a simple merge")

    con.execute("UPDATE security_identifier_history SET valid_to = ? WHERE security_id = ? AND valid_to IS NULL",
                [drop_start, keep])  # fmt: skip
    for table in ("security_identifier_history", "ohlcv", "corp_actions", "index_constituents_history",
                  "quarantine_queue"):  # fmt: skip
        con.execute(f"UPDATE {table} SET security_id = ? WHERE security_id = ?", [keep, drop])
    drop_entity = con.execute("SELECT entity_id FROM securities WHERE security_id = ?", [drop]).fetchone()[0]
    keep_entity = con.execute("SELECT entity_id FROM securities WHERE security_id = ?", [keep]).fetchone()[0]
    # Tombstone, never delete: the dropped security keeps its row (now unreferenced); its entity is MERGED.
    # (Deleting would also trip DuckDB's same-transaction foreign-key limitation.)
    if (
        not con.execute(
            "SELECT count(*) FROM securities WHERE entity_id = ? AND security_id <> ?", [drop_entity, drop]
        ).fetchone()[0]
        and drop_entity != keep_entity
    ):
        for table in ("filing_meta", "fact_observations", "segment_observations", "shareholding_meta",
                      "shareholding_observations", "corp_actions", "company_overrides"):  # fmt: skip
            con.execute(f"UPDATE {table} SET entity_id = ? WHERE entity_id = ?", [keep_entity, drop_entity])
        con.execute(
            "UPDATE entity_master SET status = 'MERGED', inactive_date = ?, exit_reason = ? WHERE entity_id = ?",
            [drop_start, f"duplicate of {keep_entity} (security merge)", drop_entity],
        )
    _override(con, keep_entity, "merged_security", {"merged": drop, "into": keep}, drop_start, note)
    # Prices, identity and (when the entities merge) fundamentals move: both entities, every materialised day.
    dirty.mark_entities(con, {keep_entity, drop_entity}, MIN_TRADE_DATE, "MERGE_SECURITIES", q["quarantine_id"])

    # Load the bar that collided, now that identity is unambiguous.
    raw = fetch_dicts(
        con,
        "SELECT * FROM raw_cm_bhavcopy WHERE trade_date = ? AND fin_instrm_id = ? AND isin = ? AND series IN "
        "('EQ','BE','BZ') ORDER BY filing_id LIMIT 1",
        [trade_date, details["fin_instrm_id"], details["isin"]],
    )
    loaded = 0
    if raw:
        r = raw[0]
        con.execute("UPDATE security_identifier_history SET valid_to = ? WHERE security_id = ? AND valid_to IS NULL",
                    [trade_date, keep])  # fmt: skip
        insert_rows(con, "security_identifier_history", [{
            "security_id": keep, "exchange": r["exchange"], "fin_instrm_id": r["fin_instrm_id"], "symbol": r["symbol"],
            "series": r["series"], "isin": r["isin"], "valid_from": trade_date, "valid_to": None,
            "evidence_filing_id": r["filing_id"],
        }])  # fmt: skip
        deliv = con.execute(
            "SELECT deliv_qty, filing_id FROM raw_delivery WHERE trade_date = ? AND symbol = ? AND series = ? LIMIT 1",
            [trade_date, r["symbol"], r["series"]],
        ).fetchone()
        insert_rows(con, "ohlcv", [{
            "security_id": keep, "exchange": r["exchange"], "series": r["series"], "trade_date": trade_date,
            "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"], "volume": r["volume"],
            "turnover_inr": r["turnover_inr"], "deliv_qty": deliv[0] if deliv else None,
            "price_filing_id": r["filing_id"], "delivery_filing_id": deliv[1] if deliv else None,
        }], or_ignore=True)  # fmt: skip
        loaded = 1
        prev = _prev_closes(con, r["exchange"], trade_date).get(keep)
        acts = _actions(con, "security_id = ? AND ex_date = ?", [keep, trade_date])
        for f in audit_day(keep, trade_date, r["open"], prev, acts, False):
            _quarantine(
                con,
                stage="GAP",
                reason_code=f.reason_code,
                security_id=keep,
                details={"trade_date": trade_date, "gap": f.gap, "prev_close": prev, "open": r["open"]},
            )
    return {"kept": keep, "merged": drop, "bars_loaded": loaded}


# ── duplicate entity repair (X321) ─────────────────────────────────────────

# Derived tables: rows of the merged security are deleted and both entities marked dirty, so materialisation
# recomputes them under the kept security. Everything else that names the merged security or entity is rebound.
_DERIVED_TABLES = ("features_daily", "features_events", "screener_features")
_NOT_REBOUND = ("securities", "entity_master", "materialize_dirty", "entity_lineage", *_DERIVED_TABLES)


def duplicate_entity_isins(con, exchange: str = "NSE") -> list[dict]:
    """X321 candidates: ISINs whose identifier history names more than one security (read-only)."""
    return fetch_dicts(
        con,
        "SELECT h.isin, list(DISTINCT h.security_id ORDER BY h.security_id) AS securities, "
        "list(DISTINCT e.legal_name) AS names FROM security_identifier_history h JOIN securities s USING (security_id) "
        "JOIN entity_master e USING (entity_id) WHERE h.exchange = ? GROUP BY 1 "
        "HAVING count(DISTINCT h.security_id) > 1 ORDER BY 1",
        [exchange],
    )


def merge_duplicate_entity(con, isin: str, *, note: str, exchange: str = "NSE") -> dict:
    """Rule X321: merge the second security (and entity) that the pre-X320 resolver created for an ISIN that came
    back after inactivity in another series into the original one (audited). See `_merge_duplicate`."""
    if not note.strip():
        raise AdminError("a note is required")
    return _transaction(con, _merge_duplicate, isin, note.strip(), exchange)


def _merge_duplicate(con, isin: str, note: str, exchange: str) -> dict:
    """The kept security is the one whose identifier history starts first: the id a replay under X320 assigns
    (stable_id of the first row seen), so the repair and a rebuild agree. Refused unless the ISIN has exactly two
    securities with the same legal name, the kept one's intervals all end on or before the duplicate's first day,
    no trading day has bars for both, and neither entity is in entity_lineage. Raw tables are not touched (they hold
    source identifiers, not ours); every other row naming the duplicate security or entity is rebound, derived
    feature rows of the duplicate are deleted, and both entities are marked dirty from the first trade date. The
    duplicate's first bar is gap-audited against the kept security's last close, as promotion under X320 does."""
    secs = [r[0] for r in con.execute(
        "SELECT security_id FROM security_identifier_history WHERE exchange = ? AND isin = ? GROUP BY 1 "
        "ORDER BY min(valid_from), 1", [exchange, isin]).fetchall()]  # fmt: skip
    if len(secs) != 2:
        raise AdminError(f"{isin}: {len(secs)} securities, X321 merges exactly two")
    keep, drop = secs
    ent = dict(con.execute("SELECT security_id, entity_id FROM securities WHERE security_id IN (?, ?)",
                           secs).fetchall())  # fmt: skip
    keep_ent, drop_ent = ent[keep], ent[drop]
    names = {r[0] for r in con.execute("SELECT upper(trim(legal_name)) FROM entity_master WHERE entity_id IN (?, ?)",
                                       [keep_ent, drop_ent]).fetchall()}  # fmt: skip
    if keep_ent == drop_ent or len(names) != 1:
        raise AdminError(f"{isin}: entities {keep_ent}, {drop_ent} are not same-name duplicates")
    if con.execute("SELECT count(*) FROM securities WHERE entity_id = ? AND security_id <> ?",
                   [drop_ent, drop]).fetchone()[0]:  # fmt: skip
        raise AdminError(f"{drop_ent} has other securities: manual surgery needed")
    drop_start = con.execute("SELECT min(valid_from) FROM security_identifier_history WHERE security_id = ?",
                             [drop]).fetchone()[0]  # fmt: skip
    if con.execute("SELECT count(*) FROM security_identifier_history WHERE security_id = ? "
                   "AND (valid_to IS NULL OR valid_to > ?)", [keep, drop_start]).fetchone()[0]:  # fmt: skip
        raise AdminError(f"{keep} has identifier history after {drop} starts on {drop_start}: not a duplicate")
    if con.execute("SELECT count(*) FROM ohlcv a JOIN ohlcv b USING (exchange, trade_date) WHERE a.security_id = ? "
                   "AND b.security_id = ?", [keep, drop]).fetchone()[0]:  # fmt: skip
        raise AdminError("some trading days have bars for both securities: not a duplicate")
    if con.execute("SELECT count(*) FROM entity_lineage WHERE ? IN (parent_entity_id, child_entity_id) "
                   "OR ? IN (parent_entity_id, child_entity_id)", [keep_ent, drop_ent]).fetchone()[0]:  # fmt: skip
        raise AdminError("an entity_lineage edge names one of the entities: decide by hand")

    cols = con.execute(
        "SELECT c.table_name, c.column_name FROM information_schema.columns c JOIN information_schema.tables t "
        "USING (table_schema, table_name) WHERE c.table_schema = 'main' AND t.table_type = 'BASE TABLE' "
        "AND c.column_name IN ('security_id', 'entity_id') ORDER BY 1, 2"
    ).fetchall()
    moved: dict[str, int] = {}
    for table, col in cols:
        old, new = (drop, keep) if col == "security_id" else (drop_ent, keep_ent)
        if table in _DERIVED_TABLES:
            n = len(con.execute(f"DELETE FROM {table} WHERE {col} = ? RETURNING 1", [old]).fetchall())
            key = f"{table}.deleted"
        elif table in _NOT_REBOUND:
            continue
        else:
            n = len(con.execute(f"UPDATE {table} SET {col} = ? WHERE {col} = ? RETURNING 1", [new, old]).fetchall())
            key = f"{table}.{col}"
        if n:
            moved[key] = moved.get(key, 0) + n
    # Tombstone, never delete (as _merge_securities): the duplicate security stays unreferenced, its entity MERGED.
    con.execute(
        "UPDATE entity_master SET status = 'MERGED', inactive_date = ?, exit_reason = ? WHERE entity_id = ?",
        [drop_start, f"duplicate of {keep_ent} (X321 duplicate entity repair)", drop_ent],
    )
    _override(con, keep_ent, "merged_security", {"merged": drop, "into": keep, "rule": "X321"}, drop_start, note)
    dirty.mark_entities(con, {keep_ent, drop_ent}, MIN_TRADE_DATE, "MERGE_DUPLICATE_ENTITY", isin)

    gap = None
    first = con.execute("SELECT trade_date, open FROM ohlcv WHERE security_id = ? AND trade_date >= ? "
                        "ORDER BY 1 LIMIT 1", [keep, drop_start]).fetchone()  # fmt: skip
    if first is not None:
        prev = _prev_closes(con, exchange, first[0]).get(keep)
        acts = _actions(con, "security_id = ? AND ex_date = ?", [keep, first[0]])
        for f in audit_day(keep, first[0], first[1], prev, acts, False):
            gap = _quarantine(con, stage="GAP", reason_code=f.reason_code, security_id=keep,
                              details={"trade_date": first[0], "gap": f.gap, "prev_close": prev,
                                       "open": first[1]})  # fmt: skip
    out = {"isin": isin, "kept": keep, "merged": drop, "kept_entity": keep_ent, "merged_entity": drop_ent,
           "rebound": moved, "gap_finding": gap}  # fmt: skip
    con.execute("INSERT INTO admin_log VALUES (?, 'MERGE_DUPLICATE_ENTITY', ?, ?, ?, ?)",
                [stable_id("adm", "X321", isin, keep, drop), json.dumps({"isin": isin, "exchange": exchange}),
                 json.dumps(out, default=str), note, utc_now()])  # fmt: skip
    return out


# ── scope override (Mandate 3) ─────────────────────────────────────────────

SCOPE_VALUES = ("CONSOLIDATED", "STANDALONE")


def set_scope_override(con, entity_id: str, *, quarterly: str | None, annual: str | None, reason: str) -> dict:
    """Pin a company's quarterly / annual scope (C18), or clear the pin with quarterly = annual = None.
    Audited: every change appends a company_overrides row (field 'scope_policy')."""
    if not reason.strip():
        raise AdminError("a reason is required")
    if (quarterly is None) != (annual is None):
        raise AdminError("set both scopes, or neither to clear the override")
    for v in (quarterly, annual):
        if v is not None and v not in SCOPE_VALUES:
            raise AdminError(f"scope must be one of {SCOPE_VALUES}")
    return _transaction(con, _set_scope, entity_id, quarterly, annual, reason.strip())


def _set_scope(con, entity_id: str, quarterly: str | None, annual: str | None, reason: str) -> dict:
    if con.execute("SELECT 1 FROM entity_master WHERE entity_id = ?", [entity_id]).fetchone() is None:
        raise AdminError(f"unknown entity {entity_id}")
    now = utc_now()
    con.execute("DELETE FROM entity_scope_override WHERE entity_id = ?", [entity_id])
    value = {"quarterly": quarterly, "annual": annual} if quarterly else "CLEARED"
    if quarterly:
        row = {"entity_id": entity_id, "quarterly_scope": quarterly, "annual_scope": annual, "reason": reason,
               "recorded_at": now}  # fmt: skip
        insert_rows(con, "entity_scope_override", [row])
    body = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    dirty.mark_entities(con, [entity_id], MIN_TRADE_DATE, "SCOPE_OVERRIDE", body)  # applies at every as-of
    insert_rows(con, "company_overrides", [{
        "override_id": stable_id("ovr", entity_id, "scope_policy", body, now), "entity_id": entity_id,
        "field": "scope_policy", "value": body, "valid_from": now.date(), "valid_to": None, "reason": reason,
        "created_at": now,
    }])  # fmt: skip
    return {"entity_id": entity_id, "scope_policy": value}


ARCHETYPE_VALUES = ("INDUSTRIAL_SERVICES", "FINANCIAL_LENDING", "INSURANCE", "NEW_GEN_TECH")


def set_archetype_override(con, entity_id: str, *, archetype: str | None, reason: str) -> dict:
    """Pin (or clear with archetype=None) a company's valuation archetype (C21); audited in company_overrides."""
    if not reason.strip():
        raise AdminError("a reason is required")
    if archetype is not None and archetype not in ARCHETYPE_VALUES:
        raise AdminError(f"archetype must be one of {ARCHETYPE_VALUES}")
    return _transaction(con, _set_archetype, entity_id, archetype, reason.strip())


def _set_archetype(con, entity_id: str, archetype: str | None, reason: str) -> dict:
    if con.execute("SELECT 1 FROM entity_master WHERE entity_id = ?", [entity_id]).fetchone() is None:
        raise AdminError(f"unknown entity {entity_id}")
    now = utc_now()
    con.execute("DELETE FROM entity_archetype_override WHERE entity_id = ?", [entity_id])
    if archetype:
        insert_rows(con, "entity_archetype_override", [{"entity_id": entity_id, "valuation_archetype": archetype,
                                                        "reason": reason, "recorded_at": now}])  # fmt: skip
    body = archetype or "CLEARED"
    dirty.mark_entities(con, [entity_id], MIN_TRADE_DATE, "ARCHETYPE_OVERRIDE", body)  # applies at every as-of
    insert_rows(con, "company_overrides", [{
        "override_id": stable_id("ovr", entity_id, "valuation_archetype", body, now), "entity_id": entity_id,
        "field": "valuation_archetype", "value": body, "valid_from": now.date(), "valid_to": None, "reason": reason,
        "created_at": now,
    }])  # fmt: skip
    return {"entity_id": entity_id, "valuation_archetype": body}


# ── PDF-verified corrections (owner decision B, 2026-11-15) ──

# Batch K: tags the parsers file as INR_PER_SHARE (fact_observations.value_other). Their corrections carry
# `value_other` (rupees per share, at most 4 decimals); every other tag is corrected in rupees (`value_inr`).
PER_SHARE_TAGS = frozenset({
    "eps_basic", "eps_basic_continuing", "eps_diluted", "eps_basic_before_extraordinary", "face_value_per_share",
})  # fmt: skip


def correct_from_pdf(
    con,
    filing_id: str,
    corrections: list[dict],
    *,
    evidence_url: str,
    evidence_page: int,
    evidence_text: str,
    reads: str,
    note: str,
    quarantine_id: str | None = None,
) -> list[str]:
    """Record values read from the filing's signed statutory results PDF, where the company's XBRL is wrong. Each
    correction: {canonical_tag, period_start, period_end, value_inr} in rupees, or for a per-share tag
    (PER_SHARE_TAGS: EPS, face value) {canonical_tag, period_start, period_end, value_other} in rupees per share.
    Requires the evidence (URL, page, printed text) and at least two independent reads that agreed (`reads`, e.g.
    "TEXT+HAIKU"). Correcting owners or NCI also withdraws the X86 attribution_withheld marker for that period. Raw
    XBRL and fact_observations are never touched; readers rank a correction above the filing's own value
    (fundamentals._fact_source). Resolves `quarantine_id` as CORRECTED when given. Returns the correction ids."""
    if not corrections or not evidence_url or not evidence_text.strip() or not note.strip():
        raise AdminError("corrections, evidence_url, evidence_text and note are required")
    if "+" not in reads:
        raise AdminError("a correction needs at least two independent reads that agreed, e.g. TEXT+HAIKU")
    return _transaction(con, _correct, filing_id, corrections, evidence_url, int(evidence_page),
                        evidence_text.strip(), reads, note.strip(), quarantine_id)  # fmt: skip


def _correct(con, filing_id, corrections, url, page, text, reads, note, qid) -> list[str]:
    meta = con.execute("SELECT entity_id, scope FROM filing_meta WHERE filing_id = ? LIMIT 1", [filing_id]).fetchone()
    if meta is None:
        raise AdminError(f"{filing_id} has no promoted filing_meta")
    entity, scope = meta
    rows, now = [], utc_now()
    rows_in = list(corrections)
    for c in corrections:
        if c["canonical_tag"] in ATTRIBUTION_TAGS:
            marker = {"canonical_tag": "attribution_withheld", "period_start": c["period_start"],
                      "period_end": c["period_end"], "value_inr": None}  # fmt: skip
            if marker not in rows_in:
                rows_in.append(marker)
    for c in rows_in:
        start, end = date.fromisoformat(str(c["period_start"])), date.fromisoformat(str(c["period_end"]))
        value_inr, value_other = _correction_values(c)
        value = value_other if c["canonical_tag"] in PER_SHARE_TAGS else value_inr
        cid = stable_id("corr", filing_id, c["canonical_tag"], start, end, value)
        rows.append({
            "correction_id": cid, "filing_id": filing_id, "entity_id": entity, "scope": scope,
            "canonical_tag": c["canonical_tag"], "period_type": "INSTANT" if start == end else "DURATION",
            "period_start": start, "period_end": end, "value_inr": value_inr, "evidence_url": url,
            "evidence_page": page, "evidence_text": text, "reads": reads, "quarantine_id": qid, "note": note,
            "created_at": now, "revoked_at": None, "value_other": value_other,
        })  # fmt: skip
    # X201: a value read from the PDF replaces the rule's rescaled value of the same filing, tag and period
    for r in rows:
        con.execute(
            "UPDATE fact_corrections SET revoked_at = ?, note = note || ' | revoked: replaced by a PDF correction' "
            "WHERE filing_id = ? AND canonical_tag = ? AND period_start = ? AND period_end = ? AND revoked_at IS NULL "
            "AND reads LIKE ? AND correction_id <> ?",
            [now, filing_id, r["canonical_tag"], r["period_start"], r["period_end"], SLIP_READS_PREFIX + "%",
             r["correction_id"]],
        )  # fmt: skip
    existing = {r[0] for r in con.execute("SELECT correction_id FROM fact_corrections").fetchall()}
    new = [r for r in rows if r["correction_id"] not in existing]
    if new:
        insert_rows(con, "fact_corrections", new)
        _mark_correction_dirty(con, filing_id, entity, "fact_correction")
    if qid is not None:
        q = con.execute("SELECT resolved_at FROM quarantine_queue WHERE quarantine_id = ?", [qid]).fetchone()
        if q is None:
            raise AdminError(f"unknown quarantine id {qid}")
        if q[0] is None:
            con.execute(
                "UPDATE quarantine_queue SET resolved_at = ?, resolution = 'CORRECTED', resolution_note = ? "
                "WHERE quarantine_id = ?",
                [now, f"{note} [PDF {url} p.{page}; reads {reads}]", qid],
            )
    return [r["correction_id"] for r in rows]


# ── X201 rule LEVEL_OF_ROUNDING_SLIP (level_slip.py) ──
# A results filing that declares the wrong LevelOfRounding has every rupee amount off by the unit ratio. The rule's
# corrections sit in fact_corrections like a PDF correction (same ranking, revocable, raw facts untouched), with the
# XBRL as evidence_url and `reads` naming the agreeing checks; a later PDF correction of the same value replaces it.
SLIP_READS_PREFIX = "RULE_X201"
SLIP_SHARE_COUNT_TAGS = ("shares_from_paid_up",)  # value_other derived from paid-up / face value: off by the ratio
VK = version_key()


def find_level_slips(con) -> list[dict]:
    """Every quarterly results filing (current parser version) the X201 rule rescales, with its proof, and every
    Reg. 34 annual filing it rescales (X235, `_annual_level_slips`)."""
    meta = con.execute(
        "SELECT m.filing_id, m.entity_id, m.scope, m.level_of_rounding, m.period_end, f.source_url FROM filing_meta m "
        "JOIN filings f USING (filing_id) WHERE "
        + RESULTS_CATEGORY_SQL
        + " AND m.accounting_profile <> 'REG34_ANNUAL' "
        "QUALIFY row_number() OVER (PARTITION BY m.filing_id ORDER BY " + version_key("m.parser_version") + " DESC) = 1"
    ).fetchall()
    quarter = {}
    for fid, tag, v in con.execute(
        "SELECT o.filing_id, o.canonical_tag, any_value(coalesce(o.value_inr, o.value_other)) FROM fact_observations o "
        f"JOIN (SELECT filing_id, arg_max(parser_version, {VK}) AS pv, arg_max(period_end, {VK}) AS pe "
        "FROM filing_meta GROUP BY filing_id) m ON m.filing_id = o.filing_id "
        "AND m.pv = o.parser_version AND m.pe = o.period_end "
        "WHERE o.period_type = 'DURATION' AND o.period_months = 3 AND o.canonical_tag IN "
        "('paid_up_equity_capital', 'face_value_per_share', 'eps_basic', 'pat', 'pat_owners') GROUP BY ALL"
    ).fetchall():
        quarter.setdefault(fid, {})[tag] = v
    shp: dict[str, list] = {}
    for ent, as_of, shares in con.execute(
        "SELECT entity_id, as_of_date, max(shares) FROM shareholding_observations WHERE category = 'TOTAL' "
        "AND shares > 0 GROUP BY ALL"
    ).fetchall():
        shp.setdefault(ent, []).append((as_of, shares))
    by_pair: dict[tuple[str, str], list] = {}
    for row in meta:
        by_pair.setdefault((row[1], row[2]), []).append(row)
    out = []
    for (ent, scope), rows in by_pair.items():
        if len({r[3] for r in rows}) < 2:
            continue
        for fid, _, _, level, end, url in rows:
            others = [r for r in rows if r[0] != fid]
            near = [s for s in shp.get(ent, []) if abs((s[0] - end).days) <= 92]
            shares = min(near, key=lambda s: (abs((s[0] - end).days), s[0]))[1] if near else None
            q = quarter.get(fid, {})
            usual = usual_level([r[3] for r in others])
            v = level_slip(
                level, [r[3] for r in others], paid_up=q.get("paid_up_equity_capital"),
                neighbour_paid_ups=[quarter.get(r[0], {}).get("paid_up_equity_capital") for r in others
                                    if r[3] == usual],
                face_value=q.get("face_value_per_share"), shp_shares=shares, eps_basic=q.get("eps_basic"),
                profit=q.get("pat_owners") or q.get("pat"),
            )  # fmt: skip
            if v is not None:
                out.append({"filing_id": fid, "entity_id": ent, "scope": scope, "period_end": end,
                            "source_url": url, "verdict": v})  # fmt: skip
    out += _annual_level_slips(con, by_pair, quarter, shp)
    return sorted(out, key=lambda x: (x["entity_id"], x["scope"], x["period_end"], x["filing_id"]))


def _annual_level_slips(con, by_pair: dict, quarter: dict, shp: dict) -> list[dict]:
    """X235: the X201 proof for a Reg. 34 annual filing, against the entity-scope's quarterly results filings (the
    neighbours; another annual never votes, so two slipped annuals cannot outvote the results). The annual files
    no face value and no quarter, so: (A) its FY-end `equity_share_capital` against the neighbours' paid-up capital
    at the usual level; (B) the shareholding pattern's total shares nearest the FY end x the face value of the
    entity's results filing nearest the FY end (either scope; per share, independent of the declared unit) against
    that capital; (C) its full-year basic EPS (`eps_basic`, else `eps_basic_continuing`) x those shares against its
    full-year profit (owners' where filed). Same thresholds as X201: two checks at the unit ratio, none at 1.
    TD Power Systems consolidated FY25 and FY26 (`Rupees`, results `Lakhs`): FY26 revenue 185,623.38 rupees = Rs
    1,856.23 Cr typed in lakhs; equity capital 3,124.30 vs 156,214,830 shares x Rs 2."""
    metas = con.execute(
        "SELECT m.filing_id, m.entity_id, m.scope, m.level_of_rounding, m.fy_end, f.source_url FROM filing_meta m "
        "JOIN filings f USING (filing_id) WHERE m.accounting_profile = 'REG34_ANNUAL' "
        "QUALIFY row_number() OVER (PARTITION BY m.filing_id ORDER BY " + version_key("m.parser_version") + " DESC) = 1"
    ).fetchall()
    if not metas:
        return []
    facts: dict[str, dict] = {}
    for fid, tag, v in con.execute(
        "SELECT o.filing_id, o.canonical_tag, any_value(coalesce(o.value_inr, o.value_other)) FROM fact_observations o "
        f"JOIN (SELECT filing_id, arg_max(parser_version, {VK}) AS pv, arg_max(fy_end, {VK}) AS fe FROM filing_meta "
        "WHERE accounting_profile = 'REG34_ANNUAL' GROUP BY filing_id) m ON m.filing_id = o.filing_id "
        "AND m.pv = o.parser_version AND m.fe = o.period_end "
        "WHERE ((o.period_type = 'INSTANT' AND o.canonical_tag = 'equity_share_capital') OR (o.period_type = "
        "'DURATION' AND o.period_months = 12 AND o.canonical_tag IN ('eps_basic', 'eps_basic_continuing', 'pat', "
        "'pat_owners'))) GROUP BY ALL"
    ).fetchall():
        facts.setdefault(fid, {})[tag] = v
    face: dict[str, list] = {}
    for (ent, _scope), rows in by_pair.items():
        for fid, _, _, _, end, _ in rows:
            fv = quarter.get(fid, {}).get("face_value_per_share")
            if fv:
                face.setdefault(ent, []).append((end, fv))
    out = []
    for fid, ent, scope, level, fy_end, url in metas:
        results = by_pair.get((ent, scope), [])
        usual = usual_level([r[3] for r in results])
        if usual is None or usual == level:
            continue
        near = [s for s in shp.get(ent, []) if abs((s[0] - fy_end).days) <= 92]
        shares = min(near, key=lambda s: (abs((s[0] - fy_end).days), s[0]))[1] if near else None
        fvs = [x for x in face.get(ent, []) if abs((x[0] - fy_end).days) <= 92]
        fv = min(fvs, key=lambda x: (abs((x[0] - fy_end).days), x[0]))[1] if fvs else None
        a = facts.get(fid, {})
        v = level_slip(
            level, [r[3] for r in results], paid_up=a.get("equity_share_capital"),
            neighbour_paid_ups=[quarter.get(r[0], {}).get("paid_up_equity_capital") for r in results
                                if r[3] == usual],
            face_value=fv, shp_shares=shares, eps_basic=a.get("eps_basic") or a.get("eps_basic_continuing"),
            profit=a.get("pat_owners") or a.get("pat"),
        )  # fmt: skip
        if v is not None:
            out.append({"filing_id": fid, "entity_id": ent, "scope": scope, "period_end": fy_end, "source_url": url,
                        "verdict": v, "annual": True})  # fmt: skip
    return out


def rescale_level_slips(con, *, dry_run: bool = False) -> list[dict]:
    """X201: record, for every filing `find_level_slips` proves, each rupee amount (and the share count derived from
    paid-up capital) times the unit ratio as a correction; (tag, period)s already corrected are left alone. Then the
    YTD audit of the affected entity-scopes closes the findings the slip caused. Idempotent (stable ids)."""
    slips = find_level_slips(con)
    if dry_run or not slips:
        return slips
    return _transaction(con, _rescale, slips)


def _rescale(con, slips: list[dict]) -> list[dict]:
    from financials.promoter import audit_ytd_identity

    now = utc_now()
    existing = {r[0] for r in con.execute("SELECT correction_id FROM fact_corrections").fetchall()}
    for s in slips:
        v = s["verdict"]
        taken = {tuple(r) for r in con.execute(
            "SELECT canonical_tag, period_start, period_end FROM fact_corrections WHERE filing_id = ? "
            "AND revoked_at IS NULL", [s["filing_id"]]).fetchall()}  # fmt: skip
        facts = con.execute(
            "SELECT canonical_tag, period_type, period_start, period_end, value_inr, value_other "
            f"FROM fact_observations o WHERE filing_id = ? AND parser_version = (SELECT arg_max(parser_version, {VK}) "
            "FROM filing_meta m WHERE m.filing_id = o.filing_id) "
            "AND (value_inr IS NOT NULL OR canonical_tag IN (SELECT unnest(?))) "
            "ORDER BY ALL",
            [s["filing_id"], list(SLIP_SHARE_COUNT_TAGS)],
        ).fetchall()
        rows, seen = [], set()
        for tag, ptype, start, end, inr, other in facts:
            if (tag, start, end) in taken or (tag, start, end) in seen:
                continue
            seen.add((tag, start, end))
            value_inr = rescaled(inr, v.factor) if inr is not None else None
            value_other = (Decimal(other) * v.factor).quantize(Decimal("0.0001")) if inr is None else None
            cid = stable_id("corr", s["filing_id"], tag, start, end, value_inr if inr is not None else value_other)
            if cid in existing:
                continue
            existing.add(cid)
            rows.append({
                "correction_id": cid, "filing_id": s["filing_id"], "entity_id": s["entity_id"], "scope": s["scope"],
                "canonical_tag": tag, "period_type": ptype, "period_start": start, "period_end": end,
                "value_inr": value_inr, "evidence_url": s["source_url"], "evidence_page": 0,
                "evidence_text": v.evidence(), "reads": SLIP_READS_PREFIX + "+" + "+".join(
                    c.name for c in v.checks if c.verdict == "SLIP"),
                "quarantine_id": None, "created_at": now, "revoked_at": None, "value_other": value_other,
                "note": f"X201 {v.declared} declared, filed in {v.usual}: as filed x {v.factor:f}",
            })  # fmt: skip
        if rows:
            insert_rows(con, "fact_corrections", rows)
            _mark_correction_dirty(con, s["filing_id"], s["entity_id"], "level_of_rounding_slip")
        s["corrections"] = len(rows)
    audit_ytd_identity(con, sorted({(s["entity_id"], s["scope"]) for s in slips}))
    annual = sorted({s["entity_id"] for s in slips if s.get("annual")})
    if annual:  # X235: the prior-year check of these entities' annuals compares at the corrected scale
        from financials.promoter import audit_annual_checks

        audit_annual_checks(con, entity_ids=annual)
    return slips


def _correction_values(c: dict) -> tuple[Decimal | None, Decimal | None]:
    """(value_inr, value_other) of one correction. A per-share tag takes `value_other` only (DECIMAL(18,4), as in
    fact_observations it is never rupees); any other tag takes `value_inr` only (DECIMAL(20,2) rupees). None
    withdraws the tag for that period either way."""
    tag = c["canonical_tag"]
    per_share = tag in PER_SHARE_TAGS
    key, other = ("value_other", "value_inr") if per_share else ("value_inr", "value_other")
    if key not in c or c.get(other) is not None:
        unit = "rupees per share" if per_share else "rupees"
        raise AdminError(f"{tag}: give `{key}` ({unit}), not `{other}`")
    if c[key] is None:
        return None, None
    v = Decimal(str(c[key]))
    places = Decimal("0.0001") if per_share else Decimal("0.01")
    if v != v.quantize(places) or abs(v) >= Decimal(10) ** (14 if per_share else 18):
        raise AdminError(f"{tag}: {v} does not fit {'DECIMAL(18,4)' if per_share else 'DECIMAL(20,2)'}")
    # not quantized: the stable_id of a rupee correction recorded before batch K must not change
    return (None, v) if per_share else (v, None)


def revoke_correction(con, correction_id: str, note: str) -> None:
    """Withdraw a correction (the filed value applies again); the row stays for the audit trail."""
    if not note.strip():
        raise AdminError("a note is required")
    n = con.execute(
        "UPDATE fact_corrections SET revoked_at = ?, note = note || ' | revoked: ' || ? "
        "WHERE correction_id = ? AND revoked_at IS NULL RETURNING filing_id, entity_id",
        [utc_now(), note.strip(), correction_id],
    ).fetchall()
    if not n:
        raise AdminError(f"no active correction {correction_id}")
    _mark_correction_dirty(con, n[0][0], n[0][1], "fact_correction_revoked")


def _mark_correction_dirty(con, filing_id: str, entity_id: str, reason: str) -> None:
    """Incremental materialisation: the entity's rows change from the corrected filing's earliest visibility."""
    from financials.dirty import mark_visible

    vis = con.execute("SELECT min(visible_from_ts) FROM filing_meta WHERE filing_id = ?", [filing_id]).fetchone()[0]
    if vis is not None:
        mark_visible(con, entity_id, vis, reason, filing_id)


# ── corporate lineage (G37, G51, G56, G57; architecture §11.7) ────────────
# Append-only edges in entity_lineage (financials.lineage). A merger marks the target MERGED with merged_into; it
# never writes corp_actions, so neither the acquirer's nor the target's adjusted prices change (factor 1.0, G57).


def _dec(x) -> str | None:
    return None if x is None else f"{Decimal(x).normalize():f}"


def _lineage_entity(con, ident: str) -> str:
    """An entity id, an ISIN or an NSE symbol (any interval of the identifier history); must name one entity."""
    ident = ident.strip()
    if con.execute("SELECT 1 FROM entity_master WHERE entity_id = ?", [ident]).fetchone():
        return ident
    is_isin = len(ident) == 12 and ident[:2].isalpha() and ident[2:].isalnum() and ident[-1].isdigit()
    col = "isin" if is_isin else "symbol"
    rows = con.execute(
        f"SELECT DISTINCT s.entity_id FROM security_identifier_history h JOIN securities s USING (security_id) "
        f"WHERE h.{col} = ?",
        [ident],
    ).fetchall()
    if len(rows) != 1:
        raise AdminError(f"{col} {ident!r} names {len(rows)} entities; pass the entity id")
    return rows[0][0]


def _lineage_rows(con, where: str = "", params: list | None = None) -> list[dict]:
    return fetch_dicts(con, f"SELECT * FROM entity_lineage {where}", params or [])


def _current_lineage(con, lineage_id: str) -> dict:
    rows = _lineage_rows(con, "WHERE lineage_id = ?", [lineage_id])
    if not rows:
        raise AdminError(f"no lineage row {lineage_id}")
    if lineage_id not in {e.lineage_id for e in _lineage_edges(con)}:
        raise AdminError(f"{lineage_id} is superseded or retired; amend the current row")
    return rows[0]


def _demerger_evidence(con, parent: str, effective: date) -> str:
    """A DEMERGED_FROM edge needs the parent's accepted DEMERGER action on the effective date (its price factor)."""
    from financials.corp_actions import ACCEPTED_STATUSES

    row = con.execute(
        "SELECT source_filing_id FROM corp_actions c JOIN securities s USING (security_id) WHERE s.entity_id = ? "
        "AND c.action_type = 'DEMERGER' AND c.ex_date = ? AND c.status IN (SELECT unnest(?)) "
        "ORDER BY c.action_id LIMIT 1",
        [parent, effective, sorted(ACCEPTED_STATUSES)],
    ).fetchone()
    if row is None:
        raise AdminError(f"{parent} has no accepted DEMERGER action with ex-date {effective}")
    return row[0]


def _insert_lineage(con, row: dict, *, action: str, note: str, reactivate: bool = False) -> dict:
    """Validate, insert (deterministic id), apply the merger status, check the COA split and audit one edge row."""
    from financials.lineage import MERGE_RELATIONS, LineageEdge, LineageError, coa_split, load_edges

    keys = ("parent_entity_id", "child_entity_id", "relation", "effective_date", "swap_ratio_num", "swap_ratio_den",
            "coa_pct", "parent_coa_pct", "state", "supersedes_lineage_id")  # fmt: skip
    try:
        edge = LineageEdge("new", *(row.get(k) for k in keys))
    except LineageError as exc:
        raise AdminError(str(exc)) from exc
    lineage_id = stable_id("lin", edge.parent_entity_id, edge.child_entity_id, edge.relation, edge.effective_date,
                           _dec(edge.swap_ratio_num), _dec(edge.swap_ratio_den), _dec(edge.coa_pct),
                           _dec(edge.parent_coa_pct), edge.state, edge.supersedes_lineage_id)  # fmt: skip
    if con.execute("SELECT 1 FROM entity_lineage WHERE lineage_id = ?", [lineage_id]).fetchone():
        tip = _chain_tip(con, lineage_id)
        if not reactivate or tip == lineage_id:
            return {"lineage_id": lineage_id, "inserted": False}
        if con.execute("SELECT state FROM entity_lineage WHERE lineage_id = ?", [tip]).fetchone()[0] != "RETIRED":
            raise AdminError(f"edge exists as {tip}; use `lineage amend` or `lineage coa`")
        # `lineage add` of an edge retired earlier: a new ACTIVE row supersedes the RETIRED one.
        return _insert_lineage(con, {**row, "supersedes_lineage_id": tip}, action=action, note=note)
    if edge.supersedes_lineage_id is None:
        same = [e for e in load_edges(con) if (e.parent_entity_id, e.child_entity_id, e.relation, e.effective_date)
                == (edge.parent_entity_id, edge.child_entity_id, edge.relation, edge.effective_date)]  # fmt: skip
        if same:
            raise AdminError(f"edge exists as {same[0].lineage_id}; use `lineage amend` or `lineage coa`")
    now = utc_now()
    insert_rows(con, "entity_lineage", [{**{k: row.get(k) for k in keys}, "lineage_id": lineage_id,
                                         "evidence_filing_id": row.get("evidence_filing_id"),
                                         "evidence_url": row.get("evidence_url"), "source": row["source"],
                                         "note": note, "recorded_at": now}])  # fmt: skip

    if edge.relation in MERGE_RELATIONS:
        _apply_merger_status(con, edge, lineage_id)
    elif edge.state == "ACTIVE":
        try:
            coa_split(load_edges(con), edge.parent_entity_id, edge.effective_date)
        except LineageError as exc:
            raise AdminError(str(exc)) from exc
    value = {k: row.get(k) for k in keys if row.get(k) is not None} | {"lineage_id": lineage_id}
    _override(con, edge.child_entity_id, "lineage", value, edge.effective_date, note)
    con.execute(
        "INSERT INTO admin_log VALUES (?, ?, ?, ?, ?, ?)",
        [stable_id("adm", "lineage", action, lineage_id, now), "LINEAGE_" + action,
         json.dumps(value, default=str, sort_keys=True), json.dumps({"lineage_id": lineage_id}), note, now],
    )  # fmt: skip
    return {"lineage_id": lineage_id, "inserted": True}


def _chain_tip(con, lineage_id: str) -> str:
    """The latest row of a supersession chain (append-only: each row is superseded at most once by design)."""
    while True:
        nxt = con.execute("SELECT lineage_id FROM entity_lineage WHERE supersedes_lineage_id = ? ORDER BY recorded_at "
                          "DESC LIMIT 1", [lineage_id]).fetchone()  # fmt: skip
        if nxt is None:
            return lineage_id
        lineage_id = nxt[0]


def _apply_merger_status(con, edge, lineage_id: str) -> None:
    """G56: the target of a current merger edge is MERGED into the acquirer from the effective date; a retired edge
    reactivates it. Prices are never touched (G57)."""
    status, merged_into = con.execute("SELECT status, merged_into FROM entity_master WHERE entity_id = ?",
                                      [edge.child_entity_id]).fetchone()  # fmt: skip
    if edge.state == "RETIRED":
        if merged_into == edge.parent_entity_id:
            con.execute("UPDATE entity_master SET status = 'ACTIVE', inactive_date = NULL, exit_reason = NULL, "
                        "merged_into = NULL WHERE entity_id = ?", [edge.child_entity_id])  # fmt: skip
        return
    if status == "MERGED" and merged_into != edge.parent_entity_id:
        raise AdminError(f"{edge.child_entity_id} is already MERGED ({merged_into or 'duplicate-security repair'})")
    con.execute(
        "UPDATE entity_master SET status = 'MERGED', inactive_date = ?, exit_reason = ?, merged_into = ? "
        "WHERE entity_id = ?",
        [edge.effective_date, f"{edge.relation} {edge.parent_entity_id} ({lineage_id})", edge.parent_entity_id,
         edge.child_entity_id],
    )  # fmt: skip


def add_lineage(
    con,
    *,
    parent: str,
    child: str,
    relation: str,
    effective_date: date,
    ratio_num: Decimal | None = None,
    ratio_den: Decimal | None = None,
    evidence_url: str,
    note: str,
) -> dict:
    """Record one edge by hand (`lineage add`). Automatic merger parsing is BLOCKED: no merger purpose exists in the
    NSE corporate-actions feed [CA14], so mergers come only from here, each with the URL of its evidence."""
    if not evidence_url.strip() or not note.strip():
        raise AdminError("an evidence URL and a note are required")

    def run(con):
        p, c = _lineage_entity(con, parent), _lineage_entity(con, child)
        evidence = _demerger_evidence(con, p, effective_date) if relation == "DEMERGED_FROM" else None
        return _insert_lineage(con, {
            "parent_entity_id": p, "child_entity_id": c, "relation": relation, "effective_date": effective_date,
            "swap_ratio_num": ratio_num, "swap_ratio_den": ratio_den, "state": "ACTIVE",
            "evidence_filing_id": evidence, "evidence_url": evidence_url.strip(), "source": "ADMIN",
        }, action="ADD", note=note.strip(), reactivate=True)  # fmt: skip

    return _transaction(con, run)


def amend_lineage(con, lineage_id: str, *, ratio_num: Decimal, ratio_den: Decimal, evidence_url: str, note: str):
    """Set the swap / entitlement ratio of a current edge: a superseding row (the old row stays)."""
    if not evidence_url.strip() or not note.strip():
        raise AdminError("an evidence URL and a note are required")

    def run(con):
        old = _current_lineage(con, lineage_id)
        new = {**old, "swap_ratio_num": ratio_num, "swap_ratio_den": ratio_den, "supersedes_lineage_id": lineage_id,
               "evidence_url": evidence_url.strip(), "source": "ADMIN"}  # fmt: skip
        return _insert_lineage(con, new, action="AMEND", note=note.strip())

    return _transaction(con, run)


def set_demerger_coa(
    con,
    *,
    parent: str,
    effective_date: date,
    parent_pct: Decimal,
    children: dict[str, Decimal],
    evidence_url: str,
    note: str,
) -> dict:
    """G51: the cost-of-acquisition split of one demerger, for every child of the scheme at once; parent + children
    must sum to 100% (within 0.01 pp). Only from a figure an admin read at `evidence_url` (R7 stays UNVERIFIED)."""
    from financials.lineage import COA_TOLERANCE, HUNDRED, load_edges

    if not evidence_url.strip() or not note.strip():
        raise AdminError("an evidence URL and a note are required")
    total = Decimal(parent_pct) + sum((Decimal(v) for v in children.values()), Decimal(0))
    if abs(total - HUNDRED) > COA_TOLERANCE:
        raise AdminError(f"COA split sums to {total}%, not 100")

    def run(con):
        p = _lineage_entity(con, parent)
        named = {_lineage_entity(con, c): Decimal(v) for c, v in children.items()}
        scheme = {
            e.child_entity_id: e
            for e in load_edges(con)
            if e.relation == "DEMERGED_FROM" and e.parent_entity_id == p and e.effective_date == effective_date
        }
        if set(named) != set(scheme):
            raise AdminError(f"the scheme's children are {sorted(scheme)}; name each of them exactly once")
        out = []
        for child, pct in sorted(named.items()):
            old = _current_lineage(con, scheme[child].lineage_id)
            new = {**old, "coa_pct": pct, "parent_coa_pct": Decimal(parent_pct), "supersedes_lineage_id":
                   old["lineage_id"], "evidence_url": evidence_url.strip(), "source": "ADMIN"}  # fmt: skip
            out.append(_insert_lineage(con, new, action="COA", note=note.strip()))
        return {"parent": p, "effective_date": effective_date, "total_pct": total, "rows": out}

    return _transaction(con, run)


def retire_lineage(con, lineage_id: str, *, note: str) -> dict:
    """Withdraw an edge: a RETIRED row supersedes it; a merged target becomes ACTIVE again."""
    if not note.strip():
        raise AdminError("a note is required")

    def run(con):
        old = _current_lineage(con, lineage_id)
        new = {**old, "state": "RETIRED", "supersedes_lineage_id": lineage_id, "source": "ADMIN"}
        return _insert_lineage(con, new, action="RETIRE", note=note.strip())

    return _transaction(con, run)


def load_lineage_manifest(con, rows: list[dict], *, source: str = "entity_lineage.csv") -> dict:
    """Load edges from a manifest whose rows are pinned to committed fixtures (`reference/entity_lineage.csv`, test
    tests/test_lineage.py). Idempotent. A row whose entities are not in the database yet, or (DEMERGED_FROM) whose
    parent has no accepted DEMERGER action on the date, is skipped with its reason and loads on a later run."""
    from financials.lineage import parse_ratio

    def run(con):
        out: dict[str, Any] = {"inserted": [], "present": [], "skipped": []}
        current = {(e.parent_entity_id, e.child_entity_id, e.relation, e.effective_date): e.lineage_id
                   for e in _lineage_edges(con)}  # fmt: skip
        for r in rows:
            eff = date.fromisoformat(r["effective_date"])
            try:
                p, c = _lineage_entity(con, r["parent"]), _lineage_entity(con, r["child"])
                evidence = _demerger_evidence(con, p, eff) if r["relation"] == "DEMERGED_FROM" else None
            except AdminError as exc:
                out["skipped"].append({"parent": r["parent"], "child": r["child"], "reason": str(exc)})
                continue
            if (p, c, r["relation"], eff) in current:  # loaded before (possibly amended since): leave it
                out["present"].append(current[(p, c, r["relation"], eff)])
                continue
            num, den = parse_ratio(f"{r['ratio_num']}:{r['ratio_den']}" if r["ratio_num"] else None)
            coa, pcoa = (Decimal(r[k]) if r[k] else None for k in ("coa_pct", "parent_coa_pct"))
            res = _insert_lineage(con, {
                "parent_entity_id": p, "child_entity_id": c, "relation": r["relation"], "effective_date": eff,
                "swap_ratio_num": num, "swap_ratio_den": den, "coa_pct": coa, "parent_coa_pct": pcoa, "state": "ACTIVE",
                "evidence_filing_id": evidence, "evidence_url": r["evidence_url"], "source": "MANIFEST",
            }, action="LOAD", note=f"{source}: {r['evidence_fixture']}: {r['evidence_quote']}")  # fmt: skip
            out["inserted" if res["inserted"] else "present"].append(res["lineage_id"])
        return out

    return _transaction(con, run)


def _lineage_edges(con):
    from financials.lineage import load_edges

    return load_edges(con)
