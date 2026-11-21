"""X201 rule LEVEL_OF_ROUNDING_SLIP: one results filing declares the wrong `LevelOfRounding`.

The NSE filing utility multiplies what the filer types by the declared unit (X4: XBRL values are absolute rupees). A
filer who types its usual unit (crores) under another declared unit (lakhs) files every amount off by exactly the unit
ratio, while per-share values (EPS, face value) are typed per share and stay right. Nothing inside the filing shows it
(EPS = PAT / (paid-up / face value) holds at both scales), so the proof uses three facts from outside the filing's
amounts, each of which is independent of the declared unit:

  A. paid-up equity capital against the entity's other filings (same scope) that declare the usual unit;
  B. paid-up capital against the shareholding pattern's total shares x the filing's own face value;
  C. the filing's own basic EPS x the shareholding pattern's total shares against its profit (owners' share).

Each check reads SLIP (off by the unit ratio k), GENUINE (ratio 1) or NA. The filing is rescaled by k only when at
least two checks read SLIP at the same k and none reads GENUINE. A company that changed its unit for good files right
values in the new unit (all checks GENUINE) and is never touched. Navneet Education Q4 FY26 consolidated (1670953,
`Lakhs`; Q1-Q3 `Crores`): paid-up 0.44 Cr vs 44.00 Cr, SHP 22.12 Cr shares x Rs 2 = 44.24 Cr; FY revenue 17.21 Cr
becomes 1,721 Cr = the quarters 794 + 247 + 250 + 430.

X235: the same proof applies to a Reg. 34 annual filing (`admin._annual_level_slips`): its FY-end equity share capital,
the face value of the nearest results filing and its full-year EPS and profit stand in for the quarter's facts, and
the entity-scope's quarterly results are its neighbours (TD Power Systems consolidated FY25 and FY26, `Rupees`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from financials.money import ROUNDING_UNITS

RULE = "LEVEL_OF_ROUNDING_SLIP"
# paid-up capital (checks A, B) is a stated amount: 2% covers the declared rounding of a small capital (0.44 Cr in
# lakhs) and share issues between the filing and its neighbours' quarter ends. EPS (check C) is rounded to the paisa
# and weighted over the period: 10%.
CAPITAL_TOLERANCE = Decimal("0.02")
EPS_TOLERANCE = Decimal("0.10")
MIN_SLIP_CHECKS = 2


@dataclass(frozen=True)
class SlipCheck:
    name: str
    ratio: Decimal | None  # observed / expected-if-genuine
    verdict: str  # SLIP | GENUINE | NA


@dataclass(frozen=True)
class SlipVerdict:
    factor: Decimal  # multiply the filing's rupee amounts by this
    declared: str
    usual: str
    checks: tuple[SlipCheck, ...] = field(default_factory=tuple)

    def evidence(self) -> str:
        parts = [f"{c.name}={'NA' if c.ratio is None else f'{c.ratio:.4f}'}:{c.verdict}" for c in self.checks]
        return f"{RULE}: declared {self.declared}, usual {self.usual}, factor {self.factor:f}; " + ", ".join(parts)


def _verdict(ratio: Decimal | None, k: Decimal, tol: Decimal) -> str:
    if ratio is None:
        return "NA"
    if abs(ratio / k - 1) <= tol:
        return "SLIP"
    if abs(ratio - 1) <= tol:
        return "GENUINE"
    return "NA"


def _median(xs: list[Decimal]) -> Decimal:
    s = sorted(xs)
    return s[len(s) // 2]


def usual_level(neighbour_levels: list[str]) -> str | None:
    """The level most of the entity-scope's other filings declare (ties: none, nothing is usual)."""
    counts: dict[str, int] = {}
    for lvl in neighbour_levels:
        counts[lvl] = counts.get(lvl, 0) + 1
    if not counts:
        return None
    top = sorted(counts.items(), key=lambda x: -x[1])
    if len(top) > 1 and top[0][1] == top[1][1]:
        return None
    return top[0][0]


def level_slip(
    declared: str | None,
    neighbour_levels: list[str],
    *,
    paid_up: Decimal | None,
    neighbour_paid_ups: list[Decimal],
    face_value: Decimal | None,
    shp_shares: int | Decimal | None,
    eps_basic: Decimal | None,
    profit: Decimal | None,
) -> SlipVerdict | None:
    """The rescale factor of one filing, or None. `neighbour_paid_ups`: paid-up capital (rupees) of the entity-scope's
    other filings that declare the usual level; `shp_shares`: total shares of the shareholding pattern nearest the
    filing's quarter end; `eps_basic` / `profit`: the filing's own quarter (owners' profit where filed)."""
    usual = usual_level(neighbour_levels)
    if declared not in ROUNDING_UNITS or usual not in ROUNDING_UNITS or usual == declared:
        return None
    k = ROUNDING_UNITS[usual] / ROUNDING_UNITS[declared]
    pu = Decimal(paid_up) if paid_up else None
    nb = [Decimal(x) for x in neighbour_paid_ups if x]
    a = (_median(nb) / pu) if pu and nb else None  # neighbours / own: k when slipped
    b = (Decimal(shp_shares) * Decimal(face_value) / pu) if pu and shp_shares and face_value else None
    c = (Decimal(eps_basic) * Decimal(shp_shares) / Decimal(profit)) if eps_basic and shp_shares and profit else None
    checks = (
        SlipCheck("PAIDUP_VS_NEIGHBOURS", a, _verdict(a, k, CAPITAL_TOLERANCE)),
        SlipCheck("SHP_SHARES_X_FACE_VALUE_VS_PAIDUP", b, _verdict(b, k, CAPITAL_TOLERANCE)),
        SlipCheck("EPS_X_SHP_SHARES_VS_PROFIT", c, _verdict(c, k, EPS_TOLERANCE)),
    )
    if any(x.verdict == "GENUINE" for x in checks) or sum(x.verdict == "SLIP" for x in checks) < MIN_SLIP_CHECKS:
        return None
    return SlipVerdict(k, declared, usual, checks)


def rescaled(value: Decimal, factor: Decimal) -> Decimal:
    """A rupee amount times the unit ratio, to the paisa (exact for every pair of ROUNDING_UNITS)."""
    return (Decimal(value) * factor).quantize(Decimal("0.01"))
