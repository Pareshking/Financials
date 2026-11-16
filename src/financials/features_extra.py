"""Remaining Phase 2 ratios (batch G; docs/phase_status.md "Phase 2 pending: ratios", ratio catalogue BUILDABLE NOW
rows), for `features.py`.

Two stages, both batched (never a query per security):
1. `period_values(con, book, end, b, as_of)` per entity, from the row's own scope book [C18] (one scope per row,
   never mixed); only the profit-leakage columns read the entity's other scope book, which is what they compare.
2. `add_columns(...)` per security row (the `features.compute_rows` hook, after batch D): Reg. 31 flow, 90-day
   volume, Reg. 30 counts and red flags, audit opinion, supplemental-KPI history, and the per-row ratios that need
   market cap / EV.

Definitions (fractions as DOUBLE, `_pp` = fraction points, money DECIMAL rupees; growth NULL when the base <= 0):
- margin acceleration (G152) = [OPM(Q) - OPM(Q-4)] - [OPM(Q-1) - OPM(Q-5)], quarter OPM = EBITDA / sales as
  `opm_latest_quarter_pct`; gross-margin change (G257) = GPM(Q) - GPM(Q-4), each under the C6 guard (materials +
  purchases >= 10% of sales); profit-growth acceleration = owners' profit YoY of the latest quarter - that of the
  preceding quarter; growth streaks = consecutive quarters, newest first, with quarter YoY > 0 (stops at the first
  quarter that is not, or cannot be measured; at most STREAK_MAX).
- cost shares (G133, G258; ratio catalogue B3.4-B3.6) = line / sales of the latest quarter and of the last fiscal
  year: material cost = materials + purchases of stock-in-trade + change in inventories (C6 guard not applied: the
  share itself is the screen), employee cost, other expenses, power & fuel [X50], freight [X50], advertising &
  promotion [X68] (label rules in the quarterly filing; elements in Reg. 34 [X74]). Absent label = not disclosed,
  NULL, never 0. Marketing efficiency (G256) = sales change vs a year earlier / A&P of the earlier period (quarter
  and fiscal-year forms).
- acquisitions (G276) = `CashFlowsUsedInObtainingControlOfSubsidiariesOrOtherBusinesses...` (zero-drop key, 74
  INDAS_CORP + Reg. 34 filings) of the last / preceding fiscal year; absent in a filed fiscal-year cash flow = nil
  (Schedule III omits nil lines). `inorganic_growth_flag` [C26]: TRUE when the outflow of either of the two
  fiscal years behind the last FY growth rate is >= INORGANIC_MIN_SHARE of that year's sales, FALSE when both are
  measured and below, else NULL. Reg. 30 acquisition events are not parsed (no event type), so only cash flow counts.
- profit leakage (G278) = 1 - consolidated owners' profit / standalone PAT (TTM and latest quarter, same end date);
  NULL unless both scopes file the window and standalone PAT > 0.
- incremental asset turnover 3Y (G220) = (FY sales - sales 3 FYs earlier) / (net block at the last FY end - net
  block 3 FY ends earlier, Screener-style S10); NULL until FY28 (C9) and when the net block did not grow.
- earnings quality (B1.8, B1.11, B1.12, B1.14, B2.11): CFO / PAT, cash taxes paid / tax expense, capex / sales on the
  12-month cash-flow window (`cf_as_of`, H1 / FY, as cfo_to_ebitda [C19]); effective tax rate = TTM tax / TTM PBT
  (PBT > 0; not clamped: the clamped rate is only the NOPAT input); exceptional items / PBT (TTM) and the number of
  the last 4 quarters with a non-zero exceptional line.
- RPT intensity (B1.19, partial G236) = `rpt_total_amount` / sales of the same period. The per-counterparty split
  (purchases / loans / royalties) is not parsed (RPT detail rows stay in raw_xbrl_facts): G236 is blocked on a parser.
- annual notes (Reg. 34, read at the last fiscal year end): audit fees / sales, managerial remuneration / PAT,
  capital commitments / owners' equity, unquoted investments (book), quoted investments (market value),
  revaluation reserve.
- valuation: P/S and EV/Sales on `sales_ttm`; P/EV = market cap / embedded value (G270); EV / TTM GOV (G265; TTM =
  a 12-month KPI period or 4 consecutive quarters); YoY growth of GOV, ARPU and MTU (G266) and the contribution
  margin change (G257) compare the latest KPI period with the same-length period ending 12 months earlier; bank CASA
  (master backlog M4). KPIs come from `supplemental_kpis` (manual `load-kpis`, point in time); NULL until loaded.
- institutional absorption (G241) = change in FII + DII shares between two adjacent Reg. 31 quarter ends / median
  daily volume over the 90 calendar days to the as-of (days of volume); NULL when a share-count action went ex after
  the earlier pattern (shares and volume would be on different bases). Pledge change QoQ = pledged / promoter
  shares now - the same a quarter earlier (fraction points).
- Reg. 30 (G117, B8.2-B8.3): counts of litigation, allotment and fund-raising disclosures in 90 days, and red-flag
  booleans kept as separate columns, never summed into one score (architecture §10.2): auditor resignation, >= 2 KMP
  / director resignations, fraud / default, litigation, a qualified audit opinion (latest Reg. 34
  `auditor_qualified`, or an Integrated Filing statement on the impact of a qualification [E8]), a pledge increase.
- raw numerator / denominator (G244) for pe, roe, roce, ev_ebitda and opm, exactly the inputs of those columns;
  NULL where the ratio does not apply (lenders / insurers for roce, ev_ebitda and opm).
Industrial cost / margin / cash-conversion ratios are NULL for lenders and insurers (`INDUSTRIAL_ONLY`).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from financials import features_pl
from financials.db import version_key
from financials.fundamentals import (
    _add_months,
    entity_filter,
    latest_fiscal_year,
    load_factbook,
    qoq_growth,
    safe_div,
)
from financials.parsers.indas_corp import period_months

# ── columns (schema order: `-- batch G (remaining Phase 2 ratios)` in db/schema.sql) ──────────────────────────────

COST_LINES = ("material_cost", "employee_cost", "other_expenses", "power_fuel", "freight", "ad_promo")
COST_PERIODS = ("latest_quarter", "last_year")
FY_LINES = ("material_cost", "employee_cost", "minority_share", "dividends_paid")
FYS = ("last_year", "preceding_year")
G244_RATIOS = ("pe", "roe", "roce", "ev_ebitda", "opm")

MARGIN_COLUMNS = (
    "opm_acceleration_pp", "gpm_change_yoy_pp", "profit_growth_acceleration_pp", "sales_growth_streak_quarters",
    "profit_growth_streak_quarters",
)  # fmt: skip
COST_COLUMNS = (
    *(f"{line}_{p}_pct" for line in COST_LINES for p in COST_PERIODS),
    "marketing_efficiency_latest_quarter", "marketing_efficiency_last_year",
)  # fmt: skip
FY_COLUMNS = tuple(f"{line}_{fy}" for line in FY_LINES for fy in FYS)
PERIMETER_COLUMNS = (
    "acquisition_outflow_last_year", "acquisition_outflow_preceding_year", "acquisition_outflow_to_sales_last_year",
    "inorganic_growth_flag", "standalone_pat_ttm", "profit_leakage_pct", "profit_leakage_latest_quarter_pct",
    "incremental_asset_turnover_3y",
)  # fmt: skip
QUALITY_COLUMNS = (
    "cfo_to_pat", "cash_tax_rate", "effective_tax_rate", "exceptional_to_pbt", "exceptional_quarters_4q",
    "capex_intensity", "net_cash_to_market_cap", "rpt_to_sales", "intangibles_to_equity",
    "audit_fees_to_sales", "managerial_remuneration_to_pat", "capital_commitments_to_net_worth",
    "unquoted_investments", "quoted_investments_market_value", "revaluation_reserve",
)  # fmt: skip
VALUATION_COLUMNS = (
    "price_to_sales", "ev_to_sales", "price_to_embedded_value", "gov_ttm", "ev_to_gov", "gov_growth_yoy_pct", "arpu",
    "arpu_growth_yoy_pct", "mtu", "mtu_growth_yoy_pct", "contribution_margin_change_yoy_pp", "casa_pct",
)  # fmt: skip
FLOW_COLUMNS = (
    "inst_shares_change_qoq", "volume_median_90d", "institutional_absorption_90d", "promoter_pledge_change_qoq_pp",
    "public_holders_above_1pct",
)  # fmt: skip
RED_FLAGS = ("auditor_resignation_90d", "kmp_resignations_90d", "fraud_or_default_90d", "litigation_90d",
             "audit_qualified", "pledge_increase_qoq")  # fmt: skip
EVENT_COLUMNS = ("litigations_90d", "allotments_90d", "fund_raising_events_90d", *(f"rf_{f}" for f in RED_FLAGS))
RAW_COLUMNS = tuple(f"{r}_{part}" for r in G244_RATIOS for part in ("numerator", "denominator"))
EXTRA_COLUMNS = (
    *MARGIN_COLUMNS, *COST_COLUMNS, *FY_COLUMNS, *PERIMETER_COLUMNS, *QUALITY_COLUMNS, *VALUATION_COLUMNS,
    *FLOW_COLUMNS, *EVENT_COLUMNS, *RAW_COLUMNS,
)  # fmt: skip

MONEY_COLUMNS = frozenset(
    {*FY_COLUMNS, "acquisition_outflow_last_year", "acquisition_outflow_preceding_year", "standalone_pat_ttm",
     "unquoted_investments", "quoted_investments_market_value", "revaluation_reserve", "gov_ttm", "arpu",
     *RAW_COLUMNS}
)  # fmt: skip
# Meaningless for lenders and insurers (their sales line is interest earned / premium; CFO holds loan flows).
INDUSTRIAL_ONLY = frozenset(
    {*MARGIN_COLUMNS[:2], *COST_COLUMNS, "acquisition_outflow_to_sales_last_year", "inorganic_growth_flag",
     "incremental_asset_turnover_3y", "cfo_to_pat", "capex_intensity", "net_cash_to_market_cap", "rpt_to_sales",
     "audit_fees_to_sales", "ev_to_sales", "roce_numerator", "roce_denominator", "ev_ebitda_numerator",
     "ev_ebitda_denominator", "opm_numerator", "opm_denominator"}
)  # fmt: skip

STREAK_MAX = 8
INORGANIC_MIN_SHARE = Decimal("0.05")  # [C26]: an acquisition >= 5% of the year's sales changes the perimeter
KMP_EXODUS_MIN = 2
VOLUME_WINDOW_DAYS = 90
ACQUISITION_TAG = (
    "li_cash_flows_used_in_obtaining_control_of_subsidiaries_or_other_businesses_classified_as_investing_activities"
)
ANNUAL_TAGS = {
    "managerial_remuneration": "li_managerial_remuneration",
    "capital_commitments": "li_estimated_amount_of_contracts_remaining_to_be_executed_on_capital_account_and_not_provided_for",  # noqa: E501
    "unquoted": ("li_aggregate_amount_of_unquoted_noncurrent_investments",
                 "li_aggregate_amount_of_unquoted_current_investments"),
    "quoted_mv": ("li_market_value_of_quoted_noncurrent_investments", "li_market_value_of_quoted_current_investments"),
    "revaluation": "li_property_plant_and_equipment_revaluation_surplus",
}  # fmt: skip
KPI_NAMES = ("gov", "arpu", "mtu", "contribution_margin", "casa_pct")
FINANCIAL_ARCHETYPES = frozenset({"FINANCIAL_LENDING", "INSURANCE"})
ZERO = Decimal(0)


def _f(x) -> float | None:
    return None if x is None else float(x)


def _q(x) -> Decimal | None:
    return None if x is None else Decimal(x).quantize(Decimal("0.01"))


def _sum(*xs):
    return None if any(x is None for x in xs) else sum(xs, ZERO)


# ── stage 1: per entity, from the scope book ──────────────────────────────────────────────────────────────────────


def _cost_tags(book) -> dict[str, str]:
    """Derived per-period material cost (materials + purchases + inventory change; absent purchases / change = 0 as
    in the filed statement, absent materials = not a manufacturer's statement -> NULL) and the cost lines."""
    key = "extra:material_cost"
    if key not in book.durations:
        mats = book.durations.get("cost_of_materials_consumed", {})
        pur, inv = (book.durations.get(t, {}) for t in ("purchases_of_stock_in_trade", "changes_in_inventories"))
        book.durations[key] = {p: v + pur.get(p, ZERO) + inv.get(p, ZERO) for p, v in mats.items()}
    return {"material_cost": key, "employee_cost": "employee_benefit_expense", "other_expenses": "other_expenses",
            "power_fuel": "power_and_fuel", "freight": "freight", "ad_promo": "advertising_promotion"}  # fmt: skip


def _quarter_opm(book, tags, end: date) -> Decimal | None:
    return safe_div(book.quarter(features_pl.EBITDA, end), book.quarter(tags["sales"], end))


def _quarter_gpm(book, tags, end: date) -> Decimal | None:
    q = lambda t: book.quarter(t, end)  # noqa: E731
    return features_pl._gpm(q(tags["sales"]), *features_pl._cogs_parts(q))


def margin_acceleration(book, end: date) -> Decimal | None:
    """[OPM(Q) - OPM(Q-4)] - [OPM(Q-1) - OPM(Q-5)] (G152); NULL unless all four quarters are filed."""
    tags = features_pl._tags(book)
    o = [_quarter_opm(book, tags, _add_months(end, m)) for m in (0, -12, -3, -15)]
    return None if None in o else (o[0] - o[1]) - (o[2] - o[3])


def growth_streak(book, tag: str, end: date) -> int | None:
    """Consecutive quarters (newest first) whose value grew vs the same quarter a year earlier; NULL when the latest
    quarter cannot be measured."""
    n = 0
    for i in range(STREAK_MAX):
        q = _add_months(end, -3 * i)
        g = qoq_growth(book.quarter(tag, q), book.quarter(tag, _add_months(q, -12)))
        if g is None:
            return None if i == 0 else n
        if g <= 0:
            return n
        n += 1
    return n


def _fy_cash(book, tag: str, fy: tuple[date, date] | None) -> Decimal | None:
    """A cash-flow line of fiscal year `fy`: as filed; nil when the year's cash flow is filed without it; else NULL."""
    if fy is None:
        return None
    v = book.durations.get(tag, {}).get(fy)
    if v is not None:
        return v
    return ZERO if fy in book.durations.get("cfo", {}) else None


def inorganic_flag(shares: list[Decimal | None]) -> bool | None:
    """C26 over the acquisition-outflow shares of the two fiscal years (three-valued)."""
    if any(s is not None and s >= INORGANIC_MIN_SHARE for s in shares):
        return True
    return None if any(s is None for s in shares) else False


def profit_leakage(consolidated, standalone, end: date) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    """(standalone TTM PAT, TTM leakage, latest-quarter leakage): 1 - consolidated owners' profit / standalone PAT."""
    if consolidated is None or standalone is None:
        return None, None, None
    owners = consolidated.coalesced("pat_owners", "pat")
    sa_ttm = standalone.ttm("pat", end)
    out = [sa_ttm]
    for cons, sa in ((consolidated.ttm(owners, end), sa_ttm),
                     (consolidated.quarter(owners, end), standalone.quarter("pat", end))):  # fmt: skip
        out.append(None if cons is None or sa is None or sa <= 0 else 1 - cons / sa)
    return tuple(out)


def net_block_at(book, d: date) -> Decimal | None:
    """Screener-style Net Block on balance-sheet date `d` (features_bs.bs_lines, S10)."""
    from financials.features_bs import bs_lines

    return bs_lines(book, d).get("net_block")


def incremental_asset_turnover(book, end: date, years: int = 3, fixed_assets=net_block_at) -> Decimal | None:
    """(FY sales - sales `years` FYs earlier) / (net block at the last FY end - net block `years` FY ends earlier)
    (ratio catalogue B2.9); C9-gated, NULL when the net block did not grow."""
    fy = latest_fiscal_year(book, end)
    if fy is None or not features_pl._history_ok(fy[1], years):
        return None
    base = (_add_months(fy[0], -12 * years), _add_months(fy[1], -12 * years))
    tag = features_pl._tags(book)["sales"]
    s1, s0 = features_pl.fy_value(book, tag, fy), features_pl.fy_value(book, tag, base)
    a1, a0 = fixed_assets(book, fy[1]), fixed_assets(book, base[1])
    if None in (s1, s0, a1, a0) or a1 - a0 <= 0:
        return None
    return (s1 - s0) / (a1 - a0)


def _same_period_sales(book, sales_tag: str, p: tuple[date, date]) -> Decimal | None:
    v = book.durations.get(sales_tag, {}).get(p)
    if v is not None:
        return v
    m = period_months(*p)
    return book.quarter(sales_tag, p[1]) if m == 3 else None


def rpt_intensity(book, sales_tag: str, end: date) -> Decimal | None:
    """Latest filed RPT total (on or before `end`) / sales of exactly that period."""
    rpt = book.durations.get("rpt_total_amount", {})
    periods = [p for p in rpt if p[1] <= end]
    if not periods:
        return None
    p = max(periods, key=lambda p: (p[1], p[0]))
    return safe_div(rpt[p], _same_period_sales(book, sales_tag, p))


def _other_scope(con, book, as_of: datetime | None):
    if con is None or as_of is None:
        return None
    other = "STANDALONE" if book.scope == "CONSOLIDATED" else "CONSOLIDATED"
    return load_factbook(con, book.entity_id, other, as_of)


def period_values(con, book, end: date, b: dict, as_of: datetime | None = None, other=None) -> dict:
    """Stage 1 (one per entity and scope book). `b` = fundamentals.building_blocks(book, end); `other` = the entity's
    other scope book (read through the active fundamentals prefetch when omitted)."""
    tags = features_pl._tags(book)
    cost = _cost_tags(book)
    sales = tags["sales"]
    out: dict = {}
    out["opm_acceleration_pp"] = margin_acceleration(book, end)
    g_now, g_ly = _quarter_gpm(book, tags, end), _quarter_gpm(book, tags, _add_months(end, -12))
    out["gpm_change_yoy_pp"] = None if g_now is None or g_ly is None else g_now - g_ly
    out["sales_growth_streak_quarters"] = growth_streak(book, sales, end)
    out["profit_growth_streak_quarters"] = growth_streak(book, tags["net_profit"], end)

    fy, prev = features_pl.fiscal_years(book, end)
    q_sales = book.quarter(sales, end)
    fy_sales = features_pl.fy_value(book, sales, fy) if fy else None
    for line, tag in cost.items():
        out[f"{line}_latest_quarter_pct"] = safe_div(book.quarter(tag, end), q_sales)
        out[f"{line}_last_year_pct"] = safe_div(features_pl.fy_value(book, tag, fy), fy_sales) if fy else None
    ad = cost["ad_promo"]
    q_ly = _add_months(end, -12)
    q_sales_ly = book.quarter(sales, q_ly)
    if None not in (q_sales, q_sales_ly):
        out["marketing_efficiency_latest_quarter"] = safe_div(q_sales - q_sales_ly, book.quarter(ad, q_ly))
    prev_sales = features_pl.fy_value(book, sales, prev) if prev else None
    if None not in (fy_sales, prev_sales):
        out["marketing_efficiency_last_year"] = safe_div(fy_sales - prev_sales, features_pl.fy_value(book, ad, prev))

    fy_tags = {"material_cost": cost["material_cost"], "employee_cost": "employee_benefit_expense",
               "minority_share": "pat_nci"}  # fmt: skip
    for k, p in (("last_year", fy), ("preceding_year", prev)):
        for line, tag in fy_tags.items():
            out[f"{line}_{k}"] = features_pl.fy_value(book, tag, p) if p else None
        out[f"dividends_paid_{k}"] = _fy_cash(book, "dividends_paid", p)
        out[f"acquisition_outflow_{k}"] = _fy_cash(book, ACQUISITION_TAG, p)
    shares = [
        safe_div(out["acquisition_outflow_last_year"], fy_sales),
        safe_div(out["acquisition_outflow_preceding_year"], prev_sales),
    ]
    out["acquisition_outflow_to_sales_last_year"] = shares[0]
    out["inorganic_growth_flag"] = inorganic_flag(shares)

    other = other if other is not None else _other_scope(con, book, as_of)
    cons, sa = (book, other) if book.scope == "CONSOLIDATED" else (other, book)
    out["standalone_pat_ttm"], out["profit_leakage_pct"], out["profit_leakage_latest_quarter_pct"] = profit_leakage(
        cons, sa, end
    )
    out["incremental_asset_turnover_3y"] = incremental_asset_turnover(book, end)

    cf_end = b.get("cf_as_of")
    if cf_end is not None:
        pat_cf, tax_cf = book.ttm("pat", cf_end), book.ttm("tax_expense", cf_end)
        if pat_cf is not None and pat_cf > 0:
            out["cfo_to_pat"] = safe_div(b.get("cfo"), pat_cf)
        out["cash_tax_rate"] = safe_div(book.ttm_from_ytd("income_taxes_paid", cf_end), tax_cf)
        out["capex_intensity"] = safe_div(b.get("capex"), book.ttm(features_pl.REV_OPS, cf_end))
    pbt, tax = b.get("pbt"), book.ttm("tax_expense", end)
    if pbt is not None and pbt > 0:
        out["effective_tax_rate"] = safe_div(tax, pbt)
        out["exceptional_to_pbt"] = safe_div(book.ttm(tags["exceptional_items"], end), pbt)
    exc = [book.quarter(tags["exceptional_items"], _add_months(end, -3 * i)) for i in range(4)]
    if None not in exc and all(book.quarter("pbt", _add_months(end, -3 * i)) is not None for i in range(4)):
        out["exceptional_quarters_4q"] = sum(1 for v in exc if v != 0)
    out["net_debt"] = b.get("net_debt")
    out["rpt_to_sales"] = rpt_intensity(book, sales, end)
    bs = b.get("bs_as_of")
    if bs is not None:
        gw, oi = (book.instants.get(t, {}).get(bs) for t in ("goodwill", "other_intangibles"))
        if gw is not None or oi is not None:
            out["intangibles_to_equity"] = safe_div((gw or ZERO) + (oi or ZERO), b.get("equity_owners"))

    if fy is not None:  # Reg. 34 annual notes at the last fiscal year end [X73]
        at = lambda t: book.instants.get(t, {}).get(fy[1])  # noqa: E731
        fees = book.durations.get("audit_fees", {}).get(fy)  # 0 = rounded to nil at the filing's unit (TCS, Eternal)
        out["audit_fees_to_sales"] = safe_div(fees, fy_sales) if fees else None
        fy_pat = book.durations.get("pat", {}).get(fy)
        if fy_pat is not None and fy_pat > 0:
            out["managerial_remuneration_to_pat"] = safe_div(
                book.durations.get(ANNUAL_TAGS["managerial_remuneration"], {}).get(fy), fy_pat)  # fmt: skip
        equity = at("equity_attributable_to_owners") or at("total_equity")
        out["capital_commitments_to_net_worth"] = safe_div(at(ANNUAL_TAGS["capital_commitments"]), equity)
        for col, key in (("unquoted_investments", "unquoted"), ("quoted_investments_market_value", "quoted_mv")):
            parts = [at(t) for t in ANNUAL_TAGS[key]]
            out[col] = None if all(v is None for v in parts) else sum((v or ZERO for v in parts), ZERO)
        out["revaluation_reserve"] = at(ANNUAL_TAGS["revaluation"])

    out["_roce_inputs"] = (b.get("ebit"), _sum(b.get("total_equity"), b.get("total_debt")))
    return out


# ── stage 2: batched reads and per-row columns ────────────────────────────────────────────────────────────────────

_RANKED_SHP = """WITH f AS (
    SELECT entity_id, as_of_date, filing_id, parser_version FROM (
        SELECT entity_id, as_of_date, filing_id, parser_version, row_number() OVER (
            PARTITION BY entity_id, as_of_date ORDER BY visible_from_ts DESC, {vk} DESC, filing_id DESC) AS rn
        FROM shareholding_meta WHERE visible_from_ts <= ?{only}) WHERE rn = 1),
    r AS (SELECT *, row_number() OVER (PARTITION BY entity_id ORDER BY as_of_date DESC) AS r FROM f)"""


def shareholding_flow_inputs(con, as_of_ts: datetime, entities=None) -> dict[str, dict]:
    """Per entity, for the two latest visible Reg. 31 patterns (rank 1 = latest): as-of date, FII + DII shares,
    promoter shares, pledged shares; and the count of named public holders above 1% in the latest. Two queries."""
    only, only_p = entity_filter("entity_id", entities)
    ranked = _RANKED_SHP.format(vk=version_key(), only=only)
    out: dict[str, dict] = defaultdict(lambda: {"dates": {}, "inst": {}, "promoter": {}, "pledged": {}})
    for ent, rank, d, inst, n_inst, pledged in con.execute(
        ranked
        + """ SELECT r.entity_id, r.r, r.as_of_date,
                     sum(o.shares) FILTER (WHERE o.category IN ('FII', 'DII')),
                     count(*) FILTER (WHERE o.category IN ('FII', 'DII')),
                     any_value(m.promoter_pledged_shares)
              FROM r JOIN shareholding_observations o USING (filing_id, parser_version)
              JOIN shareholding_meta m USING (filing_id, parser_version)
              WHERE r.r <= 2 GROUP BY ALL""",
        [as_of_ts, *only_p],
    ).fetchall():
        e = out[ent]
        e["dates"][rank] = d
        e["inst"][rank] = inst if n_inst == 2 else None  # both categories filed
        e["pledged"][rank] = pledged
    for ent, rank, shares in con.execute(
        ranked
        + """ SELECT r.entity_id, r.r, o.shares
              FROM r JOIN shareholding_observations o USING (filing_id, parser_version)
              WHERE r.r <= 2 AND o.category = 'PROMOTER'""",
        [as_of_ts, *only_p],
    ).fetchall():
        out[ent]["promoter"][rank] = shares
    for ent, n in con.execute(
        ranked
        + """ SELECT r.entity_id, count(h.holder_name) FROM r
              LEFT JOIN shareholding_major_holders h USING (filing_id, parser_version)
              WHERE r.r = 1 GROUP BY ALL""",
        [as_of_ts, *only_p],
    ).fetchall():
        out[ent]["holders_1pct"] = n
    return out


def volume_medians(con, as_of: date, exchange: str = "NSE", securities=None) -> dict[str, float]:
    """Median daily traded volume over the VOLUME_WINDOW_DAYS calendar days to `as_of` (raw shares). One query."""
    only, only_p = entity_filter("security_id", securities)
    return {
        sec: float(m)
        for sec, m in con.execute(
            "SELECT security_id, median(volume) FROM ohlcv WHERE exchange = ? AND trade_date > ? AND trade_date <= ? "
            "AND volume IS NOT NULL" + only + " GROUP BY security_id",
            [exchange, as_of - timedelta(days=VOLUME_WINDOW_DAYS), as_of, *only_p],
        ).fetchall()
        if m is not None
    }


def event_inputs(con, as_of: date, as_of_ts: datetime, entities=None) -> dict[str, dict]:
    """Reg. 30 counts in the 90 days to as-of (disclosure date, as features._event_counts) and the latest audit
    opinion signals (filing_meta). Two queries."""
    only, only_p = entity_filter("entity_id", entities)
    out: dict[str, dict] = defaultdict(dict)
    for ent, lit, allot, fund in con.execute(
        """SELECT entity_id, count(*) FILTER (WHERE event_type = 'LITIGATION'),
                  count(*) FILTER (WHERE event_type = 'ALLOTMENT'), count(*) FILTER (WHERE family = 'FUND_RAISING')
           FROM corporate_events WHERE visible_from_ts <= ? AND report_date > ? AND report_date <= ?"""
        + only
        + " GROUP BY entity_id",
        [as_of_ts, as_of - timedelta(days=90), as_of, *only_p],
    ).fetchall():
        out[ent] |= {"litigations_90d": lit, "allotments_90d": allot, "fund_raising_events_90d": fund}
    for ent, annual, opinion in con.execute(
        """SELECT entity_id,
                  arg_max(auditor_qualified, (visible_from_ts, filing_id))
                      FILTER (WHERE accounting_profile = 'REG34_ANNUAL' AND auditor_qualified IS NOT NULL),
                  arg_max(audit_opinion, (visible_from_ts, filing_id)) FILTER (WHERE audit_opinion IS NOT NULL)
           FROM filing_meta WHERE visible_from_ts <= ?"""
        + only
        + " GROUP BY entity_id",
        [as_of_ts, *only_p],
    ).fetchall():
        out[ent]["_audit"] = (annual, opinion)
    return out


def audit_qualified(annual: bool | None, opinion: str | None) -> bool | None:
    """TRUE on a qualified Reg. 34 report or an Integrated Filing statement on the impact of a qualification (any
    text other than the two observed declarations [E8]); FALSE when what is filed is clean; NULL when nothing is."""
    modified = None if opinion is None else opinion not in ("UNMODIFIED", "NOT_APPLICABLE")
    if annual is True or modified is True:
        return True
    return None if annual is None and modified is None else False


def kpi_inputs(con, as_of_ts: datetime, entities=None) -> dict[str, dict[str, dict]]:
    """{entity: {kpi: {(start, end): value}}} for KPI_NAMES, latest visible version per period (one query)."""
    only, only_p = entity_filter("entity_id", entities)
    out: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(dict))
    for ent, kpi, start, end, value in con.execute(
        "SELECT entity_id, kpi, period_start, period_end, arg_max(value, visible_from_ts) FROM supplemental_kpis "
        "WHERE visible_from_ts <= ? AND kpi IN ('gov', 'arpu', 'mtu', 'contribution_margin', 'casa_pct')"
        + only
        + " GROUP BY ALL",
        [as_of_ts, *only_p],
    ).fetchall():
        out[ent][kpi][(start, end)] = Decimal(value)
    return out


