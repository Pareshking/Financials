"""Screener DSL → parameterised DuckDB SQL (architecture §14).

    query      := or_expr
    or_expr    := and_expr ("OR" and_expr)*
    and_expr   := not_expr ("AND" not_expr)*
    not_expr   := "NOT" not_expr | comparison | "(" or_expr ")"
    comparison := arith ("<" | "<=" | ">" | ">=" | "=" | "!=") arith
    arith      := term (("+" | "-") term)*
    term       := factor (("*" | "/") factor)*
    factor     := NUMBER | ALIAS | "(" arith ")" | "-" factor

Safety: user text never reaches SQL. Aliases resolve to fixed SQL expressions from ALIASES (or to
saved custom ratios, themselves parsed by this grammar); numbers become bound parameters. Division
compiles to `x / NULLIF(y, 0)`; any NULL comparison is not TRUE, so missing data never passes a filter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from financials.db import table_columns
from financials.timeutil import utc_now

# alias (lower-case, single-spaced) -> (SQL over screener_features columns, unit note)
ALIASES: dict[str, tuple[str, str]] = {
    "current price": ("close", "INR"),
    "market capitalization": ("(market_cap / 10000000)", "INR crore"),
    "market cap": ("(market_cap / 10000000)", "INR crore"),
    "enterprise value": ("(enterprise_value / 10000000)", "INR crore"),
    "sales": ("(sales_ttm / 10000000)", "INR crore, TTM"),
    "ebitda": ("(ebitda_ttm / 10000000)", "INR crore, TTM"),
    "net profit": ("(pat_ttm / 10000000)", "INR crore, TTM"),
    "free cash flow": ("(fcf_ttm / 10000000)", "INR crore, TTM (H1/FY bridge)"),
    "net debt": ("(net_debt / 10000000)", "INR crore"),
    "book value": ("book_value_per_share", "INR per share, owners' equity / shares (Screener's meaning)"),
    "book value per share": ("book_value_per_share", "INR per share, owners' equity / shares"),
    "net worth": ("(total_equity / 10000000)", "INR crore, total equity (latest H1/FY BS)"),
    "price to earning": ("pe", "x"),
    "pe": ("pe", "x"),
    "price to book value": ("pb", "x"),
    "pb": ("pb", "x"),
    "ev to ebitda": ("ev_ebitda", "x"),
    "opm": ("(opm * 100)", "%"),
    "sales growth": ("(sales_growth_yoy * 100)", "% YoY on TTM"),
    "profit growth": ("(profit_growth_yoy * 100)", "% YoY on TTM"),
    "roe": ("(roe * 100)", "%"),
    "roce": ("(roce * 100)", "%"),
    "roic": ("(roic * 100)", "%"),
    "croic": ("(croic * 100)", "%"),
    "debt to equity": ("debt_to_equity", "x (lending NBFCs: borrowed funds / equity, X228; NULL for banks)"),
    "fcf yield": ("(fcff_yield * 100)", "% of EV (unlevered)"),
    "other income to pbt": ("(other_income_to_pbt * 100)", "%"),
    "altman z": ("altman_z_dd", "Z'' score"),
    "piotroski score": ("piotroski_f", "0..9 (NULL without two fiscal years)"),
    "piotroski f score": ("piotroski_f", "0..9 (NULL without two fiscal years)"),
    "beneish m": ("beneish_m", "score (NULL without two fiscal years)"),
    "beneish m score": ("beneish_m", "score (NULL without two fiscal years)"),
    "capex to depreciation": ("capex_to_depreciation", "x"),
    "cwip to gross block": ("(cwip_to_gross_block * 100)", "%"),
    "rote": ("(rote * 100)", "%"),
    "roce screener": ("(roce_screener * 100)", "% (Screener: PBT + interest over average capital)"),
    "roe screener": ("(roe_screener * 100)", "% (Screener: last FY owners' profit over average owners' equity)"),
    "return on equity screener": ("(roe_screener * 100)", "% (Screener: last FY profit / average equity)"),
    "debtor days": ("debtor_days", "days (closing debtors)"),
    "inventory turnover": ("inventory_turnover", "x (sales / closing inventory)"),
    "working capital": ("(working_capital / 10000000)", "Rs Cr (Other Assets - Other Liabilities)"),
    "inventory days": ("inventory_days", "days (closing inventory / COGS)"),
    "vnb margin": ("(vnb_margin * 100)", "%, life insurers (supplemental KPI)"),
    "embedded value": ("(embedded_value / 10000000)", "Rs Cr, life insurers (supplemental KPI)"),
    "ape growth": ("(ape_growth * 100)", "%, life insurers (supplemental KPI)"),
    "gov": ("(gov / 10000000)", "Rs Cr, gross order value (supplemental KPI)"),
    "take rate": ("(take_rate * 100)", "% (supplemental KPI)"),
    "net take rate": ("(take_rate * 100)", "% (supplemental KPI)"),
    "contribution margin": ("(contribution_margin * 100)", "% (supplemental KPI)"),
    "nrr": ("(nrr * 100)", "%, net revenue retention (supplemental KPI)"),
    "cac payback": ("cac_payback", "months (supplemental KPI)"),
    "days payable": ("days_payable", "days (closing trade payables / COGS)"),
    "payable days": ("days_payable", "days (closing trade payables / COGS)"),
    "cash conversion cycle": ("cash_conversion_cycle", "days (debtor + inventory - payable)"),
    "working capital days": ("working_capital_days", "days ((CA - cash - current investments - CL) / sales)"),
    "return on tangible equity": ("(rote * 100)", "%"),
    "rnd royalty intensity": ("(rnd_and_royalty_intensity * 100)", "% of revenue"),
    "order wins 90d": ("order_wins_90d", "count, Reg. 30 order wins in 90 days"),
    "order value 90d": ("(order_value_90d / 10000000)", "Rs Cr, Reg. 30 order wins in 90 days"),
    "kmp resignations 90d": ("kmp_resignations_90d", "count"),
    "auditor resignations 90d": ("auditor_resignations_90d", "count"),
    "fraud default 90d": ("fraud_or_default_90d", "count"),
    "penalties 90d": ("penalties_90d", "count (NULL: no verified penalty event yet)"),
    "contingent liabilities to net worth": ("(contingent_liabilities_to_net_worth * 100)", "%"),
    "return 1m": ("(return_1m * 100)", "%"),
    "return 3m": ("(return_3m * 100)", "%"),
    "return 6m": ("(return_6m * 100)", "%"),
    "return 12m": ("(return_12m * 100)", "%"),
    "price to 50dma": ("price_to_dma50", "x"),
    "price to 200dma": ("price_to_dma200", "x"),
    "distance from 52w high": ("(dist_52w_high * 100)", "% (<= 0)"),
    "delivery 5d": ("deliv_avg_5d", "shares/day"),
    "delivery 20d": ("deliv_avg_20d", "shares/day"),
    "delivery velocity": ("delivery_velocity", "x (5D / 20D)"),
    "float turnover": ("float_turnover_pct", "% of public shares per day (5D)"),
    "promoter holding": ("(promoter_holding_pct * 100)", "%"),
    "promoter pledge": ("(promoter_pledge_pct * 100)", "% of promoter shares pledged"),
    "pledged percentage": ("(promoter_pledge_pct * 100)", "% of promoter shares pledged"),
    "promoter encumbered": ("(promoter_encumbered_pct * 100)", "% of promoter shares encumbered (pledge+NDU+other)"),
    "fii holding": ("(fii_holding_pct * 100)", "% (SEBI Institutions (Foreign), incl. FDI)"),
    "fpi holding": ("(fpi_holding_pct * 100)", "% (FPI Category I + II)"),
    "dii holding": ("(dii_holding_pct * 100)", "%"),
    "public holding": ("(public_holding_pct * 100)", "%"),
    "change in fii dii holding": ("(fii_dii_qoq_change_pct * 100)", "percentage points, QoQ"),
    "fii dii qoq change": ("(fii_dii_qoq_change_pct * 100)", "percentage points, QoQ"),
    "in nifty 500": ("CAST(in_nifty500 AS INTEGER)", "1/0"),
    "eps": ("eps_ttm", "INR per share, TTM owners' profit / current shares"),
    "eps continuing": ("eps_continuing_ttm", "INR per share, TTM, ex discontinued"),
    "roe continuing": ("(roe_continuing * 100)", "%, ex discontinued"),
    "core profit": ("(core_profit_ttm / 10000000)", "INR crore, TTM, ex discontinued and exceptional (net of tax)"),
    "lending nbfc": ("CAST(is_lending_nbfc AS INTEGER)", "1/0 (NULL if not an NBFC)"),
    "nii": ("(nii_ttm / 10000000)", "INR crore, TTM, lenders"),
    "ppop": ("(ppop_ttm / 10000000)", "INR crore, TTM, lenders"),
    "cost to income": ("(cost_to_income * 100)", "%, lenders"),
    "credit cost": ("(credit_cost * 100)", "% of avg loans, TTM"),
    "nim": ("(nim_asset_proxy * 100)", "% of avg total assets (proxy), TTM"),
    "roa": ("(roa * 100)", "%, lenders, avg total assets"),
    "gnpa": ("(gnpa_pct * 100)", "% (NULL for NBFCs: not in taxonomy)"),
    "nnpa": ("(nnpa_pct * 100)", "% (NULL for NBFCs: not in taxonomy)"),
    "pcr": ("(pcr * 100)", "% (NULL for NBFCs: not in taxonomy)"),
    "credit to deposit": ("(credit_to_deposit * 100)", "%, banks"),
    "cet1": ("(cet1_pct * 100)", "%, banks (standalone, filed)"),
    "at1": ("(at1_pct * 100)", "%, banks (standalone, filed)"),
    "roa filed": ("(roa_filed * 100)", "%, as filed (annualisation varies by bank)"),
    "government holding": ("(govt_holding_pct * 100)", "%, banks (PSU marker)"),
    "claims ratio": ("(claims_ratio * 100)", "%, general insurers (basis in insurer_basis)"),
    "expense ratio": ("(expense_ratio * 100)", "%, insurers"),
    "combined ratio": ("(combined_ratio * 100)", "%, general insurers (IRDAI and Ind AS 117 bases differ)"),
    "solvency ratio": ("solvency_ratio", "x (times)"),
    "net premium earned": ("(net_premium_earned_ttm / 10000000)", "INR crore, TTM"),
    "insurance revenue": ("(insurance_revenue_ttm / 10000000)", "INR crore, TTM, Ind AS 117"),
    "investment income": ("(investment_income_ttm / 10000000)", "INR crore, TTM, insurers"),
    "persistency 13m": ("(persistency_13m * 100)", "%, life insurers"),
    "persistency 61m": ("(persistency_61m * 100)", "%, life insurers"),
    "sloan accrual": ("(sloan_accrual * 100)", "% of avg total assets"),
    "cfo to ebitda": ("(cfo_to_ebitda * 100)", "%"),
    "fcf to pat": ("(fcf_to_pat * 100)", "%"),
    "working capital intensity": ("(working_capital_intensity * 100)", "% of TTM revenue"),
    "receivables sales divergence": ("(receivables_sales_divergence * 100)", "percentage points (needs 8 quarters)"),
    "net debt to fcf": ("net_debt_to_fcf", "years"),
    "cost of debt": ("(cost_of_debt * 100)", "%"),
    "effective cost of debt": ("(cost_of_debt * 100)", "%"),
    "degree of operating leverage": ("dol", "x (needs 8 quarters, |revenue change| >= 5%)"),
    "unlevered fcf yield": ("(fcff_yield * 100)", "% of EV"),
    "dol": ("dol", "x (needs 8 quarters, |revenue change| >= 5%)"),
    "gross ebitda spread": ("(gross_ebitda_spread * 100)", "percentage points"),
    "reverse dcf growth": ("(reverse_dcf_implied_g * 100)", "% p.a. FCFF growth implied (WACC 12%, terminal 4%)"),
    "pe percentile": ("(pe_percentile * 100)", "percentile of own quarterly history (>= 4 quarters)"),
    "ev to ebitda percentile": ("(ev_ebitda_percentile * 100)", "percentile of own quarterly history (>= 4 quarters)"),
    "new gen tech": ("CAST(valuation_archetype = 'NEW_GEN_TECH' AS INTEGER)", "1/0"),
    "ev to gross profit": ("ev_to_gross_profit", "x"),
    "ex cash pe": ("ex_cash_pe", "x"),
    "ev to billings": ("ev_to_billings", "x"),
    "ev to esop adjusted ebitda": ("ev_to_esop_adj_ebitda", "x"),
    "price to cfo": ("price_to_cfo", "x"),
    "rule of 40": ("(rule_of_40 * 100)", "% (needs 8 quarters)"),
    "billings growth": ("(billings_growth_pct * 100)", "% YoY (needs 8 quarters)"),
    "working capital float": ("(neg_working_capital_float_pct * 100)", "% of TTM revenue"),
    "net burn multiple": ("net_burn_multiple", "x (cash burners, needs 8 quarters)"),
    "cash runway": ("cash_runway_months", "months (cash burners)"),
    "esop adjusted fcf": ("(esop_adj_fcf / 10000000)", "INR crore"),
    "liquid cash": ("(liquid_cash / 10000000)", "INR crore"),
    "qoq sales": ("(sales_growth_qoq_pct * 100)", "% latest quarter vs previous quarter"),
    "sales growth qoq": ("(sales_growth_qoq_pct * 100)", "% latest quarter vs previous quarter"),
    "qoq profits": ("(profit_growth_qoq_pct * 100)", "% owners' profit, latest quarter vs previous (base > 0)"),
    "profit growth qoq": ("(profit_growth_qoq_pct * 100)", "% owners' profit, latest quarter vs previous (base > 0)"),
    "npm": ("(npm_pct * 100)", "% TTM owners' profit / TTM sales"),
    "net profit margin": ("(npm_pct * 100)", "% TTM owners' profit / TTM sales"),
    "interest coverage": ("interest_coverage", "x TTM (PBT + finance costs) / finance costs (not for lenders)"),
    "interest coverage ratio": ("interest_coverage", "x TTM (PBT + finance costs) / finance costs (not for lenders)"),
    "dividend yield": ("(dividend_yield_pct * 100)", "% trailing 365 days of ex-dates / close"),
    "dividend payout": ("(dividend_payout_pct * 100)", "% trailing dividends per share / EPS TTM"),
    "change in promoter holding": ("promoter_holding_change_qoq_pp", "percentage points, QoQ"),
    "promoter holding qoq change": ("promoter_holding_change_qoq_pp", "percentage points, QoQ"),
    # batch B (price/technicals): adjusted closes unless noted; NULL until the window's bars exist [C9]
    "return over 1day": ("(return_1d * 100)", "%"),
    "return 1d": ("(return_1d * 100)", "%"),
    "return over 1week": ("(return_1w * 100)", "% (5 bars)"),
    "return 1w": ("(return_1w * 100)", "% (5 bars)"),
    "return over 1month": ("(return_1m * 100)", "% (21 bars)"),
    "return over 3months": ("(return_3m * 100)", "% (63 bars)"),
    "return over 6months": ("(return_6m * 100)", "% (126 bars)"),
    "return over 1year": ("(return_12m * 100)", "% (252 bars)"),
    "return over 3years": ("(return_3y * 100)", "% cumulative, not annualised (756 bars)"),
    "return over 5years": ("(return_5y * 100)", "% cumulative, not annualised (1,260 bars)"),
    "return over 7years": ("(return_7y * 100)", "% cumulative, not annualised (1,764 bars)"),
    "return over 10years": ("(return_10y * 100)", "% cumulative, not annualised (2,520 bars)"),
    "volume": ("volume", "shares traded today"),
    "volume 1week average": ("volume_1w_avg", "shares/day, adjusted, 5 bars"),
    "volume 1month average": ("volume_1m_avg", "shares/day, adjusted, 21 bars"),
    "volume 1year average": ("volume_1y_avg", "shares/day, adjusted, 252 bars"),
    "high price": ("high_52w", "INR, 52-week high of adjusted closes"),
    "low price": ("low_52w", "INR, 52-week low of adjusted closes"),
    "52w high": ("high_52w", "INR, adjusted closes"),
    "52w low": ("low_52w", "INR, adjusted closes"),
    "distance from 52w low": ("(dist_52w_low * 100)", "% (>= 0)"),
    "high since data start": ("high_since_data_start", "INR, adjusted, since 2024-10-01 (not all-time)"),
    "low since data start": ("low_since_data_start", "INR, adjusted, since 2024-10-01 (not all-time)"),
    "dma 50": ("dma50", "INR"),
    "dma 200": ("dma200", "INR"),
    "dma 50 previous day": ("dma50_prev", "INR"),
    "dma 200 previous day": ("dma200_prev", "INR"),
    "rsi": ("rsi_14", "0-100, Wilder 14"),
    "rsi previous day": ("rsi_14_prev", "0-100, Wilder 14"),
    "macd": ("macd", "INR, EMA12 - EMA26"),
    "macd signal": ("macd_signal", "INR, EMA9 of MACD"),
    "macd previous day": ("macd_prev", "INR"),
    "macd signal previous day": ("macd_signal_prev", "INR"),
    "atr": ("(atr_14_pct * 100)", "% of close, Wilder 14"),
    "relative strength 3m": ("(rs_nifty500_3m * 100)", "percentage points vs Nifty 500"),
    "relative strength 6m": ("(rs_nifty500_6m * 100)", "percentage points vs Nifty 500"),
    "relative strength 12m": ("(rs_nifty500_12m * 100)", "percentage points vs Nifty 500"),
    "beta": ("beta_1y_nifty500", "x vs Nifty 500, 1 year of daily log returns"),
    "median traded value 20d": ("(turnover_median_20d / 10000000)", "INR crore/day"),
    "delivery percentage": ("(deliv_pct * 100)", "% of today's volume"),
    "delivery percentage 20d": ("(deliv_pct_avg_20d * 100)", "%, mean of 20 days"),
    "vwap": ("vwap", "INR, today"),
    "vwap 20d": ("vwap_20d", "INR, adjusted"),
}


def _yyyymmdd(column: str) -> str:
    return f"CAST(strftime({column}, '%Y%m%d') AS INTEGER)"


# Batch 0: aliases for built columns that had none (ratio catalogue C2).
ALIASES.update(
    {
        "shares": ("shares", "count (Reg. 31 total, else paid-up / face value)"),
        "number of equity shares": ("shares", "count (Reg. 31 total, else paid-up / face value)"),
        "restatement suspected": (
            "CAST(restatement_suspected AS INTEGER)",
            "1/0 (X106 YTD break in the TTM; X108 discontinued ops, X109 merger in 5 quarters)",
        ),
        "non promoter non public holding": ("(non_promoter_non_public_pct * 100)", "% (employee trusts, DRs)"),
        "annual fy end": (_yyyymmdd("annual_fy_end"), "YYYYMMDD, fiscal year of the annual ratios"),
        "fundamentals end": (_yyyymmdd("fundamentals_end"), "YYYYMMDD, latest quarter end of the TTM window"),
        "balance sheet date": (_yyyymmdd("bs_as_of"), "YYYYMMDD"),
        "cash flow date": (_yyyymmdd("cf_as_of"), "YYYYMMDD"),
        "shareholding date": (_yyyymmdd("shp_as_of"), "YYYYMMDD, Reg. 31 as-of"),
        "price date": (_yyyymmdd("price_date"), "YYYYMMDD, last bar on/before the as-of"),
        "loans": ("(loans / 10000000)", "INR crore, lenders"),
        "reverse dcf wacc": ("(reverse_dcf_wacc_used * 100)", "% used by reverse dcf growth"),
        "reverse dcf terminal growth": ("(reverse_dcf_terminal_g * 100)", "% used by reverse dcf growth"),
        "consolidated": ("CAST(scope_used = 'CONSOLIDATED' AS INTEGER)", "1/0, scope of this row's fundamentals"),
        "trade to trade": ("CAST(is_trade_to_trade AS INTEGER)", "1/0, series BE or BZ (M6)"),
        "is trade to trade": ("CAST(is_trade_to_trade AS INTEGER)", "1/0, series BE or BZ (M6)"),
    }
)


def _period_aliases() -> dict[str, tuple[str, str]]:
    """Batch 1 (period P&L family, features_pl): Screener's names, e.g. "Sales latest quarter", "Net profit preceding
    year quarter", "OPM last year", "Sales growth 3Years". Money in INR crore, ratios in %."""
    lines = {"sales": ["sales"], "operating_profit": ["operating profit"], "other_income": ["other income"],
             "depreciation": ["depreciation"], "ebit": ["ebit"], "interest": ["interest"],
             "pbt": ["profit before tax", "pbt"], "tax": ["tax"], "pat": ["profit after tax", "pat"],
             "net_profit": ["net profit"],
             "exceptional_items": ["extraordinary items", "exceptional items"]}  # fmt: skip
    periods = {"latest_quarter": ["latest quarter"], "preceding_quarter": ["preceding quarter"],
               "preceding_year_quarter": ["preceding year quarter"],
               "2quarters_back": ["2quarters back", "2 quarters back"],
               "3quarters_back": ["3quarters back", "3 quarters back"],
               "last_year": ["last year"], "preceding_year": ["preceding year"]}  # fmt: skip
    from financials.features_pl import EPS_COLUMNS, EQUITY_CAPITAL_COLUMNS, MARGIN_COLUMNS, MONEY_COLUMNS

    out: dict[str, tuple[str, str]] = {}
    for line, names in lines.items():
        for period, pnames in periods.items():
            if f"{line}_{period}" in MONEY_COLUMNS:
                for n in names:
                    for pn in pnames:
                        out[f"{n} {pn}"] = (f"({line}_{period} / 10000000)", f"INR crore, {pn}")
    for period, pnames in periods.items():
        for pn in pnames:
            if f"eps_{period}" in EPS_COLUMNS:
                out[f"eps {pn}"] = (f"eps_{period}", f"INR per share, filed, today's share basis, {pn}")
            if f"equity_capital_{period}" in EQUITY_CAPITAL_COLUMNS:
                out[f"equity capital {pn}"] = (f"(equity_capital_{period} / 10000000)", f"INR crore, {pn}")
            for m in ("opm", "npm", "gpm"):
                if f"{m}_{period}_pct" in (*MARGIN_COLUMNS, "opm_last_year_pct", "opm_preceding_year_quarter_pct"):
                    out[f"{m} {pn}"] = (f"({m}_{period}_pct * 100)", f"%, {pn}")
    out["opm same quarter last year"] = ("(opm_preceding_year_quarter_pct * 100)", "%, the pre-4A 'opm last year'")
    for name in ("yoy quarterly sales growth", "quarterly sales growth yoy"):
        out[name] = ("(sales_growth_yoy_quarter_pct * 100)", "% latest quarter vs same quarter last year")
    for name in ("yoy quarterly profit growth", "quarterly profit growth yoy"):
        out[name] = ("(profit_growth_yoy_quarter_pct * 100)", "% owners' profit, latest quarter vs same quarter LY")
    out["operating profit growth"] = ("(operating_profit_growth_yoy_quarter_pct * 100)",
                                      "% EBITDA, latest quarter vs same quarter last year")  # fmt: skip
    for name in ("sales ttm 1year back", "sales preceding 12months", "sales preceding 12 months"):
        out[name] = ("(sales_ttm_1y_back / 10000000)", "INR crore, TTM ending a year before the latest quarter")
    for n in (3, 5, 7, 10):
        for key, names in (("sales", ["sales"]), ("profit", ["profit"]), ("eps", ["eps"]),
                           ("operating_profit", ["operating profit", "ebitda"])):  # fmt: skip
            for name in names:
                for y in (f"{n}years", f"{n} years"):
                    out[f"{name} growth {y}"] = (f"({key}_growth_{n}y_pct * 100)", f"% FY CAGR over {n} years")
    for n in (5, 10):
        for y in (f"{n}years", f"{n} years"):
            out[f"sales growth {y} median"] = (f"(sales_growth_median_{n}y_pct * 100)", "% median yearly FY growth")
        for y in (f"{n}year", f"{n}years", f"{n} years"):
            out[f"average earnings {y}"] = (f"(avg_earnings_{n}y / 10000000)", "INR crore, mean FY owners' profit")
            out[f"average ebit {y}"] = (f"(avg_ebit_{n}y / 10000000)", "INR crore, mean FY EBIT")
            out[f"opm {y}"] = (f"(opm_{n}y_pct * 100)", f"% mean FY OPM over {n} years")
    out["last result date"] = (_yyyymmdd("last_result_date"), "YYYYMMDD (IST), latest quarter's results")
    out["last annual result date"] = (_yyyymmdd("last_annual_result_date"), "YYYYMMDD (IST), latest FY results")
    out["days since last result"] = ("date_diff('day', last_result_date, as_of_date)", "days")
    return out


