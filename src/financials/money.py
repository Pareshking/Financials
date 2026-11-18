"""Exact decimal handling. Money is DECIMAL(20,2) rupees; never float."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

INR_QUANTUM = Decimal("0.01")
PRICE_QUANTUM = Decimal("0.0001")

# Rupee value of one unit for XBRL `LevelOfRounding` [references X4/X5].
ROUNDING_UNITS: dict[str, Decimal] = {
    "Rupees": Decimal(1),
    "Thousands": Decimal(10) ** 3,
    "Lakhs": Decimal(10) ** 5,
    "Millions": Decimal(10) ** 6,
    "Crores": Decimal(10) ** 7,
}

_MISSING = {"", "-", "NA", "N.A.", "nil"}


def parse_decimal(text: str | None) -> Decimal | None:
    """Parse an exchange-file number; blanks and '-' mean missing."""
    if text is None:
        return None
    s = text.strip().replace(",", "")
    if s in _MISSING:
        return None
    try:
        return Decimal(s)
    except InvalidOperation as exc:
        raise ValueError(f"not a number: {text!r}") from exc


def parse_int(text: str | None) -> int | None:
    d = parse_decimal(text)
    if d is None:
        return None
    if d != d.to_integral_value():
        raise ValueError(f"not an integer: {text!r}")
    return int(d)


def to_inr(value: Decimal | None) -> Decimal | None:
    return None if value is None else value.quantize(INR_QUANTUM, rounding=ROUND_HALF_EVEN)


def to_price(value: Decimal | None) -> Decimal | None:
    return None if value is None else value.quantize(PRICE_QUANTUM, rounding=ROUND_HALF_EVEN)


def identity_tolerance(level_of_rounding: str, n_terms: int) -> Decimal:
    """Allowed absolute rupee mismatch for an identity with `n_terms` rounded addends."""
    return ROUNDING_UNITS[level_of_rounding] * Decimal("0.5") * n_terms


# Rule ROUNDING_ONLY [X260] (owner 2026-11-18: "Ignore rounding errors if any"). Every figure a filing states is
# rounded to its LevelOfRounding, so it is off by at most half a unit. A comparison of rounded figures (a total
# against the sum of N rounded lines, the same line in two filings, ...) can therefore differ by rounding alone by at
# most half a unit per figure compared: the sum of the figures' units / 2. Where the figures' own filings are not
# known one by one (a factbook mixes filings), every figure counts at the coarsest unit of the filings compared:
# (N addends + the total) x coarser unit / 2. `units` lists one unit per rounded figure on both sides, including a
# derived figure's own addends (pbt_incl_jv = PBT + JV share: two figures in a period whose JV share is filed). A
# difference within that bound is a rounding difference, never a finding. Worst case and deterministic; nothing is
# corrected. The checks already built on it: the YTD identity [X80] ((n + 1) x coarsest unit / 2), the annual
# prior-year comparison [X110] (half a unit of each of the two filings), share capital in whole units [X188].
ROUNDING_ONLY_RULE = "ROUNDING_ONLY"


def rounding_only_tolerance(units: Iterable[Decimal]) -> Decimal:
    """X260: largest rupee difference rounding alone can produce between rounded figures, one rupee unit per
    figure (ROUNDING_UNITS of each figure's LevelOfRounding, or the coarser unit when unknown per figure)."""
    units = [Decimal(u) for u in units]
    if not units or any(u <= 0 for u in units):
        raise ValueError(f"need one positive unit per rounded figure, got {units}")
    return sum(units, Decimal(0)) / 2


def within_rounding_only(difference: Decimal, units: Iterable[Decimal]) -> bool:
    """X260: True when `difference` (rupees) is explained by rounding alone (see rounding_only_tolerance)."""
    return abs(Decimal(difference)) <= rounding_only_tolerance(units)