def latest_kpi_period(series: dict) -> tuple[date, date] | None:
    """Latest period end; among periods ending then, the shortest (a quarter before a half-year)."""
    return max(series, key=lambda p: (p[1], p[0])) if series else None


def kpi_yoy(series: dict) -> tuple[Decimal | None, Decimal | None]:
    """(latest value, the same-length period ending 12 months earlier)."""
    p = latest_kpi_period(series)
    if p is None:
        return None, None
    return series[p], series.get((_add_months(p[0], -12), _add_months(p[1], -12)))


def kpi_ttm(series: dict) -> Decimal | None:
    """TTM of a flow KPI: a 12-month period ending at the latest end, else its 4 consecutive quarters."""
    p = latest_kpi_period(series)
    if p is None:
        return None
    end = p[1]
    for (s, e), v in series.items():
        if e == end and period_months(s, e) == 12:
            return v
    qs = []
    for i in range(4):
        e = _add_months(end, -3 * i)
        qs.append(series.get((_add_months(date(e.year, e.month, 1), -2), e)))
    return None if None in qs else sum(qs, ZERO)


def _share_action_since(factors, start: date | None, as_of: date) -> bool:
    return any(start is not None and start < ex <= as_of and (pf != 1 or ef != 1) for ex, pf, ef in factors)


