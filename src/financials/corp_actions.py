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
ACTION_TYPES = SHARE_COUNT_TYPES | {"DEMERGER", "MERGER", "DIVIDEND"}
ACCEPTED_STATUSES = frozenset({"VERIFIED", "UNOBSERVABLE", "VERIFIED_MANUAL"})

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
    return Decimal(1), Decimal(1)  # MERGER (acquirer), DIVIDEND: never adjust prices [C2]


def verify_action(action: CorpAction, open_ex: Decimal | None, close_prev: Decimal | None) -> Verification:
    observed = open_ex / close_prev if open_ex is not None and close_prev else None
    try:
        price_f, eps_f = theoretical_factors(action, close_prev)
    except ValueError as exc:
        return Verification("QUARANTINED", None, None, observed, str(exc))

    if action.action_type == "DEMERGER":
        if observed is None:
            return Verification("QUARANTINED", None, eps_f, None, "no ex-date open/prior close")
        return Verification("VERIFIED", observed, eps_f, observed, "factor defined by observed gap [C3]")
    assert price_f is not None
    if abs(price_f - 1) < UNOBSERVABLE_BAND:
        return Verification("UNOBSERVABLE", price_f, eps_f, observed, "factor within noise band")
    if observed is None:
        return Verification("QUARANTINED", price_f, eps_f, None, "no ex-date open/prior close")
    if abs(observed / price_f - 1) <= VERIFY_TOLERANCE:
        return Verification("VERIFIED", price_f, eps_f, observed, "observed gap matches factor")
    return Verification("QUARANTINED", price_f, eps_f, observed, "observed gap does not match factor")


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
    """Unconditional gap auditor for one security-day (architecture §11.3)."""
    actions = list(actions_on_date)
    explained = any(a.status in ACCEPTED_STATUSES for a in actions)
    findings: list[GapFinding] = []
    gap = open_t / close_prev - 1 if open_t is not None and close_prev else None
    if gap is not None and abs(gap) > GAP_THRESHOLD and not explained:
        findings.append(GapFinding(security_id, trade_date, "UNEXPLAINED_GAP", gap))
    if isin_changed and not any(
        a.action_type in ("SPLIT", "CONSOLIDATION") and a.status in ACCEPTED_STATUSES for a in actions
    ):
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
