# Data sources

<!-- GENERATED from config/data_sources.yaml by `python -m financials.sources --write`. Do not edit. -->

34 feeds: 16 VERIFIED, 9 OBSERVED, 7 UNVERIFIED, 2 PLANNED. Status meanings and runtime labels are defined in `config/data_sources.yaml`; evidence IDs point to `docs/references.md`.

| ID | Feed | Phase | Status | Runtime | Evidence |
|---|---|---|---|---|---|
| F01 | UDiFF cash-market bhavcopy | 1 | VERIFIED | CONTAINER_DIRECT | P1, P2, P5, P13 |
| F02 | Security-wise deliverable position | 1 | VERIFIED | CONTAINER_DIRECT | P10 |
| F03 | Corporate actions API and RSS | 1 | VERIFIED | CONTAINER_DIRECT | P12, CA1, CA2, CA3, CA4, CA5, CA6, CA7, CA8, CA9 |
| F04 | NSE trading holiday calendar | 1 | VERIFIED | CONTAINER_DIRECT | CAL1 |
| F05 | Index constituents and rebalance notices | 1 | VERIFIED | CONTAINER_DIRECT | IDX1, IDX2, IDX4, IDX5, IDX6 |
| F06 | Integrated Filing - Financials (Reg. 33 quarterly XBRL) | 1 | VERIFIED | CONTAINER_DIRECT | X1, X2, X4, X6, X32, X33, X34, X35, X38, A7, A9 |
| F07 | Reg. 34(1) annual report XBRL (MCA Ind AS taxonomy) | 2 | VERIFIED | CONTAINER_DIRECT | X36, X37, A8, X69, X70, X71, X72, X73, X74, X75, X76, X112, X113, X114 |
| F08 | Reg. 31 shareholding pattern XBRL | 1 | VERIFIED | CONTAINER_DIRECT | SHP1, SHP2, SHP3, SHP4, SHP6, SHP7, SHP8, SHP9, SHP10, SHP11, SHP12, SHP13, SHP14, SHP15 |
| F09 | Reg. 76 reconciliation of share capital audit XBRL | 2 | UNVERIFIED | UNKNOWN | — |
| F10 | Reg. 23(9) related party transactions | 2 | VERIFIED | CONTAINER_DIRECT | X19 |
| F11 | SEBI PIT Reg. 7(2) insider trading disclosures | 3 | UNVERIFIED | UNKNOWN | — |
| F12 | SEBI SAST Reg. 29 and Reg. 31(1)/31(2) encumbrance | 3 | OBSERVED | CONTAINER_DIRECT | A8, SHP7 |
| F13 | Depository system-driven disclosures (PIT/SAST SDD) | 3 | UNVERIFIED | UNKNOWN | — |
| F14 | Bulk and block deals | 3 | OBSERVED | CONTAINER_DIRECT | FD14 |
| F15 | Short selling | 3 | OBSERVED | CONTAINER_DIRECT | FD15 |
| F16 | UDiFF F&O bhavcopy | 3 | OBSERVED | CONTAINER_DIRECT | FD16 |
| F17 | Participant-wise open interest and volume | 3 | OBSERVED | CONTAINER_DIRECT | FD17 |
| F18 | MWPL and F&O ban list | 3 | OBSERVED | CONTAINER_DIRECT | FD18 |
| F19 | SLBM bhavcopy | 3 | OBSERVED | CONTAINER_DIRECT | FD19 |
| F20 | ASM/GSM surveillance, price bands, VaR/ELM margins | 3 | OBSERVED | CONTAINER_DIRECT | FD20 |
| F21 | Reg. 30 structured event XBRL and announcements RSS | 2 | VERIFIED | CONTAINER_DIRECT | A3, A4, E1, E2, E3, E4, E5, E6, E7 |
| F22 | Credit rating disclosures and Reg. 50/52/57 debt XBRL | 3 | UNVERIFIED | UNKNOWN | — |
| F23 | Governance, voting results, fund deviation, secretarial compliance XBRL | 3 | OBSERVED | CONTAINER_DIRECT | A7 |
| F24 | Reg. 34(2)(f) BRSR XBRL | 3 | UNVERIFIED | UNKNOWN | — |
| F25 | Macro, yield and commodity feeds | 3 | PLANNED | UNKNOWN | — |
| F26 | Per-AMC monthly portfolios and new-gen supplemental KPIs | 3 | PLANNED | UNKNOWN | — |
| F27 | Daily index closes (all NSE price indices) | 1 | VERIFIED | CONTAINER_DIRECT | IDX9 |
| F28 | NSE equity master (EQUITY_L.csv) | 1 | VERIFIED | CONTAINER_DIRECT | IDX10 |
| F29 | Nifty 500 total-return index (TRI) | 1 | UNVERIFIED | UNKNOWN | — |
| F30 | NSE 4-level industry classification (quote API) | 1 | VERIFIED | CONTAINER_DIRECT | IC1, IC2, IC3, A14 |
| F31 | NSE daily PR zip market-capitalisation file (mcapddmmyyyy.csv) | 1 | VERIFIED | CONTAINER_DIRECT | X130, X131, X132, X133, X134, P18 |
| F34 | BSE equity UDiFF bhavcopy | 1 | VERIFIED | CONTAINER_DIRECT | X165, A16 |
| F35 | BSE list of securities (ListofScripData, per BSE group) | 1 | VERIFIED | GITHUB_RUNNER | X169, A17, A18 |
| F36 | BSE announcements (+ AttachLive attachments) and shareholding filings (+ inline XBRL) | 1 | UNVERIFIED | GITHUB_RUNNER | — |