def flow_columns(row: dict, flow: dict | None, volume_median: float | None, factors, as_of: date) -> dict:
    from financials.features import _quarter_before

    out = dict.fromkeys(FLOW_COLUMNS)
    out["volume_median_90d"] = volume_median
    if not flow or 1 not in flow["dates"]:
        return out
    out["public_holders_above_1pct"] = flow.get("holders_1pct")
    d1, d2 = flow["dates"][1], flow["dates"].get(2)
    if d2 is None or d2 != _quarter_before(d1):
        return out
    i1, i2 = flow["inst"].get(1), flow["inst"].get(2)
    if i1 is not None and i2 is not None and not _share_action_since(factors, d2, as_of):
        out["inst_shares_change_qoq"] = int(i1 - i2)
        if volume_median:
            out["institutional_absorption_90d"] = (i1 - i2) / volume_median
    pledge = []
    for rank in (1, 2):
        promoter, pledged = flow["promoter"].get(rank), flow["pledged"].get(rank)
        pledge.append(None if promoter is None or pledged is None else
                      (0.0 if promoter == 0 else float(Decimal(pledged) / Decimal(promoter))))  # fmt: skip
    if None not in pledge:
        out["promoter_pledge_change_qoq_pp"] = pledge[0] - pledge[1]
    return out


