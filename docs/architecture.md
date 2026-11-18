# Architecture: Indian Equity Research & Screening Engine

Claim IDs in brackets (e.g. [X2], [P5]) point to `docs/references.md`. Anything marked
UNVERIFIED there must not be hard-coded; code that depends on it quarantines on surprise.

---

## 1. Scope

- **Purpose:** personal, single-user research, screening and point-in-time (PIT) backtesting. No redistribution [C8].
- **Universe v1:** NSE Mainboard `EQ`, `BE`, `BZ`, starting with the Nifty 500 [C7]. SME (`SM`, `ST`) out of scope. BSE is used only as a fallback and for historical Reg. 34 annual XBRL backfill.
- **Filings universe `mcap500`** (owner 2026-11-17, rule U1 [X134], §11.12): every `EQ`/`BE`/`BZ` row of NSE's mcap file, Category `Listed` or `Permitted` (rule U1-P, owner 2026-11-17; Permitted securities are listed on another exchange, mostly BSE, and file there [X166], §11.13), whose NSE market cap (PR-zip mcap file [X130]) is >= Rs 500 Cr on the last trading day of a week joins `universe_membership`; members never leave; SME series and the zip's SME file are never read for it; no share-class aggregation ("ignore DVR"). The Nifty 500 set the project started with is its seed. `discover-filings --universe mcap500` (or `mcap500-new`: members without financials yet) fetches their filings; `nifty500` keeps working. The feature universe is unchanged (every security with a recent bar, §4.1).
- **Data scope (v1, CHOICE [C9]):** `trade_date >= 2024-10-01` for prices, delivery, corporate actions and index snapshots; `period_end >= 2025-03-31` for financials and shareholding (Q4 FY25, the first Integrated Filing quarter [X38]; `financials/scope.py`). As of Nov 2026 that is 7 quarters: TTM works, YoY-on-TTM is NULL until Q3 FY27 (Dec-2026) results are filed. Promotion returns `OUT_OF_SCOPE` for older inputs (vaulted, not parsed); `fetch-days` / `fetch-corp-actions` clamp start dates. Multi-year windows use `fundamentals.cagr(..., min_periods_required)` and stay NULL until enough in-scope quarters exist.
- **Non-goals (v1):** multi-user, UI hosting, Cloudflare (R2/D1/Workers), real-time intraday prices, SME/Indian-GAAP corporates.

## 2. Runtime topology

| Where | What runs |
|---|---|
| **Local machine** (owner's) | All fetchers (both `www.nseindia.com` session-cookie fetchers and `nsearchives.nseindia.com` archive fetchers), the vault, staging Parquet, the promoter, `data/market.duckdb`. |
| **GitHub Actions** | Offline `pytest` on every push and PR (`.github/workflows/ci.yml`). Tests never touch the network. |

Decision **D-1** (owner, 2026-11-13): GitHub Actions runs only offline lint + tests; all fetching stays local (`data/` gitignored) until the pipeline is proven end to end. `www.nseindia.com/api/` endpoints also answered from a cloud container [A1], but that is not relied on.

Operator commands (`python -m financials --data-dir data …`):

| Command | Effect |
|---|---|
| `init-db` | apply `schema.sql` to `data/market.duckdb` |
| `fetch-days START [END]`, `fetch-corp-actions START END`, `fetch-holidays`, `fetch-index --as-of D`, `fetch-shareholding SYM…\|--universe U`, `fetch-annual SYM…\|--universe U`, `fetch-results [URL] [--symbols …\|--universe U]`, `discover-filings [--symbols …\|--universe nifty500\|mcap500\|mcap500-new\|active\|--from-rss] [--workers N]` | download → vault → staging only (`--workers` threads overlap hosts; each host stays at ≥ 1 s between requests). Vaulted archive files are never downloaded again (vault URL index); a failed day or file is reported and the run goes on; corporate actions are asked in 30-day windows |
| `promote` | the single writer: applies pending stages in order (holidays, market days by date, index snapshots and PR-zip mcap files, corporate actions, results, shareholding, raw-only) and records them in `promotion_log`. ABORTED batches stay pending, and every later market day waits behind an aborted one |
| `rebuild-market --from D` | rolls market-derived state back to `D` (bars, bhavcopy/inferred calendar rows, identifier intervals, auto-decided corporate actions, feature history), replays the staged days and re-materialises; raw tables untouched; audited in `admin_log` |
| `materialize D` / `materialize --from D1 --to D2` | builds features for `D` (or every promoted trading day in the range, ascending) with gates G4/G5; consumes the dirty markers the range covers (§11.10) |
| `materialize --incremental [--to D]` | recomputes only the rows marked dirty since the last run, on already-materialised days, with G4/G5 on each merged day (§11.10); refuses when a day was built by another `FEATURES_VERSION` |
| `compact [--keep-old \| --spill DIR]` | `--spill`: low-disk mode through verified Parquet (§4.1). Otherwise CHECKPOINT, copy every table into a sibling file created from `schema.sql`, verify row counts and views, swap the files atomically (§4.1). Refuses when free disk < 1.1 x the live size. Also runs at the end of a full `materialize --from/--to`, `rebuild-market` and `prune-versions` when there is dead space and room (`--no-compact` skips it) |
| `prune-versions [--archive DIR] [--dry-run]` | archives (zstd Parquet + manifest + `admin_log`) and then deletes the rows of superseded parser versions no reader can select (decision I, §4.1) |
| `drop-raw-xbrl [--spill DIR] [--no-compact] [--note N]` | one-shot, owner decision J: refuses unless the coverage check (`scripts/disclosure_coverage.py`) reports 0 uncaptured elements per profile, then drops `raw_xbrl_facts` with an `admin_log` entry in one transaction (idempotent) and compacts (§4.1) |
| `run-day --date D` | holiday list, market days D−7..D (each with its PR-zip mcap file [X130]), corporate actions D−7..D+30, discovery for symbols with results in the day's RSS (A9) + Reg. 30 events, promote, rule U1 for the week ends in D−7..D (§11.12), `materialize --incremental --to D−1`, materialise D in full; idempotent |
| `fetch-mcap START [END] [--weekly]` | the PR-zip mcap files of promoted trading days (`--weekly`: each ISO week's last trading day only, the universe backfill); vaulted zips are not downloaded again (`fetch-days` fetches each day's zip too) |
| `import-bse DIR`, `bse-members [--as-of D]` | vault + stage a BSE runner ledger (then `promote`; rule BSE1 for the list of securities); list the Permitted members with ISIN and BSE scrip code (§11.13) |
| `update-universe [--from D] [--to D]` | rule U1 over the week ends in the range (default 2024-10-01 → today) plus the one-time seed; sticky, idempotent, audited in `admin_log` (§11.12) |
| `check-issue-size --as-of D [--all]` | read-only cross-check: NSE Issue Size vs Reg. 31 total per security on a quarter end, 0.5% tolerance [X133] |
| `screen "QUERY" [--as-of D]` | runs a DSL screen on the live table or point-in-time on history (read-only connection) |
| `load-kpis FILE` | stages a supplemental-KPI CSV/JSON (`parsers.kpis`) for `promote` into `supplemental_kpis` |
| `export-bundle --out DIR [--max-file-mb 50 --max-total-mb 250]`, `import-bundle DIR --db PATH` | zstd Parquet shards of every table of schema.sql with a manifest of row counts and checksums; import verifies them (a `raw_xbrl_facts` part of an older `--include-raw` bundle is skipped: decision J). Local or private storage only: the data is NSE-derived and the repository is public |
| `quarantine list [--stage --reason --entity --security --all]`, `quarantine inspect Q`, `quarantine resolve --id Q --action A --note N [--payload-json J]`, `quarantine reprocess` | audited quarantine resolution (D-6); `list` and `inspect` are read-only |
| `extract-index-changes TEXT_DIR --out CSV`, `backfill-index --manifest CSV` | index membership before the first snapshot (§11.6) |
| `lineage list`, `lineage add --parent P --child C --relation R --effective D [--ratio A:B] --evidence-url U --note N`, `lineage amend --id L --ratio A:B …`, `lineage coa --parent P --effective D --parent-pct X --child C=Y …`, `lineage retire --id L`, `lineage load --manifest reference/entity_lineage.csv` | merger / demerger lineage and the demerger COA split, audited (§11.7) |
| `python -m financials.bench --out docs/benchmarks.md` | reproducible benchmarks on the fixtures (`docs/benchmarks.md`) |

### 2.1 Data flow

```
fetchers (many, parallel)                 promoter (exactly one process)
  │  download → sha256 → data/vault/        │  reads staging Parquet
  │  write filings row + raw rows to        │  runs quality gates (§12)
  │  data/staging/<job>/<run_id>.parquet    │  resolves identifiers
  ▼                                         │  writes canonical + derived tables
data/vault/ab/ab12…ef.<ext>   ───────────▶  ▼  in one DuckDB transaction
                                          data/market.duckdb
```

- Fetchers and parsers **never open `market.duckdb` for writing**. DuckDB allows one writer process.
- Parsing is a pure function of (blob bytes, `parser_version`). Any parser change can be replayed from the vault with no network.

## 3. Data sources

| Dataset | Source | Format | Status | Phase |
|---|---|---|---|---|
| Daily prices + identifiers | `nsearchives…/content/cm/BhavCopy_NSE_CM_0_0_0_<YYYYMMDD>_F_0000.csv.zip` | UDiFF CSV in zip | VERIFIED [P1] | 1 |
| Daily delivery | `nsearchives…/products/content/sec_bhavdata_full_<DDMMYYYY>.csv` | CSV, no ISIN | VERIFIED [P10] | 1 |
| Index constituents (current) | `nsearchives…/content/indices/ind_nifty500list.csv` | CSV | VERIFIED [IDX1, IDX2] | 1 |
| Quarterly results XBRL | `nsearchives…/corporate/xbrl/<file>.xml`; discovery via `www.nseindia.com` API | XBRL | Files VERIFIED [X1]; discovery UNVERIFIED [A7] | 1 (corp), 2 (others) |
| Reg. 30 event XBRL | `content/RSS/Online_announcements.xml` → `corporate/xbrl/` links | RSS + XBRL | OBSERVED [A3] | 3 |
| Corporate actions | `www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=…&to_date=…` | JSON | VERIFIED [P12, CA1-CA9] | 1 |
| Corporate actions (discovery) | `nsearchives…/content/RSS/Corporate_action.xml` (no symbol/ISIN) | RSS | VERIFIED [CA6] | discovery only |
| Trading holidays | `www.nseindia.com/api/holiday-master?type=trading` | JSON (current year) | VERIFIED [CAL1] | 1 |
| Market cap + Issue Size per security | `nsearchives…/archives/equities/bhavcopy/pr/PR<DDMMYY>.zip` → `mcapddmmyyyy.csv` | CSV in zip (fixed-width) | VERIFIED [X130-X133] | 1 |
| Shareholding (Reg. 31) | `www.nseindia.com/api/corporate-share-holdings-master?index=equities&symbol=X` → `nsearchives…/corporate/xbrl/SHP_*.xml` | JSON + XBRL | VERIFIED [SHP1-SHP15] | 1 |
| Reg. 34 annual XBRL | UNVERIFIED [R2] | XBRL | — | 2 |
| F&O, SLBM, AMC portfolios, macro | UNVERIFIED | various | — | 3 |

Fetch etiquette (implemented in `financials.fetch.http.PoliteFetcher`): ≥1 s between requests per host, at most 4 attempts with jittered exponential backoff on 403/429/5xx, other 4xx fail at once, a fixed identifiable User-Agent, optional one-time warm-up page per host. Every response that feeds the pipeline is vaulted (including the shareholding master JSON, via the `raw_only` job). Whether NSE blocks the identifiable User-Agent is UNVERIFIED: the probes used a plain browser string.

## 4. Storage layers

| Layer | Contents | Mutability |
|---|---|---|
| L0 Vault | `blobs`, `filings`, files under `data/vault/` | Append-only. Never rewritten. |
| L1 Raw | `raw_cm_bhavcopy`, `raw_delivery`, `raw_index_snapshot` (XBRL facts: the vault blob, decision J), all keyed by **source identifiers** (symbol, series, ISIN as the exchange sent them) | Append-only. Re-parse appends new rows keyed by `parser_version`. |
| L2 Canonical | Identity (`entity_master`, `securities`, `security_identifier_history`), `ohlcv`, `filing_meta`, `fact_observations`, `corp_actions`, `index_constituents_history`, `trading_calendar` | Rebuildable from L0/L1 + `quarantine_queue` resolutions + `company_overrides`. |
| L3 Derived | Adjustment factors, adjusted prices, total-return index, `screener_features`, snapshots | Fully rebuildable. Swapped atomically. |

### 4.1 Storage: what lives where, sizes, compaction and pruning

| Where | What | Size (live database, 2026-11-16) |
|---|---|---|
| `data/vault/` | every downloaded file, by sha256; the source of truth for every parse | |
| `data/staging/` | parsed Parquet batches waiting for (or recorded by) `promote` | |
| `data/market.duckdb` | every table below; one file, one writer | 22.4 GiB file, ~6 GB in use by tables |
| `raw_xbrl_facts` | **removed by `drop-raw-xbrl` (owner decision J)**: every XBRL fact verbatim, once per parser version. Every element of every parsed filing reaches a clean table (`disclosure_facts`, X116); the vault blobs (0.7 GB) stay the source of truth | was 48.9 M rows, 4.4 GB (~24.9 M rows, ~2.2 GB after `prune-versions`) |
| `disclosure_facts` | every fact of an element no other clean table holds (X116), as filed, slimmed by parser `disc-2` (owner decision M, X120): the 783 (source kind, element) pairs of `reference/disclosure_exclusions.csv` and values that are asterisks only (`******` masks) are not stored, and a value longer than 1,000 characters is a pointer row (`value_text` NULL; `text_len`, `text_sha256`, `text_snippet` of 300 plain-text characters). `disclosures.full_text(con, vault, filing_id, seq)` returns such a text from the vault blob after checking its sha256. Elements a reader selects (`parsers.disclosures.READ_ELEMENTS`) are exempt, so every reader's answer is the same as under `disc-1`. Re-parse: `backfill-disclosures`, then `prune-versions` (archives and removes disc-1), then `compact` | disc-2: 3.01 M rows (28,779 pointers), 0.15 GB of table blocks (disc-1: 4.61 M rows, 1.49 GB); scratch copy 2026-11-16: file 3.87 GB -> 2.47 GB after `backfill-disclosures`, `prune-versions`, `compact` |
| `audit_opinions` | one row per results / annual filing (parser `audit-1`, X121-X124): the audit opinion derived from the auditor's report text (Reg. 34) or the Integrated Filing audit fields, going-concern material uncertainty (entity / group and component-only apart), emphasis of matter, the checkbox as filed next to it and their conflict, the report text's length and sha256. Promoted with the filing; `backfill-audit-opinions` fills filings promoted earlier (vault blobs, process pool, one insert) | ~10k rows (1,458 annual) |
| `screener_features_history` | view: one row per security and materialised day (§11.9) over `features_daily` + `features_events` (below) | 1.33 M rows; was a 1.0 GB table before -17E |
| `fact_observations`, `shareholding_*`, `segment_observations`, … | canonical facts, per parser version | ~0.4 GB together |
| `data/archive/` | `prune-versions` output: zstd Parquet per table / version + `manifest.json` | |

The rest of the file is dead space. DuckDB marks deleted rows and reuses whole free blocks, but never shrinks the file.
Before -16S every materialised day of a run deleted and rewrote the live `screener_features` table, a full rebuild
deleted and rewrote the history, and every re-parse added a full copy of a filing's raw facts (9 parser versions:
0.6.0 alone holds 21.6 M raw rows). Three things keep the file at its live size:

- **The live table once per run** (`features.materialize_days`, §11.11): a `materialize --from/--to`, `--incremental`
  or `rebuild-market` run writes `screener_features` in the transaction of its last day only (gates unchanged; if
  the run stops early, it is written from the last published day, so the tables end as the day-by-day publish
  left them).
- **`compact`** (`financials.storage.compact`): CHECKPOINT; the live size is the blocks the tables' persistent
  segments occupy (`pragma_storage_info`); refuses when the free disk is below 1.1 x that. A sibling
  `market.duckdb.compact` is created from `schema.sql` (constraints and views from the source of truth), every table
  is copied in schema order (each foreign key finds its parent), each table's row count and the views are verified,
  then `market.duckdb` is renamed to `.bak`, the copy to `market.duckdb`, and the `.bak` deleted (`--keep-old`
  keeps it). It opens the database for writing, so it refuses while another process holds it. Run it monthly
  (`ops/cron/financials.cron`) and after full rebuilds; full `materialize --from/--to`, `rebuild-market` and
  `prune-versions` run it themselves when >= 20% (and >= 256 MB) of the file is dead and the disk has room, else
  print the command.
- **`compact --spill DIR`** (`compact_via_spill`, low disk; added 2026-11-16 when the container had 3.3 GB free for a
  6 GB live size): every table is exported to zstd Parquet under DIR and each export's content digest (row count,
  xor and sum of row hashes) is checked against the table; a manifest marks the spill complete; only then is the
  database deleted, recreated from `schema.sql`, reloaded in schema order and every digest re-checked before the
  spill is removed. Needs room for the Parquet only. An interruption after the delete is resumed by re-running
  with the same DIR (the manifest is the checkpoint).
