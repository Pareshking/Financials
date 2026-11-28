"""NSE `annual-reports` listing JSON [A8, X365]: the annual report PDF (or, for older years, zip) of one symbol per
fiscal year and submission. Pure: bytes in, rows out.

Fixture `annual/nse_annual-reports_AEGISVOPAK_20261125.json` (one request, 2026-11-25): `data[]` rows with
`companyName`, `fromYr`, `toYr`, `submission_type` (New, or "-" on older rows), `broadcast_dttm` and
`disseminationDateTime` (IST, `DD-MON-YYYY HH:MM:SS`), `timeTaken`, `fileName` (the full archive URL, host
`nsearchives.nseindia.in`, path `/annual_reports/AR_<n>_<SYM>_<from>_<to>_...`) and `attFileSize` (e.g. "5.77 MB",
or null). The file is kept at the URL as listed: that the `.com` archive host serves `/annual_reports/` too is
UNVERIFIED (canonical_archive_url was checked on XBRL files only). Nothing in the file is parsed into canonical tables.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from financials.parsers import ParseError
from financials.timeutil import IST

LISTED_TS_FORMAT = "%d-%b-%Y %H:%M:%S"


@dataclass(frozen=True)
class AnnualReportPdfEntry:
    company_name: str
    from_year: int
    to_year: int
    submission_type: str
    broadcast_ts_ist: datetime
    disseminated_ts_ist: datetime | None
    file_url: str  # as listed
    listed_size: str | None  # NSE's own rounding ("5.77 MB"); not a byte count

    @property
    def ext(self) -> str:
        name = self.file_url.rsplit("/", 1)[-1]
        return name.rsplit(".", 1)[-1].lower() if "." in name else "bin"


def _ts(text: str | None) -> datetime | None:
    if text is None or not text.strip() or text.strip() == "-":
        return None
    return datetime.strptime(text.strip(), LISTED_TS_FORMAT).replace(tzinfo=IST)


def parse_annual_report_listing(data: bytes) -> list[AnnualReportPdfEntry]:
    """One entry per listed annual report file, in the listing's order (newest first in the fixture)."""
    try:
        rows = json.loads(data.decode("utf-8"))["data"]
        out = []
        for r in rows:
            url = r["fileName"].strip()
            if not url.startswith("https://") or "/annual_reports/" not in url:
                raise ValueError(f"fileName {url!r} is not an annual_reports archive URL")
            broadcast = _ts(r["broadcast_dttm"])
            if broadcast is None:
                raise ValueError(f"{url}: no broadcast_dttm")
            out.append(
                AnnualReportPdfEntry(
                    company_name=(r.get("companyName") or "").strip(),
                    from_year=int(r["fromYr"]),
                    to_year=int(r["toYr"]),
                    submission_type=(r.get("submission_type") or "").strip(),
                    broadcast_ts_ist=broadcast,
                    disseminated_ts_ist=_ts(r.get("disseminationDateTime")),
                    file_url=url,
                    listed_size=r.get("attFileSize"),
                )
            )
        return out
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ParseError(f"annual report PDF listing: {exc}") from exc
