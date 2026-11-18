"""Ownership (ratio catalogue Batch 5) and hidden-gem signals, hats and scores (docs/hidden_gems.md), for `features.py`.

Three stages, all batched (never a query per security):
1. `period_values(book, end, b)` per entity, from the row's own scope book [C18]: core profit (PBT - other income -
   exceptional items) of the latest quarter, the preceding quarter and the same quarters a year earlier; sales and
   owners' profit of the quarter 15 months back (for the preceding quarter's YoY); TTM core profit after the TTM
   effective tax rate and the owners' share; TTM EBIT; the history-gated stability ratios.
2. `add_columns(...)` per security row (the `features.compute_rows` hook): Reg. 31 ownership columns from two
   batched reads (category totals of the five latest visible patterns, category-member line items of the latest),
   the Nifty 500 industry from the latest snapshot on or before the as-of, the signal columns and flags.
3. `cross_section(rows)` over all rows of one as-of date: magic-formula rank, universe medians, gem score and the
   hat booleans of docs/hidden_gems.md section B. `refresh_cross_section(con, as_of)` recomputes them from the
   stored day inside the materialize transaction, so an incremental run (a subset of rows recomputed) leaves every
   row of the day ranked against the same universe as a full run.

Conventions: `_pct`, `_pp`, yields and growth are DOUBLE fractions (0.08 = 8 percentage points; the DSL shows x100);
money is DECIMAL rupees. Growth is NULL when the base is <= 0 (`qoq_growth`). Industrial signals (core profit, PE on
core, earnings yield, margin change) are NULL for lenders and insurers: their other income is fee income, not a
one-off. Booleans are three-valued like SQL: a NULL input gives NULL, except `forensic_clean` (below).

`forensic_clean` (hidden_gems.md section A) is TRUE unless a measured red flag fails: other-income lift >= 8 pp in
the latest quarter, a suspected restatement [X106], Beneish M >= -1.78, promoter pledge >= 5%, an auditor resignation
or a fraud / default disclosure in 90 days [E5], other income >= 30% of TTM PBT (industrial books only), a modified
audit opinion (the latest visible annual auditor's report text or the latest results audit opinion is QUALIFIED /
ADVERSE / DISCLAIMER; features_audit, X121-X124), or a material uncertainty related to going concern in the latest
annual report (an emphasis of matter does not fail it). A flag that cannot be measured (NULL) does not fail it; it is
NULL only for rows without fundamentals.

History-gated (C9, NULL until the window is in scope, then on by themselves): `roce_stability_5y` and
`opm_stability_5y` (1 - population std / mean over 5 fiscal years; FY25-FY29, ~May 2029), `pe_vs_own_5y_median`
(PE / median of the security's own daily PE over 5 years; from 2029-10-01), and the TTM-on-TTM core growth that
replaces the quarter growth in `peg` once 8 quarters are in scope (~Feb 2027).
"""

from __future__ import annotations

import csv
import statistics
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from financials import features_audit, features_pl
from financials.db import version_key
from financials.fundamentals import (
    _add_months,
    debt_at,
    entity_filter,
    latest_fiscal_year,
    qoq_growth,
    quarters_available_since,
    safe_div,
)
from financials.scope import MIN_TRADE_DATE

# ── columns (schema order: `-- batch D (ownership / hidden gems)` in db/schema.sql) ─────────────────────────────────

OWNERSHIP_COLUMNS = (
    "fii_holding_change_qoq_pct", "dii_holding_change_qoq_pct", "inst_holding_pct", "unpledged_promoter_holding_pct",
    "mf_holding_pct", "mf_holding_change_qoq_pct", "insurance_holding_pct", "retail_holding_pct", "num_shareholders",
    "num_shareholders_preceding_quarter", "num_shareholders_change_qoq_pct", "num_shareholders_1y_back",
)  # fmt: skip
SIGNAL_COLUMNS = (
    "sales_growth_yoy_preceding_quarter_pct", "profit_growth_yoy_preceding_quarter_pct", "core_profit_latest_quarter",
    "core_profit_yoy_latest_q", "core_profit_yoy_preceding_q", "other_income_lift_pp", "pe_core", "growth_sustained",
    "growth_acceleration_pp", "opm_change_yoy_pp", "operating_leverage", "peg", "earnings_yield", "industry",
    "cyclical_flag", "under_owned", "forensic_clean", "cash_conversion_ok", "capex_pay_off_signal",
    "roce_stability_5y", "opm_stability_5y", "pe_vs_own_5y_median",
)  # fmt: skip
HATS = (
    "hidden_compounder", "quality_fair_price", "magic_formula", "garp", "turnaround", "under_owned", "cash_machine",
    "fallen_quality", "capex_pay_off", "cyclical", "lender",
)  # fmt: skip
HAT_COLUMNS = tuple(f"hat_{h}" for h in HATS)
CROSS_COLUMNS = (
    "magic_formula_rank", "pe_core_universe_median", "market_cap_universe_median", "gem_score", *HAT_COLUMNS,
    "hats_passed",
)  # fmt: skip
GEM_COLUMNS = (*OWNERSHIP_COLUMNS, *SIGNAL_COLUMNS, *CROSS_COLUMNS)

