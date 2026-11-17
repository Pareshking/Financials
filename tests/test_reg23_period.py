"""Which period the Reg. 23(9) amounts of an Integrated Filing cover [X160, X161; R13 resolved].

Characterisation on real, unmodified files (tests/fixtures/rpt_half_year/, circulars/; MANIFEST.md "Reg. 23(9)
disclosure period"): every row sits on the filing's three-month context, but

- SEBI's format D (circular SEBI/HO/CFD/CFD-PoD-2/CIR/P/2024/185, note 4) asks for the six months ended September 30
  and March 31, or the six months of another financial year;
- POLYMED (April-March year) and CASTROLIND (calendar year): the Q2 and Q4 amounts per counterparty add up exactly to
  the Reg. 34 Ind AS 24 schedule of the year, and every Q4 opening balance is the Q2 closing balance (X160);
- EIDPARRY reports financial-year-to-date in its Q4 filing instead: Q4 amounts equal the year (within the annual
  filing's rounding level, Lakhs) and the Q4 opening balances are the closing balances of the previous Q4 (X161).

Every value is read straight from the XML with the production parsers.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from _fixture_helpers import FIXTURES
from financials.parsers.integrated import parse_integrated_results
from financials.parsers.reg23_rpt import (
    HALF_YEAR_MONTHS,
    REG23_PARSER_VERSION,
    half_year_start,
    parse_reg23_rpt,
)
from financials.parsers.reg34_annual import parse_reg34_annual
from financials.parsers.rpt import parse_related_parties
from financials.parsers.xbrl import parse_instance

DIR = FIXTURES / "rpt_half_year"
CIRCULAR = FIXTURES / "circulars" / "sebi_cir_2024_185.txt"

POLYMED_Q2 = "INTEGRATED_FILING_INDAS_1569348_08112025095047_WEB.xml"
POLYMED_Q4 = "INTEGRATED_FILING_INDAS_1672831_25052026105506_WEB.xml"
POLYMED_AR = "AR_XBRL_POLYMED_03102026150104.xml"
CASTROL_JUN = "INTEGRATED_FILING_INDAS_1503459_05082025091749_WEB.xml"
CASTROL_DEC = "INTEGRATED_FILING_INDAS_1617588_03022026083116_WEB.xml"
CASTROL_AR = "AR_XBRL_CASTROLIND_28042026134722.xml"
EID_Q4_FY25 = "INTEGRATED_FILING_INDAS_1453034_27052025055732_WEB.xml"
EID_Q2 = "INTEGRATED_FILING_INDAS_1571468_11112025064700_WEB.xml"
EID_Q4 = "INTEGRATED_FILING_INDAS_1673448_26052026074140_WEB.xml"
EID_AR = "AR_XBRL_EIDPARRY_07092026144251.xml"


def _norm(name: str) -> str:
    """Names differ in case and spacing between filings ("VITROMED HEALTHCARE" / "VITROMED HEALTH CARE")."""
    return "".join(ch for ch in name.upper() if ch.isalnum())


def _reg23(name: str):
    data = (DIR / name).read_bytes()
    parsed = parse_integrated_results(data, name)
    return parsed.meta, parse_reg23_rpt(parse_instance(data), parsed.meta["period_end"])


def _annual(name: str, start: date, end: date) -> dict[tuple[str, str], Decimal]:
    data = (DIR / name).read_bytes()
    m = parse_reg34_annual(data, name).meta
    rows = parse_related_parties(parse_instance(data), set(m["in_scope_periods"]), set(m["in_scope_instants"]))
    out: dict[tuple[str, str], Decimal] = {}
    for r in rows:
        if r.period_type == "DURATION" and (r.period_start, r.period_end) == (start, end):
            key = (_norm(r.counterparty_name), r.source_element)
            out[key] = out.get(key, 0) + r.amount
    return out


def _one(rows, name: str, txn_type: str):
    hits = [r for r in rows if _norm(r.counterparty_name) == _norm(name) and r.txn_type == txn_type]
    assert len(hits) == 1, hits
    return hits[0]


def test_sebi_format_prescribes_six_months():
    text = " ".join(CIRCULAR.read_text(encoding="utf-8").split())
    head = "FORMAT FOR DISCLOSURE OF RELATED PARTY TRANSACTIONS (applicable only for half-yearly filings i.e., 2nd and"
    assert head in text
    assert (
        "For companies with financial year ending March 31, this information has to be provided for six months ended "
        "September 30 and six months ended March 31. Companies with financial years ending in other months, the six "
        "months period shall apply accordingly."
    ) in text
    assert "opening and closing balances, including commitments, to be disclosed for existing related party" in text


@pytest.mark.parametrize(("end", "start"), [
    (date(2025, 9, 30), date(2025, 4, 1)),
    (date(2026, 3, 31), date(2025, 10, 1)),
    (date(2025, 6, 30), date(2025, 1, 1)),
    (date(2025, 12, 31), date(2025, 7, 1)),
])  # fmt: skip
def test_half_year_rule(end, start):
    assert half_year_start(end) == start


@pytest.mark.parametrize("name", [POLYMED_Q2, POLYMED_Q4, CASTROL_JUN, CASTROL_DEC, EID_Q2, EID_Q4])
def test_quarter_context_half_year_disclosure(name):
    meta, rows = _reg23(name)
    assert meta["scope"] == "STANDALONE" and rows
    assert REG23_PARSER_VERSION == "reg23-2"
    for r in rows:
        assert r.period_months == 3  # the tagged context is the quarter...
        assert r.period_end == meta["period_end"]
        assert (r.disclosure_start, r.disclosure_months) == (half_year_start(r.period_end), HALF_YEAR_MONTHS)


def test_polymed_half_years_add_up_to_the_year():
    _, q2 = _reg23(POLYMED_Q2)
    _, q4 = _reg23(POLYMED_Q4)
    year = _annual(POLYMED_AR, date(2025, 4, 1), date(2026, 3, 31))
    assert {r.period_start for r in q2} == {date(2025, 7, 1)} and {r.period_start for r in q4} == {date(2026, 1, 1)}
    cases = [  # (reg23 name, type, Q2 amount, Q4 amount, Ind AS 24 name, element, FY26 amount)
        ("Himanshu Baid", "remuneration", 77852000, 103720000, "Himanshu Baid", "OtherRelatedPartyTransactionsExpense",
         181572000),
        ("Aaryaman Baid", "remuneration", 6402000, 6399000, "Aaryaman Baid", "OtherRelatedPartyTransactionsExpense",
         12801000),
        ("Vitromed Healthcare", "sales", 84529000, 144122000, "VITROMED HEALTH CARE",
         "RevenueFromSaleOfGoodsRelatedPartyTransactions", 228651000),
        ("Vitromed Healthcare", "purchases", 1177000, 3907000, "VITROMED HEALTH CARE",
         "PurchasesOfGoodsRelatedPartyTransactions", 5084000),
    ]  # fmt: skip
    for name, kind, a2, a4, ann_name, element, fy in cases:
        h1, h2 = _one(q2, name, kind), _one(q4, name, kind)
        assert (h1.amount, h2.amount) == (Decimal(a2), Decimal(a4))
        assert h1.amount + h2.amount == year[(_norm(ann_name), element)] == Decimal(fy)

    # every Q4 opening balance (tagged on 2025-12-31) is the Q2 closing balance at 2025-09-30
    def by_key(rows):  # (counterparty, type) filed once in the filing
        keys = [(_norm(r.counterparty_name), r.txn_type) for r in rows]
        return {k: r for k, r in zip(keys, rows, strict=True) if keys.count(k) == 1}

    q2_rows, q4_rows = by_key(q2), by_key(q4)
    pairs = [(q4_rows[k].opening_balance, q2_rows[k].closing_balance) for k in q4_rows.keys() & q2_rows.keys()]
    assert len(pairs) == 24 and all(o == c for o, c in pairs)
    assert _one(q4, "Himanshu Baid", "remuneration").opening_balance == Decimal(48608000)


def test_castrol_calendar_year_half_years_add_up_to_the_year():
    _, jun = _reg23(CASTROL_JUN)
    _, dec = _reg23(CASTROL_DEC)
    year = _annual(CASTROL_AR, date(2025, 1, 1), date(2025, 12, 31))
    assert {r.disclosure_start for r in jun} == {date(2025, 1, 1)}
    assert {r.disclosure_start for r in dec} == {date(2025, 7, 1)}
    cases = [  # (name in both filings, type, Jun amount, Dec amount, Ind AS 24 name, element)
        ("Castrol Germany GmbH", "purchases", 257800000, 294500000, "PurchasesOfGoodsRelatedPartyTransactions"),
        ("Castrol Belgium BV", "purchases", 111800000, 83100000, "PurchasesOfGoodsRelatedPartyTransactions"),
        ("BP Lubricants USA Inc", "purchases", 34500000, 32700000, "PurchasesOfGoodsRelatedPartyTransactions"),
    ]
    for name, kind, a1, a2, element in cases:
        h1, h2 = _one(jun, name, kind), _one(dec, name, kind)
        assert (h1.amount, h2.amount) == (Decimal(a1), Decimal(a2))
        hits = [v for (n, e), v in year.items() if e == element and n == _norm(name)]
        assert hits == [h1.amount + h2.amount]
        assert h2.opening_balance == h1.closing_balance  # opening of Jul-Dec = closing at 2025-06-30
    assert _one(dec, "Castrol Germany GmbH", "purchases").opening_balance == Decimal(92000000)


def test_eid_parry_q4_is_financial_year_to_date():
    """X161: the exception. Q4 amounts are the whole year and Q4 opens on the previous year-end balance, while the
    filing's contexts look exactly like a half-year filer's (nothing in the file tells them apart)."""
    _, q4_prev = _reg23(EID_Q4_FY25)
    _, q2 = _reg23(EID_Q2)
    _, q4 = _reg23(EID_Q4)
    year = _annual(EID_AR, date(2025, 4, 1), date(2026, 3, 31))
    rounding = Decimal(100000)  # the annual filing's LevelOfRounding: Lakhs
    refinery = "Parry Sugars Refinery India Private Limited"
    ann = [v for (n, e), v in year.items() if e == "PurchasesOfGoodsRelatedPartyTransactions" and "REFINERY" in n]
    h1, fy = _one(q2, refinery, "purchases"), _one(q4, refinery, "purchases")
    assert (h1.amount, fy.amount, ann) == (Decimal(106168000), Decimal(272627000), [Decimal(272700000)])
    assert abs(fy.amount - ann[0]) < rounding  # Q4 = the year...
    assert h1.amount + fy.amount - ann[0] > 100 * rounding  # ...not the second half
    pf = "Parry Group Staff Provident Fund"
    assert _one(q4, pf, "other").amount == Decimal(43775000)
    assert [v for (n, e), v in year.items() if n == _norm(pf)] == [Decimal(43800000)]
    # opening balances roll forward from the previous Q4 (2025-03-31), not from the Q2 close (2025-09-30)
    cor = "Coromandel International Limited"
    assert _one(q4, cor, "sales").opening_balance == _one(q4_prev, cor, "sales").closing_balance == Decimal(3100000)
    assert _one(q2, cor, "sales").closing_balance == Decimal(4966000)
    # same contexts as a half-year filer: three months, ending on the period end
    assert {(r.period_start, r.period_months) for r in q4} == {(date(2026, 1, 1), 3)}
