"""Exact decimal handling. Money is DECIMAL(20,2) rupees; never float."""

from __future__ import annotations

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
