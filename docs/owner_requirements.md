# Owner requirements: Aligning Financial Results Databases (2026-11-14)

Source document (owner-provided, committed at the owner's request 2026-11-14): `docs/inputs/Aligning_Financial_Results_Databases.pdf`.

Source: a long chat between the owner and another AI assistant (26 printed pages), exported 2026-11-14. The owner's own prompts are requirements. The assistant's answers are suggestions and claims: they are **inputs, not evidence** (CLAUDE.md evidence rules 1-4). Nothing here may be coded against until it is VERIFIED in `docs/references.md` with a real fixture and a test.

Every concrete item in the chat is mapped to the repository as of 2026-11-14. The machine-readable version (with page numbers and sources) is the gap table this digest was generated from. Ids are stable (G1..G343). Repeated items are listed where they first appear, or once per distinct claim.

## Status summary

Recounted from the rows on 2026-11-21 (G93 DONE 2026-11-17; G214 DONE, G275 / G336 out of scope 2026-11-21).

| Status | Meaning | Count |
|---|---|---|
| DONE | implemented and tested (file and test cited) | 225 |
| DOCUMENTED_PLANNED | planned in architecture.md / references.md / data_sources.md | 52 |
| IN_PROGRESS | being built now | 2 |
| MISSING | not anywhere in docs or code | 12 |
| CONFLICTS_WITH_EVIDENCE | contradicted by our verified fixtures or tests | 19 |
| OUT_OF_SCOPE_BY_DECISION | excluded by a recorded decision (C2, C7, C9, invariants, CLAUDE.md Don'ts, owner decisions A-V) | 33 |
| NEEDS_OWNER_DECISION | the docs do not settle it | 0 |
| **Total** | | **343** |

Source column in the gap table: OWNER_PROMPT 54, ASSISTANT_SUGGESTION 289. Rows prefixed "Review:" are the code-review points the owner pasted into the chat, so they count as owner requirements.

## Ingestion (34)

| id | requirement | status | where / next step |
|---|---|---|---|
| G16 | Every quarterly XBRL holds current and prior-year comparative columns; ingest both | CONFLICTS_WITH_EVIDENCE | X2, X3, X52; Muthoot 1750817. Only current quarter, YTD and period-end instants (+ PY_I opening cash) |
| G25 | Extract notes and adjustments from varied annual-report PDFs with code *(owner)* | DONE | F07; X36, X69-X76; parsers/reg34_annual.py; tests/test_batch9_annual.py. Notes come from Reg. 34 annual XBRL instead of PDFs |
| G29 | 3-stage PDF pipeline: PyMuPDF page triage, vision-LLM to strict JSON, deterministic checks | OUT_OF_SCOPE_BY_DECISION | arch 7.6, arch 15. PDF numbers out of scope; see decision G28 |
| G30 | PDF checks: note tie-out 0.5%, balance-sheet identity, cross-source scale check vs XBRL; quarantine failures | OUT_OF_SCOPE_BY_DECISION | arch 7.6, arch 15. Gate G3 already checks filed XBRL identities |
| G36 | Permanent entity master: immutable entity_id mapped to ISIN; tickers may change | DONE | entity_master, securities, security_identifier_history; arch 5.1; tests/test_identity.py. Keyed by FinInstrmId + ISIN, not ISIN alone |
| G40 | Evening job polls NSE corporate actions and bhavcopy; purposes parsed by deterministic rules | DONE | run-day; arch 11.2, 13; CA9; tests/test_nse_corp_actions.py, tests/test_phase1_fixes_b.py. Scheduled by ops/ (20:15 IST) or, batch K, by the GitHub Actions nightly-pipeline workflow on a self-hosted runner (22:00 IST; ops/README.md, tests/test_nightly_workflows.py) |
| G79 | Map NSE symbols to BSE scrip codes | DONE | X111; filing_checks.apply_bse_scrip_code fills security_identifier_history.bse_scrip_code from the in-filing ScripCode (rows matching the filing's ISIN and symbol); IDENTIFIER/BSE_SCRIP_CODE_CONFLICT on disagreement; tests/test_restatement_triggers.py (TCS, HDFC Bank) |
| G85 | Key the master table on ISIN, identical across NSE and BSE | CONFLICTS_WITH_EVIDENCE | P5 (split changes ISIN), P13; arch 5.1 |
| G90 | Quarterly + annual XBRL: statements, notes (borrowings, leases, fixed assets) | DONE | F06, F07; parsers/integrated.py, parsers/reg34_annual.py; X71-X73. Segments tracked separately |
| G91 | Shareholding XBRL: promoter, FII, DII (MF, insurance, banks), public, pledged shares | DONE | F08; SHP7-SHP15; tests/test_batch8_shareholding.py |
| G92 | SAST Reg. 31(1)/31(2) encumbrance events with lender details | DOCUMENTED_PLANNED | F12 (Phase 3, OBSERVED) |
| G93 | Reg. 76 reconciliation of share capital audit (exact issued / listed shares) | DONE | Listed side (2026-11-17, owner "check bhavcopy zip, everything is inside it"): NSE Issue Size per security daily from the PR-zip mcap file (F31, X133; `raw_nse_mcap`; tests/test_mcap_universe.py), cross-checked against Reg. 31 by `check-issue-size` (0.5%). Measured 98.4% of 4,035 same-date pairs within 0.5% (84.6% exact), below the 99% bar (listing lag after allotments, buy-backs, partly-paid E1, bonus ex-date), so Reg. 31 stays the market-cap count (decision C). The Reg. 76 audit report itself (demat vs physical) is still unsourced: F09 UNVERIFIED, probed 2026-11-15 (vault ledger, announcements RSS, TCS announcements API Jul-Nov 2026; BSE 403), no Reg. 76 file found (A15); Reg. 31 x paid-up cross-check (X103) stands in; batch J adds the annual stand-in: Reg. 34 year-end issued / subscribed / paid-up counts vs Reg. 31 and paid-up / face (X114, ANNUAL_SHARE_COUNT_DIFFERS) Owner 2026-11-24: "Demat vs physical not required": the Reg. 76 report is not needed; G93 is closed on the listed side. |
| G99 | Related-party transactions from Reg. 23(9) half-yearly Integrated Filing | DONE | X19; RPT contexts land in `reg23_related_party_transactions` / `disclosure_facts` (raw facts: the vault blob, decision J). Batch J: per counterparty from the Reg. 34 annual schedule (X113, `related_party_transactions`, `backfill-rpt`); the Reg. 23(9) rows per counterparty of standalone Q2 / Q4 Integrated Filings are parsed into `reg23_related_party_transactions` (X115, parsers/reg23_rpt.py, promoted with the results filing and by `backfill-rpt`; tests/test_reg23_rpt.py); they cover the Reg. 23(9) half-year (X160, `disclosure_start` / `disclosure_months`, tests/test_reg23_period.py) and feed no feature because a few filers report FY-to-date in Q4 (X161) |
| G101 | Daily delivery % | DONE | F02; P10; tests/test_market_parsers.py |
| G105 | Audit qualification / modified opinion flag | DONE | E8; X75 filing_meta.auditor_qualified; since 2026-11-17 (owner decision: the text decides) X121-X124 `audit_opinions` from the auditor's report text and the Integrated Filing audit fields, tests/test_audit_opinions.py. Screener columns `audit_opinion`, `audit_opinion_quarterly`, `audit_opinion_conflict`, `going_concern_uncertainty`, `emphasis_of_matter` (20A), `rf_audit_qualified` (batch G), and the `forensic_clean` gate |
| G106 | Reg. 30 director / auditor / KMP change alerts | DONE | E5; kmp_resignations_90d, auditor_resignations_90d; tests/test_batch10_events.py |
| G107 | Reg. 30 scheme of arrangement (merger / demerger) filings | DOCUMENTED_PLANNED | E2 (REG30_Restructuring vaulted raw); arch 15 Phase 3 |
| G114 | Reg. 30 order wins (client type, value, timeline) | DONE | E3; order_wins_90d, order_value_90d; tests/test_batch10_events.py |
| G116 | Fraud / default / arrest / forensic-audit filings | DONE | E7; fraud_or_default_90d; tests/test_batch10_events.py. Amount is free text, never parsed |
| G118 | Regulatory / judicial actions and penalty amounts | DOCUMENTED_PLANNED | penalties_90d (NULL); E12 (contents UNVERIFIED) |
| G119 | Allotments, preferential issues, QIPs, warrants (price, allottees, dilution) | DONE | E6; corporate_events; tests/test_batch10_events.py. Screener column `allotments_90d` (count, batch G); no warrant tracker yet |
| G120 | Agreements, JVs, MoUs (counterparty, stake) | DOCUMENTED_PLANNED | E2 (ANN_AGREEMENT vaulted raw); arch 15 Phase 3 |
| G130 | Segment reporting (Ind AS 108): revenue, result, assets, liabilities per segment | DONE | X49, X97-X99; parsers/segments.py, `segment_observations` (point in time, `fundamentals.load_segments`); screener columns `segment_count`, `largest_segment_revenue_share`, `fastest_growing_segment(_growth_yoy)`, `largest_segment_margin_change_yoy_pp` (batch I, features_more.py); tests/test_segment_observations.py, tests/test_features_more.py |
| G131 | Geographic revenue split (domestic vs export) | DONE | X75, X97; `segment_observations` GEOGRAPHY rows (parsers/segments.py), `exports_pct`, `exports_pct_{3,5}y_back` (features_bs.py, batch C); tests/test_balance_sheet_cash_flow_family.py (test_tcs_annual_notes_at_the_last_fiscal_year_end: TCS FY26 domestic + foreign), tests/test_segment_observations.py (test_annual_geography_*) |
| G143 | NSE RSS feeds per filing type drive targeted XBRL downloads | DONE | A2, A3, A9, CA6, E1; run-day RSS hint. The list of nine feeds: R22 (UNVERIFIED) |
| G192 | Analyst / investor meet XBRL (funds, dates) | DOCUMENTED_PLANNED | E2 (SAIIM vaulted raw); Phase 3 |
| G193 | Forward event calendar: board intimations, AGM/EGM notices | DOCUMENTED_PLANNED | E2 (PRIOR_INTIMATION, NOTICE_OF_SHAREHOLDERS_MEETINGS vaulted raw); CA11 |
| G264 | Platform KPIs side table (GOV, take rate, contribution margin, NRR, CAC payback) | DONE | supplemental_kpis; load-kpis; tests/test_supplemental_kpis.py. Manual load; no fetcher (Phase 3) |
| G277 | AOC-1 subsidiary, associate and JV tree from annual XBRL | DONE | group_structure (subsidiary / associate / JV, name, CIN, country, holding fraction, net worth, turnover, PAT, investment per FY) from the Reg. 34 AOC-1 schedule; parsers/aoc1.py, backfill-group-structure; X112; tests/test_batch_h_industry_peers.py |
| G295 | Review: ISINs change on splits; use a surrogate security_id with dated identifier history *(owner)* | DONE | arch 5.1; P5; tests/test_identity.py |
| G296 | Review: price table needs exchange and series columns *(owner)* | DONE | ohlcv PK (security_id, exchange, series, trade_date) |
| G306 | Review: DVR shares get INE ISINs; only partly-paid get IN9 *(owner)* | CONFLICTS_WITH_EVIDENCE | P17, R10: partly-paid are IN9 + series E1 (true); DVRs carry IN9 (JISLDVREQS, FELDVR) or INE (GATECHDVR) ISINs; tests/test_share_class_fixture_facts.py |
| G313 | Review: insurer and new-gen KPIs (VNB, EV, APE, platform KPIs) are not in XBRL *(owner)* | DONE | X62; supplemental_kpis; tests/test_supplemental_kpis.py |
| G336 | Share classes COMMON / DVR / PARTLY_PAID with voting-rights ratio and face value | OUT_OF_SCOPE_BY_DECISION | owner 2026-11-19 "Ignore DVR"; partly-paid series E1 stays outside the universe (P17) |

## Taxonomy/profile (17)

| id | requirement | status | where / next step |
|---|---|---|---|
| G5 | NBFCs and banks use their own Division III / Banking taxonomies, not corporate Ind AS | DONE | X1, X20, X54, X58; parsers/indas_nbfc.py, parsers/igaap_bank.py; tests/test_batch4_nbfc.py, tests/test_batch5_bank.py |
| G6 | Separate life and general insurer taxonomies (policyholders' / shareholders' accounts) | DONE | X62, X63; parsers/irdai_insurance.py; tests/test_batch6_insurers.py. Also Ind AS 117 insurers (X64, INDAS_INSURANCE) |
| G7 | Integrated Filing XBRL applies from quarters ended Dec 2024 / Mar 2025 | CONFLICTS_WITH_EVIDENCE | R12 (contradicted), X38; scope.py (C9). Integrated Filing starts at Mar-2025; Dec-2024 results are legacy files |
| G15 | Route each filing by XBRL namespace into separate parsers (5 proposed) | DONE | arch 7.1; X1; tests/test_indas_corp_parser.py. 7 profiles built; unknown namespace -> PARSE/UNKNOWN_TAXONOMY |
| G22 | Company override table (symbol, forced_profile, custom_revenue_tags) for 3-5% conglomerates | OUT_OF_SCOPE_BY_DECISION | arch 7.1 ('never guess the profile from the company'); invariant 5. Audited scope-override / archetype-override exist instead |
| G23 | Confirm XBRL has no previous-quarter values *(owner)* | DONE | X2; tests/test_xbrl_fixture_facts.py |
| G26 | XBRL contexts OneD / FourD / OneI / FourI; OneD = 6M for half-yearly SME filers | DONE | X2; invariant 6; SHP16. Context ids are never trusted as period labels |
| G249 | ESOP charges sit only in cash flow; contract liabilities and treasury cash distort legacy ratios | DONE | X68; label rules CONTRACT_LIABILITIES_*, ADVERTISING |
| G267 | Valuation archetype per company (industrial, lending, insurance, new-gen) | DONE | C21; reference/valuation_archetypes.csv; archetype-override; tests/test_batch7_newgen.py |
| G290 | Calculation-linkbase auto-mapping of unknown tags | OUT_OF_SCOPE_BY_DECISION | invariant 9 |
| G299 | Review: banks report interest earned / expended and provisions, not NBFC tags *(owner)* | DONE | X21, X58; parsers/igaap_bank.py; tests/test_batch5_bank.py |
| G300 | Review: insurers are not on Ind AS *(owner)* | CONFLICTS_WITH_EVIDENCE | X64, X90 (Star Health and Go Digit file Ind AS 117). True only for IRDAI-format insurers |
| G301 | Review: SME companies file Indian GAAP; no parser *(owner)* | OUT_OF_SCOPE_BY_DECISION | C7; R4 (UNVERIFIED) |
| G333 | entity_master carries accounting_profile and valuation_archetype | OUT_OF_SCOPE_BY_DECISION | invariant 5 (profile per filing); C18, C21 (per as-of) |
| G339 | Bank profile maps casa_pct from XBRL | CONFLICTS_WITH_EVIDENCE | X23, X35 (CASA not tagged). CASA goes to supplemental_kpis |
| G340 | Insurer persistency ingested separately from presentations | CONFLICTS_WITH_EVIDENCE | X62 (PersistencyRatio13ThMonth...61ThMonth filed). Filed value wins |
| G341 | Insurer solvency ratio from XBRL | DONE | X65 SOLVENCY_PERCENT_SCALING; tests/test_batch6_insurers.py |

## Normalization (26)

| id | requirement | status | where / next step |
|---|---|---|---|
| G1 | Align NSE XBRL results to one consistent treatment for every company (Screener-like, but rule-based) *(owner)* | DONE | statements/quarterly.py (arch 14b); C11; tests/test_screener_parity.py. Uniform canonical rules; Screener divergences are reported, never imitated |
| G3 | A complete database that matches what other websites show *(owner)* | DONE | tests/test_screener_parity.py (34 exports, S1-S23). Parity on Data Sheet rows; unexplained residuals pinned (S11, S13) |
| G8 | Screener uses a 'Financial template' (Financing Profit) for lenders and a corporate template otherwise | CONFLICTS_WITH_EVIDENCE | S5 (NBFC rows have the corporate shape), S4 (banks). True for banks only |
| G9 | Screener deducts excise duty from sales (net sales) | DONE | X40 EXCISE_DUTY label rule; S1; tests/test_label_rules.py |
| G10 | Screener strips exceptional items out of core earnings, PE and ROCE | CONFLICTS_WITH_EVIDENCE | S2 (Other Income includes exceptional items); S22 (Screener ROCE uses PBT + interest). We keep exceptional items as a sub-row of Other Income (arch 14b) |
| G11 | Screener moves director remuneration into employee cost | DOCUMENTED_PLANNED | R14 (UNVERIFIED, what would verify it recorded). Quarterly XBRL has no director-remuneration split |
| G12 | Screener folds current debt maturities and Ind AS 116 lease liabilities into Borrowings | DONE | S10; statements/balance_sheet.py; R5 (current maturities) UNVERIFIED. Borrowings = borrowings + labelled leases (label rules X39, X72) |
| G14 | Matching Screener digit-for-digit from quarterly XBRL alone is a trap (it uses annual-report notes) | DONE | S13 (annual P&L != sum of quarters); residuals pinned in tests/test_screener_parity.py. Screener's source itself stays UNVERIFIED |
| G18 | Corporate profile: Sales = revenue - excise; Opex = expenses - finance - D&A - excise; EBITDA excludes other income and exceptional items | DONE | arch 8 (rev_ops, ebitda), 14b; tests/test_fundamentals.py, tests/test_screener_parity.py |
| G19 | Lending profile: revenue = interest + fees + FV gains + other; financing profit; profit_basis = FINANCING flag | DONE | arch 10.5 (nii_ttm, ppop_ttm); C21 valuation_archetype; tests/test_batch4_nbfc.py, tests/test_batch5_bank.py. Flag is valuation_archetype = FINANCIAL_LENDING |
| G20 | Insurance profile: revenue = net premium earned + policyholders' investment income; operating surplus | DONE | arch 10.6; S6, S7; tests/test_batch6_insurers.py. Uses filed subtotals (NetSurplusDeficit, OperatingProfitOrLoss) |
| G53 | Never multiply a demerged company's historical revenue / PAT by the COA ratio | DONE | invariant 8 |
| G70 | Unit detection by ratio to XBRL: lakhs, crores, thousands | CONFLICTS_WITH_EVIDENCE | X4 (a corporate filing rounded in Millions); arch 7.3. Omits millions |
| G71 | Anchor tolerance of +-0.01% / +-0.02 | CONFLICTS_WITH_EVIDENCE | X5, X93; arch 7.3. Tolerance must come from the rounding unit |
| G72 | Vertical P&L identities: Income - Expenses = PBT; PBT - Tax = PAT | DONE | gate G3; X9, X42; tests/test_xbrl_fixture_facts.py, tests/test_consolidated_chain.py. Applied to XBRL |
| G132 | Granular cost structure: materials, power & fuel, freight, subcontracting, employee cost | DONE | X50 (POWER_AND_FUEL, FREIGHT); arch 14b-1; tests/test_label_rules.py. Subcontracting stays in other expenses |
| G209 | Compare quarters by calendar period-end dates (Dec / Sep fiscal-year MNCs) | DONE | invariant 6; arch 6.1; X82, X87; tests/test_x87_stale_context_dates.py |
| G272 | Scope continuity: TTM on consolidated only when 4 consolidated quarters exist; else standalone | DONE | arch 6.4; C18; tests/test_scope_policy.py |
| G273 | Semi-annual cash-flow / balance-sheet bridge: TTM CFO = H1 + FY_prev - H1_prev | DONE | arch 6.5; cf_as_of / bs_as_of; tests/test_fundamentals.py, tests/test_cash_conversion.py |
| G274 | SME 6M to mainboard 3M cadence: gate on period_months | DONE | invariant 6; arch 6.1. SME itself excluded (C7) |
| G302 | Review: current maturities sit inside short-term borrowings since Schedule III FY22 *(owner)* | DONE | arch 8 total_debt uses filed BorrowingsCurrent; R5 (UNVERIFIED) |
| G303 | Review: leases must not be counted twice *(owner)* | DONE | arch 8 total_debt (leases once); X39; tests/test_label_rules.py |
| G304 | Review: unlevered FCF add-back depends on where interest paid is classified *(owner)* | DONE | arch 8 fcff; X14 |
| G307 | Review: 15-month transition years; period_months beyond 12 *(owner)* | DONE | period_months 1..18; X87; E11; tests/test_x87_stale_context_dates.py |
| G310 | Review: unit table omits INR millions; tolerance must follow the rounding unit *(owner)* | DONE | arch 7.3; X4, X5 |
| G317 | Review: gross profit undefined (no COGS line) *(owner)* | DONE | arch 8 cogs / gross_profit; C6 |

## Metric (105)

| id | requirement | status | where / next step |
|---|---|---|---|
| G94 | Bhavcopy close, 52-week high/low | DONE | close, high_52w, low_52w, dist_52w_high, dist_52w_low (252 adjusted closes); high/low since data start (not all-time, C9); tests/test_features.py, tests/test_features_price.py |
| G95 | VWAP from the full bhavcopy | DONE | vwap = turnover_inr / volume, equal to the full bhavcopy's AVG_PRICE on every row of both committed files (P16); vwap_20d on today's share basis; tests/test_features_price.py |
| G110 | Live PE, PB, EV/EBITDA from close x shares + net debt + TTM | DONE | arch 8, 10.1; tests/test_features.py |
| G111 | ROCE, ROE, working-capital days, ROIC | DONE | roce, roe, roic, working_capital_days; tests/test_features.py, tests/test_batch9_annual.py |
| G115 | Order-book-to-sales ratio | CONFLICTS_WITH_EVIDENCE | No order-book (backlog) element anywhere: `docs/tag_registry.yaml` and every committed XBRL fixture (results, annual, Reg. 30) were searched 2026-11-16 for order book / backlog / unexecuted order / remaining performance obligation; the only order elements are per-order Reg. 30 fields (`AmountOfTheOrdersOrContracts`, E3), already `order_wins_90d` / `order_value_90d` (G114). Catalogue B8.11 NOT POSSIBLE; dropped |
| G117 | Automated forensic red-flag score from Reg. 30 events | DONE | batch G (features_extra): rf_auditor_resignation_90d, rf_kmp_resignations_90d, rf_fraud_or_default_90d, rf_litigation_90d, rf_audit_qualified, rf_pledge_increase_qoq + litigations / allotments / fund-raising 90d counts, separate columns never summed (arch 10.2); penalties wait for E12; tests/test_features_extra.py |
| G133 | Screens for sensitivity to crude, power or freight inflation | DONE | batch G: material / employee / other-expense / power & fuel / freight / A&P shares of sales, latest quarter and last FY (X50, X68, X74); tests/test_features_extra.py |
| G134 | Capex, CWIP -> FCF, CFO/EBITDA, CWIP / gross block | DONE | arch 8; C19; X71; tests/test_cash_conversion.py, tests/test_batch9_annual.py |
| G152 | Revision velocity / QoQ operating-margin acceleration | DONE | batch G: opm_acceleration_pp = [OPM(Q) - OPM(Q-4)] - [OPM(Q-1) - OPM(Q-5)]; revision velocity (estimates) stays out (no forecasts); tests/test_features_extra.py |
| G155 | 50 / 200 DMA | DONE | dma50, dma200 and previous-day values, price_to_dma50/200; tests/test_features.py, tests/test_features_price.py |
| G156 | RSI(14) | DONE | rsi_14, rsi_14_prev (Wilder, adjusted closes); tests/test_features_price.py |
| G157 | ATR% | DONE | atr_14_pct (Wilder ATR(14) on adjusted H/L/C / close); tests/test_features_price.py |
| G158 | Relative strength vs Nifty 500 | DONE | rs_nifty500_3m/6m/12m and beta_1y_nifty500 on index_ohlcv (IDX9); NULL until the index closes for the window are loaded; tests/test_features_price.py |
| G159 | 5D / 20D delivery spikes | DONE | deliv_avg_5d/20d, delivery_velocity; tests/test_features.py |
| G160 | Piotroski F-score | DONE | C23; tests/test_batch9_annual.py |
| G161 | Beneish M-score | DONE | C23; tests/test_batch9_annual.py |
| G162 | Altman Z-score | DONE | altman_z_dd (Z''); tests/test_fundamentals.py. NULL for financials |
| G167 | Valuation: market cap, price, PE, PB, EV/EBITDA | DONE | tests/test_features.py |
| G168 | PEG ratio | DONE | peg = pe_core / (100 x core profit YoY of the latest quarter), TTM-on-TTM core growth once 8 quarters are in scope (C9); batch D, features_gems; docs/hidden_gems.md; tests/test_features_gems.py |
| G169 | Dividend yield | DONE | dividend_yield_pct: trailing-365-day accepted dividends (the TR ledger, C2) restated to today's share basis / close; NULL before a full window (C9) or while a gap freezes prices; tests/test_owner_items_qoq_dividend_promoter.py |
| G170 | FCF yield | DONE | fcff_yield (unlevered); tests/test_phase1_fixes_b.py. Equity form: equity_fcf_yield = fcf_ttm / market cap, price_to_fcf (features_bs, batch C); tests/test_balance_sheet_cash_flow_family.py |
| G171 | Sales growth and profit growth YoY | DONE | sales_growth_yoy, profit_growth_yoy; tests/test_features.py. 8 quarters |
| G172 | Sales / profit growth 3Y and 5Y, EPS growth 3Y | DONE | history-gated (C9, owner rule: built, NULL until history): sales_growth_{3,5,7,10}y_pct, profit_growth_*, operating_profit_growth_*, eps_growth_* (features_pl; FY CAGR via fundamentals.cagr(min_periods_required = 4 x years + 1), EPS restated by later EPS factors); 3Y switches on with FY28 (~May 2028). tests/test_period_pl_family.py (NULL on fixtures, values on synthetic FY25-FY35) |
| G173 | QoQ sales % and QoQ profit % | DONE | sales_growth_qoq_pct, profit_growth_qoq_pct (owners' profit, NULL on a base <= 0); same scope book; tests/test_owner_items_qoq_dividend_promoter.py, tests/test_phase1_phase2_e2e.py |
| G174 | ROCE, ROE, ROIC, OPM, debt/equity, working-capital days, CFO/EBITDA | DONE | tests/test_features.py, tests/test_cash_conversion.py |
| G175 | OPM last year, NPM, interest coverage | DONE | opm_last_year_pct (= the last fiscal year's OPM since features 2026.11.15-4A, Screener's meaning; the same-quarter value built in -3 is now opm_preceding_year_quarter_pct), npm_pct (TTM owners' profit / sales_ttm), interest_coverage (TTM (PBT + finance costs) / finance costs; NULL for lenders, insurers); tests/test_owner_items_qoq_dividend_promoter.py. Filed DSCR / ISCR (X41) not exposed; OPM last year NULL on every committed company until a same-quarter pair exists |
| G176 | OPM 5Y | DONE | history-gated: opm_5y_pct, opm_10y_pct (mean FY OPM; NULL until FY29 / FY34, C9); features_pl; tests/test_period_pl_family.py |
| G177 | Promoter holding, pledge %, FII, DII holding | DONE | arch 10.7; tests/test_batch8_shareholding.py |
| G178 | Change in promoter holding | DONE | promoter_holding_change_qoq_pp (adjacent Reg. 31 quarters, percentage points); RELIANCE 2025-03-31 -> 2025-06-30 = -0.04 pp; tests/test_owner_items_qoq_dividend_promoter.py |
| G179 | MF holding change 1M (AMFI) | DOCUMENTED_PLANNED | F26 |
| G180 | Insider net buy 3M (PIT / SDD) | DOCUMENTED_PLANNED | F11, F13 |
| G181 | Reg. 30 red-flag count | DONE | order/kmp/auditor/fraud 90-day counts; tests/test_batch10_events.py |
| G182 | Returns 1M/3M/6M/12M, price to 50/200 DMA, distance from 52W high | DONE | arch 10.7; also return_1d/1w and return_3y/5y/7y/10y (NULL until the bars exist, C9); tests/test_features.py, tests/test_features_price.py |
| G183 | Average delivery % over 20 days | DONE | deliv_pct_avg_20d (mean of deliv_qty / volume, = DELIV_PER / 100, P16), deliv_pct; tests/test_features_price.py |
| G184 | F&O PCR column | DOCUMENTED_PLANNED | F16 |
| G194 | Ace investor graph across Reg. 31 >1% holders, PIT/SAST and bulk/block deals | DOCUMENTED_PLANNED | SHP12 (shareholding_major_holders); F14. Name normalisation not designed |
| G198 | Valuation bands: current PE / PB / EV-EBITDA percentile vs own history | DONE | pe_percentile, ev_ebitda_percentile (C20); tests/test_valuation_bands.py. P/B, P/S and EV/Sales bands: pb_percentile, price_to_sales_percentile, ev_to_sales_percentile (batch I, tests/test_features_more.py); 5Y/10Y windows NULL under C9 |
| G199 | Discount / premium to basic-industry median | DONE | pe_/pb_premium_to_basic_industry and _to_industry (own / median - 1); NSE classification F30, IC1-IC3, C25; features_peers.py; tests/test_batch_h_industry_peers.py |
| G200 | Reverse DCF implied growth using the live 10Y G-Sec | DONE | reverse_dcf_implied_g (C20, WACC fixed 12%); tests/test_valuation_bands.py. Live yield needs F25 |
| G201 | Capital-allocation scorecard (incremental ROIC, buyback yield, 5Y dilution) | DONE | view capital_allocation_scorecard (schema.sql, after the column upgrade): batch C / G components side by side, never one score; tests/test_features_extra.py |
| G202 | Dividend payout % | DONE | dividend_payout_pct = trailing dividends per share / eps_ttm, NULL if EPS <= 0; arch 10.7; tests/test_owner_items_qoq_dividend_promoter.py. No committed company has both an accepted dividend and a TTM EPS yet |
| G203 | YoY sales-growth acceleration (current YoY - prior-quarter YoY) | DONE | growth_acceleration_pp (quarter form: sales YoY latest - preceding quarter); TTM form waits for 9 quarters (C9); batch D; tests/test_features_gems.py |
| G204 | Operating-margin expansion vs the same quarter last year | DONE | opm_change_yoy_pp (quarter OPM - same quarter last year, NULL for lenders); batch D; tests/test_features_gems.py |
| G205 | Sector earnings breadth during results season | DONE | `industry_earnings_breadth` (+ `_n`): share of the NSE industry's companies reporting its latest quarter with core profit YoY > 0, >= 3 companies, refresh step over the stored day (batch I, features_more.py); tests/test_features_more.py |
| G207 | Liquidity: 20D median traded value; bid-ask / circuit-lock days | MISSING | 20D median traded value built (turnover_median_20d; tests/test_features_price.py); bid-ask is in no ingested EOD file; circuit-lock days wait for an F20 price-band fixture |
| G208 | Market regime / breadth: % of Nifty 500 above 50/200 DMA, 52W high/low ratio, advance-decline | DONE | market_breadth table, one row per materialised day from the in_nifty500 rows (arch 10.7); tests/test_features_price.py |
| G214 | 20-30 distinctive ratios for all companies *(owner)* | DONE | arch 10 catalogue built (batches B-J, gems, forensic scores; Piotroski / Beneish filled where two annuals exist). Not built by evidence rule: Screener "Price to Quarterly Earning" (definition UNVERIFIED), filed ISCR / DSCR (implausible filed values) |
| G215 | Incremental ROIC (3Y/5Y) | DONE | incremental_roic_1y (on now, FY26 vs FY25), incremental_roic_3y / _5y (history-gated: FY28 ~May 2028 / FY30); ΔNOPAT / Δ invested capital, NULL when ΔIC <= 0; features_bs; tests/test_balance_sheet_cash_flow_family.py |
| G216 | Reinvestment rate | DONE | reinvestment_rate = FY (capex - D&A + Δ non-cash working capital) / NOPAT; features_bs; tests/test_balance_sheet_cash_flow_family.py |
| G217 | Cash ROIC (CROIC) | DONE | croic; tests/test_fundamentals.py |
| G218 | Total shareholder yield (dividends + net buybacks - equity issued) | DONE | shareholder_yield = TTM (dividends_paid + li_payments_to_acquire_or_redeem_entitys_shares - share_issue_proceeds) / market cap over the CFO bridge's filed periods (G316 formula); buyback_yield; features_bs; tests/test_balance_sheet_cash_flow_family.py |
| G219 | 5Y net equity dilution % | DONE | dilution_5y (history-gated, NULL until the Reg. 31 pattern 5 years back is in scope, ~Apr 2030) and dilution_1y; Reg. 31 counts restated to today's share basis by later EPS factors; features_bs; tests/test_balance_sheet_cash_flow_family.py |
| G220 | Incremental asset turnover (3Y) | DONE | batch G: incremental_asset_turnover_3y (d FY sales / d net block), NULL until FY28 (C9); tests/test_features_extra.py |
| G221 | Return on tangible equity (ROTE) | DONE | rote; tests/test_batch9_annual.py |
| G222 | Sloan accrual ratio | DONE | sloan_accrual (C19); tests/test_cash_conversion.py |
| G223 | EBITDA-to-CFO conversion | DONE | cfo_to_ebitda (pre-tax CFO, C19); tests/test_cash_conversion.py. FY forms cfo_to_ebitda_last_year / _preceding_year and 3-FY cfo_to_ebitda_3y (history-gated); features_bs; tests/test_balance_sheet_cash_flow_family.py |
| G224 | FCF-to-net-income conversion (3Y) | DONE | fcf_to_pat (TTM, C19); tests/test_cash_conversion.py. 3Y form fcf_conversion_3y (3-FY FCF / owners' profit; history-gated, FY27 ~May 2027); features_bs; tests/test_balance_sheet_cash_flow_family.py |
| G225 | Receivables-to-sales divergence | DONE | receivables_sales_divergence; tests/test_cash_conversion.py |
| G226 | Capex-to-depreciation | DONE | capex_to_depreciation; tests/test_batch9_annual.py |
| G227 | CWIP-to-gross-block | DONE | cwip_to_gross_block (X71); tests/test_batch9_annual.py |
| G228 | Degree of operating leverage | DONE | dol (C19); tests/test_cash_conversion.py |
| G229 | Gross-to-operating margin spread | DONE | gross_ebitda_spread (C6, C19); tests/test_cash_conversion.py |
| G230 | R&D and royalty intensity | DONE | rnd_and_royalty_intensity (X73); tests/test_batch9_annual.py. Mostly NULL: R&D is text |
| G231 | Working-capital intensity | DONE | working_capital_intensity; tests/test_cash_conversion.py |
| G232 | Other-income dependency (OI / PBT) | DONE | other_income_to_pbt; tests/test_features.py |
| G233 | Net debt (incl. leases) / 3Y average FCF | DONE | net_debt_to_fcf (TTM FCF); tests/test_cash_conversion.py. 3Y form net_debt_to_fcf_3y (history-gated, FY27 ~May 2027); features_bs; tests/test_balance_sheet_cash_flow_family.py |
| G234 | Effective cost of debt | DONE | cost_of_debt; tests/test_cash_conversion.py |
| G235 | Contingent liabilities / net worth | DONE | contingent_liabilities_to_net_worth (X73); tests/test_batch9_annual.py |
| G236 | RPT leak % (purchases + loans + royalties / revenue) | DONE | batch J: X113, C27; parsers/rpt.py -> `related_party_transactions` (per counterparty, Reg. 34 annual schedule), features_rpt.py `rpt_leak_pct`, `rpt_purchases_to_sales`, `rpt_royalty_to_sales`, `rpt_loans_given_to_net_worth`; tests/test_batch_j_rpt_share_capital.py. Royalties in a catch-all expense with a "refer below" nature are not counted (floor) |
| G237 | Composite forensic score combining Piotroski, Beneish and Altman | OUT_OF_SCOPE_BY_DECISION | arch 10.2 (separate columns, never summed) |
| G238 | Unlevered FCF yield (adds back interest x (1 - t)) | DONE | fcff_yield, per-filing interest classification (X14); tests/test_phase1_fixes_b.py |
| G239 | Reverse-DCF implied 5Y growth | DONE | C20; tests/test_valuation_bands.py |
| G240 | 5Y EV/EBITDA band percentile (20 quarters) | DONE | ev_ebitda_percentile (C20, >= 4 prior quarters); ev_ebitda_percentile_20q (last 20 prior quarter-ends, all > 0; history-gated, ~2031; batch C); tests/test_balance_sheet_cash_flow_family.py |
| G241 | Institutional absorption rate (MF + FII shares vs 90D median volume) | DONE | batch G: inst_shares_change_qoq / volume_median_90d = institutional_absorption_90d (FII + DII, adjacent quarters; NULL after a share-count action); monthly MF form is Phase 3; tests/test_features_extra.py |
| G242 | Float-adjusted delivery velocity | DONE | delivery_velocity, float_turnover_pct; tests/test_features.py. Formula corrected (no float multiplication) |
| G243 | Guardrail: NULL on non-positive denominators | DONE | arch 10 (any ratio with denominator <= 0 is NULL); tests/test_cash_conversion.py |
| G244 | Guardrail: expose raw numerator and denominator columns | DONE | batch G: pe / roe / roce / ev_ebitda / opm _numerator and _denominator columns; tests/test_features_extra.py |
| G245 | Guardrail: NULL industrial ratios for banks, NBFCs, insurers | DONE | arch 9, 10.5, 10.6; tests/test_batch4_nbfc.py, tests/test_batch6_insurers.py |
| G246 | Financial cohort metrics: NIM, cost-to-income, provision coverage, P/B | DONE | arch 10.5; tests/test_batch5_bank.py, tests/test_batch4_nbfc.py. PCR NULL for NBFCs (X54) |
| G247 | Smooth incremental ratios over 3Y / 5Y windows | DONE | history-gated (C9): incremental_roic_3y / _5y (FY28 / FY30), fcf_ / cfo_ / cfi_{3,5,7,10}y sums, fcf_conversion_3y, cfo_to_ebitda_3y, net_debt_to_fcf_3y; features_bs; tests/test_balance_sheet_cash_flow_family.py |
| G248 | New-generation businesses need different ratios *(owner)* | DONE | arch 10.8; C21; tests/test_batch7_newgen.py |
| G250 | EV / gross profit | DONE | ev_to_gross_profit; tests/test_batch7_newgen.py |
| G251 | Ex-cash PE | DONE | ex_cash_pe; tests/test_batch7_newgen.py |
| G252 | EV / billings | DONE | ev_to_billings; tests/test_batch7_newgen.py |
| G253 | EV / ESOP-adjusted EBITDA | DONE | ev_to_esop_adj_ebitda; tests/test_batch7_newgen.py |
| G254 | Price / operating cash flow | DONE | price_to_cfo; tests/test_batch7_newgen.py |
| G255 | Rule of 40 | DONE | rule_of_40; tests/test_batch7_newgen.py |
| G256 | Marketing efficiency (magic-number proxy) | DONE | batch G: marketing_efficiency_latest_quarter / _last_year (Eternal FY26 pinned); tests/test_features_extra.py |
| G257 | Gross / contribution margin expansion (bps YoY) | DONE | batch G: gpm_change_yoy_pp (C6 guard; DSL 'Gross margin expansion bps'), contribution_margin_change_yoy_pp (KPI); tests/test_features_extra.py |
| G258 | Advertising and promotion intensity % | DONE | batch G: ad_promo_latest_quarter_pct / ad_promo_last_year_pct (ADVERTISING rule X68, Reg. 34 element X74); tests/test_features_extra.py |
| G259 | Billings growth vs revenue growth | DONE | billings_growth_pct; tests/test_batch7_newgen.py |
| G260 | Negative working-capital float % | DONE | neg_working_capital_float_pct; tests/test_batch7_newgen.py |
| G261 | Net burn multiple | DONE | net_burn_multiple; tests/test_batch7_newgen.py |
| G262 | Cash runway (months) | DONE | cash_runway_months; tests/test_batch7_newgen.py |
| G263 | ESOP-adjusted free cash flow | DONE | esop_adj_fcf; tests/test_batch7_newgen.py |
| G265 | EV / GOV | DONE | batch G: gov_ttm (12-month KPI or 4 quarters), ev_to_gov; tests/test_features_extra.py |
| G266 | ARPU and MTU growth | DONE | batch G: KPI names arpu (INR), mtu (COUNT) in parsers/kpis.py; arpu, mtu, arpu_ / mtu_ / gov_growth_yoy_pct; tests/test_features_extra.py |
| G269 | Insurance archetype metrics: P/EV, VNB margin, combined ratio | DONE | combined_ratio (X66), vnb_margin, embedded_value (supplemental); tests/test_batch6_insurers.py. P/EV itself not built |
| G270 | P/EV for life insurers | DONE | batch G: price_to_embedded_value; tests/test_features_extra.py |
| G275 | Dual-ISIN securities (partly paid, DVR): sum market cap over all linked ISINs | OUT_OF_SCOPE_BY_DECISION | owner 2026-11-19 "Ignore DVR": each listed security keeps its own market cap |
| G276 | Organic vs inorganic perimeter flag (business-combination outflows, acquisition filings) | DONE | C26; `inorganic_growth_flag` from the business-combination cash outflow (features_extra.py, batch G); tests/test_features_extra.py (test_business_combination_outflows_and_the_inorganic_flag, test_inorganic_flag_is_three_valued). Reg. 30 acquisition events are not an input (no event type parsed) |
| G278 | Standalone-to-consolidated profit leakage | DONE | `profit_leakage_pct`, `profit_leakage_latest_quarter_pct`, `standalone_pat_ttm` (features_extra.py, batch G); tests/test_features_extra.py (test_reliance_profit_leakage_latest_quarter, test_ttm_profit_leakage) |
| G314 | Review: forensic scores have different scales; never sum; Altman not for financials *(owner)* | DONE | arch 10.2 |
| G315 | Review: delivery velocity must divide by free float, not multiply *(owner)* | DONE | arch 10.3 (float_turnover_pct) |
| G316 | Review: shareholder yield subtracts issuance twice *(owner)* | DONE | shareholder_yield subtracts gross share issuance once and adds gross buybacks (TTM cash flow / market cap); features_bs; tests/test_balance_sheet_cash_flow_family.py |

## Corporate-action (22)

| id | requirement | status | where / next step |
|---|---|---|---|
| G33 | Automate corporate-action adjustment (mergers, demergers like Tata Motors, splits) with zero human intervention *(owner)* | OUT_OF_SCOPE_BY_DECISION | invariant 9; D-6; C4; CA12. Automatic for parsed purposes and named rules; unknowns quarantine |
| G34 | Adjust per-share series (prices, volume, EPS) by ex-date factors; never multiply absolute financials | DONE | invariant 8; arch 11.1; tests/test_corp_actions.py |
| G37 | Directed lineage table (parent, child, relation, effective date, swap ratio) | DONE | arch 11.7; CA14; `entity_lineage` (append-only, deterministic ids), lineage.py, admin.py `lineage add/amend/coa/retire/load`; reference/entity_lineage.csv (TMCV from TMPV); tests/test_lineage.py |
| G38 | Corp-action ledger keyed by (entity, ex_date); recompute cumulative backward factors on any change | DONE | corp_actions; rebuild-market; tests/test_corp_actions.py, tests/test_phase1_fixes_a.py |
| G41 | Split factor F = Y/X (face value X to Y) | DONE | arch 11.1; tests/test_corp_actions.py |
| G42 | Bonus A:B factor F = B/(A+B) | DONE | arch 11.1; CA5; tests/test_corp_actions.py |
| G43 | Rights A:B at P factor (B*C + A*P) / ((A+B)*C) | DONE | arch 11.1; CA4; tests/test_corp_actions.py |
| G44 | Historical volumes divided by F | DONE | arch 11.1 |
| G45 | Extraordinary dividends > 5% of prior close adjust prices | OUT_OF_SCOPE_BY_DECISION | C2; invariant 8; arch 15 (deliberate divergence). Dividends feed the total-return index only |
| G46 | Overnight gap check: > 25% move on an ex-date; verify parsed factor within +-5% | DONE | C4 (unconditional, 10%, every day); arch 11.3-11.4; tests/test_pipeline.py, tests/test_ca12_market_moves.py. Built in the corrected form |
| G47 | Missing or mismatched factor: derive F automatically from the pre-open price | OUT_OF_SCOPE_BY_DECISION | invariant 9; C4. GAP quarantine freezes the adjusted series; only demergers use the observed gap |
| G48 | Demerger parent factor = special pre-open price / prior close | DONE | C3; P7; tests/test_corp_actions.py (test_demerger_factor_is_observed_gap). Uses the ex-date open |
| G50 | Apply the demerger factor to historical EPS | OUT_OF_SCOPE_BY_DECISION | invariant 8; arch 11.1 (eps_factor 1.0) |
| G51 | Cost-of-acquisition watcher: parse COA %, check they sum to 100%, keep for tax cost basis | DONE | arch 11.7; `entity_lineage.coa_pct` / `parent_coa_pct`, `lineage.coa_split` (parent + children = 100), cost fraction in `convert_position`; tests/test_lineage.py. Entered by `lineage coa` with an evidence URL: COA is announced as PDF, no source verified, so parsing is BLOCKED (watcher = G62). R7 stays UNVERIFIED and is not stored |
| G56 | Merger: delisting circular sets status MERGED, merged_into and swap_ratio on the target | DONE | arch 11.7; `lineage add --relation MERGED_INTO --ratio A:B --evidence-url <circular>` sets `entity_master.status = MERGED`, `merged_into`, `inactive_date`; retire reverts; tests/test_lineage.py. Automatic circular parsing BLOCKED: no merger purpose in the corp-action feed and no circular fixture (CA14) |
| G57 | Merger: acquirer prices not back-adjusted (factor 1.0) | DONE | arch 11.1, 11.7; lineage never writes corp_actions; tests/test_lineage.py::test_merger_marks_target_and_never_adjusts_prices (acquirer and target adjusted series unchanged) |
| G61 | Ex-date adjuster verifies the adjusted overnight gap within +-15% | DONE | arch 11.3 (+-10%) |
| G62 | Hourly keyword watcher for 'Cost of Acquisition' and 'Swap Ratio' in announcement PDFs | MISSING | not in docs. PDF text; no source verified |
| G97 | Corporate actions with ex/record dates, dividend per share, bonus ratios, FV changes | DONE | F03; P12; CA1-CA11; tests/test_nse_corp_actions.py. Reg. 30 OUTCOME XBRL vaulted raw (E2) |
| G305 | Review: EPS is adjusted only for splits, bonuses and the rights bonus element *(owner)* | DONE | invariant 8; arch 11.1; tests/test_corp_actions.py |
| G318 | Review: gap auditor must run every day, not only on ex-dates *(owner)* | DONE | C4; arch 11.4; tests/test_pipeline.py |
| G338 | corp_actions with audit status, special pre-open price, COA %, source blob | DONE | corp_actions (status, observed_gap, coa_pct, source_filing_id) |

## PIT/restatement (25)

| id | requirement | status | where / next step |
|---|---|---|---|
| G13 | Screener overwrites prior periods after restatements / demergers | OUT_OF_SCOPE_BY_DECISION | C12; invariant 4; S9 (OBSERVED). We never backdate: restated history is visible only from its own filing |
| G17 | Store filing date with period end so as-reported and later restated values both survive | DONE | fact_observations.visible_from_ts; arch 6.3; tests/test_x83_visibility.py |
| G21 | Detect restatements by comparing a new filing's comparative quarter with the stored one; supersede the old row | CONFLICTS_WITH_EVIDENCE | X2, X3; invariant 1. No comparative columns exist; rows are never superseded in place |
| G24 | Confirm whether corrections / restatements are filed as XBRL *(owner)* | DONE | E9, X51, X57, X63; filing_revisions; tests/test_batch10_edge_cases.py. Same-period revisions are XBRL; retrospective restatements are not (X3) |
| G27 | Same-period correction: ingest the latest submission per (symbol, period, scope) | DONE | E9; arch 6.3; tests/test_x83_visibility.py. Latest-wins only as of a date (invariant 4) |
| G28 | Retrospective restatement: take restated comparatives from the quarterly PDF or the annual report | DONE | Decision E (2026-11-15): no PDF recovery of restated comparatives; quarters stay as first published (PIT), TTM uses the restated YTD bridge with `restatement_suspected` (X106); PDFs only for audited error corrections (X107) |
| G35 | Never overwrite history: immutable raw tables plus a computed adjustment layer | DONE | invariant 1; arch 4; tests/test_foundations.py |
| G54 | Parent restates comparatives (Ind AS 105); a PDF comparator promotes the continuing-operations series | OUT_OF_SCOPE_BY_DECISION | arch 7.6, 15 (no PDFs); X80 withholds TTM over the re-presented year |
| G55 | Spun-off baseline from carve-out comparatives in the first PDF / Information Memorandum | OUT_OF_SCOPE_BY_DECISION | C12. History before the first own filing does not exist for PIT reads |
| G63 | Restatement checksums: continuing + discontinued = old PAT; merged PAT = A + B; restated YTD = sum of quarters | OUT_OF_SCOPE_BY_DECISION | arch 7.6, 15 (no PDFs). The A + B check ignores eliminations (owner-forwarded review) |
| G64 | Scanned quarterly PDFs and vision LLMs misread digits and units; they must never corrupt the database *(owner)* | DONE | arch 7.6; invariant 9. No PDF number enters canonical tables |
| G65 | Skip PDFs for most filings: flag only where YTD != sum of quarters | DONE | X80; audit-ytd; tests/test_x80_ytd_identity.py. Not a Q4 restatement detector (arch 6.2); a break withholds TTM |
| G66 | About 95% of filings satisfy the YTD identity | DONE | X80 (94% of 8,081 comparisons tie). Claim verified on live data |
| G67 | Also flag restatement when ProfitLossFromDiscontinuedOperations != 0 | DONE | X108; FactBook.restatement_triggers (last 5 quarter ends); tests/test_restatement_triggers.py (Reliance Power Q4 FY25) |
| G68 | Also flag restatement when a demerger / merger effective date is logged | DONE | X109; MERGER / DEMERGER ledger ex-date in the last 5 quarters (issuer or related entity); tests/test_restatement_triggers.py (Tata Motors CV demerger) |
| G69 | XBRL anchor locking: PDF current columns must match XBRL OneD / FourD before restated columns are trusted | OUT_OF_SCOPE_BY_DECISION | Decision E (2026-11-15): no PDF extraction of restated quarters, so there are no PDF columns to anchor; PDFs only for audited corrections (decision B, X107), which already need two agreeing reads. arch 7.6 |
| G73 | Safe failure: if any check fails, keep the verified XBRL numbers | DONE | invariant 9 |
| G149 | Bitemporal rows: period end + broadcast timestamp; queries filter broadcast <= as-of | DONE | invariant 4; arch 6.3; tests/test_x83_visibility.py |
| G150 | Broadcast timestamp is embedded in XBRL / CSV metadata | CONFLICTS_WITH_EVIDENCE | X83, A7, SHP6; arch 6.3. Comes from the listing at fetch time |
| G293 | Review: PIT key must include visibility; append-only facts with as-of queries *(owner)* | DONE | fact_observations PK (filing_id, parser_version, ...); arch 6.3; tests/test_x83_visibility.py |
| G294 | Review: Q4 Reg. 33 and Reg. 34 annual 12-month rows must not collide; define precedence *(owner)* | DONE | arch 6.3 (annual supersedes from its own visibility); tests/test_batch9_annual.py |
| G309 | Review: YTD identity misses prior-year re-presentations and holds trivially in Q4 *(owner)* | DONE | arch 6.2; X80 |
| G311 | Review: capture broadcast time at fetch time (not in XBRL or bhavcopy) *(owner)* | DONE | X83; arch 6.3 |
| G319 | Review: Q3 TTM cash flow is stale; expose an as-of date *(owner)* | DONE | cf_as_of, bs_as_of; L3 |
| G328 | Prior-year columns come from Reg. 34 annual XBRL: compare them with stored FY figures | DONE | X110; CONSISTENCY/ANNUAL_PRIOR_YEAR_DIFFERS at promotion (non-blocking, filing_checks.py); tests/test_restatement_triggers.py (TCS FY26 vs FY25 annual) |

## Data-source (49)

| id | requirement | status | where / next step |
|---|---|---|---|
| G2 | Verify the owner's belief that insurance and NBFC results are not on NSE *(owner)* | CONFLICTS_WITH_EVIDENCE | references X54, X62-X64; tests/test_batch4_nbfc.py, tests/test_batch6_insurers.py. Both are filed on NSE as XBRL and parsed (10 NBFCs, 10 insurers) |
| G4 | Insurers sit only under a separate NSE 'Insurance' results tab; an equity-feed scraper never sees them | CONFLICTS_WITH_EVIDENCE | references A7; src/financials/fetch/jobs.py:78; X62-X66. index=insurance exists only for the legacy listing (to Dec 2024); Integrated Filing insurer XBRL is found via the equities integrated-filing endpoint |
| G32 | MCA AOC-4 XBRL carries full notes and prior-year columns; banks, NBFCs and insurers are exempt | OUT_OF_SCOPE_BY_DECISION | Follows G74 (no paid sources). Prior-year columns come from free Reg. 34 XBRL only (G328) |
| G74 | Is MCA AOC-4 XBRL free and available? *(owner)* | OUT_OF_SCOPE_BY_DECISION | Owner decision 2026-11-15: **no paid source at all**. Annual XBRL stays the free NSE Reg. 34 feed (F07) |
| G76 | Use free exchange Reg. 34(1) annual XBRL (same MCA taxonomy) instead of MCA | DONE | A8, R2, X36, X69; tests/test_batch9_annual.py. Fetched from NSE; BSE unreachable (A1) |
| G80 | Should the project move from NSE to BSE? *(owner)* | DONE | C7; arch 1. NSE primary |
| G81 | NSE has only 150+ exclusive companies; NSE gives the complete universe | OUT_OF_SCOPE_BY_DECISION | C7. Universe is NSE-only by decision |
| G82 | NSE is better for OHLCV, corporate actions and demerger price discovery | DONE | F01, F03 |
| G83 | Backfill FY20-FY25 annual XBRL from BSE's deeper archive | OUT_OF_SCOPE_BY_DECISION | C9. Financials start at period end 2025-03-31 |
| G84 | NSE needs Akamai cookie rotation; BSE JSON API is cleaner, use it when NSE throttles | CONFLICTS_WITH_EVIDENCE | A1 (api.bseindia.com 403; www.nseindia.com/api answered without cookies); A7 |
| G86 | Fall back to BSE when an NSE XBRL download fails or is rate-limited | DOCUMENTED_PLANNED | arch 1; D-4 (BSE fallback not built). Blocked: BSE unreachable (A1) |
| G88 | List all machine-readable exchange data worth collecting *(owner)* | DONE | config/data_sources.yaml -> docs/data_sources.md (F01-F29) |
| G98 | Credit rating XBRL (agency, instrument, amount, grade, action) | DOCUMENTED_PLANNED | F22 (UNVERIFIED) |
| G100 | Insider trading PIT Reg. 7(2) and SAST Reg. 29 XBRL | DOCUMENTED_PLANNED | F11 (UNVERIFIED), F12 (OBSERVED); Phase 3 |
| G102 | Bulk and block deals CSV | DOCUMENTED_PLANNED | F14 (OBSERVED); Phase 3 |
| G103 | Short-selling CSV | DOCUMENTED_PLANNED | F15 (OBSERVED); Phase 3 |
| G104 | Reg. 32(1) deviation / variation of issue proceeds | DOCUMENTED_PLANNED | F23 |
| G108 | Reg. 44(3) voting results (dissent %) | DOCUMENTED_PLANNED | F23 |
| G109 | BRSR XBRL: headcount, attrition, R&D, energy / water intensity (~893 tags) | DOCUMENTED_PLANNED | F24 (UNVERIFIED, not searched). Tag count: R21 (UNVERIFIED) |
| G121 | Governance XBRL (Reg. 27, 13(3)): board independence, committees, attendance, complaints | DOCUMENTED_PLANNED | F23 (OBSERVED) |
| G122 | AMFI monthly scheme-wise portfolios (one ISIN file by the 10th); month-on-month MF diff | DOCUMENTED_PLANNED | F26; R8 (UNVERIFIED: no consolidated file; per-AMC adapters). Phase 3 |
| G123 | NSDL / CDSL fortnightly sector-wise FPI flows and AUC | MISSING | not in data_sources.yaml |
| G124 | NSDL FPI trade-wise and 3% breach / limit reports | MISSING | not in data_sources.yaml |
| G125 | F&O UDiFF bhavcopy: PCR, max pain, IV skew, long/short buildup | DOCUMENTED_PLANNED | F16 (OBSERVED); Phase 3 |
| G126 | Participant-wise OI and volume (FII/DII/Pro/Client) | DOCUMENTED_PLANNED | F17 (OBSERVED) |
| G127 | MWPL and F&O ban (95%) list | DOCUMENTED_PLANNED | F18 (OBSERVED) |
| G128 | SLBM bhavcopy: lending fee as short-demand signal | DOCUMENTED_PLANNED | F19 (OBSERVED) |
| G129 | Index constituent weightage files (free-float market cap, weights) for passive-flow prediction | MISSING | IDX1 (constituents only), IDX9 (closes) |
| G135 | RBI DBIE / FBIL: repo, T-bill, 10Y G-Sec, USD/INR, CPI/WPI | DOCUMENTED_PLANNED | F25 (PLANNED, no source probed) |
| G136 | Corporate bond / commercial paper secondary-market yields (credit stress) | MISSING | not in data_sources.yaml (F22 covers ratings and debt XBRL) |
| G138 | Depository system-driven disclosures (SAST-SDD, PIT-SDD) | DOCUMENTED_PLANNED | F13 (UNVERIFIED) |
| G139 | ASM / GSM surveillance lists | DOCUMENTED_PLANNED | F20 (OBSERVED; GSM not probed) |
| G140 | Daily price band / circuit file; exclude circuit-locked stocks | DOCUMENTED_PLANNED | F20 |
| G141 | VaR / ELM margin files as a tail-risk proxy | DOCUMENTED_PLANNED | F20 |
| G142 | Daily buyback report (shares bought vs approved size) | MISSING | CA10 (buyback purpose only) |
| G145 | Reg. 50/52 debt XBRL of debt-listed subsidiaries (results, security cover) | DOCUMENTED_PLANNED | F22 (UNVERIFIED) |
| G146 | REIT / InvIT XBRL (NDCF, distribution yield) | OUT_OF_SCOPE_BY_DECISION | C7; IDX8 (REITs trade as RR) |
| G147 | RBI DBIE sectoral bank credit deployment | DOCUMENTED_PLANNED | F25 |
| G148 | IIP and RBI OBICUS capacity utilisation mapped to NSE basic industry | DOCUMENTED_PLANNED | F25. Not named in F25; NIC-to-industry mapping TBD |
| G154 | Commodity, EXIM, card/UPI, SIAM, TRAI, IRDAI, CEA sector KPIs mapped to sectors | DOCUMENTED_PLANNED | F25 (agencies listed; card/UPI not) |
| G163 | IPO subscription (QIB/NII/retail) and anchor lock-in expiry calendar | MISSING | not in data_sources.yaml |
| G195 | Debt servicing: interest / redemption payment and default XBRL | DOCUMENTED_PLANNED | F22 |
| G196 | Annual secretarial compliance (Reg. 24A) | DOCUMENTED_PLANNED | F23 |
| G197 | CDR, OTS and CIRP / NCLT insolvency filings | MISSING | E2 (REG30_Restructuring vaulted raw); no plan row |
| G279 | May-June 2026 Reg. 30 XBRL utilities (restructuring, CDR/OTS, search and seizure, forensic audit) | MISSING | not in references.md. Unregistered claim |
| G280 | Commodity / input-cost feeds (World Bank Pink Sheet, FRED, MCX, PPAC, CEA) mapped to industries | DOCUMENTED_PLANNED | F25. FRED not listed |
| G308 | Review: decide explicitly that the universe is NSE-only *(owner)* | DONE | C7 |
| G312 | Review: AMFI publishes per-AMC files, not one ISIN file (verify) *(owner)* | DOCUMENTED_PLANNED | R8 (UNVERIFIED); F26 |
| G331 | Universe can grow from Nifty 500 to all NSE mainboard stocks | DONE | C7; discover-filings --universe active; owner 2026-11-17: sticky Rs 500 Cr universe `mcap500` (decision O, X134, arch 11.12; tests/test_mcap_universe.py) |

## UI/screener (20)

| id | requirement | status | where / next step |
|---|---|---|---|
| G89 | A personal website like Screener.in *(owner)* | OUT_OF_SCOPE_BY_DECISION | Decision F (2026-11-15, reversible): no hosted site for now; screens run from the CLI/DSL. Revisit after the ratio catalogue is built |
| G96 | Industry / basic-industry mapping (NSE 4-tier classification) | DONE | F30 NSE quote API (macro / sector / industry / basic industry), fetch-classification, raw_quote_classification, entity_classification_history (PIT from the first fetch, IC3); IC1-IC3; tests/test_batch_h_industry_peers.py |
| G112 | Peer comparison table ranked by market cap, PE, ROCE, quarterly profit growth | DONE | peer_count, peer_rank_market_cap / _pe / _roce / _profit_growth within the NSE basic industry, industry medians (C25); screen by nse_basic_industry for the peer table; features_peers.py; tests/test_batch_h_industry_peers.py |
| G153 | Screening queries are a must *(owner)* | DONE | dsl.py; arch 14; tests/test_dsl.py; CLI screen |
| G164 | Concall / presentation / DRHP RAG with citations, separate from XBRL numbers | OUT_OF_SCOPE_BY_DECISION | Decision G (2026-11-15, reversible): no text retrieval over announcement PDFs for now |
| G165 | Custom Excel / DCF model exporter over the database | MISSING | export-bundle writes Parquet only |
| G166 | One wide nightly feature table, one row per security | DONE | screener_features(_history); materialize; tests/test_features.py. About 150 columns |
| G185 | Alias dictionary mapping readable names to columns | DONE | dsl.ALIASES; tests/test_dsl.py |
| G186 | Arithmetic, AND/OR/NOT and comparisons compiled to parameterised SQL; no injection | DONE | arch 14; tests/test_dsl.py |
| G187 | Saved custom ratios expand inline in any screen | DONE | dsl.save_custom_ratio; user_custom_ratios; CLI `save-ratio NAME EXPR`, `ratios`; usable as output columns (`screen --columns`, `--order-by`, M1 / G07); tests/test_dsl.py, tests/test_period_pl_family.py |
| G188 | Natural-language to DSL translator that shows the formula for checking | MISSING | not built |
| G189 | Daily screen alerts when a stock enters or exits a saved screen | DOCUMENTED_PLANNED | arch 15 Phase 3 (daily diff digest) |
| G211 | Portfolio overlap, sector weights, weighted PE/ROCE, correlation | OUT_OF_SCOPE_BY_DECISION | Decision H (2026-11-15, reversible): portfolio analytics out of scope for now (arch 1) |
| G212 | Point-in-time thesis snapshot and post-mortem (decision journal) | OUT_OF_SCOPE_BY_DECISION | Follows decision H |
| G268 | Cross-sector columns (Rule of 40, EV/GP, ex-cash PE) usable in one query | DONE | arch 10.8; tests/test_batch7_newgen.py |
| G281 | Synchronised price and fundamental charts on each stock page | OUT_OF_SCOPE_BY_DECISION | Follows decision F |
| G282 | Post-EOD diff engine and digest (watchlist events, screen entries/exits) | DOCUMENTED_PLANNED | arch 15 Phase 3 (daily diff digest). Delivery channel (Telegram / email) undecided |
| G283 | Alert: 52-week high on > 2x 20-day median delivery volume | DONE | screenable flag `high_52w_on_delivery_spike` (DSL `New high on delivery`; batch I, features_more.py); tests/test_features_more.py. The alert digest itself waits on owner decision 2 |
| G332 | Optional read-only SQLite / D1 export of screener_features for a UI | OUT_OF_SCOPE_BY_DECISION | CLAUDE.md Don'ts (no second database engine) |
| G334 | entity_master carries macro sector, sector, industry, basic industry | DONE | entity_classification_history (date-bounded per entity, PIT) rather than entity_master columns; screener columns nse_macro_sector, nse_sector, nse_industry, nse_basic_industry; tests/test_batch_h_industry_peers.py |

## Backtest (6)

| id | requirement | status | where / next step |
|---|---|---|---|
| G52 | Spun-off entity starts at its listing date with no synthetic pre-listing bars | DONE | C12; X52; tests/test_demerger_and_listing.py |
| G58 | Backtest positions in the target convert into acquirer shares by swap ratio | DONE | arch 11.7; `lineage.convert_position` (merger by swap ratio, demerger children by entitlement with the COA cost split; chains; raises without a verified ratio); tests/test_lineage.py |
| G151 | PEAD tracker: abnormal return (vs Nifty 500) and relative volume at T+0/1/5/20 after broadcast | DONE | `pead_event_date`, `pead_ar_t0/1/5/20` (vs Nifty 500 closes, index_ohlcv IDX9; NULL without them), `pead_relvol_t0/1/5/20` after the latest results broadcast (batch I, features_more.py); tests/test_features_more.py. Backtest claims still need TRI (F29 UNVERIFIED) |
| G190 | Historical screens on quarter-end feature snapshots | DONE | screener_features_history (daily); screen --as-of (arch 11.9) |
| G191 | Point-in-time screen backtester across past years | DOCUMENTED_PLANNED | arch 15 Phase 3 (PIT backtester). Needs TRI benchmark (F29) |
| G206 | Survivorship-free universe: keep delisted / merged securities with inactive_date and exit_reason | DONE | entity_master; ID1; L1; tests/test_phase1_fixes_b.py, tests/test_index_backfill.py |

## Ops (25)

| id | requirement | status | where / next step |
|---|---|---|---|
| G60 | Daily master and lineage sync: symbol master, ISIN changes, new listings, delistings | DONE | arch 5.1, 12 (inactive securities), 13 (daily run scheduled by ops/); F28; tests/test_identity.py, tests/test_phase1_fixes_b.py, tests/test_batch_h_industry_peers.py. Identity sync runs from the daily bhavcopy; EQUITY_L (fetch-equity-master) is not in the daily run. BSE master not reachable (A1). Batch K: the nightly-pipeline workflow also fetches the NSE classification of Nifty 500 symbols that have none (fetch-classification --missing-only) |
| G144 | Poll RSS every 1-2 minutes for live alerts | OUT_OF_SCOPE_BY_DECISION | CLAUDE.md Fetching (minimal volume); C8; arch 13 |
| G213 | Three-phase roadmap (core / deep edge / alpha) | DONE | arch 15 (corrected: corporate actions in Phase 1) |
| G284 | Taxonomy namespace registry: detect unknown namespaces / version bumps | DONE | arch 7.1; docs/tag_registry.yaml; tests/test_indas_corp_parser.py, tests/test_registry_audit.py |
| G285 | Row-count circuit breaker (< 90% of expected symbols aborts) | DONE | gate G1 (92%); tests/test_pipeline.py, tests/test_phase1_fixes_a.py |
| G286 | Null-rate circuit breaker (critical columns, 2% spike) | DONE | gate G4 (1.5 pp); tests/test_features.py |
| G287 | SHA-256 vault for offline replay | DONE | vault.py; invariant 2; tests/test_foundations.py |
| G288 | Keep the raw vault in Cloudflare R2 | OUT_OF_SCOPE_BY_DECISION | CLAUDE.md Don'ts (no Cloudflare/R2) |
| G289 | Make the platform self-healing and autonomous from next quarter *(owner)* | DONE | run-day (arch 2, 13) scheduled daily by ops/ (systemd, cron, Windows Task Scheduler) or by the GitHub Actions nightly-pipeline on the owner's self-hosted runner (batch K, ops/README.md), with materialize --incremental after it; nightly-tests runs the offline suite on GitHub at 22:00 IST; tests/test_phase1_fixes_b.py, tests/test_batch_h_industry_peers.py, tests/test_nightly_workflows.py. Auto-healing limited to named rules (invariant 9) |
| G291 | Multi-mirror NSE <-> BSE failover | DOCUMENTED_PLANNED | D-4 (not built). BSE unreachable (A1) |
| G292 | Tables entity_securities, subsidiary_tree, pipeline_audit_log | DONE | schema.sql securities, promotion_log, admin_log; subsidiary tree = group_structure (AOC-1, X112) |
| G297 | Review: corporate-action adjustment must ship with Phase 1 momentum features *(owner)* | DONE | arch 15 Phase 1 |
| G298 | Review: quarantine plus review queue, not auto-heal *(owner)* | DONE | invariant 9; D-6; tests/test_quarantine_cli.py |
| G320 | Review: tables named but missing (raw facts, overrides, staging, shareholding, revisions, custom ratios, snapshots, index history, calendar) *(owner)* | DONE | src/financials/db/schema.sql |
| G321 | Review: long-format facts with a wide view on top *(owner)* | DONE | fact_observations + screener_features |
| G322 | Review: one runtime; no D1 unless deploying on Workers *(owner)* | DONE | CLAUDE.md Don'ts; arch 1 |
| G324 | Review: legal / licensing, personal vs product, local vs cloud *(owner)* | DONE | C8; D-1; arch 1 |
| G325 | Review: golden fixtures from real filings (about 20 companies across archetypes) *(owner)* | DONE | tests/fixtures + MANIFEST.md; Batches 1-10 |
| G326 | Review: start with a thin slice (bhavcopy, identity, vault, corp actions, corporate XBRL, Nifty 500) *(owner)* | DONE | arch 15 Phase 1 |
| G327 | Review: keep CLAUDE.md short; blueprint in architecture.md; dated facts in references.md *(owner)* | DONE | CLAUDE.md; docs/ |
| G330 | Fetch politely with an identifiable User-Agent and raw-file caching | DONE | arch 3 PoliteFetcher; vault url_index |
| G335 | cin as a UNIQUE column | CONFLICTS_WITH_EVIDENCE | I1 (nullable UNIQUE drops rows); arch 5 |
| G337 | Prices and values as REAL (float) | OUT_OF_SCOPE_BY_DECISION | invariant 7; C1 |
| G342 | Phase 1 includes a 20-company golden test suite; then multi-archetype parsers | DONE | arch 15; D-3 |
| G343 | Drop one real XBRL per profile before coding parsers | DONE | tests/fixtures/xbrl; X1, X32-X38 |

## Other (14)

| id | requirement | status | where / next step |
|---|---|---|---|
| G31 | Annual-report PDF pitfalls: page-spanning tables, unit switches, note numbering, ~10-15% scans | OUT_OF_SCOPE_BY_DECISION | arch 15. Claim moot while PDFs are out of scope |
| G39 | Tata Motors had an indicative 60:40 ratio before the final 68.85:31.15 COA | DOCUMENTED_PLANNED | R15 (UNVERIFIED); R7 holds the final COA (UNVERIFIED) |
| G49 | NSE holds a special pre-open session (9:00-9:45) on demerger ex-dates | DOCUMENTED_PLANNED | R16 (UNVERIFIED); P7 shows the ex-date open price only |
| G59 | Ind AS 103: common-control mergers restate comparatives; third-party acquisitions consolidate prospectively | DOCUMENTED_PLANNED | R17 (UNVERIFIED; the appointed-date detail was disputed in the review) |
| G75 | AOC-4 thresholds, 30-day-after-AGM deadline, XML embedded in the PDF | DOCUMENTED_PLANNED | R18 (UNVERIFIED); MCA is paid and login-gated (no paid sources), Reg. 34 XBRL used instead (X36) |
| G77 | BSE circulars LIST/COMP/40/2018-19 and 13/2019-20 adopted the MCA taxonomy | DOCUMENTED_PLANNED | R19 (UNVERIFIED); consistent with X36, circulars not seen |
| G78 | Single Filing System for Reg. 34 XBRL (Apr 2026) and BRSR (Mar 2026); NSE/CML/2026/08 or BSE 20260529-28 | DOCUMENTED_PLANNED | R1 (UNVERIFIED). Cited notice is dated after the dates it supports |
| G87 | Quarterly XBRL is identical on NSE and BSE (SEBI in-capmkt) | DOCUMENTED_PLANNED | R20 (UNVERIFIED); needs both exchanges' file for one quarter (BSE 403 from the container, A1) |
| G113 | Beat Screener, Tijori and Trendlyne using machine-readable data only *(owner)* | DOCUMENTED_PLANNED | data_sources F01-F29; arch 15 |
| G137 | What else is still missing from the platform? *(owner)* | IN_PROGRESS | this digest (docs/owner_requirements.md) |
| G210 | Siemens and Bosch follow Sep / Dec fiscal years | CONFLICTS_WITH_EVIDENCE | X87 (Siemens moved to a 31-March year via a 15-month period). Bosch retracted in the chat itself; Nestle R6 UNVERIFIED |
| G271 | Compile the whole discussion into one document, double-checked so nothing is missed *(owner)* | IN_PROGRESS | this digest |
| G323 | Review: unverified claims (BSE notice, five schemas, Tata Motors dates, 893 BRSR tags, nine RSS feeds, Screener's five rules) *(owner)* | DOCUMENTED_PLANNED | R1, R7, S1-S23; BRSR tag count R21, nine-RSS-feed list R22 (all UNVERIFIED rows with what would verify them). Fully registered |
| G329 | Tata Motors demerger dates and 68.85% / 31.15% COA 'confirmed' | DOCUMENTED_PLANNED | R7 (P7 and X52 VERIFIED; dates and COA UNVERIFIED) |

## Owner decisions needed first

None open. Decided 2026-11-15: no paid sources at all (G74, by the owner); E-H below (on the owner's behalf, reversible).

## Missing: proposed to-do (priority order)

**Phase 1-2 clean-up (inputs already promoted)**
1. **DONE (2026-11-15)** ~~G173, G175: QoQ sales %, QoQ profit %, OPM last year, NPM, interest coverage. Verify: pin values on committed Q2 FY27 fixtures against the Screener export goldens; pin filed `InterestServiceCoverageRatio` / `DebtServiceCoverageRatio` (X41) on a committed fixture before exposing them.~~ Built as specified in arch 10.7, pinned on the facts of Finolex Cables Q4 FY25-Q2 FY26 and Glenmark FY26 (the Screener goldens hold one quarter only, so no QoQ golden exists); filed ISCR / DSCR still not exposed.
2. **DONE (G203, G204 batch D; G152 batch G: `opm_acceleration_pp`)** G203, G204, G152: YoY sales-growth acceleration, OPM expansion vs same quarter last year, margin acceleration. Verify: FactBook unit test over committed quarters; NULL until 9 same-scope quarters exist (C9).
3. **DONE (2026-11-15)** ~~G178: change in promoter holding QoQ. Verify: the two-quarter Reg. 31 fixtures (SHP14: ADANIENT, JSWSTEEL).~~
4. **DONE (2026-11-15)** ~~G169, G202: dividend yield and dividend payout %. Verify: dividend records in the committed corporate-actions fixture (CA9) and the dividends-paid element in a committed Reg. 34 fixture.~~
5. **DONE (2026-11-15)** ~~G183, G95: 20-day average delivery % and VWAP. Verify: `DELIV_PER` (P10) and confirm an average-price column exists in the committed `sec_bhavdata_full` fixture; add a P-row.~~ `AVG_PRICE` = turnover / volume on every row (P16); `deliv_pct_avg_20d`, `vwap`, `vwap_20d`.
6. **DONE (2026-11-15) except G207 bid-ask / circuit-lock** ~~G156, G157, G158, G207, G208: RSI(14), ATR%, relative strength vs Nifty 500, 20-day median traded value, market breadth. Verify: index closes fixture (IDX9 / `index_ohlcv`) and `TtlTrfVal` (P1); circuit-lock days wait for an F20 price-band fixture.~~ Batch B (`features_price.py`, arch 10.7): RSI, MACD, ATR%, RS and beta vs Nifty 500, 20D median traded value, `market_breadth`; RS / beta switch on once the daily `ind_close_all` closes (IDX9, fetched with each market day) cover the window.
7. **DONE (2026-11-15, batch G)** G256, G257, G258: A&P intensity, gross-margin expansion, marketing-efficiency proxy. Verify: the `ADVERTISING` label rule on the Batch 7 fixtures (X68).
8. **DONE (2026-11-15, batch G)** G265, G266, G270: EV/GOV, ARPU/MTU growth, P/EV. Verify: a sample KPI CSV fixture for `load-kpis` with the new KPI names; P/EV reads `embedded_value`.
9. **DONE (2026-11-15, batch G)** G278: standalone-to-consolidated profit leakage. Verify: a company with both scopes committed for the same quarter.
10. **DONE (X111, `filing_checks.apply_bse_scrip_code`)** G79: fill `bse_scrip_code` from the in-filing `ScripCode` (X7). Verify: corporate and bank fixtures; quarantine on disagreement.
11. **DONE (2026-11-16)** G11, G39, G49, G59, G75, G77, G87 and the BRSR tag count / nine-RSS-feed list (G323) are UNVERIFIED rows R14-R22 in `docs/references.md`, each with what would verify it. G32 is OUT_OF_SCOPE_BY_DECISION (G74); G279 stays MISSING. No code.

11a. **DONE (2026-11-15)** ~~the `restatement_suspected` flag (architecture §7.6).~~ YTD trigger (X106), discontinued operations (X108), logged merger / demerger (X109); Reg. 34 prior-year comparison as a finding (X110).
11b. **Dropped (owner, 2026-11-19: "Ignore DVR")** ~~market cap summed across share classes (architecture §8).~~ Each listed security keeps its own market cap (rule U1 already: owner "ignore DVR", no share-class aggregation); the code creates only COMMON securities; partly-paid series E1 stays outside the universe (P17).

**Phase 2 completion**
12. **DONE (2026-11-15, batch G; cash-flow element only, Reg. 30 acquisition events unparsed)** G276: organic vs inorganic perimeter flag. Verify: a Reg. 34 fixture with a business-combination cash-flow element and a Reg. 30 acquisition XBRL fixture.
13. **DONE (2026-11-15, batch H)** ~~G112, G199: peer comparison and discount to industry median. Verify: a real fixture of NSE's industry classification feeding a point-in-time `entity_classification_history`.~~ NSE quote API fixtures (IC1-IC3), `features_peers.py`.
14. **DONE (batch G)** G133: input-cost sensitivity columns (materials, power, freight as % of revenue). Verify: X50 fixtures (AIA, SRF).
15. **DONE (batch G; penalties still wait for E12)** G117: Reg. 30 red-flag columns, kept separate (never summed). Verify: E3/E5/E7 fixtures; penalties wait for an E12 content fixture.
16. **Dropped (2026-11-16)** ~~G115: order-book-to-sales.~~ No committed fixture or registry element tags an order book (CONFLICTS_WITH_EVIDENCE).
17. **DONE (2026-11-15, batch D)** ~~G168: PEG. Define with `min_periods_required`; NULL until 3 years of in-scope EPS (C9).~~ Built on core profit growth and PE on core profit (docs/hidden_gems.md principle 6): quarter YoY now, TTM-on-TTM once 8 quarters exist.

**Phase 3**
18. G151, G205: PEAD tracker and results-season sector breadth (columns DONE in batch I, features_more.py). Verify: index closes (IDX9) now, Nifty 500 TRI fixture (F29) before any backtest claims.
19. G283: 52-week-high-on-delivery alert, inside the Phase 3 diff digest (after decision 2); the screenable flag `high_52w_on_delivery_spike` is DONE (batch I).
20. G188: natural-language to DSL translator that only emits a DSL string shown for editing. No data fixture; needs owner approval of an LLM call.
21. G165: Excel model exporter over `fact_observations`. Verify: a template fixture and round-trip test.
22. G197: CDR / OTS / CIRP filings. Verify: a `REG30_Restructuring` XBRL fixture (prefix seen in E2).
23. G142: daily buyback progress report. Verify: a real NSE file fixture and source row in `config/data_sources.yaml`.
24. G163: IPO subscription and anchor lock-in calendar. Verify: real NSE bid-detail and lock-in fixtures.
25. G129: index weightage files. Verify: a real weights file fixture.
26. G123, G124: NSDL/CDSL fortnightly FPI and FPI limit reports. Verify: reachability probe and a fixture.
27. G136: corporate bond / CP trade yields. Verify: a real debt-segment trade report fixture.
28. G62: cost-of-acquisition / swap-ratio watcher. Blocked by decision 1; verify on a real COA announcement.

**Last (owner, 2026-11-17: "add last in to do")**
29. Automatic merger detection and the demerger cost-of-acquisition split (entitlement ratios, COA percentages). Today
    both are admin-entered, audited edges (architecture §11.7); the terms are announced only in PDFs (R7 UNVERIFIED).
30. Reg. 30 penalty amounts (G117 red flags carry the event, not the amount). Verify: an E12 content fixture.

**Later (owner, 2026-11-17: "Companies listed only on BSE but having market cap > 500 Cr must be also added in our
Universe, this will be later, not right now. Companies like NSE are listed on BSE and we miss such companies.")**
31. BSE-only companies with market cap >= Rs 500 Cr join the universe (same sticky weekly rule as U1). Needs: a
    verified BSE market-cap / share-count source (fetched with headless Chrome on a GitHub runner, as for the
    permitted securities), identity without an NSE symbol (BSE scrip code + ISIN), BSE price history (no NSE
    bhavcopy rows exist for them), and BSE filings. Not started.


## Decisions taken on the owner's behalf (2026-11-15)

The owner asked the assistant to take these with its recommendation. Each is reversible.

- **A. TTM after restatements:** use the company's latest (restated) YTD via the YTD bridge and flag the row `restatement_suspected` (X106). The open YTD_QUARTER_MISMATCH findings stay as the record of each restatement.
- **B. Company filing errors:** correct from the signed statutory results PDF through an audited correction path. Raw XBRL is never edited; each correction stores the PDF link, page and printed line, needs two independent reads that agree, and can be reversed. (In progress.)
- **C. Share count:** the Reg. 31 total is the source of truth for market cap (already so in `market_cap_shares`). Cross-check findings that differ by an exact factor (2, 5, 10, 100, 1000), or by the same gap in 3+ quarters (trust-held treasury shares or rounded paid-up), are closed ACCEPTED with the reason; 92 closed, 12 left open.
- **D. Non-blocking notes:** segment / geography findings (the filer's own totals not adding up) are ACCEPTED (41). A price gap is ACCEPTED as a market move only when it is not near a split / bonus / consolidation ratio and the next closes hold (114); the other 105, including ratio-like gaps such as Infibeam x10 and Vertoz x10, stay open as candidate missing corporate actions.
- **E. Restated comparatives (G28):** no PDF extraction of restated earlier quarters. A quarter stays as first published, which is what a point-in-time backtest must see; TTM across a restatement uses the latest YTD (decision A, X106). PDFs are used only for audited corrections of clear filing errors (decision B, X107).
- **F. Front end (G89, G281):** none for now; screens run through the CLI and DSL. The Phase 3 digest channel (G282) is chosen when the digest is built.
- **G. Announcement text retrieval (G164):** out of scope for now; numbers come only from XBRL and audited PDF corrections.
- **H. Portfolio analytics and decision journal (G211, G212):** out of scope for now (architecture §1: research, screening, backtesting).
- **Paid sources (G74, owner, 2026-11-15):** none at all.

## Owner decisions (2026-11-16)

- **I. Storage (owner: "Fix everything"):** the live `screener_features` table is written once per materialize run
  (its last day), not every day; `compact` rewrites `market.duckdb` without dead space (monthly, and automatically
  after full runs when the disk has room); `prune-versions` may delete the rows of superseded parser versions that no
  reader can select, only after archiving them to zstd Parquet with a manifest (table, version, rows, sha256) and an
  `admin_log` entry. The vault blobs remain the source of truth, so every version stays reproducible by a re-parse
  (CLAUDE.md invariant 1, architecture §4.1). The feature universe stays every security with a recent bar (about
  3,000 EQ / BE / BZ securities, not only the Nifty 500), because the universe will be expanded soon: the history
  grows by about 1 GB per ~1.3 M rows (~3,000 securities x ~440 days) and with the universe.
- **J. Drop `raw_xbrl_facts` (owner, 2026-11-16: "Ok with plan once we have everything covered, go ahead and don't
  ask for it again. Approved."):** condition: every XBRL element of every vaulted file type reaches a clean table
  (`disclosure_facts` for everything no other clean table captures), proven by a fixture coverage test for each
  accounting profile and file type and by a live measurement showing 0 uncaptured elements per profile. Once the
  condition holds, the raw table is removed from the schema and the code paths that read it (quarantine inspect /
  reprocess, prune rules, lineage) read the vault blob on demand instead. The vault blobs stay (0.7 GB): they remain
  the source of truth for every re-parse. **Implemented (2026-11-16):** `drop-raw-xbrl` (gated on
  `raw_xbrl.coverage`, audited in `admin_log`, idempotent, then compacts; `--spill DIR` on low disk); the readers
  moved to clean rows or the blob (architecture §4.1); the fixture proof is `tests/test_disclosures.py` (raw facts
  parsed from each blob). Pre-cutoff contexts (~2.49 M values) and the 64 quarantined / out-of-scope filings' facts
  (~2.36 M values) then live only in the vault, by design (C9; invariant 9).
- **K (proposed, not decided):** R2 for the vault and the nightly database snapshot or Parquet bundle, GitHub
  Actions as the writer, a private Cloudflare-hosted site behind a login, and a free LLM API that translates
  questions into the screener DSL. Recorded as a direction only; CLAUDE.md's "no Cloudflare/R2 without an explicit
  decision" still applies until the owner decides.
- **L. Public repository with real fixtures (owner, 2026-11-16):** the repository stays public with the real NSE
  fixtures in `tests/fixtures/`; not to be raised again. `data/` stays uncommitted as before.
- **M. `disclosure_facts` slimmed (owner, 2026-11-16, after two independent reviews and a live sample):** "disclosure_facts
  slimmed: masked values dropped, agreed-junk elements dropped, long text kept as a pointer; the vault blob holds the
  full text." Parser `disc-2` (`parsers/disclosures.py`, X120): (1) a value that is asterisks only (NSE's `******`
  masks of PAN etc.; 863,876 live rows) is not stored; (2) the 783 (source kind, element) pairs of
  `reference/disclosure_exclusions.csv` (both reviewers DROP in every profile; subsidiary registry data, policy
  boilerplate, placeholders, masked / personal ids, web links; no code reads them) are not stored; (3) a value longer
  than 1,000 characters is stored as a pointer (value_text NULL; `text_len`, `text_sha256`, `text_snippet`), and
  `disclosures.full_text` returns it from the vault blob after checking the sha256. Everything else is kept exactly as
  under `disc-1`, and the elements a reader selects (`READ_ELEMENTS`) are exempt from all three rules. Live sequence:
  `backfill-disclosures` (re-parses every filing to disc-2), `prune-versions` (archives, then removes the disc-1
  rows), `compact`. The 18D feature values do not change (FEATURES_VERSION unchanged).

## Owner decisions (2026-11-17)

- **N. Drop key / foreign-key indexes on large tables: PARKED (owner, 2026-11-17: "Let it be there given risk of
  duplicate ... park it").** Measured on a copy: of the 2.47 GB file, the constraint indexes take ~1.44 GB (primary
  keys ~1.1 GB, foreign keys ~0.34 GB); without them the same data is ~1.03 GB. The proposal replaced insert-time
  duplicate refusal with a duplicate / orphan audit in the promote gates. Parked because a duplicate would then be
  caught after the load instead of refused at entry. All constraints stay. Consequence for decision K: 7 daily
  snapshots of the ~2.5 GB file (~17 GB) do not fit R2's 10 GB free tier; snapshots would need to be fewer or stored
  as the zstd Parquet bundle (~0.47 GB measured), to be settled with decision K.
- **P. Exchange data in public places (owner, 2026-11-17):** "Everything on exchange is public limited company data
  and do not worry about it again and again." Workflow artifacts and fixtures with exchange data in this public
  repository are acceptable; not to be raised again (as decision L). Artifact retention is a size choice only.
- **Q. Re-validate every rule on the expanded universe (owner, 2026-11-17):** "When we are expanding our universe, we
  need to be careful about rules we made to match our data with Screener etc. ... be careful once all 3 financial
  statements are available for expanded universe." The named rules (X82 onward) and the Screener / Tijori
  cross-checks were derived on ~595 mostly large companies. Before the ~1,350 new members' fundamentals are trusted,
  once their results, balance sheets, cash flows and annual reports are promoted: (1) the existing companies' values
  must be unchanged (or every change explained by a rule or parser change); (2) quarantine rate per reason and the
  firing rate of each named rule, new members vs the original set, with any outlier investigated; (3) accounting
  identity pass rates (balance sheet, P&L lines, cash flow) per accounting profile and size band; (4) a fresh,
  stratified sample of new members cross-checked against Screener / Tijori as before (compared, never stored); (5) a
  rule found wrong is fixed for every company with a new parser version, a fixture and a test, never special-cased for
  the new set. Until then the new members' fundamentals are marked as not yet validated.
- **Site data layout (agreed 2026-11-17, part of the proposed decision K):** the site never reads the DuckDB file.
  Page views read small precomputed files (per-company JSON, saved-screen results); custom screens read one Parquet
  file of the latest screener table (3,003 x 665: 2.9 MB zstd measured) with column-only range reads; Cloudflare
  caching in front of R2. DuckDB runs only on the writer (GitHub runner or PC).
- **O. Market-cap universe (owner, 2026-11-17: "Add all the companies having market cap of 500 Cr and above. Every
  week download marketcap from bhavcopy file and add companies qualified for 500 cr and above. Companies which are
  already in universe will not go out. No SME. Ignore DVR."):** rule U1 (version `U1-2026.11.17-L`) (`financials/universe.py`, X134, architecture
  §11.12). Source: the `mcapddmmyyyy.csv` of NSE's daily `PRddmmyy.zip` (X130-X132), fetched with every market day
  and backfilled weekly from 2024-10-01. On each week's last trading day every EQ / BE / BZ row with Market Cap >=
  Rs 500 Cr and Category `Listed` joins `universe_membership`; members never leave; SME series and the zip's SME file are not used; each
  row stands on its own (no DVR aggregation). Seed: the ~595 companies that already have financials. Live
  2026-11-17: 595 seeded + 1,352 joined = 1,947 members; `discover-filings --universe mcap500-new` fetches the new
  members' filings. `Permitted` rows (listed on another exchange, only permitted to trade on NSE) never qualify
  (coordinator 2026-11-17: the universe is NSE Mainboard listed companies and the filings pipeline is NSE-only;
  none of them had NSE financials); their raw rows stay stored.
- **Share count (owner, 2026-11-17: "check bhavcopy zip, everything is inside it"):** the same mcap file carries NSE's
  Issue Size. Evaluated against Reg. 31 (X133): 98.4% of 4,035 pairs within 0.5%, under the 99% bar set for a
  switch, with the disagreements explained (listing lag, buy-backs, partly-paid, bonus timing). Decision C stands
  (Reg. 31 is the market-cap share count); Issue Size is stored and is a cross-check (`check-issue-size`).

## Owner decisions (2026-11-18)

- **Decision R (wrong declared unit, rule X201 LEVEL_OF_ROUNDING_SLIP):** approved. A filing whose declared
  `LevelOfRounding` contradicts the company's other filings, proven by at least two of three independent checks
  (paid-up capital vs other filings, Reg. 31 shares x face value vs paid-up, EPS x shares vs profit) and none reading
  1:1, is rescaled as rule-made rows in `fact_corrections` (raw facts untouched; a later PDF correction revokes the
  rule's value). This is a correction of a unit label, not a price or share-count adjustment (CLAUDE.md invariant 8).
  Applied live 2026-11-18: 16 filings, 12 entities (5 Nifty 500 seed filings: AFCONS, COROMANDEL x3, IGIL, MARKSANS,
  METROBRAND; their PDF corrections kept).
- **Decision S (share count when Reg. 31 is the outlier, rule X221 SHARES_REG31_OUTLIER):** when the results
  filing's paid-up / face value and NSE PR-zip Issue Size agree and the same-date Reg. 31 total does not, market cap
  uses NSE's count. When all three differ (HMT), Reg. 31 is kept and the finding stays open.
- **Decision T (fixed assets at the fiscal-year end; delegated, owner-approved 2026-11-18: "you check industry
  practice and decide; already approved"):** the audited Reg. 34 annual report stays the source of the March balance
  sheet, but every balance-sheet line has one definition across all periods of a company (as screeners keep line
  definitions consistent across periods). Rule X273 FIXED_ASSET_ONE_DEFINITION: the fixed-asset lines of a year end
  (PPE, right-of-use, other intangibles, goodwill, investment property, CWIP, intangibles under development) come from
  one filing, never mixed line by line; when the annual and the results filing report the same total split
  differently (right-of-use inside PPE or inside intangibles), the split the company's half-year balance sheets use is
  taken; when the annual restates the year end, its own lines stand. Screener rows are unchanged (Net Block = PPE +
  right-of-use + other intangibles + goodwill + investment property; CWIP = CWIP + intangibles under development).
  Raw facts are untouched; nothing changes before the annual report is visible.
- **Decision U (restated comparatives; delegated, owner-approved 2026-11-18):** as point-in-time databases keep "as
  first reported" and "restated" side by side: the history keeps every figure as first filed (a backtest sees only
  what was published then); a later filing's restated comparatives are visible from that filing's broadcast and are
  what "latest" readers use. Verified to be how the engine already works (X274); exception by the existing rule X100:
  an annual report's re-presented income-statement comparative does not replace a results filing's figure for that
  year (it is reported as the X182 prior-year finding). No separate `restated` column; the prior-year findings list
  which annual reports restate.

## Decisions taken on the owner's behalf (2026-11-18, owner: "use agents where needed to speed up"; reversible)

My 19:31 (2026-11-17) recommendations, unanswered, applied:
1. **REGROUPED prior-year findings** (X182) are bulk-ACCEPTed with their class in the note when every statement
   total agrees; restatements of the bottom line or the cash flow stay open (X233, X234 sub-classes).
2. **`roe_screener`** (X227) is added beside `roe` (Screener's form: last full year's owners' profit over average
   owners' equity); `roe` is unchanged, and C16 no longer claims to match Screener.
3. **Debt/equity for lending NBFCs** (X228): (debt securities + borrowings + deposits + subordinated liabilities) /
   total equity; banks and insurers stay NULL.
4. **TTM is NULL on a proven mis-filed YTD** (X226 YTD_MISFILED_NO_BRIDGE) instead of the X106 bridge (NAZARA).
5. **Restated TTM windows bridge the operating lines too** (X300 OPERATING_LINES_BRIDGE; main session, owner:
   "continue doing what you are doing"): other income, D&A, finance costs, PBT before exceptional items, PBT and
   labelled excise follow revenue and PAT through the YTD bridge (X106) when their own YTD identity breaks in
   a restated row, so OPM, EBITDA, EBIT (ROCE) and interest coverage are on one basis (POLYPLEX TTM other income
   105 Cr via the YTD instead of 158 Cr from the quarters). X226 (no bridge on a proven mis-filed YTD) and X173
   hold for these lines; a row whose operating lines have no bridge on one basis keeps the quarter sums.
6. **X106 bridges revenue and profit only on one basis** (X301 GUARDED_BRIDGE_ONE_BASIS; main session, owner:
   "continue doing what you are doing"): the guarded tags (revenue, total income, PAT, PBT incl. JV, owners' PAT)
   use the YTD bridge only when the prior year's FY and YTD are on one basis. When one of them holds the YTD
   identity and the other breaks it (Swiggy standalone FY26 revenue 8,258 Cr continuing vs H1 FY26 5,693 Cr as
   first filed), TTM is the sum of the latest 4 quarters as filed, as Screener and data vendors show it (Swiggy Q2
   FY27 TTM revenue 10,468 Cr instead of 7,673), NULL only if a quarter is missing or proven mis-filed (X226 first);
   the row carries `restatement_suspected`. (A first version returned NULL unless the quarters were provably on one
   basis: 1,231 NULLs incl. Bajaj Finance, HUL, Coal India and LTTS revenue; judged too costly.) Owners' profit TTM
   (EPS, P/E, ROE) follows the same rules with PAT's basis. On the snapshot 1,238 guarded values change (239
   entities, 57 in the Nifty 500 seed), 14 NULL (missing quarters); owners' TTM 584 values (180 entities), 23 NULL.
   Reversible.
7. **Rights entitlements leave the Rs 500 Cr universe** (X311 RE_NOT_A_MEMBER, rule `U1-2026.11.18-R`; main
   session brief QU): the PR-zip mcap file lists an NSE rights entitlement (symbol `-RE[n]`, series BE, Category
   Permitted, ISIN type code 20) like any security, so rule U1 admitted 5 of them above Rs 500 Cr (UPL-RE,
   LLOYDS-RE1, M&MFIN-RE1, LLOYDSE-RE, ADANI-RE). An RE is a short-lived right to subscribe a rights issue, not an
   equity share: no financials, and its "market cap" is meaningless; index providers and screeners exclude them,
   and the parent equity (UPL, LLOYDSENGG, M&MFIN, LLOYDSENT, ADANIENT) is the member. REs no longer join, and
   although membership is sticky ("members never leave"), the 5 admitted before the rule are removed because they
   were never valid members; each removed row is logged in full in admin_log (UNIVERSE_REMOVE_RIGHTS_ENTITLEMENT)
   and `update-universe` reports the count. Members 2,070 -> 2,065 (Permitted 128 -> 123); no other member changes.
   Reversible: re-insert the logged rows, or re-run rule U1-2026.11.17-P.

8. **Owners' profit = PAT less NCI when owners is filed 0 and NCI is within rounding** (X318 OWNERS_ZERO_NCI_WITHIN_ROUNDING, with X317 widening X214; main session, owner: "use agents where needed"). Industry practice: with nil minority interest, profit attributable to owners equals PAT (EPS and P/E use it). This supersedes the earlier ACCEPT note on 4 KAYNES findings ("X86 withholding is correct"); those filings have no open finding and stay withheld until they are restaged. Owners + NCI = continuing profit only (AURUM, NAZARA, UNIECOM, URAVI) stays withheld: the X52 assumption is wrong for NAZARA FY25 (annual owners 758.2 Mn vs 753.5 Mn). Reversible: drop X318 and re-parse.

9. **A long first financial period is stored as a one-off period** (X337 FIRST_PERIOD_LONG, X338
   PRE_CUTOFF_DECLARED_PERIOD_IGNORED; work QF5, 2026-11-19, delegated by the main session). Industry practice: a
   newly incorporated (e.g. demerged) company's first financial year runs from incorporation to the next 31 March and
   may exceed 12 months (Companies Act 2013 s. 2(41)); it is reported as such and never annualised or compared.
   A declared period starting mid-month with 13..18 calendar months (invariant 6 allows 1..18) is a regular period
   with `period_months` 13..18; no TTM, YoY or annual-on-annual reader uses it (they take 3- / 12-month periods);
   its year-end balance sheet is ordinary. A pre-cutoff comparative that is irregular, or whose declared dates
   disagree with its context (TRANSRAILL: day and month swapped), is out of scope (invariant 14) and ignored instead
   of holding the filing back. Releases 4 annual reports (BLUSPRING, DIGITIDE x2, TRANSRAILL; 8 PERIOD findings).
   Reversible: drop the two rules and re-parse.

## Owner decisions (2026-11-19)

- **Done criterion for Phases 1-2 (expanded universe):** done when the random-sample accuracy is >= 98% (QD2: 99.54% adjudicated, met) and every open finding carries a stated cause, even where it stays withheld. Withheld numbers are NULL in screens, never shown wrong. Stop chasing the long tail of filer errors after the in-flight reviews (QY3, QA2).
- **DVR:** ignored (to-do 11b dropped).
- **Decision V (show everything, flag the suspect):** "Ensure we show everything for all companies, if required flag suspected one, using the correct way." Supersedes "Withheld numbers are NULL in screens" above. Every number a filing states is shown in the feature rows; where a check failed, the row shows the validated value if there is one, else the figure as filed, and names the reason in `dq_flags` / `dq_suspect` (rule SHOW_AND_FLAG, X325; architecture §7.7). Open non-blocking findings flag the rows they concern (`OPEN_FINDING:<reason>`). Screens include flagged rows; `Data Suspect = 0` excludes them. Genuine absence stays NULL (fewer than 4 quarters, pre-cutoff windows, no filing, undefined ratios), and a failed identity, unknown taxonomy or undetermined period still parses nothing.
- **Exchange request rates (X354):** after a measured probe with no refusals, the NSE archive host runs at 12 req/s and the NSE API at 2 req/s with 3 in flight (was 8 and 1). BSE 2-3 s apart (owner 2026-11-21 "Yes"; probe: 2 s held for 20 of 20; was 4-6 s).
- **Reg. 76 (owner 2026-11-24, "Demat vs physical not required"):** G93 closes on the listed-share checks already built (NSE Issue Size from the PR-zip mcap file vs Reg. 31, X133; Reg. 34 year-end counts, X114); no Reg. 76 source is needed.
- **Weekly sweep runs `audit-annual` (owner 2026-11-21 "Add"):** after promote and the incremental materialize, so new annual prior-year findings get their X312 class the same day. A week is clean only when `docs/open_findings.md` shows UNCLASSIFIED 0 (first clean week 21 Nov 2026: 750 open, 0 unclassified).
- **Phase 3 reference (owner 2026-11-21):** many Phase 3 feeds (F&O, AMFI MF portfolios, PIT / SAST insider trading, bulk / block deals, BRSR, governance, RBI macro, backtester) are already built in the owner's repo `Pareshking/NSE-BSE-Insider-Tracker`. Reuse it (import, not copy) before building any Phase 3 feed here.
