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
        current = index_members(con, index_name, first)
        intervals, steps = reconstruct_backward(
            current, first, events, start, lambda s, d: resolve_symbol(con, s, d), expected_count=expected_count
        )
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


def _override(con, entity_id: str | None, field: str, value: Any, valid_from: date, reason: str) -> None:
    if entity_id is None:
        raise AdminError("this resolution needs an entity")
    body = value if isinstance(value, str) else json.dumps(value, default=str, sort_keys=True)
    insert_rows(con, "company_overrides", [{
        "override_id": stable_id("ovr", entity_id, field, body, valid_from), "entity_id": entity_id, "field": field,
        "value": body, "valid_from": valid_from, "valid_to": None, "reason": reason, "created_at": utc_now(),
    }], or_ignore=True)  # fmt: skip


def resolve_quarantine(con, quarantine_id: str, *, action: str, note: str, payload: dict | None = None) -> dict:
    if action not in RESOLUTIONS:
        raise AdminError(f"action must be one of {sorted(RESOLUTIONS)}")
    if not note.strip():
        raise AdminError("a resolution note is required")
    return _transaction(con, _resolve, quarantine_id, action, note.strip(), payload or {})


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
        for key in ("field", "value"):
            if key not in payload:
                raise AdminError(f"OVERRIDE needs payload.{key}")
        vf = date.fromisoformat(payload.get("valid_from", str(date.today())))
        _override(con, entity, payload["field"], payload["value"], vf, f"{qid}: {note}")
        effects["override"] = payload["field"]

    elif action == "CORP_ACTION":
        if q["stage"] != "GAP" or not q["security_id"]:
            raise AdminError("CORP_ACTION resolves GAP quarantines")
        effects.update(_add_corp_action(con, q, details, payload, entity, note))

    elif action == "MERGE_SECURITIES":
        if q["reason_code"] != "ISIN_COLLISION":
            raise AdminError("MERGE_SECURITIES resolves IDENTIFIER/ISIN_COLLISION quarantines")
        effects.update(_merge_securities(con, q, details, note))

    con.execute(
        "UPDATE quarantine_queue SET resolved_at = ?, resolution = ?, resolution_note = ? WHERE quarantine_id = ?",
        [utc_now(), RESOLUTIONS[action], note, qid],
    )
    return {"quarantine_id": qid, "resolution": RESOLUTIONS[action], **effects}


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
    record_corp_action(con, action, source_filing_id=filing[0], entity_id=entity)
    verify_pending_actions(con, "NSE")
    status = con.execute("SELECT status FROM corp_actions WHERE action_id = ?", [action.action_id]).fetchone()[0]
    if status not in ("VERIFIED", "UNOBSERVABLE"):
        raise AdminError(f"recorded {payload['action_type']} does not explain the gap (status {status}); not applied")
    _override(con, entity, "manual_corp_action", {"action_id": action.action_id, **payload}, ex, note)
    still_open = con.execute(
        "SELECT count(*) FROM quarantine_queue WHERE stage = 'GAP' AND security_id = ? AND resolved_at IS NULL "
        "AND CAST(json_extract_string(details, '$.trade_date') AS DATE) = ? AND quarantine_id <> ?",
        [sec, ex, q["quarantine_id"]],
    ).fetchone()[0]
    return {"corp_action": action.action_id, "status": status, "other_gaps_open_same_day": still_open}


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
        for table in ("filing_meta", "fact_observations", "shareholding_meta", "shareholding_observations",
                      "corp_actions", "company_overrides"):  # fmt: skip
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
