"""The single writer. Reads staged batches, runs gates, commits atomically to market.duckdb.

Gates (docs/architecture.md §12): G1 completeness, G2 identifier resolution, ORDER and the CAL3 no-session
inference for market days; G3 accounting identities are enforced by the parsers and surface as staged issues;
G4 (null spike) and G5 (atomic universe) run in feature materialisation (financials.features.materialize).
"""

from __future__ import annotations

import json
import re
import statistics
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from financials import PARSER_VERSION, dirty
from financials.corp_actions import ACCEPTED_STATUSES, CorpAction, adjust_closes, audit_day, verify_group
from financials.db import fetch_dicts, insert_rows, version_key
from financials.fundamentals import CURRENT_VERSION
from financials.identity import UNIVERSE_SERIES, Interval, SecurityRegistry, rights_entitlement_sql
from financials.ids import stable_id
from financials.money import ROUNDING_UNITS
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


# Jobs whose rules can change price-side feature inputs (factors, GAP freezes, identifiers, Nifty 500 membership).
MARKET_STATE_JOBS = frozenset({"market_day", "corp_actions", "index_snapshot"})


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
        "index_close": _promote_vault_and_raw,
        "equity_master": _promote_vault_and_raw,
        "classification": _promote_classification,
        "mcap_day": _promote_mcap_day,
        "bse_securities": _promote_bse_securities,
    }.get(job)
    if handler is None:
        raise ValueError(f"unknown job {job!r}")
    con.execute("BEGIN TRANSACTION")
    try:
        before = dirty.market_state(con) if job in MARKET_STATE_JOBS else None
        result = handler(con, Path(stage_dir), manifest)
        if before is not None:  # price-side changes made by any rule this batch ran (dirty.py)
            dirty.mark_market_changes(con, before, job.upper(), Path(stage_dir).name)
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
    dirty.mark_all(con, trade_date, "MARKET_DAY", filing_id)  # new bars: every row from this day on (lookbacks)
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
    resolve_rights_entitlement_gaps(con)
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


# X140 (live backfill 2024-10 .. 2026-11): 87 of the 104 gap findings left after CA12 / CA13 were rights entitlements
# (RE): a temporary instrument that carries the right to subscribe a rights issue, traded for a few sessions and then
# deactivated (SEBI circular SEBI/HO/CFD/DIL2/CIR/P/2020/13, 22 Jan 2020: separate ISIN, secondary-market trading,
# ISIN permanently deactivated after allotment). NSE lists it with the parent's issuer code, security-type code 20
# (ISIN chars 8-9) and symbol <prefix>-RE[n] (fixture: SHIVAM-RE1 INE637H20024 beside SHIVAMAUTO INE637H01024). No
# split, bonus or other share-count event ever applies to an RE, so its gaps are market moves (worthless-or-not
# pricing of a right with days to live, penny ticks: 0.02 -> 0.03 is +50%). Both markers and an equity listing of
# the same issuer are required; nothing else is touched.
RIGHTS_ENTITLEMENT_NOTE = "rights entitlement: no share-count event applies, market move [X140]"


def resolve_rights_entitlement_gaps(con) -> int:
    """Named rule X140: close open UNEXPLAINED_GAP findings of rights entitlements (ISIN security-type 20, symbol
    ending -RE or -RE<n>, an equity ISIN of the same issuer with type 01 in the identifier history) as FIXED_BY_RULE.
    One batched statement."""
    rows = con.execute(
        """UPDATE quarantine_queue SET resolved_at = ?, resolution = 'FIXED_BY_RULE', resolution_note = ?
           WHERE quarantine_id IN (
             SELECT q.quarantine_id FROM quarantine_queue q
             JOIN security_identifier_history h ON h.security_id = q.security_id
                  AND h.valid_from <= CAST(json_extract_string(q.details, '$.trade_date') AS DATE)
                  AND (h.valid_to IS NULL OR h.valid_to > CAST(json_extract_string(q.details, '$.trade_date') AS DATE))
             WHERE q.stage = 'GAP' AND q.reason_code = 'UNEXPLAINED_GAP' AND q.resolved_at IS NULL
               AND """
        + rights_entitlement_sql("h")
        + """)
           RETURNING 1""",
        [utc_now(), RIGHTS_ENTITLEMENT_NOTE],
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
    after its last bar. A security that trades again reopens through its FinInstrmId, or, back in another series
    with a new FinInstrmId, through the ISIN of its latest interval (rule X320, identity.py)."""
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
           RETURNING o.security_id""",
        [path, trade_date],
    ).fetchall()
    if not updated:  # a replay, or every bar already has delivery
        return PromotionResult("ALREADY_PROMOTED", "market_day", message=str(trade_date))
    dirty.mark_securities(con, {sec: trade_date for (sec,) in updated}, "DELIVERY", str(trade_date))
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


ISIN_TYPO_RULE = "ISIN_TYPO_SYMBOL_MATCH"


def is_isin_typo(stated: str, actual: str) -> bool:
    """X81: the stated ISIN is the actual one with the letter O typed for the digit 0, or with one pair of adjacent
    characters swapped. Nothing looser (no other substitutions, insertions or deletions)."""
    if not stated or len(stated) != len(actual) or stated == actual:
        return False
    if all(a == b or (a == "O" and b == "0") for a, b in zip(stated, actual, strict=True)):
        return True
    diff = [i for i, (a, b) in enumerate(zip(stated, actual, strict=True)) if a != b]
    return (
        len(diff) == 2
        and diff[1] == diff[0] + 1
        and stated[diff[0]] == actual[diff[1]]
        and stated[diff[1]] == actual[diff[0]]
    )


def resolve_isin_typo(con, exchange: str, isin: str, symbol: str | None, on_date: date, filing_id: str) -> list[str]:
    """Rule ISIN_TYPO_SYMBOL_MATCH [X81]: an unknown stated ISIN is accepted only when the stated symbol names exactly
    one security on `on_date` (else in any interval, as resolve_security_by_isin) and that security's ISIN is the
    stated one up to an O/0 typo or one adjacent swap. Logged in admin_log; raw keeps the ISIN as sent (invariant 3)."""
    if not symbol or not isin:
        return []
    rows = con.execute(
        "SELECT DISTINCT security_id, isin FROM security_identifier_history WHERE exchange = ? AND symbol = ? "
        "AND valid_from <= ? AND (valid_to IS NULL OR valid_to > ?)",
        [exchange, symbol, on_date, on_date],
    ).fetchall()
    if not rows:  # same fallback as resolve_security_by_isin: any interval, still exactly one security
        rows = con.execute(
            "SELECT DISTINCT security_id, isin FROM security_identifier_history WHERE exchange = ? AND symbol = ?",
            [exchange, symbol],
        ).fetchall()
    if len({sec for sec, _ in rows}) != 1 or not all(is_isin_typo(isin, actual) for _, actual in rows):
        return []
    sec, actual = rows[0]
    params = json.dumps({"filing_id": filing_id, "stated_isin": isin, "symbol": symbol, "isin": actual,
                         "security_id": sec}, sort_keys=True)  # fmt: skip
    row = [stable_id("adm", ISIN_TYPO_RULE, params), "RULE:" + ISIN_TYPO_RULE, params, "X81", utc_now()]
    con.execute("INSERT OR IGNORE INTO admin_log VALUES (?, ?, ?, NULL, ?, ?)", row)
    return [sec]


UNREGISTERED_ISIN_RULE = "UNREGISTERED_ISIN_SYMBOL_MATCH"
_NAME_SUFFIXES = {"LTD", "LIMITED", "L"}


def _name_tokens(name: str) -> list[str]:
    tokens = re.sub(r"[^A-Z0-9 ]", " ", name.upper().replace(".", "")).split()
    while tokens and tokens[-1] in _NAME_SUFFIXES:
        tokens.pop()
    return tokens


def names_agree(stated: str | None, legal: str | None) -> bool:
    """Exchange names are abbreviated ("KRISHNA INST OF MED SCI L"): every legal-name word must be a prefix of the
    stated word in the same position, after dropping punctuation and a trailing LTD / LIMITED / L."""
    if not stated or not legal:
        return False
    a, b = _name_tokens(stated), _name_tokens(legal)
    return bool(b) and len(a) == len(b) and all(x.startswith(y) for x, y in zip(a, b, strict=True))


def resolve_unregistered_isin(
    con, exchange: str, isin: str, symbol: str | None, company_name: str | None, on_date: date, filing_id: str
) -> list[str]:
    """Rule UNREGISTERED_ISIN_SYMBOL_MATCH [X88]: the stated ISIN belongs to no security we know (any exchange, any
    time), so it cannot name another listed issuer; the stated symbol names exactly one security (on `on_date`, else
    any interval) and that security has the same ISIN issuer code or the same company name (names_agree). Covers
    garbled ISINs, a bond ISIN (HDB Financial INE756I08058) and a pre-split ISIN (Persistent INE262H01016).
    Logged in admin_log; raw keeps the ISIN as sent (invariant 3)."""
    if not symbol or not isin:
        return []
    if con.execute("SELECT count(*) FROM security_identifier_history WHERE isin = ?", [isin]).fetchone()[0]:
        return []
    rows = (
        con.execute(
            "SELECT DISTINCT h.security_id, h.isin, e.legal_name FROM security_identifier_history h "
            "JOIN securities s USING (security_id) JOIN entity_master e USING (entity_id) WHERE h.exchange = ? "
            "AND h.symbol = ? AND h.valid_from <= ? AND (h.valid_to IS NULL OR h.valid_to > ?)",
            [exchange, symbol, on_date, on_date],
        ).fetchall()
        or con.execute(
            "SELECT DISTINCT h.security_id, h.isin, e.legal_name FROM security_identifier_history h "
            "JOIN securities s USING (security_id) JOIN entity_master e USING (entity_id) WHERE h.exchange = ? "
            "AND h.symbol = ?",
            [exchange, symbol],
        ).fetchall()
    )
    if len({sec for sec, _, _ in rows}) != 1:
        return []
    sec, actual, legal = rows[0]
    if isin_issuer_code(actual) != isin_issuer_code(isin) and not names_agree(company_name, legal):
        return []
    params = json.dumps({"filing_id": filing_id, "stated_isin": isin, "symbol": symbol, "isin": actual,
                         "security_id": sec, "company_name": company_name}, sort_keys=True)  # fmt: skip
    row = [stable_id("adm", UNREGISTERED_ISIN_RULE, params), "RULE:" + UNREGISTERED_ISIN_RULE, params, "X88", utc_now()]
    con.execute("INSERT OR IGNORE INTO admin_log VALUES (?, ?, ?, NULL, ?, ?)", row)
    return [sec]


