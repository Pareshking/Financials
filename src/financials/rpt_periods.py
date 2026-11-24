"""Which period a filing's Reg. 23(9) amounts cover, checked across filings (rule RPT_BALANCE_ROLL, X358).

SEBI's format D asks for the half-year ending on the period end (X160), but a few filers put financial-year-to-date
amounts in the Q4 filing with nothing inside the filing to say so (X161). The balances tell them apart: a filing's
opening balance per counterparty and transaction type is the closing balance of the filing that ends where its
disclosure starts. Half-year amounts open on the closing of the filing six months earlier; twelve-month amounts open on
the closing of the filing a year earlier. Only pairs where those two closings differ can tell, so only they count.

Point in time: the earlier filings are the latest ones (same entity and scope) visible when the filing became visible.
Pure classification in `classify`; `classify_filings` reads every current-version row in one query.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from financials.parsers.reg23_rpt import REG23_PARSER_VERSION

RPT_PERIOD_RULE_VERSION = "rpt-period-1"
MIN_PAIRS = 3  # fewer telling pairs decide nothing
WIN_SHARE = Decimal("0.5")  # the deciding side explains at least half the telling pairs (new deals, netting: X358)
DOMINANCE = 3  # and at least three times the pairs the other side explains
REL_TOL = Decimal("0.005")  # filings round differently (rupees, thousands, lakhs)
ABS_TOL = Decimal(1000)

HALF_YEAR, TWELVE_MONTHS, UNDETERMINED, NO_HISTORY = "HALF_YEAR", "TWELVE_MONTHS", "UNDETERMINED", "NO_HISTORY"


def _norm(name: str) -> str:
    """Names differ in case, spacing and punctuation between filings ("VITROMED HEALTHCARE" / "Vitromed Health
    Care")."""
    return "".join(ch for ch in name.upper() if ch.isalnum())


def _same(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= max(ABS_TOL, REL_TOL * max(abs(a), abs(b)))


@dataclass(frozen=True)
class Basis:
    basis: str
    pairs: int  # telling pairs: both earlier closings present and different
    from_half: int
    from_year: int


def classify(
    opening: dict, half_ago_closing: dict | None, year_ago_closing: dict | None, *, year_end: bool = True
) -> Basis:
    """`opening`: {(counterparty, txn_type): opening balance} of the filing; the others: closing balances of the
    filings six and twelve months earlier (None when there is no such filing). `year_end`: the filing ends the
    financial year; only there can amounts cover twelve months (financial year to date, X161). At mid-year the year to
    date is the half-year, so a twelve-month roll there fits neither format: UNDETERMINED."""
    if half_ago_closing is None or year_ago_closing is None:
        return Basis(NO_HISTORY, 0, 0, 0)
    pairs = half = year = 0
    for key, op in opening.items():
        h, y = half_ago_closing.get(key), year_ago_closing.get(key)
        if h is None or y is None or _same(h, y):
            continue
        pairs += 1
        half += _same(op, h)
        year += _same(op, y)
    if pairs >= MIN_PAIRS and half >= WIN_SHARE * pairs and half >= DOMINANCE * year:
        return Basis(HALF_YEAR, pairs, half, year)
    if year_end and pairs >= MIN_PAIRS and year >= WIN_SHARE * pairs and year >= DOMINANCE * half:
        return Basis(TWELVE_MONTHS, pairs, half, year)
    return Basis(UNDETERMINED, pairs, half, year)


def balance_maps(rows) -> tuple[dict, dict]:
    """(opening, closing) per (counterparty, txn_type) from (counterparty, txn_type, opening, closing) tuples; several
    rows for one pair (several contracts with one party) add up."""
    opening: dict = defaultdict(Decimal)
    closing: dict = defaultdict(Decimal)
    for cp, typ, op, cl in rows:
        opening[(_norm(cp), typ)] += op or 0
        closing[(_norm(cp), typ)] += cl or 0
    return dict(opening), dict(closing)


def _months_back(d: date, months: int) -> date:
    """Month end `months` before the month end `d`."""
    y, m = divmod(d.year * 12 + d.month - 1 - months, 12)
    m += 1
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return date.fromordinal(nxt.toordinal() - 1)


def _start_after(end: date) -> date:
    return date.fromordinal(end.toordinal() + 1)


def classify_filings(con) -> list[dict]:
    """One row per filing with current-version Reg. 23(9) rows: its basis and the disclosure window it implies."""
    rows = con.execute(
        "SELECT r.filing_id, r.entity_id, r.scope, r.period_end, r.visible_from_ts, r.counterparty_name, r.txn_type, "
        "r.opening_balance_inr, r.closing_balance_inr, m.fy_end FROM reg23_related_party_transactions r "
        "LEFT JOIN (SELECT filing_id, max(fy_end) AS fy_end FROM filing_meta GROUP BY filing_id) m USING (filing_id) "
        "WHERE r.parser_version = ?",
        [REG23_PARSER_VERSION],
    ).fetchall()
    meta: dict[str, tuple] = {}
    opening: dict[str, dict] = defaultdict(lambda: defaultdict(Decimal))
    closing: dict[str, dict] = defaultdict(lambda: defaultdict(Decimal))
    fy_end: dict[str, date | None] = {}
    for fid, ent, scope, end, vis, cp, typ, op, cl, fye in rows:
        meta[fid] = (ent, scope, end, vis)
        fy_end[fid] = fye
        key = (_norm(cp), typ)
        opening[fid][key] += op or 0
        closing[fid][key] += cl or 0
    by_period: dict[tuple, list[tuple[datetime, str]]] = defaultdict(list)
    for fid, (ent, scope, end, vis) in meta.items():
        by_period[(ent, scope, end)].append((vis, fid))

    def earlier(ent, scope, end, as_of) -> str | None:
        seen = [(v, f) for v, f in by_period.get((ent, scope, end), []) if v <= as_of]
        return max(seen)[1] if seen else None  # the latest filing visible then (a revision replaces the original)

    out = []
    for fid, (ent, scope, end, vis) in sorted(meta.items()):
        half_end, year_end = _months_back(end, 6), _months_back(end, 12)
        h, y = earlier(ent, scope, half_end, vis), earlier(ent, scope, year_end, vis)
        b = classify(opening[fid], closing[h] if h else None, closing[y] if y else None,
                     year_end=fy_end[fid] is not None and fy_end[fid] == end)  # fmt: skip
        start = _start_after(year_end) if b.basis == TWELVE_MONTHS else _start_after(half_end)
        out.append({
            "filing_id": fid, "rule_version": RPT_PERIOD_RULE_VERSION, "entity_id": ent, "scope": scope,
            "period_end": end, "basis": b.basis, "disclosure_start": start,
            "disclosure_months": 12 if b.basis == TWELVE_MONTHS else 6, "pairs_compared": b.pairs,
            "pairs_from_half_year": b.from_half, "pairs_from_year": b.from_year, "half_year_ago_filing_id": h,
            "year_ago_filing_id": y, "visible_from_ts": vis,
        })  # fmt: skip
    return out


def write_periods(con) -> dict[str, int]:
    """Replace this rule version's rows (derived and deterministic; callers own the transaction)."""
    from financials.db import insert_rows

    rows = classify_filings(con)
    con.execute("DELETE FROM reg23_period_basis WHERE rule_version = ?", [RPT_PERIOD_RULE_VERSION])
    if rows:
        insert_rows(con, "reg23_period_basis", rows)
    counts: dict[str, int] = defaultdict(int)
    for r in rows:
        counts[r["basis"]] += 1
    return {"filings": len(rows), **dict(sorted(counts.items()))}