## F01 — UDiFF cash-market bhavcopy

| Field | Value |
|---|---|
| exchange_or_agency | NSE |
| url_or_endpoint_pattern | https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_<YYYYMMDD>_F_0000.csv.zip |
| format | CSV in zip (UDiFF) |
| cadence | Daily, trading days |
| fetch_runtime | CONTAINER_DIRECT |
| join_keys | trade_date, FinInstrmId, ISIN, TckrSymb, SctySrs |
| target_tables | raw_cm_bhavcopy, ohlcv, security_identifier_history, trading_calendar |
| unlocked_metrics | close, returns, DMA, 52W high, market cap, gap auditor |
| phase | 1 |
| verification_status | VERIFIED |
| evidence | P1, P2, P5, P13 |
| notes | PrvsClsgPric is unadjusted on ex-dates. FinInstrmId follows (security, series). |

## F02 — Security-wise deliverable position

| Field | Value |
|---|---|
| exchange_or_agency | NSE |
| url_or_endpoint_pattern | https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_<DDMMYYYY>.csv |
| format | CSV (space-padded, no ISIN) |
| cadence | Daily, trading days |
| fetch_runtime | CONTAINER_DIRECT |
| join_keys | trade_date, SYMBOL, SERIES |
| target_tables | raw_delivery, ohlcv.deliv_qty |
| unlocked_metrics | deliv_avg_5d, deliv_avg_20d, delivery_velocity, float_turnover_pct |
| phase | 1 |
| verification_status | VERIFIED |
| evidence | P10 |
| notes | Non-delivery series report '-'. |

## F03 — Corporate actions API and RSS

| Field | Value |
|---|---|
| exchange_or_agency | NSE |
| url_or_endpoint_pattern | https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=<DD-MM-YYYY>&to_date=<DD-MM-YYYY>; RSS https://nsearchives.nseindia.com/content/RSS/Corporate_action.xml |
| format | JSON; RSS XML |
| cadence | Daily (rolling window) |
| fetch_runtime | CONTAINER_DIRECT |
| join_keys | isin (often stale), symbol (current), ex_date |
| target_tables | corp_actions, quarantine_queue |
| unlocked_metrics | adjusted prices, total return, eps factor, share roll-forward |
| phase | 1 |
| verification_status | VERIFIED |
| evidence | P12, CA1, CA2, CA3, CA4, CA5, CA6, CA7, CA8, CA9 |
| notes | Symbol is current, ISIN stale for ~25%; RSS has no symbol/ISIN (discovery only); caBroadcastDate null. |

## F04 — NSE trading holiday calendar

| Field | Value |
|---|---|
| exchange_or_agency | NSE |
| url_or_endpoint_pattern | https://www.nseindia.com/api/holiday-master?type=trading |
| format | JSON keyed by segment |
| cadence | Yearly (current year only) and on change |
| fetch_runtime | CONTAINER_DIRECT |
| join_keys | exchange, cal_date |
| target_tables | trading_calendar, calendar_coverage |
| unlocked_metrics | next_trading_day, board-meeting visibility rule |
| phase | 1 |
| verification_status | VERIFIED |
| evidence | CAL1 |
| notes | A bhavcopy overrides a holiday row (special sessions). |

## F05 — Index constituents and rebalance notices

