# References & Evidence Register

Every external claim the design relies on lives here with a status. **Code may only depend
on VERIFIED claims.** An UNVERIFIED claim may shape a plan, but the code path that relies
on it must quarantine on surprise and must get a fixture + test before it is trusted.

Status meanings:
- **VERIFIED**: checked against a real file in `tests/fixtures/` and pinned by a test.
  Scope is exactly what was tested (e.g. "one Q2 standalone filing"). Not a universal law.
- **OBSERVED**: seen in live data on a stated date, but not pinned by a committed fixture.
- **UNVERIFIED**: from documents, memory or another tool's assertion. Do not code against it.
- **CHOICE**: a methodology decision, not a fact. Changing it is a design change.

Last reviewed: 2026-11-13.

## 1. XBRL quarterly results (fixtures: `tests/fixtures/xbrl/`, tests: `tests/test_xbrl_fixture_facts.py`)

| # | Claim | Status | Evidence / scope |
|---|---|---|---|
| X1 | Accounting profile is routable from the `in-capmkt-ent` namespace: `IntegratedFinance_IndAS`, `IntegratedFinance_NBFC`, `IntegratedFinance_Banking` (SEBI `2026-01-31` taxonomy); legacy general insurer uses `bseindia.com/xbrl/GeneralInsurance/2020-03-31`. | VERIFIED | 4 fixtures |
| X2 | Quarterly XBRL has **no prior-period comparative durations**. Contexts: `OneD` (quarter), `FourD` (FY-to-date), `OneI` (period-end instant). Only prior-period fact: `PY_I` → `CashAndCashEquivalentsCashFlowStatement` (opening cash for the cash-flow statement). | VERIFIED | corp, NBFC, bank fixtures |
| X3 | Restated prior-year quarters (e.g. after a demerger) are **not available** in quarterly XBRL. | VERIFIED (consequence of X2) | Design consequence: see architecture §7.6 |
| X4 | Numeric values are **absolute rupees** whatever `LevelOfRounding` says (Millions, Lakhs). | VERIFIED | corp (Millions), bank (Lakhs) |
| X5 | The `decimals` attribute is inconsistent inside one filing (corp mixes `-4`, `-5`, `-6` under `LevelOfRounding = Millions`). Do not use it for tolerances. | VERIFIED | corp |
| X6 | Scope is a per-filing text fact `NatureOfReportStandaloneConsolidated`, not a context dimension. Standalone and consolidated are separate filings. | VERIFIED (standalone only) | 4 fixtures; no consolidated fixture yet |
| X7 | Issuer identifiers are inside the filing: `Symbol`/`NSESymbol`, `ISIN`, `ScripCode` (BSE). | VERIFIED | corp, NBFC, bank, GI |
| X8 | Filing contains `DateOfStartOfFinancialYear`, `ReportingQuarter`, board meeting start/end date and time, `WhetherResultsAreAuditedOrUnaudited`. | VERIFIED | corp, GI |
| X9 | Corp P&L identities tie exactly: `Income − Expenses = ProfitBeforeExceptionalItemsAndTax`; `PBEIT + ExceptionalItemsBeforeTax = ProfitBeforeTax`; `PBT − TaxExpense = ProfitLossForPeriodFromContinuingOperations`. | VERIFIED | corp OneD + FourD |
| X10 | `ExceptionalItemsBeforeTax` sign: positive increases PBT. | VERIFIED (one filing, positive value only) | corp. A loss-valued fixture is still needed. |
| X11 | `ChangesInInventoriesOfFinishedGoodsWorkInProgressAndStockInTrade` is an expense-signed component of `Expenses` (negative = inventory build-up). | VERIFIED | corp |
| X12 | H1 corp/NBFC filing has a full balance sheet in `OneI`; `Assets = EquityAndLiabilities` exactly. | VERIFIED | corp, NBFC (Q2) |
| X13 | Cash flow appears only in `FourD` (YTD), not `OneD`. | VERIFIED | corp Q2 |
| X14 | Interest classification is tagged: `InterestPaidClassifiedAsOperatingActivities` / `…AsFinancingActivities`, `InterestReceivedClassifiedAsOperatingActivities` / `…AsInvestingActivities`. | VERIFIED | corp (interest paid in financing) |
| X15 | Cash-flow outflow tags (e.g. `PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities`, `InterestPaidClassifiedAsFinancingActivities`) hold **positive magnitudes**; net totals (`CashFlowsFromUsedInOperatingActivities`) are signed. | VERIFIED (one filing) | corp |
| X16 | Quarterly corp balance sheet has **no separate lease-liability tag**; leases sit inside other financial liabilities. Only `BorrowingsNoncurrent` / `BorrowingsCurrent` are tagged. | VERIFIED (absence, one filing) | corp |
| X17 | `NoncurrentInvestments` is a single total, with no split between treasury and strategic holdings. | VERIFIED (one filing) | corp |
| X18 | Share count derivable: `PaidUpValueOfEquityShareCapital / FaceValueOfEquityShareCapital` (corp: 248,550,000 / 5 = 49,710,000). Wrong for partly-paid shares. | VERIFIED (tags present) | corp |
| X19 | Related-party transactions (Reg. 23(9)) are inside the Integrated Filing XBRL under `RelatedPartyTransactionAxis` contexts. | VERIFIED | corp, NBFC |
| X20 | NBFC taxonomy uses `InterestEarned` (not `InterestIncome`), plus `FeesAndCommissionIncome`, `NetGainOnFairValueChanges`, `ImpairmentOnFinancialInstruments`, `FinanceCosts`. | VERIFIED (tags present) | NBFC fixture is an **investment company**, not a lender |
| X21 | Bank tags: `InterestEarned`, `InterestExpended`, `OperatingExpenses`, `OperatingProfitBeforeProvisionAndContingencies`, `ProvisionsOtherThanTaxAndContingencies`, `GrossNonPerformingAssets`, `NonPerformingAssets`, `PercentageOfGrossNpa`, `PercentageOfNpa`, `ReturnOnAssets`, `CET1Ratio`, `AdditionalTier1Ratio`. Ratios are **fractions** (0.0175 = 1.75%). | VERIFIED | CSB Bank Q1 |
| X22 | Bank Q1 filing has **no balance sheet** (no advances/deposits) and no `FourD`. | VERIFIED | CSB Bank Q1 |
| X23 | CASA is **not tagged** in bank quarterly XBRL. | VERIFIED (one Q1 filing) | → `supplemental_kpis` |
| X24 | Total CRAR tag | UNVERIFIED | Only CET1 and AT1 seen |
| X25 | Whether bank `ReturnOnAssets` is annualised | UNVERIFIED | |
| X26 | **Filer defect**: Star Health Q3 FY25 `FourD` context dates say 2024-10-01..2024-12-31 (same as `OneD`), but `DateOfStartOfReportingPeriod@FourI = 2024-04-01` and values are 9-month YTD. | VERIFIED | GI fixture. Context dates cannot be trusted blindly. |
| X27 | Insurers have moved to the Integrated Filing taxonomy | UNVERIFIED | Fixture is legacy (Jan 2025) |
| X28 | Life-insurer taxonomy and tags | UNVERIFIED | No fixture |
| X29 | Consolidated-filing tags (NCI, share of associates placement) | UNVERIFIED | No fixture |
| X30 | Q1/Q3 corp filings omit the balance sheet and cash flow (SEBI Reg. 33 half-yearly requirement) | UNVERIFIED for corp | Bank Q1 consistent |
| X31 | `ExciseDuty` tag name in corp taxonomy | UNVERIFIED | Not in ELIN fixture |