FINANCIAL_ARCHETYPES = frozenset({"FINANCIAL_LENDING", "INSURANCE"})

# ── thresholds (docs/hidden_gems.md; fractions) ──────────────────────────────────────────────────────────────────

SUSTAINED_SALES_GROWTH = 0.12
LIFT_MAX = 0.08  # other income / exceptional lift of reported profit growth, latest quarter
BENEISH_MAX = -1.78
PLEDGE_MAX = 0.05
OTHER_INCOME_TO_PBT_MAX = 0.30
CASH_CONVERSION_MIN = 0.7
CAPEX_CWIP_MIN, CAPEX_TO_DEP_MIN, CAPEX_DE_MAX = 0.25, 2.0, 1.0
UNDER_OWNED_INST_MAX, UNDER_OWNED_PROMOTER_MIN = 0.15, 0.50
MAGIC_FORMULA_TOP = 15
CRORE = Decimal(10_000_000)

# Cyclical industries: the NSE Nifty 500 list's "Industry" column (one of 20 sector groups; the 4-level
# classification is a new free source). Shipping and other cyclicals classified elsewhere ("Services") come from the
# curated reference/cyclical_symbols.csv, never from names in code.
CYCLICAL_INDUSTRIES = frozenset({"Metals & Mining", "Oil Gas & Consumable Fuels"})
INDUSTRY_INDEX = "NIFTY 500"

# gem_score (hidden_gems.md section A): weight, clip bounds of the raw input. Inputs are clipped, z-scored within the
# gated non-financial, non-cyclical universe of the day, z clipped to +-3; a missing input scores 0 (the mean).
GEM_WEIGHTS = {
    "roce": (1.0, (-0.25, 0.75)),
    "sustained_growth": (1.0, (-0.5, 1.0)),  # min(sales YoY latest, preceding quarter)
    "earnings_yield": (1.2, (-0.10, 0.25)),
    "under_ownership": (0.8, (-1.0, 0.0)),  # - institutional holding
    "cash_conversion": (0.6, (-0.5, 2.0)),  # CFO / EBITDA
    "margin_trend": (0.6, (-0.15, 0.15)),  # OPM change vs the same quarter a year earlier
}
Z_CLIP = 3.0

STABILITY_YEARS = 5
PE_MEDIAN_YEARS = 5
SHP18_RULE = "SHP18_PERCENT_SCALE"
PCT_ELEMENT = "ShareholdingAsAPercentageOfTotalNumberOfShares"
# Reg. 31 category members (CategoryOfShareholdersAxis) stored as line items (C24) [SHP19].
INSURANCE_MEMBER = "InsuranceCompaniesMember"
RETAIL_MEMBER = "ResidentIndividualShareholdersHoldingNominalShareCapitalUpToRsTwoLakhMember"


def _f(x) -> float | None:
    return None if x is None else float(x)


def _and(*conds) -> bool | None:
    """SQL three-valued AND."""
    if any(c is False for c in conds):
        return False
    return None if any(c is None for c in conds) else True


def _ge(x, t) -> bool | None:
    return None if x is None else x >= t


def _le(x, t) -> bool | None:
    return None if x is None else x <= t


def _lt(x, t) -> bool | None:
    return None if x is None else x < t


# ── stage 1: per entity, from the scope book ──────────────────────────────────────────────────────────────────────


def _owners_share(owners: Decimal | None, total: Decimal | None) -> Decimal | None:
    """Owners' share of TTM profit: 1 without NCI, owners / PAT when both are positive, else unknown."""
    if owners is None or total is None:
        return None
    if owners == total:
        return Decimal(1)
    return owners / total if total > 0 and owners >= 0 else None


def _stability(values: list[Decimal | None]) -> float | None:
    """1 - population std / mean; NULL when a year is missing or the mean is <= 0."""
    if not values or None in values:
        return None
    xs = [float(v) for v in values]
    mean = statistics.fmean(xs)
    return None if mean <= 0 else 1 - statistics.pstdev(xs) / mean


