"""BSE list of securities (`ListofScripData/w`, the `bse` package's `listSecurities`, one BSE group per answer)
[A17, X169]: a JSON list, one object per active security, `SCRIP_CD` (BSE scrip code), `ISIN_NUMBER`, `scrip_id`
(BSE ticker), `GROUP`, `FACE_VALUE`, `Status`, `Segment`, `Scrip_Name`, `Issuer_Name` and `Mktcap` (Rs crore, two
decimals, as text). Pure: bytes -> rows; identifiers kept as sent, the market cap converted exactly to rupees.

Rule BSE2 [X200]: a row without an ISIN (blank or `NA`, as in group Y of 2026-11-17: A D S Diagnostics 523031 and
Pushpsons 531562) cannot be matched to anything (rule BSE1 keys on ISIN) and is skipped; the rest of the list is
kept. Any other malformed row (a non-digit code, an ISIN of the wrong length, a code twice) still rejects the answer."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from financials.parsers import ParseError

REQUIRED = ("SCRIP_CD", "ISIN_NUMBER", "scrip_id", "GROUP", "Status", "Segment", "Scrip_Name", "Mktcap")
CRORE = Decimal(10_000_000)
NO_ISIN = frozenset({"", "NA"})  # rule BSE2: what BSE sends for a security without an ISIN


@dataclass(frozen=True)
class BseSecurity:
    scrip_code: str
    isin: str
    ticker: str
    bse_group: str
    status: str
    segment: str
    name: str
    issuer_name: str | None
    face_value: Decimal | None
    market_cap_inr: Decimal | None  # Mktcap (Rs crore) x 1e7, exact; NULL when blank


def _dec(v, field: str, i: int) -> Decimal | None:
    s = str(v).replace(",", "").strip() if v is not None else ""
    if not s:
        return None
    try:
        return Decimal(s)
    except InvalidOperation as exc:
        raise ParseError(f"row {i}: {field} {v!r} is not a number") from exc


def parse_list_securities(data: bytes) -> list[BseSecurity]:
    try:
        rows = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ParseError(f"BSE list of securities: not JSON ({exc})") from exc
    if not isinstance(rows, list):
        raise ParseError("BSE list of securities: not a JSON list")
    out, codes = [], set()
    for i, r in enumerate(rows):
        missing = [k for k in REQUIRED if k not in r]
        if missing:
            raise ParseError(f"row {i}: missing {missing}")
        code, isin = str(r["SCRIP_CD"]).strip(), str(r["ISIN_NUMBER"] or "").strip()
        if code.isdigit() and isin.upper() in NO_ISIN:  # BSE2
            continue
        if not code.isdigit() or len(isin) != 12:
            raise ParseError(f"row {i}: scrip code {code!r} / ISIN {isin!r} malformed")
        if code in codes:
            raise ParseError(f"row {i}: scrip code {code} twice")
        codes.add(code)
        cr = _dec(r["Mktcap"], "Mktcap", i)
        out.append(BseSecurity(
            scrip_code=code, isin=isin, ticker=str(r["scrip_id"] or "").strip(), bse_group=str(r["GROUP"]).strip(),
            status=str(r["Status"]).strip(), segment=str(r["Segment"]).strip(), name=str(r["Scrip_Name"]).strip(),
            issuer_name=(str(r.get("Issuer_Name") or "").strip() or None),
            face_value=_dec(r.get("FACE_VALUE"), "FACE_VALUE", i),
            market_cap_inr=None if cr is None else (cr * CRORE).quantize(Decimal("0.01")),
        ))  # fmt: skip
    return out
