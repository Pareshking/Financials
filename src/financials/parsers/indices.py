"""NSE index constituent lists (`content/indices/ind_<index>list.csv`) [references A6]."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from financials.parsers import ParseError

REQUIRED = ("Company Name", "Industry", "Symbol", "Series", "ISIN Code")


@dataclass(frozen=True)
class IndexMember:
    company_name: str
    industry: str
    symbol: str
    series: str
    isin: str


def parse_index_list(data: bytes) -> list[IndexMember]:
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
    missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
    if missing:
        raise ParseError(f"index list: missing columns {missing}")
    out = []
    for i, r in enumerate(reader, start=2):
        m = IndexMember(*(r[c].strip() for c in REQUIRED))
        if not m.isin or not m.symbol:
            raise ParseError(f"index list line {i}: blank ISIN/symbol")
        out.append(m)
    if len({m.isin for m in out}) != len(out):
        raise ParseError("index list: duplicate ISIN")
    return out