def _fy_periods(book, end: date, n: int) -> list[tuple[date, date]] | None:
    """The `n` fiscal years ending with the latest one on or before `end`, when the oldest is in scope [C9]."""
    fy = latest_fiscal_year(book, end)
    if fy is None or not quarters_available_since(fy[1], 4 * (n - 1) + 1):
        return None
    return [(_add_months(fy[0], -12 * i), _add_months(fy[1], -12 * i)) for i in range(n)]


def opm_stability(book, end: date, n: int = STABILITY_YEARS) -> float | None:
    periods = _fy_periods(book, end, n)
    if periods is None:
        return None
    tags = features_pl._tags(book)
    return _stability([safe_div(features_pl.fy_value(book, features_pl.EBITDA, p),
                                features_pl.fy_value(book, tags["sales"], p)) for p in periods])  # fmt: skip


def roce_stability(book, end: date, n: int = STABILITY_YEARS) -> float | None:
    """Annual ROCE = FY EBIT / (total equity + debt) at the FY end balance sheet (as `roce`, one year at a time)."""
    periods = _fy_periods(book, end, n)
    if periods is None:
        return None
    features_pl._tags(book)
    values = []
    for p in periods:
        ebit = features_pl.fy_value(book, features_pl.EBIT, p)
        eq, debt = book.instants.get("total_equity", {}).get(p[1]), debt_at(book, p[1])
        values.append(None if ebit is None or eq is None or debt is None else safe_div(ebit, eq + debt))
    return _stability(values)


def core_quarter(book, tags: dict, end: date) -> Decimal | None:
    """PBT - other income - exceptional items of the quarter ending `end` (absent exceptional line = 0)."""
    parts = [book.quarter(tags[k], end) for k in ("pbt", "other_income", "exceptional_items")]
    return None if None in parts else parts[0] - parts[1] - parts[2]


def core_ttm(book, tags: dict, end: date) -> Decimal | None:
    parts = [book.ttm(tags[k], end) for k in ("pbt", "other_income", "exceptional_items")]
    return None if None in parts else parts[0] - parts[1] - parts[2]


def period_values(book, end: date, b: dict) -> dict:
    """Stage 1 (one per entity and scope book). `b` = fundamentals.building_blocks(book, end)."""
    tags = features_pl._tags(book)
    cores = {m: core_quarter(book, tags, _add_months(end, m)) for m in (0, -3, -12, -15)}
    pre = core_ttm(book, tags, end)
    share = _owners_share(b.get("pat_owners"), b.get("pat"))
    after_tax = None if pre is None or share is None else pre * (1 - b.get("etr", Decimal(0))) * share
    ttm_yoy = None
    if quarters_available_since(end, 8):  # TTM-on-TTM needs 8 in-scope quarters [C9]
        ttm_yoy = qoq_growth(pre, core_ttm(book, tags, _add_months(end, -12)))
    return {
        "core_q": cores,
        "sales_q15": book.quarter(tags["sales"], _add_months(end, -15)),
        "net_profit_q15": book.quarter(tags["net_profit"], _add_months(end, -15)),
        "core_earnings_ttm": after_tax,
        "core_ttm_yoy": ttm_yoy,
        "ebit_ttm": b.get("ebit"),
        "roce_stability_5y": roce_stability(book, end),
        "opm_stability_5y": opm_stability(book, end),
    }


# ── stage 2: batched reads and per-row columns ────────────────────────────────────────────────────────────────────


def ownership_inputs(con, as_of_ts: datetime, entities=None) -> dict[str, dict]:
    """Per entity: {"dates": {rank: as_of_date}, "cats": {rank: {category: (pct, holders)}}, "members": {member:
    pct}} for the five latest visible Reg. 31 patterns (latest visible revision per as-of date, as features._preload)
    and the category-member percentages of the latest one, scaled to fractions [SHP18]. Two queries."""
    only, only_p = entity_filter("entity_id", entities)
    ranked = (
        """WITH f AS (
               SELECT entity_id, as_of_date, filing_id, parser_version FROM (
                   SELECT entity_id, as_of_date, filing_id, parser_version, row_number() OVER (
                       PARTITION BY entity_id, as_of_date ORDER BY visible_from_ts DESC, """
        + version_key()
        + """ DESC, filing_id DESC) AS rn
                   FROM shareholding_meta WHERE visible_from_ts <= ?"""
        + only
        + """) WHERE rn = 1),
           r AS (SELECT *, row_number() OVER (PARTITION BY entity_id ORDER BY as_of_date DESC) AS r FROM f)"""
    )
    out: dict[str, dict] = defaultdict(lambda: {"dates": {}, "cats": defaultdict(dict), "members": {}})
    for ent, d, rank, cat, pct, holders in con.execute(
        ranked
        + """ SELECT r.entity_id, r.as_of_date, r.r, o.category, o.pct, o.holders
                     FROM r JOIN shareholding_observations o USING (filing_id, parser_version)
                     WHERE r.r <= 5 AND o.category IN ('TOTAL', 'FII', 'DII', 'MUTUAL_FUNDS')""",
        [as_of_ts, *only_p],
    ).fetchall():
        out[ent]["dates"][rank] = d
        out[ent]["cats"][rank][cat] = (pct, holders)
    for ent, member, value, rules in con.execute(
        ranked
        + """ SELECT r.entity_id, li.category_member, li.value, m.rules_applied
                     FROM r JOIN shareholding_line_items li USING (filing_id, parser_version)
                     JOIN shareholding_meta m USING (filing_id, parser_version)
                     WHERE r.r = 1 AND li.element = ? AND li.category_member IN (?, ?)""",
        [as_of_ts, *only_p, PCT_ELEMENT, INSURANCE_MEMBER, RETAIL_MEMBER],
    ).fetchall():
        scale = Decimal(100) if SHP18_RULE in (rules or "").split(",") else Decimal(1)
        out[ent]["members"][member] = float(Decimal(value) / scale)
    return out