## 2. Prices, delivery, identifiers (fixtures: `tests/fixtures/bhavcopy/`, tests: `tests/test_bhavcopy_fixture_facts.py`)

| # | Claim | Status | Evidence / scope |
|---|---|---|---|
| P1 | UDiFF CM bhavcopy columns include `TradDt, FinInstrmId, ISIN, TckrSymb, SctySrs, OpnPric, HghPric, LwPric, ClsPric, LastPric, PrvsClsgPric, TtlTradgVol, TtlTrfVal, TtlNbOfTxsExctd`; **no delivery column**. | VERIFIED | 5 fixtures |
| P2 | `PrvsClsgPric` is **not** adjusted for corporate actions on ex-dates (split, bonus, demerger). | VERIFIED | ADANIPOWER, PIDILITIND, TATAMOTORS |
| P3 | 23 large ex-date gaps in 28 trading days (2025-09-15..2025-10-17), all with unadjusted `PrvsClsgPric`. | OBSERVED | scratch analysis 2026-11-13 |
| P4 | Days with \|Open_t/Close_{t−1} − 1\| > 10% among EQ/BE/BZ: 0–7 per day out of ~2,460 (mostly real corporate actions). | OBSERVED | same window |
| P5 | Split changes ISIN (ADANIPOWER `INE814H01011 → INE814H01029`); symbol and `FinInstrmId` (17388) unchanged. | VERIFIED | fixtures |
| P6 | Bonus keeps ISIN (PIDILITIND). | VERIFIED | fixtures |
| P7 | Demerger parent keeps ISIN and symbol on ex-date (TATAMOTORS `INE155A01022`, open 400.00 vs prior close 660.75). | VERIFIED | fixtures |
| P8 | `FinInstrmId` stable across ISIN change: TATAINVEST (1621) and PIDILITIND (2664) too. | OBSERVED | scratch analysis |
| P14 | A split and a series change can both happen between two promoted days: SIGMA split on 2025-10-06 (ISIN `INE0A0S01010` → `INE0A0S01028`) and traded as BE (new `FinInstrmId` 16664) by 2025-10-13; by 2026-11-12 it was back in EQ under `FinInstrmId` 16658 with the new ISIN. The registry opens a second security and later quarantines `ISIN_COLLISION`. | OBSERVED | full-market test build |
| P15 | Symbol changes keep ISIN and `FinInstrmId`: TATAMOTORS (2025) → TMPV (2026-11-12 bhavcopy), ISIN `INE155A01022`. | VERIFIED | `tests/test_features.py` |
| P13 | `FinInstrmId` identifies a **(security, series)** pair: a series change (EQ↔BE↔BZ) keeps the ISIN but assigns a different `FinInstrmId` (AAATECH EQ 12533 → BE 12542). 143 ISINs did this in 28 days; 97 within the 5 committed fixture days. No `FinInstrmId` appeared in more than one series. | VERIFIED | `test_series_change_changes_fin_instrm_id_but_keeps_isin`; scratch analysis for counts |
| P9 | `FinInstrmId` is never reused for a different security | UNVERIFIED | |
| P10 | `sec_bhavdata_full_DDMMYYYY.csv` has `PREV_CLOSE`, OHLC, `TTL_TRD_QNTY`, `DELIV_QTY`, `DELIV_PER`; **no ISIN**; `PREV_CLOSE` unadjusted on ex-date. Leading spaces after commas. | VERIFIED | 2025-10-14 fixture |
| P11 | Time of day the bhavcopy and delivery files become available | UNVERIFIED | |
| P12 | Source for corporate-action records: `www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY` (JSON list: `symbol, series, isin, exDate, recDate, faceVal, subject, caBroadcastDate, …`). | VERIFIED | `corp_actions/` fixture, `tests/test_nse_corp_actions.py` |

