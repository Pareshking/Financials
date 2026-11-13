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
from financials.parsers.indas_corp import parse_indas_corp_results
from financials.parsers.nse_corp_actions import parse_nse_corp_actions_json
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
    interest_recd_cfo_class VARCHAR, stated_isin VARCHAR, stated_symbol VARCHAR, company_name VARCHAR
);
CREATE TABLE stg_xbrl_facts (
    filing_id VARCHAR NOT NULL, parser_version VARCHAR NOT NULL, scope VARCHAR NOT NULL,
    canonical_tag VARCHAR NOT NULL, period_type VARCHAR NOT NULL, period_start DATE NOT NULL,
    period_end DATE NOT NULL, period_months INTEGER, unit VARCHAR NOT NULL, value_inr DECIMAL(20,2),
    value_other DECIMAL(28,8), source_element VARCHAR NOT NULL
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
CREATE TABLE stg_issues (
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
    "stg_holidays",
    "stg_xbrl_filing",
    "stg_xbrl_facts",
    "stg_corp_actions",
    "stg_issues",
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
        raise FileExistsError(f"stage already exists: {final}")
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
    if delivery is not None:
        if not delivery_url:
            raise ValueError("delivery_url required with delivery bytes")
        d_rows = parse_sec_bhavdata_full(delivery)
        if d_rows[0].trade_date != trade_date:
            raise ParseError(f"delivery date {d_rows[0].trade_date} != bhavcopy date {trade_date}")
        d_blob = vault.put(delivery, ext="csv", media_type="text/csv", fetched_at=fetched_at)
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
        raw_deliv = [{"filing_id": d_fil.filing_id, **asdict(r)} for r in d_rows]

    run_id = f"{trade_date:%Y%m%d}-{b_blob.sha256[:12]}"
    return write_stage(
        stage_root,
        "market_day",
        run_id,
        {"blobs": blobs, "filings": filings, "raw_cm_bhavcopy": raw_bhav, "raw_delivery": raw_deliv},
        extra={"trade_date": trade_date.isoformat(), "exchange": "NSE"},
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
) -> Path:
    """Vault + parse one quarterly results XBRL. Parse problems are staged as issues, not raised."""
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
        return write_stage(stage_root, "results_xbrl", fid, tables)

    tables["raw_xbrl_facts"] = [
        {
            "filing_id": fid,
            "parser_version": PARSER_VERSION,
            "seq": f.seq,
            "element_ns": f.ns,
            "element_name": f.name,
            "context_id": f.context_id,
            "ctx_start": inst.contexts[f.context_id].start,
            "ctx_end": inst.contexts[f.context_id].end,
            "ctx_instant": inst.contexts[f.context_id].instant,
            "dimensions": json.dumps(dict(inst.contexts[f.context_id].dimensions))
            if inst.contexts[f.context_id].dimensions
            else None,
            "unit_ref": f.unit_ref,
            "decimals": f.decimals,
            "value_text": f.value_text,
        }
        for f in inst.facts
    ]

    try:
        parsed = parse_indas_corp_results(data)
    except ParseError as exc:
        tables["stg_issues"] = [
            {
                "filing_id": fid,
                "stage": "PARSE",
                "reason_code": "PARSE_ERROR",
                "details": json.dumps({"error": str(exc)}),
            }
        ]
        return write_stage(stage_root, "results_xbrl", fid, tables)

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
        return write_stage(stage_root, "results_xbrl", fid, tables)

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
        }
        for f in parsed.facts
    ]
    _assert_exact(tables["stg_xbrl_facts"], parsed)
    return write_stage(stage_root, "results_xbrl", fid, tables)


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
        filing.filing_id,
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
