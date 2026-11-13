"""Corporate-action factors, verification and the unconditional gap auditor.

docs/architecture.md §11. Factors multiply history strictly before `ex_date`.
Exchange `PrvsClsgPric` is unadjusted on ex-dates [references P2], so verification
compares the theoretical factor with the observed Open_ex / Close_{ex-1} gap.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

SHARE_COUNT_TYPES = frozenset({"SPLIT", "CONSOLIDATION", "BONUS", "RIGHTS"})
ACTION_TYPES = SHARE_COUNT_TYPES | {"DEMERGER", "MERGER", "DIVIDEND", "BUYBACK", "UNKNOWN"}  # UNKNOWN = unparsed
ACCEPTED_STATUSES = frozenset({"VERIFIED", "UNOBSERVABLE", "VERIFIED_MANUAL"})
# Out of every computation: SUPERSEDED (replaced by a manual action on the same date), REJECTED (a human ruled
# the record wrong). Kept in the ledger for audit, never deleted.
RETIRED_STATUSES = frozenset({"SUPERSEDED", "REJECTED"})

VERIFY_TOLERANCE = Decimal("0.10")  # |observed/theoretical - 1|
UNOBSERVABLE_BAND = Decimal("0.10")  # |factor - 1| below this is indistinguishable from noise
GAP_THRESHOLD = Decimal("0.10")  # references C4


@dataclass(frozen=True)
class CorpAction:
    """Ratios: SPLIT/CONSOLIDATION num=new face value, den=old face value;
    BONUS/RIGHTS num=new shares (A), den=shares held (B)."""

    action_id: str
    security_id: str
    action_type: str
    ex_date: date
    ratio_num: Decimal | None = None
    ratio_den: Decimal | None = None
    issue_price: Decimal | None = None
    cash_per_share: Decimal | None = None
    status: str = "PENDING"
    price_factor: Decimal | None = None
    eps_factor: Decimal | None = None

    def __post_init__(self) -> None:
        if self.action_type not in ACTION_TYPES:
            raise ValueError(f"unknown action_type {self.action_type!r}")


@dataclass(frozen=True)
class Verification:
    status: str
    price_factor: Decimal | None
    eps_factor: Decimal | None
    observed_gap: Decimal | None
    reason: str


def _need(value: Decimal | None, name: str, action: CorpAction) -> Decimal:
    if value is None or value <= 0:
        raise ValueError(f"{action.action_type} {action.action_id}: {name} must be positive")
    return value


def theoretical_factors(action: CorpAction, close_prev: Decimal | None) -> tuple[Decimal | None, Decimal]:
    """(price_factor, eps_factor). price_factor is None for DEMERGER (defined by the market)."""
    t = action.action_type
    if t in ("SPLIT", "CONSOLIDATION"):
        f = _need(action.ratio_num, "ratio_num", action) / _need(action.ratio_den, "ratio_den", action)
        if (t == "SPLIT") != (f < 1):
            raise ValueError(f"{t} {action.action_id}: face value must {'fall' if t == 'SPLIT' else 'rise'}")
        return f, f
    if t == "BONUS":
        a, b = _need(action.ratio_num, "ratio_num", action), _need(action.ratio_den, "ratio_den", action)
        f = b / (a + b)
        return f, f
    if t == "RIGHTS":
        a, b = _need(action.ratio_num, "ratio_num", action), _need(action.ratio_den, "ratio_den", action)
        p = action.issue_price
        if p is None or p < 0:
            raise ValueError(f"RIGHTS {action.action_id}: issue_price required")
        c = _need(close_prev, "close_prev", action)
        f = (b * c + a * p) / ((a + b) * c)
        return f, f
    if t == "DEMERGER":
        return None, Decimal(1)
    if t == "UNKNOWN":
        raise ValueError(f"{action.action_id}: unparsed corporate action cannot be factored")
    return Decimal(1), Decimal(1)  # MERGER (acquirer), DIVIDEND, BUYBACK: never adjust prices [C2, CA10]


def verify_group(actions: list[CorpAction], open_ex: Decimal | None, close_prev: Decimal | None) -> list[Verification]:
    """Verify all actions of one security on one ex-date together (e.g. NAZARA split + bonus).

    The observed gap reflects the product of every factor that day, so members are judged on
    the combined factor. A DEMERGER absorbs whatever the other members do not explain [C3].
    One unfactorable member (UNKNOWN or bad ratios) quarantines the whole group.
    """
    observed = open_ex / close_prev if open_ex is not None and close_prev else None
    factors: list[tuple[Decimal | None, Decimal]] = []
    try:
        for a in actions:
            factors.append(theoretical_factors(a, close_prev))
    except ValueError as exc:
        return [Verification("QUARANTINED", None, None, observed, str(exc)) for _ in actions]

    known = Decimal(1)
    for price_f, _ in factors:
        if price_f is not None:
            known *= price_f
    demergers = [i for i, a in enumerate(actions) if a.action_type == "DEMERGER"]

    if demergers:
        if observed is None or len(demergers) > 1:
            reason = "no ex-date open/prior close" if observed is None else "several demergers on one date"
            return [Verification("QUARANTINED", f, e, observed, reason) for f, e in factors]
        out = []
        for i, (price_f, eps_f) in enumerate(factors):
            pf = observed / known if i in demergers else price_f
            out.append(Verification("VERIFIED", pf, eps_f, observed, "demerger absorbs residual gap [C3]"))
        return out

    if abs(known - 1) < UNOBSERVABLE_BAND:
        return [Verification("UNOBSERVABLE", f, e, observed, "combined factor within noise band") for f, e in factors]
    if observed is None:
        return [Verification("QUARANTINED", f, e, None, "no ex-date open/prior close") for f, e in factors]
    if abs(observed / known - 1) <= VERIFY_TOLERANCE:
        return [Verification("VERIFIED", f, e, observed, "observed gap matches combined factor") for f, e in factors]
    return [
        Verification("QUARANTINED", f, e, observed, "observed gap does not match combined factor") for f, e in factors
    ]


def verify_action(action: CorpAction, open_ex: Decimal | None, close_prev: Decimal | None) -> Verification:
    return verify_group([action], open_ex, close_prev)[0]


@dataclass(frozen=True)
class GapFinding:
    security_id: str
    trade_date: date
    reason_code: str  # UNEXPLAINED_GAP | ISIN_CHANGE_WITHOUT_ACTION
    gap: Decimal | None


def audit_day(
    security_id: str,
    trade_date: date,
    open_t: Decimal | None,
    close_prev: Decimal | None,
    actions_on_date: Iterable[CorpAction],
    isin_changed: bool,
) -> list[GapFinding]:
    """Unconditional gap auditor for one security-day (architecture §11.3).

    A gap is explained only if dividing out the accepted price factors of that day leaves a
    residual within the threshold. A dividend (factor 1) therefore never explains a large gap.
    """
    actions = list(actions_on_date)
    accepted = [a for a in actions if a.status in ACCEPTED_STATUSES]
    combined = Decimal(1)
    for a in accepted:
        if a.price_factor is None:
            raise ValueError(f"accepted action {a.action_id} has no price factor")
        combined *= a.price_factor
    findings: list[GapFinding] = []
    gap = open_t / close_prev - 1 if open_t is not None and close_prev else None
    if gap is not None:
        residual = open_t / (close_prev * combined) - 1
        if abs(residual) > GAP_THRESHOLD:
            findings.append(GapFinding(security_id, trade_date, "UNEXPLAINED_GAP", gap))
    if isin_changed and not any(a.action_type in ("SPLIT", "CONSOLIDATION") for a in accepted):
        findings.append(GapFinding(security_id, trade_date, "ISIN_CHANGE_WITHOUT_ACTION", gap))
    return findings


def cumulative_factor(actions: Iterable[CorpAction], on_date: date, *, kind: str = "price") -> Decimal:
    """Product of accepted factors with ex_date > on_date (multiply a raw value on `on_date`)."""
    total = Decimal(1)
    for a in actions:
        if a.status not in ACCEPTED_STATUSES or a.ex_date <= on_date:
            continue
        f = a.price_factor if kind == "price" else a.eps_factor
        if f is None:
            raise ValueError(f"accepted action {a.action_id} has no {kind} factor")
        total *= f
    return total


def adjust_closes(
    bars: Iterable[tuple[date, Decimal]],
    actions: Iterable[CorpAction],
    frozen_from: date | None = None,
) -> list[tuple[date, Decimal]]:
    """Back-adjusted closes. Bars on/after `frozen_from` (first unresolved gap) are withheld."""
    actions = list(actions)
    out = []
    for d, close in sorted(bars):
        if frozen_from is not None and d >= frozen_from:
            break
        out.append((d, close * cumulative_factor(actions, d)))
    return out
