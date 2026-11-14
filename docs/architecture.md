# Architecture: Indian Equity Research & Screening Engine

Claim IDs in brackets (e.g. [X2], [P5]) point to `docs/references.md`. Anything marked
UNVERIFIED there must not be hard-coded; code that depends on it quarantines on surprise.

---

## 1. Scope

- **Purpose:** personal, single-user research, screening and point-in-time (PIT) backtesting. No redistribution [C8].
- **Universe v1:** NSE Mainboard `EQ`, `BE`, `BZ`, starting with the Nifty 500 [C7]. SME (`SM`, `ST`) out of scope. BSE is used only as a fallback and for historical Reg. 34 annual XBRL backfill.
- **Data scope (v1, CHOICE [C9]):** `trade_date >= 2024-10-01` for prices, delivery, corporate actions and index snapshots; `period_end >= 2025-03-31` for financials and shareholding (Q4 FY25, the first Integrated Filing quarter [X38]; `financials/scope.py`). As of Nov 2026 that is 7 quarters: TTM works, YoY-on-TTM is NULL until Q3 FY27 (Dec-2026) results are filed. Promotion returns `OUT_OF_SCOPE` for older inputs (vaulted, not parsed); `fetch-days` / `fetch-corp-actions` clamp start dates. Multi-year windows use `fundamentals.cagr(..., min_periods_required)` and stay NULL until enough in-scope quarters exist.
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
| `fetch-days START [END]`, `fetch-corp-actions START END`, `fetch-holidays`, `fetch-index --as-of D`, `fetch-shareholding SYM…\|--universe U`, `fetch-annual SYM…\|--universe U`, `fetch-results [URL] [--symbols …\|--universe U]`, `discover-filings [--symbols …\|--universe nifty500\|active\|--from-rss] [--workers N]` | download → vault → staging only (`--workers` threads overlap hosts; each host stays at ≥ 1 s between requests). Vaulted archive files are never downloaded again (vault URL index); a failed day or file is reported and the run goes on; corporate actions are asked in 30-day windows |
| `promote` | the single writer: applies pending stages in order (holidays, market days by date, index snapshots, corporate actions, results, shareholding, raw-only) and records them in `promotion_log`. ABORTED batches stay pending, and every later market day waits behind an aborted one |
| `rebuild-market --from D` | rolls market-derived state back to `D` (bars, bhavcopy/inferred calendar rows, identifier intervals, auto-decided corporate actions, feature history), replays the staged days and re-materialises; raw tables untouched; audited in `admin_log` |
| `materialize D` / `materialize --from D1 --to D2` | builds features for `D` (or every promoted trading day in the range, ascending) with gates G4/G5 |
| `run-day --date D` | holiday list, market days D−7..D, corporate actions D−7..D+30, discovery for symbols with results in the day's RSS (A9) + Reg. 30 events, promote, materialise D; idempotent |
| `screen "QUERY" [--as-of D]` | runs a DSL screen on the live table or point-in-time on history (read-only connection) |
| `load-kpis FILE` | stages a supplemental-KPI CSV/JSON (`parsers.kpis`) for `promote` into `supplemental_kpis` |
| `export-bundle --out DIR [--include-raw --max-file-mb 50 --max-total-mb 250]`, `import-bundle DIR --db PATH` | zstd Parquet shards of every table (raw facts optional) with a manifest of row counts and checksums; import verifies them. Local or private storage only: the data is NSE-derived and the repository is public |
| `quarantine list [--stage --reason --entity --security --all]`, `quarantine inspect Q`, `quarantine resolve --id Q --action A --note N [--payload-json J]`, `quarantine reprocess` | audited quarantine resolution (D-6); `list` and `inspect` are read-only |
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
| Shareholding (Reg. 31) | `www.nseindia.com/api/corporate-share-holdings-master?index=equities&symbol=X` → `nsearchives…/corporate/xbrl/SHP_*.xml` | JSON + XBRL | VERIFIED [SHP1-SHP15] | 1 |
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
| L2 fundamentals | `filing_meta` (per filing × parser_version), `fact_observations` (long format), `segment_observations` (Ind AS 108 segment and geography rows, §14b-1) |
| Control | `corp_actions`, `quarantine_queue`, `company_overrides` |
| L2 calendar/index | `trading_calendar`, `calendar_coverage`, `raw_index_snapshot`, `index_constituents_history` |
| L2 shareholding | `shareholding_meta`, `shareholding_observations` |
| L3 | `screener_features`, `screener_features_history`, `user_custom_ratios`; control: `promotion_log` |
| Not yet built | `entity_classification_history` (sector/archetype history) |

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
- Otherwise quarter = YTD_k − YTD_{k−1}, both in the same FY, scope and profile, and both starting on a declared fiscal-year start (`filing_meta.fy_start`): an Oct-Mar six-month context in a "Yearly" filing is not a YTD [X82]. The derived row records `source_element = 'DERIVED:YTD_DIFF'`.
- Q4 is frequently reported as FY − 9M, so the identity `FourD(Qk) = Σ OneD` is **not** a restatement detector.

