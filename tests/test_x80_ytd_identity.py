"""X80 / blueprint §3.2: a filed YTD must equal the sum of its directly filed quarters. Tata Motors FY26 standalone
(four real Integrated Filings) re-presents Q1 on a continuing-operations basis after the commercial-vehicle demerger:
the H1, 9M and FY revenue YTDs are each 4,644 crore below the quarters as first filed. Summing the original quarters
into TTM would mix bases, so TTM is withheld; profit (which carries the demerger gain) still ties."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from _fixture_helpers import XBRL_DIR
from financials.fundamentals import FactBook
from financials.parsers.integrated import parse_integrated_results

TML_FY26 = [
    "INTEGRATED_FILING_INDAS_1506803_08082025045458_WEB.xml",  # Q1 (filed 8 Aug 2025)
    "INTEGRATED_FILING_INDAS_1574914_14112025041626_WEB.xml",  # Q2 + H1
    "INTEGRATED_FILING_INDAS_1619042_05022026042048_WEB.xml",  # Q3 + 9M
    "INTEGRATED_FILING_INDAS_1667176_14052026062559_WEB.xml",  # Q4 + FY
]
CR = Decimal(10) ** 7


def _book() -> FactBook:
    book = FactBook("TML", "STANDALONE", rounding_unit=Decimal(10) ** 7)  # LevelOfRounding: Crores
    for name in TML_FY26:
        r = parse_integrated_results((XBRL_DIR / name).read_bytes(), name)
        assert not r.issues and r.meta["scope"] == "STANDALONE"
        for f in r.facts:
            if f.period_type == "DURATION":
                book.durations.setdefault(f.canonical_tag, {})[(f.period_start, f.period_end)] = f.value
    return book


def test_demerger_restatement_breaks_the_revenue_identity():
    breaks = _book().ytd_breaks("revenue_from_operations")
    got = {b["ytd_period"][1]: (Decimal(b["ytd"]) / CR, Decimal(b["quarters_sum"]) / CR) for b in breaks}
    assert got == {
        "2025-09-30": (Decimal("23993"), Decimal("28637")),
        "2025-12-31": (Decimal("39261"), Decimal("43905")),
        "2026-03-31": (Decimal("57859"), Decimal("62503")),
    }


def test_continuing_pbt_is_restated_by_the_same_quarter():
    breaks = _book().ytd_breaks("pbt")
    assert [(Decimal(b["quarters_sum"]) - Decimal(b["ytd"])) / CR for b in breaks] == [Decimal("1727")] * 3


def test_ttm_is_withheld_across_a_break_and_kept_where_the_identity_holds():
    book = _book()
    assert book.ttm("revenue_from_operations", date(2026, 3, 31)) is None
    assert book.ytd_breaks("pat") == []  # 873,470 vs 535 + 82,081 crore: inside half a crore per term / 0.5%
    assert book.ttm("pat", date(2026, 3, 31)) == Decimal("876530000000")  # 5,350 + 82,081 - 233 + 455 crore
