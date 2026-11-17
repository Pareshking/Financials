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

-- raw_xbrl_facts (every XBRL fact verbatim) was removed by owner decision J (2026-11-16, `drop-raw-xbrl`): every
-- element of every parsed filing reaches a clean table (disclosure_facts for whatever no other table holds) and the
-- vault blob stays the source of truth; anything that needs the raw facts parses the blob (parsers.xbrl).

-- ── L2 Identity ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS entity_master (
    entity_id      VARCHAR PRIMARY KEY,
    legal_name     VARCHAR NOT NULL,
    cin            VARCHAR,                 -- no UNIQUE: DuckDB INSERT OR IGNORE treats NULLs as conflicts
    status         VARCHAR NOT NULL DEFAULT 'ACTIVE',
    inactive_date  DATE,
    exit_reason    VARCHAR,
    merged_into    VARCHAR                  -- acquirer entity_id when status = MERGED by an entity_lineage merger (G56)
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
    source      VARCHAR,                         -- BHAVCOPY | HOLIDAY_MASTER | INFERRED_PREV_CLOSE [CAL3]
    PRIMARY KEY (exchange, cal_date)
);

CREATE TABLE IF NOT EXISTS calendar_coverage (   -- years for which a holiday list was loaded
    exchange          VARCHAR NOT NULL,
    cal_year          INTEGER NOT NULL,
    source_filing_id  VARCHAR NOT NULL REFERENCES filings(filing_id),
    PRIMARY KEY (exchange, cal_year)
);

-- Daily index levels from content/indices/ind_close_all_DDMMYYYY.csv [IDX9] (price indices; no TRI rows). L1, append-only.
CREATE TABLE IF NOT EXISTS index_ohlcv (
    index_name    VARCHAR NOT NULL,
    trade_date    DATE    NOT NULL,
    open          DECIMAL(18,4),
    high          DECIMAL(18,4),
    low           DECIMAL(18,4),
    close         DECIMAL(18,4) NOT NULL,
    volume        BIGINT,
    turnover_inr  DECIMAL(24,2),                 -- filed in Rs crore
    pe            DOUBLE,
    pb            DOUBLE,
    div_yield     DOUBLE,
    filing_id     VARCHAR NOT NULL REFERENCES filings(filing_id),
    PRIMARY KEY (index_name, trade_date, filing_id)
);

-- NSE equity master content/equities/EQUITY_L.csv [IDX10]: listing date, face value, ISIN per symbol. L1, append-only.
CREATE TABLE IF NOT EXISTS raw_equity_master (
    filing_id      VARCHAR NOT NULL REFERENCES filings(filing_id),
    snapshot_date  DATE    NOT NULL,
    symbol         VARCHAR NOT NULL,
    name           VARCHAR NOT NULL,
    series         VARCHAR NOT NULL,
    listing_date   DATE,
    paid_up_value  DECIMAL(18,4),
    market_lot     INTEGER,
    isin           VARCHAR NOT NULL,
    face_value     DECIMAL(18,4),
    PRIMARY KEY (filing_id, symbol, series)
);

-- One row per Integrated Filing listing row (api/integrated-filing-results, vaulted as RESULTS_LISTING) [A7, X83].
-- `creation_Date` is on every row; `broadcast_Date` is null on revised rows. Times are UTC (listing is IST).
CREATE TABLE IF NOT EXISTS raw_results_listing (
    filing_id        VARCHAR NOT NULL REFERENCES filings(filing_id),   -- the vaulted listing JSON
    xbrl_url         VARCHAR NOT NULL,
    symbol           VARCHAR NOT NULL,
    period_end       DATE    NOT NULL,
    scope            VARCHAR,
    filing_type      VARCHAR NOT NULL,
    broadcast_ts     TIMESTAMP,
    creation_ts      TIMESTAMP,
    revised_ts       TIMESTAMP,
    revision_remark  VARCHAR,
    PRIMARY KEY (filing_id, xbrl_url)
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
    line_item_category VARCHAR,                 -- C24: PNL_EXPENSE | CASH_FLOW | BALANCE_SHEET | ... (line_items.py)
    parent_subtotal VARCHAR,                    -- canonical key of the subtotal this line sits under
    PRIMARY KEY (filing_id, parser_version, canonical_tag, period_start, period_end),
    CHECK ((unit = 'INR') = (value_inr IS NOT NULL)),
    CHECK ((unit = 'INR') = (value_other IS NULL)),
    CHECK (period_type IN ('DURATION', 'INSTANT')),
    CHECK ((period_type = 'INSTANT') = (period_months IS NULL)),
    CHECK (period_months IS NULL OR period_months BETWEEN 1 AND 18)
);

