"""Per-filing COALESCE before TTM: a window mixing filings with and without a line never collapses to NULL."""

from datetime import date
from decimal import Decimal

from financials.fundamentals import FactBook, building_blocks

ENDS = [date(2025, 12, 31), date(2026, 3, 31), date(2026, 6, 30), date(2026, 9, 30)]
STARTS = [date(2025, 10, 1), date(2026, 1, 1), date(2026, 4, 1), date(2026, 7, 1)]


def _book() -> FactBook:
    b = FactBook("e", "CONSOLIDATED")
    q = list(zip(STARTS, ENDS, strict=True))
    b.durations["pat"] = {p: Decimal(100) for p in q}
    b.durations["revenue_from_operations"] = {p: Decimal(1000) for p in q}
    # Owners' share tagged only in the two filings with a non-wholly-owned subsidiary
    b.durations["pat_owners"] = {q[0]: Decimal(90), q[3]: Decimal(80)}
    # Excise labelled only in one filing
    b.durations["excise_duty"] = {q[2]: Decimal(50)}
    b.instants["total_assets"] = {ENDS[-1]: Decimal(5000)}
    b.instants["total_equity"] = {ENDS[-1]: Decimal(2000)}
    return b


def test_owners_profit_ttm_coalesces_per_filing():
    blocks = building_blocks(_book(), ENDS[-1])
    assert blocks["pat"] == Decimal(400)
    assert blocks["pat_owners"] == Decimal(90 + 100 + 100 + 80)


def test_ttm_was_null_without_coalesce():
    """Regression: the naive 4-quarter sum of the owners' tag alone is NULL for this window."""
    assert _book().ttm("pat_owners", ENDS[-1]) is None


def test_excise_absent_in_some_filings_counts_as_zero():
    blocks = building_blocks(_book(), ENDS[-1])
    assert blocks["excise_duty"] == Decimal(50)
    assert blocks["rev_ops"] == Decimal(4000 - 50)


def test_owners_equity_falls_back_to_total_equity_when_untagged():
    blocks = building_blocks(_book(), ENDS[-1])
    assert blocks["equity_owners"] == Decimal(2000)
    assert blocks["minority_interest"] == Decimal(0)
