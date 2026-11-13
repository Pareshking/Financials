"""Filing discovery listings (pure: bytes -> entries).

- `integrated-filing-results?index=equities&symbol=X` [A7]: `{"data": [...], "size", "page", "totalCount"}`, newest
  20 rows; each row has `symbol`, `qe_Date` (DD-MON-YYYY), `consolidated` (Consolidated | Standalone | null for
  Governance), `type` (`Integrated Filing- Financials` | `Integrated Filing- Governance`), `type_Sub`, `broadcast_Date`
  (DD-Mon-YYYY HH:MM:SS, IST) and `xbrl` (archive URL). Only the Financials rows are results; Governance rows are a
  phase-3 feed (F23). Older rows than the newest 20 need a pagination parameter that has not been verified.
- Announcements RSS [E1]: "financial results" items link a PDF whose file name starts with the NSE symbol
  (`DCAL_13112026213948_...pdf`); a hint for which symbols to look up, not a complete list (CAL/A9).
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime

from financials.parsers import ParseError

RESULTS_TYPE = "Integrated Filing- Financials"


@dataclass(frozen=True)
class IntegratedFilingEntry:
    symbol: str
    period_end: date
    scope: str | None
    filing_type: str
    type_sub: str | None
    broadcast_ts_ist: datetime
    xbrl_url: str


def parse_integrated_filing_listing(data: bytes, *, results_only: bool = True) -> list[IntegratedFilingEntry]:
    try:
        doc = json.loads(data.decode("utf-8"))
        rows = doc["data"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ParseError(f"integrated-filing-results: {exc}") from exc
    out = []
    for i, r in enumerate(rows):
        if results_only and r.get("type") != RESULTS_TYPE:
            continue
        try:
            out.append(
                IntegratedFilingEntry(
                    symbol=r["symbol"].strip(),
                    period_end=datetime.strptime(r["qe_Date"].strip().title(), "%d-%b-%Y").date(),
                    scope=(r.get("consolidated") or None),
                    filing_type=r["type"],
                    type_sub=r.get("type_Sub"),
                    broadcast_ts_ist=datetime.strptime(r["broadcast_Date"].strip(), "%d-%b-%Y %H:%M:%S"),
                    xbrl_url=r["xbrl"].strip(),
                )
            )
        except (KeyError, AttributeError, ValueError) as exc:
            raise ParseError(f"integrated-filing-results row {i}: {exc}") from exc
    return out


_ATTACHMENT = re.compile(r"^https://nsearchives\.nseindia\.com/corporate/([A-Z0-9&\-]+)_\d{14}_")


def symbols_with_results_today(rss: bytes) -> list[str]:
    """Symbols named by the attachment file of 'financial results' items in the announcements RSS."""
    try:
        root = ET.fromstring(rss)
    except ET.ParseError as exc:
        raise ParseError(f"announcements RSS: {exc}") from exc
    found: list[str] = []
    for it in root.iter("item"):
        if "financial results for the period" not in (it.findtext("description") or ""):
            continue
        m = _ATTACHMENT.match((it.findtext("link") or "").strip())
        if m and m.group(1) not in found:
            found.append(m.group(1))
    return found
