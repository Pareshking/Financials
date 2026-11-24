# Phase 3 reuse map: the owner's NSE-BSE-Insider-Tracker

Owner 2026-11-21: "Many of next phase requirements you can find from here already built". Source: the tracker's own
code inventory (`docs/INVENTORY.md`, draft PR #326 there, read from the code on 21 Nov 2026; held ranges measured
from its R2 store). This replaces an earlier keyword check that missed the mutual-fund, flows and backtest code.
Rule for Phase 3: import the tracker's pure parsers before building a feed here, and keep this repo's evidence rules
(real fixture, MANIFEST row, test) for anything that lands in this engine.

## Working in the tracker (reuse)

| Our item | Tracker dataset (inventory row) | Held / notes |
|---|---|---|
| G122, G179 MF portfolios, MF holding change 1M | 27 fund-house month-end portfolios (44 houses + 5 NPS), 28 AMFI scheme lists | Oct 2025 to Oct 2026; per scheme x ISIN: shares, value, passive flag; derived monthly changes. From fund houses' own files (AMFI publishes no holdings file). Not collected: Kotak, Navi, Union, Angel One, WhiteOak, Edelweiss, Bajaj |
| G191 point-in-time backtester | `insiders_clean/track.py`, `evidence.py`, `basket.py` | 10 insider / deal signals, 1W-6M horizons, excess over Nifty 500 and a size-matched index, forward ledger written once |
| G100 PIT insider trades, SAST Reg. 29 | 1, 2, 4 (NSE + BSE PIT); 6, 7 (SAST) | from 8 Oct 2025; NSE PIT history to 2 May 2026 |
| G92 SAST Reg. 31 encumbrances | 8 | NSE only, lender and event type |
| G102 bulk and block deals | 3, 5 | NSE from 8 Oct 2025; BSE from Jan / Feb 2026 |
| G123 NSDL FPI flows, G124 (part) | 26 market flows: NSE FII/DII, NSDL FPI daily + fortnightly sectors, SEBI MF trends | NSE FII/DII is latest-day only (no history) |
| G193 forward event calendar | 11 board meetings NSE + BSE (-30 / +60 days) | |
| G142 buybacks | 16 tender offers + daily open-market reports | daily feed keeps ~2 months; max price only in PDFs |
| G163 (part) further issues | 15 preferential, rights, QIP + allottees + lock-ins | no IPO subscription |
| G139, G140, G207 surveillance, price band, circuit | 23 ASM / GSM / ESM + `sec_list.csv` | daily snapshot from 12 Oct 2026 |
| G62 / G118 (part) announcement text | 17 announcements (NSE 253k, BSE 385k rows), 18 filing text | filing text kept only for recent days |
| Industry classification (4 levels) | 29 | NSE refuses runners: 867 NSE-only companies have 2 levels |

Overlaps where this engine already has its own verified pipeline (do not replace): results XBRL (14), shareholding
(12, 13), corporate actions (9, 10), prices and market cap (19-22), calendar (25), security master (24).

## Not built there (Phase 3 here)

F&O bhavcopy / OI / PCR / participant OI / ban list (G125-G128, G184), BRSR (G109), governance XBRL facts (G121; the
tracker keeps links only), RBI / macro (G135, G147, G148), credit-rating agency feeds (G98; announcement tagging
only), short selling (G103), IPO subscription (G163), index weights (G129), bond / CP yields (G136), Excel exporter
(G165), natural-language to DSL (G188).

## Reuse notes

- No package metadata: put the tracker root on `PYTHONPATH`. Pure parsers (pandas, numpy, pyarrow only):
  `collectors.nse_events.parsers`, `collectors.bse.parsers`, `insiders_clean.prices`, `results`, `industry`,
  `mf_holdings`. Clients need requests; `run_daily` pulls boto3.
- Storage there is Cloudflare R2 + zstd Parquet, raw responses write-once; the owner's R2 account already exists for it.
- Politeness there: NSE 3-5 s, never parallel; BSE 4-6 s. This engine runs NSE archive 12 req/s and API 2 req/s with
  3 in flight, BSE 2-3 s (X354, measured). Keep each repo's own limits; do not run both against the same host at once.