ALIASES.update(_period_aliases())


def _balance_sheet_aliases() -> dict[str, tuple[str, str]]:
    """Batches 2-3 (balance sheet, working capital, cash flow, capital allocation): features_bs.dsl_aliases."""
    from financials.features_bs import dsl_aliases

    return dsl_aliases()


ALIASES.update(_balance_sheet_aliases())
ALIASES["ev to ebitda percentile 20q"] = ("(ev_ebitda_percentile_20q * 100)", "percentile of the last 20 quarter-ends")
ALIASES["roa"] = ("(roa * 100)", "%, TTM owners' profit / avg total assets (lenders: TTM to the quarter end)")


def _gem_aliases() -> dict[str, tuple[str, str]]:
    """Batch D (features_gems): ownership (ratio catalogue Batch 5, Screener's names) and the hidden-gem signals,
    flags, ranks and hats of docs/hidden_gems.md. Fractions are shown x100; booleans as 1/0 (NULL when unknown)."""
    from financials.features_gems import HATS

    pp = "percentage points"
    out: dict[str, tuple[str, str]] = {
        "change in fii holding": ("(fii_holding_change_qoq_pct * 100)", f"{pp}, QoQ (adjacent quarters)"),
        "change in dii holding": ("(dii_holding_change_qoq_pct * 100)", f"{pp}, QoQ (adjacent quarters)"),
        "institutional holding": ("(inst_holding_pct * 100)", "%, FII + DII"),
        "inst holding": ("(inst_holding_pct * 100)", "%, FII + DII"),
        "change in institutional holding": ("(fii_dii_qoq_change_pct * 100)", f"{pp}, FII + DII QoQ"),
        "unpledged promoter holding": ("(unpledged_promoter_holding_pct * 100)", "%, promoter x (1 - pledged share)"),
        "mf holding": ("(mf_holding_pct * 100)", "%, mutual funds / UTI"),
        "mutual fund holding": ("(mf_holding_pct * 100)", "%, mutual funds / UTI"),
        "change in mf holding": ("(mf_holding_change_qoq_pct * 100)", f"{pp}, QoQ"),
        "insurance holding": ("(insurance_holding_pct * 100)", "%, insurance companies"),
        "retail holding": ("(retail_holding_pct * 100)", "%, resident individuals up to Rs 2 lakh"),
        "number of shareholders": ("num_shareholders", "count, latest Reg. 31"),
        "number of shareholders preceding quarter": ("num_shareholders_preceding_quarter", "count"),
        "number of shareholders 1year back": ("num_shareholders_1y_back", "count, Reg. 31 12 months earlier"),
        "change in number of shareholders": ("(num_shareholders_change_qoq_pct * 100)", "% QoQ"),
        "sales yoy latest quarter": ("(sales_growth_yoy_quarter_pct * 100)", "% vs same quarter last year"),
        "sales yoy preceding quarter": ("(sales_growth_yoy_preceding_quarter_pct * 100)", "% vs a year earlier"),
        "profit yoy latest quarter": ("(profit_growth_yoy_quarter_pct * 100)", "% owners' profit vs a year earlier"),
        "profit yoy preceding quarter": ("(profit_growth_yoy_preceding_quarter_pct * 100)", "% owners' profit"),
        "core profit latest quarter": ("(core_profit_latest_quarter / 10000000)", "INR crore, PBT - OI - exceptional"),
        "core profit growth": ("(core_profit_yoy_latest_q * 100)", "% YoY, latest quarter (PBT - OI - exceptional)"),
        "core profit yoy latest quarter": ("(core_profit_yoy_latest_q * 100)", "% YoY, latest quarter"),
        "core profit yoy preceding quarter": ("(core_profit_yoy_preceding_q * 100)", "% YoY, preceding quarter"),
        "other income lift": ("(other_income_lift_pp * 100)", f"{pp}, profit YoY - core profit YoY"),
        "pe core": ("pe_core", "x, market cap / TTM core profit after tax (owners)"),
        "core pe": ("pe_core", "x, market cap / TTM core profit after tax (owners)"),
        "growth sustained": ("CAST(growth_sustained AS INTEGER)", "1/0, sales YoY >= 12% in both quarters"),
        "growth acceleration": ("(growth_acceleration_pp * 100)", f"{pp}, sales YoY latest - preceding quarter"),
        "opm change yoy": ("(opm_change_yoy_pp * 100)", f"{pp}, quarter OPM vs same quarter last year"),
        "operating leverage": ("operating_leverage", "x, core profit YoY / sales YoY"),
        "peg": ("peg", "x, pe core / core profit growth"),
        "earnings yield": ("(earnings_yield * 100)", "%, TTM EBIT / EV"),
        "magic formula rank": ("magic_formula_rank", "1 = best, gated non-financial universe of the day"),
        "under owned": ("CAST(under_owned AS INTEGER)", "1/0, inst <= 15%, promoter >= 50%, no pledge"),
        "cyclical": ("CAST(cyclical_flag AS INTEGER)", "1/0, Metals & Mining, Oil Gas, curated shipping"),
        "forensic clean": ("CAST(forensic_clean AS INTEGER)", "1/0, no measured red flag"),
        "cash conversion ok": ("CAST(cash_conversion_ok AS INTEGER)", "1/0, CFO / EBITDA >= 0.7"),
        "capex pay off signal": ("CAST(capex_pay_off_signal AS INTEGER)", "1/0, CWIP / gross block >= 25%, ..."),
        "roce stability 5years": ("roce_stability_5y", "1 - std / mean of 5 FY ROCE (NULL until FY29)"),
        "opm stability 5years": ("opm_stability_5y", "1 - std / mean of 5 FY OPM (NULL until FY29)"),
        "pe vs own 5year median": ("pe_vs_own_5y_median", "x (NULL until 2029-10)"),
        "pe core universe median": ("pe_core_universe_median", "x, the day's gated non-financial universe"),
        "market cap universe median": ("(market_cap_universe_median / 10000000)", "INR crore, same universe"),
        "gem score": ("gem_score", "z-score blend (docs/hidden_gems.md)"),
        "hats passed": ("hats_passed", "count of hidden-gem screens passed"),
        "financial": ("CAST(valuation_archetype IN ('FINANCIAL_LENDING', 'INSURANCE') AS INTEGER)",
                      "1/0, lender or insurer"),
        "lender": ("CAST(valuation_archetype = 'FINANCIAL_LENDING' AS INTEGER)", "1/0"),
        "piotroski known": ("CAST(piotroski_f IS NOT NULL AS INTEGER)", "1/0"),
        "gnpa known": ("CAST(gnpa_pct IS NOT NULL AS INTEGER)", "1/0"),
    }  # fmt: skip
    for h in HATS:
        out[f"hat {h.replace('_', ' ')}"] = (f"CAST(hat_{h} AS INTEGER)", "1/0, docs/hidden_gems.md section B")
    return out