ISIN_ONE_CHAR_RULE = "ISIN_ONE_CHAR_SYMBOL_NAME_MATCH"
_LEADING_ARTICLE = re.compile(r"^THE\s+")
_TRAILING_SUFFIX = re.compile(r"(LIMITED|LTD)$")


def compact_name(name: str | None) -> str:
    """X336: a company name reduced to its letters and digits, upper case, without a leading THE and a trailing
    LIMITED / LTD: "J.KUMAR INFRAPROJECTS LIMITED" -> JKUMARINFRAPROJECTS, exchange "JKUMAR INFR.LTD." -> JKUMARINFR,
    "THE ANDHRA SUGARS LIMITED" and "ANDHRA SUGARS LTD" -> ANDHRASUGARS."""
    s = _LEADING_ARTICLE.sub("", (name or "").upper().strip())
    return _TRAILING_SUFFIX.sub("", re.sub(r"[^A-Z0-9]", "", s))


def company_names_match(stated: str | None, legal: str | None) -> bool:
    """X336: the filed company name matches the entity's (exchange, often abbreviated) name: names_agree (X88), or
    the compact exchange name is the compact filed name or a prefix of it ("JKUMARINFR" of "JKUMARINFRAPROJECTS")."""
    if names_agree(stated, legal):
        return True
    a, b = compact_name(stated), compact_name(legal)
    return bool(a) and bool(b) and a.startswith(b)


def _hamming1(a: str, b: str) -> bool:
    return len(a) == len(b) and sum(x != y for x, y in zip(a, b, strict=True)) == 1


def isin_one_char_match(con, exchange: str, isin: str | None, symbol: str | None, company_name: str | None,
                        on_date: date) -> tuple[str, str, str] | None:  # fmt: skip
    """The decision of rule ISIN_ONE_CHAR_SYMBOL_NAME_MATCH [X336] (read-only): (security_id, its ISIN, legal name)
    or None. See resolve_isin_one_char."""
    if not symbol or not isin:
        return None
    if con.execute("SELECT count(*) FROM security_identifier_history WHERE isin = ?", [isin]).fetchone()[0]:
        return None
    rows = con.execute(
        "SELECT DISTINCT h.security_id, h.isin, e.legal_name FROM security_identifier_history h "
        "JOIN securities s USING (security_id) JOIN entity_master e USING (entity_id) WHERE h.exchange = ? "
        "AND h.symbol = ? AND h.valid_from <= ? AND (h.valid_to IS NULL OR h.valid_to > ?)",
        [exchange, symbol, on_date, on_date],
    ).fetchall()
    if len(rows) != 1:
        return None
    sec, actual, legal = rows[0]
    if not _hamming1(isin, actual) or not company_names_match(company_name, legal):
        return None
    return sec, actual, legal


def resolve_isin_one_char(
    con, exchange: str, isin: str, symbol: str | None, company_name: str | None, on_date: date, filing_id: str
) -> list[str]:
    """Rule ISIN_ONE_CHAR_SYMBOL_NAME_MATCH [X336], in the X88 family: the stated ISIN belongs to no security we know
    (any exchange, any time), the stated symbol held exactly one ISIN on `on_date` (no any-interval fallback), the
    stated ISIN differs from it in exactly one character (Hamming distance 1), and the filed company name matches
    the entity's name (company_names_match). J. Kumar Infraprojects files INE576101022 (digit 1 for the letter I of
    INE576I01022, 10 results filings Q4 FY25..Q1 FY27); Andhra Sugars Q4 FY26 files INE715N01021 for INE715B01021.
    X81 (O / 0, adjacent swap) and X88 (same issuer code or names_agree) do not cover them: the typo is inside the
    issuer code and the exchange name is abbreviated ("JKUMAR INFR.LTD.") or lacks the filed "THE". Anything else
    stays quarantined. Logged in admin_log; raw keeps the ISIN as sent (invariant 3)."""
    hit = isin_one_char_match(con, exchange, isin, symbol, company_name, on_date)
    if hit is None:
        return []
    sec, actual, _ = hit
    params = json.dumps({"filing_id": filing_id, "stated_isin": isin, "symbol": symbol, "isin": actual,
                         "security_id": sec, "company_name": company_name}, sort_keys=True)  # fmt: skip
    row = [stable_id("adm", ISIN_ONE_CHAR_RULE, params), "RULE:" + ISIN_ONE_CHAR_RULE, params, "X336", utc_now()]
    con.execute("INSERT OR IGNORE INTO admin_log VALUES (?, ?, ?, NULL, ?, ?)", row)
    return [sec]


ISIN_OF_OTHER_ISSUER_RULE = "ISIN_OF_OTHER_ISSUER"


def resolve_isin_symbol_conflict(
    con, exchange: str, isin_entity: str, symbol: str | None, company_name: str | None, on_date: date, filing_id: str
) -> tuple[str | None, dict | None]:
    """[X101] The stated ISIN names one entity; the stated symbol may name another (Gillette Q1 FY26 1498822: symbol
    GILLETTE, company "Gillette India Limited", ISIN INE179A01014 = P&G Hygiene). Invariant 3: identifiers that
    disagree quarantine, except under the named rule ISIN_OF_OTHER_ISSUER: the symbol names exactly one entity
    whose legal name agrees with the filed company name, and the ISIN entity's does not. Returns (entity_id, None)
    to promote, or (None, details) to quarantine as IDENTITY/ISIN_SYMBOL_CONFLICT. An unknown symbol is no conflict."""
    if not symbol:
        return isin_entity, None
    q = ("SELECT DISTINCT s.entity_id, s.security_id, e.legal_name FROM security_identifier_history h "
         "JOIN securities s USING (security_id) JOIN entity_master e USING (entity_id) WHERE h.exchange = ? "
         "AND h.symbol = ?")  # fmt: skip
    on = " AND h.valid_from <= ? AND (h.valid_to IS NULL OR h.valid_to > ?)"
    rows = con.execute(q + on, [exchange, symbol, on_date, on_date]).fetchall()
    rows = rows or con.execute(q, [exchange, symbol]).fetchall()
    ents = {e for e, _, _ in rows}
    if not ents or isin_entity in ents:
        return isin_entity, None
    isin_legal = con.execute("SELECT legal_name FROM entity_master WHERE entity_id = ?", [isin_entity]).fetchone()
    details = {"isin_entity": isin_entity, "symbol": symbol, "symbol_entities": sorted(ents),
               "company_name": company_name}  # fmt: skip
    if len(ents) == 1 and names_agree(company_name, rows[0][2]) and not names_agree(company_name, isin_legal[0]):
        params = json.dumps({"filing_id": filing_id, **details}, sort_keys=True)
        row = [stable_id("adm", ISIN_OF_OTHER_ISSUER_RULE, params), "RULE:" + ISIN_OF_OTHER_ISSUER_RULE, params,
               "X101", utc_now()]  # fmt: skip
        con.execute("INSERT OR IGNORE INTO admin_log VALUES (?, ?, ?, NULL, ?, ?)", row)
        return rows[0][0], None
    return None, details


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
    source_url: str | None = None,
) -> tuple[datetime | None, str | None]:
    """Earliest time the filing can have been public (UTC) [X83, architecture §6.3].

    1. The later of the filing's broadcast time and the listing's broadcast/creation time (raw_results_listing):
       a revised listing row has no broadcast_Date, and a re-uploaded file is created after the broadcast it replaces.
    2. Without either: the board-meeting rule (board end + next trading day) [R9, UNVERIFIED], lifted to the XBRL file
       name's upload time read as PM (12-hour clock) when that is later (re-filings uploaded weeks after the meeting).
    Never earlier than the file name's upload time read as AM: a file cannot be public before it was made.
    """
    from financials.calendar import next_trading_day
    from financials.parsers.discovery import filename_ts_bounds

    listed = (
        con.execute(
            "SELECT max(broadcast_ts), max(creation_ts) FROM raw_results_listing WHERE xbrl_url = ?", [source_url]
        ).fetchone()
        if source_url
        else (None, None)
    )
    bounds = filename_ts_bounds(source_url) if source_url else None
    lo, hi = (ist_to_utc(b.date(), b.time()) for b in bounds) if bounds else (None, None)
    board = None
    if board_end is not None and board_end_ist_date is not None:
        nxt = next_trading_day(con, exchange, board_end_ist_date)
        board = None if nxt is None else ist_to_utc(nxt, time(0, 0))
    known = [t for t in (broadcast_ts, *listed) if t is not None]
    if known:
        visible = max(known)
        source = "BROADCAST" if visible == broadcast_ts else "LISTING_CREATION"
    elif board is None:
        return None, None  # no broadcast, listing or board-meeting evidence: NO_VISIBILITY
    elif hi is not None and hi > board:
        visible, source = hi, "FILENAME_TS"
    else:
        visible, source = board, "BOARD_MEETING_RULE"
    if lo is not None and lo > visible:
        visible, source = lo, "FILENAME_TS"
    return visible, source


def _declared_period_end(con, stage_dir: Path, manifest: dict[str, Any]) -> date | None:
    """The latest `DateOfEndOfReportingPeriod` the file states (any context), from the stage manifest. A batch
    staged before decision J carries the raw facts as Parquet instead: read from there."""
    if "declared_period_ends" in manifest:
        ends = list(manifest["declared_period_ends"])
    else:
        path = Path(stage_dir) / "raw_xbrl_facts.parquet"
        ends = [] if not path.exists() else [v.strip() for (v,) in con.execute(
            "SELECT value_text FROM read_parquet(?) WHERE element_name = 'DateOfEndOfReportingPeriod'",
            [path.as_posix()]).fetchall()]  # fmt: skip
    try:
        return max(date.fromisoformat(e) for e in ends) if ends else None
    except ValueError:
        return None


