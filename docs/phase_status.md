# Phase 1 and Phase 2: done and pending (2026-11-16)

Measured against the owner's PDF (`docs/inputs/Aligning_Financial_Results_Databases.pdf`). The PDF defines the phases
twice: an early roadmap (§7, "Core Engine / Deep Edge / Alpha") and the final "Phased Implementation Plan" (§5,
"Thin Slice / Multi-Archetype & Annual Depth / Catalysts"). This report follows §5, which `docs/architecture.md` §15
also follows, and flags where §7 placed an item differently. Requirement ids (G…) are from `docs/owner_requirements.md`;
the full line-by-line audit of the PDF is `docs/master_backlog.md`; ratios are in `docs/ratio_catalogue.md`.

## Phase 1: Thin slice, Nifty 500 (PDF §5)

| PDF item | Status | Where |
|---|---|---|
| entity_master, security_identifier_history (ISIN master) | DONE | identity.py; FinInstrmId + ISIN, date-bounded |
| SHA-256 raw vault | DONE | vault.py; blob != filing |
| UDiFF bhavcopy + delivery loader | DONE | parsers; P-rows in references.md |
| Corporate-action ledger + unconditional gap auditor | DONE | corp_actions.py; quarantine on unexplained gaps |
| INDAS_CORP quarterly XBRL parser | DONE | parser 0.10.4; rules X1-X107 (X108-X111: readers and promotion checks) |
| 20-company golden test suite | DONE | G342; Screener-export goldens |
| §7 adds: Reg. 31 shareholding, wide screener_features + DSL, "full Screener.in parity" | DONE except the parity gaps below | features*.py, dsl.py |

**Phase 1 pending (Screener parity gaps):**
1. **DONE (batch H)** Industry PE / PBV, peer ranks, premium / discount to the industry and basic-industry median
   (G112, G199) on NSE's 4-level classification (G96, G334) from the quote API (F30, IC1-IC3): `fetch-classification`,
   `entity_classification_history`, `features_peers.py`. Point in time from the first fetch (never backdated, C25), so
   the columns are NULL on earlier days; the owner runs `fetch-classification --universe nifty500` once to start it.
2. **DONE (batch H)** Daily run scheduled: `ops/` systemd timer + service, crontab line, Windows Task Scheduler XML
   (20:15 IST daily: `run-day`, then `materialize --incremental`; arch §13). `run-day` takes today's IST date and
   publishes no feature day on a holiday. Installing the unit on the owner's machine is the remaining step.
   **Batch K (2026-11-16):** alternatively GitHub Actions: `nightly-pipeline.yml` on a self-hosted runner (labels
   `self-hosted, financials`) at 22:00 IST runs `run-day`, `fetch-classification --missing-only` + `promote` and
   `materialize --incremental`; `nightly-tests.yml` runs the offline suite on a hosted runner. A hosted runner cannot
   run the pipeline (no data, NSE blocks datacenter IPs, no redistribution); registering the runner is the owner's
   step (`ops/README.md`).
2b. **DONE (storage, 2026-11-16, features `2026.11.16-16S`, decision I)** The 22.4 GiB database held ~6 GB of tables:
   `screener_features` is now written once per materialize run, `compact` rewrites the file without dead space
   (monthly cron line; automatic after full runs when the disk has room) and `prune-versions` archives and deletes
   superseded parser versions (~24 M raw rows, ~2.3 GB). Owner steps: free >= ~4.5 GB next to `data/`, then
   `prune-versions` (it compacts itself when there is room). Architecture §4.1, ops/README.md.
3. Credit rating (Screener ratio) needs credit-rating XBRL (G98, F22 UNVERIFIED).
4. Not possible by design: all-time high/low (data starts 2024-10-01), "Expected quarterly …" (forecasts),
   G Factor (formula unpublished).
5. Waiting for history (built, NULL until data exists): 3/5/7/10-year growth, averages, N-years-back values,
   historical PE/PBV, 3Y+ returns.

## Phase 2: Multi-archetype and annual depth (PDF §5)