def event_columns(row: dict, ev: dict | None, flows: dict) -> dict:
    ev = ev or {}
    out = {k: ev.get(k, 0) for k in ("litigations_90d", "allotments_90d", "fund_raising_events_90d")}
    kmp = row.get("kmp_resignations_90d")
    out |= {
        "rf_auditor_resignation_90d": None if row.get("auditor_resignations_90d") is None
        else row["auditor_resignations_90d"] > 0,
        "rf_kmp_resignations_90d": None if kmp is None else kmp >= KMP_EXODUS_MIN,
        "rf_fraud_or_default_90d": None if row.get("fraud_or_default_90d") is None else row["fraud_or_default_90d"] > 0,
        "rf_litigation_90d": out["litigations_90d"] > 0,
        "rf_audit_qualified": audit_qualified(*ev.get("_audit", (None, None))),
        "rf_pledge_increase_qoq": None if flows.get("promoter_pledge_change_qoq_pp") is None
        else flows["promoter_pledge_change_qoq_pp"] > 0,
    }  # fmt: skip
    return out


def _ratio(a, b, positive=True) -> float | None:
    if a is None or b is None or (positive and b <= 0) or b == 0:
        return None
    return float(Decimal(a) / Decimal(b))


def valuation_columns(row: dict, kpis: dict | None) -> dict:
    out = dict.fromkeys(VALUATION_COLUMNS)
    mcap, ev, sales = row.get("market_cap"), row.get("enterprise_value"), row.get("sales_ttm")
    out["price_to_sales"] = _ratio(mcap, sales)
    out["ev_to_sales"] = _ratio(ev, sales)
    out["price_to_embedded_value"] = _ratio(mcap, row.get("embedded_value"))
    kpis = kpis or {}
    gov = kpis.get("gov", {})
    gov_ttm = kpi_ttm(gov)
    out["gov_ttm"] = _q(gov_ttm)
    out["ev_to_gov"] = _ratio(ev, gov_ttm)
    for k in ("gov", "arpu", "mtu"):
        now, before = kpi_yoy(kpis.get(k, {}))
        out[f"{k}_growth_yoy_pct"] = _f(qoq_growth(now, before))
        if k == "arpu":
            out["arpu"] = _q(now)
        elif k == "mtu":
            out["mtu"] = None if now is None else int(now)
    now, before = kpi_yoy(kpis.get("contribution_margin", {}))
    out["contribution_margin_change_yoy_pp"] = None if now is None or before is None else float(now - before)
    casa, _ = kpi_yoy(kpis.get("casa_pct", {}))
    out["casa_pct"] = _f(casa)
    return out