def _pp(now, prev) -> float | None:
    """Difference of two filed fractions, exact in Decimal, then one float."""
    if now is None or prev is None:
        return None
    return float(Decimal(str(now)) - Decimal(str(prev)))


def ownership_columns(row: dict, own: dict | None) -> dict:
    """Batch 5 columns of one row. Changes need the immediately preceding quarter end (as promoter change [SHP14])."""
    from financials.features import _quarter_before

    out = dict.fromkeys(OWNERSHIP_COLUMNS)
    fii, dii, promoter, pledge = (row.get(k) for k in ("fii_holding_pct", "dii_holding_pct", "promoter_holding_pct",
                                                       "promoter_pledge_pct"))  # fmt: skip
    if fii is not None and dii is not None:
        out["inst_holding_pct"] = float(Decimal(str(fii)) + Decimal(str(dii)))
    if promoter is not None and promoter == 0:
        out["unpledged_promoter_holding_pct"] = 0.0
    elif promoter is not None and pledge is not None:
        out["unpledged_promoter_holding_pct"] = promoter * (1 - pledge)
    if not own or 1 not in own["dates"]:
        return out
    cur, now = own["dates"][1], own["cats"][1]
    adjacent = own["dates"].get(2) is not None and own["dates"][2] == _quarter_before(cur)
    prev = own["cats"].get(2, {}) if adjacent else {}

    def pct(cats, cat):
        return cats.get(cat, (None, None))[0]

    def holders(cats, cat="TOTAL"):
        return cats.get(cat, (None, None))[1]

    out["mf_holding_pct"] = _f(pct(now, "MUTUAL_FUNDS"))
    out["insurance_holding_pct"] = own["members"].get(INSURANCE_MEMBER)
    out["retail_holding_pct"] = own["members"].get(RETAIL_MEMBER)
    out["num_shareholders"] = holders(now)
    if adjacent:
        out["fii_holding_change_qoq_pct"] = _pp(pct(now, "FII"), pct(prev, "FII"))
        out["dii_holding_change_qoq_pct"] = _pp(pct(now, "DII"), pct(prev, "DII"))
        out["mf_holding_change_qoq_pct"] = _pp(pct(now, "MUTUAL_FUNDS"), pct(prev, "MUTUAL_FUNDS"))
        out["num_shareholders_preceding_quarter"] = holders(prev)
        out["num_shareholders_change_qoq_pct"] = _f(qoq_growth(
            *(None if h is None else Decimal(h) for h in (holders(now), holders(prev)))))  # fmt: skip
    year_back = _add_months(cur, -12)
    for rank, d in own["dates"].items():
        if d == year_back:
            out["num_shareholders_1y_back"] = holders(own["cats"][rank])
    return out


def industries(con, as_of: date, securities=None) -> dict[str, str]:
    """Security -> industry of the latest Nifty 500 snapshot on or before `as_of` that lists it (ISIN resolved
    through the identifier history valid at `as_of`, invariant 3). One query."""
    only, only_p = entity_filter("h.security_id", securities)
    return dict(
        con.execute(
            """SELECT h.security_id, arg_max(s.industry, s.snapshot_date)
               FROM raw_index_snapshot s JOIN security_identifier_history h
                 ON h.isin = s.isin AND h.valid_from <= ? AND (h.valid_to IS NULL OR h.valid_to > ?)
               WHERE s.index_name = ? AND s.snapshot_date <= ? AND s.industry IS NOT NULL"""
            + only
            + " GROUP BY h.security_id",
            [as_of, as_of, INDUSTRY_INDEX, as_of, *only_p],
        ).fetchall()
    )


