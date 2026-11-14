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

from financials.corp_actions import CorpAction, audit_day
from financials.db import fetch_dicts, insert_rows
from financials.ids import stable_id
from financials.index_changes import IndexEvent, reconstruct_backward
from financials.promoter import (
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
    con.execute("BEGIN TRANSACTION")
    try:
        out = fn(con, *args, **kwargs)
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
        from financials.promoter import REBUILD_SUPERSEDED

        now = utc_now()
        counts: dict[str, int] = {}

        def n(key: str, sql: str, params: list) -> None:
            counts[key] = len(con.execute(sql + " RETURNING 1", params).fetchall())

        features_dates = [r[0] for r in con.execute(
            "SELECT DISTINCT as_of_date FROM screener_features_history WHERE as_of_date >= ? ORDER BY 1", [from_date]
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
        n("features", "DELETE FROM screener_features_history WHERE as_of_date >= ?", [from_date])
        con.execute("DELETE FROM screener_features")
        con.execute("INSERT INTO screener_features SELECT * FROM screener_features_history WHERE as_of_date = "
                    "(SELECT max(as_of_date) FROM screener_features_history)")  # fmt: skip
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
    derivable, a filing override recorded since). Each open finding is marked REPROCESSING first; promoting
    the batch again reopens it if the problem is still there (same deterministic id), otherwise it is closed as
    REPROCESSED. MISSING_FIN_INSTRM_ID bars are loaded when their ISIN belongs to exactly one security that day
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
    if filing_ids:
        logged = [r[0] for r in con.execute("SELECT stage_path FROM promotion_log").fetchall()]
        files = [
            (stage_root / p / "filings.parquet").as_posix()
            for p in logged
            if (stage_root / p / "filings.parquet").exists()
        ]
        if files:
            rows = con.execute(
                "SELECT DISTINCT filename FROM read_parquet(?, filename = true) WHERE filing_id IN (SELECT unnest(?))",
                [files, filing_ids],
            ).fetchall()
            stages = sorted({Path(f).parent.relative_to(stage_root).as_posix() for (f,) in rows})
    ids = [q["quarantine_id"] for q in open_q]
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
    out = {"batches": results, "cleared": [r[0] for r in fixed], "bars_loaded": loaded}
    con.execute("INSERT INTO admin_log VALUES (?, 'REPROCESS', '{}', ?, NULL, ?)",
                [stable_id("adm", "reprocess", now), json.dumps(out, default=str), now])  # fmt: skip
    return out


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
               "MERGE_SECURITIES": "OVERRIDDEN"}  # fmt: skip


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
                             "resolve the day's GAP finding with --action CORP_ACTION (supersedes this record)"],
        "VERIFY_FAILED": [f"{base} --action REJECT --note '<wrong record>'",
                          "resolve the day's GAP finding with --action CORP_ACTION (supersedes this record)"],
        "NO_VISIBILITY": [f"{base} --action OVERRIDE --note '<source>' --payload-json "
                          "'{\"field\": \"broadcast_ts\", \"value\": \"YYYY-MM-DDTHH:MM:SS (UTC)\"}'",
                          "python -m financials quarantine reprocess  (after the calendar covers the date)"],
        "MISSING_SESSION": ["fetch the missing day(s), then python -m financials rebuild-market --from <date>"],
    }  # fmt: skip
    for r in ("UNKNOWN_ISIN", "UNKNOWN_SYMBOL", "AMBIGUOUS_ISIN", "AMBIGUOUS_SYMBOL", "CIN_MISMATCH"):
        suggest[r] = [f"{base} --action OVERRIDE --note '<evidence>' --payload-json "
                      "'{\"field\": \"security_id\", \"value\": \"<sec_...>\"}'",
                      "python -m financials quarantine reprocess  (once the security is known)"]  # fmt: skip
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
    "security_id": ("UNKNOWN_ISIN", "UNKNOWN_SYMBOL", "AMBIGUOUS_ISIN", "AMBIGUOUS_SYMBOL", "CIN_MISMATCH"),
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
    insert_rows(con, "company_overrides", [{
        "override_id": stable_id("ovr", entity_id, "valuation_archetype", body, now), "entity_id": entity_id,
        "field": "valuation_archetype", "value": body, "valid_from": now.date(), "valid_to": None, "reason": reason,
        "created_at": now,
    }])  # fmt: skip
    return {"entity_id": entity_id, "valuation_archetype": body}