| Field | Value |
|---|---|
| exchange_or_agency | NSE Indices |
| url_or_endpoint_pattern | https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv; notices https://niftyindices.com/Press_Release/ind_prs<DDMMYYYY>[_n].pdf (listed on /press-release) |
| format | CSV; PDF (pdftotext -layout) |
| cadence | Daily snapshot; notices ad hoc and semi-annual |
| fetch_runtime | CONTAINER_DIRECT |
| join_keys | ISIN (snapshot), symbol at effective date (notices) |
| target_tables | raw_index_snapshot, index_constituents_history |
| unlocked_metrics | in_nifty500, point-in-time universe, survivorship-free backtests |
| phase | 1 |
| verification_status | VERIFIED |
| evidence | IDX1, IDX2, IDX4, IDX5, IDX6 |
| notes | Only the Nifty 500 list and its notices are verified. Nifty 50 / Next 50 / Midcap 150 / Smallcap 250 list URLs (ind_<stub>list.csv) are UNVERIFIED. Demerger dummies are prose, not extracted. |

## F06 — Integrated Filing - Financials (Reg. 33 quarterly XBRL)

| Field | Value |
|---|---|
| exchange_or_agency | NSE (SEBI taxonomy) |
| url_or_endpoint_pattern | discovery https://www.nseindia.com/api/integrated-filing-results?index=equities&symbol=<SYM>; files https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_<PROFILE>_<id>_<ts>_WEB.xml |
| format | XBRL instance |
| cadence | Quarterly per company (standalone and consolidated filings) |
| fetch_runtime | CONTAINER_DIRECT |
| join_keys | ISIN, Symbol, ScripCode, NatureOfReportStandaloneConsolidated, period |
| target_tables | filing_meta, fact_observations, segment_observations, reg23_related_party_transactions, disclosure_facts |
| unlocked_metrics | P&L, H1/FY balance sheet and cash flow, TTM, valuation ratios |
| phase | 1 |
| verification_status | VERIFIED |
| evidence | X1, X2, X4, X6, X32, X33, X34, X35, X38, A7, A9 |
| notes | Discovery via `discover-filings` / `fetch-results --symbols\|--universe` (A7 listing, newest 20 rows; pagination UNVERIFIED) and the RSS symbol hint (A9) in `run-day`. Verified namespaces IntegratedFinance_IndAS, _NBFC, _Banking (2026-01-31), _LI (2025-01-31). Only INDAS_CORP is parsed. General-insurance Integrated namespace not yet seen (legacy GI only, X26). Integrated filing starts Q4 FY25 for Bajaj Finance (X38). |

## F07 — Reg. 34(1) annual report XBRL (MCA Ind AS taxonomy)

| Field | Value |
|---|---|
| exchange_or_agency | NSE (ICAI/MCA taxonomy) |
| url_or_endpoint_pattern | discovery https://www.nseindia.com/api/annual-reports-xbrl?index=equities&symbol=<SYM>; files https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_<SYM>_<ts>.xml |
| format | XBRL instance (ICAI ind-as 2017-03-31) |
| cadence | Annual (post-AGM) |
| fetch_runtime | CONTAINER_DIRECT |
| join_keys | symbol in the NSE file name (resolved on broadcast date), CIN, FY end |
| target_tables | filing_meta, fact_observations, group_structure, related_party_transactions, disclosure_facts |
| unlocked_metrics | lease liabilities, gross block by class, CWIP, contingent liabilities, audit fees, R&D, royalty, geographic revenue, restated comparatives, Piotroski, Beneish, capex/depreciation, ROTE, RPT leak % per counterparty, year-end share counts |
| phase | 2 |
| verification_status | VERIFIED |
| evidence | X36, X37, A8, X69, X70, X71, X72, X73, X74, X75, X76, X112, X113, X114 |
| notes | Parsed by REG34_ANNUAL (fetch-annual). No ISIN in the instance (X70). PPE schedule dimensional (X71). R&D 1/13, royalty 4/13 filings (X73). AOC-1 subsidiary / associate / JV schedule parsed into group_structure (X112; backfill-group-structure for filings promoted earlier). Ind AS 24 related-party schedule parsed per counterparty into related_party_transactions (X113; backfill-rpt for filings promoted earlier). Year-end share counts are facts, cross-checked against Reg. 31 (X114, ANNUAL_SHARE_COUNT_DIFFERS). |

## F08 — Reg. 31 shareholding pattern XBRL

