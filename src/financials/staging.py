"""Staging: fetch/parse jobs write immutable Parquet batches; they never touch market.duckdb.

A stage directory is `<stage_root>/<job>/<run_id>/` containing one Parquet file per table and
`manifest.json`. Batches are written to a temp dir and renamed into place, so a reader sees a
whole batch or nothing. Staging uses an in-memory DuckDB with the real schema, so types and
foreign keys inside a batch are checked before the promoter ever sees it.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import asdict
from datetime import datetime, time
from pathlib import Path
from typing import Any

from financials import PARSER_VERSION
from financials.db import apply_schema, connect, fetch_dicts, insert_rows
from financials.ids import stable_id
from financials.money import to_inr
from financials.parsers import ParseError
from financials.parsers.delivery import parse_sec_bhavdata_full
from financials.parsers.integrated import parse_integrated_results
from financials.parsers.nse_corp_actions import PURPOSE_RULES_VERSION, parse_nse_corp_actions_json
from financials.parsers.udiff import parse_udiff_cm
from financials.parsers.xbrl import parse_instance
from financials.timeutil import ist_to_utc
from financials.vault import Blob, Filing, Vault, make_filing

STAGING_SCHEMA = """
CREATE TABLE stg_xbrl_filing (
    filing_id VARCHAR PRIMARY KEY, parser_version VARCHAR NOT NULL, accounting_profile VARCHAR NOT NULL,
    taxonomy_ns VARCHAR NOT NULL, scope VARCHAR NOT NULL, level_of_rounding VARCHAR NOT NULL,
    fy_start DATE NOT NULL, fy_end DATE NOT NULL, period_end DATE NOT NULL, reporting_quarter VARCHAR,
    audited BOOLEAN, board_meeting_end_ts TIMESTAMP, interest_paid_cfo_class VARCHAR,
    interest_recd_cfo_class VARCHAR, stated_isin VARCHAR, stated_symbol VARCHAR, company_name VARCHAR,
    stated_cin VARCHAR, auditor_qualified BOOLEAN, audit_opinion VARCHAR
);
CREATE TABLE stg_xbrl_facts (
    filing_id VARCHAR NOT NULL, parser_version VARCHAR NOT NULL, scope VARCHAR NOT NULL,
    canonical_tag VARCHAR NOT NULL, period_type VARCHAR NOT NULL, period_start DATE NOT NULL,
    period_end DATE NOT NULL, period_months INTEGER, unit VARCHAR NOT NULL, value_inr DECIMAL(20,2),
    value_other DECIMAL(28,8), source_element VARCHAR NOT NULL, line_item_category VARCHAR, parent_subtotal VARCHAR
);
CREATE TABLE stg_corp_actions (
    filing_id VARCHAR NOT NULL, seq INTEGER NOT NULL, component INTEGER NOT NULL, exchange VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL, series VARCHAR NOT NULL, isin VARCHAR NOT NULL, ex_date DATE NOT NULL,
    record_date DATE, face_value DECIMAL(18,4), subject VARCHAR NOT NULL, parse_status VARCHAR NOT NULL,
    parse_reason VARCHAR, action_type VARCHAR, ratio_num DECIMAL(18,6), ratio_den DECIMAL(18,6),
    issue_price DECIMAL(18,4), cash_per_share DECIMAL(18,4),
    PRIMARY KEY (filing_id, seq, component)
);
CREATE TABLE stg_holidays (
    filing_id VARCHAR NOT NULL, exchange VARCHAR NOT NULL, cal_date DATE NOT NULL, description VARCHAR NOT NULL,
    PRIMARY KEY (filing_id, cal_date)
);
CREATE TABLE stg_shp_meta (
    filing_id VARCHAR PRIMARY KEY, parser_version VARCHAR NOT NULL, as_of_date DATE NOT NULL,
    stated_isin VARCHAR NOT NULL, stated_symbol VARCHAR, has_partly_paid BOOLEAN, promoter_pledge_flag BOOLEAN,
    promoter_pledged_shares BIGINT, promoter_encumbered_shares BIGINT, rules_applied VARCHAR
);
CREATE TABLE stg_shp_line_items (
    filing_id VARCHAR NOT NULL, category_member VARCHAR NOT NULL, element VARCHAR NOT NULL,
    value DECIMAL(28,8) NOT NULL, unit VARCHAR NOT NULL, PRIMARY KEY (filing_id, category_member, element)
);
CREATE TABLE stg_shp_holders (
    filing_id VARCHAR NOT NULL, holder_category VARCHAR NOT NULL, row_member VARCHAR NOT NULL,
    holder_name VARCHAR NOT NULL, shares BIGINT NOT NULL, pct DOUBLE,
    PRIMARY KEY (filing_id, holder_category, row_member)
);
CREATE TABLE stg_shp_categories (
    filing_id VARCHAR NOT NULL, category VARCHAR NOT NULL, shares BIGINT, holders BIGINT, pct DOUBLE,
    demat_shares BIGINT, voting_rights BIGINT, PRIMARY KEY (filing_id, category)
);
CREATE TABLE stg_events (
    filing_id VARCHAR NOT NULL, record_key VARCHAR NOT NULL, family VARCHAR NOT NULL, event_type VARCHAR NOT NULL,
    event_subtype VARCHAR, occurred_on DATE, report_date DATE NOT NULL, counterparty VARCHAR,
    amount_inr DECIMAL(20,2), person_name VARCHAR, person_category VARCHAR, change_type VARCHAR,
    cessation_category VARCHAR, details JSON, stated_symbol VARCHAR, stated_isin VARCHAR,
    PRIMARY KEY (filing_id, record_key)
);
CREATE TABLE stg_kpis (
    filing_id VARCHAR NOT NULL, seq INTEGER NOT NULL, symbol VARCHAR NOT NULL, kpi VARCHAR NOT NULL,
    period_start DATE, period_end DATE, value DECIMAL(24,6), unit VARCHAR NOT NULL, source_kind VARCHAR NOT NULL,
    source_url VARCHAR NOT NULL, visible_from_ts TIMESTAMP, notes VARCHAR, issue VARCHAR, PRIMARY KEY (filing_id, seq)
);
CREATE TABLE stg_issues (
    filing_id VARCHAR, stage VARCHAR NOT NULL, reason_code VARCHAR NOT NULL, details JSON NOT NULL
);
CREATE TABLE stg_findings (
    filing_id VARCHAR, stage VARCHAR NOT NULL, reason_code VARCHAR NOT NULL, details JSON NOT NULL
);
"""

# Insertion order respects foreign keys.
TABLE_ORDER = (
    "blobs",
    "filings",
    "raw_cm_bhavcopy",
    "raw_delivery",
    "raw_xbrl_facts",
    "raw_index_snapshot",
    "index_ohlcv",
    "raw_equity_master",
    "raw_results_listing",
    "stg_holidays",
    "stg_shp_meta",
    "stg_shp_categories",
    "stg_shp_holders",
    "stg_shp_line_items",
    "stg_xbrl_filing",
    "stg_xbrl_facts",
    "stg_corp_actions",
    "stg_events",
    "stg_kpis",
    "stg_issues",
    "stg_findings",
)


def _blob_row(b: Blob) -> dict[str, Any]:
    return asdict(b)


def _filing_row(f: Filing) -> dict[str, Any]:
    return asdict(f)


def write_stage(
    stage_root: Path,
    job: str,
    run_id: str,
    tables: dict[str, list[dict[str, Any]]],
    extra: dict[str, Any] | None = None,
) -> Path:
    unknown = set(tables) - set(TABLE_ORDER)
    if unknown:
        raise KeyError(f"unknown staging tables {sorted(unknown)}")
    final = Path(stage_root) / job / run_id
    if final.exists():
        # Run ids are derived from content (sha/filing id), so an existing stage is the same batch.
        if read_manifest(final).get("job") != job:
            raise FileExistsError(f"stage {final} exists for another job")
        return final
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(dir=final.parent, prefix=f".{run_id}-"))
    try:
        con = connect()
        apply_schema(con)
        con.execute(STAGING_SCHEMA)
        counts = {}
        for name in TABLE_ORDER:
            rows = tables.get(name) or []
            if not rows:
                continue
            insert_rows(con, name, rows)
            con.execute(f"COPY {name} TO '{(tmp / (name + '.parquet')).as_posix()}' (FORMAT PARQUET)")
            counts[name] = len(rows)
        con.close()
        manifest = {"job": job, "run_id": run_id, "tables": counts, **(extra or {})}
        (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, final)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return final


def read_manifest(stage_dir: Path) -> dict[str, Any]:
    return json.loads((Path(stage_dir) / "manifest.json").read_text(encoding="utf-8"))


def read_table(con, stage_dir: Path, table: str) -> list[dict[str, Any]]:
    path = Path(stage_dir) / f"{table}.parquet"
    if not path.exists():
        return []
    return fetch_dicts(con, "SELECT * FROM read_parquet(?)", [path.as_posix()])


# ── Jobs ────────────────────────────────────────────────────────────────


def stage_market_day(
    vault: Vault,
    stage_root: Path,
    *,
    bhavcopy: bytes,
    bhavcopy_url: str,
    delivery: bytes | None,
    delivery_url: str | None,
    fetched_at: datetime,
) -> Path:
    """Vault + parse one trading day of UDiFF bhavcopy and (optionally) sec_bhavdata_full."""
    bhav_rows = parse_udiff_cm(bhavcopy)
    trade_date = bhav_rows[0].trade_date
    eod_utc = ist_to_utc(trade_date, time(23, 59, 59))  # publish time UNVERIFIED [P11]: end of day

    b_blob = vault.put(bhavcopy, ext="csv.zip", media_type="application/zip", fetched_at=fetched_at)
    b_fil = make_filing(
        b_blob,
        exchange="NSE",
        category="BHAVCOPY_CM",
        source_url=bhavcopy_url,
        fetched_at=fetched_at,
        broadcast_ts=eod_utc,
        broadcast_ts_source="EOD_RULE",
    )
    blobs, filings = [_blob_row(b_blob)], [_filing_row(b_fil)]
    raw_bhav = [{"filing_id": b_fil.filing_id, **asdict(r)} for r in bhav_rows]

    raw_deliv: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    d_sha = "nodeliv"
    if delivery is not None:
        if not delivery_url:
            raise ValueError("delivery_url required with delivery bytes")
        d_rows = parse_sec_bhavdata_full(delivery)
        d_blob = vault.put(delivery, ext="csv", media_type="text/csv", fetched_at=fetched_at)
        d_sha = d_blob.sha256[:12]
        d_fil = make_filing(
            d_blob,
            exchange="NSE",
            category="DELIVERY",
            source_url=delivery_url,
            fetched_at=fetched_at,
            broadcast_ts=eod_utc,
            broadcast_ts_source="EOD_RULE",
        )
        blobs.append(_blob_row(d_blob))
        filings.append(_filing_row(d_fil))
        if d_rows[0].trade_date != trade_date:
            # Kept as evidence (blob + filing), never joined: quarantined by the promoter [P1-8].
            issues.append({"filing_id": d_fil.filing_id, "stage": "DELIVERY", "reason_code": "DELIVERY_DATE_MISMATCH",
                           "details": json.dumps({"delivery_date": str(d_rows[0].trade_date),
                                                  "trade_date": str(trade_date), "url": delivery_url})})  # fmt: skip
        else:
            raw_deliv = [{"filing_id": d_fil.filing_id, **asdict(r)} for r in d_rows]

    # The delivery file is part of the batch identity: a later fetch that adds it is a new batch [P0-2].
    run_id = f"{trade_date:%Y%m%d}-{b_blob.sha256[:12]}-{d_sha}"
    return write_stage(
        stage_root,
        "market_day",
        run_id,
        {
            "blobs": blobs,
            "filings": filings,
            "raw_cm_bhavcopy": raw_bhav,
            "raw_delivery": raw_deliv,
            "stg_issues": issues,
        },
        extra={"trade_date": trade_date.isoformat(), "exchange": "NSE", "has_delivery": bool(raw_deliv)},
    )


def stage_results_xbrl(
    vault: Vault,
    stage_root: Path,
    *,
    data: bytes,
    source_url: str,
    fetched_at: datetime,
    broadcast_ts: datetime | None = None,
    broadcast_ts_source: str = "UNKNOWN",
    exchange: str = "NSE",
    run_suffix: str | None = None,
) -> Path:
    """Vault + parse one quarterly results XBRL. Parse problems are staged as issues, not raised.
    `run_suffix` (restage) gives a re-parse its own batch, promoted as a new parser_version."""
    blob = vault.put(data, ext="xml", media_type="application/xml", fetched_at=fetched_at)
    filing = make_filing(
        blob,
        exchange=exchange,
        category="RESULTS_XBRL",
        source_url=source_url,
        fetched_at=fetched_at,
        broadcast_ts=broadcast_ts,
        broadcast_ts_source=broadcast_ts_source,
    )
    tables: dict[str, list[dict[str, Any]]] = {"blobs": [_blob_row(blob)], "filings": [_filing_row(filing)]}
    fid = filing.filing_id
    run_id = fid if run_suffix is None else f"{fid}-{run_suffix}"

    try:
        inst = parse_instance(data)
    except ParseError as exc:
        tables["stg_issues"] = [
            {
                "filing_id": fid,
                "stage": "PARSE",
                "reason_code": "INVALID_XBRL",
                "details": json.dumps({"error": str(exc)}),
            }
        ]
        return write_stage(stage_root, "results_xbrl", run_id, tables)

    tables["raw_xbrl_facts"] = _raw_fact_rows(fid, inst)

    try:
        parsed = parse_integrated_results(data, source_url.rsplit("/", 1)[-1])
    except ParseError as exc:
        tables["stg_issues"] = [
            {
                "filing_id": fid,
                "stage": "PARSE",
                "reason_code": "PARSE_ERROR",
                "details": json.dumps({"error": str(exc)}),
            }
        ]
        return write_stage(stage_root, "results_xbrl", run_id, tables)

    if parsed.issues:
        tables["stg_issues"] = [
            {
                "filing_id": fid,
                "stage": i.stage,
                "reason_code": i.reason_code,
                "details": json.dumps(i.details, default=str, sort_keys=True),
            }
            for i in parsed.issues
        ]
        return write_stage(stage_root, "results_xbrl", run_id, tables)

    if getattr(parsed, "findings", None):  # non-blocking: promoted, each opens a quarantine row [X86]
        tables["stg_findings"] = [
            {
                "filing_id": fid,
                "stage": i.stage,
                "reason_code": i.reason_code,
                "details": json.dumps(i.details, default=str, sort_keys=True),
            }
            for i in parsed.findings
        ]
    m = parsed.meta
    tables["stg_xbrl_filing"] = [
        {
            "filing_id": fid,
            "parser_version": PARSER_VERSION,
            "accounting_profile": parsed.profile,
            "taxonomy_ns": parsed.taxonomy_ns,
            "scope": m["scope"],
            "level_of_rounding": m["level_of_rounding"],
            "fy_start": m["fy_start"],
            "fy_end": m["fy_end"],
            "period_end": m["period_end"],
            "reporting_quarter": m["reporting_quarter"],
            "audited": m["audited"],
            "board_meeting_end_ts": m["board_meeting_end_ts"],
            "interest_paid_cfo_class": m["interest_paid_cfo_class"],
            "interest_recd_cfo_class": m["interest_recd_cfo_class"],
            "stated_isin": m["stated_isin"],
            "stated_symbol": m["stated_symbol"],
            "company_name": m["company_name"],
            "stated_cin": m.get("stated_cin"),
            "auditor_qualified": m.get("auditor_qualified"),
            "audit_opinion": m.get("audit_opinion"),
        }
    ]
    tables["stg_xbrl_facts"] = [
        {
            "filing_id": fid,
            "parser_version": PARSER_VERSION,
            "scope": m["scope"],
            "canonical_tag": f.canonical_tag,
            "period_type": f.period_type,
            "period_start": f.period_start,
            "period_end": f.period_end,
            "period_months": f.period_months,
            "unit": f.unit,
            "value_inr": to_inr(f.value) if f.unit == "INR" else None,
            "value_other": None if f.unit == "INR" else f.value,
            "source_element": f.source_element,
            "line_item_category": f.line_item_category,
            "parent_subtotal": f.parent_subtotal,
        }
        for f in parsed.facts
    ]
    _assert_exact(tables["stg_xbrl_facts"], parsed)
    return write_stage(stage_root, "results_xbrl", run_id, tables)


def _assert_exact(rows: list[dict[str, Any]], parsed) -> None:
    """Money must survive DECIMAL(20,2) unchanged (XBRL rupees have no sub-paise digits)."""
    for row, fact in zip(rows, parsed.facts, strict=True):
        if row["value_inr"] is not None and row["value_inr"] != fact.value:
            raise ParseError(f"{fact.canonical_tag}: {fact.value} not representable as DECIMAL(20,2)")


def quarantine_id(*parts: object) -> str:
    return stable_id("q", *parts)


def stage_corp_actions(
    vault: Vault,
    stage_root: Path,
    *,
    data: bytes,
    source_url: str,
    fetched_at: datetime,
    exchange: str = "NSE",
) -> Path:
    """Vault + parse an NSE corporate-actions API response (one row per parsed component)."""
    records = parse_nse_corp_actions_json(data)
    blob = vault.put(data, ext="json", media_type="application/json", fetched_at=fetched_at)
    filing = make_filing(blob, exchange=exchange, category="CORP_ACTIONS", source_url=source_url, fetched_at=fetched_at)
    rows: list[dict[str, Any]] = []
    for r in records:
        base = {
            "filing_id": filing.filing_id,
            "seq": r.seq,
            "exchange": exchange,
            "symbol": r.symbol,
            "series": r.series,
            "isin": r.isin,
            "ex_date": r.ex_date,
            "record_date": r.record_date,
            "face_value": r.face_value,
            "subject": r.subject,
            "parse_status": r.parse_status,
            "parse_reason": r.parse_reason,
        }
        empty = {"action_type": None, "ratio_num": None, "ratio_den": None, "issue_price": None, "cash_per_share": None}
        if not r.components:
            rows.append(
                {**base, "component": 0, **empty, "action_type": "UNKNOWN" if r.parse_status == "UNPARSED" else None}
            )
        for i, c in enumerate(r.components):
            rows.append(
                {
                    **base,
                    "component": i,
                    "action_type": c.action_type,
                    "ratio_num": c.ratio_num,
                    "ratio_den": c.ratio_den,
                    "issue_price": c.issue_price,
                    "cash_per_share": c.cash_per_share,
                }
            )
    return write_stage(
        stage_root,
        "corp_actions",
        f"{filing.filing_id}-{PURPOSE_RULES_VERSION}",
        {"blobs": [_blob_row(blob)], "filings": [_filing_row(filing)], "stg_corp_actions": rows},
        extra={"exchange": exchange},
    )


def stage_holidays(
    vault: Vault, stage_root: Path, *, data: bytes, source_url: str, fetched_at: datetime, exchange: str = "NSE"
) -> Path:
    from financials.calendar import parse_holiday_master

    holidays = parse_holiday_master(data)
    blob = vault.put(data, ext="json", media_type="application/json", fetched_at=fetched_at)
    filing = make_filing(blob, exchange=exchange, category="HOLIDAYS", source_url=source_url, fetched_at=fetched_at)
    rows = [
        {"filing_id": filing.filing_id, "exchange": exchange, "cal_date": d, "description": desc}
        for d, desc in holidays
    ]
    return write_stage(
        stage_root,
        "holidays",
        filing.filing_id,
        {"blobs": [_blob_row(blob)], "filings": [_filing_row(filing)], "stg_holidays": rows},
        extra={"exchange": exchange},
    )


def stage_index_snapshot(
    vault: Vault,
    stage_root: Path,
    *,
    data: bytes,
    source_url: str,
    index_name: str,
    snapshot_date,
    fetched_at: datetime,
    exchange: str = "NSE",
) -> Path:
    from financials.parsers.indices import parse_index_list

    members = parse_index_list(data)
    blob = vault.put(data, ext="csv", media_type="text/csv", fetched_at=fetched_at)
    filing = make_filing(blob, exchange=exchange, category="INDEX_LIST", source_url=source_url, fetched_at=fetched_at)
    rows = [
        {
            "filing_id": filing.filing_id,
            "index_name": index_name,
            "snapshot_date": snapshot_date,
            "symbol": m.symbol,
            "series": m.series,
            "isin": m.isin,
            "company_name": m.company_name,
            "industry": m.industry,
        }
        for m in members
    ]
    return write_stage(
        stage_root,
        "index_snapshot",
        f"{index_name.replace(' ', '_')}-{snapshot_date}-{blob.sha256[:12]}",
        {"blobs": [_blob_row(blob)], "filings": [_filing_row(filing)], "raw_index_snapshot": rows},
        extra={"index_name": index_name, "snapshot_date": str(snapshot_date)},
    )


def _raw_fact_rows(fid: str, inst) -> list[dict[str, Any]]:
    """Every fact of an instance, every context, exactly as sent (invariant 3)."""
    rows = []
    for f in inst.facts:
        c = inst.contexts[f.context_id]
        rows.append(
            {
                "filing_id": fid,
                "parser_version": PARSER_VERSION,
                "seq": f.seq,
                "element_ns": f.ns,
                "element_name": f.name,
                "context_id": f.context_id,
                "ctx_start": c.start,
                "ctx_end": c.end,
                "ctx_instant": c.instant,
                "dimensions": json.dumps(dict(c.dimensions)) if c.dimensions else None,
                "unit_ref": f.unit_ref,
                "decimals": f.decimals,
                "value_text": f.value_text,
            }
        )
    return rows


def _int_or_none(v) -> int | None:
    return None if v is None else int(v)


def stage_shareholding(
    vault: Vault,
    stage_root: Path,
    *,
    data: bytes,
    source_url: str,
    fetched_at: datetime,
    broadcast_ts: datetime | None = None,
    broadcast_ts_source: str = "UNKNOWN",
    exchange: str = "NSE",
    run_suffix: str | None = None,
) -> Path:
    """Vault + parse one Reg. 31 shareholding XBRL. Broadcast time comes from the NSE master JSON.
    `run_suffix` (restage) gives a re-parse its own batch next to the first one, so it promotes as a new
    parser_version instead of being taken for the batch already promoted."""
    from financials.parsers.shareholding import parse_shareholding, shp_instance

    blob = vault.put(data, ext="xml", media_type="application/xml", fetched_at=fetched_at)
    filing = make_filing(
        blob,
        exchange=exchange,
        category="SHP_XBRL",
        source_url=source_url,
        fetched_at=fetched_at,
        broadcast_ts=broadcast_ts,
        broadcast_ts_source=broadcast_ts_source,
    )
    fid = filing.filing_id
    run_id = fid if run_suffix is None else f"{fid}-{run_suffix}"
    tables: dict[str, list[dict[str, Any]]] = {"blobs": [_blob_row(blob)], "filings": [_filing_row(filing)]}
    try:
        tables["raw_xbrl_facts"] = _raw_fact_rows(fid, shp_instance(data)[0])
        parsed = parse_shareholding(data)
    except ParseError as exc:
        tables["stg_issues"] = [
            {
                "filing_id": fid,
                "stage": "PARSE",
                "reason_code": "PARSE_ERROR",
                "details": json.dumps({"error": str(exc)}),
            }
        ]
        return write_stage(stage_root, "shareholding", run_id, tables)
    if parsed.issues:
        tables["stg_issues"] = [
            {
                "filing_id": fid,
                "stage": i.stage,
                "reason_code": i.reason_code,
                "details": json.dumps(i.details, default=str, sort_keys=True),
            }
            for i in parsed.issues
        ]
        return write_stage(stage_root, "shareholding", run_id, tables)
    m = parsed.meta
    tables["stg_shp_meta"] = [
        {
            "filing_id": fid,
            "parser_version": PARSER_VERSION,
            "as_of_date": m["as_of_date"],
            "stated_isin": m["stated_isin"],
            "stated_symbol": m["stated_symbol"],
            "has_partly_paid": m["has_partly_paid"],
            "promoter_pledge_flag": m["promoter_pledge_flag"],
            "promoter_pledged_shares": _int_or_none(m["promoter_pledged_shares"]),
            "promoter_encumbered_shares": _int_or_none(m["promoter_encumbered_shares"]),
            "rules_applied": ",".join(m["rules_applied"]) or None,
        }
    ]
    tables["stg_shp_line_items"] = [
        {"filing_id": fid, "category_member": li["category_member"], "element": li["element"], "value": li["value"],
         "unit": li["unit"] or "UNKNOWN"}
        for li in parsed.line_items
    ]  # fmt: skip
    tables["stg_shp_holders"] = [
        {
            "filing_id": fid,
            "holder_category": h["holder_category"],
            "row_member": h["row_member"],
            "holder_name": h["holder_name"],
            "shares": int(h["shares"]),
            "pct": None if h["pct"] is None else float(h["pct"]),
        }
        for h in parsed.major_holders
    ]
    tables["stg_shp_categories"] = [
        {
            "filing_id": fid,
            "category": cat,
            **{
                k: (float(v) if k == "pct" else int(v)) if v is not None else None
                for k, v in ((k, vals.get(k)) for k in ("shares", "holders", "pct", "demat_shares", "voting_rights"))
            },
        }
        for cat, vals in sorted(parsed.categories.items())
    ]
    return write_stage(stage_root, "shareholding", run_id, tables)


def stage_reg30_event(
    vault: Vault,
    stage_root: Path,
    *,
    data: bytes,
    source_url: str,
    fetched_at: datetime,
    broadcast_ts: datetime | None = None,
    broadcast_ts_source: str = "UNKNOWN",
    exchange: str = "NSE",
) -> Path:
    """Vault + parse one Reg. 30 structured event XBRL [E1-E7]; broadcast time from the announcements RSS."""
    from financials.parsers.reg30_events import parse_reg30_event

    blob = vault.put(data, ext="xml", media_type="application/xml", fetched_at=fetched_at)
    filing = make_filing(
        blob,
        exchange=exchange,
        category="REG30_EVENT",
        source_url=source_url,
        fetched_at=fetched_at,
        broadcast_ts=broadcast_ts,
        broadcast_ts_source=broadcast_ts_source,
    )
    fid = filing.filing_id
    tables: dict[str, list[dict[str, Any]]] = {"blobs": [_blob_row(blob)], "filings": [_filing_row(filing)]}
    try:
        tables["raw_xbrl_facts"] = _raw_fact_rows(fid, parse_instance(data))
        parsed = parse_reg30_event(data)
    except ParseError as exc:
        tables["stg_issues"] = [
            {
                "filing_id": fid,
                "stage": "PARSE",
                "reason_code": "PARSE_ERROR",
                "details": json.dumps({"error": str(exc)}),
            }
        ]
        return write_stage(stage_root, "reg30_event", fid, tables)
    if parsed.issues:
        tables["stg_issues"] = [
            {
                "filing_id": fid,
                "stage": i.stage,
                "reason_code": i.reason_code,
                "details": json.dumps(i.details, default=str, sort_keys=True),
            }
            for i in parsed.issues
        ]
        return write_stage(stage_root, "reg30_event", fid, tables)
    m = parsed.meta
    tables["stg_events"] = [
        {
            "filing_id": fid,
            "record_key": e["record_key"],
            "family": parsed.family,
            "event_type": e["event_type"],
            "event_subtype": e.get("event_subtype"),
            "occurred_on": e.get("occurred_on"),
            "report_date": m["report_date"],
            "counterparty": e.get("counterparty"),
            "amount_inr": e.get("amount_inr"),
            "person_name": e.get("person_name"),
            "person_category": e.get("person_category"),
            "change_type": e.get("change_type"),
            "cessation_category": e.get("cessation_category"),
            "details": json.dumps(e.get("details") or {}, default=str, sort_keys=True),
            "stated_symbol": m["stated_symbol"],
            "stated_isin": m["stated_isin"],
        }
        for e in parsed.events
    ]
    return write_stage(stage_root, "reg30_event", fid, tables, extra={"family": parsed.family})


def stage_kpis(vault: Vault, stage_root: Path, *, data: bytes, source_url: str, fetched_at: datetime) -> Path:
    """Vault + parse a supplemental-KPI file (CSV/JSON, parsers.kpis). The file itself is the evidence."""
    from financials.parsers.kpis import parse_kpis

    rows = parse_kpis(data)
    ext = "json" if data.lstrip()[:1] in (b"[", b"{") else "csv"
    blob = vault.put(
        data, ext=ext, media_type="application/json" if ext == "json" else "text/csv", fetched_at=fetched_at
    )
    filing = make_filing(blob, exchange="MANUAL", category="SUPPLEMENTAL_KPIS", source_url=source_url,
                         fetched_at=fetched_at)  # fmt: skip
    return write_stage(
        stage_root, "kpis", filing.filing_id,
        {"blobs": [_blob_row(blob)], "filings": [_filing_row(filing)],
         "stg_kpis": [{"filing_id": filing.filing_id, **asdict(r)} for r in rows]},
    )  # fmt: skip


def stage_index_closes(vault: Vault, stage_root: Path, *, data: bytes, source_url: str, fetched_at: datetime) -> Path:
    """Vault + parse one ind_close_all_DDMMYYYY.csv [IDX9]."""
    from financials.parsers.indices import parse_index_closes

    rows = parse_index_closes(data)
    blob = vault.put(data, ext="csv", media_type="text/csv", fetched_at=fetched_at)
    eod = ist_to_utc(rows[0].trade_date, time(23, 59, 59))
    filing = make_filing(blob, exchange="NSE", category="INDEX_CLOSE", source_url=source_url, fetched_at=fetched_at,
                         broadcast_ts=eod, broadcast_ts_source="EOD_RULE")  # fmt: skip
    day = rows[0].trade_date
    return write_stage(
        stage_root, "index_close", f"{day:%Y%m%d}-{blob.sha256[:12]}",
        {"blobs": [_blob_row(blob)], "filings": [_filing_row(filing)],
         "index_ohlcv": [{**asdict(r), "filing_id": filing.filing_id} for r in rows]},
        extra={"trade_date": day.isoformat()},
    )  # fmt: skip


def stage_equity_master(vault: Vault, stage_root: Path, *, data: bytes, source_url: str, fetched_at: datetime) -> Path:
    """Vault + parse EQUITY_L.csv [IDX10]; the snapshot date is the IST date of the fetch."""
    from financials.parsers.indices import parse_equity_master
    from financials.timeutil import utc_to_ist_date

    rows = parse_equity_master(data)
    blob = vault.put(data, ext="csv", media_type="text/csv", fetched_at=fetched_at)
    filing = make_filing(blob, exchange="NSE", category="EQUITY_MASTER", source_url=source_url, fetched_at=fetched_at)
    snap = utc_to_ist_date(fetched_at)
    return write_stage(
        stage_root, "equity_master", f"{snap:%Y%m%d}-{blob.sha256[:12]}",
        {"blobs": [_blob_row(blob)], "filings": [_filing_row(filing)],
         "raw_equity_master": [{**asdict(r), "filing_id": filing.filing_id, "snapshot_date": snap} for r in rows]},
        extra={"snapshot_date": snap.isoformat()},
    )  # fmt: skip


def stage_raw_only(
    vault: Vault,
    stage_root: Path,
    *,
    data: bytes,
    ext: str,
    media_type: str,
    category: str,
    source_url: str,
    fetched_at: datetime,
    exchange: str = "NSE",
) -> Path:
    """Vault a download that feeds another job (e.g. the shareholding master JSON) so it stays evidence."""
    blob = vault.put(data, ext=ext, media_type=media_type, fetched_at=fetched_at)
    filing = make_filing(blob, exchange=exchange, category=category, source_url=source_url, fetched_at=fetched_at)
    return write_stage(
        stage_root, "raw_only", filing.filing_id, {"blobs": [_blob_row(blob)], "filings": [_filing_row(filing)]}
    )


def _utc(ts: datetime | None) -> datetime | None:
    return None if ts is None else ist_to_utc(ts.date(), ts.time())


def results_listing_rows(listing_filing_id: str, data: bytes) -> list[dict[str, Any]]:
    """Every row of an integrated-filing-results listing as visibility evidence [A7, X83]; unparsable -> none."""
    from financials.parsers.discovery import parse_integrated_filing_listing

    try:
        entries = parse_integrated_filing_listing(data, results_only=False)
    except ParseError:
        return []
    rows = {}
    for e in entries:
        rows[e.xbrl_url] = {
            "filing_id": listing_filing_id, "xbrl_url": e.xbrl_url, "symbol": e.symbol, "period_end": e.period_end,
            "scope": e.scope, "filing_type": e.filing_type, "broadcast_ts": _utc(e.broadcast_ts_ist),
            "creation_ts": _utc(e.creation_ts_ist), "revised_ts": _utc(e.revised_ts_ist),
            "revision_remark": e.revision_remark,
        }  # fmt: skip
    return list(rows.values())


def stage_results_listing(
    vault: Vault,
    stage_root: Path,
    *,
    data: bytes,
    source_url: str,
    fetched_at: datetime,
    exchange: str = "NSE",
    run_suffix: str | None = None,
) -> Path:
    """Vault an integrated-filing-results listing (RESULTS_LISTING) and stage its rows as raw_results_listing."""
    blob = vault.put(data, ext="json", media_type="application/json", fetched_at=fetched_at)
    filing = make_filing(blob, exchange=exchange, category="RESULTS_LISTING", source_url=source_url,
                         fetched_at=fetched_at)  # fmt: skip
    run_id = filing.filing_id if run_suffix is None else f"{filing.filing_id}-{run_suffix}"
    return write_stage(stage_root, "raw_only", run_id,
                       {"blobs": [_blob_row(blob)], "filings": [_filing_row(filing)],
                        "raw_results_listing": results_listing_rows(filing.filing_id, data)})  # fmt: skip
