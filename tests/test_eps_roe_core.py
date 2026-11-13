"""Pre-Batch-4 sweep: effective EPS, continuing ROE, core continuing profit [X53, C14, C15]."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from _fixture_helpers import XBRL_DIR
from financials.dsl import compile_screen
from financials.features import _eps
from financials.fundamentals import FactBook, building_blocks
from financials.parsers.indas_corp import parse_indas_corp_results
from financials.statements.quarterly import corp_quarter, eps_row

TMPV = XBRL_DIR / "INTEGRATED_FILING_INDAS_1574923_14112025041850_WEB.xml"
RELIANCE = XBRL_DIR / "INTEGRATED_FILING_INDAS_1750537_30102026093254_WEB.xml"
TMCV = XBRL_DIR / "INTEGRATED_FILING_INDAS_1574016_13112025070452_WEB.xml"
Q25 = (date(2025, 7, 1), date(2025, 9, 30))
Q26 = (date(2026, 7, 1), date(2026, 9, 30))


def test_filed_eps_is_not_a_zero_placeholder():
    """[X53] Correction of X52: filed EPS is non-zero in Reliance, TMPV and Tata Motors Ltd (an earlier read
    divided per-share values by 1e7)."""
    assert parse_indas_corp_results(RELIANCE.read_bytes()).value("eps_basic", *Q26) == Decimal("18.88")
    assert parse_indas_corp_results(TMCV.read_bytes()).value("eps_basic", *Q25) == Decimal("-2.35")


def test_tmpv_filed_total_eps_omits_the_discontinued_gain():
    """[X53] TMPV files total EPS -17.5 (= continuing) and discontinued EPS 0, while owners' profit is +76,170 Cr."""
    r = parse_indas_corp_results(TMPV.read_bytes())
    assert r.value("eps_basic", *Q25) == Decimal("-17.5") == r.value("eps_basic_continuing", *Q25)
    assert r.meta["warnings"] == [{"code": "EPS_INCONSISTENT", "filed": "-17.5", "computed": "206.70"}]
    st = corp_quarter(r, *Q25)
    assert st.rows["EPS"].value == Decimal("-17.5")  # filed value kept as headline (COALESCE only replaces 0)
    assert st.rows["EPS"].parts["Computed (owners' profit / period-end shares)"].quantize(Decimal("0.01")) == Decimal(
        "206.70"
    )
    assert any(d.startswith("EPS_INCONSISTENT") for d in st.divergences)


def test_reliance_eps_consistent_no_warning():
    r = parse_indas_corp_results(RELIANCE.read_bytes())
    assert "warnings" not in r.meta
    assert corp_quarter(r, *Q26).rows["EPS"].value == Decimal("18.88")


def _fake(values: dict):
    def value(tag, start, end):
        return values.get(tag)

    return SimpleNamespace(value=value, meta={})


def test_zero_filed_eps_falls_back_to_profit_over_shares():
    """COALESCE(NULLIF(filed, 0), owners' profit / period-end shares), for both total and continuing EPS."""
    row = eps_row(_fake({"eps_basic": Decimal(0), "eps_basic_continuing": Decimal(0), "pat_owners": Decimal(500),
                         "pat_discontinued": Decimal(100), "shares_from_paid_up": Decimal(100)}), *Q26)  # fmt: skip
    assert row.value == Decimal(5)
    assert row.parts["Continuing EPS (effective)"] == Decimal(4)
    assert row.parts["Filed EPS"] == 0  # the raw filed value stays visible


def test_features_eps_is_never_zero_for_non_zero_profit():
    assert _eps(Decimal("2546200000000"), Decimal("13532472634")) == Decimal("188.1548")
    assert _eps(Decimal(100), None) is None and _eps(Decimal(100), Decimal(0)) is None


def test_roe_continuing_and_core_profit_blocks():
    b = FactBook("e", "CONSOLIDATED")
    qs = [(date(2025, 10, 1), date(2025, 12, 31)), (date(2026, 1, 1), date(2026, 3, 31)),
          (date(2026, 4, 1), date(2026, 6, 30)), (date(2026, 7, 1), date(2026, 9, 30))]  # fmt: skip
    b.durations["pat"] = {p: Decimal(100) for p in qs}
    b.durations["pat"][qs[3]] = Decimal(1100)
    b.durations["pat_discontinued"] = {qs[3]: Decimal(1000)}
    b.durations["revenue_from_operations"] = {p: Decimal(1000) for p in qs}
    b.durations["exceptional_items"] = {qs[2]: Decimal(-40)}  # a one-off loss in continuing operations
    b.durations["pbt"] = {p: Decimal(125) for p in qs}
    b.durations["tax_expense"] = {p: Decimal(25) for p in qs}  # ETR 20%
    b.instants["total_assets"] = {qs[3][1]: Decimal(5000)}
    b.instants["total_equity"] = {qs[3][1]: Decimal(2000)}
    blocks = building_blocks(b, qs[3][1])
    assert blocks["pat_owners"] == Decimal(1400)
    assert blocks["pat_owners_continuing"] == Decimal(400)  # PE earnings keep the exceptional loss (C10)
    assert blocks["core_continuing_profit"] == Decimal(400) + Decimal(40) * Decimal("0.8")


def test_new_dsl_aliases_compile():
    cs = compile_screen("roe continuing > 15 AND credit cost < 2 AND core profit > 100 AND eps > 0")
    assert "roe_continuing" in cs.where_sql and "credit_cost" in cs.where_sql and "core_profit_ttm" in cs.where_sql