-- Ind AS 108 segment and geography disclosures (parsers/segments.py) [X49, X97-X99]: one row per member fact, axis,
-- member, label and element exactly as filed; no cross-company segment taxonomy. Promoted with its filing (same
-- entity, scope, visibility and parser version). Never feeds fact_observations, the factbook or any ratio (§14b-1).
CREATE TABLE IF NOT EXISTS segment_observations (
    filing_id        VARCHAR NOT NULL REFERENCES filings(filing_id),
    parser_version   VARCHAR NOT NULL,
    entity_id        VARCHAR NOT NULL REFERENCES entity_master(entity_id),
    scope            VARCHAR NOT NULL,
    axis_kind        VARCHAR NOT NULL,          -- BUSINESS | GEOGRAPHY
    axis             VARCHAR NOT NULL,          -- dimension QName as filed (in-capmkt:ReportableSegmentsAxis, ...)
    member           VARCHAR NOT NULL,          -- member QName as filed
    member_role      VARCHAR NOT NULL,          -- from the member name: SEGMENT | UNALLOCATED | ELIMINATION | RECONCILING | DOMICILE | FOREIGN_TOTAL | FOREIGN | AREA
    label            VARCHAR,                   -- DescriptionOfReportableSegment / NatureOfReportableSegment / country, as filed
    element          VARCHAR NOT NULL,          -- as filed
    canonical_metric VARCHAR NOT NULL,          -- segments.SEGMENT_METRICS: REVENUE | RESULT | ASSETS | ...
    period_type      VARCHAR NOT NULL,          -- DURATION | INSTANT
    period_start     DATE NOT NULL,             -- = period_end for INSTANT
    period_end       DATE NOT NULL,
    period_months    INTEGER,                   -- NULL for INSTANT; 1..18
    value_inr        DECIMAL(20,2) NOT NULL,
    visible_from_ts  TIMESTAMP NOT NULL,
    PRIMARY KEY (filing_id, parser_version, axis, member, element, period_start, period_end),
    CHECK (axis_kind IN ('BUSINESS', 'GEOGRAPHY')),
    CHECK (period_type IN ('DURATION', 'INSTANT')),
    CHECK ((period_type = 'INSTANT') = (period_months IS NULL)),
    CHECK ((period_type = 'INSTANT') = (period_start = period_end)),
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

-- Every numeric Reg. 31 fact per shareholder-category member (C24, zero drop).
CREATE TABLE IF NOT EXISTS shareholding_line_items (
    filing_id       VARCHAR NOT NULL REFERENCES filings(filing_id),
    parser_version  VARCHAR NOT NULL,
    entity_id       VARCHAR NOT NULL REFERENCES entity_master(entity_id),
    as_of_date      DATE NOT NULL,
    category_member VARCHAR NOT NULL,           -- CategoryOfShareholdersAxis member (ENTITY when non-dimensional)
    element         VARCHAR NOT NULL,
    value           DECIMAL(28,8) NOT NULL,
    unit            VARCHAR NOT NULL,           -- SHARES | PURE | INR
    visible_from_ts TIMESTAMP NOT NULL,
    PRIMARY KEY (filing_id, parser_version, category_member, element)
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
    related_entity_id VARCHAR REFERENCES entity_master(entity_id),  -- never written: lineage is entity_lineage
    coa_pct           DOUBLE,                                         -- never written: entity_lineage.coa_pct
    source_filing_id  VARCHAR NOT NULL REFERENCES filings(filing_id),
    recorded_at       TIMESTAMP,                 -- when the ledger first held the action (system time)
    decided_at        TIMESTAMP                  -- when status last changed (verification / manual resolution)
);

-- Directed corporate lineage (G37, architecture §11.7). Read as "child RELATION parent":
--   MERGED_INTO / AMALGAMATED: the child (target) ceased to exist; its holders received parent (acquirer) shares.
--   DEMERGED_FROM: the child (resulting company) was carved out of the parent; parent holders kept their shares and
--   received child shares.
-- Append-only: a correction or a retirement is a new row naming the row it replaces (supersedes_lineage_id); the
-- current edges are the ACTIVE rows no other row supersedes. Ids are deterministic over the content. Written only by
-- financials.admin (lineage add / amend / coa / retire / load), each audited in admin_log and company_overrides.
CREATE TABLE IF NOT EXISTS entity_lineage (
    lineage_id            VARCHAR PRIMARY KEY,
    parent_entity_id      VARCHAR NOT NULL REFERENCES entity_master(entity_id),
    child_entity_id       VARCHAR NOT NULL REFERENCES entity_master(entity_id),
    relation              VARCHAR NOT NULL,       -- MERGED_INTO | AMALGAMATED | DEMERGED_FROM
    effective_date        DATE NOT NULL,          -- first trading day the holders hold the new shares (the ex-date)
    swap_ratio_num        DECIMAL(18,6),          -- shares received (parent for a merger, child for a demerger) ...
    swap_ratio_den        DECIMAL(18,6),          -- ... per this many shares held (child / parent); NULL = not verified
    coa_pct               DECIMAL(9,4),           -- DEMERGED_FROM: % of the parent's pre-scheme cost given to the child
    parent_coa_pct        DECIMAL(9,4),           -- DEMERGED_FROM: % the parent keeps (parent + children = 100, G51)
    state                 VARCHAR NOT NULL,       -- ACTIVE | RETIRED
    supersedes_lineage_id VARCHAR,                -- the row this one corrects or retires (no UNIQUE: [I1])
    evidence_filing_id    VARCHAR REFERENCES filings(filing_id),
    evidence_url          VARCHAR,
    source                VARCHAR NOT NULL,       -- MANIFEST | ADMIN
    note                  VARCHAR NOT NULL,
    recorded_at           TIMESTAMP NOT NULL
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

-- Owner decision B (2026-11-15): a company's wrong XBRL value corrected from its signed statutory results PDF.
-- Raw XBRL and fact_observations stay as filed; readers rank a correction above the corrected filing's own value,
-- visible from that filing's visibility (the PDF was published with it), and a later filing still wins. A NULL
-- value withdraws the tag for that period (the X86 attribution_withheld marker once owners / NCI are corrected).
-- Batch K: per-share tags (EPS, face value; admin.PER_SHARE_TAGS) carry value_other (rupees per share) with a NULL
-- value_inr, like fact_observations; a rupee tag never has value_other (admin._correct enforces both).
CREATE TABLE IF NOT EXISTS fact_corrections (
    correction_id   VARCHAR PRIMARY KEY,           -- stable_id(filing, tag, period, value)
    filing_id       VARCHAR NOT NULL REFERENCES filings(filing_id),
    entity_id       VARCHAR NOT NULL REFERENCES entity_master(entity_id),
    scope           VARCHAR NOT NULL,
    canonical_tag   VARCHAR NOT NULL,
    period_type     VARCHAR NOT NULL,
    period_start    DATE NOT NULL,
    period_end      DATE NOT NULL,
    value_inr       DECIMAL(20,2),
    evidence_url    VARCHAR NOT NULL,              -- the statutory results PDF
    evidence_page   INTEGER NOT NULL,
    evidence_text   VARCHAR NOT NULL,              -- the printed line(s) the value was read from
    reads           VARCHAR NOT NULL,              -- independent reads that agreed, e.g. TEXT+HAIKU
    quarantine_id   VARCHAR,
    note            VARCHAR NOT NULL,
    created_at      TIMESTAMP NOT NULL,
    revoked_at      TIMESTAMP,
    value_other     DECIMAL(18,4),                 -- batch K: rupees per share for PER_SHARE_TAGS, else NULL
    CHECK (period_type IN ('DURATION', 'INSTANT'))
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
-- screener_features_history is stored event-sparse (architecture §4.1, features_store.py) and read through the view
-- of the same name (below VIEWS_MARKER): features_daily holds the DAILY columns (price, volume, market cap / EV
-- ratios, windows over the as-of day, the day's cross-section) for every materialised day; features_events holds
-- the EVENT columns (features_store.EVENT_COLUMNS: values that change only when one of the security's
-- fundamentals-cache inputs becomes visible) once per interval [valid_from_date, valid_to_date) of identical values.
-- A new column goes into exactly one of the two tables (and the view; tests/test_features_store.py checks).
CREATE TABLE IF NOT EXISTS features_daily (
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
    pe                  DOUBLE,
    pb                  DOUBLE,
    ev_ebitda           DOUBLE,
    fcff_yield          DOUBLE,
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
    shp_as_of           DATE,
    in_nifty500         BOOLEAN,
    eps_ttm             DECIMAL(18,4),       -- TTM owners' profit / current shares [X53]
    eps_continuing_ttm  DECIMAL(18,4),       -- TTM continuing owners' profit / current shares [C10]
    persistency_13m     DOUBLE,              -- life insurers, filed in XBRL [X62]
    persistency_61m     DOUBLE,
    reverse_dcf_implied_g  DOUBLE,           -- 5Y FCFF growth implied by EV [C20]
    reverse_dcf_wacc_used  DOUBLE,           -- assumption stored with the result (0.12)
    reverse_dcf_terminal_g DOUBLE,           -- assumption stored with the result (0.04)
    pe_percentile       DOUBLE,              -- rank vs own prior quarter-end values, >= 4 quarters [C20]
    ev_ebitda_percentile DOUBLE,
    ev_to_gross_profit  DOUBLE,
    ex_cash_pe          DOUBLE,              -- (mcap - liquid cash) / (continuing owners' PAT - OI x (1 - ETR))
    ev_to_billings      DOUBLE,              -- EV / (TTM revenue + YoY change in contract liabilities)
    ev_to_esop_adj_ebitda DOUBLE,            -- EV / (EBITDA + ESOP cost), cash-flow window
    price_to_cfo        DOUBLE,
    promoter_holding_pct DOUBLE,             -- Reg. 31 fractions as filed; denominator excludes DR shares [SHP9]
    promoter_pledge_pct DOUBLE,              -- pledged / promoter shares [SHP10]
    promoter_encumbered_pct DOUBLE,          -- (pledge + NDU + other encumbrance) / promoter shares [SHP10]
    fii_holding_pct     DOUBLE,              -- SEBI "Institutions (Foreign)": includes FDI and overseas depositories
    fpi_holding_pct     DOUBLE,              -- FPI Category I + II only [SHP13]
    dii_holding_pct     DOUBLE,              -- SEBI "Institutions (Domestic)"
    public_holding_pct  DOUBLE,
    non_promoter_non_public_pct DOUBLE,      -- DR custodian + employee trusts, of total issued shares
    fii_dii_qoq_change_pct DOUBLE,           -- (FII + DII) now minus previous quarter end; fraction points
    order_wins_90d      INTEGER,             -- Reg. 30 order wins visible, occurred in the 90 days to as-of [E3]
    order_value_90d     DECIMAL(24,2),       -- sum of their filed amounts (rupees)
    kmp_resignations_90d INTEGER,            -- KMP / director cessations by resignation [E5]
    auditor_resignations_90d INTEGER,        -- auditor cessations by resignation [E5]
    fraud_or_default_90d INTEGER,            -- fraud / default disclosures [E7]
    penalties_90d       INTEGER,             -- NULL: no penalty / regulatory-action event observed (UNVERIFIED) [E7]
    vnb_margin          DOUBLE,              -- supplemental_kpis (life insurers), latest period visible at as-of
    embedded_value      DECIMAL(24,2),       -- supplemental_kpis, rupees
    ape_growth          DOUBLE,              -- supplemental_kpis
    gov                 DECIMAL(24,2),       -- supplemental_kpis (new-gen tech): gross order value, rupees
    take_rate           DOUBLE,              -- supplemental_kpis: net take rate
    contribution_margin DOUBLE,              -- supplemental_kpis
    nrr                 DOUBLE,              -- supplemental_kpis: net revenue retention
    cac_payback         DOUBLE,              -- supplemental_kpis: months
    dividend_yield_pct  DOUBLE,              -- trailing-365-day accepted cash dividends (today's share basis) / close
    dividend_payout_pct DOUBLE,              -- the same dividends per share / eps_ttm; NULL if EPS <= 0
    promoter_holding_change_qoq_pp DOUBLE,   -- Reg. 31 promoter % now minus the previous quarter end, in pp
    -- batch B (price/technicals): features_price.py; adjusted = x price factors of later accepted share-count / demerger
    -- actions (volume / the same); NULL while a gap freezes the series or the window exceeds the stored bars [C9]
    return_1d           DOUBLE,              -- adjusted close / close 1 bar earlier - 1
    return_1w           DOUBLE,              -- 5 bars
    return_3y           DOUBLE,              -- 756 bars, cumulative (not annualised); NULL until ~Oct 2027
    return_5y           DOUBLE,              -- 1,260 bars, cumulative; NULL until ~Oct 2029
    return_7y           DOUBLE,              -- 1,764 bars, cumulative; NULL until ~Oct 2031
    return_10y          DOUBLE,              -- 2,520 bars, cumulative; NULL until ~Oct 2034
    volume              BIGINT,              -- today's traded quantity as filed (TtlTradgVol)
    volume_1w_avg       DOUBLE,              -- mean adjusted volume, 5 bars
    volume_1m_avg       DOUBLE,              -- 21 bars
    volume_1y_avg       DOUBLE,              -- 252 bars
    high_52w            DECIMAL(18,4),       -- max adjusted close, 252 bars
    low_52w             DECIMAL(18,4),       -- min adjusted close, 252 bars
    dist_52w_low        DOUBLE,              -- adjusted close / low_52w - 1 (>= 0)
    high_since_data_start DECIMAL(18,4),     -- max adjusted close since the first bar (>= 2024-10-01): NOT all-time
    low_since_data_start  DECIMAL(18,4),     -- min adjusted close since the first bar: NOT all-time
    dma50               DECIMAL(18,4),       -- mean adjusted close, 50 bars
    dma200              DECIMAL(18,4),       -- 200 bars
    dma50_prev          DECIMAL(18,4),       -- same, window ending one bar earlier
    dma200_prev         DECIMAL(18,4),
    rsi_14              DOUBLE,              -- Wilder RSI(14) on adjusted closes, seeded at the first bar
    rsi_14_prev         DOUBLE,
    macd                DOUBLE,              -- EMA12 - EMA26 of adjusted closes (EMAs seeded by an SMA)
    macd_signal         DOUBLE,              -- EMA9 of MACD (34 bars)
    macd_prev           DOUBLE,
    macd_signal_prev    DOUBLE,
    atr_14_pct          DOUBLE,              -- Wilder ATR(14) on adjusted H/L/C / adjusted close (fraction)
    rs_nifty500_3m      DOUBLE,              -- stock return - Nifty 500 price-index return over 63 bars (fraction points)
    rs_nifty500_6m      DOUBLE,              -- 126 bars
    rs_nifty500_12m     DOUBLE,              -- 252 bars
    beta_1y_nifty500    DOUBLE,              -- OLS beta of daily log returns vs Nifty 500, 252 returns
    turnover_median_20d DECIMAL(24,2),       -- median daily traded value (TtlTrfVal), 20 bars, rupees
    deliv_pct           DOUBLE,              -- today's deliv_qty / volume (fraction) [P16]
    deliv_pct_avg_20d   DOUBLE,              -- mean daily delivery fraction, 20 bars
    vwap                DECIMAL(18,4),       -- today's turnover / volume (= AVG_PRICE) [P16]
    vwap_20d            DECIMAL(18,4),       -- 20-bar traded value / adjusted volume (today's share basis)
    eps_latest_quarter                       DECIMAL(18,4),   -- filed EPS x later EPS factors
    eps_preceding_quarter                    DECIMAL(18,4),
    eps_preceding_year_quarter               DECIMAL(18,4),
    eps_last_year                            DECIMAL(18,4),
    eps_preceding_year                       DECIMAL(18,4),
    eps_growth_3y_pct                        DOUBLE,
    eps_growth_5y_pct                        DOUBLE,
    eps_growth_7y_pct                        DOUBLE,
    eps_growth_10y_pct                       DOUBLE,
    book_value_per_share                     DECIMAL(18,4),   -- owners' equity / shares
    is_trade_to_trade                        BOOLEAN,         -- series BE or BZ
    book_value_preceding_year                DECIMAL(18,4),      -- owners' equity / Reg. 31 shares, both at that FY end, today's share basis
    book_value_3y_back                       DECIMAL(18,4),      -- gated (~May 2028)
    book_value_5y_back                       DECIMAL(18,4),
    book_value_10y_back                      DECIMAL(18,4),
    graham_number                            DECIMAL(18,4),      -- sqrt(22.5 x EPS TTM x book value per share)
    shares_preceding_year                    BIGINT,             -- Reg. 31 total a year before the latest SHP, today's basis
    shares_10y_back                          BIGINT,             -- gated (~Apr 2035)
    price_to_fcf                             DOUBLE,             -- market cap / fcf_ttm; NULL when FCF <= 0
    equity_fcf_yield                         DOUBLE,             -- fcf_ttm / market cap (G170, signed)
    shareholder_yield                        DOUBLE,             -- TTM (dividends + buybacks - share issues) cash / mcap (G316)
    buyback_yield                            DOUBLE,             -- TTM buyback cash / market cap
    dilution_1y                              DOUBLE,             -- Reg. 31 shares now / a year earlier - 1 (today's basis)
    dilution_5y                              DOUBLE,             -- G219: same, 5 years (gated, ~Apr 2030)
    ev_ebitda_percentile_20q                 DOUBLE,             -- G240: rank vs the last 20 quarter-ends (C9: ~2031)
    -- batch D (ownership / hidden gems): features_gems.py; fractions like other _pct columns
    fii_holding_change_qoq_pct               DOUBLE,          -- Reg. 31 FII (Institutions Foreign) now - previous quarter end (fraction points)
    dii_holding_change_qoq_pct               DOUBLE,          -- same for DII; NULL unless the two latest are adjacent quarters [SHP14]
    inst_holding_pct                         DOUBLE,          -- FII + DII (fraction)
    unpledged_promoter_holding_pct           DOUBLE,          -- promoter pct x (1 - pledge of promoter shares)
    mf_holding_pct                           DOUBLE,          -- Reg. 31 mutual funds / UTI (fraction)
    mf_holding_change_qoq_pct                DOUBLE,          -- adjacent quarters (fraction points)
    insurance_holding_pct                    DOUBLE,          -- InsuranceCompaniesMember line item [SHP19]
    retail_holding_pct                       DOUBLE,          -- resident individuals up to Rs 2 lakh nominal capital [SHP19]
    num_shareholders                         BIGINT,          -- TOTAL NumberOfShareholders, latest visible pattern [SHP19]
    num_shareholders_preceding_quarter       BIGINT,          -- adjacent previous quarter end
    num_shareholders_change_qoq_pct          DOUBLE,          -- growth vs the preceding quarter (fraction)
    num_shareholders_1y_back                 BIGINT,          -- pattern exactly 12 months before the latest
    pe_core                                  DOUBLE,          -- market cap / TTM core profit after TTM tax, owners' share
    peg                                      DOUBLE,          -- pe_core / (100 x core growth): quarter YoY, TTM YoY once 8 quarters exist
    earnings_yield                           DOUBLE,          -- TTM EBIT / EV; NULL if EV <= 0 or lender
    industry                                 VARCHAR,         -- Nifty 500 snapshot industry (latest on/before as-of listing the ISIN)
    cyclical_flag                            BOOLEAN,         -- industry in the cyclical set or reference/cyclical_symbols.csv
    under_owned                              BOOLEAN,         -- inst <= 15% and promoter >= 50% and pledge = 0
    forensic_clean                           BOOLEAN,         -- no measured red flag (features_gems.forensic_clean)
    pe_vs_own_5y_median                      DOUBLE,          -- PE / own 5-year median daily PE (gated, C9)
    magic_formula_rank                       INTEGER,         -- EY rank + ROCE rank position in the gated non-financial universe (1 = best)
    pe_core_universe_median                  DOUBLE,          -- median pe_core of the day's gated non-financial universe
    market_cap_universe_median               DECIMAL(24,2),   -- median market cap of the same universe, rupees
    gem_score                                DOUBLE,          -- weighted clipped z-score blend (hidden_gems.md), non-cyclical universe
    hat_hidden_compounder                    BOOLEAN,         -- hidden_gems.md section B screen
    hat_quality_fair_price                   BOOLEAN,
    hat_magic_formula                        BOOLEAN,
    hat_garp                                 BOOLEAN,
    hat_turnaround                           BOOLEAN,
    hat_under_owned                          BOOLEAN,
    hat_cash_machine                         BOOLEAN,
    hat_fallen_quality                       BOOLEAN,
    hat_capex_pay_off                        BOOLEAN,
    hat_cyclical                             BOOLEAN,
    hat_lender                               BOOLEAN,
    hats_passed                              INTEGER,         -- count of hat_* TRUE
    -- batch H (industry / peers): features_peers.py; NSE 4-level classification [IC1-IC3], visible from its first fetch
    nse_macro_sector                         VARCHAR,         -- NSE macro-economic sector (quote API secInfo.macro), PIT
    nse_sector                               VARCHAR,         -- NSE sector (secInfo.sector)
    nse_industry                             VARCHAR,         -- NSE industry (secInfo.industryInfo)
    nse_basic_industry                       VARCHAR,         -- NSE basic industry (secInfo.basicIndustry)
    industry_pe_median                       DOUBLE,          -- median PE (> 0) of the day's companies in nse_industry (>= 3 values)
    industry_pb_median                       DOUBLE,          -- same for PB (> 0)
    industry_roce_median                     DOUBLE,          -- same for ROCE (fraction)
    industry_sales_growth_median             DOUBLE,          -- same for sales_growth_yoy (fraction)
    basic_industry_pe_median                 DOUBLE,          -- the four medians within nse_basic_industry
    basic_industry_pb_median                 DOUBLE,
    basic_industry_roce_median               DOUBLE,
    basic_industry_sales_growth_median       DOUBLE,
    pe_premium_to_industry                   DOUBLE,          -- pe / industry_pe_median - 1 (negative = discount)
    pb_premium_to_industry                   DOUBLE,          -- pb / industry_pb_median - 1
    pe_premium_to_basic_industry             DOUBLE,          -- pe / basic_industry_pe_median - 1 (G199)
    pb_premium_to_basic_industry             DOUBLE,          -- pb / basic_industry_pb_median - 1
    peer_count                               INTEGER,         -- companies in nse_basic_industry on the day (incl. itself)
    peer_rank_market_cap                     INTEGER,         -- 1 = largest market cap in nse_basic_industry (G112)
    peer_rank_pe                             INTEGER,         -- 1 = lowest PE (> 0)
    peer_rank_roce                           INTEGER,         -- 1 = highest ROCE
    peer_rank_profit_growth                  INTEGER,         -- 1 = highest profit_growth_yoy_quarter_pct
    industry_group_pe_median                 DOUBLE,          -- fallback: medians over the Nifty 500 file's `industry` (never mixed with NSE levels)
    industry_group_pb_median                 DOUBLE,
    industry_group_roce_median               DOUBLE,
    industry_group_sales_growth_median       DOUBLE,
    pe_premium_to_industry_group             DOUBLE,          -- pe / industry_group_pe_median - 1
    pb_premium_to_industry_group             DOUBLE,          -- pb / industry_group_pb_median - 1
    net_cash_to_market_cap                   DOUBLE,          -- -(net debt) / market cap (B2.17)
    price_to_sales                           DOUBLE,          -- market cap / sales_ttm (A1.7)
    ev_to_sales                              DOUBLE,          -- EV / sales_ttm (B5.6)
    price_to_embedded_value                  DOUBLE,          -- market cap / embedded value KPI (G270)
    gov_ttm                                  DECIMAL(24,2),   -- TTM gross order value KPI, rupees (12M period or 4 quarters)
    ev_to_gov                                DOUBLE,          -- EV / gov_ttm (G265)
    gov_growth_yoy_pct                       DOUBLE,          -- latest KPI period vs the same period a year earlier
    arpu                                     DECIMAL(24,2),   -- KPI, rupees per user, latest period (G266)
    arpu_growth_yoy_pct                      DOUBLE,          -- YoY, same-length period
    mtu                                      BIGINT,          -- KPI, monthly transacting users, latest period (G266)
    mtu_growth_yoy_pct                       DOUBLE,          -- YoY, same-length period
    contribution_margin_change_yoy_pp        DOUBLE,          -- KPI contribution margin YoY change (G257)
    casa_pct                                 DOUBLE,          -- banks, KPI (master backlog M4)
    inst_shares_change_qoq                   BIGINT,          -- FII + DII shares, adjacent Reg. 31 quarters
    volume_median_90d                        DOUBLE,          -- median daily volume, 90 calendar days
    institutional_absorption_90d             DOUBLE,          -- inst_shares_change_qoq / volume_median_90d, days (G241)
    promoter_pledge_change_qoq_pp            DOUBLE,          -- pledged / promoter shares QoQ (B7.4)
    public_holders_above_1pct                INTEGER,         -- named public holders > 1%, latest Reg. 31 (B7.6)
    litigations_90d                          INTEGER,         -- Reg. 30 LITIGATION disclosures in 90 days (B8.3)
    allotments_90d                           INTEGER,         -- Reg. 30 ALLOTMENT records (B8.2)
    fund_raising_events_90d                  INTEGER,         -- Reg. 30 FUND_RAISING family
    rf_auditor_resignation_90d               BOOLEAN,         -- red flags (G117): separate columns, never summed
    rf_kmp_resignations_90d                  BOOLEAN,         -- >= 2 KMP / director resignations in 90 days
    rf_fraud_or_default_90d                  BOOLEAN,
    rf_litigation_90d                        BOOLEAN,
    rf_pledge_increase_qoq                   BOOLEAN,         -- promoter_pledge_change_qoq_pp > 0
    pe_numerator                             DECIMAL(24,2),   -- G244 raw inputs: market cap
    ev_ebitda_numerator                      DECIMAL(24,2),   -- EV
    altman_z_original                        DOUBLE,          -- B1.5 original Z, manufacturers (C6 guard), MVE = market cap
    pb_percentile                            DOUBLE,          -- B5.2 / B5.3 vs own prior quarter-ends [C20], >= 4
    price_to_sales_percentile                DOUBLE,
    ev_to_sales_percentile                   DOUBLE,
    momentum_12m_1m                          DOUBLE,          -- B6.3 (1 + return_12m) / (1 + return_1m) - 1
    volatility_1y                            DOUBLE,          -- B6.4 annualised std of 252 daily log returns
    max_drawdown_1y                          DOUBLE,
    high_52w_on_delivery_spike               BOOLEAN,         -- B6.11 / G283 52W high with delivery > 2x 20D median
    pead_event_date                          DATE,            -- B6.14 / G151 latest results broadcast (IST)
    pead_ar_t0                               DOUBLE,          -- stock - Nifty 500 return since the pre-results close
    pead_ar_t1                               DOUBLE,
    pead_ar_t5                               DOUBLE,
    pead_ar_t20                              DOUBLE,
    pead_relvol_t0                           DOUBLE,          -- volume / mean of the 20 bars before T+0
    pead_relvol_t1                           DOUBLE,
    pead_relvol_t5                           DOUBLE,
    pead_relvol_t20                          DOUBLE,
    nifty500_inclusion_90d                   BOOLEAN,         -- B8.4 NULL until stored history covers 90 days
    nifty500_exclusion_90d                   BOOLEAN,
    days_to_next_ex_date                     INTEGER,         -- B8.5 announced (visible) actions only
    next_ex_date_action                      VARCHAR,
    dividend_365d                            BOOLEAN,         -- NULL while the window starts before C9
    bonus_365d                               BOOLEAN,
    split_365d                               BOOLEAN,
    rs_rank_12m_1m                           DOUBLE,          -- cross-section (refresh step): 1 = strongest
    industry_earnings_breadth                DOUBLE,          -- B4.9 / G205 share of NSE industry with core profit YoY > 0
    industry_earnings_breadth_n              INTEGER,         -- companies measured (latest quarter of the industry)
    -- 18D: Reg. 31 declarations of the latest visible shareholding filing (entity-level element) [X118]
    has_warrants                             BOOLEAN,
    has_convertibles                         BOOLEAN,
    has_partly_paid                          BOOLEAN,
    has_locked_in                            BOOLEAN,
    has_dvr_shares                           BOOLEAN,         -- equity shares with differential voting rights
    has_sbo                                  BOOLEAN,         -- any significant beneficial owner
    is_psu                                   BOOLEAN,         -- public sector undertaking
    PRIMARY KEY (as_of_date, security_id)
);

CREATE TABLE IF NOT EXISTS features_events (
    security_id         VARCHAR NOT NULL,
    valid_from_date     DATE    NOT NULL,    -- first materialised day with these values
    valid_to_date       DATE,                -- exclusive; NULL = open (still current)
    sales_ttm           DECIMAL(24,2),
    ebitda_ttm          DECIMAL(24,2),
    pat_ttm             DECIMAL(24,2),
    fcf_ttm             DECIMAL(24,2),
    net_debt            DECIMAL(24,2),
    total_equity        DECIMAL(24,2),
    opm                 DOUBLE,
    sales_growth_yoy    DOUBLE,
    profit_growth_yoy   DOUBLE,
    roe                 DOUBLE,
    roce                DOUBLE,
    roic                DOUBLE,
    croic               DOUBLE,
    debt_to_equity      DOUBLE,
    other_income_to_pbt DOUBLE,
    altman_z_dd         DOUBLE,              -- X2 uses OtherEquity as retained-earnings proxy
    piotroski_f         INTEGER,             -- 0..9, year-end-assets variant; NULL without two FYs [C23]
    beneish_m           DOUBLE,              -- 8-variable M-score; NULL without two FYs [C23]
    scope_used          VARCHAR,
    fundamentals_end    DATE,                -- quarter end of the TTM window
    bs_as_of            DATE,
    cf_as_of            DATE,
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
    scope_reason        VARCHAR,             -- DEFAULT | FALLBACK_DEFAULT_INCOMPLETE | OVERRIDE | YTD_BRIDGE | BALANCE_SHEET_ONLY
    restatement_suspected BOOLEAN,           -- X106: a restated quarter inside the TTM window; TTM uses the YTD bridge
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
    valuation_archetype VARCHAR,             -- INDUSTRIAL_SERVICES | FINANCIAL_LENDING | INSURANCE | NEW_GEN_TECH [C21]
    rule_of_40          DOUBLE,              -- revenue YoY + EBITDA margin (needs 8 quarters)
    billings_growth_pct DOUBLE,              -- billings YoY (needs 8 quarters and labelled contract liabilities)
    neg_working_capital_float_pct DOUBLE,    -- ((payables + contract liabilities) - (receivables + inventory)) / revenue
    net_burn_multiple   DOUBLE,              -- cash burn / incremental revenue, only when FCF < 0 (needs 8 quarters)
    cash_runway_months  DOUBLE,              -- liquid cash / monthly burn, only when FCF < 0
    esop_adj_fcf        DECIMAL(24,2),       -- FCF - ESOP cost
    liquid_cash         DECIMAL(24,2),       -- cash + other bank balances + current investments
    capex_to_depreciation DOUBLE,            -- FY (PPE + intangibles capex) / D&A [C23]
    cwip_to_gross_block DOUBLE,              -- CWIP / gross block (Reg. 34 PPE schedule) [X71]
    rote                DOUBLE,              -- FY owners' PAT / (owners' equity - goodwill - other intangibles)
    rnd_and_royalty_intensity DOUBLE,        -- (R&D + royalty) / revenue; NULL when neither is disclosed [X73]
    contingent_liabilities_to_net_worth DOUBLE, -- contingent liabilities / owners' equity [X73]
    annual_fy_end       DATE,                -- fiscal year the annual ratios (incl. Piotroski/Beneish) use
    roce_screener       DOUBLE,              -- Screener export: (PBT + Interest) x 2 / (opening + closing capital) [S22]
    debtor_days         DOUBLE,              -- Screener export: closing debtors / (sales / 365) [S22]
    inventory_turnover  DOUBLE,              -- Screener export: sales / closing inventory [S22]
    working_capital     DECIMAL(24,2),       -- Screener export: Other Assets - Other Liabilities (rupees) [S22]
    inventory_days      DOUBLE,              -- closing inventory / (COGS / 365); NULL if COGS < 1% of sales [S23]
    days_payable        DOUBLE,              -- closing trade payables / (COGS / 365) [S23]
    cash_conversion_cycle DOUBLE,            -- debtor + inventory - payable days [S23]
    working_capital_days DOUBLE,             -- (CA - cash & bank - current investments - CL) / (sales / 365) [S23]
    sales_growth_qoq_pct DOUBLE,             -- latest quarter's sales / previous quarter's - 1, same scope book
    profit_growth_qoq_pct DOUBLE,            -- same for COALESCE(owners, PAT) per filing; NULL if the base <= 0
    npm_pct             DOUBLE,              -- TTM owners' profit / sales_ttm (fraction)
    interest_coverage   DOUBLE,              -- TTM (PBT + finance costs) / finance costs; NULL for lenders, insurers
    opm_last_year_pct   DOUBLE,              -- last fiscal year's EBITDA / sales (fraction; was same quarter until 4A)
    -- batch A (P&L family)
    sales_latest_quarter                     DECIMAL(24,2),   -- quarter lines, rupees (features_pl)
    sales_preceding_quarter                  DECIMAL(24,2),
    sales_preceding_year_quarter             DECIMAL(24,2),
    operating_profit_latest_quarter          DECIMAL(24,2),
    operating_profit_preceding_quarter       DECIMAL(24,2),
    operating_profit_preceding_year_quarter  DECIMAL(24,2),
    other_income_latest_quarter              DECIMAL(24,2),
    other_income_preceding_quarter           DECIMAL(24,2),
    other_income_preceding_year_quarter      DECIMAL(24,2),
    depreciation_latest_quarter              DECIMAL(24,2),
    depreciation_preceding_quarter           DECIMAL(24,2),
    depreciation_preceding_year_quarter      DECIMAL(24,2),
    ebit_latest_quarter                      DECIMAL(24,2),
    ebit_preceding_quarter                   DECIMAL(24,2),
    ebit_preceding_year_quarter              DECIMAL(24,2),
    interest_latest_quarter                  DECIMAL(24,2),
    interest_preceding_quarter               DECIMAL(24,2),
    interest_preceding_year_quarter          DECIMAL(24,2),
    pbt_latest_quarter                       DECIMAL(24,2),
    pbt_preceding_quarter                    DECIMAL(24,2),
    pbt_preceding_year_quarter               DECIMAL(24,2),
    tax_latest_quarter                       DECIMAL(24,2),
    tax_preceding_quarter                    DECIMAL(24,2),
    tax_preceding_year_quarter               DECIMAL(24,2),
    pat_latest_quarter                       DECIMAL(24,2),
    pat_preceding_quarter                    DECIMAL(24,2),
    pat_preceding_year_quarter               DECIMAL(24,2),
    net_profit_latest_quarter                DECIMAL(24,2),
    net_profit_preceding_quarter             DECIMAL(24,2),
    net_profit_preceding_year_quarter        DECIMAL(24,2),
    exceptional_items_latest_quarter         DECIMAL(24,2),
    exceptional_items_preceding_quarter      DECIMAL(24,2),
    exceptional_items_preceding_year_quarter DECIMAL(24,2),
    sales_2quarters_back                     DECIMAL(24,2),
    sales_3quarters_back                     DECIMAL(24,2),
    operating_profit_2quarters_back          DECIMAL(24,2),
    operating_profit_3quarters_back          DECIMAL(24,2),
    net_profit_2quarters_back                DECIMAL(24,2),
    net_profit_3quarters_back                DECIMAL(24,2),
    sales_last_year                          DECIMAL(24,2),   -- latest FY <= fundamentals_end: filed 12M, else 4 Qs
    sales_preceding_year                     DECIMAL(24,2),
    operating_profit_last_year               DECIMAL(24,2),
    operating_profit_preceding_year          DECIMAL(24,2),
    other_income_last_year                   DECIMAL(24,2),
    other_income_preceding_year              DECIMAL(24,2),
    depreciation_last_year                   DECIMAL(24,2),
    depreciation_preceding_year              DECIMAL(24,2),
    ebit_last_year                           DECIMAL(24,2),
    ebit_preceding_year                      DECIMAL(24,2),
    interest_last_year                       DECIMAL(24,2),
    interest_preceding_year                  DECIMAL(24,2),
    pbt_last_year                            DECIMAL(24,2),
    pbt_preceding_year                       DECIMAL(24,2),
    tax_last_year                            DECIMAL(24,2),
    tax_preceding_year                       DECIMAL(24,2),
    pat_last_year                            DECIMAL(24,2),
    pat_preceding_year                       DECIMAL(24,2),
    net_profit_last_year                     DECIMAL(24,2),
    net_profit_preceding_year                DECIMAL(24,2),
    exceptional_items_last_year              DECIMAL(24,2),
    exceptional_items_preceding_year         DECIMAL(24,2),
    sales_ttm_1y_back                        DECIMAL(24,2),   -- TTM ending fundamentals_end - 12 months
    avg_earnings_5y                          DECIMAL(24,2),   -- mean of N FYs (history-gated, C9)
    avg_earnings_10y                         DECIMAL(24,2),
    avg_ebit_5y                              DECIMAL(24,2),
    avg_ebit_10y                             DECIMAL(24,2),
    equity_capital_latest_quarter            DECIMAL(24,2),   -- paid-up, results filing
    equity_capital_preceding_quarter         DECIMAL(24,2),
    equity_capital_preceding_year_quarter    DECIMAL(24,2),
    opm_latest_quarter_pct                   DOUBLE,          -- fractions; GPM only per C6
    opm_preceding_quarter_pct                DOUBLE,
    opm_preceding_year_pct                   DOUBLE,
    npm_latest_quarter_pct                   DOUBLE,
    npm_preceding_quarter_pct                DOUBLE,
    npm_preceding_year_quarter_pct           DOUBLE,
    npm_last_year_pct                        DOUBLE,
    npm_preceding_year_pct                   DOUBLE,
    gpm_latest_quarter_pct                   DOUBLE,
    gpm_last_year_pct                        DOUBLE,
    gpm_preceding_year_pct                   DOUBLE,
    sales_growth_yoy_quarter_pct             DOUBLE,          -- Q / same Q last year - 1; base > 0
    profit_growth_yoy_quarter_pct            DOUBLE,
    operating_profit_growth_yoy_quarter_pct  DOUBLE,
    sales_growth_3y_pct                      DOUBLE,          -- FY CAGR; NULL until base FY in scope
    sales_growth_5y_pct                      DOUBLE,
    sales_growth_7y_pct                      DOUBLE,
    sales_growth_10y_pct                     DOUBLE,
    profit_growth_3y_pct                     DOUBLE,
    profit_growth_5y_pct                     DOUBLE,
    profit_growth_7y_pct                     DOUBLE,
    profit_growth_10y_pct                    DOUBLE,
    operating_profit_growth_3y_pct           DOUBLE,
    operating_profit_growth_5y_pct           DOUBLE,
    operating_profit_growth_7y_pct           DOUBLE,
    operating_profit_growth_10y_pct          DOUBLE,
    sales_growth_median_5y_pct               DOUBLE,          -- median yearly FY growth (gated)
    sales_growth_median_10y_pct              DOUBLE,
    opm_5y_pct                               DOUBLE,          -- mean FY OPM over 5 / 10 FYs (gated)
    opm_10y_pct                              DOUBLE,
    last_result_date                         DATE,            -- IST, latest quarter first visible
    last_annual_result_date                  DATE,            -- IST, latest FY first visible
    opm_preceding_year_quarter_pct           DOUBLE,          -- same quarter last year (fraction)
    -- batch C (balance sheet / cash flow): features_bs.py; money in rupees, ratios as fractions, days in days;
    -- unsuffixed BS lines = latest BS, 'preceding year' / 'N years back' = FY ends; NULL for lenders where noted
    debt                                     DECIMAL(24,2),      -- latest BS (bs_as_of): borrowings + leases, absent line = 0 [C23]
    equity_capital                           DECIMAL(24,2),      -- latest BS, rupees
    reserves                                 DECIMAL(24,2),      -- other equity (banks / insurers: reserves and surplus)
    balance_sheet_total                      DECIMAL(24,2),      -- total assets net of DTA/DTL netting (Screener) [S10]
    net_block                                DECIMAL(24,2),      -- PPE + investment property + goodwill + intangibles + ROU
    cwip                                     DECIMAL(24,2),      -- CWIP + intangibles under development
    investments                              DECIMAL(24,2),      -- non-current + current + equity-method
    current_assets                           DECIMAL(24,2),
    current_liabilities                      DECIMAL(24,2),
    lease_liabilities                        DECIMAL(24,2),
    inventory                                DECIMAL(24,2),
    trade_receivables                        DECIMAL(24,2),
    trade_payables                           DECIMAL(24,2),
    cash_equivalents                         DECIMAL(24,2),      -- cash and cash equivalents (BS line)
    gross_block                              DECIMAL(24,2),      -- Reg. 34 PPE schedule at the last FY end [X71]
    accumulated_depreciation                 DECIMAL(24,2),      -- Reg. 34 at the last FY end
    contingent_liabilities                   DECIMAL(24,2),      -- Reg. 34 at the last FY end (excl. commitments) [X73]
    advance_from_customers                   DECIMAL(24,2),      -- Reg. 34 at the last FY end [X73]
    debt_preceding_year                      DECIMAL(24,2),      -- BS at the end of the FY before the last FY
    net_block_preceding_year                 DECIMAL(24,2),
    gross_block_preceding_year               DECIMAL(24,2),
    cwip_preceding_year                      DECIMAL(24,2),
    working_capital_preceding_year           DECIMAL(24,2),      -- Screener: Other Assets - Other Liabilities
    debt_3y_back                             DECIMAL(24,2),      -- last FY end - N years; NULL until in scope (~May 2028)
    debt_5y_back                             DECIMAL(24,2),      -- ~May 2030
    debt_7y_back                             DECIMAL(24,2),      -- ~May 2032
    debt_10y_back                            DECIMAL(24,2),      -- ~May 2035
    net_block_3y_back                        DECIMAL(24,2),
    net_block_5y_back                        DECIMAL(24,2),
    net_block_7y_back                        DECIMAL(24,2),
    net_block_10y_back                       DECIMAL(24,2),
    working_capital_3y_back                  DECIMAL(24,2),
    working_capital_5y_back                  DECIMAL(24,2),
    working_capital_7y_back                  DECIMAL(24,2),
    working_capital_10y_back                 DECIMAL(24,2),
    cash_3y_back                             DECIMAL(24,2),      -- cash-flow-statement cash, FY end - N years (gated)
    cash_5y_back                             DECIMAL(24,2),
    cash_7y_back                             DECIMAL(24,2),
    cfo_last_year                            DECIMAL(24,2),      -- filed 12-month cash flow, last / preceding FY
    cfo_preceding_year                       DECIMAL(24,2),
    cfi_last_year                            DECIMAL(24,2),
    cfi_preceding_year                       DECIMAL(24,2),
    cff_last_year                            DECIMAL(24,2),
    cff_preceding_year                       DECIMAL(24,2),
    net_cash_flow_last_year                  DECIMAL(24,2),      -- after the FX effect on cash [S12]
    net_cash_flow_preceding_year             DECIMAL(24,2),
    cash_beginning_last_year                 DECIMAL(24,2),      -- prior FY-end cash, else cash end - net cash flow
    cash_beginning_preceding_year            DECIMAL(24,2),
    cash_end_last_year                       DECIMAL(24,2),
    cash_end_preceding_year                  DECIMAL(24,2),
    fcf_last_year                            DECIMAL(24,2),      -- CFO - (PPE + intangibles capex)
    fcf_preceding_year                       DECIMAL(24,2),
    fcf_3y                                   DECIMAL(24,2),      -- sum over N FYs; NULL until the oldest FY is in scope (3y ~May 2027)
    fcf_5y                                   DECIMAL(24,2),
    fcf_7y                                   DECIMAL(24,2),
    fcf_10y                                  DECIMAL(24,2),
    cfo_3y                                   DECIMAL(24,2),
    cfo_5y                                   DECIMAL(24,2),
    cfo_7y                                   DECIMAL(24,2),
    cfo_10y                                  DECIMAL(24,2),
    cfi_3y                                   DECIMAL(24,2),
    cfi_5y                                   DECIMAL(24,2),
    cfi_7y                                   DECIMAL(24,2),
    cfi_10y                                  DECIMAL(24,2),
    face_value                               DECIMAL(18,4),      -- INR per share, latest results filing
    current_ratio                            DOUBLE,             -- current assets / current liabilities (latest BS)
    quick_ratio                              DOUBLE,             -- (current assets - inventory) / current liabilities
    net_debt_to_equity                       DOUBLE,             -- net_debt / total equity
    long_term_debt_to_equity                 DOUBLE,             -- (non-current borrowings + leases) / total equity
    debt_to_equity_preceding_year            DOUBLE,             -- debt / total equity at the preceding FY end
    financial_leverage                       DOUBLE,             -- avg total assets / avg owners' equity (12 months to bs_as_of)
    asset_turnover                           DOUBLE,             -- TTM sales to bs_as_of / avg total assets
    earning_power                            DOUBLE,             -- TTM EBIT / total assets
    roe_preceding_year                       DOUBLE,             -- FY-1 owners' profit / owners' equity at FY-1 end
    roce_preceding_year                      DOUBLE,             -- FY-1 EBIT / (debt + total equity) at FY-1 end
    roa_preceding_year                       DOUBLE,             -- FY-1 owners' profit / avg total assets (needs FY-2 BS)
    exports_pct                              DOUBLE,             -- foreign / (domestic + foreign) revenue, Reg. 34 [X75]
    exports_pct_3y_back                      DOUBLE,             -- gated (~Sep 2028)
    exports_pct_5y_back                      DOUBLE,
    inventory_turnover_3y_back               DOUBLE,             -- Screener convention, FY N years back (gated)
    inventory_turnover_5y_back               DOUBLE,
    inventory_turnover_7y_back               DOUBLE,
    inventory_turnover_10y_back              DOUBLE,
    debtor_days_3y_back                      DOUBLE,             -- gated (~May 2028)
    debtor_days_5y_back                      DOUBLE,
    avg_debtor_days_3y                       DOUBLE,             -- mean of 3 FYs (gated, ~May 2027)
    avg_working_capital_days_3y              DOUBLE,             -- mean of 3 FYs (gated, ~May 2027)
    cfo_to_ebitda_last_year                  DOUBLE,             -- FY CFO / FY EBITDA
    cfo_to_ebitda_preceding_year             DOUBLE,
    fcf_conversion_3y                        DOUBLE,             -- 3-FY FCF / 3-FY owners' profit (G224, gated)
    cfo_to_ebitda_3y                         DOUBLE,             -- 3-FY CFO / 3-FY EBITDA (G223, gated)
    net_debt_to_fcf_3y                       DOUBLE,             -- net_debt / mean 3-FY FCF > 0 (G233, gated)
    reinvestment_rate                        DOUBLE,             -- FY (capex - D&A + change in non-cash WC) / NOPAT (G216)
    incremental_roic_1y                      DOUBLE,             -- FY change in NOPAT / change in invested capital
    incremental_roic_3y                      DOUBLE,             -- G215, gated (~May 2028)
    incremental_roic_5y                      DOUBLE,             -- G215, gated (~May 2030)
    net_debt_to_ebitda                       DOUBLE,             -- net_debt / ebitda_ttm (> 0)
    sales_growth_yoy_preceding_quarter_pct   DOUBLE,          -- preceding quarter vs the same quarter a year earlier
    profit_growth_yoy_preceding_quarter_pct  DOUBLE,          -- same for owners' profit; NULL if the base <= 0
    core_profit_latest_quarter               DECIMAL(24,2),   -- PBT - other income - exceptional items, rupees
    core_profit_yoy_latest_q                 DOUBLE,          -- core profit YoY, latest quarter; NULL if the base <= 0 or lender
    core_profit_yoy_preceding_q              DOUBLE,          -- same, preceding quarter
    other_income_lift_pp                     DOUBLE,          -- profit YoY - core profit YoY, latest quarter (fraction points)
    growth_sustained                         BOOLEAN,         -- sales YoY >= 12% in both latest and preceding quarter
    growth_acceleration_pp                   DOUBLE,          -- sales YoY latest - preceding quarter (fraction points)
    opm_change_yoy_pp                        DOUBLE,          -- quarter OPM - same quarter last year (fraction points)
    operating_leverage                       DOUBLE,          -- core profit YoY / sales YoY, latest quarter; NULL if sales YoY <= 0
    cash_conversion_ok                       BOOLEAN,         -- CFO / EBITDA >= 0.7
    capex_pay_off_signal                     BOOLEAN,         -- CWIP / gross block >= 25% and capex / D&A >= 2 and D/E <= 1
    roce_stability_5y                        DOUBLE,          -- 1 - std / mean of 5 FY ROCE (gated, C9)
    opm_stability_5y                         DOUBLE,          -- 1 - std / mean of 5 FY OPM (gated, C9)
    -- batch G (remaining Phase 2 ratios): features_extra.py; fractions like other _pct columns, money in rupees
    opm_acceleration_pp                      DOUBLE,          -- [OPM(Q) - OPM(Q-4)] - [OPM(Q-1) - OPM(Q-5)] (G152)
    gpm_change_yoy_pp                        DOUBLE,          -- quarter GPM - same quarter last year, C6 guard (G257)
    profit_growth_acceleration_pp            DOUBLE,          -- owners' profit YoY latest - preceding quarter (B4.6)
    sales_growth_streak_quarters             INTEGER,         -- consecutive quarters with sales YoY > 0, newest first (B4.8)
    profit_growth_streak_quarters            INTEGER,         -- same for owners' profit
    material_cost_latest_quarter_pct         DOUBLE,          -- (materials + purchases + inventory change) / sales (G133, B3.4)
    material_cost_last_year_pct              DOUBLE,
    employee_cost_latest_quarter_pct         DOUBLE,
    employee_cost_last_year_pct              DOUBLE,
    other_expenses_latest_quarter_pct        DOUBLE,
    other_expenses_last_year_pct             DOUBLE,
    power_fuel_latest_quarter_pct            DOUBLE,          -- labelled power & fuel / sales [X50]; NULL when not labelled
    power_fuel_last_year_pct                 DOUBLE,
    freight_latest_quarter_pct               DOUBLE,          -- labelled freight / sales [X50]
    freight_last_year_pct                    DOUBLE,
    ad_promo_latest_quarter_pct              DOUBLE,          -- advertising & promotion / sales, A&P intensity [X68] (G258)
    ad_promo_last_year_pct                   DOUBLE,          -- same on the last FY (Reg. 34 element [X74])
    marketing_efficiency_latest_quarter      DOUBLE,          -- sales change YoY / A&P of the quarter a year earlier (G256)
    marketing_efficiency_last_year           DOUBLE,          -- FY sales change / preceding FY A&P
    material_cost_last_year                  DECIMAL(24,2),   -- rupees, fiscal-year lines (A4.16-A4.19)
    material_cost_preceding_year             DECIMAL(24,2),
    employee_cost_last_year                  DECIMAL(24,2),
    employee_cost_preceding_year             DECIMAL(24,2),
    minority_share_last_year                 DECIMAL(24,2),
    minority_share_preceding_year            DECIMAL(24,2),
    dividends_paid_last_year                 DECIMAL(24,2),   -- cash-flow dividends paid; nil when the FY cash flow omits the line
    dividends_paid_preceding_year            DECIMAL(24,2),
    acquisition_outflow_last_year            DECIMAL(24,2),   -- CF obtaining control of subsidiaries / businesses, FY (G276)
    acquisition_outflow_preceding_year       DECIMAL(24,2),
    acquisition_outflow_to_sales_last_year   DOUBLE,          -- the same / FY sales
    inorganic_growth_flag                    BOOLEAN,         -- acquisitions >= 5% of sales in either of the last two FYs [C26]
    standalone_pat_ttm                       DECIMAL(24,2),   -- standalone TTM PAT (G278 input)
    profit_leakage_pct                       DOUBLE,          -- 1 - consolidated owners' TTM profit / standalone TTM PAT (G278)
    profit_leakage_latest_quarter_pct        DOUBLE,          -- same on the latest quarter
    incremental_asset_turnover_3y            DOUBLE,          -- FY sales change / net block change over 3 FYs (G220, C9 gated)
    cfo_to_pat                               DOUBLE,          -- cash-flow window CFO / PAT (B1.8)
    cash_tax_rate                            DOUBLE,          -- taxes paid / tax expense, cash-flow window (B1.11)
    effective_tax_rate                       DOUBLE,          -- TTM tax / TTM PBT, not clamped (B1.12)
    exceptional_to_pbt                       DOUBLE,          -- TTM exceptional items / PBT (B1.14)
    exceptional_quarters_4q                  INTEGER,         -- last 4 quarters with exceptional items != 0
    capex_intensity                          DOUBLE,          -- capex / sales, cash-flow window (B2.11)
    rpt_to_sales                             DOUBLE,          -- RPT total / sales of the same period (B1.19; G236 split blocked)
    intangibles_to_equity                    DOUBLE,          -- (goodwill + other intangibles) / owners' equity (B1.23)
    audit_fees_to_sales                      DOUBLE,          -- Reg. 34 last FY (B1.20)
    managerial_remuneration_to_pat           DOUBLE,          -- Reg. 34 last FY (B1.20)
    capital_commitments_to_net_worth         DOUBLE,          -- Reg. 34 last FY end (B1.22)
    unquoted_investments                     DECIMAL(24,2),   -- book value, non-current + current, last FY end (A6.12)
    quoted_investments_market_value          DECIMAL(24,2),   -- market value, non-current + current (A6.13)
    revaluation_reserve                      DECIMAL(24,2),   -- PPE revaluation surplus (A6.14)
    rf_audit_qualified                       BOOLEAN,         -- latest annual report text / results opinion modified [X121] (B1.16)
    pe_denominator                           DECIMAL(24,2),   -- continuing owners' TTM profit
    roe_numerator                            DECIMAL(24,2),   -- owners' TTM profit
    roe_denominator                          DECIMAL(24,2),   -- owners' equity
    roce_numerator                           DECIMAL(24,2),   -- TTM EBIT
    roce_denominator                         DECIMAL(24,2),   -- total equity + debt
    ev_ebitda_denominator                    DECIMAL(24,2),   -- TTM EBITDA
    opm_numerator                            DECIMAL(24,2),   -- TTM EBITDA
    opm_denominator                          DECIMAL(24,2),   -- sales_ttm
    -- batch I (last catalogue rows): features_more.py; fractions like other _pct columns, days as DOUBLE
    beneish_dsri                             DOUBLE,          -- B1.2 Beneish indices, last FY vs preceding FY (inputs of beneish_m)
    beneish_gmi                              DOUBLE,
    beneish_aqi                              DOUBLE,
    beneish_sgi                              DOUBLE,
    beneish_depi                             DOUBLE,
    beneish_sgai                             DOUBLE,
    beneish_lvgi                             DOUBLE,
    beneish_tata                             DOUBLE,
    piotroski_roa_positive                   BOOLEAN,         -- B1.3 Piotroski tests (inputs of piotroski_f), all or none
    piotroski_cfo_positive                   BOOLEAN,
    piotroski_roa_up                         BOOLEAN,
    piotroski_cfo_above_pat                  BOOLEAN,
    piotroski_leverage_down                  BOOLEAN,
    piotroski_current_ratio_up               BOOLEAN,
    piotroski_no_dilution                    BOOLEAN,
    piotroski_gross_margin_up                BOOLEAN,
    piotroski_asset_turnover_up              BOOLEAN,
    bs_accruals                              DOUBLE,          -- B1.7 change in NOA / avg total assets, last FY
    depreciation_rate                        DOUBLE,          -- B2.12 FY D&A / avg gross block (Reg. 34)
    asset_age_proxy                          DOUBLE,          -- B2.12 accumulated depreciation / gross block
    debtor_days_change_yoy                   DOUBLE,          -- B3.2 last FY - preceding FY, days
    ccc_change_yoy                           DOUBLE,
    h1_bs_as_of                              DATE,            -- B3.3 latest non-FY-end balance sheet (12 months)
    debtor_days_h1                           DOUBLE,
    inventory_days_h1                        DOUBLE,
    debtor_days_h1_change_yoy                DOUBLE,
    inventory_days_h1_change_yoy             DOUBLE,
    segment_period_end                       DATE,            -- B9.1 / B9.2 BUSINESS SEGMENT members, row scope
    segment_count                            INTEGER,
    largest_segment_revenue_share            DOUBLE,
    fastest_growing_segment                  VARCHAR,
    fastest_growing_segment_growth_yoy       DOUBLE,
    largest_segment_margin_change_yoy_pp     DOUBLE,
    -- batch J (related-party leak, G236): features_rpt.py; last FY related-party schedule (Reg. 34) [X113]
    rpt_fy_end                               DATE,            -- FY end of the schedule used (row scope, else the other)
    rpt_counterparties                       INTEGER,         -- outside the group, non-zero FY transactions
    rpt_leak_pct                             DOUBLE,          -- (purchases + loans given + royalties paid) / revenue
    rpt_purchases_to_sales                   DOUBLE,
    rpt_royalty_to_sales                     DOUBLE,
    rpt_loans_given_to_net_worth             DOUBLE,          -- loans given / total equity at the FY end
    -- 18D (disclosure_facts, X116): features_disclosures.py; insider receivables (Reg. 34 trade-receivables note) [X117]
    insider_receivables_as_of                DATE,            -- FY-end instant used (row scope, else the other)
    insider_receivables                      DECIMAL(24,2),   -- due by directors + other officers + their firms / companies
    insider_receivables_to_receivables       DOUBLE,          -- / trade receivables of the same filing and instant
    has_insider_receivables                  BOOLEAN,         -- insider_receivables > 0
    -- 18D: Schedule III additional information per consolidated entity (latest consolidated annual) [X119]
    subsidiary_fy_end                        DATE,
    parent_profit_share                      DOUBLE,          -- parent row's share in profit / consolidated PAT
    largest_subsidiary_profit_share          DOUBLE,          -- largest subsidiary row / consolidated PAT
    largest_subsidiary_name                  VARCHAR,
    consolidated_entities_count              INTEGER,         -- distinct subsidiaries + associates + joint ventures
    -- 20A: audit opinions (features_audit.py, audit_opinions) [X121-X124]; latest visible annual report text / results
    audit_opinion                            VARCHAR,         -- UNMODIFIED | QUALIFIED | ADVERSE | DISCLAIMER (most severe scope)
    audit_opinion_fy_end                     DATE,
    audit_opinion_conflict                   BOOLEAN,         -- report text vs the Reg. 34 checkbox
    going_concern_uncertainty                BOOLEAN,         -- material uncertainty related to going concern (entity / group)
    emphasis_of_matter                       BOOLEAN,         -- informational
    audit_opinion_quarterly                  VARCHAR,         -- latest results filing stating an opinion
    audit_opinion_quarter_end                DATE,
    PRIMARY KEY (security_id, valid_from_date)
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
    restatement_suspected BOOLEAN,           -- X106: a restated quarter inside the TTM window; TTM uses the YTD bridge
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
    roce_screener       DOUBLE,              -- Screener export: (PBT + Interest) x 2 / (opening + closing capital) [S22]
    debtor_days         DOUBLE,              -- Screener export: closing debtors / (sales / 365) [S22]
    inventory_turnover  DOUBLE,              -- Screener export: sales / closing inventory [S22]
    working_capital     DECIMAL(24,2),       -- Screener export: Other Assets - Other Liabilities (rupees) [S22]
    inventory_days      DOUBLE,              -- closing inventory / (COGS / 365); NULL if COGS < 1% of sales [S23]
    days_payable        DOUBLE,              -- closing trade payables / (COGS / 365) [S23]
    cash_conversion_cycle DOUBLE,            -- debtor + inventory - payable days [S23]
    working_capital_days DOUBLE,             -- (CA - cash & bank - current investments - CL) / (sales / 365) [S23]
    vnb_margin          DOUBLE,              -- supplemental_kpis (life insurers), latest period visible at as-of
    embedded_value      DECIMAL(24,2),       -- supplemental_kpis, rupees
    ape_growth          DOUBLE,              -- supplemental_kpis
    gov                 DECIMAL(24,2),       -- supplemental_kpis (new-gen tech): gross order value, rupees
    take_rate           DOUBLE,              -- supplemental_kpis: net take rate
    contribution_margin DOUBLE,              -- supplemental_kpis
    nrr                 DOUBLE,              -- supplemental_kpis: net revenue retention
    cac_payback         DOUBLE,              -- supplemental_kpis: months
    sales_growth_qoq_pct DOUBLE,             -- latest quarter's sales / previous quarter's - 1, same scope book
    profit_growth_qoq_pct DOUBLE,            -- same for COALESCE(owners, PAT) per filing; NULL if the base <= 0
    npm_pct             DOUBLE,              -- TTM owners' profit / sales_ttm (fraction)
    interest_coverage   DOUBLE,              -- TTM (PBT + finance costs) / finance costs; NULL for lenders, insurers
    opm_last_year_pct   DOUBLE,              -- last fiscal year's EBITDA / sales (fraction; was same quarter until 4A)
    dividend_yield_pct  DOUBLE,              -- trailing-365-day accepted cash dividends (today's share basis) / close
    dividend_payout_pct DOUBLE,              -- the same dividends per share / eps_ttm; NULL if EPS <= 0
    promoter_holding_change_qoq_pp DOUBLE,   -- Reg. 31 promoter % now minus the previous quarter end, in pp
    -- batch B (price/technicals): features_price.py; adjusted = x price factors of later accepted share-count / demerger
    -- actions (volume / the same); NULL while a gap freezes the series or the window exceeds the stored bars [C9]
    return_1d           DOUBLE,              -- adjusted close / close 1 bar earlier - 1
    return_1w           DOUBLE,              -- 5 bars
    return_3y           DOUBLE,              -- 756 bars, cumulative (not annualised); NULL until ~Oct 2027
    return_5y           DOUBLE,              -- 1,260 bars, cumulative; NULL until ~Oct 2029
    return_7y           DOUBLE,              -- 1,764 bars, cumulative; NULL until ~Oct 2031
    return_10y          DOUBLE,              -- 2,520 bars, cumulative; NULL until ~Oct 2034
    volume              BIGINT,              -- today's traded quantity as filed (TtlTradgVol)
    volume_1w_avg       DOUBLE,              -- mean adjusted volume, 5 bars
    volume_1m_avg       DOUBLE,              -- 21 bars
    volume_1y_avg       DOUBLE,              -- 252 bars
    high_52w            DECIMAL(18,4),       -- max adjusted close, 252 bars
    low_52w             DECIMAL(18,4),       -- min adjusted close, 252 bars
    dist_52w_low        DOUBLE,              -- adjusted close / low_52w - 1 (>= 0)
    high_since_data_start DECIMAL(18,4),     -- max adjusted close since the first bar (>= 2024-10-01): NOT all-time
    low_since_data_start  DECIMAL(18,4),     -- min adjusted close since the first bar: NOT all-time
    dma50               DECIMAL(18,4),       -- mean adjusted close, 50 bars
    dma200              DECIMAL(18,4),       -- 200 bars
    dma50_prev          DECIMAL(18,4),       -- same, window ending one bar earlier
    dma200_prev         DECIMAL(18,4),
    rsi_14              DOUBLE,              -- Wilder RSI(14) on adjusted closes, seeded at the first bar
    rsi_14_prev         DOUBLE,
    macd                DOUBLE,              -- EMA12 - EMA26 of adjusted closes (EMAs seeded by an SMA)
    macd_signal         DOUBLE,              -- EMA9 of MACD (34 bars)
    macd_prev           DOUBLE,
    macd_signal_prev    DOUBLE,
    atr_14_pct          DOUBLE,              -- Wilder ATR(14) on adjusted H/L/C / adjusted close (fraction)
    rs_nifty500_3m      DOUBLE,              -- stock return - Nifty 500 price-index return over 63 bars (fraction points)
    rs_nifty500_6m      DOUBLE,              -- 126 bars
    rs_nifty500_12m     DOUBLE,              -- 252 bars
    beta_1y_nifty500    DOUBLE,              -- OLS beta of daily log returns vs Nifty 500, 252 returns
    turnover_median_20d DECIMAL(24,2),       -- median daily traded value (TtlTrfVal), 20 bars, rupees
    deliv_pct           DOUBLE,              -- today's deliv_qty / volume (fraction) [P16]
    deliv_pct_avg_20d   DOUBLE,              -- mean daily delivery fraction, 20 bars
    vwap                DECIMAL(18,4),       -- today's turnover / volume (= AVG_PRICE) [P16]
    vwap_20d            DECIMAL(18,4),       -- 20-bar traded value / adjusted volume (today's share basis)
    -- batch A (P&L family)
    sales_latest_quarter                     DECIMAL(24,2),   -- quarter lines, rupees (features_pl)
    sales_preceding_quarter                  DECIMAL(24,2),
    sales_preceding_year_quarter             DECIMAL(24,2),
    operating_profit_latest_quarter          DECIMAL(24,2),
    operating_profit_preceding_quarter       DECIMAL(24,2),
    operating_profit_preceding_year_quarter  DECIMAL(24,2),
    other_income_latest_quarter              DECIMAL(24,2),
    other_income_preceding_quarter           DECIMAL(24,2),
    other_income_preceding_year_quarter      DECIMAL(24,2),
    depreciation_latest_quarter              DECIMAL(24,2),
    depreciation_preceding_quarter           DECIMAL(24,2),
    depreciation_preceding_year_quarter      DECIMAL(24,2),
    ebit_latest_quarter                      DECIMAL(24,2),
    ebit_preceding_quarter                   DECIMAL(24,2),
    ebit_preceding_year_quarter              DECIMAL(24,2),
    interest_latest_quarter                  DECIMAL(24,2),
    interest_preceding_quarter               DECIMAL(24,2),
    interest_preceding_year_quarter          DECIMAL(24,2),
    pbt_latest_quarter                       DECIMAL(24,2),
    pbt_preceding_quarter                    DECIMAL(24,2),
    pbt_preceding_year_quarter               DECIMAL(24,2),
    tax_latest_quarter                       DECIMAL(24,2),
    tax_preceding_quarter                    DECIMAL(24,2),
    tax_preceding_year_quarter               DECIMAL(24,2),
    pat_latest_quarter                       DECIMAL(24,2),
    pat_preceding_quarter                    DECIMAL(24,2),
    pat_preceding_year_quarter               DECIMAL(24,2),
    net_profit_latest_quarter                DECIMAL(24,2),
    net_profit_preceding_quarter             DECIMAL(24,2),
    net_profit_preceding_year_quarter        DECIMAL(24,2),
    exceptional_items_latest_quarter         DECIMAL(24,2),
    exceptional_items_preceding_quarter      DECIMAL(24,2),
    exceptional_items_preceding_year_quarter DECIMAL(24,2),
    sales_2quarters_back                     DECIMAL(24,2),
    sales_3quarters_back                     DECIMAL(24,2),
    operating_profit_2quarters_back          DECIMAL(24,2),
    operating_profit_3quarters_back          DECIMAL(24,2),
    net_profit_2quarters_back                DECIMAL(24,2),
    net_profit_3quarters_back                DECIMAL(24,2),
    sales_last_year                          DECIMAL(24,2),   -- latest FY <= fundamentals_end: filed 12M, else 4 Qs
    sales_preceding_year                     DECIMAL(24,2),
    operating_profit_last_year               DECIMAL(24,2),
    operating_profit_preceding_year          DECIMAL(24,2),
    other_income_last_year                   DECIMAL(24,2),
    other_income_preceding_year              DECIMAL(24,2),
    depreciation_last_year                   DECIMAL(24,2),
    depreciation_preceding_year              DECIMAL(24,2),
    ebit_last_year                           DECIMAL(24,2),
    ebit_preceding_year                      DECIMAL(24,2),
    interest_last_year                       DECIMAL(24,2),
    interest_preceding_year                  DECIMAL(24,2),
    pbt_last_year                            DECIMAL(24,2),
    pbt_preceding_year                       DECIMAL(24,2),
    tax_last_year                            DECIMAL(24,2),
    tax_preceding_year                       DECIMAL(24,2),
    pat_last_year                            DECIMAL(24,2),
    pat_preceding_year                       DECIMAL(24,2),
    net_profit_last_year                     DECIMAL(24,2),
    net_profit_preceding_year                DECIMAL(24,2),
    exceptional_items_last_year              DECIMAL(24,2),
    exceptional_items_preceding_year         DECIMAL(24,2),
    sales_ttm_1y_back                        DECIMAL(24,2),   -- TTM ending fundamentals_end - 12 months
    avg_earnings_5y                          DECIMAL(24,2),   -- mean of N FYs (history-gated, C9)
    avg_earnings_10y                         DECIMAL(24,2),
    avg_ebit_5y                              DECIMAL(24,2),
    avg_ebit_10y                             DECIMAL(24,2),
    eps_latest_quarter                       DECIMAL(18,4),   -- filed EPS x later EPS factors
    eps_preceding_quarter                    DECIMAL(18,4),
    eps_preceding_year_quarter               DECIMAL(18,4),
    eps_last_year                            DECIMAL(18,4),
    eps_preceding_year                       DECIMAL(18,4),
    equity_capital_latest_quarter            DECIMAL(24,2),   -- paid-up, results filing
    equity_capital_preceding_quarter         DECIMAL(24,2),
    equity_capital_preceding_year_quarter    DECIMAL(24,2),
    opm_latest_quarter_pct                   DOUBLE,          -- fractions; GPM only per C6
    opm_preceding_quarter_pct                DOUBLE,
    opm_preceding_year_pct                   DOUBLE,
    npm_latest_quarter_pct                   DOUBLE,
    npm_preceding_quarter_pct                DOUBLE,
    npm_preceding_year_quarter_pct           DOUBLE,
    npm_last_year_pct                        DOUBLE,
    npm_preceding_year_pct                   DOUBLE,
    gpm_latest_quarter_pct                   DOUBLE,
    gpm_last_year_pct                        DOUBLE,
    gpm_preceding_year_pct                   DOUBLE,
    sales_growth_yoy_quarter_pct             DOUBLE,          -- Q / same Q last year - 1; base > 0
    profit_growth_yoy_quarter_pct            DOUBLE,
    operating_profit_growth_yoy_quarter_pct  DOUBLE,
    sales_growth_3y_pct                      DOUBLE,          -- FY CAGR; NULL until base FY in scope
    sales_growth_5y_pct                      DOUBLE,
    sales_growth_7y_pct                      DOUBLE,
    sales_growth_10y_pct                     DOUBLE,
    profit_growth_3y_pct                     DOUBLE,
    profit_growth_5y_pct                     DOUBLE,
    profit_growth_7y_pct                     DOUBLE,
    profit_growth_10y_pct                    DOUBLE,
    operating_profit_growth_3y_pct           DOUBLE,
    operating_profit_growth_5y_pct           DOUBLE,
    operating_profit_growth_7y_pct           DOUBLE,
    operating_profit_growth_10y_pct          DOUBLE,
    eps_growth_3y_pct                        DOUBLE,
    eps_growth_5y_pct                        DOUBLE,
    eps_growth_7y_pct                        DOUBLE,
    eps_growth_10y_pct                       DOUBLE,
    sales_growth_median_5y_pct               DOUBLE,          -- median yearly FY growth (gated)
    sales_growth_median_10y_pct              DOUBLE,
    opm_5y_pct                               DOUBLE,          -- mean FY OPM over 5 / 10 FYs (gated)
    opm_10y_pct                              DOUBLE,
    last_result_date                         DATE,            -- IST, latest quarter first visible
    last_annual_result_date                  DATE,            -- IST, latest FY first visible
    book_value_per_share                     DECIMAL(18,4),   -- owners' equity / shares
    is_trade_to_trade                        BOOLEAN,         -- series BE or BZ
    opm_preceding_year_quarter_pct           DOUBLE,          -- same quarter last year (fraction)
    -- batch C (balance sheet / cash flow): features_bs.py; money in rupees, ratios as fractions, days in days;
    -- unsuffixed BS lines = latest BS, 'preceding year' / 'N years back' = FY ends; NULL for lenders where noted
    debt                                     DECIMAL(24,2),      -- latest BS (bs_as_of): borrowings + leases, absent line = 0 [C23]
    equity_capital                           DECIMAL(24,2),      -- latest BS, rupees
    reserves                                 DECIMAL(24,2),      -- other equity (banks / insurers: reserves and surplus)
    balance_sheet_total                      DECIMAL(24,2),      -- total assets net of DTA/DTL netting (Screener) [S10]
    net_block                                DECIMAL(24,2),      -- PPE + investment property + goodwill + intangibles + ROU
    cwip                                     DECIMAL(24,2),      -- CWIP + intangibles under development
    investments                              DECIMAL(24,2),      -- non-current + current + equity-method
    current_assets                           DECIMAL(24,2),
    current_liabilities                      DECIMAL(24,2),
    lease_liabilities                        DECIMAL(24,2),
    inventory                                DECIMAL(24,2),
    trade_receivables                        DECIMAL(24,2),
    trade_payables                           DECIMAL(24,2),
    cash_equivalents                         DECIMAL(24,2),      -- cash and cash equivalents (BS line)
    gross_block                              DECIMAL(24,2),      -- Reg. 34 PPE schedule at the last FY end [X71]
    accumulated_depreciation                 DECIMAL(24,2),      -- Reg. 34 at the last FY end
    contingent_liabilities                   DECIMAL(24,2),      -- Reg. 34 at the last FY end (excl. commitments) [X73]
    advance_from_customers                   DECIMAL(24,2),      -- Reg. 34 at the last FY end [X73]
    debt_preceding_year                      DECIMAL(24,2),      -- BS at the end of the FY before the last FY
    net_block_preceding_year                 DECIMAL(24,2),
    gross_block_preceding_year               DECIMAL(24,2),
    cwip_preceding_year                      DECIMAL(24,2),
    working_capital_preceding_year           DECIMAL(24,2),      -- Screener: Other Assets - Other Liabilities
    debt_3y_back                             DECIMAL(24,2),      -- last FY end - N years; NULL until in scope (~May 2028)
    debt_5y_back                             DECIMAL(24,2),      -- ~May 2030
    debt_7y_back                             DECIMAL(24,2),      -- ~May 2032
    debt_10y_back                            DECIMAL(24,2),      -- ~May 2035
    net_block_3y_back                        DECIMAL(24,2),
    net_block_5y_back                        DECIMAL(24,2),
    net_block_7y_back                        DECIMAL(24,2),
    net_block_10y_back                       DECIMAL(24,2),
    working_capital_3y_back                  DECIMAL(24,2),
    working_capital_5y_back                  DECIMAL(24,2),
    working_capital_7y_back                  DECIMAL(24,2),
    working_capital_10y_back                 DECIMAL(24,2),
    cash_3y_back                             DECIMAL(24,2),      -- cash-flow-statement cash, FY end - N years (gated)
    cash_5y_back                             DECIMAL(24,2),
    cash_7y_back                             DECIMAL(24,2),
    cfo_last_year                            DECIMAL(24,2),      -- filed 12-month cash flow, last / preceding FY
    cfo_preceding_year                       DECIMAL(24,2),
    cfi_last_year                            DECIMAL(24,2),
    cfi_preceding_year                       DECIMAL(24,2),
    cff_last_year                            DECIMAL(24,2),
    cff_preceding_year                       DECIMAL(24,2),
    net_cash_flow_last_year                  DECIMAL(24,2),      -- after the FX effect on cash [S12]
    net_cash_flow_preceding_year             DECIMAL(24,2),
    cash_beginning_last_year                 DECIMAL(24,2),      -- prior FY-end cash, else cash end - net cash flow
    cash_beginning_preceding_year            DECIMAL(24,2),
    cash_end_last_year                       DECIMAL(24,2),
    cash_end_preceding_year                  DECIMAL(24,2),
    fcf_last_year                            DECIMAL(24,2),      -- CFO - (PPE + intangibles capex)
    fcf_preceding_year                       DECIMAL(24,2),
    fcf_3y                                   DECIMAL(24,2),      -- sum over N FYs; NULL until the oldest FY is in scope (3y ~May 2027)
    fcf_5y                                   DECIMAL(24,2),
    fcf_7y                                   DECIMAL(24,2),
    fcf_10y                                  DECIMAL(24,2),
    cfo_3y                                   DECIMAL(24,2),
    cfo_5y                                   DECIMAL(24,2),
    cfo_7y                                   DECIMAL(24,2),
    cfo_10y                                  DECIMAL(24,2),
    cfi_3y                                   DECIMAL(24,2),
    cfi_5y                                   DECIMAL(24,2),
    cfi_7y                                   DECIMAL(24,2),
    cfi_10y                                  DECIMAL(24,2),
    face_value                               DECIMAL(18,4),      -- INR per share, latest results filing
    book_value_preceding_year                DECIMAL(18,4),      -- owners' equity / Reg. 31 shares, both at that FY end, today's share basis
    book_value_3y_back                       DECIMAL(18,4),      -- gated (~May 2028)
    book_value_5y_back                       DECIMAL(18,4),
    book_value_10y_back                      DECIMAL(18,4),
    graham_number                            DECIMAL(18,4),      -- sqrt(22.5 x EPS TTM x book value per share)
    shares_preceding_year                    BIGINT,             -- Reg. 31 total a year before the latest SHP, today's basis
    shares_10y_back                          BIGINT,             -- gated (~Apr 2035)
    current_ratio                            DOUBLE,             -- current assets / current liabilities (latest BS)
    quick_ratio                              DOUBLE,             -- (current assets - inventory) / current liabilities
    net_debt_to_equity                       DOUBLE,             -- net_debt / total equity
    long_term_debt_to_equity                 DOUBLE,             -- (non-current borrowings + leases) / total equity
    debt_to_equity_preceding_year            DOUBLE,             -- debt / total equity at the preceding FY end
    financial_leverage                       DOUBLE,             -- avg total assets / avg owners' equity (12 months to bs_as_of)
    asset_turnover                           DOUBLE,             -- TTM sales to bs_as_of / avg total assets
    earning_power                            DOUBLE,             -- TTM EBIT / total assets
    roe_preceding_year                       DOUBLE,             -- FY-1 owners' profit / owners' equity at FY-1 end
    roce_preceding_year                      DOUBLE,             -- FY-1 EBIT / (debt + total equity) at FY-1 end
    roa_preceding_year                       DOUBLE,             -- FY-1 owners' profit / avg total assets (needs FY-2 BS)
    exports_pct                              DOUBLE,             -- foreign / (domestic + foreign) revenue, Reg. 34 [X75]
    exports_pct_3y_back                      DOUBLE,             -- gated (~Sep 2028)
    exports_pct_5y_back                      DOUBLE,
    inventory_turnover_3y_back               DOUBLE,             -- Screener convention, FY N years back (gated)
    inventory_turnover_5y_back               DOUBLE,
    inventory_turnover_7y_back               DOUBLE,
    inventory_turnover_10y_back              DOUBLE,
    debtor_days_3y_back                      DOUBLE,             -- gated (~May 2028)
    debtor_days_5y_back                      DOUBLE,
    avg_debtor_days_3y                       DOUBLE,             -- mean of 3 FYs (gated, ~May 2027)
    avg_working_capital_days_3y              DOUBLE,             -- mean of 3 FYs (gated, ~May 2027)
    cfo_to_ebitda_last_year                  DOUBLE,             -- FY CFO / FY EBITDA
    cfo_to_ebitda_preceding_year             DOUBLE,
    fcf_conversion_3y                        DOUBLE,             -- 3-FY FCF / 3-FY owners' profit (G224, gated)
    cfo_to_ebitda_3y                         DOUBLE,             -- 3-FY CFO / 3-FY EBITDA (G223, gated)
    net_debt_to_fcf_3y                       DOUBLE,             -- net_debt / mean 3-FY FCF > 0 (G233, gated)
    price_to_fcf                             DOUBLE,             -- market cap / fcf_ttm; NULL when FCF <= 0
    equity_fcf_yield                         DOUBLE,             -- fcf_ttm / market cap (G170, signed)
    shareholder_yield                        DOUBLE,             -- TTM (dividends + buybacks - share issues) cash / mcap (G316)
    buyback_yield                            DOUBLE,             -- TTM buyback cash / market cap
    dilution_1y                              DOUBLE,             -- Reg. 31 shares now / a year earlier - 1 (today's basis)
    dilution_5y                              DOUBLE,             -- G219: same, 5 years (gated, ~Apr 2030)
    reinvestment_rate                        DOUBLE,             -- FY (capex - D&A + change in non-cash WC) / NOPAT (G216)
    incremental_roic_1y                      DOUBLE,             -- FY change in NOPAT / change in invested capital
    incremental_roic_3y                      DOUBLE,             -- G215, gated (~May 2028)
    incremental_roic_5y                      DOUBLE,             -- G215, gated (~May 2030)
    net_debt_to_ebitda                       DOUBLE,             -- net_debt / ebitda_ttm (> 0)
    ev_ebitda_percentile_20q                 DOUBLE,             -- G240: rank vs the last 20 quarter-ends (C9: ~2031)
    -- batch D (ownership / hidden gems): features_gems.py; fractions like other _pct columns
    fii_holding_change_qoq_pct               DOUBLE,          -- Reg. 31 FII (Institutions Foreign) now - previous quarter end (fraction points)
    dii_holding_change_qoq_pct               DOUBLE,          -- same for DII; NULL unless the two latest are adjacent quarters [SHP14]
    inst_holding_pct                         DOUBLE,          -- FII + DII (fraction)
    unpledged_promoter_holding_pct           DOUBLE,          -- promoter pct x (1 - pledge of promoter shares)
    mf_holding_pct                           DOUBLE,          -- Reg. 31 mutual funds / UTI (fraction)
    mf_holding_change_qoq_pct                DOUBLE,          -- adjacent quarters (fraction points)
    insurance_holding_pct                    DOUBLE,          -- InsuranceCompaniesMember line item [SHP19]
    retail_holding_pct                       DOUBLE,          -- resident individuals up to Rs 2 lakh nominal capital [SHP19]
    num_shareholders                         BIGINT,          -- TOTAL NumberOfShareholders, latest visible pattern [SHP19]
    num_shareholders_preceding_quarter       BIGINT,          -- adjacent previous quarter end
    num_shareholders_change_qoq_pct          DOUBLE,          -- growth vs the preceding quarter (fraction)
    num_shareholders_1y_back                 BIGINT,          -- pattern exactly 12 months before the latest
    sales_growth_yoy_preceding_quarter_pct   DOUBLE,          -- preceding quarter vs the same quarter a year earlier
    profit_growth_yoy_preceding_quarter_pct  DOUBLE,          -- same for owners' profit; NULL if the base <= 0
    core_profit_latest_quarter               DECIMAL(24,2),   -- PBT - other income - exceptional items, rupees
    core_profit_yoy_latest_q                 DOUBLE,          -- core profit YoY, latest quarter; NULL if the base <= 0 or lender
    core_profit_yoy_preceding_q              DOUBLE,          -- same, preceding quarter
    other_income_lift_pp                     DOUBLE,          -- profit YoY - core profit YoY, latest quarter (fraction points)
    pe_core                                  DOUBLE,          -- market cap / TTM core profit after TTM tax, owners' share
    growth_sustained                         BOOLEAN,         -- sales YoY >= 12% in both latest and preceding quarter
    growth_acceleration_pp                   DOUBLE,          -- sales YoY latest - preceding quarter (fraction points)
    opm_change_yoy_pp                        DOUBLE,          -- quarter OPM - same quarter last year (fraction points)
    operating_leverage                       DOUBLE,          -- core profit YoY / sales YoY, latest quarter; NULL if sales YoY <= 0
    peg                                      DOUBLE,          -- pe_core / (100 x core growth): quarter YoY, TTM YoY once 8 quarters exist
    earnings_yield                           DOUBLE,          -- TTM EBIT / EV; NULL if EV <= 0 or lender
    industry                                 VARCHAR,         -- Nifty 500 snapshot industry (latest on/before as-of listing the ISIN)
    cyclical_flag                            BOOLEAN,         -- industry in the cyclical set or reference/cyclical_symbols.csv
    under_owned                              BOOLEAN,         -- inst <= 15% and promoter >= 50% and pledge = 0
    forensic_clean                           BOOLEAN,         -- no measured red flag (features_gems.forensic_clean)
    cash_conversion_ok                       BOOLEAN,         -- CFO / EBITDA >= 0.7
    capex_pay_off_signal                     BOOLEAN,         -- CWIP / gross block >= 25% and capex / D&A >= 2 and D/E <= 1
    roce_stability_5y                        DOUBLE,          -- 1 - std / mean of 5 FY ROCE (gated, C9)
    opm_stability_5y                         DOUBLE,          -- 1 - std / mean of 5 FY OPM (gated, C9)
    pe_vs_own_5y_median                      DOUBLE,          -- PE / own 5-year median daily PE (gated, C9)
    magic_formula_rank                       INTEGER,         -- EY rank + ROCE rank position in the gated non-financial universe (1 = best)
    pe_core_universe_median                  DOUBLE,          -- median pe_core of the day's gated non-financial universe
    market_cap_universe_median               DECIMAL(24,2),   -- median market cap of the same universe, rupees
    gem_score                                DOUBLE,          -- weighted clipped z-score blend (hidden_gems.md), non-cyclical universe
    hat_hidden_compounder                    BOOLEAN,         -- hidden_gems.md section B screen
    hat_quality_fair_price                   BOOLEAN,
    hat_magic_formula                        BOOLEAN,
    hat_garp                                 BOOLEAN,
    hat_turnaround                           BOOLEAN,
    hat_under_owned                          BOOLEAN,
    hat_cash_machine                         BOOLEAN,
    hat_fallen_quality                       BOOLEAN,
    hat_capex_pay_off                        BOOLEAN,
    hat_cyclical                             BOOLEAN,
    hat_lender                               BOOLEAN,
    hats_passed                              INTEGER,         -- count of hat_* TRUE
    -- batch H (industry / peers): features_peers.py; NSE 4-level classification [IC1-IC3], visible from its first fetch
    nse_macro_sector                         VARCHAR,         -- NSE macro-economic sector (quote API secInfo.macro), PIT
    nse_sector                               VARCHAR,         -- NSE sector (secInfo.sector)
    nse_industry                             VARCHAR,         -- NSE industry (secInfo.industryInfo)
    nse_basic_industry                       VARCHAR,         -- NSE basic industry (secInfo.basicIndustry)
    industry_pe_median                       DOUBLE,          -- median PE (> 0) of the day's companies in nse_industry (>= 3 values)
    industry_pb_median                       DOUBLE,          -- same for PB (> 0)
    industry_roce_median                     DOUBLE,          -- same for ROCE (fraction)
    industry_sales_growth_median             DOUBLE,          -- same for sales_growth_yoy (fraction)
    basic_industry_pe_median                 DOUBLE,          -- the four medians within nse_basic_industry
    basic_industry_pb_median                 DOUBLE,
    basic_industry_roce_median               DOUBLE,
    basic_industry_sales_growth_median       DOUBLE,
    pe_premium_to_industry                   DOUBLE,          -- pe / industry_pe_median - 1 (negative = discount)
    pb_premium_to_industry                   DOUBLE,          -- pb / industry_pb_median - 1
    pe_premium_to_basic_industry             DOUBLE,          -- pe / basic_industry_pe_median - 1 (G199)
    pb_premium_to_basic_industry             DOUBLE,          -- pb / basic_industry_pb_median - 1
    peer_count                               INTEGER,         -- companies in nse_basic_industry on the day (incl. itself)
    peer_rank_market_cap                     INTEGER,         -- 1 = largest market cap in nse_basic_industry (G112)
    peer_rank_pe                             INTEGER,         -- 1 = lowest PE (> 0)
    peer_rank_roce                           INTEGER,         -- 1 = highest ROCE
    peer_rank_profit_growth                  INTEGER,         -- 1 = highest profit_growth_yoy_quarter_pct
    industry_group_pe_median                 DOUBLE,          -- fallback: medians over the Nifty 500 file's `industry` (never mixed with NSE levels)
    industry_group_pb_median                 DOUBLE,
    industry_group_roce_median               DOUBLE,
    industry_group_sales_growth_median       DOUBLE,
    pe_premium_to_industry_group             DOUBLE,          -- pe / industry_group_pe_median - 1
    pb_premium_to_industry_group             DOUBLE,          -- pb / industry_group_pb_median - 1
    -- batch G (remaining Phase 2 ratios): features_extra.py; fractions like other _pct columns, money in rupees
    opm_acceleration_pp                      DOUBLE,          -- [OPM(Q) - OPM(Q-4)] - [OPM(Q-1) - OPM(Q-5)] (G152)
    gpm_change_yoy_pp                        DOUBLE,          -- quarter GPM - same quarter last year, C6 guard (G257)
    profit_growth_acceleration_pp            DOUBLE,          -- owners' profit YoY latest - preceding quarter (B4.6)
    sales_growth_streak_quarters             INTEGER,         -- consecutive quarters with sales YoY > 0, newest first (B4.8)
    profit_growth_streak_quarters            INTEGER,         -- same for owners' profit
    material_cost_latest_quarter_pct         DOUBLE,          -- (materials + purchases + inventory change) / sales (G133, B3.4)
    material_cost_last_year_pct              DOUBLE,
    employee_cost_latest_quarter_pct         DOUBLE,
    employee_cost_last_year_pct              DOUBLE,
    other_expenses_latest_quarter_pct        DOUBLE,
    other_expenses_last_year_pct             DOUBLE,
    power_fuel_latest_quarter_pct            DOUBLE,          -- labelled power & fuel / sales [X50]; NULL when not labelled
    power_fuel_last_year_pct                 DOUBLE,
    freight_latest_quarter_pct               DOUBLE,          -- labelled freight / sales [X50]
    freight_last_year_pct                    DOUBLE,
    ad_promo_latest_quarter_pct              DOUBLE,          -- advertising & promotion / sales, A&P intensity [X68] (G258)
    ad_promo_last_year_pct                   DOUBLE,          -- same on the last FY (Reg. 34 element [X74])
    marketing_efficiency_latest_quarter      DOUBLE,          -- sales change YoY / A&P of the quarter a year earlier (G256)
    marketing_efficiency_last_year           DOUBLE,          -- FY sales change / preceding FY A&P
    material_cost_last_year                  DECIMAL(24,2),   -- rupees, fiscal-year lines (A4.16-A4.19)
    material_cost_preceding_year             DECIMAL(24,2),
    employee_cost_last_year                  DECIMAL(24,2),
    employee_cost_preceding_year             DECIMAL(24,2),
    minority_share_last_year                 DECIMAL(24,2),
    minority_share_preceding_year            DECIMAL(24,2),
    dividends_paid_last_year                 DECIMAL(24,2),   -- cash-flow dividends paid; nil when the FY cash flow omits the line
    dividends_paid_preceding_year            DECIMAL(24,2),
    acquisition_outflow_last_year            DECIMAL(24,2),   -- CF obtaining control of subsidiaries / businesses, FY (G276)
    acquisition_outflow_preceding_year       DECIMAL(24,2),
    acquisition_outflow_to_sales_last_year   DOUBLE,          -- the same / FY sales
    inorganic_growth_flag                    BOOLEAN,         -- acquisitions >= 5% of sales in either of the last two FYs [C26]
    standalone_pat_ttm                       DECIMAL(24,2),   -- standalone TTM PAT (G278 input)
    profit_leakage_pct                       DOUBLE,          -- 1 - consolidated owners' TTM profit / standalone TTM PAT (G278)
    profit_leakage_latest_quarter_pct        DOUBLE,          -- same on the latest quarter
    incremental_asset_turnover_3y            DOUBLE,          -- FY sales change / net block change over 3 FYs (G220, C9 gated)
    cfo_to_pat                               DOUBLE,          -- cash-flow window CFO / PAT (B1.8)
    cash_tax_rate                            DOUBLE,          -- taxes paid / tax expense, cash-flow window (B1.11)
    effective_tax_rate                       DOUBLE,          -- TTM tax / TTM PBT, not clamped (B1.12)
    exceptional_to_pbt                       DOUBLE,          -- TTM exceptional items / PBT (B1.14)
    exceptional_quarters_4q                  INTEGER,         -- last 4 quarters with exceptional items != 0
    capex_intensity                          DOUBLE,          -- capex / sales, cash-flow window (B2.11)
    net_cash_to_market_cap                   DOUBLE,          -- -(net debt) / market cap (B2.17)
    rpt_to_sales                             DOUBLE,          -- RPT total / sales of the same period (B1.19; G236 split blocked)
    intangibles_to_equity                    DOUBLE,          -- (goodwill + other intangibles) / owners' equity (B1.23)
    audit_fees_to_sales                      DOUBLE,          -- Reg. 34 last FY (B1.20)
    managerial_remuneration_to_pat           DOUBLE,          -- Reg. 34 last FY (B1.20)
    capital_commitments_to_net_worth         DOUBLE,          -- Reg. 34 last FY end (B1.22)
    unquoted_investments                     DECIMAL(24,2),   -- book value, non-current + current, last FY end (A6.12)
    quoted_investments_market_value          DECIMAL(24,2),   -- market value, non-current + current (A6.13)
    revaluation_reserve                      DECIMAL(24,2),   -- PPE revaluation surplus (A6.14)
    price_to_sales                           DOUBLE,          -- market cap / sales_ttm (A1.7)
    ev_to_sales                              DOUBLE,          -- EV / sales_ttm (B5.6)
    price_to_embedded_value                  DOUBLE,          -- market cap / embedded value KPI (G270)
    gov_ttm                                  DECIMAL(24,2),   -- TTM gross order value KPI, rupees (12M period or 4 quarters)
    ev_to_gov                                DOUBLE,          -- EV / gov_ttm (G265)
    gov_growth_yoy_pct                       DOUBLE,          -- latest KPI period vs the same period a year earlier
    arpu                                     DECIMAL(24,2),   -- KPI, rupees per user, latest period (G266)
    arpu_growth_yoy_pct                      DOUBLE,          -- YoY, same-length period
    mtu                                      BIGINT,          -- KPI, monthly transacting users, latest period (G266)
    mtu_growth_yoy_pct                       DOUBLE,          -- YoY, same-length period
    contribution_margin_change_yoy_pp        DOUBLE,          -- KPI contribution margin YoY change (G257)
    casa_pct                                 DOUBLE,          -- banks, KPI (master backlog M4)
    inst_shares_change_qoq                   BIGINT,          -- FII + DII shares, adjacent Reg. 31 quarters
    volume_median_90d                        DOUBLE,          -- median daily volume, 90 calendar days
    institutional_absorption_90d             DOUBLE,          -- inst_shares_change_qoq / volume_median_90d, days (G241)
    promoter_pledge_change_qoq_pp            DOUBLE,          -- pledged / promoter shares QoQ (B7.4)
    public_holders_above_1pct                INTEGER,         -- named public holders > 1%, latest Reg. 31 (B7.6)
    litigations_90d                          INTEGER,         -- Reg. 30 LITIGATION disclosures in 90 days (B8.3)
    allotments_90d                           INTEGER,         -- Reg. 30 ALLOTMENT records (B8.2)
    fund_raising_events_90d                  INTEGER,         -- Reg. 30 FUND_RAISING family
    rf_auditor_resignation_90d               BOOLEAN,         -- red flags (G117): separate columns, never summed
    rf_kmp_resignations_90d                  BOOLEAN,         -- >= 2 KMP / director resignations in 90 days
    rf_fraud_or_default_90d                  BOOLEAN,
    rf_litigation_90d                        BOOLEAN,
    rf_audit_qualified                       BOOLEAN,         -- latest annual report text / results opinion modified [X121] (B1.16)
    rf_pledge_increase_qoq                   BOOLEAN,         -- promoter_pledge_change_qoq_pp > 0
    pe_numerator                             DECIMAL(24,2),   -- G244 raw inputs: market cap
    pe_denominator                           DECIMAL(24,2),   -- continuing owners' TTM profit
    roe_numerator                            DECIMAL(24,2),   -- owners' TTM profit
    roe_denominator                          DECIMAL(24,2),   -- owners' equity
    roce_numerator                           DECIMAL(24,2),   -- TTM EBIT
    roce_denominator                         DECIMAL(24,2),   -- total equity + debt
    ev_ebitda_numerator                      DECIMAL(24,2),   -- EV
    ev_ebitda_denominator                    DECIMAL(24,2),   -- TTM EBITDA
    opm_numerator                            DECIMAL(24,2),   -- TTM EBITDA
    opm_denominator                          DECIMAL(24,2),   -- sales_ttm
    -- batch I (last catalogue rows): features_more.py; fractions like other _pct columns, days as DOUBLE
    beneish_dsri                             DOUBLE,          -- B1.2 Beneish indices, last FY vs preceding FY (inputs of beneish_m)
    beneish_gmi                              DOUBLE,
    beneish_aqi                              DOUBLE,
    beneish_sgi                              DOUBLE,
    beneish_depi                             DOUBLE,
    beneish_sgai                             DOUBLE,
    beneish_lvgi                             DOUBLE,
    beneish_tata                             DOUBLE,
    piotroski_roa_positive                   BOOLEAN,         -- B1.3 Piotroski tests (inputs of piotroski_f), all or none
    piotroski_cfo_positive                   BOOLEAN,
    piotroski_roa_up                         BOOLEAN,
    piotroski_cfo_above_pat                  BOOLEAN,
    piotroski_leverage_down                  BOOLEAN,
    piotroski_current_ratio_up               BOOLEAN,
    piotroski_no_dilution                    BOOLEAN,
    piotroski_gross_margin_up                BOOLEAN,
    piotroski_asset_turnover_up              BOOLEAN,
    altman_z_original                        DOUBLE,          -- B1.5 original Z, manufacturers (C6 guard), MVE = market cap
    bs_accruals                              DOUBLE,          -- B1.7 change in NOA / avg total assets, last FY
    depreciation_rate                        DOUBLE,          -- B2.12 FY D&A / avg gross block (Reg. 34)
    asset_age_proxy                          DOUBLE,          -- B2.12 accumulated depreciation / gross block
    debtor_days_change_yoy                   DOUBLE,          -- B3.2 last FY - preceding FY, days
    ccc_change_yoy                           DOUBLE,
    h1_bs_as_of                              DATE,            -- B3.3 latest non-FY-end balance sheet (12 months)
    debtor_days_h1                           DOUBLE,
    inventory_days_h1                        DOUBLE,
    debtor_days_h1_change_yoy                DOUBLE,
    inventory_days_h1_change_yoy             DOUBLE,
    pb_percentile                            DOUBLE,          -- B5.2 / B5.3 vs own prior quarter-ends [C20], >= 4
    price_to_sales_percentile                DOUBLE,
    ev_to_sales_percentile                   DOUBLE,
    momentum_12m_1m                          DOUBLE,          -- B6.3 (1 + return_12m) / (1 + return_1m) - 1
    volatility_1y                            DOUBLE,          -- B6.4 annualised std of 252 daily log returns
    max_drawdown_1y                          DOUBLE,
    high_52w_on_delivery_spike               BOOLEAN,         -- B6.11 / G283 52W high with delivery > 2x 20D median
    pead_event_date                          DATE,            -- B6.14 / G151 latest results broadcast (IST)
    pead_ar_t0                               DOUBLE,          -- stock - Nifty 500 return since the pre-results close
    pead_ar_t1                               DOUBLE,
    pead_ar_t5                               DOUBLE,
    pead_ar_t20                              DOUBLE,
    pead_relvol_t0                           DOUBLE,          -- volume / mean of the 20 bars before T+0
    pead_relvol_t1                           DOUBLE,
    pead_relvol_t5                           DOUBLE,
    pead_relvol_t20                          DOUBLE,
    nifty500_inclusion_90d                   BOOLEAN,         -- B8.4 NULL until stored history covers 90 days
    nifty500_exclusion_90d                   BOOLEAN,
    days_to_next_ex_date                     INTEGER,         -- B8.5 announced (visible) actions only
    next_ex_date_action                      VARCHAR,
    dividend_365d                            BOOLEAN,         -- NULL while the window starts before C9
    bonus_365d                               BOOLEAN,
    split_365d                               BOOLEAN,
    segment_period_end                       DATE,            -- B9.1 / B9.2 BUSINESS SEGMENT members, row scope
    segment_count                            INTEGER,
    largest_segment_revenue_share            DOUBLE,
    fastest_growing_segment                  VARCHAR,
    fastest_growing_segment_growth_yoy       DOUBLE,
    largest_segment_margin_change_yoy_pp     DOUBLE,
    rs_rank_12m_1m                           DOUBLE,          -- cross-section (refresh step): 1 = strongest
    industry_earnings_breadth                DOUBLE,          -- B4.9 / G205 share of NSE industry with core profit YoY > 0
    industry_earnings_breadth_n              INTEGER,         -- companies measured (latest quarter of the industry)
    -- batch J (related-party leak, G236): features_rpt.py; last FY related-party schedule (Reg. 34) [X113]
    rpt_fy_end                               DATE,            -- FY end of the schedule used (row scope, else the other)
    rpt_counterparties                       INTEGER,         -- outside the group, non-zero FY transactions
    rpt_leak_pct                             DOUBLE,          -- (purchases + loans given + royalties paid) / revenue
    rpt_purchases_to_sales                   DOUBLE,
    rpt_royalty_to_sales                     DOUBLE,
    rpt_loans_given_to_net_worth             DOUBLE,          -- loans given / total equity at the FY end
    -- 18D (disclosure_facts, X116): features_disclosures.py; insider receivables (Reg. 34 trade-receivables note) [X117]
    insider_receivables_as_of                DATE,            -- FY-end instant used (row scope, else the other)
    insider_receivables                      DECIMAL(24,2),   -- due by directors + other officers + their firms / companies
    insider_receivables_to_receivables       DOUBLE,          -- / trade receivables of the same filing and instant
    has_insider_receivables                  BOOLEAN,         -- insider_receivables > 0
    -- 18D: Reg. 31 declarations of the latest visible shareholding filing (entity-level element) [X118]
    has_warrants                             BOOLEAN,
    has_convertibles                         BOOLEAN,
    has_partly_paid                          BOOLEAN,
    has_locked_in                            BOOLEAN,
    has_dvr_shares                           BOOLEAN,         -- equity shares with differential voting rights
    has_sbo                                  BOOLEAN,         -- any significant beneficial owner
    is_psu                                   BOOLEAN,         -- public sector undertaking
    -- 18D: Schedule III additional information per consolidated entity (latest consolidated annual) [X119]
    subsidiary_fy_end                        DATE,
    parent_profit_share                      DOUBLE,          -- parent row's share in profit / consolidated PAT
    largest_subsidiary_profit_share          DOUBLE,          -- largest subsidiary row / consolidated PAT
    largest_subsidiary_name                  VARCHAR,
    consolidated_entities_count              INTEGER,         -- distinct subsidiaries + associates + joint ventures
    -- 20A: audit opinions (features_audit.py, audit_opinions) [X121-X124]; latest visible annual report text / results
    audit_opinion                            VARCHAR,         -- UNMODIFIED | QUALIFIED | ADVERSE | DISCLAIMER (most severe scope)
    audit_opinion_fy_end                     DATE,
    audit_opinion_conflict                   BOOLEAN,         -- report text vs the Reg. 34 checkbox
    going_concern_uncertainty                BOOLEAN,         -- material uncertainty related to going concern (entity / group)
    emphasis_of_matter                       BOOLEAN,         -- informational
    audit_opinion_quarterly                  VARCHAR,         -- latest results filing stating an opinion
    audit_opinion_quarter_end                DATE,
    PRIMARY KEY (as_of_date, security_id)
);

-- Market breadth per materialised day (G208): from the day's screener_features_history rows with in_nifty500,
-- refreshed inside the materialize transaction (features_price.refresh_breadth).
CREATE TABLE IF NOT EXISTS market_breadth (
    as_of_date          DATE    NOT NULL,
    universe            VARCHAR NOT NULL,    -- NIFTY 500
    members             INTEGER,             -- rows with in_nifty500 on the day
    pct_above_dma50     DOUBLE,              -- share with price_to_dma50 > 1, of members with a value
    pct_above_dma200    DOUBLE,
    new_52w_highs       INTEGER,             -- dist_52w_high = 0 (close is the 252-bar high)
    new_52w_lows        INTEGER,             -- dist_52w_low = 0
    high_low_ratio      DOUBLE,              -- new highs / new lows; NULL without a new low
    advances            INTEGER,             -- return_1d > 0
    declines            INTEGER,             -- return_1d < 0
    unchanged           INTEGER,             -- return_1d = 0
    ad_ratio            DOUBLE,              -- advances / declines; NULL without a decline
    PRIMARY KEY (as_of_date, universe)
);

CREATE TABLE IF NOT EXISTS user_custom_ratios (
    name        VARCHAR PRIMARY KEY,            -- alias usable in screens
    expression  VARCHAR NOT NULL,               -- DSL arithmetic over aliases / other custom ratios
    created_at  TIMESTAMP NOT NULL
);

-- Audited administrative operations (rebuild-market, reprocess): one row per run, never updated.
CREATE TABLE IF NOT EXISTS admin_log (
    admin_id    VARCHAR PRIMARY KEY,
    action      VARCHAR NOT NULL,
    params      JSON NOT NULL,
    result      JSON,
    note        VARCHAR,
    created_at  TIMESTAMP NOT NULL
);

-- Filing-level overrides from `quarantine resolve --action OVERRIDE` (whitelisted fields, read by the promoter).
CREATE TABLE IF NOT EXISTS filing_overrides (
    override_id    VARCHAR PRIMARY KEY,
    filing_id      VARCHAR NOT NULL,
    field          VARCHAR NOT NULL,              -- broadcast_ts | security_id
    value          VARCHAR NOT NULL,
    quarantine_id  VARCHAR,
    reason         VARCHAR NOT NULL,
    created_at     TIMESTAMP NOT NULL
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
                                             -- | gov | take_rate | contribution_margin | nrr | cac_payback | arpu | mtu | casa_pct
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

-- Incremental materialisation (architecture §11.10). A work queue, not data: written only by the single writers
-- (promoter.py, admin.py) in the same transaction as the change it describes, consumed by `materialize
-- --incremental` (rows deleted, or moved forward, only after a successful run). One row = "materialised rows of
-- this entity on as_of_date >= from_date may be stale". entity_id '*' marks every entity (FULL).
CREATE TABLE IF NOT EXISTS materialize_dirty (
    dirty_id    VARCHAR PRIMARY KEY,         -- stable_id(entity_id, from_date, reason, source_id)
    entity_id   VARCHAR NOT NULL,            -- entity_master.entity_id, or '*' = every entity
    from_date   DATE    NOT NULL,            -- first as_of_date that may be affected (IST calendar date)
    reason      VARCHAR NOT NULL,            -- RESULTS | SHAREHOLDING | REG30_EVENT | KPI | MARKET_DAY | ...
    source_id   VARCHAR NOT NULL,            -- filing_id / quarantine_id / stage path / '' when none
    created_at  TIMESTAMP NOT NULL
);

-- Reader version of each materialised day (features.FEATURES_VERSION); `materialize --incremental` refuses when
-- any materialised day was built by another version (or by code that predates this table).
CREATE TABLE IF NOT EXISTS features_meta (
    as_of_date        DATE PRIMARY KEY,
    features_version  VARCHAR NOT NULL,
    mode              VARCHAR NOT NULL,      -- FULL | INCREMENTAL (how the day was last published)
    row_count         INTEGER NOT NULL,
    materialized_at   TIMESTAMP NOT NULL
);

-- ── batch H: industry classification (NSE quote API) and AOC-1 group structure ─────────────────────
-- Raw: one row per fetched quote answer, exactly as sent [IC1]. Append-only.
CREATE TABLE IF NOT EXISTS raw_quote_classification (
    filing_id        VARCHAR NOT NULL REFERENCES filings(filing_id),
    symbol           VARCHAR NOT NULL,
    series           VARCHAR NOT NULL,
    isin             VARCHAR NOT NULL,
    company_name     VARCHAR,
    macro            VARCHAR,                -- secInfo.macro
    sector           VARCHAR,                -- secInfo.sector
    industry         VARCHAR,                -- secInfo.industryInfo
    basic_industry   VARCHAR,                -- secInfo.basicIndustry
    quote_update_ts  TIMESTAMP,              -- lastUpdateTime (IST in the answer), UTC
    observed_date    DATE NOT NULL,          -- IST date of the fetch
    PRIMARY KEY (filing_id)
);

-- L2: date-bounded classification per entity (promoter._promote_classification). NSE gives no effective date
-- [IC3]: an interval starts on the IST date it was first observed and is visible from that fetch; a changed answer
-- closes the open interval (valid_to, exclusive) and opens a new one. PIT read: valid_from <= as_of AND (valid_to
-- IS NULL OR valid_to > as_of) AND visible_from_ts <= as_of_ts. Never backdated.
CREATE TABLE IF NOT EXISTS entity_classification_history (
    entity_id           VARCHAR NOT NULL REFERENCES entity_master(entity_id),
    source              VARCHAR NOT NULL,       -- NSE_QUOTE
    macro               VARCHAR,
    sector              VARCHAR,
    industry            VARCHAR,
    basic_industry      VARCHAR,
    valid_from          DATE NOT NULL,
    valid_to            DATE,                   -- exclusive; NULL = current
    visible_from_ts     TIMESTAMP NOT NULL,
    evidence_filing_id  VARCHAR NOT NULL REFERENCES filings(filing_id),
    PRIMARY KEY (entity_id, source, valid_from)
);

-- Reg. 34 AOC-1 schedule (parsers/aoc1.py) [X112]: one row per subsidiary / associate / JV row of a fiscal year in an
-- annual filing, promoted with its filing (same entity, scope, visibility). row_member is a row position inside the
-- year, not an identity across years. Never feeds fact_observations or a ratio.
CREATE TABLE IF NOT EXISTS group_structure (
    filing_id         VARCHAR NOT NULL REFERENCES filings(filing_id),
    parser_version    VARCHAR NOT NULL,          -- parsers.aoc1.AOC1_PARSER_VERSION
    entity_id         VARCHAR NOT NULL REFERENCES entity_master(entity_id),   -- the filer (parent)
    scope             VARCHAR NOT NULL,
    relation          VARCHAR NOT NULL,          -- SUBSIDIARY | ASSOCIATE | JOINT_VENTURE
    row_member        VARCHAR NOT NULL,          -- typed axis member as filed
    period_end        DATE NOT NULL,             -- fiscal year end of the row
    name              VARCHAR NOT NULL,
    cin               VARCHAR,
    country           VARCHAR,
    holding_as_filed  VARCHAR,
    holding_fraction  DECIMAL(9,6),              -- 0..1; NULL when the filed value is outside 0..1
    net_worth_inr     DECIMAL(20,2),
    turnover_inr      DECIMAL(20,2),
    pat_inr           DECIMAL(20,2),
    investment_inr    DECIMAL(20,2),
    visible_from_ts   TIMESTAMP NOT NULL,
    PRIMARY KEY (filing_id, parser_version, relation, row_member, period_end),
    CHECK (relation IN ('SUBSIDIARY', 'ASSOCIATE', 'JOINT_VENTURE')),
    CHECK (holding_fraction IS NULL OR (holding_fraction >= 0 AND holding_fraction <= 1))
);
-- Reg. 34 related-party schedule (parsers/rpt.py) [X113]: one row per related party x category x transaction element
-- x in-scope period of an annual filing, promoted with its filing (same entity, scope, visibility). row_member is a
-- row position inside the filing, not an identity. Feeds only the batch J RPT columns (features_rpt.py).
CREATE TABLE IF NOT EXISTS related_party_transactions (
    filing_id         VARCHAR NOT NULL REFERENCES filings(filing_id),
    parser_version    VARCHAR NOT NULL,          -- parsers.rpt.RPT_PARSER_VERSION
    entity_id         VARCHAR NOT NULL REFERENCES entity_master(entity_id),   -- the filer
    scope             VARCHAR NOT NULL,
    row_member        VARCHAR NOT NULL,          -- typed RelatedPartyAxis member as filed
    category_member   VARCHAR NOT NULL,          -- CategoriesOfRelatedPartiesAxis member as filed (local name)
    category          VARCHAR NOT NULL,          -- SUBSIDIARY | ASSOCIATE | JOINT_VENTURE | KMP | PROMOTER_GROUP | OTHER
    period_type       VARCHAR NOT NULL,          -- DURATION (transactions) | INSTANT (year-end balances)
    period_start      DATE NOT NULL,
    period_end        DATE NOT NULL,
    counterparty_name VARCHAR NOT NULL,
    pan               VARCHAR,
    cin               VARCHAR,
    country           VARCHAR,
    relationship      VARCHAR,                   -- DescriptionOfNatureOfRelatedPartyRelationship as filed
    nature            VARCHAR,                   -- DescriptionOfNatureOfTransactionsWithRelatedParty as filed
    txn_type          VARCHAR NOT NULL,          -- parsers.rpt.TXN_TYPES | balance_payable | balance_receivable
    source_element    VARCHAR NOT NULL,
    amount_inr        DECIMAL(20,2) NOT NULL,
    visible_from_ts   TIMESTAMP NOT NULL,
    PRIMARY KEY (filing_id, parser_version, row_member, category_member, source_element, period_start, period_end),
    CHECK (category IN ('SUBSIDIARY', 'ASSOCIATE', 'JOINT_VENTURE', 'KMP', 'PROMOTER_GROUP', 'OTHER')),
    CHECK (period_type IN ('DURATION', 'INSTANT'))
);
-- Reg. 23(9) related-party transactions per counterparty from the Integrated Filing (Governance) section [X19, X115]:
-- one row per typed RelatedPartyTransactionAxis member of a standalone Q2 / Q4 results filing, promoted with it and
-- by `backfill-rpt`. A separate table from the annual schedule on purpose: the tagged context is the filing's quarter,
-- the amounts cover the Reg. 23(9) half-year (disclosure_start / disclosure_months, X160), and a few filers put
-- financial-year-to-date amounts in the Q4 filing without saying so (X161), so these rows never feed a ratio or a
-- feature column (features_rpt reads related_party_transactions only). prune-versions keeps the latest version.
CREATE TABLE IF NOT EXISTS reg23_related_party_transactions (
    filing_id           VARCHAR NOT NULL REFERENCES filings(filing_id),
    parser_version      VARCHAR NOT NULL,        -- parsers.reg23_rpt.REG23_PARSER_VERSION
    entity_id           VARCHAR NOT NULL REFERENCES entity_master(entity_id),   -- the filer
    scope               VARCHAR NOT NULL,
    row_member          VARCHAR NOT NULL,        -- typed RelatedPartyTransactionAxis member as filed
    period_start        DATE NOT NULL,           -- the duration context as tagged: the filing's quarter, not the disclosure
    period_end          DATE NOT NULL,           -- = the filing's declared period end
    period_months       INTEGER,                 -- of the tagged context
    disclosure_start    DATE,                    -- the period the amounts cover: the Reg. 23(9) half-year ending on
    disclosure_months   INTEGER,                 -- period_end (HALF_YEAR_RULE, X160; NULL only on reg23-1 rows). A few
                                                 -- filers put FY-to-date in Q4 (X161), undetectable inside the filing
    listed_party_name   VARCHAR,                 -- the listed entity or subsidiary entering into the transaction
    counterparty_name   VARCHAR NOT NULL,
    counterparty_pan    VARCHAR,                 -- NULL when masked ("******")
    relationship        VARCHAR,                 -- as filed (free text)
    type_as_filed       VARCHAR,                 -- TypeOfRelatedPartyTransaction as filed
    txn_type            VARCHAR NOT NULL,        -- parsers.reg23_rpt.TYPE_MAP value | unmapped
    details             VARCHAR,                 -- DetailsOfOtherRelatedPartyTransaction
    approval_remarks    VARCHAR,
    terms               VARCHAR,                 -- JSON: loan / ICD / investment / indebtedness terms as filed
    amount_inr          DECIMAL(20,2) NOT NULL,  -- AmountOfRelatedPartyTransactionDuringTheReportingPeriod
    approved_value_inr  DECIMAL(20,2),           -- as approved by the audit committee
    ratified_value_inr  DECIMAL(20,2),
    opening_balance_inr DECIMAL(20,2),           -- AmountOfRelatedPartyTransaction the day before period_start
    closing_balance_inr DECIMAL(20,2),           -- AmountOfRelatedPartyTransaction at period_end
    visible_from_ts     TIMESTAMP NOT NULL,
    PRIMARY KEY (filing_id, parser_version, row_member)
);
-- Audit-opinion flags per results / annual filing (parsers/audit_report.py, owner decision 2026-11-17) [X121-X124]:
-- derived from the auditor's report text (Reg. 34 `DisclosureInAuditorsReportExplanatory`, read whole from the vault
-- blob) and the Integrated Filing audit fields, never from the checkbox, which is recorded next to it
-- (`checkbox_qualified` = filing_meta.auditor_qualified for annual filings; the declaration for results) with
-- `opinion_conflict`. Promoted with the filing (same entity, scope, visibility) and by `backfill-audit-opinions`; one
-- row per filing and AUDIT_PARSER_VERSION; a filing filing none of the elements has no row.
CREATE TABLE IF NOT EXISTS audit_opinions (
    audit_opinion_id          VARCHAR NOT NULL,          -- stable_id('audit', filing_id, parser_version)
    filing_id                 VARCHAR NOT NULL REFERENCES filings(filing_id),
    parser_version            VARCHAR NOT NULL,          -- parsers.audit_report.AUDIT_PARSER_VERSION
    entity_id                 VARCHAR NOT NULL REFERENCES entity_master(entity_id),
    source_kind               VARCHAR NOT NULL,          -- ANNUAL (Reg. 34) | RESULTS (Integrated Filing)
    scope                     VARCHAR NOT NULL,          -- the filing's scope
    period_end                DATE NOT NULL,             -- annual: FY end; results: the quarter end
    visible_from_ts           TIMESTAMP NOT NULL,        -- the filing's visibility (filing_meta)
    audit_opinion             VARCHAR,                   -- UNMODIFIED | QUALIFIED | ADVERSE | DISCLAIMER; NULL = none filed
    opinion_rule              VARCHAR NOT NULL,          -- OPINION_HEADING | OPINION_PARAGRAPH | NO_REPORT | DECLARATION |
                                                         -- OPINION_OF_AUDITORS | TYPE_OF_QUALIFICATION | NO_OPINION
    going_concern_uncertainty BOOLEAN,                   -- annual: a Material Uncertainty Related to Going Concern section
                                                         -- about the reporting entity / group; NULL for results
    going_concern_component   BOOLEAN,                   -- annual consolidated: such a section about a component only
    emphasis_of_matter        BOOLEAN,                   -- annual: an Emphasis of Matter section (informational)
    checkbox_qualified        BOOLEAN,                   -- annual: WhetherAuditorsReportHasBeenQualified...; results:
                                                         -- the declaration (statement on impact = true)
    opinion_conflict          BOOLEAN,                   -- (audit_opinion is modified) <> checkbox_qualified
    declaration               VARCHAR,                   -- results: UNMODIFIED | NOT_APPLICABLE | STATEMENT | as filed
    qualification_count       INTEGER,                   -- results: AuditQualificationAxis members with a type
    qualification_repetitive  BOOLEAN,                   -- results: any FrequencyOfAuditQualification "Repetitive"
    text_len                  INTEGER,                   -- annual: characters of the report text read
    text_sha256               VARCHAR,                   -- annual: sha256 of that text (UTF-8)
    PRIMARY KEY (filing_id, parser_version),
    CHECK (source_kind IN ('ANNUAL', 'RESULTS')),
    CHECK (audit_opinion IS NULL OR audit_opinion IN ('UNMODIFIED', 'QUALIFIED', 'ADVERSE', 'DISCLAIMER'))
);
-- Every XBRL fact whose element no other clean table holds per element, as filed (parsers/disclosures.py) [X116]: one
-- row per fact of a parsed, in-scope results / annual / shareholding / Reg. 30 filing, promoted with it (same entity,
-- scope, visibility) and by `backfill-disclosures`. Parser disc-2 (owner decision M, X120) leaves three kinds of fact
-- in the vault blob only: elements of reference/disclosure_exclusions.csv, values that are asterisks only (masked),
-- and the text of values longer than 1,000 characters (a pointer row: value_text NULL, text_len / text_sha256 /
-- text_snippet; disclosures.full_text reads the blob). Elements a reader selects are exempt (READ_ELEMENTS). `seq` is the fact's document order (= parsers.xbrl Fact.seq). The
-- captured set is computed per filing from its other clean rows (staging.captured_elements). Money is value_inr
-- (unit INR, rupees); every other numeric unit (PURE fractions or percent points as filed, SHARES, per-share, foreign
-- currency, counts) is value_num as filed, never rescaled; true/false/yes/no text also value_bool; value_text always.
-- Readers take in_window rows (periods the filing's own parser validated) unless they state otherwise.
CREATE TABLE IF NOT EXISTS disclosure_facts (
    filing_id        VARCHAR NOT NULL REFERENCES filings(filing_id),
    parser_version   VARCHAR NOT NULL,           -- parsers.disclosures.DISCLOSURE_PARSER_VERSION
    entity_id        VARCHAR NOT NULL REFERENCES entity_master(entity_id),   -- the filer
    source_kind      VARCHAR NOT NULL,           -- RESULTS | ANNUAL | SHAREHOLDING | EVENT
    scope            VARCHAR,                    -- the filing's scope (results / annual); NULL for SHAREHOLDING, EVENT
    seq              INTEGER NOT NULL,           -- document order of the fact in its filing
    element_ns       VARCHAR NOT NULL,
    element          VARCHAR NOT NULL,           -- local name as filed
    context_id       VARCHAR NOT NULL,
    period_type      VARCHAR NOT NULL,           -- DURATION | INSTANT | NONE (a context with no period, SHP16)
    period_start     DATE,                       -- = period_end for INSTANT; NULL for NONE
    period_end       DATE,                       -- the instant for INSTANT
    period_months    INTEGER,                    -- DURATION on whole calendar months (1..18), else NULL
    in_window        BOOLEAN NOT NULL,           -- a period the filing's own parser validated
    dimensions       JSON,                       -- {axis QName: member QName} as filed; NULL when none
    unit_ref         VARCHAR,                    -- as filed; NULL for a non-numeric fact
    unit             VARCHAR,                    -- INR | PURE | SHARES | INR_PER_SHARE | <CCY> | UNKNOWN
    value_inr        DECIMAL(20,2),              -- unit INR only, exact rupees
    value_num        DECIMAL(28,8),              -- every other numeric unit, exact as filed
    value_bool       BOOLEAN,                    -- non-numeric true / false / yes / no
    value_text       VARCHAR,                    -- exactly as filed; NULL only for a pointer row (> 1,000 characters)
    visible_from_ts  TIMESTAMP NOT NULL,
    text_len         INTEGER,                    -- pointer rows: characters of the text as filed
    text_sha256      VARCHAR,                    -- pointer rows: sha256 of the text as filed (UTF-8)
    text_snippet     VARCHAR,                    -- pointer rows: first 300 characters, HTML tags / entities removed
    PRIMARY KEY (filing_id, parser_version, seq),
    CHECK (source_kind IN ('RESULTS', 'ANNUAL', 'SHAREHOLDING', 'EVENT')),
    CHECK (period_type IN ('DURATION', 'INSTANT', 'NONE')),
    CHECK ((period_type = 'NONE') = (period_end IS NULL)),
    CHECK (period_months IS NULL OR period_months BETWEEN 1 AND 18),
    CHECK (value_inr IS NULL OR unit = 'INR'),
    CHECK (value_num IS NULL OR (unit IS NOT NULL AND unit <> 'INR')),
    CHECK (value_bool IS NULL OR unit_ref IS NULL),
    CHECK ((value_text IS NULL) = (text_sha256 IS NOT NULL)),
    CHECK ((text_sha256 IS NULL) = (text_len IS NULL) AND (text_sha256 IS NULL) = (text_snippet IS NULL))
);
-- ── Views ──────────────────────────────────────────────────────────────
-- Everything below VIEWS_MARKER runs after the column upgrade (db.apply_schema), so a view may name columns that an
-- existing database gains in the same run. Views hold no data; CREATE OR REPLACE keeps them at this definition.
-- views (after column upgrade)

-- screener_features_history (architecture §4.1): one row per security and materialised day, the exact columns (names,
-- order, types) of screener_features. Every daily row lies in exactly one interval of its security (features_store).
CREATE OR REPLACE VIEW screener_features_history AS
SELECT d.as_of_date, d.security_id, d.entity_id, d.symbol, d.series, d.price_date,
       d.close, d.shares, d.shares_source, d.market_cap, d.enterprise_value, e.sales_ttm,
       e.ebitda_ttm, e.pat_ttm, e.fcf_ttm, e.net_debt, e.total_equity, d.pe,
       d.pb, d.ev_ebitda, e.opm, e.sales_growth_yoy, e.profit_growth_yoy, e.roe,
       e.roce, e.roic, e.croic, e.debt_to_equity, d.fcff_yield, e.other_income_to_pbt,
       e.altman_z_dd, e.piotroski_f, e.beneish_m, d.return_1m, d.return_3m, d.return_6m,
       d.return_12m, d.price_to_dma50, d.price_to_dma200, d.dist_52w_high, d.deliv_avg_5d, d.deliv_avg_20d,
       d.delivery_velocity, d.float_turnover_pct, d.promoter_pct, d.fii_pct, d.dii_pct, e.scope_used,
       e.fundamentals_end, e.bs_as_of, e.cf_as_of, d.shp_as_of, d.in_nifty500, d.eps_ttm,
       d.eps_continuing_ttm, e.roe_continuing, e.core_profit_ttm, e.is_lending_nbfc, e.nii_ttm, e.ppop_ttm,
       e.cost_to_income, e.credit_cost, e.nim_asset_proxy, e.roa, e.loans, e.loans_as_of,
       e.loans_avg_from, e.gnpa_pct, e.nnpa_pct, e.pcr, e.credit_to_deposit, e.cet1_pct,
       e.at1_pct, e.roa_filed, e.govt_holding_pct, e.insurer_basis, e.net_premium_earned_ttm, e.insurance_revenue_ttm,
       e.claims_ratio, e.expense_ratio, e.combined_ratio, e.solvency_ratio, e.investment_income_ttm, d.persistency_13m,
       d.persistency_61m, e.scope_reason, e.restatement_suspected, e.default_quarterly_scope, e.default_annual_scope, e.sloan_accrual,
       e.cfo_to_ebitda, e.fcf_to_pat, e.working_capital_intensity, e.receivables_sales_divergence, e.net_debt_to_fcf, e.cost_of_debt,
       e.dol, e.gross_ebitda_spread, d.reverse_dcf_implied_g, d.reverse_dcf_wacc_used, d.reverse_dcf_terminal_g, d.pe_percentile,
       d.ev_ebitda_percentile, e.valuation_archetype, d.ev_to_gross_profit, d.ex_cash_pe, d.ev_to_billings, d.ev_to_esop_adj_ebitda,
       d.price_to_cfo, e.rule_of_40, e.billings_growth_pct, e.neg_working_capital_float_pct, e.net_burn_multiple, e.cash_runway_months,
       e.esop_adj_fcf, e.liquid_cash, d.promoter_holding_pct, d.promoter_pledge_pct, d.promoter_encumbered_pct, d.fii_holding_pct,
       d.fpi_holding_pct, d.dii_holding_pct, d.public_holding_pct, d.non_promoter_non_public_pct, d.fii_dii_qoq_change_pct, e.capex_to_depreciation,
       e.cwip_to_gross_block, e.rote, e.rnd_and_royalty_intensity, e.contingent_liabilities_to_net_worth, e.annual_fy_end, d.order_wins_90d,
       d.order_value_90d, d.kmp_resignations_90d, d.auditor_resignations_90d, d.fraud_or_default_90d, d.penalties_90d, e.roce_screener,
       e.debtor_days, e.inventory_turnover, e.working_capital, e.inventory_days, e.days_payable, e.cash_conversion_cycle,
       e.working_capital_days, d.vnb_margin, d.embedded_value, d.ape_growth, d.gov, d.take_rate,
       d.contribution_margin, d.nrr, d.cac_payback, e.sales_growth_qoq_pct, e.profit_growth_qoq_pct, e.npm_pct,
       e.interest_coverage, e.opm_last_year_pct, d.dividend_yield_pct, d.dividend_payout_pct, d.promoter_holding_change_qoq_pp, d.return_1d,
       d.return_1w, d.return_3y, d.return_5y, d.return_7y, d.return_10y, d.volume,
       d.volume_1w_avg, d.volume_1m_avg, d.volume_1y_avg, d.high_52w, d.low_52w, d.dist_52w_low,
       d.high_since_data_start, d.low_since_data_start, d.dma50, d.dma200, d.dma50_prev, d.dma200_prev,
       d.rsi_14, d.rsi_14_prev, d.macd, d.macd_signal, d.macd_prev, d.macd_signal_prev,
       d.atr_14_pct, d.rs_nifty500_3m, d.rs_nifty500_6m, d.rs_nifty500_12m, d.beta_1y_nifty500, d.turnover_median_20d,
       d.deliv_pct, d.deliv_pct_avg_20d, d.vwap, d.vwap_20d, e.sales_latest_quarter, e.sales_preceding_quarter,
       e.sales_preceding_year_quarter, e.operating_profit_latest_quarter, e.operating_profit_preceding_quarter, e.operating_profit_preceding_year_quarter, e.other_income_latest_quarter, e.other_income_preceding_quarter,
       e.other_income_preceding_year_quarter, e.depreciation_latest_quarter, e.depreciation_preceding_quarter, e.depreciation_preceding_year_quarter, e.ebit_latest_quarter, e.ebit_preceding_quarter,
       e.ebit_preceding_year_quarter, e.interest_latest_quarter, e.interest_preceding_quarter, e.interest_preceding_year_quarter, e.pbt_latest_quarter, e.pbt_preceding_quarter,
       e.pbt_preceding_year_quarter, e.tax_latest_quarter, e.tax_preceding_quarter, e.tax_preceding_year_quarter, e.pat_latest_quarter, e.pat_preceding_quarter,
       e.pat_preceding_year_quarter, e.net_profit_latest_quarter, e.net_profit_preceding_quarter, e.net_profit_preceding_year_quarter, e.exceptional_items_latest_quarter, e.exceptional_items_preceding_quarter,
       e.exceptional_items_preceding_year_quarter, e.sales_2quarters_back, e.sales_3quarters_back, e.operating_profit_2quarters_back, e.operating_profit_3quarters_back, e.net_profit_2quarters_back,
       e.net_profit_3quarters_back, e.sales_last_year, e.sales_preceding_year, e.operating_profit_last_year, e.operating_profit_preceding_year, e.other_income_last_year,
       e.other_income_preceding_year, e.depreciation_last_year, e.depreciation_preceding_year, e.ebit_last_year, e.ebit_preceding_year, e.interest_last_year,
       e.interest_preceding_year, e.pbt_last_year, e.pbt_preceding_year, e.tax_last_year, e.tax_preceding_year, e.pat_last_year,
       e.pat_preceding_year, e.net_profit_last_year, e.net_profit_preceding_year, e.exceptional_items_last_year, e.exceptional_items_preceding_year, e.sales_ttm_1y_back,
       e.avg_earnings_5y, e.avg_earnings_10y, e.avg_ebit_5y, e.avg_ebit_10y, d.eps_latest_quarter, d.eps_preceding_quarter,
       d.eps_preceding_year_quarter, d.eps_last_year, d.eps_preceding_year, e.equity_capital_latest_quarter, e.equity_capital_preceding_quarter, e.equity_capital_preceding_year_quarter,
       e.opm_latest_quarter_pct, e.opm_preceding_quarter_pct, e.opm_preceding_year_pct, e.npm_latest_quarter_pct, e.npm_preceding_quarter_pct, e.npm_preceding_year_quarter_pct,
       e.npm_last_year_pct, e.npm_preceding_year_pct, e.gpm_latest_quarter_pct, e.gpm_last_year_pct, e.gpm_preceding_year_pct, e.sales_growth_yoy_quarter_pct,
       e.profit_growth_yoy_quarter_pct, e.operating_profit_growth_yoy_quarter_pct, e.sales_growth_3y_pct, e.sales_growth_5y_pct, e.sales_growth_7y_pct, e.sales_growth_10y_pct,
       e.profit_growth_3y_pct, e.profit_growth_5y_pct, e.profit_growth_7y_pct, e.profit_growth_10y_pct, e.operating_profit_growth_3y_pct, e.operating_profit_growth_5y_pct,
       e.operating_profit_growth_7y_pct, e.operating_profit_growth_10y_pct, d.eps_growth_3y_pct, d.eps_growth_5y_pct, d.eps_growth_7y_pct, d.eps_growth_10y_pct,
       e.sales_growth_median_5y_pct, e.sales_growth_median_10y_pct, e.opm_5y_pct, e.opm_10y_pct, e.last_result_date, e.last_annual_result_date,
       d.book_value_per_share, d.is_trade_to_trade, e.opm_preceding_year_quarter_pct, e.debt, e.equity_capital, e.reserves,
       e.balance_sheet_total, e.net_block, e.cwip, e.investments, e.current_assets, e.current_liabilities,
       e.lease_liabilities, e.inventory, e.trade_receivables, e.trade_payables, e.cash_equivalents, e.gross_block,
       e.accumulated_depreciation, e.contingent_liabilities, e.advance_from_customers, e.debt_preceding_year, e.net_block_preceding_year, e.gross_block_preceding_year,
       e.cwip_preceding_year, e.working_capital_preceding_year, e.debt_3y_back, e.debt_5y_back, e.debt_7y_back, e.debt_10y_back,
       e.net_block_3y_back, e.net_block_5y_back, e.net_block_7y_back, e.net_block_10y_back, e.working_capital_3y_back, e.working_capital_5y_back,
       e.working_capital_7y_back, e.working_capital_10y_back, e.cash_3y_back, e.cash_5y_back, e.cash_7y_back, e.cfo_last_year,
       e.cfo_preceding_year, e.cfi_last_year, e.cfi_preceding_year, e.cff_last_year, e.cff_preceding_year, e.net_cash_flow_last_year,
       e.net_cash_flow_preceding_year, e.cash_beginning_last_year, e.cash_beginning_preceding_year, e.cash_end_last_year, e.cash_end_preceding_year, e.fcf_last_year,
       e.fcf_preceding_year, e.fcf_3y, e.fcf_5y, e.fcf_7y, e.fcf_10y, e.cfo_3y,
       e.cfo_5y, e.cfo_7y, e.cfo_10y, e.cfi_3y, e.cfi_5y, e.cfi_7y,
       e.cfi_10y, e.face_value, d.book_value_preceding_year, d.book_value_3y_back, d.book_value_5y_back, d.book_value_10y_back,
       d.graham_number, d.shares_preceding_year, d.shares_10y_back, e.current_ratio, e.quick_ratio, e.net_debt_to_equity,
       e.long_term_debt_to_equity, e.debt_to_equity_preceding_year, e.financial_leverage, e.asset_turnover, e.earning_power, e.roe_preceding_year,
       e.roce_preceding_year, e.roa_preceding_year, e.exports_pct, e.exports_pct_3y_back, e.exports_pct_5y_back, e.inventory_turnover_3y_back,
       e.inventory_turnover_5y_back, e.inventory_turnover_7y_back, e.inventory_turnover_10y_back, e.debtor_days_3y_back, e.debtor_days_5y_back, e.avg_debtor_days_3y,
       e.avg_working_capital_days_3y, e.cfo_to_ebitda_last_year, e.cfo_to_ebitda_preceding_year, e.fcf_conversion_3y, e.cfo_to_ebitda_3y, e.net_debt_to_fcf_3y,
       d.price_to_fcf, d.equity_fcf_yield, d.shareholder_yield, d.buyback_yield, d.dilution_1y, d.dilution_5y,
       e.reinvestment_rate, e.incremental_roic_1y, e.incremental_roic_3y, e.incremental_roic_5y, e.net_debt_to_ebitda, d.ev_ebitda_percentile_20q,
       d.fii_holding_change_qoq_pct, d.dii_holding_change_qoq_pct, d.inst_holding_pct, d.unpledged_promoter_holding_pct, d.mf_holding_pct, d.mf_holding_change_qoq_pct,
       d.insurance_holding_pct, d.retail_holding_pct, d.num_shareholders, d.num_shareholders_preceding_quarter, d.num_shareholders_change_qoq_pct, d.num_shareholders_1y_back,
       e.sales_growth_yoy_preceding_quarter_pct, e.profit_growth_yoy_preceding_quarter_pct, e.core_profit_latest_quarter, e.core_profit_yoy_latest_q, e.core_profit_yoy_preceding_q, e.other_income_lift_pp,
       d.pe_core, e.growth_sustained, e.growth_acceleration_pp, e.opm_change_yoy_pp, e.operating_leverage, d.peg,
       d.earnings_yield, d.industry, d.cyclical_flag, d.under_owned, d.forensic_clean, e.cash_conversion_ok,
       e.capex_pay_off_signal, e.roce_stability_5y, e.opm_stability_5y, d.pe_vs_own_5y_median, d.magic_formula_rank, d.pe_core_universe_median,
       d.market_cap_universe_median, d.gem_score, d.hat_hidden_compounder, d.hat_quality_fair_price, d.hat_magic_formula, d.hat_garp,
       d.hat_turnaround, d.hat_under_owned, d.hat_cash_machine, d.hat_fallen_quality, d.hat_capex_pay_off, d.hat_cyclical,
       d.hat_lender, d.hats_passed, d.nse_macro_sector, d.nse_sector, d.nse_industry, d.nse_basic_industry,
       d.industry_pe_median, d.industry_pb_median, d.industry_roce_median, d.industry_sales_growth_median, d.basic_industry_pe_median, d.basic_industry_pb_median,
       d.basic_industry_roce_median, d.basic_industry_sales_growth_median, d.pe_premium_to_industry, d.pb_premium_to_industry, d.pe_premium_to_basic_industry, d.pb_premium_to_basic_industry,
       d.peer_count, d.peer_rank_market_cap, d.peer_rank_pe, d.peer_rank_roce, d.peer_rank_profit_growth, d.industry_group_pe_median,
       d.industry_group_pb_median, d.industry_group_roce_median, d.industry_group_sales_growth_median, d.pe_premium_to_industry_group, d.pb_premium_to_industry_group, e.opm_acceleration_pp,
       e.gpm_change_yoy_pp, e.profit_growth_acceleration_pp, e.sales_growth_streak_quarters, e.profit_growth_streak_quarters, e.material_cost_latest_quarter_pct, e.material_cost_last_year_pct,
       e.employee_cost_latest_quarter_pct, e.employee_cost_last_year_pct, e.other_expenses_latest_quarter_pct, e.other_expenses_last_year_pct, e.power_fuel_latest_quarter_pct, e.power_fuel_last_year_pct,
       e.freight_latest_quarter_pct, e.freight_last_year_pct, e.ad_promo_latest_quarter_pct, e.ad_promo_last_year_pct, e.marketing_efficiency_latest_quarter, e.marketing_efficiency_last_year,
       e.material_cost_last_year, e.material_cost_preceding_year, e.employee_cost_last_year, e.employee_cost_preceding_year, e.minority_share_last_year, e.minority_share_preceding_year,
       e.dividends_paid_last_year, e.dividends_paid_preceding_year, e.acquisition_outflow_last_year, e.acquisition_outflow_preceding_year, e.acquisition_outflow_to_sales_last_year, e.inorganic_growth_flag,
       e.standalone_pat_ttm, e.profit_leakage_pct, e.profit_leakage_latest_quarter_pct, e.incremental_asset_turnover_3y, e.cfo_to_pat, e.cash_tax_rate,
       e.effective_tax_rate, e.exceptional_to_pbt, e.exceptional_quarters_4q, e.capex_intensity, d.net_cash_to_market_cap, e.rpt_to_sales,
       e.intangibles_to_equity, e.audit_fees_to_sales, e.managerial_remuneration_to_pat, e.capital_commitments_to_net_worth, e.unquoted_investments, e.quoted_investments_market_value,
       e.revaluation_reserve, d.price_to_sales, d.ev_to_sales, d.price_to_embedded_value, d.gov_ttm, d.ev_to_gov,
       d.gov_growth_yoy_pct, d.arpu, d.arpu_growth_yoy_pct, d.mtu, d.mtu_growth_yoy_pct, d.contribution_margin_change_yoy_pp,
       d.casa_pct, d.inst_shares_change_qoq, d.volume_median_90d, d.institutional_absorption_90d, d.promoter_pledge_change_qoq_pp, d.public_holders_above_1pct,
       d.litigations_90d, d.allotments_90d, d.fund_raising_events_90d, d.rf_auditor_resignation_90d, d.rf_kmp_resignations_90d, d.rf_fraud_or_default_90d,
       d.rf_litigation_90d, e.rf_audit_qualified, d.rf_pledge_increase_qoq, d.pe_numerator, e.pe_denominator, e.roe_numerator,
       e.roe_denominator, e.roce_numerator, e.roce_denominator, d.ev_ebitda_numerator, e.ev_ebitda_denominator, e.opm_numerator,
       e.opm_denominator, e.beneish_dsri, e.beneish_gmi, e.beneish_aqi, e.beneish_sgi, e.beneish_depi,
       e.beneish_sgai, e.beneish_lvgi, e.beneish_tata, e.piotroski_roa_positive, e.piotroski_cfo_positive, e.piotroski_roa_up,
       e.piotroski_cfo_above_pat, e.piotroski_leverage_down, e.piotroski_current_ratio_up, e.piotroski_no_dilution, e.piotroski_gross_margin_up, e.piotroski_asset_turnover_up,
       d.altman_z_original, e.bs_accruals, e.depreciation_rate, e.asset_age_proxy, e.debtor_days_change_yoy, e.ccc_change_yoy,
       e.h1_bs_as_of, e.debtor_days_h1, e.inventory_days_h1, e.debtor_days_h1_change_yoy, e.inventory_days_h1_change_yoy, d.pb_percentile,
       d.price_to_sales_percentile, d.ev_to_sales_percentile, d.momentum_12m_1m, d.volatility_1y, d.max_drawdown_1y, d.high_52w_on_delivery_spike,
       d.pead_event_date, d.pead_ar_t0, d.pead_ar_t1, d.pead_ar_t5, d.pead_ar_t20, d.pead_relvol_t0,
       d.pead_relvol_t1, d.pead_relvol_t5, d.pead_relvol_t20, d.nifty500_inclusion_90d, d.nifty500_exclusion_90d, d.days_to_next_ex_date,
       d.next_ex_date_action, d.dividend_365d, d.bonus_365d, d.split_365d, e.segment_period_end, e.segment_count,
       e.largest_segment_revenue_share, e.fastest_growing_segment, e.fastest_growing_segment_growth_yoy, e.largest_segment_margin_change_yoy_pp, d.rs_rank_12m_1m, d.industry_earnings_breadth,
       d.industry_earnings_breadth_n, e.rpt_fy_end, e.rpt_counterparties, e.rpt_leak_pct, e.rpt_purchases_to_sales, e.rpt_royalty_to_sales,
       e.rpt_loans_given_to_net_worth, e.insider_receivables_as_of, e.insider_receivables, e.insider_receivables_to_receivables, e.has_insider_receivables, d.has_warrants, d.has_convertibles,
       d.has_partly_paid, d.has_locked_in, d.has_dvr_shares, d.has_sbo, d.is_psu, e.subsidiary_fy_end,
       e.parent_profit_share, e.largest_subsidiary_profit_share, e.largest_subsidiary_name, e.consolidated_entities_count,
       e.audit_opinion, e.audit_opinion_fy_end, e.audit_opinion_conflict, e.going_concern_uncertainty, e.emphasis_of_matter,
       e.audit_opinion_quarterly, e.audit_opinion_quarter_end
FROM features_daily d
LEFT JOIN features_events e ON e.security_id = d.security_id AND e.valid_from_date <= d.as_of_date
     AND d.as_of_date < coalesce(e.valid_to_date, DATE '9999-12-31');  -- open interval; an OR here is ~400x slower

-- Capital-allocation scorecard (G201): the batch C / G components side by side, one row per security of the latest
-- materialised day. Never summed into one score (architecture §10.2); history-gated components stay NULL (C9).
CREATE OR REPLACE VIEW capital_allocation_scorecard AS
SELECT as_of_date, security_id, symbol, valuation_archetype,
       roic, incremental_roic_1y, incremental_roic_3y, incremental_roic_5y, reinvestment_rate,
       capex_to_depreciation, capex_intensity, cfo_to_ebitda, fcf_conversion_3y,
       dividend_payout_pct, buyback_yield, shareholder_yield, dilution_1y, dilution_5y,
       net_debt_to_ebitda, acquisition_outflow_last_year, acquisition_outflow_to_sales_last_year, inorganic_growth_flag
FROM screener_features;