| PDF item | Status | Where / what is missing |
|---|---|---|
| INDAS_NBFC, IGAAP_BANK, IRDAI_INSURANCE parsers | DONE | batches 4-6; insurer basis, bank columns |
| Reg. 34 annual XBRL: notes, segments, CWIP | DONE | reg34_annual.py; segment_observations (X97-X99) |
| Reg. 34 annual XBRL: AOC-1 subsidiary/associate/JV tree | DONE (batch H) | `group_structure` from the schedule already in committed annual fixtures (X112); `backfill-group-structure` for filings promoted earlier |
| Reg. 31 shareholding (full) | DONE | incl. pledge, FII/DII/MF/insurance/retail, shareholder count |
| Reg. 76 share capital reconciliation | **BLOCKED** (G93) | no machine-readable NSE source found (probes A15, 2026-11-15); F09 UNVERIFIED; Reg. 31 x paid-up cross-check stands in, plus (batch J) the Reg. 34 year-end share counts cross-checked against both (X114, ANNUAL_SHARE_COUNT_DIFFERS; annual only, no listed / demat split) |
| Reg. 34 annual XBRL: related parties per counterparty | DONE (batch J; Reg. 23(9) rows 2026-11-16) | `related_party_transactions` from the Ind AS 24 schedule (X113, `parsers/rpt.py`); Reg. 23(9) rows of standalone Q2 / Q4 Integrated Filings in `reg23_related_party_transactions` (X115, `parsers/reg23_rpt.py`; data only, R13); `backfill-rpt` fills both for filings promoted earlier |
| Materialized screener_features + DSL-to-SQL compiler | DONE | ~490 columns, saved screens, custom ratios |
| §7 adds: corporate-action auto-adjuster | DONE | prices adjusted for splits/bonus/rights/demergers |
| §7 adds: AMFI monthly MF holdings | Moved to Phase 3 by the PDF's own review (per-AMC files, R8) | quarterly MF % from Reg. 31 is built |
| §7 adds: PIT/SDD insider, bulk/block deals | Phase 3 in §5 (G100, G102, G138) | sources UNVERIFIED / OBSERVED |

**Phase 2 built since the PDF (one line each; details in the batch notes below and in architecture.md)**
- Merger lineage and demerger COA split as audited admin edges (batch F, arch §11.7); restatement detector triggers
  X106-X110 (batch E; owner decision E: no PDF recovery of restated quarters); BSE scrip codes (X111, G79); 2022 Reg. 31
  mutual-fund member (SHP20; a `restage` of the Q3-Q4 FY25 shareholding files is needed on the live database).
- Related parties per counterparty: the Reg. 34 annual schedule (batch J, X113, `rpt_*` columns) and, 2026-11-16, the
  Reg. 23(9) rows of standalone Q2 / Q4 Integrated Filings (`reg23_related_party_transactions`, X115,
  `parsers/reg23_rpt.py`, promoted with each results filing and by `backfill-rpt`; data only, see blocked item 4).

**Phase 2 pending (2026-11-16): only blocked items remain, each with its evidence**
1. **Reg. 76 share-capital reconciliation (G93): BLOCKED.** No machine-readable NSE source: probes A15 (2026-11-15:
   vault ledger, announcements RSS, TCS announcements API) found none; BSE answers 403 (A1); F09 UNVERIFIED. Stand-ins
   built: Reg. 31 x paid-up (X103) and the Reg. 34 year-end share counts (X114).
2. **Automatic merger detection and automatic entitlement / COA ratios: BLOCKED.** No merger purpose in the
   corp-action feed and no delisting-circular fixture (CA14); ratios and COA percentages are published only in PDFs
   (R7, R15 UNVERIFIED). Admin entries with an evidence URL until a source is verified.
3. **Share classes (G275, G336): BLOCKED.** The classes exist in the committed bhavcopies (P17: partly-paid = `IN9` +
   series E1, e.g. OLAPP; DVR in EQ / BZ with `IN9` or `INE` ISINs: JISLDVREQS, FELDVR, GATECHDVR; each shares the
   issuer code with its ordinary share, so G306 / R10 are corrected). Not built because (a) partly-paid trade only in
   series E1, outside the v1 universe (needs an owner decision to admit E1), (b) summing market cap needs the share
   count per class, and whether Reg. 31 counts DVR shares with the ordinary shares is unverified: no DVR issuer is in
   the Nifty 500 and no such pattern is committed or in the vault, (c) no fixture states a DVR voting-rights ratio or
   face value.
4. **A half-yearly RPT view from the Reg. 23(9) rows: BLOCKED** on R13. The rows sit on the filing's quarter context and
   NETWEB filed identical amounts under an Oct-Mar and a Jan-Mar context (X115), so whether they are quarter or
   half-year amounts is unverified. Needs a Reg. 23(9) or results PDF to compare with the XBRL rows.