### 6.3 Point-in-time visibility
- `visible_from_ts` = the latest of `filings.broadcast_ts` and the listing's `broadcast_Date` / `creation_Date` (`raw_results_listing`, filled from every vaulted `RESULTS_LISTING`) [X83]. A revised listing row has no `broadcast_Date`, and a re-uploaded file is created after the broadcast of the row it replaces. Source `BROADCAST` or `LISTING_CREATION`.
- Otherwise (last resort) `board_meeting_end_ts + 1 trading day`, flagged `BOARD_MEETING_RULE` [R9, UNVERIFIED], lifted to the XBRL file-name upload time read as PM (`FILENAME_TS`) when that is later. The board-meeting rule alone is **not** conservative for re-filings: 408 of 684 such filings were uploaded more than a day after the date it gave (X83).
- Never earlier than the file-name upload time read as AM (the name is a 12-hour clock without AM/PM).
- If no broadcast, listing or board-meeting time is known, the filing is quarantined (`PERIOD/NO_VISIBILITY`).
- Every PIT query filters `visible_from_ts <= :as_of` and reads only each filing's latest `parser_version` (`fundamentals.CURRENT_VERSION`), so a re-parse that moves a filing's visibility later leaves no early row. The "current view" then picks, for each (entity, scope, tag, period), the row with the latest `visible_from_ts`.
- `restage --category RESULTS_XBRL --visibility` re-parses promoted filings whose rule now gives a later time; `backfill-listing-evidence` stages `raw_results_listing` from vaulted listings first.
- Precedence for 12-month periods: a Reg. 34 annual fact supersedes the Reg. 33 FY fact **only from its own `visible_from_ts`**.

### 6.4 Scope continuity

**Default scope per company (Mandate 3, C18).** `fundamentals.resolve_scope` returns one `ScopeDecision` per company and
as-of: the default quarterly scope (consolidated if the latest quarterly filing has a consolidated version, else
standalone), a complete fallback scope, an H1/FY bridge, or balance-sheet-only, never a mix. `scope_reason` records
which. `default_annual_scope` (same rule on FY filings) drives annual statements. A manual override
(`python -m financials scope-override --entity … --quarterly … --annual … --reason …`, or `--clear`) pins both and is
audited.

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

### 7.5 Named label rules
Some lines exist only as a free-text `Description*` label on a dimensional "Others" or detail member, with the amount in contexts carrying the same member. `indas_corp.LABEL_RULES` fixes, per rule, the axis, the amount element and an anchored label pattern: `LEASE_LIAB_NONCURRENT`, `LEASE_LIAB_CURRENT` [X39] and `EXCISE_DUTY` [X40]. Duration amounts go through the same period reconciliation as every other fact. Canonical facts record `source_element = LABEL:<rule>`. New rules need a real fixture and a test (`tests/test_label_rules.py`); every rule is listed in `docs/tag_registry.yaml`.

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
| `rev_ops` | `RevenueFromOperations − excise_duty`, where `excise_duty` comes from the `EXCISE_DUTY` label rule (there is no `ExciseDuty` element [X40]); no excise label = 0 |
| `cogs` | `CostOfMaterialsConsumed + PurchasesOfStockInTrade + ChangesInInventoriesOfFinishedGoodsWorkInProgressAndStockInTrade` (inventory change is expense-signed [X11]) |
| `gross_profit` | `rev_ops − cogs`, only for `INDAS_CORP` with `(CostOfMaterialsConsumed + PurchasesOfStockInTrade) ≥ 0.10 × rev_ops`; otherwise NULL [C6] |
| `ebitda` | `ProfitBeforeExceptionalItemsAndTax + FinanceCosts + DepreciationDepletionAndAmortisationExpense − OtherIncome`. Avoids the exceptional-items sign [X9, X10]. For consolidated filings, where share of associates sits relative to PBEIT is UNVERIFIED [X29]. |
| `ebit` | `ebitda − DepreciationDepletionAndAmortisationExpense` |
| `etr` | `clamp(TaxExpense / ProfitBeforeTax, 0, 0.50)` if PBT > 0 and tax ≥ 0; else 0 [C5] |
| `nopat` | `ebit × (1 − etr)` |
| `total_debt` | `BorrowingsNoncurrent + BorrowingsCurrent + lease_liabilities_noncurrent + lease_liabilities_current`; leases come from the `LEASE_LIAB_*` label rules [X39] and are added exactly once (no label = 0) |
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
| `IRDAI_LIFE` | `IntegratedFinance_LI` (2025-01-31) [X33] | premium, actuarial, benefits, surplus, policyholder investments (VERIFIED) | Parser not built; extra `OcurI`/`OprevI` instants |

Financial profiles are archetype `FINANCIAL_LENDING` or `INSURANCE`. For those archetypes, industrial ratios (EBITDA, gross profit, working capital, EV-based) are NULL.

## 10. Ratio catalogue

Notation: `avg(x)` = mean of opening and closing balance; `ttm(x)` = trailing 4 quarters (§6.4–6.5). Any ratio whose denominator is ≤ 0 or NULL is NULL; numerator and denominator are stored alongside it. Phase = when inputs exist.

### 10.1 Industrial (`INDUSTRIAL_SERVICES`, `NEW_GEN_TECH`)

