"""Rule ROUNDING_ONLY [X260] (owner 2026-11-18: "Ignore rounding errors if any").

Every rounded figure is off by at most half a unit of its LevelOfRounding, so a comparison of rounded figures can
differ by rounding alone by at most the sum of their half units (the coarser unit per figure when the figures' own
filings are not known one by one). The YTD identity counts the figures behind a derived tag: pbt_incl_jv is PBT +
the JV share, two rounded figures in each period whose JV share is filed and non-zero (Finolex Cables FY26
consolidated, real Integrated Filings of X102: Q1 files a JV share of 26.18 Cr, Q2 files 0).

On the 2026-11-18 snapshot no open finding is within this bound (466 open YTD_QUARTER_MISMATCH, the nearest at 1.1x
the bound; 262 ANNUAL_PRIOR_YEAR_DIFFERS, whose tolerance already is X260 for two figures): the existing checks
already allow the rounding of the filings compared. The tests pin the bound and the closure note.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from _fixture_helpers import XBRL_DIR
from financials.fundamentals import PBT_INCL_JV, FactBook
from financials.money import ROUNDING_UNITS, rounding_only_tolerance, within_rounding_only
from financials.parsers.integrated import parse_integrated_results

CR, LAKH = ROUNDING_UNITS["Crores"], ROUNDING_UNITS["Lakhs"]
Q1, Q2, H1 = (
    (date(2025, 4, 1), date(2025, 6, 30)),
    (date(2025, 7, 1), date(2025, 9, 30)),
    (date(2025, 4, 1), date(2025, 9, 30)),
)
FINOLEX = [
    "INTEGRATED_FILING_INDAS_1510705_13082025092940_WEB.xml",  # Q1 FY26 (JV share 26.18 Cr after PBT)
    "INTEGRATED_FILING_INDAS_1571804_11112025093544_WEB.xml",  # Q2 + H1 (JV share 0, inside PBT as exceptional)
]


def test_bound_is_half_a_unit_per_rounded_figure():
    # a total against the sum of 4 crore-rounded lines: 5 figures, 2.5 Cr
    assert rounding_only_tolerance([CR] * 5) == Decimal("25000000")
    # the same line in a lakh-rounded and a crore-rounded filing: 0.5 Cr + 0.5 lakh (what G328 / X110 allows)
    assert rounding_only_tolerance([LAKH, CR]) == Decimal("5050000")
    assert within_rounding_only(Decimal("-5050000"), [LAKH, CR])
    assert not within_rounding_only(Decimal("5050001"), [LAKH, CR])
    with pytest.raises(ValueError):
        rounding_only_tolerance([])


def _finolex_book() -> FactBook:
    book = FactBook("FINCABLES", "CONSOLIDATED", rounding_unit=CR, fy_starts=frozenset({date(2025, 4, 1)}))
    for name in FINOLEX:
        r = parse_integrated_results((XBRL_DIR / name).read_bytes(), name)
        if r.meta["scope"] != "CONSOLIDATED":
            continue
        for f in r.facts:
            if f.period_type == "DURATION":
                book.durations.setdefault(f.canonical_tag, {})[(f.period_start, f.period_end)] = f.value
    jv = book.durations.get("share_of_associates_jv", {})
    book.durations[PBT_INCL_JV] = {p: v + jv.get(p, Decimal(0)) for p, v in book.durations["pbt"].items()}
    return book


def test_finolex_pbt_incl_jv_counts_the_filed_jv_share_as_a_second_figure():
    book = _finolex_book()
    jv = book.durations["share_of_associates_jv"]
    assert (jv[Q1], jv[Q2]) == (Decimal("261800000"), Decimal(0))
    assert not jv.get(H1)  # H1 PBT 408.75 Cr already includes it (X102)
    # Q1 PBT + JV share, Q2 PBT (JV filed 0), H1 PBT: 4 rounded figures, 2 Cr at crore rounding
    assert book._ytd_rounded_figures(PBT_INCL_JV, [Q1, Q2, H1]) == 4
    assert book._ytd_rounded_figures("pbt", [Q1, Q2, H1]) == 3
    assert book.ytd_breaks(PBT_INCL_JV) == [] and book.ytd_rounding_only(PBT_INCL_JV) == []


def _jv_book(h1_pbt_cr: str) -> FactBook:
    """Crore-rounded PBT and JV share filed in every period (illustrative figures, crores)."""
    book = FactBook("X", "CONSOLIDATED", rounding_unit=CR, fy_starts=frozenset({date(2025, 4, 1)}))
    pbt = {Q1: Decimal(10) * CR, Q2: Decimal(12) * CR, H1: Decimal(h1_pbt_cr) * CR}
    jv = {Q1: Decimal(3) * CR, Q2: Decimal(2) * CR, H1: Decimal(5) * CR}
    book.durations["pbt"], book.durations["share_of_associates_jv"] = pbt, jv
    book.durations[PBT_INCL_JV] = {p: v + jv[p] for p, v in pbt.items()}
    return book


def test_a_pbt_incl_jv_gap_within_six_half_crores_is_rounding_only():
    # H1 PBT + JV 28.9 Cr vs quarters 27 Cr: 1.9 Cr > the old (2 + 1) x 0.5 Cr, <= 6 figures x 0.5 Cr = 3 Cr
    book = _jv_book("23.9")
    assert book.ytd_breaks(PBT_INCL_JV) == []
    (b,) = book.ytd_rounding_only(PBT_INCL_JV)
    assert (b["ytd"], b["quarters_sum"], b["tolerance"]) == ("289000000.0", "270000000", "15000000")
    # filed PBT alone is one figure per period: the same 1.9 Cr still breaks
    assert [x["ytd_period"] for x in book.ytd_breaks("pbt")] == [["2025-04-01", "2025-09-30"]]


def test_a_pbt_incl_jv_gap_beyond_the_bound_still_breaks():
    book = _jv_book("25.1")  # 3.1 Cr > 3 Cr
    assert [x["ytd_period"] for x in book.ytd_breaks(PBT_INCL_JV)] == [["2025-04-01", "2025-09-30"]]
    assert book.ytd_rounding_only(PBT_INCL_JV) == []


def test_stale_rounding_only_finding_is_closed_naming_the_rule(market):
    from financials.promoter import (
        ROUNDING_ONLY_NOTE,
        _close_stale_ytd_findings,
        _quarantine_many,
        _quarantine_row,
    )

    con = market.con
    rows = [
        _quarantine_row(stage="CONSISTENCY", reason_code="YTD_QUARTER_MISMATCH", entity_id="ent_x",
                        details={"scope": "CONSOLIDATED", "tag": t, "ytd_period": ["2025-04-01", "2025-09-30"]})
        for t in ("pbt_incl_jv", "pat")
    ]  # fmt: skip
    _quarantine_many(con, rows)
    rounding, other = (r["quarantine_id"] for r in rows)
    _close_stale_ytd_findings(con, [("ent_x", "CONSOLIDATED")], set(), {rounding})
    got = dict(
        con.execute(
            "SELECT quarantine_id, resolution || ' | ' || resolution_note FROM quarantine_queue "
            "WHERE entity_id = 'ent_x'"
        ).fetchall()
    )
    assert got[rounding] == "FIXED_BY_RULE | " + ROUNDING_ONLY_NOTE and "X260" in ROUNDING_ONLY_NOTE
    assert got[other] == "FIXED_BY_RULE | consistency holds on re-audit"