5. **Penalty amounts (G118): BLOCKED** on an E12 content fixture (`penalties_90d` stays NULL). Reg. 30 acquisition
   events as a second G276 input: no acquisition event type is parsed and no such fixture is committed (G276 itself is
   built from the business-combination cash outflow, C26).
6. **Filed ISCR / DSCR (catalogue B1.24): BLOCKED** on an evidence row: the filed values are implausible (C26).
7. **Price to quarterly earnings (catalogue A1.12): BLOCKED** on Screener's definition (UNVERIFIED).

Not built by decision or evidence: order book to sales (G115, CONFLICTS_WITH_EVIDENCE: no order-book element in
`docs/tag_registry.yaml` or any committed fixture; only per-order Reg. 30 amounts, already `order_value_90d`); "Is
SME" (A1.24, a constant in an SME-free universe, C7); XBRL anchor locking of PDF columns (G69, decision E).

**Phase 2 ratios: built 2026-11-15 (batch G, features `2026.11.15-8G`, `features_extra.py`, arch §10.7)**
Margin acceleration (G152), gross / contribution margin expansion (G257), A&P intensity and marketing efficiency (G256,
G258), input-cost shares (G133), organic vs inorganic flag from business-combination cash outflows (G276, C26),
standalone-to-consolidated profit leakage (G278), incremental asset turnover 3Y (G220, NULL until FY28), institutional
absorption (G241), P/EV (G270), EV/GOV and ARPU / MTU growth (G265, G266; KPI names `arpu`, `mtu`, `casa_pct`), bank
CASA (M4), Reg. 30 red-flag columns kept separate (G117), raw numerator / denominator columns (G244), the
capital-allocation scorecard view `capital_allocation_scorecard` (G201), and 30 more catalogue rows (cost lines, CFO /
PAT, cash tax rate, ETR, exceptional share, capex intensity, net cash / mcap, RPT intensity, Reg. 34 note ratios, P/S,
EV/Sales, pledge change, >1% holder count, event counts).

**Last catalogue rows: built 2026-11-15 (batch I, features `2026.11.15-11I`, `features_more.py`, arch §10.7)**
Beneish components and the nine Piotroski tests, original Altman Z (manufacturers), balance-sheet accruals,
depreciation rate and asset-age proxy, Δ debtor days / Δ CCC on FY and half-year debtor / inventory days YoY, PB / P/S
/ EV-Sales percentiles (G198), RS rank of 12M-1M momentum, volatility and max drawdown 1Y, 52W high on a delivery
spike (G283 flag), PEAD tracker (G151), sector earnings breadth per NSE industry (G205), Nifty 500 inclusion /
exclusion in 90 days, ex-date recency and days to the next ex-date, segment mix (G130 columns). Industry medians, peer
ranks and premiums (A1.19, B5.7, B5.8) were built by batch H.

**PDF corrections of per-share facts (batch K, features `2026.11.15-12K`)**: `correct_from_pdf` also takes EPS and face
value (`fact_corrections.value_other`, rupees per share); the FactBook, the batch prefetch and the EPS result-date
visibility rank them exactly like rupee corrections, and revoking restores the filed value (X107).

## Data quality still open (not a phase item, but blocks trust)

- 101 open Nifty 500 quarantine items: 47 YTD mismatches (mostly restatements, handled by X106), 26 owners/NCI withheld,
  12 share-count mismatches, 7 BSE Ltd shareholding files in an unknown format, 5 unknown ISINs, 4 other.
- 23 consolidated quarters still use total PAT where NCI exists (IKS, Gabriel, Max Healthcare, Lloyds Metals, Syrma,
  Choice, JWL, Shyam Metals, Privi): their PDFs print no owners split or are scanned.
- Syrma files two six-month periods that hold quarter figures (XBRL error, not corrected).
- MCX and Abbott India: NSE returns no Q2 FY27 results.
- One-off income inside operating lines is not detected (only other income and exceptional items are).

## Phase 3 (for completeness; PDF §5)

Reg. 30 event XBRLs (agreements, restructuring, analyst meets, debt servicing), PIT/SDD insider and SAST, bulk/block
deals, F&O UDiFF + participant OI + SLBM, per-AMC monthly portfolios, the point-in-time backtester (needs a verified
Nifty 500 TRI, F29), and the daily diff digest with screen alerts (G189, G282, G283). Owner decisions F-H keep the
website, announcement-text search, portfolio analytics and decision journal out of scope for now; no paid sources.
