"""NSE index constituent lists (`content/indices/ind_<index>list.csv`) [references A6]."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

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


# ── daily index closes: content/indices/ind_close_all_DDMMYYYY.csv [IDX9] ──
CLOSE_REQUIRED = ("Index Name", "Index Date", "Open Index Value", "High Index Value", "Low Index Value",
                  "Closing Index Value", "Volume", "Turnover (Rs. Cr.)", "P/E", "P/B", "Div Yield")  # fmt: skip


@dataclass(frozen=True)
class IndexClose:
    index_name: str
    trade_date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal
    volume: int | None
    turnover_inr: Decimal | None  # filed in Rs crore; stored in rupees
    pe: float | None
    pb: float | None
    div_yield: float | None


def _num(v: str) -> Decimal | None:
    v = (v or "").strip()
    return None if v in ("", "-") else Decimal(v)


def parse_index_closes(data: bytes) -> list[IndexClose]:
    """One row per index (price indices only: no total-return rows in this file [IDX9]); '-' means not published."""
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
    missing = [c for c in CLOSE_REQUIRED if c not in (reader.fieldnames or [])]
    if missing:
        raise ParseError(f"index closes: missing columns {missing}")
    out = []
    for i, r in enumerate(reader, start=2):
        try:
            close = _num(r["Closing Index Value"])
            if close is None:
                raise ParseError(f"index closes line {i}: no close")
            turnover, volume = _num(r["Turnover (Rs. Cr.)"]), _num(r["Volume"])
            out.append(IndexClose(
                r["Index Name"].strip(), datetime.strptime(r["Index Date"].strip(), "%d-%m-%Y").date(),
                _num(r["Open Index Value"]), _num(r["High Index Value"]), _num(r["Low Index Value"]), close,
                None if volume is None else int(volume),
                None if turnover is None else (turnover * Decimal(10) ** 7).quantize(Decimal("0.01")),
                *(None if (x := _num(r[c])) is None else float(x) for c in ("P/E", "P/B", "Div Yield")),
            ))  # fmt: skip
        except (ValueError, ArithmeticError) as exc:
            raise ParseError(f"index closes line {i}: {exc}") from exc
    if len({c.trade_date for c in out}) != 1:
        raise ParseError("index closes: expected one date per file")
    return out


# ── equity master: content/equities/EQUITY_L.csv [IDX10] ──
@dataclass(frozen=True)
class EquityListing:
    symbol: str
    name: str
    series: str
    listing_date: date | None
    paid_up_value: Decimal | None
    market_lot: int | None
    isin: str
    face_value: Decimal | None


def parse_equity_master(data: bytes) -> list[EquityListing]:
    """Header has a space after each comma ('SYMBOL,NAME OF COMPANY, SERIES, ...'): names are stripped."""
    rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
    if not rows:
        raise ParseError("equity master: empty")
    head = [h.strip() for h in rows[0]]
    need = ("SYMBOL", "NAME OF COMPANY", "SERIES", "DATE OF LISTING", "PAID UP VALUE", "MARKET LOT", "ISIN NUMBER",
            "FACE VALUE")  # fmt: skip
    if [h for h in need if h not in head]:
        raise ParseError(f"equity master: missing columns {[h for h in need if h not in head]}")
    ix = {h: head.index(h) for h in need}
    out = []
    for i, r in enumerate(rows[1:], start=2):
        g = {h: r[ix[h]].strip() for h in need}
        try:
            listed = (
                datetime.strptime(g["DATE OF LISTING"].title(), "%d-%b-%Y").date() if g["DATE OF LISTING"] else None
            )
            lot = _num(g["MARKET LOT"])
            out.append(EquityListing(
                g["SYMBOL"], g["NAME OF COMPANY"], g["SERIES"], listed, _num(g["PAID UP VALUE"]),
                None if lot is None else int(lot), g["ISIN NUMBER"], _num(g["FACE VALUE"]),
            ))  # fmt: skip
        except (ValueError, ArithmeticError) as exc:
            raise ParseError(f"equity master line {i}: {exc}") from exc
    return out
