# Architecture: Indian Equity Research & Screening Engine

Claim IDs in brackets (e.g. [X2], [P5]) point to `docs/references.md`. Anything marked
UNVERIFIED there must not be hard-coded; code that depends on it quarantines on surprise.

---

## 1. Scope

- **Purpose:** personal, single-user research, screening and point-in-time (PIT) backtesting. No redistribution [C8].
- **Universe v1:** NSE Mainboard `EQ`, `BE`, `BZ`, starting with the Nifty 500 [C7]. SME (`SM`, `ST`) out of scope. BSE is used only as a fallback and for historical Reg. 34 annual XBRL backfill.
- **Non-goals (v1):** multi-user, UI hosting, Cloudflare (R2/D1/Workers), real-time intraday prices, SME/Indian-GAAP corporates.

## 2. Runtime topology

| Where | What runs |
|---|---|
| **Local machine** (owner's) | All fetchers (both `www.nseindia.com` session-cookie fetchers and `nsearchives.nseindia.com` archive fetchers), the vault, staging Parquet, the promoter, `data/market.duckdb`. |
| **GitHub Actions** | Offline `pytest` on every push and PR (`.github/workflows/ci.yml`). Tests never touch the network. |

Open decision **D-1** (see §16): scheduled archive fetching *in* GitHub Actions has no durable place to keep the data (`data/` is gitignored, artifacts expire, Cloudflare is deferred). Until D-1 is settled, every fetch runs locally.

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
| Index constituents (current) | `nsearchives…/content/indices/ind_nifty500list.csv` | CSV | OBSERVED [A6] | 1 |
| Quarterly results XBRL | `nsearchives…/corporate/xbrl/<file>.xml`; discovery via `www.nseindia.com` API | XBRL | Files VERIFIED [X1]; discovery UNVERIFIED [A7] | 1 (corp), 2 (others) |
| Reg. 30 event XBRL | `content/RSS/Online_announcements.xml` → `corporate/xbrl/` links | RSS + XBRL | OBSERVED [A3] | 3 |
| Corporate actions | UNVERIFIED [P12] | ? | — | 1 |
| Shareholding (Reg. 31) | UNVERIFIED | XBRL | — | 1 (total shares), 2 (full) |
| Reg. 34 annual XBRL | UNVERIFIED [R2] | XBRL | — | 2 |
| F&O, SLBM, AMC portfolios, macro | UNVERIFIED | various | — | 3 |

Fetch etiquette: ≥1 s between requests per host, exponential backoff with jitter on 403/429/5xx, never re-download a blob whose URL+ETag/sha is already vaulted, and keep a fixed, honest User-Agent per run.

## 4. Storage layers

| Layer | Contents | Mutability |
|---|---|---|
| L0 Vault | `blobs`, `filings`, files under `data/vault/` | Append-only. Never rewritten. |
| L1 Raw | `raw_xbrl_facts`, `raw_cm_bhavcopy`, `raw_delivery`, `raw_index_snapshot`, all keyed by **source identifiers** (symbol, series, ISIN as the exchange sent them) | Append-only. Re-parse appends new rows keyed by `parser_version`. |
| L2 Canonical | Identity (`entity_master`, `securities`, `security_identifier_history`), `ohlcv`, `filing_meta`, `fact_observations`, `corp_actions`, `index_constituents_history`, `trading_calendar` | Rebuildable from L0/L1 + `quarantine_queue` resolutions + `company_overrides`. |
| L3 Derived | Adjustment factors, adjusted prices, total-return index, `screener_features`, snapshots | Fully rebuildable. Swapped atomically. |

## 5. Schema (DuckDB DDL, Phase 1 core)

Conventions:
- Timestamps are `TIMESTAMPTZ` stored in UTC. IST is used only at parse and display boundaries.
- Money is `DECIMAL(20,2)` rupees [C1]. Prices are `DECIMAL(18,4)`. Ratios are `DOUBLE`.
- IDs are ULID strings.

```sql
-- ── L0 Vault ─────────────────────────────────────────────────────────────
CREATE TABLE blobs (
    sha256            VARCHAR PRIMARY KEY,
    byte_size         BIGINT  NOT NULL,
    media_type        VARCHAR NOT NULL,
    storage_path      VARCHAR NOT NULL,          -- data/vault/<sha[:2]>/<sha>.<ext>
    first_fetched_at  TIMESTAMPTZ NOT NULL
);

-- A filing is one publication of a blob. The same blob mirrored on NSE and BSE,
-- or re-sent unchanged, is one blob with two filings.
CREATE TABLE filings (
    filing_id            VARCHAR PRIMARY KEY,
    sha256               VARCHAR NOT NULL REFERENCES blobs(sha256),
    exchange             VARCHAR NOT NULL,       -- NSE | BSE
    category             VARCHAR NOT NULL,       -- RESULTS_XBRL | ANNUAL_XBRL | SHP_XBRL | REG30_XBRL
                                                 -- | BHAVCOPY_CM | DELIVERY | INDEX_LIST | CORP_ACTIONS
    source_url           VARCHAR NOT NULL,
    exchange_ref         VARCHAR,                -- exchange-assigned id, if any
    stated_symbol        VARCHAR,                -- as published, unresolved
    stated_isin          VARCHAR,
    broadcast_ts         TIMESTAMPTZ,            -- exchange dissemination time; NULL if unknown
    broadcast_ts_source  VARCHAR NOT NULL,       -- RSS_PUBDATE | API_FIELD | EOD_RULE | UNKNOWN
    fetched_at           TIMESTAMPTZ NOT NULL,
    supersedes_filing_id VARCHAR REFERENCES filings(filing_id),  -- revised filing
    UNIQUE (exchange, source_url, sha256)
);

-- ── L1 Raw (source identifiers only, no surrogate IDs) ──────────────────
CREATE TABLE raw_cm_bhavcopy (
    filing_id      VARCHAR NOT NULL REFERENCES filings(filing_id),
    exchange       VARCHAR NOT NULL,
    trade_date     DATE    NOT NULL,
    fin_instrm_id  VARCHAR,                      -- UDiFF FinInstrmId
    isin           VARCHAR NOT NULL,
    symbol         VARCHAR NOT NULL,
    series         VARCHAR NOT NULL,
    open           DECIMAL(18,4), high DECIMAL(18,4), low DECIMAL(18,4),
    close          DECIMAL(18,4) NOT NULL,
    last           DECIMAL(18,4),
    prev_close_reported DECIMAL(18,4),           -- unadjusted [P2]; informational only
    volume         BIGINT,
    turnover_inr   DECIMAL(20,2),
    trades         BIGINT,
    PRIMARY KEY (exchange, trade_date, symbol, series, filing_id)
);

CREATE TABLE raw_delivery (
    filing_id   VARCHAR NOT NULL REFERENCES filings(filing_id),
    exchange    VARCHAR NOT NULL,
    trade_date  DATE    NOT NULL,
    symbol      VARCHAR NOT NULL,
    series      VARCHAR NOT NULL,
    traded_qty  BIGINT,
    deliv_qty   BIGINT,
    deliv_pct   DOUBLE,
    PRIMARY KEY (exchange, trade_date, symbol, series, filing_id)
);

CREATE TABLE raw_index_snapshot (
    filing_id      VARCHAR NOT NULL REFERENCES filings(filing_id),
    index_name     VARCHAR NOT NULL,             -- NIFTY 500
    snapshot_date  DATE    NOT NULL,
    symbol         VARCHAR NOT NULL,
    series         VARCHAR NOT NULL,
    isin           VARCHAR NOT NULL,
    company_name   VARCHAR,
    industry       VARCHAR,
    PRIMARY KEY (index_name, snapshot_date, isin)
);

CREATE TABLE raw_xbrl_facts (
    filing_id       VARCHAR NOT NULL REFERENCES filings(filing_id),
    parser_version  VARCHAR NOT NULL,
    element_ns      VARCHAR NOT NULL,
    element_name    VARCHAR NOT NULL,
    context_id      VARCHAR NOT NULL,
    ctx_start       DATE,                         -- as written in the context (may be wrong [X26])
    ctx_end         DATE,
    ctx_instant     DATE,
    dimensions      JSON,                         -- {"RelatedPartyTransactionAxis": "...", ...}
    unit_ref        VARCHAR,
    decimals        VARCHAR,                      -- recorded, never trusted [X5]
    value_text      VARCHAR
);

-- ── L2 Identity ─────────────────────────────────────────────────────────
CREATE TABLE entity_master (
    entity_id      VARCHAR PRIMARY KEY,
    legal_name     VARCHAR NOT NULL,
    cin            VARCHAR UNIQUE,
    status         VARCHAR NOT NULL DEFAULT 'ACTIVE', -- ACTIVE | MERGED | DELISTED | SUSPENDED
    inactive_date  DATE,
    exit_reason    VARCHAR
);

CREATE TABLE securities (
    security_id  VARCHAR PRIMARY KEY,
    entity_id    VARCHAR NOT NULL REFERENCES entity_master(entity_id),
    share_class  VARCHAR NOT NULL                  -- COMMON | DVR | PARTLY_PAID
);

-- Splits change ISIN [P5]; symbols get renamed; series move EQ↔BE↔BZ.
CREATE TABLE security_identifier_history (
    security_id     VARCHAR NOT NULL REFERENCES securities(security_id),
    exchange        VARCHAR NOT NULL,
    fin_instrm_id   VARCHAR,                       -- stable across ISIN change [P5, P8]; reuse UNVERIFIED [P9]
    symbol          VARCHAR NOT NULL,
    series          VARCHAR NOT NULL,
    isin            VARCHAR NOT NULL,
    bse_scrip_code  VARCHAR,
    valid_from      DATE NOT NULL,
    valid_to        DATE,                          -- NULL = current
    evidence_filing_id VARCHAR REFERENCES filings(filing_id),
    PRIMARY KEY (security_id, exchange, valid_from)
);

CREATE TABLE entity_classification_history (
    entity_id           VARCHAR NOT NULL REFERENCES entity_master(entity_id),
    valuation_archetype VARCHAR NOT NULL,           -- INDUSTRIAL_SERVICES | FINANCIAL_LENDING | INSURANCE | NEW_GEN_TECH
    macro_sector VARCHAR, sector VARCHAR, industry VARCHAR, basic_industry VARCHAR,
    valid_from          DATE NOT NULL,
    valid_to            DATE,
    source              VARCHAR NOT NULL,           -- INDEX_LIST | MANUAL_OVERRIDE | …
    PRIMARY KEY (entity_id, valid_from)
);

CREATE TABLE trading_calendar (
    exchange    VARCHAR NOT NULL,
    cal_date    DATE    NOT NULL,
    is_trading  BOOLEAN NOT NULL,                  -- historical truth = a bhavcopy exists for the date
    note        VARCHAR,
    PRIMARY KEY (exchange, cal_date)
);

CREATE TABLE index_constituents_history (
    index_name   VARCHAR NOT NULL,
    security_id  VARCHAR NOT NULL REFERENCES securities(security_id),
    valid_from   DATE NOT NULL,
    valid_to     DATE,
    source       VARCHAR NOT NULL,                 -- SNAPSHOT | MANUAL_BACKFILL
    PRIMARY KEY (index_name, security_id, valid_from)
);

-- ── L2 Market ───────────────────────────────────────────────────────────
CREATE TABLE ohlcv (                               -- resolved, unadjusted
    security_id  VARCHAR NOT NULL REFERENCES securities(security_id),
    exchange     VARCHAR NOT NULL,
    series       VARCHAR NOT NULL,
    trade_date   DATE    NOT NULL,
    open DECIMAL(18,4), high DECIMAL(18,4), low DECIMAL(18,4), close DECIMAL(18,4) NOT NULL,
    volume       BIGINT,
    turnover_inr DECIMAL(20,2),
    deliv_qty    BIGINT,
    price_filing_id    VARCHAR NOT NULL REFERENCES filings(filing_id),
    delivery_filing_id VARCHAR REFERENCES filings(filing_id),
    PRIMARY KEY (security_id, exchange, series, trade_date)
);

-- ── L2 Fundamentals ─────────────────────────────────────────────────────
CREATE TABLE filing_meta (                          -- one row per parsed XBRL filing
    filing_id            VARCHAR PRIMARY KEY REFERENCES filings(filing_id),
    parser_version       VARCHAR NOT NULL,
    entity_id            VARCHAR NOT NULL REFERENCES entity_master(entity_id),
    accounting_profile   VARCHAR NOT NULL,          -- from namespace [X1]: INDAS_CORP | INDAS_NBFC | IGAAP_BANK
                                                    -- | IRDAI_GENERAL | IRDAI_LIFE
    taxonomy_ns          VARCHAR NOT NULL,
    scope                VARCHAR NOT NULL,          -- STANDALONE | CONSOLIDATED [X6]
    level_of_rounding    VARCHAR NOT NULL,          -- Rupees | Thousands | Lakhs | Millions | Crores
    fy_start             DATE NOT NULL,
    fy_end               DATE NOT NULL,
    reporting_quarter    VARCHAR,
    audited              BOOLEAN,
    board_meeting_end_ts TIMESTAMPTZ,
    visible_from_ts      TIMESTAMPTZ NOT NULL,      -- §6.3
    visible_from_source  VARCHAR NOT NULL,          -- BROADCAST | BOARD_MEETING_RULE
    interest_paid_cfo_class VARCHAR,                -- OPERATING | FINANCING | NONE | MIXED [X14]
    interest_recd_cfo_class VARCHAR                 -- OPERATING | INVESTING | NONE | MIXED
);

-- Long-format canonical facts. Never updated in place: a revision is a new filing,
-- a re-parse is a new parser_version.
CREATE TABLE fact_observations (
    filing_id       VARCHAR NOT NULL REFERENCES filings(filing_id),
    parser_version  VARCHAR NOT NULL,
    entity_id       VARCHAR NOT NULL,
    scope           VARCHAR NOT NULL,
    canonical_tag   VARCHAR NOT NULL,               -- revenue_ops, pbt, borrowings_current, …
    period_start    DATE,                           -- NULL for instants
    period_end      DATE NOT NULL,
    period_months   INTEGER,                        -- NULL for instants; 1..18
    unit            VARCHAR NOT NULL,               -- INR | INR_PER_SHARE | PURE | SHARES
    value_inr       DECIMAL(20,2),                  -- when unit = INR
    value_other     DECIMAL(28,8),                  -- otherwise
    source_element  VARCHAR NOT NULL,               -- raw element name(s)
    visible_from_ts TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (filing_id, parser_version, canonical_tag, period_end, period_start),
    CHECK ((unit = 'INR') = (value_inr IS NOT NULL))
);

-- ── Corporate actions & control ─────────────────────────────────────────
CREATE TABLE corp_actions (
    action_id         VARCHAR PRIMARY KEY,
    entity_id         VARCHAR NOT NULL REFERENCES entity_master(entity_id),
    security_id       VARCHAR REFERENCES securities(security_id),
    action_type       VARCHAR NOT NULL,             -- SPLIT | BONUS | RIGHTS | DEMERGER | MERGER | DIVIDEND | CONSOLIDATION
    ex_date           DATE NOT NULL,
    record_date       DATE,
    ratio_num         DECIMAL(18,6),
    ratio_den         DECIMAL(18,6),
    issue_price       DECIMAL(18,4),                -- RIGHTS
    cash_per_share    DECIMAL(18,4),                -- DIVIDEND (total-return only)
    price_factor      DOUBLE,                       -- multiply prices before ex_date
    eps_factor        DOUBLE,                       -- multiply per-share figures before ex_date (share-count events only)
    observed_gap      DOUBLE,                       -- Open_ex / Close_{ex-1}
    status            VARCHAR NOT NULL DEFAULT 'PENDING', -- PENDING | VERIFIED | UNOBSERVABLE | QUARANTINED | VERIFIED_MANUAL
    related_entity_id VARCHAR REFERENCES entity_master(entity_id),
    coa_pct           DOUBLE,                       -- cost-of-acquisition split for this side of a demerger
    source_filing_id  VARCHAR NOT NULL REFERENCES filings(filing_id)
);

CREATE TABLE quarantine_queue (
    quarantine_id   VARCHAR PRIMARY KEY,
    stage           VARCHAR NOT NULL,               -- FETCH | PARSE | PERIOD | IDENTITY | IDENTIFIER | CORP_ACTION | GAP | GATE
    reason_code     VARCHAR NOT NULL,
    entity_id       VARCHAR,
    security_id     VARCHAR,
    filing_id       VARCHAR,
    details         JSON NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL,
    resolved_at     TIMESTAMPTZ,
    resolution      VARCHAR,                        -- ACCEPTED | REJECTED | FIXED_BY_RULE | OVERRIDDEN
    resolution_note VARCHAR
);

CREATE TABLE company_overrides (                    -- human decisions, each with a reason
    override_id  VARCHAR PRIMARY KEY,
    entity_id    VARCHAR NOT NULL REFERENCES entity_master(entity_id),
    field        VARCHAR NOT NULL,                  -- e.g. valuation_archetype
    value        VARCHAR NOT NULL,
    valid_from   DATE NOT NULL,
    valid_to     DATE,
    reason       VARCHAR NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL
);
```

L3 objects (views or tables rebuilt by the promoter): `price_adj_factors`, `ohlcv_adj`, `total_return_index`, `screener_features`, `screener_features_snapshots`, `user_custom_ratios`. Phase 2 adds `shareholding_observations` and `supplemental_kpis`. Phase 3 adds the event, F&O and AMC tables.

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

### 11.2 Verification
`observed_gap = Open_ex / Close_{ex−1}` from unadjusted `ohlcv` (exchange `PrvsClsgPric` is unadjusted and useless here [P2]).

| Condition | Status |
|---|---|
| \|price_factor − 1\| < 0.10 | `UNOBSERVABLE` (indistinguishable from market noise; accepted, flagged) |
| \|observed_gap / price_factor − 1\| ≤ 0.10 | `VERIFIED` |
| otherwise | `QUARANTINED` |
| DEMERGER | `VERIFIED` once a demerger record exists (the factor is defined from the observed gap) |

### 11.3 Unconditional gap auditor [C4]
Every security, every trading day: if \|Open_t / Close_{t−1} − 1\| > 10% and no corp action is VERIFIED/UNOBSERVABLE/VERIFIED_MANUAL for that date, or the ISIN changed versus t−1 without a SPLIT/CONSOLIDATION record:
- quarantine `GAP`;
- raw and `ohlcv` rows are still stored;
- the **adjusted** series and price-derived features for that security are frozen at t−1 until resolved.

Expected volume is 0–7 per day [P4].

## 12. Promoter quality gates (in order)

| Gate | Rule | On failure |
|---|---|---|
| G1 Completeness | EQ/BE/BZ rows ≥ 92% of the trailing 5-trading-day median | Abort batch; keep previous state; retry later |
| G2 Identifier resolution | Every raw price row resolves to a `security_id` via `(exchange, fin_instrm_id \| symbol+series, isin, date)`; unresolved rows ≤ 1% | Unresolved rows → quarantine; above 1% → abort |
| G3 Accounting identities | Per filing: P&L chain (X9 / bank equivalents), `Assets = EquityAndLiabilities` when BS present, expense components sum to `Expenses`; tolerance §7.3 | Quarantine that filing only |
| G4 Null-spike | Null rate of critical canonical tags (close, market_cap, rev_ops, PAT, Equity) rises ≤ 1.5 percentage points vs the previous promotion | Abort batch |
| G5 Atomic features | Build `screener_features_next`; row count = active universe; swap in one transaction | No partial state is ever visible |

## 13. Schedule (local machine, IST)

| When | Job |
|---|---|
| Trading days from 18:30, retry every 30 min until 23:30 | UDiFF bhavcopy + `sec_bhavdata_full` (publish time UNVERIFIED [P11]) |
| Daily | `ind_nifty500list.csv` snapshot → close/open membership intervals on change |
| Results season, every 2 h; otherwise daily | Results XBRL discovery (local, `www.nseindia.com` API) |
| Daily | Corporate-actions feed (source TBD [P12]) |
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
ALIAS      := a name in the alias registry (case-insensitive, spaces allowed, e.g. "Sales growth 3Years")
```

- Aliases map **only** to whitelisted `screener_features` columns or saved custom ratios.
- Saved custom ratios are expanded before compilation; cycles are rejected.
- Output is parameterised SQL: numbers become bound parameters, columns come from the registry, and no user text reaches SQL.
- Division compiles to `x / NULLIF(y, 0)`. NULL comparisons are false, so a stock missing a metric never passes that filter.
- An unknown alias is a compile error, never a guess.

## 15. Phases

**Phase 1: thin slice, screenable end-to-end (Nifty 500)**
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
| D-1 | Run archive fetchers in GitHub Actions? They need durable storage (artifacts expire; committing data bloats git; Cloudflare deferred). | All fetchers local; CI is offline tests only |
| D-2 | Which known-defect rules (§7.4) to allow | None yet; quarantine |
| D-3 | Fixtures still needed: lending NBFC, life insurer, H1 bank, consolidated corp, Q1/Q3 corp, loss-valued exceptional items, Reg. 34 annual, Reg. 31 shareholding, corp-actions feed sample | Block the related parser until present |
| D-4 | Corporate-actions source [P12] | Undecided |
| D-5 | Historical index-membership backfill source | Snapshot-forward only [L1] |