def raw_columns(row: dict, fund: dict, x: dict) -> dict:
    """G244: the exact numerator and denominator of pe, roe, roce, ev_ebitda and opm."""
    ebit, capital = x.get("_roce_inputs", (None, None))
    pairs = {
        "pe": (row.get("market_cap"), fund.get("_pe_earnings")),
        "roe": (fund.get("_pat_owners"), fund.get("_equity_owners")),
        "roce": (ebit, capital),
        "ev_ebitda": (row.get("enterprise_value"), row.get("ebitda_ttm")),
        "opm": (row.get("ebitda_ttm"), row.get("sales_ttm")),
    }
    out = {}
    for r, (num, den) in pairs.items():
        out[f"{r}_numerator"], out[f"{r}_denominator"] = _q(num), _q(den)
    return out


def row_columns(row: dict, fund: dict | None, extras: dict | None, kpis, flow, volume_median, events, factors,
                as_of: date) -> dict:  # fmt: skip
    """All columns of this module for one security row (row = the row built so far, batches A-D included)."""
    out = dict.fromkeys(EXTRA_COLUMNS)
    fund = fund or {}
    x = extras or {}
    out.update({k: v for k, v in x.items() if k in out})
    pl, pp = row.get("profit_growth_yoy_quarter_pct"), row.get("profit_growth_yoy_preceding_quarter_pct")
    out["profit_growth_acceleration_pp"] = None if pl is None or pp is None else pl - pp
    nd, mcap = x.get("net_debt"), row.get("market_cap")
    if nd is not None and mcap is not None and mcap > 0:
        out["net_cash_to_market_cap"] = float(-nd / mcap)
    out.update(valuation_columns(row, kpis))
    out.update(flow_columns(row, flow, volume_median, factors, as_of))
    out.update(event_columns(row, events, out))
    out.update(raw_columns(row, fund, x))
    if row.get("valuation_archetype") in FINANCIAL_ARCHETYPES:
        out.update(dict.fromkeys(INDUSTRIAL_ONLY))
    for c in EXTRA_COLUMNS:
        v = out[c]
        if v is None or (isinstance(v, bool | int) and c not in MONEY_COLUMNS):
            continue
        out[c] = _q(v) if c in MONEY_COLUMNS else float(v)
    return out