| Field | Value |
|---|---|
| exchange_or_agency | NSE (BSE shp taxonomy) |
| url_or_endpoint_pattern | listing https://www.nseindia.com/api/corporate-share-holdings-master?index=equities&symbol=<SYM>; files https://nsearchives.nseindia.com/corporate/xbrl/SHP_<id>_<ts>_WEB.xml; RSS https://nsearchives.nseindia.com/content/RSS/Shareholding_Pattern.xml |
| format | JSON + XBRL instance |
| cadence | Quarterly per company |
| fetch_runtime | CONTAINER_DIRECT |
| join_keys | ISIN, DateOfReport |
| target_tables | shareholding_meta, shareholding_observations |
| unlocked_metrics | shares outstanding, promoter/FII/DII/MF holdings, pledge, float turnover |
| phase | 1 |
| verification_status | VERIFIED |
| evidence | SHP1, SHP2, SHP3, SHP4, SHP6, SHP7, SHP8, SHP9, SHP10, SHP11, SHP12, SHP13, SHP14, SHP15 |
| notes | Visibility from master broadcastDate. Pledge and encumbrance quantities, NPNP, >1% public holders parsed (SHP8-SHP14). Percentages exclude DR shares (SHP9). |

## F09 — Reg. 76 reconciliation of share capital audit XBRL

| Field | Value |
|---|---|
| exchange_or_agency | NSE |
| url_or_endpoint_pattern | endpoint TBD |
| format | XBRL (expected) |
| cadence | Quarterly |
| fetch_runtime | UNKNOWN |
| join_keys | ISIN, quarter end |
| target_tables | (planned) share_capital_reconciliation |
| unlocked_metrics | issued/listed/demat shares, dilution tracking |
| phase | 2 |
| verification_status | UNVERIFIED |
| evidence | — |
| notes | BLOCKED 2026-11-15 (references A15): no Reg. 76 file in the vault ledger, the announcements RSS or TCS's announcements API for Jul-Nov 2026; BSE answers 403. The Reg. 31 total x paid-up capital cross-check (X103) and the Reg. 34 year-end share counts cross-check (X114, annual stand-in; issued / subscribed / paid-up) stand in. Since 2026-11-17 the listed side is daily: NSE Issue Size from the PR zip (F31, X133), cross-checked against Reg. 31 by check-issue-size; the audit report itself (demat vs physical, Reg. 76) is still unsourced. |

## F10 — Reg. 23(9) related party transactions

| Field | Value |
|---|---|
| exchange_or_agency | NSE (inside Integrated Filing - Financials) |
| url_or_endpoint_pattern | same files as F06 (RelatedPartyTransactionAxis contexts) |
| format | XBRL dimensional contexts |
| cadence | Half-yearly (with H1/FY filings) |
| fetch_runtime | CONTAINER_DIRECT |
| join_keys | filing_id, RelatedPartyTransactionAxis member |
| target_tables | reg23_related_party_transactions, disclosure_facts |
| unlocked_metrics | RPT leak % |
| phase | 2 |
| verification_status | VERIFIED |
| evidence | X19 |
| notes | Present in the corp and NBFC fixtures; the Reg. 23(9) per-counterparty rows (NameOfCounterParty, PANOfCounterParty, TypeOfRelatedPartyTransaction, AmountOfRelatedPartyTransactionDuringTheReportingPeriod) are not parsed yet (X113 OBSERVED: 25 committed Integrated Filings carry them). Per-counterparty RPT comes from the Reg. 34 annual schedule (F07, X113) for now. |

## F11 — SEBI PIT Reg. 7(2) insider trading disclosures

| Field | Value |
|---|---|
| exchange_or_agency | NSE |
| url_or_endpoint_pattern | endpoint TBD |
| format | XBRL / JSON (expected) |
| cadence | Event |
| fetch_runtime | UNKNOWN |
| join_keys | ISIN, acquirer, transaction date |
| target_tables | (planned) insider_trades |
| unlocked_metrics | insider net buy 3M |
| phase | 3 |
| verification_status | UNVERIFIED |
| evidence | — |
| notes | Not searched yet. |

## F12 — SEBI SAST Reg. 29 and Reg. 31(1)/31(2) encumbrance

| Field | Value |
|---|---|
| exchange_or_agency | NSE |
| url_or_endpoint_pattern | pledge summary https://www.nseindia.com/api/corporate-pledgedata?index=equities; per-event filings endpoint TBD |
| format | JSON (pledge summary); XBRL expected for events |
| cadence | Event |
| fetch_runtime | CONTAINER_DIRECT |
| join_keys | company name / ISIN, disclosure date |
| target_tables | (planned) encumbrance_events |
| unlocked_metrics | pledge changes between Reg. 31 snapshots |
| phase | 3 |
| verification_status | OBSERVED |
| evidence | A8, SHP7 |
| notes | Pledge summary differs from Reg. 31 figures for the same company (different date/basis); never mix. |

## F13 — Depository system-driven disclosures (PIT/SAST SDD)

