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