- **`prune-versions`** (owner decision I, `financials.storage.PRUNE_RULES`): deletes the rows of superseded parser
  versions that no reader can select, after writing them to `DIR/prune-<UTC time>/<table>/parser_version=<v>/
  rows.parquet` (zstd) with `manifest.json` (table, version, rows, sha256), reading each file back, and logging the
  run in `admin_log`; a failed archive write deletes nothing. What a reader can select, per table:
  - `fact_observations`, `segment_observations`: every value reader filters `CURRENT_VERSION` (the latest
    `filing_meta` version of the filing; a filing without `filing_meta` keeps every version). The scope decision's
    anchor periods (`pat`, 3 / 12 months) group every version, so an old anchor row stays unless the current version
    has the same period visible no later.
  - `raw_xbrl_facts`: no rule since decision J; the table is gone (below).
  - `shareholding_observations` / `_line_items` / `_major_holders`: readers join the ranked `shareholding_meta` row
    (latest visible, then highest version), so an old version goes only when a newer version of the same filing,
    entity and as-of date is visible from the same instant (a re-parse that moved visibility leaves it selectable,
    X83); observations also need the same category in the newer version (the promoter's share cross-check).
  - `related_party_transactions`: ranked per (entity, scope, period end) by visibility, filing, version: an old row
    goes only when a newer version covers the same period from the same instant. `group_structure` and
    `reg23_related_party_transactions` (X160): the latest version per filing stays (no feature reader).
  - Never pruned: versions named by a quarantine finding (`details.parser_version`) and every version of a filing
    with an open finding; `filing_meta` and `shareholding_meta` whole (read across versions: rounding level, fiscal
    year starts, accounting basis, visibility timestamps; small); `corporate_events` (one row per event);
    `fact_corrections` names a filing, not a version.
  `tests/test_storage.py` materialises the fixture market with injected superseded versions (different values) and
  the rows above that must stay, prunes, materialises again and compares every table; the archive is read back.

**Event-sparse history (features `2026.11.16-17E`, `financials.features_store`).** The wide history table stored
every column of every security on every day, although most columns (TTM / annual / quarterly lines, margins, growth,
ratios on filed values, scope and restatement flags, Beneish / Piotroski, segment mix, related-party ratios) change
only when one of the security's filed inputs becomes visible. It is now two tables and a view:

- `features_daily (as_of_date, security_id, DAILY columns)`, PRIMARY KEY (as_of_date, security_id): every
  materialised day. 249 columns (with the two keys): identity (entity, symbol, series), price / volume / delivery
  and every technical, share count, market cap, EV and every ratio on them (PE, PB, EV/EBITDA, yields, P/S,
  P/FCF, PE core, PEG, earnings yield, EPS restated for share-count events, book value per share, Graham number,
  dilution), percentiles vs own history, windows that move with the as-of date (Reg. 30 90-day counts and red
  flags, 365-day corporate-action flags, Nifty 500 inclusion, days to the next ex-date, PEAD), inputs outside the
  fundamentals-cache key (shareholding and ownership, NSE classification, supplemental KPIs and what reads them,
  Nifty 500 membership) and the same-day cross-section (magic formula, gem score, hats, industry medians and peer
  ranks, RS rank, industry earnings breadth: the refresh steps UPDATE only this table).
- `features_events (security_id, valid_from_date, valid_to_date, EVENT columns)`, PRIMARY KEY (security_id,
  valid_from_date): one row per interval [valid_from_date, valid_to_date) of identical EVENT values (400 columns,
  `features_store.EVENT_COLUMNS`); `valid_to_date` NULL = open.
- `screener_features_history` (view, below VIEWS_MARKER): `features_daily LEFT JOIN features_events` on the
  security and `valid_from_date <= as_of_date < valid_to_date`, with exactly the names, order and types of
  `screener_features` (a test compares `information_schema`), so the DSL, `screen --as-of`, the backtest readers,
  G4 and the compare script read the same rows as before. `screener_features` stays a table.

*The split.* EVENT = exactly the columns computed from the per-entity fundamentals block (`features._fundamentals`
and the period values of batches A, C, D, G, I, J) and from static inputs (archetype override, curated CSVs).
`FundamentalsCache` (§11.11) reuses that block for every day of a run whose key (latest visible quarter, number of
the entity's visibility timestamps in `fact_observations` / `filing_meta` / `fact_corrections`, number of its
structural ex-dates) did not move, so these values can change only on a key change; `segment_observations` and
`related_party_transactions` rows are written by the same promotion as their filing's `filing_meta` row, with the
same entity and visibility; so are `disclosure_facts` rows (18D; the annual ones feed EVENT columns, the Reg. 31
declarations DAILY ones), and `backfill-disclosures` marks the entity dirty from the filing's visibility. Empirical check on the live database (read-only, 2026-11-16, 1.33 M rows, 526 days):
for each column, the security-day transitions where the value changed while the key did not. 485 columns had none;
85 of them stay DAILY by code reading (they read the price, the day, KPIs, classification, a moving window, or are
always NULL so far but price-based, e.g. `return_3y`, `pe_vs_own_5y_median`, peer medians); the 400 EVENT columns all
had zero. Every column with a violation is DAILY (e.g. `eps_latest_quarter`: 42 days where only a split moved it;
the shareholding columns: shareholding is outside the key). When in doubt a column is DAILY. The split never
decides correctness: a write stores the values it was given, whatever their column; a wrongly classified column
only adds intervals.

*Writes* (`features_store.write_day`, inside the day's publish transaction): the day's DAILY rows are replaced
(the whole day, or for `--incremental` only the recomputed entities' rows, as before); then each security's EVENT
values are compared (`IS NOT DISTINCT FROM`, column by column) with the interval covering the day. Equal: nothing
is written. Different: the values are set on [D, N), N = the security's next materialised day after D (open when
none); the overlapping interval keeps its parts before D and from N; adjacent intervals with identical values are
merged. In a normal run (days ascending) this is "close the open interval at D, open a new one". Batched: a fixed
handful of statements per day whatever the number of securities. Invariants (`check_invariants`, tested): no
overlap, no identical neighbours, every daily row in exactly one interval; any write order (full runs, incremental
runs, a re-materialised past day, deletions) leaves the intervals a day-by-day write of the final rows would.
`rebuild-market` calls `features_store.delete_from` (daily rows >= the date, intervals starting from it, the
interval still covering an earlier day reopens). Multi-day readers that need only DAILY columns (PE / EV-EBITDA /
PB / P/S / EV/S percentile history, the 5-year PE median, market breadth, `max(as_of_date)`) read `features_daily`
directly; everything else reads the view.

*Identity.* `tests/test_features_store.py` materialises the fixture market while a shadow wide table is written the
old way (DELETE + INSERT of the full rows, the cross-section UPDATEs run on it): after a full run, an incremental
run, an out-of-order day, a deletion from a middle day and its replay, `rebuild-market`, and the migration, the view
and the wide table are identical (Decimals with their exponent, floats, NULLs). On the live database (read-only
copy into a temporary DuckDB) the whole history converted with `convert_wide` equals the live table row for row
(EXCEPT ALL both ways), and the `write_day` path fed the live rows of a sample of days in and out of order too
(`docs/phase_status.md` has the numbers).

*Migration of an existing database* (single writer, one transaction): `apply_schema` refuses a database whose
`screener_features_history` is still a table (`SchemaMigrationError`), so nothing writes into the old layout.
- **`drop-raw-xbrl`** (owner decision J, `financials.raw_xbrl`, one-shot, single writer): refuses unless the
  coverage check (`raw_xbrl.coverage`, printed by `scripts/disclosure_coverage.py`) reports 0 uncaptured elements
  for every profile / file type; then `DROP TABLE raw_xbrl_facts` and an `admin_log` entry (`DROP_RAW_XBRL`: rows,
  coverage, the values that from then on live only in the vault, decision J) in one transaction; idempotent (a
  database without the table is left alone); then compacts as a full run does (`maybe_compact`, needs ~1.1 x the
  live size free; `--spill DIR` compacts through Parquet instead, ~0.5 x). `compact` (both modes) refuses a
  database that still has the table, naming this command, so it is never dropped silently. `apply_schema` never
  recreates it. What then lives **only in the vault blob, by design**: facts of pre-cutoff contexts of promoted
  filings (C9; ~2.49 M values on the live database) and every fact of the 64 quarantined / out-of-scope filings
  (~2.36 M values; invariant 9: quarantine keeps the raw data, which is the blob). Readers that used the table now
  read clean rows or the blob: the X89 wrong-template rule parses the quarantined filing's blob
  (`promoter.wrong_template_keys`), the G79 ScripCode comes from `disclosure_facts`, the Reg. 23(9) backfill
  selection from reg23 rows or `NameOfCounterParty` in `disclosure_facts`, `statements.segments` from
  `segment_observations`; staging no longer writes raw facts (the scope gate's declared period ends travel in the
  stage manifest). Expected effect on the live file: the table's blocks (4.4 GB, or ~2.2 GB if `prune-versions` ran
  first) are freed and given back by the compaction.
`python -m financials --data-dir data migrate-sparse-history` renames the wide table, creates the two tables and
the view, fills them (`features_store.convert_wide`: DAILY columns copied, EVENT runs of identical consecutive rows
found with exact window comparisons, 40 columns per pass), verifies the view against the wide table (counts and
EXCEPT ALL both ways, 20 days per pass) and drops it; any difference rolls everything back. It then compacts
when the dead space is worth it (the dropped table), as a full run does. Then `materialize --from 2024-10-01 --to
<last day>` (FEATURES_VERSION changed, so `--incremental` refuses until a full run).

Measured read-only on the live database (2026-11-16, `prune-versions --dry-run` rules): prune removes 23.97 M of
48.9 M `raw_xbrl_facts` rows (~2.16 GB), 2.73 M of 5.78 M `fact_observations` (~0.10 GB), 3.84 M shareholding rows
(~0.06 GB) and 1,340 segment rows; nothing in `related_party_transactions` / `group_structure` (one version each).
After prune + compact the file should be ~4-5 GB (≈3.6 GB of table blocks plus primary-key indexes), from 22.4 GiB;
`drop-raw-xbrl` (decision J) then removes the remaining ~2.2 GB of raw XBRL blocks (the whole 4.4 GB without a prune).
The owner kept the full feature universe (every security with a recent bar, ~3,000 today, to be expanded): the
history is ~1 GB for 1.33 M rows and grows with the days and the universe.

## 5. Schema

**Source of truth: `src/financials/db/schema.sql`.** It is applied by `financials.db.apply_schema`
and, so batches are type- and FK-checked before promotion, also by the staging writer.
This section only records the decisions; it does not duplicate the DDL.

| Layer | Tables |
|---|---|
| L0 | `blobs` (sha256 PK), `filings` (one publication of a blob; `UNIQUE(exchange, source_url, sha256)`) |
| L1 | `raw_cm_bhavcopy`, `raw_delivery`, `raw_index_snapshot`. Keyed by source identifiers plus `filing_id`. No surrogate IDs. XBRL facts have no raw table (decision J): the vault blob. |
| L2 identity | `entity_master`, `securities`, `security_identifier_history` (date-bounded; `valid_to` exclusive), `trading_calendar` |
| L2 market | `ohlcv` (resolved, unadjusted; delivery joined) |
| L2 fundamentals | `filing_meta` (per filing × parser_version), `fact_observations` (long format), `segment_observations` (Ind AS 108 segment and geography rows, §14b-1), `group_structure` (AOC-1 subsidiaries / associates / JVs per fiscal year from Reg. 34 [X112]), `related_party_transactions` (Ind AS 24 related-party schedule per counterparty, category and transaction element from Reg. 34 [X113]), `reg23_related_party_transactions` (Reg. 23(9) rows per counterparty from standalone Q2 / Q4 Integrated Filings [X115]; the half-year in `disclosure_start` / `disclosure_months` [X160, exceptions X161], never feeds a ratio), `disclosure_facts` (every fact of an element no other clean table holds per element, as filed: results, annual, Reg. 31 and Reg. 30 filings; typed value columns, `in_window`; [X116, C28]) |
| Control | `corp_actions`, `quarantine_queue`, `company_overrides` |
| L2 calendar/index | `trading_calendar`, `calendar_coverage`, `raw_index_snapshot`, `index_constituents_history` |
| L2 shareholding | `shareholding_meta`, `shareholding_observations` |
| L3 | `screener_features`, `features_daily` + `features_events` (read as the view `screener_features_history`, §4.1), `user_custom_ratios`; control: `promotion_log` |
| L2 classification | `raw_quote_classification` (NSE quote answer as sent [IC1]), `entity_classification_history` (NSE macro / sector / industry / basic industry, date-bounded, visible from the first fetch, never backdated [IC3]) |

Decisions:
- **Timestamps are `TIMESTAMP` holding UTC.** `TIMESTAMPTZ` would make DuckDB's Python client require `pytz` [I2].
- **Money is `DECIMAL(20,2)`, prices `DECIMAL(18,4)`, factors and ratios `DOUBLE`.** Bulk inserts go through Arrow (`decimal128`), which keeps decimals exact [I4].
- **`fact_observations` has `period_type` (`DURATION`/`INSTANT`).** Instants store `period_start = period_end` because DuckDB PK columns cannot be NULL. CHECK constraints tie `unit` to `value_inr`/`value_other` and `period_type` to `period_months` (1..18).
- **`filings.supersedes_filing_id` has no FK** (DuckDB self-reference limitation [I3]). It is enforced in code.
- **No nullable `UNIQUE` columns.** DuckDB's `INSERT OR IGNORE` treats NULLs in them as conflicts and silently drops rows [I1]. `entity_master.cin` is therefore not UNIQUE.
- **Deterministic IDs** (`financials.ids.stable_id`). A replay produces identical keys, so `INSERT OR IGNORE` makes promotion idempotent.

### 5.1 Identity resolution
A universe row (`EQ`/`BE`/`BZ`) continues an existing security if **either**:
- its `FinInstrmId` has ever belonged to that security (this survives splits [P5]), **or**
- its ISIN is held by that security's open interval (this survives series changes, which assign a new `FinInstrmId` [P13]).

Other outcomes:
- Both keys pointing at different securities → `IDENTIFIER/ISIN_COLLISION`.
- Any change of ISIN, symbol, series or `FinInstrmId` closes the open interval and opens a new one, emitting an event. `ISIN_CHANGE` feeds the gap auditor.
- A split and a series change on the same day would create a new security. This is not seen yet; the gap auditor would flag it.

## 6. Time, period and scope rules

### 6.1 Period length
`period_months` = whole months from `period_start` to `period_end` inclusive, allowed range 1..18. Transition years can be 15 months [R6]. Flows are only compared, summed or differenced when `period_months`, `scope` and fiscal alignment all match.

### 6.2 Deriving quarterly flows
- Quarter value = `OneD` fact when present.
- Otherwise quarter = YTD_k − YTD_{k−1}, both in the same FY, scope and profile, and both starting on a declared fiscal-year start (`filing_meta.fy_start`): an Oct-Mar six-month context in a "Yearly" filing is not a YTD [X82]. The derived row records `source_element = 'DERIVED:YTD_DIFF'`.
- Q4 is frequently reported as FY − 9M, so the identity `FourD(Qk) = Σ OneD` is **not** a restatement detector.

### 6.3 Point-in-time visibility
- `visible_from_ts` = the latest of `filings.broadcast_ts` and the listing's `broadcast_Date` / `creation_Date` (`raw_results_listing`, filled from every vaulted `RESULTS_LISTING`) [X83]. A revised listing row has no `broadcast_Date`, and a re-uploaded file is created after the broadcast of the row it replaces. Source `BROADCAST` or `LISTING_CREATION`.
- Otherwise (last resort) `board_meeting_end_ts + 1 trading day`, flagged `BOARD_MEETING_RULE` [R9, UNVERIFIED], lifted to the XBRL file-name upload time read as PM (`FILENAME_TS`) when that is later. The board-meeting rule alone is **not** conservative for re-filings: 408 of 684 such filings were uploaded more than a day after the date it gave (X83).
- Never earlier than the file-name upload time read as AM (the name is a 12-hour clock without AM/PM).
- If no broadcast, listing or board-meeting time is known, the filing is quarantined (`PERIOD/NO_VISIBILITY`).
- Every PIT query filters `visible_from_ts <= :as_of` and reads only each filing's latest `parser_version` (`fundamentals.CURRENT_VERSION`), so a re-parse that moves a filing's visibility later leaves no early row. The "current view" then picks, for each (entity, scope, tag, period), the row with the latest `visible_from_ts`.
- `restage --category RESULTS_XBRL --visibility` re-parses promoted filings whose rule now gives a later time; `backfill-listing-evidence` stages `raw_results_listing` from vaulted listings first.
- Precedence for 12-month periods: a Reg. 34 annual fact supersedes the Reg. 33 FY fact **only from its own `visible_from_ts`**.

### 6.4 Scope continuity

**Default scope per company (Mandate 3, C18).** `fundamentals.resolve_scope` returns one `ScopeDecision` per company and
as-of: the default quarterly scope (consolidated if the latest quarterly filing has a consolidated version, else
standalone), a complete fallback scope, an H1/FY bridge, or balance-sheet-only, never a mix. `scope_reason` records
which. `default_annual_scope` (same rule on FY filings) drives annual statements. A manual override
(`python -m financials scope-override --entity … --quarterly … --annual … --reason …`, or `--clear`) pins both and is
audited.

- TTM uses CONSOLIDATED only when all 4 trailing quarters exist in CONSOLIDATED; otherwise STANDALONE.
- YoY on TTM needs **8** consecutive same-scope quarters.
- A ratio never mixes scopes. Every row exposes `scope_used`.

### 6.5 Half-yearly statements
Balance sheet and cash flow come only from H1/FY filings [X12, X13, X22]. In Q2/Q3: TTM CFO = H1_curr + FY_prev − H1_prev. In Q4: FY. Q1 carries forward the last value. Every derived ratio exposes `bs_as_of` and `cf_as_of`.

## 7. XBRL parsing rules

1. **Route by namespace** of `in-capmkt-ent` [X1]. An unknown namespace or taxonomy version → quarantine `PARSE/UNKNOWN_TAXONOMY`. Never guess the profile from the company.
2. **Identity:** resolve the entity from the in-file `ISIN`/`Symbol`/`ScripCode` [X7] against `security_identifier_history` as of the period end. Any mismatch with the filing's listing metadata → quarantine.
3. **Units:** values are absolute rupees [X4]. Identity tolerance = `n_terms × 0.5 × rounding_unit`, where `rounding_unit` comes from `LevelOfRounding` (Rupees 1, Thousands 1e3, Lakhs 1e5, Millions 1e6, Crores 1e7). Never use `decimals` [X5].
4. **Period reconciliation:**
   - Compare each context family's dates against the declared `DateOfStart/EndOfReportingPeriod` facts and the FY start.
   - On conflict → quarantine `PERIOD/CONTEXT_CONFLICT`. Star Health Q3 FY25 [X26] is the reference case.
   - A conflict pattern that recurs may get a **named, deterministic known-defect rule**, e.g. `FOURD_DATES_EQUAL_ONED_USE_DECLARED_YTD`. It needs its own fixture and test and is recorded in `quarantine_queue` as `FIXED_BY_RULE`. Rules are code, never inference.
5. **Scope** from `NatureOfReportStandaloneConsolidated` [X6].
6. **Comparatives:** quarterly XBRL has none [X2]. Restated prior-year quarters cannot be machine-read [X3]. Restatement handling (§7.6) is therefore flag-based in v1.
7. **Unknown elements** are kept as filed in `disclosure_facts` (X116; the vault blob holds every fact; parser disc-2 leaves excluded elements, masked values and long text in the vault, X120) and simply not mapped. If a **mapped critical tag** is missing where the profile requires it → quarantine `PARSE/MISSING_CRITICAL`.
8. **Revisions:** a revised filing for the same (entity, scope, period) is a new filing linked by `supersedes_filing_id`. Both stay. PIT picks by `visible_from_ts`.

### 7.5 Named label rules
Some lines exist only as a free-text `Description*` label on a dimensional "Others" or detail member, with the amount in contexts carrying the same member. `indas_corp.LABEL_RULES` fixes, per rule, the axis, the amount element and an anchored label pattern: `LEASE_LIAB_NONCURRENT`, `LEASE_LIAB_CURRENT` [X39] and `EXCISE_DUTY` [X40]. Duration amounts go through the same period reconciliation as every other fact. Canonical facts record `source_element = LABEL:<rule>`. New rules need a real fixture and a test (`tests/test_label_rules.py`); every rule is listed in `docs/tag_registry.yaml`.

### 7.6 Restatement policy (v1)
Flag `restatement_suspected` for an entity-period when any of these hold:
- `ProfitLossFromDiscontinuedOperations* ≠ 0`;
- a DEMERGER or MERGER corp action falls within the last 5 quarters;
- a later annual (Reg. 34) prior-year figure differs from the stored as-reported FY figure by more than the tolerance.

Built (2026-11-15): the YTD identity break [X106], discontinued operations in the last 5 quarter ends [X108] and a
MERGER / DEMERGER ledger action with ex-date in the last 5 quarters [X109] set the flag (`FactBook.restatement_triggers`).
The Reg. 34 comparison runs at promotion and raises CONSISTENCY / ANNUAL_PRIOR_YEAR_DIFFERS [X110]; it is a finding,
not yet a flag input, classed SCALE / RESTATED / REGROUPED for triage [X182]. Because the outcome at promotion depends on
what was promoted before, `audit-annual` re-runs it and the annual share-count check on the stored data [X180].

YoY growth across a flagged boundary is set to NULL in screens (with a reason). The PDF anchor-locking extractor from the original blueprint is **deferred**. If built, it must prove its numbers against the same filing's XBRL `OneD`/`FourD` before any row is promoted.

## 8. Canonical building blocks (defined once; every ratio uses these)

Element names are VERIFIED in the INDAS_CORP fixture unless marked otherwise.

| Block | Definition |
|---|---|
| `rev_ops` | `RevenueFromOperations − excise_duty`, where `excise_duty` comes from the `EXCISE_DUTY` label rule (there is no `ExciseDuty` element [X40]); no excise label = 0 |
| `cogs` | `CostOfMaterialsConsumed + PurchasesOfStockInTrade + ChangesInInventoriesOfFinishedGoodsWorkInProgressAndStockInTrade` (inventory change is expense-signed [X11]) |
| `gross_profit` | `rev_ops − cogs`, only for `INDAS_CORP` with `(CostOfMaterialsConsumed + PurchasesOfStockInTrade) ≥ 0.10 × rev_ops`; otherwise NULL [C6] |
| `ebitda` | `ProfitBeforeExceptionalItemsAndTax + FinanceCosts + DepreciationDepletionAndAmortisationExpense − OtherIncome`. Avoids the exceptional-items sign [X9, X10]. For consolidated filings, where share of associates sits relative to PBEIT is UNVERIFIED [X29]. |
| `ebit` | `ebitda − DepreciationDepletionAndAmortisationExpense` |
| `etr` | `clamp(TaxExpense / ProfitBeforeTax, 0, 0.50)` if PBT > 0 and tax ≥ 0; else 0 [C5] |
| `nopat` | `ebit × (1 − etr)` |
| `total_debt` | `BorrowingsNoncurrent + BorrowingsCurrent + lease_liabilities_noncurrent + lease_liabilities_current`; leases come from the `LEASE_LIAB_*` label rules [X39] and are added exactly once (no label = 0) |
| `cash_liquid` | `CashAndCashEquivalents + BankBalanceOtherThanCashAndCashEquivalents + CurrentInvestments` (+ non-current treasury investments only once annual notes split them [X17]) |
| `net_debt` | `total_debt − cash_liquid` |
| `invested_capital` | `Equity` (incl. NCI on consolidated; tag UNVERIFIED [X29]) `+ total_debt − cash_liquid` |
| `shares_out` | Phase 1: Reg. 31 total shares, cross-checked against `PaidUpValueOfEquityShareCapital / FaceValueOfEquityShareCapital` [X18]; a >1% disagreement → quarantine. Shares are rolled forward across later share-count actions by **dividing** by `eps_factor`. |
| `market_cap` | Σ over the entity's active share classes of `close × shares_out` |
| `ev` | `market_cap + net_debt + minority_interest + preference_capital` (consolidated basis, consistent with `invested_capital`) |
| `capex` | `PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities + PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities` (positive magnitudes [X15]) |
| `fcf` | `CashFlowsFromUsedInOperatingActivities − capex` (H1/FY bridge §6.5) |
| `fcff` | `fcf + InterestPaidClassifiedAsOperatingActivities × (1 − etr) − InterestReceivedClassifiedAsOperatingActivities × (1 − etr)`; classification per filing [X14] |

## 9. Accounting profiles

| Profile | Detected by | Core tags (status) | Notes |
|---|---|---|---|
| `INDAS_CORP` | `IntegratedFinance_IndAS` | §8 (VERIFIED, one standalone Q2) | Consolidated fixture needed |
| `INDAS_NBFC` | `IntegratedFinance_NBFC` | `InterestEarned`, `FeesAndCommissionIncome`, `NetGainOnFairValueChanges`, `FinanceCosts`, `ImpairmentOnFinancialInstruments` (tags VERIFIED [X20]) | Fixture is an investment company; lending behaviour UNVERIFIED |
| `IGAAP_BANK` | `IntegratedFinance_Banking` | [X21] (VERIFIED, Q1) | No BS in Q1 [X22]; CASA not tagged [X23]; CRAR UNVERIFIED [X24] |
| `IRDAI_GENERAL` | `GeneralInsurance` namespace | `GrossPremiumsWritten`, `NetPremiumWritten`, `PremiumEarned`, `NetCommission`, `OperatingExpensesRelatedToInsuranceBusiness` (VERIFIED, legacy) | Context-date defect [X26] |
| `IRDAI_LIFE` | `IntegratedFinance_LI` (2025-01-31) [X33] | premium, actuarial, benefits, surplus, policyholder investments (VERIFIED) | Parser not built; extra `OcurI`/`OprevI` instants |

Financial profiles are archetype `FINANCIAL_LENDING` or `INSURANCE`. For those archetypes, industrial ratios (EBITDA, gross profit, working capital, EV-based) are NULL.

## 10. Ratio catalogue

Notation: `avg(x)` = mean of opening and closing balance; `ttm(x)` = trailing 4 quarters (§6.4–6.5). Any ratio whose denominator is ≤ 0 or NULL is NULL; numerator and denominator are stored alongside it. Phase = when inputs exist.

### 10.1 Industrial (`INDUSTRIAL_SERVICES`, `NEW_GEN_TECH`)

| Ratio | Formula | Phase |
|---|---|---|
| ROCE | `ttm(ebit) / avg(invested_capital + cash_liquid)` | 1 |
| ROE | `ttm(ProfitOrLossAttributableToOwnersOfParent) / avg(EquityAttributableToOwnersOfParent)`; standalone filings fall back to `ProfitLossForPeriod` / `Equity` [X42] | 1 |
| ROIC | `ttm(nopat) / ((opening + closing) / 2 invested_capital)`, NULL without the opening balance sheet [C16] | 1 |
| ROIIC 3Y/5Y | `(nopat_t − nopat_{t−n}) / (IC_t − IC_{t−n})`, FY values | 2 |
| Reinvestment rate | `(capex − depreciation + Δ(working capital)) / nopat`, FY | 2 |
| CROIC | `ttm(fcf) / ((opening + closing) / 2 invested_capital)`, NULL without the opening balance sheet [C16] | 1 |
| Shareholder yield | `(dividends paid + gross buybacks − gross equity issued) / market_cap` | 2 |
| 5Y net dilution | `shares_adj_t / shares_adj_{t−5y} − 1` | 2 |
| Incremental asset turnover | `Δ3y rev_ops / Δ3y net fixed assets` | 2 |
| ROTE | `ttm(PAT) / avg(Equity − Goodwill − OtherIntangibleAssets)` | 1 |
| Sloan accrual | `(PAT − CFO − CFI) / avg(Assets)`, FY | 2 |
| CFO / EBITDA | `cfo / ebitda`, 3Y sum | 2 |
| FCF / PAT | `Σ3y fcf / Σ3y PAT` | 2 |
| Receivables vs sales divergence | `YoY% TradeReceivables − YoY% rev_ops` (H1/FY) | 1 |
| Capex / depreciation | `capex / D&A` (YTD-matched) | 1 |
| CWIP / gross block | `CapitalWorkInProgress / gross PPE` (gross PPE from annual notes) | 2 |
| DOL | `%Δ ebit / %Δ rev_ops` (YoY), only if \|%Δ rev_ops\| ≥ 5% and `ebit_{t−4} > 0` | 1 |
| Gross − EBITDA margin spread | `gross_profit/rev_ops − ebitda/rev_ops` | 1 |
| Working capital intensity | `(Inventories + TradeReceivablesCurrent − TradePayablesCurrent) / ttm(rev_ops)` | 1 |
| Other income / PBT | `ttm(OtherIncome) / ttm(ProfitBeforeTax)` | 1 |
| Net debt / 3Y avg FCF | `net_debt / avg3y(fcf)` | 2 |
| Effective cost of debt | `ttm(FinanceCosts) / avg(total_debt)` (includes lease interest while debt excludes leases [L4], so overstated for lease-heavy firms) | 1 |
| Contingent liabilities / net worth | annual notes | 2 |
| RPT leak % | `(RPT purchases + loans given + royalties paid, outside the group) / rev_ops` of the same annual filing, from `related_party_transactions` [X113, C27]; `rpt_leak_pct` (batch J) | 2 |
| PE | `market_cap / ttm(COALESCE(owners, PAT) − discontinued)`, per filing before TTM [C10] | 1 |
| ROE (continuing), core profit, EPS | C14, C15: `roe_continuing`, `core_profit_ttm`, `eps_ttm`, `eps_continuing_ttm` | 1 |
| PB, EV/EBITDA, EV/Sales, P/CFO | standard, using §8 blocks (PB on owners' equity; EV adds minority interest) | 1 |

### 10.2 Forensic (stored as separate columns, never summed)
- `piotroski_f` (0..9)
- `beneish_m`
- `altman_z_dd` (Z'' = 3.25 + 6.56·X1 + 3.26·X2 + 6.72·X3 + 1.05·X4, with X1 = WC/TA, X2 = retained earnings/TA, X3 = EBIT/TA, X4 = book equity/total liabilities)

All three are NULL for `FINANCIAL_LENDING` and `INSURANCE`; Beneish additionally needs annual data. Phase 2.

### 10.3 Valuation & flow

| Ratio | Formula | Phase |
|---|---|---|
| Unlevered FCF yield | `ttm(fcff) / ev` | 1 |
| Reverse-DCF implied g | solve for g; stored with `wacc_used`, `terminal_g_used`, `horizon_years` | 3 |
| 5Y EV/EBITDA percentile | rank of current vs trailing 20 quarter-end values | 2 |
| Delivery velocity | `avg5d(deliv_qty) / avg20d(deliv_qty)` | 1 |
| Float turnover % | `avg5d(deliv_qty) / free_float_shares × 100` | 2 |
| Quarterly FII+DII absorption | `Δ(FII+DII shares) / median90d(volume)` from Reg. 31 | 2 |
| Institutional absorption (monthly) | needs AMC adapters | 3 |

### 10.4 New-gen tech (archetype `NEW_GEN_TECH`)
- From XBRL: EV/gross profit, ex-cash PE `(market_cap − cash_liquid) / (PAT − OtherIncome × (1 − etr))`, EV/billings `ev / (rev_ops + Δ contract liabilities)` (annual), EV/ESOP-adjusted EBITDA (`AdjustmentsForSharebasedPayments` is tagged in the CF), P/CFO, Rule of 40, net working-capital float, burn multiple, cash runway, ESOP-adjusted FCF.
- From `supplemental_kpis` (`load-kpis FILE`, manual or presentation-sourced): GOV, take rate, contribution margin, NRR, CAC payback.

### 10.1b Cash conversion and operating leverage (industrial, C19)

| Column | Formula | Guard |
|---|---|---|
| `sloan_accrual` | (TTM PAT − CFO − CFI) / avg total assets | opening balance sheet |
| `cfo_to_ebitda` | TTM CFO / TTM EBITDA | EBITDA > 0 |
| `fcf_to_pat` | TTM FCF / TTM PAT | PAT > 0 |
| `working_capital_intensity` | (receivables + inventories − payables) / TTM revenue | latest balance sheet |
| `receivables_sales_divergence` | receivables YoY − revenue YoY | 8 quarters |
| `net_debt_to_fcf` | net debt / TTM FCF | FCF > 0 |
| `cost_of_debt` | TTM finance costs / avg (borrowings + leases) | opening balance sheet |
| `dol` | EBIT YoY / revenue YoY | 8 quarters, \|revenue YoY\| ≥ 5%, EBIT > 0 both years |
| `gross_ebitda_spread` | (gross profit − EBITDA) / revenue | COGS ≥ 10% of revenue |
| `fcff_yield` | FCFF / EV, interest add-back per filing CFO classification | existing |

### 10.5 Lenders (`INDAS_NBFC`, `IGAAP_BANK`)

NBFC columns come from the Division III parser (`parsers/indas_nbfc.py`, X54-X57); bank columns from the RBI-format
parser (`parsers/igaap_bank.py`, X58-X61). Industrial ratios (EBITDA, OPM, ROCE, ROIC, CROIC, D/E, Altman, FCF, EV) are
NULL for both. Bank `sales_ttm` = TTM interest earned (Screener's bank "Revenue", S4). Bank regulatory ratios come from
the standalone book (X60).

**Denominators (C16):** ROE and ROE (continuing) use the latest **closing** owners' equity (Screener's export
formula S22, available from the first balance sheet; Screener's website ROE averages opening and closing equity over
the last FY and is stored separately as `roe_screener`, X227). RoA, NIM proxy, credit cost, **ROIC and CROIC** use **(opening + closing) / 2** over 12
months and stay NULL until the opening balance sheet exists.

| Column | NBFC formula | Bank formula |
|---|---|---|
| `nii_ttm` | TTM `InterestEarned − FinanceCosts` | TTM `InterestEarned − InterestExpended` |
| `ppop_ttm` | TTM net total income − opex = PBEIT + impairment (X55) | TTM `OperatingProfitBeforeProvisionAndContingencies` (= NII + OI − opex, X58) |
| `cost_to_income` | opex / (revenue + other income − finance costs) | `OperatingExpenses / (NII + OtherIncome)` |
| `credit_cost` | TTM impairment / avg(loans) | TTM `ProvisionsOtherThanTaxAndContingencies` / avg(advances) |
| `loans`, `loans_as_of`, `loans_avg_from` | loans, latest BS date, opening date of the average | advances (same fields) |
| `nim_asset_proxy` | TTM NII / avg(total assets) | same |
| `roa` | TTM owners' profit / avg(total assets) | same; filed RoA in `roa_filed` (annualisation varies, X59) |
| `gnpa_pct`, `nnpa_pct`, `pcr` | **NULL**: no NBFC element (X54) | `PercentageOfGrossNpa`, `PercentageOfNpa`, `(GNPA − NNPA) / GNPA` (standalone, latest period) |
| `credit_to_deposit` | — | advances / deposits (latest BS) |
| `cet1_pct`, `at1_pct` | — | `CET1Ratio`, `AdditionalTier1Ratio` (standalone; no total CRAR element) |
| `govt_holding_pct` | — | `PercentageOfShareHeldByGovernmentOfIndia` (PSU marker) |
| `is_lending_nbfc` | C13 | NULL |
| `pb` | market cap / owners' equity | market cap / (Capital + Reserves and surplus) |
| CASA % | — | `supplemental_kpis` (not in XBRL [X23]) |

### 10.6 Insurers (`IRDAI_LIFE`, `IRDAI_GENERAL`, `INDAS_INSURANCE`)

Parsed by `parsers/irdai_insurance.py` (X62-X66). Three accounting bases coexist and are **never compared**:
`insurer_basis` says which one a row uses. Industrial and lender ratios (EBITDA, OPM, ROCE, ROIC, CROIC, D/E, Altman,
FCF, EV, NII, NIM) are NULL for insurers. `sales_ttm` = net premium earned (general), net premium (life) or insurance
revenue (Ind AS 117). P/B = market cap / (share capital + reserves and surplus + application money) for IRDAI formats,
market cap / `Equity` for Ind AS 117.

| Column | IRDAI general | IRDAI life | Ind AS 117 |
|---|---|---|---|
| `net_premium_earned_ttm` | `PremiumEarned` | `NetPremiumIncome` | NULL |
| `insurance_revenue_ttm` | NULL | NULL | `InsuranceRevenue` |
| `claims_ratio` | `IncurredClaims / PremiumEarned` (= filed `IncurredClaimRatio`) | NULL | incurred claims / insurance revenue (gross of reinsurance) |
| `expense_ratio` | (net commission + opex) / `NetPremiumWritten` | `ExpensesOfManagement / GrossPremiumIncome` | NULL |
| `combined_ratio` | claims + expense (= filed `CombinedRatio`, X66) | NULL | (service expenses − net reinsurance) / insurance revenue |
| `solvency_ratio` | filed, times (`SOLVENCY_PERCENT_SCALING`, X65) | same | NULL (no element) |
| `investment_income_ttm` | policyholders' + shareholders' | same | `InvestmentIncome` |
| `persistency_13m`, `_61m` | — | filed `PersistencyRatio13ThMonth`, `…61ThMonth` | — |

`supplemental_kpis` (schema.sql) holds what XBRL lacks: VNB margin, embedded value, APE growth (life), and Batch 7's
new-gen tech KPIs. Each row is point in time (`visible_from_ts` = publication of the source document). Loaded with
`load-kpis FILE` (CSV/JSON, `financials.parsers.kpis`): the file is vaulted, staged and promoted like any batch; rows
with an unknown KPI, the wrong unit, a publication before period end or an unresolvable symbol are quarantined `KPI/…`.
`screener_features` carries `vnb_margin`, `embedded_value`, `ape_growth`, `gov`, `take_rate`, `contribution_margin`,
`nrr`, `cac_payback` (latest period visible at as-of; NULL when none is loaded). Persistency filed in XBRL [X62] wins; a
loaded persistency only fills a NULL. Batch G adds the KPI names `arpu` (INR), `mtu` (COUNT) and `casa_pct` (RATIO, alias
`casa`) and reads the KPI history for TTM GOV, YoY growth and P/EV (§10.7). No fetcher (Phase 3).

### 10.8 New-gen tech (`NEW_GEN_TECH`, C21) and valuation bands (C20)

| Column | Formula | Guard |
|---|---|---|
| `valuation_archetype` | profile-derived; NEW_GEN_TECH by curated list / override | — |
| `ev_to_gross_profit` | EV / TTM gross profit | gross profit exists (COGS ≥ 10%) |
| `ex_cash_pe` | (mcap − liquid cash) / (continuing owners' PAT − OI × (1 − ETR)) | denominator > 0 |
| `ev_to_billings` | EV / (TTM revenue + Δ contract liabilities over 12 months) | labelled contract liabilities, opening BS |
| `ev_to_esop_adj_ebitda` | EV / (EBITDA + ESOP), cash-flow window | ESOP add-back present |
| `price_to_cfo` | mcap / TTM CFO | CFO > 0 |
| `rule_of_40` | revenue YoY + EBITDA margin | 8 quarters |
| `billings_growth_pct` | billings YoY | 8 quarters + contract liabilities 24 months back |
| `neg_working_capital_float_pct` | ((payables + contract liabilities) − (receivables + inventory)) / revenue | latest BS |
| `net_burn_multiple` | −FCF / revenue increase | FCF < 0, revenue up, 8 quarters |
| `cash_runway_months` | liquid cash / (−FCF / 12) | FCF < 0 |
| `esop_adj_fcf`, `liquid_cash` | FCF − ESOP; cash + bank + current investments | — |
| `reverse_dcf_implied_g` | g such that 5-year DCF (WACC 12%, terminal 4%) = EV | FCFF > 0, EV > 0 |
| `pe_percentile`, `ev_ebitda_percentile` | rank vs own prior quarter-end values | ≥ 4 prior quarters |

### 10.8b Zero-drop line items (C24)

Every numeric XBRL line item is a fact: curated tags for the ratio engine, `li_<element>` for every other element,
`oth_<element>__<label>` for amounts on text-labelled "Others"/"Details" members, `asfiled_<element>` for a value a
named rule withholds. `fact_observations.line_item_category` / `parent_subtotal` place each line under its subtotal.
Ratios still read only curated tags; line items are for statements, sub-rows and audits.

### 10.9 Annual-statement ratios (Reg. 34, C23) and Reg. 30 event counts (E3-E7)

| Column | Definition |
|---|---|
| `piotroski_f` | Piotroski F-score 0..9 for the latest 12-month FY in the row's scope; year-end total assets (C23); NULL without a post-cutoff prior FY |
| `beneish_m` | Beneish 8-variable M-score (SG&A proxy = `OtherExpenses`); NULL without a post-cutoff prior FY |
| `capex_to_depreciation`, `cwip_to_gross_block`, `rote`, `rnd_and_royalty_intensity`, `contingent_liabilities_to_net_worth`, `annual_fy_end` | FY ratios from the Reg. 34 notes (PPE schedule X71, notes X73) |
| `order_wins_90d`, `order_value_90d`, `kmp_resignations_90d`, `auditor_resignations_90d`, `fraud_or_default_90d` | Reg. 30 events visible at the as-of and disclosed in the 90 days to it (`corporate_events`) |
| `penalties_90d` | NULL: no penalty / regulatory-action filing observed (UNVERIFIED, E7) |
| `roce_screener`, `debtor_days`, `inventory_turnover`, `working_capital` | Screener export formulas (S22) on our Screener-style statement rows, latest FY; kept beside our own `roce` (operating EBIT over closing capital) |
| `roe_screener` | Screener website ROE (X195, X227): last FY owners' profit × 2 / (opening + closing owners' equity), every profile; NULL unless both balance sheets are filed and positive; kept beside `roe` (TTM, closing equity, C16) |
| `inventory_days`, `days_payable`, `cash_conversion_cycle`, `working_capital_days` | closing balance / (Sales / 365); cycle = debtor + inventory − payable days; working-capital days on (CA − cash − current investments − CL) (S23: matches the website on TCS; CCC does not) |

Revisions (E9, E10): `filing_revisions` links a filing to the one it supersedes (REVISION or byte-identical RESEND);
PIT reads already take the latest version visible at the as-of, so the link is provenance, not a read path.
Linking is order-independent: a promoted filing is linked to the latest earlier-visible filing of the same key, and
the earliest later-visible filing already promoted is linked to it (a reverse-order replay gives the same pairs;
when a middle filing arrives last a non-adjacent pair can also be linked, which "supersedes" allows as transitive).
A later filing for the same key is **not** always the better one: some companies file a "Fourth quarter" and then a
"Yearly" XBRL whose quarter column is mis-dated (X82), so the read path never drops a superseded filing wholesale.

### 10.7 `screener_features` columns in Phase 1

Source of truth: `screener_features` in `schema.sql` (the history view has the same columns); aliases in
`financials.dsl.ALIASES`.

| Status | Columns |
|---|---|
| **Active** (always computed when a bar exists) | `close`, `price_date`, `return_1m/3m/6m/12m` (need 22/64/127/253 bars), `price_to_dma50/200` (50/200 bars), `dist_52w_high` (252 bars), `deliv_avg_5d/20d`, `delivery_velocity`, `in_nifty500` |
| **Price / volume / technicals** (batch B, `features_price.py`; bars counted in stored sessions; adjusted = close, high, low × the accepted `price_factor`s with later ex-dates, volume ÷ the same, never dividends [C2]; every adjusted column NULL while an unresolved gap freezes the series; a window longer than the bars held is NULL, never partial [C9]) | Active now: `return_1d` (2 bars), `return_1w` (6), `volume` (as filed), `volume_1w_avg` / `volume_1m_avg` / `volume_1y_avg` (5 / 21 / 252 adjusted volumes), `high_52w` / `low_52w` / `dist_52w_low` (252 adjusted closes), `high_since_data_start` / `low_since_data_start` (every adjusted close since the first bar ≥ 2024-10-01; **not** all-time highs, which are not possible under C9), `dma50` / `dma200` (50 / 200 adjusted closes) and `dma50_prev` / `dma200_prev` (window ending one bar earlier: 51 / 201 bars), `rsi_14` / `rsi_14_prev` (Wilder: gains and losses averaged over the first 14 changes, then `avg = (avg × 13 + x) / 14`, recursion from the first bar; 15 / 16 bars; 100 with no losses, NULL when flat), `macd` / `macd_prev` (EMA12 − EMA26, EMAs alpha 2/(n+1) seeded by the SMA of their first n closes; 26 / 27 bars), `macd_signal` / `macd_signal_prev` (EMA9 of MACD, same seeding; 34 / 35 bars), `atr_14_pct` (Wilder ATR(14) of adjusted true ranges / adjusted close; restarts after a bar without high or low), `rs_nifty500_3m/6m/12m` (stock return − Nifty 500 price-index return over 63 / 126 / 252 bars, `index_ohlcv` [IDX9]; NULL when the index close is missing on either date), `beta_1y_nifty500` (OLS slope of 252 daily log returns on the index's over the stock's bar dates; NULL if any index close is missing), `turnover_median_20d` (median `turnover_inr`, rupees), `deliv_pct` / `deliv_pct_avg_20d` (`deliv_qty / volume`, today / mean of 20 days), `vwap` (today's `turnover_inr / volume` = `AVG_PRICE` [P16]), `vwap_20d` (20-day traded value / adjusted volume). Raw same-day columns (`volume`, `vwap`, `deliv_pct`, `deliv_pct_avg_20d`, `turnover_median_20d`) are not frozen by a gap. When history exists: `return_3y/5y/7y/10y` (756 / 1,260 / 1,764 / 2,520 bars, cumulative, not annualised; ~Oct 2027 / 2029 / 2031 / 2034). Market level: `market_breadth` (one row per materialised day, universe NIFTY 500 = the day's `in_nifty500` rows): members, % above DMA 50 / 200 (`price_to_dma50/200 > 1` among members with a value), new 52-week highs / lows (`dist_52w_high = 0` / `dist_52w_low = 0`) and their ratio, advances / declines / unchanged (`return_1d`) and their ratio; rewritten inside the materialize transaction from the stored rows (full or incremental) and deleted by `rebuild-market` with the history |
| **Active once the input filing is visible** | `shares` (+`shares_source`), `market_cap`, `promoter_holding_pct`, `promoter_pledge_pct`, `promoter_encumbered_pct`, `fii_holding_pct`, `fpi_holding_pct`, `dii_holding_pct`, `public_holding_pct`, `non_promoter_non_public_pct`, `float_turnover_pct`, `shp_as_of` (Reg. 31; `shares` from NSE Issue Size instead when rule SHARES_REG31_OUTLIER finds the Reg. 31 total the outlier [X221]; `promoter_pct`/`fii_pct`/`dii_pct` kept as deprecated duplicates for saved screens); `fii_dii_qoq_change_pct` and `promoter_holding_change_qoq_pp` (need the filing for the immediately preceding quarter end, both visible; the promoter change is in percentage points, the FII + DII change in fraction points); `dividend_yield_pct` (sum of the accepted cash dividends the total-return index adds, ex-date in the 365 days to as-of, each multiplied by the EPS factor of every later accepted share-count action up to as-of, over the raw close; 0 when none went ex, NULL while the window starts before `MIN_TRADE_DATE` [C9] or an unresolved gap freezes the price series); `total_equity`, `net_debt`, `pb`, `debt_to_equity`, `bs_as_of` (H1/FY balance sheet); `altman_z_dd` (H1/FY BS + TTM EBIT; OtherEquity proxy) |
| **Active once 2 adjacent same-scope quarters exist** | `sales_growth_qoq_pct` (latest quarter's `sales_ttm` line, i.e. revenue net of excise / interest earned for banks / premium for insurers, over the previous quarter's, − 1), `profit_growth_qoq_pct` (same for `COALESCE(owners, PAT)` per filing; NULL when the base ≤ 0). Same scope book as the TTM columns; a missing quarter is NULL, never a longer-gap change |
| **Active once 4 same-scope quarters exist** | `sales_ttm`, `ebitda_ttm`, `pat_ttm`, `pe`, `ev_ebitda`, `enterprise_value`, `opm`, `roe`, `roce`, `roic`, `other_income_to_pbt`; `npm_pct` (`ttm(COALESCE(owners, PAT)) / sales_ttm`); `interest_coverage` (`ttm(PBT + FinanceCosts) / ttm(FinanceCosts)`, NULL when finance costs ≤ 0 and for `FINANCIAL_LENDING` / `INSURANCE`; the filed `InterestServiceCoverageRatio` is not exposed); `dividend_payout_pct` (the `dividend_yield_pct` dividends per share / `eps_ttm`, NULL when EPS ≤ 0); `fcf_ttm`, `croic`, `fcff_yield`, `cf_as_of` via the H1/FY bridge |
| **Active once the same quarter a year earlier exists** | `opm_preceding_year_quarter_pct` (named `opm_last_year_pct` until features `2026.11.15-4A`): quarterly EBITDA / revenue (the §8 definitions on one quarter) of the quarter ending 12 months before `fundamentals_end`; NULL for lenders and insurers. Period P&L family (below): every `*_preceding_year_quarter` column, `sales_growth_yoy_quarter_pct`, `profit_growth_yoy_quarter_pct` (owners), `operating_profit_growth_yoy_quarter_pct` (latest quarter / same quarter last year − 1, NULL when the base ≤ 0) |
| **Period P&L family** (`features_pl`, ratio catalogue Batch 1; each column NULL when its period is not in the row's scope book, never a partial period) | Lines `sales`, `operating_profit` (EBITDA as in `opm`), `other_income`, `depreciation`, `ebit`, `interest` (finance costs), `pbt`, `tax`, `pat` (total), `net_profit` (owners, `COALESCE(owners, PAT)` per filing [X42]), `exceptional_items`, in rupees, for `_latest_quarter`, `_preceding_quarter`, `_preceding_year_quarter` (quarter ending `fundamentals_end`, −3, −12 months; `FactBook.quarter`), `_2quarters_back` / `_3quarters_back` (sales, operating profit, net profit only), `_last_year` / `_preceding_year` (latest 12-month PAT period ≤ `fundamentals_end` and the one 12 months before it: the filed 12-month value, results outranking the annual report [X100], else 4 quarters). `eps_*` (3 quarters, 2 years): the filed basic EPS of exactly that period (never derived by subtraction), × the EPS factor of every accepted share-count action with ex-date after the value became visible, up to as-of; NULL while an unresolved gap freezes the security. `equity_capital_*` (3 quarters): paid-up capital stated in the results. Margins (fractions): `opm_latest_quarter_pct`, `opm_preceding_quarter_pct`, `opm_last_year_pct` (**fiscal year**, Screener's "OPM last year"), `opm_preceding_year_pct`, `npm_*_pct` (owners' profit / sales, 5 periods), `gpm_latest_quarter_pct`, `gpm_last_year_pct`, `gpm_preceding_year_pct` (only where materials + purchases ≥ 10% of sales [C6]). `sales_ttm_1y_back` (FactBook TTM ending 12 months before `fundamentals_end`; on from TTM Dec-2025 ~Feb 2027 except where an FY-end bridge exists). `last_result_date` (IST date the scope's latest quarter-end results were first visible), `last_annual_result_date` (same for the latest FY's 12-month figures): one batched visibility query per day. Operating profit, EBIT, OPM and GPM columns are NULL for lenders and insurers (sales = interest earned for banks, premium for insurers, as `sales_ttm`) |
| **History-gated (NULL until the base fiscal year is in scope [C9], then on by themselves)** | FY CAGR `sales_growth_{3,5,7,10}y_pct`, `profit_growth_*` (owners), `operating_profit_growth_*` (EBITDA): `fundamentals.cagr(..., min_periods_required = 4 × years + 1)` at the latest FY end, so FY25 (filed in the Q4 FY25 Integrated Filing) is a valid base: 3Y from FY28 (~May 2028), 5Y FY30, 7Y FY32, 10Y FY35; `eps_growth_*` on the restated filed FY EPS (same gate); `sales_growth_median_{5,10}y_pct` (median of yearly FY growth, needs years + 1 FYs: FY30 / FY35); `avg_earnings_{5,10}y`, `avg_ebit_{5,10}y` (mean of 5 / 10 FY values: FY29 / FY34). Any missing year or base ≤ 0 → NULL |
| **Row flags** | `book_value_per_share` (owners' equity of the latest H1/FY balance sheet / `shares`; DSL `book value`, while `net worth` is total equity in crore), `is_trade_to_trade` (current series BE or BZ, M6; the ASM/GSM stage itself is G139) |
| **Balance sheet / cash flow / capital allocation** (batch C, `features_bs.py`, ratio catalogue Batches 2-3; features `2026.11.15-6C`) | Latest balance sheet (`bs_as_of`, H1 or FY), rupees, from the Screener-style statement (`statements.balance_sheet`, S10; a line a filed balance sheet omits is nil [C23]): `debt` (borrowings + leases), `equity_capital`, `reserves` (other equity; banks / insurers reserves and surplus), `balance_sheet_total` (DTA netted against DTL), `net_block`, `cwip`, `investments`, `current_assets`, `current_liabilities`, `lease_liabilities`, `inventory`, `trade_receivables`, `trade_payables`, `cash_equivalents`; ratios `current_ratio`, `quick_ratio` ((CA − inventory) / CL), `net_debt_to_equity`, `long_term_debt_to_equity` ((non-current borrowings + leases) / total equity), `earning_power` (TTM EBIT / total assets), `face_value` (latest results filing). Average balances over the 12 months to `bs_as_of` (needs the balance sheet 12 months earlier [C16]): `financial_leverage` (avg total assets / avg owners' equity), `asset_turnover` (TTM sales to `bs_as_of` / avg total assets), and `roa` now also for industrial books (TTM owners' profit to `bs_as_of` / avg total assets; lenders keep their own definition). Reg. 34 notes at the last FY end (NULL until that year's annual report is visible): `gross_block`, `accumulated_depreciation` [X71], `contingent_liabilities` (without commitments), `advance_from_customers` [X73], `exports_pct` (foreign / (domestic + foreign) revenue by geography [X75]). Preceding year = the end of the fiscal year before the last one (the year of `sales_preceding_year`): `debt_`, `net_block_`, `gross_block_`, `cwip_`, `working_capital_preceding_year`, `debt_to_equity_preceding_year`, `roe_preceding_year` (closing owners' equity), `roce_preceding_year` (FY EBIT / closing debt + equity), `roa_preceding_year` (average assets: FY27 first, ~May 2027), `book_value_preceding_year` (owners' equity / Reg. 31 shares at that FY end, today's share basis). Cash flow, filed 12-month values of the last / preceding FY: `cfo_`, `cfi_`, `cff_`, `net_cash_flow_` (after FX, S12), `cash_end_`, `cash_beginning_` (prior FY-end cash, else cash end − net cash flow: FY25's opening equals the filed but out-of-scope Mar-2024 value on TCS), `fcf_` (CFO − PPE − intangibles capex), `cfo_to_ebitda_{last,preceding}_year`. TTM / market: `price_to_fcf` (NULL when FCF ≤ 0), `equity_fcf_yield` (G170, signed), `shareholder_yield` (TTM dividends + `li_payments_to_acquire_or_redeem_entitys_shares` − share issues over the CFO bridge's filed periods, a line a filing omits = nil, / mcap; G316), `buyback_yield`, `net_debt_to_ebitda`, `graham_number` (√(22.5 × `eps_ttm` × `book_value_per_share`), both > 0). Fiscal-year capital allocation: `reinvestment_rate` (FY capex − D&A + Δ non-cash working capital, / NOPAT = EBIT × (1 − ETR clamped 0-50%); G216), `incremental_roic_1y` (ΔNOPAT / Δ invested capital, NULL when ΔIC ≤ 0). Shares: `shares_preceding_year` (Reg. 31 total of the pattern exactly 12 months before the latest, ÷ later EPS factors), `dilution_1y` (now / a year earlier − 1; Reg. 31 only, paid-up capital in rounded crore would fake dilution). History-gated [C9] (NULL until the year or date is in scope, then on by themselves): `debt_`, `net_block_`, `working_capital_{3,5,7,10}y_back`, `cash_{3,5,7}y_back`, `book_value_{3,5,10}y_back`, `inventory_turnover_{3,5,7,10}y_back`, `debtor_days_{3,5}y_back`, `exports_pct_{3,5}y_back` (last FY end − N years: FY28 ~May 2028 for 3Y), `fcf_`, `cfo_`, `cfi_{3,5,7,10}y` (sums over N FYs: FY27 ~May 2027 for 3Y), `fcf_conversion_3y` (G224), `cfo_to_ebitda_3y` (G223), `net_debt_to_fcf_3y` (net debt / mean 3-FY FCF, G233), `avg_debtor_days_3y`, `avg_working_capital_days_3y` (FY27), `incremental_roic_{3,5}y` (G215: FY28 / FY30), `shares_10y_back`, `dilution_5y` (G219, ~Apr 2030), `ev_ebitda_percentile_20q` (G240: rank among the last 20 prior quarter-ends, all > 0; `_valuation_history` now returns quarters oldest first; ~2031). Lenders and insurers keep only the capital, total, cash, contingent-liability, face-value, share-count, per-share book value, cash-flow statement and payout-yield columns (`features_bs.LENDER_COLUMNS`); every other column of the family is NULL (`NOT_FOR_LENDERS`). Not built: preference capital, secured / unsecured loans (NEEDS PARSER: no mapped element, catalogue A6.2 / A6.4) |
| **Ownership and hidden gems** (batch D, `features_gems.py`, docs/hidden_gems.md; fractions; industrial signals NULL for lenders and insurers) | Reg. 31 (two batched reads: category totals of the five latest visible patterns, member line items of the latest): `fii_holding_change_qoq_pct`, `dii_holding_change_qoq_pct`, `mf_holding_change_qoq_pct` (fraction points, only between the latest and the immediately preceding quarter end, as the promoter change), `inst_holding_pct` (FII + DII), `unpledged_promoter_holding_pct` (promoter × (1 − pledge share); 0 without a promoter group), `mf_holding_pct`, `insurance_holding_pct` and `retail_holding_pct` (category-member line items, `InsuranceCompaniesMember` / resident individuals up to Rs 2 lakh, scaled by SHP18 [SHP19]), `num_shareholders` (TOTAL holders), `num_shareholders_preceding_quarter`, `num_shareholders_change_qoq_pct`, `num_shareholders_1y_back` (pattern exactly 12 months earlier). Signals from the row's scope book: `core_profit_latest_quarter` (PBT − other income − exceptional items; absent exceptional line = 0), `core_profit_yoy_latest_q` / `_preceding_q` (vs the same quarter a year earlier; NULL when a quarter is missing or the base ≤ 0), `sales_growth_yoy_preceding_quarter_pct`, `profit_growth_yoy_preceding_quarter_pct` (quarter 15 months back), `other_income_lift_pp` (owners' profit YoY − core YoY), `pe_core` (market cap / (TTM core pre-tax × (1 − TTM effective tax rate, clipped 0-50% as NOPAT) × owners' share of TTM PAT); NULL when ≤ 0), `growth_sustained` (both quarters' sales YoY ≥ 12%), `growth_acceleration_pp`, `opm_change_yoy_pp`, `operating_leverage` (core YoY / sales YoY, sales YoY > 0), `peg` (pe_core / (100 × core growth): the latest quarter's YoY until 8 quarters are in scope, then TTM-on-TTM, ~Feb 2027), `earnings_yield` (TTM EBIT / EV, EV > 0). Flags: `industry` (Nifty 500 list industry from the latest snapshot on or before the as-of that lists the ISIN; identifier history valid at the as-of), `cyclical_flag` (Metals & Mining, Oil Gas & Consumable Fuels, or `reference/cyclical_symbols.csv`: shipping), `under_owned`, `forensic_clean` (TRUE unless a measured red flag fails: lift ≥ 8 pp, X106 restatement, Beneish ≥ −1.78, pledge ≥ 5%, auditor resignation / fraud event in 90 days, other income ≥ 30% of PBT for industrials, a modified annual / quarterly audit opinion or a going-concern material uncertainty [X121-X124, 20A]; NULL without fundamentals), `cash_conversion_ok`, `capex_pay_off_signal`. Cross-section of the day (`features_gems.cross_section`; recomputed from the stored day inside the materialize transaction by `refresh_cross_section`, so an incremental run ranks against the same universe as a full one): `magic_formula_rank` (EY rank + ROCE rank within the forensic-clean non-financial universe, ties by EY rank then symbol), `pe_core_universe_median`, `market_cap_universe_median`, `gem_score` (weighted clipped z-scores, non-cyclical universe), `hat_*` (11 screens of hidden_gems.md section B; each equals its saved screen in `reference/saved_screens.csv`, DSL `screen --saved NAME`), `hats_passed`. History-gated: `roce_stability_5y`, `opm_stability_5y` (5 in-scope FYs: FY25-FY29, ~May 2029), `pe_vs_own_5y_median` (stored daily PE from 2024-10-01: 2029-10) |
| **Industry / peers** (batch H, `features_peers.py`, C25; features `2026.11.15-8H`) | NSE classification read point in time (`nse_macro_sector`, `nse_sector`, `nse_industry`, `nse_basic_industry`; NULL before the company's first `fetch-classification`). Cross-section of the day's materialised companies (one value per company, its largest-market-cap security; recomputed over the stored day by `features_peers.refresh_cross_section` like batch D): `{industry,basic_industry}_{pe,pb,roce,sales_growth}_median` (>= 3 company values; PE / PB > 0 only), `{pe,pb}_premium_to_{industry,basic_industry}` (own / median - 1, G199), `peer_count` and `peer_rank_{market_cap,pe,roce,profit_growth}` within the basic industry (G112). Fallback over the Nifty 500 file's `industry` (20 groups) in separately named `industry_group_{pe,pb,roce,sales_growth}_median`, `{pe,pb}_premium_to_industry_group`, never mixed with the NSE levels |
| **Active once 8 quarters exist** | `sales_growth_yoy`, `profit_growth_yoy` |
| **Remaining Phase 2 ratios** (batch G, `features_extra.py`; features `2026.11.15-8G`; fractions, `_pp` = fraction points, money in rupees; industrial cost / margin / cash-conversion ratios NULL for lenders and insurers, `INDUSTRIAL_ONLY`) | Margin deltas from the row's scope book: `opm_acceleration_pp` (G152: [OPM(Q) − OPM(Q−4)] − [OPM(Q−1) − OPM(Q−5)], quarter OPM as `opm_latest_quarter_pct`), `gpm_change_yoy_pp` (G257: quarter GPM − the same quarter a year earlier, both under C6), `profit_growth_acceleration_pp` (owners' profit YoY latest − preceding quarter), `sales_growth_streak_quarters` / `profit_growth_streak_quarters` (consecutive quarters with YoY > 0, newest first, max 8; today ≤ 3 because Dec-2024 is out of scope). Cost shares of sales (G133, G258; latest quarter and last FY): `material_cost_*` (materials + purchases + Δ inventories), `employee_cost_*`, `other_expenses_*`, `power_fuel_*`, `freight_*` [X50], `ad_promo_*` [X68] (labelled lines in the quarterly filing, elements in Reg. 34 [X74]; absent label = NULL, never 0); `marketing_efficiency_latest_quarter` / `_last_year` (G256: sales change vs a year earlier / A&P of the earlier period). FY lines `material_cost_`, `employee_cost_`, `minority_share_` (`pat_nci`), `dividends_paid_{last,preceding}_year`. Perimeter (G276): `acquisition_outflow_{last,preceding}_year` (`CashFlowsUsedInObtainingControlOfSubsidiariesOrOtherBusinesses…`, nil when the FY cash flow is filed without it), `acquisition_outflow_to_sales_last_year`, `inorganic_growth_flag` ([C26]: ≥ 5% of the year's sales in either of the two FYs behind the last FY growth rate; three-valued; Reg. 30 acquisition events are not parsed). `standalone_pat_ttm`, `profit_leakage_pct` / `_latest_quarter_pct` (G278: 1 − consolidated owners' profit / standalone PAT, same end, standalone PAT > 0; the other scope book is read from the day's fundamentals prefetch). Earnings quality on the 12-month cash-flow window (`cf_as_of`, C19): `cfo_to_pat`, `cash_tax_rate`, `capex_intensity`; TTM `effective_tax_rate` (not clamped), `exceptional_to_pbt`, `exceptional_quarters_4q`; `net_cash_to_market_cap`, `rpt_to_sales` (RPT total / same-period sales; the per-counterparty split of G236 is not parsed), `intangibles_to_equity`. Reg. 34 notes at the last FY end: `audit_fees_to_sales` (a filed 0 = rounded to nil → NULL), `managerial_remuneration_to_pat`, `capital_commitments_to_net_worth`, `unquoted_investments`, `quoted_investments_market_value`, `revaluation_reserve`. Valuation: `price_to_sales`, `ev_to_sales`, `price_to_embedded_value` (G270), and from `supplemental_kpis` history (one batched read): `gov_ttm` (12-month period or 4 consecutive quarters) and `ev_to_gov` (G265), `gov_`, `arpu_`, `mtu_growth_yoy_pct` (latest period vs the same-length period 12 months earlier; G266), `arpu`, `mtu`, `contribution_margin_change_yoy_pp`, `casa_pct` (banks, M4; KPI names `arpu` INR, `mtu` COUNT, `casa_pct` RATIO alias `casa`). Flow: `inst_shares_change_qoq` (FII + DII shares, adjacent quarter ends), `volume_median_90d`, `institutional_absorption_90d` (G241: the change / median daily volume of the 90 calendar days to as-of, in days; NULL after a share-count action since the earlier pattern), `promoter_pledge_change_qoq_pp` (B7.4), `public_holders_above_1pct`. Reg. 30 (G117): `litigations_90d`, `allotments_90d`, `fund_raising_events_90d` and the red-flag booleans `rf_auditor_resignation_90d`, `rf_kmp_resignations_90d` (≥ 2), `rf_fraud_or_default_90d`, `rf_litigation_90d`, `rf_audit_qualified` (the latest annual report text or results audit opinion is modified [X121-X124]; `features_audit.modified_opinion`), `rf_pledge_increase_qoq`: separate columns, never summed (§10.2). Raw inputs (G244): `{pe,roe,roce,ev_ebitda,opm}_{numerator,denominator}` (rupees; exactly what the ratio divides). History-gated: `incremental_asset_turnover_3y` (G220: Δ FY sales / Δ net block over 3 FYs, FY28 ~May 2028). View `capital_allocation_scorecard` (G201; created after the column upgrade, below `VIEWS_MARKER` in schema.sql): ROIC, incremental ROIC 1/3/5Y, reinvestment rate, capex / D&A, capex intensity, CFO / EBITDA, FCF conversion 3Y, payout, buyback and shareholder yield, dilution 1Y / 5Y, net debt / EBITDA and the acquisition columns side by side, never one score |
| **Last catalogue rows** (batch I, `features_more.py`; features `2026.11.15-11I`; fractions, days as DOUBLE; forensic / days columns NULL for lenders and insurers) | Forensic inputs on the latest FY vs the one before (the same years as `piotroski_f` / `beneish_m`, which `fundamentals.annual_ratios` fills for industrial books once both FYs are filed): `beneish_dsri`, `_gmi`, `_aqi`, `_sgi`, `_depi`, `_sgai`, `_lvgi`, `_tata` (`fundamentals.beneish_components`, all or none) and the nine BOOLEAN tests `piotroski_roa_positive`, `_cfo_positive`, `_roa_up`, `_cfo_above_pat`, `_leverage_down`, `_current_ratio_up`, `_no_dilution`, `_gross_margin_up`, `_asset_turnover_up` (`fundamentals.piotroski_signals`); `altman_z_original` (1.2 WC/TA + 1.4 RE/TA + 3.3 EBIT/TA + 0.6 market cap/TL + sales/TA on the Z'' inputs; manufacturers only = the C6 guard); `bs_accruals` (Δ NOA / avg total assets, NOA = `invested_capital_at`); `depreciation_rate` (FY D&A / avg gross block), `asset_age_proxy` (accumulated depreciation / gross block); `debtor_days_change_yoy`, `ccc_change_yoy` (FY days, Screener convention); half-year `h1_bs_as_of`, `debtor_days_h1`, `inventory_days_h1` (H1 sales / COGS × 2) and their `_change_yoy`. Valuation percentiles `pb_percentile`, `price_to_sales_percentile`, `ev_to_sales_percentile` (own prior quarter-ends, ≥ 4 [C20]). Price (adjusted closes, frozen rule, one batched read of 450 calendar days of bars): `momentum_12m_1m`, `volatility_1y` (std of 252 log returns × √252), `max_drawdown_1y`, `high_52w_on_delivery_spike` (252-bar high and delivery > 2 × the median of the previous 20 bars); PEAD on the latest results broadcast (`last_result_date`): `pead_event_date`, `pead_ar_t0/1/5/20` (stock − Nifty 500 return from the pre-event close; NULL without both index closes), `pead_relvol_t0/1/5/20` (volume / mean of the 20 bars before T+0). Events: `nifty500_inclusion_90d`, `nifty500_exclusion_90d` (NULL until stored index history covers 90 days; first snapshot and backfill→snapshot hand-overs are not events), `dividend_365d`, `bonus_365d`, `split_365d` (NULL while the window starts before C9), `days_to_next_ex_date`, `next_ex_date_action` (announced actions whose listing is visible at the as-of; retired actions never count). Segments (`segment_observations`, point in time like `load_segments`, row scope, BUSINESS SEGMENT members): `segment_period_end`, `segment_count`, `largest_segment_revenue_share`, `fastest_growing_segment` (+ `_growth_yoy`, matched by filed label), `largest_segment_margin_change_yoy_pp`. Cross-section (refresh step after the day's rows are written, like batches D / H): `rs_rank_12m_1m` (share of the day's other rows with lower 12M−1M momentum), `industry_earnings_breadth` (+ `_n`: share of the NSE industry's companies reporting its latest quarter with core profit YoY > 0, ≥ 3 companies) |
| **Related-party leak** (batch J, `features_rpt.py`, C27; features `2026.11.15-12J`; fractions) | From `related_party_transactions` [X113], point in time (latest visible annual filing per entity, scope and FY end), the row's scope else the other (consolidated first); numerator and denominators from the same filing and FY; SUBSIDIARY rows excluded (outside the consolidated group = every other category): `rpt_fy_end`, `rpt_counterparties`, `rpt_leak_pct` ((purchases + loans given + royalties paid) / revenue from operations, G236), `rpt_purchases_to_sales`, `rpt_royalty_to_sales` (a floor: royalties in the catch-all expense with a "refer below" nature text are not counted), `rpt_loans_given_to_net_worth` (/ total equity at the FY end). Filed nil = 0, no schedule = NULL |
| **Disclosure columns** (18D, `features_disclosures.py`, C28; features `2026.11.16-18D`; fractions) | From `disclosure_facts` [X116], point in time, NULL when not filed. Insider receivables (X117; latest visible annual filing per entity, scope and FY end, the row's scope else the other): `insider_receivables_as_of`, `insider_receivables` (due by directors + other officers + the firms / companies subtotal; never `...OrOthers`, which includes third parties), `insider_receivables_to_receivables` (/ trade receivables of the same filing and instant), `has_insider_receivables`. Reg. 31 declarations of the latest visible shareholding filing (X118; DAILY columns): `has_warrants`, `has_convertibles`, `has_partly_paid`, `has_locked_in`, `has_dvr_shares`, `has_sbo`, `is_psu` (entity-level element; else the OR of the category variants). Schedule III subsidiary contribution (X119; latest visible consolidated annual): `subsidiary_fy_end`, `parent_profit_share`, `largest_subsidiary_profit_share`, `largest_subsidiary_name` (/ the filing's consolidated PAT; adjustment and NCI rows excluded by name / type), `consolidated_entities_count`. Not used by `forensic_clean` or a hat |
| **Audit opinions** (20A, `features_audit.py`; features `2026.11.17-20A`) | From `audit_opinions` [X121-X124] (one row per results / annual filing and `audit-1`, promoted with the filing; `backfill-audit-opinions` parses vaulted blobs in a process pool, verifies the report text against the disclosure_facts pointer's sha256 and inserts once), point in time, NULL when not filed. Annual (the auditor's report text, never the checkbox): per entity the scopes of the latest fiscal year end, each from its latest visible filing: `audit_opinion` (most severe of UNMODIFIED / QUALIFIED / ADVERSE / DISCLAIMER), `audit_opinion_fy_end`, `audit_opinion_conflict` (text vs the Reg. 34 checkbox), `going_concern_uncertainty` (entity / group section; component-only sections excluded), `emphasis_of_matter` (informational). Quarterly: the latest visible results filing that states an opinion: `audit_opinion_quarterly`, `audit_opinion_quarter_end`. EVENT columns. `rf_audit_qualified` = either opinion modified; `forensic_clean` fails on it or on `going_concern_uncertainty` |
| Not built (Phase 2+) | Screener's "Price to Quarterly Earning" (definition UNVERIFIED), Reg. 30 penalty amounts (E12), filed ISCR / DSCR (implausible filed values, e.g. Tata Motors CV DSCR −0.0014, need an evidence row first). `fundamentals.cagr(..., min_periods_required)` already returns NULL until history exists [C9] |

## 11. Corporate actions

### 11.1 Factors (applied to history strictly before `ex_date`)

| Action | `price_factor` | `eps_factor` |
|---|---|---|
| Split FV X→Y | Y/X | Y/X |
| Bonus A:B (A new per B held) | B/(A+B) | B/(A+B) |
| Rights A:B at P, cum-rights close C | (B·C + A·P)/((A+B)·C) | same (bonus element) |
| Demerger (parent) | Open_ex / Close_{ex−1} [C3] | 1.0 |
| Merger (acquirer) | 1.0 | 1.0. Holders of the target convert by swap ratio in portfolio backtests (§11.7). |
| Dividend (any size) | 1.0 [C2] | 1.0; goes to the total-return index only |

Volumes before the ex-date are divided by `price_factor` for share-count events. Absolute financials (revenue, PAT, debt) are never multiplied by any factor.

### 11.2 Ingestion and resolution
- Source: the NSE corporate-actions API [P12]. Purposes are parsed by explicit rules only (dividend, bonus `A:B`, face-value split, `Rights A:B @ Premium Rs X/-` with issue price = face value + premium, demerger) [CA4, CA5, CA9]. Anything else is recorded as `UNKNOWN` with status `QUARANTINED`, so the gap auditor freezes adjusted prices.
- Security resolution [CA1, CA2, CA7]: the API ISIN on `ex_date − 1`; if no match, the API symbol, but only for a holder whose ISIN has the same 4-character issuer code (chars 4-7). Otherwise quarantine `STALE_ISIN_OTHER_ISSUER` / `UNKNOWN_ISIN`. Re-promoting the same file later records actions whose security has appeared since.
- Action ids are deterministic (`ISIN, ex_date, subject, component`), so re-promotion is idempotent.

### 11.3 Verification (per security and ex-date, as a group)
`observed_gap = Open_ex / Close_{ex−1}` from unadjusted `ohlcv` (exchange `PrvsClsgPric` is unadjusted and useless here [P2]). All actions of one security on one ex-date are judged on their **combined** factor (NAZARA split + bonus = 0.25) [CA5].

| Condition | Status |
|---|---|
| any member unfactorable (UNKNOWN, bad ratio) | all `QUARANTINED` |
| a DEMERGER in the group | all `VERIFIED`; demerger factor = observed / product of the others |
| \|combined − 1\| < 0.10 | `UNOBSERVABLE` (dividends, small rights; accepted, flagged) |
| \|observed_gap / combined − 1\| ≤ 0.10 | `VERIFIED` |
| otherwise | `QUARANTINED` |

### 11.4 Unconditional gap auditor [C4]
Every security, every trading day: if the residual gap after dividing out the day's accepted price factors, \|Open_t / (Close_{t−1} · ΠF) − 1\|, exceeds 10% (so a dividend never explains a gap), or the ISIN changed versus t−1 without an accepted SPLIT/CONSOLIDATION:
- quarantine `GAP`;
- raw and `ohlcv` rows are still stored;
- the **adjusted** series and price-derived features for that security are frozen at t−1 until resolved.

Named rules close findings that are not missing actions: CA12 (equity market moves ≤ 20%), CA13 (ETF unit splits / re-ISINs), X140 (rights entitlements: ISIN type `20`, symbol `-RE[n]`; no share-count event ever applies). Expected volume is 0–7 per day [P4]. When an action verifies later, matching gap quarantines are resolved (`FIXED_BY_RULE`) only after re-auditing the residual. The auditor compares consecutive *stored* bars, so promote every trading day: a gap of months between bars (as in the test fixtures) quarantines most of the market.

### 11.5 Total return
`financials.returns.total_return_index`: r_t = (close_t + accepted cash dividends_t) / (close_{t−1} · F_t) − 1. Adjusted prices never include dividends [C2]. Both series stop at the first unresolved gap.

### 11.6 Index membership backfill (before the first snapshot)
`financials backfill-index --manifest reference/nifty500_changes.csv` (`financials.admin.backfill_index`, one transaction):
- Starts from the membership resolved at the **first** `SNAPSHOT` date and walks **backward** through manifest events (`effective_date, action, symbol, kind, source`) to `MIN_TRADE_DATE`.
- An ADD at E is reverted (must be a member); a REMOVE at E is restored (must not be). Symbols resolve on E (ADD) or E − 1 (REMOVE) through `security_identifier_history`, which handles renames such as AKZOINDIA → JSWDULUX [IDX6].
- After every event date the real-member count must equal `expected_count` (500) plus active `TEMPORARY` members (listed spin-offs held between dummy inclusion and exclusion). Membership is constant between events, so this checks every trading day.
- Any unresolved symbol, inconsistent event or count break aborts and writes nothing. On success `MANUAL_BACKFILL` rows `[from, min(to, first snapshot))` replace earlier backfill rows, so the operation is idempotent.
- Prerequisites: price history (bhavcopy days) covering the event dates, and a complete first snapshot. The fixture snapshot resolves 497/500, so the backfill correctly refuses [IDX7].
- Manifest: `reference/nifty500_changes.csv` is generated by `financials extract-index-changes` from the committed notices, and a test asserts it equals the extraction. Prose-only demerger notices (dummies) are **not** extracted; add `TEMPORARY` rows by hand when a backtest needs those days exact.

### 11.7 Corporate lineage: mergers and demergers (G37, G51, G56-G58)
`entity_lineage` (schema.sql) is a directed, append-only edge list read as "child RELATION parent":
`MERGED_INTO` / `AMALGAMATED` (the child is the target, the parent the acquirer) and `DEMERGED_FROM` (the child is
the resulting company). Columns: `effective_date` (the ex-date: first day the holders hold the new shares),
`swap_ratio_num:den` (shares received per shares held; NULL = not verified), `coa_pct` / `parent_coa_pct` (demerger
cost-of-acquisition split), `evidence_filing_id`, `evidence_url`, `source`, `note`. Ids are `stable_id` over the content;
a correction (`amend`, `coa`) or withdrawal (`retire`, state `RETIRED`) is a new row naming the row it supersedes, and
the current edges are the ACTIVE rows nothing supersedes (`lineage.current_edges`).

- **Single writer, audited** (`financials.admin`, one transaction each, `admin_log` + `company_overrides`):
  `lineage add --parent --child --relation --effective --ratio A:B --evidence-url --note`, `lineage amend --id
  --ratio` (ratio of a current edge), `lineage coa --parent --effective --parent-pct P --child C=PCT ...` (every child
  of the scheme at once), `lineage retire --id`, `lineage load --manifest reference/entity_lineage.csv`, `lineage list`.
  Parent and child are an entity id, an ISIN or an NSE symbol naming exactly one entity in the identifier history.
- **Sources** [CA14]: demergers from `reference/entity_lineage.csv`, whose rows a test pins to committed fixtures
  (today one: TMCV `DEMERGED_FROM` TMPV, ex 2025-10-14, from the NSE Indices dummy notice, the corp-action record and
  the TMCV bhavcopy row). A `DEMERGED_FROM` edge needs the parent's accepted `DEMERGER` action on the effective date
  (its `source_filing_id` becomes the edge's evidence); the manifest skips a row until then. Mergers: the corp-action
  feed carries no merger purpose, so automatic merger parsing is **BLOCKED** pending a fixture (a delisting circular or
  scheme document); they are entered by hand with the evidence URL. Ratios and COA percentages are stored only from an
  admin-supplied source (R7, Tata Motors COA, is UNVERIFIED and not stored).
- **Merger effect (G56, G57)**: the target becomes `entity_master.status = MERGED`, `merged_into = parent`,
  `inactive_date = effective_date`; retiring the edge reactivates it. Lineage never writes `corp_actions`, so the
  acquirer is never back-adjusted (factor 1.0) and the target's history stays as traded (test: both adjusted series
  unchanged). A demerged child stays ACTIVE; the parent's price factor remains the observed gap [C3].
- **COA split (G51)**: parent + children = 100% (±0.01 pp) for a scheme; `lineage coa` refuses any other total, and
  `lineage.coa_split` refuses a stored split above 100% or children that disagree on the parent's share.
- **Backtests (G58)**: `lineage.convert_position(edges, entity, shares, on_date, held_since=None)` (pure) maps a
  position through every event with `held_since < effective_date <= on_date`, in date order (chains): a target's
  shares × swap ratio become acquirer shares with the full cost; a demerger parent keeps its shares and each child
  adds parent shares × entitlement, with the cost split by the COA percentages (`cost_fraction` NULL while the split
  is incomplete). Fractional entitlements are kept (cash in lieu is not modelled). An event without a verified ratio
  raises: a backtest never guesses it.
- Not affected: `corp_actions.related_entity_id` / `coa_pct` stay unwritten (superseded by this table); no feature
  reads lineage yet, so it marks nothing dirty.

## 11.8c Derived quarters in statements

Statement builders read a point-in-time FactBook through `fundamentals.BookAsResult`. A flow not filed for exactly
`(start, end)` is derived as YTD(s0, end) − YTD(s0, start − 1 day): Q4 = FY − 9M for the P&L and H2 = FY − H1 for the
cash flow. The book holds one entity and one scope, so standalone FY − consolidated 9M is never formed, and the derived
value exists only once both filings are visible (visibility = the later broadcast). `FactBook.quarter` and
`ttm_from_ytd` apply the same rule for TTM (`tests/test_q4_derivation.py`; no real 9-month filing is a fixture yet).

## 11.9 Knowledge modes and feature snapshots

`screener_features_history` holds one row per security in the universe per materialised `as_of_date`: a full
daily snapshot, not a change log (read through a view; stored event-sparse, §4.1). `screen --as-of D` reads `as_of_date = D` exactly; a date that was never
materialised returns no rows. Re-materialising a date replaces that date's rows (the inputs stay append-only), and
`rebuild-market` deletes the history from its date before replaying. Unchanged rows are not deduplicated: a screen
on `D` needs the full universe of `D`, and ~2,500 securities × ~530 sessions (2024-10 → 2026-11) is ~1.3 M rows
(what is deduplicated is the storage of the EVENT columns, §4.1: the rows read are the same).

Price inputs are read in one of two knowledge modes (`features._price_inputs`):
- `valid` (default; all materialised history): what the market knew on `D`. A corporate action counts from its
  ex-date and a GAP finding freezes the series until resolved, whenever the resolution happened. A fix of our
  pipeline (an unparsed split, a missed action) is a correction, not new information. Rule resolutions
  (FIXED_BY_RULE) are written at promotion time, so a backfill run today would otherwise freeze every split.
- `system` (`compute_rows(..., knowledge="system")`): what this system had decided by `as_of_ts` (an action counts
  once `decided_at <= as_of_ts`; a finding freezes if created by then and not resolved by then). For auditing what
  the live system showed; never written to history.

## 11.10 Incremental materialisation

A row `(D, security)` depends only on that security's and entity's own inputs: bars, accepted factors and gap
freezes up to `D`, fundamentals / shareholding / Reg. 30 events / KPIs visible at the end of `D` (IST), Nifty 500
membership on `D`, overrides, and its own earlier rows (the PE / EV-EBITDA percentile history, C20). No column compares
securities. So after a change that touches a few entities only their rows need recomputing.

**Dirty markers** (`materialize_dirty`, `financials.dirty`): "rows of entity E on `as_of_date >= from_date` may be
stale" (`entity_id = '*'` = every entity). Only the single writers write them, inside the transaction of the change:

| Writer | Marker |
|---|---|
| `promoter._promote_results_xbrl` (results + Reg. 34 annual, revisions, re-parses) | the filing's entity (and the entity of any earlier version of the filing) from the IST date of the earliest `visible_from_ts` of any version: a re-parse can move visibility later (X83) |
| `promoter._promote_shareholding` | same rule on `shareholding_meta` |
| `promoter._promote_reg30_event`, `promoter._promote_kpis` | the entity from the IST date of `visible_from_ts` |
| `promoter._promote_market_day` | `'*'` from the trade date (new bars move every lookback from that day on) |
| `promoter._attach_delivery` (late delivery file) | the entities of the bars it filled, from the trade date |
| `promote()` around `market_day`, `corp_actions`, `index_snapshot`; `admin._transaction` around every admin operation (quarantine resolution incl. CORP_ACTION / ACCEPT / REJECT / MERGE_SECURITIES, backfill-index, rebuild-market, overrides) | market-state diff: accepted factors (`corp_actions` with status in `ACCEPTED_STATUSES`), open `GAP` findings, announced actions (listing visibility date, retired or not: `days_to_next_ex_date`, batch I), identifier intervals, Nifty 500 intervals, security → entity map are snapshotted before and compared after; each changed row marks its security's entity from the earliest date in the row (ex-date, gap trade date, `valid_from` / `valid_to`). This catches every rule that writes them (verification, CA11–CA13, gap auditor, inactivity closing, manual actions) without a hook per statement |
| `admin._merge_securities` | both entities from the first trade date (prices, identity and, when entities merge, fundamentals move) |
| `admin._set_scope`, `admin._set_archetype` | the entity from the first trade date (overrides apply at every as-of) |
| `admin._load_missing_fin_instrm_id_bars` (reprocess) | the bar's entity from its trade date |
| `admin.rebuild_market` | `'*'` from the date (it also deletes the feature history and `features_meta` from there) |

A corporate action changes bars before its ex-date, but `_price_inputs` reads an action only once `ex_date <= D`
(and the share roll-forward only for `count date < ex_date <= D`), so rows before the ex-date never change: the
marker starts at the ex-date. Writes that feed no feature column (raw tables, vault rows, quarantines other than
`GAP`, `segment_observations`, the calendar, `promotion_log`) mark nothing.

**`materialize --incremental [--to D]`** (`features.materialize_incremental`): refuses unless every materialised day
was built by the code's `FEATURES_VERSION` (`features_meta`, written in each day's publish transaction; a day built
before the table existed counts as another version). Then, for every materialised day ≥ the earliest marker
(≤ `D`), ascending so each day's percentile history sees the recomputed earlier days: the entities whose marker
`from_date <= day` (all, if a `'*'` marker applies) are recomputed through the same `compute_rows`, with every batched
read restricted to them (one prefetch per day, never a per-entity query), merged with the day's other stored rows,
gated by G5 (the merged day's securities = the universe) and G4 (null rates of the merged day vs the previous day),
and published atomically (only the recomputed rows are replaced). A failed gate stops the run: that day stays as it
was and every marker stays, so a rerun resumes. After a successful run the consumed markers are deleted, or moved
to `D + 1` when materialised days after `D` exist. A full `materialize --from/--to` consumes the markers whose date
falls in the range (or after the last materialised day before it), provided every materialised day in the range was
rebuilt. Equivalence with a full rebuild, row for row, is pinned by `tests/test_incremental_materialize.py` for a
results filing, a shareholding filing, a corporate-action batch, a gap resolution and a scope override.

**Reader changes**: `FEATURES_VERSION` must be bumped whenever `features.py`, `fundamentals.py`, `scope.py`,
`money.py`, `price_history.py`, `features_store.py` or `reference/valuation_archetypes.csv` changes; a test pins a hash of those files together with the
version. After a bump only a full `materialize --from --to` is equivalent.

An incremental day replaces only the recomputed entities' `features_daily` rows and sets their EVENT values through
the interval store (§4.1); the other securities' intervals are not touched (their EVENT values did not change) and
the cross-section refresh UPDATEs the day's `features_daily` rows of every security, as before.

## 11.11 Run-level materialisation (performance)

A materialised day used to re-read every security's whole bar history (`_price_inputs`, `features_price.load_bars`,
`features_more.load_bars`: up to ~450 days x ~3,000 securities, three times), recompute every indicator from the
first bar, rebuild every entity's fundamentals from a fresh prefetch, and checkpoint the database on every commit:
quadratic in the history, ~3 s a day at the start of the data and 25-35 s at the end (a full rebuild ~2.5 h). A
`materialize --from/--to`, `--incremental` or `rebuild-market` run now shares one run state across its days
(`features.materialize_run`); the rows are the same, row for row and column for column (`FEATURES_VERSION` -14P
only because the pinned files changed).

- **Price history** (`financials.price_history.PriceHistory`): bars (all fields), accepted price factors, open GAP
  freezes and Nifty 500 closes are read once, up to the run's last day; a day sees each security's prefix of bars
  dated <= D. A back-adjusted series depends on D only through the set of accepted actions with ex-date <= D
  ("valid" knowledge, the only mode materialised history uses), so each security's adjusted series and every
  causal indicator over it (RSI, MACD / signal EMAs, ATR restarting after a bar without high / low, running highs /
  lows since data start, daily log returns) is computed once per such set (a *factor regime*) and indexed at D's
  last bar; a GAP freeze only cuts the series at its first frozen bar (every adjusted column is NULL from there).
  Windowed values (returns, 52-week and 1-year windows, beta, drawdown, delivery spike, PEAD, the 450-day window of
  batch I) are computed per day from slices with the same expressions in the same order, so Decimals are equal and
  floats bit-identical. Two windowed sums use prefix sums where that is provably the same value: Decimal sums
  (DMAs, volume averages, the momentum DMA ratios) when every partial sum is exact in the 28-digit context (else
  the window is summed as before), and the 1-year volatility from exact integer sums of the log returns and the
  correctly rounded square root `statistics.stdev` itself uses (falls back to `statistics.stdev` where that
  internal is missing). `features._momentum` multiplies factors in query order, `features_price` in ex-date order:
  both orders are kept. Memory: ~1.5 KB a bar (~2-2.5 GB of Python objects for 3,000 securities x 526 days, plus
  DuckDB's buffers); the run freezes these long-lived objects out of the cyclic garbage collector (`gc.freeze`,
  one collection a day) because full collections over them took more than half of a day's time.
- **Fundamentals cache** (`features.FundamentalsCache`): `_fundamentals(entity, as_of)` reads only rows filtered
  `visible_from_ts <= as_of` (facts, filing_meta, corrections through their filing, result dates), MERGER /
  DEMERGER ledger rows with ex-date <= as_of and static overrides. A run cannot change those tables, so an entity's
  block (scope decision, TTM / annual / lender / insurer ratios, the period values of batches A, C, D, G, I) changes
  only on a day one of its visibility timestamps or structural ex-dates falls on: the block is keyed by (latest
  visible quarter, count of its visibility timestamps <= as_of, count of its structural ex-dates <= as_of) from one
  read per run, and a day prefetches and recomputes only the entities whose key moved. Everything price-, share-
  or day-dependent (market cap, EV, PE / PB / yields, percentiles, shareholding, Reg. 30 windows, KPIs,
  cross-sectional ranks) is still computed every day.
- **Checkpoints**: each day's commit writes ~30 MB of WAL; at DuckDB's default 16 MB threshold every commit
  checkpointed and rewrote the history table's open row groups (3-4 s of a 4-5 s day). The run raises the
  threshold to 512 MB (`RUN_CHECKPOINT_THRESHOLD`), restores it and checkpoints once at the end. Storage only: each
  day is still published atomically after G4 / G5.
- `FINANCIALS_MATERIALIZE_LEGACY=1` selects the per-day path (and `compute_rows(knowledge="system")` always uses
  it). `tests/test_materialize_fast_path.py` pins the equality: every column of the price functions for every prefix
  of randomised series (splits, several inexact factors on one bar, holes, missing index closes, GAP freezes,
  sparse trading), and the materialised tables of the fixture market and of the fixture market extended with long
  synthetic histories (`bench.extend_synthetic`), both paths. `scripts/compare_materialize.py DB --from --to
  [--every N]` runs the same comparison on a copy of a real database.
- **Determinism** (-15P). The first comparison on the live database found rows that differed between the two
  paths and between two runs of the same query. They came from reads whose result depended on DuckDB's scan order,
  shared by both paths: the paid-up share count (`arg_max(value_other, period_end)` tied between the STANDALONE and
  CONSOLIDATED filings of one quarter, 225.4 vs 225.5 million shares; one consolidated filing tagged 0), two
  segment members filed under one label ("Others" twice: the last row scanned won) and audit-opinion ties on
  `visible_from_ts`. Now: the share count of the latest period end, STANDALONE first (the issuer's own capital),
  then latest visible, then filing_id, counts <= 0 ignored; segment rows in a fixed order, members sharing a label
  add up, a member reported by two elements counts once; audit ties broken by filing_id
  (`tests/test_materialize_determinism.py`). Every other read under `_fundamentals` and the period-value stages
  ranks with a full tie-break (filing_id / parser version) or groups by its key.
- **Live table once per run** (-16S, `features.materialize_days`): every day of a run used to delete and rewrite
  `screener_features` with the latest materialised day (the same rows again), leaving the deleted copies as dead
  blocks. Now only the run's last day rewrites it, inside its own publish transaction (`materialize(...,
  snapshot=False)` on the others reports `snapshot_due`); a run that stops early rewrites it from the last
  published day. The tables end identical to the day-by-day publish (`tests/test_storage.py`).
- Not done: parallel day computation. DuckDB lets no other process open the database file while the single writer
  holds it, and the per-day Python work is GIL-bound, so worker processes would need their own copy of every input;
  after the changes above a day of ~3,000 securities is ~1.5-2 s (half per-row Python, half the Arrow insert, the
  cross-section SQL and the WAL), see docs/benchmarks.md section 6.

## 11.12 Market-cap universe (rule U1, owner 2026-11-17) [X130-X134]
- **Source.** `PRddmmyy.zip` (one per trading day, ~0.6 MB) is vaulted whole; only `mcapddmmyyyy.csv` is parsed
  (`parsers/pr_mcap.py`, member name matched case-insensitively). The parser checks the file's own summary rows
  (Listed / Permitted / Total sums, paisa rounding), so a truncated file fails; promotion (`mcap_day`) is
  OUT_OF_SCOPE before 2024-10-01 and G1 needs the EQ / BE / BZ row count >= 0.92 x the median of the previous five
  files. `raw_nse_mcap` keeps every row as sent (all series, symbol / series as printed, Issue Size BIGINT, close and
  market cap DECIMAL); the file has no ISIN.
- **Rule U1** (`financials/universe.py`, `RULE_VERSION`): a day is its ISO week's last trading day when every later
  day of that week is known not to trade (holiday master / CAL3 rows / weekend of a covered year). On it, every
  EQ / BE / BZ row with Category `Listed` or `Permitted` (U1-P; the row's category is kept as
  `universe_membership.listing_category`) and filed Market Cap >= Rs 500 Cr joins (`universe_membership`, MCAP_GE_500CR, visible from the
  file's EOD broadcast time), resolving symbol + series on that date through `security_identifier_history`; an
  unresolved row is quarantined (UNIVERSE / UNRESOLVED_SYMBOL, one finding per symbol / series, closed by rule once it
  joins). Seed, once: EQ / BE / BZ securities with a bar of entities with financials, on their first bar date
  (SEED_EXISTING; hindsight, L1). Members never leave; a backfill that finds an earlier qualifying week moves the
  join date earlier. Each row stands alone: a DVR or other listed class joins only on its own market cap.
- **PIT read**: `joined_date <= as_of` (`universe.members`). `discover-filings --universe mcap500` lists members
  joined by today; `mcap500-new` only those whose entity has no `filing_meta` yet.
- **Backfill** (once): `fetch-days` for the scope, `promote`, `fetch-mcap 2024-10-01 <today> --weekly` (111 zips on
  2026-11-17), `promote`, `update-universe`. Live result (rule U1-2026.11.17-L): 595 seeded + 1,352 joined = 1,947 members;
  the next `update-universe` (U1-P) adds the Permitted joiners and fills `listing_category` (sticky, idempotent).

## 11.13 BSE for Permitted members (owner 2026-11-17) [X165-X169, A16-A18]
- **Who**: `universe.bse_members(as_of)` = members whose latest mcap row is `Permitted` (they file results, annual
  reports and shareholding on BSE, not NSE [X166]); `mcap500-new` NSE discovery skips them. CLI `bse-members` prints
  them with ISIN and BSE scrip code. Identity keys on **ISIN + BSE scrip code**, never on an NSE symbol or NSE bars,
  so a BSE-only company (owner to-do 31) fits the same path once it has identifier rows.
- **Identity, rule BSE1** [X169]: the BSE list of securities (`ListofScripData`, per group: scrip code, ISIN, ticker,
  BSE market cap) is staged `bse_securities` -> `raw_bse_securities` (append-only); promotion fills
  `security_identifier_history.bse_scrip_code` by ISIN on rows valid on the observed date; a different stored code is
  a non-blocking BSE_SCRIP_CODE_CONFLICT. The in-filing ScripCode (G79, X111) keeps working beside it. The BSE
  bhavcopy (UDiFF, FinInstrmId = scrip code [X165]) gives the same map and is reachable from the container; it is
  parsed (`parse_udiff_cm(exchange="BSE")`) but not yet fetched or promoted.
- **Fetching** [A16, A17]: the container is refused by `api.bseindia.com`; BSE is fetched only on GitHub-hosted runners
  with the owner's method, ported as-is (`financials/fetch/bse.py`: BSE's headers, plain requests, 4-6 s apart, 3
  retries on network / 5xx, hard stop on 401/403/429, then in-page XHR in headless Chrome; HTTP 400 ends that call
  only). Workflows: `bse-reach` (probe) and `bse-fetch` (by hand, scrip codes from `bse-members`;
  `scripts/bse_fetch.py`: every group's list of securities, per scrip announcements + `Result` attachments, shareholding
  filings + inline XBRL). The runner writes only a **ledger** (bytes as sent in `blobs/<sha256>` + `ledger.jsonl`)
  uploaded as a 1-day artifact; it never sees the database.
- **Import** (owner's machine): `import-bse DIR` checks every blob against its ledger sha256, vaults it as a `filings`
  row with exchange `BSE` (blob != filing: an NSE and a BSE filing may share one sha256), and stages it; `promote`
  (single writer) promotes. The same ledger format is the owner-provided route (files fetched elsewhere by the same
  client). Parsed: the list of securities (BSE1) and the shareholding inline XBRL: `parsers/ixbrl.py` rebuilds the
  instance it denotes (rule IXBRL1_BOOLEAN_TEXT for BSE's Yes / No tags) and the unchanged shareholding parser reads
  it; the filing resolves by ISIN through the NSE identifier rows of the same security, visible from the listing's
  broadcast `D` [X170]. Announcements and their PDFs stay raw. BSE announcements link no results XBRL (X168): the
  results of Permitted members are PDFs only, so their financial statements are BLOCKED on a source.

## 12. Promoter quality gates (in order)

| Gate | Rule | On failure |
|---|---|---|
| G1 Completeness | EQ/BE/BZ rows ≥ 92% of the trailing 5-trading-day median | Abort batch; keep previous state; retry later |
| G2 Identifier resolution | Every raw price row resolves to a `security_id` via `(exchange, fin_instrm_id \| symbol+series, isin, date)`; unresolved rows ≤ 1% | Every unresolved row carries an identity issue (missing `FinInstrmId`, ISIN collision, out of order, duplicate) and is quarantined `IDENTIFIER/…`; above 1% → abort. `quarantine reprocess` loads a missing-`FinInstrmId` bar by ISIN |
| G3 Accounting identities | Per filing, in the parsers (staged issues): P&L chain (X9 / bank equivalents), `Assets = EquityAndLiabilities` when BS present, expense components sum to `Expenses`; tolerance §7.3 | Quarantine that filing only |
| G4 Null-spike (features) | Null rate of `close`, `market_cap`, `sales_ttm`, `pat_ttm`, `total_equity` rises ≤ 1.5 percentage points vs the previous materialised date. Rule G4_C9_WINDOW: a TTM that turns NULL because the company's latest quarter moved forward and the new 4-quarter window reaches before the financials cutoff (C9) is not counted; on the live backfill this is every company filing Q1–Q3 FY26 (Jul 2025–Jan 2026), until four in-scope quarters exist | Abort; previous features stay live |
| G5 Atomic features | Row count = universe (securities with a bar in the last 15 days and a valid identifier); history rows for the date and the live table replaced in one transaction | No partial state is ever visible |
| ORDER | Market days and index snapshots must arrive in date order | Abort. `promote` holds later market days behind an aborted one, so a day that fails G1 is never overtaken; an older day found later needs `rebuild-market --from D` |
| CAL3 No-session inference | After a market day, its `PrvsClsgPric` vs the previous promoted close: ≥ 99% of ≥ 100 common securities equal → the dates in between had no session (`trading_calendar.source = INFERRED_PREV_CLOSE`) | Otherwise `CALENDAR/MISSING_SESSION` (a session is missing from the database) |
| Delivery | A delivery file for another date than its bhavcopy | `DELIVERY/DELIVERY_DATE_MISMATCH`; the file is vaulted, not joined. A delivery fetched after its bhavcopy fills `deliv_qty` on the promoted bars |
| Inactive securities | Open identifier interval with no bar in the last 20 promoted sessions (CHOICE, ID1) | Closed the day after the last bar; reopens via `FinInstrmId` when it trades again |
| Share cross-check | Reg. 31 total vs results paid-up / face value differ by > 0.5% (skipped for partly-paid issuers) | Quarantine `SHARES/CROSS_CHECK_FAILED`; promotion continues |

## 13. Schedule (local machine, IST)

| When | Job |
|---|---|
| Trading days from 18:30, retry every 30 min until 23:30 | UDiFF bhavcopy + `sec_bhavdata_full` (publish time UNVERIFIED [P11]) |
| Daily | `ind_nifty500list.csv` snapshot → close/open membership intervals on change |
| Results season, every 2 h; otherwise daily | Results XBRL discovery (local, `www.nseindia.com` API) |
| Daily | Corporate-actions API for a rolling window (e.g. last 30 days to next 30 days) |
| Yearly (January) and on change | Holiday master |
| After each quarter's Reg. 31 deadline | Shareholding master + XBRL per symbol in the universe |
| After each fetch batch | Promoter: gates → canonical → corp-action verification → gap auditor → features |
| Monthly, and after an index change | `fetch-classification --universe nifty500` (quote API, 1 request/s, ~9 min) then `promote` [IC1] |
| Daily, inside `run-day` | PR-zip mcap file with each market day; on the week's last trading day rule U1 adds the Rs 500 Cr joiners (§11.12); `discover-filings --universe mcap500-new` then fetches the new members' filings |

**Automation (G40, G60, G289).** `ops/` holds the scheduler files; each runs, every day at 20:15 IST:

1. `python -m financials --data-dir data run-day` (no `--date`: today's IST date). It fetches the holiday list,
   the market days of the lookback window (vaulted days are not fetched again), corporate actions, the RSS-hinted
   filings and Reg. 30 events, promotes everything, catches up dirty rows of earlier days and materialises the day.
   On a holiday or weekend of the promoted calendar (`calendar.is_trading_day` is FALSE) it still fetches and
   promotes (filings and corporate actions arrive on non-trading days) but publishes no feature day. It exits 1 when
   a fetch step reported an error; the next run retries what failed.
2. `python -m financials --data-dir data materialize --incremental`: recomputes the rows marked dirty by that run's
   promotions on already materialised days (§11.10). It runs even when step 1 exited 1.

| File | Scheduler |
|---|---|
| `ops/systemd/financials-daily.service`, `ops/systemd/financials-daily.timer` | systemd user units (`OnCalendar=*-*-* 20:15:00 Asia/Kolkata`, `Persistent=true`): copy to `~/.config/systemd/user/`, `systemctl --user enable --now financials-daily.timer` |
| `ops/cron/financials.cron` | one crontab line (`CRON_TZ=Asia/Kolkata`; 14:45 UTC without CRON_TZ), log to `data/logs/daily.log` |
| `ops/windows/financials-daily.xml` | Windows Task Scheduler (UTF-16): `schtasks /Create /TN "Financials daily" /XML ops\windows\financials-daily.xml`; the PC clock must be IST or the trigger shifted |

Paths assume the checkout at `~/Financials` with a `.venv`; edit them. `tests/test_batch_h_industry_peers.py` checks
that the files call only existing CLI commands. The quarterly sweeps (`discover-filings --universe nifty500`,
`fetch-classification`, `fetch-index`) are not scheduled: the daily run's RSS hint covers new results.

**GitHub Actions nightly (batch K, 22:00 IST = cron `30 16 * * *` UTC).** Two workflows, both also `workflow_dispatch`:

| Workflow | Runner | What it does |
|---|---|---|
| `.github/workflows/nightly-tests.yml` | GitHub-hosted `ubuntu-latest` | the CI checks (ruff check / format, offline pytest) on the default branch every night |
| `.github/workflows/nightly-pipeline.yml` | **self-hosted**, labels `[self-hosted, financials]`, i.e. the owner's own machine | `run-day`, then `fetch-classification --universe nifty500 --missing-only` + `promote` (only entities with no current classification, so not the ~9 min full sweep), then `materialize --incremental` |

The data pipeline cannot run on a GitHub-hosted runner: (1) the market database (~10 GB) and the vault are gitignored
and live only on the owner's disk, and a hosted runner starts empty every time (no persistent disk; re-fetching history
nightly would break the "never re-download a vaulted blob" rule); (2) NSE blocks datacenter IP ranges, and
`www.nseindia.com` needs session cookies from a residential connection; (3) the exchange terms forbid redistribution,
and data in a hosted runner, cache or artifact is data on someone else's servers. So the pipeline workflow is only a
scheduler for the owner's machine: it checks out the code, runs it with `PYTHONPATH=<checkout>/src` and the owner's venv
(`FINANCIALS_VENV`), against `FINANCIALS_DATA_DIR` (both set in the runner's `.env`; the data directory must be outside
the workspace, a step refuses otherwise). It has `permissions: contents: read`, a `concurrency` group without
cancellation (single writer: runs queue, never overlap), a 240 min timeout, and uploads only the run log
(`$RUNNER_TEMP/nightly-log/nightly-pipeline.log`, 14 days). It never commits or uploads data. Use it **instead of** the
`ops/` scheduler, not with it: two schedulers would race for the DuckDB write lock. Registration steps: `ops/README.md`.
`tests/test_nightly_workflows.py` pins the cron, the runner labels, the CLI commands and the no-data rules.

## 14. Screener DSL

```
query      := or_expr
or_expr    := and_expr ( "OR" and_expr )*
and_expr   := not_expr ( "AND" not_expr )*
not_expr   := "NOT" not_expr | comparison | "(" or_expr ")"
comparison := arith ( "<" | "<=" | ">" | ">=" | "=" | "!=" ) arith
arith      := term ( ("+" | "-") term )*
term       := factor ( ("*" | "/") factor )*
factor     := NUMBER | ALIAS | "(" arith ")" | "-" factor
ALIAS      := a name in financials.dsl.ALIASES or user_custom_ratios (case-insensitive, words may end in digits,
              e.g. "Return 12M", "In Nifty 500")
```

- Units follow Screener conventions and are stated per alias: money in INR crore, growth/returns/margins/holdings in percent,
  dates as `YYYYMMDD` integers (`Last result date > 20261001`), flags as 1/0.
- Period P&L aliases use Screener's names: "Sales latest quarter", "Net profit preceding year quarter", "Sales
  2quarters back" (also "2 quarters back"), "OPM last year" (fiscal year; the same-quarter value is "OPM same quarter
  last year"), "Sales growth 3Years", "Sales growth 5Years median", "Average earnings 5Year", "YOY Quarterly sales
  growth", "Last result date".
- Output columns (M1): `screen QUERY --columns "Sales latest quarter, OPM last year, Sales / Market cap"` adds each
  comma-separated arithmetic expression (aliases, saved custom ratios, arithmetic) to every match, labelled by its
  normalised text; `--order-by EXPR [--desc]` sorts (NULLs last, then symbol); `--limit N`. Custom ratios are saved with
  `save-ratio NAME EXPRESSION` (validated by compiling it; built-in names refused) and listed with `ratios`.

- Aliases map **only** to whitelisted `screener_features` columns or saved custom ratios.
- Saved custom ratios are expanded before compilation; cycles are rejected.
- Output is parameterised SQL: numbers become bound parameters, columns come from the registry, and no user text reaches SQL.
- Division compiles to `x / NULLIF(y, 0)`. NULL comparisons are not TRUE, and `NOT` keeps NULL as NULL, so a stock missing a metric never passes a filter on it.
- An unknown alias is a compile error, never a guess.

## 14b. Statement builder: quarterly rows (Mandate 4, first slice)

`financials/statements/quarterly.py` builds Screener-style quarterly rows from **our** definitions. Every row
keeps its sub-rows, so any figure can be traced to XBRL. `tie_out` must return exactly 0, to the rupee:
Revenue − Expenses − Interest − Depreciation + Other Income (+ bank exceptional) = PBT. Divergences from Screener
are reported in `QuarterStatement.divergences`, never imitated. Evidence: S1–S7.

| Row | INDAS_CORP (canonical tags) | Sub-rows |
|---|---|---|
| Sales | `revenue_from_operations − excise_duty` | revenue from operations, less excise |
| Expenses | `total_expenses − depreciation − finance_costs − excise_duty` | materials, stock-in-trade purchases, inventory change, employee cost, other expenses net of excise |
| Operating Profit | Sales − Expenses | — |
| Other Income | `other_income + exceptional_items` [S2] | reported other income, exceptional items |
| Depreciation / Interest / Tax | as reported | tax: current, deferred |
| Profit before tax | `pbt` (associates excluded: `ASSOCIATES_PLACEMENT` [S3]) | before exceptional, exceptional |
| Net Profit | `pat_owners`, else `pat` | continuing PAT, regulatory deferral, discontinued, associates, PAT, less NCI |

Banks, NBFCs, life and general insurers use the raw-element formulas in S4–S7 until their parsers land
(Mandate 2 batches 4–6). They then switch to canonical tags with the same tests. Annual-only sub-rows
(fixed-asset schedule, notes) are NULL on quarterly statements. The Screener export carries only the
Data Sheet rows, so golden parity covers top-level rows only. Sub-rows are checked by summation, not by golden values.

### 14b-1. Expense sub-rows and segments (X49, X50, X97-X99)

Expenses sub-rows add **Power and fuel** and **Freight** when the filer labels them (named label rules). They stay NULL
when it doesn't, and the rest of other expenses absorbs them, so the sub-rows still sum to Expenses.

**Segments are persisted** (owner decision 2026-11-14) in `segment_observations`, one row per member fact:
`axis_kind` (BUSINESS | GEOGRAPHY), `axis`, `member`, `label` and `element` exactly as filed, `member_role` derived from
the member name only (SEGMENT, UNALLOCATED, ELIMINATION, RECONCILING; DOMICILE, FOREIGN_TOTAL, FOREIGN, AREA),
`canonical_metric` derived from the element only (`segments.SEGMENT_METRICS`), periods as in `fact_observations`
(instants store `period_start = period_end`), `value_inr DECIMAL(20,2)`, and the filing's `entity_id`, `scope`,
`parser_version` and `visible_from_ts`. Primary key (filing_id, parser_version, axis, member, element, period_start,
period_end): no nullable key column.
- **Sources.** Quarterly results (every profile that files the four `ReportableSegment*Axis` elements: corporate,
  NBFC, bank, life insurer) and Reg. 34 annual (`EntitySReportableSegmentsAxis`, `GeographicalAreasAxis`). The
  Integrated Filing has no geography axis. Elements no committed fixture shows (e.g. segment tax, capex additions,
  equity-method investments) are not mapped; they reach `disclosure_facts` as filed (X116).
- **How.** `parsers/segments.py` is pure (bytes -> rows + findings) and keeps only facts in the periods the filing's
  own parser validated (`Windows.from_meta`: declared quarter / YTD and period end, or the Reg. 34 in-scope years);
  a declared pre-cutoff year is skipped (C9), any other context outside the declared periods is a finding.
  `stage_results_xbrl` stages `stg_segments` with the filing and the promoter inserts them in the same transaction
  as `fact_observations`. A quarantined or out-of-scope filing promotes none. PARSER_VERSION 0.10.0 restages.
- **Checks (non-blocking findings, stage `SEGMENT`).** SEGMENT_SUM (members vs the filed non-dimensional total,
  within the LevelOfRounding tolerance; with unallocated / elimination members also accepted), SEGMENT_RECONCILING
  (reconciling = unallocated + eliminations), GEOGRAPHY_FOREIGN_SUM (ForeignCountriesMember = its ForeignCountryN
  children), SEGMENT_ASSETS (segment + unallocable = net segment assets). A finding is promoted with the filing and
  opens a quarantine row; it never blocks the filing or corrects a value. Net segment assets vs total assets is a
  warning only.
- **Reader.** `fundamentals.load_segments(con, entity_id, scope, as_of)`: each filing's current parser version,
  `visible_from_ts <= as_of`, and per (axis, element, period) every member of the latest visible filing. Members are
  per-filing ids (`ReportableSegments1Member` may be another business in another filing), so two filings' members are
  never mixed.
- **What is never done with them.** Segment rows never feed `fact_observations`, the factbook, a P&L row, a ratio or a
  screen, and no cross-company segment taxonomy is built: labels are free text. Segment totals are not P&L
  substitutes (Cummins: segment revenue is before inter-segment elimination; segment PBT includes associates).
  Unchanged from C24: labelled quarterly members also appear in `fact_observations` as `oth_segment_*` line items, and
  Reg. 34 domicile / foreign revenue as `revenue_domestic` / `revenue_foreign` [X75].

### 14c. Annual statements and conventions (S10-S15)

**Balance sheet** (`statements/balance_sheet.py`; H1 and FY ends only; Q1/Q3 NULL):

| Row | Definition | Sub-rows |
|---|---|---|
| Equity Capital | `equity_share_capital` | — |
| Reserves | `other_equity` (owners only) | — |
| Borrowings | borrowings (NC + C) + lease liabilities (NC + C, label rule) | the four lines |
| Other Liabilities | Total − Equity Capital − Reserves − Borrowings | NCI, trade payables, other |
| Total | `total_assets − min(DTA, DTL)` when both are positive | deferred tax netted |
| Net Block | PPE + investment property + goodwill + other intangibles + ROU (label rule) | the five lines |
| CWIP | CWIP + intangibles under development | both |
| Investments | non-current + current + equity-method | the three lines |
| Other Assets | Total − Net Block − CWIP − Investments | receivables (current), inventory, cash & bank, other |

**Cash flow** (`statements/cashflow.py`; YTD only, so H1 and FY; Q1/Q3 NULL): CFO as filed = Profit from operations
(cash generated − working-capital changes) + Receivables + Inventory + Payables + Loans & Advances + Other WC items
+ Direct taxes + Other operating items; CFI = fixed assets purchased/sold, interest and dividends received, other;
CFF = borrowings in/out, interest, dividends, leases, shares, other; Net Cash Flow after FX. Groupings are listed in
`WC_GROUPS`. Every "other" row is the residual, so sub-rows always sum to the filed total.

**Conventions**
- Signs: P&L costs positive, as filed. Cash flow positive = cash in. We show Change in Inventory with the XBRL sign;
  Screener reverses it.
- Rounding: we keep rupees (`DECIMAL(20,2)`). Comparisons with Screener use ₹ Cr to 2 dp with ±0.01 tolerance,
  because filings in ₹ lakh round differently.
- Scope: consolidated when a consolidated filing exists, else standalone (S1; Mandate 3 makes this per company).
- Quarterly vs annual-only: quarterly statements carry the P&L rows of §14b; BS and CF only at H1/FY. Annual-only
  sub-rows (other-expense split, dividend amount, fixed-asset schedule, notes) are NULL on every quarterly statement
  and wait for the Reg. 34 parser.
- Divergence codes: `ASSOCIATES_PLACEMENT`, `BANK_EXCEPTIONAL`, `LIFE_TRANSFER_GROSSUP`, `FX_IN_INVESTING`.
  Unexplained residuals are pinned in the parity harness (S11, S13), never imitated.

## 15. Phases

**Phase 1: thin slice, screenable end-to-end (Nifty 500)**

Status (2026-11-13): **built and tested end to end** on real fixtures, all listed items below, plus index backfill (§11.6), quarantine resolution (D-6) and benchmarks (`docs/benchmarks.md`). Known gaps inside Phase 1:
- `piotroski_f` / `beneish_m` columns exist but stay NULL: both need year-over-year annual data (Reg. 34, Phase 2).
- Altman Z'' uses OtherEquity as the retained-earnings proxy; ROCE and ROE use the latest balance sheet (ROE by decision, C16); ROIC, CROIC, RoA, NIM proxy and credit cost use opening + closing averages.
- EV adds minority interest (`NonControllingInterest`, VERIFIED [X34, X42]); preference capital is still excluded (no tag seen). PE and ROE use the owners' share of profit and equity [X42].
- Results-XBRL discovery API is UNVERIFIED [A7]; `fetch-results` takes URLs.
- A split and a series change between two promoted days create a second security; the collision is quarantined and resolved with `quarantine resolve --action MERGE_SECURITIES` (SIGMA, Oct 2025).
- Index backfill covers regular replacement tables only; dummy/spin-off `TEMPORARY` rows are manual.

- Vault (`blobs`, `filings`) and staging/promoter skeleton.
- UDiFF bhavcopy + `sec_bhavdata_full` loaders.
- `trading_calendar`.
- `security_identifier_history` (with `FinInstrmId`).
- `index_constituents_history` (snapshot-forward).
- Corp-action ledger, verification, gap auditor, price/EPS adjuster, total-return index.
- `INDAS_CORP` results parser (standalone and consolidated; RPT contexts land in raw).
- `shares_out`.
- Minimal `screener_features`: market cap, PE, PB, EV/EBITDA, sales growth, OPM, ROCE, ROE, returns 1M/3M/6M/12M, price/200DMA, delivery 5D/20D, delivery velocity.
- DSL v0 and gates G1–G5.

**Phase 2: multi-archetype and annual depth**
- NBFC, bank and general-insurer parsers (each gated on a representative fixture).
- Reg. 34 annual XBRL (leases, notes, segments, AOC-1, restatement comparison).
- Full Reg. 31 shareholding.
- RPT ratios, forensic scores and the remaining §10 ratios.
- Feature snapshots.

**Gaps against the owner's master blueprint (reviewed 2026-11-14), still open:**
- Restatement detector (blueprint §3.2): the YTD-vs-quarters identity is **built** [X80] (TTM withheld over a broken
  year, `CONSISTENCY/YTD_QUARTER_MISMATCH` findings, `audit-ytd`). Still open: the extra triggers on
  `ProfitLossFromDiscontinuedOperations` ≠ 0 and on a demerger/merger in `corp_actions` when the identity happens to
  hold, and any recovery of restated quarters (NSE XBRL has no prior-period columns; PDFs are out of scope).
- AOC-1 subsidiary tree: **built** (batch H): `group_structure` from the Reg. 34 schedule [X112], promoted with each
  annual filing; `backfill-group-structure` fills filings promoted earlier from the vault. Not yet a screener column.
- Related parties per counterparty: **built** (batch J): `related_party_transactions` from the Reg. 34 Ind AS 24 schedule
  [X113] (`parsers/rpt.py`), promoted with each annual filing; `backfill-rpt` fills filings promoted earlier. The
  Reg. 23(9) per-counterparty rows of the Integrated Filing (X19) are **built** too: `reg23_related_party_transactions`
  [X115] (`parsers/reg23_rpt.py`), promoted with each results filing and filled by the same `backfill-rpt`. They are a
  separate table and feed no feature. Their context is the filing's own quarter context, but the amounts cover the
  Reg. 23(9) half-year ending on the period end (SEBI format D note 4; Q2 + Q4 tie out to the Ind AS 24 year and Q4
  opening balances to Q2 closing balances: X160, R13 resolved), recorded as `disclosure_start` / `disclosure_months`
  (HALF_YEAR_RULE, parser `reg23-2`). A few filers put financial-year-to-date amounts in the Q4 filing with nothing in
  the filing to say so (X161), which is why the rows still feed no ratio; `prune-versions` keeps the latest version.
- Everything else filed in XBRL: **built** (18D): `disclosure_facts` [X116] (`parsers/disclosures.py`, parser
  `disc-2` since owner decision M, X120) holds every fact of every element that no other clean table holds per
  element, for results, annual, Reg. 31 and Reg. 30 filings, promoted with each filing, except what the named disc-2
  rules leave in the vault (excluded elements, masked values, the text of long values: §4.1); `backfill-disclosures` fills filings promoted earlier from
  the vault: a process pool (`--workers`, default the CPU count) parses the blobs to staging Parquet, then the single
writer inserts them in one statement and commits once (resumable: staged files are reused; no new results
parser version). `scripts/disclosure_coverage.py DB` prints the per-profile coverage against raw_xbrl_facts on a
database that still has it (the gate of `drop-raw-xbrl`, owner decision J, §4.1); after the drop the same property
is pinned per profile by `tests/test_disclosures.py`, which parses the fixture blobs directly. Under
  disc-1 annual text blocks dominated its size (C28; ~0.9 MB per annual filing); since disc-2 a value over 1,000
  characters is a pointer row and `disclosures.full_text` reads it from the vault (X120, §4.1).
- Merger lineage and the demerger cost-of-acquisition split are **built** as admin-entered, audited edges (§11.7).
  Still open: automatic merger detection (no merger purpose in the corp-action feed, no delisting-circular fixture
  [CA14]) and automatic entitlement ratios / COA percentages (announced only in PDFs; R7 UNVERIFIED).
- Exact share count: the listed count is now daily: NSE's Issue Size in the PR-zip mcap file (`raw_nse_mcap`, X133;
  owner 2026-11-17 "check bhavcopy zip, everything is inside it"). Evaluated against Reg. 31 on the live data: 98.4%
  of 4,035 same-date pairs within 0.5% (84.6% exact), below the 99% bar, because Issue Size counts only shares
  already listed on NSE (allotments wait for listing, bought-back shares stay until extinguished, partly-paid shares
  are a separate E1 security, a bonus counts from its ex-date). So Reg. 31 stays the market-cap share count and
  Issue Size is a cross-check (`check-issue-size`). The Reg. 76 reconciliation audit report itself (issued vs listed vs
  demat) still has no machine-readable source (F09, A15); Reg. 31 x paid-up capital (X103) and the Reg. 34 year-end
  counts (`share_capital.py`, ANNUAL_SHARE_COUNT_DIFFERS, X114) remain the other cross-checks.
- The blueprint files AMFI holdings, PIT/SAST/SDD and bulk/block deals under Phase 2; they stay in Phase 3 here
  because their sources are UNVERIFIED (F11, F13, R8) or only OBSERVED (F14).
- Deliberate divergences: special dividends never adjust prices (invariant 8; the blueprint's §4.2 factor is not
  used), and context ids (`OneD`, `FourD`, `OneI`) are never trusted as period labels (invariant 6; [SHP16]).

**Owner requirements (2026-11-14):** every item from the owner's requirements chat, with status and the phased to-do of what is still missing, is in `docs/owner_requirements.md`.

**Pre-work before Phase 3:** a verified Nifty 500 TRI source (F29) for backtest benchmarks; real fixtures for PIT
(F11), SDD (F13), credit-rating and debt XBRL (F22) and BRSR (F24); a per-AMC adapter plan for monthly portfolios (R8).

**Phase 3: catalysts, flows and backtesting**
- Reg. 30 event XBRL via RSS; insider/SAST/SDD.
- F&O and SLBM; per-AMC portfolio adapters.
- `supplemental_kpis`; Reverse-DCF.
- PIT backtester (queries `fact_observations` and `ohlcv` with `visible_from_ts` and `trade_date` gates, not snapshots).
- Daily diff digest.

## 16. Open decisions

| ID | Question | Current default |
|---|---|---|
| D-1 | Where fetchers run | **Decided**: local only; CI = offline lint + tests |
| D-2 | Which known-defect rules (§7.4) to allow | None yet; quarantine |
| D-3 | Phase 2 fixtures | **Done** (2026-11-13): lending NBFC, life insurer, consolidated corporate with NCI, H1 bank, Reg. 34 annual and pledged Reg. 31 committed with evidence tests [X32-X38, SHP7]. Still useful later: Q1/Q3 corp, a loss-valued exceptional item. (Employee-trust shareholding: Batch 8, Vedanta/JSW [SHP8].) |
| D-4 | Corporate-actions source | **Decided**: NSE API adapter (+ RSS for discovery); unparseable purposes → QUARANTINED. BSE fallback not built (`api.bseindia.com` returned 403 [A1]) |
| D-6 | How a human resolves a quarantine | **Built**: `financials quarantine list` / `inspect Q` (context + the exact resolving commands) / `resolve --action ACCEPT\|REJECT\|OVERRIDE\|CORP_ACTION\|MERGE_SECURITIES --note …` / `reprocess` (`financials.admin`). One transaction; rows are never deleted; every change is logged in `company_overrides`. `CORP_ACTION` must verify against the observed gap; records of that date the parser could not factor (UNKNOWN purpose, failed verification) are retired as `SUPERSEDED`, the manual action is stored `VERIFIED_MANUAL`, and the adjusted series unfreezes. `REJECT` on a corporate-action finding retires that record (`REJECTED`). `OVERRIDE` takes only fields the promoter reads: `broadcast_ts` for `NO_VISIBILITY` and `security_id` for identity failures of a filing (`filing_overrides`), applied at once by promoting that filing again. `MERGE_SECURITIES` repoints identity, prices, actions, index rows and quarantine links to the `FinInstrmId` owner, tombstones the duplicate entity as `MERGED`, and loads the colliding bar from raw (SIGMA case [P14]). `ACCEPT` with a payload on a corporate-action finding [X142]: `{"accept_recorded_factor": true}` accepts a `VERIFY_FAILED` record whose ratio other evidence proves (status `VERIFIED_MANUAL`, the day re-audited, a residual gap raised for its own decision); `{"security_id": …}` records a `STALE_ISIN_OTHER_ISSUER` / `UNKNOWN_ISIN` / `AMBIGUOUS_SECURITY` record for that symbol holder under the promoter's action id; an explicit parse upgrades an `UNPARSED_PURPOSE` record. `reprocess` re-promotes batches with open identity / visibility findings that are still staged (others stay open, listed as `batch_not_staged` [X141]) and re-runs the named gap rules CA12, CA13, X140. Known-defect rules (D-2) are still not built |
| D-5 | Historical index-membership backfill source | Snapshot-forward only [L1] |