| Field | Value |
|---|---|
| exchange_or_agency | NSDL / CDSL via NSE |
| url_or_endpoint_pattern | endpoint TBD |
| format | CSV/XBRL (expected) |
| cadence | Event (T+2) |
| fetch_runtime | UNKNOWN |
| join_keys | ISIN, PAN-grouped holder |
| target_tables | (planned) sdd_movements |
| unlocked_metrics | early insider/>5% trades |
| phase | 3 |
| verification_status | UNVERIFIED |
| evidence | — |
| notes | Not searched yet. |

## F14 — Bulk and block deals

| Field | Value |
|---|---|
| exchange_or_agency | NSE |
| url_or_endpoint_pattern | https://nsearchives.nseindia.com/content/equities/bulk.csv; https://nsearchives.nseindia.com/content/equities/block.csv |
| format | CSV |
| cadence | Daily (current day only) |
| fetch_runtime | CONTAINER_DIRECT |
| join_keys | Date, Symbol |
| target_tables | (planned) deals |
| unlocked_metrics | institutional block prints, superstar investor graph |
| phase | 3 |
| verification_status | OBSERVED |
| evidence | FD14 |
| notes | No history at these URLs; capture daily. |

## F15 — Short selling

| Field | Value |
|---|---|
| exchange_or_agency | NSE |
| url_or_endpoint_pattern | https://nsearchives.nseindia.com/archives/equities/shortSelling/shortselling_<DDMMYYYY>.csv |
| format | CSV |
| cadence | Daily |
| fetch_runtime | CONTAINER_DIRECT |
| join_keys | Trade Date, Symbol Name |
| target_tables | (planned) short_selling |
| unlocked_metrics | short interest proxies |
| phase | 3 |
| verification_status | OBSERVED |
| evidence | FD15 |
| notes | File date is one day after the trade date it contains. |

## F16 — UDiFF F&O bhavcopy

| Field | Value |
|---|---|
| exchange_or_agency | NSE |
| url_or_endpoint_pattern | https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_<YYYYMMDD>_F_0000.csv.zip |
| format | CSV in zip (UDiFF) |
| cadence | Daily, trading days |
| fetch_runtime | CONTAINER_DIRECT |
| join_keys | TradDt, FinInstrmId, TckrSymb, XpryDt, StrkPric, OptnTp |
| target_tables | (planned) fo_bhavcopy |
| unlocked_metrics | PCR, max pain, OI change, lot size |
| phase | 3 |
| verification_status | OBSERVED |
| evidence | FD16 |
| notes | — |

## F17 — Participant-wise open interest and volume

| Field | Value |
|---|---|
| exchange_or_agency | NSE |
| url_or_endpoint_pattern | https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_<DDMMYYYY>.csv; …/fao_participant_vol_<DDMMYYYY>.csv |
| format | CSV (title line + header) |
| cadence | Daily |
| fetch_runtime | CONTAINER_DIRECT |
| join_keys | date, Client Type |
| target_tables | (planned) participant_positions |
| unlocked_metrics | FII/DII/Pro/Client net futures and options positioning |
| phase | 3 |
| verification_status | OBSERVED |
| evidence | FD17 |
| notes | — |

## F18 — MWPL and F&O ban list

| Field | Value |
|---|---|
| exchange_or_agency | NSE |
| url_or_endpoint_pattern | ban https://nsearchives.nseindia.com/archives/fo/sec_ban/fo_secban_<DDMMYYYY>.csv; MWPL endpoint TBD |
| format | CSV |
| cadence | Daily |
| fetch_runtime | CONTAINER_DIRECT |
| join_keys | trade date, symbol |
| target_tables | (planned) fo_ban |
| unlocked_metrics | ban flag, MWPL proximity |
| phase | 3 |
| verification_status | OBSERVED |
| evidence | FD18 |
| notes | Ban list observed; MWPL utilisation file not probed. |

## F19 — SLBM bhavcopy

| Field | Value |
|---|---|
| exchange_or_agency | NSE |
| url_or_endpoint_pattern | https://nsearchives.nseindia.com/archives/slbs/bhavcopy/SLBM_BC_<DDMMYYYY>.DAT |
| format | DAT (comma-separated, no header) |
| cadence | Daily |
| fetch_runtime | CONTAINER_DIRECT |
| join_keys | symbol, series, expiry |
| target_tables | (planned) slbm |
| unlocked_metrics | lent quantity, borrowing fee |
| phase | 3 |
| verification_status | OBSERVED |
| evidence | FD19 |
| notes | Column meaning needs a spec or careful inference before parsing. |

## F20 — ASM/GSM surveillance, price bands, VaR/ELM margins