## 2b. Corporate actions (fixture: 2025-09-15..2025-10-17 API response, 265 records)

| # | Claim | Status | Evidence |
|---|---|---|---|
| CA1 | API `symbol` is the **current** symbol: Tata Motors' 2025-10-14 demerger is listed under `TMPV`. | VERIFIED | test |
| CA2 | API `isin` is usually the ISIN in force before the action (ADANIPOWER `INE814H01011` on its split). | VERIFIED | test |
| CA3 | `faceVal` is the **current** face value (ADANIPOWER shows 2 on its 10→2 split record). | VERIFIED | test |
| CA4 | Rights are quoted `Rights A:B @ Premium Rs X/-`; issue price = face value + premium. CAPTRUST 1:1 @ 4 (FV 10) opened at 0.689 × prior close vs theoretical 0.656. | VERIFIED (formula against one real gap) | test |
| CA5 | Bonus `A:B` = A new per B held (GODFRYPHLP 2:1 opened at 0.342 × prior close; theory 1/3). Split + bonus on one day are two records (NAZARA, combined 0.25, observed 0.261). | VERIFIED | tests |
| CA6 | The `Corporate_action.xml` RSS has company name, ex-date, purpose, face value, record date, but **no symbol or ISIN**, so it can only trigger an API fetch. | VERIFIED | test |
| CA7 | API ISIN is **stale** for ~25% of records: 60 of 237 resolvable records in 28 trading days carried an older ISIN than bhavcopy (e.g. DIXON `INE935N01012` vs `INE935N01020`). Old and new ISINs share the 4-char issuer code (chars 4-7), except PREMIERPOL (`INE247401016` vs `INE309M01020`). | VERIFIED (DIXON, PREMIERPOL in test); counts OBSERVED | Resolution: ISIN, then symbol with same issuer code, else quarantine |
| CA8 | `caBroadcastDate` is `null` on every record in the fixture, so action visibility time is unknown. | VERIFIED | fixture |
| CA9 | All 256 EQ records in the window match one of five purpose patterns (dividend, bonus, face-value split, rights with premium, demerger); 9 GS records are interest payments. | VERIFIED | test |

