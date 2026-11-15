# Master backlog: owner PDF vs digest vs ratio catalogue vs code (2026-11-15)

Read-only audit. Inputs: the text of `docs/inputs/Aligning_Financial_Results_Databases.pdf` (all 2,816 lines read in order, the `pdftotext -layout` text of
`docs/inputs/Aligning_Financial_Results_Databases.pdf`), `docs/owner_requirements.md` (G1-G343, "digest"),
`docs/ratio_catalogue.md` (292 rows, "catalogue"), and the code on branch `phase-2-live-backfill` at
`e085eb5` (`src/financials`, `db/schema.sql`, `dsl.ALIASES` = 138 aliases at the time of the audit). Nothing was run
against the DB.

Note on timing: commit `e085eb5` ("Add QoQ growth, NPM, interest coverage, dividend and promoter-change features")
landed while this audit ran. It builds G169, G173, G175, G178, G202, which the digest still lists as MISSING and the
catalogue as IN PROGRESS. They are counted as BUILT here.

## Classes

| Class | Meaning |
|---|---|
| BUILT | implemented in code (column, parser, table, rule or CLI found); "partial" notes say what part is missing |
| CATALOGUE | a metric with a ratio_catalogue row that is not built (BUILDABLE NOW, WHEN HISTORY, NEEDS PARSER, NEW FREE SOURCE, NOT POSSIBLE) |
| DIGEST | open in the digest only (non-ratio work, or a metric the catalogue does not list) |
| MISSED | in neither the digest nor the catalogue |
| OOS | out of scope by a recorded owner decision (no paid sources; C7 NSE-only/SME out; C2 dividends never adjust prices; invariants 4/8/9; CLAUDE.md Don'ts). History-gated (C9) items are **not** OOS. |

## Summary counts (one row per distinct requirement below; repeats in the PDF are merged into one row)

| Area | BUILT | CATALOGUE | DIGEST | MISSED | OOS | Total |
|---|---|---|---|---|---|---|
| A. Ratios / metrics | 79 | 32 | 2 | 4 | 1 | 118 |
| B. Data sources | 14 | 22 | 15 | 2 | 3 | 56 |
| C. Corporate structure / identity | 11 | 1 | 6 | 0 | 2 | 20 |
| D. Events, flows, corporate actions | 16 | 1 | 7 | 0 | 4 | 28 |
| E. Data quality / rules / assistant claims | 63 | 0 | 13 | 0 | 8 | 84 |
| F. Backtest | 6 | 0 | 2 | 0 | 0 | 8 |
| G. Alerts / UI / tools / ops | 8 | 1 | 11 | 2 | 2 | 24 |
| **Total** | **197** | **57** | **56** | **8** | **20** | **338** |

Counts are tallied from the Class column of section 3 (last bold token per row). Of the 197 BUILT rows (7 moved from
CATALOGUE by batch C, 3 from DIGEST by batch E, 2026-11-15), 10 are only
partly built, 1 is built with a different definition (`opm_last_year_pct`), and 13 are rows where the PDF's claim was
wrong and the corrected behaviour is built (marked "corrected").

The digest has 343 G-rows; this list merges PDF repeats (e.g. G110 + G167 in A04, G77 + G78 in E81, G273 + G319 in E43)
and adds 5 rows the digest never named but the code already has: A13 geographic non-current assets
(`parsers/segments.py`), A106 bank advances / deposits / GNPA / NNPA, E74 `filing_meta.audited` (the blueprint's
`is_audited`), E75 PDF-verified corrections (`fact_corrections`), E40 Beneish / Altman NULL for financials.

**Verdict on "many things from the PDF were not taken":** as *capture*, largely disproved: 8 of 338 requirements
appear in neither the digest nor the catalogue, all minor (one is a desk-research task, one comes from an example
query). As *implementation*, confirmed: 130 requirements (71 CATALOGUE + 59 DIGEST) are captured but not built, 20 are
excluded by owner decision, and 15 of the BUILT rows are partial or differ from the PDF (section 2). The digest itself
is also stale in both directions (section 2, last paragraph).

---

## 1. Missed by both digest and catalogue (the key list)

| # | req.txt lines | PDF wording (brief) | Proposed status | Data it uses / why | Proposed batch |
|---|---|---|---|---|---|
| M1 | 1284-1285 | saved custom ratios "expand inline inside any screening query **or custom results column**" | BUILDABLE NOW | `dsl.run_screen` already selects the metrics referenced in the WHERE clause; add an explicit output-column list (`screen --columns "..."`, custom ratios allowed) and ORDER BY. G187 covers only inline expansion (and notes there is no CLI to save a ratio: add `save-ratio` in the same batch) | Batch 0 (DSL / CLI). **DONE 2026-11-15 (batch A)**: `screen --columns`, `--order-by`, `save-ratio`, `ratios` |
| M2 | 1048-1049, 1671-1673, 1717-1719 | 10Y G-Sec as "risk-free rate Rf for automated DCF and **Equity Risk Premium models**"; cost of debt "spikes above prevailing **MCLR/G-Sec** yields"; unlevered FCF yield "directly comparable against the **live 10Y G-Sec** yield" | NEEDS NEW FREE SOURCE | RBI DBIE / FBIL 10Y benchmark G-Sec yield and MCLR (F25, PLANNED, no source probed). Columns: `earnings_yield - gsec_10y` (market ERP proxy), `fcff_yield - gsec_10y`, `cost_of_debt - gsec_10y`. G135 covers only the feed, catalogue B10.2 only the WACC | Phase 3 macro, together with the live-WACC reverse DCF (G200) |
| M3 | 1883-1885 | Rule of 40 = YoY revenue growth % + EBITDA margin % "**(or FCF Margin %)**" | WHEN HISTORY | `rule_of_40` (EBITDA form) is BUILT; FCF-margin variant = revenue YoY (8 quarters, ~Feb 2027) + `fcf_ttm / sales_ttm` (H1/FY bridge) | Batch 6 (new-gen) |
| M4 | 2651-2652 (assistant's corrected architecture: IGAAP_BANK "maps ... casa_pct") | CASA % for banks | BUILDABLE NOW (manual KPI) | XBRL has no CASA element (X23, X35). Digest G339 says "CASA goes to supplemental_kpis", but `parsers/kpis.py` `KPI_UNITS` has no `casa` key (load-kpis rejects it as UNKNOWN_KPI) and no column exists. Add `casa_pct` (RATIO) to KPI_UNITS, `screener_features`, DSL alias; source = bank investor presentations (manual, like VNB) | Batch 5 (ownership / KPI) |
| M5 | 1290 (example NL query "Debt-free **smallcaps** ..."), 1018-1020 (Nifty 50 / Next 50 / Midcap 150 / Smallcap 250) | market-cap size bucket / index-family membership | BUILDABLE NOW as a proxy; exact form NEEDS NEW FREE SOURCE | proxy: rank by `market_cap` inside the active universe (top 100 / 101-250 / rest). Exact: AMFI half-yearly large/mid/small-cap list (free, UNVERIFIED) or NSE Midcap 150 / Smallcap 250 constituent CSVs (same family as IDX1 `ind_nifty500list.csv`, needs a fixture). Example-derived: the PDF names it only inside an example query and the weightage-file row | Batch 6 (cross-section) |
| M6 | 1100-1102 | ASM/GSM row: "Flags regulatory overhang and **trade-to-trade (BE/BZ)** settlement traps before you enter" | BUILDABLE NOW (T2T part) | `ohlcv.series` / `screener_features.series` already hold EQ/BE/BZ; add a boolean `is_trade_to_trade` (series in BE, BZ) and a DSL alias. The ASM/GSM stage itself stays G139 (F20, NEW FREE SOURCE) | Batch 0 (alias) or Batch 4 (price). **DONE 2026-11-15 (batch A)**: `is_trade_to_trade`, DSL `trade to trade` |
| M7 | 2284-2286 | "the BSE fallback and the **NSE-vs-BSE cross-check (Gate 4)**" (owner-pasted review describing the blueprint's gate) | NEEDS NEW FREE SOURCE | BSE equity bhavcopy (not in `config/data_sources.yaml`; BSE endpoints unreachable from the container, A1). Close-price cross-check per dual-listed security as a promotion warning, never a writer. G291 (failover) is related but is not the check | Phase 3 with G86 / G291 |
| M8 | 1184-1188, 1196-1250 (owner: "You must check all websites and other new generation websites ... to find out what additional inputs we must add") | competitor feature inventory beyond Screener (Tijori, Trendlyne, Chartink, StockEdge, Tickertape, Altys, MarketsMojo, Tapetide, MarketMind) | BUILDABLE NOW (desk work, no data) | the catalogue's Part A is the Screener gallery only; G113 records the goal ("beat Screener, Tijori and Trendlyne") but no inventory of the other sites' screen fields exists. Output = extra Part A sections in the catalogue, each row mapped like A1-A8 | Docs batch (before Batch 6) |

M8 is a work item (desk research), not a data requirement; it is counted under G. Row ids in section 3: M1 = G07,
M2 = A113, M3 = A94, M4 = A112, M5 = A114, M6 = B31, M7 = B51, M8 = G23.

---

## 2. Digest says DONE but not found (fully or partly) in code

| G | Digest claim | What the code has | Finding |
|---|---|---|---|
| G292 | "Tables entity_securities, subsidiary_tree, pipeline_audit_log": DONE | `securities`, `promotion_log`, `admin_log` exist; **no `subsidiary_tree`** (schema.sql has none; G277 AOC-1 is DOCUMENTED_PLANNED) | DIGEST SAYS DONE, NOT FOUND (subsidiary_tree) |
| G94 | "Bhavcopy close, 52-week high/low": DONE | `close`, `dist_52w_high` only (`features._momentum` line ~221). **No 52-week low, no 52W high/low levels** | FIXED 2026-11-15 (batch B): `high_52w`, `low_52w`, `dist_52w_low` |
| G40, G60, G289 | evening job / daily master sync / "Daily run is automatic" | `run-day` CLI exists (arch §2, schedule documented in arch §13), but **nothing schedules it**: no cron / systemd / Task Scheduler file or install step in the repo | DONE as a command; "automatic" NOT FOUND |
| G224 | FCF-to-net-income conversion (3Y) | `fcf_to_pat` is TTM; no 3Y-sum column returning NULL until history | PARTLY NOT FOUND (owner decision: history-gated ratios are built and return NULL) **FIXED 2026-11-15 (batch C)**: `fcf_conversion_3y` (history-gated) |
| G233 | Net debt / 3Y average FCF | `net_debt_to_fcf` uses TTM FCF; no 3Y-average form | PARTLY NOT FOUND **FIXED 2026-11-15 (batch C)**: `net_debt_to_fcf_3y` (history-gated) |
| G240 | 5Y EV/EBITDA band percentile (20 quarters) | `ev_ebitda_percentile` with >= 4 prior quarters; no 20-quarter column | PARTLY NOT FOUND **FIXED 2026-11-15 (batch C)**: `ev_ebitda_percentile_20q` (history-gated) |
| G198 | Valuation bands PE / PB / EV-EBITDA vs own 3/5/10Y median and percentile | PE and EV/EBITDA percentile only; **no P/B band, no median, no 3/5/10Y windows** | PARTLY NOT FOUND (digest notes P/B) |
| G200, G239 | Reverse DCF using the live 10Y G-Sec | fixed WACC 12% / terminal 4% stored with the result | PARTLY NOT FOUND (needs F25) |
| G170 | FCF yield | `fcff_yield` (unlevered, FCFF/EV) only; the plain/equity FCF yield of the PDF's screener list (L1262) is not built | PARTLY NOT FOUND (catalogue B5.11) **FIXED 2026-11-15 (batch C)**: `equity_fcf_yield` |
| G181 | Reg. 30 red-flag count | five separate 90-day counts; **no single "Reg 30 Red Flag Count" column** (L1271); `penalties_90d` always NULL | PARTLY NOT FOUND |
| G187 | Saved custom ratios | `dsl.save_custom_ratio()` + `user_custom_ratios`; **no CLI command** to save one; not usable as output columns (M1) | PARTLY NOT FOUND |
| G119 | Allotments / preferential / QIP / warrants | `corporate_events` ALLOTMENT rows; **no warrant-conversion tracker, no dilution column** (PDF L958-959) | PARTLY NOT FOUND (digest notes it) |
| G99 | RPT from Reg. 23(9) | `rpt_total_amount` only; per-counterparty purchases / loans / royalties not mapped (`data_sources.yaml` F10 note) | PARTLY NOT FOUND (blocks G236) |
| G175 (new, e085eb5) | "OPM last year" | `opm_last_year_pct` = OPM of **the same quarter one year earlier**; Screener's "OPM last year" (the PDF's example `OPM > OPM last year`, L1254, L1267) and catalogue A4.20 = **FY** EBITDA / FY sales | BUILT WITH A DIFFERENT DEFINITION: rename to `opm_same_quarter_ly_pct` (it is the base of G204) and add the FY form. **FIXED 2026-11-15 (batch A)**: renamed `opm_preceding_year_quarter_pct` (DSL `opm same quarter last year`); `opm_last_year_pct` is now the FY OPM |

Stale the other way (digest says open, code has it): G130 / G131 IN_PROGRESS, but segment and geography rows are
promoted on this branch (`segment_observations`, `axis_kind` BUSINESS | GEOGRAPHY, `promoter.py:1261`); G67 / G68
say "restatement_suspected not implemented", but the X106 flag exists (`FactBook.restatement_suspected`, YTD trigger
only at the time; the discontinued-ops and corporate-action triggers were added by batch E, X108 / X109); G169 / G173 / G175 / G178 / G202 MISSING
are now BUILT (e085eb5); G28 NEEDS_OWNER_DECISION was settled by decisions A and B (2026-11-15). Also mislabelled:
G172, G176, G247 are marked OUT_OF_SCOPE_BY_DECISION, but under the owner's rule they are history-gated BUILD items
(catalogue A4.29-A4.32, A2.34, B2.8; `fundamentals.cagr(min_periods_required=...)` exists but no feature uses it).

---

## 3. Full item list by area

Columns: lines = req.txt line numbers; G = digest id and its status; Cat = catalogue row and its status; Code = what
exists (file / column); Class.

### A. Ratios and metrics

| # | Lines | Item (PDF wording, brief) | G (digest status) | Cat | Code | Class |
|---|---|---|---|---|---|---|
| A01 | 831 | daily close | G94 DONE | A1.1 BUILT | `close` | **BUILT** |
| A02 | 831 | VWAP from full bhavcopy | G95 DONE | B6.6 BUILT | `vwap`, `vwap_20d` (P16) | **BUILT** |
| A03 | 831 | 52-week high / low | G94 DONE | A8.7, B6.5 BUILT | `high_52w`, `low_52w`, `dist_52w_high`, `dist_52w_low` | **BUILT** |
| A04 | 904, 1262 | market cap, current price, PE, PB, EV/EBITDA | G110, G167 DONE | A1.1-A1.6 BUILT | `market_cap`, `pe`, `pb`, `ev_ebitda`, `enterprise_value` | **BUILT** |
| A05 | 904-906 | EV adds net debt from latest H1/FY balance sheet; TTM from Reg. 33 | G110 DONE | A1.3 | `net_debt`, `bs_as_of` | **BUILT** |
| A06 | 908-909 | ROCE, ROE, working-capital days, ROIC | G111 DONE | A2.5, A2.1, A2.29, A2.11 | `roce`, `roe`, `working_capital_days`, `roic` | **BUILT** |
| A07 | 911-913, 835 | peer table ranked by mcap, PE, ROCE, quarterly profit growth | G112 MISSING | B5.8 BUILDABLE NOW (coarse industry) | none | **CATALOGUE** |
| A08 | 940-943 | order-book-to-sales ratio | G115 MISSING | B8.11 NOT POSSIBLE | `order_value_90d` only | **CATALOGUE** |
| A09 | 946-947 | automated forensic red-flag score from Reg. 30 | G117 MISSING | B8.7 BUILDABLE NOW (separate counts) | 90-day counts | **CATALOGUE** |
| A10 | 949-952 | quantify contingent tax / regulatory liabilities from penalty filings | G118 DOC_PLANNED | B8.8 NEW FREE SOURCE | `penalties_90d` NULL | **CATALOGUE** |
| A11 | 1032-1034 | segment revenue, results, assets, liabilities (Ind AS 108) | G130 IN_PROGRESS (stale) | B9.1-B9.2 BUILDABLE NOW | `segment_observations` BUSINESS promoted; no feature columns | **BUILT** (data; mix columns = catalogue) |
| A12 | 1036-1037 | geographic revenue split domestic vs export | G131 IN_PROGRESS (stale) | A2.32 BUILDABLE NOW | `segment_observations` GEOGRAPHY; `exports_pct`, `exports_pct_{3,5}y_back` (batch C, 2026-11-15) | **BUILT** |
| A13 | 1036-1037 | geographic **non-current asset** split | not named (G131 is revenue only) | none | `parsers/segments.py` NON_CURRENT_ASSETS on GEOGRAPHY | **BUILT** (data only) |
| A14 | 1039-1041 | cost-structure shares (materials, power & fuel, freight, subcontracting, employee); crude / power / freight sensitivity screens | G132 DONE (tags), G133 MISSING (screens) | B3.4, B3.5 BUILDABLE NOW | label rules POWER_AND_FUEL, FREIGHT; no share columns | **CATALOGUE** |
| A15 | 1043-1045 | capex, CWIP -> FCF, CFO/EBITDA, CWIP / gross block | G134 DONE | B2.10 BUILT | `fcf_ttm`, `cfo_to_ebitda`, `cwip_to_gross_block` | **BUILT** |
| A16 | 1216, 1273 | 50 / 200 DMA, price to 50 / 200 DMA | G155 DONE | A8.9 (levels BUILDABLE), ratio BUILT | `price_to_dma50/200` | **BUILT** |
| A17 | 1216, 1274 | RSI(14) | G156 DONE | A8.11 BUILT | `rsi_14`, `rsi_14_prev` | **BUILT** |
| A18 | 1216 | ATR% | G157 DONE | B6.1 BUILT | `atr_14_pct` | **BUILT** |
| A19 | 1216-1218, 1273 | 52W high proximity / distance from 52W high | G182 DONE | A8.7 | `dist_52w_high` | **BUILT** |
| A20 | 1218, 2209 | relative strength vs Nifty 500 | G158 DONE | B6.2 BUILT | `rs_nifty500_3m/6m/12m`, `beta_1y_nifty500` | **BUILT** |
| A21 | 1220 | 5D / 20D delivery spikes | G159 DONE | B6.8 BUILT | `deliv_avg_5d/20d`, `delivery_velocity` | **BUILT** |
| A22 | 1224 | Piotroski F-score | G160 DONE | A2.15 BUILT | `piotroski_f` | **BUILT** |
| A23 | 1224-1226 | Beneish M-score | G161 DONE | B1.1 BUILT | `beneish_m` | **BUILT** |
| A24 | 1226 | Altman Z-score | G162 DONE | B1.4 BUILT (Z''); B1.5 original Z BUILDABLE | `altman_z_dd` | **BUILT** |
| A25 | 1228-1229 | cash conversion CFO/EBITDA and contingent liabilities / net worth flags | G223, G235 DONE | B1.21 BUILT | `cfo_to_ebitda`, `contingent_liabilities_to_net_worth` | **BUILT** |
| A26 | 1262 | PEG ratio | G168 DONE (batch D) | A1.11 | `peg` = `pe_core` / core profit growth (quarter YoY now, TTM-on-TTM after 8 quarters) | **BUILT** |
| A27 | 1262 | dividend yield | G169 MISSING (stale) | A1.10 | `dividend_yield_pct` (e085eb5) | **BUILT** |
| A28 | 1262 | FCF yield | G170 DONE | B5.11 BUILDABLE NOW (equity form) | `fcff_yield` (unlevered); `equity_fcf_yield`, `price_to_fcf` (batch C, 2026-11-15) | **BUILT** |
| A29 | 1264 | sales growth, profit growth (TTM YoY) | G171 DONE | A4.26 BUILT | `sales_growth_yoy`, `profit_growth_yoy` (NULL until ~Feb 2027) | **BUILT** |
| A30 | 1264-1265, 2046 | sales growth 3Y / 5Y, profit growth 3Y, EPS growth 3Y | G172 OOS (mislabelled) | A4.29-A4.32 WHEN HISTORY | `fundamentals.cagr` exists, no column / alias | **CATALOGUE** |
| A31 | 1265 | QoQ sales %, QoQ profit % | G173 MISSING (stale) | A5.19 | `sales_growth_qoq_pct`, `profit_growth_qoq_pct` (e085eb5) | **BUILT** |
| A32 | 1254, 1267 | OPM, OPM last year (example `OPM > OPM last year`) | G174 DONE, G175 MISSING (stale) | A4.3 BUILT, A4.20 (FY form) | `opm`; `opm_last_year_pct` = same quarter last year (not FY) | **BUILT** (definition differs, see §2) |
| A33 | 1267 | OPM 5Year | G176 OOS (mislabelled) | A2.34 WHEN HISTORY (~May 2029) | none | **CATALOGUE** |
| A34 | 1267 | NPM | G175 | A4.22 | `npm_pct` (e085eb5) | **BUILT** |
| A35 | 1268 | interest coverage | G175 | A2.24 | `interest_coverage` (e085eb5); filed ISCR not exposed (B1.24) | **BUILT** |
| A36 | 1267-1268 | ROCE, ROE, ROIC, debt/equity, WC days, CFO to EBITDA | G174 DONE | A2.x BUILT | columns exist | **BUILT** |
| A37 | 1270 | promoter holding, pledged %, FII, DII holding | G177 DONE | A3.1, A3.4, A3.7 BUILT | `promoter_holding_pct`, `promoter_pledge_pct`, `fii_holding_pct`, `dii_holding_pct` | **BUILT** |
| A38 | 1270 | change in promoter holding | G178 MISSING (stale) | A3.2 | `promoter_holding_change_qoq_pp` (e085eb5) | **BUILT** |
| A39 | 1271 | MF holding change 1M (AMFI) | G179 DOC_PLANNED | B7.7 NEW FREE SOURCE | none | **CATALOGUE** |
| A40 | 1271 | insider net buy 3M (PIT / SDD) | G180 DOC_PLANNED | B7.8 NEW FREE SOURCE | none | **CATALOGUE** |
| A41 | 1271 | Reg. 30 red-flag count | G181 DONE | B8.1 BUILT, B8.7 | five 90-day counts, no single count | **BUILT** (partial) |
| A42 | 1273 | returns 1M / 3M / 6M / 12M | G182 DONE | A8.2 BUILT | `return_1m..12m` | **BUILT** |
| A43 | 1274 | average delivery % 20D | G183 DONE | B6.7 BUILT | `deliv_pct_avg_20d`, `deliv_pct` | **BUILT** |
| A44 | 1274 | F&O PCR | G184 DOC_PLANNED | B6.15 NEW FREE SOURCE | none | **CATALOGUE** |
| A45 | 1284-1285 | Net Cash to MCap = (cash + investments - total debt) / mcap (custom-ratio example) | none | B2.17 BUILDABLE NOW | no column; expressible now as a saved ratio over `cash equivalents`, `investments`, `debt`, `market cap` (batch C, 2026-11-15) (liquid cash = `liquid_cash`) | **CATALOGUE** |
| A46 | 1353-1355, 1742-1746 | valuation bands: PE, PB, EV/EBITDA vs own 3/5/10Y median and percentile | G198 DONE (partial), G240 DONE | B5.1 BUILT, B5.2-B5.4, A1.20-A1.21 | `pe_percentile`, `ev_ebitda_percentile`; `ev_ebitda_percentile_20q` (G240, history-gated) (batch C, 2026-11-15) | **BUILT** (partial: PB band, medians, 3/10Y windows) |
| A47 | 1355 | discount / premium to basic-industry median | G199 MISSING | B5.7 BUILDABLE NOW (coarse) | none | **CATALOGUE** |
| A48 | 1357-1359, 1728-1740 | reverse DCF implied 5Y growth with live 10Y G-Sec | G200, G239 DONE | B5.5 BUILT | `reverse_dcf_implied_g` (WACC fixed 12%) | **BUILT** (partial: live yield needs F25) |
| A49 | 1361, 1452-1459 | incremental ROIC (1Y / 3Y / 5Y) | G215 DOC_PLANNED | B2.7 BUILDABLE NOW, B2.8 WHEN HISTORY | `incremental_roic_1y`, `_3y`, `_5y` (3Y / 5Y history-gated) (batch C, 2026-11-15) | **BUILT** |
| A50 | 1361 | dividend payout % | G202 MISSING (stale) | B2.1 | `dividend_payout_pct` (e085eb5) | **BUILT** |
| A51 | 1361 | buyback yield | G201 DOC_PLANNED | B2.3 BUILDABLE NOW | `buyback_yield` (batch C, 2026-11-15) | **BUILT** |
| A52 | 1362, 1491-1498 | equity dilution % over 5Y (split/bonus-adjusted share counts) | G219 DOC_PLANNED | B2.4 (1Y) BUILDABLE NOW, B2.5 WHEN HISTORY | `dilution_1y`, `dilution_5y` (5Y history-gated), Reg. 31 counts on today's share basis (batch C, 2026-11-15) | **BUILT** |
| A53 | 1367-1368 | YoY sales-growth acceleration | G203 MISSING | B4.1 BUILDABLE NOW, B4.2 WHEN HISTORY | none | **CATALOGUE** |
| A54 | 1368-1369 | OPM expansion vs same quarter last year | G204 MISSING | B4.3 BUILDABLE NOW | base exists as `opm_last_year_pct`; no delta column | **CATALOGUE** |
| A55 | 1173-1174 | revision velocity / QoQ operating-margin acceleration | G152 MISSING | B4.4 BUILDABLE NOW | none | **CATALOGUE** |
| A56 | 1173, 1371-1372 | PEAD: abnormal return vs Nifty 500 and relative volume at T+0/1/5/20 after broadcast | G151 MISSING | B6.14 BUILDABLE NOW, B6.10 | none | **CATALOGUE** |
| A57 | 1374-1375 | sector earnings breadth in results season | G205 MISSING | B4.9 BUILDABLE NOW | none | **CATALOGUE** |
| A58 | 1390 | 20-day median daily traded value | G207 MISSING (bid-ask, circuit days) | B6.9 BUILT | `turnover_median_20d` | **BUILT** |
| A59 | 1390 | average bid-ask | G207 MISSING | none | none (no bid-ask in any ingested EOD file) | **DIGEST** |
| A60 | 1390-1391 | circuit-lock days | G207, G140 | B6.12 NEW FREE SOURCE | none | **CATALOGUE** |
| A61 | 1393-1394 | breadth: % Nifty 500 above 50/200 DMA, 52W high/low ratio, advance-decline | G208 DONE | B6.13 BUILT | `market_breadth` table | **BUILT** |
| A62 | 1470-1474 | reinvestment rate | G216 DOC_PLANNED | B2.6 BUILDABLE NOW | `reinvestment_rate` (batch C, 2026-11-15) | **BUILT** |
| A63 | 1476-1477 | cash ROIC (CROIC) | G217 DONE | B2.13 BUILT | `croic` | **BUILT** |
| A64 | 1483-1485, 2775-2776 | total shareholder yield (corrected: dividends + gross buybacks - gross issuance) | G218, G316 DOC_PLANNED | B2.2 BUILDABLE NOW | `shareholder_yield` (G316 formula) (batch C, 2026-11-15) | **BUILT** |
| A65 | 1516-1523 | incremental asset turnover 3Y | G220 DOC_PLANNED | B2.9 WHEN HISTORY | none | **CATALOGUE** |
| A66 | 1534-1535 | ROTE | G221 DONE | B2.13 BUILT | `rote` | **BUILT** |
| A67 | 1548-1550 | Sloan accrual ratio | G222 DONE | B1.6 BUILT | `sloan_accrual` | **BUILT** |
| A68 | 1558-1560 | EBITDA-to-CFO conversion (3Y cycle) | G223 DONE | B1.9 (3Y) WHEN HISTORY | `cfo_to_ebitda` (TTM); `cfo_to_ebitda_last_year` / `_preceding_year`, `cfo_to_ebitda_3y` (history-gated) (batch C, 2026-11-15) | **BUILT** |
| A69 | 1566-1580 | FCF-to-net-income conversion, 3Y sums | G224 DONE | B1.9 WHEN HISTORY, B1.8 | `fcf_to_pat` (TTM); `fcf_conversion_3y`, `fcf_{3,5,7,10}y` (history-gated) (batch C, 2026-11-15) | **BUILT** |
| A70 | 1586-1588 | receivables-to-sales divergence | G225 DONE | B1.10 BUILT | `receivables_sales_divergence` | **BUILT** |
| A71 | 1590-1592 | capex-to-depreciation | G226 DONE | B2.10 BUILT | `capex_to_depreciation` | **BUILT** |
| A72 | 1598-1607 | CWIP-to-gross-block | G227 DONE | B2.10 BUILT | `cwip_to_gross_block` | **BUILT** |
| A73 | 1616-1624 | degree of operating leverage | G228 DONE | B3.9 BUILT | `dol` | **BUILT** |
| A74 | 1626-1628 | gross-to-operating margin spread | G229 DONE | B3.9 BUILT | `gross_ebitda_spread` | **BUILT** |
| A75 | 1630-1632 | R&D and royalty intensity | G230 DONE | B3.8 BUILT | `rnd_and_royalty_intensity` | **BUILT** |
| A76 | 1638-1640 | working-capital intensity | G231 DONE | B3.1 BUILT | `working_capital_intensity` | **BUILT** |
| A77 | 1646-1648 | other-income dependency (OI / PBT) | G232 DONE | B1.13 BUILT | `other_income_to_pbt` | **BUILT** |
| A78 | 1660-1669 | net debt (incl. leases) / 3Y average FCF | G233 DONE | B2.14 BUILT (TTM; 3Y WHEN HISTORY) | `net_debt_to_fcf` (TTM); `net_debt_to_fcf_3y` (history-gated) (batch C, 2026-11-15) | **BUILT** |
| A79 | 1671-1680 | effective cost of debt | G234 DONE | B2.16 BUILT | `cost_of_debt` | **BUILT** |
| A80 | 1682-1686 | contingent liabilities / net worth | G235 DONE | B1.21 BUILT | `contingent_liabilities_to_net_worth` | **BUILT** |
| A81 | 1697-1701 | RPT leak % (purchases + loans given + royalties) / revenue | G236 DOC_PLANNED | B1.19 BUILDABLE NOW (total) / NEEDS PARSER (split) | `rpt_total_amount` only | **CATALOGUE** |
| A82 | 1703-1708 | composite forensic risk score (Piotroski + Beneish in one) | G237 OOS | B1.25 NOT POSSIBLE | separate columns (arch 10.2, owner review L2321) | **OOS** |
| A83 | 1717-1726, 2786-2787 | unlevered FCF yield (interest add-back only when interest is in CFO) | G238, G304 DONE | B5.11 | `fcff_yield`, per-filing `interest_paid_cfo_class` | **BUILT** |
| A84 | 1754-1763 | institutional absorption rate | G241 DOC_PLANNED | B7.5 BUILDABLE NOW (quarterly) | none | **CATALOGUE** |
| A85 | 1765-1777, 2788 | float-adjusted delivery velocity (corrected: divide by float) | G242, G315 DONE | B6.8 BUILT | `delivery_velocity`, `float_turnover_pct` | **BUILT** |
| A86 | 1788-1791 | financial cohort: NIM, cost-to-income, provision coverage, P/B | G246 DONE | none needed | `nim_asset_proxy`, `cost_to_income`, `pcr`, `pb` | **BUILT** |
| A87 | 1792-1794 | 3Y / 5Y smoothed windows for ROIIC, reinvestment, EBITDA-CFO | G247 OOS (mislabelled) | B2.8, B1.9 WHEN HISTORY | `incremental_roic_3y` / `_5y`, `cfo_to_ebitda_3y`, `fcf_conversion_3y`, 3-10Y cash-flow sums (history-gated) (batch C, 2026-11-15); smoothed reinvestment rate not built | **BUILT** (partial) |
| A88 | 1837-1846 | EV / gross profit | G250 DONE | B5.9 BUILT | `ev_to_gross_profit` | **BUILT** |
| A89 | 1848-1852 | ex-cash P/E | G251 DONE | B5.9 BUILT | `ex_cash_pe` | **BUILT** |
| A90 | 1854-1858 | EV / billings | G252 DONE | B5.9 BUILT | `ev_to_billings` | **BUILT** |
| A91 | 1860-1869 | EV / ESOP-adjusted EBITDA | G253 DONE | B5.9 BUILT | `ev_to_esop_adj_ebitda` | **BUILT** |
| A92 | 1871-1876 | price / operating cash flow | G254 DONE | B5.9 BUILT | `price_to_cfo` | **BUILT** |
| A93 | 1883-1885 | Rule of 40 (revenue growth + EBITDA margin) | G255 DONE | B4.7 BUILT | `rule_of_40` | **BUILT** |
| A94 | 1885 | Rule of 40 with **FCF margin** variant | none | none | none | **MISSED** (M3) |
| A95 | 1887-1908 | marketing efficiency (magic-number proxy) | G256 MISSING | B3.7 BUILDABLE NOW | ADVERTISING label rule only | **CATALOGUE** |
| A96 | 1910-1913 | contribution / gross margin expansion (bps) | G257 MISSING | B4.5 BUILDABLE NOW | none | **CATALOGUE** |
| A97 | 1916-1924 | ad & promotion intensity % | G258 MISSING | B3.6 BUILDABLE NOW | none | **CATALOGUE** |
| A98 | 1931-1933 | billings growth vs revenue growth | G259 DONE | B4.7 BUILT | `billings_growth_pct` | **BUILT** |
| A99 | 1935-1944 | negative working-capital float % | G260 DONE | B3.1 BUILT | `neg_working_capital_float_pct` | **BUILT** |
| A100 | 1946-1951 | net burn multiple | G261 DONE | B5.9 BUILT | `net_burn_multiple` | **BUILT** |
| A101 | 1953-1955 | cash runway (months) | G262 DONE | B5.9 BUILT | `cash_runway_months` | **BUILT** |
| A102 | 1961-1964 | ESOP-adjusted FCF | G263 DONE | B5.9 BUILT | `esop_adj_fcf` | **BUILT** |
| A103 | 1981-1986 | EV / GOV (annualised) | G265 MISSING | B5.10 BUILDABLE NOW (manual KPI) | `gov` column, no ratio | **CATALOGUE** |
| A104 | 1988-1990, 1995-2003, 2013-2029 | net take rate, contribution margin % of GOV, NRR, CAC payback | G264 DONE | none | `take_rate`, `contribution_margin`, `nrr`, `cac_payback` (manual `load-kpis`) | **BUILT** |
| A105 | 2005-2010 | ARPU and MTU growth % | G266 MISSING | not in catalogue | not in `KPI_UNITS` | **DIGEST** |
| A106 | 2039, 2651 | lending archetype: P/B, RoA, NIM, GNPA; bank advances, deposits, GNPA, NNPA | G246, G267 DONE | none | `roa`, `gnpa_pct`, `nnpa_pct`, `loans`, `credit_to_deposit` | **BUILT** |
| A107 | 2041, 2663-2665 | insurance archetype: VNB margin, combined ratio, solvency, persistency, EV, APE | G269, G341, G340, G313 | none | `vnb_margin`, `combined_ratio`, `solvency_ratio`, `persistency_13m/61m`, `embedded_value`, `ape_growth` | **BUILT** |
| A108 | 2041 | P/EV for life insurers | G270 MISSING | B5.10 BUILDABLE NOW | `embedded_value` loadable, no ratio | **CATALOGUE** |
| A109 | 2045-2048 | cross-sector columns usable in one query (Rule of 40, EV/GP, ex-cash PE) | G268 DONE | — | DSL aliases exist | **BUILT** |
| A110 | 2176-2180 | organic vs inorganic perimeter flag (`is_inorganic_perimeter`) | G276 MISSING | B8.12 NEEDS PARSER | none | **CATALOGUE** |
| A111 | 2185-2187 | standalone-to-consolidated profit leakage | G278 MISSING | B1.18 BUILDABLE NOW | both scopes parsed, no column | **CATALOGUE** |
| A112 | 2651-2652 | bank CASA % | G339 CONFLICTS ("goes to supplemental_kpis") | none | `KPI_UNITS` rejects `casa` | **MISSED** (M4) |
| A113 | 1048-1049, 1671-1673, 1717-1719 | ERP model; FCF yield and cost of debt vs live G-Sec / MCLR | G135 (feed only) | B10.2 (WACC only) | none | **MISSED** (M2) |
| A114 | 1290, 1018-1020 | market-cap size bucket (smallcap) / Midcap 150, Smallcap 250 membership | none | none | `in_nifty500` only | **MISSED** (M5) |
| A115 | 1408 | rs_rank (thesis snapshot field) | G212 | B6.3 BUILDABLE NOW | none | **CATALOGUE** |
| A116 | 767-768, 1254 | "exact same screener.in" ratio set (Screener gallery parity) | G89, G3 | Part A: 173 rows, 29 BUILT (+5 by e085eb5) | partial | **CATALOGUE** |
| A117 | 1259 | ~250-350 pre-computed columns | G166 DONE (~150) | Part C1 batches | 150+ columns | **BUILT** (partial by count) |
| A118 | 1360-1362 | capital-allocation scorecard as a whole | G201 DOC_PLANNED | B2 | components built (batch C, 2026-11-15): incremental ROIC, reinvestment rate, buyback / shareholder yield, dilution 1Y / 5Y; no combined view (arch 10.2) | **CATALOGUE** |


### B. Data sources

| # | Lines | Item | G (status) | Cat | Code / config | Class |
|---|---|---|---|---|---|---|
| B01 | 801-805, 1029 | Integrated Filing quarterly XBRL + Reg. 34 annual XBRL (statements, segments, notes) | G90 DONE | — | `parsers/integrated.py`, `parsers/reg34_annual.py` (F06, F07) | **BUILT** |
| B02 | 819-823 | Reg. 31 shareholding XBRL (promoter, FII, DII incl. MF / insurance / banks, public, pledge) | G91 DONE | — | `parsers/shareholding.py` (F08) | **BUILT** |
| B03 | 819-823 | SAST 31(1)/31(2) encumbrance events with lender details | G92 DOC_PLANNED | B7.10 NEW FREE SOURCE | F12 | **CATALOGUE** |
| B04 | 826-829, 904, 1498 | Reg. 76 share-capital audit (issued, listed, demat shares) | G93 DOC_PLANNED | — | F09 UNVERIFIED; Reg. 31 stands in (decision C) | **DIGEST** |
| B05 | 831-835 | full bhavcopy (`sec_bhavdata_full`) | G94, G101 DONE | — | F01, F02 | **BUILT** |
| B06 | 832-835, 911-913, 1156 | NSE 4-tier industry classification ("in the exchange equity master CSV") | G96 DOC_PLANNED, G334 | A1.19 note | `raw_index_snapshot.industry` (one tier) | **DIGEST** |
| B07 | 837-841 | corporate-actions feed + Reg. 30 board-outcome XBRL | G97 DONE | — | F03; outcome XBRL vaulted raw (E2) | **BUILT** |
| B08 | 843-847 | credit-rating disclosure XBRL | G98 DOC_PLANNED | A1.23, B8.9 NEW FREE SOURCE | F22 | **CATALOGUE** |
| B09 | 857-861 | Reg. 23(9) RPT XBRL | G99 DONE | B1.19 | `rpt_total_amount` (total only) | **BUILT** (partial) |
| B10 | 864-867 | PIT Reg. 7(2) and SAST Reg. 29 XBRL | G100 DOC_PLANNED | B7.8 NEW FREE SOURCE | F11, F12 | **CATALOGUE** |
| B11 | 869-873 | security-wise deliverable position CSV | G101 DONE | — | `raw_delivery` (F02) | **BUILT** |
| B12 | 869-873 | bulk and block deals CSV | G102 DOC_PLANNED | B7.9 NEW FREE SOURCE | F14 | **CATALOGUE** |
| B13 | 869-873 | short-selling CSV | G103 DOC_PLANNED | B6.16 NEW FREE SOURCE | F15 | **CATALOGUE** |
| B14 | 875-878 | Reg. 32(1) deviation / variation of issue proceeds | G104 DOC_PLANNED | — | F23 | **DIGEST** |
| B15 | 877-878 | audit qualifications in Integrated Filing | G105 DONE | B1.16 BUILDABLE NOW (column) | `filing_meta.audit_opinion`, `auditor_qualified` | **BUILT** |
| B16 | 887-891 | Reg. 44(3) voting results (dissent %) | G108 DOC_PLANNED | B10.5 NEW FREE SOURCE | F23 | **CATALOGUE** |
| B17 | 893-897 | BRSR XBRL (headcount, attrition, R&D, energy / water) | G109 DOC_PLANNED | B10.1 NEW FREE SOURCE | F24 | **CATALOGUE** |
| B18 | 964-968 | governance XBRL (Reg. 27, 13(3)) | G121 DOC_PLANNED | B10.5 NEW FREE SOURCE | F23 | **CATALOGUE** |
| B19 | 975-977, 1068 | AMFI monthly scheme-wise portfolios; month-on-month diff | G122, G312 DOC_PLANNED | B7.7 NEW FREE SOURCE | F26 | **CATALOGUE** |
| B20 | 979-980 | NSDL / CDSL fortnightly sector-wise FPI flows and AUC | G123 MISSING | — | not in data_sources.yaml | **DIGEST** |
| B21 | 982-983 | NSDL FPI trade-wise and 3% breach / limit reports | G124 MISSING | — | not in data_sources.yaml | **DIGEST** |
| B22 | 993-996 | F&O UDiFF bhavcopy: PCR, max pain, IV skew, long / short buildup | G125 DOC_PLANNED | B6.15 NEW FREE SOURCE (PCR, OI, max pain) | F16 | **CATALOGUE** |
| B23 | 999-1001 | participant-wise OI and volume (FII / DII / Pro / Client) | G126 DOC_PLANNED | — | F17 | **DIGEST** |
| B24 | 1004-1007 | MWPL and F&O ban list | G127 DOC_PLANNED | B6.17 NEW FREE SOURCE | F18 | **CATALOGUE** |
| B25 | 1010-1014 | SLBM bhavcopy (lending fee) | G128 DOC_PLANNED | B6.16 NEW FREE SOURCE | F19 | **CATALOGUE** |
| B26 | 1016-1020 | index constituent weightage files (free-float mcap, weights) | G129 MISSING | B10.4 NEW FREE SOURCE | not in data_sources.yaml | **CATALOGUE** |
| B27 | 1048-1055 | RBI DBIE / FBIL: repo, T-bills, 10Y G-Sec, USD/INR, CPI / WPI | G135 DOC_PLANNED | B10.2 NEW FREE SOURCE | F25 | **CATALOGUE** |
| B28 | 1057-1058 | corporate bond / CP secondary-market yields | G136 MISSING | — | not in data_sources.yaml | **DIGEST** |
| B29 | 1082-1091 | depository SDD (SAST-SDD, PIT-SDD) | G138 DOC_PLANNED | B7.8 NEW FREE SOURCE | F13 | **CATALOGUE** |
| B30 | 1100-1102 | ASM / GSM surveillance lists | G139 DOC_PLANNED | B6.17 NEW FREE SOURCE | F20 | **CATALOGUE** |
| B31 | 1100-1102 | trade-to-trade (BE/BZ) flag | none | none | `series` stored, no flag / alias | **MISSED** (M6) |
| B32 | 1104-1106 | daily price-band / circuit file | G140 DOC_PLANNED | B6.12 NEW FREE SOURCE | F20 | **CATALOGUE** |
| B33 | 1108-1110 | VaR / ELM margin files | G141 DOC_PLANNED | B6.17 NEW FREE SOURCE | F20 | **CATALOGUE** |
| B34 | 1122-1124 | daily buyback / redemption report | G142 MISSING | — | CA10 purpose only | **DIGEST** |
| B35 | 1127-1132 | NSE XML RSS feeds per filing type | G143 DONE | — | `parsers/discovery.py`, run-day RSS hint | **BUILT** |
| B36 | 1141-1143 | Reg. 50 / 52 debt XBRL of debt-listed subsidiaries | G145 DOC_PLANNED | — | F22 | **DIGEST** |
| B37 | 1145-1146 | REIT / InvIT XBRL (NDCF, distribution yield) | G146 OOS | — | C7 | **OOS** |
| B38 | 1152-1153 | RBI DBIE sectoral bank-credit deployment | G147 DOC_PLANNED | B10.2 NEW FREE SOURCE | F25 | **CATALOGUE** |
| B39 | 1155-1157 | IIP and RBI OBICUS mapped to basic industry | G148 DOC_PLANNED | B10.2 NEW FREE SOURCE | F25 | **CATALOGUE** |
| B40 | 1208-1213 | EXIM, card/UPI, SIAM, TRAI, IRDAI, CEA sector KPIs | G154 DOC_PLANNED | B10.2 NEW FREE SOURCE | F25 (card/UPI not listed) | **CATALOGUE** |
| B41 | 1232-1236 | IPO subscription (QIB / NII / retail) and 30/90-day anchor lock-in expiry | G163 MISSING | — | not in data_sources.yaml | **DIGEST** |
| B42 | 1343-1345 | debt-servicing XBRL (interest / redemption payment, default) | G195 DOC_PLANNED | — | F22 | **DIGEST** |
| B43 | 1347-1348 | annual secretarial compliance Reg. 24A (fines, non-compliances) | G196 DOC_PLANNED | — | F23 | **DIGEST** |
| B44 | 1347-1348 | CDR, OTS, CIRP / NCLT insolvency XBRL | G197 MISSING | — | E2 REG30_Restructuring vaulted raw | **DIGEST** |
| B45 | 2189-2192 | May-June 2026 Reg. 30 XBRL utilities (restructuring, CDR/OTS, search and seizure, forensic audit) | G279 MISSING | — | not in references.md | **DIGEST** |
| B46 | 2194-2197 | World Bank Pink Sheet, FRED, MCX, PPAC, CEA commodity spreads to basic industry | G280 DOC_PLANNED | B10.2 NEW FREE SOURCE | F25 (FRED not listed) | **CATALOGUE** |
| B47 | 268-279, 631-633, 637-654 | MCA AOC-4 XBRL annual backstop | G32 MISSING, G74 NEEDS_OWNER_DECISION | B10.6 NOT POSSIBLE | — | **OOS** (owner: no paid source) |
| B48 | 656-666 | free Reg. 34(1) annual XBRL instead of MCA | G76 DONE | — | F07 via NSE | **BUILT** |
| B49 | 736-740, 759 | BSE backfill of FY20-FY25 annual XBRL | G83 OOS | — | C9 | **OOS** |
| B50 | 761, 2492 | BSE fallback when an NSE download fails / throttles | G86 DOC_PLANNED | — | D-4, BSE unreachable (A1) | **DIGEST** |
| B51 | 2284-2286 | NSE-vs-BSE cross-check gate | none | none | none | **MISSED** (M7) |
| B52 | 2319-2320, 2663-2665 | insurer KPIs from presentations / IRDAI public disclosures | G313 DONE, G340 | — | `supplemental_kpis.source_kind` IRDAI_PUBLIC_DISCLOSURE; manual | **BUILT** |
| B53 | 1830, 1967-1976 | platform KPIs from shareholder letters (structured JSON) | G264 DONE | — | manual `load-kpis`; no fetcher | **BUILT** (manual) |
| B54 | 8-12, 14-47 | insurance and NBFC results are on NSE; separate taxonomies | G2, G5, G6 DONE | — | `parsers/indas_nbfc.py`, `igaap_bank.py`, `irdai_insurance.py` | **BUILT** |
| B55 | 24-26 | insurers only under a separate "Insurance" tab | G4 CONFLICTS | — | found via the integrated-filing endpoint | **BUILT** (claim corrected) |
| B56 | 700-747 | keep NSE primary; BSE secondary | G80, G82 DONE | — | C7 | **BUILT** |

### C. Corporate structure and identity

| # | Lines | Item | G (status) | Code | Class |
|---|---|---|---|---|---|
| C01 | 310-312 | permanent entity master, immutable entity_id; tickers change | G36 DONE | `entity_master`, `securities` | **BUILT** |
| C02 | 311-312 | directed lineage table (parent, child, relation, effective date, swap ratio) | G37 DOC_PLANNED | `corp_actions.related_entity_id` only | **DIGEST** |
| C03 | 496-498 | merger: delisting circular sets MERGED, merged_into, swap_ratio | G56 DOC_PLANNED | MERGED only for duplicate repair (D-6) | **DIGEST** |
| C04 | 514-515 | daily master sync: symbol master, ISIN changes, new listings, delistings | G60 DONE | F28 `raw_equity_master`; NSE only | **BUILT** |
| C05 | 686-688, 756, 2528 | map NSE symbols to BSE scrip codes | G79 DONE | filled from the in-filing ScripCode at promotion (X111, `filing_checks.py`, 2026-11-15 batch E) | **BUILT** |
| C06 | 751 | key the master on ISIN | G85 CONFLICTS | security_id + FinInstrmId / ISIN history (invariant 3) | **BUILT** (corrected) |
| C07 | 2162-2174 | dual-ISIN (INE + IN9 partly paid / DVR) under one entity; market cap summed | G275 DOC_PLANNED | only COMMON securities created (`promoter.py:236`); BLOCKED: two-class listings exist (P17) but shares per class are unknown and partly-paid E1 is outside the universe | **DIGEST** |
| C08 | 2184-2187 | AOC-1 subsidiary / associate / JV tree (name, %, net worth, turnover, PAT) | G277 DOC_PLANNED | not parsed (X75) | **DIGEST** |
| C09 | 2266-2267 | tables entity_securities, subsidiary_tree, pipeline_audit_log | G292 DONE | `securities`, `promotion_log`, `admin_log`; no subsidiary_tree | **BUILT** (partial; §2) |
| C10 | 2283-2284 | surrogate security_id + dated ISIN / symbol history | G295 DONE | `security_identifier_history` | **BUILT** |
| C11 | 2305-2306 | DVR shares get INE ISINs, only partly-paid IN9 | G306 CONFLICTS | P17: DVRs carry IN9 (JISLDVREQS, FELDVR) or INE (GATECHDVR); partly-paid IN9 + E1 | **BUILT** (corrected) |
| C12 | 2513-2520, 2531 | share classes COMMON / DVR / PARTLY_PAID, voting_rights_ratio, face_value per identifier | G336 DOC_PLANNED | `securities.share_class`; no voting-rights ratio; BLOCKED as G275 (no fixture states a DVR voting ratio or face value) | **DIGEST** |
| C13 | 2035-2043 | valuation_archetype per company, classified automatically | G267 DONE | `derived_archetype`, `reference/valuation_archetypes.csv`, override | **BUILT** |
| C14 | 2503-2504 | accounting_profile and archetype on entity_master | G333 OOS | per filing / per as-of (invariant 5) | **OOS** |
| C15 | 2505-2508 | macro sector, sector, industry, basic industry on the master | G334 DOC_PLANNED | `entity_classification_history` not built | **DIGEST** |
| C16 | 2502 | cin UNIQUE | G335 CONFLICTS | no nullable UNIQUE (invariant 13) | **BUILT** (corrected) |
| C17 | 2509-2510 | status ACTIVE / MERGED / DELISTED, inactive_date | G206 DONE | `inactive_date`, `exit_reason` | **BUILT** |
| C18 | 148-150 | company override table (forced_profile, custom_revenue_tags) | G22 OOS | audited scope / archetype overrides instead | **OOS** |
| C19 | 2431-2433, 716-718 | universe NSE mainboard EQ/BE/BZ, Nifty 500 first, expandable; SME out | G308, G331 DONE; G81, G301 OOS | `--universe nifty500|active`; C7 | **BUILT** |
| C20 | 1336-1338 | ace-investor entity graph across Reg. 31 > 1% holders, PIT/SAST, bulk/block | G194 DOC_PLANNED | B7.6 partial (`shareholding_major_holders`, names not normalised) | **CATALOGUE** |

### D. Events, flows and corporate actions

| # | Lines | Item | G (status) | Code | Class |
|---|---|---|---|---|---|
| D01 | 292-293 | zero-human-intervention corporate-action adjustment (mergers, demergers, splits) | G33 OOS | automatic for parsed purposes and named rules; unknowns quarantine (invariant 9, owner review G298) | **OOS** |
| D02 | 298-301, 481 | adjust per-share series; never multiply absolute financials | G34, G53 DONE | invariant 8 | **BUILT** |
| D03 | 314-319 | immutable raw ledger + CA ledger keyed (entity, ex_date); recompute cumulative factors | G35, G38 DONE | `corp_actions`, `rebuild-market` | **BUILT** |
| D04 | 322-324, 517-518 | evening job polls CA feed + bhavcopy; deterministic purpose rules | G40 DONE | `run-day`; not scheduled (§2) | **BUILT** |
| D05 | 326-335 | split F = Y/X | G41 DONE | `corp_actions.py` | **BUILT** |
| D06 | 337-347 | bonus F = B/(A+B) | G42 DONE | `corp_actions.py` | **BUILT** |
| D07 | 349-362 | rights factor | G43 DONE | `corp_actions.py` | **BUILT** |
| D08 | 323-324 | historical volumes divided by F | G44 DONE | arch 11.1 | **BUILT** |
| D09 | 372-374, 2737 | extraordinary dividends > 5% adjust prices | G45 OOS | C2; dividends feed `returns.total_return_index` | **OOS** |
| D10 | 391-408, 2755-2772 | overnight gap auditor; verify parsed factor | G46, G318 DONE | daily, 10% (C4), `UNEXPLAINED_GAP` quarantine | **BUILT** |
| D11 | 410-412 | derive F from the pre-open price when missing / mismatched | G47 OOS | invariant 9 | **OOS** |
| D12 | 438-459 | demerger factor = special pre-open price / prior close | G48 DONE | `test_demerger_factor_is_observed_gap` (uses ex-date open) | **BUILT** |
| D13 | 459 | apply demerger factor to historical EPS | G50 OOS | invariant 8 (eps_factor 1.0) | **OOS** |
| D14 | 467-470, 520-523 | COA / swap-ratio watcher; COA sums to 100%; tax cost basis | G51 DOC_PLANNED, G62 MISSING | `corp_actions.coa_pct` column only | **DIGEST** |
| D15 | 476-477 | spun-off entity starts at listing date, no synthetic bars | G52 DONE | C12, `test_demerger_and_listing.py` | **BUILT** |
| D16 | 500-502 | merger: acquirer prices not back-adjusted | G57 DOC_PLANNED | merger purposes quarantine as UNKNOWN | **DIGEST** |
| D17 | 517-518 | adjusted overnight gap within +-15% | G61 DONE | +-10% (arch 11.3) | **BUILT** |
| D18 | 2686-2692 | split creates a new ISIN row; bonus keeps ISIN | G295 | identity + CA13 named rule | **BUILT** |
| D19 | 940-943 | Reg. 30 order wins (client type, value, timeline) | G114 DONE | `order_wins_90d`, `order_value_90d` | **BUILT** |
| D20 | 946-947 | fraud / default / arrest / forensic audit | G116 DONE | `fraud_or_default_90d` (amount free text) | **BUILT** |
| D21 | 949-952 | regulatory / judicial actions, penalty quantum | G118 DOC_PLANNED | `penalties_90d` NULL (E12 UNVERIFIED) | **DIGEST** |
| D22 | 955-956, 881-885 | auditor / KMP / director resignations | G106 DONE | `kmp_resignations_90d`, `auditor_resignations_90d` | **BUILT** |
| D23 | 958-959 | allotments, preferential, QIP, warrants (price, allottees, dilution, warrant conversions) | G119 DONE | events stored; B8.2 count/dilution BUILDABLE NOW | **BUILT** (partial) |
| D24 | 961-962 | agreements, JVs, MoUs (counterparty, stake) | G120 DOC_PLANNED | vaulted raw | **DIGEST** |
| D25 | 881-885 | Reg. 30 scheme of arrangement (merger / demerger) filings | G107 DOC_PLANNED | vaulted raw | **DIGEST** |
| D26 | 1328-1330 | analyst / investor meet XBRL (funds, dates; clusters) | G192 DOC_PLANNED | vaulted raw | **DIGEST** |
| D27 | 1332-1334 | forward calendar: board intimations, AGM / EGM notices | G193 DOC_PLANNED | B8.10 NEEDS PARSER | **CATALOGUE** |
| D28 | 2218 | watchlist alerts on SDD / PIT insider clusters | G282 DOC_PLANNED | needs F11 / F13 | **DIGEST** |

### E. Data quality, normalisation, PIT rules and assistant claims

| # | Lines | Item | G (status) | Code | Class |
|---|---|---|---|---|---|
| E01 | 8-12 | one consistent, rule-based treatment for every company | G1 DONE | `statements/quarterly.py`, C11 | **BUILT** |
| E02 | 11-12 | a complete database matching other websites | G3 DONE | `tests/test_screener_parity.py` | **BUILT** |
| E03 | 54-64 | Screener corporate vs financial template | G8 CONFLICTS | S4, S5 | **BUILT** (claim corrected) |
| E04 | 66-72, 124 | excise duty deducted from sales | G9 DONE | EXCISE_DUTY label rule | **BUILT** |
| E05 | 74-80 | exceptional items stripped from core earnings | G10 CONFLICTS | `core_profit_ttm` | **BUILT** |
| E06 | 82-90 | director remuneration moved into employee cost | G11 MISSING (claim) | unverified competitor claim | **DIGEST** |
| E07 | 86-88 | current maturities + Ind AS 116 leases into borrowings | G12 DONE | `statements/balance_sheet.py` | **BUILT** |
| E08 | 92-98 | Screener overwrites history after restatements | G13 OOS | C12, invariant 4 | **OOS** |
| E09 | 107-108 | digit-for-digit Screener match is a trap | G14 DONE | S13 residuals pinned | **BUILT** |
| E10 | 111-112 | route each filing by namespace into profile parsers | G15 DONE | 7 profiles; UNKNOWN_TAXONOMY | **BUILT** |
| E11 | 114-115 | ingest current and comparative columns | G16 CONFLICTS | X2: none exist | **BUILT** (corrected) |
| E12 | 115-116 | store filing date with period end | G17 DONE | `visible_from_ts` | **BUILT** |
| E13 | 122-128 | corporate profile Sales / Opex / EBITDA | G18 DONE | arch 8 | **BUILT** |
| E14 | 130-135 | lending profile; `profit_basis = FINANCING` flag | G19 DONE | `valuation_archetype` FINANCIAL_LENDING, `nii_ttm`, `ppop_ttm` | **BUILT** |
| E15 | 137-141 | insurance profile revenue / operating surplus | G20 DONE | filed subtotals | **BUILT** |
| E16 | 144-146 | restatement detection by comparing comparatives; supersede | G21 CONFLICTS | YTD identity X80 + X106 instead | **BUILT** (corrected) |
| E17 | 160-161 | confirm XBRL has no previous-quarter values | G23 DONE | X2 | **BUILT** |
| E18 | 161 | confirm corrections / restatements filed as XBRL | G24 DONE | `filing_revisions` | **BUILT** |
| E19 | 162-163 | extract notes / adjustments from annual-report PDFs with code | G25 DONE | Reg. 34 XBRL; PDF-verified corrections X107 | **BUILT** |
| E20 | 173-180 | contexts OneD / FourD / OneI / FourI | G26 DONE | context ids never trusted | **BUILT** |
| E21 | 199-205 | same-period correction: latest submission per (symbol, period, scope) | G27 DONE | as-of only | **BUILT** |
| E22 | 208-214 | retrospective restatement from quarterly PDF / annual report | G28 NEEDS_OWNER_DECISION (settled by decisions A, B) | YTD bridge + `restatement_suspected`; `fact_corrections` | **DIGEST** (status update due) |
| E23 | 220-231 | annual-report PDF pitfalls | G31 OOS | — | **OOS** |
| E24 | 233-266 | 3-stage PDF pipeline; note tie-out, BS identity, scale checks | G29, G30 OOS | decision B path instead | **OOS** |
| E25 | 484-491 | Ind AS 105 PDF comparator; carve-out baseline | G54, G55 OOS | X80 withholds TTM | **OOS** |
| E26 | 504-506 | Ind AS 103 common-control vs acquisitions | G59 MISSING (claim) | not in references.md | **DIGEST** |
| E27 | 526-529, 599-619 | restatement checksums (continuing + discontinued, A + B, YTD) | G63 OOS | owner review L2312-2314 | **OOS** |
| E28 | 538-547 | scanned PDFs must never corrupt the DB | G64 DONE | invariant 9; corrections need two agreeing reads | **BUILT** |
| E29 | 549-566 | skip PDFs; YTD vs sum-of-quarters identity; ~95% hold | G65, G66 DONE | `audit-ytd`, X80 | **BUILT** |
| E30 | 567-569 | also flag on discontinued ops != 0 or a logged demerger / merger | G67, G68 DONE | `FactBook.restatement_triggers`: YTD (X106), discontinued ops (X108), merger / demerger (X109); Reg. 34 prior-year comparison as a finding (G328, X110) | **BUILT** |
| E31 | 573-578 | XBRL anchor locking of PDF columns | G69 DOC_PLANNED | — | **DIGEST** |
| E32 | 580-593 | unit detection by ratio; +-0.01% / +-0.02 tolerance | G70, G71 CONFLICTS | G310: rounding-unit tolerance | **BUILT** (corrected) |
| E33 | 599-601 | vertical P&L identities | G72 DONE | gate G3 | **BUILT** |
| E34 | 627-628 | safe failure: keep verified XBRL | G73 DONE | invariant 9 | **BUILT** |
| E35 | 1162-1167 | bitemporal rows: period end + broadcast timestamp (also shareholding) | G149 DONE | `visible_from_ts` on facts and `shareholding_meta` | **BUILT** |
| E36 | 1165-1166 | broadcast timestamp embedded in XBRL / CSV | G150 CONFLICTS | captured at fetch (G311) | **BUILT** (corrected) |
| E37 | 1396-1398 | compare quarters by calendar period-end dates | G209 DONE | invariant 6 | **BUILT** |
| E38 | 1784-1786 | NULL on non-positive denominators | G243 DONE | arch 10 | **BUILT** |
| E39 | 1785-1786 | expose raw numerator / denominator columns | G244 DOC_PLANNED | not in `screener_features` | **DIGEST** |
| E40 | 1788-1791, 2785-2786 | NULL industrial ratios for financials; Beneish NULL for financials; Altman NULL for financials | G245 DONE | `_NOT_FOR_LENDERS`; annual ratios industrial-only (`features.py:631-633`) | **BUILT** |
| E41 | 1810-1820 | new-gen distortions: expensed growth capex, treasury cash, ESOP, contract liabilities | G248, G249 DONE | label rules; new-gen columns | **BUILT** |
| E42 | 2120-2130, 2669-2670 | scope continuity (consolidated only with 4 consolidated quarters) | G272 DONE | C18 | **BUILT** |
| E43 | 2132-2150, 2672-2674 | semi-annual CF / BS TTM bridge; carry forward latest net debt; as-of dates | G273, G319 DONE | `cf_as_of`, `bs_as_of` | **BUILT** |
| E44 | 2152-2160 | period_months gating (SME 6M vs mainboard 3M) | G274 DONE | invariant 6 | **BUILT** |
| E45 | 2224-2232 | pre-publish gates: namespace registry, row-count, null-rate | G284, G285, G286 DONE | `tag_registry.yaml`, G1 (92%), G4 (1.5 pp) | **BUILT** |
| E46 | 2234-2235, 2269 | SHA-256 vault for offline replay | G287 DONE | `vault.py` | **BUILT** |
| E47 | 2234-2235, 2436 | vault in Cloudflare R2 | G288 OOS | CLAUDE.md Don'ts | **OOS** |
| E48 | 2270 | calculation-linkbase auto-mapping of unknown tags | G290 OOS | invariant 9 | **OOS** |
| E49 | 2270 | multi-mirror NSE <-> BSE failover | G291 DOC_PLANNED | D-4 | **DIGEST** |
| E50 | 2278-2281, 2676-2677 | PIT key incl. visibility; Q4 vs Reg. 34 annual precedence | G293, G294 DONE | `fact_observations` PK | **BUILT** |
| E51 | 2284-2286 | price table needs exchange and series columns | G296 DONE | `ohlcv` PK | **BUILT** |
| E52 | 2286-2287 | CA engine must ship with Phase 1 momentum | G297 DONE | arch 15 | **BUILT** |
| E53 | 2288-2291 | quarantine plus review queue, not auto-heal | G298 DONE | `quarantine` CLI | **BUILT** |
| E54 | 2291-2293 | banks: interest earned / expended, provisions | G299 DONE | `igaap_bank.py` | **BUILT** |
| E55 | 2291 | insurers not on Ind AS | G300 CONFLICTS | Ind AS 117 parsed (X64) | **BUILT** (corrected) |
| E57 | 2294 | current maturities inside short-term borrowings | G302 DONE | arch 8 | **BUILT** |
| E58 | 2295-2296 | leases counted once | G303 DONE | X39 | **BUILT** |
| E59 | 2304-2305 | EPS adjusted only for splits, bonuses, rights bonus element | G305 DONE | invariant 8 | **BUILT** |
| E60 | 2306-2308 | 15-month transition periods | G307 DONE | period_months 1..18 | **BUILT** |
| E61 | 2310-2312 | YTD identity misses re-presentations; trivial in Q4 | G309 DONE | arch 6.2 | **BUILT** |
| E62 | 2314-2316 | unit table omits millions; tolerance from rounding unit | G310 DONE | X4, X5 | **BUILT** |
| E63 | 2316-2317, 2493 | capture broadcast time at fetch | G311 DONE | listing / RSS | **BUILT** |
| E64 | 2317-2319 | AMFI publishes per-AMC files (verify) | G312 DOC_PLANNED | R8 | **DIGEST** |
| E65 | 2319-2320 | zero-PDF fails for insurer / new-gen KPIs | G313 DONE | `supplemental_kpis` | **BUILT** |
| E66 | 2321-2323 | forensic scores never summed; Altman not for financials | G314 DONE | arch 10.2 | **BUILT** |
| E67 | 2325-2326, 2780-2781 | gross profit defined (materials + purchases + inventory change; NULL for services) | G317 DONE | C6 | **BUILT** |
| E68 | 2329-2336 | missing tables; long-format facts with wide view | G320, G321 DONE | schema.sql | **BUILT** |
| E69 | 2335-2337 | one runtime | G322 DONE | — | **BUILT** |
| E70 | 2337-2343 | register unverified claims (BSE notice, schemas, Tata, BRSR tags, RSS list, Screener rules) | G323 DOC_PLANNED (partly) | references.md | **DIGEST** |
| E71 | 2343, 2420-2422 | UDiFF names and columns | — (C9) | `parsers/udiff.py` | **BUILT** |
| E72 | 2343-2346, 2428-2429 | legal / licensing; personal; polite fetching with UA and caching | G324, G330 DONE | C8, PoliteFetcher | **BUILT** |
| E73 | 2346-2348, 2439-2441 | golden fixtures (~20 companies), thin slice, real XBRL per profile first | G325, G326, G342, G343 DONE | `tests/fixtures` | **BUILT** |
| E74 | 2604 | `is_audited` on every fact row | not in digest | `filing_meta.audited` | **BUILT** |
| E75 | 2601 | `VERIFIED_PDF_SUPP` source type | G28 / decision B | `fact_corrections` (X107) | **BUILT** (in progress per decision B) |
| E76 | 2348-2351 | short CLAUDE.md; blueprint in architecture.md | G327 DONE | — | **BUILT** |
| E77 | 2546-2547 | prices / values as REAL | G337 OOS | invariant 7 | **OOS** |
| E78 | 42-44 | Integrated Filing from Dec 2024 / Mar 2025 | G7 CONFLICTS | C9, X38 | **BUILT** (corrected) |
| E79 | 305-306, 2390-2396 | Tata Motors 60:40 indicative, final 68.85 / 31.15, dates | G39 MISSING, G329 DOC_PLANNED | R7 | **DIGEST** |
| E80 | 641-654 | AOC-4 thresholds, deadline, XML in PDF, fees | G75 MISSING (claim) | — | **DIGEST** |
| E81 | 657-660, 782-784, 2370-2377 | BSE circulars; Single Filing System dates; NSE/CML/2026/08 | G77 MISSING, G78 DOC_PLANNED | R1 | **DIGEST** |
| E82 | 772-775 | quarterly XBRL identical on NSE and BSE (in-capmkt) | G87 MISSING (claim) | — | **DIGEST** |
| E83 | 1396-1398, 2409-2413 | Nestle / ABB / Siemens / Bosch fiscal years | G210 CONFLICTS | X87 | **BUILT** (corrected) |
| E84 | 744-747 | NSE needs Akamai cookies; BSE JSON cleaner | G84 CONFLICTS | A1, A7 | **BUILT** (corrected) |
| E85 | 438 | NSE special pre-open session on demerger ex-dates | G49 MISSING (claim) | P7 open price only | **DIGEST** |

### F. Backtest

| # | Lines | Item | G (status) | Code | Class |
|---|---|---|---|---|---|
| F01 | 476-477 | spun-off entity: no synthetic pre-listing bars | G52 | `test_demerger_and_listing.py` | **BUILT** |
| F02 | 502 | positions in the target convert into acquirer shares by swap ratio | G58 DOC_PLANNED | — | **DIGEST** |
| F03 | 1170-1171 | PIT queries `broadcast <= backtest_date` | G149 DONE | `visible_from_ts <= as_of` | **BUILT** |
| F04 | 1306-1308 | quarter-end feature snapshots; historical screens | G190 DONE | `screener_features_history` (daily), `screen --as-of` | **BUILT** |
| F05 | 1294-1308, 2803-2804 | point-in-time screen backtester | G191 DOC_PLANNED | stock TRI exists (`returns.total_return_index`); benchmark TRI F29 UNVERIFIED | **DIGEST** |
| F06 | 1387-1388 | survivorship-free universe with inactive_date, exit_reason | G206 DONE | `entity_master` | **BUILT** |
| F07 | 2330-2331 | historical index constituents for survivorship-free breadth | G320 DONE | `index_constituents_history` | **BUILT** |
| F08 | 2286-2288 | Phase 1 momentum must not show fake split returns | G297 DONE | adjusted closes, GAP freeze | **BUILT** |

### G. Alerts, UI, tools and operations

| # | Lines | Item | G (status) | Code | Class |
|---|---|---|---|---|---|
| G01 | 767-768 | personal website like Screener | G89 NEEDS_OWNER_DECISION | none | **DIGEST** |
| G02 | 1184-1185 | screening queries are a must | G153 DONE | `dsl.py`, `screen` | **BUILT** |
| G03 | 1257-1260 | one wide nightly feature table | G166 DONE | `screener_features` | **BUILT** |
| G04 | 1278-1279 | alias dictionary | G185 DONE | `dsl.ALIASES` (138) | **BUILT** |
| G05 | 1281-1282 | arithmetic, AND/OR/NOT, comparisons to parameterised SQL | G186 DONE | `compile_screen` | **BUILT** |
| G06 | 1284-1285 | saved custom ratios expand inline | G187 DONE | `save_custom_ratio` (no CLI) | **BUILT** (partial) |
| G07 | 1285 | custom ratios as **custom results columns** | none | output = WHERE metrics only | **MISSED** (M1) |
| G08 | 1289-1292 | natural-language to DSL translator, formula shown for editing | G188 MISSING | none | **DIGEST** |
| G09 | 1296-1297 | daily screen alerts on entry / exit | G189 DOC_PLANNED | none | **DIGEST** |
| G10 | 1238-1244 | concall / presentation / DRHP RAG with citations | G164 NEEDS_OWNER_DECISION | none | **DIGEST** |
| G11 | 1246-1250 | custom Excel / DCF model exporter | G165 MISSING | `export-bundle` Parquet only | **DIGEST** |
| G12 | 1404-1405 | portfolio overlap, sector weights, weighted PE / ROCE, correlation | G211 NEEDS_OWNER_DECISION | none | **DIGEST** |
| G13 | 1407-1409 | PIT thesis snapshot / post-mortem (watchlist) | G212 NEEDS_OWNER_DECISION | none | **DIGEST** |
| G14 | 1411-1427, 2795-2804 | three-phase roadmap | G213 DONE | arch 15 | **BUILT** |
| G15 | 2202-2213 | synchronised price + fundamental charts | G281 NEEDS_OWNER_DECISION | none | **DIGEST** |
| G16 | 2215-2220 | post-EOD diff engine and digest (Telegram / email / inbox) | G282 DOC_PLANNED | none | **DIGEST** |
| G17 | 2222 | 52W high on > 2x 20-day median delivery | G283 MISSING | B6.11 BUILDABLE NOW (flag) | **CATALOGUE** |
| G18 | 1134-1135 | poll RSS every 1-2 minutes | G144 OOS | CLAUDE.md Fetching | **OOS** |
| G19 | 2228-2229 | schema-drift alert while parsers keep running | G284 DONE | UNKNOWN_TAXONOMY quarantine, registry audit | **BUILT** |
| G20 | 2244-2246, 514-523 | self-healing, autonomous from next quarter; 08:00 master sync, 18:00 adjuster, hourly watcher | G289 DONE | `run-day`; schedule in arch §13 but **no scheduler shipped** | **BUILT** (partial; §2) |
| G21 | 2052-2054, 2078, 2104 | compile everything into one double-checked document | G271 IN_PROGRESS | digest + catalogue + this file | **DIGEST** |
| G22 | 921-922, 1077 | beat Screener / Tijori / Trendlyne with machine-readable data; what is still missing | G113 DOC_PLANNED, G137 IN_PROGRESS | — | **DIGEST** |
| G23 | 1184-1188 | survey all competitor and new-generation sites for inputs | (G113 goal only) | none | **MISSED** (M8) |
| G24 | 2436-2437 | read-only SQLite / D1 export for a UI | G332 OOS | CLAUDE.md Don'ts | **OOS** |

---

## 4. Proposed batches for everything open (MISSED rows slotted into the catalogue's batch plan)

| Batch | MISSED rows added | Already-captured rows it closes (examples) |
|---|---|---|
| 0. DSL / CLI | M1 (output columns + `save-ratio` CLI), M6 (T2T alias) | G187 CLI gap; aliases for `shares`, `restatement_suspected`, `book value` per share (catalogue C2) |
| 1-3. FactBook period lines, BS, CF | — | A4/A5/A6/A7 families; fix `opm_last_year_pct` naming and add FY OPM last year; 3Y forms of G224 / G233 and 20Q of G240 returning NULL (history-gated). **DONE 2026-11-15**: batch A (P&L, `features_pl`), batch C (BS / CF / capital allocation, `features_bs`, incl. the G224 / G233 / G240 forms) |
| 4. Price / technicals | (M6 if not in 0) | DONE 2026-11-15 (batch B): G95, G156-G158, G183, G207 median, G208, 52W low (G94 gap). Open: G283 flag, RS rank, volatility / drawdown, volume spike |
| 5. Ownership, events, KPIs | M4 (CASA KPI) | DONE 2026-11-15 (batch D, ownership part): FII / DII / MF change QoQ, unpledged promoter, shareholder counts, MF / insurance / retail holding (A3.5, A3.8, A3.10, A3.11, B7.1-B7.3), plus the hidden-gem signals, hats and saved screens (docs/hidden_gems.md; G168, G203, G204). Open: G241, G119 dilution column, pledge change (B7.4), >1% holder count (B7.6), event flags (B8.2-B8.7), single Reg. 30 red-flag count (G181 gap), M4 |
| 6. Valuation / cross-section | M3 (Rule of 40 FCF form), M5 (size bucket proxy) | G112, G199, G205, G265, G270, G278 |
| Docs | M8 (competitor inventory) | update digest statuses (§2 stale list) |
| Phase 3 sources | M2 (G-Sec / MCLR spreads, ERP), M7 (NSE-vs-BSE check) | F25, F29, F11-F20, G86 / G291 |