ALIASES.update(_gem_aliases())


def _peer_aliases() -> dict[str, tuple[str, str]]:
    """Batch H (features_peers, C25): NSE industry / basic-industry medians, premiums and peer ranks (Screener's
    "Industry PE" / "Industry PBV"); the Nifty 500 industry-group fallback keeps its own names."""
    out: dict[str, tuple[str, str]] = {
        "industry pe": ("industry_pe_median", "median PE (> 0) of the NSE industry, >= 3 companies"),
        "industry pbv": ("industry_pb_median", "median PB (> 0) of the NSE industry"),
        "industry roce": ("(industry_roce_median * 100)", "%, median ROCE of the NSE industry"),
        "industry sales growth": ("(industry_sales_growth_median * 100)", "%, median sales growth YoY"),
        "basic industry pe": ("basic_industry_pe_median", "median PE (> 0) of the NSE basic industry"),
        "basic industry pbv": ("basic_industry_pb_median", "median PB (> 0) of the NSE basic industry"),
        "basic industry roce": ("(basic_industry_roce_median * 100)", "%"),
        "basic industry sales growth": ("(basic_industry_sales_growth_median * 100)", "%"),
        "pe premium to industry": ("(pe_premium_to_industry * 100)", "%, PE / industry median - 1 (< 0 = discount)"),
        "pbv premium to industry": ("(pb_premium_to_industry * 100)", "%"),
        "pe premium to basic industry": ("(pe_premium_to_basic_industry * 100)", "%"),
        "pbv premium to basic industry": ("(pb_premium_to_basic_industry * 100)", "%"),
        "peer count": ("peer_count", "companies in the NSE basic industry"),
        "peer rank market cap": ("peer_rank_market_cap", "1 = largest in the basic industry"),
        "peer rank pe": ("peer_rank_pe", "1 = lowest PE (> 0)"),
        "peer rank roce": ("peer_rank_roce", "1 = highest ROCE"),
        "peer rank profit growth": ("peer_rank_profit_growth", "1 = highest quarterly profit growth YoY"),
        "industry group pe": ("industry_group_pe_median", "median PE over the Nifty 500 file's industry group"),
        "industry group pbv": ("industry_group_pb_median", "median PB over the Nifty 500 file's industry group"),
    }  # fmt: skip
    return out


