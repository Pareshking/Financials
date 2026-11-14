"""The single writer. Reads staged batches, runs gates, commits atomically to market.duckdb.

Gates (docs/architecture.md §12): G1 completeness, G2 identifier resolution, ORDER and the CAL3 no-session
inference for market days; G3 accounting identities are enforced by the parsers and surface as staged issues;
G4 (null spike) and G5 (atomic universe) run in feature materialisation (financials.features.materialize).
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

from financials import PARSER_VERSION
from financials.corp_actions import ACCEPTED_STATUSES, CorpAction, adjust_closes, audit_day, verify_group
from financials.db import fetch_dicts, insert_rows
from financials.identity import UNIVERSE_SERIES, Interval, SecurityRegistry
from financials.ids import stable_id
from financials.parsers.udiff import BhavRow
from financials.scope import MIN_PERIOD_END_DATE, MIN_TRADE_DATE, financials_in_scope, market_in_scope
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
        "reg30_event": _promote_reg30_event,
        "raw_only": _promote_raw_only,
        "kpis": _promote_kpis,
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


def _out_of_scope(con, stage_dir: Path, job: str, reason: str) -> PromotionResult:
    """v1 scope cutoff [C9]: keep the evidence (blob + filing), parse nothing into canonical tables."""
    _insert_vault_rows(con, stage_dir, ("blobs", "filings"))
    return PromotionResult("OUT_OF_SCOPE", job, message=reason)


def _insert_vault_rows(con, stage_dir: Path, tables: Iterable[str]) -> None:
    """Load staged tables straight from Parquet; identical rows from a replay are ignored."""
    for t in tables:
        path = Path(stage_dir) / f"{t}.parquet"
        if path.exists():
            con.execute(f"INSERT OR IGNORE INTO {t} BY NAME SELECT * FROM read_parquet(?)", [path.as_posix()])


def _quarantine_row(
    *,
    stage: str,
    reason_code: str,
    details: dict[str, Any],
    entity_id: str | None = None,
    security_id: str | None = None,
    filing_id: str | None = None,
) -> dict[str, Any]:
    body = json.dumps(details, default=str, sort_keys=True)
    return {
        "quarantine_id": stable_id("q", stage, reason_code, entity_id, security_id, filing_id, body),
        "stage": stage,
        "reason_code": reason_code,
        "entity_id": entity_id,
        "security_id": security_id,
        "filing_id": filing_id,
        "details": body,
        "created_at": utc_now(),
    }


REBUILD_SUPERSEDED = "SUPERSEDED_BY_REBUILD"
REPROCESSING = "REPROCESSING"  # set by `quarantine reprocess` while the batch is promoted again


def _quarantine_many(con, rows: list[dict[str, Any]]) -> list[str]:
    """One bulk insert for many findings (a gap-heavy day can raise thousands). IDs are deterministic, so a
    replayed finding hits its old row: kept as is (a human decision stands), except a row that rebuild-market
    superseded or that `quarantine reprocess` is retrying, which is reopened because the problem is still there."""
    insert_rows(con, "quarantine_queue", rows, on_conflict=(
        "ON CONFLICT (quarantine_id) DO UPDATE SET resolved_at = NULL, resolution = NULL, resolution_note = NULL "
        f"WHERE quarantine_queue.resolution IN ('{REBUILD_SUPERSEDED}', '{REPROCESSING}')"))  # fmt: skip
    return [r["quarantine_id"] for r in rows]


def _quarantine(con, **kwargs: Any) -> str:
    return _quarantine_many(con, [_quarantine_row(**kwargs)])[0]


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
    if not market_in_scope(trade_date):
        return _out_of_scope(con, stage_dir, "market_day", f"trade_date {trade_date} < {MIN_TRADE_DATE}")
    bhav = read_table(con, stage_dir, "raw_cm_bhavcopy")
    deliv = read_table(con, stage_dir, "raw_delivery")
    universe = [r for r in bhav if r["series"] in UNIVERSE_SERIES]

    already = con.execute(
        "SELECT count(*) FROM ohlcv WHERE exchange = ? AND trade_date = ?", [exchange, trade_date]
    ).fetchone()[0]
    if already:
        if deliv:
            return _attach_delivery(con, stage_dir, exchange, trade_date)
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
        "INSERT OR REPLACE INTO trading_calendar (exchange, cal_date, is_trading, note, source) "
        "VALUES (?, ?, TRUE, 'bhavcopy present', 'BHAVCOPY')",
        [exchange, trade_date],
    )

    quarantined += _stage_issue_quarantines(con, stage_dir)
    quarantined += _infer_non_sessions(con, exchange, trade_date, filing_id)
    verify_pending_actions(con, exchange)
    quarantined += _audit_gaps(con, exchange, trade_date, obs)
    resolve_market_moves(con)
    resolve_isin_changes(con, exchange)
    closed = close_inactive_securities(con, exchange, trade_date)
    message = str(trade_date) + (f", {closed} inactive securities closed" if closed else "")
    return PromotionResult("PROMOTED", "market_day", message=message, quarantined=quarantined)


# CAL3: a session's PrvsClsgPric equals the previous session's close for (nearly) every security, across weekends
# and holidays alike (2025-10-17 -> 20, 10-01 -> 03, 10-21 -> 23: 100% of ~2,450). Skipping a real session drops
# the match to ~1-2% (10-20 -> 23). So when the match against the last promoted day is >= 99%, no session took
# place on the dates in between; otherwise a session is missing from the database.
CAL3_MIN_MATCH = Decimal("0.99")
CAL3_MIN_COMMON = 100


def _infer_non_sessions(con, exchange: str, trade_date: date, filing_id: str) -> list[str]:
    from datetime import timedelta

    prev = con.execute(
        "SELECT max(trade_date) FROM ohlcv WHERE exchange = ? AND trade_date < ?", [exchange, trade_date]
    ).fetchone()[0]
    if prev is None or (trade_date - prev).days <= 1:
        return []
    common, equal = con.execute(
        """SELECT count(*), count(*) FILTER (WHERE r.prev_close_reported = o.close)
           FROM raw_cm_bhavcopy r
           JOIN security_identifier_history h
             ON h.exchange = r.exchange AND h.symbol = r.symbol AND h.series = r.series
            AND h.valid_from <= r.trade_date AND (h.valid_to IS NULL OR h.valid_to > r.trade_date)
           JOIN ohlcv o ON o.security_id = h.security_id AND o.exchange = r.exchange AND o.trade_date = ?
           WHERE r.filing_id = ? AND r.trade_date = ? AND r.prev_close_reported IS NOT NULL""",
        [prev, filing_id, trade_date],
    ).fetchone()
    ratio = Decimal(equal) / Decimal(common) if common else Decimal(0)
    if common >= CAL3_MIN_COMMON and ratio >= CAL3_MIN_MATCH:
        gap = [prev + timedelta(days=i) for i in range(1, (trade_date - prev).days)]
        insert_rows(con, "trading_calendar", [
            {"exchange": exchange, "cal_date": d, "is_trading": False, "source": "INFERRED_PREV_CLOSE",
             "note": f"no session: {trade_date} PrvsClsgPric = {prev} close ({equal}/{common})"} for d in gap
        ], or_ignore=True)  # fmt: skip
        return []
    return [
        _quarantine(
            con,
            stage="CALENDAR",
            reason_code="MISSING_SESSION",
            filing_id=filing_id,
            details={
                "trade_date": trade_date,
                "previous_promoted": prev,
                "matched": equal,
                "common": common,
                "hint": "fetch the missing day(s), then rebuild-market --from",
            },
        )
    ]


# CA12 (live backfill 2024-10 .. 2026-11): of 2,227 open-gap findings, 2,153 were equity shares and 1,997 of them
# moved <= 20% with no corporate-action record of any kind within 7 days in a feed that covers the date. A missing
# share-count event is what the auditor exists to catch, and it would sit in that feed; so such a gap is a market move.
MARKET_MOVE_MAX_GAP = Decimal("0.20")
MARKET_MOVE_WINDOW_DAYS = 7


def resolve_market_moves(con) -> int:
    """Named rule CA12: close UNEXPLAINED_GAP findings of equity shares (INE ISIN) with |gap| <= 20% when the
    corporate-action feed covers the date (+/- 7 days) and holds no record for the security in that window.
    ETF units (INF), larger gaps and gaps near any action stay for a human. One batched statement."""
    rows = con.execute(
        f"""WITH cov AS (
              SELECT CAST(strptime(regexp_extract(source_url, 'from_date=([0-9-]+)', 1), '%d-%m-%Y') AS DATE) f,
                     CAST(strptime(regexp_extract(source_url, 'to_date=([0-9-]+)', 1), '%d-%m-%Y') AS DATE) t
              FROM filings WHERE category = 'CORP_ACTIONS' AND source_url LIKE '%from_date=%'),
            g AS (
              SELECT q.quarantine_id, q.security_id, CAST(json_extract_string(q.details, '$.trade_date') AS DATE) d,
                     abs(CAST(json_extract_string(q.details, '$.gap') AS DOUBLE)) a
              FROM quarantine_queue q
              WHERE q.stage = 'GAP' AND q.reason_code = 'UNEXPLAINED_GAP' AND q.resolved_at IS NULL)
           UPDATE quarantine_queue SET resolved_at = ?, resolution = 'FIXED_BY_RULE',
                  resolution_note = 'market move: equity, <= 20%, no action within 7 days in a covering feed [CA12]'
           WHERE quarantine_id IN (
             SELECT g.quarantine_id FROM g
             JOIN security_identifier_history h ON h.security_id = g.security_id AND h.valid_from <= g.d
                  AND (h.valid_to IS NULL OR h.valid_to > g.d) AND h.isin LIKE 'INE%'
             WHERE g.a <= {float(MARKET_MOVE_MAX_GAP)}
               AND EXISTS (SELECT 1 FROM cov WHERE g.d - INTERVAL {MARKET_MOVE_WINDOW_DAYS} DAY BETWEEN cov.f AND cov.t)
               AND EXISTS (SELECT 1 FROM cov WHERE g.d + INTERVAL {MARKET_MOVE_WINDOW_DAYS} DAY BETWEEN cov.f AND cov.t)
               AND NOT EXISTS (SELECT 1 FROM corp_actions ca WHERE ca.security_id = g.security_id
                               AND ca.ex_date BETWEEN g.d - INTERVAL {MARKET_MOVE_WINDOW_DAYS} DAY
                                                  AND g.d + INTERVAL {MARKET_MOVE_WINDOW_DAYS} DAY))
           RETURNING 1""",
        [utc_now()],
    ).fetchall()
    return len(rows)


# CA13 (live backfill): 15 ETF units (INF ISINs) changed ISIN with an opening price at ~1/10 or ~1/100 of the previous
# close (GROWWGOLD 2026-02-06: -0.903; LICMFGOLD 2026-03-06: -0.99): unit splits, absent from the equities
# corporate-action feed. And a re-ISIN without price effect (HDFCLIQUID 2025-02-28: gap 0.0) has nothing to adjust.
ETF_SPLIT_DIVISORS = (2, 5, 10, 20, 50, 100)
ETF_SPLIT_TOLERANCE = Decimal("0.10")  # = VERIFY_TOLERANCE: units move on the split day too (NV20 0.106)


def resolve_isin_changes(con, exchange: str = "NSE") -> int:
    """Named rule CA13 for open ISIN_CHANGE_WITHOUT_ACTION findings: (1) an ETF unit (INF ISIN) whose open / previous
    close is within 10% of 1/k for k in ETF_SPLIT_DIVISORS gets a SPLIT 1:k recorded (verified like any action, which
    also closes its gap findings); (2) a change with |gap| below the no-effect band closes (nothing to adjust)."""
    from financials.corp_actions import UNOBSERVABLE_BAND

    rows = con.execute(
        """SELECT q.quarantine_id, q.security_id, CAST(json_extract_string(q.details, '$.trade_date') AS DATE) d,
                  CAST(json_extract_string(q.details, '$.gap') AS DOUBLE) gap, h.isin, o.price_filing_id
           FROM quarantine_queue q
           JOIN security_identifier_history h ON h.security_id = q.security_id
                AND h.valid_from <= CAST(json_extract_string(q.details, '$.trade_date') AS DATE)
                AND (h.valid_to IS NULL OR h.valid_to > CAST(json_extract_string(q.details, '$.trade_date') AS DATE))
           JOIN ohlcv o ON o.security_id = q.security_id
                AND o.trade_date = CAST(json_extract_string(q.details, '$.trade_date') AS DATE)
           WHERE q.reason_code = 'ISIN_CHANGE_WITHOUT_ACTION' AND q.resolved_at IS NULL"""
    ).fetchall()
    done = 0
    for qid, sec, d, gap, isin, filing in rows:
        if gap is None:
            continue
        ratio = Decimal(str(1 + gap))
        k = next((k for k in ETF_SPLIT_DIVISORS if abs(ratio * k - 1) <= ETF_SPLIT_TOLERANCE), None)
        if isin.startswith("INF") and k is not None:
            record_corp_action(con, CorpAction(stable_id("ca", "RULE_CA13", sec, d, k), sec, "SPLIT", d, Decimal(1),
                                               Decimal(k)), source_filing_id=filing)  # fmt: skip
            done += 1
        elif abs(Decimal(str(gap))) < UNOBSERVABLE_BAND:
            con.execute(
                "UPDATE quarantine_queue SET resolved_at = ?, resolution = 'FIXED_BY_RULE', resolution_note = "
                "'ISIN change without price effect [CA13]' WHERE quarantine_id = ?",
                [utc_now(), qid],
            )
            done += 1
    if done:
        verify_pending_actions(con, exchange)
    return done


INACTIVITY_TRADING_DAYS = 20  # CHOICE: an open interval with no bar in the last 20 promoted sessions is closed


def close_inactive_securities(con, exchange: str, as_of: date, threshold: int | None = None) -> int:
    """P1-11: close the open identifier interval of a security that has not traded in the last `threshold`
    promoted sessions (delisted, merged, suspended, moved to a series outside the universe). valid_to = the day
    after its last bar. A security that trades again reopens through its FinInstrmId (identity.py)."""
    n = INACTIVITY_TRADING_DAYS if threshold is None else threshold
    recent = [r[0] for r in con.execute(
        "SELECT DISTINCT trade_date FROM ohlcv WHERE exchange = ? AND trade_date <= ? ORDER BY 1 DESC LIMIT ?",
        [exchange, as_of, n],
    ).fetchall()]  # fmt: skip
    if len(recent) < n:
        return 0
    cutoff = min(recent)
    rows = con.execute(
        """UPDATE security_identifier_history h SET valid_to = greatest(l.last_bar + INTERVAL 1 DAY, h.valid_from
                  + INTERVAL 1 DAY)::DATE
           FROM (SELECT security_id, max(trade_date) AS last_bar FROM ohlcv WHERE exchange = ? GROUP BY 1) l
           WHERE h.security_id = l.security_id AND h.exchange = ? AND h.valid_to IS NULL AND l.last_bar < ?
           RETURNING 1""",
        [exchange, exchange, cutoff],
    ).fetchall()
    return len(rows)


def _stage_issue_quarantines(con, stage_dir: Path) -> list[str]:
    rows = [
        _quarantine_row(
            stage=i["stage"], reason_code=i["reason_code"], filing_id=i["filing_id"], details=json.loads(i["details"])
        )
        for i in read_table(con, stage_dir, "stg_issues")
    ]
    return _quarantine_many(con, rows) if rows else []


def _attach_delivery(con, stage_dir: Path, exchange: str, trade_date: date) -> PromotionResult:
    """A delivery file fetched after its bhavcopy was promoted [P0-2]: raw rows are appended, and bars of that
    day whose delivery is still NULL get it, matched on (symbol, series) through the identifier interval valid on
    the day. Bars that already carry delivery are never changed."""
    _insert_vault_rows(con, stage_dir, ("blobs", "filings", "raw_delivery"))
    path = (Path(stage_dir) / "raw_delivery.parquet").as_posix()
    updated = con.execute(
        """UPDATE ohlcv o SET deliv_qty = d.deliv_qty, delivery_filing_id = d.filing_id
           FROM read_parquet(?) d JOIN security_identifier_history h
             ON h.exchange = d.exchange AND h.symbol = d.symbol AND h.series = d.series
            AND h.valid_from <= d.trade_date AND (h.valid_to IS NULL OR h.valid_to > d.trade_date)
           WHERE o.security_id = h.security_id AND o.exchange = d.exchange AND o.series = d.series
             AND o.trade_date = d.trade_date AND o.trade_date = ? AND o.deliv_qty IS NULL AND d.deliv_qty IS NOT NULL
           RETURNING 1""",
        [path, trade_date],
    ).fetchall()
    if not updated:  # a replay, or every bar already has delivery
        return PromotionResult("ALREADY_PROMOTED", "market_day", message=str(trade_date))
    return PromotionResult("PROMOTED", "market_day", message=f"{trade_date}: delivery attached to {len(updated)} bars")


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
    rows = [
        _quarantine_row(
            stage="GAP",
            reason_code=finding.reason_code,
            security_id=sec,
            details={"trade_date": trade_date, "gap": finding.gap, "prev_close": prev.get(sec), "open": open_t},
        )
        for sec, open_t in opens.items()
        for finding in audit_day(sec, trade_date, open_t, prev.get(sec), by_sec.get(sec, ()), sec in isin_changed)
    ]
    return _quarantine_many(con, rows)


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
                "recorded_at": utc_now(),
                "decided_at": None,
            }
        ],
        or_ignore=True,
    )


def verify_pending_actions(con, exchange: str) -> int:
    """Verify PENDING actions, grouped per (security, ex_date), once both bars exist.

    Returns the number of actions decided. Earlier GAP quarantines on that date are resolved
    only if the accepted factors now explain the gap (residual re-audit).
    """
    # Only actions whose ex-date bar exists can be decided: find them in one query (no per-action N+1).
    ready = con.execute(
        """SELECT DISTINCT a.security_id, a.ex_date, o.open,
                  (SELECT arg_max(p.close, p.trade_date) FROM ohlcv p
                    WHERE p.security_id = a.security_id AND p.exchange = o.exchange AND p.trade_date < a.ex_date)
           FROM corp_actions a JOIN ohlcv o
             ON o.security_id = a.security_id AND o.trade_date = a.ex_date AND o.exchange = ?
           WHERE a.status = 'PENDING' ORDER BY 1, 2""",
        [exchange],
    ).fetchall()
    decided = 0
    for sec, ex, open_ex, prev_close in ready:
        if prev_close is None:
            continue
        group = _actions(con, "security_id = ? AND ex_date = ? AND status IN ('PENDING', 'QUARANTINED')", [sec, ex])
        bar, prev = (open_ex,), (prev_close,)
        results = verify_group(group, bar[0], prev[0])
        for a, v in zip(group, results, strict=True):
            con.execute(
                "UPDATE corp_actions SET status = ?, price_factor = ?, eps_factor = ?, observed_gap = ?, "
                "decided_at = ? WHERE action_id = ?",
                [v.status, _f(v.price_factor), _f(v.eps_factor), _f(v.observed_gap), utc_now(), a.action_id],
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
    con.execute(
        "UPDATE quarantine_queue q SET resolved_at = ?, resolution = 'FIXED_BY_RULE', "
        "resolution_note = 'action verified on re-check' WHERE q.reason_code = 'VERIFY_FAILED' "
        "AND q.resolved_at IS NULL AND EXISTS (SELECT 1 FROM corp_actions a WHERE a.action_id = "
        "json_extract_string(q.details, '$.action_id') "
        "AND a.status IN ('VERIFIED', 'UNOBSERVABLE', 'VERIFIED_MANUAL'))",
        [utc_now()],
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
    skipped = 0
    for r in read_table(con, stage_dir, "stg_corp_actions"):
        if r["parse_status"] == "IGNORED":
            _retire_ignored(con, stable_id("ca", exchange, r["isin"], r["ex_date"], r["subject"], r["component"]))
            continue
        if not market_in_scope(r["ex_date"]):
            skipped += 1
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
        if not unparsed:
            _upgrade_unparsed(con, action)
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
                    details={
                        "subject": r["subject"],
                        "reason": r["parse_reason"],
                        "ex_date": r["ex_date"],
                        "action_id": action.action_id,
                    },
                )
            )
        recorded += 1
    _requeue_orphaned(con)
    verify_pending_actions(con, exchange)
    resolve_market_moves(con)
    message = f"{recorded} actions" + (f", {skipped} before {MIN_TRADE_DATE} skipped" if skipped else "")
    return PromotionResult("PROMOTED", "corp_actions", message=message, quarantined=quarantined)


def _upgrade_unparsed(con, action: CorpAction) -> None:
    """A record stored as UNKNOWN (unparsed purpose) that a later parser version reads: same action id (same ISIN,
    ex-date, subject, component), so the ledger row takes the parsed type and ratios, goes back to PENDING for
    verification, and its UNPARSED_PURPOSE finding closes [CA11]. Manual decisions (SUPERSEDED, REJECTED) stand."""
    hit = con.execute(
        "UPDATE corp_actions SET action_type = ?, ratio_num = ?, ratio_den = ?, issue_price = ?, cash_per_share = ?, "
        "status = 'PENDING', price_factor = NULL, eps_factor = NULL, observed_gap = NULL, decided_at = NULL "
        "WHERE action_id = ? AND action_type = 'UNKNOWN' AND status = 'QUARANTINED' RETURNING 1",
        [action.action_type, action.ratio_num, action.ratio_den, action.issue_price, action.cash_per_share,
         action.action_id],
    ).fetchall()  # fmt: skip
    if hit:
        con.execute(
            "UPDATE quarantine_queue SET resolved_at = ?, resolution = 'FIXED_BY_RULE', resolution_note = ? "
            "WHERE reason_code = 'UNPARSED_PURPOSE' AND resolved_at IS NULL "
            "AND json_extract_string(details, '$.action_id') = ?",
            [utc_now(), f"parsed by {action.action_type} rule [CA11]", action.action_id],
        )
    if hit:
        _requeue_siblings(con, action.action_id)


def _retire_ignored(con, action_id: str) -> None:
    """A record once stored as UNKNOWN that the current rules read as no action (an AGM / EGM notice [CA11]):
    the ledger row is retired (REJECTED, kept for audit) and its UNPARSED_PURPOSE finding closes."""
    hit = con.execute(
        "UPDATE corp_actions SET status = 'REJECTED', decided_at = ? WHERE action_id = ? AND action_type = 'UNKNOWN' "
        "AND status = 'QUARANTINED' RETURNING 1",
        [utc_now(), action_id],
    ).fetchall()
    if hit:
        con.execute(
            "UPDATE quarantine_queue SET resolved_at = ?, resolution = 'FIXED_BY_RULE', resolution_note = "
            "'meeting notice, no corporate action [CA11]' WHERE reason_code = 'UNPARSED_PURPOSE' "
            "AND resolved_at IS NULL AND json_extract_string(details, '$.action_id') = ?",
            [utc_now(), action_id],
        )
    if hit:
        _requeue_siblings(con, action_id)


def _requeue_orphaned(con) -> None:
    """Quarantined actions whose group was blocked only by an unfactorable (UNKNOWN) record that is no longer
    quarantined (upgraded or retired [CA11]) go back to PENDING; one batched statement."""
    con.execute(
        """UPDATE corp_actions a SET status = 'PENDING', decided_at = NULL
           WHERE a.status = 'QUARANTINED' AND a.action_type <> 'UNKNOWN'
             AND EXISTS (SELECT 1 FROM quarantine_queue q WHERE q.reason_code = 'VERIFY_FAILED'
                         AND q.resolved_at IS NULL AND json_extract_string(q.details, '$.action_id') = a.action_id
                         AND json_extract_string(q.details, '$.reason') LIKE '%unparsed corporate action%')
             AND NOT EXISTS (SELECT 1 FROM corp_actions u WHERE u.security_id = a.security_id
                             AND u.ex_date = a.ex_date AND u.action_type = 'UNKNOWN' AND u.status = 'QUARANTINED')"""
    )


def _requeue_siblings(con, action_id: str) -> None:
    """Actions of the same security and ex-date that were quarantined only because this record could not be
    factored go back to PENDING, so the next verification judges the group again (JNKINDIA 2024-10-21)."""
    con.execute(
        "UPDATE corp_actions SET status = 'PENDING', decided_at = NULL WHERE status = 'QUARANTINED' "
        "AND action_type <> 'UNKNOWN' AND (security_id, ex_date) IN "
        "(SELECT security_id, ex_date FROM corp_actions WHERE action_id = ?)",
        [action_id],
    )


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


def _declared_period_end(con, stage_dir: Path) -> date | None:
    ends = [
        r["value_text"].strip()
        for r in read_table(con, stage_dir, "raw_xbrl_facts")
        if r["element_name"] == "DateOfEndOfReportingPeriod"
    ]
    try:
        return max(date.fromisoformat(e) for e in ends) if ends else None
    except ValueError:
        return None


def _promote_results_xbrl(con, stage_dir: Path, manifest: dict[str, Any]) -> PromotionResult:
    declared_end = _declared_period_end(con, stage_dir)
    if declared_end is not None and not financials_in_scope(declared_end):
        return _out_of_scope(con, stage_dir, "results_xbrl", f"period end {declared_end} < {MIN_PERIOD_END_DATE}")
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

    if meta["stated_isin"] is None and meta["accounting_profile"] == "REG34_ANNUAL":
        # Reg. 34 annual XBRL carries no ISIN: the symbol in the NSE file name, resolved on the broadcast date (the
        # file is named when it is filed), plus the filed CIN when the entity has one on record [X70].
        on = utc_to_ist_date(filing["broadcast_ts"]) if filing["broadcast_ts"] is not None else meta["fy_end"]
        ent = con.execute(
            "SELECT DISTINCT s.entity_id FROM security_identifier_history h JOIN securities s USING (security_id) "
            "WHERE h.exchange = ? AND h.symbol = ? AND h.valid_from <= ? AND (h.valid_to IS NULL OR h.valid_to > ?)",
            [filing["exchange"], meta["stated_symbol"], on, on],
        ).fetchall()
        reason = "UNKNOWN_SYMBOL" if not ent else "AMBIGUOUS_SYMBOL"
        if len(ent) == 1 and meta.get("stated_cin"):
            cin = con.execute("SELECT cin FROM entity_master WHERE entity_id = ?", [ent[0][0]]).fetchone()[0]
            if cin is not None and cin != meta["stated_cin"]:
                ent, reason = [], "CIN_MISMATCH"
    else:
        ent = con.execute(
            "SELECT DISTINCT s.entity_id FROM security_identifier_history h "
            "JOIN securities s USING (security_id) WHERE h.exchange = ? AND h.isin = ?",
            [filing["exchange"], meta["stated_isin"]],
        ).fetchall()
        reason = "UNKNOWN_ISIN" if not ent else "AMBIGUOUS_ISIN"
    ovr = filing_overrides(con, fid)
    if "security_id" in ovr:  # `quarantine resolve --action OVERRIDE` [P2-13]
        ent = con.execute("SELECT entity_id FROM securities WHERE security_id = ?", [ovr["security_id"]]).fetchall()
    if len(ent) != 1:
        q = _quarantine(
            con,
            stage="IDENTITY",
            reason_code=reason,
            filing_id=fid,
            details={"isin": meta["stated_isin"], "symbol": meta["stated_symbol"], "cin": meta.get("stated_cin")},
        )
        return PromotionResult("QUARANTINED", "results_xbrl", message=fid, quarantined=[q])
    entity_id = ent[0][0]

    board_end = meta["board_meeting_end_ts"]
    board_ist_date = utc_to_ist_date(board_end) if board_end is not None else None
    visible, source = _visible_from(con, filing["exchange"], filing["broadcast_ts"], board_end, board_ist_date)
    if visible is None and "broadcast_ts" in ovr:
        visible, source = datetime.fromisoformat(ovr["broadcast_ts"]), "MANUAL_OVERRIDE"
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
                "auditor_qualified": meta.get("auditor_qualified"),
                "audit_opinion": meta.get("audit_opinion"),
            }
        ],
    )
    _link_revision(con, fid, entity_id, meta, visible)
    facts = read_table(con, stage_dir, "stg_xbrl_facts")
    insert_rows(con, "fact_observations", [{**f, "entity_id": entity_id, "visible_from_ts": visible} for f in facts])
    q = cross_check_shares(con, entity_id, meta["period_end"])
    return PromotionResult("PROMOTED", "results_xbrl", message=fid, quarantined=[q] if q else [])


def filing_overrides(con, filing_id: str) -> dict[str, str]:
    """Latest value per field of the filing's OVERRIDE resolutions (append-only table; later rows win)."""
    rows = con.execute(
        "SELECT field, value FROM filing_overrides WHERE filing_id = ? ORDER BY created_at", [filing_id]
    ).fetchall()
    return dict(rows)


