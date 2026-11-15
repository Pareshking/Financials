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
| INDAS_CORP quarterly XBRL parser | DONE | parser 0.10.3; rules X1-X107 |
| 20-company golden test suite | DONE | G342; Screener-export goldens |
| §7 adds: Reg. 31 shareholding, wide screener_features + DSL, "full Screener.in parity" | DONE except the parity gaps below | features*.py, dsl.py |

**Phase 1 pending (Screener parity gaps):**
1. Industry PE / PBV, peer table, discount to industry median (G112, G199) need NSE's 4-level industry
   classification (G96, G334): a new free source; today only the 20 sector groups of the Nifty 500 file exist.
2. Daily run is not scheduled: `run-day` exists, nothing runs it automatically (G40/G60/G289 were overclaimed).
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
| Reg. 34 annual XBRL: AOC-1 subsidiary/associate/JV tree | **PENDING** (G277, G292) | no fixture with the schedule; table not built |
| Reg. 31 shareholding (full) | DONE | incl. pledge, FII/DII/MF/insurance/retail, shareholder count |
| Reg. 76 share capital reconciliation | **PENDING** (G93) | source F09 UNVERIFIED; Reg. 31 x paid-up cross-check stands in |
| Materialized screener_features + DSL-to-SQL compiler | DONE | ~490 columns, saved screens, custom ratios |
| §7 adds: corporate-action auto-adjuster | DONE | prices adjusted for splits/bonus/rights/demergers |
| §7 adds: AMFI monthly MF holdings | Moved to Phase 3 by the PDF's own review (per-AMC files, R8) | quarterly MF % from Reg. 31 is built |
| §7 adds: PIT/SDD insider, bulk/block deals | Phase 3 in §5 (G100, G102, G138) | sources UNVERIFIED / OBSERVED |

**Phase 2 pending: functionality**
1. AOC-1 group tree (G277) and Reg. 76 (G93), above.
2. Merger lineage: target -> acquirer, swap ratio, MERGED status, backtest conversion (G37, G56, G57, G58);
   demerger cost-of-acquisition split (G51).
3. Share classes: DVR / partly-paid ISINs and market cap summed across classes (G275, G306, G336).
4. Restatement detector, remaining triggers: discontinued operations != 0 and a logged merger/demerger (G67, G68);
   compare Reg. 34 prior-year columns with stored FY figures (G328). The YTD trigger and `restatement_suspected` are
   built (X80, X106). Owner decision E: no PDF recovery of restated quarters (G28, G69 closed by it).
5. BSE scrip codes from the in-filing ScripCode (G79).
6. Mutual-fund holding for the 2022 Reg. 31 taxonomy: the parser does not map `MutualFundsOrUtiMember`
   (Q3-Q4 FY25 patterns), a parser rule + version bump.

**Phase 2 ratios: built 2026-11-15 (batch G, features `2026.11.15-8G`, `features_extra.py`, arch §10.7)**
Margin acceleration (G152), gross / contribution margin expansion (G257), A&P intensity and marketing efficiency (G256,
G258), input-cost shares (G133), organic vs inorganic flag from business-combination cash outflows (G276, C25),
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
4. Filed ISCR / DSCR (catalogue B1.24): filed values are implausible (C25); needs an evidence row first.
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
