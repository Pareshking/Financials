"""NSE daily `PRddmmyy.zip`: its price-band file `bhddmmyy(yy).csv` [X359].

NSE's readme: "bhddmmyyyy.csv file contains a list of securities which have hit their price bands during the day."
Header `SYMBOL,SERIES,SECURITY,HIGH/LOW` (2024-2025 zips add `,INDEX FLAG`, never filled in a data row); one row per
security that touched its band, `H` (upper) or `L` (lower), every series (EQ, BE, SM, GS, ...). The member is
`bhddmmyy.csv` up to 2025 and `bhddmmyyyy.csv` after; the trade date comes from the name. Kept as filed, every
series: the universe filter is the reader's.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime

from financials.parsers import ParseError

MEMBER = re.compile(r"bh(\d{6}|\d{8})\.csv", re.IGNORECASE)
HEADERS = (("SYMBOL", "SERIES", "SECURITY", "HIGH/LOW"), ("SYMBOL", "SERIES", "SECURITY", "HIGH/LOW", "INDEX FLAG"))
BANDS = ("H", "L")


@dataclass(frozen=True)
class BandHitRow:
    exchange: str
    trade_date: date
    symbol: str
    series: str
    security_name: str
    band: str  # H = upper band, L = lower band


def parse_price_band_hits(data: bytes) -> list[BandHitRow]:
    """Rows of the bh member of one PR zip (an empty list on a day no security touched a band)."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = [n for n in zf.namelist() if MEMBER.fullmatch(n)]
            if len(names) != 1:
                raise ParseError(f"PR zip: expected one bh file, found {names}")
            name, body = names[0], zf.read(names[0])
    except zipfile.BadZipFile as exc:
        raise ParseError(f"PR zip: {exc}") from exc
    digits = MEMBER.fullmatch(name).group(1)
    day = datetime.strptime(digits, "%d%m%y" if len(digits) == 6 else "%d%m%Y").date()
    lines = [ln for ln in body.decode("latin-1").splitlines() if ln.strip()]
    if not lines or tuple(h.strip() for h in lines[0].split(",")) not in HEADERS:
        raise ParseError(f"bh: unexpected header {lines[0][:200] if lines else ''!r}")
    rows, seen = [], set()
    for i, ln in enumerate(lines[1:], start=2):
        p = [x.strip() for x in ln.split(",")]
        if len(p) == 5 and not p[4]:
            p = p[:4]
        if len(p) != 4 or not p[0] or not p[1] or p[3] not in BANDS:
            raise ParseError(f"bh line {i}: {ln[:120]!r}")
        if (p[0], p[1], p[3]) in seen:
            raise ParseError(f"bh line {i}: duplicate {p[0]} {p[1]} {p[3]}")
        seen.add((p[0], p[1], p[3]))
        rows.append(BandHitRow("NSE", day, p[0], p[1], p[2], p[3]))
    return rows