def audit_ytd_identity(con, pairs: Iterable[tuple[str, str]]) -> list[str]:
    """X80 / blueprint §3.2: for each (entity, scope), every filed YTD whose quarters were all filed directly must
    equal their sum. Each break is a CONSISTENCY/YTD_QUARTER_MISMATCH finding (deterministic id, so a re-run raises
    nothing new); TTM over that year comes from the YTD bridge and the row is flagged (X106). A corrected or revised
    filing that restores the identity is the only fix."""
    from financials.fundamentals import YTD_GUARDED_TAGS, load_factbook

    rows, pairs, rule_notes = [], list(pairs), {}
    for entity_id, scope in pairs:
        book = load_factbook(con, entity_id, scope, datetime(9999, 12, 31))
        for tag in sorted(YTD_GUARDED_TAGS):
            for b in book.ytd_breaks(tag):
                rows.append(_quarantine_row(stage="CONSISTENCY", reason_code="YTD_QUARTER_MISMATCH",
                                            entity_id=entity_id, details={"scope": scope, **b}))  # fmt: skip
            # X260 / X314: the id the finding had, to name the rule when closing it
            ruled = ((ROUNDING_ONLY_NOTE, book.ytd_rounding_only), (NET_LINE_SIDE_NOTE, book.ytd_net_line_side))
            for note, found in ((n, f(tag)) for n, f in ruled):
                for b in found:
                    row = _quarantine_row(stage="CONSISTENCY", reason_code="YTD_QUARTER_MISMATCH",
                                          entity_id=entity_id, details={"scope": scope, **b})  # fmt: skip
                    rule_notes[row["quarantine_id"]] = note
        for b in book.tax_copied:  # X94: already withheld by load_factbook; the finding makes it visible
            rows.append(_quarantine_row(stage="CONSISTENCY", reason_code="TAX_COPIED_FROM_PRIOR_YEAR",
                                        entity_id=entity_id, details={"scope": scope, **b}))  # fmt: skip
    _close_stale_ytd_findings(con, pairs, {r["quarantine_id"] for r in rows}, rule_notes=rule_notes)
    return _quarantine_many(con, rows) if rows else []


ROUNDING_ONLY_NOTE = (
    "ROUNDING_ONLY [X260]: the difference is within the rounding of the figures compared (half a unit of the "
    "coarser LevelOfRounding per rounded figure)"
)
NET_LINE_SIDE_NOTE = (
    "NBFC_NET_LINE_SIDE [X314]: the identity holds with every period's net loss on fair value changes / on "
    "derecognition netted against revenue; the NBFC template shows that net result in revenue in a period with a net "
    "gain and in expenses in a period with a net loss, so revenue and total income are not additive across periods"
)


def _close_stale_ytd_findings(
    con,
    pairs: list[tuple[str, str]],
    current: set[str],
    rounding_only: set[str] = frozenset(),
    rule_notes: dict[str, str] | None = None,
) -> None:
    """An open YTD_QUARTER_MISMATCH of an audited (entity, scope) that the audit no longer raises is closed: a
    corrected filing or a later rule (X82: a non-FY-start duration is not a YTD) removed the break. One whose
    difference is a rounding difference (`rounding_only`, rule X260) or that another named rule explains
    (`rule_notes`: id -> note, X314) is closed with a note naming the rule."""
    notes = {q: ROUNDING_ONLY_NOTE for q in rounding_only} | dict(rule_notes or {})
    if not pairs:
        return
    open_rows = con.execute(
        "SELECT quarantine_id, entity_id, json_extract_string(details, '$.scope') FROM quarantine_queue "
        "WHERE stage = 'CONSISTENCY' AND reason_code IN ('YTD_QUARTER_MISMATCH', 'TAX_COPIED_FROM_PRIOR_YEAR') "
        "AND resolved_at IS NULL"
    ).fetchall()
    audited = set(pairs)
    stale = [q for q, e, s in open_rows if (e, s) in audited and q not in current]
    if stale:
        by_note: dict[str, list[str]] = {}
        for q in stale:
            by_note.setdefault(notes.get(q, "consistency holds on re-audit"), []).append(q)
        now = utc_now()
        for note, ids in sorted(by_note.items()):
            con.execute(
                "UPDATE quarantine_queue SET resolved_at = ?, resolution = 'FIXED_BY_RULE', resolution_note = ? "
                "WHERE quarantine_id IN (SELECT unnest(?))",
                [now, note, sorted(ids)],
            )


def _entities_by_staged_scrip_code(con, stage_dir: Path) -> list[tuple[str]]:
    """Entities whose identifier rows hold the BSE scrip code a staged BSE results file states (its non-dimensional
    `ScripCode`, rule SC0; codes filled by rule BSE1 from BSE's list of securities) [X265]."""
    from financials import filing_checks as fc

    path = Path(stage_dir) / "stg_disclosures.parquet"
    if not path.exists():
        return []
    vals = {fc.scrip_code(v) for (v,) in con.execute(
        "SELECT value_text FROM read_parquet(?) WHERE element = 'ScripCode' AND dimensions IS NULL",
        [path.as_posix()]).fetchall()}  # fmt: skip
    vals.discard(None)
    if len(vals) != 1:
        return []
    return con.execute(
        "SELECT DISTINCT s.entity_id FROM security_identifier_history h JOIN securities s USING (security_id) "
        "WHERE h.exchange <> 'BSE' AND h.bse_scrip_code = ?",
        [vals.pop()],
    ).fetchall()


def _promote_results_xbrl(con, stage_dir: Path, manifest: dict[str, Any]) -> PromotionResult:
    declared_end = _declared_period_end(con, stage_dir, manifest)
    if declared_end is not None and not financials_in_scope(declared_end):
        return _out_of_scope(con, stage_dir, "results_xbrl", f"period end {declared_end} < {MIN_PERIOD_END_DATE}")
    _insert_vault_rows(con, stage_dir, ("blobs", "filings"))
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

    # A BSE results file (Permitted member, X265) resolves through the NSE identifier rows of the same security, as
    # BSE shareholding does (X170); with no ISIN match, by its filed ScripCode (codes of rule BSE1).
    ix = "NSE" if filing["exchange"] == "BSE" else filing["exchange"]
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
            [ix, meta["stated_isin"]],
        ).fetchall()
        if not ent:
            typo = resolve_isin_typo(con, ix, meta["stated_isin"], meta["stated_symbol"], meta["period_end"], fid)
            typo = typo or resolve_unregistered_isin(con, ix, meta["stated_isin"], meta["stated_symbol"],
                                                     meta.get("company_name"), meta["period_end"], fid)  # fmt: skip
            typo = typo or resolve_isin_one_char(con, ix, meta["stated_isin"], meta["stated_symbol"],
                                                 meta.get("company_name"), meta["period_end"], fid)  # fmt: skip
            ent = con.execute("SELECT entity_id FROM securities WHERE security_id IN (SELECT unnest(?))",
                              [typo]).fetchall()  # fmt: skip
        if not ent and filing["exchange"] == "BSE":
            ent = _entities_by_staged_scrip_code(con, stage_dir)
        reason = "UNKNOWN_ISIN" if not ent else "AMBIGUOUS_ISIN"
    ovr = filing_overrides(con, fid)
    conflict = None
    if "security_id" in ovr:  # `quarantine resolve --action OVERRIDE` [P2-13]
        ent = con.execute("SELECT entity_id FROM securities WHERE security_id = ?", [ovr["security_id"]]).fetchall()
    elif len(ent) == 1 and meta["stated_isin"] is not None:
        resolved, conflict = resolve_isin_symbol_conflict(
            con, ix, ent[0][0], meta["stated_symbol"], meta.get("company_name"), meta["period_end"], fid
        )
        ent = [(resolved,)] if resolved else []
        reason = "ISIN_SYMBOL_CONFLICT"
    if len(ent) != 1:
        q = _quarantine(
            con,
            stage="IDENTITY",
            reason_code=reason,
            filing_id=fid,
            details={"isin": meta["stated_isin"], "symbol": meta["stated_symbol"], "cin": meta.get("stated_cin"),
                     **(conflict or {})},
        )  # fmt: skip
        return PromotionResult("QUARANTINED", "results_xbrl", message=fid, quarantined=[q])
    entity_id = ent[0][0]

    board_end = meta["board_meeting_end_ts"]
    board_ist_date = utc_to_ist_date(board_end) if board_end is not None else None
    visible, source = _visible_from(con, filing["exchange"], filing["broadcast_ts"], board_end, board_ist_date,
                                    filing["source_url"])  # fmt: skip
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

    # Dirty from the earliest visibility of any version of this filing: a re-parse can move visibility later (X83)
    # or to another entity (identity override), and the older version's rows stop being read at once.
    earlier = con.execute(
        "SELECT entity_id, min(visible_from_ts) FROM filing_meta WHERE filing_id = ? GROUP BY 1", [fid]
    ).fetchall()
    for ent, ts in [*earlier, (entity_id, visible)]:
        dirty.mark_visible(con, ent, min(ts, visible), "RESULTS", fid)
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
    # Segment / geography rows [X97]: same entity, scope, visibility and parser version as the filing; a separate
    # table that never feeds fact_observations or a ratio.
    segs = read_table(con, stage_dir, "stg_segments")
    insert_rows(con, "segment_observations", [{**r, "entity_id": entity_id, "visible_from_ts": visible} for r in segs])
    # AOC-1 group structure [X112]: same entity, scope and visibility as the annual filing; never feeds a ratio.
    group = read_table(con, stage_dir, "stg_group_structure")
    insert_rows(con, "group_structure", [{**r, "entity_id": entity_id, "visible_from_ts": visible} for r in group],
                or_ignore=True)  # fmt: skip
    # Related-party schedule [X113]: same entity, scope and visibility; feeds only the batch J RPT columns.
    rpt = read_table(con, stage_dir, "stg_related_parties")
    insert_rows(con, "related_party_transactions", [{**r, "entity_id": entity_id, "visible_from_ts": visible}
                                                    for r in rpt], or_ignore=True)  # fmt: skip
    # Reg. 23(9) rows of a standalone Q2 / Q4 Integrated Filing [X115]: same entity, scope and visibility; never feed a
    # ratio or a feature column (half-year amounts, X160, but some filers put FY-to-date in Q4, X161).
    reg23 = read_table(con, stage_dir, "stg_reg23_rpt")
    insert_rows(con, "reg23_related_party_transactions", [{**r, "entity_id": entity_id, "visible_from_ts": visible}
                                                          for r in reg23], or_ignore=True)  # fmt: skip
    _insert_disclosures(con, stage_dir, entity_id, visible)  # X116: every element no other clean table holds
    _insert_audit_opinions(con, stage_dir, entity_id, visible)  # X121: audit-opinion flags from the report text
    # Non-blocking parse findings (X86 ATTRIBUTION_WITHHELD): the filing is promoted, the finding stays open.
    finding_rows = [
        _quarantine_row(stage=i["stage"], reason_code=i["reason_code"], filing_id=fid, entity_id=entity_id,
                        details=json.loads(i["details"]))
        for i in read_table(con, stage_dir, "stg_findings")
    ]  # fmt: skip
    finding_rows += _filing_check_rows(con, fid, filing["exchange"], entity_id, meta, visible)  # G328, G79
    _close_filing_findings(con, fid, f"parser {meta['parser_version']}: promoted",
                           keep=[r["quarantine_id"] for r in finding_rows])  # fmt: skip
    qs = (_quarantine_many(con, finding_rows) if finding_rows else []) + audit_ytd_identity(
        con, [(entity_id, meta["scope"])]
    )
    q = cross_check_shares(con, entity_id, meta["period_end"])
    qa = annual_share_check(con, fid, entity_id, meta) if meta["accounting_profile"] == "REG34_ANNUAL" else None  # G93
    return PromotionResult("PROMOTED", "results_xbrl", message=fid, quarantined=qs + [x for x in (q, qa) if x])


