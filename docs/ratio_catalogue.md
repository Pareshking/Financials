# Ratio catalogue: Screener gallery + owner PDF vs what we can build (2026-11-15)

Inputs: the Screener.in ratio-gallery names the owner pasted (2026-11-15), the text of `docs/inputs/Aligning_Financial_Results_Databases.pdf` + `docs/owner_requirements.md`
(G-numbers), `src/financials/features.py`, `db/schema.sql` (`screener_features`, 142 columns), `dsl.py` (ALIASES),
`fundamentals.py` (`building_blocks`, `annual_ratios`, `screener_convention_ratios`), `parsers/indas_corp.py`
(`DURATION_TAGS`, `INSTANT_TAGS`), `parsers/reg34_annual.py`, `parsers/shareholding.py`, `docs/tag_registry.yaml`
(zero-drop `li_<element>` keys, C24), `config/data_sources.yaml` (F01-F29), `docs/references.md`, `docs/architecture.md` §8-10.
Read-only survey; nothing was run against the DB. Tag names below were grepped, not guessed.

## 0. Conventions and the C9 calendar

**Status values** (column 5 of every table):

| Status | Meaning |
|---|---|
| BUILT | a `screener_features` column exists (named) |
| IN PROGRESS | being added now by another agent (the e085eb5 columns are BUILT since; none open at 2026-11-15 batch A) |
| BUILDABLE NOW | every input is already promoted (`fact_observations` curated or `li_` tags, `ohlcv`, `index_ohlcv`, `shareholding_*`, `corp_actions`, `corporate_events`, `filing_meta`, `raw_index_snapshot`) and the window fits after the cutoff today |
| WHEN HISTORY | the formula is buildable but its window reaches before C9; NULL via `min_periods_required` until the date given |
| NEEDS PARSER | *(extra status, used sparingly)* the source is already vaulted (raw XBRL in the vault blob, as filed in `disclosure_facts`) but the axis/element is not mapped to a canonical fact; needs a fixture-pinned rule, no new source |
| NEW FREE SOURCE | needs a feed we do not ingest; its `data_sources.yaml` status is given |
| NOT POSSIBLE | forecast, proprietary/undisclosed, not disclosed in any free filing, or excluded by decision (C7/C9) |

