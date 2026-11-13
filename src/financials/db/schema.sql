-- Phase 1 schema. Conventions: TIMESTAMP columns are UTC; money DECIMAL(20,2) rupees;
-- prices DECIMAL(18,4); ratios/factors DOUBLE. See docs/architecture.md §5.

-- ── L0 Vault ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS blobs (
    sha256            VARCHAR PRIMARY KEY,
    byte_size         BIGINT  NOT NULL,
    media_type        VARCHAR NOT NULL,
    storage_path      VARCHAR NOT NULL,
    first_fetched_at  TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS filings (
    filing_id            VARCHAR PRIMARY KEY,
    sha256               VARCHAR NOT NULL REFERENCES blobs(sha256),
    exchange             VARCHAR NOT NULL,
    category             VARCHAR NOT NULL,
    source_url           VARCHAR NOT NULL,
    exchange_ref         VARCHAR,
    stated_symbol        VARCHAR,
    stated_isin          VARCHAR,
    broadcast_ts         TIMESTAMP,
    broadcast_ts_source  VARCHAR NOT NULL,
    fetched_at           TIMESTAMP NOT NULL,
    supersedes_filing_id VARCHAR,           -- integrity enforced in code (DuckDB self-FK limitation)
    UNIQUE (exchange, source_url, sha256)
);

-- ── L1 Raw (source identifiers only) ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS raw_cm_bhavcopy (
    filing_id      VARCHAR NOT NULL REFERENCES filings(filing_id),
    exchange       VARCHAR NOT NULL,
    trade_date     DATE    NOT NULL,
    fin_instrm_id  VARCHAR,
    isin           VARCHAR NOT NULL,
    symbol         VARCHAR NOT NULL,
    series         VARCHAR NOT NULL,
    name           VARCHAR,
    open           DECIMAL(18,4),
    high           DECIMAL(18,4),
    low            DECIMAL(18,4),
    close          DECIMAL(18,4) NOT NULL,
    last           DECIMAL(18,4),
    prev_close_reported DECIMAL(18,4),
    volume         BIGINT,
    turnover_inr   DECIMAL(20,2),
    trades         BIGINT,
    PRIMARY KEY (exchange, trade_date, symbol, series, filing_id)
);

CREATE TABLE IF NOT EXISTS raw_delivery (
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

CREATE TABLE IF NOT EXISTS raw_xbrl_facts (
    filing_id       VARCHAR NOT NULL REFERENCES filings(filing_id),
    parser_version  VARCHAR NOT NULL,
    seq             INTEGER NOT NULL,          -- document order
    element_ns      VARCHAR NOT NULL,
    element_name    VARCHAR NOT NULL,
    context_id      VARCHAR NOT NULL,
    ctx_start       DATE,
    ctx_end         DATE,
    ctx_instant     DATE,
    dimensions      JSON,
    unit_ref        VARCHAR,
    decimals        VARCHAR,
    value_text      VARCHAR,
    PRIMARY KEY (filing_id, parser_version, seq)
);

-- ── L2 Identity ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS entity_master (
    entity_id      VARCHAR PRIMARY KEY,
    legal_name     VARCHAR NOT NULL,
    cin            VARCHAR,                 -- no UNIQUE: DuckDB INSERT OR IGNORE treats NULLs as conflicts
    status         VARCHAR NOT NULL DEFAULT 'ACTIVE',
    inactive_date  DATE,
    exit_reason    VARCHAR
);

CREATE TABLE IF NOT EXISTS securities (
    security_id  VARCHAR PRIMARY KEY,
    entity_id    VARCHAR NOT NULL REFERENCES entity_master(entity_id),
    share_class  VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS security_identifier_history (
    security_id        VARCHAR NOT NULL REFERENCES securities(security_id),
    exchange           VARCHAR NOT NULL,
    fin_instrm_id      VARCHAR,
    symbol             VARCHAR NOT NULL,
    series             VARCHAR NOT NULL,
    isin               VARCHAR NOT NULL,
    bse_scrip_code     VARCHAR,
    valid_from         DATE NOT NULL,
    valid_to           DATE,                    -- exclusive; NULL = current
    evidence_filing_id VARCHAR REFERENCES filings(filing_id),
    PRIMARY KEY (security_id, exchange, valid_from)
);

CREATE TABLE IF NOT EXISTS trading_calendar (
    exchange    VARCHAR NOT NULL,
    cal_date    DATE    NOT NULL,
    is_trading  BOOLEAN NOT NULL,
    note        VARCHAR,
    PRIMARY KEY (exchange, cal_date)
);

CREATE TABLE IF NOT EXISTS calendar_coverage (   -- years for which a holiday list was loaded
    exchange          VARCHAR NOT NULL,
    cal_year          INTEGER NOT NULL,
    source_filing_id  VARCHAR NOT NULL REFERENCES filings(filing_id),
    PRIMARY KEY (exchange, cal_year)
);

CREATE TABLE IF NOT EXISTS raw_index_snapshot (
    filing_id      VARCHAR NOT NULL REFERENCES filings(filing_id),
    index_name     VARCHAR NOT NULL,
    snapshot_date  DATE    NOT NULL,
    symbol         VARCHAR NOT NULL,
    series         VARCHAR NOT NULL,
    isin           VARCHAR NOT NULL,
    company_name   VARCHAR,
    industry       VARCHAR,
    PRIMARY KEY (index_name, snapshot_date, isin, filing_id)
);

CREATE TABLE IF NOT EXISTS index_constituents_history (
    index_name   VARCHAR NOT NULL,
    security_id  VARCHAR NOT NULL REFERENCES securities(security_id),
    valid_from   DATE NOT NULL,                  -- first snapshot seen in (true inclusion may be earlier) [L1]
    valid_to     DATE,                           -- exclusive; snapshot date it was first missing
    source       VARCHAR NOT NULL,               -- SNAPSHOT | MANUAL_BACKFILL
    PRIMARY KEY (index_name, security_id, valid_from)
);

-- ── L2 Market ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ohlcv (
    security_id        VARCHAR NOT NULL REFERENCES securities(security_id),
    exchange           VARCHAR NOT NULL,
    series             VARCHAR NOT NULL,
    trade_date         DATE    NOT NULL,
    open               DECIMAL(18,4),
    high               DECIMAL(18,4),
    low                DECIMAL(18,4),
    close              DECIMAL(18,4) NOT NULL,
    volume             BIGINT,
    turnover_inr       DECIMAL(20,2),
    deliv_qty          BIGINT,
    price_filing_id    VARCHAR NOT NULL REFERENCES filings(filing_id),
    delivery_filing_id VARCHAR REFERENCES filings(filing_id),
    PRIMARY KEY (security_id, exchange, series, trade_date)
);

-- ── L2 Fundamentals ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS filing_meta (
    filing_id               VARCHAR NOT NULL REFERENCES filings(filing_id),
    parser_version          VARCHAR NOT NULL,
    entity_id               VARCHAR NOT NULL REFERENCES entity_master(entity_id),
    accounting_profile      VARCHAR NOT NULL,
    taxonomy_ns             VARCHAR NOT NULL,
    scope                   VARCHAR NOT NULL,
    level_of_rounding       VARCHAR NOT NULL,
    fy_start                DATE NOT NULL,
    fy_end                  DATE NOT NULL,
    period_end              DATE NOT NULL,
    reporting_quarter       VARCHAR,
    audited                 BOOLEAN,
    board_meeting_end_ts    TIMESTAMP,
    visible_from_ts         TIMESTAMP NOT NULL,
    visible_from_source     VARCHAR NOT NULL,   -- BROADCAST | BOARD_MEETING_RULE
    interest_paid_cfo_class VARCHAR,
    interest_recd_cfo_class VARCHAR,
    auditor_qualified       BOOLEAN,            -- Reg. 34: WhetherAuditorsReportHasBeenQualified... [X76]
    audit_opinion           VARCHAR,            -- Integrated Filing declaration: UNMODIFIED | NOT_APPLICABLE | raw text [E8]
    PRIMARY KEY (filing_id, parser_version)
);

-- Revision chains (append-only link table; filings rows are never updated) [E9]. A later filing of the same
-- entity, profile, scope and period end supersedes the earlier one: REVISION when the bytes differ, RESEND when
-- the blob is byte-identical.
CREATE TABLE IF NOT EXISTS filing_revisions (
    filing_id             VARCHAR NOT NULL REFERENCES filings(filing_id),
    supersedes_filing_id  VARCHAR NOT NULL REFERENCES filings(filing_id),
    entity_id             VARCHAR NOT NULL REFERENCES entity_master(entity_id),
    period_end            DATE NOT NULL,
    scope                 VARCHAR NOT NULL,
    relation              VARCHAR NOT NULL,     -- REVISION | RESEND
    PRIMARY KEY (filing_id, supersedes_filing_id)
);

-- Reg. 30 structured events [E1-E7]. One row per record (an order, a person, an allotment). event_id derives from
-- the blob sha256 + record, so byte-identical re-sends are one event.
CREATE TABLE IF NOT EXISTS corporate_events (
    event_id           VARCHAR PRIMARY KEY,
    filing_id          VARCHAR NOT NULL REFERENCES filings(filing_id),
    parser_version     VARCHAR NOT NULL,
    entity_id          VARCHAR NOT NULL REFERENCES entity_master(entity_id),
    family             VARCHAR NOT NULL,        -- PARA_B | CHANGE_IN_MANAGEMENT | FUND_RAISING | FRAUD_OR_DEFAULT
    event_type         VARCHAR NOT NULL,        -- ORDER_WIN | LITIGATION | MANAGEMENT_CHANGE | AUDITOR_CHANGE | ...
    event_subtype      VARCHAR,                 -- as filed
    occurred_on        DATE,
    report_date        DATE NOT NULL,
    counterparty       VARCHAR,
    amount_inr         DECIMAL(20,2),           -- absolute rupees as filed; NULL when not a number
    person_name        VARCHAR,
    person_category    VARCHAR,                 -- as filed (Key Managerial Personnel, Auditors, ...)
    change_type        VARCHAR,                 -- Appointment | Cessation
    cessation_category VARCHAR,                 -- Resignation | Superannuation or retirement | Cessation | ...
    details            JSON,
    visible_from_ts    TIMESTAMP NOT NULL       -- broadcast (RSS pubDate, IST -> UTC)
);

CREATE TABLE IF NOT EXISTS fact_observations (
    filing_id       VARCHAR NOT NULL REFERENCES filings(filing_id),
    parser_version  VARCHAR NOT NULL,
    entity_id       VARCHAR NOT NULL REFERENCES entity_master(entity_id),
    scope           VARCHAR NOT NULL,
    canonical_tag   VARCHAR NOT NULL,
    period_type     VARCHAR NOT NULL,           -- DURATION | INSTANT
    period_start    DATE NOT NULL,              -- = period_end for INSTANT
    period_end      DATE NOT NULL,
    period_months   INTEGER,                    -- NULL for INSTANT; 1..18
    unit            VARCHAR NOT NULL,           -- INR | INR_PER_SHARE | PURE | SHARES
    value_inr       DECIMAL(20,2),
    value_other     DECIMAL(28,8),
    source_element  VARCHAR NOT NULL,
    visible_from_ts TIMESTAMP NOT NULL,
    PRIMARY KEY (filing_id, parser_version, canonical_tag, period_start, period_end),
    CHECK ((unit = 'INR') = (value_inr IS NOT NULL)),
    CHECK ((unit = 'INR') = (value_other IS NULL)),
    CHECK (period_type IN ('DURATION', 'INSTANT')),
    CHECK ((period_type = 'INSTANT') = (period_months IS NULL)),
    CHECK (period_months IS NULL OR period_months BETWEEN 1 AND 18)
);

CREATE TABLE IF NOT EXISTS shareholding_meta (
    filing_id               VARCHAR NOT NULL REFERENCES filings(filing_id),
    parser_version          VARCHAR NOT NULL,
    entity_id               VARCHAR NOT NULL REFERENCES entity_master(entity_id),
    as_of_date              DATE NOT NULL,
    has_partly_paid         BOOLEAN,
    promoter_pledge_flag    BOOLEAN,
    promoter_pledged_shares BIGINT,              -- NULL when a pledge is declared but no quantity is filed
    visible_from_ts         TIMESTAMP NOT NULL,
    promoter_encumbered_shares BIGINT,           -- pledge + NDU + other encumbrances [SHP10]
    rules_applied           VARCHAR,             -- comma-separated named rules (e.g. NO_PROMOTER_CATEGORY)
    PRIMARY KEY (filing_id, parser_version)
);

-- Named public holders above 1% (Reg. 31 detail tables) [SHP12].
CREATE TABLE IF NOT EXISTS shareholding_major_holders (
    filing_id       VARCHAR NOT NULL REFERENCES filings(filing_id),
    parser_version  VARCHAR NOT NULL,
    entity_id       VARCHAR NOT NULL REFERENCES entity_master(entity_id),
    as_of_date      DATE NOT NULL,
    holder_category VARCHAR NOT NULL,           -- MUTUAL_FUNDS | INSURANCE | FPI_CAT1 | FDI | BODIES_CORPORATE | ...
    row_member      VARCHAR NOT NULL,           -- the filing's own typed-member id for the row
    holder_name     VARCHAR NOT NULL,
    shares          BIGINT NOT NULL,
    pct             DOUBLE,                     -- fraction, as filed
    visible_from_ts TIMESTAMP NOT NULL,
    PRIMARY KEY (filing_id, parser_version, holder_category, row_member)
);

CREATE TABLE IF NOT EXISTS shareholding_observations (
    filing_id       VARCHAR NOT NULL REFERENCES filings(filing_id),
    parser_version  VARCHAR NOT NULL,
    entity_id       VARCHAR NOT NULL REFERENCES entity_master(entity_id),
    as_of_date      DATE NOT NULL,
    category        VARCHAR NOT NULL,           -- parsers/shareholding.py CATEGORIES (TOTAL, PROMOTER, PUBLIC, FII, ...)
    shares          BIGINT,
    holders         BIGINT,
    pct             DOUBLE,                     -- fraction, as filed (denominator excludes DR shares [SHP9])
    demat_shares    BIGINT,
    voting_rights   BIGINT,
    visible_from_ts TIMESTAMP NOT NULL,
    PRIMARY KEY (filing_id, parser_version, category)
);

-- ── Corporate actions & control ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS corp_actions (
    action_id         VARCHAR PRIMARY KEY,
    entity_id         VARCHAR REFERENCES entity_master(entity_id),
    security_id       VARCHAR NOT NULL REFERENCES securities(security_id),
    action_type       VARCHAR NOT NULL,
    ex_date           DATE NOT NULL,
    record_date       DATE,
    ratio_num         DECIMAL(18,6),
    ratio_den         DECIMAL(18,6),
    issue_price       DECIMAL(18,4),
    cash_per_share    DECIMAL(18,4),
    price_factor      DOUBLE,
    eps_factor        DOUBLE,
    observed_gap      DOUBLE,
    status            VARCHAR NOT NULL DEFAULT 'PENDING',
    related_entity_id VARCHAR REFERENCES entity_master(entity_id),
    coa_pct           DOUBLE,
    source_filing_id  VARCHAR NOT NULL REFERENCES filings(filing_id)
);

CREATE TABLE IF NOT EXISTS quarantine_queue (
    quarantine_id   VARCHAR PRIMARY KEY,
    stage           VARCHAR NOT NULL,
    reason_code     VARCHAR NOT NULL,
    entity_id       VARCHAR,
    security_id     VARCHAR,
    filing_id       VARCHAR,
    details         JSON NOT NULL,
    created_at      TIMESTAMP NOT NULL,
    resolved_at     TIMESTAMP,
    resolution      VARCHAR,
    resolution_note VARCHAR
);

CREATE TABLE IF NOT EXISTS company_overrides (
    override_id  VARCHAR PRIMARY KEY,
    entity_id    VARCHAR NOT NULL REFERENCES entity_master(entity_id),
    field        VARCHAR NOT NULL,
    value        VARCHAR NOT NULL,
    valid_from   DATE NOT NULL,
    valid_to     DATE,
    reason       VARCHAR NOT NULL,
    created_at   TIMESTAMP NOT NULL
);

-- ── L3 Features (rebuilt by the promoter process; G4/G5 in financials.features) ──
CREATE TABLE IF NOT EXISTS screener_features_history (
    as_of_date          DATE    NOT NULL,
    security_id         VARCHAR NOT NULL,
    entity_id           VARCHAR NOT NULL,
    symbol              VARCHAR NOT NULL,
    series              VARCHAR NOT NULL,
    price_date          DATE,                -- last bar on/before as_of_date
    close               DECIMAL(18,4),
    shares              BIGINT,
    shares_source       VARCHAR,             -- REG31 | PAID_UP
    market_cap          DECIMAL(24,2),
    enterprise_value    DECIMAL(24,2),
    sales_ttm           DECIMAL(24,2),
    ebitda_ttm          DECIMAL(24,2),
    pat_ttm             DECIMAL(24,2),
    fcf_ttm             DECIMAL(24,2),
    net_debt            DECIMAL(24,2),
    total_equity        DECIMAL(24,2),
    pe                  DOUBLE,
    pb                  DOUBLE,
    ev_ebitda           DOUBLE,
    opm                 DOUBLE,
    sales_growth_yoy    DOUBLE,
    profit_growth_yoy   DOUBLE,
    roe                 DOUBLE,
    roce                DOUBLE,
    roic                DOUBLE,
    croic               DOUBLE,
    debt_to_equity      DOUBLE,
    fcff_yield          DOUBLE,
    other_income_to_pbt DOUBLE,
    altman_z_dd         DOUBLE,              -- X2 uses OtherEquity as retained-earnings proxy
    piotroski_f         INTEGER,             -- 0..9, year-end-assets variant; NULL without two FYs [C23]
    beneish_m           DOUBLE,              -- 8-variable M-score; NULL without two FYs [C23]
    return_1m           DOUBLE,
    return_3m           DOUBLE,
    return_6m           DOUBLE,
    return_12m          DOUBLE,
    price_to_dma50      DOUBLE,
    price_to_dma200     DOUBLE,
    dist_52w_high       DOUBLE,
    deliv_avg_5d        DOUBLE,
    deliv_avg_20d       DOUBLE,
    delivery_velocity   DOUBLE,
    float_turnover_pct  DOUBLE,
    promoter_pct        DOUBLE,
    fii_pct             DOUBLE,
    dii_pct             DOUBLE,
    scope_used          VARCHAR,
    fundamentals_end    DATE,                -- quarter end of the TTM window
    bs_as_of            DATE,
    cf_as_of            DATE,
    shp_as_of           DATE,
    in_nifty500         BOOLEAN,
    eps_ttm             DECIMAL(18,4),       -- TTM owners' profit / current shares [X53]
    eps_continuing_ttm  DECIMAL(18,4),       -- TTM continuing owners' profit / current shares [C10]
    roe_continuing      DOUBLE,              -- same denominator as roe [C14]
    core_profit_ttm     DECIMAL(24,2),       -- continuing owners' profit less exceptional items net of tax [C14]
    is_lending_nbfc     BOOLEAN,             -- INDAS_NBFC only [C13]; NULL for other profiles
    nii_ttm             DECIMAL(24,2),       -- lenders: interest earned - finance costs
    ppop_ttm            DECIMAL(24,2),       -- lenders: pre-provision operating profit
    cost_to_income      DOUBLE,
    credit_cost         DOUBLE,              -- TTM impairment / avg loans (opening + closing)
    nim_asset_proxy     DOUBLE,              -- TTM NII / avg total assets
    roa                 DOUBLE,              -- TTM owners' profit / avg total assets (lenders)
    loans               DECIMAL(24,2),
    loans_as_of         DATE,
    loans_avg_from      DATE,                -- opening balance-sheet date of the average
    gnpa_pct            DOUBLE,              -- NULL for NBFCs: no taxonomy element [X54]
    nnpa_pct            DOUBLE,
    pcr                 DOUBLE,
    credit_to_deposit   DOUBLE,              -- banks: advances / deposits (latest balance sheet)
    cet1_pct            DOUBLE,              -- banks: filed CET1 ratio (standalone)
    at1_pct             DOUBLE,              -- banks: filed AT1 ratio (standalone)
    roa_filed           DOUBLE,              -- banks: filed ReturnOnAssets, annualisation varies by bank [X59]
    govt_holding_pct    DOUBLE,              -- banks: PercentageOfShareHeldByGovernmentOfIndia (PSU marker)
    insurer_basis       VARCHAR,             -- IRDAI_LIFE | IRDAI_GENERAL | INDAS117 (ratios not comparable across) [X64]
    net_premium_earned_ttm DECIMAL(24,2),    -- IRDAI general: PremiumEarned; life: NetPremiumIncome
    insurance_revenue_ttm  DECIMAL(24,2),    -- Ind AS 117 insurers only
    claims_ratio        DOUBLE,              -- general / Ind AS 117 insurers (definitions in §10.6)
    expense_ratio       DOUBLE,
    combined_ratio      DOUBLE,
    solvency_ratio      DOUBLE,              -- times, after SOLVENCY_PERCENT_SCALING [X65]; NULL for Ind AS 117 filers
    investment_income_ttm DECIMAL(24,2),
    persistency_13m     DOUBLE,              -- life insurers, filed in XBRL [X62]
    persistency_61m     DOUBLE,
    scope_reason        VARCHAR,             -- DEFAULT | FALLBACK_DEFAULT_INCOMPLETE | OVERRIDE | YTD_BRIDGE | BALANCE_SHEET_ONLY
    default_quarterly_scope VARCHAR,         -- company default for quarterly / TTM figures [C18]
    default_annual_scope    VARCHAR,         -- company default for annual statements [C18]
    sloan_accrual       DOUBLE,              -- (TTM PAT - CFO - CFI) / avg total assets [C19]
    cfo_to_ebitda       DOUBLE,
    fcf_to_pat          DOUBLE,
    working_capital_intensity DOUBLE,        -- (receivables + inventory - payables) / TTM revenue
    receivables_sales_divergence DOUBLE,     -- receivables YoY - revenue YoY (needs 8 quarters)
    net_debt_to_fcf     DOUBLE,
    cost_of_debt        DOUBLE,              -- TTM finance costs / avg (borrowings + leases)
    dol                 DOUBLE,              -- EBIT YoY / revenue YoY, only if |revenue YoY| >= 5% (needs 8 quarters)
    gross_ebitda_spread DOUBLE,              -- (gross profit - EBITDA) / revenue; COGS >= 10% guard (C6)
    reverse_dcf_implied_g  DOUBLE,           -- 5Y FCFF growth implied by EV [C20]
    reverse_dcf_wacc_used  DOUBLE,           -- assumption stored with the result (0.12)
    reverse_dcf_terminal_g DOUBLE,           -- assumption stored with the result (0.04)
    pe_percentile       DOUBLE,              -- rank vs own prior quarter-end values, >= 4 quarters [C20]
    ev_ebitda_percentile DOUBLE,
    valuation_archetype VARCHAR,             -- INDUSTRIAL_SERVICES | FINANCIAL_LENDING | INSURANCE | NEW_GEN_TECH [C21]
    ev_to_gross_profit  DOUBLE,
    ex_cash_pe          DOUBLE,              -- (mcap - liquid cash) / (continuing owners' PAT - OI x (1 - ETR))
    ev_to_billings      DOUBLE,              -- EV / (TTM revenue + YoY change in contract liabilities)
    ev_to_esop_adj_ebitda DOUBLE,            -- EV / (EBITDA + ESOP cost), cash-flow window
    price_to_cfo        DOUBLE,
    rule_of_40          DOUBLE,              -- revenue YoY + EBITDA margin (needs 8 quarters)
    billings_growth_pct DOUBLE,              -- billings YoY (needs 8 quarters and labelled contract liabilities)
    neg_working_capital_float_pct DOUBLE,    -- ((payables + contract liabilities) - (receivables + inventory)) / revenue
    net_burn_multiple   DOUBLE,              -- cash burn / incremental revenue, only when FCF < 0 (needs 8 quarters)
    cash_runway_months  DOUBLE,              -- liquid cash / monthly burn, only when FCF < 0
    esop_adj_fcf        DECIMAL(24,2),       -- FCF - ESOP cost
    liquid_cash         DECIMAL(24,2),       -- cash + other bank balances + current investments
    promoter_holding_pct DOUBLE,             -- Reg. 31 fractions as filed; denominator excludes DR shares [SHP9]
    promoter_pledge_pct DOUBLE,              -- pledged / promoter shares [SHP10]
    promoter_encumbered_pct DOUBLE,          -- (pledge + NDU + other encumbrance) / promoter shares [SHP10]
    fii_holding_pct     DOUBLE,              -- SEBI "Institutions (Foreign)": includes FDI and overseas depositories
    fpi_holding_pct     DOUBLE,              -- FPI Category I + II only [SHP13]
    dii_holding_pct     DOUBLE,              -- SEBI "Institutions (Domestic)"
    public_holding_pct  DOUBLE,
    non_promoter_non_public_pct DOUBLE,      -- DR custodian + employee trusts, of total issued shares
    fii_dii_qoq_change_pct DOUBLE,           -- (FII + DII) now minus previous quarter end; fraction points
    capex_to_depreciation DOUBLE,            -- FY (PPE + intangibles capex) / D&A [C23]
    cwip_to_gross_block DOUBLE,              -- CWIP / gross block (Reg. 34 PPE schedule) [X71]
    rote                DOUBLE,              -- FY owners' PAT / (owners' equity - goodwill - other intangibles)
    rnd_and_royalty_intensity DOUBLE,        -- (R&D + royalty) / revenue; NULL when neither is disclosed [X73]
    contingent_liabilities_to_net_worth DOUBLE, -- contingent liabilities / owners' equity [X73]
    annual_fy_end       DATE,                -- fiscal year the annual ratios (incl. Piotroski/Beneish) use
    order_wins_90d      INTEGER,             -- Reg. 30 order wins visible, occurred in the 90 days to as-of [E3]
    order_value_90d     DECIMAL(24,2),       -- sum of their filed amounts (rupees)
    kmp_resignations_90d INTEGER,            -- KMP / director cessations by resignation [E5]
    auditor_resignations_90d INTEGER,        -- auditor cessations by resignation [E5]
    fraud_or_default_90d INTEGER,            -- fraud / default disclosures [E7]
    penalties_90d       INTEGER,             -- NULL: no penalty / regulatory-action event observed (UNVERIFIED) [E7]
    PRIMARY KEY (as_of_date, security_id)
);

CREATE TABLE IF NOT EXISTS screener_features (
    as_of_date          DATE    NOT NULL,
    security_id         VARCHAR NOT NULL,
    entity_id           VARCHAR NOT NULL,
    symbol              VARCHAR NOT NULL,
    series              VARCHAR NOT NULL,
    price_date          DATE,                -- last bar on/before as_of_date
    close               DECIMAL(18,4),
    shares              BIGINT,
    shares_source       VARCHAR,             -- REG31 | PAID_UP
    market_cap          DECIMAL(24,2),
    enterprise_value    DECIMAL(24,2),
    sales_ttm           DECIMAL(24,2),
    ebitda_ttm          DECIMAL(24,2),
    pat_ttm             DECIMAL(24,2),
    fcf_ttm             DECIMAL(24,2),
    net_debt            DECIMAL(24,2),
    total_equity        DECIMAL(24,2),
    pe                  DOUBLE,
    pb                  DOUBLE,
    ev_ebitda           DOUBLE,
    opm                 DOUBLE,
    sales_growth_yoy    DOUBLE,
    profit_growth_yoy   DOUBLE,
    roe                 DOUBLE,
    roce                DOUBLE,
    roic                DOUBLE,
    croic               DOUBLE,
    debt_to_equity      DOUBLE,
    fcff_yield          DOUBLE,
    other_income_to_pbt DOUBLE,
    altman_z_dd         DOUBLE,              -- X2 uses OtherEquity as retained-earnings proxy
    piotroski_f         INTEGER,             -- 0..9, year-end-assets variant; NULL without two FYs [C23]
    beneish_m           DOUBLE,              -- 8-variable M-score; NULL without two FYs [C23]
    return_1m           DOUBLE,
    return_3m           DOUBLE,
    return_6m           DOUBLE,
    return_12m          DOUBLE,
    price_to_dma50      DOUBLE,
    price_to_dma200     DOUBLE,
    dist_52w_high       DOUBLE,
    deliv_avg_5d        DOUBLE,
    deliv_avg_20d       DOUBLE,
    delivery_velocity   DOUBLE,
    float_turnover_pct  DOUBLE,
    promoter_pct        DOUBLE,
    fii_pct             DOUBLE,
    dii_pct             DOUBLE,
    scope_used          VARCHAR,
    fundamentals_end    DATE,                -- quarter end of the TTM window
    bs_as_of            DATE,
    cf_as_of            DATE,
    shp_as_of           DATE,
    in_nifty500         BOOLEAN,
    eps_ttm             DECIMAL(18,4),       -- TTM owners' profit / current shares [X53]
    eps_continuing_ttm  DECIMAL(18,4),       -- TTM continuing owners' profit / current shares [C10]
    roe_continuing      DOUBLE,              -- same denominator as roe [C14]
    core_profit_ttm     DECIMAL(24,2),       -- continuing owners' profit less exceptional items net of tax [C14]
    is_lending_nbfc     BOOLEAN,             -- INDAS_NBFC only [C13]; NULL for other profiles
    nii_ttm             DECIMAL(24,2),       -- lenders: interest earned - finance costs
    ppop_ttm            DECIMAL(24,2),       -- lenders: pre-provision operating profit
    cost_to_income      DOUBLE,
    credit_cost         DOUBLE,              -- TTM impairment / avg loans (opening + closing)
    nim_asset_proxy     DOUBLE,              -- TTM NII / avg total assets
    roa                 DOUBLE,              -- TTM owners' profit / avg total assets (lenders)
    loans               DECIMAL(24,2),
    loans_as_of         DATE,
    loans_avg_from      DATE,                -- opening balance-sheet date of the average
    gnpa_pct            DOUBLE,              -- NULL for NBFCs: no taxonomy element [X54]
    nnpa_pct            DOUBLE,
    pcr                 DOUBLE,
    credit_to_deposit   DOUBLE,              -- banks: advances / deposits (latest balance sheet)
    cet1_pct            DOUBLE,              -- banks: filed CET1 ratio (standalone)
    at1_pct             DOUBLE,              -- banks: filed AT1 ratio (standalone)
    roa_filed           DOUBLE,              -- banks: filed ReturnOnAssets, annualisation varies by bank [X59]
    govt_holding_pct    DOUBLE,              -- banks: PercentageOfShareHeldByGovernmentOfIndia (PSU marker)
    insurer_basis       VARCHAR,             -- IRDAI_LIFE | IRDAI_GENERAL | INDAS117 (ratios not comparable across) [X64]
    net_premium_earned_ttm DECIMAL(24,2),    -- IRDAI general: PremiumEarned; life: NetPremiumIncome
    insurance_revenue_ttm  DECIMAL(24,2),    -- Ind AS 117 insurers only
    claims_ratio        DOUBLE,              -- general / Ind AS 117 insurers (definitions in §10.6)
    expense_ratio       DOUBLE,
    combined_ratio      DOUBLE,
    solvency_ratio      DOUBLE,              -- times, after SOLVENCY_PERCENT_SCALING [X65]; NULL for Ind AS 117 filers
    investment_income_ttm DECIMAL(24,2),
    persistency_13m     DOUBLE,              -- life insurers, filed in XBRL [X62]
    persistency_61m     DOUBLE,
    scope_reason        VARCHAR,             -- DEFAULT | FALLBACK_DEFAULT_INCOMPLETE | OVERRIDE | YTD_BRIDGE | BALANCE_SHEET_ONLY
    default_quarterly_scope VARCHAR,         -- company default for quarterly / TTM figures [C18]
    default_annual_scope    VARCHAR,         -- company default for annual statements [C18]
    sloan_accrual       DOUBLE,              -- (TTM PAT - CFO - CFI) / avg total assets [C19]
    cfo_to_ebitda       DOUBLE,
    fcf_to_pat          DOUBLE,
    working_capital_intensity DOUBLE,        -- (receivables + inventory - payables) / TTM revenue
    receivables_sales_divergence DOUBLE,     -- receivables YoY - revenue YoY (needs 8 quarters)
    net_debt_to_fcf     DOUBLE,
    cost_of_debt        DOUBLE,              -- TTM finance costs / avg (borrowings + leases)
    dol                 DOUBLE,              -- EBIT YoY / revenue YoY, only if |revenue YoY| >= 5% (needs 8 quarters)
    gross_ebitda_spread DOUBLE,              -- (gross profit - EBITDA) / revenue; COGS >= 10% guard (C6)
    reverse_dcf_implied_g  DOUBLE,           -- 5Y FCFF growth implied by EV [C20]
    reverse_dcf_wacc_used  DOUBLE,           -- assumption stored with the result (0.12)
    reverse_dcf_terminal_g DOUBLE,           -- assumption stored with the result (0.04)
    pe_percentile       DOUBLE,              -- rank vs own prior quarter-end values, >= 4 quarters [C20]
    ev_ebitda_percentile DOUBLE,
    valuation_archetype VARCHAR,             -- INDUSTRIAL_SERVICES | FINANCIAL_LENDING | INSURANCE | NEW_GEN_TECH [C21]
    ev_to_gross_profit  DOUBLE,
    ex_cash_pe          DOUBLE,              -- (mcap - liquid cash) / (continuing owners' PAT - OI x (1 - ETR))
    ev_to_billings      DOUBLE,              -- EV / (TTM revenue + YoY change in contract liabilities)
    ev_to_esop_adj_ebitda DOUBLE,            -- EV / (EBITDA + ESOP cost), cash-flow window
    price_to_cfo        DOUBLE,
    rule_of_40          DOUBLE,              -- revenue YoY + EBITDA margin (needs 8 quarters)
    billings_growth_pct DOUBLE,              -- billings YoY (needs 8 quarters and labelled contract liabilities)
    neg_working_capital_float_pct DOUBLE,    -- ((payables + contract liabilities) - (receivables + inventory)) / revenue
    net_burn_multiple   DOUBLE,              -- cash burn / incremental revenue, only when FCF < 0 (needs 8 quarters)
    cash_runway_months  DOUBLE,              -- liquid cash / monthly burn, only when FCF < 0
    esop_adj_fcf        DECIMAL(24,2),       -- FCF - ESOP cost
    liquid_cash         DECIMAL(24,2),       -- cash + other bank balances + current investments
    promoter_holding_pct DOUBLE,             -- Reg. 31 fractions as filed; denominator excludes DR shares [SHP9]
    promoter_pledge_pct DOUBLE,              -- pledged / promoter shares [SHP10]
    promoter_encumbered_pct DOUBLE,          -- (pledge + NDU + other encumbrance) / promoter shares [SHP10]
    fii_holding_pct     DOUBLE,              -- SEBI "Institutions (Foreign)": includes FDI and overseas depositories
    fpi_holding_pct     DOUBLE,              -- FPI Category I + II only [SHP13]
    dii_holding_pct     DOUBLE,              -- SEBI "Institutions (Domestic)"
    public_holding_pct  DOUBLE,
    non_promoter_non_public_pct DOUBLE,      -- DR custodian + employee trusts, of total issued shares
    fii_dii_qoq_change_pct DOUBLE,           -- (FII + DII) now minus previous quarter end; fraction points
    capex_to_depreciation DOUBLE,            -- FY (PPE + intangibles capex) / D&A [C23]
    cwip_to_gross_block DOUBLE,              -- CWIP / gross block (Reg. 34 PPE schedule) [X71]
    rote                DOUBLE,              -- FY owners' PAT / (owners' equity - goodwill - other intangibles)
    rnd_and_royalty_intensity DOUBLE,        -- (R&D + royalty) / revenue; NULL when neither is disclosed [X73]
    contingent_liabilities_to_net_worth DOUBLE, -- contingent liabilities / owners' equity [X73]
    annual_fy_end       DATE,                -- fiscal year the annual ratios (incl. Piotroski/Beneish) use
    order_wins_90d      INTEGER,             -- Reg. 30 order wins visible, occurred in the 90 days to as-of [E3]
    order_value_90d     DECIMAL(24,2),       -- sum of their filed amounts (rupees)
    kmp_resignations_90d INTEGER,            -- KMP / director cessations by resignation [E5]
    auditor_resignations_90d INTEGER,        -- auditor cessations by resignation [E5]
    fraud_or_default_90d INTEGER,            -- fraud / default disclosures [E7]
    penalties_90d       INTEGER,             -- NULL: no penalty / regulatory-action event observed (UNVERIFIED) [E7]
    PRIMARY KEY (as_of_date, security_id)
);

CREATE TABLE IF NOT EXISTS user_custom_ratios (
    name        VARCHAR PRIMARY KEY,            -- alias usable in screens
    expression  VARCHAR NOT NULL,               -- DSL arithmetic over aliases / other custom ratios
    created_at  TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS promotion_log (
    stage_path   VARCHAR PRIMARY KEY,          -- relative to the staging root
    job          VARCHAR NOT NULL,
    status       VARCHAR NOT NULL,             -- PROMOTED | ALREADY_PROMOTED | QUARANTINED
    message      VARCHAR,
    promoted_at  TIMESTAMP NOT NULL
);

-- Presentation / IRDAI public-disclosure KPIs that are not in exchange XBRL (VNB margin, embedded value, APE growth for
-- life insurers; GOV, take rate, contribution margin, NRR, CAC payback for new-gen tech). Point-in-time like every
-- fundamental: visible_from_ts is when the source document became public. Phase 3 fills it; no fetcher yet.
CREATE TABLE IF NOT EXISTS supplemental_kpis (
    entity_id       VARCHAR NOT NULL REFERENCES entity_master(entity_id),
    kpi             VARCHAR NOT NULL,        -- vnb_margin | embedded_value | ape_growth | persistency_13m | persistency_61m
                                             -- | gov | take_rate | contribution_margin | nrr | cac_payback
    period_start    DATE    NOT NULL,
    period_end      DATE    NOT NULL,
    value           DECIMAL(24,6) NOT NULL,
    unit            VARCHAR NOT NULL,        -- INR | RATIO | MONTHS | COUNT
    source_kind     VARCHAR NOT NULL,        -- INVESTOR_PRESENTATION | IRDAI_PUBLIC_DISCLOSURE | ANNUAL_REPORT | MANUAL
    source_url      VARCHAR NOT NULL,
    source_sha256   VARCHAR NOT NULL,        -- vaulted document
    visible_from_ts TIMESTAMP NOT NULL,      -- UTC
    recorded_at     TIMESTAMP NOT NULL,
    notes           VARCHAR,
    PRIMARY KEY (entity_id, kpi, period_start, period_end, visible_from_ts)
);

-- Manual per-company scope override (Mandate 3, C18). Written only through admin.set_scope_override, which also
-- appends an audit row to company_overrides; a user preference, not data, so it applies at every as-of date.
CREATE TABLE IF NOT EXISTS entity_scope_override (
    entity_id       VARCHAR PRIMARY KEY REFERENCES entity_master(entity_id),
    quarterly_scope VARCHAR NOT NULL,        -- CONSOLIDATED | STANDALONE
    annual_scope    VARCHAR NOT NULL,
    reason          VARCHAR NOT NULL,
    recorded_at     TIMESTAMP NOT NULL
);

-- Manual valuation-archetype override (C21): written only by admin.set_archetype_override, audited in company_overrides.
CREATE TABLE IF NOT EXISTS entity_archetype_override (
    entity_id           VARCHAR PRIMARY KEY REFERENCES entity_master(entity_id),
    valuation_archetype VARCHAR NOT NULL,
    reason              VARCHAR NOT NULL,
    recorded_at         TIMESTAMP NOT NULL
);
