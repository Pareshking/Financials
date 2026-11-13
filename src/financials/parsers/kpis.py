"""Supplemental KPIs file (manual / presentation-sourced; not exchange XBRL): CSV or JSON -> rows. Pure.

One row per (company, KPI, period, publication):

    symbol, kpi, period_start, period_end, value, unit, source_kind, source_url, visible_from_utc[, notes]

- `kpi`: life insurers vnb_margin | embedded_value | ape_growth | persistency_13m | persistency_61m; new-gen tech
  gov | take_rate (alias net_take_rate) | contribution_margin | nrr | cac_payback.
- `unit`: INR (absolute rupees) | RATIO (0.27 = 27%) | MONTHS | COUNT; each KPI has exactly one allowed unit.
- `visible_from_utc`: when the source document became public (ISO timestamp, UTC). It is the point-in-time key.
- `source_kind`: INVESTOR_PRESENTATION | IRDAI_PUBLIC_DISCLOSURE | ANNUAL_REPORT | MANUAL.
Anything else is a row-level issue (quarantined by the promoter), never guessed.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from financials.parsers import ParseError

KPI_UNITS = {
    "vnb_margin": "RATIO", "embedded_value": "INR", "ape_growth": "RATIO", "persistency_13m": "RATIO",
    "persistency_61m": "RATIO", "gov": "INR", "take_rate": "RATIO", "contribution_margin": "RATIO",
    "nrr": "RATIO", "cac_payback": "MONTHS",
}  # fmt: skip
ALIASES = {"net_take_rate": "take_rate"}
SOURCE_KINDS = {"INVESTOR_PRESENTATION", "IRDAI_PUBLIC_DISCLOSURE", "ANNUAL_REPORT", "MANUAL"}
REQUIRED = ("symbol", "kpi", "period_start", "period_end", "value", "unit", "source_kind", "source_url",
            "visible_from_utc")  # fmt: skip


@dataclass(frozen=True)
class KpiRow:
    seq: int
    symbol: str
    kpi: str
    period_start: date | None
    period_end: date | None
    value: Decimal | None
    unit: str
    source_kind: str
    source_url: str
    visible_from_ts: datetime | None
    notes: str | None
    issue: str | None  # None = valid


def _records(data: bytes) -> list[dict]:
    text = data.decode("utf-8-sig")
    if text.lstrip().startswith(("[", "{")):
        try:
            doc = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ParseError(f"kpis: invalid JSON: {exc}") from exc
        rows = doc.get("rows") if isinstance(doc, dict) else doc
        if not isinstance(rows, list):
            raise ParseError("kpis: expected a JSON list of rows")
        return [{k: ("" if v is None else str(v)) for k, v in r.items()} for r in rows]
    reader = csv.DictReader(io.StringIO(text))
    missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
    if missing:
        raise ParseError(f"kpis: missing columns {missing}")
    return list(reader)


def parse_kpis(data: bytes) -> list[KpiRow]:
    out = []
    for i, r in enumerate(_records(data)):
        g = {k: (r.get(k) or "").strip() for k in (*REQUIRED, "notes")}
        kpi = ALIASES.get(g["kpi"].lower(), g["kpi"].lower())
        issue = None
        try:
            start, end = date.fromisoformat(g["period_start"]), date.fromisoformat(g["period_end"])
            seen = datetime.fromisoformat(g["visible_from_utc"].replace("Z", ""))
            value = Decimal(g["value"])
        except (ValueError, InvalidOperation):
            start = end = seen = value = None
            issue = "BAD_VALUE_OR_DATE"
        if issue is None:
            if kpi not in KPI_UNITS:
                issue = "UNKNOWN_KPI"
            elif g["unit"].upper() != KPI_UNITS[kpi]:
                issue = "WRONG_UNIT"
            elif g["source_kind"].upper() not in SOURCE_KINDS:
                issue = "UNKNOWN_SOURCE_KIND"
            elif not g["source_url"] or not g["symbol"]:
                issue = "MISSING_SOURCE_OR_SYMBOL"
            elif end < start or seen.date() < end:
                issue = "VISIBLE_BEFORE_PERIOD_END" if end >= start else "BAD_PERIOD"
        out.append(KpiRow(i, g["symbol"].upper(), kpi, start, end, value, g["unit"].upper(), g["source_kind"].upper(),
                          g["source_url"], seen, g["notes"] or None, issue))  # fmt: skip
    return out