ALIASES.update(_peer_aliases())


def _extra_aliases() -> dict[str, tuple[str, str]]:
    """Batch G (remaining Phase 2 ratios): features_extra.dsl_aliases."""
    from financials.features_extra import dsl_aliases

    return dsl_aliases()


ALIASES.update(_extra_aliases())


def _more_aliases() -> dict[str, tuple[str, str]]:
    """Batch I (last catalogue rows): features_more.dsl_aliases."""
    from financials.features_more import dsl_aliases

    return dsl_aliases()


ALIASES.update(_more_aliases())


def _rpt_aliases() -> dict[str, tuple[str, str]]:
    """Batch J (related-party leak): features_rpt.dsl_aliases."""
    from financials.features_rpt import dsl_aliases

    return dsl_aliases()


ALIASES.update(_rpt_aliases())


def _disclosure_aliases() -> dict[str, tuple[str, str]]:
    """Batch 18D (disclosure_facts: insider receivables, subsidiary contribution): features_disclosures.dsl_aliases."""
    from financials.features_disclosures import dsl_aliases

    return dsl_aliases()


ALIASES.update(_disclosure_aliases())


def _audit_aliases() -> dict[str, tuple[str, str]]:
    """Batch 20A (audit opinions from the report text, X121): features_audit.dsl_aliases."""
    from financials.features_audit import dsl_aliases

    return dsl_aliases()