| Field | Value |
|---|---|
| exchange_or_agency | NSE / NSE Clearing |
| url_or_endpoint_pattern | bands https://nsearchives.nseindia.com/content/equities/sec_list_<DDMMYYYY>.csv; ASM https://www.nseindia.com/api/reportASM; VaR https://nsearchives.nseindia.com/archives/nsccl/var/C_VAR1_<DDMMYYYY>_1.DAT; GSM endpoint TBD |
| format | CSV; JSON; DAT |
| cadence | Daily |
| fetch_runtime | CONTAINER_DIRECT |
| join_keys | symbol, series, ISIN |
| target_tables | (planned) surveillance |
| unlocked_metrics | ASM/GSM stage, circuit band, VaR/ELM tail-risk proxy |
| phase | 3 |
| verification_status | OBSERVED |
| evidence | FD20 |
| notes | GSM not probed. |

## F21 — Reg. 30 structured event XBRL and announcements RSS

| Field | Value |
|---|---|
| exchange_or_agency | NSE |
| url_or_endpoint_pattern | RSS https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml -> https://nsearchives.nseindia.com/corporate/xbrl/<file>.xml |
| format | RSS XML + XBRL |
| cadence | Intraday / event |
| fetch_runtime | CONTAINER_DIRECT |
| join_keys | company, broadcast time |
| target_tables | corporate_events, disclosure_facts |
| unlocked_metrics | order_wins_90d, order_value_90d, kmp_resignations_90d, auditor_resignations_90d, fraud_or_default_90d |
| phase | 2 |
| verification_status | VERIFIED |
| evidence | A3, A4, E1, E2, E3, E4, E5, E6, E7 |
| notes | fetch-events: Para B (orders, litigation), changes in management, allotments, fraud/default parsed; other families vaulted raw. Penalty / regulatory-action filings are Para B sub-para 20 AIATOP_*.xml (E12): listed in the RSS, contents not yet inspected, so not fetched or parsed; penalties_90d NULL. |

## F22 — Credit rating disclosures and Reg. 50/52/57 debt XBRL

| Field | Value |
|---|---|
| exchange_or_agency | NSE |
| url_or_endpoint_pattern | endpoint TBD |
| format | XBRL (expected) |
| cadence | Event / quarterly |
| fetch_runtime | UNKNOWN |
| join_keys | issuer, instrument ISIN |
| target_tables | (planned) credit_events |
| unlocked_metrics | rating actions, debt-servicing defaults |
| phase | 3 |
| verification_status | UNVERIFIED |
| evidence | — |
| notes | Credit Rating appears as an announcements RSS subject (PDF), XBRL not seen. |

## F23 — Governance, voting results, fund deviation, secretarial compliance XBRL

| Field | Value |
|---|---|
| exchange_or_agency | NSE |
| url_or_endpoint_pattern | Integrated Filing - Governance rows in https://www.nseindia.com/api/integrated-filing-results (INTEGRATED_FILING_GOVERNANCE_<id>_<ts>_WEB.xml); others TBD |
| format | XBRL |
| cadence | Quarterly / event |
| fetch_runtime | CONTAINER_DIRECT |
| join_keys | company, quarter end |
| target_tables | (planned) governance |
| unlocked_metrics | board independence, dissent %, fund diversion flags |
| phase | 3 |
| verification_status | OBSERVED |
| evidence | A7 |
| notes | Governance filings are listed by the integrated-filing-results endpoint; contents not inspected. Voting results / Reg. 32 / Reg. 24A endpoints TBD. |

## F24 — Reg. 34(2)(f) BRSR XBRL

| Field | Value |
|---|---|
| exchange_or_agency | NSE |
| url_or_endpoint_pattern | endpoint TBD |
| format | XBRL (expected) |
| cadence | Annual (top 1,000 companies) |
| fetch_runtime | UNKNOWN |
| join_keys | company, FY |
| target_tables | (planned) brsr |
| unlocked_metrics | headcount, attrition, R&D/ESG metrics |
| phase | 3 |
| verification_status | UNVERIFIED |
| evidence | — |
| notes | Not searched yet. |

## F25 — Macro, yield and commodity feeds

| Field | Value |
|---|---|
| exchange_or_agency | RBI DBIE, FBIL, World Bank, MCX, PPAC, CEA, Commerce, SIAM, TRAI, IRDAI |
| url_or_endpoint_pattern | endpoints TBD (one adapter per agency) |
| format | JSON / CSV / XLSX (expected) |
| cadence | Daily to quarterly |
| fetch_runtime | UNKNOWN |
| join_keys | date, series id, NSE basic industry (mapping TBD) |
| target_tables | (planned) macro_series |
| unlocked_metrics | 10Y G-Sec for reverse-DCF, sector credit, commodity spreads |
| phase | 3 |
| verification_status | PLANNED |
| evidence | — |
| notes | No source probed. |