def add_columns(con, rows: list[dict], as_of: date, as_of_ts: datetime, fundamentals: dict, factors,
                entities=None, exchange: str = "NSE") -> None:  # fmt: skip
    """The features.compute_rows hook: batched reads, then each row's columns, in place."""
    secs = None if entities is None else {r["security_id"] for r in rows}
    kpis = kpi_inputs(con, as_of_ts, entities)
    flows = shareholding_flow_inputs(con, as_of_ts, entities)
    volumes = volume_medians(con, as_of, exchange, secs)
    events = event_inputs(con, as_of, as_of_ts, entities)
    for row in rows:
        ent, sec = row["entity_id"], row["security_id"]
        fund = fundamentals.get(ent) or {}
        row.update(row_columns(row, fund, fund.get("_extra"), kpis.get(ent), flows.get(ent), volumes.get(sec),
                               events.get(ent), factors.get(sec, []), as_of))  # fmt: skip


def dsl_aliases() -> dict[str, tuple[str, str]]:
    """Screener-style names for every column of this module (fractions shown x100, money in crore, flags 1/0)."""
    pp, cr = "percentage points", "INR crore"
    out: dict[str, tuple[str, str]] = {
        "opm acceleration": ("(opm_acceleration_pp * 100)", f"{pp}, OPM YoY change latest - preceding quarter"),
        "margin acceleration": ("(opm_acceleration_pp * 100)", f"{pp}, OPM YoY change latest - preceding quarter"),
        "gross margin expansion bps": ("(gpm_change_yoy_pp * 10000)", "bps, quarter GPM vs same quarter last year"),
        "gpm change yoy": ("(gpm_change_yoy_pp * 100)", f"{pp}, quarter GPM vs same quarter last year (C6)"),
        "profit growth acceleration": ("(profit_growth_acceleration_pp * 100)",
                                       f"{pp}, profit YoY latest - preceding quarter"),
        "consecutive quarters of sales growth": ("sales_growth_streak_quarters", f"count, YoY > 0 (max {STREAK_MAX})"),
        "consecutive quarters of profit growth": ("profit_growth_streak_quarters", f"count (max {STREAK_MAX})"),
        "marketing efficiency latest quarter": ("marketing_efficiency_latest_quarter",
                                                "x, sales change YoY / A&P a year earlier"),
        "marketing efficiency last year": ("marketing_efficiency_last_year", "x, FY sales change / preceding FY A&P"),
        "acquisition outflow last year": ("(acquisition_outflow_last_year / 10000000)", f"{cr}, CF obtaining control"),
        "acquisition outflow preceding year": ("(acquisition_outflow_preceding_year / 10000000)", cr),
        "acquisitions to sales last year": ("(acquisition_outflow_to_sales_last_year * 100)", "% of FY sales"),
        "inorganic growth": ("CAST(inorganic_growth_flag AS INTEGER)",
                             "1/0, acquisitions >= 5% of sales in either of the last two FYs"),
        "standalone net profit": ("(standalone_pat_ttm / 10000000)", f"{cr}, TTM standalone PAT"),
        "profit leakage": ("(profit_leakage_pct * 100)", "%, 1 - consolidated owners' / standalone TTM profit"),
        "profit leakage latest quarter": ("(profit_leakage_latest_quarter_pct * 100)", "%, same, latest quarter"),
        "incremental asset turnover 3years": ("incremental_asset_turnover_3y", "x, d sales / d net block, FY28 (C9)"),
        "cfo to pat": ("cfo_to_pat", "x, 12-month cash-flow window"),
        "cash tax rate": ("(cash_tax_rate * 100)", "%, taxes paid / tax expense, cash-flow window"),
        "effective tax rate": ("(effective_tax_rate * 100)", "%, TTM tax / PBT"),
        "exceptional items to pbt": ("(exceptional_to_pbt * 100)", "%, TTM"),
        "quarters with exceptional items": ("exceptional_quarters_4q", "count of the last 4 quarters"),
        "capex intensity": ("(capex_intensity * 100)", "%, capex / sales, cash-flow window"),
        "net cash to market cap": ("(net_cash_to_market_cap * 100)", "%, (liquid cash - debt) / market cap"),
        "rpt to sales": ("(rpt_to_sales * 100)", "%, RPT total / sales of the same period"),
        "intangibles to equity": ("(intangibles_to_equity * 100)", "%, (goodwill + intangibles) / owners' equity"),
        "audit fees to sales": ("(audit_fees_to_sales * 100)", "%, last FY (Reg. 34)"),
        "managerial remuneration to pat": ("(managerial_remuneration_to_pat * 100)", "%, last FY (Reg. 34)"),
        "capital commitments to net worth": ("(capital_commitments_to_net_worth * 100)", "%, last FY end (Reg. 34)"),
        "book value of unquoted investments": ("(unquoted_investments / 10000000)", f"{cr}, last FY end"),
        "market value of quoted investments": ("(quoted_investments_market_value / 10000000)", f"{cr}, last FY end"),
        "revaluation reserve": ("(revaluation_reserve / 10000000)", f"{cr}, last FY end"),
        "price to sales": ("price_to_sales", "x, market cap / TTM sales"),
        "ev to sales": ("ev_to_sales", "x, EV / TTM sales"),
        "price to embedded value": ("price_to_embedded_value", "x, life insurers (supplemental KPI)"),
        "gov ttm": ("(gov_ttm / 10000000)", f"{cr}, supplemental KPI"),
        "ev to gov": ("ev_to_gov", "x, EV / TTM gross order value"),
        "gov growth": ("(gov_growth_yoy_pct * 100)", "% YoY, latest KPI period"),
        "arpu": ("arpu", "INR per user, latest KPI period"),
        "arpu growth": ("(arpu_growth_yoy_pct * 100)", "% YoY"),
        "mtu": ("mtu", "count, monthly transacting users"),
        "mtu growth": ("(mtu_growth_yoy_pct * 100)", "% YoY"),
        "contribution margin change": ("(contribution_margin_change_yoy_pp * 100)", f"{pp}, YoY (KPI)"),
        "casa": ("(casa_pct * 100)", "%, banks (supplemental KPI)"),
        "casa ratio": ("(casa_pct * 100)", "%, banks (supplemental KPI)"),
        "change in institutional shares": ("inst_shares_change_qoq", "shares, FII + DII QoQ"),
        "median volume 90days": ("volume_median_90d", "shares per day, 90 calendar days"),
        "institutional absorption": ("institutional_absorption_90d", "days of median 90D volume, FII + DII QoQ"),
        "change in pledge": ("(promoter_pledge_change_qoq_pp * 100)", f"{pp}, pledged / promoter shares QoQ"),
        "public holders above 1 percent": ("public_holders_above_1pct", "count, named holders in Reg. 31"),
        "litigations 90days": ("litigations_90d", "count, Reg. 30"),
        "allotments 90days": ("allotments_90d", "count, Reg. 30"),
        "fund raising events 90days": ("fund_raising_events_90d", "count, Reg. 30"),
        "audit qualified": ("CAST(rf_audit_qualified AS INTEGER)", "1/0, latest audit opinion"),
        "ebidt latest quarter": ("((operating_profit_latest_quarter + other_income_latest_quarter) / 10000000)",
                                 f"{cr}, EBITDA + other income"),
        "ebidt last year": ("((operating_profit_last_year + other_income_last_year) / 10000000)", cr),
        "ebidt preceding year": ("((operating_profit_preceding_year + other_income_preceding_year) / 10000000)", cr),
        "sales growth last year": ("(CASE WHEN sales_preceding_year > 0 THEN (sales_last_year / sales_preceding_year"
                                   " - 1) * 100 END)", "% FY vs preceding FY"),
        "profit growth last year": ("(CASE WHEN net_profit_preceding_year > 0 THEN (net_profit_last_year / "
                                    "net_profit_preceding_year - 1) * 100 END)", "% FY owners' profit"),
        "days since last result": ("date_diff('day', last_result_date, as_of_date)", "days"),
        "volume to 1 month average": ("(CAST(volume AS DOUBLE) / NULLIF(volume_1m_avg, 0))", "x, volume spike"),
    }  # fmt: skip
    names = {"material_cost": "material cost", "employee_cost": "employee cost", "other_expenses": "other expenses",
             "power_fuel": "power fuel", "freight": "freight", "ad_promo": "advertising"}  # fmt: skip
    for line, name in names.items():
        for p in COST_PERIODS:
            out[f"{name} to sales {p.replace('_', ' ')}"] = (f"({line}_{p}_pct * 100)", "% of sales")
    out["ad promo intensity"] = ("(ad_promo_last_year_pct * 100)", "% of FY sales, advertising and promotion")
    for line, name in (("material_cost", "material cost"), ("employee_cost", "employee cost"),
                       ("minority_share", "minority share"), ("dividends_paid", "dividend")):  # fmt: skip
        for fy in FYS:
            out[f"{name} {fy.replace('_', ' ')}"] = (f"({line}_{fy} / 10000000)", f"{cr}, fiscal year")
    for f in RED_FLAGS:
        label = f.replace("_or_", " ").replace("_", " ").replace("90d", "90days")
        out[f"red flag {label}"] = (f"CAST(rf_{f} AS INTEGER)", "1/0, Reg. 30")
    for r in G244_RATIOS:
        label = r.replace("_", " ")
        out[f"{label} numerator"] = (f"({r}_numerator / 10000000)", f"{cr}, input of {r}")
        out[f"{label} denominator"] = (f"({r}_denominator / 10000000)", f"{cr}, input of {r}")
    return out