ALIASES.update(_audit_aliases())


def _dq_aliases() -> dict[str, tuple[str, str]]:
    """X325 (rule SHOW_AND_FLAG, owner decision V): screens include flagged rows by default; `Data Suspect = 0`
    excludes them, `Data Flag <code> = 1` keeps only rows carrying one code (code words lower-case, spaces for
    underscores and the colon, e.g. "Data Flag Open Finding Ytd Quarter Mismatch"). Missing flags read as 0."""
    from financials.features import DQ_CODES, DQ_FINDING_REASONS

    out = {
        "data suspect": ("CAST(coalesce(dq_suspect, FALSE) AS INTEGER)", "1/0, any data-quality flag (X325)"),
        "data open finding": (
            "CAST(coalesce(dq_flags LIKE '%OPEN_FINDING:%', FALSE) AS INTEGER)",
            "1/0, an open finding concerns the row's window (X325)",
        ),
    }
    for code in (*DQ_CODES, *(f"OPEN_FINDING:{r}" for r in DQ_FINDING_REASONS)):
        name = "data flag " + code.lower().replace("_", " ").replace(":", " ")
        out[name] = (
            f"CAST(coalesce(list_contains(string_split(dq_flags, ','), '{code}'), FALSE) AS INTEGER)",
            f"1/0, row flagged {code} (X325)",
        )
    return out