def curated_cyclicals() -> dict[str, str]:
    """reference/cyclical_symbols.csv: symbol -> cyclical group, for cyclicals outside CYCLICAL_INDUSTRIES."""
    from financials.sources import ROOT

    path = ROOT / "reference" / "cyclical_symbols.csv"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        return {r["symbol"]: r["cyclical_group"] for r in csv.DictReader(fh)}


def pe_history_gate(as_of: date, years: int = PE_MEDIAN_YEARS) -> date | None:
    """Start of the PE window, or None while it reaches before MIN_TRADE_DATE [C9]."""
    start = _add_months(as_of, -12 * years)
    return start if start >= MIN_TRADE_DATE else None


def pe_medians(con, as_of: date, securities=None) -> dict[str, float]:
    """Median of each security's own positive daily PE over the 5 years before `as_of` (stored history), only for
    securities with a stored PE in the window's first month (a shorter history is not a 5-year median). One query;
    empty while the window is not in scope."""
    start = pe_history_gate(as_of)
    if start is None:
        return {}
    only, only_p = entity_filter("security_id", securities)
    rows = con.execute(
        "SELECT security_id, median(pe), min(as_of_date) FROM features_daily "  # pe: a DAILY column
        "WHERE as_of_date >= ? AND as_of_date < ? AND pe > 0" + only + " GROUP BY security_id",
        [start, as_of, *only_p],
    ).fetchall()
    first_month = _add_months(start, 1)
    return {sec: float(med) for sec, med, first in rows if first <= first_month}


def signal_columns(row: dict, g: dict | None, industry: str | None, curated: dict, pe_median: float | None) -> dict:
    """Hidden-gem signal columns of one row (hidden_gems.md section A); `g` = stage 1 values of its entity."""
    out = dict.fromkeys(SIGNAL_COLUMNS)
    g = g or {}
    financial = row.get("valuation_archetype") in FINANCIAL_ARCHETYPES
    out["industry"] = industry
    if industry is not None or row.get("symbol") in curated:
        out["cyclical_flag"] = industry in CYCLICAL_INDUSTRIES or row.get("symbol") in curated
    sales_l = row.get("sales_growth_yoy_quarter_pct")
    profit_l = row.get("profit_growth_yoy_quarter_pct")
    sales_p = _f(qoq_growth(row.get("sales_preceding_quarter"), g.get("sales_q15")))
    out["sales_growth_yoy_preceding_quarter_pct"] = sales_p
    out["profit_growth_yoy_preceding_quarter_pct"] = _f(qoq_growth(row.get("net_profit_preceding_quarter"),
                                                                   g.get("net_profit_q15")))  # fmt: skip
    if sales_l is not None and sales_p is not None:
        out["growth_sustained"] = sales_l >= SUSTAINED_SALES_GROWTH and sales_p >= SUSTAINED_SALES_GROWTH
        out["growth_acceleration_pp"] = sales_l - sales_p
    if not financial and g:
        cores = g["core_q"]
        if cores[0] is not None:
            out["core_profit_latest_quarter"] = cores[0].quantize(Decimal("0.01"))
        core_l, core_p = _f(qoq_growth(cores[0], cores[-12])), _f(qoq_growth(cores[-3], cores[-15]))
        out["core_profit_yoy_latest_q"], out["core_profit_yoy_preceding_q"] = core_l, core_p
        if profit_l is not None and core_l is not None:
            out["other_income_lift_pp"] = profit_l - core_l
        opm_now, opm_ly = row.get("opm_latest_quarter_pct"), row.get("opm_preceding_year_quarter_pct")
        if opm_now is not None and opm_ly is not None:
            out["opm_change_yoy_pp"] = opm_now - opm_ly
        if core_l is not None and sales_l is not None and sales_l > 0:
            out["operating_leverage"] = core_l / sales_l
        mcap, earnings = row.get("market_cap"), g.get("core_earnings_ttm")
        if mcap is not None and earnings is not None and earnings > 0:
            out["pe_core"] = float(mcap / earnings)
        growth = _f(g.get("core_ttm_yoy")) if g.get("core_ttm_yoy") is not None else core_l
        if out["pe_core"] is not None and growth is not None and growth > 0:
            out["peg"] = out["pe_core"] / (100 * growth)
        ev, ebit = row.get("enterprise_value"), g.get("ebit_ttm")
        if ev is not None and ebit is not None and ev > 0:
            out["earnings_yield"] = float(ebit / ev)
        out["roce_stability_5y"], out["opm_stability_5y"] = g.get("roce_stability_5y"), g.get("opm_stability_5y")
    if row.get("pe") is not None and row["pe"] > 0 and pe_median:
        out["pe_vs_own_5y_median"] = row["pe"] / pe_median
    inst = row.get("inst_holding_pct")
    out["under_owned"] = _and(_le(inst, UNDER_OWNED_INST_MAX), _ge(row.get("promoter_holding_pct"),
                              UNDER_OWNED_PROMOTER_MIN), None if row.get("promoter_pledge_pct") is None
                              else row["promoter_pledge_pct"] == 0)  # fmt: skip
    out["cash_conversion_ok"] = _ge(row.get("cfo_to_ebitda"), CASH_CONVERSION_MIN)
    # industrial signal: NULL for lenders and insurers (lending NBFCs carry a debt / equity since X228)
    out["capex_pay_off_signal"] = None if financial else _and(_ge(row.get("cwip_to_gross_block"), CAPEX_CWIP_MIN),
                                                              _ge(row.get("capex_to_depreciation"), CAPEX_TO_DEP_MIN),
                                                              _le(row.get("debt_to_equity"), CAPEX_DE_MAX))  # fmt: skip
    out["forensic_clean"] = forensic_clean({**row, **out})
    return out


