# Architecture: Indian Equity Research & Screening Engine

Claim IDs in brackets (e.g. [X2], [P5]) point to `docs/references.md`. Anything marked
UNVERIFIED there must not be hard-coded; code that depends on it quarantines on surprise.

---

## 1. Scope

- **Purpose:** personal, single-user research, screening and point-in-time (PIT) backtesting. No redistribution [C8].
- **Universe v1:** NSE Mainboard `EQ`, `BE`, `BZ`, starting with the Nifty 500 [C7]. SME (`SM`, `ST`) out of scope. BSE is used only as a fallback and for historical Reg. 34 annual XBRL backfill.
- **Data scope (v1, CHOICE [C9]):** `trade_date >= 2024-10-01` for prices, delivery, corporate actions and index snapshots; `period_end >= 2024-12-31` for financials and shareholding (`financials/scope.py`). Promotion returns `OUT_OF_SCOPE` for older inputs (vaulted, not parsed); `fetch-days` / `fetch-corp-actions` clamp start dates. Multi-year windows use `fundamentals.cagr(..., min_periods_required)` and stay NULL until enough in-scope quarters exist.
- **Non-goals (v1):** multi-user, UI hosting, Cloudflare (R2/D1/Workers), real-time intraday prices, SME/Indian-GAAP corporates.

## 2. Runtime topology