def _link_revision(con, fid: str, entity_id: str, meta: dict, visible: datetime) -> None:
    """Revision chain [E9]: this filing supersedes the latest filing of the same entity, profile, scope and period end
    that became visible before it. Byte-identical blobs are RESENDs. Append-only link rows; facts need nothing else,
    because every PIT read already takes the latest version visible at the as-of."""
    prior = con.execute(
        "SELECT m.filing_id, f.sha256 FROM filing_meta m JOIN filings f USING (filing_id) WHERE m.entity_id = ? "
        "AND m.accounting_profile = ? AND m.scope = ? AND m.period_end = ? AND m.filing_id <> ? "
        "AND m.visible_from_ts < ? ORDER BY m.visible_from_ts DESC, m.filing_id DESC LIMIT 1",
        [entity_id, meta["accounting_profile"], meta["scope"], meta["period_end"], fid, visible],
    ).fetchone()
    if prior is None:
        return
    sha = con.execute("SELECT sha256 FROM filings WHERE filing_id = ?", [fid]).fetchone()[0]
    insert_rows(
        con,
        "filing_revisions",
        [{"filing_id": fid, "supersedes_filing_id": prior[0], "entity_id": entity_id, "period_end": meta["period_end"],
          "scope": meta["scope"], "relation": "RESEND" if sha == prior[1] else "REVISION"}],
        or_ignore=True,
    )  # fmt: skip


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
            "INSERT OR IGNORE INTO trading_calendar (exchange, cal_date, is_trading, note, source) "
            "VALUES (?, ?, FALSE, ?, 'HOLIDAY_MASTER')",
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
    if not market_in_scope(snap):
        return _out_of_scope(con, stage_dir, "index_snapshot", f"snapshot {snap} < {MIN_TRADE_DATE}")
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
    staged_meta = read_table(con, stage_dir, "stg_shp_meta")
    if staged_meta and not financials_in_scope(staged_meta[0]["as_of_date"]):
        return _out_of_scope(
            con, stage_dir, "shareholding", f"as of {staged_meta[0]['as_of_date']} < {MIN_PERIOD_END_DATE}"
        )
    _insert_vault_rows(con, stage_dir, ("blobs", "filings", "raw_xbrl_facts"))
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
                "promoter_encumbered_shares": meta.get("promoter_encumbered_shares"),
                "rules_applied": meta.get("rules_applied"),
                "visible_from_ts": visible,
            }
        ],
    )
    insert_rows(
        con,
        "shareholding_line_items",
        [
            {**li, "parser_version": meta["parser_version"], "entity_id": entity_id, "as_of_date": meta["as_of_date"],
             "visible_from_ts": visible}
            for li in read_table(con, stage_dir, "stg_shp_line_items")
        ],
    )  # fmt: skip
    holders = read_table(con, stage_dir, "stg_shp_holders")  # [] for stages written before 0.4.0
    insert_rows(
        con,
        "shareholding_major_holders",
        [
            {
                **{k: h[k] for k in ("filing_id", "holder_category", "row_member", "holder_name", "shares", "pct")},
                "parser_version": meta["parser_version"],
                "entity_id": entity_id,
                "as_of_date": meta["as_of_date"],
                "visible_from_ts": visible,
            }
            for h in holders
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


def _promote_kpis(con, stage_dir: Path, manifest: dict[str, Any]) -> PromotionResult:
    """Supplemental KPIs [P2 closeout]: each valid row resolves its symbol on period_end and lands in
    supplemental_kpis keyed by visible_from_ts (point in time). Invalid or unresolvable rows are quarantined."""
    _insert_vault_rows(con, stage_dir, ("blobs", "filings"))
    filing = read_table(con, stage_dir, "filings")[0]
    blob_sha = filing["sha256"]
    rows = read_table(con, stage_dir, "stg_kpis")
    good, quarantined = [], []
    for r in rows:
        ent = []
        if r["issue"] is None:
            ent = con.execute(
                "SELECT DISTINCT s.entity_id FROM security_identifier_history h JOIN securities s USING (security_id) "
                "WHERE h.symbol = ? AND h.valid_from <= ? AND (h.valid_to IS NULL OR h.valid_to > ?)",
                [r["symbol"], r["period_end"], r["period_end"]],
            ).fetchall() or con.execute(
                "SELECT DISTINCT s.entity_id FROM security_identifier_history h JOIN securities s USING (security_id) "
                "WHERE h.symbol = ?", [r["symbol"]]).fetchall()  # fmt: skip
        if r["issue"] is not None or len(ent) != 1:
            reason = r["issue"] or ("UNKNOWN_SYMBOL" if not ent else "AMBIGUOUS_SYMBOL")
            quarantined.append(
                _quarantine(
                    con,
                    stage="KPI",
                    reason_code=reason,
                    filing_id=filing["filing_id"],
                    details={"seq": r["seq"], "symbol": r["symbol"], "kpi": r["kpi"]},
                )
            )
            continue
        good.append(
            {
                "entity_id": ent[0][0],
                "kpi": r["kpi"],
                "period_start": r["period_start"],
                "period_end": r["period_end"],
                "value": r["value"],
                "unit": r["unit"],
                "source_kind": r["source_kind"],
                "source_url": r["source_url"],
                "source_sha256": blob_sha,
                "visible_from_ts": r["visible_from_ts"],
                "recorded_at": utc_now(),
                "notes": r["notes"],
            }
        )
    insert_rows(con, "supplemental_kpis", good, or_ignore=True)
    return PromotionResult("PROMOTED", "kpis", message=f"{len(good)} KPI rows", quarantined=quarantined)


def _promote_raw_only(con, stage_dir: Path, manifest: dict[str, Any]) -> PromotionResult:
    _insert_vault_rows(con, stage_dir, ("blobs", "filings"))
    return PromotionResult("PROMOTED", "raw_only", message=read_table(con, stage_dir, "filings")[0]["category"])


# ── Reg. 30 structured events [E1-E7] ──────────────────────────────────────


def _promote_reg30_event(con, stage_dir: Path, manifest: dict[str, Any]) -> PromotionResult:
    _insert_vault_rows(con, stage_dir, ("blobs", "filings", "raw_xbrl_facts"))
    filing = read_table(con, stage_dir, "filings")[0]
    fid = filing["filing_id"]
    issues = read_table(con, stage_dir, "stg_issues")
    if issues:
        qs = [
            _quarantine(con, stage=i["stage"], reason_code=i["reason_code"], filing_id=fid,
                        details=json.loads(i["details"]))
            for i in issues
        ]  # fmt: skip
        return PromotionResult("QUARANTINED", "reg30_event", message=fid, quarantined=qs)
    events = read_table(con, stage_dir, "stg_events")
    if not events:  # an event family we do not parse: vaulted raw only [E2]
        return PromotionResult("PROMOTED", "reg30_event", message=f"{fid} raw only")
    first = events[0]
    on = first["report_date"]
    if first["stated_isin"]:
        secs = resolve_security_by_isin(con, filing["exchange"], first["stated_isin"], on)
    else:  # fraud/default disclosures carry the symbol only [E7]
        secs = [r[0] for r in con.execute(
            "SELECT DISTINCT security_id FROM security_identifier_history WHERE exchange = ? AND symbol = ? "
            "AND valid_from <= ? AND (valid_to IS NULL OR valid_to > ?)",
            [filing["exchange"], first["stated_symbol"], on, on]).fetchall()]  # fmt: skip
    entities = sorted(
        {con.execute("SELECT entity_id FROM securities WHERE security_id = ?", [s_]).fetchone()[0] for s_ in secs}
    )
    if len(entities) != 1:
        key = "ISIN" if first["stated_isin"] else "SYMBOL"  # SME symbols are outside the universe (C9 scope)
        q = _quarantine(
            con,
            stage="IDENTITY",
            reason_code=("UNKNOWN_" if not entities else "AMBIGUOUS_") + key,
            filing_id=fid,
            details={"isin": first["stated_isin"], "symbol": first["stated_symbol"]},
        )
        return PromotionResult("QUARANTINED", "reg30_event", message=fid, quarantined=[q])
    if filing["broadcast_ts"] is None:
        q = _quarantine(
            con,
            stage="PERIOD",
            reason_code="NO_VISIBILITY",
            filing_id=fid,
            entity_id=entities[0],
            details={"report_date": on},
        )
        return PromotionResult("QUARANTINED", "reg30_event", message=fid, quarantined=[q])
    insert_rows(
        con,
        "corporate_events",
        [
            {
                "event_id": stable_id("evt", filing["sha256"], e["record_key"]),
                "filing_id": fid, "parser_version": PARSER_VERSION, "entity_id": entities[0],
                **{k: e[k] for k in ("family", "event_type", "event_subtype", "occurred_on", "report_date",
                                     "counterparty", "amount_inr", "person_name", "person_category", "change_type",
                                     "cessation_category", "details")},
                "visible_from_ts": filing["broadcast_ts"],
            }
            for e in events
        ],
        or_ignore=True,  # a byte-identical re-send is the same event [E4]
    )  # fmt: skip
    return PromotionResult("PROMOTED", "reg30_event", message=fid)
