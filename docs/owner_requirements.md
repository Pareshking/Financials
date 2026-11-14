# Owner requirements: Aligning Financial Results Databases (2026-11-14)

Source document (owner-provided, committed at the owner's request 2026-11-14): `docs/inputs/Aligning_Financial_Results_Databases.pdf`.

Source: a long chat between the owner and another AI assistant (26 printed pages), exported 2026-11-14. The owner's own prompts are requirements. The assistant's answers are suggestions and claims: they are **inputs, not evidence** (CLAUDE.md evidence rules 1-4). Nothing here may be coded against until it is VERIFIED in `docs/references.md` with a real fixture and a test.

Every concrete item in the chat is mapped to the repository as of 2026-11-14. The machine-readable version (with page numbers and sources) is the gap table this digest was generated from. Ids are stable (G1..G343). Repeated items are listed where they first appear, or once per distinct claim.

## Status summary

| Status | Meaning | Count |
|---|---|---|
| DONE | implemented and tested (file and test cited) | 165 |
| DOCUMENTED_PLANNED | planned in architecture.md / references.md / data_sources.md | 72 |
| IN_PROGRESS | being built now | 4 |
| MISSING | not anywhere in docs or code | 52 |
| CONFLICTS_WITH_EVIDENCE | contradicted by our verified fixtures or tests | 17 |
| OUT_OF_SCOPE_BY_DECISION | excluded by a recorded decision (C2, C7, C9, invariants, CLAUDE.md Don'ts) | 26 |
| NEEDS_OWNER_DECISION | the docs do not settle it | 7 |
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
| G40 | Evening job polls NSE corporate actions and bhavcopy; purposes parsed by deterministic rules | DONE | run-day; arch 11.2; CA9; tests/test_nse_corp_actions.py, tests/test_phase1_fixes_b.py |
| G79 | Map NSE symbols to BSE scrip codes | MISSING | security_identifier_history.bse_scrip_code (column never filled). ScripCode is inside every results XBRL (X7) |
| G85 | Key the master table on ISIN, identical across NSE and BSE | CONFLICTS_WITH_EVIDENCE | P5 (split changes ISIN), P13; arch 5.1 |
| G90 | Quarterly + annual XBRL: statements, notes (borrowings, leases, fixed assets) | DONE | F06, F07; parsers/integrated.py, parsers/reg34_annual.py; X71-X73. Segments tracked separately |
| G91 | Shareholding XBRL: promoter, FII, DII (MF, insurance, banks), public, pledged shares | DONE | F08; SHP7-SHP15; tests/test_batch8_shareholding.py |
| G92 | SAST Reg. 31(1)/31(2) encumbrance events with lender details | DOCUMENTED_PLANNED | F12 (Phase 3, OBSERVED) |
| G93 | Reg. 76 reconciliation of share capital audit (exact issued / listed shares) | DOCUMENTED_PLANNED | F09 (UNVERIFIED, not searched); arch 15 gaps |
| G99 | Related-party transactions from Reg. 23(9) half-yearly Integrated Filing | DONE | X19; RPT contexts land in raw_xbrl_facts. RPT ratio planned |
| G101 | Daily delivery % | DONE | F02; P10; tests/test_market_parsers.py |
| G105 | Audit qualification / modified opinion flag | DONE | E8; X75 filing_meta.auditor_qualified; tests/test_batch9_annual.py, tests/test_batch10_edge_cases.py. Not yet a screener column |
| G106 | Reg. 30 director / auditor / KMP change alerts | DONE | E5; kmp_resignations_90d, auditor_resignations_90d; tests/test_batch10_events.py |
| G107 | Reg. 30 scheme of arrangement (merger / demerger) filings | DOCUMENTED_PLANNED | E2 (REG30_Restructuring vaulted raw); arch 15 Phase 3 |
| G114 | Reg. 30 order wins (client type, value, timeline) | DONE | E3; order_wins_90d, order_value_90d; tests/test_batch10_events.py |
| G116 | Fraud / default / arrest / forensic-audit filings | DONE | E7; fraud_or_default_90d; tests/test_batch10_events.py. Amount is free text, never parsed |
| G118 | Regulatory / judicial actions and penalty amounts | DOCUMENTED_PLANNED | penalties_90d (NULL); E12 (contents UNVERIFIED) |
| G119 | Allotments, preferential issues, QIPs, warrants (price, allottees, dilution) | DONE | E6; corporate_events; tests/test_batch10_events.py. No screener column or warrant tracker yet |
| G120 | Agreements, JVs, MoUs (counterparty, stake) | DOCUMENTED_PLANNED | E2 (ANN_AGREEMENT vaulted raw); arch 15 Phase 3 |
| G130 | Segment reporting (Ind AS 108): revenue, result, assets, liabilities per segment | IN_PROGRESS | X49; parsers/segments.py; segment table on another branch |
| G131 | Geographic revenue split (domestic vs export) | IN_PROGRESS | X75 |
| G143 | NSE RSS feeds per filing type drive targeted XBRL downloads | DONE | A2, A3, A9, CA6, E1; run-day RSS hint. The list of nine feeds is unverified |
| G192 | Analyst / investor meet XBRL (funds, dates) | DOCUMENTED_PLANNED | E2 (SAIIM vaulted raw); Phase 3 |
| G193 | Forward event calendar: board intimations, AGM/EGM notices | DOCUMENTED_PLANNED | E2 (PRIOR_INTIMATION, NOTICE_OF_SHAREHOLDERS_MEETINGS vaulted raw); CA11 |
| G264 | Platform KPIs side table (GOV, take rate, contribution margin, NRR, CAC payback) | DONE | supplemental_kpis; load-kpis; tests/test_supplemental_kpis.py. Manual load; no fetcher (Phase 3) |
| G277 | AOC-1 subsidiary, associate and JV tree from annual XBRL | DOCUMENTED_PLANNED | arch 15 gaps; X75 (axes inspected, not parsed) |
| G295 | Review: ISINs change on splits; use a surrogate security_id with dated identifier history *(owner)* | DONE | arch 5.1; P5; tests/test_identity.py |
| G296 | Review: price table needs exchange and series columns *(owner)* | DONE | ohlcv PK (security_id, exchange, series, trade_date) |
| G306 | Review: DVR shares get INE ISINs; only partly-paid get IN9 *(owner)* | DOCUMENTED_PLANNED | R10 (UNVERIFIED) |
| G313 | Review: insurer and new-gen KPIs (VNB, EV, APE, platform KPIs) are not in XBRL *(owner)* | DONE | X62; supplemental_kpis; tests/test_supplemental_kpis.py |
| G336 | Share classes COMMON / DVR / PARTLY_PAID with voting-rights ratio and face value | DOCUMENTED_PLANNED | arch 8; securities.share_class. voting_rights_ratio and identifier face_value not stored |

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
| G11 | Screener moves director remuneration into employee cost | MISSING | not in references.md. Unverified claim about a competitor; quarterly XBRL has no such split |
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
| G94 | Bhavcopy close, 52-week high/low | DONE | close, dist_52w_high; tests/test_features.py |
| G95 | VWAP from the full bhavcopy | MISSING | not computed. Average-price column not in P10 claims; check the fixture |
| G110 | Live PE, PB, EV/EBITDA from close x shares + net debt + TTM | DONE | arch 8, 10.1; tests/test_features.py |
| G111 | ROCE, ROE, working-capital days, ROIC | DONE | roce, roe, roic, working_capital_days; tests/test_features.py, tests/test_batch9_annual.py |
| G115 | Order-book-to-sales ratio | MISSING | not built. Needs an order-book field (E3) |
| G117 | Automated forensic red-flag score from Reg. 30 events | MISSING | not built. Keep components as separate columns (arch 10.2 spirit) |
| G133 | Screens for sensitivity to crude, power or freight inflation | MISSING | no cost-share columns |
| G134 | Capex, CWIP -> FCF, CFO/EBITDA, CWIP / gross block | DONE | arch 8; C19; X71; tests/test_cash_conversion.py, tests/test_batch9_annual.py |
| G152 | Revision velocity / QoQ operating-margin acceleration | MISSING | not built |
| G155 | 50 / 200 DMA | DONE | price_to_dma50/200; tests/test_features.py |
| G156 | RSI(14) | MISSING | not built |
| G157 | ATR% | MISSING | not built |
| G158 | Relative strength vs Nifty 500 | MISSING | not built. Index closes available (F27, index_ohlcv) |
| G159 | 5D / 20D delivery spikes | DONE | deliv_avg_5d/20d, delivery_velocity; tests/test_features.py |
| G160 | Piotroski F-score | DONE | C23; tests/test_batch9_annual.py |
| G161 | Beneish M-score | DONE | C23; tests/test_batch9_annual.py |
| G162 | Altman Z-score | DONE | altman_z_dd (Z''); tests/test_fundamentals.py. NULL for financials |
| G167 | Valuation: market cap, price, PE, PB, EV/EBITDA | DONE | tests/test_features.py |
| G168 | PEG ratio | MISSING | not built. Needs multi-year EPS growth (C9 limits) |
| G169 | Dividend yield | MISSING | not built. Dividends are in corp_actions.cash_per_share |
| G170 | FCF yield | DONE | fcff_yield (unlevered); tests/test_phase1_fixes_b.py. Equity FCF yield not built |
| G171 | Sales growth and profit growth YoY | DONE | sales_growth_yoy, profit_growth_yoy; tests/test_features.py. 8 quarters |
| G172 | Sales / profit growth 3Y and 5Y, EPS growth 3Y | OUT_OF_SCOPE_BY_DECISION | C9; fundamentals.cagr(min_periods_required); tests/test_scope.py. NULL until history exists |
| G173 | QoQ sales % and QoQ profit % | MISSING | not built |
| G174 | ROCE, ROE, ROIC, OPM, debt/equity, working-capital days, CFO/EBITDA | DONE | tests/test_features.py, tests/test_cash_conversion.py |
| G175 | OPM last year, NPM, interest coverage | MISSING | not built. Filed DSCR / ISCR seen in 5/10 filings (X41) |
| G176 | OPM 5Y | OUT_OF_SCOPE_BY_DECISION | C9 |
| G177 | Promoter holding, pledge %, FII, DII holding | DONE | arch 10.7; tests/test_batch8_shareholding.py |
| G178 | Change in promoter holding | MISSING | fii_dii_qoq_change_pct exists; promoter change not |
| G179 | MF holding change 1M (AMFI) | DOCUMENTED_PLANNED | F26 |
| G180 | Insider net buy 3M (PIT / SDD) | DOCUMENTED_PLANNED | F11, F13 |
| G181 | Reg. 30 red-flag count | DONE | order/kmp/auditor/fraud 90-day counts; tests/test_batch10_events.py |
| G182 | Returns 1M/3M/6M/12M, price to 50/200 DMA, distance from 52W high | DONE | arch 10.7; tests/test_features.py |
| G183 | Average delivery % over 20 days | MISSING | deliv_avg_20d is a quantity. DELIV_PER is in the delivery file (P10) |
| G184 | F&O PCR column | DOCUMENTED_PLANNED | F16 |
| G194 | Ace investor graph across Reg. 31 >1% holders, PIT/SAST and bulk/block deals | DOCUMENTED_PLANNED | SHP12 (shareholding_major_holders); F14. Name normalisation not designed |
| G198 | Valuation bands: current PE / PB / EV-EBITDA percentile vs own history | DONE | pe_percentile, ev_ebitda_percentile (C20); tests/test_valuation_bands.py. P/B band missing; 5Y/10Y windows NULL under C9 |
| G199 | Discount / premium to basic-industry median | MISSING | not built. Needs the industry classification |
| G200 | Reverse DCF implied growth using the live 10Y G-Sec | DONE | reverse_dcf_implied_g (C20, WACC fixed 12%); tests/test_valuation_bands.py. Live yield needs F25 |
| G201 | Capital-allocation scorecard (incremental ROIC, buyback yield, 5Y dilution) | DOCUMENTED_PLANNED | arch 10.1 (Phase 2); C9 |
| G202 | Dividend payout % | MISSING | not listed in arch 10 |
| G203 | YoY sales-growth acceleration (current YoY - prior-quarter YoY) | MISSING | not built |
| G204 | Operating-margin expansion vs the same quarter last year | MISSING | not built |
| G205 | Sector earnings breadth during results season | MISSING | not built |
| G207 | Liquidity: 20D median traded value; bid-ask / circuit-lock days | MISSING | ohlcv.turnover_inr stored, not used |
| G208 | Market regime / breadth: % of Nifty 500 above 50/200 DMA, 52W high/low ratio, advance-decline | MISSING | not built |
| G214 | 20-30 distinctive ratios for all companies *(owner)* | DOCUMENTED_PLANNED | arch 10 catalogue. Most built; rest Phase 2 |
| G215 | Incremental ROIC (3Y/5Y) | DOCUMENTED_PLANNED | arch 10.1 (Phase 2); C9 |
| G216 | Reinvestment rate | DOCUMENTED_PLANNED | arch 10.1 (Phase 2) |
| G217 | Cash ROIC (CROIC) | DONE | croic; tests/test_fundamentals.py |
| G218 | Total shareholder yield (dividends + net buybacks - equity issued) | DOCUMENTED_PLANNED | arch 10.1 (formula corrected: gross buybacks) |
| G219 | 5Y net equity dilution % | DOCUMENTED_PLANNED | arch 10.1; C9 |
| G220 | Incremental asset turnover (3Y) | DOCUMENTED_PLANNED | arch 10.1; C9 |
| G221 | Return on tangible equity (ROTE) | DONE | rote; tests/test_batch9_annual.py |
| G222 | Sloan accrual ratio | DONE | sloan_accrual (C19); tests/test_cash_conversion.py |
| G223 | EBITDA-to-CFO conversion | DONE | cfo_to_ebitda (pre-tax CFO, C19); tests/test_cash_conversion.py |
| G224 | FCF-to-net-income conversion (3Y) | DONE | fcf_to_pat (TTM, C19); tests/test_cash_conversion.py. 3Y sum NULL under C9 |
| G225 | Receivables-to-sales divergence | DONE | receivables_sales_divergence; tests/test_cash_conversion.py |
| G226 | Capex-to-depreciation | DONE | capex_to_depreciation; tests/test_batch9_annual.py |
| G227 | CWIP-to-gross-block | DONE | cwip_to_gross_block (X71); tests/test_batch9_annual.py |
| G228 | Degree of operating leverage | DONE | dol (C19); tests/test_cash_conversion.py |
| G229 | Gross-to-operating margin spread | DONE | gross_ebitda_spread (C6, C19); tests/test_cash_conversion.py |
| G230 | R&D and royalty intensity | DONE | rnd_and_royalty_intensity (X73); tests/test_batch9_annual.py. Mostly NULL: R&D is text |
| G231 | Working-capital intensity | DONE | working_capital_intensity; tests/test_cash_conversion.py |
| G232 | Other-income dependency (OI / PBT) | DONE | other_income_to_pbt; tests/test_features.py |
| G233 | Net debt (incl. leases) / 3Y average FCF | DONE | net_debt_to_fcf (TTM FCF); tests/test_cash_conversion.py. 3Y average NULL under C9 |
| G234 | Effective cost of debt | DONE | cost_of_debt; tests/test_cash_conversion.py |
| G235 | Contingent liabilities / net worth | DONE | contingent_liabilities_to_net_worth (X73); tests/test_batch9_annual.py |
| G236 | RPT leak % (purchases + loans + royalties / revenue) | DOCUMENTED_PLANNED | arch 10.1 (Phase 2); X19 |
| G237 | Composite forensic score combining Piotroski, Beneish and Altman | OUT_OF_SCOPE_BY_DECISION | arch 10.2 (separate columns, never summed) |
| G238 | Unlevered FCF yield (adds back interest x (1 - t)) | DONE | fcff_yield, per-filing interest classification (X14); tests/test_phase1_fixes_b.py |
| G239 | Reverse-DCF implied 5Y growth | DONE | C20; tests/test_valuation_bands.py |
| G240 | 5Y EV/EBITDA band percentile (20 quarters) | DONE | ev_ebitda_percentile (C20, >= 4 prior quarters). 20-quarter window NULL under C9 |
| G241 | Institutional absorption rate (MF + FII shares vs 90D median volume) | DOCUMENTED_PLANNED | arch 10.3 (quarterly FII+DII, Phase 2; monthly Phase 3) |
| G242 | Float-adjusted delivery velocity | DONE | delivery_velocity, float_turnover_pct; tests/test_features.py. Formula corrected (no float multiplication) |
| G243 | Guardrail: NULL on non-positive denominators | DONE | arch 10 (any ratio with denominator <= 0 is NULL); tests/test_cash_conversion.py |
| G244 | Guardrail: expose raw numerator and denominator columns | DOCUMENTED_PLANNED | arch 10 (stated rule). Not present in screener_features |
| G245 | Guardrail: NULL industrial ratios for banks, NBFCs, insurers | DONE | arch 9, 10.5, 10.6; tests/test_batch4_nbfc.py, tests/test_batch6_insurers.py |
| G246 | Financial cohort metrics: NIM, cost-to-income, provision coverage, P/B | DONE | arch 10.5; tests/test_batch5_bank.py, tests/test_batch4_nbfc.py. PCR NULL for NBFCs (X54) |
| G247 | Smooth incremental ratios over 3Y / 5Y windows | OUT_OF_SCOPE_BY_DECISION | C9 |
| G248 | New-generation businesses need different ratios *(owner)* | DONE | arch 10.8; C21; tests/test_batch7_newgen.py |
| G250 | EV / gross profit | DONE | ev_to_gross_profit; tests/test_batch7_newgen.py |
| G251 | Ex-cash PE | DONE | ex_cash_pe; tests/test_batch7_newgen.py |
| G252 | EV / billings | DONE | ev_to_billings; tests/test_batch7_newgen.py |
| G253 | EV / ESOP-adjusted EBITDA | DONE | ev_to_esop_adj_ebitda; tests/test_batch7_newgen.py |
| G254 | Price / operating cash flow | DONE | price_to_cfo; tests/test_batch7_newgen.py |
| G255 | Rule of 40 | DONE | rule_of_40; tests/test_batch7_newgen.py |
| G256 | Marketing efficiency (magic-number proxy) | MISSING | not built. Advertising label rule exists (X68) |
| G257 | Gross / contribution margin expansion (bps YoY) | MISSING | not built |
| G258 | Advertising and promotion intensity % | MISSING | not built. Advertising label rule exists (X68) |
| G259 | Billings growth vs revenue growth | DONE | billings_growth_pct; tests/test_batch7_newgen.py |
| G260 | Negative working-capital float % | DONE | neg_working_capital_float_pct; tests/test_batch7_newgen.py |
| G261 | Net burn multiple | DONE | net_burn_multiple; tests/test_batch7_newgen.py |
| G262 | Cash runway (months) | DONE | cash_runway_months; tests/test_batch7_newgen.py |
| G263 | ESOP-adjusted free cash flow | DONE | esop_adj_fcf; tests/test_batch7_newgen.py |
| G265 | EV / GOV | MISSING | gov column exists; ratio not built |
| G266 | ARPU and MTU growth | MISSING | not in supplemental_kpis |
| G269 | Insurance archetype metrics: P/EV, VNB margin, combined ratio | DONE | combined_ratio (X66), vnb_margin, embedded_value (supplemental); tests/test_batch6_insurers.py. P/EV itself not built |
| G270 | P/EV for life insurers | MISSING | not built. embedded_value is loadable |
| G275 | Dual-ISIN securities (partly paid, DVR): sum market cap over all linked ISINs | DOCUMENTED_PLANNED | arch 8 (market_cap over active share classes). Code creates only COMMON securities (promoter.py:229); partly-paid only skips the share cross-check |
| G276 | Organic vs inorganic perimeter flag (business-combination outflows, acquisition filings) | MISSING | not in docs |
| G278 | Standalone-to-consolidated profit leakage | MISSING | not in docs. Both scopes are already parsed |
| G314 | Review: forensic scores have different scales; never sum; Altman not for financials *(owner)* | DONE | arch 10.2 |
| G315 | Review: delivery velocity must divide by free float, not multiply *(owner)* | DONE | arch 10.3 (float_turnover_pct) |
| G316 | Review: shareholder yield subtracts issuance twice *(owner)* | DOCUMENTED_PLANNED | arch 10.1 (corrected formula) |

## Corporate-action (22)

| id | requirement | status | where / next step |
|---|---|---|---|
| G33 | Automate corporate-action adjustment (mergers, demergers like Tata Motors, splits) with zero human intervention *(owner)* | OUT_OF_SCOPE_BY_DECISION | invariant 9; D-6; C4; CA12. Automatic for parsed purposes and named rules; unknowns quarantine |
| G34 | Adjust per-share series (prices, volume, EPS) by ex-date factors; never multiply absolute financials | DONE | invariant 8; arch 11.1; tests/test_corp_actions.py |
| G37 | Directed lineage table (parent, child, relation, effective date, swap ratio) | DOCUMENTED_PLANNED | arch 15 gaps (merger lineage); corp_actions.related_entity_id |
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
| G51 | Cost-of-acquisition watcher: parse COA %, check they sum to 100%, keep for tax cost basis | DOCUMENTED_PLANNED | arch 15 gaps (demerger COA split); corp_actions.coa_pct; R7 UNVERIFIED. COA is announced as PDF; no source verified |
| G56 | Merger: delisting circular sets status MERGED, merged_into and swap_ratio on the target | DOCUMENTED_PLANNED | arch 15 gaps (merger lineage). MERGED is used today only for duplicate-security repair (D-6) |
| G57 | Merger: acquirer prices not back-adjusted (factor 1.0) | DOCUMENTED_PLANNED | arch 11.1. Merger purposes are not among the parsed patterns (CA9) and quarantine as UNKNOWN |
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
| G28 | Retrospective restatement: take restated comparatives from the quarterly PDF or the annual report | NEEDS_OWNER_DECISION | arch 7.6 (PDF extractor deferred) vs arch 15 ('PDFs are out of scope') vs L2 ('verified PDF supplement'). Docs disagree; owner to decide |
| G35 | Never overwrite history: immutable raw tables plus a computed adjustment layer | DONE | invariant 1; arch 4; tests/test_foundations.py |
| G54 | Parent restates comparatives (Ind AS 105); a PDF comparator promotes the continuing-operations series | OUT_OF_SCOPE_BY_DECISION | arch 7.6, 15 (no PDFs); X80 withholds TTM over the re-presented year |
| G55 | Spun-off baseline from carve-out comparatives in the first PDF / Information Memorandum | OUT_OF_SCOPE_BY_DECISION | C12. History before the first own filing does not exist for PIT reads |
| G63 | Restatement checksums: continuing + discontinued = old PAT; merged PAT = A + B; restated YTD = sum of quarters | OUT_OF_SCOPE_BY_DECISION | arch 7.6, 15 (no PDFs). The A + B check ignores eliminations (owner-forwarded review) |
| G64 | Scanned quarterly PDFs and vision LLMs misread digits and units; they must never corrupt the database *(owner)* | DONE | arch 7.6; invariant 9. No PDF number enters canonical tables |
| G65 | Skip PDFs for most filings: flag only where YTD != sum of quarters | DONE | X80; audit-ytd; tests/test_x80_ytd_identity.py. Not a Q4 restatement detector (arch 6.2); a break withholds TTM |
| G66 | About 95% of filings satisfy the YTD identity | DONE | X80 (94% of 8,081 comparisons tie). Claim verified on live data |
| G67 | Also flag restatement when ProfitLossFromDiscontinuedOperations != 0 | DOCUMENTED_PLANNED | arch 7.6, 15 gaps. restatement_suspected not implemented |
| G68 | Also flag restatement when a demerger / merger effective date is logged | DOCUMENTED_PLANNED | arch 7.6, 15 gaps. restatement_suspected not implemented |
| G69 | XBRL anchor locking: PDF current columns must match XBRL OneD / FourD before restated columns are trusted | DOCUMENTED_PLANNED | arch 7.6 (deferred; must prove itself against the same filing). Depends on the PDF decision |
| G73 | Safe failure: if any check fails, keep the verified XBRL numbers | DONE | invariant 9 |
| G149 | Bitemporal rows: period end + broadcast timestamp; queries filter broadcast <= as-of | DONE | invariant 4; arch 6.3; tests/test_x83_visibility.py |
| G150 | Broadcast timestamp is embedded in XBRL / CSV metadata | CONFLICTS_WITH_EVIDENCE | X83, A7, SHP6; arch 6.3. Comes from the listing at fetch time |
| G293 | Review: PIT key must include visibility; append-only facts with as-of queries *(owner)* | DONE | fact_observations PK (filing_id, parser_version, ...); arch 6.3; tests/test_x83_visibility.py |
| G294 | Review: Q4 Reg. 33 and Reg. 34 annual 12-month rows must not collide; define precedence *(owner)* | DONE | arch 6.3 (annual supersedes from its own visibility); tests/test_batch9_annual.py |
| G309 | Review: YTD identity misses prior-year re-presentations and holds trivially in Q4 *(owner)* | DONE | arch 6.2; X80 |
| G311 | Review: capture broadcast time at fetch time (not in XBRL or bhavcopy) *(owner)* | DONE | X83; arch 6.3 |
| G319 | Review: Q3 TTM cash flow is stale; expose an as-of date *(owner)* | DONE | cf_as_of, bs_as_of; L3 |
| G328 | Prior-year columns come from Reg. 34 annual XBRL: compare them with stored FY figures | DOCUMENTED_PLANNED | arch 7.6 (third trigger); L2. Not implemented |

## Data-source (49)

| id | requirement | status | where / next step |
|---|---|---|---|
| G2 | Verify the owner's belief that insurance and NBFC results are not on NSE *(owner)* | CONFLICTS_WITH_EVIDENCE | references X54, X62-X64; tests/test_batch4_nbfc.py, tests/test_batch6_insurers.py. Both are filed on NSE as XBRL and parsed (10 NBFCs, 10 insurers) |
| G4 | Insurers sit only under a separate NSE 'Insurance' results tab; an equity-feed scraper never sees them | CONFLICTS_WITH_EVIDENCE | references A7; src/financials/fetch/jobs.py:78; X62-X66. index=insurance exists only for the legacy listing (to Dec 2024); Integrated Filing insurer XBRL is found via the equities integrated-filing endpoint |
| G32 | MCA AOC-4 XBRL carries full notes and prior-year columns; banks, NBFCs and insurers are exempt | MISSING | not in references.md. Matters for whether Reg. 34 XBRL exists for financials |
| G74 | Is MCA AOC-4 XBRL free and available? *(owner)* | NEEDS_OWNER_DECISION | not in data_sources.yaml. Paid per company with login/CAPTCHA (per the chat, UNVERIFIED); annual XBRL already free from NSE (F07) |
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
| G109 | BRSR XBRL: headcount, attrition, R&D, energy / water intensity (~893 tags) | DOCUMENTED_PLANNED | F24 (UNVERIFIED, not searched). Tag count unverified |
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
| G331 | Universe can grow from Nifty 500 to all NSE mainboard stocks | DONE | C7; discover-filings --universe active |

## UI/screener (20)

| id | requirement | status | where / next step |
|---|---|---|---|
| G89 | A personal website like Screener.in *(owner)* | NEEDS_OWNER_DECISION | arch 1 (non-goal: UI hosting); arch 14, 14b (DSL and statements built). No front end decided |
| G96 | Industry / basic-industry mapping (NSE 4-tier classification) | DOCUMENTED_PLANNED | arch 5 (entity_classification_history 'not yet built'); raw_index_snapshot.industry. No verified source for the 4-tier classification |
| G112 | Peer comparison table ranked by market cap, PE, ROCE, quarterly profit growth | MISSING | no peer grouping in features. Needs the industry classification |
| G153 | Screening queries are a must *(owner)* | DONE | dsl.py; arch 14; tests/test_dsl.py; CLI screen |
| G164 | Concall / presentation / DRHP RAG with citations, separate from XBRL numbers | NEEDS_OWNER_DECISION | arch 15 (PDFs out of scope for numbers) |
| G165 | Custom Excel / DCF model exporter over the database | MISSING | export-bundle writes Parquet only |
| G166 | One wide nightly feature table, one row per security | DONE | screener_features(_history); materialize; tests/test_features.py. About 150 columns |
| G185 | Alias dictionary mapping readable names to columns | DONE | dsl.ALIASES; tests/test_dsl.py |
| G186 | Arithmetic, AND/OR/NOT and comparisons compiled to parameterised SQL; no injection | DONE | arch 14; tests/test_dsl.py |
| G187 | Saved custom ratios expand inline in any screen | DONE | dsl.save_custom_ratio; user_custom_ratios; tests/test_dsl.py. No CLI command to save one |
| G188 | Natural-language to DSL translator that shows the formula for checking | MISSING | not built |
| G189 | Daily screen alerts when a stock enters or exits a saved screen | DOCUMENTED_PLANNED | arch 15 Phase 3 (daily diff digest) |
| G211 | Portfolio overlap, sector weights, weighted PE/ROCE, correlation | NEEDS_OWNER_DECISION | arch 1 (purpose: research, screening, backtesting). Scope extension |
| G212 | Point-in-time thesis snapshot and post-mortem (decision journal) | NEEDS_OWNER_DECISION | arch 1. Scope extension |
| G268 | Cross-sector columns (Rule of 40, EV/GP, ex-cash PE) usable in one query | DONE | arch 10.8; tests/test_batch7_newgen.py |
| G281 | Synchronised price and fundamental charts on each stock page | NEEDS_OWNER_DECISION | arch 1 (non-goal: UI hosting) |
| G282 | Post-EOD diff engine and digest (watchlist events, screen entries/exits) | DOCUMENTED_PLANNED | arch 15 Phase 3 (daily diff digest). Delivery channel (Telegram / email) undecided |
| G283 | Alert: 52-week high on > 2x 20-day median delivery volume | MISSING | not built |
| G332 | Optional read-only SQLite / D1 export of screener_features for a UI | OUT_OF_SCOPE_BY_DECISION | CLAUDE.md Don'ts (no second database engine) |
| G334 | entity_master carries macro sector, sector, industry, basic industry | DOCUMENTED_PLANNED | arch 5 (entity_classification_history not yet built) |

## Backtest (6)

| id | requirement | status | where / next step |
|---|---|---|---|
| G52 | Spun-off entity starts at its listing date with no synthetic pre-listing bars | DONE | C12; X52; tests/test_demerger_and_listing.py |
| G58 | Backtest positions in the target convert into acquirer shares by swap ratio | DOCUMENTED_PLANNED | arch 11.1, 15 |
| G151 | PEAD tracker: abnormal return (vs Nifty 500) and relative volume at T+0/1/5/20 after broadcast | MISSING | not built. Needs index closes (F27) or TRI (F29) |
| G190 | Historical screens on quarter-end feature snapshots | DONE | screener_features_history (daily); screen --as-of (arch 11.9) |
| G191 | Point-in-time screen backtester across past years | DOCUMENTED_PLANNED | arch 15 Phase 3 (PIT backtester). Needs TRI benchmark (F29) |
| G206 | Survivorship-free universe: keep delisted / merged securities with inactive_date and exit_reason | DONE | entity_master; ID1; L1; tests/test_phase1_fixes_b.py, tests/test_index_backfill.py |

## Ops (25)

| id | requirement | status | where / next step |
|---|---|---|---|
| G60 | Daily master and lineage sync: symbol master, ISIN changes, new listings, delistings | DONE | arch 5.1, 12 (inactive securities); F28; tests/test_identity.py, tests/test_phase1_fixes_b.py. BSE master not reachable (A1) |
| G144 | Poll RSS every 1-2 minutes for live alerts | OUT_OF_SCOPE_BY_DECISION | CLAUDE.md Fetching (minimal volume); C8; arch 13 |
| G213 | Three-phase roadmap (core / deep edge / alpha) | DONE | arch 15 (corrected: corporate actions in Phase 1) |
| G284 | Taxonomy namespace registry: detect unknown namespaces / version bumps | DONE | arch 7.1; docs/tag_registry.yaml; tests/test_indas_corp_parser.py, tests/test_registry_audit.py |
| G285 | Row-count circuit breaker (< 90% of expected symbols aborts) | DONE | gate G1 (92%); tests/test_pipeline.py, tests/test_phase1_fixes_a.py |
| G286 | Null-rate circuit breaker (critical columns, 2% spike) | DONE | gate G4 (1.5 pp); tests/test_features.py |
| G287 | SHA-256 vault for offline replay | DONE | vault.py; invariant 2; tests/test_foundations.py |
| G288 | Keep the raw vault in Cloudflare R2 | OUT_OF_SCOPE_BY_DECISION | CLAUDE.md Don'ts (no Cloudflare/R2) |
| G289 | Make the platform self-healing and autonomous from next quarter *(owner)* | DONE | run-day (arch 2); tests/test_phase1_fixes_b.py. Daily run is automatic; auto-healing limited to named rules (invariant 9) |
| G291 | Multi-mirror NSE <-> BSE failover | DOCUMENTED_PLANNED | D-4 (not built). BSE unreachable (A1) |
| G292 | Tables entity_securities, subsidiary_tree, pipeline_audit_log | DONE | schema.sql securities, promotion_log, admin_log. subsidiary tree planned with AOC-1 |
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
| G39 | Tata Motors had an indicative 60:40 ratio before the final 68.85:31.15 COA | MISSING | R7 (final COA only, UNVERIFIED). Unregistered claim |
| G49 | NSE holds a special pre-open session (9:00-9:45) on demerger ex-dates | MISSING | P7 shows the open price only. Unregistered claim |
| G59 | Ind AS 103: common-control mergers restate comparatives; third-party acquisitions consolidate prospectively | MISSING | not in references.md. Unregistered claim (appointed-date detail disputed in the review) |
| G75 | AOC-4 thresholds, 30-day-after-AGM deadline, XML embedded in the PDF | MISSING | not in references.md. Unregistered claim |
| G77 | BSE circulars LIST/COMP/40/2018-19 and 13/2019-20 adopted the MCA taxonomy | MISSING | not in references.md. Unregistered claim |
| G78 | Single Filing System for Reg. 34 XBRL (Apr 2026) and BRSR (Mar 2026); NSE/CML/2026/08 or BSE 20260529-28 | DOCUMENTED_PLANNED | R1 (UNVERIFIED). Cited notice is dated after the dates it supports |
| G87 | Quarterly XBRL is identical on NSE and BSE (SEBI in-capmkt) | MISSING | not in references.md. Unverifiable from the container |
| G113 | Beat Screener, Tijori and Trendlyne using machine-readable data only *(owner)* | DOCUMENTED_PLANNED | data_sources F01-F29; arch 15 |
| G137 | What else is still missing from the platform? *(owner)* | IN_PROGRESS | this digest (docs/owner_requirements.md) |
| G210 | Siemens and Bosch follow Sep / Dec fiscal years | CONFLICTS_WITH_EVIDENCE | X87 (Siemens moved to a 31-March year via a 15-month period). Bosch retracted in the chat itself; Nestle R6 UNVERIFIED |
| G271 | Compile the whole discussion into one document, double-checked so nothing is missed *(owner)* | IN_PROGRESS | this digest |
| G323 | Review: unverified claims (BSE notice, five schemas, Tata Motors dates, 893 BRSR tags, nine RSS feeds, Screener's five rules) *(owner)* | DOCUMENTED_PLANNED | R1, R7, S1-S23 registered; BRSR tag count and RSS list not registered. Partly registered |
| G329 | Tata Motors demerger dates and 68.85% / 31.15% COA 'confirmed' | DOCUMENTED_PLANNED | R7 (P7 and X52 VERIFIED; dates and COA UNVERIFIED) |

## Owner decisions needed first

1. G28: restated comparatives. architecture §7.6 defers an anchor-locked PDF extractor, §15 says PDFs are out of scope, and L2 mentions a "verified PDF supplement". Pick one and fix all three places (G62 depends on it).
2. G89, G281: whether to build any front end (stock pages, charts, peer tables). §1 lists UI hosting as a non-goal. Also pick the alert channel for the Phase 3 digest (G282).
3. G74: whether paid sources (MCA AOC-4) are allowed at all.
4. G164: whether text retrieval over announcement PDFs (concalls, presentations) is in scope, kept apart from numbers.
5. G211, G212: whether portfolio analytics and a decision journal are in scope (§1 says research, screening, backtesting).

## Missing: proposed to-do (priority order)

**Phase 1-2 clean-up (inputs already promoted)**
1. G173, G175: QoQ sales %, QoQ profit %, OPM last year, NPM, interest coverage. Verify: pin values on committed Q2 FY27 fixtures against the Screener export goldens; pin filed `InterestServiceCoverageRatio` / `DebtServiceCoverageRatio` (X41) on a committed fixture before exposing them.
2. G203, G204, G152: YoY sales-growth acceleration, OPM expansion vs same quarter last year, margin acceleration. Verify: FactBook unit test over committed quarters; NULL until 9 same-scope quarters exist (C9).
3. G178: change in promoter holding QoQ. Verify: the two-quarter Reg. 31 fixtures (SHP14: ADANIENT, JSWSTEEL).
4. G169, G202: dividend yield and dividend payout %. Verify: dividend records in the committed corporate-actions fixture (CA9) and the dividends-paid element in a committed Reg. 34 fixture.
5. G183, G95: 20-day average delivery % and VWAP. Verify: `DELIV_PER` (P10) and confirm an average-price column exists in the committed `sec_bhavdata_full` fixture; add a P-row.
6. G156, G157, G158, G207, G208: RSI(14), ATR%, relative strength vs Nifty 500, 20-day median traded value, market breadth. Verify: index closes fixture (IDX9 / `index_ohlcv`) and `TtlTrfVal` (P1); circuit-lock days wait for an F20 price-band fixture.
7. G256, G257, G258: A&P intensity, gross-margin expansion, marketing-efficiency proxy. Verify: the `ADVERTISING` label rule on the Batch 7 fixtures (X68).
8. G265, G266, G270: EV/GOV, ARPU/MTU growth, P/EV. Verify: a sample KPI CSV fixture for `load-kpis` with the new KPI names; P/EV reads `embedded_value`.
9. G278: standalone-to-consolidated profit leakage. Verify: a company with both scopes committed for the same quarter.
10. G79: fill `bse_scrip_code` from the in-filing `ScripCode` (X7). Verify: corporate and bank fixtures; quarantine on disagreement.
11. G11, G32, G39, G49, G59, G75, G77, G87, G279: record the chat's unverified claims as UNVERIFIED rows in `docs/references.md` (also the BRSR tag count and the nine-RSS-feed list). No code.

11a. Documented but not implemented: the `restatement_suspected` flag (architecture §7.6). Verify: a restated-quarter pair already committed (Tata Motors CV, X80) pins the flag.
11b. Documented but not implemented: market cap summed across share classes (architecture §8; the code creates only COMMON securities). Verify: a real two-class listing (e.g. a DVR) in a bhavcopy fixture.

**Phase 2 completion**
12. G276: organic vs inorganic perimeter flag. Verify: a Reg. 34 fixture with a business-combination cash-flow element and a Reg. 30 acquisition XBRL fixture.
13. G112, G199: peer comparison and discount to industry median. Verify: a real fixture of NSE's industry classification feeding a point-in-time `entity_classification_history`.
14. G133: input-cost sensitivity columns (materials, power, freight as % of revenue). Verify: X50 fixtures (AIA, SRF).
15. G117: Reg. 30 red-flag columns, kept separate (never summed). Verify: E3/E5/E7 fixtures; penalties wait for an E12 content fixture.
16. G115: order-book-to-sales. Verify first whether any committed Reg. 30 order XBRL (E3) or results XBRL tags an order book; otherwise drop.
17. G168: PEG. Define with `min_periods_required`; NULL until 3 years of in-scope EPS (C9).

**Phase 3**
18. G151, G205: PEAD tracker and results-season sector breadth. Verify: index closes (IDX9) now, Nifty 500 TRI fixture (F29) before any backtest claims.
19. G283: 52-week-high-on-delivery alert, inside the Phase 3 diff digest (after decision 2).
20. G188: natural-language to DSL translator that only emits a DSL string shown for editing. No data fixture; needs owner approval of an LLM call.
21. G165: Excel model exporter over `fact_observations`. Verify: a template fixture and round-trip test.
22. G197: CDR / OTS / CIRP filings. Verify: a `REG30_Restructuring` XBRL fixture (prefix seen in E2).
23. G142: daily buyback progress report. Verify: a real NSE file fixture and source row in `config/data_sources.yaml`.
24. G163: IPO subscription and anchor lock-in calendar. Verify: real NSE bid-detail and lock-in fixtures.
25. G129: index weightage files. Verify: a real weights file fixture.
26. G123, G124: NSDL/CDSL fortnightly FPI and FPI limit reports. Verify: reachability probe and a fixture.
27. G136: corporate bond / CP trade yields. Verify: a real debt-segment trade report fixture.
28. G62: cost-of-acquisition / swap-ratio watcher. Blocked by decision 1; verify on a real COA announcement.
