"""X314 (rule NBFC_NET_LINE_SIDE) and X315 (rule YTD_COPIES_PRIOR_YEAR, extends X173), work QY3.

X314: the NBFC template (Schedule III Division III) shows the net result on fair value changes (and on derecognition
of amortised-cost instruments) as one line, in revenue when it is a net gain and in expenses when a net loss, decided
per period. A quarter's net loss is then inside the YTD's netted revenue, so revenue and total income are not
additive across periods while PBT is. Ashika Credit Capital (BSE 543766) consolidated Q1 / H1 FY27 and PNB Gilts
(NSE) standalone Q1 / H1 FY27 (fixtures `nbfc_net_line/`, MANIFEST section QY3).

X315: Andrew Yule (BSE 526173) consolidated Q3 FY26 files the Apr-Dec 2025 context with exactly the FY25 values of its
Q4 FY25 filing (fixtures `ytd_copy/Integrated_Finance_Ind_As_526173_*`).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import duckdb
import pytest

from _fixture_helpers import FIXTURES
from financials.fundamentals import FactBook
from financials.parsers.integrated import parse_integrated_results

NET = FIXTURES / "nbfc_net_line"
COPY = FIXTURES / "ytd_copy"
FY27 = date(2026, 4, 1)
Q1, Q2, H1 = (FY27, date(2026, 6, 30)), (date(2026, 7, 1), date(2026, 9, 30)), (FY27, date(2026, 9, 30))
ASHIKA_C = (
    "Integrated_Finance_NBFC_543766_3172026221822_IFNBFC.xml",
    "Integrated_Finance_NBFC_543766_31102026181525_IFNBFC.xml",
)
PNBGILTS_S = ("INTEGRATED_FILING_NBFC_INDAS_1694707_16072026105712_WEB.xml",
              "INTEGRATED_FILING_NBFC_INDAS_1737076_13102026051135_WEB.xml")  # fmt: skip


def _book(directory, names, fy_starts, entity="E") -> FactBook:
    scopes = set()
    book = FactBook(entity, "?", fy_starts=frozenset(fy_starts), rounding_unit=Decimal(1000))
    for name in names:
        r = parse_integrated_results((directory / name).read_bytes(), name)
        assert r.ok, r.issues
        scopes.add(r.meta["scope"])
        for f in r.facts:
            if f.period_type == "DURATION":
                book.durations.setdefault(f.canonical_tag, {})[(f.period_start, f.period_end)] = f.value
    (book.scope,) = scopes
    return book


@pytest.mark.parametrize(
    ("names", "loss_q1", "loss_q2"),
    [(ASHIKA_C, 406000, 19963000), (PNBGILTS_S, 0, 177075000)],
)
def test_x314_net_loss_quarters_are_inside_the_ytd_netted_revenue(names, loss_q1, loss_q2):
    book = _book(NET, names, {FY27})
    d = book.durations
    assert d["net_loss_fair_value"][Q1] == loss_q1 and d["net_loss_fair_value"][Q2] == loss_q2
    assert d["net_loss_fair_value"][H1] == 0 and d["net_loss_derecognition"][H1] == 0
    for tag in ("revenue_from_operations", "total_income", "total_expenses"):  # gross lines: off by the losses
        assert d[tag][Q1] + d[tag][Q2] - d[tag][H1] == loss_q1 + loss_q2
    assert d["pbt"][Q1] + d["pbt"][Q2] == d["pbt"][H1]  # the bottom line is additive
    for tag in ("revenue_from_operations", "total_income"):
        assert book.ytd_breaks(tag) == [] and book.ytd_rounding_only(tag) == []
        (b,) = book.ytd_net_line_side(tag)
        assert b["ytd_period"] == [str(H1[0]), str(H1[1])]
        assert Decimal(b["quarters_sum"]) - Decimal(b["ytd"]) == loss_q1 + loss_q2


def test_x314_only_the_loss_lines_close_the_gap():
    """The same break with the loss lines removed (a template without them), or with a different gap, stays a break."""
    book = _book(NET, ASHIKA_C, {FY27})
    for t in ("net_loss_fair_value", "net_loss_derecognition"):
        book.durations.pop(t)
    assert (
        len(book.ytd_breaks("revenue_from_operations")) == 1 and book.ytd_net_line_side("revenue_from_operations") == []
    )
    book = _book(NET, ASHIKA_C, {FY27})
    book.durations["revenue_from_operations"][H1] -= Decimal(20_000_000)  # 2 Cr beyond the losses: over the tolerance
    assert len(book.ytd_breaks("revenue_from_operations")) == 1
    book = _book(NET, ASHIKA_C, {FY27})
    assert book.ytd_net_line_side("pat") == [] and book.ytd_breaks("pat") == []  # PAT needs no netting


def test_x314_audit_closes_the_finding_with_the_rule_note():
    from financials.promoter import NET_LINE_SIDE_NOTE, _close_stale_ytd_findings

    con = duckdb.connect()
    con.execute(
        "CREATE TABLE quarantine_queue (quarantine_id VARCHAR, stage VARCHAR, reason_code VARCHAR, entity_id VARCHAR,"
        " details JSON, resolved_at TIMESTAMP, resolution VARCHAR, resolution_note VARCHAR)"
    )
    for q in ("q_net", "q_other"):
        con.execute(
            "INSERT INTO quarantine_queue VALUES "
            "(?, 'CONSISTENCY', 'YTD_QUARTER_MISMATCH', 'ent_x', ?, NULL, NULL, NULL)",
            [q, '{"scope": "CONSOLIDATED"}'],
        )
    _close_stale_ytd_findings(con, [("ent_x", "CONSOLIDATED")], set(), rule_notes={"q_net": NET_LINE_SIDE_NOTE})
    got = dict(
        con.execute("SELECT quarantine_id, resolution || ' | ' || resolution_note FROM quarantine_queue").fetchall()
    )
    assert got["q_net"] == "FIXED_BY_RULE | " + NET_LINE_SIDE_NOTE and "X314" in NET_LINE_SIDE_NOTE
    assert got["q_other"] == "FIXED_BY_RULE | consistency holds on re-audit"


FY25, FY26 = date(2024, 4, 1), date(2025, 4, 1)
M9, PRIOR_FY = (FY26, date(2025, 12, 31)), (FY25, date(2025, 3, 31))
ANDREWYU_C = (
    "Integrated_Finance_Ind_As_526173_16620251264_IFIndAs.html",  # Q4 FY25: FY25 column
    "Integrated_Finance_Ind_As_526173_148202518736_IFIndAs.html",  # Q1 FY26
    "Integrated_Finance_Ind_As_526173_13112025185648_IFIndAs.html",  # Q2 FY26 + H1
    "Integrated_Finance_Ind_As_526173_1122026181616_IFIndAs.html",  # Q3 FY26 + the copied 9M
)


def test_x315_the_nine_month_context_repeats_the_prior_full_year():
    book = _book(COPY, ANDREWYU_C, {FY25, FY26})
    for tag, v in (("revenue_from_operations", 3117097000), ("total_income", 3752739000), ("pbt", -285057000),
                   ("pat", -28382000), ("total_expenses", 4037796000)):  # fmt: skip
        assert book.durations[tag][M9] == book.durations[tag][PRIOR_FY] == Decimal(v)
    assert book.ytd_breaks("total_income")  # 9M 375.27 Cr vs quarters 282.92 Cr
    (c,) = book.prior_year_copy_periods()
    assert c["ytd_period"] == [str(M9[0]), str(M9[1])] and c["copied_period"] == [str(PRIOR_FY[0]), str(PRIOR_FY[1])]
    assert c["rule"] == "YTD_COPIES_PRIOR_YEAR"


def test_x315_rule_withholds_the_copied_ytd_and_keeps_the_rest():
    book = _book(COPY, ANDREWYU_C, {FY25, FY26})
    book.withhold_ytd_copies()
    assert [b["ytd_period"] for b in book.ytd_copies] == [[str(M9[0]), str(M9[1])]]
    for tag in ("revenue_from_operations", "total_income", "pbt", "pat", "total_expenses"):
        assert M9 not in book.durations[tag] and PRIOR_FY in book.durations[tag]
        assert not book.ytd_breaks(tag)  # H1 FY26 = Q1 + Q2 holds; the copied 9M no longer compared
    assert (FY26, date(2025, 9, 30)) in book.durations["pat"]


def test_x315_a_ytd_differing_from_the_prior_year_is_not_a_copy():
    book = _book(COPY, ANDREWYU_C, {FY25, FY26})
    book.durations["pat"][M9] += 1  # one rupee off on one of the three figures
    assert book.prior_year_copy_periods() == []
    book = _book(COPY, ANDREWYU_C[1:], {FY25, FY26})  # the prior year not filed: nothing to compare with
    assert book.prior_year_copy_periods() == []