def _insert_disclosures(con, stage_dir: Path, entity_id: str, visible: datetime) -> None:
    """disclosure_facts rows of a promoted filing [X116]: same entity and visibility as its other clean rows;
    deterministic keys, so a replay inserts nothing twice."""
    rows = read_table(con, stage_dir, "stg_disclosures")
    insert_rows(con, "disclosure_facts", [{**r, "entity_id": entity_id, "visible_from_ts": visible} for r in rows],
                or_ignore=True)  # fmt: skip


def _insert_audit_opinions(con, stage_dir: Path, entity_id: str, visible: datetime) -> None:
    """The audit_opinions row of a promoted results / annual filing [X121]: same entity and visibility as its other
    clean rows; deterministic id and key, so a replay inserts nothing twice."""
    rows = read_table(con, stage_dir, "stg_audit_opinions")
    insert_rows(con, "audit_opinions", [{**r, "entity_id": entity_id, "visible_from_ts": visible} for r in rows],
                or_ignore=True)  # fmt: skip


def _filing_check_rows(con, fid: str, exchange: str, entity_id: str, meta: dict, visible: datetime) -> list[dict]:
    """Non-blocking findings of filing_checks: Reg. 34 prior-year columns vs stored FY figures [G328, X110]; the
    in-filing BSE scrip code onto the matching NSE identifier rows [G79, X111]."""
    from financials import filing_checks as fc

    rows = []
    if meta["accounting_profile"] == "REG34_ANNUAL":
        diffs, ctx = fc.annual_prior_year_comparison(
            con, filing_id=fid, parser_version=meta["parser_version"], entity_id=entity_id, scope=meta["scope"],
            fy_start=meta["fy_start"], level_of_rounding=meta["level_of_rounding"], visible_from_ts=visible,
        )  # fmt: skip
        if diffs:
            details = {"scope": meta["scope"], "differences": diffs, **fc.prior_year_class(diffs, ctx)}  # X182
            rows.append(_quarantine_row(stage="CONSISTENCY", reason_code=fc.PRIOR_YEAR_REASON, filing_id=fid,
                                        entity_id=entity_id, details=details))  # fmt: skip
    code = fc.filed_scrip_code(con, fid)
    if exchange == "BSE":  # X265: BSE's own file states the code BSE lists; a different stored code is a finding
        conflicts = [
            {"security_id": sec, "valid_from": str(vf), "stored": old, "filed": code, "isin": meta["stated_isin"],
             "symbol": sym}
            for sec, vf, old, sym in con.execute(
                "SELECT h.security_id, h.valid_from, h.bse_scrip_code, h.symbol FROM security_identifier_history h "
                "JOIN securities s USING (security_id) WHERE s.entity_id = ? AND h.exchange <> 'BSE' AND h.isin = ? "
                "ORDER BY h.security_id, h.valid_from", [entity_id, meta["stated_isin"]]).fetchall()
            if code and fc.scrip_code(old) is not None and old != code
        ]  # fmt: skip
    else:
        conflicts = fc.apply_bse_scrip_code(con, exchange=exchange, entity_id=entity_id, isin=meta["stated_isin"],
                                            symbol=meta["stated_symbol"], code=code)  # fmt: skip
    for c in conflicts:
        rows.append(_quarantine_row(stage="IDENTIFIER", reason_code=fc.SCRIP_CONFLICT_REASON, filing_id=fid,
                                    entity_id=entity_id, security_id=c["security_id"], details=c))  # fmt: skip
    return rows


def filing_overrides(con, filing_id: str) -> dict[str, str]:
    """Latest value per field of the filing's OVERRIDE resolutions (append-only table; later rows win)."""
    rows = con.execute(
        "SELECT field, value FROM filing_overrides WHERE filing_id = ? ORDER BY created_at", [filing_id]
    ).fetchall()
    return dict(rows)


# X313: BSE results XBRL vaulted raw only before its form was proven (NBFC plain XML) keeps the raw-only category and
# no broadcast_ts in `filings` (append-only); the re-import that parses it stages the ledger's broadcast time, so its
# visibility sits in filing_meta (visible_from_source BROADCAST). Readers of results filings take both categories,
# and that broadcast time where the filings row has none.
RESULTS_FILING_CATEGORIES = ("RESULTS_XBRL", "BSE_RESULTS_XBRL")
RESULTS_CATEGORY_SQL = "f.category IN ('RESULTS_XBRL', 'BSE_RESULTS_XBRL')"
FILING_BROADCAST_SQL = (
    "coalesce(f.broadcast_ts, CASE WHEN f.category = 'BSE_RESULTS_XBRL' THEN (SELECT min(x.visible_from_ts) "
    "FROM filing_meta x WHERE x.filing_id = f.filing_id AND x.visible_from_source = 'BROADCAST') END)"
)
FILING_BROADCAST_SOURCE_SQL = (
    "CASE WHEN f.broadcast_ts IS NULL AND " + FILING_BROADCAST_SQL + " IS NOT NULL THEN 'API_CREATION' "
    "ELSE f.broadcast_ts_source END"
)


def filings_with_later_visibility(con) -> list[str]:
    """Promoted results filings whose current visibility rule [X83] gives a later time than their latest
    filing_meta row (backdated re-filings). `restage --category RESULTS_XBRL --visibility` re-parses these."""
    rows = con.execute(
        "SELECT m.filing_id, f.exchange, " + FILING_BROADCAST_SQL + ", f.source_url, m.board_meeting_end_ts, "
        "m.visible_from_ts FROM filing_meta m JOIN filings f USING (filing_id) WHERE "
        + RESULTS_CATEGORY_SQL
        + " AND m.parser_version = "
        "(SELECT arg_max(x.parser_version, " + version_key("x.parser_version") + ") FROM filing_meta x "
        "WHERE x.filing_id = m.filing_id) ORDER BY m.filing_id"
    ).fetchall()
    out = []
    for fid, exch, bts, url, board_end, current in rows:
        board_date = utc_to_ist_date(board_end) if board_end is not None else None
        visible, _ = _visible_from(con, exch, bts, board_end, board_date, url)
        if visible is not None and visible > current:
            out.append(fid)
    return out


def _link_revision(con, fid: str, entity_id: str, meta: dict, visible: datetime) -> None:
    """Revision chain [E9]: a filing supersedes the filings of the same entity, profile, scope and period end that
    became visible before it. Byte-identical blobs are RESENDs. Linking is order-independent: this filing is linked
    to the latest earlier-visible one, and the earliest later-visible one already promoted is linked to it, so the
    chain does not depend on which of the two was promoted first. Append-only link rows (a pair may also be linked
    across a gap when the middle filing arrives last; "supersedes" is transitive). Facts need nothing else, because
    every PIT read already takes the latest version visible at the as-of."""
    key = [entity_id, meta["accounting_profile"], meta["scope"], meta["period_end"], fid]
    base = ("SELECT m.filing_id, f.sha256 FROM filing_meta m JOIN filings f USING (filing_id) WHERE m.entity_id = ? "
            "AND m.accounting_profile = ? AND m.scope = ? AND m.period_end = ? AND m.filing_id <> ? ")  # fmt: skip
    prior = con.execute(
        base
        + "AND (m.visible_from_ts, m.filing_id) < (?, ?) ORDER BY m.visible_from_ts DESC, m.filing_id DESC LIMIT 1",
        [*key, visible, fid],
    ).fetchone()
    later = con.execute(
        base + "AND (m.visible_from_ts, m.filing_id) > (?, ?) ORDER BY m.visible_from_ts, m.filing_id LIMIT 1",
        [*key, visible, fid],
    ).fetchone()
    sha = con.execute("SELECT sha256 FROM filings WHERE filing_id = ?", [fid]).fetchone()[0]
    rows = []
    if prior is not None:
        rows.append((fid, prior[0], sha == prior[1]))
    if later is not None:
        rows.append((later[0], fid, sha == later[1]))
    if not rows:
        return
    insert_rows(
        con,
        "filing_revisions",
        [{"filing_id": new, "supersedes_filing_id": old, "entity_id": entity_id, "period_end": meta["period_end"],
          "scope": meta["scope"], "relation": "RESEND" if same else "REVISION"} for new, old, same in rows],
        or_ignore=True,
    )  # fmt: skip


