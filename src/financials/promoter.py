"""The single writer. Reads staged batches, runs gates, commits atomically to market.duckdb.

Gates (docs/architecture.md §12): G1 completeness and G2 identifier resolution for market
days; G3 accounting identities are enforced by the parser and surface as staged issues.
G4/G5 belong to feature materialisation (not built yet).
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from financials.corp_actions import ACCEPTED_STATUSES, CorpAction, adjust_closes, audit_day, verify_group
from financials.db import fetch_dicts, insert_rows
from financials.identity import UNIVERSE_SERIES, Interval, SecurityRegistry
from financials.ids import stable_id
from financials.parsers.udiff import BhavRow
from financials.staging import read_manifest, read_table
from financials.timeutil import ist_to_utc, utc_now, utc_to_ist_date

G1_MIN_RATIO = Decimal("0.92")
G1_LOOKBACK_DAYS = 5
G2_MAX_UNRESOLVED = Decimal("0.01")


class GateFailure(Exception):
    def __init__(self, gate: str, message: str) -> None:
        super().__init__(f"{gate}: {message}")
        self.gate = gate


@dataclass
class PromotionResult:
    status: str  # PROMOTED | ALREADY_PROMOTED | QUARANTINED | ABORTED
    job: str
    gate: str | None = None
    message: str = ""
    quarantined: list[str] = field(default_factory=list)


def promote(con: duckdb.DuckDBPyConnection, stage_dir: Path) -> PromotionResult:
    manifest = read_manifest(stage_dir)
    job = manifest["job"]
    handler = {
        "market_day": _promote_market_day,
        "results_xbrl": _promote_results_xbrl,
        "corp_actions": _promote_corp_actions,
        "holidays": _promote_holidays,
        "index_snapshot": _promote_index_snapshot,
        "shareholding": _promote_shareholding,
        "raw_only": _promote_raw_only,
    }.get(job)
    if handler is None:
        raise ValueError(f"unknown job {job!r}")
    con.execute("BEGIN TRANSACTION")
    try:
        result = handler(con, Path(stage_dir), manifest)
    except GateFailure as exc:
        con.execute("ROLLBACK")
        return PromotionResult("ABORTED", job, exc.gate, str(exc))
    except BaseException:
        con.execute("ROLLBACK")
        raise
    con.execute("COMMIT")
    return result


# ── shared helpers ──────────────────────────────────────────────────────


def _insert_vault_rows(con, stage_dir: Path, tables: Iterable[str]) -> None:
    """Load staged tables straight from Parquet; identical rows from a replay are ignored."""
    for t in tables:
        path = Path(stage_dir) / f"{t}.parquet"
        if path.exists():
            con.execute(f"INSERT OR IGNORE INTO {t} BY NAME SELECT * FROM read_parquet(?)", [path.as_posix()])


def _quarantine(
    con,
    *,
    stage: str,
    reason_code: str,
    details: dict[str, Any],
    entity_id: str | None = None,
    security_id: str | None = None,
    filing_id: str | None = None,
) -> str:
    body = json.dumps(details, default=str, sort_keys=True)
    qid = stable_id("q", stage, reason_code, entity_id, security_id, filing_id, body)
    insert_rows(
        con,
        "quarantine_queue",
        [
            {
                "quarantine_id": qid,
                "stage": stage,
                "reason_code": reason_code,
                "entity_id": entity_id,
                "security_id": security_id,
                "filing_id": filing_id,
                "details": body,
                "created_at": utc_now(),
            }
        ],
        or_ignore=True,
    )
    return qid


def _load_intervals(con, exchange: str) -> list[Interval]:
    rows = fetch_dicts(con, "SELECT * FROM security_identifier_history WHERE exchange = ?", [exchange])
    return [
        Interval(
            r["security_id"],
            r["exchange"],
            r["fin_instrm_id"],
            r["symbol"],
            r["series"],
            r["isin"],
            r["valid_from"],
            r["valid_to"],
            r["evidence_filing_id"],
        )
        for r in rows
    ]


# ── market day ──────────────────────────────────────────────────────────


def _promote_market_day(con, stage_dir: Path, manifest: dict[str, Any]) -> PromotionResult:
    exchange = manifest["exchange"]
    trade_date = date.fromisoformat(manifest["trade_date"])
    bhav = read_table(con, stage_dir, "raw_cm_bhavcopy")
    deliv = read_table(con, stage_dir, "raw_delivery")
    universe = [r for r in bhav if r["series"] in UNIVERSE_SERIES]

    already = con.execute(
        "SELECT count(*) FROM ohlcv WHERE exchange = ? AND trade_date = ?", [exchange, trade_date]
    ).fetchone()[0]
    if already:
        return PromotionResult("ALREADY_PROMOTED", "market_day", message=str(trade_date))
    later = con.execute("SELECT max(trade_date) FROM ohlcv WHERE exchange = ?", [exchange]).fetchone()[0]
    if later is not None and later > trade_date:
        raise GateFailure("ORDER", f"{trade_date} is older than promoted {later}; replay requires a rebuild")

    # G1 completeness
    prior = [
        c
        for (c,) in con.execute(
            """SELECT count(*) FROM raw_cm_bhavcopy
           WHERE exchange = ? AND trade_date < ? AND series IN ('EQ','BE','BZ')
           GROUP BY trade_date ORDER BY trade_date DESC LIMIT ?""",
            [exchange, trade_date, G1_LOOKBACK_DAYS],
        ).fetchall()
    ]
    if prior:
        median = Decimal(statistics.median(prior))
        if Decimal(len(universe)) < G1_MIN_RATIO * median:
            raise GateFailure("G1", f"{len(universe)} universe rows < {G1_MIN_RATIO} x median {median}")

    _insert_vault_rows(con, stage_dir, ("blobs", "filings", "raw_cm_bhavcopy", "raw_delivery"))

    registry = SecurityRegistry(exchange, _load_intervals(con, exchange))
    filing_id = bhav[0]["filing_id"]
    rows = [BhavRow(**{k: v for k, v in r.items() if k != "filing_id"}) for r in universe]
    obs = registry.observe(rows, filing_id)

    # G2 identifier resolution
    unresolved = len(universe) - len(obs.resolved)
    if universe and Decimal(unresolved) / Decimal(len(universe)) > G2_MAX_UNRESOLVED:
        raise GateFailure("G2", f"{unresolved}/{len(universe)} rows unresolved")

    quarantined: list[str] = []
    for issue in obs.issues:
        quarantined.append(
            _quarantine(
                con,
                stage="IDENTIFIER",
                reason_code=issue.reason_code,
                details={"trade_date": issue.trade_date, **issue.details},
                filing_id=filing_id,
            )
        )
    insert_rows(
        con,
        "entity_master",
        [{"entity_id": s.entity_id, "legal_name": s.legal_name} for s in obs.new_securities],
        or_ignore=True,
    )
    insert_rows(
        con,
        "securities",
        [{"security_id": s.security_id, "entity_id": s.entity_id, "share_class": "COMMON"} for s in obs.new_securities],
        or_ignore=True,
    )
    for iv in obs.closed:
        con.execute(
            "UPDATE security_identifier_history SET valid_to = ? WHERE security_id = ? AND exchange = ? "
            "AND valid_from = ?",
            [iv.valid_to, iv.security_id, iv.exchange, iv.valid_from],
        )
    insert_rows(
        con,
        "security_identifier_history",
        [
            {
                "security_id": iv.security_id,
                "exchange": iv.exchange,
                "fin_instrm_id": iv.fin_instrm_id,
                "symbol": iv.symbol,
                "series": iv.series,
                "isin": iv.isin,
                "valid_from": iv.valid_from,
                "valid_to": iv.valid_to,
                "evidence_filing_id": iv.evidence_filing_id,
            }
            for iv in obs.opened
        ],
    )

    deliv_by_key = {(d["symbol"], d["series"]): d for d in deliv}
    ohlcv_rows = []
    for r in universe:
        sec = obs.resolved.get((r["symbol"], r["series"]))
        if sec is None:
            continue
        d = deliv_by_key.get((r["symbol"], r["series"]))
        ohlcv_rows.append(
            {
                "security_id": sec,
                "exchange": exchange,
                "series": r["series"],
                "trade_date": trade_date,
                "open": r["open"],
                "high": r["high"],
                "low": r["low"],
                "close": r["close"],
                "volume": r["volume"],
                "turnover_inr": r["turnover_inr"],
                "deliv_qty": d["deliv_qty"] if d else None,
                "price_filing_id": filing_id,
                "delivery_filing_id": d["filing_id"] if d else None,
            }
        )
    insert_rows(con, "ohlcv", ohlcv_rows)
    # A bhavcopy is ground truth: it overrides a holiday row (e.g. a special/Muhurat session).
    con.execute(
        "INSERT OR REPLACE INTO trading_calendar VALUES (?, ?, TRUE, 'bhavcopy present')", [exchange, trade_date]
    )

    verify_pending_actions(con, exchange)
    quarantined += _audit_gaps(con, exchange, trade_date, obs)
    return PromotionResult("PROMOTED", "market_day", message=str(trade_date), quarantined=quarantined)


def _prev_closes(con, exchange: str, trade_date: date) -> dict[str, Decimal]:
    return dict(
        con.execute(
            "SELECT security_id, arg_max(close, trade_date) FROM ohlcv WHERE exchange = ? AND trade_date < ? "
            "GROUP BY security_id",
            [exchange, trade_date],
        ).fetchall()
    )


def _audit_gaps(con, exchange: str, trade_date: date, obs) -> list[str]:
    prev = _prev_closes(con, exchange, trade_date)
    opens = dict(
        con.execute(
            "SELECT security_id, open FROM ohlcv WHERE exchange = ? AND trade_date = ?",
            [exchange, trade_date],
        ).fetchall()
    )
    actions = _actions(con, "ex_date = ?", [trade_date])
    by_sec: dict[str, list[CorpAction]] = {}
    for a in actions:
        by_sec.setdefault(a.security_id, []).append(a)
    isin_changed = {e.security_id for e in obs.events if e.kind == "ISIN_CHANGE"}
    out = []
    for sec, open_t in opens.items():
        for finding in audit_day(sec, trade_date, open_t, prev.get(sec), by_sec.get(sec, ()), sec in isin_changed):
            out.append(
                _quarantine(
                    con,
                    stage="GAP",
                    reason_code=finding.reason_code,
                    security_id=sec,
                    details={
                        "trade_date": trade_date,
                        "gap": finding.gap,
                        "prev_close": prev.get(sec),
                        "open": open_t,
                    },
                )
            )
    return out


# ── corporate actions ───────────────────────────────────────────────────


def _actions(con, where: str, params: list[Any]) -> list[CorpAction]:
    rows = fetch_dicts(con, f"SELECT * FROM corp_actions WHERE {where}", params)
    return [
        CorpAction(
            action_id=r["action_id"],
            security_id=r["security_id"],
            action_type=r["action_type"],
            ex_date=r["ex_date"],
            ratio_num=r["ratio_num"],
            ratio_den=r["ratio_den"],
            issue_price=r["issue_price"],
            cash_per_share=r["cash_per_share"],
            status=r["status"],
            price_factor=None if r["price_factor"] is None else Decimal(str(r["price_factor"])),
            eps_factor=None if r["eps_factor"] is None else Decimal(str(r["eps_factor"])),
        )
        for r in rows
    ]


def record_corp_action(
    con,
    action: CorpAction,
    *,
    source_filing_id: str,
    entity_id: str | None = None,
    status: str = "PENDING",
) -> None:
    """Ledger insert (idempotent on action_id). Callers own the transaction."""
    if status not in ("PENDING", "QUARANTINED"):
        raise ValueError("new actions start PENDING (or QUARANTINED when unparseable)")
    insert_rows(
        con,
        "corp_actions",
        [
            {
                "action_id": action.action_id,
                "entity_id": entity_id,
                "security_id": action.security_id,
                "action_type": action.action_type,
                "ex_date": action.ex_date,
                "ratio_num": action.ratio_num,
                "ratio_den": action.ratio_den,
                "issue_price": action.issue_price,
                "cash_per_share": action.cash_per_share,
                "status": status,
                "source_filing_id": source_filing_id,
            }
        ],
        or_ignore=True,
    )


def verify_pending_actions(con, exchange: str) -> int:
    """Verify PENDING actions, grouped per (security, ex_date), once both bars exist.

    Returns the number of actions decided. Earlier GAP quarantines on that date are resolved
    only if the accepted factors now explain the gap (residual re-audit).
    """
    pending = _actions(con, "status = 'PENDING'", [])
    keys = sorted({(a.security_id, a.ex_date) for a in pending})
    decided = 0
    for sec, ex in keys:
        group = _actions(con, "security_id = ? AND ex_date = ? AND status IN ('PENDING', 'QUARANTINED')", [sec, ex])
        bar = con.execute(
            "SELECT open FROM ohlcv WHERE security_id = ? AND exchange = ? AND trade_date = ?", [sec, exchange, ex]
        ).fetchone()
        prev = con.execute(
            "SELECT arg_max(close, trade_date) FROM ohlcv WHERE security_id = ? AND exchange = ? AND trade_date < ?",
            [sec, exchange, ex],
        ).fetchone()
        if bar is None or prev is None or prev[0] is None:
            continue
        results = verify_group(group, bar[0], prev[0])
        for a, v in zip(group, results, strict=True):
            con.execute(
                "UPDATE corp_actions SET status = ?, price_factor = ?, eps_factor = ?, observed_gap = ? "
                "WHERE action_id = ?",
                [v.status, _f(v.price_factor), _f(v.eps_factor), _f(v.observed_gap), a.action_id],
            )
            if v.status == "QUARANTINED" and a.status == "PENDING":
                _quarantine(
                    con,
                    stage="CORP_ACTION",
                    reason_code="VERIFY_FAILED",
                    security_id=sec,
                    details={
                        "action_id": a.action_id,
                        "reason": v.reason,
                        "observed_gap": v.observed_gap,
                        "price_factor": v.price_factor,
                    },
                )
            decided += a.status == "PENDING"
        accepted = [
            a for a in _actions(con, "security_id = ? AND ex_date = ?", [sec, ex]) if a.status in ACCEPTED_STATUSES
        ]
        if accepted and not [
            f for f in audit_day(sec, ex, bar[0], prev[0], accepted, False) if f.reason_code == "UNEXPLAINED_GAP"
        ]:
            con.execute(
                "UPDATE quarantine_queue SET resolved_at = ?, resolution = 'FIXED_BY_RULE', resolution_note = ? "
                "WHERE stage = 'GAP' AND reason_code = 'UNEXPLAINED_GAP' AND security_id = ? AND resolved_at IS NULL "
                "AND CAST(json_extract_string(details, '$.trade_date') AS DATE) = ?",
                [utc_now(), "explained by " + ", ".join(f"{a.action_type} {a.action_id}" for a in accepted), sec, ex],
            )
        if any(a.action_type in ("SPLIT", "CONSOLIDATION") for a in accepted):
            con.execute(
                "UPDATE quarantine_queue SET resolved_at = ?, resolution = 'FIXED_BY_RULE', resolution_note = ? "
                "WHERE stage = 'GAP' AND reason_code = 'ISIN_CHANGE_WITHOUT_ACTION' AND security_id = ? "
                "AND resolved_at IS NULL AND CAST(json_extract_string(details, '$.trade_date') AS DATE) = ?",
                [utc_now(), "explained by recorded split/consolidation", sec, ex],
            )
    return decided


def resolve_security_by_isin(con, exchange: str, isin: str, on_date: date) -> list[str]:
    """Securities holding `isin` on `on_date`; falls back to any interval with that ISIN."""
    rows = con.execute(
        "SELECT DISTINCT security_id FROM security_identifier_history WHERE exchange = ? AND isin = ? "
        "AND valid_from <= ? AND (valid_to IS NULL OR valid_to > ?)",
        [exchange, isin, on_date, on_date],
    ).fetchall()
    if not rows:
        rows = con.execute(
            "SELECT DISTINCT security_id FROM security_identifier_history WHERE exchange = ? AND isin = ?",
            [exchange, isin],
        ).fetchall()
    return [r[0] for r in rows]


def isin_issuer_code(isin: str) -> str:
    """Characters 4-7 of an Indian ISIN identify the issuer; splits keep them [CA7]."""
    return isin[3:7]


def resolve_corp_action_security(con, exchange: str, isin: str, symbol: str, on_date: date) -> tuple[list[str], str]:
    """(candidates, method). The API ISIN is often stale [CA7], so after the ISIN, try the symbol
    but only accept holders whose ISIN has the same issuer code (PREMIERPOL changed issuer code)."""
    secs = resolve_security_by_isin(con, exchange, isin, on_date)
    if secs:
        return secs, "ISIN"
    rows = (
        con.execute(
            "SELECT DISTINCT security_id, isin FROM security_identifier_history WHERE exchange = ? AND symbol = ? "
            "AND valid_from <= ? AND (valid_to IS NULL OR valid_to > ?)",
            [exchange, symbol, on_date, on_date],
        ).fetchall()
        or con.execute(
            "SELECT DISTINCT security_id, isin FROM security_identifier_history WHERE exchange = ? AND symbol = ?",
            [exchange, symbol],
        ).fetchall()
    )
    same_issuer = sorted({sec for sec, held in rows if isin_issuer_code(held) == isin_issuer_code(isin)})
    if same_issuer:
        return same_issuer, "SYMBOL_SAME_ISSUER"
    return [], "STALE_ISIN_OTHER_ISSUER" if rows else "UNKNOWN_ISIN"


def _promote_corp_actions(con, stage_dir: Path, manifest: dict[str, Any]) -> PromotionResult:
    """Record staged actions; the API ISIN is the pre-action ISIN, so resolve on ex_date - 1 [CA2]."""
    from datetime import timedelta

    exchange = manifest["exchange"]
    _insert_vault_rows(con, stage_dir, ("blobs", "filings"))
    quarantined: list[str] = []
    recorded = 0
    for r in read_table(con, stage_dir, "stg_corp_actions"):
        if r["parse_status"] == "IGNORED":
            continue
        secs, method = resolve_corp_action_security(
            con, exchange, r["isin"], r["symbol"], r["ex_date"] - timedelta(days=1)
        )
        if len(secs) != 1:
            quarantined.append(
                _quarantine(
                    con,
                    stage="CORP_ACTION",
                    reason_code=method if not secs else "AMBIGUOUS_SECURITY",
                    filing_id=r["filing_id"],
                    details={
                        "isin": r["isin"],
                        "symbol": r["symbol"],
                        "ex_date": r["ex_date"],
                        "subject": r["subject"],
                    },
                )
            )
            continue
        sec = secs[0]
        entity = con.execute("SELECT entity_id FROM securities WHERE security_id = ?", [sec]).fetchone()[0]
        action = CorpAction(
            action_id=stable_id("ca", exchange, r["isin"], r["ex_date"], r["subject"], r["component"]),
            security_id=sec,
            action_type=r["action_type"],
            ex_date=r["ex_date"],
            ratio_num=r["ratio_num"],
            ratio_den=r["ratio_den"],
            issue_price=r["issue_price"],
            cash_per_share=r["cash_per_share"],
        )
        unparsed = r["parse_status"] == "UNPARSED"
        record_corp_action(
            con,
            action,
            source_filing_id=r["filing_id"],
            entity_id=entity,
            status="QUARANTINED" if unparsed else "PENDING",
        )
        if unparsed:
            quarantined.append(
                _quarantine(
                    con,
                    stage="CORP_ACTION",
                    reason_code="UNPARSED_PURPOSE",
                    security_id=sec,
                    entity_id=entity,
                    filing_id=r["filing_id"],
                    details={"subject": r["subject"], "reason": r["parse_reason"], "ex_date": r["ex_date"]},
                )
            )
        recorded += 1
    verify_pending_actions(con, exchange)
    return PromotionResult("PROMOTED", "corp_actions", message=f"{recorded} actions", quarantined=quarantined)


def _f(x: Decimal | None) -> float | None:
    return None if x is None else float(x)


def total_return(con, security_id: str, exchange: str = "NSE") -> list[tuple[date, Decimal]]:
    """Total-return index (base 100) including accepted cash dividends; see financials.returns."""
    from financials.returns import total_return_index

    return total_return_index(con, security_id, _actions(con, "security_id = ?", [security_id]), exchange)


def adjusted_closes(con, security_id: str, exchange: str = "NSE") -> list[tuple[date, Decimal]]:
    """Back-adjusted closes; withheld from the first unresolved GAP quarantine onwards."""
    bars = con.execute(
        "SELECT trade_date, close FROM ohlcv WHERE security_id = ? AND exchange = ?", [security_id, exchange]
    ).fetchall()
    frozen = con.execute(
        "SELECT min(CAST(json_extract_string(details, '$.trade_date') AS DATE)) FROM quarantine_queue "
        "WHERE stage = 'GAP' AND security_id = ? AND resolved_at IS NULL",
        [security_id],
    ).fetchone()[0]
    actions = [a for a in _actions(con, "security_id = ?", [security_id]) if a.status in ACCEPTED_STATUSES]
    return adjust_closes(bars, actions, frozen_from=frozen)


# ── results XBRL ────────────────────────────────────────────────────────


def _visible_from(
    con,
    exchange: str,
    broadcast_ts: datetime | None,
    board_end: datetime | None,
    board_end_ist_date: date | None,
) -> tuple[datetime | None, str | None]:
    if broadcast_ts is not None:
        return broadcast_ts, "BROADCAST"
    if board_end is None or board_end_ist_date is None:
        return None, None
    from financials.calendar import next_trading_day

    nxt = next_trading_day(con, exchange, board_end_ist_date)
    if nxt is None:
        return None, None
    return ist_to_utc(nxt, time(0, 0)), "BOARD_MEETING_RULE"


def _promote_results_xbrl(con, stage_dir: Path, manifest: dict[str, Any]) -> PromotionResult:
    _insert_vault_rows(con, stage_dir, ("blobs", "filings", "raw_xbrl_facts"))
    filing = read_table(con, stage_dir, "filings")[0]
    fid = filing["filing_id"]
    issues = read_table(con, stage_dir, "stg_issues")
    if issues:
        qs = [
            _quarantine(
                con,
                stage=i["stage"],
                reason_code=i["reason_code"],
                filing_id=fid,
                details=json.loads(i["details"]),
            )
            for i in issues
        ]
        return PromotionResult("QUARANTINED", "results_xbrl", message=fid, quarantined=qs)

    meta = read_table(con, stage_dir, "stg_xbrl_filing")[0]
    if con.execute(
        "SELECT count(*) FROM filing_meta WHERE filing_id = ? AND parser_version = ?",
        [fid, meta["parser_version"]],
    ).fetchone()[0]:
        return PromotionResult("ALREADY_PROMOTED", "results_xbrl", message=fid)

    ent = con.execute(
        "SELECT DISTINCT s.entity_id FROM security_identifier_history h "
        "JOIN securities s USING (security_id) WHERE h.exchange = ? AND h.isin = ?",
        [filing["exchange"], meta["stated_isin"]],
    ).fetchall()
    if len(ent) != 1:
        q = _quarantine(
            con,
            stage="IDENTITY",
            reason_code="UNKNOWN_ISIN" if not ent else "AMBIGUOUS_ISIN",
            filing_id=fid,
            details={"isin": meta["stated_isin"], "symbol": meta["stated_symbol"]},
        )
        return PromotionResult("QUARANTINED", "results_xbrl", message=fid, quarantined=[q])
    entity_id = ent[0][0]

    board_end = meta["board_meeting_end_ts"]
    board_ist_date = utc_to_ist_date(board_end) if board_end is not None else None
    visible, source = _visible_from(con, filing["exchange"], filing["broadcast_ts"], board_end, board_ist_date)
    if visible is None:
        q = _quarantine(
            con,
            stage="PERIOD",
            reason_code="NO_VISIBILITY",
            filing_id=fid,
            entity_id=entity_id,
            details={"board_meeting_end_ts": board_end},
        )
        return PromotionResult("QUARANTINED", "results_xbrl", message=fid, quarantined=[q])

    insert_rows(
        con,
        "filing_meta",
        [
            {
                "filing_id": fid,
                "parser_version": meta["parser_version"],
                "entity_id": entity_id,
                "accounting_profile": meta["accounting_profile"],
                "taxonomy_ns": meta["taxonomy_ns"],
                "scope": meta["scope"],
                "level_of_rounding": meta["level_of_rounding"],
                "fy_start": meta["fy_start"],
                "fy_end": meta["fy_end"],
                "period_end": meta["period_end"],
                "reporting_quarter": meta["reporting_quarter"],
                "audited": meta["audited"],
                "board_meeting_end_ts": board_end,
                "visible_from_ts": visible,
                "visible_from_source": source,
                "interest_paid_cfo_class": meta["interest_paid_cfo_class"],
                "interest_recd_cfo_class": meta["interest_recd_cfo_class"],
            }
        ],
    )
    facts = read_table(con, stage_dir, "stg_xbrl_facts")
    insert_rows(con, "fact_observations", [{**f, "entity_id": entity_id, "visible_from_ts": visible} for f in facts])
    q = cross_check_shares(con, entity_id, meta["period_end"])
    return PromotionResult("PROMOTED", "results_xbrl", message=fid, quarantined=[q] if q else [])


def pit_fact(
    con, entity_id: str, scope: str, canonical_tag: str, period_start: date, period_end: date, as_of: datetime
) -> Decimal | None:
    """Point-in-time read: latest-visible value as known at `as_of` (architecture §6.3)."""
    row = con.execute(
        """SELECT coalesce(value_inr, value_other) FROM fact_observations
           WHERE entity_id = ? AND scope = ? AND canonical_tag = ? AND period_start = ? AND period_end = ?
             AND visible_from_ts <= ?
           ORDER BY visible_from_ts DESC, parser_version DESC LIMIT 1""",
        [entity_id, scope, canonical_tag, period_start, period_end, as_of],
    ).fetchone()
    return None if row is None else row[0]


# ── calendar & index membership ────────────────────────────────────────────


def _promote_holidays(con, stage_dir: Path, manifest: dict[str, Any]) -> PromotionResult:
    _insert_vault_rows(con, stage_dir, ("blobs", "filings"))
    rows = read_table(con, stage_dir, "stg_holidays")
    for r in rows:
        # Never overwrite a day a bhavcopy proved to be a trading day.
        con.execute(
            "INSERT OR IGNORE INTO trading_calendar VALUES (?, ?, FALSE, ?)",
            [r["exchange"], r["cal_date"], "holiday: " + r["description"]],
        )
    years = sorted({r["cal_date"].year for r in rows})
    for y in years:
        con.execute(
            "INSERT OR REPLACE INTO calendar_coverage VALUES (?, ?, ?)", [manifest["exchange"], y, rows[0]["filing_id"]]
        )
    return PromotionResult("PROMOTED", "holidays", message=f"{len(rows)} holidays, years {years}")


def _promote_index_snapshot(con, stage_dir: Path, manifest: dict[str, Any]) -> PromotionResult:
    index_name = manifest["index_name"]
    snap = date.fromisoformat(manifest["snapshot_date"])
    latest = con.execute(
        "SELECT max(snapshot_date) FROM raw_index_snapshot WHERE index_name = ?", [index_name]
    ).fetchone()[0]
    if latest is not None and snap < latest:
        raise GateFailure("ORDER", f"{index_name} snapshot {snap} older than {latest}")
    _insert_vault_rows(con, stage_dir, ("blobs", "filings", "raw_index_snapshot"))
    rows = [r for r in read_table(con, stage_dir, "raw_index_snapshot")]
    members: set[str] = set()
    quarantined = []
    for r in rows:
        if not r["isin"].startswith("IN"):  # e.g. DUMMYHEG / DUM545A01024 placeholder [IDX2]
            quarantined.append(
                _quarantine(
                    con,
                    stage="INDEX",
                    reason_code="PLACEHOLDER_ISIN",
                    filing_id=r["filing_id"],
                    details={"index": index_name, "isin": r["isin"], "symbol": r["symbol"], "snapshot": snap},
                )
            )
            continue
        secs, method = resolve_corp_action_security(con, "NSE", r["isin"], r["symbol"], snap)
        if len(secs) != 1:
            quarantined.append(
                _quarantine(
                    con,
                    stage="INDEX",
                    reason_code=method if not secs else "AMBIGUOUS_SECURITY",
                    filing_id=r["filing_id"],
                    details={"index": index_name, "isin": r["isin"], "symbol": r["symbol"], "snapshot": snap},
                )
            )
            continue
        members.add(secs[0])
    real = [r for r in rows if r["isin"].startswith("IN")]
    unresolved = len(real) - len(members)
    if real and unresolved / len(real) > float(G2_MAX_UNRESOLVED):
        raise GateFailure("G2", f"{unresolved}/{len(real)} constituents unresolved")
    open_now = {
        sec
        for (sec,) in con.execute(
            "SELECT security_id FROM index_constituents_history WHERE index_name = ? AND valid_to IS NULL",
            [index_name],
        ).fetchall()
    }
    for sec in open_now - members:
        con.execute(
            "UPDATE index_constituents_history SET valid_to = ? WHERE index_name = ? AND security_id = ? "
            "AND valid_to IS NULL",
            [snap, index_name, sec],
        )
    insert_rows(
        con,
        "index_constituents_history",
        [
            {"index_name": index_name, "security_id": sec, "valid_from": snap, "valid_to": None, "source": "SNAPSHOT"}
            for sec in sorted(members - open_now)
        ],
    )
    return PromotionResult(
        "PROMOTED",
        "index_snapshot",
        message=f"{index_name} {snap}: +{len(members - open_now)} -{len(open_now - members)}",
        quarantined=quarantined,
    )


class SurvivorshipBiasError(LookupError):
    """Raised when a point-in-time universe is requested before membership history begins [L1]."""


def index_members(con, index_name: str, as_of: date, *, allow_survivorship_bias: bool = False) -> list[str]:
    first = con.execute(
        "SELECT min(valid_from) FROM index_constituents_history WHERE index_name = ?", [index_name]
    ).fetchone()[0]
    if first is None:
        raise SurvivorshipBiasError(f"no membership history for {index_name}")
    if as_of < first:
        if not allow_survivorship_bias:
            raise SurvivorshipBiasError(f"{index_name} history starts {first}; {as_of} would use later members")
        as_of = first
    rows = con.execute(
        "SELECT security_id FROM index_constituents_history WHERE index_name = ? AND valid_from <= ? "
        "AND (valid_to IS NULL OR valid_to > ?) ORDER BY security_id",
        [index_name, as_of, as_of],
    ).fetchall()
    return [r[0] for r in rows]


# ── shareholding (Reg. 31) ─────────────────────────────────────────────────

SHARE_CROSS_CHECK_TOLERANCE = Decimal("0.005")  # 0.5% relative (owner decision)


def cross_check_shares(con, entity_id: str, as_of: date) -> str | None:
    """Compare Reg. 31 total shares with results-derived paid-up / face value for the same date.

    Returns a quarantine id on disagreement, else None. Skipped when partly-paid shares exist
    (paid-up / face value is then not a share count [X18]) or either side is missing.
    """
    shp = con.execute(
        "SELECT o.shares, m.has_partly_paid, o.filing_id FROM shareholding_observations o "
        "JOIN shareholding_meta m USING (filing_id, parser_version) "
        "WHERE o.entity_id = ? AND o.as_of_date = ? AND o.category = 'TOTAL' "
        "ORDER BY o.visible_from_ts DESC, o.parser_version DESC LIMIT 1",
        [entity_id, as_of],
    ).fetchone()
    res = con.execute(
        "SELECT value_other, filing_id FROM fact_observations WHERE entity_id = ? AND canonical_tag = "
        "'shares_from_paid_up' AND period_end = ? ORDER BY visible_from_ts DESC, parser_version DESC LIMIT 1",
        [entity_id, as_of],
    ).fetchone()
    if shp is None or res is None or shp[1]:
        return None
    shp_total, derived = Decimal(shp[0]), Decimal(res[0])
    diff = abs(shp_total - derived) / shp_total
    if diff <= SHARE_CROSS_CHECK_TOLERANCE:
        return None
    return _quarantine(
        con,
        stage="SHARES",
        reason_code="CROSS_CHECK_FAILED",
        entity_id=entity_id,
        details={
            "as_of": as_of,
            "reg31_total": shp_total,
            "paid_up_over_face_value": derived,
            "relative_diff": diff,
            "shp_filing": shp[2],
            "results_filing": res[1],
        },
    )


def _promote_shareholding(con, stage_dir: Path, manifest: dict[str, Any]) -> PromotionResult:
    _insert_vault_rows(con, stage_dir, ("blobs", "filings"))
    filing = read_table(con, stage_dir, "filings")[0]
    fid = filing["filing_id"]
    issues = read_table(con, stage_dir, "stg_issues")
    if issues:
        qs = [
            _quarantine(
                con, stage=i["stage"], reason_code=i["reason_code"], filing_id=fid, details=json.loads(i["details"])
            )
            for i in issues
        ]
        return PromotionResult("QUARANTINED", "shareholding", message=fid, quarantined=qs)
    meta = read_table(con, stage_dir, "stg_shp_meta")[0]
    if con.execute(
        "SELECT count(*) FROM shareholding_meta WHERE filing_id = ? AND parser_version = ?",
        [fid, meta["parser_version"]],
    ).fetchone()[0]:
        return PromotionResult("ALREADY_PROMOTED", "shareholding", message=fid)
    secs = resolve_security_by_isin(con, filing["exchange"], meta["stated_isin"], meta["as_of_date"])
    entities = sorted(
        {con.execute("SELECT entity_id FROM securities WHERE security_id = ?", [s_]).fetchone()[0] for s_ in secs}
    )
    if len(entities) != 1:
        q = _quarantine(
            con,
            stage="IDENTITY",
            reason_code="UNKNOWN_ISIN" if not entities else "AMBIGUOUS_ISIN",
            filing_id=fid,
            details={"isin": meta["stated_isin"], "symbol": meta["stated_symbol"]},
        )
        return PromotionResult("QUARANTINED", "shareholding", message=fid, quarantined=[q])
    entity_id = entities[0]
    visible = filing["broadcast_ts"]
    if visible is None:  # no board-meeting fallback exists for Reg. 31
        q = _quarantine(
            con,
            stage="PERIOD",
            reason_code="NO_VISIBILITY",
            filing_id=fid,
            entity_id=entity_id,
            details={"as_of": meta["as_of_date"]},
        )
        return PromotionResult("QUARANTINED", "shareholding", message=fid, quarantined=[q])
    insert_rows(
        con,
        "shareholding_meta",
        [
            {
                "filing_id": fid,
                "parser_version": meta["parser_version"],
                "entity_id": entity_id,
                "as_of_date": meta["as_of_date"],
                "has_partly_paid": meta["has_partly_paid"],
                "promoter_pledge_flag": meta["promoter_pledge_flag"],
                "promoter_pledged_shares": meta["promoter_pledged_shares"],
                "visible_from_ts": visible,
            }
        ],
    )
    insert_rows(
        con,
        "shareholding_observations",
        [
            {
                **{
                    k: c[k]
                    for k in ("filing_id", "category", "shares", "holders", "pct", "demat_shares", "voting_rights")
                },
                "parser_version": meta["parser_version"],
                "entity_id": entity_id,
                "as_of_date": meta["as_of_date"],
                "visible_from_ts": visible,
            }
            for c in read_table(con, stage_dir, "stg_shp_categories")
        ],
    )
    q = cross_check_shares(con, entity_id, meta["as_of_date"])
    return PromotionResult("PROMOTED", "shareholding", message=fid, quarantined=[q] if q else [])


def _promote_raw_only(con, stage_dir: Path, manifest: dict[str, Any]) -> PromotionResult:
    _insert_vault_rows(con, stage_dir, ("blobs", "filings"))
    return PromotionResult("PROMOTED", "raw_only", message=read_table(con, stage_dir, "filings")[0]["category"])
