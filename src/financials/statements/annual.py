"""Annual fixed-asset schedule (Mandate 4 sub-rows) from a Reg. 34 annual filing [X71].

Rows follow Screener's fixed-asset breakdown: Land, Building, Plant & Machinery, Equipments, Computers,
Furniture n fittings, Vehicles, Other fixed assets (gross block by class), Gross Block, Accumulated Depreciation,
Net PPE, Intangible Assets (net), CWIP. Tie-outs: classes sum to Gross Block, Gross - Accumulated = Net PPE.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from financials.statements.quarterly import QuarterStatement, Row

ZERO = Decimal(0)
CLASS_ROWS = {
    "Land": "ppe_gross_land",
    "Building": "ppe_gross_buildings",
    "Plant & Machinery": "ppe_gross_plant_equipment",
    "Equipments": "ppe_gross_office_equipment",
    "Computers": "ppe_gross_computers",
    "Furniture n fittings": "ppe_gross_furniture",
    "Vehicles": "ppe_gross_vehicles",
    "Other fixed assets": "ppe_gross_other",
}


def fixed_asset_schedule(result, end: date) -> QuarterStatement | None:
    """None when the filing has no PPE schedule for `end`; classes are 0 when the class line is not filed."""

    def v(tag: str) -> Decimal | None:
        return result.value(tag, end, end)

    gross = v("ppe_gross_block")
    if gross is None:
        return None
    rows = {name: Row(name, v(tag) or ZERO) for name, tag in CLASS_ROWS.items()}
    rows["Gross Block"] = Row("Gross Block", gross, {n: r.value for n, r in rows.items()})
    rows["Accumulated Depreciation"] = Row("Accumulated Depreciation", v("ppe_accumulated_depreciation"))
    rows["Net PPE"] = Row("Net PPE", v("ppe_net"))
    rows["Intangible Assets"] = Row("Intangible Assets", v("other_intangibles"))
    rows["CWIP"] = Row("CWIP", v("cwip"))
    return QuarterStatement("REG34_ANNUAL", (end, end), rows, scope_used=result.meta.get("scope"))


def schedule_tie_out(st: QuarterStatement) -> tuple[Decimal, Decimal | None]:
    """(class sum - gross block, gross - accumulated - net PPE); both 0 when the schedule ties."""
    classes = sum((st.rows[n].value for n in CLASS_ROWS), ZERO)
    gross, acc, net = (st.rows[n].value for n in ("Gross Block", "Accumulated Depreciation", "Net PPE"))
    return classes - gross, None if acc is None or net is None else gross - acc - net
