# Phase 1 and Phase 2: done and pending (2026-11-15)

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
| Reg. 76 share capital reconciliation | **BLOCKED** (G93) | no machine-readable NSE source found (probes A15, 2026-11-15); F09 UNVERIFIED; Reg. 31 x paid-up cross-check stands in |
| Materialized screener_features + DSL-to-SQL compiler | DONE | ~490 columns, saved screens, custom ratios |
| §7 adds: corporate-action auto-adjuster | DONE | prices adjusted for splits/bonus/rights/demergers |
| §7 adds: AMFI monthly MF holdings | Moved to Phase 3 by the PDF's own review (per-AMC files, R8) | quarterly MF % from Reg. 31 is built |
| §7 adds: PIT/SDD insider, bulk/block deals | Phase 3 in §5 (G100, G102, G138) | sources UNVERIFIED / OBSERVED |

**Phase 2 pending: functionality**
1. Reg. 76 (G93), above: BLOCKED until a source is found. (AOC-1 group tree G277: done in batch H.)
2. ~~Merger lineage: target -> acquirer, swap ratio, MERGED status, backtest conversion (G37, G56, G57, G58);
   demerger cost-of-acquisition split (G51).~~ **Built 2026-11-15 (batch F)**: `entity_lineage`, `lineage
   add/amend/coa/retire/load/list`, `lineage.convert_position` (architecture §11.7). Still BLOCKED: automatic merger
   detection (no merger purpose in the corp-action feed, no circular fixture, CA14) and automatic ratios / COA
   percentages (PDF only; R7 UNVERIFIED): both are admin entries with an evidence URL until a source is verified.
3. Share classes: DVR / partly-paid ISINs and market cap summed across classes (G275, G336). **BLOCKED** (2026-11-15):
   the classes exist in the committed bhavcopies (P17: partly-paid = `IN9` + series E1, e.g. OLAPP; DVR in EQ / BZ with
   `IN9` or `INE` ISINs: JISLDVREQS, FELDVR, GATECHDVR; each shares the issuer code with its ordinary share, so G306 /
   R10 are corrected). Not built because (a) partly-paid trade only in series E1, outside the v1 universe (needs an
   owner decision to admit E1), (b) summing market cap needs the share count per class, and whether Reg. 31 counts
   DVR shares with the ordinary shares is unverified: no DVR issuer is in the Nifty 500 and no such pattern is
   committed or in the vault, (c) no fixture states a DVR voting-rights ratio or face value.
4. **DONE (2026-11-15, batch E)** Restatement detector: `restatement_suspected` now also fires on discontinued
   operations != 0 (X108, G67) and a logged MERGER / DEMERGER (X109, G68) in the last 5 quarters
   (`FactBook.restatement_triggers`); Reg. 34 prior-year columns are compared with the stored FY figures at promotion,
   differences are CONSISTENCY / ANNUAL_PRIOR_YEAR_DIFFERS findings (X110, G328; TCS FY26 restates FY25 directors'
   remuneration and salaries). The YTD trigger is X106. Owner decision E: no PDF recovery of restated quarters.
5. **DONE (2026-11-15, batch E)** BSE scrip codes from the in-filing ScripCode (X111, G79); a disagreement with a stored
   code is IDENTIFIER / BSE_SCRIP_CODE_CONFLICT.
6. **DONE (2026-11-15, batch E)** Mutual-fund holding for the 2022 Reg. 31 taxonomy: `MutualFundsOrUtiMember` and its
   holder axis map to MUTUAL_FUNDS (SHP20, parser 0.10.4). A `restage` of the Q3-Q4 FY25 shareholding files is needed
   on the live database for the MF columns of those quarters.

**Phase 2 ratios: built 2026-11-15 (batch G, features `2026.11.15-8G`, `features_extra.py`, arch §10.7)**
Margin acceleration (G152), gross / contribution margin expansion (G257), A&P intensity and marketing efficiency (G256,
G258), input-cost shares (G133), organic vs inorganic flag from business-combination cash outflows (G276, C26),
standalone-to-consolidated profit leakage (G278), incremental asset turnover 3Y (G220, NULL until FY28), institutional
absorption (G241), P/EV (G270), EV/GOV and ARPU / MTU growth (G265, G266; KPI names `arpu`, `mtu`, `casa_pct`), bank
CASA (M4), Reg. 30 red-flag columns kept separate (G117), raw numerator / denominator columns (G244), the
capital-allocation scorecard view `capital_allocation_scorecard` (G201), and 30 more catalogue rows (cost lines, CFO /
PAT, cash tax rate, ETR, exceptional share, capex intensity, net cash / mcap, RPT intensity, Reg. 34 note ratios, P/S,
EV/Sales, pledge change, >1% holder count, event counts).

**Phase 2 pending: ratios**
1. RPT leak % per counterparty type (G236): BLOCKED on a parser. RPT is stored as a total (`rpt_to_sales` is built on
   it); the purchases / loans / royalties split sits in `RelatedPartyTransactionAxis` rows in raw_xbrl_facts (G99).
2. Order book to sales (G115) only if a filing tags an order book; otherwise drop.
3. Penalty amounts (G118, needs an E12 content fixture); Reg. 30 acquisition events for G276 (no event type parsed).
4. Filed ISCR / DSCR (catalogue B1.24): filed values are implausible (C26); needs an evidence row first.
5. The rest of `docs/ratio_catalogue.md` BUILDABLE NOW rows (24): industry medians / peer ranks / sector breadth (with
   the industry-classification work), Beneish / Piotroski components, original Altman Z, balance-sheet accruals,
   depreciation rate, Δ CCC and H1 days, PB / P/S percentiles, RS rank, volatility / drawdown, 52W-high-on-delivery,
   PEAD, index inclusion and ex-date flags, segment mix; price to quarterly earnings waits on Screener's definition.

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
