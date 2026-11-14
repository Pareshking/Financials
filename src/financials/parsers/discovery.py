"""Filing discovery listings (pure: bytes -> entries).

- `integrated-filing-results?index=equities&symbol=X` [A7]: `{"data": [...], "size", "page", "totalCount"}`, newest
  20 rows; each row has `symbol`, `qe_Date` (DD-MON-YYYY), `consolidated` (Consolidated | Standalone | null for
  Governance), `type` (`Integrated Filing- Financials` | `Integrated Filing- Governance`), `type_Sub`, `broadcast_Date`
  (DD-Mon-YYYY HH:MM:SS, IST) and `xbrl` (archive URL). `creation_Date` (same format, 24-hour IST) is on every
  row; `broadcast_Date` is null exactly on revised rows, which carry `revised_Date` (DD-MON-YYYY HH:MM:SS) and
  `revision_Remark` (ADANIGREEN fixture) [X83]. Only the Financials rows are results; Governance rows are a
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
from typing import Any

from financials.parsers import ParseError

RESULTS_TYPE = "Integrated Filing- Financials"


@dataclass(frozen=True)
class IntegratedFilingEntry:
    symbol: str
    period_end: date
    scope: str | None
    filing_type: str
    type_sub: str | None
    broadcast_ts_ist: datetime | None  # null on revised rows (ADANIGREEN): visibility then from creation_ts_ist [X83]
    xbrl_url: str
    creation_ts_ist: datetime | None = None
    revised_ts_ist: datetime | None = None
    revision_remark: str | None = None

    @property
    def visible_ts_ist(self) -> datetime | None:
        """The later of broadcast and creation time: a revised row has no broadcast, and a re-uploaded file can be
        created after the broadcast of the row it replaces [X83]."""
        ts = [t for t in (self.broadcast_ts_ist, self.creation_ts_ist) if t is not None]
        return max(ts) if ts else None


def _listing_ts(value: Any) -> datetime | None:
    """`29-Oct-2026 12:14:33` (broadcast/creation) or `21-OCT-2026 18:10:52` (revised); 24-hour IST."""
    if not value or not str(value).strip():
        return None
    return datetime.strptime(str(value).strip().title(), "%d-%b-%Y %H:%M:%S")


_FILENAME_TS = re.compile(r"_(\d{2})(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})_WEB\.xml$")


def filename_ts_bounds(url: str) -> tuple[datetime, datetime] | None:
    """Earliest and latest IST upload time encoded in an Integrated Filing XBRL name `..._DDMMYYYYhhmmss_WEB.xml`.

    The clock is 12-hour without AM/PM [X83]: broadcast 21-Oct-2026 17:12:44 is `21102026051244`, 22:07:33 is
    `...100810`, 00:10:07 is `...121002` (TCS, ADANIGREEN listing fixtures). So hh 12 means 00 or 12, hh h means h
    or h + 12."""
    m = _FILENAME_TS.search(url)
    if not m:
        return None
    dd, mm, yyyy, hh, mi, ss = (int(g) for g in m.groups())
    try:
        lo = datetime(yyyy, mm, dd, hh % 12, mi, ss)
    except ValueError:
        return None
    return lo, lo.replace(hour=hh % 12 + 12)


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
                    broadcast_ts_ist=_listing_ts(r.get("broadcast_Date")),
                    xbrl_url=r["xbrl"].strip(),
                    creation_ts_ist=_listing_ts(r.get("creation_Date")),
                    revised_ts_ist=_listing_ts(r.get("revised_Date")),
                    revision_remark=(r.get("revision_Remark") or None),
                )
            )
        except (KeyError, AttributeError, ValueError) as exc:
            raise ParseError(f"integrated-filing-results row {i}: {exc}") from exc
    return out


def listing_progress(data: bytes) -> tuple[int, int]:
    """(rows on this page, totalCount) of an integrated-filing-results answer."""
    doc = json.loads(data.decode("utf-8"))
    return len(doc.get("data") or []), int(doc.get("totalCount") or 0)


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