def forensic_clean(r: dict) -> bool | None:
    """TRUE unless a measured red flag fails (module docstring); NULL without fundamentals."""
    if r.get("fundamentals_end") is None:
        return None
    financial = r.get("valuation_archetype") in FINANCIAL_ARCHETYPES
    fails = (
        r.get("restatement_suspected") is True,
        r.get("beneish_m") is not None and r["beneish_m"] >= BENEISH_MAX,
        r.get("promoter_pledge_pct") is not None and r["promoter_pledge_pct"] >= PLEDGE_MAX,
        bool(r.get("auditor_resignations_90d")),
        bool(r.get("fraud_or_default_90d")),
        features_audit.modified_opinion(r) is True,  # [X121-X124]: text / results opinion, never the checkbox
        r.get("going_concern_uncertainty") is True,  # emphasis_of_matter is informational only
        not financial and _ge(r.get("other_income_lift_pp"), LIFT_MAX) is True,
        not financial and _ge(r.get("other_income_to_pbt"), OTHER_INCOME_TO_PBT_MAX) is True,
    )
    return not any(fails)


def add_columns(con, rows: list[dict], as_of: date, as_of_ts: datetime, fundamentals: dict, entities=None) -> None:
    """The features.compute_rows hook: ownership, signals and the day's cross-section, in place (batched reads)."""
    secs = None if entities is None else {r["security_id"] for r in rows}
    own = ownership_inputs(con, as_of_ts, entities)
    ind = industries(con, as_of, secs)
    curated = curated_cyclicals()
    medians = pe_medians(con, as_of, secs)
    for row in rows:
        row.update(ownership_columns(row, own.get(row["entity_id"])))
        g = (fundamentals.get(row["entity_id"]) or {}).get("_gems")
        row.update(signal_columns(row, g, ind.get(row["security_id"]), curated, medians.get(row["security_id"])))
    cross_section(rows)


# ── stage 3: cross-section of one as-of date ──────────────────────────────────────────────────────────────────────

# Every column the cross-section reads (refresh_cross_section selects exactly these from the stored day).
CROSS_INPUTS = (
    "security_id", "symbol", "valuation_archetype", "forensic_clean", "cyclical_flag", "earnings_yield", "roce", "roe",
    "roic", "pe", "pb", "pe_core", "peg", "market_cap", "inst_holding_pct", "under_owned", "growth_sustained",
    "sales_growth_yoy_quarter_pct", "sales_growth_yoy_preceding_quarter_pct", "profit_growth_yoy_quarter_pct",
    "core_profit_yoy_latest_q", "opm_change_yoy_pp", "cfo_to_ebitda", "debt_to_equity", "return_6m", "fcf_to_pat",
    "price_to_cfo", "working_capital_days", "dist_52w_high", "piotroski_f", "capex_pay_off_signal", "roa", "gnpa_pct",
)  # fmt: skip


def _nonfin(r: dict) -> bool | None:
    a = r.get("valuation_archetype")
    return None if a is None else a not in FINANCIAL_ARCHETYPES


def _gated(r: dict) -> bool:
    """The gated non-financial universe: forensic_clean and not a lender / insurer."""
    return r.get("forensic_clean") is True and _nonfin(r) is True


def _ranks(values: list[float], descending: bool = True) -> list[int]:
    """Competition ranks (1 = best; ties share the lower rank)."""
    order = sorted(values, reverse=descending)
    first = {}
    for i, v in enumerate(order, 1):
        first.setdefault(v, i)
    return [first[v] for v in values]


