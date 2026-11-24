"""QF4 X306-X307: CASH_FLOW_RESTATED prior-year findings whose net cash flow moved without any amount being restated.

- X306 CASH_EQUIVALENTS_RECLASSIFIED: Vindhya Telelinks standalone FY26 annual redefines FY25 cash and cash
  equivalents (95.44 -> 85.01 Cr; other bank balances 30.02 -> 40.46 Cr): the FY25 net change moves by the same
  10.43 Cr (-57.16 -> -67.60 Cr) while PAT, total equity and total assets agree.
- X307 FX_EFFECT_RECLASSIFIED: Kirloskar Pneumatic consolidated FY26 annual moves the FY25 exchange difference on cash
  (0.22 -> -0.22 Cr) into the net change (13.63 -> 14.07 Cr); the net change after it is 13.85 Cr in both.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

from conftest import FETCHED_AT

from _fixture_helpers import FIXTURES
from financials.filing_checks import PRIOR_YEAR_REASON, prior_year_class
from financials.promoter import promote
from financials.staging import stage_results_xbrl

RESTATED = FIXTURES / "annual_restated"
URL = "https://nsearchives.nseindia.com/corporate/xbrl/"
CR = Decimal(10) ** 7


def _promote(m, name, ts):
    r = promote(m.con, stage_results_xbrl(m.vault, m.stage_root, data=(RESTATED / name).read_bytes(),
                                          source_url=URL + name, fetched_at=FETCHED_AT, broadcast_ts=ts,
                                          broadcast_ts_source="API_FIELD"))  # fmt: skip
    assert r.status == "PROMOTED", (name, r)


def _open(con):
    return [json.loads(d) for (d,) in con.execute(
        "SELECT details FROM quarantine_queue WHERE reason_code = ? AND resolved_at IS NULL ORDER BY quarantine_id",
        [PRIOR_YEAR_REASON]).fetchall()]  # fmt: skip


def _line(d, tag):
    x = next(x for x in d["differences"] if x["tag"] == tag)
    return (Decimal(x["stored"]) / CR).quantize(Decimal("0.01")), (Decimal(x["annual"]) / CR).quantize(Decimal("0.01"))


def test_x306_cash_equivalents_redefined(market):
    assert promote(market.con, market.stage_day("20250919")).status == "PROMOTED"
    _promote(market, "INTEGRATED_FILING_INDAS_1447925_22052025091528_WEB.xml", datetime(2025, 5, 22, 15, 45, 29))
    _promote(market, "AR_XBRL_VINDHYATEL_01092026190709.xml", datetime(2026, 9, 1, 13, 37, 10))
    [d] = _open(market.con)
    assert d["class"] == "RESTATED" and d["subclass"] == "CASH_EQUIVALENTS_RECLASSIFIED"
    tags = {x["tag"] for x in d["differences"]}
    assert not tags & {"pat", "total_equity", "total_assets"}
    assert _line(d, "net_cash_flow") == (Decimal("-57.16"), Decimal("-67.60"))
    assert _line(d, "cash_and_equivalents") == (Decimal("95.44"), Decimal("85.01"))
    net, cash = (next(x for x in d["differences"] if x["tag"] == t) for t in ("net_cash_flow", "cash_and_equivalents"))
    moved = Decimal(net["annual"]) - Decimal(net["stored"])
    assert abs(Decimal(cash["annual"]) - Decimal(cash["stored"]) - moved) <= 2 * Decimal(net["tolerance"])


def test_x307_exchange_difference_moved_into_the_net_change(market):
    assert promote(market.con, market.stage_day("20250919")).status == "PROMOTED"
    _promote(market, "INTEGRATED_FILING_INDAS_1424269_24042025081042_WEB.xml", datetime(2025, 4, 24, 14, 40, 43))
    _promote(market, "AR_XBRL_KIRLPNU_19082026192059.xml", datetime(2026, 8, 19, 13, 51, 0))
    [d] = _open(market.con)
    assert d["class"] == "RESTATED" and d["subclass"] == "FX_EFFECT_RECLASSIFIED"
    tags = {x["tag"] for x in d["differences"]}
    assert "net_cash_flow_after_fx" not in tags and not tags & {"pat", "total_equity"}
    assert _line(d, "net_cash_flow") == (Decimal("13.63"), Decimal("14.07"))
    assert _line(d, "fx_effect_on_cash") == (Decimal("0.22"), Decimal("-0.22"))


def test_cash_flow_subclass_needs_its_proof():
    ncf = {"tag": "net_cash_flow", "period": ["2024-04-01", "2025-03-31"], "annual": "-67", "stored": "-57",
           "tolerance": "0.5"}  # fmt: skip
    cash = {"tag": "cash_and_equivalents", "period": ["2025-03-31", "2025-03-31"], "annual": "85", "stored": "95",
            "tolerance": "0.5"}  # fmt: skip
    base = {"pat", "total_equity", "total_assets", "net_cash_flow", "cash_and_equivalents"}
    ctx = {"compared": base, "discontinued_filed": False}
    assert prior_year_class([ncf, cash], ctx)["subclass"] == "CASH_EQUIVALENTS_RECLASSIFIED"
    # total assets not compared, or differing: the balance sheet may have been restated too
    assert prior_year_class([ncf, cash], {**ctx, "compared": base - {"total_assets"}})["subclass"] == (
        "CASH_FLOW_RESTATED"
    )
    ta = {"tag": "total_assets", "period": ["2025-03-31", "2025-03-31"], "annual": "1", "stored": "2"}
    assert prior_year_class([ncf, cash, ta], ctx)["subclass"] == "CASH_FLOW_RESTATED"
    # the cash balance moved by another amount, or at another date
    other = {**cash, "annual": "80"}
    assert prior_year_class([ncf, other], ctx)["subclass"] == "CASH_FLOW_RESTATED"
    opening = {**cash, "period": ["2024-03-31", "2024-03-31"]}
    assert prior_year_class([ncf, opening], ctx)["subclass"] == "CASH_FLOW_RESTATED"
    # X307: the net change after the exchange difference compared and agrees
    fx = {**ctx, "compared": base | {"net_cash_flow_after_fx"}}
    assert prior_year_class([ncf], fx)["subclass"] == "FX_EFFECT_RECLASSIFIED"
    after = {**ncf, "tag": "net_cash_flow_after_fx"}
    assert prior_year_class([ncf, after], fx)["subclass"] == "CASH_FLOW_RESTATED"  # differs too, cash did not move
    assert prior_year_class([ncf, after, cash], fx)["subclass"] == "CASH_EQUIVALENTS_RECLASSIFIED"
    # PAT differs: still a bottom-line restatement
    pat = {"tag": "pat", "period": ["2024-04-01", "2025-03-31"], "annual": "1", "stored": "2"}
    assert prior_year_class([ncf, cash, pat], ctx)["subclass"] == "BOTTOM_LINE_RESTATED"