ALIASES.update(_dq_aliases())

KEYWORDS = {"and", "or", "not"}
COMPARATORS = {"<", "<=", ">", ">=", "=", "!="}
NAME_RE = re.compile(r"^[a-z][a-z0-9 ]{0,62}$")


class DslError(ValueError):
    pass


# ── tokens ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Tok:
    kind: str  # NUM | NAME | OP | KW | END
    text: str
    pos: int


_TOKEN = re.compile(
    r"\s*(?:(?P<num>\d+(?:\.\d+)?)(?![A-Za-z0-9_%])|(?P<op><=|>=|!=|[<>=+\-*/()])|(?P<word>[A-Za-z0-9_%]+))"
)


def tokenize(text: str) -> list[Tok]:
    if len(text) > 2000:
        raise DslError("query too long")
    toks: list[Tok] = []
    pos = 0
    while pos < len(text):
        if text[pos:].strip() == "":
            break
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise DslError(f"unexpected character {text[pos:].lstrip()[:1]!r} at {pos}")
        if m.group("num") and toks and toks[-1].kind == "NAME":  # "in nifty 500": a number ends an alias
            prev = toks.pop()
            toks.append(Tok("NAME", f"{prev.text} {m.group('num')}", prev.pos))
        elif m.group("num"):
            toks.append(Tok("NUM", m.group("num"), m.start("num")))
        elif m.group("op"):
            toks.append(Tok("OP", m.group("op"), m.start("op")))
        else:
            w = m.group("word")
            if w.lower() in KEYWORDS:
                toks.append(Tok("KW", w.lower(), m.start("word")))
            elif toks and toks[-1].kind == "NAME":  # multi-word alias
                prev = toks.pop()
                toks.append(Tok("NAME", f"{prev.text} {w}", prev.pos))
            else:
                toks.append(Tok("NAME", w, m.start("word")))
        pos = m.end()
    toks.append(Tok("END", "", len(text)))
    return toks