def magic_formula(rows: list[dict]) -> None:
    """Rank of earnings yield + rank of ROCE (each 1 = highest) within the gated universe, then the position by that
    sum (ties: earnings-yield rank, then symbol); 1 = best. NULL outside the universe or without both inputs."""
    pool = [r for r in rows if _gated(r) and r.get("earnings_yield") is not None and r.get("roce") is not None]
    ey = _ranks([r["earnings_yield"] for r in pool])
    roce = _ranks([r["roce"] for r in pool])
    keyed = sorted(zip(pool, ey, roce, strict=True), key=lambda t: (t[1] + t[2], t[1], t[0]["symbol"]))
    for r in rows:
        r["magic_formula_rank"] = None
    for pos, (r, _, _) in enumerate(keyed, 1):
        r["magic_formula_rank"] = pos


def _gem_inputs(r: dict) -> dict[str, float | None]:
    s1, s2 = r.get("sales_growth_yoy_quarter_pct"), r.get("sales_growth_yoy_preceding_quarter_pct")
    inst = r.get("inst_holding_pct")
    return {
        "roce": r.get("roce"),
        "sustained_growth": None if s1 is None or s2 is None else min(s1, s2),
        "earnings_yield": r.get("earnings_yield"),
        "under_ownership": None if inst is None else -inst,
        "cash_conversion": r.get("cfo_to_ebitda"),
        "margin_trend": r.get("opm_change_yoy_pp"),
    }


def gem_score(rows: list[dict]) -> None:
    """Weighted mean of clipped z-scores (GEM_WEIGHTS) within the gated non-financial, non-cyclical universe; NULL
    outside it or without ROCE and earnings yield."""
    pool = [r for r in rows if _gated(r) and r.get("cyclical_flag") is False
            and r.get("roce") is not None and r.get("earnings_yield") is not None]  # fmt: skip
    inputs = [_gem_inputs(r) for r in pool]
    stats = {}
    for k, (_, (lo, hi)) in GEM_WEIGHTS.items():
        xs = [min(max(i[k], lo), hi) for i in inputs if i[k] is not None]
        stats[k] = (statistics.fmean(xs), statistics.pstdev(xs)) if xs else (0.0, 0.0)
    total = sum(w for w, _ in GEM_WEIGHTS.values())
    for r in rows:
        r["gem_score"] = None
    for r, i in zip(pool, inputs, strict=True):
        score = 0.0
        for k, (w, (lo, hi)) in GEM_WEIGHTS.items():
            mean, sd = stats[k]
            if i[k] is None or sd == 0:
                continue
            z = (min(max(i[k], lo), hi) - mean) / sd
            score += w * min(max(z, -Z_CLIP), Z_CLIP)
        r["gem_score"] = score / total


def hats(r: dict) -> dict[str, bool | None]:
    """Section B screens except the magic formula's top-N (set in cross_section). Every hat starts from
    forensic_clean; all but the lender hat exclude lenders and insurers."""
    base = _and(r.get("forensic_clean"), _nonfin(r))
    sales_l, core_l = r.get("sales_growth_yoy_quarter_pct"), r.get("core_profit_yoy_latest_q")
    mcap, med_mcap, med_pe = r.get("market_cap"), r.get("market_cap_universe_median"), r.get("pe_core_universe_median")
    piotroski = r.get("piotroski_f")
    gnpa = r.get("gnpa_pct")
    return {
        "hidden_compounder": _and(base, None if r.get("cyclical_flag") is None else not r["cyclical_flag"],
                                  _ge(mcap, 3000 * CRORE), _le(mcap, 75000 * CRORE),
                                  _le(r.get("inst_holding_pct"), 0.35), _ge(r.get("roce"), 0.18),
                                  r.get("growth_sustained"), _ge(r.get("opm_change_yoy_pp"), -0.015),
                                  _ge(r.get("cfo_to_ebitda"), 0.7), _le(r.get("debt_to_equity"), 0.5),
                                  _le(r.get("pe_core"), 40), _le(r.get("return_6m"), 0.30)),
        "quality_fair_price": _and(base, _ge(r.get("roce"), 0.20), _ge(r.get("roe"), 0.15),
                                   _le(r.get("debt_to_equity"), 0.5), _ge(r.get("cfo_to_ebitda"), 0.7),
                                   None if med_pe is None else _le(r.get("pe_core"), med_pe), _ge(core_l, 0.10)),
        "garp": _and(base, _ge(sales_l, 0.20), _ge(r.get("sales_growth_yoy_preceding_quarter_pct"), 0.15),
                     None if sales_l is None else _ge(core_l, sales_l), _ge(r.get("roce"), 0.15),
                     _le(r.get("peg"), 1)),
        "turnaround": _and(base, _ge(r.get("opm_change_yoy_pp"), 0.03), _ge(sales_l, 0.10), _le(r.get("pe"), 40),
                           _le(r.get("return_6m"), 0.15)),
        "under_owned": _and(base, r.get("under_owned"), _ge(r.get("roce"), 0.18), _ge(core_l, 0.15),
                            None if med_mcap is None else _lt(mcap, med_mcap)),
        "cash_machine": _and(base, _ge(r.get("fcf_to_pat"), 0.8), _ge(r.get("roic"), 0.25),
                             _le(r.get("price_to_cfo"), 30), _le(r.get("working_capital_days"), 45)),
        "fallen_quality": _and(base, _le(r.get("dist_52w_high"), -0.30), _ge(r.get("roce"), 0.18),
                               _le(r.get("debt_to_equity"), 0.5), _ge(core_l, 0),
                               True if piotroski is None else piotroski >= 6),
        "capex_pay_off": _and(base, r.get("capex_pay_off_signal"), _ge(r.get("roce"), 0.15), _ge(sales_l, 0.10)),
        "cyclical": _and(base, r.get("cyclical_flag"), _ge(r.get("roce"), 0.15), _ge(sales_l, 0.15)),
        "lender": _and(r.get("forensic_clean"), None if r.get("valuation_archetype") is None
                       else r["valuation_archetype"] == "FINANCIAL_LENDING", _ge(r.get("roa"), 0.015),
                       _le(r.get("pb"), 2.5), _ge(r.get("profit_growth_yoy_quarter_pct"), 0.15),
                       True if gnpa is None else gnpa <= 0.03),
    }  # fmt: skip


