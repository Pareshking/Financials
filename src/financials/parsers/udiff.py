"""NSE UDiFF cash-market bhavcopy (BhavCopy_NSE_CM_0_0_0_<YYYYMMDD>_F_0000.csv.zip) [references P1]."""

from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from financials.money import parse_decimal, parse_int, to_inr, to_price
from financials.parsers import ParseError

REQUIRED_COLUMNS = (
    "TradDt",
    "Sgmt",
    "Src",
    "FinInstrmTp",
    "FinInstrmId",
    "ISIN",
    "TckrSymb",
    "SctySrs",
    "FinInstrmNm",
    "OpnPric",
    "HghPric",
    "LwPric",
    "ClsPric",
    "LastPric",
    "PrvsClsgPric",
    "TtlTradgVol",
    "TtlTrfVal",
    "TtlNbOfTxsExctd",
)


@dataclass(frozen=True)
class BhavRow:
    exchange: str
    trade_date: date
    fin_instrm_id: str | None
    isin: str
    symbol: str
    series: str
    name: str | None
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal
    last: Decimal | None
    prev_close_reported: Decimal | None  # unadjusted on ex-dates [P2]; informational only
    volume: int | None
    turnover_inr: Decimal | None
    trades: int | None


def _csv_bytes(data: bytes) -> bytes:
    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if len(names) != 1:
                raise ParseError(f"expected one CSV in zip, found {names}")
            return zf.read(names[0])
    return data


def parse_udiff_cm(data: bytes) -> list[BhavRow]:
    text = _csv_bytes(data).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
    if missing:
        raise ParseError(f"UDiFF CM: missing columns {missing}")
    rows: list[BhavRow] = []
    trade_dates: set[date] = set()
    for i, r in enumerate(reader, start=2):
        if r["Sgmt"] != "CM" or r["Src"] != "NSE":
            raise ParseError(f"line {i}: unexpected Sgmt/Src {r['Sgmt']}/{r['Src']}")
        try:
            close = to_price(parse_decimal(r["ClsPric"]))
            if close is None:
                raise ParseError(f"line {i}: missing ClsPric")
            row = BhavRow(
                exchange="NSE",
                trade_date=date.fromisoformat(r["TradDt"]),
                fin_instrm_id=r["FinInstrmId"].strip() or None,
                isin=r["ISIN"].strip(),
                symbol=r["TckrSymb"].strip(),
                series=r["SctySrs"].strip(),
                name=r["FinInstrmNm"].strip() or None,
                open=to_price(parse_decimal(r["OpnPric"])),
                high=to_price(parse_decimal(r["HghPric"])),
                low=to_price(parse_decimal(r["LwPric"])),
                close=close,
                last=to_price(parse_decimal(r["LastPric"])),
                prev_close_reported=to_price(parse_decimal(r["PrvsClsgPric"])),
                volume=parse_int(r["TtlTradgVol"]),
                turnover_inr=to_inr(parse_decimal(r["TtlTrfVal"])),
                trades=parse_int(r["TtlNbOfTxsExctd"]),
            )
        except ValueError as exc:
            raise ParseError(f"line {i}: {exc}") from exc
        if not row.isin or not row.symbol or not row.series:
            raise ParseError(f"line {i}: blank ISIN/symbol/series")
        trade_dates.add(row.trade_date)
        rows.append(row)
    if len(trade_dates) != 1:
        raise ParseError(f"expected exactly one trade date, found {sorted(trade_dates)}")
    return rows