# ── AST ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Num:
    value: Decimal


@dataclass(frozen=True)
class Ref:
    name: str  # normalised alias


@dataclass(frozen=True)
class Neg:
    operand: object


@dataclass(frozen=True)
class Bin:
    op: str
    left: object
    right: object


@dataclass(frozen=True)
class Cmp:
    op: str
    left: object
    right: object


@dataclass(frozen=True)
class Bool:
    op: str  # and | or
    left: object
    right: object


@dataclass(frozen=True)
class Not:
    operand: object


def normalise(name: str) -> str:
    return " ".join(name.lower().split())


class _Parser:
    def __init__(self, text: str) -> None:
        self.toks = tokenize(text)
        self.i = 0

    def peek(self) -> Tok:
        return self.toks[self.i]

    def take(self, kind: str | None = None, text: str | None = None) -> Tok:
        t = self.peek()
        if (kind and t.kind != kind) or (text and t.text != text):
            want = text or kind
            raise DslError(f"expected {want} at {t.pos}, found {t.text or 'end of query'!r}")
        self.i += 1
        return t

    def done(self) -> None:
        if self.peek().kind != "END":
            raise DslError(f"unexpected {self.peek().text!r} at {self.peek().pos}")

    # boolean level
    def or_expr(self):
        node = self.and_expr()
        while self.peek().kind == "KW" and self.peek().text == "or":
            self.take()
            node = Bool("or", node, self.and_expr())
        return node

    def and_expr(self):
        node = self.not_expr()
        while self.peek().kind == "KW" and self.peek().text == "and":
            self.take()
            node = Bool("and", node, self.not_expr())
        return node

    def not_expr(self):
        t = self.peek()
        if t.kind == "KW" and t.text == "not":
            self.take()
            return Not(self.not_expr())
        if t.kind == "OP" and t.text == "(" and self._paren_is_boolean():
            self.take()
            node = self.or_expr()
            self.take("OP", ")")
            return node
        left = self.arith()
        op = self.peek()
        if op.kind != "OP" or op.text not in COMPARATORS:
            raise DslError(f"expected a comparison at {op.pos}")
        self.take()
        return Cmp(op.text, left, self.arith())

    def _paren_is_boolean(self) -> bool:
        """Does the parenthesis opened here contain a comparison/keyword at its own depth?"""
        depth = 0
        for t in self.toks[self.i :]:
            if t.kind == "OP" and t.text == "(":
                depth += 1
            elif t.kind == "OP" and t.text == ")":
                depth -= 1
                if depth == 0:
                    return False
            elif depth == 1 and (t.kind == "KW" or (t.kind == "OP" and t.text in COMPARATORS)):
                return True
        return False

    # arithmetic level
    def arith(self):
        node = self.term()
        while self.peek().kind == "OP" and self.peek().text in "+-":
            op = self.take().text
            node = Bin(op, node, self.term())
        return node

    def term(self):
        node = self.factor()
        while self.peek().kind == "OP" and self.peek().text in "*/":
            op = self.take().text
            node = Bin(op, node, self.factor())
        return node

    def factor(self):
        t = self.peek()
        if t.kind == "NUM":
            self.take()
            return Num(Decimal(t.text))
        if t.kind == "NAME":
            self.take()
            return Ref(normalise(t.text))
        if t.kind == "OP" and t.text == "(":
            self.take()
            node = self.arith()
            self.take("OP", ")")
            return node
        if t.kind == "OP" and t.text == "-":
            self.take()
            return Neg(self.factor())
        raise DslError(f"expected a number or metric at {t.pos}, found {t.text or 'end of query'!r}")


def parse_query(text: str):
    p = _Parser(text)
    node = p.or_expr()
    p.done()
    return node


def parse_arith(text: str):
    p = _Parser(text)
    node = p.arith()
    p.done()
    return node


# ── compilation ─────────────────────────────────────────────────────────


class Compiler:
    def __init__(self, custom: dict[str, str] | None = None) -> None:
        self.custom = {normalise(k): v for k, v in (custom or {}).items()}
        self.params: list[Decimal] = []
        self.refs: set[str] = set()
        self._stack: list[str] = []

    def compile(self, node) -> str:
        if isinstance(node, Num):
            self.params.append(node.value)
            return "?"
        if isinstance(node, Ref):
            return self._ref(node.name)
        if isinstance(node, Neg):
            return f"(-{self.compile(node.operand)})"
        if isinstance(node, Bin):
            left, right = self.compile(node.left), self.compile(node.right)
            if node.op == "/":
                return f"({left} / NULLIF({right}, 0))"
            return f"({left} {node.op} {right})"
        if isinstance(node, Cmp):
            op = "<>" if node.op == "!=" else node.op
            return f"({self.compile(node.left)} {op} {self.compile(node.right)})"
        if isinstance(node, Bool):
            return f"({self.compile(node.left)} {node.op.upper()} {self.compile(node.right)})"
        if isinstance(node, Not):
            return f"(NOT {self.compile(node.operand)})"  # NULL stays NULL: missing data never passes
        raise DslError(f"unsupported node {node!r}")

    def _ref(self, name: str) -> str:
        if name in ALIASES:
            self.refs.add(name)
            return ALIASES[name][0]
        if name in self.custom:
            if name in self._stack:
                raise DslError(f"custom ratio cycle: {' -> '.join([*self._stack, name])}")
            self._stack.append(name)
            try:
                return f"({self.compile(parse_arith(self.custom[name]))})"
            finally:
                self._stack.pop()
        close = [a for a in ALIASES if a.startswith(name.split()[0])][:5]
        hint = f"; did you mean {', '.join(close)}?" if close else ""
        raise DslError(f"unknown metric {name!r}{hint}")


