"""X226 (rule YTD_MISFILED_NO_BRIDGE): the X106 bridge is withheld when the YTD it would read is provably mis-filed.

NAZARA consolidated FY26. The quarters as filed: Q1 51.34, Q2 -33.93, Q3 8.84, Q4 55.70 Cr = 81.95 Cr, and the
Q4 results (1666284, 12-May-2026) state the FY as 81.94 Cr. A results filing re-sent on 16-Oct-2026 (1740461) keeps
every quarter and PBT (323.75 Cr) but states FY PAT -23.24 Cr; it outranks the first by visibility, so the YTD
identity breaks and X106 bridged TTM across it: Q2 FY27 TTM = H1 FY27 -47.11 + FY26 -23.24 - H1 FY26 17.41 = -87.76
Cr, against +17.43 Cr from the four quarters. The Reg. 34 annual report of 16-Nov-2026 states FY PAT 81.94 Cr again
(ranked below the results filing on P&L lines by X100): a filing later than the ranked one agrees with the quarters,
so the ranked YTD is the mis-filed side and the TTM is withheld (NULL) instead of bridged. Before the annual report
is visible there is no evidence (point in time); since X301 the re-sent FY (breaking) and H1 FY26 (holding) are on two
bases, so the TTM is then the 4 quarters (+17.43 Cr), not the bridge.

Aarti Pharmalabs consolidated H1 FY26 (1569445): Q1 49.50 Cr and Q2 27.92 Cr, H1 filed as -44.18 Cr; the 9M of
1622052 equals Q1 + Q2 + Q3 (NEXT_YTD_AGREES), and both quarters are positive while the H1 is negative (PAT_SIGN_FLIP).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import financials.fundamentals as F
from _fixture_helpers import FIXTURES
from financials.fundamentals import FactBook, clear_prefetch, load_factbook, prefetch_fundamentals
from financials.parsers.integrated import parse_integrated_results
from financials.promoter import promote
from financials.staging import stage_results_xbrl

DIR = FIXTURES / "ytd_misfiled"
CR = Decimal(10) ** 7
NAZARA = [  # (file, broadcast UTC as in the filings ledger)
    ("INTEGRATED_FILING_INDAS_1510585_12082025093306_WEB.xml", datetime(2025, 8, 12, 16, 3, 7)),  # Q1 FY26
    ("INTEGRATED_FILING_INDAS_1573094_12112025104605_WEB.xml", datetime(2025, 11, 12, 17, 16, 5)),  # Q2 + H1
    ("INTEGRATED_FILING_INDAS_1617405_03022026063441_WEB.xml", datetime(2026, 2, 3, 13, 4, 42)),  # Q3 + 9M
    ("INTEGRATED_FILING_INDAS_1666284_12052026113715_WEB.xml", datetime(2026, 5, 12, 18, 7, 15)),  # Q4 + FY 81.94
    ("INTEGRATED_FILING_INDAS_1707299_03082026104926_WEB.xml", datetime(2026, 8, 3, 17, 19, 26)),  # Q1 FY27
    ("INTEGRATED_FILING_INDAS_1740461_16102026080647_WEB.xml", datetime(2026, 10, 16, 14, 36, 48)),  # FY -23.24
    ("INTEGRATED_FILING_INDAS_1746358_26102026114756_WEB.xml", datetime(2026, 10, 26, 18, 17, 57)),  # Q2 FY27
]
NAZARA_AR = ("AR_XBRL_NAZARA_16112026123324.xml", datetime(2026, 11, 16, 7, 3, 25))  # annual report, FY 81.94
FY26 = (date(2025, 4, 1), date(2026, 3, 31))
Q2_FY27 = date(2026, 9, 30)
BEFORE_AR, AFTER_AR = datetime(2026, 11, 13, 18), datetime(2026, 11, 17, 18)

AARTI = [
    "INTEGRATED_FILING_INDAS_1510310_12082025074319_WEB.xml",  # Q1 FY26
    "INTEGRATED_FILING_INDAS_1569445_09112025092410_WEB.xml",  # Q2 + H1 (H1 PAT filed negative)
    "INTEGRATED_FILING_INDAS_1622052_09022026083722_WEB.xml",  # Q3 + 9M
]
H1_FY26 = (date(2025, 4, 1), date(2025, 9, 30))


def _promote(market, name: str, broadcast: datetime) -> str:
    r = promote(market.con, stage_results_xbrl(
        market.vault, market.stage_root, data=(DIR / name).read_bytes(),
        source_url="https://nsearchives.nseindia.com/corporate/xbrl/" + name,
        fetched_at=datetime(2026, 11, 17, 6), broadcast_ts=broadcast, broadcast_ts_source="API_FIELD"))  # fmt: skip
    assert r.status == "PROMOTED", r
    return r.message


def _nazara(market, with_annual=True) -> str:
    promote(market.con, market.stage_day("20261112"))
    fid = None
    for name, ts in NAZARA + ([NAZARA_AR] if with_annual else []):
        fid = _promote(market, name, ts)
    return market.con.execute("SELECT entity_id FROM filing_meta WHERE filing_id = ?", [fid]).fetchone()[0]


def test_nazara_ranked_fy_breaks_the_quarters_and_the_annual_report_agrees_with_them(market):
    ent = _nazara(market)
    book = load_factbook(market.con, ent, "CONSOLIDATED", AFTER_AR)
    pat = book.durations["pat"]
    assert pat[FY26] == Decimal("-232400000")  # the re-sent results filing (X100: results outrank the annual)
    assert [b["ytd_period"] for b in book.ytd_breaks("pat")] == [[str(FY26[0]), str(FY26[1])]]
    assert sum(book._ytd_quarters("pat", *FY26)) == Decimal("819500000")
    assert book.later_filed["pat"][FY26] == [Decimal("819400000")]  # annual report of 16-Nov-2026
    assert book.misfiled_ytd_evidence("pat", FY26) == "LATER_FILING_AGREES"
    quarters = sum(book.quarter("pat", date(y, m, d)) for y, m, d in ((2025, 12, 31), (2026, 3, 31), (2026, 6, 30),
                                                                      (2026, 9, 30)))  # fmt: skip
    assert quarters == Decimal("174300000")  # 8.84 + 55.70 - 82.47 + 35.36 Cr
    assert book.ttm_from_ytd("pat", Q2_FY27) == Decimal("-877600000")  # the X106 bridge on the mis-filed FY
    assert book.ttm("pat", Q2_FY27) is None  # X226: withheld
    assert book.ttm("pat", FY26[1]) is None  # the FY itself
    assert book.ttm("revenue_from_operations", Q2_FY27) is not None  # other lines are untouched
    prefetch_fundamentals(market.con, AFTER_AR)  # the batch path keeps the same evidence rows
    try:
        batch = load_factbook(market.con, ent, "CONSOLIDATED", AFTER_AR)
        assert batch.durations == book.durations and batch.later_filed == book.later_filed
    finally:
        clear_prefetch(market.con, AFTER_AR)


def test_nazara_bridge_stays_until_the_agreeing_filing_is_visible(market):
    ent = _nazara(market)
    book = load_factbook(market.con, ent, "CONSOLIDATED", BEFORE_AR)
    assert "pat" not in book.later_filed  # the first Q4 filing (81.94) is earlier than the ranked re-send
    assert book.misfiled_ytd_evidence("pat", FY26) is None
    assert book.ttm_from_ytd("pat", Q2_FY27) == Decimal("-877600000")  # the X106 bridge
    # X301 (decision 2026-11-18 item 6): FY26 (-23.24 Cr, the re-send) breaks the identity while H1 FY26 holds it, so
    # the bridge would mix two bases: the latest 4 quarters as filed instead (was the -87.76 Cr bridge before X301).
    assert book.prior_year_mixed_basis("pat", book._bridge_periods("pat", Q2_FY27))
    assert book.ttm("pat", Q2_FY27) == Decimal("174300000")
    assert book.restatement_suspected(Q2_FY27)  # the flag tells a reader the TTM spans a YTD-identity break
    # owners' profit TTM (EPS, P/E, ROE) follows PAT's basis (X301): the same 4-quarter sum
    owners = book.coalesced("pat_owners", "pat")
    assert book._bridge_periods(owners, Q2_FY27) == []  # FY26 / H1 FY26 attribution withheld (X86): no own bridge
    assert book.ttm(owners, Q2_FY27) == sum(book.quarter(owners, F._add_months(Q2_FY27, -3 * i)) for i in range(4))


def test_nazara_owners_ttm_follows_pat_after_the_annual_report(market):
    """X301: owners' profit TTM is withheld with PAT's (X226 on PAT's FY26), not summed from the quarters."""
    ent = _nazara(market)
    book = load_factbook(market.con, ent, "CONSOLIDATED", AFTER_AR)
    assert book.ttm("pat", Q2_FY27) is None
    assert book.ttm(book.coalesced("pat_owners", "pat"), Q2_FY27) is None
    assert book.ttm(book.continuing_owners(), Q2_FY27) is None


def _aarti_book() -> FactBook:
    book = FactBook("AARTIPHARM", "CONSOLIDATED", fy_starts=frozenset({date(2025, 4, 1)}))
    for name in AARTI:
        r = parse_integrated_results((DIR / name).read_bytes(), name)
        assert r.ok and r.meta["scope"] == "CONSOLIDATED"
        for f in r.facts:
            if f.period_type == "DURATION":
                book.durations.setdefault(f.canonical_tag, {})[(f.period_start, f.period_end)] = f.value
    return book


def test_aarti_pharmalabs_negative_half_year_against_positive_quarters():
    book = _aarti_book()
    pat = book.durations["pat"]
    assert pat[H1_FY26] == Decimal("-441809000")
    assert book._ytd_quarters("pat", *H1_FY26) == [Decimal("279230000"), Decimal("495013000")]  # Q2, Q1
    assert book.misfiled_ytd_evidence("pat", H1_FY26) == "NEXT_YTD_AGREES"  # 9M = Q1 + Q2 + Q3
    del pat[(date(2025, 4, 1), date(2025, 12, 31))]  # without the 9M, the sign evidence alone
    assert book.misfiled_ytd_evidence("pat", H1_FY26) == "PAT_SIGN_FLIP"


def test_genuine_restatement_is_still_bridged():
    """Tata Motors FY26 standalone (X106): restated YTDs agree with each other, not with the original quarters."""
    from test_x80_ytd_identity import _book as tml

    book = tml()
    for b in book.ytd_breaks("revenue_from_operations"):
        p = tuple(date.fromisoformat(x) for x in b["ytd_period"])
        assert book.misfiled_ytd_evidence("revenue_from_operations", p) is None
    assert book.ttm("revenue_from_operations", date(2026, 3, 31)) / CR == Decimal("57859")
