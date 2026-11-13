"""Cash-flow sub-rows [X45]: sign convention, reconciliation and summation on real H1 FY27 filings."""

from datetime import date
from decimal import Decimal

import pytest

from _fixture_helpers import XBRL_DIR
from financials.parsers.indas_corp import parse_indas_corp_results
from financials.statements.cashflow import cashflow
from financials.statements.quarterly import CR

H1 = (date(2026, 4, 1), date(2026, 9, 30))
Q2 = (date(2026, 7, 1), date(2026, 9, 30))
FILES = {
    "TATAPOWER": "INTEGRATED_FILING_INDAS_1756234_11112026070341_WEB.xml",
    "ITC": "INTEGRATED_FILING_INDAS_1751357_02112026065559_WEB.xml",
    "TCS": "INTEGRATED_FILING_INDAS_1734607_08102026100810_WEB.xml",
    "ELIN": "INTEGRATED_FILING_INDAS_1753872_05112026061939_WEB.xml",
}


@pytest.fixture(scope="module", params=sorted(FILES))
def parsed(request):
    return request.param, parse_indas_corp_results((XBRL_DIR / FILES[request.param]).read_bytes())


def test_identities_hold(parsed):
    name, r = parsed
    assert r.ok, (name, r.issues)
    pbt, adj, cgo = (r.value(t, *H1) for t in ("pbt", "cf_adjustments_total", "cash_generated_from_operations"))
    assert pbt + adj == cgo


def test_sub_rows_sum_to_totals(parsed):
    name, r = parsed
    st = cashflow(r, *H1)
    for row in ("Cash from Operating Activity", "Cash from Investing Activity", "Cash from Financing Activity"):
        parts = st.rows[row].parts
        assert sum(v for v in parts.values() if v is not None) == st.rows[row].value, (name, row)
    net = st.rows["Net Cash Flow"]
    assert sum(net.parts.values()) == net.value


def test_tata_power_values_and_signs():
    r = parse_indas_corp_results((XBRL_DIR / FILES["TATAPOWER"]).read_bytes())
    st = cashflow(r, *H1)
    op = st.rows["Cash from Operating Activity"]
    assert op.value / CR == Decimal("6136.81")
    p = {k: (v / CR).quantize(Decimal("0.01")) for k, v in op.parts.items()}
    assert p["Receivables"] == Decimal("-1784.48") + Decimal("449.81")  # increase in receivables uses cash
    assert p["Inventory"] == Decimal("-1118.18")
    assert p["Payables"] == Decimal("1853.83")
    assert p["Direct taxes"] == Decimal("-171.20")
    assert p["Other operating items"] == 0
    # Interest income is filed positive (466.79 Cr) and deducted by the filer [X45]
    assert r.value("cf_adj_interest_income_deducted", *H1) / CR == Decimal("466.79")
    assert st.rows["Cash from Investing Activity"].parts["Fixed assets purchased"] / CR == Decimal("-9832.62")
    assert st.rows["Cash from Financing Activity"].parts["Dividends paid"] / CR == Decimal("-1427.05")


def test_no_cash_flow_for_the_quarter_context():
    """Cash flow is YTD-only: the 3-month context has none, so the builder returns None, never a derived number."""
    r = parse_indas_corp_results((XBRL_DIR / FILES["TATAPOWER"]).read_bytes())
    assert cashflow(r, *Q2) is None