def cross_section(rows: list[dict]) -> None:
    """Stage 3 over every row of one as-of date, in place."""
    gated = [r for r in rows if _gated(r)]
    pe = [r["pe_core"] for r in gated if r.get("pe_core") is not None]
    mc = [r["market_cap"] for r in gated if r.get("market_cap") is not None]
    med_pe = statistics.median(pe) if pe else None
    med_mc = Decimal(statistics.median(mc)).quantize(Decimal("0.01")) if mc else None
    magic_formula(rows)
    gem_score(rows)
    for r in rows:
        r["pe_core_universe_median"], r["market_cap_universe_median"] = med_pe, med_mc
        r.update({f"hat_{k}": v for k, v in hats(r).items()})
    top = sorted((r for r in rows if r["magic_formula_rank"] is not None and _ge(r.get("roce"), 0.15)),
                 key=lambda r: (r["magic_formula_rank"], r["symbol"]))[:MAGIC_FORMULA_TOP]  # fmt: skip
    chosen = {id(r) for r in top}
    for r in rows:
        r["hat_magic_formula"] = id(r) in chosen
        r["hats_passed"] = sum(r[c] is True for c in HAT_COLUMNS)


_ARROW_TYPES = {"magic_formula_rank": "int32", "hats_passed": "int32", "market_cap_universe_median": "decimal",
                "pe_core_universe_median": "float64", "gem_score": "float64"}  # fmt: skip


def refresh_cross_section(con, as_of: date) -> None:
    """Recompute CROSS_COLUMNS for every stored row of `as_of` (inside the materialize transaction, after the day's
    rows are written): one read of the history view, one UPDATE of features_daily (CROSS_COLUMNS are DAILY columns,
    tests/test_features_store.py) through Arrow."""
    import pyarrow as pa

    from financials.db import fetch_dicts

    rows = fetch_dicts(con, f"SELECT {', '.join(CROSS_INPUTS)} FROM screener_features_history WHERE as_of_date = ? "
                       "ORDER BY security_id",
                       [as_of])  # fmt: skip
    if not rows:
        return
    cross_section(rows)
    types = {"int32": pa.int32(), "float64": pa.float64(), "decimal": pa.decimal128(24, 2)}
    fields = [pa.field("security_id", pa.string())] + [
        pa.field(c, types[_ARROW_TYPES[c]] if c in _ARROW_TYPES else pa.bool_()) for c in CROSS_COLUMNS
    ]
    table = pa.Table.from_pylist([{c: r[c] for c in ("security_id", *CROSS_COLUMNS)} for r in rows],
                                 schema=pa.schema(fields))  # fmt: skip
    con.register("_gems_cross", table)
    try:
        sets = ", ".join(f"{c} = s.{c}" for c in CROSS_COLUMNS)
        con.execute(
            f"UPDATE features_daily h SET {sets} FROM _gems_cross s "  # DAILY columns (features_store)
            "WHERE h.as_of_date = ? AND h.security_id = s.security_id",
            [as_of],
        )
    finally:
        con.unregister("_gems_cross")