## 2c. Calendar and index lists

| # | Claim | Status | Evidence |
|---|---|---|---|
| CAL1 | `holiday-master?type=trading` returns a dict keyed by segment (`CM`, `FO`, …); `CM` lists 20 holidays for 2026 only (`tradingDate` `DD-Mon-YYYY`, weekend holidays included, Diwali Laxmi Pujan marked `*`). | VERIFIED | `tests/test_calendar_and_index.py` |
| CAL2 | Special sessions (Muhurat) can produce a bhavcopy on a listed holiday. | UNVERIFIED | Rule anyway: bhavcopy overrides holiday rows |
| IDX1 | `ind_nifty500list.csv` (2026-11-13): 501 rows, columns `Company Name, Industry, Symbol, Series, ISIN Code`. | VERIFIED | test |
| IDX2 | Index lists can contain non-ISIN placeholders (`DUMMYHEG`, `DUM545A01024`), presumably around demergers. | VERIFIED (present) | test; quarantined as `PLACEHOLDER_ISIN` |
| IDX4 | NSE Indices "Replacement(s) in indices" notices (`niftyindices.com/Press_Release/ind_prsDDMMYYYY[_n].pdf`, listed on `/press-release`) give, per index, a `1) Nifty 500` / `b) Nifty 500` section with "being excluded" / "being included" tables (Sr. No., Company Name, Symbol). The effective date is the first "w.e.f. / effective from Month DD, YYYY", which can wrap across lines. Replacement tables are balanced (18/18, 27/27, 31/31). | VERIFIED | 12 PDFs + derived text; `tests/test_index_backfill.py` |
| IDX5 | Demerger dummies: e.g. `DUMMYTATAM` included 2025-10-14, the listed TMCV excluded 2025-11-17. Such notices are prose with a list of affected indices, not tables, so they are not machine-extracted. | VERIFIED (one notice) | `ind_prs13112025` |
| IDX6 | Walking back from the 2026-11-13 list through the 12 regular notices to 2024-10-01 is consistent (no contradiction, 500 on every step) once renames are resolved via `FinInstrmId`; without that, AKZOINDIA (added 2025-09-30, now JSWDULUX, ISIN `INE133A01011` → `INE133A01029`) breaks the walk. | VERIFIED | `test_real_walk_keeps_500_on_every_step` |
| IDX7 | A consistent walk does not prove completeness: a missing *balanced* event is only caught if a later event contradicts it. Ad-hoc notices without a table section, and dummies, are not in the manifest. | CHOICE / limitation | |
| IDX3 | Against the 2025-10-14 bhavcopy, 31 of the 2026 constituents do not resolve by ISIN: later IPOs plus splits since (e.g. KOTAKBANK `INE237A01028` → `INE237A01036`). | OBSERVED | Snapshot must be promoted after the same day's bhavcopy |

## 2d. Shareholding (Reg. 31) — fixture: ELIN 2026-09-30

| # | Claim | Status | Evidence |
|---|---|---|---|
| SHP1 | Taxonomy namespace `http://www.bseindia.com/xbrl/shp/2025-10-31/in-bse-shp`; no `in-capmkt-ent`. | VERIFIED | `tests/test_shareholding.py` |
| SHP2 | Category totals are instant contexts with one `CategoryOfShareholdersAxis` member (`ShareholdingPatternMember` total, `ShareholdingOfPromoterAndPromoterGroupMember`, `PublicShareholdingMember`, `InstitutionsDomesticMember`, `InstitutionsForeignMember`, `MutualFundsOrUTIMember`, `NonInstitutionsMember`); measures `NumberOfShares`, `NumberOfShareholders`, `ShareholdingAsAPercentageOfTotalNumberOfShares` (fraction), `NumberOfEquitySharesHeldInDematerializedForm`, `NumberOfVotingRights`. | VERIFIED | test |
| SHP3 | Promoter + public = total exactly (16,388,405 + 33,320,815 = 49,709,220). A filing with non-promoter non-public (employee trust) shares would break this; member name UNVERIFIED. | VERIFIED (one filing) | test |
| SHP4 | Reg. 31 total (49,709,220) vs results paid-up / face value (49,710,000): 0.0016%, within the 0.5% cross-check. The gap is rounding of paid-up capital to 0.01 M. | VERIFIED | test |
| SHP5 | Pledged-share **quantity** tag: not present when nothing is pledged. | UNVERIFIED | Need a fixture with pledges |
| SHP6 | `www.nseindia.com/api/corporate-share-holdings-master?index=equities&symbol=X` lists filings with `date`, `broadcastDate` (IST, second precision), `xbrl` URL, `revisedData`. | VERIFIED | test |