| Where | What runs |
|---|---|
| **Local machine** (owner's) | All fetchers (both `www.nseindia.com` session-cookie fetchers and `nsearchives.nseindia.com` archive fetchers), the vault, staging Parquet, the promoter, `data/market.duckdb`. |
| **GitHub Actions** | Offline `pytest` on every push and PR (`.github/workflows/ci.yml`). Tests never touch the network. |

Decision **D-1** (owner, 2026-11-13): GitHub Actions runs only offline lint + tests; all fetching stays local (`data/` gitignored) until the pipeline is proven end to end. `www.nseindia.com/api/` endpoints also answered from a cloud container [A1], but that is not relied on.

Operator commands (`python -m financials --data-dir data …`):

| Command | Effect |
|---|---|
| `init-db` | apply `schema.sql` to `data/market.duckdb` |
| `fetch-days START [END]`, `fetch-corp-actions START END`, `fetch-holidays`, `fetch-index --as-of D`, `fetch-shareholding SYM…`, `fetch-results URL [--broadcast-utc TS]` | download → vault → staging only |
| `promote` | the single writer: applies pending stages in order (holidays, market days by date, index snapshots, corporate actions, results, shareholding, raw-only) and records them in `promotion_log`; ABORTED batches stay pending |
| `materialize D` | builds features for `D` with gates G4/G5 |
| `screen "QUERY" [--as-of D]` | runs a DSL screen on the live table or point-in-time on history |
| `quarantine list [--stage --reason --entity --security --all]`, `quarantine resolve --id Q --action A --note N [--payload-json J]` | audited quarantine resolution (D-6) |
| `extract-index-changes TEXT_DIR --out CSV`, `backfill-index --manifest CSV` | index membership before the first snapshot (§11.6) |
| `python -m financials.bench --out docs/benchmarks.md` | reproducible benchmarks on the fixtures (`docs/benchmarks.md`) |

### 2.1 Data flow

```
fetchers (many, parallel)                 promoter (exactly one process)
  │  download → sha256 → data/vault/        │  reads staging Parquet
  │  write filings row + raw rows to        │  runs quality gates (§12)
  │  data/staging/<job>/<run_id>.parquet    │  resolves identifiers
  ▼                                         │  writes canonical + derived tables
data/vault/ab/ab12…ef.<ext>   ───────────▶  ▼  in one DuckDB transaction
                                          data/market.duckdb
```

- Fetchers and parsers **never open `market.duckdb` for writing**. DuckDB allows one writer process.
- Parsing is a pure function of (blob bytes, `parser_version`). Any parser change can be replayed from the vault with no network.

## 3. Data sources

| Dataset | Source | Format | Status | Phase |
|---|---|---|---|---|
| Daily prices + identifiers | `nsearchives…/content/cm/BhavCopy_NSE_CM_0_0_0_<YYYYMMDD>_F_0000.csv.zip` | UDiFF CSV in zip | VERIFIED [P1] | 1 |
| Daily delivery | `nsearchives…/products/content/sec_bhavdata_full_<DDMMYYYY>.csv` | CSV, no ISIN | VERIFIED [P10] | 1 |
| Index constituents (current) | `nsearchives…/content/indices/ind_nifty500list.csv` | CSV | VERIFIED [IDX1, IDX2] | 1 |
| Quarterly results XBRL | `nsearchives…/corporate/xbrl/<file>.xml`; discovery via `www.nseindia.com` API | XBRL | Files VERIFIED [X1]; discovery UNVERIFIED [A7] | 1 (corp), 2 (others) |
| Reg. 30 event XBRL | `content/RSS/Online_announcements.xml` → `corporate/xbrl/` links | RSS + XBRL | OBSERVED [A3] | 3 |
| Corporate actions | `www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=…&to_date=…` | JSON | VERIFIED [P12, CA1-CA9] | 1 |
| Corporate actions (discovery) | `nsearchives…/content/RSS/Corporate_action.xml` (no symbol/ISIN) | RSS | VERIFIED [CA6] | discovery only |
| Trading holidays | `www.nseindia.com/api/holiday-master?type=trading` | JSON (current year) | VERIFIED [CAL1] | 1 |
| Shareholding (Reg. 31) | `www.nseindia.com/api/corporate-share-holdings-master?index=equities&symbol=X` → `nsearchives…/corporate/xbrl/SHP_*.xml` | JSON + XBRL | VERIFIED [SHP1-SHP6] | 1 |
| Reg. 34 annual XBRL | UNVERIFIED [R2] | XBRL | — | 2 |
| F&O, SLBM, AMC portfolios, macro | UNVERIFIED | various | — | 3 |

Fetch etiquette (implemented in `financials.fetch.http.PoliteFetcher`): ≥1 s between requests per host, at most 4 attempts with jittered exponential backoff on 403/429/5xx, other 4xx fail at once, a fixed identifiable User-Agent, optional one-time warm-up page per host. Every response that feeds the pipeline is vaulted (including the shareholding master JSON, via the `raw_only` job). Whether NSE blocks the identifiable User-Agent is UNVERIFIED: the probes used a plain browser string.

## 4. Storage layers

| Layer | Contents | Mutability |
|---|---|---|
| L0 Vault | `blobs`, `filings`, files under `data/vault/` | Append-only. Never rewritten. |
| L1 Raw | `raw_xbrl_facts`, `raw_cm_bhavcopy`, `raw_delivery`, `raw_index_snapshot`, all keyed by **source identifiers** (symbol, series, ISIN as the exchange sent them) | Append-only. Re-parse appends new rows keyed by `parser_version`. |
| L2 Canonical | Identity (`entity_master`, `securities`, `security_identifier_history`), `ohlcv`, `filing_meta`, `fact_observations`, `corp_actions`, `index_constituents_history`, `trading_calendar` | Rebuildable from L0/L1 + `quarantine_queue` resolutions + `company_overrides`. |
| L3 Derived | Adjustment factors, adjusted prices, total-return index, `screener_features`, snapshots | Fully rebuildable. Swapped atomically. |

## 5. Schema

**Source of truth: `src/financials/db/schema.sql`.** It is applied by `financials.db.apply_schema`
and, so batches are type- and FK-checked before promotion, also by the staging writer.
This section only records the decisions; it does not duplicate the DDL.

| Layer | Tables |
|---|---|
| L0 | `blobs` (sha256 PK), `filings` (one publication of a blob; `UNIQUE(exchange, source_url, sha256)`) |
| L1 | `raw_cm_bhavcopy`, `raw_delivery`, `raw_xbrl_facts`. Keyed by source identifiers plus `filing_id`. No surrogate IDs. |
| L2 identity | `entity_master`, `securities`, `security_identifier_history` (date-bounded; `valid_to` exclusive), `trading_calendar` |
| L2 market | `ohlcv` (resolved, unadjusted; delivery joined) |
| L2 fundamentals | `filing_meta` (per filing × parser_version), `fact_observations` (long format) |
| Control | `corp_actions`, `quarantine_queue`, `company_overrides` |
| L2 calendar/index | `trading_calendar`, `calendar_coverage`, `raw_index_snapshot`, `index_constituents_history` |
| L2 shareholding | `shareholding_meta`, `shareholding_observations` |
| L3 | `screener_features`, `screener_features_history`, `user_custom_ratios`; control: `promotion_log` |
| Not yet built | `entity_classification_history` (sector/archetype history), `supplemental_kpis` |

Decisions:
- **Timestamps are `TIMESTAMP` holding UTC.** `TIMESTAMPTZ` would make DuckDB's Python client require `pytz` [I2].
- **Money is `DECIMAL(20,2)`, prices `DECIMAL(18,4)`, factors and ratios `DOUBLE`.** Bulk inserts go through Arrow (`decimal128`), which keeps decimals exact [I4].
- **`fact_observations` has `period_type` (`DURATION`/`INSTANT`).** Instants store `period_start = period_end` because DuckDB PK columns cannot be NULL. CHECK constraints tie `unit` to `value_inr`/`value_other` and `period_type` to `period_months` (1..18).
- **`filings.supersedes_filing_id` has no FK** (DuckDB self-reference limitation [I3]). It is enforced in code.
- **No nullable `UNIQUE` columns.** DuckDB's `INSERT OR IGNORE` treats NULLs in them as conflicts and silently drops rows [I1]. `entity_master.cin` is therefore not UNIQUE.
- **Deterministic IDs** (`financials.ids.stable_id`). A replay produces identical keys, so `INSERT OR IGNORE` makes promotion idempotent.

### 5.1 Identity resolution
A universe row (`EQ`/`BE`/`BZ`) continues an existing security if **either**:
- its `FinInstrmId` has ever belonged to that security (this survives splits [P5]), **or**
- its ISIN is held by that security's open interval (this survives series changes, which assign a new `FinInstrmId` [P13]).

Other outcomes:
- Both keys pointing at different securities → `IDENTIFIER/ISIN_COLLISION`.
- Any change of ISIN, symbol, series or `FinInstrmId` closes the open interval and opens a new one, emitting an event. `ISIN_CHANGE` feeds the gap auditor.
- A split and a series change on the same day would create a new security. This is not seen yet; the gap auditor would flag it.

## 6. Time, period and scope rules

### 6.1 Period length
`period_months` = whole months from `period_start` to `period_end` inclusive, allowed range 1..18. Transition years can be 15 months [R6]. Flows are only compared, summed or differenced when `period_months`, `scope` and fiscal alignment all match.

### 6.2 Deriving quarterly flows
- Quarter value = `OneD` fact when present.
- Otherwise quarter = YTD_k − YTD_{k−1}, both in the same FY, scope and profile. The derived row records `source_element = 'DERIVED:YTD_DIFF'`.
- Q4 is frequently reported as FY − 9M, so the identity `FourD(Qk) = Σ OneD` is **not** a restatement detector.

### 6.3 Point-in-time visibility
- `visible_from_ts` = `filings.broadcast_ts` when known.
- Otherwise `board_meeting_end_ts + 1 trading day`, flagged `BOARD_MEETING_RULE` [R9]. This is conservative: it may hide data a day too long but never shows it early.
- If neither is known, the filing is quarantined (`PERIOD/NO_VISIBILITY`).
- Every PIT query filters `visible_from_ts <= :as_of`. The "current view" picks, for each (entity, scope, tag, period), the row with the latest `visible_from_ts`, then the latest `parser_version`.
- Precedence for 12-month periods: a Reg. 34 annual fact supersedes the Reg. 33 FY fact **only from its own `visible_from_ts`**.

### 6.4 Scope continuity
- TTM uses CONSOLIDATED only when all 4 trailing quarters exist in CONSOLIDATED; otherwise STANDALONE.
- YoY on TTM needs **8** consecutive same-scope quarters.
- A ratio never mixes scopes. Every row exposes `scope_used`.

### 6.5 Half-yearly statements
Balance sheet and cash flow come only from H1/FY filings [X12, X13, X22]. In Q2/Q3: TTM CFO = H1_curr + FY_prev − H1_prev. In Q4: FY. Q1 carries forward the last value. Every derived ratio exposes `bs_as_of` and `cf_as_of`.

## 7. XBRL parsing rules

1. **Route by namespace** of `in-capmkt-ent` [X1]. An unknown namespace or taxonomy version → quarantine `PARSE/UNKNOWN_TAXONOMY`. Never guess the profile from the company.
2. **Identity:** resolve the entity from the in-file `ISIN`/`Symbol`/`ScripCode` [X7] against `security_identifier_history` as of the period end. Any mismatch with the filing's listing metadata → quarantine.
3. **Units:** values are absolute rupees [X4]. Identity tolerance = `n_terms × 0.5 × rounding_unit`, where `rounding_unit` comes from `LevelOfRounding` (Rupees 1, Thousands 1e3, Lakhs 1e5, Millions 1e6, Crores 1e7). Never use `decimals` [X5].
4. **Period reconciliation:**
   - Compare each context family's dates against the declared `DateOfStart/EndOfReportingPeriod` facts and the FY start.
   - On conflict → quarantine `PERIOD/CONTEXT_CONFLICT`. Star Health Q3 FY25 [X26] is the reference case.
   - A conflict pattern that recurs may get a **named, deterministic known-defect rule**, e.g. `FOURD_DATES_EQUAL_ONED_USE_DECLARED_YTD`. It needs its own fixture and test and is recorded in `quarantine_queue` as `FIXED_BY_RULE`. Rules are code, never inference.
5. **Scope** from `NatureOfReportStandaloneConsolidated` [X6].
6. **Comparatives:** quarterly XBRL has none [X2]. Restated prior-year quarters cannot be machine-read [X3]. Restatement handling (§7.6) is therefore flag-based in v1.
7. **Unknown elements** are kept in `raw_xbrl_facts` and simply not mapped. If a **mapped critical tag** is missing where the profile requires it → quarantine `PARSE/MISSING_CRITICAL`.
8. **Revisions:** a revised filing for the same (entity, scope, period) is a new filing linked by `supersedes_filing_id`. Both stay. PIT picks by `visible_from_ts`.

### 7.6 Restatement policy (v1)
Flag `restatement_suspected` for an entity-period when any of these hold:
- `ProfitLossFromDiscontinuedOperations* ≠ 0`;
- a DEMERGER or MERGER corp action falls within the last 5 quarters;
- a later annual (Reg. 34) prior-year figure differs from the stored as-reported FY figure by more than the tolerance.

YoY growth across a flagged boundary is set to NULL in screens (with a reason). The PDF anchor-locking extractor from the original blueprint is **deferred**. If built, it must prove its numbers against the same filing's XBRL `OneD`/`FourD` before any row is promoted.

## 8. Canonical building blocks (defined once; every ratio uses these)

Element names are VERIFIED in the INDAS_CORP fixture unless marked otherwise.

| Block | Definition |
|---|---|
| `rev_ops` | `RevenueFromOperations − ExciseDuty` (excise tag UNVERIFIED [X31]; if absent, `RevenueFromOperations`) |
| `cogs` | `CostOfMaterialsConsumed + PurchasesOfStockInTrade + ChangesInInventoriesOfFinishedGoodsWorkInProgressAndStockInTrade` (inventory change is expense-signed [X11]) |
| `gross_profit` | `rev_ops − cogs`, only for `INDAS_CORP` with `(CostOfMaterialsConsumed + PurchasesOfStockInTrade) ≥ 0.10 × rev_ops`; otherwise NULL [C6] |
| `ebitda` | `ProfitBeforeExceptionalItemsAndTax + FinanceCosts + DepreciationDepletionAndAmortisationExpense − OtherIncome`. Avoids the exceptional-items sign [X9, X10]. For consolidated filings, where share of associates sits relative to PBEIT is UNVERIFIED [X29]. |
| `ebit` | `ebitda − DepreciationDepletionAndAmortisationExpense` |
| `etr` | `clamp(TaxExpense / ProfitBeforeTax, 0, 0.50)` if PBT > 0 and tax ≥ 0; else 0 [C5] |
| `nopat` | `ebit × (1 − etr)` |
| `total_debt` | `BorrowingsNoncurrent + BorrowingsCurrent` (+ `lease_liabilities` only once annual notes provide them; quarterly has no lease tag [X16]) |
| `cash_liquid` | `CashAndCashEquivalents + BankBalanceOtherThanCashAndCashEquivalents + CurrentInvestments` (+ non-current treasury investments only once annual notes split them [X17]) |
| `net_debt` | `total_debt − cash_liquid` |
| `invested_capital` | `Equity` (incl. NCI on consolidated; tag UNVERIFIED [X29]) `+ total_debt − cash_liquid` |
| `shares_out` | Phase 1: Reg. 31 total shares, cross-checked against `PaidUpValueOfEquityShareCapital / FaceValueOfEquityShareCapital` [X18]; a >1% disagreement → quarantine. Shares are rolled forward across later share-count actions by **dividing** by `eps_factor`. |
| `market_cap` | Σ over the entity's active share classes of `close × shares_out` |
| `ev` | `market_cap + net_debt + minority_interest + preference_capital` (consolidated basis, consistent with `invested_capital`) |
| `capex` | `PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities + PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities` (positive magnitudes [X15]) |
| `fcf` | `CashFlowsFromUsedInOperatingActivities − capex` (H1/FY bridge §6.5) |
| `fcff` | `fcf + InterestPaidClassifiedAsOperatingActivities × (1 − etr) − InterestReceivedClassifiedAsOperatingActivities × (1 − etr)`; classification per filing [X14] |

## 9. Accounting profiles

| Profile | Detected by | Core tags (status) | Notes |
|---|---|---|---|
| `INDAS_CORP` | `IntegratedFinance_IndAS` | §8 (VERIFIED, one standalone Q2) | Consolidated fixture needed |
| `INDAS_NBFC` | `IntegratedFinance_NBFC` | `InterestEarned`, `FeesAndCommissionIncome`, `NetGainOnFairValueChanges`, `FinanceCosts`, `ImpairmentOnFinancialInstruments` (tags VERIFIED [X20]) | Fixture is an investment company; lending behaviour UNVERIFIED |
| `IGAAP_BANK` | `IntegratedFinance_Banking` | [X21] (VERIFIED, Q1) | No BS in Q1 [X22]; CASA not tagged [X23]; CRAR UNVERIFIED [X24] |
| `IRDAI_GENERAL` | `GeneralInsurance` namespace | `GrossPremiumsWritten`, `NetPremiumWritten`, `PremiumEarned`, `NetCommission`, `OperatingExpensesRelatedToInsuranceBusiness` (VERIFIED, legacy) | Context-date defect [X26] |
| `IRDAI_LIFE` | UNVERIFIED | UNVERIFIED [X28] | No fixture |

Financial profiles are archetype `FINANCIAL_LENDING` or `INSURANCE`. For those archetypes, industrial ratios (EBITDA, gross profit, working capital, EV-based) are NULL.

## 10. Ratio catalogue

Notation: `avg(x)` = mean of opening and closing balance; `ttm(x)` = trailing 4 quarters (§6.4–6.5). Any ratio whose denominator is ≤ 0 or NULL is NULL; numerator and denominator are stored alongside it. Phase = when inputs exist.

### 10.1 Industrial (`INDUSTRIAL_SERVICES`, `NEW_GEN_TECH`)

| Ratio | Formula | Phase |
|---|---|---|
| ROCE | `ttm(ebit) / avg(invested_capital + cash_liquid)` | 1 |
| ROE | `ttm(ProfitLossForPeriod) / avg(Equity)` | 1 |
| ROIC | `ttm(nopat) / avg(invested_capital)` | 1 |
| ROIIC 3Y/5Y | `(nopat_t − nopat_{t−n}) / (IC_t − IC_{t−n})`, FY values | 2 |
| Reinvestment rate | `(capex − depreciation + Δ(working capital)) / nopat`, FY | 2 |
| CROIC | `fcf / avg(invested_capital)` | 1 |
| Shareholder yield | `(dividends paid + gross buybacks − gross equity issued) / market_cap` | 2 |
| 5Y net dilution | `shares_adj_t / shares_adj_{t−5y} − 1` | 2 |
| Incremental asset turnover | `Δ3y rev_ops / Δ3y net fixed assets` | 2 |
| ROTE | `ttm(PAT) / avg(Equity − Goodwill − OtherIntangibleAssets)` | 1 |
| Sloan accrual | `(PAT − CFO − CFI) / avg(Assets)`, FY | 2 |
| CFO / EBITDA | `cfo / ebitda`, 3Y sum | 2 |
| FCF / PAT | `Σ3y fcf / Σ3y PAT` | 2 |
| Receivables vs sales divergence | `YoY% TradeReceivables − YoY% rev_ops` (H1/FY) | 1 |
| Capex / depreciation | `capex / D&A` (YTD-matched) | 1 |
| CWIP / gross block | `CapitalWorkInProgress / gross PPE` (gross PPE from annual notes) | 2 |
| DOL | `%Δ ebit / %Δ rev_ops` (YoY), only if \|%Δ rev_ops\| ≥ 5% and `ebit_{t−4} > 0` | 1 |
| Gross − EBITDA margin spread | `gross_profit/rev_ops − ebitda/rev_ops` | 1 |
| Working capital intensity | `(Inventories + TradeReceivablesCurrent − TradePayablesCurrent) / ttm(rev_ops)` | 1 |
| Other income / PBT | `ttm(OtherIncome) / ttm(ProfitBeforeTax)` | 1 |
| Net debt / 3Y avg FCF | `net_debt / avg3y(fcf)` | 2 |
| Effective cost of debt | `ttm(FinanceCosts) / avg(total_debt)` (includes lease interest while debt excludes leases [L4], so overstated for lease-heavy firms) | 1 |
| Contingent liabilities / net worth | annual notes | 2 |
| RPT leak % | `(RPT purchases + loans given + royalties) / rev_ops` from RPT contexts [X19] | 2 |
| PE, PB, EV/EBITDA, EV/Sales, P/CFO | standard, using §8 blocks | 1 |

### 10.2 Forensic (stored as separate columns, never summed)
- `piotroski_f` (0..9)
- `beneish_m`
- `altman_z_dd` (Z'' = 3.25 + 6.56·X1 + 3.26·X2 + 6.72·X3 + 1.05·X4, with X1 = WC/TA, X2 = retained earnings/TA, X3 = EBIT/TA, X4 = book equity/total liabilities)

All three are NULL for `FINANCIAL_LENDING` and `INSURANCE`; Beneish additionally needs annual data. Phase 2.

### 10.3 Valuation & flow

| Ratio | Formula | Phase |
|---|---|---|
| Unlevered FCF yield | `ttm(fcff) / ev` | 1 |
| Reverse-DCF implied g | solve for g; stored with `wacc_used`, `terminal_g_used`, `horizon_years` | 3 |
| 5Y EV/EBITDA percentile | rank of current vs trailing 20 quarter-end values | 2 |
| Delivery velocity | `avg5d(deliv_qty) / avg20d(deliv_qty)` | 1 |
| Float turnover % | `avg5d(deliv_qty) / free_float_shares × 100` | 2 |
| Quarterly FII+DII absorption | `Δ(FII+DII shares) / median90d(volume)` from Reg. 31 | 2 |
| Institutional absorption (monthly) | needs AMC adapters | 3 |

### 10.4 New-gen tech (archetype `NEW_GEN_TECH`)
- From XBRL: EV/gross profit, ex-cash PE `(market_cap − cash_liquid) / (PAT − OtherIncome × (1 − etr))`, EV/billings `ev / (rev_ops + Δ contract liabilities)` (annual), EV/ESOP-adjusted EBITDA (`AdjustmentsForSharebasedPayments` is tagged in the CF), P/CFO, Rule of 40, net working-capital float, burn multiple, cash runway, ESOP-adjusted FCF.
- From `supplemental_kpis` (manual or presentation-sourced, Phase 3): EV/GOV, take rate, contribution margin, NRR, CAC payback.

### 10.5 Lenders (`INDAS_NBFC`, `IGAAP_BANK`)

| Ratio | Formula | Status |
|---|---|---|
| NII | bank `InterestEarned − InterestExpended`; NBFC `InterestEarned − FinanceCosts` | tags VERIFIED |
| NIM (proxy) | `annualised NII / avg(total assets)`, labelled `nim_asset_proxy` | H1/FY only |
| PPOP | bank `OperatingProfitBeforeProvisionAndContingencies` | VERIFIED |
| Cost / income | `OperatingExpenses / (NII + OtherIncome)` | VERIFIED tags |
| Credit cost | `annualised ProvisionsOtherThanTaxAndContingencies / avg(advances)` | advances H1/FY only |
| GNPA %, NNPA % | `PercentageOfGrossNpa`, `PercentageOfNpa` (fractions) | VERIFIED |
| PCR | `(GrossNonPerformingAssets − NonPerformingAssets) / GrossNonPerformingAssets` | VERIFIED tags |
| CET1, AT1 | tagged | VERIFIED; total CRAR UNVERIFIED |
| RoA | tagged `ReturnOnAssets` (annualisation UNVERIFIED) or `ttm(PAT)/avg(assets)` | — |
| P/B | `market_cap / Equity` | — |
| CASA % | `supplemental_kpis` | not in XBRL [X23] |

### 10.6 Insurers
- General: claims ratio `NetClaimsIncurred / PremiumEarned`; combined ratio = claims ratio + `(NetCommission + OperatingExpensesRelatedToInsuranceBusiness) / NetPremiumWritten`; solvency (tag UNVERIFIED).
- Life (UNVERIFIED): VNB margin, APE growth, EV, persistency → `supplemental_kpis`.

### 10.7 `screener_features` columns in Phase 1

Source of truth: `screener_features_history` in `schema.sql`; aliases in `financials.dsl.ALIASES`.

| Status | Columns |
|---|---|
| **Active** (always computed when a bar exists) | `close`, `price_date`, `return_1m/3m/6m/12m` (need 22/64/127/253 bars), `price_to_dma50/200` (50/200 bars), `dist_52w_high` (252 bars), `deliv_avg_5d/20d`, `delivery_velocity`, `in_nifty500` |
| **Active once the input filing is visible** | `shares` (+`shares_source`), `market_cap`, `promoter_pct`, `fii_pct`, `dii_pct`, `float_turnover_pct`, `shp_as_of` (Reg. 31); `total_equity`, `net_debt`, `pb`, `debt_to_equity`, `bs_as_of` (H1/FY balance sheet); `altman_z_dd` (H1/FY BS + TTM EBIT; OtherEquity proxy) |
| **Active once 4 same-scope quarters exist** | `sales_ttm`, `ebitda_ttm`, `pat_ttm`, `pe`, `ev_ebitda`, `enterprise_value`, `opm`, `roe`, `roce`, `roic`, `other_income_to_pbt`; `fcf_ttm`, `croic`, `fcff_yield`, `cf_as_of` via the H1/FY bridge |
| **Active once 8 quarters exist** | `sales_growth_yoy`, `profit_growth_yoy` |
| **NULL placeholder until Phase 2** | `piotroski_f`, `beneish_m` (need year-over-year annual Reg. 34 data) |
| Not built (Phase 2+) | 3Y/5Y CAGR, 5Y dilution, valuation percentiles, RPT, lender/insurer ratios. `fundamentals.cagr(..., min_periods_required)` already returns NULL until history exists [C9] |

## 11. Corporate actions

### 11.1 Factors (applied to history strictly before `ex_date`)

| Action | `price_factor` | `eps_factor` |
|---|---|---|
| Split FV X→Y | Y/X | Y/X |
| Bonus A:B (A new per B held) | B/(A+B) | B/(A+B) |
| Rights A:B at P, cum-rights close C | (B·C + A·P)/((A+B)·C) | same (bonus element) |
| Demerger (parent) | Open_ex / Close_{ex−1} [C3] | 1.0 |
| Merger (acquirer) | 1.0 | 1.0. Holders of the target convert by swap ratio in portfolio backtests. |
| Dividend (any size) | 1.0 [C2] | 1.0; goes to the total-return index only |

Volumes before the ex-date are divided by `price_factor` for share-count events. Absolute financials (revenue, PAT, debt) are never multiplied by any factor.

### 11.2 Ingestion and resolution
- Source: the NSE corporate-actions API [P12]. Purposes are parsed by explicit rules only (dividend, bonus `A:B`, face-value split, `Rights A:B @ Premium Rs X/-` with issue price = face value + premium, demerger) [CA4, CA5, CA9]. Anything else is recorded as `UNKNOWN` with status `QUARANTINED`, so the gap auditor freezes adjusted prices.
- Security resolution [CA1, CA2, CA7]: the API ISIN on `ex_date − 1`; if no match, the API symbol, but only for a holder whose ISIN has the same 4-character issuer code (chars 4-7). Otherwise quarantine `STALE_ISIN_OTHER_ISSUER` / `UNKNOWN_ISIN`. Re-promoting the same file later records actions whose security has appeared since.
- Action ids are deterministic (`ISIN, ex_date, subject, component`), so re-promotion is idempotent.

### 11.3 Verification (per security and ex-date, as a group)
`observed_gap = Open_ex / Close_{ex−1}` from unadjusted `ohlcv` (exchange `PrvsClsgPric` is unadjusted and useless here [P2]). All actions of one security on one ex-date are judged on their **combined** factor (NAZARA split + bonus = 0.25) [CA5].

| Condition | Status |
|---|---|
| any member unfactorable (UNKNOWN, bad ratio) | all `QUARANTINED` |
| a DEMERGER in the group | all `VERIFIED`; demerger factor = observed / product of the others |
| \|combined − 1\| < 0.10 | `UNOBSERVABLE` (dividends, small rights; accepted, flagged) |
| \|observed_gap / combined − 1\| ≤ 0.10 | `VERIFIED` |
| otherwise | `QUARANTINED` |

### 11.4 Unconditional gap auditor [C4]
Every security, every trading day: if the residual gap after dividing out the day's accepted price factors, \|Open_t / (Close_{t−1} · ΠF) − 1\|, exceeds 10% (so a dividend never explains a gap), or the ISIN changed versus t−1 without an accepted SPLIT/CONSOLIDATION:
- quarantine `GAP`;
- raw and `ohlcv` rows are still stored;
- the **adjusted** series and price-derived features for that security are frozen at t−1 until resolved.

Expected volume is 0–7 per day [P4]. When an action verifies later, matching gap quarantines are resolved (`FIXED_BY_RULE`) only after re-auditing the residual. The auditor compares consecutive *stored* bars, so promote every trading day: a gap of months between bars (as in the test fixtures) quarantines most of the market.

### 11.5 Total return
`financials.returns.total_return_index`: r_t = (close_t + accepted cash dividends_t) / (close_{t−1} · F_t) − 1. Adjusted prices never include dividends [C2]. Both series stop at the first unresolved gap.

### 11.6 Index membership backfill (before the first snapshot)
`financials backfill-index --manifest reference/nifty500_changes.csv` (`financials.admin.backfill_index`, one transaction):
- Starts from the membership resolved at the **first** `SNAPSHOT` date and walks **backward** through manifest events (`effective_date, action, symbol, kind, source`) to `MIN_TRADE_DATE`.
- An ADD at E is reverted (must be a member); a REMOVE at E is restored (must not be). Symbols resolve on E (ADD) or E − 1 (REMOVE) through `security_identifier_history`, which handles renames such as AKZOINDIA → JSWDULUX [IDX6].
- After every event date the real-member count must equal `expected_count` (500) plus active `TEMPORARY` members (listed spin-offs held between dummy inclusion and exclusion). Membership is constant between events, so this checks every trading day.
- Any unresolved symbol, inconsistent event or count break aborts and writes nothing. On success `MANUAL_BACKFILL` rows `[from, min(to, first snapshot))` replace earlier backfill rows, so the operation is idempotent.
- Prerequisites: price history (bhavcopy days) covering the event dates, and a complete first snapshot. The fixture snapshot resolves 497/500, so the backfill correctly refuses [IDX7].
- Manifest: `reference/nifty500_changes.csv` is generated by `financials extract-index-changes` from the committed notices, and a test asserts it equals the extraction. Prose-only demerger notices (dummies) are **not** extracted; add `TEMPORARY` rows by hand when a backtest needs those days exact.

## 12. Promoter quality gates (in order)

| Gate | Rule | On failure |
|---|---|---|
| G1 Completeness | EQ/BE/BZ rows ≥ 92% of the trailing 5-trading-day median | Abort batch; keep previous state; retry later |
| G2 Identifier resolution | Every raw price row resolves to a `security_id` via `(exchange, fin_instrm_id \| symbol+series, isin, date)`; unresolved rows ≤ 1% | Unresolved rows → quarantine; above 1% → abort |
| G3 Accounting identities | Per filing: P&L chain (X9 / bank equivalents), `Assets = EquityAndLiabilities` when BS present, expense components sum to `Expenses`; tolerance §7.3 | Quarantine that filing only |
| G4 Null-spike (features) | Null rate of `close`, `market_cap`, `sales_ttm`, `pat_ttm`, `total_equity` rises ≤ 1.5 percentage points vs the previous materialised date | Abort; previous features stay live |
| G5 Atomic features | Row count = universe (securities with a bar in the last 15 days and a valid identifier); history rows for the date and the live table replaced in one transaction | No partial state is ever visible |
| ORDER | Market days and index snapshots must arrive in date order | Abort; replay needs a rebuild |
| Share cross-check | Reg. 31 total vs results paid-up / face value differ by > 0.5% (skipped for partly-paid issuers) | Quarantine `SHARES/CROSS_CHECK_FAILED`; promotion continues |

## 13. Schedule (local machine, IST)

| When | Job |
|---|---|
| Trading days from 18:30, retry every 30 min until 23:30 | UDiFF bhavcopy + `sec_bhavdata_full` (publish time UNVERIFIED [P11]) |
| Daily | `ind_nifty500list.csv` snapshot → close/open membership intervals on change |
| Results season, every 2 h; otherwise daily | Results XBRL discovery (local, `www.nseindia.com` API) |
| Daily | Corporate-actions API for a rolling window (e.g. last 30 days to next 30 days) |
| Yearly (January) and on change | Holiday master |
| After each quarter's Reg. 31 deadline | Shareholding master + XBRL per symbol in the universe |
| After each fetch batch | Promoter: gates → canonical → corp-action verification → gap auditor → features |

## 14. Screener DSL

```
query      := or_expr
or_expr    := and_expr ( "OR" and_expr )*
and_expr   := not_expr ( "AND" not_expr )*
not_expr   := "NOT" not_expr | comparison | "(" or_expr ")"
comparison := arith ( "<" | "<=" | ">" | ">=" | "=" | "!=" ) arith
arith      := term ( ("+" | "-") term )*
term       := factor ( ("*" | "/") factor )*
factor     := NUMBER | ALIAS | "(" arith ")" | "-" factor
ALIAS      := a name in financials.dsl.ALIASES or user_custom_ratios (case-insensitive, words may end in digits,
              e.g. "Return 12M", "In Nifty 500")
```

- Units follow Screener conventions and are stated per alias: money in INR crore, growth/returns/margins/holdings in percent.

- Aliases map **only** to whitelisted `screener_features` columns or saved custom ratios.
- Saved custom ratios are expanded before compilation; cycles are rejected.
- Output is parameterised SQL: numbers become bound parameters, columns come from the registry, and no user text reaches SQL.
- Division compiles to `x / NULLIF(y, 0)`. NULL comparisons are not TRUE, and `NOT` keeps NULL as NULL, so a stock missing a metric never passes a filter on it.
- An unknown alias is a compile error, never a guess.

## 15. Phases

**Phase 1: thin slice, screenable end-to-end (Nifty 500)**

Status (2026-11-13): **built and tested end to end** on real fixtures, all listed items below, plus index backfill (§11.6), quarantine resolution (D-6) and benchmarks (`docs/benchmarks.md`). Known gaps inside Phase 1:
- `piotroski_f` / `beneish_m` columns exist but stay NULL: both need year-over-year annual data (Reg. 34, Phase 2).
- Altman Z'' uses OtherEquity as the retained-earnings proxy; ROCE/ROE use the latest balance sheet, not an average.
- EV excludes minority interest and preference capital (tags UNVERIFIED [X29]).
- Results-XBRL discovery API is UNVERIFIED [A7]; `fetch-results` takes URLs.
- A split and a series change between two promoted days create a second security; the collision is quarantined and resolved with `quarantine resolve --action MERGE_SECURITIES` (SIGMA, Oct 2025).
- Index backfill covers regular replacement tables only; dummy/spin-off `TEMPORARY` rows are manual.

- Vault (`blobs`, `filings`) and staging/promoter skeleton.
- UDiFF bhavcopy + `sec_bhavdata_full` loaders.
- `trading_calendar`.
- `security_identifier_history` (with `FinInstrmId`).
- `index_constituents_history` (snapshot-forward).
- Corp-action ledger, verification, gap auditor, price/EPS adjuster, total-return index.
- `INDAS_CORP` results parser (standalone and consolidated; RPT contexts land in raw).
- `shares_out`.
- Minimal `screener_features`: market cap, PE, PB, EV/EBITDA, sales growth, OPM, ROCE, ROE, returns 1M/3M/6M/12M, price/200DMA, delivery 5D/20D, delivery velocity.
- DSL v0 and gates G1–G5.

**Phase 2: multi-archetype and annual depth**
- NBFC, bank and general-insurer parsers (each gated on a representative fixture).
- Reg. 34 annual XBRL (leases, notes, segments, AOC-1, restatement comparison).
- Full Reg. 31 shareholding.
- RPT ratios, forensic scores and the remaining §10 ratios.
- Feature snapshots.

**Phase 3: catalysts, flows and backtesting**
- Reg. 30 event XBRL via RSS; insider/SAST/SDD.
- F&O and SLBM; per-AMC portfolio adapters.
- `supplemental_kpis`; Reverse-DCF.
- PIT backtester (queries `fact_observations` and `ohlcv` with `visible_from_ts` and `trade_date` gates, not snapshots).
- Daily diff digest.

## 16. Open decisions

| ID | Question | Current default |
|---|---|---|
| D-1 | Where fetchers run | **Decided**: local only; CI = offline lint + tests |
| D-2 | Which known-defect rules (§7.4) to allow | None yet; quarantine |
| D-3 | Fixtures still needed: lending NBFC, life insurer, H1 bank, consolidated corp, Q1/Q3 corp, loss-valued exceptional items, Reg. 34 annual, Reg. 31 with pledges / employee trusts | Owner supplies URLs after Phase 1; block the related parser until present |
| D-4 | Corporate-actions source | **Decided**: NSE API adapter (+ RSS for discovery); unparseable purposes → QUARANTINED. BSE fallback not built (`api.bseindia.com` returned 403 [A1]) |
| D-6 | How a human resolves a quarantine | **Built**: `financials quarantine list` / `resolve --action ACCEPT\|REJECT\|OVERRIDE\|CORP_ACTION\|MERGE_SECURITIES --note …` (`financials.admin`). One transaction; rows are never deleted; every change is logged in `company_overrides`. `CORP_ACTION` must verify against the observed gap, which then unfreezes the adjusted series. `MERGE_SECURITIES` repoints identity, prices, actions, index rows and quarantine links to the `FinInstrmId` owner, tombstones the duplicate entity as `MERGED`, and loads the colliding bar from raw (SIGMA case [P14]). Known-defect rules (D-2) are still not built |
| D-5 | Historical index-membership backfill source | Snapshot-forward only [L1] |