| Ratio | Formula | Phase |
|---|---|---|
| ROCE | `ttm(ebit) / avg(invested_capital + cash_liquid)` | 1 |
| ROE | `ttm(ProfitOrLossAttributableToOwnersOfParent) / avg(EquityAttributableToOwnersOfParent)`; standalone filings fall back to `ProfitLossForPeriod` / `Equity` [X42] | 1 |
| ROIC | `ttm(nopat) / ((opening + closing) / 2 invested_capital)`, NULL without the opening balance sheet [C16] | 1 |
| ROIIC 3Y/5Y | `(nopat_t − nopat_{t−n}) / (IC_t − IC_{t−n})`, FY values | 2 |
| Reinvestment rate | `(capex − depreciation + Δ(working capital)) / nopat`, FY | 2 |
| CROIC | `ttm(fcf) / ((opening + closing) / 2 invested_capital)`, NULL without the opening balance sheet [C16] | 1 |
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
| PE | `market_cap / ttm(COALESCE(owners, PAT) − discontinued)`, per filing before TTM [C10] | 1 |
| ROE (continuing), core profit, EPS | C14, C15: `roe_continuing`, `core_profit_ttm`, `eps_ttm`, `eps_continuing_ttm` | 1 |
| PB, EV/EBITDA, EV/Sales, P/CFO | standard, using §8 blocks (PB on owners' equity; EV adds minority interest) | 1 |

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
- From `supplemental_kpis` (`load-kpis FILE`, manual or presentation-sourced): GOV, take rate, contribution margin, NRR, CAC payback.

### 10.1b Cash conversion and operating leverage (industrial, C19)

| Column | Formula | Guard |
|---|---|---|
| `sloan_accrual` | (TTM PAT − CFO − CFI) / avg total assets | opening balance sheet |
| `cfo_to_ebitda` | TTM CFO / TTM EBITDA | EBITDA > 0 |
| `fcf_to_pat` | TTM FCF / TTM PAT | PAT > 0 |
| `working_capital_intensity` | (receivables + inventories − payables) / TTM revenue | latest balance sheet |
| `receivables_sales_divergence` | receivables YoY − revenue YoY | 8 quarters |
| `net_debt_to_fcf` | net debt / TTM FCF | FCF > 0 |
| `cost_of_debt` | TTM finance costs / avg (borrowings + leases) | opening balance sheet |
| `dol` | EBIT YoY / revenue YoY | 8 quarters, \|revenue YoY\| ≥ 5%, EBIT > 0 both years |
| `gross_ebitda_spread` | (gross profit − EBITDA) / revenue | COGS ≥ 10% of revenue |
| `fcff_yield` | FCFF / EV, interest add-back per filing CFO classification | existing |

### 10.5 Lenders (`INDAS_NBFC`, `IGAAP_BANK`)

NBFC columns come from the Division III parser (`parsers/indas_nbfc.py`, X54-X57); bank columns from the RBI-format
parser (`parsers/igaap_bank.py`, X58-X61). Industrial ratios (EBITDA, OPM, ROCE, ROIC, CROIC, D/E, Altman, FCF, EV) are
NULL for both. Bank `sales_ttm` = TTM interest earned (Screener's bank "Revenue", S4). Bank regulatory ratios come from
the standalone book (X60).

**Denominators (C16):** ROE and ROE (continuing) use the latest **closing** owners' equity (Screener's convention,
available from the first balance sheet). RoA, NIM proxy, credit cost, **ROIC and CROIC** use **(opening + closing) / 2** over 12
months and stay NULL until the opening balance sheet exists.

| Column | NBFC formula | Bank formula |
|---|---|---|
| `nii_ttm` | TTM `InterestEarned − FinanceCosts` | TTM `InterestEarned − InterestExpended` |
| `ppop_ttm` | TTM net total income − opex = PBEIT + impairment (X55) | TTM `OperatingProfitBeforeProvisionAndContingencies` (= NII + OI − opex, X58) |
| `cost_to_income` | opex / (revenue + other income − finance costs) | `OperatingExpenses / (NII + OtherIncome)` |
| `credit_cost` | TTM impairment / avg(loans) | TTM `ProvisionsOtherThanTaxAndContingencies` / avg(advances) |
| `loans`, `loans_as_of`, `loans_avg_from` | loans, latest BS date, opening date of the average | advances (same fields) |
| `nim_asset_proxy` | TTM NII / avg(total assets) | same |
| `roa` | TTM owners' profit / avg(total assets) | same; filed RoA in `roa_filed` (annualisation varies, X59) |
| `gnpa_pct`, `nnpa_pct`, `pcr` | **NULL**: no NBFC element (X54) | `PercentageOfGrossNpa`, `PercentageOfNpa`, `(GNPA − NNPA) / GNPA` (standalone, latest period) |
| `credit_to_deposit` | — | advances / deposits (latest BS) |
| `cet1_pct`, `at1_pct` | — | `CET1Ratio`, `AdditionalTier1Ratio` (standalone; no total CRAR element) |
| `govt_holding_pct` | — | `PercentageOfShareHeldByGovernmentOfIndia` (PSU marker) |
| `is_lending_nbfc` | C13 | NULL |
| `pb` | market cap / owners' equity | market cap / (Capital + Reserves and surplus) |
| CASA % | — | `supplemental_kpis` (not in XBRL [X23]) |

### 10.6 Insurers (`IRDAI_LIFE`, `IRDAI_GENERAL`, `INDAS_INSURANCE`)

Parsed by `parsers/irdai_insurance.py` (X62-X66). Three accounting bases coexist and are **never compared**:
`insurer_basis` says which one a row uses. Industrial and lender ratios (EBITDA, OPM, ROCE, ROIC, CROIC, D/E, Altman,
FCF, EV, NII, NIM) are NULL for insurers. `sales_ttm` = net premium earned (general), net premium (life) or insurance
revenue (Ind AS 117). P/B = market cap / (share capital + reserves and surplus + application money) for IRDAI formats,
market cap / `Equity` for Ind AS 117.

| Column | IRDAI general | IRDAI life | Ind AS 117 |
|---|---|---|---|
| `net_premium_earned_ttm` | `PremiumEarned` | `NetPremiumIncome` | NULL |
| `insurance_revenue_ttm` | NULL | NULL | `InsuranceRevenue` |
| `claims_ratio` | `IncurredClaims / PremiumEarned` (= filed `IncurredClaimRatio`) | NULL | incurred claims / insurance revenue (gross of reinsurance) |
| `expense_ratio` | (net commission + opex) / `NetPremiumWritten` | `ExpensesOfManagement / GrossPremiumIncome` | NULL |
| `combined_ratio` | claims + expense (= filed `CombinedRatio`, X66) | NULL | (service expenses − net reinsurance) / insurance revenue |
| `solvency_ratio` | filed, times (`SOLVENCY_PERCENT_SCALING`, X65) | same | NULL (no element) |
| `investment_income_ttm` | policyholders' + shareholders' | same | `InvestmentIncome` |
| `persistency_13m`, `_61m` | — | filed `PersistencyRatio13ThMonth`, `…61ThMonth` | — |

`supplemental_kpis` (schema.sql) holds what XBRL lacks: VNB margin, embedded value, APE growth (life), and Batch 7's
new-gen tech KPIs. Each row is point in time (`visible_from_ts` = publication of the source document). Loaded with
`load-kpis FILE` (CSV/JSON, `financials.parsers.kpis`): the file is vaulted, staged and promoted like any batch; rows
with an unknown KPI, the wrong unit, a publication before period end or an unresolvable symbol are quarantined `KPI/…`.
`screener_features` carries `vnb_margin`, `embedded_value`, `ape_growth`, `gov`, `take_rate`, `contribution_margin`,
`nrr`, `cac_payback` (latest period visible at as-of; NULL when none is loaded). Persistency filed in XBRL [X62] wins; a
loaded persistency only fills a NULL. No fetcher (Phase 3).

### 10.8 New-gen tech (`NEW_GEN_TECH`, C21) and valuation bands (C20)

| Column | Formula | Guard |
|---|---|---|
| `valuation_archetype` | profile-derived; NEW_GEN_TECH by curated list / override | — |
| `ev_to_gross_profit` | EV / TTM gross profit | gross profit exists (COGS ≥ 10%) |
| `ex_cash_pe` | (mcap − liquid cash) / (continuing owners' PAT − OI × (1 − ETR)) | denominator > 0 |
| `ev_to_billings` | EV / (TTM revenue + Δ contract liabilities over 12 months) | labelled contract liabilities, opening BS |
| `ev_to_esop_adj_ebitda` | EV / (EBITDA + ESOP), cash-flow window | ESOP add-back present |
| `price_to_cfo` | mcap / TTM CFO | CFO > 0 |
| `rule_of_40` | revenue YoY + EBITDA margin | 8 quarters |
| `billings_growth_pct` | billings YoY | 8 quarters + contract liabilities 24 months back |
| `neg_working_capital_float_pct` | ((payables + contract liabilities) − (receivables + inventory)) / revenue | latest BS |
| `net_burn_multiple` | −FCF / revenue increase | FCF < 0, revenue up, 8 quarters |
| `cash_runway_months` | liquid cash / (−FCF / 12) | FCF < 0 |
| `esop_adj_fcf`, `liquid_cash` | FCF − ESOP; cash + bank + current investments | — |
| `reverse_dcf_implied_g` | g such that 5-year DCF (WACC 12%, terminal 4%) = EV | FCFF > 0, EV > 0 |
| `pe_percentile`, `ev_ebitda_percentile` | rank vs own prior quarter-end values | ≥ 4 prior quarters |

### 10.8b Zero-drop line items (C24)

Every numeric XBRL line item is a fact: curated tags for the ratio engine, `li_<element>` for every other element,
`oth_<element>__<label>` for amounts on text-labelled "Others"/"Details" members, `asfiled_<element>` for a value a
named rule withholds. `fact_observations.line_item_category` / `parent_subtotal` place each line under its subtotal.
Ratios still read only curated tags; line items are for statements, sub-rows and audits.

### 10.9 Annual-statement ratios (Reg. 34, C23) and Reg. 30 event counts (E3-E7)

| Column | Definition |
|---|---|
| `piotroski_f` | Piotroski F-score 0..9 for the latest 12-month FY in the row's scope; year-end total assets (C23); NULL without a post-cutoff prior FY |
| `beneish_m` | Beneish 8-variable M-score (SG&A proxy = `OtherExpenses`); NULL without a post-cutoff prior FY |
| `capex_to_depreciation`, `cwip_to_gross_block`, `rote`, `rnd_and_royalty_intensity`, `contingent_liabilities_to_net_worth`, `annual_fy_end` | FY ratios from the Reg. 34 notes (PPE schedule X71, notes X73) |
| `order_wins_90d`, `order_value_90d`, `kmp_resignations_90d`, `auditor_resignations_90d`, `fraud_or_default_90d` | Reg. 30 events visible at the as-of and disclosed in the 90 days to it (`corporate_events`) |
| `penalties_90d` | NULL: no penalty / regulatory-action filing observed (UNVERIFIED, E7) |
| `roce_screener`, `debtor_days`, `inventory_turnover`, `working_capital` | Screener export formulas (S22) on our Screener-style statement rows, latest FY; kept beside our own `roce` (operating EBIT over closing capital) |
| `inventory_days`, `days_payable`, `cash_conversion_cycle`, `working_capital_days` | closing balance / (Sales / 365); cycle = debtor + inventory − payable days; working-capital days on (CA − cash − current investments − CL) (S23: matches the website on TCS; CCC does not) |

Revisions (E9, E10): `filing_revisions` links a filing to the one it supersedes (REVISION or byte-identical RESEND);
PIT reads already take the latest version visible at the as-of, so the link is provenance, not a read path.
Linking is order-independent: a promoted filing is linked to the latest earlier-visible filing of the same key, and
the earliest later-visible filing already promoted is linked to it (a reverse-order replay gives the same pairs;
when a middle filing arrives last a non-adjacent pair can also be linked, which "supersedes" allows as transitive).
A later filing for the same key is **not** always the better one: some companies file a "Fourth quarter" and then a
"Yearly" XBRL whose quarter column is mis-dated (X82), so the read path never drops a superseded filing wholesale.

### 10.7 `screener_features` columns in Phase 1

Source of truth: `screener_features_history` in `schema.sql`; aliases in `financials.dsl.ALIASES`.

| Status | Columns |
|---|---|
| **Active** (always computed when a bar exists) | `close`, `price_date`, `return_1m/3m/6m/12m` (need 22/64/127/253 bars), `price_to_dma50/200` (50/200 bars), `dist_52w_high` (252 bars), `deliv_avg_5d/20d`, `delivery_velocity`, `in_nifty500` |
| **Active once the input filing is visible** | `shares` (+`shares_source`), `market_cap`, `promoter_holding_pct`, `promoter_pledge_pct`, `promoter_encumbered_pct`, `fii_holding_pct`, `fpi_holding_pct`, `dii_holding_pct`, `public_holding_pct`, `non_promoter_non_public_pct`, `float_turnover_pct`, `shp_as_of` (Reg. 31; `promoter_pct`/`fii_pct`/`dii_pct` kept as deprecated duplicates for saved screens); `fii_dii_qoq_change_pct` (needs the filing for the immediately preceding quarter end, both visible); `total_equity`, `net_debt`, `pb`, `debt_to_equity`, `bs_as_of` (H1/FY balance sheet); `altman_z_dd` (H1/FY BS + TTM EBIT; OtherEquity proxy) |
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

## 11.8c Derived quarters in statements

Statement builders read a point-in-time FactBook through `fundamentals.BookAsResult`. A flow not filed for exactly
`(start, end)` is derived as YTD(s0, end) − YTD(s0, start − 1 day): Q4 = FY − 9M for the P&L and H2 = FY − H1 for the
cash flow. The book holds one entity and one scope, so standalone FY − consolidated 9M is never formed, and the derived
value exists only once both filings are visible (visibility = the later broadcast). `FactBook.quarter` and
`ttm_from_ytd` apply the same rule for TTM (`tests/test_q4_derivation.py`; no real 9-month filing is a fixture yet).

## 11.9 Knowledge modes and feature snapshots

`screener_features_history` holds one row per security in the universe per materialised `as_of_date`: a full
daily snapshot, not a change log. `screen --as-of D` reads `as_of_date = D` exactly; a date that was never
materialised returns no rows. Re-materialising a date replaces that date's rows (the inputs stay append-only), and
`rebuild-market` deletes the history from its date before replaying. Unchanged rows are not deduplicated: a screen
on `D` needs the full universe of `D`, and ~2,500 securities × ~530 sessions (2024-10 → 2026-11) is ~1.3 M rows.

Price inputs are read in one of two knowledge modes (`features._price_inputs`):
- `valid` (default; all materialised history): what the market knew on `D`. A corporate action counts from its
  ex-date and a GAP finding freezes the series until resolved, whenever the resolution happened. A fix of our
  pipeline (an unparsed split, a missed action) is a correction, not new information. Rule resolutions
  (FIXED_BY_RULE) are written at promotion time, so a backfill run today would otherwise freeze every split.
- `system` (`compute_rows(..., knowledge="system")`): what this system had decided by `as_of_ts` (an action counts
  once `decided_at <= as_of_ts`; a finding freezes if created by then and not resolved by then). For auditing what
  the live system showed; never written to history.

## 12. Promoter quality gates (in order)

| Gate | Rule | On failure |
|---|---|---|
| G1 Completeness | EQ/BE/BZ rows ≥ 92% of the trailing 5-trading-day median | Abort batch; keep previous state; retry later |
| G2 Identifier resolution | Every raw price row resolves to a `security_id` via `(exchange, fin_instrm_id \| symbol+series, isin, date)`; unresolved rows ≤ 1% | Every unresolved row carries an identity issue (missing `FinInstrmId`, ISIN collision, out of order, duplicate) and is quarantined `IDENTIFIER/…`; above 1% → abort. `quarantine reprocess` loads a missing-`FinInstrmId` bar by ISIN |
| G3 Accounting identities | Per filing, in the parsers (staged issues): P&L chain (X9 / bank equivalents), `Assets = EquityAndLiabilities` when BS present, expense components sum to `Expenses`; tolerance §7.3 | Quarantine that filing only |
| G4 Null-spike (features) | Null rate of `close`, `market_cap`, `sales_ttm`, `pat_ttm`, `total_equity` rises ≤ 1.5 percentage points vs the previous materialised date. Rule G4_C9_WINDOW: a TTM that turns NULL because the company's latest quarter moved forward and the new 4-quarter window reaches before the financials cutoff (C9) is not counted; on the live backfill this is every company filing Q1–Q3 FY26 (Jul 2025–Jan 2026), until four in-scope quarters exist | Abort; previous features stay live |
| G5 Atomic features | Row count = universe (securities with a bar in the last 15 days and a valid identifier); history rows for the date and the live table replaced in one transaction | No partial state is ever visible |
| ORDER | Market days and index snapshots must arrive in date order | Abort. `promote` holds later market days behind an aborted one, so a day that fails G1 is never overtaken; an older day found later needs `rebuild-market --from D` |
| CAL3 No-session inference | After a market day, its `PrvsClsgPric` vs the previous promoted close: ≥ 99% of ≥ 100 common securities equal → the dates in between had no session (`trading_calendar.source = INFERRED_PREV_CLOSE`) | Otherwise `CALENDAR/MISSING_SESSION` (a session is missing from the database) |
| Delivery | A delivery file for another date than its bhavcopy | `DELIVERY/DELIVERY_DATE_MISMATCH`; the file is vaulted, not joined. A delivery fetched after its bhavcopy fills `deliv_qty` on the promoted bars |
| Inactive securities | Open identifier interval with no bar in the last 20 promoted sessions (CHOICE, ID1) | Closed the day after the last bar; reopens via `FinInstrmId` when it trades again |
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

## 14b. Statement builder: quarterly rows (Mandate 4, first slice)

`financials/statements/quarterly.py` builds Screener-style quarterly rows from **our** definitions. Every row
keeps its sub-rows, so any figure can be traced to XBRL. `tie_out` must return exactly 0, to the rupee:
Revenue − Expenses − Interest − Depreciation + Other Income (+ bank exceptional) = PBT. Divergences from Screener
are reported in `QuarterStatement.divergences`, never imitated. Evidence: S1–S7.

| Row | INDAS_CORP (canonical tags) | Sub-rows |
|---|---|---|
| Sales | `revenue_from_operations − excise_duty` | revenue from operations, less excise |
| Expenses | `total_expenses − depreciation − finance_costs − excise_duty` | materials, stock-in-trade purchases, inventory change, employee cost, other expenses net of excise |
| Operating Profit | Sales − Expenses | — |
| Other Income | `other_income + exceptional_items` [S2] | reported other income, exceptional items |
| Depreciation / Interest / Tax | as reported | tax: current, deferred |
| Profit before tax | `pbt` (associates excluded: `ASSOCIATES_PLACEMENT` [S3]) | before exceptional, exceptional |
| Net Profit | `pat_owners`, else `pat` | continuing PAT, regulatory deferral, discontinued, associates, PAT, less NCI |

Banks, NBFCs, life and general insurers use the raw-element formulas in S4–S7 until their parsers land
(Mandate 2 batches 4–6). They then switch to canonical tags with the same tests. Annual-only sub-rows
(fixed-asset schedule, notes) are NULL on quarterly statements. The Screener export carries only the
Data Sheet rows, so golden parity covers top-level rows only. Sub-rows are checked by summation, not by golden values.

### 14b-1. Expense sub-rows and segments (X49, X50, X97-X99)

Expenses sub-rows add **Power and fuel** and **Freight** when the filer labels them (named label rules). They stay NULL
when it doesn't, and the rest of other expenses absorbs them, so the sub-rows still sum to Expenses.

**Segments are persisted** (owner decision 2026-11-14) in `segment_observations`, one row per member fact:
`axis_kind` (BUSINESS | GEOGRAPHY), `axis`, `member`, `label` and `element` exactly as filed, `member_role` derived from
the member name only (SEGMENT, UNALLOCATED, ELIMINATION, RECONCILING; DOMICILE, FOREIGN_TOTAL, FOREIGN, AREA),
`canonical_metric` derived from the element only (`segments.SEGMENT_METRICS`), periods as in `fact_observations`
(instants store `period_start = period_end`), `value_inr DECIMAL(20,2)`, and the filing's `entity_id`, `scope`,
`parser_version` and `visible_from_ts`. Primary key (filing_id, parser_version, axis, member, element, period_start,
period_end): no nullable key column.
- **Sources.** Quarterly results (every profile that files the four `ReportableSegment*Axis` elements: corporate,
  NBFC, bank, life insurer) and Reg. 34 annual (`EntitySReportableSegmentsAxis`, `GeographicalAreasAxis`). The
  Integrated Filing has no geography axis. Elements no committed fixture shows (e.g. segment tax, capex additions,
  equity-method investments) are not mapped; they stay in `raw_xbrl_facts`.
- **How.** `parsers/segments.py` is pure (bytes -> rows + findings) and keeps only facts in the periods the filing's
  own parser validated (`Windows.from_meta`: declared quarter / YTD and period end, or the Reg. 34 in-scope years);
  a declared pre-cutoff year is skipped (C9), any other context outside the declared periods is a finding.
  `stage_results_xbrl` stages `stg_segments` with the filing and the promoter inserts them in the same transaction
  as `fact_observations`. A quarantined or out-of-scope filing promotes none. PARSER_VERSION 0.10.0 restages.
- **Checks (non-blocking findings, stage `SEGMENT`).** SEGMENT_SUM (members vs the filed non-dimensional total,
  within the LevelOfRounding tolerance; with unallocated / elimination members also accepted), SEGMENT_RECONCILING
  (reconciling = unallocated + eliminations), GEOGRAPHY_FOREIGN_SUM (ForeignCountriesMember = its ForeignCountryN
  children), SEGMENT_ASSETS (segment + unallocable = net segment assets). A finding is promoted with the filing and
  opens a quarantine row; it never blocks the filing or corrects a value. Net segment assets vs total assets is a
  warning only.
- **Reader.** `fundamentals.load_segments(con, entity_id, scope, as_of)`: each filing's current parser version,
  `visible_from_ts <= as_of`, and per (axis, element, period) every member of the latest visible filing. Members are
  per-filing ids (`ReportableSegments1Member` may be another business in another filing), so two filings' members are
  never mixed.
- **What is never done with them.** Segment rows never feed `fact_observations`, the factbook, a P&L row, a ratio or a
  screen, and no cross-company segment taxonomy is built: labels are free text. Segment totals are not P&L
  substitutes (Cummins: segment revenue is before inter-segment elimination; segment PBT includes associates).
  Unchanged from C24: labelled quarterly members also appear in `fact_observations` as `oth_segment_*` line items, and
  Reg. 34 domicile / foreign revenue as `revenue_domestic` / `revenue_foreign` [X75].

### 14c. Annual statements and conventions (S10-S15)

**Balance sheet** (`statements/balance_sheet.py`; H1 and FY ends only; Q1/Q3 NULL):

| Row | Definition | Sub-rows |
|---|---|---|
| Equity Capital | `equity_share_capital` | — |
| Reserves | `other_equity` (owners only) | — |
| Borrowings | borrowings (NC + C) + lease liabilities (NC + C, label rule) | the four lines |
| Other Liabilities | Total − Equity Capital − Reserves − Borrowings | NCI, trade payables, other |
| Total | `total_assets − min(DTA, DTL)` when both are positive | deferred tax netted |
| Net Block | PPE + investment property + goodwill + other intangibles + ROU (label rule) | the five lines |
| CWIP | CWIP + intangibles under development | both |
| Investments | non-current + current + equity-method | the three lines |
| Other Assets | Total − Net Block − CWIP − Investments | receivables (current), inventory, cash & bank, other |

**Cash flow** (`statements/cashflow.py`; YTD only, so H1 and FY; Q1/Q3 NULL): CFO as filed = Profit from operations
(cash generated − working-capital changes) + Receivables + Inventory + Payables + Loans & Advances + Other WC items
+ Direct taxes + Other operating items; CFI = fixed assets purchased/sold, interest and dividends received, other;
CFF = borrowings in/out, interest, dividends, leases, shares, other; Net Cash Flow after FX. Groupings are listed in
`WC_GROUPS`. Every "other" row is the residual, so sub-rows always sum to the filed total.

**Conventions**
- Signs: P&L costs positive, as filed. Cash flow positive = cash in. We show Change in Inventory with the XBRL sign;
  Screener reverses it.
- Rounding: we keep rupees (`DECIMAL(20,2)`). Comparisons with Screener use ₹ Cr to 2 dp with ±0.01 tolerance,
  because filings in ₹ lakh round differently.
- Scope: consolidated when a consolidated filing exists, else standalone (S1; Mandate 3 makes this per company).
- Quarterly vs annual-only: quarterly statements carry the P&L rows of §14b; BS and CF only at H1/FY. Annual-only
  sub-rows (other-expense split, dividend amount, fixed-asset schedule, notes) are NULL on every quarterly statement
  and wait for the Reg. 34 parser.
- Divergence codes: `ASSOCIATES_PLACEMENT`, `BANK_EXCEPTIONAL`, `LIFE_TRANSFER_GROSSUP`, `FX_IN_INVESTING`.
  Unexplained residuals are pinned in the parity harness (S11, S13), never imitated.

## 15. Phases

**Phase 1: thin slice, screenable end-to-end (Nifty 500)**

Status (2026-11-13): **built and tested end to end** on real fixtures, all listed items below, plus index backfill (§11.6), quarantine resolution (D-6) and benchmarks (`docs/benchmarks.md`). Known gaps inside Phase 1:
- `piotroski_f` / `beneish_m` columns exist but stay NULL: both need year-over-year annual data (Reg. 34, Phase 2).
- Altman Z'' uses OtherEquity as the retained-earnings proxy; ROCE and ROE use the latest balance sheet (ROE by decision, C16); ROIC, CROIC, RoA, NIM proxy and credit cost use opening + closing averages.
- EV adds minority interest (`NonControllingInterest`, VERIFIED [X34, X42]); preference capital is still excluded (no tag seen). PE and ROE use the owners' share of profit and equity [X42].
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

**Gaps against the owner's master blueprint (reviewed 2026-11-14), still open:**
- Restatement detector (blueprint §3.2): the YTD-vs-quarters identity is **built** [X80] (TTM withheld over a broken
  year, `CONSISTENCY/YTD_QUARTER_MISMATCH` findings, `audit-ytd`). Still open: the extra triggers on
  `ProfitLossFromDiscontinuedOperations` ≠ 0 and on a demerger/merger in `corp_actions` when the identity happens to
  hold, and any recovery of restated quarters (NSE XBRL has no prior-period columns; PDFs are out of scope).
- AOC-1 subsidiary tree from Reg. 34 (only AOC-1-like elements seen so far [X75]; needs a fixture with the schedule).
- Merger lineage (`merged_into`, swap ratio, position conversion) and demerger cost-of-acquisition split; today
  `MERGED` exists only for duplicate-security repair.
- Reg. 76 exact share count (F09 UNVERIFIED); Reg. 31 cross-checked with paid-up capital stands in.
- The blueprint files AMFI holdings, PIT/SAST/SDD and bulk/block deals under Phase 2; they stay in Phase 3 here
  because their sources are UNVERIFIED (F11, F13, R8) or only OBSERVED (F14).
- Deliberate divergences: special dividends never adjust prices (invariant 8; the blueprint's §4.2 factor is not
  used), and context ids (`OneD`, `FourD`, `OneI`) are never trusted as period labels (invariant 6; [SHP16]).

**Owner requirements (2026-11-14):** every item from the owner's requirements chat, with status and the phased to-do of what is still missing, is in `docs/owner_requirements.md`.

**Pre-work before Phase 3:** a verified Nifty 500 TRI source (F29) for backtest benchmarks; real fixtures for PIT
(F11), SDD (F13), credit-rating and debt XBRL (F22) and BRSR (F24); a per-AMC adapter plan for monthly portfolios (R8).

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
| D-3 | Phase 2 fixtures | **Done** (2026-11-13): lending NBFC, life insurer, consolidated corporate with NCI, H1 bank, Reg. 34 annual and pledged Reg. 31 committed with evidence tests [X32-X38, SHP7]. Still useful later: Q1/Q3 corp, a loss-valued exceptional item. (Employee-trust shareholding: Batch 8, Vedanta/JSW [SHP8].) |
| D-4 | Corporate-actions source | **Decided**: NSE API adapter (+ RSS for discovery); unparseable purposes → QUARANTINED. BSE fallback not built (`api.bseindia.com` returned 403 [A1]) |
| D-6 | How a human resolves a quarantine | **Built**: `financials quarantine list` / `inspect Q` (context + the exact resolving commands) / `resolve --action ACCEPT\|REJECT\|OVERRIDE\|CORP_ACTION\|MERGE_SECURITIES --note …` / `reprocess` (`financials.admin`). One transaction; rows are never deleted; every change is logged in `company_overrides`. `CORP_ACTION` must verify against the observed gap; records of that date the parser could not factor (UNKNOWN purpose, failed verification) are retired as `SUPERSEDED`, the manual action is stored `VERIFIED_MANUAL`, and the adjusted series unfreezes. `REJECT` on a corporate-action finding retires that record (`REJECTED`). `OVERRIDE` takes only fields the promoter reads: `broadcast_ts` for `NO_VISIBILITY` and `security_id` for identity failures of a filing (`filing_overrides`), applied at once by promoting that filing again. `MERGE_SECURITIES` repoints identity, prices, actions, index rows and quarantine links to the `FinInstrmId` owner, tombstones the duplicate entity as `MERGED`, and loads the colliding bar from raw (SIGMA case [P14]). `reprocess` re-promotes batches with open identity / visibility findings. Known-defect rules (D-2) are still not built |
| D-5 | Historical index-membership backfill source | Snapshot-forward only [L1] |
