"""Security identity across ISIN, symbol and series changes.

Evidence (docs/references.md):
- a split changes the ISIN but keeps `FinInstrmId` [P5, P8];
- a series change (EQ↔BE↔BZ) keeps the ISIN but changes `FinInstrmId` [P13].

So a row continues an existing security if **either** its `FinInstrmId` has belonged to it
or its ISIN is currently held by it. If the two keys point at different securities the row
is quarantined (`ISIN_COLLISION`). A split coinciding with a series change on the same day
would create a new security; that is rare and surfaces through the gap auditor.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date

from financials.ids import stable_id
from financials.parsers.udiff import BhavRow

UNIVERSE_SERIES = frozenset({"EQ", "BE", "BZ"})


@dataclass(frozen=True)
class Interval:
    security_id: str
    exchange: str
    fin_instrm_id: str | None
    symbol: str
    series: str
    isin: str
    valid_from: date
    valid_to: date | None = None  # exclusive
    evidence_filing_id: str | None = None


@dataclass(frozen=True)
class NewSecurity:
    security_id: str
    entity_id: str
    legal_name: str


@dataclass(frozen=True)
class IdentityEvent:
    kind: str  # NEW_SECURITY | ISIN_CHANGE | SYMBOL_CHANGE | SERIES_CHANGE | FIN_INSTRM_ID_CHANGE
    security_id: str
    trade_date: date
    old: str | None
    new: str


@dataclass(frozen=True)
class IdentityIssue:
    reason_code: str  # MISSING_FIN_INSTRM_ID | ISIN_COLLISION | OUT_OF_ORDER | DUPLICATE_IN_FILE
    trade_date: date
    details: dict


@dataclass
class ObservationResult:
    resolved: dict[tuple[str, str], str]  # (symbol, series) -> security_id
    new_securities: list[NewSecurity]
    closed: list[Interval]  # intervals whose valid_to was just set
    opened: list[Interval]
    events: list[IdentityEvent]
    issues: list[IdentityIssue]


class SecurityRegistry:
    """In-memory view of identifier intervals for one exchange."""

    def __init__(self, exchange: str, intervals: Iterable[Interval] = ()) -> None:
        self.exchange = exchange
        self._current: dict[str, Interval] = {}  # security_id -> open interval
        self._fid_owner: dict[str, str] = {}  # every FinInstrmId ever seen -> security_id
        self._isin_owner: dict[str, str] = {}  # ISIN of an open interval -> security_id
        self._last_seen: dict[str, date] = {}
        for iv in intervals:
            if iv.exchange != exchange:
                continue
            if iv.fin_instrm_id:
                self._fid_owner[iv.fin_instrm_id] = iv.security_id
            prev = self._last_seen.get(iv.security_id)
            self._last_seen[iv.security_id] = iv.valid_from if prev is None else max(prev, iv.valid_from)
            if iv.valid_to is None:
                self._current[iv.security_id] = iv
                self._isin_owner[iv.isin] = iv.security_id

    def current(self, security_id: str) -> Interval | None:
        return self._current.get(security_id)

    def owner_of_fin_instrm_id(self, fin_instrm_id: str) -> str | None:
        return self._fid_owner.get(fin_instrm_id)

    def observe(self, rows: Iterable[BhavRow], filing_id: str | None = None) -> ObservationResult:
        """Apply one trading day's rows (non-universe series are ignored). Days must arrive in order."""
        out = ObservationResult({}, [], [], [], [], [])
        seen_today: set[str] = set()
        for row in rows:
            if row.series not in UNIVERSE_SERIES or row.exchange != self.exchange:
                continue
            fid = row.fin_instrm_id
            if not fid:
                out.issues.append(
                    IdentityIssue("MISSING_FIN_INSTRM_ID", row.trade_date, {"symbol": row.symbol, "isin": row.isin})
                )
                continue
            by_fid = self._fid_owner.get(fid)
            by_isin = self._isin_owner.get(row.isin)
            sec_id = by_fid or by_isin
            if sec_id is not None:
                last = self._last_seen.get(sec_id)
                if last is not None and row.trade_date < last:
                    out.issues.append(
                        IdentityIssue("OUT_OF_ORDER", row.trade_date, {"security_id": sec_id, "last_seen": str(last)})
                    )
                    continue
            if by_fid and by_isin and by_fid != by_isin:
                out.issues.append(
                    IdentityIssue(
                        "ISIN_COLLISION",
                        row.trade_date,
                        {"fin_instrm_id": fid, "isin": row.isin, "fid_owner": by_fid, "isin_owner": by_isin},
                    )
                )
                continue
            if sec_id is not None and sec_id in seen_today:
                out.issues.append(IdentityIssue("DUPLICATE_IN_FILE", row.trade_date, {"security_id": sec_id}))
                continue

            if sec_id is None:
                sec_id = stable_id("sec", self.exchange, fid, row.isin)
                ent_id = stable_id("ent", self.exchange, fid, row.isin)
                out.new_securities.append(NewSecurity(sec_id, ent_id, row.name or row.symbol))
                iv = Interval(
                    sec_id,
                    self.exchange,
                    fid,
                    row.symbol,
                    row.series,
                    row.isin,
                    row.trade_date,
                    None,
                    filing_id,
                )
                out.opened.append(iv)
                out.events.append(IdentityEvent("NEW_SECURITY", sec_id, row.trade_date, None, row.isin))
                self._current[sec_id] = iv
            else:
                cur = self._current.get(sec_id)
                if cur is None:  # only closed intervals known: reopen from this row
                    cur = Interval(sec_id, self.exchange, None, "", "", "", row.trade_date)
                changes = [
                    (kind, old, new)
                    for kind, old, new in (
                        ("ISIN_CHANGE", cur.isin, row.isin),
                        ("SYMBOL_CHANGE", cur.symbol, row.symbol),
                        ("SERIES_CHANGE", cur.series, row.series),
                        ("FIN_INSTRM_ID_CHANGE", cur.fin_instrm_id, fid),
                    )
                    if old != new
                ]
                if changes:
                    if cur.valid_from == row.trade_date and cur.isin:
                        out.issues.append(
                            IdentityIssue(
                                "OUT_OF_ORDER",
                                row.trade_date,
                                {"security_id": sec_id, "reason": "change on same day"},
                            )
                        )
                        continue
                    new_iv = Interval(
                        sec_id,
                        self.exchange,
                        fid,
                        row.symbol,
                        row.series,
                        row.isin,
                        row.trade_date,
                        None,
                        filing_id,
                    )
                    if cur.isin:  # a real open interval
                        out.closed.append(replace(cur, valid_to=row.trade_date))
                        self._isin_owner.pop(cur.isin, None)
                        out.events.extend(IdentityEvent(k, sec_id, row.trade_date, o, n) for k, o, n in changes)
                    out.opened.append(new_iv)
                    self._current[sec_id] = new_iv
            self._fid_owner[fid] = sec_id
            self._isin_owner[row.isin] = sec_id
            self._last_seen[sec_id] = row.trade_date
            seen_today.add(sec_id)
            out.resolved[(row.symbol, row.series)] = sec_id
        return out
