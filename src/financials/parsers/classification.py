"""NSE quote API (`GetQuoteApi?functionName=getSymbolData`) -> the security's 4-level industry classification [IC1].

Evidence (docs/references.md IC1-IC3, tests/fixtures/classification/): the answer is
`{"equityResponse": [{"metaData": {...}, "secInfo": {...}, "lastUpdateTime": "13-Nov-2026 16:00:00", ...}]}`.
`metaData` carries `symbol`, `series`, `isinCode`, `companyName`; `secInfo` carries the classification as
`macro` (macro-economic sector), `sector`, `industryInfo` (industry) and `basicIndustry` (basic industry). Macro and
sector can carry the same text (TCS: "Information Technology" twice; IC2). The rest of the answer (prices, order
book, margins) is ignored here: the bhavcopy is the price source.

The answer has no effective date for the classification: it is what NSE shows on the day it was fetched (IC3).
Point in time therefore starts at the fetch; nothing is backdated.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from financials.parsers import ParseError

LEVELS = ("macro", "sector", "industryInfo", "basicIndustry")  # secInfo keys, top to bottom [IC1]


@dataclass(frozen=True)
class Classification:
    symbol: str
    series: str
    isin: str
    company_name: str | None
    macro: str | None
    sector: str | None
    industry: str | None
    basic_industry: str | None
    last_update_ist: datetime | None  # `lastUpdateTime` of the quote (IST, naive)

    @property
    def levels(self) -> tuple[str | None, str | None, str | None, str | None]:
        return (self.macro, self.sector, self.industry, self.basic_industry)


def _text(v) -> str | None:
    if v is None:
        return None
    s = " ".join(str(v).split())
    return None if s in ("", "-", "NA", "N/A", "null") else s


def parse_quote_classification(data: bytes) -> Classification:
    try:
        doc = json.loads(data.decode("utf-8"))
        item = doc["equityResponse"][0]
        meta, sec = item["metaData"], item["secInfo"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        raise ParseError(f"quote classification: {exc}") from exc
    symbol, series, isin = _text(meta.get("symbol")), _text(meta.get("series")), _text(meta.get("isinCode"))
    if not symbol or not series or not isin:
        raise ParseError(f"quote classification: missing symbol / series / ISIN in {meta!r:.200}")
    ts = _text(item.get("lastUpdateTime"))
    try:
        last = datetime.strptime(ts, "%d-%b-%Y %H:%M:%S") if ts else None
    except ValueError as exc:
        raise ParseError(f"quote classification: lastUpdateTime {ts!r}") from exc
    macro, sector, industry, basic = (_text(sec.get(k)) for k in LEVELS)
    return Classification(symbol, series, isin, _text(meta.get("companyName")), macro, sector, industry, basic, last)