## 2a. Implementation facts (DuckDB 1.3.2, pyarrow 26)

| # | Claim | Status | Evidence |
|---|---|---|---|
| I1 | `INSERT OR IGNORE` into a table with a nullable `UNIQUE` column treats NULLs as conflicts: 2 of 2,460 rows inserted. | VERIFIED | `test_insert_or_ignore_keeps_all_rows_with_null_optional_columns` |
| I2 | Fetching `TIMESTAMPTZ` into Python requires `pytz`. | OBSERVED | 2026-11-13 |
| I3 | A self-referencing FK rejects a parent and child inserted in one statement. | OBSERVED | 2026-11-13 |
| I4 | DECIMAL and JSON survive a Parquet round trip; Arrow `decimal128` loads into DECIMAL columns exactly. | VERIFIED | pipeline tests (exact Decimal assertions) |
| I6 | DuckDB cannot delete a referenced row in the same transaction that repointed its references ("still referenced by a foreign key"). Merges therefore tombstone instead of deleting. | OBSERVED | `tests/test_quarantine_cli.py` |
| I7 | Inserting quarantine rows one at a time (Arrow register + insert per row) made a gap-heavy promotion take 11.2 s; bulk insert takes 0.9 s. | OBSERVED | `docs/benchmarks.md`, `tests/test_benchmarks.py` |
| I5 | `executemany` is ~1 ms/row; Arrow registration loads ~3,000 rows in <0.1 s. | OBSERVED | benchmark 2026-11-13 |

## 3. Access & discovery

| # | Claim | Status | Evidence |
|---|---|---|---|
| A1 | `nsearchives.nseindia.com` returns 200 from a cloud container. The `www.nseindia.com/` HTML page and `api.bseindia.com` return 403, but `www.nseindia.com/api/` endpoints (corporate actions, shareholding master, holiday master) returned 200 with a browser User-Agent and no cookie warm-up. | OBSERVED | 2026-11-13 |
| A2 | `content/RSS/Financial_Results.xml` items carry no file links (period/scope description only). | OBSERVED | 2026-11-13 |
| A3 | `content/RSS/Online_announcements.xml` carries direct `corporate/xbrl/*.xml` links for Reg. 30 event filings (54 of ~300 items: analyst meets, KMP changes, orders, board outcomes, demerger, acquisitions). | OBSERVED | 2026-11-13 |
| A4 | RSS `pubDate` has second precision (`13-Nov-2026 00:25:25`), IST. IST is assumed, not stated in the feed. | OBSERVED | 2026-11-13 |
| A5 | Late filings exist: results RSS item published 2026-11-03 for period ended 2024-06-30. | OBSERVED | 2026-11-13 |
| A6 | `content/indices/ind_nifty500list.csv` gives **current** constituents only (`Company Name, Industry, Symbol, Series, ISIN Code`, 501 rows). No machine-readable history found. | OBSERVED | 2026-11-13 |
| A7 | Results-XBRL discovery needs the `www.nseindia.com` API with browser session cookies. | UNVERIFIED | Inferred from A1/A2 |

## 4. Regulatory and corporate facts (all UNVERIFIED unless noted)

