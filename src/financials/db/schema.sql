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
    PRIMARY KEY (filing_id, parser_version)
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
    promoter_pledged_shares BIGINT,              -- NULL when pledged but quantity tag unverified
    visible_from_ts         TIMESTAMP NOT NULL,
    PRIMARY KEY (filing_id, parser_version)
);

CREATE TABLE IF NOT EXISTS shareholding_observations (
    filing_id       VARCHAR NOT NULL REFERENCES filings(filing_id),
    parser_version  VARCHAR NOT NULL,
    entity_id       VARCHAR NOT NULL REFERENCES entity_master(entity_id),
    as_of_date      DATE NOT NULL,
    category        VARCHAR NOT NULL,           -- TOTAL | PROMOTER | PUBLIC | FII | DII | MUTUAL_FUNDS | NON_INSTITUTIONS
    shares          BIGINT,
    holders         BIGINT,
    pct             DOUBLE,                     -- fraction of total shares
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
    piotroski_f         INTEGER,             -- NULL until annual (Reg. 34) data exists
    beneish_m           DOUBLE,              -- NULL until annual (Reg. 34) data exists
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
    piotroski_f         INTEGER,             -- NULL until annual (Reg. 34) data exists
    beneish_m           DOUBLE,              -- NULL until annual (Reg. 34) data exists
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
