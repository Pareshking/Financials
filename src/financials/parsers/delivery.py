"""NSE sec_bhavdata_full_<DDMMYYYY>.csv: delivery quantities [references P10].

Has no ISIN; joined to UDiFF rows on (symbol, series, trade_date). Values after commas are
space-padded, and non-delivery series report '-' for delivery columns.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime

from financials.money import parse_decimal, parse_int
from financials.parsers import ParseError

REQUIRED_COLUMNS = ("SYMBOL", "SERIES", "DATE1", "TTL_TRD_QNTY", "DELIV_QTY", "DELIV_PER")


@dataclass(frozen=True)
class DeliveryRow:
    exchange: str
    trade_date: date
    symbol: str
    series: str
    traded_qty: int | None
    deliv_qty: int | None
    deliv_pct: float | None


def parse_sec_bhavdata_full(data: bytes) -> list[DeliveryRow]:
    reader = csv.reader(io.StringIO(data.decode("utf-8-sig")), skipinitialspace=True)
    try:
        header = [h.strip() for h in next(reader)]
    except StopIteration as exc:
        raise ParseError("empty delivery file") from exc
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        raise ParseError(f"sec_bhavdata_full: missing columns {missing}")
    idx = {name: header.index(name) for name in REQUIRED_COLUMNS}
    rows: list[DeliveryRow] = []
    dates: set[date] = set()
    for i, raw in enumerate(reader, start=2):
        if not raw or not any(v.strip() for v in raw):
            continue
        if len(raw) != len(header):
            raise ParseError(f"line {i}: {len(raw)} fields, expected {len(header)}")
        get = lambda name, raw=raw: raw[idx[name]].strip()  # noqa: E731
        try:
            d = datetime.strptime(get("DATE1"), "%d-%b-%Y").date()
            pct = parse_decimal(get("DELIV_PER"))
            row = DeliveryRow(
                exchange="NSE",
                trade_date=d,
                symbol=get("SYMBOL"),
                series=get("SERIES"),
                traded_qty=parse_int(get("TTL_TRD_QNTY")),
                deliv_qty=parse_int(get("DELIV_QTY")),
                deliv_pct=None if pct is None else float(pct),
            )
        except ValueError as exc:
            raise ParseError(f"line {i}: {exc}") from exc
        dates.add(d)
        rows.append(row)
    if len(dates) != 1:
        raise ParseError(f"expected exactly one trade date, found {sorted(dates)}")
    return rows