## F26 — Per-AMC monthly portfolios and new-gen supplemental KPIs

| Field | Value |
|---|---|
| exchange_or_agency | ~45 AMCs; company investor presentations; IRDAI public disclosures |
| url_or_endpoint_pattern | per-AMC adapters TBD; supplemental KPIs manual or presentation-sourced |
| format | XLSX / PDF |
| cadence | Monthly (AMC); quarterly (KPIs) |
| fetch_runtime | UNKNOWN |
| join_keys | ISIN (AMC holdings), company + quarter (KPIs) |
| target_tables | (planned) mf_holdings, supplemental_kpis |
| unlocked_metrics | MF holding change, GOV, take rate, NRR, VNB margin, EV, APE, persistency |
| phase | 3 |
| verification_status | PLANNED |
| evidence | — |
| notes | AMFI consolidated file not believed to exist (R8, UNVERIFIED). |

## F27 — Daily index closes (all NSE price indices)

| Field | Value |
|---|---|
| exchange_or_agency | NSE Indices via NSE archives |
| url_or_endpoint_pattern | https://nsearchives.nseindia.com/content/indices/ind_close_all_DDMMYYYY.csv |
| format | CSV |
| cadence | Daily (trading days) |
| fetch_runtime | CONTAINER_DIRECT |
| join_keys | Index Name, Index Date |
| target_tables | index_ohlcv |
| unlocked_metrics | Nifty 500 / sector index levels, index P/E, P/B, dividend yield, relative strength |
| phase | 1 |
| verification_status | VERIFIED |
| evidence | IDX9 |
| notes | Fetched by fetch-days with each trading day's bhavcopy. Price indices only; no total-return rows (F29). |

## F28 — NSE equity master (EQUITY_L.csv)

| Field | Value |
|---|---|
| exchange_or_agency | NSE |
| url_or_endpoint_pattern | https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv |
| format | CSV |
| cadence | Snapshot (current list) |
| fetch_runtime | CONTAINER_DIRECT |
| join_keys | SYMBOL, SERIES, ISIN NUMBER |
| target_tables | raw_equity_master |
| unlocked_metrics | listing date, face value, market lot, company legal name |
| phase | 1 |
| verification_status | VERIFIED |
| evidence | IDX10 |
| notes | fetch-equity-master. Current listings only; header fields carry a leading space after each comma. |

## F29 — Nifty 500 total-return index (TRI)

| Field | Value |
|---|---|
| exchange_or_agency | NSE Indices |
| url_or_endpoint_pattern | endpoint TBD (not in ind_close_all; niftyindices.com historical TRI not probed) |
| format | UNKNOWN |
| cadence | Daily |
| fetch_runtime | UNKNOWN |
| join_keys | index name, date |
| target_tables | (planned) index_ohlcv |
| unlocked_metrics | benchmark total return for backtests |
| phase | 1 |
| verification_status | UNVERIFIED |
| evidence | — |
| notes | Per-stock total return is computed from prices and accepted dividends (financials.returns); the index TRI needs a verified source. |

## F30 — NSE 4-level industry classification (quote API)

| Field | Value |
|---|---|
| exchange_or_agency | NSE |
| url_or_endpoint_pattern | https://www.nseindia.com/api/NextApi/apiClient/GetQuoteApi?functionName=getSymbolData&marketType=N&series=<SERIES>&symbol=<SYM> |
| format | JSON (equityResponse[0].secInfo macro / sector / industryInfo / basicIndustry) |
| cadence | Snapshot (as shown on the fetch day; no effective dates) |
| fetch_runtime | CONTAINER_DIRECT |
| join_keys | metaData.isinCode, metaData.symbol, fetch date (IST) |
| target_tables | raw_quote_classification, entity_classification_history |
| unlocked_metrics | macro sector, sector, industry, basic industry, industry / basic-industry median PE PB ROCE sales growth, premium to industry median, peer ranks |
| phase | 1 |
| verification_status | VERIFIED |
| evidence | IC1, IC2, IC3, A14 |
| notes | fetch-classification [SYMBOLS] --universe nifty500 (API host, 1 request/s). /api/quote-equity answers 403 from the container (A14). Point in time from the first fetch (C25): never backdated. |

## F31 — NSE daily PR zip market-capitalisation file (mcapddmmyyyy.csv)