def load_custom_ratios(con) -> dict[str, str]:
    return dict(con.execute("SELECT name, expression FROM user_custom_ratios").fetchall())


def save_custom_ratio(con, name: str, expression: str) -> None:
    key = normalise(name)
    if not NAME_RE.match(key) or key in KEYWORDS or key.split()[0] in KEYWORDS:
        raise DslError(f"invalid custom ratio name {name!r}")
    if key in ALIASES:
        raise DslError(f"{name!r} is a built-in metric")
    custom = {**load_custom_ratios(con), key: expression}
    Compiler(custom).compile(Ref(key))  # validates syntax, metrics and cycles
    con.execute("INSERT OR REPLACE INTO user_custom_ratios VALUES (?, ?, ?)", [key, expression, utc_now()])


@dataclass
class CompiledScreen:
    where_sql: str
    params: list[Decimal]
    metrics: list[str]


def compile_screen(query: str, custom: dict[str, str] | None = None) -> CompiledScreen:
    node = parse_query(query)
    c = Compiler(custom)
    where = c.compile(node)
    return CompiledScreen(where, c.params, sorted(c.refs))


def compile_columns(columns: list[str], custom: dict[str, str] | None = None) -> list[tuple[str, str, list[Decimal]]]:
    """Output columns (M1): each a DSL arithmetic expression (an alias, a saved custom ratio, or arithmetic over them),
    compiled like a filter operand. Returns (label, SQL, params); the label is the normalised expression text."""
    out = []
    for text in columns:
        if not text.strip():
            continue
        c = Compiler(custom)
        out.append((normalise(text), c.compile(parse_arith(text)), c.params))
    return out


def split_columns(text: str | None) -> list[str]:
    """`--columns "Sales latest quarter, OPM last year, Sales / Market cap"`: the grammar has no commas."""
    return [c.strip() for c in (text or "").split(",") if c.strip()]


def run_screen(
    con,
    query: str,
    as_of: date | None = None,
    limit: int = 500,
    *,
    columns: list[str] | None = None,
    order_by: str | None = None,
    descending: bool = False,
) -> list[dict]:
    """Run against the live table, or point-in-time against history when `as_of` is given. Each match carries the
    metrics the query references plus `columns` (DSL expressions, custom ratios allowed); `order_by` (an expression)
    sorts the matches, NULLs last, then by symbol."""
    custom = load_custom_ratios(con)
    cs = compile_screen(query, custom)
    extra_cols = [(m, ALIASES[m][0], []) for m in cs.metrics]
    seen = set(cs.metrics)
    for label, sql, params in compile_columns(columns or [], custom):
        if label not in seen:
            seen.add(label)
            extra_cols.append((label, sql, params))
    select_params = [p for _, _, ps in extra_cols for p in ps]
    extra = ", ".join(f'{sql} AS "{label}"' for label, sql, _ in extra_cols)
    # X325: every match shows its data-quality flags (a database not yet upgraded has none to show)
    table = "screener_features" if as_of is None else "screener_features_history"
    dq = ", dq_suspect, dq_flags" if "dq_flags" in table_columns(con, table) else ""
    select = "as_of_date, symbol, series, close" + dq + (f", {extra}" if extra else "")
    order, order_params = "symbol", []
    if order_by:
        ((_, order_sql, order_params),) = compile_columns([order_by], custom)
        order = f"{order_sql} {'DESC' if descending else 'ASC'} NULLS LAST, symbol"
    if as_of is None:
        sql = f"SELECT {select} FROM screener_features WHERE {cs.where_sql} ORDER BY {order} LIMIT {int(limit)}"
        params = [*select_params, *cs.params, *order_params]
    else:
        sql = (
            f"SELECT {select} FROM screener_features_history WHERE as_of_date = ? AND {cs.where_sql} "
            f"ORDER BY {order} LIMIT {int(limit)}"
        )
        params = [*select_params, as_of, *cs.params, *order_params]
    cur = con.execute(sql, params)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]


# ── saved screens (docs/hidden_gems.md section B; reference/saved_screens.csv) ─────────────────────────────────────


@dataclass(frozen=True)
class SavedScreen:
    name: str
    hat_column: str  # the features_gems hat boolean computing the same rule ("" if none)
    expression: str
    order_by: str
    descending: bool
    limit: int
    description: str


def load_saved_screens() -> dict[str, SavedScreen]:
    """The curated saved screens, keyed by normalised name (reference/saved_screens.csv, a reviewed file)."""
    import csv

    from financials.sources import ROOT

    with (ROOT / "reference" / "saved_screens.csv").open(encoding="utf-8") as fh:
        return {
            normalise(r["name"]): SavedScreen(normalise(r["name"]), r["hat_column"], r["expression"], r["order_by"],
                                              r["descending"] == "1", int(r["limit"]), r["description"])
            for r in csv.DictReader(fh)
        }  # fmt: skip


def run_saved_screen(
    con, name: str, as_of: date | None = None, *, columns: list[str] | None = None, limit: int | None = None
) -> list[dict]:
    """Run a saved screen with its own order and limit (`limit` overrides); the order-by expression is also returned
    as a column."""
    screens = load_saved_screens()
    key = normalise(name)
    if key not in screens:
        raise DslError(f"unknown saved screen {name!r}; saved: {', '.join(sorted(screens))}")
    s = screens[key]
    n = s.limit if limit is None else limit
    return run_screen(con, s.expression, as_of, n, columns=[s.order_by, *(columns or [])], order_by=s.order_by,
                      descending=s.descending)  # fmt: skip