**Our conventions** (architecture §8, §10; apply to every row): money is `Decimal` rupees (DSL divides by 1e7 for crore);
ratios stored as DOUBLE fractions, DSL multiplies by 100. Profit for PE / EPS / ROE = owners' profit
(`COALESCE(pat_owners, pat)` per filing before TTM; PE and EPS on continuing owners' profit, C10). `rev_ops` = revenue −
labelled excise (X40). `ebitda` = PBEIT + finance costs + D&A − other income (Screener "Operating profit"); `ebit` =
ebitda − D&A. TTM = 4 same-scope quarters (`FactBook.ttm`), else the H1/FY YTD bridge; YoY on TTM needs 8 quarters;
never mix scopes or `period_months`. Balance sheets are filed H1 (Sep) and FY (Mar) only (`bs_as_of`); cash flow H1/FY
(`cf_as_of`, YTD bridge). Annual notes (gross block, contingent liabilities, exports, audit fees, investments quoted /
unquoted, advance from customers) exist only in Reg. 34 annual XBRL (F07, X69-X76). Denominator ≤ 0 or NULL → NULL.
Financial archetypes (lenders, insurers) get NULL for industrial ratios (G245).

"Q" = quarter, "FY" = 12-month period. "last year" = latest FY visible at as-of; "preceding year" = the FY before it.

**C9 calendar** (`scope.py`: `MIN_TRADE_DATE = 2024-10-01`, `MIN_PERIOD_END_DATE = 2025-03-31`). Today = 2026-11-15;
latest results visible = Q2 FY27 (Sep 2026); latest FY = FY26; FY25 exists from the Q4 FY25 Integrated Filing (12M
context) and Reg. 34 FY25/FY26 comparatives. Due dates assumed: Q1-Q3 results within 45 days, Q4 within 60 days
(→ "by end-May"), Reg. 31 within 21 days, Reg. 34 annual XBRL with the annual report (~Aug-Sep).

| Window | First computable | Why |
|---|---|---|
| Price window of N trading days | 1Y (252 bars) since ~2025-10; 3Y ~2027-10; 5Y ~2029-10; 7Y ~2031-10; 10Y ~2034-10 | bars from 2024-10-01 |
| Quarter vs same quarter last year, QoQ, 2-3 quarters back | now | Sep-2025 and Jun-2025 quarters are in scope |
| TTM (4 quarters) | continuous from TTM Dec-2025 (Q3 FY26, ~Feb 2026); TTM Mar-2025 = FY25 directly | first in-scope quarter = Jan-Mar 2025 |
| TTM YoY (8 quarters) — `sales_growth_yoy`, `profit_growth_yoy` | TTM Dec-2026 → Q3 FY27 results, ~mid-Feb 2027 (NULL today: oldest quarter for Sep-2026 would be Dec-2024) | `yoy_growth` + `quarters_available_since(end, 8)` |
| TTM-YoY acceleration (9 quarters) | TTM Mar-2027 → ~end-May 2027 | |
| FY vs FY (1Y) | now (FY26 vs FY25) | |
| N-year CAGR on FY (FY25 base) | 3Y: FY28 ~end-May 2028; 5Y: FY30 ~May 2030; 7Y: FY32 ~May 2032; 10Y: FY35 ~May 2035 | NB: `fundamentals.cagr` is TTM-on-TTM with `4*(years+1)` quarters, which would wait until TTM Dec-2028 (~Feb 2029) for 3Y; pass `min_periods_required=13` at an FY end (FY25 resolves via `ttm_from_ytd`) to get May 2028 |
| Average of N FY values (flows or closing balances) | 3Y: FY25-FY27 ~May 2027; 5Y: ~May 2029; 7Y: ~May 2031; 10Y: ~May 2034 | |
| Average of N FY ratios on **average** balances (ROIC, Screener ROCE) | 3Y: FY26-FY28 ~May 2028; 5Y ~May 2030 | FY25 needs the Mar-2024 balance sheet |
| Value "N years back" (FY) | 3Y back ~May 2028; 5Y ~May 2030; 7Y ~May 2032; 10Y ~May 2035 (Reg. 34-only items ~Sep of those years) | |
| Reg. 31 change over N years | 3Y: SHP Mar-2028 ~Apr 2028; 5Y ~Apr 2030 | first SHP as-of 2025-03-31 |
| Market cap / shares N years back | 3Y ~Apr 2028; 5Y ~Apr 2030; 7Y ~2032; 10Y ~2035 | first visible share count ~Apr 2025 (Reg. 31 / PAID_UP) |
| Quarter-end valuation band of 20 quarters | quarter-end 2030-12-31 | continuous quarter-end PE / EV/EBITDA from 2026-03-31 |

★ = in Screener's "Most used" list. G-numbers from `docs/owner_requirements.md`.

---

# Part A. Screener ratio gallery (deduplicated into families)

## A1. Price, valuation and per-share (Most used + Ratios)

| ID | Name (Screener variants) | Family | Definition (our tags) | Status | Data / notes |
|---|---|---|---|---|---|
| A1.1 | ★ Current price | price | last close on/before as-of | BUILT | `close`, `price_date` |
| A1.2 | ★ Market Capitalization | valuation | close × shares (Reg. 31 total, else paid-up / FV) | BUILT | `market_cap` |
| A1.3 | ★ Enterprise Value | valuation | mcap + net debt (incl. leases) + NCI | BUILT | `enterprise_value` |
| A1.4 | ★ Price to Earning (G110, G167) | valuation | mcap / TTM continuing owners' profit | BUILT | `pe` |
| A1.5 | ★ Price to book value | valuation | mcap / owners' equity (latest H1/FY BS) | BUILT | `pb` |
| A1.6 | ★ EVEBITDA | valuation | EV / TTM ebitda | BUILT | `ev_ebitda` |
| A1.7 | ★ Price to Sales | valuation | mcap / TTM rev_ops | BUILT | `price_to_sales` (batch G) |
| A1.8 | ★ Price to Free Cash Flow | valuation | mcap / TTM fcf (CFO − capex, H1/FY bridge) | BUILT | `price_to_fcf` (mcap / `fcf_ttm`; NULL when FCF ≤ 0); batch C |
| A1.9 | ★ Earnings yield | valuation | TTM ebit / EV (Greenblatt form; Screener's exact formula UNVERIFIED) | BUILT | `earnings_yield` (batch D, features_gems: TTM `ebit` / `enterprise_value`, NULL if EV <= 0 or lender); DSL `earnings yield` |
| A1.10 | ★ Dividend yield (G169) | valuation | TTM cash dividends per share (ex-date in last 365 days) / close | BUILT | `dividend_yield_pct`; `corp_actions` DIVIDEND `cash_per_share` |
| A1.11 | ★ PEG Ratio (G168) | valuation | PE / (3Y EPS CAGR × 100) | BUILT | `peg` (batch D) = `pe_core` / (100 x core profit growth): the latest quarter's YoY now, TTM-on-TTM once 8 quarters exist (hidden_gems.md principle 6, catalogue G168). Screener's 3Y EPS-CAGR form is `PE / EPS growth 3Years` in the DSL once FY28 exists (~May 2028) |
| A1.12 | Price to Quarterly Earning | valuation | mcap / (4 × latest quarter continuing owners' profit) (definition UNVERIFIED) | BUILDABLE NOW | `FactBook.quarter(continuing_owners)` |
| A1.13 | Book value (per share) | per-share | owners' equity / shares | BUILT | `book_value_per_share` (owners' equity, fallback total equity / `shares`); DSL `book value` now per share, `net worth` = total equity in Rs Cr (batch A) |
| A1.14 | ★ EPS | per-share | TTM owners' profit / current shares | BUILT | `eps_ttm` (+ `eps_continuing_ttm`) |
| A1.15 | Number of equity shares | per-share | Reg. 31 total (else paid-up / FV) | BUILT | `shares` (DSL `shares`, `number of equity shares`) |
| A1.16 | Number of equity shares preceding year | per-share | shares at as-of − 1 year, split/bonus-adjusted by `eps_factor` | BUILT | `shares_preceding_year` (Reg. 31 pattern exactly 12 months before the latest, today's share basis; Reg. 31 only); batch C |
| A1.17 | Number of equity shares 10years back | per-share | same, 10 years | BUILT | `shares_10y_back` (history-gated, NULL until ~Apr 2035); batch C |
| A1.18 | Face value | per-share | filed FV | BUILT | `face_value` (latest results filing's `face_value_per_share`); batch C |
| A1.19 | ★ Industry PE / Industry PBV | relative | median PE (PB) of peers in the same industry at as-of | BUILT | `industry_pe_median`, `industry_pb_median` (also basic industry and the Nifty 500 industry-group fallback; batch H, features_peers, NSE 4-level classification PIT from its first fetch) |
| A1.20 | Historical PE 3/5/7/10Years | valuation history | average of PE at each FY results date over N FYs (Screener definition UNVERIFIED) | WHEN HISTORY | FY basis: 3Y ~May 2027, 5Y ~May 2029, 7Y ~2031, 10Y ~2034. Daily-median basis: 3Y ~Feb 2029 |
| A1.21 | Historical PBV 3/5/7/10Years | valuation history | same with PB | WHEN HISTORY | as A1.20 (PB exists from ~May 2025) |
| A1.22 | Market Capitalization 3/5/7/10years back | valuation history | mcap at as-of − N years | WHEN HISTORY | ~Apr 2028 / 2030 / 2032 / 2035 |
| A1.23 | Credit rating | credit | latest long-term rating and action | NEW FREE SOURCE | F22 UNVERIFIED (rating announcements are PDF; no XBRL seen). G98 |
| A1.24 | Is SME / Is not SME | universe | series in SM/ST vs EQ/BE/BZ | BUILDABLE NOW | trivial: SME is excluded by C7, so "Is SME" is always 0 in our universe |
| A1.25 | ★ Debt | balance sheet | total_debt = borrowings (non-current + current) + labelled lease liabilities | BUILT | `debt` (latest BS, Screener statement Borrowings incl. leases; a line a filed BS omits = nil, C23); batch C |

## A2. Returns, efficiency, leverage (Most used + Ratios)

| ID | Name (Screener variants) | Family | Definition (our tags) | Status | Data / notes |
|---|---|---|---|---|---|
| A2.1 | ★ Return on equity | returns | TTM owners' profit / closing owners' equity (C16) | BUILT | `roe` (+ `roe_continuing`) |
| A2.2 | ROE preceding year | returns | FY(−1) owners' PAT / closing owners' equity at that FY end | BUILT | `roe_preceding_year` (closing owners' equity, as `roe`); batch C |
| A2.3 | ★ Average return on equity 3/5Years; Average ROE 3/5/7/10Years | returns | mean of FY ROE over N FYs | WHEN HISTORY | ~May 2027 / 2029 / 2031 / 2034 |
| A2.4 | ROE 5years growth | returns | ROE(FY) − ROE(FY−5) (definition UNVERIFIED) | WHEN HISTORY | ~May 2030 |
| A2.5 | ★ Return on capital employed | returns | TTM ebit / closing (equity + debt) | BUILT | `roce`; Screener form (PBT + interest) / avg capital = `roce_screener` |
| A2.6 | ROCE preceding year | returns | FY(−1) ROCE | BUILT | `roce_preceding_year` (FY EBIT / closing debt + total equity, as `roce`); Screener average-capital form not built; batch C |
| A2.7 | Average ROCE 3/5/7/10Years; Median ROCE 3/5/7/10Years | returns | mean / median of FY ROCE | WHEN HISTORY | closing form ~May 2027/2029/2031/2034; `roce_screener` form ~May 2028/2030/2032/2035 |
| A2.8 | ★ Return on assets | returns | TTM owners' PAT / avg total assets (opening = BS 12 months earlier) | BUILT | `roa` now also for industrial books: TTM owners' profit / avg total assets over the 12 months to `bs_as_of` (NULL until the BS 12 months earlier is visible); batch C |
| A2.9 | ROA preceding year | returns | FY(−1) PAT / total assets | BUILT | `roa_preceding_year` (average assets; history-gated, NULL until FY27 ~May 2027); batch C |
| A2.10 | Return on assets 3/5years | returns | mean FY ROA | WHEN HISTORY | ~May 2027 / 2029 |
| A2.11 | Return on invested capital | returns | TTM nopat / avg invested capital | BUILT | `roic` |
| A2.12 | Average ROIC 3/5Years | returns | mean FY ROIC | WHEN HISTORY | average IC → FY26 first → ~May 2028 / 2030 |
| A2.13 | Earning Power | returns | TTM ebit / total assets (Screener definition UNVERIFIED) | BUILT | `earning_power` (TTM EBIT / closing total assets; Screener definition still UNVERIFIED); batch C |
| A2.14 | Graham Number | valuation | √(22.5 × EPS × book value per share), NULL if either ≤ 0 | BUILT | `graham_number`; batch C |
| A2.15 | Piotroski score (G160) | composite | 0..9, FY vs FY | BUILT | `piotroski_f` (FY26 vs FY25 works) |
| A2.16 | G Factor | composite | Screener's formula is undisclosed; the likely basis is Mohanram's G-score (8 binary tests vs industry medians incl. 16-quarter earnings and sales variability) — UNVERIFIED | WHEN HISTORY | variability needs 16 quarters (~Feb 2029) and industry medians (coarse A1.19 only). Do not build until the definition is confirmed |
| A2.17 | Financial leverage | leverage | avg total assets / avg owners' equity (closing form until two BS) | BUILT | `financial_leverage` (average form only; NULL until two balance sheets 12 months apart); batch C |
| A2.18 | Asset Turnover Ratio | efficiency | TTM rev_ops / avg total assets | BUILT | `asset_turnover` (TTM sales to `bs_as_of` / avg total assets); batch C |
| A2.19 | Inventory turnover ratio | efficiency | sales / closing inventory (Screener S22) | BUILT | `inventory_turnover` |
| A2.20 | Inventory turnover 3/5/7/10Years back | efficiency history | FY value N years back | BUILT | `inventory_turnover_{3,5,7,10}y_back` (history-gated, NULL until ~May 2028 / 2030 / 2032 / 2035); batch C |
| A2.21 | Current ratio | liquidity | current_assets / current_liabilities | BUILT | `current_ratio`; batch C |
| A2.22 | Quick ratio | liquidity | (current_assets − inventories) / current_liabilities | BUILT | `quick_ratio`; batch C |
| A2.23 | ★ Debt to equity | leverage | total_debt / total_equity | BUILT | `debt_to_equity` |
| A2.24 | ★ Interest Coverage Ratio (G175) | leverage | TTM ebit (or PBT + finance costs) / TTM finance costs | BUILT | `interest_coverage`. Filed `li_interest_service_coverage_ratio` exists in 38 INDAS_CORP filings (listed-debt issuers only) |
| A2.25 | Debtor days; Days Receivable Outstanding | working capital | closing trade receivables / (FY sales / 365) | BUILT | `debtor_days` |
| A2.26 | Days Inventory Outstanding | working capital | closing inventory / (COGS / 365) | BUILT | `inventory_days` |
| A2.27 | Days Payable Outstanding | working capital | closing trade payables / (COGS / 365) | BUILT | `days_payable` |
| A2.28 | Cash Conversion Cycle | working capital | DSO + DIO − DPO | BUILT | `cash_conversion_cycle` |
| A2.29 | Working Capital Days (G111) | working capital | (CA − cash & bank − current investments − CL) / (sales / 365) | BUILT | `working_capital_days` |
| A2.30 | Average debtor days 3years; Average Working Capital Days 3years | working capital history | mean over FY25-FY27 | BUILT | `avg_debtor_days_3y`, `avg_working_capital_days_3y` (history-gated, NULL until FY27 ~May 2027); batch C |
| A2.31 | Debtor days 3/5years back | working capital history | FY value N years back | BUILT | `debtor_days_{3,5}y_back` (history-gated, NULL until ~May 2028 / 2030); batch C |
| A2.32 | Exports percentage | mix | FY foreign revenue / revenue (Reg. 34 `GeographicalAreasAxis`, `revenue_foreign`; alternative `li_export_turnover_goods_gross` + `li_export_revenue_services`, 12 and 7 filings) | BUILT | `exports_pct` (foreign / (domestic + foreign) by geography, Reg. 34); the `li_export_*` alternative not used; batch C |
| A2.33 | Exports percentage 3/5Years back | mix history |  | BUILT | `exports_pct_{3,5}y_back` (history-gated, NULL until ~Sep 2028 / 2030); batch C |
| A2.34 | OPM 5Year / 10Year | margin history | mean FY OPM | BUILT | `opm_5y_pct`, `opm_10y_pct` (history-gated: NULL until FY29 ~May 2029 / FY34 ~May 2034) |
| A2.35 | Average 5years dividend | payout history | mean FY dividend (rupees) over 5 FYs | WHEN HISTORY | ~May 2029 (FY basis) / ~Oct 2029 (ex-date basis) |
| A2.36 | Average dividend payout 3years | payout history | mean FY (dividends / owners' PAT) | WHEN HISTORY | ~May 2027 |

## A3. Ownership (Most used + Ratios)

| ID | Name (Screener variants) | Family | Definition (our tags) | Status | Data / notes |
|---|---|---|---|---|---|
| A3.1 | ★ Promoter holding | ownership | Reg. 31 PROMOTER pct | BUILT | `promoter_holding_pct` |
| A3.2 | ★ Change in promoter holding (G178) | ownership | QoQ percentage points | BUILT | `promoter_holding_change_qoq_pp` |
| A3.3 | Change in promoter holding 3Years | ownership history | pp change vs SHP 12 quarters earlier | WHEN HISTORY | ~Apr 2028 |
| A3.4 | ★ Pledged percentage | ownership | pledged / promoter shares | BUILT | `promoter_pledge_pct` (+ `promoter_encumbered_pct`) |
| A3.5 | Unpledged promoter holding | ownership | promoter pct × (1 − pledge pct) | BUILT | `unpledged_promoter_holding_pct` (batch D); 0 without a promoter group |
| A3.6 | Public holding | ownership | PUBLIC pct | BUILT | `public_holding_pct` |
| A3.7 | FII holding; DII holding | ownership | FII / DII pct | BUILT | `fii_holding_pct`, `fpi_holding_pct`, `dii_holding_pct` |
| A3.8 | Change in FII holding; Change in DII holding | ownership | QoQ pp, each separately | BUILT | `fii_holding_change_qoq_pct`, `dii_holding_change_qoq_pct` (batch D; fraction points, adjacent quarters only); combined `fii_dii_qoq_change_pct` |
| A3.9 | Change in FII holding 3Years; Change in DII holding 3Years | ownership history | | WHEN HISTORY | ~Apr 2028 |
| A3.10 | Number of Shareholders | ownership | TOTAL `holders` | BUILT | `num_shareholders` (batch D; TOTAL `NumberOfShareholders` [SHP19]) |
| A3.11 | Number of Shareholders preceding quarter; 1year back | ownership | same, previous SHP / SHP 4 quarters back | BUILT | `num_shareholders_preceding_quarter` (adjacent quarter), `num_shareholders_1y_back` (pattern exactly 12 months earlier), `num_shareholders_change_qoq_pct` (batch D) |

## A4. Annual P&L family ("last year" = latest FY, "preceding year" = FY before; growth windows)

All FY lines read the 12-month period (Q4 Integrated Filing FY context; superseded by Reg. 34 annual when visible, G294).
Screener's annual rows come from annual reports and can differ from the sum of quarters (S13); ours are as filed.

| ID | Name (Screener variants) | Family | Definition (our tags) | Status | Data / notes |
|---|---|---|---|---|---|
| A4.1 | ★ Sales (TTM) | P&L TTM | TTM rev_ops | BUILT | `sales_ttm` |
| A4.2 | ★ Profit after tax (TTM); Net profit | P&L TTM | TTM pat (total, incl. NCI); owners' share via `pat_owners` | BUILT | `pat_ttm` (DSL `net profit` = total PAT; owners' TTM not a column) |
| A4.3 | ★ OPM (TTM) | margin | TTM ebitda / rev_ops | BUILT | `opm` |
| A4.4 | Sales last/preceding year | P&L FY | FY rev_ops | BUILT | `sales_last_year`, `sales_preceding_year` (features_pl) |
| A4.5 | Operating profit last/preceding year | P&L FY | FY ebitda | BUILT | `operating_profit_last_year`, `operating_profit_preceding_year` |
| A4.6 | Other income last/preceding year | P&L FY | FY `other_income` (Screener adds exceptional items to OI, S2; we keep them separate) | BUILT | `other_income_last_year`, `other_income_preceding_year` (exceptional items kept separate) |
| A4.7 | EBIDT last/preceding year | P&L FY | FY ebitda + other_income (= PBEIT + finance costs + D&A) | BUILT | DSL `EBIDT last year` / `EBIDT preceding year` = operating_profit + other_income (alias only, batch G) |
| A4.8 | Depreciation last/preceding year | P&L FY | `depreciation_amortisation` | BUILT | `depreciation_last_year`, `depreciation_preceding_year` |
| A4.9 | EBIT last/preceding year | P&L FY | FY ebit | BUILT | `ebit_last_year`, `ebit_preceding_year` |
| A4.10 | Interest last/preceding year | P&L FY | `finance_costs` | BUILT | `interest_last_year`, `interest_preceding_year` |
| A4.11 | Profit before tax last/preceding year | P&L FY | `pbt` (or `pbt_incl_jv`, X102) | BUILT | `pbt_last_year`, `pbt_preceding_year` (filed PBT) |
| A4.12 | Tax last/preceding year; Current Tax | P&L FY | `tax_expense`; `current_tax` | BUILT | `tax_last_year`, `tax_preceding_year` (`tax_expense`; current tax alone not built); X94 withholding applies |
| A4.13 | Profit after tax last/preceding year | P&L FY | `pat` | BUILT | `pat_last_year`, `pat_preceding_year` |
| A4.14 | Extraordinary items last/preceding year | P&L FY | `exceptional_items` | BUILT | `exceptional_items_last_year`, `exceptional_items_preceding_year` |
| A4.15 | Net Profit last/preceding year | P&L FY | owners' profit `COALESCE(pat_owners, pat)` | BUILT | `net_profit_last_year`, `net_profit_preceding_year` |
| A4.16 | Minority share last/preceding year | P&L FY | `pat_nci` | BUILT | `minority_share_last_year`, `minority_share_preceding_year` (batch G) |
| A4.17 | Dividend last/preceding year | P&L FY | dividends paid in FY (`dividends_paid`, CF) or proposed (`li_amount_of_dividends_proposed_to_be_distributed_to_equity_shareholders`, Reg. 34) | BUILT | `dividends_paid_last_year`, `_preceding_year`: cash-flow dividends paid (nil when the FY cash flow omits the line; batch G) |
| A4.18 | Material cost last/preceding year | P&L FY | cogs = materials + purchases + Δinventories | BUILT | `material_cost_last_year`, `_preceding_year` (batch G) |
| A4.19 | Employee cost last/preceding year | P&L FY | `employee_benefit_expense` | BUILT | `employee_cost_last_year`, `_preceding_year` (batch G) |
| A4.20 | OPM last year | margin FY | FY ebitda / FY rev_ops | BUILT | `opm_last_year_pct` (FY since features 2026.11.15-4A; the same-quarter form is `opm_preceding_year_quarter_pct`) |
| A4.21 | OPM preceding year | margin FY | FY(−1) | BUILT | `opm_preceding_year_pct` |
| A4.22 | NPM (TTM) | margin | TTM pat / TTM rev_ops | BUILT | `npm_pct` |
| A4.23 | NPM last/preceding year | margin FY | FY net profit / FY sales | BUILT | `npm_last_year_pct`, `npm_preceding_year_pct` (owners' profit / sales) |
| A4.24 | EPS last/preceding year | per-share FY | filed FY `eps_basic` (or FY owners' PAT / adjusted shares) | BUILT | `eps_last_year`, `eps_preceding_year`: filed FY basic EPS × EPS factors of share-count actions ex after it was visible |
| A4.25 | TTM Result Date; Last annual result date | dates | `visible_from_ts` of the filing that completes the TTM window / of the latest FY | BUILT | `last_annual_result_date` (first visibility of the latest FY's 12-month figures, IST); the latest quarter's in `last_result_date` (A5.21). A separate "TTM result date" is not built: it equals `last_result_date` whenever the TTM window ends at the latest quarter |
| A4.26 | ★ Sales growth; ★ Profit growth | growth | TTM vs TTM a year earlier | BUILT | `sales_growth_yoy`, `profit_growth_yoy`: **NULL for everyone until TTM Dec-2026 (~mid-Feb 2027)**. FY26/FY25 growth (A4.28) fills the gap |
| A4.27 | Sales preceding 12months; Sales TTM 1year back; Net profit preceding 12months | P&L TTM history | TTM ending 12 months before the latest TTM | BUILT | `sales_ttm_1y_back` (history-gated: NULL until TTM Dec-2025 is complete, ~mid-Feb 2027, except where an FY-end bridge exists); net profit form not built |
| A4.28 | Sales / profit growth last year (FY YoY) | growth | FY26 / FY25 − 1 | BUILT | DSL `Sales growth last year`, `Profit growth last year` (alias over the FY lines, NULL when the base <= 0; batch G) |
| A4.29 | ★ Sales growth 3/5Years; Sales growth 7/10Years | growth | FY CAGR | BUILT | `sales_growth_{3,5,7,10}y_pct` (history-gated: `fundamentals.cagr(min_periods_required = 4 × years + 1)` at the FY end; 3Y ~May 2028, 5Y ~May 2030, 7Y ~May 2032, 10Y ~May 2035) |
| A4.30 | ★ Profit growth 3/5Years; 7/10Years | growth | FY owners' PAT CAGR (NULL if either end ≤ 0) | BUILT | `profit_growth_{3,5,7,10}y_pct` (owners' profit; history-gated, same dates) |
| A4.31 | EBIDT growth 3/5/7/10Years | growth | FY EBIDT CAGR | WHEN HISTORY | same dates. The EBITDA (operating profit) form is built, history-gated, as `operating_profit_growth_{3,5,7,10}y_pct` (DSL `ebitda growth 3years`); the EBIDT form (+ other income) is not |
| A4.32 | EPS growth 3/5/7/10Years (G172) | growth | FY EPS CAGR, EPS adjusted for share-count actions | BUILT | `eps_growth_{3,5,7,10}y_pct` (restated filed FY EPS; history-gated, same dates) |
| A4.33 | Sales growth 5years median / 10years median | growth | median of yearly FY growth rates | BUILT | `sales_growth_median_{5,10}y_pct` (history-gated: ~May 2030 / ~May 2035) |
| A4.34 | Average Earnings 5/10Year; Average EBIT 5/10Year | P&L history | mean FY owners' PAT / ebit | BUILT | `avg_earnings_{5,10}y`, `avg_ebit_{5,10}y` (history-gated: ~May 2029 / ~May 2034) |

## A5. Quarter P&L family (latest quarter, preceding quarter, preceding year quarter, 2 / 3 quarters back)

Quarter values are `FactBook.quarter(tag, end)`: the filed 3-month value, else YTD_k − YTD_k−1 (Q4 = FY − 9M), §6.2.
The period parameter maps to `end` = latest quarter end, −3, −12, −6, −9 months. All five offsets are in scope today
(Sep-2026 back to Sep-2025 needs Mar-2025 as the oldest only for "4 quarters back", which Screener does not ask for).

| ID | Name (Screener variants) | Family | Definition (our tags) | Status | Data / notes |
|---|---|---|---|---|---|
| A5.1 | ★ Sales latest quarter; Sales preceding quarter / preceding year quarter / 2quarters back / 3quarters back | P&L Q | quarter rev_ops | BUILT | `sales_{latest_quarter,preceding_quarter,preceding_year_quarter,2quarters_back,3quarters_back}` |
| A5.2 | Operating profit (same 5 offsets) | P&L Q | quarter ebitda | BUILT | `operating_profit_*` (same 5 offsets) |
| A5.3 | Other income (latest / preceding / preceding year quarter) | P&L Q | `other_income` | BUILT | `other_income_*` (3 offsets) |
| A5.4 | EBIDT (3 offsets) | P&L Q | ebitda + other_income | BUILT | DSL `EBIDT latest quarter` (alias; other offsets expressible as operating profit + other income; batch G) |
| A5.5 | Depreciation (3 offsets) | P&L Q | `depreciation_amortisation` | BUILT | `depreciation_*` |
| A5.6 | EBIT (3 offsets) | P&L Q | ebit | BUILT | `ebit_*` |
| A5.7 | Interest (3 offsets) | P&L Q | `finance_costs` | BUILT | `interest_*` |
| A5.8 | Profit before tax (3 offsets) | P&L Q | `pbt` | BUILT | `pbt_*` |
| A5.9 | Tax (3 offsets) | P&L Q | `tax_expense` | BUILT | `tax_*` |
| A5.10 | ★ Profit after tax latest quarter (+2 offsets) | P&L Q | `pat` | BUILT | `pat_*` (3 offsets) |
| A5.11 | Extraordinary items (3 offsets) | P&L Q | `exceptional_items` | BUILT | `exceptional_items_*` |
| A5.12 | Net Profit (5 offsets incl. 2/3 quarters back) | P&L Q | owners' profit | BUILT | `net_profit_*` (5 offsets) |
| A5.13 | OPM latest / preceding / preceding year quarter | margin Q | quarter ebitda / rev_ops | BUILT | `opm_latest_quarter_pct`, `opm_preceding_quarter_pct`, `opm_preceding_year_quarter_pct` |
| A5.14 | NPM latest / preceding / preceding year quarter | margin Q | quarter net profit / rev_ops | BUILT | `npm_latest_quarter_pct`, `npm_preceding_quarter_pct`, `npm_preceding_year_quarter_pct` |
| A5.15 | GPM latest quarter | margin Q | quarter gross_profit / rev_ops, only when materials + purchases ≥ 10% of revenue (C6) | BUILT | `gpm_latest_quarter_pct` (+ `gpm_last_year_pct`, `gpm_preceding_year_pct`) |
| A5.16 | Equity Capital latest / preceding / preceding year quarter | capital Q | `paid_up_equity_capital` (quarterly P&L footer) | BUILT | `equity_capital_*` (3 offsets; paid-up capital stated in the results) |
| A5.17 | EPS latest / preceding / preceding year quarter | per-share Q | filed quarter `eps_basic` | BUILT | `eps_*` (3 offsets; filed 3-month basic EPS, restated by later EPS factors) |
| A5.18 | ★ YOY Quarterly sales growth; ★ YOY Quarterly profit growth | growth Q | latest quarter / same quarter last year − 1 | BUILT | `sales_growth_yoy_quarter_pct`, `profit_growth_yoy_quarter_pct` (owners; NULL on a base ≤ 0) |
| A5.19 | QoQ sales %, QoQ profit % (owner PDF G173) | growth Q | latest / preceding quarter − 1 | BUILT | `sales_growth_qoq_pct`, `profit_growth_qoq_pct` |
| A5.20 | Operating profit growth | growth Q | quarter ebitda YoY (Screener definition UNVERIFIED: could be TTM) | BUILT | `operating_profit_growth_yoy_quarter_pct` (quarter EBITDA YoY; Screener's definition UNVERIFIED) |
| A5.21 | Last result date | dates | `visible_from_ts` of the latest results filing | BUILT | `last_result_date` (IST date the latest quarter-end results were first visible, row's scope) |
| A5.22 | Expected quarterly sales / operating profit / net profit / EPS / sales growth | forecast | Screener's own projection | NOT POSSIBLE | a forecast with an undisclosed method; no free consensus-estimate source |

## A6. Balance-sheet family

| ID | Name (Screener variants) | Family | Definition (our tags) | Status | Data / notes |
|---|---|---|---|---|---|
| A6.1 | Equity capital | BS | `equity_share_capital` | BUILT | `equity_capital` (latest BS); batch C |
| A6.2 | Preference capital | BS | — | NEEDS PARSER | no curated element; under Ind AS redeemable preference shares sit in borrowings. Class split only on Reg. 34 `ClassesOfEquityShareCapitalAxis` (vaulted, unmapped) |
| A6.3 | Reserves | BS | `other_equity` | BUILT | `reserves` (other equity; banks / insurers reserves and surplus); batch C |
| A6.4 | Secured loan; Unsecured loan | BS | borrowings by security | NEEDS PARSER | Reg. 34 `ClassificationOfBorrowingsAxis` / `ClassificationOfAssetsBasedOnSecurityAxis` are in the registry (axes) but not mapped; no flat element |
| A6.5 | Balance sheet total; Total Assets | BS | `total_assets` | BUILT | `balance_sheet_total` (Screener statement total, DTA netted against DTL, S10); batch C |
| A6.6 | Gross block | BS (annual) | `ppe_gross_block` | BUILT | `gross_block` (Reg. 34 at the last FY end); batch C |
| A6.7 | Accumulated depreciation | BS (annual) | `ppe_accumulated_depreciation` | BUILT | `accumulated_depreciation`; batch C |
| A6.8 | Net block | BS | `ppe_net` (+ `other_intangibles` if Screener includes them; S10 decides) | BUILT | `net_block` (Screener statement Net Block: PPE + investment property + goodwill + intangibles + ROU); batch C |
| A6.9 | Capital work in progress | BS | `cwip` | BUILT | `cwip` (incl. intangibles under development); batch C |
| A6.10 | Investments | BS | non-current + current + equity-method | BUILT | `investments`; batch C |
| A6.11 | Current assets; Current liabilities | BS | `current_assets`, `current_liabilities` | BUILT | `current_assets`, `current_liabilities`; batch C |
| A6.12 | Book value of unquoted investments | BS (annual) | `li_aggregate_amount_of_unquoted_noncurrent_investments` + `…_current_investments` | BUILT | `unquoted_investments` (batch G) |
| A6.13 | Market value of quoted investments | BS (annual) | `li_market_value_of_quoted_noncurrent_investments` + `…_current_investments` | BUILT | `quoted_investments_market_value` (batch G) |
| A6.14 | Revaluation reserve | BS (annual) | `li_property_plant_and_equipment_revaluation_surplus` | BUILT | `revaluation_reserve` (batch G; usually NULL) |
| A6.15 | Contingent liabilities | BS (annual) | `contingent_liabilities` (else `contingent_liabilities_and_commitments`) | BUILT | `contingent_liabilities` (excl. commitments, at the last FY end); batch C |
| A6.16 | Working capital | BS | Screener: Other Assets − Other Liabilities | BUILT | `working_capital` |
| A6.17 | Lease liabilities | BS | `lease_liabilities_current` + `_noncurrent` (label rules, X39/X72) | BUILT | `lease_liabilities`; batch C |
| A6.18 | Inventory; Trade receivables; Trade Payables; Cash Equivalents | BS | `inventories`; `trade_receivables_current` (+ noncurrent); `trade_payables_current` (+ noncurrent); `cash_and_equivalents` | BUILT | `inventory`, `trade_receivables`, `trade_payables` (current + non-current), `cash_equivalents`; batch C |
| A6.19 | Advance from Customers | BS (annual) | `advance_from_customers` | BUILT | `advance_from_customers` (Reg. 34 at the last FY end); batch C |
| A6.20 | Debt / Working capital / Net block / Gross block / CWIP preceding year | BS history | value at the previous FY end | BUILT | `debt_`, `working_capital_`, `net_block_`, `gross_block_`, `cwip_preceding_year`, `debt_to_equity_preceding_year` (end of the FY before the last FY); batch C |
| A6.21 | Working capital / Debt / Net block 3/5/7/10Years back | BS history | FY value N years back | BUILT | `debt_`, `working_capital_`, `net_block_{3,5,7,10}y_back` (history-gated, NULL until ~May 2028 / 2030 / 2032 / 2035); batch C |
| A6.22 | Book value 3/5/10years back | BS history | owners' equity per share N years back | BUILT | `book_value_{3,5,10}y_back` (owners' equity / Reg. 31 shares at that FY end; history-gated, NULL until ~May 2028 / 2030 / 2035); batch C |
| A6.23 | Book value preceding year | BS history | FY(−1) owners' equity per share | BUILT | `book_value_preceding_year` (owners' equity / Reg. 31 shares at that FY end, today's share basis); batch C |

## A7. Cash-flow family (last year / preceding year; multi-year sums)

| ID | Name (Screener variants) | Family | Definition (our tags) | Status | Data / notes |
|---|---|---|---|---|---|
| A7.1 | Cash from operations last/preceding year | CF FY | FY `cfo` | BUILT | `cfo_last_year`, `cfo_preceding_year`; batch C |
| A7.2 | Cash from investing last/preceding year | CF FY | FY `cfi` | BUILT | `cfi_last_year`, `cfi_preceding_year`; batch C |
| A7.3 | Cash from financing last/preceding year | CF FY | FY `cff` | BUILT | `cff_last_year`, `cff_preceding_year`; batch C |
| A7.4 | Net cash flow last/preceding year | CF FY | `net_cash_flow` (before FX) or `net_cash_flow_after_fx` | BUILT | `net_cash_flow_last_year`, `_preceding_year` (after FX, S12); batch C |
| A7.5 | Cash end of last/preceding year | CF FY | `cash_cf_statement` at FY end | BUILT | `cash_end_last_year`, `_preceding_year`; batch C |
| A7.6 | Cash beginning of last/preceding year | CF FY | prior FY-end `cash_cf_statement`; for FY25 derive as cash end − `net_cash_flow_after_fx` (the Mar-2024 instant is pre-cutoff) | BUILT | `cash_beginning_last_year`, `_preceding_year` (identity for FY25: equals TCS's filed, out-of-scope Mar-2024 cash); batch C |
| A7.7 | Free cash flow last/preceding year | CF FY | FY cfo − (capex_ppe + capex_intangibles) | BUILT | `fcf_last_year`, `fcf_preceding_year`; batch C |
| A7.8 | CFO to EBITDA last/preceding year | CF FY | FY cfo / FY ebitda | BUILT | `cfo_to_ebitda_last_year`, `_preceding_year` (post-tax CFO / EBITDA; the TTM `cfo_to_ebitda` is pre-tax); batch C |
| A7.9 | Free cash flow / Operating cash flow / Investing cash flow 3/5/7/10years | CF history | sum over N FYs | BUILT | `fcf_`, `cfo_`, `cfi_{3,5,7,10}y` (history-gated, NULL until ~May 2027 / 2029 / 2031 / 2034); batch C |
| A7.10 | Cash 3/5/7Years back | CF history | FY-end cash N years back | BUILT | `cash_{3,5,7}y_back` (history-gated, NULL until ~May 2028 / 2030 / 2032); batch C |

## A8. Price and technicals family

Adjusted closes = `ohlcv.close` × backward `price_factor` (splits, bonuses, rights, demergers; never dividends).
GAP-frozen securities return NULL (existing `_momentum` rule).

| ID | Name (Screener variants) | Family | Definition (our tags) | Status | Data / notes |
|---|---|---|---|---|---|
| A8.1 | Return over 1day / 1week | returns | adj close / close 1 / 5 bars back − 1 | BUILT | `return_1d`, `return_1w` (batch B) |
| A8.2 | Return over 1month / ★3months / ★6months / ★1year | returns | 21 / 63 / 126 / 252 bars | BUILT | `return_1m/3m/6m/12m` |
| A8.3 | ★ Return over 3years | returns | 756 bars, cumulative (not annualised) | WHEN HISTORY | ~Oct 2027; column `return_3y` built (batch B), NULL until then |
| A8.4 | ★ Return over 5years; 7years; 10years | returns | 1,260 / 1,764 / 2,520 bars, cumulative | WHEN HISTORY | ~Oct 2029 / ~Oct 2031 / ~Oct 2034; columns `return_5y/7y/10y` built, NULL until then |
| A8.5 | Volume | volume | latest `ohlcv.volume` (no later factor, so as filed) | BUILT | `volume` |
| A8.6 | Volume 1week / 1month / 1year average | volume | mean adjusted volume over 5 / 21 / 252 bars | BUILT | `volume_1w_avg/1m_avg/1y_avg` |
| A8.7 | High price; Low price | price | 52-week high / low of adjusted closes (Screener meaning assumed; day high/low also available) | BUILT | `high_52w`, `low_52w` (DSL `high price` / `low price`), `dist_52w_high`, `dist_52w_low` |
| A8.8 | High price all time; Low price all time | price | — | NOT POSSIBLE | no bars before 2024-10-01 by decision (C9). Proxy built as `high_since_data_start` / `low_since_data_start` (DSL `high since data start`), never labelled all-time |
| A8.9 | DMA 50; DMA 200 | technical | mean adj close over 50 / 200 bars | BUILT | `dma50`, `dma200`; ratio form `price_to_dma50/200` |
| A8.10 | DMA 50 / DMA 200 previous day | technical | same, one bar earlier | BUILT | `dma50_prev`, `dma200_prev`; golden cross: `dma 50 > dma 200 AND dma 50 previous day < dma 200 previous day` |
| A8.11 | RSI (G156) | technical | Wilder RSI(14) on adj closes | BUILT | `rsi_14`, `rsi_14_prev` (15 / 16 bars) |
| A8.12 | MACD; MACD Signal; MACD previous day; MACD Signal previous day | technical | EMA12 − EMA26; EMA9 of MACD (EMAs seeded by an SMA at the first bar; signal from bar 34, previous-day signal from bar 35) | BUILT | `macd`, `macd_signal`, `macd_prev`, `macd_signal_prev` |

---

# Part B. Beyond Screener

Owner-PDF items carry their G-number. Arch 10.2 rule: forensic scores stay separate columns, never summed (G237, G314).

## B1. Quality and forensic

| ID | Name | Family | Definition (our tags) | Status | Data / notes |
|---|---|---|---|---|---|
| B1.1 | Beneish M-score (G161) | forensic | 8-variable | BUILT | `beneish_m` |
| B1.2 | Beneish components DSRI, GMI, AQI, SGI, DEPI, SGAI, LVGI, TATA | forensic | expose the 8 inputs `beneish_m` already computes | BUILT | `beneish_dsri`, `beneish_gmi`, `beneish_aqi`, `beneish_sgi`, `beneish_depi`, `beneish_sgai`, `beneish_lvgi`, `beneish_tata` (batch I, features_more; `fundamentals.beneish_components`, all or none; TCS FY26 rebuilds the pinned −2.3193) |
| B1.3 | Piotroski components (9 binary tests) | forensic | expose the tests behind `piotroski_f` | BUILT | `piotroski_roa_positive` … `piotroski_asset_turnover_up` (9 BOOLEAN, batch I; `fundamentals.piotroski_signals`, their sum = `piotroski_f`) |
| B1.4 | Altman Z'' (G162) | forensic | 4-variable, OtherEquity proxy | BUILT | `altman_z_dd` |
| B1.5 | Altman Z (original, manufacturers) | forensic | 1.2·WC/TA + 1.4·RE/TA + 3.3·EBIT/TA + 0.6·MVE/TL + 1.0·Sales/TA | BUILT | `altman_z_original` (batch I): Z'' inputs + market cap + TTM sales; manufacturer = an industrial book passing the C6 guard (materials + purchases ≥ 10% of sales), else NULL |
| B1.6 | Sloan accrual (G222) | forensic | (TTM PAT − CFO − CFI) / avg TA | BUILT | `sloan_accrual` |
| B1.7 | Balance-sheet accruals (ΔNOA / avg TA) | forensic | Δ(operating assets − operating liabilities) FY26 vs FY25 / avg TA | BUILT | `bs_accruals` (batch I): NOA = equity + debt + leases − liquid cash (`invested_capital_at`), last FY vs preceding FY (TCS FY26 8.23%) |
| B1.8 | CFO / PAT | earnings quality | TTM cfo / TTM pat | BUILT | `cfo_to_pat` on the 12-month cash-flow window (batch G) |
| B1.9 | CFO / EBITDA 3Y; FCF / PAT 3Y (G223, G224) | earnings quality | 3-FY sums | BUILT | `cfo_to_ebitda_3y` (G223), `fcf_conversion_3y` (G224) (history-gated, NULL until FY27 ~May 2027); batch C |
| B1.10 | Receivables vs sales divergence (G225) | forensic | YoY receivables − YoY revenue | BUILT | `receivables_sales_divergence` |
| B1.11 | Cash tax rate | earnings quality | TTM `income_taxes_paid` / TTM `tax_expense` (also vs ETR) | BUILT | `cash_tax_rate`, cash-flow window (batch G) |
| B1.12 | Effective tax rate | earnings quality | TTM tax / PBT (clamped, C5) | BUILT | `effective_tax_rate`, TTM, not clamped (C26; batch G) |
| B1.13 | Other-income dependency (G232) | quality | OI / PBT | BUILT | `other_income_to_pbt` |
| B1.14 | Exceptional-items share | quality | TTM `exceptional_items` / TTM PBT; count of quarters with exceptional ≠ 0 in last 4 | BUILT | `exceptional_to_pbt`, `exceptional_quarters_4q` (batch G) |
| B1.15 | Core profit (G10 spirit) | quality | continuing owners' PAT − exceptional net of tax | BUILT | `core_profit_ttm` |
| B1.16 | Audit qualification flag (G105) | forensic | latest Reg. 34 `auditor_qualified`, Integrated Filing `audit_opinion` | BUILT | `rf_audit_qualified` (batch G) |
| B1.17 | Restatement suspected (X106) | forensic | | BUILT | `restatement_suspected` (no DSL alias) |
| B1.18 | Standalone-to-consolidated profit leakage (G278) | forensic | consolidated owners' PAT − standalone PAT, TTM and as % | BUILT | `standalone_pat_ttm`, `profit_leakage_pct`, `profit_leakage_latest_quarter_pct` (batch G; Reliance Q2 FY27 pinned) |
| B1.19 | RPT intensity (G236, partial) | forensic | `rpt_total_amount` (H1) / H1 revenue | BUILT | `rpt_to_sales` (total / same-period sales, batch G). Per-counterparty split (G236) BUILT in batch J from the Reg. 34 annual schedule [X113, C27]: `rpt_leak_pct`, `rpt_purchases_to_sales`, `rpt_royalty_to_sales`, `rpt_loans_given_to_net_worth`, `rpt_counterparties` |
| B1.20 | Audit fees / revenue; managerial remuneration / PAT | governance | `audit_fees` / revenue; `li_managerial_remuneration` / PAT | BUILT | `audit_fees_to_sales` (a filed 0 → NULL, C26), `managerial_remuneration_to_pat` (batch G) |
| B1.21 | Contingent liabilities / net worth (G235) | fragility | | BUILT | `contingent_liabilities_to_net_worth` |
| B1.22 | Capital commitments / net worth | fragility | `li_estimated_amount_of_contracts_remaining_to_be_executed_on_capital_account_and_not_provided_for` / equity | BUILT | `capital_commitments_to_net_worth` (batch G) |
| B1.23 | Goodwill + intangibles / equity | quality | (`goodwill` + `other_intangibles`) / owners' equity | BUILT | `intangibles_to_equity` (batch G) |
| B1.24 | Filed DSCR / ISCR / D/E (listed-debt issuers) | credit | `li_debt_service_coverage_ratio`, `li_interest_service_coverage_ratio`, `li_debt_equity_ratio` as filed | BUILDABLE NOW | deferred (C26): Tata Motors CV files DSCR −0.0014 / ISCR −0.0181 for Q2 FY26, which no definition reproduces; needs an evidence row before exposing |
| B1.25 | Composite forensic score (G237) | forensic | — | NOT POSSIBLE | excluded by decision (arch 10.2: never summed) |
| B1.26 | Receivables due by insiders (directors, officers, their firms / companies) | forensic | Schedule III note (Reg. 34): directors + other officers + firms / companies subtotal, last FY end; / trade receivables of the same filing | BUILT | 18D (`features_disclosures.py`, X117, C28): `insider_receivables`, `insider_receivables_to_receivables`, `has_insider_receivables`, `insider_receivables_as_of`; `...OrOthers` (includes third parties) never added. DSL `insider receivables` (crore), `insider receivables pct` |

## B2. Capital allocation

| ID | Name | Family | Definition (our tags) | Status | Data / notes |
|---|---|---|---|---|---|
| B2.1 | Dividend payout % (G202) | payout | dividends / owners' PAT | BUILT | `dividend_payout_pct` |
| B2.2 | Shareholder yield (G218, corrected G316) | payout | TTM (`dividends_paid` + `li_payments_to_acquire_or_redeem_entitys_shares` − `share_issue_proceeds`) / mcap | BUILT | `shareholder_yield` (TTM over the CFO bridge's filed periods; a line a filing omits = nil); batch C |
| B2.3 | Buyback yield | payout | TTM buyback cash / mcap | BUILT | `buyback_yield`; batch C |
| B2.4 | Net dilution 1Y | dilution | shares_adj(t) / shares_adj(t−1y) − 1 (Reg. 31, adjusted by `eps_factor`) | BUILT | `dilution_1y` (Reg. 31 both ends, today's share basis); batch C |
| B2.5 | Net dilution 5Y (G219) | dilution | Reg. 31 shares now / the pattern 5 years earlier − 1, today's share basis | BUILT | `dilution_5y` (history-gated, NULL until ~Apr 2030); batch C |
| B2.6 | Reinvestment rate (G216) | reinvestment | FY (capex − D&A + Δ non-cash working capital) / nopat | BUILT | `reinvestment_rate` (FY capex − D&A + Δ non-cash WC, / NOPAT); batch C |
| B2.7 | Incremental ROIC 1Y | reinvestment | Δnopat / Δinvested capital, FY26 vs FY25 | BUILT | `incremental_roic_1y`; batch C |
| B2.8 | Incremental ROIC 3Y / 5Y (G215) | reinvestment |  | BUILT | `incremental_roic_3y`, `incremental_roic_5y` (history-gated, NULL until FY28 / FY30); batch C |
| B2.9 | Incremental asset turnover 3Y (G220) | reinvestment | Δ3y rev_ops / Δ3y net fixed assets | BUILT | `incremental_asset_turnover_3y` (Δ FY sales / Δ net block), NULL until FY28 ~May 2028 (batch G) |
| B2.10 | Capex / depreciation (G226); CWIP / gross block (G227) | reinvestment | | BUILT | `capex_to_depreciation`, `cwip_to_gross_block` |
| B2.11 | Capex intensity | reinvestment | TTM capex / TTM rev_ops | BUILT | `capex_intensity`, cash-flow window (batch G) |
| B2.12 | Depreciation rate; asset age proxy | reinvestment | FY D&A / avg gross block; accumulated depreciation / gross block | BUILT | `depreciation_rate`, `asset_age_proxy` (batch I; TCS FY26 14.54% / 71.86%) |
| B2.13 | CROIC (G217); ROTE (G221) | returns | | BUILT | `croic`, `rote` |
| B2.14 | Net debt / FCF (G233) | leverage |  | BUILT | `net_debt_to_fcf` (TTM) and `net_debt_to_fcf_3y` (mean 3-FY FCF; history-gated, NULL until ~May 2027); batch C |
| B2.15 | Net debt / EBITDA | leverage | net_debt / TTM ebitda | BUILT | `net_debt_to_ebitda`; batch C |
| B2.16 | Effective cost of debt (G234) | leverage | | BUILT | `cost_of_debt` |
| B2.17 | Net cash to market cap (owner PDF custom-ratio example) | valuation | (liquid cash + investments − total_debt) / mcap | BUILT | `net_cash_to_market_cap` = −net debt / mcap (liquid cash = cash + bank + current investments; batch G) |

## B3. Working-capital cycle and cost structure

| ID | Name | Family | Definition (our tags) | Status | Data / notes |
|---|---|---|---|---|---|
| B3.1 | Working-capital intensity (G231); negative WC float (G260) | WC | | BUILT | `working_capital_intensity`, `neg_working_capital_float_pct` |
| B3.2 | Δ CCC / Δ debtor days YoY (FY) | WC | FY26 − FY25 days | BUILT | `debtor_days_change_yoy`, `ccc_change_yoy` (batch I, Screener-convention days of `features_bs._days`) |
| B3.3 | Half-year debtor / inventory days, YoY | WC | on the H1 balance sheet with H1-annualised sales; Sep-2026 vs Sep-2025 | BUILT | `h1_bs_as_of`, `debtor_days_h1`, `inventory_days_h1`, `debtor_days_h1_change_yoy`, `inventory_days_h1_change_yoy` (batch I; YoY from the Sep-2026 H1: the Sep-2025 balance sheet is in scope) |
| B3.4 | Material / employee / other-expense share of revenue (G133) | cost | TTM component / rev_ops | BUILT | `material_cost_`, `employee_cost_`, `other_expenses_{latest_quarter,last_year}_pct` (batch G) |
| B3.5 | Power & fuel, freight share of revenue (G133, G132) | cost | `power_and_fuel`, `freight` / rev_ops | BUILT | `power_fuel_`, `freight_{latest_quarter,last_year}_pct` (batch G; AIA pinned) |
| B3.6 | A&P intensity (G258) | cost | `advertising_promotion` / rev_ops | BUILT | `ad_promo_{latest_quarter,last_year}_pct`, DSL `Ad promo intensity` (batch G; Paytm, Eternal pinned) |
| B3.7 | Marketing efficiency proxy (G256) | cost | YoY Δ quarter revenue / A&P of the same quarter a year earlier | BUILT | `marketing_efficiency_latest_quarter`, `marketing_efficiency_last_year` (FY form pinned on Eternal FY26: 17.3x; batch G) |
| B3.8 | R&D and royalty intensity (G230) | cost | | BUILT | `rnd_and_royalty_intensity` |
| B3.9 | Gross − EBITDA spread (G229); DOL (G228) | operating leverage | | BUILT | `gross_ebitda_spread`, `dol` (DOL needs 8 quarters → ~Feb 2027) |

## B4. Growth and margin acceleration

| ID | Name | Family | Definition (our tags) | Status | Data / notes |
|---|---|---|---|---|---|
| B4.1 | Quarterly YoY sales-growth acceleration (G203, quarter form) | acceleration | YoY(Q) − YoY(Q−1): needs Sep-26, Jun-26, Sep-25, Jun-25 | BUILT | `growth_acceleration_pp` (batch D) |
| B4.2 | TTM YoY sales-growth acceleration (G203, TTM form) | acceleration | TTM YoY now − TTM YoY one quarter earlier (9 quarters) | WHEN HISTORY | ~end-May 2027 |
| B4.3 | OPM expansion vs same quarter last year (G204) | margin delta | OPM(Q) − OPM(Q−4), percentage points | BUILT | `opm_change_yoy_pp` (batch D; fraction points, NULL for lenders) |
| B4.4 | Margin acceleration (G152) | margin delta | [OPM(Q) − OPM(Q−4)] − [OPM(Q−1) − OPM(Q−5)] | BUILT | `opm_acceleration_pp` (batch G) |
| B4.5 | Gross-margin expansion bps YoY (G257) | margin delta | GPM(Q) − GPM(Q−4) | BUILT | `gpm_change_yoy_pp`, DSL `Gross margin expansion bps` (batch G) |
| B4.6 | Profit-growth acceleration (quarter form) | acceleration | as B4.1 on owners' profit (NULL when a base ≤ 0) | BUILT | `profit_growth_acceleration_pp` (batch G) |
| B4.7 | Rule of 40 (G255); billings growth (G259) | growth | | BUILT | `rule_of_40`, `billings_growth_pct` (8 quarters → ~Feb 2027) |
| B4.8 | Consecutive quarters of YoY sales / profit growth | consistency | count of the last k quarters with quarter YoY > 0 | BUILT | `sales_growth_streak_quarters`, `profit_growth_streak_quarters` (max 8; batch G) |
| B4.9 | Sector earnings breadth (G205) | cross-section | share of an industry's companies with quarter YoY PAT > 20% in the current season | BUILT | `industry_earnings_breadth`, `industry_earnings_breadth_n` (batch I, refresh step): share of the NSE industry's companies reporting the industry's latest quarter with core profit YoY > 0 (owner brief for G205), ≥ 3 companies; a per-row column, not a market-level table |
| B4.10 | Earnings surprise vs consensus | forecast | — | NOT POSSIBLE | no free consensus source |

## B5. Valuation vs own history and vs peers

| ID | Name | Family | Definition (our tags) | Status | Data / notes |
|---|---|---|---|---|---|
| B5.1 | PE percentile; EV/EBITDA percentile (G198, G240) | band | vs own prior quarter-end values, ≥ 4 | BUILT | `pe_percentile`, `ev_ebitda_percentile` |
| B5.2 | PB percentile (G198 "P/B band missing") | band | same method on PB | BUILT | `pb_percentile` (batch I; vs own prior quarter-ends, ≥ 4 like `pe_percentile` [C20]) |
| B5.3 | P/S and EV/Sales percentile | band | same method | BUILT | `price_to_sales_percentile`, `ev_to_sales_percentile` (batch I) |
| B5.4 | 5Y (20 quarter-end) valuation band (G240) | band | rank of EV/EBITDA among the last 20 prior quarter-ends, all > 0 | BUILT | `ev_ebitda_percentile_20q` (history-gated, NULL until quarter-end 2030-12-31 is stored, ~2031; PE / PB 20-quarter forms not built); batch C |
| B5.5 | Reverse-DCF implied growth (G200, G239) | valuation | WACC fixed 12% | BUILT | `reverse_dcf_implied_g`; live 10Y G-Sec WACC = NEW FREE SOURCE (F25 PLANNED) |
| B5.6 | EV / Sales | valuation | EV / TTM rev_ops | BUILT | `ev_to_sales` (batch G) |
| B5.7 | Discount / premium to industry median PE, PB, EV/EBITDA (G199) | relative | own / industry median − 1 | BUILT | `pe_premium_to_industry`, `pb_premium_to_industry` (+ `_basic_industry`, `_industry_group`; batch H). An EV/EBITDA premium is not built |
| B5.8 | Peer rank within industry: mcap, PE, ROCE, quarterly profit growth (G112) | relative | percentile rank within industry at as-of | BUILT | `peer_rank_market_cap`, `peer_rank_pe`, `peer_rank_roce`, `peer_rank_profit_growth`, `peer_count` (batch H, NSE basic industry) |
| B5.9 | New-gen ratios (G250-G263) | valuation | | BUILT | `ev_to_gross_profit`, `ex_cash_pe`, `ev_to_billings`, `ev_to_esop_adj_ebitda`, `price_to_cfo`, `net_burn_multiple`, `cash_runway_months`, `esop_adj_fcf` |
| B5.10 | EV / GOV (G265); P/EV (G270) | valuation | EV / `gov`; mcap / `embedded_value` | BUILT | `ev_to_gov` on `gov_ttm` (12-month KPI or 4 quarters), `price_to_embedded_value` (batch G) |
| B5.11 | Equity FCF yield (G170) | valuation | TTM fcf / mcap (inverse of A1.8) | BUILT | `equity_fcf_yield` (signed); unlevered `fcff_yield` BUILT; batch C |

## B6. Price, volume and delivery

| ID | Name | Family | Definition (our tags) | Status | Data / notes |
|---|---|---|---|---|---|
| B6.1 | ATR% (G157) | volatility | Wilder ATR(14) on adjusted OHLC / close | BUILT | `atr_14_pct`; high/low adjusted by the same factors |
| B6.2 | Relative strength vs Nifty 500, 3M / 6M / 12M (G158) | momentum | stock return − Nifty 500 return | BUILT | `rs_nifty500_3m/6m/12m` on `index_ohlcv` (F27, IDX9) price index; NULL until the index closes on both dates are loaded |
| B6.3 | Cross-sectional RS rank (percentile of 12M−1M momentum) | momentum |  | BUILT | `momentum_12m_1m`, `rs_rank_12m_1m` (batch I, refresh step over the day's stored rows; NULL until 253 bars) |
| B6.4 | Beta 1Y vs Nifty 500; volatility 1Y; max drawdown 1Y | risk | daily log returns, 252 bars | BUILT | `beta_1y_nifty500` (batch B), `volatility_1y`, `max_drawdown_1y` (batch I) |
| B6.5 | Distance from 52W low; new-52W-high flag | momentum | | BUILT | `dist_52w_low`; new high = `distance from 52w high = 0` |
| B6.6 | VWAP (daily) and 20D VWAP (G95) | price | `turnover_inr` / `volume` | BUILT | `vwap`, `vwap_20d`; = `AVG_PRICE` of the full bhavcopy (P16) |
| B6.7 | Delivery % (daily, 20D average) (G183) | delivery | `deliv_qty` / `volume` | BUILT | `deliv_pct`, `deliv_pct_avg_20d` (P16); `deliv_avg_5d/20d` are quantities |
| B6.8 | Delivery velocity; float turnover (G159, G242) | delivery | | BUILT | `delivery_velocity`, `float_turnover_pct` |
| B6.9 | 20D median traded value (G207) | liquidity | median `turnover_inr` over 20 bars | BUILT | `turnover_median_20d` |
| B6.10 | Volume spike | volume | volume / 20D average volume | BUILT | DSL `Volume to 1 month average` = volume / `volume_1m_avg` (21 bars, not 20; alias only, batch G) |
| B6.11 | 52W high on > 2× 20D median delivery (G283) | alert | flag | BUILT | `high_52w_on_delivery_spike` (batch I); the alert digest itself waits on owner decision 2 |
| B6.12 | Circuit-lock days; price band (G140, G207) | liquidity | | NEW FREE SOURCE | F20 OBSERVED (no fixture) |
| B6.13 | Market breadth: % Nifty 500 above 50/200 DMA, 52W high/low ratio, A/D (G208) | regime | market-level daily table | BUILT | `market_breadth` (from each materialised day's `in_nifty500` rows) |
| B6.14 | PEAD tracker: abnormal return vs Nifty 500 and relative volume at T+0/1/5/20 after broadcast (G151) | event study |  | BUILT | `pead_event_date`, `pead_ar_t0/1/5/20`, `pead_relvol_t0/1/5/20` (batch I; NULL without the index closes; backtest claims still need TRI, F29 UNVERIFIED) |
| B6.15 | F&O PCR, OI change, max pain (G184, G125) | derivatives | | NEW FREE SOURCE | F16 OBSERVED |
| B6.16 | Short selling, SLBM fee (G103, G128) | derivatives | | NEW FREE SOURCE | F15, F19 OBSERVED |
| B6.17 | ASM / GSM stage; F&O ban; VaR margin (G139, G127, G141) | surveillance | | NEW FREE SOURCE | F20, F18 OBSERVED |

## B7. Ownership flows

| ID | Name | Family | Definition (our tags) | Status | Data / notes |
|---|---|---|---|---|---|
| B7.1 | MF holding %; MF change QoQ | ownership | Reg. 31 MUTUAL_FUNDS category | BUILT | `mf_holding_pct`, `mf_holding_change_qoq_pct` (batch D). The 2022-09-30 SHP taxonomy spells the member `MutualFundsOrUtiMember`, unmapped by the parser: no MF category for Q3 / Q4 FY25 patterns (NEEDS PARSER rule) |
| B7.2 | Insurance / pension / retail (individuals) holding %, QoQ | ownership | category totals from `shareholding_line_items` | BUILT | partial (batch D): `insurance_holding_pct` (`InsuranceCompaniesMember`), `retail_holding_pct` (resident individuals up to Rs 2 lakh) from the latest pattern's line items, SHP18-scaled [SHP19]. Pension funds and the QoQ changes of these two are not built |
| B7.3 | Change in number of shareholders QoQ / YoY | ownership | Δ TOTAL `holders` | BUILT | `num_shareholders_change_qoq_pct` (batch D); YoY from `num_shareholders_1y_back` |
| B7.4 | Pledge / encumbrance change QoQ | ownership | Δ `promoter_pledge_pct`, Δ `promoter_encumbered_pct` | BUILT | `promoter_pledge_change_qoq_pp`, `rf_pledge_increase_qoq` (pledge only; encumbrance change not built; batch G) |
| B7.5 | Quarterly institutional absorption (G241) | ownership flow | Δ(FII + DII shares) QoQ / median 90D volume | BUILT | `inst_shares_change_qoq`, `volume_median_90d`, `institutional_absorption_90d` (batch G) |
| B7.6 | Count of > 1% public holders; named-holder screens (G194, partial) | ownership | `shareholding_major_holders` | BUILT | `public_holders_above_1pct` (count only; batch G) |
| B7.7 | MF holding change 1M (AMFI) (G179) | ownership flow | | NEW FREE SOURCE | F26 PLANNED; R8 UNVERIFIED |
| B7.8 | Insider net buy 3M (G180) | insider | | NEW FREE SOURCE | F11, F13 UNVERIFIED |
| B7.9 | Bulk / block deals (G102) | flow | | NEW FREE SOURCE | F14 OBSERVED, no history at the URL (capture daily) |
| B7.10 | Pledge events between Reg. 31 snapshots (G92) | ownership | | NEW FREE SOURCE | F12 OBSERVED |
| B7.11 | Reg. 31 declarations: warrants, convertibles, partly paid, locked-in, DVR shares, SBO, PSU | ownership | entity-level `Whether...` declarations of the latest visible shareholding filing | BUILT | 18D (X118, C28): `has_warrants`, `has_convertibles`, `has_partly_paid`, `has_locked_in`, `has_dvr_shares`, `has_sbo`, `is_psu` (BOOLEAN; screen by column name) |

## B8. Event flags

| ID | Name | Family | Definition (our tags) | Status | Data / notes |
|---|---|---|---|---|---|
| B8.1 | Order wins / value 90d; KMP and auditor resignations 90d; fraud/default 90d (G114, G106, G116, G181) | Reg. 30 | | BUILT | `order_wins_90d`, `order_value_90d`, `kmp_resignations_90d`, `auditor_resignations_90d`, `fraud_or_default_90d` |
| B8.2 | Allotments / preferential / QIP count and shares 90d (G119) | dilution events | `corporate_events` event_type `ALLOTMENT` | BUILT | `allotments_90d` (count; shares not summed; batch G) |
| B8.3 | Litigation count 90d; fund-raising events 90d | Reg. 30 | event_type `LITIGATION`, family `FUND_RAISING` | BUILT | `litigations_90d`, `fund_raising_events_90d` (batch G) |
| B8.4 | Index inclusion / exclusion in last N days | index | `index_constituents_history` valid_from / valid_to | BUILT | `nifty500_inclusion_90d`, `nifty500_exclusion_90d` (batch I; NULL until the stored index history covers the 90 days; the first stored snapshot is not an inclusion) |
| B8.5 | Days to next ex-date; dividend / bonus / split in last 365 days | corp action | `corp_actions` ex_date, action_type | BUILT | `days_to_next_ex_date`, `next_ex_date_action`, `dividend_365d`, `bonus_365d`, `split_365d` (batch I; the next ex-date only from listings visible at the as-of) |
| B8.6 | Days since last result; results-season flag | dates | `filing_meta.visible_from_ts` | BUILT | DSL `Days since last result` (alias over `last_result_date`; the results-season flag is not built; batch G) |
| B8.7 | Reg. 30 red-flag columns (G117) | Reg. 30 | separate counts, never summed | BUILT | `rf_auditor_resignation_90d`, `rf_kmp_resignations_90d`, `rf_fraud_or_default_90d`, `rf_litigation_90d`, `rf_audit_qualified`, `rf_pledge_increase_qoq` (batch G); penalties stay NULL (E12 UNVERIFIED) |
| B8.8 | Penalties / regulatory actions 90d (G118) | Reg. 30 | | NEW FREE SOURCE | `penalties_90d` column exists but NULL: E12 contents UNVERIFIED |
| B8.9 | Credit-rating action flag (G98) | credit | | NEW FREE SOURCE | F22 UNVERIFIED |
| B8.10 | Upcoming board meeting / results date (G193) | calendar | | NEEDS PARSER | `PRIOR_INTIMATION` vaulted raw (E2), not parsed |
| B8.11 | Order-book-to-sales (G115) | Reg. 30 | | NOT POSSIBLE | no order-book element in any committed fixture (G115 note); revisit only if one appears |
| B8.12 | Organic vs inorganic perimeter flag (G276) | M&A | business-combination cash outflow / FY sales; flag >= 5% in either of two FYs | BUILT | `acquisition_outflow_{last,preceding}_year`, `acquisition_outflow_to_sales_last_year`, `inorganic_growth_flag` (cash-flow element, C26; batch G). Reg. 30 acquisition events still unparsed |

## B9. Segments (beyond Screener, data already parsed)

| ID | Name | Family | Definition (our tags) | Status | Data / notes |
|---|---|---|---|---|---|
| B9.1 | Number of reportable segments; largest-segment revenue share | mix | `segment_observations` (BUSINESS, REVENUE, member_role SEGMENT) | BUILT | `segment_count`, `largest_segment_revenue_share`, `segment_period_end` (batch I; Cummins Q2 FY27: 2 segments, 76.2%) |
| B9.2 | Fastest-growing segment YoY; segment margin change | mix | segment RESULT / REVENUE, quarter YoY | BUILT | `fastest_growing_segment`, `fastest_growing_segment_growth_yoy`, `largest_segment_margin_change_yoy_pp` (batch I; matched by filed label within the entity) |
| B9.3 | Subsidiary contribution (Schedule III additional information) | group mix | `AmountOfShareInProfitOrLossOfEntityConsolidated` per entity row / the filing's consolidated PAT | BUILT | 18D (X119, C28): `parent_profit_share`, `largest_subsidiary_profit_share`, `largest_subsidiary_name`, `consolidated_entities_count`, `subsidiary_fy_end`; adjustment / NCI rows excluded. DSL `parent profit share`, `largest subsidiary profit share`, `consolidated entities` |

## B10. Not buildable for lack of a free source (not elsewhere listed)

| ID | Name | Family | Definition | Status | Data / notes |
|---|---|---|---|---|---|
| B10.1 | Headcount, revenue per employee, attrition (G109) | ops | | NEW FREE SOURCE | BRSR F24 UNVERIFIED; no `NumberOfEmployees` element in the registry |
| B10.2 | Live 10Y G-Sec WACC, sector credit, commodity spreads (G135, G147, G280) | macro | | NEW FREE SOURCE | F25 PLANNED |
| B10.3 | Total-return benchmark (G191) | benchmark | | NEW FREE SOURCE | F29 UNVERIFIED |
| B10.4 | Index weights for passive-flow prediction (G129) | flow | | NEW FREE SOURCE | not in data_sources.yaml |
| B10.5 | Board independence, dissent % (G108, G121) | governance | | NEW FREE SOURCE | F23 OBSERVED |
| B10.6 | Paid-database items (MCA AOC-4 prior-year columns, consensus estimates, analyst targets) | — | | NOT POSSIBLE | owner decision 2026-11-15: no paid source at all |

## B11. Hidden gems (docs/hidden_gems.md; batch D, `features_gems.py`)

| ID | Name | Family | Definition (our tags) | Status | Data / notes |
|---|---|---|---|---|---|
| B11.1 | Core profit growth, latest and preceding quarter | quality growth | (PBT − other income − exceptional items) vs the same quarter a year earlier; NULL on a base ≤ 0 or for lenders / insurers | BUILT | `core_profit_latest_quarter`, `core_profit_yoy_latest_q`, `core_profit_yoy_preceding_q`; also `sales_growth_yoy_preceding_quarter_pct`, `profit_growth_yoy_preceding_quarter_pct` |
| B11.2 | Other-income lift | forensic | owners' profit YoY − core profit YoY, latest quarter | BUILT | `other_income_lift_pp` |
| B11.3 | PE on core profit | valuation | market cap / (TTM core pre-tax × (1 − TTM ETR) × owners' share) | BUILT | `pe_core`; Glenmark FY26 pinned in the e2e test |
| B11.4 | Sustained growth, operating leverage | growth | both quarters' sales YoY ≥ 12%; core YoY / sales YoY | BUILT | `growth_sustained`, `operating_leverage` |
| B11.5 | Magic formula rank | cross-section | EY rank + ROCE rank in the day's forensic-clean non-financial universe | BUILT | `magic_formula_rank` |
| B11.6 | Gem score | cross-section | weighted clipped z-scores (ROCE, sustained growth, EY, under-ownership, cash conversion, margin trend), non-cyclical universe | BUILT | `gem_score`, `pe_core_universe_median`, `market_cap_universe_median` |
| B11.7 | Forensic gate | forensic | no measured red flag (lift, restatement, Beneish, pledge, auditor / fraud events, OI / PBT); a gate, never a summed score (B1.25) | BUILT | `forensic_clean` |
| B11.8 | Industry and cyclical flag | classification | Nifty 500 list industry (PIT snapshot); Metals & Mining, Oil Gas & Consumable Fuels, curated shipping | BUILT | `industry`, `cyclical_flag`, `reference/cyclical_symbols.csv` |
| B11.9 | Under-owned, cash conversion, capex pay-off flags | flags | inst ≤ 15%, promoter ≥ 50%, no pledge; CFO / EBITDA ≥ 0.7; CWIP / GB ≥ 25%, capex / D&A ≥ 2, D/E ≤ 1 | BUILT | `under_owned`, `cash_conversion_ok`, `capex_pay_off_signal`, `inst_holding_pct` |
| B11.10 | Investor-hat screens | screens | the 11 screens of hidden_gems.md section B | BUILT | `hat_*`, `hats_passed`; saved screens `reference/saved_screens.csv` (`screen --saved NAME`, `screens`) |
| B11.11 | ROCE / OPM stability 5Y | quality history | 1 − std / mean over 5 FYs | WHEN HISTORY | `roce_stability_5y`, `opm_stability_5y`: FY25-FY29, ~May 2029 |
| B11.12 | PE vs own 5Y median | valuation history | PE / median of own stored daily PE over 5 years | WHEN HISTORY | `pe_vs_own_5y_median`: 2029-10 |

---

# Part C. Summary

## C1. Counts per status (one count per table row; a row may cover several Screener names / period variants)

| Status | Part A (Screener gallery) | Part B (beyond Screener) | Total |
|---|---|---|---|
| BUILT | 150 | 110 | 260 |
| IN PROGRESS | 0 | 0 | 0 |
| BUILDABLE NOW | 2 | 1 | 3 |
| WHEN HISTORY | 16 | 3 | 19 |
| NEEDS PARSER | 2 | 1 | 3 |
| NEW FREE SOURCE | 1 | 15 | 16 |
| NOT POSSIBLE | 2 | 4 | 6 |
| **Total rows** | 173 | 134 | 307 |

Recounted after 18D (2026-11-16, features `2026.11.16-18D`, `features_disclosures.py`): three new BUILT rows in Part
B from `disclosure_facts` [X116]: B1.26 (insider receivables), B7.11 (Reg. 31 declarations), B9.3 (subsidiary
contribution).

Recounted from the status column after batch I (2026-11-15, features `2026.11.15-11I`, `features_more.py`): 21 rows
BUILT (1 in Part A, 20 in Part B): A1.19, B5.7, B5.8 were already built by batch H (`features_peers.py`) and only had
not been marked; B1.2, B1.3, B1.5, B1.7, B2.12, B3.2, B3.3, B4.9, B5.2, B5.3, B6.3, B6.4, B6.11, B6.14, B8.4, B8.5,
B9.1, B9.2 are new columns. Left BUILDABLE NOW on purpose: A1.12 (Screener's "Price to Quarterly Earning" definition
UNVERIFIED: no column until an evidence row pins it), A1.24 (Is SME: a constant 0 in a universe that excludes SME by
C7, no information) and B1.24 (filed DSCR / ISCR implausible, C26).

Recounted from the status column after batch G (2026-11-15, features `2026.11.15-8G`, `features_extra.py`): 43 rows
BUILT (11 in Part A, 32 in Part B, incl. B2.9 from WHEN HISTORY and B8.12 from NEEDS PARSER: the business-combination
cash-flow element is a zero-drop key). Still BUILDABLE NOW: A1.12 (Screener's definition UNVERIFIED), A1.19, B4.9,
B5.7, B5.8 (industry tiers: the industry-classification work), A1.24, B1.2, B1.3, B1.5, B1.7, B1.24 (filed DSCR / ISCR
implausible, C26), B2.12, B3.2, B3.3, B5.2, B5.3, B6.3, B6.4 (volatility, drawdown), B6.11, B6.14, B8.4, B8.5, B9.1,
B9.2.

Recounted from the status column after batch D (2026-11-15, features `2026.11.15-6D`; the earlier batch A / B row
updates had not been carried into this table). Section B11 (hidden gems) added 12 rows.

Recounted from the table rows after batch C (features `2026.11.15-6C`); before it the rows gave BUILT 85 / 29,
BUILDABLE NOW 57 / 63, WHEN HISTORY 26 / 6 (the table above had not been recounted after batches A and B). A
history-gated row whose column exists (NULL until its window is in scope, C9) counts as BUILT.

## C2. Proposed implementation order for BUILDABLE NOW

Design point to settle first (owner or reviewer): Screener's period variants (latest / preceding / preceding-year
quarter, 2 and 3 quarters back, last / preceding year) multiply ~20 P&L lines into ~90 columns. Two options:
(a) wide columns in `screener_features` (simple DSL, bigger table and `FEATURES_VERSION` churn); (b) a narrow
`period_values(as_of_date, security_id, line, period_key, value)` table that DSL aliases like `sales latest quarter`
compile to via a join. Either way the extractor is one batched function over the FactBook, never a per-row query
(test_benchmarks). Every batch below touches `features.py` / `fundamentals.py`, so each bumps `FEATURES_VERSION`
and the pinned hash in `tests/test_incremental_materialize.py`, and adds schema columns + DSL aliases + fixture-pinned
tests. Batch 0 is trivial: DSL aliases for built columns that have none (`shares`, `restatement_suspected`,
`non_promoter_non_public_pct`, `annual_fy_end`) and fix `book value` to mean per share (keep the crore value under
`net worth`).

| Batch | Scope | Rows | Code touched |
|---|---|---|---|
| 1. Period P&L family | quarter lines × 5 offsets (A5.1-A5.17), FY lines last/preceding year (A4.4-A4.19, A4.21, A4.23-A4.24), quarter YoY growth (A5.18, A5.20), FY YoY (A4.28), result dates (A4.25, A5.21), accelerations and margin deltas (B4.1, B4.3-B4.6, B4.8), cost shares (B3.4-B3.7), exceptional share (B1.14), price to quarterly earnings (A1.12) | ~35 | new `fundamentals.period_lines(book, end)` on `FactBook.quarter` / FY periods; features; schema or `period_values`; dsl |
| 2. Balance sheet, working capital and annual notes | Debt, current / quick ratio, book value per share, face value, equity capital, reserves, BS lines and preceding-year values (A1.13, A1.16, A1.18, A1.25, A2.17, A2.18, A2.21, A2.22, A6.1-A6.23 buildable), ROA / ROE / ROCE preceding year and Earning Power (A2.2, A2.6, A2.8, A2.9, A2.13), Graham number (A2.14), exports % (A2.32), Δ CCC and H1 days (B3.2, B3.3), Reg. 34 notes ratios (B1.20, B1.22, B1.23, B1.24, B2.12) | ~40 | `building_blocks` (expose stocks), `screener_convention_ratios` / `annual_ratios` (prior FY), features |
| 3. Cash flow and capital allocation | FY CF lines (A7.1-A7.8), P/FCF, equity FCF yield (A1.8, B5.11), CFO/PAT, cash tax rate, ETR (B1.8, B1.11, B1.12), shareholder and buyback yield (B2.2, B2.3), 1Y dilution (B2.4), reinvestment rate and 1Y incremental ROIC (B2.6, B2.7), capex intensity (B2.11), net debt / EBITDA (B2.15), net cash / mcap (B2.17), balance-sheet accruals (B1.7) | ~20 | `cash_conversion_blocks`, `ttm_from_ytd` users, features |
| 4. Price, volume and technicals | **Done 2026-11-15 (batch B, `features_price.py`) except** RS rank (B6.3), volatility / drawdown (B6.4), volume spike (B6.10), 52W-high-on-delivery flag (B6.11), Is SME (A1.24: always false, C7), PEAD (B6.14). Scope: 1D/1W returns, volume and averages, 52W high/low levels, DMA levels and previous day, RSI, MACD (A8.1, A8.5-A8.7, A8.9-A8.12), ATR, RS vs Nifty 500 and RS rank, beta / volatility / drawdown, 52W-low distance, VWAP, delivery %, median traded value, volume spike, 52W-high-on-delivery flag (B6.1-B6.7, B6.9-B6.11), Is SME (A1.24); then market breadth and PEAD as separate market-level tables (B6.13, B6.14) | ~25 | `features._momentum` / `_delivery` (one pass over adjusted bars), `index_ohlcv` preload; new market-level table for breadth |
| 5. Ownership and event flags | FII and DII QoQ separately, unpledged promoter, shareholder counts and changes (A3.5, A3.8, A3.10, A3.11), MF / insurance / retail holdings, pledge change, absorption, >1% holder count (B7.1-B7.6), audit-qualified flag (B1.16), allotment / litigation / fund-raising counts, index inclusion, ex-date and result-date flags (B8.2-B8.7) | ~15 | `shareholding_columns`, `_event_counts`, `_preload` (filing_meta, corp_actions, index history) |
| 6. Valuation, cross-section and composites | P/S, earnings yield, EV/Sales (A1.7, A1.9, B5.6), PB / P/S percentiles (B5.2, B5.3), coarse industry PE / PBV, discount to industry median, peer rank, sector breadth (A1.19, B5.7, B5.8, B4.9), EV/GOV and P/EV (B5.10), Beneish and Piotroski components, original Altman Z (B1.2, B1.3, B1.5), standalone-vs-consolidated leakage (B1.18), RPT intensity (B1.19), segment mix (B9.1, B9.2) | ~20 | features `_rows` (needs mcap / EV), a cross-sectional pass after rows are built (industry medians, ranks), `raw_index_snapshot` industry PIT lookup, second-scope FactBook prefetch |

Progress (2026-11-15, batch I, features `2026.11.15-11I`, `features_more.py`): every remaining buildable row of Batches
2-6 except A1.12, A1.24 and B1.24 (see C1): Beneish / Piotroski components, original Altman Z, balance-sheet accruals,
depreciation rate and asset age, FY and half-year days changes, PB / P/S / EV/Sales percentiles, RS rank of 12M-1M
momentum, volatility and drawdown, 52W high on a delivery spike, PEAD tracker, index inclusion / exclusion,
corporate-action recency, segment mix and sector earnings breadth.

Progress (2026-11-15, batch G, features `2026.11.15-8G`, `features_extra.py`): the remaining Phase 2 ratios of
docs/phase_status.md (G152, G257, G256, G258, G133, G276, G278, G220, G241, G270, G265, G266, M4, G117, G244, G201 as
the view `capital_allocation_scorecard`) and, from Batches 1-6: EBIDT, minority share, dividend, material and employee
cost lines, FY YoY growth (aliases), B1.8, B1.11, B1.12, B1.14, B1.16, B1.18-B1.20, B1.22, B1.23, B2.11, B2.17,
B3.4-B3.7, B4.4-B4.6, B4.8, P/S, EV/Sales, B5.10, volume spike (alias), B7.4-B7.6, B8.2, B8.3, B8.6 (alias), B8.7,
A6.12-A6.14.

Progress (2026-11-15, batch D, features `2026.11.15-6D`): Batch 5 ownership part done (A3.5, A3.8, A3.10, A3.11,
B7.1-B7.3; FII / DII / MF change QoQ, shareholder counts, insurance / retail holding), plus earnings yield (A1.9), PEG
on core growth (A1.11), B4.1 / B4.3 and the hidden-gem section B11 (`features_gems.py`, saved screens). Still open from
Batch 5: pledge change (B7.4), absorption (B7.5), >1% holder count (B7.6), audit-qualified flag (B1.16), event flags
(B8.2-B8.7).

Progress (2026-11-15, batch A, features `2026.11.15-4A`): Batch 0 done (aliases, `book value` per share, `screen
--columns` / `--order-by`, `save-ratio`, trade-to-trade flag). Batch 1 done for the P&L lines × 5 quarter offsets and
2 fiscal years, quarter YoY growth, result dates and the history-gated P&L windows (wide columns, `features_pl.py`).
Still open from Batch 1: EBIDT lines (A4.7, A5.4), minority share, dividend, material and employee cost lines
(A4.16-A4.19), FY YoY (A4.28), accelerations and margin deltas (B4.1, B4.3-B4.6, B4.8), cost shares (B3.4-B3.7),
exceptional share (B1.14), price to quarterly earnings (A1.12).

Progress (2026-11-15, batch C, features `2026.11.15-6C`, `features_bs.py`): Batches 2 and 3 done for the
balance-sheet lines (latest BS, preceding year, N years back), annual notes, liquidity / leverage / return ratios,
Graham number, exports %, FY cash-flow lines and N-year sums, P/FCF, equity FCF yield, shareholder and buyback yield,
1Y / 5Y dilution, reinvestment rate, incremental ROIC 1/3/5Y, the 20-quarter EV/EBITDA band (G240), net debt / EBITDA and the 3Y conversion forms of G223 / G224 /
G233. Still open from Batches 2-3: unquoted / quoted investments and revaluation reserve (A6.12-A6.14), Δ CCC and H1
days (B3.2, B3.3), Reg. 34 notes ratios (B1.20, B1.22-B1.24, B2.12), CFO / PAT, cash tax rate, ETR (B1.8, B1.11,
B1.12), capex intensity (B2.11), net cash / mcap (B2.17), balance-sheet accruals (B1.7), Screener's average-capital
ROCE preceding year (A2.6 closing form only); preference capital and secured / unsecured loans stay NEEDS PARSER.

Order rationale: 1-3 are pure FactBook work on already-tested blocks and unlock most of Screener's gallery; 4 is
independent of fundamentals (can run in parallel); 5 is small; 6 last because cross-sectional steps (industry medians,
ranks) depend on the per-row columns from 1-4 and on an explicit PIT rule for the industry snapshot. WHEN HISTORY rows
should be implemented together with their batch (formula + `min_periods_required`) so they switch on by themselves on
the dates in §0; their tests pin the NULL today and a value on synthetic in-scope history.