| Field | Value |
|---|---|
| exchange_or_agency | NSE |
| url_or_endpoint_pattern | https://nsearchives.nseindia.com/archives/equities/bhavcopy/pr/PR<DDMMYY>.zip |
| format | ZIP of 14 files (15 in Oct 2024); only mcapddmmyyyy.csv is parsed (fixed-width values between commas, summary rows Listed / Permitted / Total) |
| cadence | Daily (trading days) |
| fetch_runtime | CONTAINER_DIRECT |
| join_keys | Trade Date, Symbol, Series |
| target_tables | raw_nse_mcap, universe_membership |
| unlocked_metrics | NSE market cap per security, NSE Issue Size (shares listed on NSE), Rs 500 Cr universe (rule U1), Issue Size vs Reg. 31 cross-check |
| phase | 1 |
| verification_status | VERIFIED |
| evidence | X130, X131, X132, X133, X134, P18 |
| notes | Fetched by fetch-days / run-day with each trading day's bhavcopy; fetch-mcap START END --weekly backfills the week ends for the universe. No ISIN: rows resolve by symbol and series on the file date. Issue Size is not the market-cap share count (X133: 98.4% within 0.5% of Reg. 31, below the 99% bar); it is stored and used as a cross-check (check-issue-size). The zip's other files (corporate actions, price bands, SME, ...) are not parsed. |

## F34 — BSE equity UDiFF bhavcopy

| Field | Value |
|---|---|
| exchange_or_agency | BSE |
| url_or_endpoint_pattern | https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_<YYYYMMDD>_F_0000.CSV |
| format | CSV (UDiFF, NSE's column set; Src BSE, FinInstrmId = BSE scrip code, SctySrs = BSE group) |
| cadence | Daily, trading days |
| fetch_runtime | CONTAINER_DIRECT |
| join_keys | TradDt, FinInstrmId (scrip code), ISIN, TckrSymb |
| target_tables | — |
| unlocked_metrics | ISIN to BSE scrip code map, BSE prices for BSE-only companies (owner to-do 31) |
| phase | 1 |
| verification_status | VERIFIED |
| evidence | X165, A16 |
| notes | Plain HTTP answered 200 from the container and a GitHub runner (byte-identical, 2026-11-17). parse_udiff_cm(data, exchange='BSE') reads it; nothing fetches or promotes it yet (rule BSE1 uses F35). |

## F35 — BSE list of securities (ListofScripData, per BSE group)

| Field | Value |
|---|---|
| exchange_or_agency | BSE |
| url_or_endpoint_pattern | https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w?scripcode=&Group=<G>&industry=&segment=Equity&status=Active |
| format | JSON list (SCRIP_CD, ISIN_NUMBER, scrip_id, GROUP, FACE_VALUE, Status, Segment, Scrip_Name, Issuer_Name, Mktcap Rs crore) |
| cadence | Snapshot (fetch day) |
| fetch_runtime | GITHUB_RUNNER |
| join_keys | ISIN_NUMBER, SCRIP_CD |
| target_tables | raw_bse_securities, security_identifier_history.bse_scrip_code |
| unlocked_metrics | BSE scrip code per ISIN (rule BSE1), BSE market cap (BSE-only universe, owner to-do 31) |
| phase | 1 |
| verification_status | VERIFIED |
| evidence | X169, A17, A18 |
| notes | Ported owner client (financials.fetch.bse) on a runner: group A answered 200 by plain requests with BSE's headers (probe run 2, 705 rows). Runner ledger -> import-bse -> promote (rule BSE1). The container gets 403/404 (A16). |

## F36 — BSE announcements (+ AttachLive attachments) and shareholding filings (+ inline XBRL)

| Field | Value |
|---|---|
| exchange_or_agency | BSE |
| url_or_endpoint_pattern | TBD for our runs (owner client, A17: api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w, www.bseindia.com/xml-data/corpfiling/AttachLive/<name>, api.bseindia.com/BseIndiaAPI/api/Corp_Shareholding_ng/w, www.bseindia.com/XBRLFILES/SHPXBRLDataXML/<file>) |
| format | JSON (Table / Table1 ROWCNT); attachments PDF; shareholding inline XBRL (in-bse-shp taxonomy) |
| cadence | Per filing |
| fetch_runtime | GITHUB_RUNNER |
| join_keys | SCRIP_CD / FLD_ScripCode, NEWSID |
| target_tables | filings (exchange BSE, raw only) |
| unlocked_metrics | results and shareholding of the Permitted members of rule U1-P (once a parser is proven on BSE files) |
| phase | 1 |
| verification_status | UNVERIFIED |
| evidence | — |
| notes | References A17, X166, X167, X168. Shapes VERIFIED on the owner repo's fixtures (A17); not yet answered to our runner (run 2: strCat=Result with strScrip=500488 answered 400). bse-fetch workflow (scripts/bse_fetch.py) -> import-bse -> promote: vaulted raw only. No BSE results XBRL endpoint is known (X168). |
