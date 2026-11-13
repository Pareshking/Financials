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

from financials.corp_actions import ACCEPTED_STATUSES, CorpAction, adjust_closes, audit_day, verify_action
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
    handler = {"market_day": _promote_market_day, "results_xbrl": _promote_results_xbrl}.get(job)
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
        [
            {"security_id": s.security_id, "entity_id": s.entity_id, "share_class": "COMMON"}
            for s in obs.new_securities
        ],
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
    insert_rows(
        con,
        "trading_calendar",
        [{"exchange": exchange, "cal_date": trade_date, "is_trading": True, "note": "bhavcopy present"}],
        or_ignore=True,
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
        for finding in audit_day(
            sec, trade_date, open_t, prev.get(sec), by_sec.get(sec, ()), sec in isin_changed
        ):
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
    con, action: CorpAction, *, source_filing_id: str, entity_id: str | None = None
) -> None:
    """Ledger insert. Callers own the transaction; status always starts PENDING."""
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
                "status": "PENDING",
                "source_filing_id": source_filing_id,
            }
        ],
    )


def verify_pending_actions(con, exchange: str) -> int:
    """Verify every PENDING action whose ex-date bar and prior bar exist."""
    n = 0
    for a in _actions(con, "status = 'PENDING'", []):
        bar = con.execute(
            "SELECT open FROM ohlcv WHERE security_id = ? AND exchange = ? AND trade_date = ?",
            [a.security_id, exchange, a.ex_date],
        ).fetchone()
        prev = con.execute(
            "SELECT arg_max(close, trade_date) FROM ohlcv WHERE security_id = ? AND exchange = ? "
            "AND trade_date < ?",
            [a.security_id, exchange, a.ex_date],
        ).fetchone()
        if bar is None or prev is None or prev[0] is None:
            continue
        v = verify_action(a, bar[0], prev[0])
        con.execute(
            "UPDATE corp_actions SET status = ?, price_factor = ?, eps_factor = ?, observed_gap = ? "
            "WHERE action_id = ?",
            [v.status, _f(v.price_factor), _f(v.eps_factor), _f(v.observed_gap), a.action_id],
        )
        if v.status in ACCEPTED_STATUSES:
            # The missing explanation for an earlier gap has arrived: resolve it, keep the record.
            con.execute(
                "UPDATE quarantine_queue SET resolved_at = ?, resolution = 'FIXED_BY_RULE', "
                "resolution_note = ? WHERE stage = 'GAP' AND security_id = ? AND resolved_at IS NULL "
                "AND CAST(json_extract_string(details, '$.trade_date') AS DATE) = ?",
                [utc_now(), f"explained by {a.action_type} {a.action_id}", a.security_id, a.ex_date],
            )
        if v.status == "QUARANTINED":
            _quarantine(
                con,
                stage="CORP_ACTION",
                reason_code="VERIFY_FAILED",
                security_id=a.security_id,
                details={
                    "action_id": a.action_id,
                    "reason": v.reason,
                    "observed_gap": v.observed_gap,
                    "price_factor": v.price_factor,
                },
            )
        n += 1
    return n


def _f(x: Decimal | None) -> float | None:
    return None if x is None else float(x)


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
    nxt = con.execute(
        "SELECT min(cal_date) FROM trading_calendar WHERE exchange = ? AND is_trading AND cal_date > ?",
        [exchange, board_end_ist_date],
    ).fetchone()[0]
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
    visible, source = _visible_from(
        con, filing["exchange"], filing["broadcast_ts"], board_end, board_ist_date
    )
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
    insert_rows(
        con, "fact_observations", [{**f, "entity_id": entity_id, "visible_from_ts": visible} for f in facts]
    )
    return PromotionResult("PROMOTED", "results_xbrl", message=fid)


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