def pit_fact(
    con, entity_id: str, scope: str, canonical_tag: str, period_start: date, period_end: date, as_of: datetime
) -> Decimal | None:
    """Point-in-time read: latest-visible value as known at `as_of` (architecture §6.3)."""
    row = con.execute(
        """SELECT coalesce(value_inr, value_other) FROM fact_observations
           WHERE entity_id = ? AND scope = ? AND canonical_tag = ? AND period_start = ? AND period_end = ?
             AND visible_from_ts <= ? AND """
        + CURRENT_VERSION
        + " ORDER BY visible_from_ts DESC, "
        + version_key()
        + " DESC LIMIT 1",
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


def share_disagreement(con, entity_id: str, as_of: date) -> dict | None:
    """Reg. 31 total shares vs results-derived paid-up / face value for the same date: the disagreement details, or
    None when they agree, partly-paid shares exist (paid-up / face value is then not a share count [X18]) or either
    side is missing. X103: shares held by an employee benefit trust are treasury shares under Ind AS 32, deducted
    from equity share capital but counted in the Reg. 31 total (EMPLOYEE_TRUSTS), so paid-up / face value may equal
    the total less those shares (101 open findings, 19 companies, matched exactly, live 2026-11-14)."""
    shp = con.execute(
        "SELECT o.shares, m.has_partly_paid, o.filing_id FROM shareholding_observations o "
        "JOIN shareholding_meta m USING (filing_id, parser_version) "
        "WHERE o.entity_id = ? AND o.as_of_date = ? AND o.category = 'TOTAL' "
        "ORDER BY o.visible_from_ts DESC, " + version_key("o.parser_version") + " DESC LIMIT 1",
        [entity_id, as_of],
    ).fetchone()
    # Every results filing of the latest visibility (standalone and consolidated can both state paid-up capital);
    # the worst disagreement is reported, so the outcome does not depend on row order.
    # X188: a count <= 0 is not a share count (paid-up capital tagged 0: ATLANTAELE Q1 FY27), as in features._preload.
    rows = con.execute(
        "SELECT value_other, filing_id, visible_from_ts FROM fact_observations WHERE entity_id = ? AND canonical_tag = "
        "'shares_from_paid_up' AND period_end = ? AND value_other > 0 AND "
        + CURRENT_VERSION
        + " QUALIFY visible_from_ts = max(visible_from_ts) OVER () ORDER BY filing_id",
        [entity_id, as_of],
    ).fetchall()
    if shp is None or not rows or shp[1]:
        return None
    shp_total = Decimal(shp[0])
    trust = con.execute(
        "SELECT max(shares) FROM shareholding_observations WHERE filing_id = ? AND category = 'EMPLOYEE_TRUSTS'",
        [shp[2]],
    ).fetchone()[0]
    totals = treasury_totals(con, shp[2], shp_total, trust)
    capital = _paid_up_capital(con, [f for _, f, _ in rows], as_of)
    events = _share_events_after(con, entity_id, as_of)
    worst = []
    for v, f, vis in rows:
        # X187: a split / bonus / consolidation with ex-date after the period end but before the results were
        # published is already in the results' face value (Ind AS 33.64 restates EPS too), not in the Reg. 31 total.
        # X211: or it is not: paid-up capital is a balance-sheet figure of the period end, so a filing (or a late
        # re-send of it) stating the period-end face value agrees with the unadjusted total (AJMERA Q2 FY26 re-sent
        # after its 1:5 split, Goldiam Q1 FY27 published before its 1:3 bonus went ex).
        mult = Decimal(1)
        for ex, eps_factor in events:
            if ex <= vis.date():
                mult /= eps_factor
        expected = [t * mult for t in totals] + (totals if mult != 1 else [])
        diff = min(abs(t - Decimal(v)) / t for t in expected)
        if diff > SHARE_CROSS_CHECK_TOLERANCE and _within_rounding(capital.get(f), expected):
            diff = Decimal(0)
        worst.append((diff, Decimal(v), f, vis))
    if max(worst)[0] > SHARE_CROSS_CHECK_TOLERANCE:
        # X212: paid-up / face value may be a genuine count of a later date (an allotment after the period end, at or
        # before the results); only the disagreeing filings are re-checked.
        for i, (d, v, f, vs) in enumerate(worst):
            if d > SHARE_CROSS_CHECK_TOLERANCE and _count_after_period_end(con, entity_id, as_of, v, vs):
                worst[i] = (Decimal(0), v, f, vs)
    diff, derived, res_filing, _ = max(worst)
    if diff <= SHARE_CROSS_CHECK_TOLERANCE:
        return None
    return {
        "as_of": as_of,
        "reg31_total": shp_total,
        "employee_trust_shares": Decimal(trust) if trust else None,
        "paid_up_over_face_value": derived,
        "relative_diff": diff,
        "shp_filing": shp[2],
        "results_filing": res_filing,
    }


TREASURY_TRUST_CATEGORY = "OTHER_NON_INSTITUTIONS"  # shareholding_major_holders rows of the "Others" axis [X213]


def treasury_totals(con, shp_filing: str, total: Decimal, employee_trusts) -> list[Decimal]:
    """The Reg. 31 total and the totals less the treasury shares it may contain. X103: shares of employee benefit
    trusts (category EMPLOYEE_TRUSTS). X213 TRUST_HOLDERS_OUTSIDE_EMPLOYEE_TRUSTS: trusts holding the company's own
    shares that the pattern names under non-institutions "Others" (the 'More than 1 percentage' rows of that axis);
    Ind AS 32 deducts them from equity share capital as well. Digispice Q4 FY25 results PDF note 6: paid-up capital
    7,008.69 lakhs, presented as 6,226.65 lakhs net of the shares of 'Independent Non Promoter Trust' and
    'Independent Non Promoter (Spice Employee Benefit) Trust' (15,912,776 + 10,155,067 shares of Rs 3 = 782.04
    lakhs). A total less these shares is a candidate only: it agrees only when paid-up / face value equals it
    within the 0.5% tolerance."""
    trusts = con.execute(
        "SELECT sum(shares) FROM (SELECT DISTINCT row_member, holder_name, shares FROM shareholding_major_holders "
        "WHERE filing_id = ? AND holder_category = ? AND regexp_matches(holder_name, '(?i)\\btrust\\b'))",
        [shp_filing, TREASURY_TRUST_CATEGORY],
    ).fetchone()[0]
    out = [total]
    both = (employee_trusts or 0) + (trusts or 0) if employee_trusts and trusts else 0
    for less in (employee_trusts, trusts, both):
        if less and Decimal(less) < total and total - Decimal(less) not in out:
            out.append(total - Decimal(less))
    return out


def _count_after_period_end(con, entity_id: str, as_of: date, derived: Decimal, visible: datetime) -> bool:
    """X212 ALLOTMENT_BEFORE_RESULTS: a results filing may state paid-up capital after an allotment made after the
    period end, at or before the board meeting that approved the results. Selan Q1 FY26: XBRL paid-up 35.16 Cr =
    35,162,358 shares of Rs 10 after the allotment of 19,962,358 shares under its scheme of arrangement at the
    results meeting of 12-Aug-2025 (Reg. 31 of that date), while the PDF prints the period-end 15.20 Cr. True when
    paid-up / face value agrees (0.5%) with NSE's Issue Size (PR-zip) of the entity's EQ / BE / BZ securities on a
    trading day from the last file on or before the period end through the results' visibility date, or with a Reg. 31
    total dated after the period end and on or before that date (allotment-dated patterns: Orchid Pharma's re-filed
    Q4 FY26 of 14-Aug-2026 after the allotment of 1-Aug-2026), or the first one dated after it. Market cap keeps the
    period end's Reg. 31 total."""
    tol = float(SHARE_CROSS_CHECK_TOLERANCE)
    issue = con.execute(
        "SELECT count(*) FROM raw_nse_mcap m JOIN security_identifier_history h ON h.exchange = m.exchange "
        "AND h.symbol = m.symbol AND h.series = m.series AND h.valid_from <= m.trade_date "
        "AND (h.valid_to IS NULL OR h.valid_to > m.trade_date) JOIN securities s ON s.security_id = h.security_id "
        "WHERE s.entity_id = ? AND m.series IN (SELECT unnest(?)) AND m.trade_date <= ? AND m.trade_date >= "
        "(SELECT coalesce(max(trade_date), CAST(? AS DATE)) FROM raw_nse_mcap WHERE trade_date <= ?) "
        "AND abs(CAST(m.issue_size AS DOUBLE) - ?) <= ? * ?",
        [entity_id, sorted(UNIVERSE_SERIES), visible.date(), as_of, as_of, float(derived), tol, float(derived)],
    ).fetchone()[0]
    if issue:
        return True
    later = con.execute(
        "SELECT as_of_date, shares FROM shareholding_observations WHERE entity_id = ? AND category = 'TOTAL' "
        "AND as_of_date > ? AND shares > 0 QUALIFY row_number() OVER (PARTITION BY as_of_date ORDER BY visible_from_ts "
        "DESC, " + version_key("parser_version") + " DESC) = 1 ORDER BY as_of_date",
        [entity_id, as_of],
    ).fetchall()
    # every Reg. 31 dated up to the results' visibility (allotment-dated patterns, SHP17), and the first one after
    near = [s for d, s in later if d <= visible.date()] + [s for d, s in later if d > visible.date()][:1]
    return any(abs(Decimal(s) - derived) / Decimal(s) <= SHARE_CROSS_CHECK_TOLERANCE for s in near)


SHARE_COUNT_ACTIONS = ("SPLIT", "BONUS", "CONSOLIDATION")


def _share_events_after(con, entity_id: str, as_of: date) -> list[tuple[date, Decimal]]:
    """(ex-date, EPS factor) of the entity's split / bonus / consolidation actions with ex-date after `as_of`
    [X187]. PENDING counts as well as the accepted statuses: the action is NSE's own record, and it only explains a
    disagreement when its factor reproduces paid-up / face value exactly (within the 0.5% tolerance)."""
    return [
        (ex, Decimal(str(ef)))
        for ex, ef in con.execute(
            # a PENDING action has no eps_factor yet: the theoretical one from its ratio (corp_actions.py)
            "SELECT ex_date, ef FROM (SELECT ca.ex_date, coalesce(ca.eps_factor, CASE WHEN ca.action_type = 'BONUS' "
            "THEN ca.ratio_den / (ca.ratio_num + ca.ratio_den) ELSE ca.ratio_num / ca.ratio_den END) AS ef "
            "FROM corp_actions ca JOIN securities s USING (security_id) "
            "WHERE coalesce(ca.entity_id, s.entity_id) = ? AND ca.ex_date > ? "
            "AND ca.action_type IN (SELECT unnest(?)) AND ca.status IN (SELECT unnest(?))) WHERE ef > 0 ORDER BY 1",
            [entity_id, as_of, list(SHARE_COUNT_ACTIONS), sorted(ACCEPTED_STATUSES | {"PENDING"})],
        ).fetchall()
    ]


def _paid_up_capital(con, filing_ids: list[str], as_of: date) -> dict[str, tuple[Decimal, Decimal, str]]:
    """{filing_id: (paid-up capital, face value, LevelOfRounding)} of the results filings at `as_of` that state every
    rupee figure in whole LevelOfRounding units (no canonical rupee fact with digits below the unit) [X188]."""
    units = " ".join(f"WHEN '{k}' THEN {int(v)}" for k, v in ROUNDING_UNITS.items())
    whole = {
        fid
        for fid, n, off in con.execute(
            "SELECT o.filing_id, count(*), count(*) FILTER (WHERE o.value_inr % (CASE m.level_of_rounding "
            + units
            + " ELSE 1 END) <> 0) FROM fact_observations o JOIN filing_meta m USING (filing_id, parser_version) "
            "WHERE o.filing_id IN (SELECT unnest(?)) AND o.value_inr IS NOT NULL AND o.value_inr <> 0 "
            "AND NOT (starts_with(o.canonical_tag, 'li_') OR starts_with(o.canonical_tag, 'oth_') "
            "OR starts_with(o.canonical_tag, 'asfiled_')) GROUP BY 1",
            [filing_ids],
        ).fetchall()
        if n and not off
    }
    out = {}
    for fid, paid, face, lor in con.execute(
        "SELECT o.filing_id, "
        "max(coalesce(o.value_inr, o.value_other)) FILTER (WHERE o.canonical_tag = 'paid_up_equity_capital'), "
        "max(coalesce(o.value_other, o.value_inr)) FILTER (WHERE o.canonical_tag = 'face_value_per_share'), "
        "any_value(m.level_of_rounding) "
        "FROM fact_observations o JOIN filing_meta m USING (filing_id, parser_version) "
        "WHERE o.filing_id IN (SELECT unnest(?)) AND o.period_end = ? "
        "AND o.canonical_tag IN ('paid_up_equity_capital', 'face_value_per_share') GROUP BY 1",
        [filing_ids, as_of],
    ).fetchall():
        if paid is not None and face and fid in whole:
            out[fid] = (Decimal(paid), Decimal(face), lor)
    return out


def _within_rounding(capital: tuple[Decimal, Decimal, str] | None, totals: list[Decimal]) -> bool:
    """X188: in a filing that states every rupee figure in whole LevelOfRounding units, paid-up capital was rounded to
    that unit, so shares x face value need only agree with it to half a unit (Navneet Q1 FY26 consolidated, whole
    crores: 221,213,181 x Rs 2 = 44.24 Cr filed as 44 Cr). A filing with digits below the unit states its own
    precision and keeps the 0.5% relative test (Rallis 19.00 Cr in a 2-decimal filing; Lux 6.26 vs 6.01 Cr)."""
    if capital is None or capital[2] not in ROUNDING_UNITS:
        return False
    paid, face, lor = capital
    unit = ROUNDING_UNITS[lor]
    return paid % unit == 0 and any(abs(t * face - paid) <= unit / 2 for t in totals)


def cross_check_shares(con, entity_id: str, as_of: date) -> str | None:
    """Quarantine id when Reg. 31 total shares and paid-up / face value disagree (share_disagreement), else None."""
    details = share_disagreement(con, entity_id, as_of)
    if details is None:
        return None
    return _quarantine(con, stage="SHARES", reason_code="CROSS_CHECK_FAILED", entity_id=entity_id, details=details)


def annual_share_check(con, filing_id: str, entity_id: str, meta: dict) -> str | None:
    """G93 [X114]: non-blocking ANNUAL_SHARE_COUNT_DIFFERS finding when a Reg. 34 filing's year-end share counts
    disagree with the Reg. 31 total or paid-up / face value of the same date (share_capital.py)."""
    from financials.share_capital import REASON, annual_share_disagreement

    details = annual_share_disagreement(con, filing_id, entity_id, meta["fy_end"])
    if details is None:
        return None
    return _quarantine(con, stage="SHARES", reason_code=REASON, entity_id=entity_id, filing_id=filing_id,
                       details=details)  # fmt: skip


def close_resolved_share_findings(con) -> int:
    """Re-run the share cross-check for every open CROSS_CHECK_FAILED finding and close those that now agree (a
    later rule such as X103, or a corrected filing). Returns how many were closed."""
    rows = con.execute(
        "SELECT quarantine_id, entity_id, CAST(json_extract_string(details, '$.as_of') AS DATE) "
        "FROM quarantine_queue WHERE reason_code = 'CROSS_CHECK_FAILED' AND resolved_at IS NULL"
    ).fetchall()
    fixed = [q for q, ent, as_of in rows if ent is not None and share_disagreement(con, ent, as_of) is None]
    if fixed:
        con.execute(
            "UPDATE quarantine_queue SET resolved_at = ?, resolution = 'FIXED_BY_RULE', resolution_note = "
            "'share cross-check agrees on re-check (X103 / X213 trust shares, X187 / X211 share-count event, "
            "X188 rounding, X212 allotment before the results)' "
            "WHERE quarantine_id IN (SELECT unnest(?))",
            [utc_now(), fixed],
        )
    return len(fixed)


ANNUAL_RECHECK_NOTE = "annual re-check [X180]: "


def audit_annual_checks(con, entity_ids=None) -> dict[str, int]:
    """X180: re-run the two Reg. 34 annual checks (G328 prior-year columns [X110, X182]; G93 year-end share counts
    [X114, X181]) for every promoted annual filing on the data now stored. Both run only at promotion, so their
    outcome depended on what had been promoted before (an FY26 annual promoted before the FY25 annual or the FY-end
    Reg. 31 filing of the same company compared against less, and annuals promoted before the checks existed were
    never checked). The checks are point-in-time (prior year: what a reader had one microsecond before the annual
    became visible), so a re-run gives the answer promotion in broadcast order would have given. New findings are
    queued (deterministic ids: an unchanged finding, or one a human resolved, is kept as it is); an open finding of
    the same reason and filing that the re-run no longer produces is closed FIXED_BY_RULE. Returns counts.
    `entity_ids`: re-run only those entities' annuals (X235: after rule X201 rescaled one of their filings).
    X312: in the same write, open findings of an owner-accepted class, or with the same totals as an earlier
    ACCEPTED finding of the filing, are resolved ACCEPTED (`accept_prior_year_findings`); they stay visible."""
    from financials import filing_checks as fc
    from financials.share_capital import REASON as SHARE_REASON
    from financials.share_capital import annual_share_disagreement

    metas = con.execute(
        "SELECT filing_id, parser_version, entity_id, scope, fy_start, fy_end, level_of_rounding, visible_from_ts "
        "FROM filing_meta WHERE accounting_profile = 'REG34_ANNUAL' QUALIFY row_number() OVER (PARTITION BY "
        "filing_id ORDER BY " + version_key() + " DESC) = 1 ORDER BY filing_id"
    ).fetchall()
    if entity_ids is not None:
        wanted = set(entity_ids)
        metas = [m for m in metas if m[2] in wanted]
    rows, prior = [], []
    for fid, pv, ent, scope, fy_start, fy_end, lor, visible in metas:
        diffs, ctx = fc.annual_prior_year_comparison(
            con, filing_id=fid, parser_version=pv, entity_id=ent, scope=scope, fy_start=fy_start,
            level_of_rounding=lor, visible_from_ts=visible,
        )  # fmt: skip
        if diffs:
            details = {"scope": scope, "differences": diffs, **fc.prior_year_class(diffs, ctx)}
            rows.append(_quarantine_row(stage="CONSISTENCY", reason_code=fc.PRIOR_YEAR_REASON, filing_id=fid,
                                        entity_id=ent, details=details))  # fmt: skip
            prior.append((rows[-1]["quarantine_id"], fid, details, ctx))
        share = annual_share_disagreement(con, fid, ent, fy_end)
        if share is not None:
            rows.append(_quarantine_row(stage="SHARES", reason_code=SHARE_REASON, entity_id=ent, filing_id=fid,
                                        details=share))  # fmt: skip
    keep = [r["quarantine_id"] for r in rows]
    if rows:
        _quarantine_many(con, rows)
    closed = con.execute(
        "UPDATE quarantine_queue SET resolved_at = ?, resolution = 'FIXED_BY_RULE', resolution_note = ? || "
        "CASE WHEN reason_code = ? THEN 'prior-year comparison re-run: none, or the current finding of this filing'"
        " ELSE 'share counts re-run: they agree, or the current finding of this filing' END "
        "WHERE resolved_at IS NULL AND reason_code IN (?, ?) AND filing_id IN (SELECT unnest(?)) "
        "AND quarantine_id NOT IN (SELECT unnest(?)) RETURNING reason_code",
        [utc_now(), ANNUAL_RECHECK_NOTE, fc.PRIOR_YEAR_REASON, fc.PRIOR_YEAR_REASON, SHARE_REASON,
         [m[0] for m in metas], keep],
    ).fetchall()  # fmt: skip
    accepted = accept_prior_year_findings(con, prior)  # X312, after the insert: also an unchanged open finding
    open_now = dict(con.execute(
        "SELECT reason_code, count(*) FROM quarantine_queue WHERE resolved_at IS NULL AND reason_code IN (?, ?) "
        "GROUP BY 1", [fc.PRIOR_YEAR_REASON, SHARE_REASON]).fetchall())  # fmt: skip
    return {"annual_filings": len(metas), "findings": len(rows), "closed": len(closed), **accepted,
            "open_prior_year": open_now.get(fc.PRIOR_YEAR_REASON, 0),
            "open_share_counts": open_now.get(SHARE_REASON, 0)}  # fmt: skip


def accept_prior_year_findings(con, findings: list[tuple[str, str, dict, dict]]) -> dict[str, int]:
    """X312: resolve ACCEPTED, in one batched write, the open findings among `findings` (id, filing_id, details,
    comparison context) that rule PRIOR_YEAR_ACCEPTED_CLASS (owner-accepted class / sub-class) or
    PRIOR_YEAR_ACCEPTANCE_CARRIED (same totals as an earlier ACCEPTED finding of the filing) settles. One read of the
    earlier ACCEPTED findings of these filings; a finding already resolved (by a human or an earlier run) is kept as
    it is, so a re-run changes nothing. Returns counts by rule."""
    from financials import filing_checks as fc

    if not findings:
        return {"accepted_by_class": 0, "accepted_carried": 0}
    earlier = [(q, f, json.loads(d)) for q, f, d in con.execute(
        "SELECT quarantine_id, filing_id, details FROM quarantine_queue WHERE reason_code = ? AND resolution = "
        "'ACCEPTED' AND filing_id IN (SELECT unnest(?)) ORDER BY resolved_at DESC, quarantine_id",
        [fc.PRIOR_YEAR_REASON, sorted({f for _, f, _, _ in findings})]).fetchall()]  # fmt: skip
    notes = fc.prior_year_resolutions(findings, earlier)
    done = []
    if notes:
        done = con.execute(
            "UPDATE quarantine_queue AS q SET resolved_at = $1, resolution = 'ACCEPTED', resolution_note = v.note "
            "FROM (SELECT unnest($2) AS id, unnest($3) AS note) AS v WHERE q.quarantine_id = v.id "
            "AND q.resolved_at IS NULL RETURNING q.resolution_note",
            [utc_now(), list(notes), list(notes.values())],
        ).fetchall()
    carried = sum(1 for (n,) in done if fc.CARRIED_RULE in n)
    return {"accepted_by_class": len(done) - carried, "accepted_carried": carried}


def close_resolved_annual_share_findings(con) -> int:
    """X180 / X181: re-run the annual share-count check for every open ANNUAL_SHARE_COUNT_DIFFERS finding and close
    those that now agree (typically the FY-end Reg. 31 filing was promoted after the annual). Cheap: open findings
    only; run after every promote batch like close_resolved_share_findings."""
    from financials.share_capital import REASON as SHARE_REASON
    from financials.share_capital import annual_share_disagreement

    rows = con.execute(
        "SELECT quarantine_id, filing_id, entity_id, CAST(json_extract_string(details, '$.as_of') AS DATE) "
        "FROM quarantine_queue WHERE reason_code = ? AND resolved_at IS NULL",
        [SHARE_REASON],
    ).fetchall()
    fixed = [
        q for q, fid, ent, as_of in rows if ent and fid and annual_share_disagreement(con, fid, ent, as_of) is None
    ]
    if fixed:
        con.execute(
            "UPDATE quarantine_queue SET resolved_at = ?, resolution = 'FIXED_BY_RULE', resolution_note = ? "
            "WHERE quarantine_id IN (SELECT unnest(?))",
            [utc_now(), ANNUAL_RECHECK_NOTE + "annual share counts agree on re-check (X181)", fixed],
        )
    return len(fixed)


SHP_PARSE_FINDINGS = ("PARSE_ERROR", "CONTEXT_CONFLICT", "MISSING_CRITICAL", "PCT_SCALE_UNKNOWN", "UNKNOWN_TAXONOMY")
FILING_FINDING_STAGES = ("PARSE", "IDENTITY", "PERIOD")


def _close_shp_parse_findings(con, filing_id: str, note: str) -> None:
    """A re-parse (new parser_version) of the same filing that now parses closes its open parse findings."""
    con.execute(
        "UPDATE quarantine_queue SET resolved_at = ?, resolution = 'FIXED_BY_RULE', resolution_note = ? "
        f"WHERE filing_id = ? AND resolved_at IS NULL AND reason_code IN {SHP_PARSE_FINDINGS}",
        [utc_now(), note, filing_id],
    )


WRONG_TEMPLATE_RULE = "WRONG_TEMPLATE_DUPLICATE"
WRONG_TEMPLATE_NS = "IntegratedFinance_OtherThanBank"


def wrong_template_keys(data: bytes) -> tuple[str | None, str | None, date | None]:
    """(ISIN, scope, period end) a wrong-template filing states, read from its vault blob (any context, as the
    file sends them; no clean row exists for a quarantined filing). Raises ParseError on a file that does not parse."""
    from financials.parsers.xbrl import parse_instance

    vals: dict[str, set[str]] = {"ISIN": set(), "NatureOfReportStandaloneConsolidated": set(),
                                 "DateOfEndOfReportingPeriod": set()}  # fmt: skip
    for f in parse_instance(data).facts:
        if f.name in vals and f.value_text.strip():
            vals[f.name].add(f.value_text.strip())
    isin, scope, pe = (max(vals[k]) if vals[k] else None for k in vals)
    try:
        end = date.fromisoformat(pe) if pe else None
    except ValueError:
        end = None
    return isin, scope.upper() if scope else None, end


def close_wrong_template_duplicates(con, vault) -> int:
    """Rule WRONG_TEMPLATE_DUPLICATE [X89]: an Ind AS company that first files its results on the non-Ind AS
    template (SEBI `IntegratedFinance_OtherThanBank` taxonomy: ExtraordinaryItems, ...BeforeMinorityInterest) and
    then on the Ind AS template for the same entity, scope and period end. The UNKNOWN_TAXONOMY finding of the
    wrong-template filing is closed once such a promoted filing exists, whichever arrived first (Aarti, Kansai,
    KIMS, MRPL, Rajesh Exports). Without one (L&T Q4 FY25) it stays open. Run once per promote batch. The
    wrong-template filing's ISIN, scope and period end come from its vault blob (decision J: no raw table); a blob
    that cannot be read leaves its finding open."""
    from financials.parsers import ParseError

    found = con.execute(
        f"""SELECT q.quarantine_id, b.storage_path, b.sha256
            FROM quarantine_queue q JOIN filings f USING (filing_id) JOIN blobs b USING (sha256)
            WHERE q.stage = 'PARSE' AND q.reason_code = 'UNKNOWN_TAXONOMY' AND q.resolved_at IS NULL
              AND json_extract_string(q.details, '$.entity_namespace') LIKE '%{WRONG_TEMPLATE_NS}%'
            ORDER BY 1"""
    ).fetchall()
    keys = []
    for qid, path, sha in found:
        try:
            keys.append((qid, *wrong_template_keys(vault.read_path(path, sha))))
        except (OSError, RuntimeError, ParseError):
            continue
    if not keys:
        return 0
    import pyarrow as pa

    con.register(
        "_wt",
        pa.table(
            {
                "quarantine_id": [k[0] for k in keys],
                "isin": [k[1] for k in keys],
                "scope": [k[2] for k in keys],
                "pe": pa.array([k[3] for k in keys], pa.date32()),
            }
        ),
    )
    try:
        rows = con.execute(
            """SELECT wt.quarantine_id, min(m.filing_id)
               FROM _wt wt JOIN security_identifier_history h ON h.isin = wt.isin
               JOIN securities s ON s.security_id = h.security_id
               JOIN filing_meta m ON m.entity_id = s.entity_id AND m.scope = wt.scope
                                  AND m.period_end = wt.pe AND m.accounting_profile <> 'REG34_ANNUAL'
               GROUP BY wt.quarantine_id"""
        ).fetchall()
    finally:
        con.unregister("_wt")
    if rows:
        con.execute(
            "UPDATE quarantine_queue SET resolved_at = $1, resolution = 'FIXED_BY_RULE', resolution_note = $2 || "
            "c.correct || ' for the same entity, scope, period' "
            "FROM (SELECT unnest($3) AS qid, unnest($4) AS correct) c WHERE quarantine_id = c.qid",
            [utc_now(), f"X89 {WRONG_TEMPLATE_RULE}: Ind AS filing ", [q for q, _ in rows], [c for _, c in rows]],
        )
    return len(rows)


def _close_filing_findings(con, filing_id: str, note: str, keep: list[str] | None = None) -> None:
    """A results filing that now promotes (or is now known to be out of scope) closes the open parse, identity and
    period findings an earlier parser_version raised for it, except the non-blocking findings this promotion raises
    again (`keep`). Share cross-checks (stage SHARES) are untouched."""
    keep = keep or [""]
    con.execute(
        "UPDATE quarantine_queue SET resolved_at = ?, resolution = 'FIXED_BY_RULE', resolution_note = ? "
        f"WHERE filing_id = ? AND resolved_at IS NULL AND stage IN {FILING_FINDING_STAGES} "
        f"AND quarantine_id NOT IN ({', '.join('?' * len(keep))})",
        [utc_now(), note, filing_id, *keep],
    )


def _promote_shareholding(con, stage_dir: Path, manifest: dict[str, Any]) -> PromotionResult:
    staged_meta = read_table(con, stage_dir, "stg_shp_meta")
    if staged_meta and not financials_in_scope(staged_meta[0]["as_of_date"]):
        res = _out_of_scope(
            con, stage_dir, "shareholding", f"as of {staged_meta[0]['as_of_date']} < {MIN_PERIOD_END_DATE}"
        )
        _close_shp_parse_findings(con, staged_meta[0]["filing_id"],
                                  f"parser {staged_meta[0]['parser_version']}: parses, out of scope [C9]")  # fmt: skip
        return res
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
    # A BSE filing (Permitted member, X166) resolves by ISIN through the NSE identifier rows of the same security:
    # identifier history holds NSE rows only (a BSE-only company needs its own rows first, owner to-do 31).
    ix = "NSE" if filing["exchange"] == "BSE" else filing["exchange"]
    secs = resolve_security_by_isin(con, ix, meta["stated_isin"], meta["as_of_date"])
    if not secs:
        secs = resolve_isin_typo(con, ix, meta["stated_isin"], meta["stated_symbol"], meta["as_of_date"], fid)
        secs = secs or resolve_unregistered_isin(con, ix, meta["stated_isin"], meta["stated_symbol"],
                                                 meta.get("company_name"), meta["as_of_date"], fid)  # fmt: skip
        secs = secs or resolve_isin_one_char(con, ix, meta["stated_isin"], meta["stated_symbol"],
                                             meta.get("company_name"), meta["as_of_date"], fid)  # fmt: skip
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
    earlier = con.execute(
        "SELECT entity_id, min(visible_from_ts) FROM shareholding_meta WHERE filing_id = ? GROUP BY 1", [fid]
    ).fetchall()
    for ent, ts in [*earlier, (entity_id, visible)]:
        dirty.mark_visible(con, ent, min(ts, visible), "SHAREHOLDING", fid)
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
    _insert_disclosures(con, stage_dir, entity_id, visible)  # X116
    _close_shp_parse_findings(con, fid, f"parser {meta['parser_version']}: {meta.get('rules_applied') or 'parses'}")
    q = cross_check_shares(con, entity_id, meta["as_of_date"])
    return PromotionResult("PROMOTED", "shareholding", message=fid, quarantined=[q] if q else [])


def _promote_vault_and_raw(con, stage_dir: Path, manifest: dict[str, Any]) -> PromotionResult:
    """Raw-only feeds (index closes [IDX9], equity master [IDX10]): vault rows + the raw table, append-only."""
    tables = {"index_close": "index_ohlcv", "equity_master": "raw_equity_master"}
    _insert_vault_rows(con, stage_dir, ("blobs", "filings", tables[manifest["job"]]))
    return PromotionResult("PROMOTED", manifest["job"], message=manifest.get("trade_date") or manifest["snapshot_date"])


def _promote_mcap_day(con, stage_dir: Path, manifest: dict[str, Any]) -> PromotionResult:
    """NSE PR-zip mcap file [X130-X133]: vault rows + raw_nse_mcap, append-only. Out of scope before MIN_TRADE_DATE
    (C9). G1: the file's EQ / BE / BZ rows must be at least G1_MIN_RATIO x the median of the previous G1_LOOKBACK_DAYS
    promoted files (the parser has already checked the rows against the file's own summary sums)."""
    day = date.fromisoformat(manifest["trade_date"])
    if not market_in_scope(day):
        return _out_of_scope(con, stage_dir, "mcap_day", f"trade_date {day} < {MIN_TRADE_DATE}")
    path = (Path(stage_dir) / "raw_nse_mcap.parquet").as_posix()
    n = con.execute(
        "SELECT count(*) FROM read_parquet(?) WHERE series IN (SELECT unnest(?))", [path, list(UNIVERSE_SERIES)]
    ).fetchone()[0]
    prior = [c for (c,) in con.execute(
        "SELECT count(DISTINCT (symbol, series)) FROM raw_nse_mcap WHERE trade_date < ? "
        "AND series IN (SELECT unnest(?)) GROUP BY trade_date ORDER BY trade_date DESC LIMIT ?",
        [day, list(UNIVERSE_SERIES), G1_LOOKBACK_DAYS],
    ).fetchall()]  # fmt: skip
    if prior and Decimal(n) < G1_MIN_RATIO * Decimal(statistics.median(prior)):
        raise GateFailure("G1", f"{n} EQ/BE/BZ mcap rows < {G1_MIN_RATIO} x median {statistics.median(prior)}")
    _insert_vault_rows(con, stage_dir, ("blobs", "filings", "raw_nse_mcap"))
    # Rule SHARES_REG31_OUTLIER [X221] reads Issue Size: rows from this day on (up to features.ISSUE_SIZE_MAX_AGE_DAYS
    # later) may change share count; marked like a market day.
    dirty.mark_all(con, day, "MCAP_DAY", read_table(con, stage_dir, "filings")[0]["filing_id"])
    return PromotionResult("PROMOTED", "mcap_day", message=f"{day}: {n} EQ/BE/BZ rows")


def _promote_bse_securities(con, stage_dir: Path, manifest: dict[str, Any]) -> PromotionResult:
    """BSE list of securities [A17, X169]: vault rows + raw_bse_securities (append-only), then rule BSE1 fills
    `bse_scrip_code` by ISIN on the identifier rows valid on the observed date; a different stored code is a
    non-blocking IDENTIFIER / BSE_SCRIP_CODE_CONFLICT finding, nothing is overwritten."""
    from financials import filing_checks as fc

    _insert_vault_rows(con, stage_dir, ("blobs", "filings", "raw_bse_securities"))
    fid = read_table(con, stage_dir, "filings")[0]["filing_id"]
    filled, conflicts = fc.apply_bse_scrip_codes_by_isin(con, fid)
    q = _quarantine_many(con, [
        _quarantine_row(stage="IDENTIFIER", reason_code=fc.SCRIP_CONFLICT_REASON, filing_id=fid,
                        security_id=c["security_id"], details=c) for c in conflicts
    ]) if conflicts else []  # fmt: skip
    n = con.execute("SELECT count(*) FROM raw_bse_securities WHERE filing_id = ?", [fid]).fetchone()[0]
    return PromotionResult("PROMOTED", "bse_securities", message=f"{manifest['snapshot_date']}: {n} securities, "
                           f"{filled} identifier rows given a BSE scrip code (BSE1)", quarantined=q)  # fmt: skip


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
    first: dict[str, date] = {}
    for g in good:
        first[g["entity_id"]] = min(first.get(g["entity_id"], date.max), utc_to_ist_date(g["visible_from_ts"]))
    dirty.mark(con, first, "KPI", filing["filing_id"])
    return PromotionResult("PROMOTED", "kpis", message=f"{len(good)} KPI rows", quarantined=quarantined)


CLASSIFICATION_SOURCE = "NSE_QUOTE"


def _promote_classification(con, stage_dir: Path, manifest: dict[str, Any]) -> PromotionResult:
    """NSE quote classification [IC1-IC3]: raw row as sent, then the entity's date-bounded history. The answer has
    no effective date, so an interval starts on the IST date it was observed and is visible from the fetch. The same
    answer again extends nothing (idempotent); a different one closes the open interval on its observation date. An
    answer older than the open interval, or a second different answer on the same date, changes no history and is
    quarantined (CLASSIFICATION_CONFLICT) for a human."""
    _insert_vault_rows(con, stage_dir, ("blobs", "filings", "raw_quote_classification"))
    filing = read_table(con, stage_dir, "filings")[0]
    r = read_table(con, stage_dir, "raw_quote_classification")[0]
    fid, on = filing["filing_id"], r["observed_date"]
    secs, method = resolve_corp_action_security(con, filing["exchange"], r["isin"], r["symbol"], on)
    ents = sorted({e for (e,) in con.execute(
        "SELECT DISTINCT entity_id FROM securities WHERE security_id IN (SELECT unnest(?))", [secs]
    ).fetchall()})  # fmt: skip
    details = {"symbol": r["symbol"], "isin": r["isin"], "observed": on}
    if len(ents) != 1:
        q = _quarantine(con, stage="CLASSIFICATION", reason_code=method if not ents else "AMBIGUOUS_SECURITY",
                        filing_id=fid, details=details)  # fmt: skip
        return PromotionResult("QUARANTINED", "classification", message=r["symbol"], quarantined=[q])
    ent = ents[0]
    levels = (r["macro"], r["sector"], r["industry"], r["basic_industry"])
    if all(v is None for v in levels):
        return PromotionResult("PROMOTED", "classification", message=f"{r['symbol']}: no classification in answer")
    cur = con.execute(
        "SELECT macro, sector, industry, basic_industry, valid_from FROM entity_classification_history "
        "WHERE entity_id = ? AND source = ? AND valid_to IS NULL", [ent, CLASSIFICATION_SOURCE]).fetchone()  # fmt: skip
    if cur is not None and tuple(cur[:4]) == levels:
        return PromotionResult("PROMOTED", "classification", message=f"{r['symbol']}: unchanged since {cur[4]}")
    if cur is not None and on <= cur[4]:
        q = _quarantine(con, stage="CLASSIFICATION", reason_code="CLASSIFICATION_CONFLICT", entity_id=ent,
                        filing_id=fid, details={**details, "open_from": cur[4], "open": list(cur[:4]),
                                                "answer": list(levels)})  # fmt: skip
        return PromotionResult("QUARANTINED", "classification", message=r["symbol"], quarantined=[q])
    if cur is not None:
        con.execute(
            "UPDATE entity_classification_history SET valid_to = ? WHERE entity_id = ? AND source = ? "
            "AND valid_to IS NULL", [on, ent, CLASSIFICATION_SOURCE])  # fmt: skip
    insert_rows(con, "entity_classification_history", [{
        "entity_id": ent, "source": CLASSIFICATION_SOURCE, "macro": levels[0], "sector": levels[1],
        "industry": levels[2], "basic_industry": levels[3], "valid_from": on, "valid_to": None,
        "visible_from_ts": filing["fetched_at"], "evidence_filing_id": fid}])  # fmt: skip
    # Peer columns are cross-sectional: every company of the day reads this entity's industry.
    dirty.mark_all(con, on, "CLASSIFICATION", fid)
    return PromotionResult("PROMOTED", "classification", message=f"{r['symbol']}: {' / '.join(map(str, levels))}")


def _promote_raw_only(con, stage_dir: Path, manifest: dict[str, Any]) -> PromotionResult:
    _insert_vault_rows(con, stage_dir, ("blobs", "filings", "raw_results_listing"))
    return PromotionResult("PROMOTED", "raw_only", message=read_table(con, stage_dir, "filings")[0]["category"])


# ── Reg. 30 structured events [E1-E7] ──────────────────────────────────────


def _promote_reg30_event(con, stage_dir: Path, manifest: dict[str, Any]) -> PromotionResult:
    _insert_vault_rows(con, stage_dir, ("blobs", "filings"))
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
    _insert_disclosures(con, stage_dir, entities[0], filing["broadcast_ts"])  # X116
    dirty.mark_visible(con, entities[0], filing["broadcast_ts"], "REG30_EVENT", fid)
    return PromotionResult("PROMOTED", "reg30_event", message=fid)
