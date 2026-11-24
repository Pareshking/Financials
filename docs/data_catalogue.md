# Data catalogue

<!-- GENERATED from tests/fixtures/ by `python scripts/data_catalogue.py --write`. Do not edit. -->

What every committed fixture file contains (every zip member too), which feed it belongs to, whether the pipeline ingests it, and which open owner requirement (`docs/owner_requirements.md`) its columns could serve. Check here before saying data is unavailable. Feeds: `docs/data_sources.md`; XBRL elements: `docs/tag_registry.yaml`; sha256 and source URLs: `tests/fixtures/MANIFEST.md`.

442 fixture files (548 entries counting zip members) in 46 families; 0 unclassified (the generator fails on a file that matches no family).

Status: **INGESTED** parsed into the named table(s) by the named parser (checked against the code by this script); **DISCOVERY_ONLY** vaulted (blob + `filings` row) and parsed for links / broadcast times only; no table of its own; **VAULTED_RAW** fetched and vaulted (blob + `filings` row) but never parsed; **NOT_INGESTED** nothing fetches, stages or promotes it (a parser may exist; see the note); **REFERENCE** documentation or test metadata, not a data feed.

## Summary

| Family | Example fixture | Source | Status | Table | Could serve |
|---|---|---|---|---|---|
| [NSE UDiFF CM bhavcopy](#nse-udiff-cm-bhavcopy) | `bhavcopy/BhavCopy_NSE_CM_0_0_0_20241206_F_0000.csv.zip!BhavCopy_NSE_CM_0_0_0_20241206_F_0000.csv` | F01 | INGESTED | raw_cm_bhavcopy, ohlcv, security_identifier_history, trading_calendar | none identified |
| [NSE security-wise delivery (sec_bhavdata_full)](#nse-security-wise-delivery-sec_bhavdata_full) | `bhavcopy/sec_bhavdata_full_12112026.csv` | F02 | INGESTED | raw_delivery, ohlcv | none identified |
| [NSE PR zip: mcap market capitalisation](#nse-pr-zip-mcap-market-capitalisation) | `pr_zip/PR011024.zip!MCAP01102024.csv` | F31 | INGESTED | raw_nse_mcap, universe_membership | none identified |
| [NSE PR zip: bh price-band hits](#nse-pr-zip-bh-price-band-hits) | `pr_zip/PR011024.zip!bh011024.csv` | F31 | INGESTED | raw_price_band_hits | G207 (MISSING), G140 (DOCUMENTED_PLANNED) |
| [NSE PR zip: bm board meetings](#nse-pr-zip-bm-board-meetings) | `pr_zip/PR011024.zip!Bm011024.txt` | F31 | NOT_INGESTED | — | G193 (DOCUMENTED_PLANNED) |
| [NSE PR zip: bc corporate actions (equity and debt series)](#nse-pr-zip-bc-corporate-actions-equity-and-debt-series) | `pr_zip/PR011024.zip!Bc011024.csv` | F31 | NOT_INGESTED | — | G195 (DOCUMENTED_PLANNED) |
| [NSE PR zip: an announcements](#nse-pr-zip-an-announcements) | `pr_zip/PR011024.zip!An011024.txt` | F31 | NOT_INGESTED | — | G193 (DOCUMENTED_PLANNED) |
| [NSE PR zip: corpbond corporate bond trades](#nse-pr-zip-corpbond-corporate-bond-trades) | `pr_zip/PR011024.zip!corpbond011024.csv` | F31 | NOT_INGESTED | — | G136 (MISSING) |
| [NSE PR zip: etf ETF market data](#nse-pr-zip-etf-etf-market-data) | `pr_zip/PR011024.zip!etf011024.csv` | F31 | NOT_INGESTED | — | none identified |
| [NSE PR zip: gl gainers and losers](#nse-pr-zip-gl-gainers-and-losers) | `pr_zip/PR011024.zip!Gl011024.csv` | F31 | NOT_INGESTED | — | none identified |
| [NSE PR zip: hl new 52-week highs / lows](#nse-pr-zip-hl-new-52-week-highs--lows) | `pr_zip/PR011024.zip!HL011024.csv` | F31 | NOT_INGESTED | — | none identified |
| [NSE PR zip: pd security-wise market data with symbol](#nse-pr-zip-pd-security-wise-market-data-with-symbol) | `pr_zip/PR011024.zip!Pd011024.csv` | F31 | NOT_INGESTED | — | none identified |
| [NSE PR zip: pr security-wise market data](#nse-pr-zip-pr-security-wise-market-data) | `pr_zip/PR011024.zip!Pr011024.csv` | F31 | NOT_INGESTED | — | none identified |
| [NSE PR zip: sme SME market data](#nse-pr-zip-sme-sme-market-data) | `pr_zip/PR011024.zip!sme011024.csv` | F31 | NOT_INGESTED | — | none identified |
| [NSE PR zip: tt top 25 by traded value](#nse-pr-zip-tt-top-25-by-traded-value) | `pr_zip/PR011024.zip!Tt011024.csv` | F31 | NOT_INGESTED | — | none identified |
| [NSE PR zip: PE_ symbol P/E (2024 zips only)](#nse-pr-zip-pe_-symbol-pe-2024-zips-only) | `pr_zip/PR011024.zip!PE_011024.csv` | F31 | NOT_INGESTED | — | none identified |
| [NSE PR zip: readme](#nse-pr-zip-readme) | `pr_zip/PR011024.zip!Readme.txt` | F31 | REFERENCE | — | none identified |
| [NSE corporate actions API](#nse-corporate-actions-api) | `corp_actions/nse_corporateActions_equities_15-09-2025_17-10-2025.json` | F03 | INGESTED | corp_actions, quarantine_queue | none identified |
| [NSE corporate actions RSS](#nse-corporate-actions-rss) | `corp_actions/RSS_Corporate_action_20261113.xml` | F03 | NOT_INGESTED | — | none identified |
| [NSE holiday master](#nse-holiday-master) | `calendar/nse_holiday-master_trading_20261113.json` | F04 | INGESTED | trading_calendar | none identified |
| [NSE Nifty 500 constituents list](#nse-nifty-500-constituents-list) | `indices/ind_nifty500list_20261113.csv` | F05 | INGESTED | raw_index_snapshot, index_constituents_history | none identified |
| [NSE Indices change notices (PDF + pdftotext)](#nse-indices-change-notices-pdf--pdftotext) | `index_changes/pdf/ind_prs04042025_2.pdf` | F05 | INGESTED | index_constituents_history | none identified |
| [NSE daily index closes (ind_close_all)](#nse-daily-index-closes-ind_close_all) | `indices/ind_close_all_13112026.csv` | F27 | INGESTED | index_ohlcv | none identified |
| [NSE equity master (EQUITY_L)](#nse-equity-master-equity_l) | `indices/nse_EQUITY_L_20261114.csv` | F28 | INGESTED | raw_equity_master | none identified |
| [NSE quote API industry classification](#nse-quote-api-industry-classification) | `classification/GetQuoteApi_getSymbolData_HDFCBANK.json` | F30 | INGESTED | raw_quote_classification, entity_classification_history | G207 (MISSING), G140 (DOCUMENTED_PLANNED), G141 (DOCUMENTED_PLANNED), G129 (MISSING) |
| [NSE Integrated Filing listing API](#nse-integrated-filing-listing-api) | `discovery/nse_integrated-filing-results_equities_ABBOTINDIA_20261117.json` | F06 | INGESTED | raw_results_listing | none identified |
| [NSE annual report XBRL listing API](#nse-annual-report-xbrl-listing-api) | `annual/nse_annual-reports-xbrl_TCS_20261113.json` | F07 | DISCOVERY_ONLY | — | none identified |
| [NSE shareholding master API](#nse-shareholding-master-api) | `discovery/nse_corporate-share-holdings-master_equities_ABBOTINDIA_20261117.json` | F08 | DISCOVERY_ONLY | — | none identified |
| [NSE announcements RSS (Online_announcements)](#nse-announcements-rss-online_announcements) | `events/nse_Online_announcements_20261113.xml` | F21 | DISCOVERY_ONLY | — | none identified |
| [NSE Integrated Filing results XBRL (Reg. 33)](#nse-integrated-filing-results-xbrl-reg-33) | `annual_checks/INTEGRATED_FILING_INDAS_1426806_28042025073334_WEB.xml` | F06, F10 | INGESTED | filing_meta, fact_observations, segment_observations, reg23_related_party_transactions, disclosure_facts, audit_opinions | none identified |
| [NSE Reg. 34 annual report XBRL](#nse-reg-34-annual-report-xbrl) | `annual_checks/AR_XBRL_GREENPLY_24092025103040.xml` | F07 | INGESTED | filing_meta, fact_observations, group_structure, related_party_transactions, disclosure_facts, audit_opinions | none identified |
| [NSE Reg. 31 shareholding pattern XBRL](#nse-reg-31-shareholding-pattern-xbrl) | `annual_checks/SHP_198395_1419898_19042025033622_WEB.xml` | F08 | INGESTED | shareholding_meta, shareholding_line_items, shareholding_major_holders, shareholding_observations, disclosure_facts | none identified |
| [NSE Reg. 30 structured event XBRL](#nse-reg-30-structured-event-xbrl) | `events/ALTERATION_OF_CAPITAL_AND_FUND_RAISING_818_WebXMLFile_20261113_152039711.xml` | F21 | INGESTED | corporate_events, disclosure_facts | none identified |
| [BSE equity UDiFF bhavcopy](#bse-equity-udiff-bhavcopy) | `bse/BhavCopy_BSE_CM_0_0_0_20261113_F_0000.CSV` | F34 | NOT_INGESTED | — | none identified |
| [BSE list of securities (ListofScripData)](#bse-list-of-securities-listofscripdata) | `bse/bse_ListofScripData_A_500488_20261117.json` | F35 | INGESTED | raw_bse_securities | none identified |
| [BSE announcements API (AnnSubCategoryGetData)](#bse-announcements-api-annsubcategorygetdata) | `bse/announcements.json` | F36 | VAULTED_RAW | — | G193 (DOCUMENTED_PLANNED) |
| [BSE announcement attachments (AttachLive)](#bse-announcement-attachments-attachlive) | `bse/AttachLive_e334e776-71a5-4afd-adf3-ad10a11505cf.pdf` | F36 | VAULTED_RAW | — | G62 (MISSING) |
| [BSE shareholding filings listing (Corp_Shareholding_ng)](#bse-shareholding-filings-listing-corp_shareholding_ng) | `bse/bse_Corp_Shareholding_ng_500488_flag6_20261117.json` | F36 | DISCOVERY_ONLY | — | none identified |
| [BSE Reg. 31 shareholding inline XBRL](#bse-reg-31-shareholding-inline-xbrl) | `bse/500488_14102026161949_SP.html` | F36 | INGESTED | shareholding_meta, shareholding_line_items, shareholding_major_holders, shareholding_observations, disclosure_facts | none identified |
| [BSE results listing (Corp_FinanceResult_ng_new)](#bse-results-listing-corp_financeresult_ng_new) | `bse/bse_Corp_FinanceResult_ng_new_500488_flagdur6_20261118.json` | F36 | DISCOVERY_ONLY | — | none identified |
| [BSE results XBRL (inline .html, NBFC plain .xml)](#bse-results-xbrl-inline-html-nbfc-plain-xml) | `bse/IFOtherthan_538668_1482025163259_IFOtherthan.html` | F36 | INGESTED | filing_meta, fact_observations, segment_observations, reg23_related_party_transactions, disclosure_facts, audit_opinions | none identified |
| [BSE announcement XBRL (CorpXbrlGen)](#bse-announcement-xbrl-corpxbrlgen) | `bse/CorpXbrlGen_500488_6fa639f3-1cba-42e1-a341-ab46e27899e6.xml` | — | NOT_INGESTED | — | none identified |
| [BSE legacy results page (Comp_Resultsnew)](#bse-legacy-results-page-comp_resultsnew) | `bse/beta_Comp_Resultsnew_expandable0_20261118.html` | — | NOT_INGESTED | — | none identified |
| [BSE results dropdown lists (Corp_GetFINANCE_DRDOWN_ng)](#bse-results-dropdown-lists-corp_getfinance_drdown_ng) | `bse/bse_Corp_GetFINANCE_DRDOWN_ng_flag1_20261118.json` | — | NOT_INGESTED | — | none identified |
| [SEBI circulars (PDF + pdftotext)](#sebi-circulars-pdf--pdftotext) | `circulars/sebi_cir_2024_185.pdf` | — | REFERENCE | — | none identified |
| [Fixture manifest](#fixture-manifest) | `MANIFEST.md` | — | REFERENCE | — | none identified |

## NSE UDiFF CM bhavcopy

| Field | Value |
|---|---|
| Content | End-of-day OHLC, volume, value, trades per instrument (ISIN, FinInstrmId, series) of the cash market; the price, identity and calendar spine. |
| Source | F01 (UDiFF cash-market bhavcopy) |
| Status | INGESTED |
| Tables | `raw_cm_bhavcopy`, `ohlcv`, `security_identifier_history`, `trading_calendar` |
| Parser | `financials.parsers.udiff:parse_udiff_cm` |
| Could serve | none identified |
| Files | 20 |

Columns: `TradDt`, `BizDt`, `Sgmt`, `Src`, `FinInstrmTp`, `FinInstrmId`, `ISIN`, `TckrSymb`, `SctySrs`, `XpryDt`, `FininstrmActlXpryDt`, `StrkPric`, `OptnTp`, `FinInstrmNm`, `OpnPric`, `HghPric`, `LwPric`, `ClsPric`, `LastPric`, `PrvsClsgPric`, `UndrlygPric`, `SttlmPric`, `OpnIntrst`, `ChngInOpnIntrst`, `TtlTradgVol`, `TtlTrfVal`, `TtlNbOfTxsExctd`, `SsnId`, `NewBrdLotQty`, `Rmks`, `Rsvd1`, `Rsvd2`, `Rsvd3`, `Rsvd4`

| File | Format | Rows | Description |
|---|---|---|---|
| `bhavcopy/BhavCopy_NSE_CM_0_0_0_20241206_F_0000.csv.zip!BhavCopy_NSE_CM_0_0_0_20241206_F_0000.csv` | CSV in ZIP | 2910 | UDiFF bhavcopy of 06-Dec-2024: identity of UPL-RE (`INE628A20010`, BE) and UPL (`INE628A01036`, EQ) for the PR zip of the same day [X311] |
| `bhavcopy/BhavCopy_NSE_CM_0_0_0_20250227_F_0000.csv.zip!BhavCopy_NSE_CM_0_0_0_20250227_F_0000.csv` | CSV in ZIP | 2952 | Day before HDFCLIQUID re-ISIN (CA13) |
| `bhavcopy/BhavCopy_NSE_CM_0_0_0_20250228_F_0000.csv.zip!BhavCopy_NSE_CM_0_0_0_20250228_F_0000.csv` | CSV in ZIP | 2988 | HDFCLIQUID new ISIN, no price effect (CA13) |
| `bhavcopy/BhavCopy_NSE_CM_0_0_0_20250919_F_0000.csv.zip!BhavCopy_NSE_CM_0_0_0_20250919_F_0000.csv` | CSV in ZIP | 3139 | Day before ADANIPOWER 1:5 split ex-date |
| `bhavcopy/BhavCopy_NSE_CM_0_0_0_20250922_F_0000.csv.zip!BhavCopy_NSE_CM_0_0_0_20250922_F_0000.csv` | CSV in ZIP | 3210 | ADANIPOWER split ex-date (ISIN change) |
| `bhavcopy/BhavCopy_NSE_CM_0_0_0_20250923_F_0000.csv.zip!BhavCopy_NSE_CM_0_0_0_20250923_F_0000.csv` | CSV in ZIP | 3144 | PIDILITIND 1:1 bonus ex-date (ISIN unchanged) |
| `bhavcopy/BhavCopy_NSE_CM_0_0_0_20251013_F_0000.csv.zip!BhavCopy_NSE_CM_0_0_0_20251013_F_0000.csv` | CSV in ZIP | 3218 | Day before TATAMOTORS demerger ex-date |
| `bhavcopy/BhavCopy_NSE_CM_0_0_0_20251014_F_0000.csv.zip!BhavCopy_NSE_CM_0_0_0_20251014_F_0000.csv` | CSV in ZIP | 3215 | TATAMOTORS demerger ex-date; TATAINVEST split |
| `bhavcopy/BhavCopy_NSE_CM_0_0_0_20251017_F_0000.csv.zip!BhavCopy_NSE_CM_0_0_0_20251017_F_0000.csv` | CSV in ZIP | 3168 | Friday before a weekend: PrvsClsgPric chain across Sat/Sun (CAL3) |
| `bhavcopy/BhavCopy_NSE_CM_0_0_0_20251020_F_0000.csv.zip!BhavCopy_NSE_CM_0_0_0_20251020_F_0000.csv` | CSV in ZIP | 3244 | Monday after the weekend; session before the Muhurat day (CAL2, CAL3) |
| `bhavcopy/BhavCopy_NSE_CM_0_0_0_20251021_F_0000.csv.zip!BhavCopy_NSE_CM_0_0_0_20251021_F_0000.csv` | CSV in ZIP | 3039 | Diwali Laxmi Pujan 2025: Muhurat session bhavcopy, turnover ~20% of 20 Oct (CAL2) |
| `bhavcopy/BhavCopy_NSE_CM_0_0_0_20251023_F_0000.csv.zip!BhavCopy_NSE_CM_0_0_0_20251023_F_0000.csv` | CSV in ZIP | 3219 | Session after the 22 Oct holiday: PrvsClsgPric = 21 Oct close for every security (CAL3) |
| `bhavcopy/BhavCopy_NSE_CM_0_0_0_20260226_F_0000.csv.zip!BhavCopy_NSE_CM_0_0_0_20260226_F_0000.csv` | CSV in ZIP | 3265 | Day before five Kotak ETF unit splits (CA13) |
| `bhavcopy/BhavCopy_NSE_CM_0_0_0_20260227_F_0000.csv.zip!BhavCopy_NSE_CM_0_0_0_20260227_F_0000.csv` | CSV in ZIP | 3243 | BANKNIFTY1, CONS, MIDCAP, NV20, SILVER1 re-ISIN at ~1/10 (CA13) |
| `bhavcopy/BhavCopy_NSE_CM_0_0_0_20261112_F_0000.csv.zip!BhavCopy_NSE_CM_0_0_0_20261112_F_0000.csv` | CSV in ZIP | 3727 | 2026-11-12: prices near ELIN's Q2 FY27 results/Reg. 31 filings; TATAMOTORS now trades as TMPV (same ISIN) |
| `identity/BhavCopy_NSE_CM_0_0_0_20241230_F_0000.csv.zip!BhavCopy_NSE_CM_0_0_0_20241230_F_0000.csv` | CSV in ZIP | 2956 | BCG (Brightcom Group) INE425B01027 in BZ, FinInstrmId 23580, open 10.31 close 10.25: its last bar before the suspension [X320] |
| `identity/BhavCopy_NSE_CM_0_0_0_20250714_F_0000.csv.zip!BhavCopy_NSE_CM_0_0_0_20250714_F_0000.csv` | CSV in ZIP | 3110 | BCG back in BE with a new FinInstrmId 8841, same ISIN, open 21.80 [X320, X321] |
| `series_switch/BhavCopy_NSE_CM_0_0_0_20261029_F_0000.csv.zip!BhavCopy_NSE_CM_0_0_0_20261029_F_0000.csv` | CSV in ZIP | 3697 | GFLLIMITED, KAMAHOLD, MAHSCOOTER, NSIL, PILANIINVS, TVSHLTD, ELCIDIN, KICL in EQ (their last EQ bar) [X323] |
| `series_switch/BhavCopy_NSE_CM_0_0_0_20261102_F_0000.csv.zip!BhavCopy_NSE_CM_0_0_0_20261102_F_0000.csv` | CSV in ZIP | 3715 | KAMAHOLD, MAHSCOOTER, TVSHLTD in BE [X323] |
| `series_switch/BhavCopy_NSE_CM_0_0_0_20261103_F_0000.csv.zip!BhavCopy_NSE_CM_0_0_0_20261103_F_0000.csv` | CSV in ZIP | 3717 | GFLLIMITED, NSIL, PILANIINVS in BE (KICL only from 9 Nov, ELCIDIN no bar) [X323] |

## NSE security-wise delivery (sec_bhavdata_full)

| Field | Value |
|---|---|
| Content | Per symbol / series: prices, traded quantity and deliverable quantity / percentage. |
| Source | F02 (Security-wise deliverable position) |
| Status | INGESTED |
| Tables | `raw_delivery`, `ohlcv` |
| Parser | `financials.parsers.delivery:parse_sec_bhavdata_full` |
| Could serve | none identified |
| Files | 2 |

Columns: `SYMBOL`, `SERIES`, `DATE1`, `PREV_CLOSE`, `OPEN_PRICE`, `HIGH_PRICE`, `LOW_PRICE`, `LAST_PRICE`, `CLOSE_PRICE`, `AVG_PRICE`, `TTL_TRD_QNTY`, `TURNOVER_LACS`, `NO_OF_TRADES`, `DELIV_QTY`, `DELIV_PER`

| File | Format | Rows | Description |
|---|---|---|---|
| `bhavcopy/sec_bhavdata_full_12112026.csv` | CSV | 3566 | Delivery file for 2026-11-12 |
| `bhavcopy/sec_bhavdata_full_14102025.csv` | CSV | 3044 | Delivery file for 2025-10-14 (`PREV_CLOSE`, `DELIV_QTY`) |

## NSE PR zip: mcap market capitalisation

| Field | Value |
|---|---|
| Content | Market cap, issue size, face value, category (Listed / Permitted) per symbol and series; rule U1 universe. |
| NSE readme.txt | mcapddmmyyyy.csv file contains market capitalization of all the listed and permitted companies of the exchange by using latest available price. |
| Source | F31 (NSE daily PR zip market-capitalisation file (mcapddmmyyyy.csv) and price-band file (bhddmmyyyy.csv)) |
| Status | INGESTED |
| Tables | `raw_nse_mcap`, `universe_membership` |
| Parser | `financials.parsers.pr_mcap:parse_pr_mcap` |
| Could serve | none identified |
| Files | 8 |

Columns: `Trade Date`, `Symbol`, `Series`, `Security Name`, `Category`, `Last Trade Date`, `Face Value(Rs.)`, `Issue Size`, `Close Price/Paid up value(Rs.)`, `Market Cap(Rs.)`

| File | Format | Rows | Description |
|---|---|---|---|
| `pr_zip/PR011024.zip!MCAP01102024.csv` | CSV in ZIP | 2451 | member of the PR zip of trade date 2024-10-01 |
| `pr_zip/PR061224.zip!MCAP06122024.csv` | CSV in ZIP | 2498 | member of the PR zip of trade date 2024-12-06 |
| `pr_zip/PR120126.zip!mcap12012026.csv` | CSV in ZIP | 2803 | member of the PR zip of trade date 2026-01-12 |
| `pr_zip/PR131126.zip!mcap13112026.csv` | CSV in ZIP | 3249 | member of the PR zip of trade date 2026-11-13 |
| `pr_zip/PR250926.zip!mcap25092026.csv` | CSV in ZIP | 3188 | member of the PR zip of trade date 2026-09-25 |
| `pr_zip/PR300625.zip!MCAP30062025.csv` | CSV in ZIP | 2631 | member of the PR zip of trade date 2025-06-30 |
| `pr_zip/PR300926.zip!mcap30092026.csv` | CSV in ZIP | 3198 | member of the PR zip of trade date 2026-09-30 |
| `series_switch/PR301026.zip!mcap30102026.csv` | CSV in ZIP | 3232 | member of the PR zip of trade date 2026-10-30 |

## NSE PR zip: bh price-band hits

| Field | Value |
|---|---|
| Content | Securities that hit their upper (H) or lower (L) price band during the day. The band itself and whether the stock stayed locked are not in the file (circuit days read the close from our own bar, X359). |
| NSE readme.txt | bhddmmyyyy.csv file contains a list of securities which have hit their price bands during the day. |
| Source | F31 (NSE daily PR zip market-capitalisation file (mcapddmmyyyy.csv) and price-band file (bhddmmyyyy.csv)) |
| Status | INGESTED |
| Tables | `raw_price_band_hits` |
| Parser | `financials.parsers.pr_bands:parse_price_band_hits` |
| Could serve | G207 (MISSING): circuit days: one H / L row per security per day that touched its band; G140 (DOCUMENTED_PLANNED): band hits per day; the band percentage itself is not in the file |
| Files | 8 |

Columns (3 of 8 files): `SYMBOL`, `SERIES`, `SECURITY`, `HIGH/LOW`, `INDEX FLAG`

Columns (5 of 8 files): `SYMBOL`, `SERIES`, `SECURITY`, `HIGH/LOW`

| File | Format | Rows | Description |
|---|---|---|---|
| `pr_zip/PR011024.zip!bh011024.csv` | CSV in ZIP | 243 | member of the PR zip of trade date 2024-10-01 |
| `pr_zip/PR061224.zip!bh061224.csv` | CSV in ZIP | 202 | member of the PR zip of trade date 2024-12-06 |
| `pr_zip/PR120126.zip!bh12012026.csv` | CSV in ZIP | 0 | member of the PR zip of trade date 2026-01-12 |
| `pr_zip/PR131126.zip!bh13112026.csv` | CSV in ZIP | 251 | member of the PR zip of trade date 2026-11-13 |
| `pr_zip/PR250926.zip!bh25092026.csv` | CSV in ZIP | 259 | member of the PR zip of trade date 2026-09-25 |
| `pr_zip/PR300625.zip!bh300625.csv` | CSV in ZIP | 225 | member of the PR zip of trade date 2025-06-30 |
| `pr_zip/PR300926.zip!bh30092026.csv` | CSV in ZIP | 305 | member of the PR zip of trade date 2026-09-30 |
| `series_switch/PR301026.zip!bh30102026.csv` | CSV in ZIP | 290 | member of the PR zip of trade date 2026-10-30 |

## NSE PR zip: bm board meetings

| Field | Value |
|---|---|
| Content | Board meetings intimated: company, symbol, meeting date and purpose (financial results, dividend, fund raising, re-scheduling). |
| NSE readme.txt | bmddmmyyyy.txt file contains details of Board Meetings of companies |
| Source | F31 (NSE daily PR zip market-capitalisation file (mcapddmmyyyy.csv) and price-band file (bhddmmyyyy.csv)) |
| Status | NOT_INGESTED |
| Tables | — |
| Parser | — |
| Could serve | G193 (DOCUMENTED_PLANNED): board-meeting intimations with the meeting date (forward calendar) |
| Files | 8 |

Columns: header line `COMPANY NAME SYMBOL : BM DATE : BM PURPOSE`

| File | Format | Rows | Description |
|---|---|---|---|
| `pr_zip/PR011024.zip!Bm011024.txt` | TXT in ZIP | 40 | member of the PR zip of trade date 2024-10-01 |
| `pr_zip/PR061224.zip!Bm061224.txt` | TXT in ZIP | 6 | member of the PR zip of trade date 2024-12-06 |
| `pr_zip/PR120126.zip!bm12012026.txt` | TXT in ZIP | 81 | member of the PR zip of trade date 2026-01-12 |
| `pr_zip/PR131126.zip!bm13112026.txt` | TXT in ZIP | 14 | member of the PR zip of trade date 2026-11-13 |
| `pr_zip/PR250926.zip!bm25092026.txt` | TXT in ZIP | 22 | member of the PR zip of trade date 2026-09-25 |
| `pr_zip/PR300625.zip!Bm300625.txt` | TXT in ZIP | 23 | member of the PR zip of trade date 2025-06-30 |
| `pr_zip/PR300926.zip!bm30092026.txt` | TXT in ZIP | 13 | member of the PR zip of trade date 2026-09-30 |
| `series_switch/PR301026.zip!bm30102026.txt` | TXT in ZIP | 140 | member of the PR zip of trade date 2026-10-30 |

## NSE PR zip: bc corporate actions (equity and debt series)

| Field | Value |
|---|---|
| Content | Record / book-closure / ex / no-delivery dates and purpose per series, including debt series (interest payment, redemption, call). |
| NSE readme.txt | bcddmmyyyy.csv file contains the corporate action details for securities. |
| Source | F31 (NSE daily PR zip market-capitalisation file (mcapddmmyyyy.csv) and price-band file (bhddmmyyyy.csv)) |
| Status | NOT_INGESTED |
| Tables | — |
| Parser | — |
| Could serve | G195 (DOCUMENTED_PLANNED): scheduled interest / redemption record dates of listed debt series (not defaults) |
| Files | 8 |

Columns: `SERIES`, `SYMBOL`, `SECURITY`, `RECORD_DT`, `BC_STRT_DT`, `BC_END_DT`, `EX_DT`, `ND_STRT_DT`, `ND_END_DT`, `PURPOSE`

| File | Format | Rows | Description |
|---|---|---|---|
| `pr_zip/PR011024.zip!Bc011024.csv` | CSV in ZIP | 48 | member of the PR zip of trade date 2024-10-01 |
| `pr_zip/PR061224.zip!Bc061224.csv` | CSV in ZIP | 89 | member of the PR zip of trade date 2024-12-06 |
| `pr_zip/PR120126.zip!bc12012026.csv` | CSV in ZIP | 230 | member of the PR zip of trade date 2026-01-12 |
| `pr_zip/PR131126.zip!bc13112026.csv` | CSV in ZIP | 367 | member of the PR zip of trade date 2026-11-13 |
| `pr_zip/PR250926.zip!bc25092026.csv` | CSV in ZIP | 82 | member of the PR zip of trade date 2026-09-25 |
| `pr_zip/PR300625.zip!Bc300625.csv` | CSV in ZIP | 51 | member of the PR zip of trade date 2025-06-30 |
| `pr_zip/PR300926.zip!bc30092026.csv` | CSV in ZIP | 159 | member of the PR zip of trade date 2026-09-30 |
| `series_switch/PR301026.zip!bc30102026.csv` | CSV in ZIP | 239 | member of the PR zip of trade date 2026-10-30 |

## NSE PR zip: an announcements

| Field | Value |
|---|---|
| Content | One line per announcement: company, symbol, subject category and the summary text. |
| NSE readme.txt | anddmmyyyy.txt file contains name of the co., its symbol and the announcements made during the day. |
| Source | F31 (NSE daily PR zip market-capitalisation file (mcapddmmyyyy.csv) and price-band file (bhddmmyyyy.csv)) |
| Status | NOT_INGESTED |
| Tables | — |
| Parser | — |
| Could serve | G193 (DOCUMENTED_PLANNED): subject lines such as 'Shareholders meeting' (text only, no structured date) |
| Files | 8 |

Columns: header line `COMPANY NAME SYMBOL : ANNOUNCEMENTS`

| File | Format | Rows | Description |
|---|---|---|---|
| `pr_zip/PR011024.zip!An011024.txt` | TXT in ZIP | 2109 | member of the PR zip of trade date 2024-10-01 |
| `pr_zip/PR061224.zip!An061224.txt` | TXT in ZIP | 657 | member of the PR zip of trade date 2024-12-06 |
| `pr_zip/PR120126.zip!an12012026.txt` | TXT in ZIP | 1778 | member of the PR zip of trade date 2026-01-12 |
| `pr_zip/PR131126.zip!an13112026.txt` | TXT in ZIP | 2105 | member of the PR zip of trade date 2026-11-13 |
| `pr_zip/PR250926.zip!an25092026.txt` | TXT in ZIP | 2543 | member of the PR zip of trade date 2026-09-25 |
| `pr_zip/PR300625.zip!An300625.txt` | TXT in ZIP | 1472 | member of the PR zip of trade date 2025-06-30 |
| `pr_zip/PR300926.zip!an30092026.txt` | TXT in ZIP | 2285 | member of the PR zip of trade date 2026-09-30 |
| `series_switch/PR301026.zip!an30102026.txt` | TXT in ZIP | 1963 | member of the PR zip of trade date 2026-10-30 |

## NSE PR zip: corpbond corporate bond trades

| Field | Value |
|---|---|
| Content | Prices, traded value / quantity and 52-week range of corporate bonds traded on the day (coupon and maturity only inside the security name). |
| NSE readme.txt | corpbondddmmyyyy.csv file contains market data of Corporate bonds traded during the day. |
| Source | F31 (NSE daily PR zip market-capitalisation file (mcapddmmyyyy.csv) and price-band file (bhddmmyyyy.csv)) |
| Status | NOT_INGESTED |
| Tables | — |
| Parser | — |
| Could serve | G136 (MISSING): secondary-market bond prices; a yield would have to be computed from the name's coupon and maturity |
| Files | 8 |

Columns: `MARKET`, `SERIES`, `SYMBOL`, `SECURITY`, `PREV_CL_PR`, `OPEN_PRICE`, `HIGH_PRICE`, `LOW_PRICE`, `CLOSE_PRICE`, `NET_TRDVAL`, `NET_TRDQTY`, `CORP_IND`, `TRADES`, `HI_52_WK`, `LO_52_WK`

| File | Format | Rows | Description |
|---|---|---|---|
| `pr_zip/PR011024.zip!corpbond011024.csv` | CSV in ZIP | 144 | member of the PR zip of trade date 2024-10-01 |
| `pr_zip/PR061224.zip!corpbond061224.csv` | CSV in ZIP | 138 | member of the PR zip of trade date 2024-12-06 |
| `pr_zip/PR120126.zip!corpbond12012026.csv` | CSV in ZIP | 134 | member of the PR zip of trade date 2026-01-12 |
| `pr_zip/PR131126.zip!corpbond13112026.csv` | CSV in ZIP | 142 | member of the PR zip of trade date 2026-11-13 |
| `pr_zip/PR250926.zip!corpbond25092026.csv` | CSV in ZIP | 123 | member of the PR zip of trade date 2026-09-25 |
| `pr_zip/PR300625.zip!corpbond300625.csv` | CSV in ZIP | 129 | member of the PR zip of trade date 2025-06-30 |
| `pr_zip/PR300926.zip!corpbond30092026.csv` | CSV in ZIP | 131 | member of the PR zip of trade date 2026-09-30 |
| `series_switch/PR301026.zip!corpbond30102026.csv` | CSV in ZIP | 116 | member of the PR zip of trade date 2026-10-30 |

## NSE PR zip: etf ETF market data

| Field | Value |
|---|---|
| Content | Prices, traded value / quantity and underlying index of every ETF traded. |
| NSE readme.txt | etfddmmyyyy.csv file contains market data of exchange traded funds traded during the day. |
| Source | F31 (NSE daily PR zip market-capitalisation file (mcapddmmyyyy.csv) and price-band file (bhddmmyyyy.csv)) |
| Status | NOT_INGESTED |
| Tables | — |
| Parser | — |
| Could serve | none identified |
| Files | 8 |

Columns: `MARKET`, `SERIES`, `SYMBOL`, `SECURITY`, `PREVIOUS CLOSE PRICE`, `OPEN PRICE`, `HIGH PRICE`, `LOW PRICE`, `CLOSE PRICE`, `NET TRADED VALUE`, `NET TRADED QTY`, `TRADES`, `52 WEEK HIGH`, `52 WEEK LOW`, `UNDERLYING`

| File | Format | Rows | Description |
|---|---|---|---|
| `pr_zip/PR011024.zip!etf011024.csv` | CSV in ZIP | 219 | member of the PR zip of trade date 2024-10-01 |
| `pr_zip/PR061224.zip!etf061224.csv` | CSV in ZIP | 224 | member of the PR zip of trade date 2024-12-06 |
| `pr_zip/PR120126.zip!etf12012026.csv` | CSV in ZIP | 304 | member of the PR zip of trade date 2026-01-12 |
| `pr_zip/PR131126.zip!etf13112026.csv` | CSV in ZIP | 312 | member of the PR zip of trade date 2026-11-13 |
| `pr_zip/PR250926.zip!etf25092026.csv` | CSV in ZIP | 306 | member of the PR zip of trade date 2026-09-25 |
| `pr_zip/PR300625.zip!etf300625.csv` | CSV in ZIP | 257 | member of the PR zip of trade date 2025-06-30 |
| `pr_zip/PR300926.zip!etf30092026.csv` | CSV in ZIP | 304 | member of the PR zip of trade date 2026-09-30 |
| `series_switch/PR301026.zip!etf30102026.csv` | CSV in ZIP | 310 | member of the PR zip of trade date 2026-10-30 |

## NSE PR zip: gl gainers and losers

| Field | Value |
|---|---|
| Content | Top gainers / losers of Nifty 50, Nifty Next 50 and other securities (close, previous close, % change). |
| NSE readme.txt | glddmmyyyy.csv file contains a list of the gainers and losers for Nifty Securities, Nifty Next 50 Securities and for other Securities. |
| Source | F31 (NSE daily PR zip market-capitalisation file (mcapddmmyyyy.csv) and price-band file (bhddmmyyyy.csv)) |
| Status | NOT_INGESTED |
| Tables | — |
| Parser | — |
| Could serve | none identified |
| Files | 8 |

Columns: `GAIN_LOSS`, `SECURITY`, `CLOSE_PRIC`, `PREV_CL_PR`, `PERCENT_CG`

| File | Format | Rows | Description |
|---|---|---|---|
| `pr_zip/PR011024.zip!Gl011024.csv` | CSV in ZIP | 162 | member of the PR zip of trade date 2024-10-01 |
| `pr_zip/PR061224.zip!Gl061224.csv` | CSV in ZIP | 162 | member of the PR zip of trade date 2024-12-06 |
| `pr_zip/PR120126.zip!gl12012026.csv` | CSV in ZIP | 3013 | member of the PR zip of trade date 2026-01-12 |
| `pr_zip/PR131126.zip!gl13112026.csv` | CSV in ZIP | 3381 | member of the PR zip of trade date 2026-11-13 |
| `pr_zip/PR250926.zip!gl25092026.csv` | CSV in ZIP | 3279 | member of the PR zip of trade date 2026-09-25 |
| `pr_zip/PR300625.zip!Gl300625.csv` | CSV in ZIP | 163 | member of the PR zip of trade date 2025-06-30 |
| `pr_zip/PR300926.zip!gl30092026.csv` | CSV in ZIP | 3316 | member of the PR zip of trade date 2026-09-30 |
| `series_switch/PR301026.zip!gl30102026.csv` | CSV in ZIP | 3293 | member of the PR zip of trade date 2026-10-30 |

## NSE PR zip: hl new 52-week highs / lows

| Field | Value |
|---|---|
| Content | Securities (equity and ETFs) at a new high or low: new and previous value, H / L. |
| NSE readme.txt | hlddmmyyyy.csv file contains the list of securities (Equity and ETFs) which have reached a new high or a new low. |
| Source | F31 (NSE daily PR zip market-capitalisation file (mcapddmmyyyy.csv) and price-band file (bhddmmyyyy.csv)) |
| Status | NOT_INGESTED |
| Tables | — |
| Parser | — |
| Could serve | none identified |
| Files | 8 |

Columns: `SECURITY`, `NEW`, `PREVIOUS`, `NEW_STATUS`

| File | Format | Rows | Description |
|---|---|---|---|
| `pr_zip/PR011024.zip!HL011024.csv` | CSV in ZIP | 173 | member of the PR zip of trade date 2024-10-01 |
| `pr_zip/PR061224.zip!HL061224.csv` | CSV in ZIP | 167 | member of the PR zip of trade date 2024-12-06 |
| `pr_zip/PR120126.zip!hl12012026.csv` | CSV in ZIP | 209 | member of the PR zip of trade date 2026-01-12 |
| `pr_zip/PR131126.zip!hl13112026.csv` | CSV in ZIP | 85 | member of the PR zip of trade date 2026-11-13 |
| `pr_zip/PR250926.zip!hl25092026.csv` | CSV in ZIP | 108 | member of the PR zip of trade date 2026-09-25 |
| `pr_zip/PR300625.zip!HL300625.csv` | CSV in ZIP | 170 | member of the PR zip of trade date 2025-06-30 |
| `pr_zip/PR300926.zip!hl30092026.csv` | CSV in ZIP | 134 | member of the PR zip of trade date 2026-09-30 |
| `series_switch/PR301026.zip!hl30102026.csv` | CSV in ZIP | 141 | member of the PR zip of trade date 2026-10-30 |

## NSE PR zip: pd security-wise market data with symbol

| Field | Value |
|---|---|
| Content | Index rows then security rows: prices, traded value / quantity, trades, 52-week range (unadjusted), with symbol and series. |
| NSE readme.txt | pdddmmyyyy.csv file also contains Symbol and Series codes for each Security in addition to the information contained in the prddmmyyyy.csv file. 52 week high & 52 week low prices are not adjusted for Bonus, Split & Rights corporate actions |
| Source | F31 (NSE daily PR zip market-capitalisation file (mcapddmmyyyy.csv) and price-band file (bhddmmyyyy.csv)) |
| Status | NOT_INGESTED |
| Tables | — |
| Parser | — |
| Could serve | none identified |
| Files | 8 |

Columns: `MKT`, `SERIES`, `SYMBOL`, `SECURITY`, `PREV_CL_PR`, `OPEN_PRICE`, `HIGH_PRICE`, `LOW_PRICE`, `CLOSE_PRICE`, `NET_TRDVAL`, `NET_TRDQTY`, `IND_SEC`, `CORP_IND`, `TRADES`, `HI_52_WK`, `LO_52_WK`

| File | Format | Rows | Description |
|---|---|---|---|
| `pr_zip/PR011024.zip!Pd011024.csv` | CSV in ZIP | 2969 | member of the PR zip of trade date 2024-10-01 |
| `pr_zip/PR061224.zip!Pd061224.csv` | CSV in ZIP | 3013 | member of the PR zip of trade date 2024-12-06 |
| `pr_zip/PR120126.zip!pd12012026.csv` | CSV in ZIP | 3380 | member of the PR zip of trade date 2026-01-12 |
| `pr_zip/PR131126.zip!pd13112026.csv` | CSV in ZIP | 3873 | member of the PR zip of trade date 2026-11-13 |
| `pr_zip/PR250926.zip!pd25092026.csv` | CSV in ZIP | 3800 | member of the PR zip of trade date 2026-09-25 |
| `pr_zip/PR300625.zip!Pd300625.csv` | CSV in ZIP | 3203 | member of the PR zip of trade date 2025-06-30 |
| `pr_zip/PR300926.zip!pd30092026.csv` | CSV in ZIP | 3842 | member of the PR zip of trade date 2026-09-30 |
| `series_switch/PR301026.zip!pd30102026.csv` | CSV in ZIP | 3787 | member of the PR zip of trade date 2026-10-30 |

## NSE PR zip: pr security-wise market data

| Field | Value |
|---|---|
| Content | The pd file without symbol and series columns. |
| NSE readme.txt | prddmmyyyy.csv file contains security wise market data information along with the Index details. 52 week high & 52 week low prices are not adjusted for Bonus, Split & Rights corporate actions |
| Source | F31 (NSE daily PR zip market-capitalisation file (mcapddmmyyyy.csv) and price-band file (bhddmmyyyy.csv)) |
| Status | NOT_INGESTED |
| Tables | — |
| Parser | — |
| Could serve | none identified |
| Files | 8 |

Columns: `MKT`, `SECURITY`, `PREV_CL_PR`, `OPEN_PRICE`, `HIGH_PRICE`, `LOW_PRICE`, `CLOSE_PRICE`, `NET_TRDVAL`, `NET_TRDQTY`, `IND_SEC`, `CORP_IND`, `TRADES`, `HI_52_WK`, `LO_52_WK`

| File | Format | Rows | Description |
|---|---|---|---|
| `pr_zip/PR011024.zip!Pr011024.csv` | CSV in ZIP | 2967 | member of the PR zip of trade date 2024-10-01 |
| `pr_zip/PR061224.zip!Pr061224.csv` | CSV in ZIP | 3011 | member of the PR zip of trade date 2024-12-06 |
| `pr_zip/PR120126.zip!pr12012026.csv` | CSV in ZIP | 3380 | member of the PR zip of trade date 2026-01-12 |
| `pr_zip/PR131126.zip!pr13112026.csv` | CSV in ZIP | 3873 | member of the PR zip of trade date 2026-11-13 |
| `pr_zip/PR250926.zip!pr25092026.csv` | CSV in ZIP | 3800 | member of the PR zip of trade date 2026-09-25 |
| `pr_zip/PR300625.zip!Pr300625.csv` | CSV in ZIP | 3201 | member of the PR zip of trade date 2025-06-30 |
| `pr_zip/PR300926.zip!pr30092026.csv` | CSV in ZIP | 3842 | member of the PR zip of trade date 2026-09-30 |
| `series_switch/PR301026.zip!pr30102026.csv` | CSV in ZIP | 3787 | member of the PR zip of trade date 2026-10-30 |

## NSE PR zip: sme SME market data

| Field | Value |
|---|---|
| Content | Market data of SME securities (SME is outside the universe). |
| NSE readme.txt | smeddmmyyyy.csv file contains market data of SME securities traded during the day. |
| Source | F31 (NSE daily PR zip market-capitalisation file (mcapddmmyyyy.csv) and price-band file (bhddmmyyyy.csv)) |
| Status | NOT_INGESTED |
| Tables | — |
| Parser | — |
| Could serve | none identified |
| Files | 8 |

Columns: `MARKET`, `SERIES`, `SYMBOL`, `SECURITY`, `PREV_CL_PR`, `OPEN_PRICE`, `HIGH_PRICE`, `LOW_PRICE`, `CLOSE_PRICE`, `NET_TRDVAL`, `NET_TRDQTY`, `CORP_IND`, `HI_52_WK`, `LO_52_WK`

| File | Format | Rows | Description |
|---|---|---|---|
| `pr_zip/PR011024.zip!sme011024.csv` | CSV in ZIP | 357 | member of the PR zip of trade date 2024-10-01 |
| `pr_zip/PR061224.zip!sme061224.csv` | CSV in ZIP | 368 | member of the PR zip of trade date 2024-12-06 |
| `pr_zip/PR120126.zip!sme12012026.csv` | CSV in ZIP | 431 | member of the PR zip of trade date 2026-01-12 |
| `pr_zip/PR131126.zip!sme13112026.csv` | CSV in ZIP | 472 | member of the PR zip of trade date 2026-11-13 |
| `pr_zip/PR250926.zip!sme25092026.csv` | CSV in ZIP | 465 | member of the PR zip of trade date 2026-09-25 |
| `pr_zip/PR300625.zip!sme300625.csv` | CSV in ZIP | 413 | member of the PR zip of trade date 2025-06-30 |
| `pr_zip/PR300926.zip!sme30092026.csv` | CSV in ZIP | 478 | member of the PR zip of trade date 2026-09-30 |
| `series_switch/PR301026.zip!sme30102026.csv` | CSV in ZIP | 443 | member of the PR zip of trade date 2026-10-30 |

## NSE PR zip: tt top 25 by traded value

| Field | Value |
|---|---|
| Content | The day's 25 securities with the highest traded value. |
| NSE readme.txt | ttddmmyyyy.csv file contains a list of top twenty five securities by traded value. |
| Source | F31 (NSE daily PR zip market-capitalisation file (mcapddmmyyyy.csv) and price-band file (bhddmmyyyy.csv)) |
| Status | NOT_INGESTED |
| Tables | — |
| Parser | — |
| Could serve | none identified |
| Files | 8 |

Columns: `SECURITY`, `PREV_CL_PR`, `CLOSE_PRIC`, `NET_TRDQTY`, `NET_TRDVAL`

| File | Format | Rows | Description |
|---|---|---|---|
| `pr_zip/PR011024.zip!Tt011024.csv` | CSV in ZIP | 25 | member of the PR zip of trade date 2024-10-01 |
| `pr_zip/PR061224.zip!Tt061224.csv` | CSV in ZIP | 25 | member of the PR zip of trade date 2024-12-06 |
| `pr_zip/PR120126.zip!tt12012026.csv` | CSV in ZIP | 25 | member of the PR zip of trade date 2026-01-12 |
| `pr_zip/PR131126.zip!tt13112026.csv` | CSV in ZIP | 25 | member of the PR zip of trade date 2026-11-13 |
| `pr_zip/PR250926.zip!tt25092026.csv` | CSV in ZIP | 25 | member of the PR zip of trade date 2026-09-25 |
| `pr_zip/PR300625.zip!Tt300625.csv` | CSV in ZIP | 25 | member of the PR zip of trade date 2025-06-30 |
| `pr_zip/PR300926.zip!tt30092026.csv` | CSV in ZIP | 25 | member of the PR zip of trade date 2026-09-30 |
| `series_switch/PR301026.zip!tt30102026.csv` | CSV in ZIP | 25 | member of the PR zip of trade date 2026-10-30 |

## NSE PR zip: PE_ symbol P/E (2024 zips only)

| Field | Value |
|---|---|
| Content | NSE's Symbol P/E and Adjusted P/E per symbol (four quarters' profit; adjusted excludes exceptional items net of tax). Present in the 2024 zips only, absent from 2025 on. |
| NSE readme.txt | PE_ddmmyy.csv file contains list of Companies indicated with its Symbol, Symbol P/E and Adjusted P/E where,Symbol P/E ratio is computed considering consecutive four quarters Net Profit, issued capital and previous day closing price of the Company. Adjusted P/E ratio is computed considering consecutive four quarters Net Profit after adjustment of Exceptional items (net of tax), issued capital and previous day closing price of the Company. |
| Source | F31 (NSE daily PR zip market-capitalisation file (mcapddmmyyyy.csv) and price-band file (bhddmmyyyy.csv)) |
| Status | NOT_INGESTED |
| Tables | — |
| Parser | — |
| Could serve | none identified |
| Files | 2 |

Columns: `SYMBOL`, `SYMBOL P/E`, `ADJUSTED P/E`

| File | Format | Rows | Description |
|---|---|---|---|
| `pr_zip/PR011024.zip!PE_011024.csv` | CSV in ZIP | 1791 | member of the PR zip of trade date 2024-10-01 |
| `pr_zip/PR061224.zip!PE_061224.csv` | CSV in ZIP | 1761 | member of the PR zip of trade date 2024-12-06 |

## NSE PR zip: readme

| Field | Value |
|---|---|
| Content | NSE's own description of every member; the source of the per-member sentences in this catalogue. |
| NSE readme.txt | readme.txt is a informative file which contains information about data and structure of all other files. |
| Source | F31 (NSE daily PR zip market-capitalisation file (mcapddmmyyyy.csv) and price-band file (bhddmmyyyy.csv)) |
| Status | REFERENCE |
| Tables | — |
| Parser | — |
| Could serve | none identified |
| Files | 8 |

| File | Format | Rows | Description |
|---|---|---|---|
| `pr_zip/PR011024.zip!Readme.txt` | TXT in ZIP | 62 lines | member of the PR zip of trade date 2024-10-01 |
| `pr_zip/PR061224.zip!Readme.txt` | TXT in ZIP | 62 lines | member of the PR zip of trade date 2024-12-06 |
| `pr_zip/PR120126.zip!readme.txt` | TXT in ZIP | 55 lines | member of the PR zip of trade date 2026-01-12 |
| `pr_zip/PR131126.zip!readme.txt` | TXT in ZIP | 55 lines | member of the PR zip of trade date 2026-11-13 |
| `pr_zip/PR250926.zip!readme.txt` | TXT in ZIP | 55 lines | member of the PR zip of trade date 2026-09-25 |
| `pr_zip/PR300625.zip!Readme.txt` | TXT in ZIP | 53 lines | member of the PR zip of trade date 2025-06-30 |
| `pr_zip/PR300926.zip!readme.txt` | TXT in ZIP | 55 lines | member of the PR zip of trade date 2026-09-30 |
| `series_switch/PR301026.zip!readme.txt` | TXT in ZIP | 55 lines | member of the PR zip of trade date 2026-10-30 |

## NSE corporate actions API

| Field | Value |
|---|---|
| Content | Equity corporate actions of a date window: symbol, series, ISIN, face value, subject text, ex / record dates; the subject is parsed into typed components. |
| Source | F03 (Corporate actions API and RSS) |
| Status | INGESTED |
| Tables | `corp_actions`, `quarantine_queue` |
| Parser | `financials.parsers.nse_corp_actions:parse_nse_corp_actions_json` |
| Could serve | none identified |
| Files | 18 |

Columns: list; record: bcEndDate, bcStartDate, caBroadcastDate, comp, exDate, faceVal, ind, isin, ndEndDate, ndStartDate, recDate, series, subject, symbol

| File | Format | Rows | Description |
|---|---|---|---|
| `corp_actions/nse_corporateActions_equities_15-09-2025_17-10-2025.json` | JSON | 265 | — |
| `corp_actions/nse_corporateActions_equities_16-11-2026_15-12-2026.json` | JSON | 47 | Daily run 2026-11-23 (vault blob, unmodified): PRAXIS `Rights 5:9` with no issue price, face value 5, ex 18-Nov-2026 (rule RIGHTS_PRICE_UNSTATED, X355); also priced rights SMLMAH, BONLON |
| `corp_actions/nse_corporateActions_equities_21-09-2026_20-10-2026.json` | JSON | 155 | Live backfill 2026-11-14: real purpose texts for the CA11 rules (AGM/EGM, dividend combinations, typos, rights, consolidation) |
| `corp_actions/nse_corporateActions_equities_21-10-2026_19-11-2026.json` | JSON | 197 | Live backfill 2026-11-14: real purpose texts for the CA11 rules (AGM/EGM, dividend combinations, typos, rights, consolidation) |
| `corp_actions/nse_corporateActions_equities_22-08-2026_20-09-2026.json` | JSON | 425 | Live backfill 2026-11-14: real purpose texts for the CA11 rules (AGM/EGM, dividend combinations, typos, rights, consolidation) |
| `corp_actions/nse_corporateActions_equities_23-02-2026_24-03-2026.json` | JSON | 52 | Vault blob, unmodified: 5PAISA `Rights 1:2 @ Premium Rs 290/-` (face value 10, issue price 300, ex 17-Mar-2026; cum close 292.55: X356) |
| `corp_actions/nse_corporateActions_equities_23-06-2026_22-07-2026.json` | JSON | 250 | Live backfill 2026-11-14: real purpose texts for the CA11 rules (AGM/EGM, dividend combinations, typos, rights, consolidation) |
| `corp_actions/nse_corporateActions_equities_23-07-2026_21-08-2026.json` | JSON | 454 | Live backfill 2026-11-14: real purpose texts for the CA11 rules (AGM/EGM, dividend combinations, typos, rights, consolidation) |
| `corp_actions/nse_corporateActions_equities_24-01-2026_22-02-2026.json` | JSON | 224 | Live backfill 2026-11-14: real purpose texts for the CA11 rules (AGM/EGM, dividend combinations, typos, rights, consolidation) |
| `corp_actions/nse_corporateActions_equities_24-05-2026_22-06-2026.json` | JSON | 134 | Live backfill 2026-11-14: real purpose texts for the CA11 rules (AGM/EGM, dividend combinations, typos, rights, consolidation) |
| `corp_actions/nse_corporateActions_equities_25-12-2025_23-01-2026.json` | JSON | 36 | Live backfill 2026-11-14: real purpose texts for the CA11 rules (AGM/EGM, dividend combinations, typos, rights, consolidation) |
| `corp_actions/nse_corporateActions_equities_28-02-2025_29-03-2025.json` | JSON | 57 | Live backfill 2026-11-14: real purpose texts for the CA11 rules (AGM/EGM, dividend combinations, typos, rights, consolidation) |
| `corp_actions/nse_corporateActions_equities_28-06-2025_27-07-2025.json` | JSON | 261 | Live backfill 2026-11-14: real purpose texts for the CA11 rules (AGM/EGM, dividend combinations, typos, rights, consolidation) |
| `corp_actions/nse_corporateActions_equities_29-01-2025_27-02-2025.json` | JSON | 192 | Live backfill 2026-11-14: real purpose texts for the CA11 rules (AGM/EGM, dividend combinations, typos, rights, consolidation) |
| `corp_actions/nse_corporateActions_equities_29-05-2025_27-06-2025.json` | JSON | 155 | Live backfill 2026-11-14: real purpose texts for the CA11 rules (AGM/EGM, dividend combinations, typos, rights, consolidation) |
| `corp_actions/nse_corporateActions_equities_30-03-2025_28-04-2025.json` | JSON | 35 | Vault blob, unmodified: GATECHDVR / GATECH `Rights 51:82 @ Premium Rs 0/-` (face value 1, ex 28-Apr-2025; cum close 0.88, issue price 1 above it: rule RIGHTS_AT_OR_ABOVE_MARKET, X356) |
| `corp_actions/nse_corporateActions_equities_30-12-2024_28-01-2025.json` | JSON | 45 | Live backfill 2026-11-14: real purpose texts for the CA11 rules (AGM/EGM, dividend combinations, typos, rights, consolidation) |
| `corp_actions/nse_corporateActions_equities_31-10-2024_29-11-2024.json` | JSON | 165 | Live backfill 2026-11-14: real purpose texts for the CA11 rules (AGM/EGM, dividend combinations, typos, rights, consolidation) |

## NSE corporate actions RSS

| Field | Value |
|---|---|
| Content | RSS items of recent corporate actions. parse_corp_action_rss exists (tests only); nothing fetches it. |
| Source | F03 (Corporate actions API and RSS) |
| Status | NOT_INGESTED |
| Tables | — |
| Parser | — |
| Could serve | none identified |
| Files | 1 |

Columns: root `rss`; item: title, link, description, pubDate

| File | Format | Rows | Description |
|---|---|---|---|
| `corp_actions/RSS_Corporate_action_20261113.xml` | XML (RSS) | 39 | — |

## NSE holiday master

| Field | Value |
|---|---|
| Content | Trading holidays per segment (CM used). |
| Source | F04 (NSE trading holiday calendar) |
| Status | INGESTED |
| Tables | `trading_calendar` |
| Parser | `financials.calendar:parse_holiday_master` |
| Could serve | none identified |
| Files | 1 |

Columns: object: CBM (list of 24), CD (list of 24), CM (list of 20), CMOT (list of 20), COM (list of 21), EGR (list of 10), FO (list of 20), IRD (list of 24), MF (list of 20), NDM (list of 24), NTRP (list of 24), SLBS (list of 20); record: tradingDate, weekDay, description, morning_session, evening_session, Sr_no

| File | Format | Rows | Description |
|---|---|---|---|
| `calendar/nse_holiday-master_trading_20261113.json` | JSON | CBM: 24; CD: 24; CM: 20; CMOT: 20; COM: 21; EGR: 10; FO: 20; IRD: 24; MF: 20; NDM: 24; NTRP: 24; SLBS: 20 | — |

## NSE Nifty 500 constituents list

| Field | Value |
|---|---|
| Content | Current Nifty 500 members: company, industry, symbol, series, ISIN. |
| Source | F05 (Index constituents and rebalance notices) |
| Status | INGESTED |
| Tables | `raw_index_snapshot`, `index_constituents_history` |
| Parser | `financials.parsers.indices:parse_index_list` |
| Could serve | none identified |
| Files | 1 |

Columns: `Company Name`, `Industry`, `Symbol`, `Series`, `ISIN Code`

| File | Format | Rows | Description |
|---|---|---|---|
| `indices/ind_nifty500list_20261113.csv` | CSV | 501 | — |

## NSE Indices change notices (PDF + pdftotext)

| Field | Value |
|---|---|
| Content | Index inclusion / exclusion press releases; the text is pdftotext of the PDF. Parsed into reference/nifty500_changes.csv, which backfill-index replays. |
| Source | F05 (Index constituents and rebalance notices) |
| Status | INGESTED |
| Tables | `index_constituents_history` |
| Parser | `financials.index_changes:parse_change_notice` |
| Could serve | none identified |
| Files | 26 |

| File | Format | Rows | Description |
|---|---|---|---|
| `index_changes/pdf/ind_prs04042025_2.pdf` | PDF | 177,744 bytes | — |
| `index_changes/pdf/ind_prs04052026.pdf` | PDF | 385,708 bytes | — |
| `index_changes/pdf/ind_prs04102024.pdf` | PDF | 193,724 bytes | — |
| `index_changes/pdf/ind_prs10082026.pdf` | PDF | 983,307 bytes | — |
| `index_changes/pdf/ind_prs10102024.pdf` | PDF | 175,944 bytes | — |
| `index_changes/pdf/ind_prs11122025.pdf` | PDF | 702,491 bytes | — |
| `index_changes/pdf/ind_prs13072026_1.pdf` | PDF | 400,091 bytes | — |
| `index_changes/pdf/ind_prs13112025.pdf` | PDF | 267,658 bytes | — |
| `index_changes/pdf/ind_prs15092025_1.pdf` | PDF | 337,212 bytes | — |
| `index_changes/pdf/ind_prs17032025.pdf` | PDF | 199,021 bytes | — |
| `index_changes/pdf/ind_prs21022025.pdf` | PDF | 775,528 bytes | — |
| `index_changes/pdf/ind_prs22082025.pdf` | PDF | 773,272 bytes | — |
| `index_changes/pdf/ind_prs23022026.pdf` | PDF | 943,729 bytes | — |
| `index_changes/text/ind_prs04042025_2.txt` | TXT | 105 lines | DERIVED: `pdftotext -layout pdf/ind_prs04042025_2.pdf` (poppler 24.02) |
| `index_changes/text/ind_prs04052026.txt` | TXT | 190 lines | DERIVED: `pdftotext -layout pdf/ind_prs04052026.pdf` (poppler 24.02) |
| `index_changes/text/ind_prs04102024.txt` | TXT | 172 lines | DERIVED: `pdftotext -layout pdf/ind_prs04102024.pdf` (poppler 24.02) |
| `index_changes/text/ind_prs10082026.txt` | TXT | 1826 lines | DERIVED: `pdftotext -layout pdf/ind_prs10082026.pdf` (poppler 24.02) |
| `index_changes/text/ind_prs10102024.txt` | TXT | 93 lines | DERIVED: `pdftotext -layout pdf/ind_prs10102024.pdf` (poppler 24.02) |
| `index_changes/text/ind_prs11122025.txt` | TXT | 1245 lines | DERIVED: `pdftotext -layout pdf/ind_prs11122025.pdf` (poppler 24.02) |
| `index_changes/text/ind_prs13072026_1.txt` | TXT | 260 lines | DERIVED: `pdftotext -layout pdf/ind_prs13072026_1.pdf` (poppler 24.02) |
| `index_changes/text/ind_prs13112025.txt` | TXT | 82 lines | DERIVED: `pdftotext -layout pdf/ind_prs13112025.pdf` (poppler 24.02) |
| `index_changes/text/ind_prs15092025_1.txt` | TXT | 167 lines | DERIVED: `pdftotext -layout pdf/ind_prs15092025_1.pdf` (poppler 24.02) |
| `index_changes/text/ind_prs17032025.txt` | TXT | 189 lines | DERIVED: `pdftotext -layout pdf/ind_prs17032025.pdf` (poppler 24.02) |
| `index_changes/text/ind_prs21022025.txt` | TXT | 1665 lines | DERIVED: `pdftotext -layout pdf/ind_prs21022025.pdf` (poppler 24.02) |
| `index_changes/text/ind_prs22082025.txt` | TXT | 1375 lines | DERIVED: `pdftotext -layout pdf/ind_prs22082025.pdf` (poppler 24.02) |
| `index_changes/text/ind_prs23022026.txt` | TXT | 1744 lines | DERIVED: `pdftotext -layout pdf/ind_prs23022026.pdf` (poppler 24.02) |

## NSE daily index closes (ind_close_all)

| Field | Value |
|---|---|
| Content | OHLC, change, volume, turnover, P/E, P/B, dividend yield of every NSE price index. |
| Source | F27 (Daily index closes (all NSE price indices)) |
| Status | INGESTED |
| Tables | `index_ohlcv` |
| Parser | `financials.parsers.indices:parse_index_closes` |
| Could serve | none identified |
| Files | 1 |

Columns: `Index Name`, `Index Date`, `Open Index Value`, `High Index Value`, `Low Index Value`, `Closing Index Value`, `Points Change`, `Change(%)`, `Volume`, `Turnover (Rs. Cr.)`, `P/E`, `P/B`, `Div Yield`

| File | Format | Rows | Description |
|---|---|---|---|
| `indices/ind_close_all_13112026.csv` | CSV | 167 | IDX9: daily index closes (167 indices) |

## NSE equity master (EQUITY_L)

| Field | Value |
|---|---|
| Content | Every listed equity: symbol, name, series, listing date, paid-up value, market lot, ISIN, face value. |
| Source | F28 (NSE equity master (EQUITY_L.csv)) |
| Status | INGESTED |
| Tables | `raw_equity_master` |
| Parser | `financials.parsers.indices:parse_equity_master` |
| Could serve | none identified |
| Files | 1 |

Columns: `SYMBOL`, `NAME OF COMPANY`, `SERIES`, `DATE OF LISTING`, `PAID UP VALUE`, `MARKET LOT`, `ISIN NUMBER`, `FACE VALUE`

| File | Format | Rows | Description |
|---|---|---|---|
| `indices/nse_EQUITY_L_20261114.csv` | CSV | 2635 | IDX10: NSE equity master (2,635 listings) |

## NSE quote API industry classification

| Field | Value |
|---|---|
| Content | Quote API symbol data at fetch time: order book, trade info, price band, margins and the 4-level industry classification; only the classification fields are stored. |
| Source | F30 (NSE 4-level industry classification (quote API)) |
| Status | INGESTED |
| Tables | `raw_quote_classification`, `entity_classification_history` |
| Parser | `financials.parsers.classification:parse_quote_classification` |
| Could serve | G207 (MISSING): orderBook buyPrice1..5 / sellPrice1..5 and tradeInfo.impactCost (bid-ask), a snapshot at fetch time, not stored; G140 (DOCUMENTED_PLANNED): priceInfo.priceBand, a snapshot at fetch time, not stored; G141 (DOCUMENTED_PLANNED): secInfo.varMargin / extremelossMargin / securityvar, a snapshot at fetch time, not stored; G129 (MISSING): tradeInfo.ffmc (free-float market cap), a snapshot at fetch time, not stored |
| Files | 3 |

Columns: object: equityResponse (list of 1); record: orderBook{buyPrice1, buyQuantity1, buyPrice2, buyQuantity2, buyPrice3, buyQuantity3, buyPrice4, buyQuantity4, buyPrice5, buyQuantity5, sellPrice1, sellQuantity1, sellPrice2, sellQuantity2, sellPrice3, sellQuantity3, sellPrice4, sellQuantity4, sellPrice5, sellQuantity5, lastPrice, totalBuyQuantity, totalSellQuantity, perBuyQty, perSellQty}, metaData{identifier, companyName, isinCode, symbol, series, marketType, open, dayHigh, dayLow, previousClose, averagePrice, change, basePrice, closePrice, indicativeClose, ic_change, ic_pchange, spoChange, spoPchange, symbolStatus, adjPrice, iep, ieq, casStatus, pChange}, tradeInfo{totalTradedVolume, totalTradedValue, series, lastPrice, issuedSize, basePrice, ffmc, faceValue, impactCost, deliveryToTradedQuantity, applicableMargin, marketLot, quantitytraded, deliveryquantity, totalMarketCap, secwisedelposdate}, priceInfo{yearHightDt, yearLowDt, yearHigh, yearLow, cmDailyVolatility, cmAnnualVolatility, tickSize, inav, isINav, nav, navDate, priceBand, ppriceBand}, secInfo{secStatus, listingDate, pdSectorInd, pdSectorPe, pdSymbolPe, isSuspended, basicIndustry, index, deliveryQuantity, deliveryTotradedQuantity, securityvar, indexvar, extremelossMargin, varMargin, adhocMargin, applicableMargin, bondType, issueDesc, issueDate, maturityDate, couponRate, nxtIpDate, creditRating, macro, sector, industryInfo, indexList, boardStatus, tradingSegment, sessionNo, classShare, nameOfComplianceOfficer, casEligible, mainCatagory, subCatagory, sddcompliance}, lastUpdateTime

| File | Format | Rows | Description |
|---|---|---|---|
| `classification/GetQuoteApi_getSymbolData_HDFCBANK.json` | JSON | equityResponse: 1 | HDFCBANK, INE040A01034 |
| `classification/GetQuoteApi_getSymbolData_M_M.json` | JSON | equityResponse: 1 | M&M, INE101A01026 |
| `classification/GetQuoteApi_getSymbolData_TCS.json` | JSON | equityResponse: 1 | TCS, INE467B01029 |

## NSE Integrated Filing listing API

| Field | Value |
|---|---|
| Content | Integrated Filing rows of one symbol (Financials and Governance): period, scope, XBRL / iXBRL / PDF links, broadcast and creation times. |
| Source | F06 (Integrated Filing - Financials (Reg. 33 quarterly XBRL)) |
| Status | INGESTED |
| Tables | `raw_results_listing` |
| Parser | `financials.parsers.discovery:parse_integrated_filing_listing` |
| Could serve | none identified |
| Files | 9 |

Columns (4 of 9 files): object: data (list of 0), size (scalar), page (scalar), totalCount (scalar); record: data, size, page, totalCount

Columns (3 of 9 files): object: data (list of 20), size (scalar), page (scalar), totalCount (scalar); record: attFileSize, audited, broadcast_Date, cmName, consolidated, creation_Date, diff, ixbrl, ixbrlFileSize, pdf_attach, qe_Date, revised_Date, revision_Remark, seq_Id, smName, symbol, type, type_Sub, xbrl, xbrlFileSize

Columns (1 of 9 files): object: data (list of 1), size (scalar), page (scalar), totalCount (scalar); record: attFileSize, audited, broadcast_Date, cmName, consolidated, creation_Date, diff, ixbrl, ixbrlFileSize, pdf_attach, qe_Date, revised_Date, revision_Remark, seq_Id, smName, symbol, type, type_Sub, xbrl, xbrlFileSize

Columns (1 of 9 files): object: data (list of 2), size (scalar), page (scalar), totalCount (scalar); record: attFileSize, audited, broadcast_Date, cmName, consolidated, creation_Date, diff, ixbrl, ixbrlFileSize, pdf_attach, qe_Date, revised_Date, revision_Remark, seq_Id, smName, symbol, type, type_Sub, xbrl, xbrlFileSize

| File | Format | Rows | Description |
|---|---|---|---|
| `discovery/nse_integrated-filing-results_equities_ABBOTINDIA_20261117.json` | JSON | data: 0 | X166: Integrated Filing listing of a `Permitted` security (ABBOTINDIA) |
| `discovery/nse_integrated-filing-results_equities_ADANIGREEN_20261114.json` | JSON | data: 20 | A7: 10 of 20 rows have `broadcast_Date: null` (totalCount 36: two pages) |
| `discovery/nse_integrated-filing-results_equities_BAYERCROP_20261117.json` | JSON | data: 0 | X166: Integrated Filing listing of a `Permitted` security (BAYERCROP) |
| `discovery/nse_integrated-filing-results_equities_COALINDIA_20261115.json` | JSON | data: 20 | A7 / A13 (fetched 2026-11-15): every `xbrl`, `ixbrl` and `pdf_attach` link is on `nsearchives.nseindia.in` (was .com); the files are byte-identical to the .com host |
| `discovery/nse_integrated-filing-results_equities_GOODYEAR_20261117.json` | JSON | data: 1 | X166: Integrated Filing listing of a `Permitted` security (GOODYEAR) |
| `discovery/nse_integrated-filing-results_equities_HAWKINCOOK_20261117.json` | JSON | data: 0 | X166: Integrated Filing listing of a `Permitted` security (HAWKINCOOK) |
| `discovery/nse_integrated-filing-results_equities_MCX_20261117.json` | JSON | data: 0 | X166: Integrated Filing listing of a `Permitted` security (MCX) |
| `discovery/nse_integrated-filing-results_equities_TCS_20261113.json` | JSON | data: 20 | Results discovery (A7): newest 20 Integrated Filing rows (Financials + Governance) |
| `discovery/nse_integrated-filing-results_equities_TCS_page2_20261114.json` | JSON | data: 2 | A7 pagination (fetched 2026-11-14): `page=2` returns rows 21-22 of `totalCount` 22 (Mar 2025 standalone, Dec 2024 Governance); no overlap with page 1 |

## NSE annual report XBRL listing API

| Field | Value |
|---|---|
| Content | Reg. 34 annual XBRL rows of one symbol: file link, year, broadcast time. |
| Source | F07 (Reg. 34(1) annual report XBRL (MCA Ind AS taxonomy)) |
| Status | DISCOVERY_ONLY |
| Tables | — |
| Parser | `financials.parsers.reg34_annual:parse_annual_listing` |
| Could serve | none identified |
| Files | 6 |

Columns (1 of 6 files): object: data (list of 4); record: companyName, fromYr, toYr, report_type, submission_type, broadcast_dttm, disseminationDateTime, timeTaken, fileName

Columns (5 of 6 files): object: data (list of 0); record: data

| File | Format | Rows | Description |
|---|---|---|---|
| `annual/nse_annual-reports-xbrl_TCS_20261113.json` | JSON | data: 4 | B9: annual XBRL listing (symbol, type, broadcast time) |
| `discovery/nse_annual-reports-xbrl_equities_ABBOTINDIA_20261117.json` | JSON | data: 0 | X166: Reg. 34 annual XBRL listing of a `Permitted` security (ABBOTINDIA) |
| `discovery/nse_annual-reports-xbrl_equities_BAYERCROP_20261117.json` | JSON | data: 0 | X166: Reg. 34 annual XBRL listing of a `Permitted` security (BAYERCROP) |
| `discovery/nse_annual-reports-xbrl_equities_GOODYEAR_20261117.json` | JSON | data: 0 | X166: Reg. 34 annual XBRL listing of a `Permitted` security (GOODYEAR) |
| `discovery/nse_annual-reports-xbrl_equities_HAWKINCOOK_20261117.json` | JSON | data: 0 | X166: Reg. 34 annual XBRL listing of a `Permitted` security (HAWKINCOOK) |
| `discovery/nse_annual-reports-xbrl_equities_MCX_20261117.json` | JSON | data: 0 | X166: Reg. 34 annual XBRL listing of a `Permitted` security (MCX) |

## NSE shareholding master API

| Field | Value |
|---|---|
| Content | Reg. 31 filings of one symbol: as-of date, promoter / public %, XBRL link, broadcast time (the broadcast time of the SHP filing). |
| Source | F08 (Reg. 31 shareholding pattern XBRL) |
| Status | DISCOVERY_ONLY |
| Tables | — |
| Parser | `financials.parsers.shareholding:parse_shp_master` |
| Could serve | none identified |
| Files | 6 |

Columns (5 of 6 files): list

Columns (1 of 6 files): list; record: broadcastDate, cgTimeStamp, countString, date, desc, employeeTrusts, format, index, industry, isin, name, newColumn, pr_and_prgrp, promoterDematNotes, publicShareholdingNotes, public_val, recordId, remarksWeb, revisedData, revisedDate, revisedRemark, revisedStatus, revisionDate, revisionRemark, shareholdingPatternNotes, submissionDate, symbol, systemDate, timeDifference, typeOfSubmission, underlyingDrs, xbrl, xbrlFileSize

| File | Format | Rows | Description |
|---|---|---|---|
| `discovery/nse_corporate-share-holdings-master_equities_ABBOTINDIA_20261117.json` | JSON | 0 | X166: shareholding master of a `Permitted` security (ABBOTINDIA) |
| `discovery/nse_corporate-share-holdings-master_equities_BAYERCROP_20261117.json` | JSON | 0 | X166: shareholding master of a `Permitted` security (BAYERCROP) |
| `discovery/nse_corporate-share-holdings-master_equities_GOODYEAR_20261117.json` | JSON | 0 | X166: shareholding master of a `Permitted` security (GOODYEAR) |
| `discovery/nse_corporate-share-holdings-master_equities_HAWKINCOOK_20261117.json` | JSON | 0 | X166: shareholding master of a `Permitted` security (HAWKINCOOK) |
| `discovery/nse_corporate-share-holdings-master_equities_MCX_20261117.json` | JSON | 0 | X166: shareholding master of a `Permitted` security (MCX) |
| `shareholding/nse_corporate-share-holdings-master_ELIN_20261113.json` | JSON | 17 | — |

## NSE announcements RSS (Online_announcements)

| Field | Value |
|---|---|
| Content | Every announcement of the day: company, attachment link (Reg. 30 XBRL for structured events), subject, broadcast time. |
| Source | F21 (Reg. 30 structured event XBRL and announcements RSS) |
| Status | DISCOVERY_ONLY |
| Tables | — |
| Parser | `financials.parsers.reg30_events:parse_announcements_rss` |
| Could serve | none identified |
| Files | 1 |

Columns: root `rss`; item: title, link, description, pubDate

| File | Format | Rows | Description |
|---|---|---|---|
| `events/nse_Online_announcements_20261113.xml` | XML (RSS) | 2259 | E1: announcements RSS, 13-Nov-2026 21:52 IST (broadcast times) |

## NSE Integrated Filing results XBRL (Reg. 33)

| Field | Value |
|---|---|
| Content | Quarterly / annual results of every profile (Ind AS corporate, NBFC, bank, insurers, non-Ind AS corporate; legacy GI), with segments, Reg. 23(9) RPT and disclosures. |
| Source | F06 (Integrated Filing - Financials (Reg. 33 quarterly XBRL)); F10 (Reg. 23(9) related party transactions) |
| Status | INGESTED |
| Tables | `filing_meta`, `fact_observations`, `segment_observations`, `reg23_related_party_transactions`, `disclosure_facts`, `audit_opinions` |
| Parser | `financials.parsers.integrated:parse_integrated_results` |
| Could serve | none identified |
| Files | 206 |

XBRL instances: elements are not listed here; see `docs/tag_registry.yaml`.

| Directory | Files | Formats |
|---|---|---|
| `annual_checks/` | 1 | XML 1 |
| `annual_restated/` | 4 | XML 4 |
| `bse/` | 2 | XML 2 |
| `fixed_assets/` | 4 | XML 4 |
| `igaap_corp/` | 6 | XML 6 |
| `level_slip/` | 6 | XML 6 |
| `level_slip_annual/` | 2 | XML 2 |
| `nbfc_net_line/` | 2 | XML 2 |
| `operating_bridge/` | 18 | XML 18 |
| `owners_ytd/` | 2 | XML 2 |
| `ratio_rules/` | 2 | XML 2 |
| `rpt_half_year/` | 8 | XML 8 |
| `segments_qd/` | 2 | XML 2 |
| `shares_outlier/` | 2 | XML 2 |
| `xbrl/` | 112 | XML 112 |
| `xbrl_qa2/` | 4 | XML 4 |
| `xbrl_qc/` | 6 | XML 6 |
| `xbrl_qc2/` | 7 | XML 7 |
| `xbrl_qf5/` | 3 | XML 3 |
| `ytd_copy/` | 3 | XML 3 |
| `ytd_misfiled/` | 10 | XML 10 |

## NSE Reg. 34 annual report XBRL

| Field | Value |
|---|---|
| Content | Annual report XBRL (MCA Ind AS taxonomy): statements, AOC-1 group structure, related parties, audit report. |
| Source | F07 (Reg. 34(1) annual report XBRL (MCA Ind AS taxonomy)) |
| Status | INGESTED |
| Tables | `filing_meta`, `fact_observations`, `group_structure`, `related_party_transactions`, `disclosure_facts`, `audit_opinions` |
| Parser | `financials.parsers.reg34_annual:parse_reg34_annual` |
| Could serve | none identified |
| Files | 46 |

XBRL instances: elements are not listed here; see `docs/tag_registry.yaml`.

| Directory | Files | Formats |
|---|---|---|
| `annual_checks/` | 1 | XML 1 |
| `annual_restated/` | 4 | XML 4 |
| `fixed_assets/` | 2 | XML 2 |
| `level_slip_annual/` | 1 | XML 1 |
| `rpt_half_year/` | 3 | XML 3 |
| `xbrl/` | 32 | XML 32 |
| `xbrl_qf5/` | 2 | XML 2 |
| `ytd_misfiled/` | 1 | XML 1 |

## NSE Reg. 31 shareholding pattern XBRL

| Field | Value |
|---|---|
| Content | Shareholding pattern: categories, holders above 1%, pledges, share counts. |
| Source | F08 (Reg. 31 shareholding pattern XBRL) |
| Status | INGESTED |
| Tables | `shareholding_meta`, `shareholding_line_items`, `shareholding_major_holders`, `shareholding_observations`, `disclosure_facts` |
| Parser | `financials.parsers.shareholding:parse_shareholding` |
| Could serve | none identified |
| Files | 33 |

XBRL instances: elements are not listed here; see `docs/tag_registry.yaml`.

| Directory | Files | Formats |
|---|---|---|
| `annual_checks/` | 1 | XML 1 |
| `level_slip/` | 3 | XML 3 |
| `level_slip_annual/` | 1 | XML 1 |
| `shares_outlier/` | 2 | XML 2 |
| `xbrl/` | 18 | XML 18 |
| `xbrl_qc/` | 3 | XML 3 |
| `xbrl_qc2/` | 5 | XML 5 |

## NSE Reg. 30 structured event XBRL

| Field | Value |
|---|---|
| Content | Reg. 30 events (orders, capital changes, resignations, fraud / default, litigation). |
| Source | F21 (Reg. 30 structured event XBRL and announcements RSS) |
| Status | INGESTED |
| Tables | `corporate_events`, `disclosure_facts` |
| Parser | `financials.parsers.reg30_events:parse_reg30_event` |
| Could serve | none identified |
| Files | 9 |

XBRL instances: elements are not listed here; see `docs/tag_registry.yaml`.

| Directory | Files | Formats |
|---|---|---|
| `events/` | 9 | XML 9 |

## BSE equity UDiFF bhavcopy

| Field | Value |
|---|---|
| Content | BSE end-of-day prices in the UDiFF layout (FinInstrmId = BSE scrip code, ISIN per row). parse_udiff_cm(data, exchange='BSE') reads it; nothing fetches or promotes it. |
| Source | F34 (BSE equity UDiFF bhavcopy) |
| Status | NOT_INGESTED |
| Tables | — |
| Parser | — |
| Could serve | none identified |
| Files | 1 |

Columns: `TradDt`, `BizDt`, `Sgmt`, `Src`, `FinInstrmTp`, `FinInstrmId`, `ISIN`, `TckrSymb`, `SctySrs`, `XpryDt`, `FininstrmActlXpryDt`, `StrkPric`, `OptnTp`, `FinInstrmNm`, `OpnPric`, `HghPric`, `LwPric`, `ClsPric`, `LastPric`, `PrvsClsgPric`, `UndrlygPric`, `SttlmPric`, `OpnIntrst`, `ChngInOpnIntrst`, `TtlTradgVol`, `TtlTrfVal`, `TtlNbOfTxsExctd`, `SsnId`, `NewBrdLotQty`, `Rmks`, `Rsvd1`, `Rsvd2`, `Rsvd3`, `Rsvd4`

| File | Format | Rows | Description |
|---|---|---|---|
| `bse/BhavCopy_BSE_CM_0_0_0_20261113_F_0000.CSV` | CSV | 5141 | X165: BSE equity UDiFF bhavcopy, FinInstrmId = BSE scrip code, ISIN per row (5,141 rows) |

## BSE list of securities (ListofScripData)

| Field | Value |
|---|---|
| Content | BSE scrip code, ISIN, name, group, face value, status, industry per security (rule BSE1). |
| Source | F35 (BSE list of securities (ListofScripData, per BSE group)) |
| Status | INGESTED |
| Tables | `raw_bse_securities` |
| Parser | `financials.parsers.bse_securities:parse_list_securities` |
| Could serve | none identified |
| Files | 3 |

Columns: list; record: SCRIP_CD, Scrip_Name, Status, GROUP, FACE_VALUE, ISIN_NUMBER, INDUSTRY, scrip_id, Segment, NSURL, Issuer_Name, Mktcap

| File | Format | Rows | Description |
|---|---|---|---|
| `bse/bse_ListofScripData_A_500488_20261117.json` | JSON | 1 | A18 / X169: list of securities narrowed to scrip 500488 (one row); probe run 3 on a GitHub runner (run 44030916910, 2026-11-17, plain requests with the ported headers); ledger blob saved unmodified |
| `bse/bse_ListofScripData_GroupA_20261117.json` | JSON | 705 | X169 / A18: BSE list of securities, group A (705 rows), probe run 2 on a GitHub runner (run 44029015234), plain requests with the ported headers; ledger blob saved unmodified |
| `bse/bse_ListofScripData_GroupY_20261117.json` | JSON | 2 | X200 BSE2: BSE group Y list of securities, 2 rows, ISIN "" (A D S Diagnostics 523031) and "NA" (Pushpsons 531562) (fetched 2026-11-17T16:26:51Z on a runner) |

## BSE announcements API (AnnSubCategoryGetData)

| Field | Value |
|---|---|
| Content | Announcements: NEWSID, scrip, subject, category / subcategory, attachment name, broadcast times. |
| Source | F36 (BSE announcements (+ AttachLive attachments), shareholding filings (+ inline XBRL) and results XBRL) |
| Status | VAULTED_RAW |
| Tables | — |
| Parser | — |
| Could serve | G193 (DOCUMENTED_PLANNED): categories 'Board Meeting' and 'AGM/EGM' (subject text, no structured date) |
| Files | 3 |

Columns (1 of 3 files): list; record: NEWSID, SCRIP_CD, XML_NAME, NEWSSUB, DT_TM, NEWS_DT, CRITICALNEWS, ANNOUNCEMENT_TYPE, QUARTER_ID, FILESTATUS, ATTACHMENTNAME, MORE, HEADLINE, CATEGORYNAME, OLD, RN, PDFFLAG, NSURL, SLONGNAME, AGENDA_ID, TotalPageCnt, News_submission_dt, DissemDT, TimeDiff, Fld_Attachsize, SUBCATNAME, BSENEWSID, INVESTOR_PRESENTATION, RECORDID, DataInsDate, AUDIO_VIDEO_FILE

Columns (1 of 3 files): object: Table (list of 4), Table1 (list of 1); record: NEWSID, SCRIP_CD, XML_NAME, NEWSSUB, DT_TM, NEWS_DT, CRITICALNEWS, ANNOUNCEMENT_TYPE, QUARTER_ID, FILESTATUS, ATTACHMENTNAME, MORE, HEADLINE, CATEGORYNAME, OLD, RN, PDFFLAG, NSURL, SLONGNAME, AGENDA_ID, News_submission_dt, DissemDT, TimeDiff, Fld_Attachsize, SUBCATNAME, BSENewsid, Investor_Presentation, AUDIO_VIDEO_FILE

Columns (1 of 3 files): object: Table (list of 50), Table1 (list of 1); record: NEWSID, SCRIP_CD, XML_NAME, NEWSSUB, DT_TM, NEWS_DT, CRITICALNEWS, ANNOUNCEMENT_TYPE, QUARTER_ID, FILESTATUS, ATTACHMENTNAME, MORE, HEADLINE, CATEGORYNAME, OLD, RN, PDFFLAG, NSURL, SLONGNAME, AGENDA_ID, News_submission_dt, DissemDT, TimeDiff, Fld_Attachsize, SUBCATNAME, BSENewsid, Investor_Presentation, AUDIO_VIDEO_FILE

| File | Format | Rows | Description |
|---|---|---|---|
| `bse/announcements.json` | JSON | 68 | A17: announcements rows (68, one per category / subcategory of 12 Oct 2026; trimmed in the source repo) |
| `bse/bse_AnnSubCategoryGetData_500488_20261015_20261117.json` | JSON | Table: 4; Table1: 1 | A18 / X168: ABBOTINDIA announcements 15 Oct-17 Nov 2026, every category (4 rows, ROWCNT 4); probe run 3 on a GitHub runner (run 44030916910, 2026-11-17, plain requests with the ported headers); ledger blob saved unmodified |
| `bse/bse_AnnSubCategoryGetData_all_20261113_p1.json` | JSON | Table: 50; Table1: 1 | A18 / X168: every company's announcements of 13 Nov 2026, page 1 (50 rows, ROWCNT 2,704), the source client's exact call; probe run 3 on a GitHub runner (run 44030916910, 2026-11-17, plain requests with the ported headers); ledger blob saved unmodified |

## BSE announcement attachments (AttachLive)

| Field | Value |
|---|---|
| Content | The PDF attached to an announcement. |
| Source | F36 (BSE announcements (+ AttachLive attachments), shareholding filings (+ inline XBRL) and results XBRL) |
| Status | VAULTED_RAW |
| Tables | — |
| Parser | — |
| Could serve | G62 (MISSING): the announcement PDFs a keyword watcher would read |
| Files | 1 |

| File | Format | Rows | Description |
|---|---|---|---|
| `bse/AttachLive_e334e776-71a5-4afd-adf3-ad10a11505cf.pdf` | PDF | 1,884,669 bytes | A18 / X168: the attachment of ABBOTINDIA's Q2 FY27 'Result' announcement (PDF, size = Fld_Attachsize); probe run 3 on a GitHub runner (run 44030916910, 2026-11-17, plain requests with the ported headers); ledger blob saved unmodified |

## BSE shareholding filings listing (Corp_Shareholding_ng)

| Field | Value |
|---|---|
| Content | Reg. 31 filings per scrip: quarter, inline-XBRL link, broadcast time (used as the broadcast time of the BSE SHP filing). |
| Source | F36 (BSE announcements (+ AttachLive attachments), shareholding filings (+ inline XBRL) and results XBRL) |
| Status | DISCOVERY_ONLY |
| Tables | — |
| Parser | `financials.fetch.bse:_shp_broadcast_times` |
| Could serve | none identified |
| Files | 2 |

Columns (1 of 2 files): object: Table (list of 4); record: FLD_ScripCode, Company_NAme, industry_name, sQtrName, nqtrid, broadcastTime, D, EndDate, IsXBRL, XBRLAttachment

Columns (1 of 2 files): object: Table (list of 15); record: FLD_ScripCode, Company_NAme, industry_name, sQtrName, nqtrid, broadcastTime, D, EndDate, IsXBRL, XBRLAttachment

| File | Format | Rows | Description |
|---|---|---|---|
| `bse/bse_Corp_Shareholding_ng_500488_flag6_20261117.json` | JSON | Table: 4 | A18: shareholding filings of 500488 for the last year (flag 6, 4 rows, inline-XBRL links, broadcast `D`); probe run 3 on a GitHub runner (run 44030916910, 2026-11-17, plain requests with the ported headers); ledger blob saved unmodified |
| `bse/shareholding_listing_20261012.json` | JSON | Table: 15 | A17: shareholding filings list (15 rows, trimmed in the source repo) |

## BSE Reg. 31 shareholding inline XBRL

| Field | Value |
|---|---|
| Content | BSE's inline XBRL of the SEBI in-bse-shp taxonomy, same tables as NSE Reg. 31. |
| Source | F36 (BSE announcements (+ AttachLive attachments), shareholding filings (+ inline XBRL) and results XBRL) |
| Status | INGESTED |
| Tables | `shareholding_meta`, `shareholding_line_items`, `shareholding_major_holders`, `shareholding_observations`, `disclosure_facts` |
| Parser | `financials.parsers.shareholding:parse_shareholding` |
| Could serve | none identified |
| Files | 4 |

XBRL instances: elements are not listed here; see `docs/tag_registry.yaml`.

| Directory | Files | Formats |
|---|---|---|
| `bse/` | 4 | HTML 1, HTML (gzip) 3 |

## BSE results listing (Corp_FinanceResult_ng_new)

| Field | Value |
|---|---|
| Content | Results rows per scrip: quarter code, standalone / consolidated file names (XMLName, Consol_XMLName), creation time (the broadcast time of the BSE results filing). |
| Source | F36 (BSE announcements (+ AttachLive attachments), shareholding filings (+ inline XBRL) and results XBRL) |
| Status | DISCOVERY_ONLY |
| Tables | — |
| Parser | `financials.fetch.bse:_results_broadcast_times` |
| Could serve | none identified |
| Files | 3 |

Columns (2 of 3 files): object: Table (list of 7); record: Scrip_cd, scrip_name, quarter_code, audited, Qtr, Fld_CreateDate, DT_TM, Industry_name, company_name, XMLName, Fld_NatureOfReport, URL, Consol_XMLName, Resultpageurl

Columns (1 of 3 files): object: Table (list of 4); record: Scrip_cd, scrip_name, quarter_code, audited, Qtr, Fld_CreateDate, DT_TM, Industry_name, company_name, XMLName, Fld_NatureOfReport, URL, Consol_XMLName, Resultpageurl

| File | Format | Rows | Description |
|---|---|---|---|
| `bse/bse_Corp_FinanceResult_ng_new_500488_flagdur6_20261118.json` | JSON | Table: 7 | X247 / X265: ABBOTINDIA's results over the last year, 7 rows (SQ / SH 2026-27 .. DQ / DN 2025-26), 4 distinct standalone `XMLName` files, `Consol_XMLName` null, `Fld_CreateDate` IST |
| `bse/bse_Corp_FinanceResult_ng_new_530245_flagdur6_20261118.json` | JSON | Table: 7 | X313: the scrip's results listing (FlagDur 6) naming both files (`XMLName` / `Consol_XMLName`, `Fld_CreateDate` 2026-08-14T17:19:26.623 for JQ2026-2027) |
| `bse/bse_Corp_FinanceResult_ng_new_all_flagdur1_20261118.json` | JSON | Table: 4 | X247 / X265: every company's results of 18-Nov-2026 (SCRIP_CD blank, FlagDur 1): 4 rows of 544111 (PARKHOTELS) and 544477 (HILINFRA), with `Consol_XMLName` |

## BSE results XBRL (inline .html, NBFC plain .xml)

| Field | Value |
|---|---|
| Content | BSE copies of Integrated Filing results (SEBI in-capmkt taxonomy), read by the NSE path; several fixtures pin the repairs of malformed XHTML (see MANIFEST). |
| Source | F36 (BSE announcements (+ AttachLive attachments), shareholding filings (+ inline XBRL) and results XBRL) |
| Status | INGESTED |
| Tables | `filing_meta`, `fact_observations`, `segment_observations`, `reg23_related_party_transactions`, `disclosure_facts`, `audit_opinions` |
| Parser | `financials.parsers.integrated:parse_integrated_results` |
| Could serve | none identified |
| Files | 19 |

XBRL instances: elements are not listed here; see `docs/tag_registry.yaml`.

| Directory | Files | Formats |
|---|---|---|
| `bse/` | 13 | HTML 11, XML 2 |
| `nbfc_net_line/` | 2 | XML 2 |
| `ytd_copy/` | 4 | HTML 4 |

## BSE announcement XBRL (CorpXbrlGen)

| Field | Value |
|---|---|
| Content | BSE's per-announcement XBRL (in-bse-co namespace), and its 21-byte error answer; seen by the reach probe only. |
| Source | — |
| Status | NOT_INGESTED |
| Tables | — |
| Parser | — |
| Could serve | none identified |
| Files | 2 |

XBRL instances: elements are not listed here; see `docs/tag_registry.yaml`.

| Directory | Files | Formats |
|---|---|---|
| `bse/` | 2 | HTML 1, XML 1 |

## BSE legacy results page (Comp_Resultsnew)

| Field | Value |
|---|---|
| Content | ASP.NET results search page (form fields only); seen by the reach probe only. |
| Source | — |
| Status | NOT_INGESTED |
| Tables | — |
| Parser | — |
| Could serve | none identified |
| Files | 1 |

| File | Format | Rows | Description |
|---|---|---|---|
| `bse/beta_Comp_Resultsnew_expandable0_20261118.html` | HTML | 51,674 bytes | X248: BSE's legacy ASP.NET results page on the beta host as first loaded (GET, 51,674 bytes, CRLF): form fields with two `name` attributes per control (`ctl00$ContentPlaceHolder1$broadcastdd` / `broadcast6`, `...$btnSubmit` / `submt6`), broadcast options 1-7, period options ALL / 3 / 2 / 1, results grid `ContentPlaceHolder1_gvData` whose Std / Con XBRL links are `__doPostBack` targets `...$gvData$ctl02$lnkXML` / `$lnkConXML` |

## BSE results dropdown lists (Corp_GetFINANCE_DRDOWN_ng)

| Field | Value |
|---|---|
| Content | Code lists of the results page (broadcast periods, result periods); seen by the reach probe only. |
| Source | — |
| Status | NOT_INGESTED |
| Tables | — |
| Parser | — |
| Could serve | none identified |
| Files | 2 |

Columns (1 of 2 files): object: Table (list of 7); record: FlagDur, FlagDISPLAY, Regional_GUJ, Regional_HINDI, Regional_MAR

Columns (1 of 2 files): object: Table (list of 3); record: HFQ, HFQDISPLAY, Regional_GUJ, Regional_HINDI, Regional_MAR

| File | Format | Rows | Description |
|---|---|---|---|
| `bse/bse_Corp_GetFINANCE_DRDOWN_ng_flag1_20261118.json` | JSON | Table: 7 | X247: the comp_resultsnew broadcast-period list: FlagDur 1 Today, 2 Last 1 Week, 3 Last 15 Days, 4 Last 1 month, 5 Last 3 month, 6 Last 1 year, 7 Beyond last 1 year |
| `bse/bse_Corp_GetFINANCE_DRDOWN_ng_flag3_20261118.json` | JSON | Table: 3 | X247: result periods HFQ 3 Quarterly, 2 Yearly, 1 Half Yearly |

## SEBI circulars (PDF + pdftotext)

| Field | Value |
|---|---|
| Content | Regulatory text cited as evidence (Integrated Filing format). |
| Source | — |
| Status | REFERENCE |
| Tables | — |
| Parser | — |
| Could serve | none identified |
| Files | 2 |

| File | Format | Rows | Description |
|---|---|---|---|
| `circulars/sebi_cir_2024_185.pdf` | PDF | 1,061,829 bytes | X160: SEBI circular SEBI/HO/CFD/CFD-PoD-2/CIR/P/2024/185 (31 Dec 2024), Annexure 1 Integrated Filing (Financial) format D (Reg. 23(9) related-party transactions), notes 1 and 4; NSE copy saved as `NEW SEBI_0.pdf`, renamed only (fetched 2026-11-17) |
| `circulars/sebi_cir_2024_185.txt` | TXT | 1705 lines | DERIVED: `pdftotext -layout circulars/sebi_cir_2024_185.pdf` (poppler 24.02) |

## Fixture manifest

| Field | Value |
|---|---|
| Content | sha256 and source URL of every fixture; per-file descriptions in this catalogue come from it. |
| Source | — |
| Status | REFERENCE |
| Tables | — |
| Parser | — |
| Could serve | none identified |
| Files | 1 |

| File | Format | Rows | Description |
|---|---|---|---|
| `MANIFEST.md` | Markdown | 876 lines | — |