| # | Claim | Status | Note |
|---|---|---|---|
| R1 | Single Filing System extended to Reg. 34 Annual Report XBRL (20 Apr 2026) and BRSR (31 Mar 2026); cited as "NSE/CML/2026/08" and "BSE Notice 20260529-28". | UNVERIFIED | The BSE notice date is later than the dates it is cited for. Neither circular has been seen. |
| R2 | Reg. 34 annual XBRL on exchanges uses the MCA Ind AS taxonomy with Notes and prior-FY comparatives. | UNVERIFIED | Needs Reg. 34 fixture |
| R3 | Banks and insurers are not on Ind AS. | UNVERIFIED (consistent with X21 tags) | |
| R4 | SME-listed companies are exempt from Ind AS. | UNVERIFIED | SME out of v1 scope anyway |
| R5 | Schedule III (FY22+) shows current maturities of long-term debt inside current borrowings. | UNVERIFIED | |
| R6 | Nestlé India FY2023-24 was 15 months (Jan 2023–Mar 2024). | UNVERIFIED | Test case for `period_months > 12` |
| R7 | Tata Motors demerger: effective 1 Oct 2025, record/ex-date 14 Oct 2025, TMLCV listing 12 Nov 2025, COA 68.85% / 31.15%. | Ex-date price behaviour VERIFIED (P7); rest UNVERIFIED | |
| R8 | AMFI publishes no consolidated scheme-wise ISIN file; ~45 AMCs publish separately. | UNVERIFIED | Phase 3 only |
| R9 | Financial results must be disclosed within 30 minutes of the board meeting ending. | UNVERIFIED | Used only as a conservative-visibility rule (architecture §6.3) |
| R10 | DVR shares use `INE` ISINs; partly-paid use `IN9`. | UNVERIFIED | |
| R12 | SEBI Integrated Filing (Financials) applies from the quarter ended 2024-12-31, giving uniform `INTEGRATED_FILING_*` XBRL from then on. | UNVERIFIED, and **partly contradicted**: the Star Health Q3 FY25 (Dec 2024) fixture uses the legacy `GeneralInsurance/2020-03-31` taxonomy [X26, X27]. The C9 cutoff does not rely on it; parsers still route by namespace and quarantine unknown taxonomies. |
| R11 | Under Ind AS 7, Indian companies may classify interest paid as operating or financing. | VERIFIED as tagged choice (X14) | |

## 5. Known data limitations (affect results, must be disclosed in any backtest output)

- **L1 Survivorship bias**: `index_constituents_history` starts at the first snapshot date. `backfill-index` (architecture §11.6) reconstructs 2024-10-01 → first snapshot from the regular NSE Indices notices [IDX4-IDX7]. It needs local price history for the event dates, and dummy/spin-off days remain approximate until `TEMPORARY` rows are added. Any backtest with an as-of date before that uses today's constituents and is **survivorship-biased** until historical changes are backfilled manually.
- **L2 Restated comparatives**: after demergers or mergers, prior-year quarters are as-reported (pre-restatement) until restated values are captured from a later Reg. 34 annual XBRL (FY level only) or a verified PDF supplement. YoY growth across such events is flagged, not trusted.
- **L3 Half-yearly balance sheet and cash flow**: in Q1/Q3, balance-sheet and cash-flow inputs are carried forward from the last H1/FY filing; every derived ratio exposes `bs_as_of` / `cf_as_of`.
- **L4 Quarterly debt excludes leases** (X16) and **cash excludes non-current treasury investments** (X17) until annual notes are parsed.

## 6. Methodology choices (CHOICE)

| # | Choice |
|---|---|
| C1 | Money is `DECIMAL(20,2)` rupees in DuckDB/Parquet and `decimal.Decimal` in Python. Never float. |
| C2 | Price series adjusted only for splits, bonuses, rights bonus element and demergers. No dividend adjustment; dividends go to a separate total-return series. |
| C3 | Demerger price factor = parent's ex-date open / prior close. |
| C4 | Unconditional gap auditor threshold: \|Open_t / Close_{t−1} − 1\| > 10%. |
| C5 | Effective tax rate fallback for loss-makers = 0 (no synthetic tax shield). Statutory 25.17% (Sec. 115BAA) is used only where a ratio explicitly needs a statutory rate. |
| C6 | Gross profit is computed only for `INDAS_CORP` with (materials + stock-in-trade purchases) ≥ 10% of revenue; otherwise NULL. |
| C7 | Universe v1: NSE Mainboard `EQ`/`BE`/`BZ`, starting with Nifty 500. SME (`SM`/`ST`) excluded. |
| C9 | **v1 data scope**: market data, corporate actions and index snapshots from `2024-10-01`; financial statements and shareholding with period end `>= 2024-12-31` (Q3 FY25). Older inputs are vaulted but not parsed, and no legacy-format parsers exist. Gives 8 quarters (Q3 FY25–Q2 FY27) for TTM + YoY TTM as of Nov 2026; 3Y/5Y windows are NULL until enough quarters accumulate. | Owner decision 2026-11-13 |
| C8 | Personal, single-user research. No redistribution. Polite, rate-limited fetching with on-disk caching. This is not legal compliance with exchange terms, which prohibit automated access. |
