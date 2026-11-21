"""NSE daily `PRddmmyy.zip` (archives/equities/bhavcopy/pr/): its market-capitalisation file `mcapddmmyyyy.csv`
[X130-X133].

The zip holds 14 files (readme, price bands, corporate actions, SME, ...); only the mcap file is parsed. Its member
name is `MCAPddmmyyyy.csv` up to Nov 2025 and `mcapddmmyyyy.csv` after (X130), so it is matched case-insensitively.
Values are space-padded fixed-width text between commas. The file ends with three summary rows (blank series:
`Listed`, `Permitted`, `Total` in the Symbol column) whose Market Cap is the sum of the security rows of that
category; the parser checks those sums (a truncated file fails) and does not return them as rows [X131].

Issue Size is the security's share count as NSE uses it (an exact integer); Market Cap is Issue Size times a price
within 2 paise of the printed close (X132), so it is kept as filed, never recomputed.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from financials.parsers import ParseError

HEADER = ("Trade Date", "Symbol", "Series", "Security Name", "Category", "Last Trade Date", "Face Value(Rs.)",
          "Issue Size", "Close Price/Paid up value(Rs.)", "Market Cap(Rs.)")  # fmt: skip
MEMBER = re.compile(r"mcap(\d{8})\.csv", re.IGNORECASE)
SUMMARY_ROWS = ("Listed", "Permitted", "Total")
NOT_TRADED = "Not Traded"  # Last Trade Date of a security that has never traded (X131)
SUM_TOLERANCE_PER_ROW = Decimal("0.01")  # each row is rounded to the paisa; the summary rows sum unrounded values


@dataclass(frozen=True)
class McapRow:
    exchange: str
    trade_date: date
    symbol: str
    series: str
    security_name: str
    category: str  # Listed | Permitted (permitted to trade, listed elsewhere)
    last_trade_date: date | None  # None = "Not Traded"
    face_value: Decimal
    issue_size: int
    close: Decimal  # "Close Price/Paid up value(Rs.)" as printed
    market_cap_inr: Decimal  # as filed, rupees


def _date(v: str, what: str) -> date:
    try:
        return datetime.strptime(v, "%d %b %Y").date()
    except ValueError as exc:
        raise ParseError(f"mcap: bad {what} {v!r}") from exc


def _dec(v: str, what: str) -> Decimal:
    try:
        return Decimal(v)
    except InvalidOperation as exc:
        raise ParseError(f"mcap: bad {what} {v!r}") from exc


def mcap_member(data: bytes) -> tuple[str, bytes]:
    """(member name, bytes) of the single mcap CSV inside a PR zip."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = [n for n in zf.namelist() if MEMBER.fullmatch(n)]
            if len(names) != 1:
                raise ParseError(f"PR zip: expected one mcap file, found {names}")
            return names[0], zf.read(names[0])
    except zipfile.BadZipFile as exc:
        raise ParseError(f"PR zip: {exc}") from exc


def parse_mcap_csv(data: bytes) -> list[McapRow]:
    """Security rows of one mcap file; the summary rows are checked against the sums and dropped."""
    text = data.decode("latin-1")  # ASCII in every file seen (X130); latin-1 never fails
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines or tuple(h.strip() for h in lines[0].split(",")) != HEADER:
        raise ParseError(f"mcap: unexpected header {lines[0][:200] if lines else ''!r}")
    rows: list[McapRow] = []
    totals: dict[str, Decimal] = {}
    for i, ln in enumerate(lines[1:], start=2):
        p = [x.strip() for x in ln.split(",")]
        if len(p) != len(HEADER):
            raise ParseError(f"mcap line {i}: {len(p)} fields")
        if not p[2] and p[1] in SUMMARY_ROWS:
            totals[p[1]] = _dec(p[9], "summary market cap")
            continue
        if not p[1] or not p[2]:
            raise ParseError(f"mcap line {i}: blank symbol / series")
        if not p[7].isdigit():
            raise ParseError(f"mcap line {i}: issue size {p[7]!r} is not an integer")
        rows.append(McapRow(
            exchange="NSE", trade_date=_date(p[0], "trade date"), symbol=p[1], series=p[2], security_name=p[3],
            category=p[4], last_trade_date=None if p[5] == NOT_TRADED else _date(p[5], "last trade date"),
            face_value=_dec(p[6], "face value"), issue_size=int(p[7]), close=_dec(p[8], "close"),
            market_cap_inr=_dec(p[9], "market cap"),
        ))  # fmt: skip
    if not rows:
        raise ParseError("mcap: no security rows")
    if len({r.trade_date for r in rows}) != 1:
        raise ParseError("mcap: more than one trade date")
    if len({(r.symbol, r.series) for r in rows}) != len(rows):
        raise ParseError("mcap: duplicate symbol / series")
    _check_totals(rows, totals)
    return rows


def _check_totals(rows: list[McapRow], totals: dict[str, Decimal]) -> None:
    if set(totals) != set(SUMMARY_ROWS):
        raise ParseError(f"mcap: summary rows {sorted(totals)} (truncated file?)")
    sums = {c: sum((r.market_cap_inr for r in rows if r.category == c), Decimal(0)) for c in ("Listed", "Permitted")}
    counts = {c: sum(r.category == c for r in rows) for c in ("Listed", "Permitted")}
    if unknown := {r.category for r in rows} - set(sums):
        raise ParseError(f"mcap: unknown category {sorted(unknown)}")
    checks = [(c, sums[c], totals[c], counts[c]) for c in sums]
    checks.append(("Total", sums["Listed"] + sums["Permitted"], totals["Total"], len(rows)))
    for name, got, filed, n in checks:
        if abs(got - filed) > SUM_TOLERANCE_PER_ROW * max(n, 1):
            raise ParseError(f"mcap: {name} rows sum to {got}, summary row says {filed} (truncated file?)")


def parse_pr_mcap(data: bytes) -> list[McapRow]:
    """The mcap rows of a PRddmmyy.zip; the member's date must equal the rows' trade date."""
    name, csv_bytes = mcap_member(data)
    rows = parse_mcap_csv(csv_bytes)
    stamp = datetime.strptime(MEMBER.fullmatch(name).group(1), "%d%m%Y").date()
    if stamp != rows[0].trade_date:
        raise ParseError(f"PR zip: member {name} holds trade date {rows[0].trade_date}")
    return rows
