# CLAUDE.md

Personal, single-user Indian equity research, screening and point-in-time backtesting engine.
Universe v1: NSE Mainboard `EQ`/`BE`/`BZ`, starting with the Nifty 500. SME excluded.
**Data starts** (CHOICE C9, `financials/scope.py`): market data, corporate actions and index snapshots
`>= 2024-10-01` (`MIN_TRADE_DATE`, UDiFF era); financials and shareholding `period_end >= 2025-03-31`
(`MIN_PERIOD_END_DATE`, Q4 FY25: first Integrated Filing quarter). No parsers or fallbacks for older formats.
No redistribution.

**Read before changing anything:** `docs/architecture.md` (design), `docs/references.md`
(evidence register: what is VERIFIED vs UNVERIFIED) and `docs/data_sources.md` (every feed; generated
from `config/data_sources.yaml` by `python -m financials.sources --write`; edit the YAML, never the MD),
and `docs/tag_registry.yaml` (every XBRL element seen per profile + named label rules; extend it with
`python scripts/inspect_xbrl_exhaustive.py FILES --registry docs/tag_registry.yaml --batch <id>`).

## Commands

```bash
python -m pip install -e ".[dev]"   # Python 3.11+
python -m pytest                    # must pass before every commit
ruff check src tests && ruff format --check src tests   # CI runs both

# local operation (network; never in tests or CI)
python -m financials --data-dir data init-db
python -m financials --data-dir data fetch-days 2026-11-12        # also fetch-corp-actions / -holidays / -index / -shareholding / -results
python -m financials --data-dir data promote                       # the only writer
python -m financials --data-dir data materialize 2026-11-12
python -m financials --data-dir data screen "Market Cap > 500 AND ROE > 15"
python -m financials --data-dir data quarantine list --reason ISIN_COLLISION    # resolve: quarantine resolve --id … --action … --note …
python -m financials --data-dir data backfill-index --manifest reference/nifty500_changes.csv
python -m financials.bench --out docs/benchmarks.md                # after performance-relevant changes
```

## Layout

```
docs/                  architecture.md, references.md
tests/fixtures/        real, unmodified NSE files + MANIFEST.md (sha256 + source URL)
tests/test_*_fixture_facts.py   characterisation tests pinning VERIFIED claims
src/financials/        db/schema.sql (DDL source of truth), parsers/ (pure: bytes → rows), identity.py,
                       corp_actions.py, returns.py, calendar.py, fundamentals.py, features.py, dsl.py,
                       vault.py, staging.py (fetch/parse side), promoter.py (single writer),
                       admin.py (index backfill, quarantine resolution; single writer), index_changes.py,
                       fetch/ (polite HTTP + jobs), cli.py, bench.py
reference/             curated data derived from fixtures (e.g. nifty500_changes.csv; a test pins it)
data/                  local only, gitignored: vault/, staging/, market.duckdb
```

## Evidence rules

1. **Never code against an UNVERIFIED claim** in `docs/references.md`. Get a real file into
   `tests/fixtures/`, record it in `MANIFEST.md`, pin the behaviour with a test, then mark it VERIFIED.
2. **Fixtures are evidence.** Never edit, trim or regenerate one. Add a new file instead.
3. If a characterisation test fails, the claim is wrong. Do not edit the test to pass;
   revisit the claim and everything that depends on it.
4. Do not invent circular numbers, tag names, URLs or file formats. If unsure, say so and add an UNVERIFIED row.

## Data invariants (non-negotiable)

1. **Append-only.** Vault blobs, `filings`, raw tables and `fact_observations` are never updated
   in place. A revision is a new filing (`supersedes_filing_id`). A re-parse is a new `parser_version`.
2. **Blob ≠ filing.** One sha256 can have many filings (NSE + BSE mirror, re-sends), each with its own `broadcast_ts`.
3. **Raw keeps source identifiers.** Raw tables store symbol/series/ISIN exactly as sent. Resolution
   to `security_id` happens in L2 via `security_identifier_history` (date-bounded). Splits change the
   ISIN but keep `FinInstrmId`; series changes keep the ISIN but change `FinInstrmId`. Match on either, and
   quarantine if they disagree (architecture §5.1).
4. **Point-in-time.** Every fundamental row carries `visible_from_ts`. Every PIT read filters
   `visible_from_ts <= as_of`. Never "latest wins" without an as-of.
5. **Per-filing, not per-entity:** accounting profile (from XBRL namespace), scope
   (`NatureOfReportStandaloneConsolidated`), interest-classification in cash flow.
6. **Period gating.** Derive `period_months` from validated dates (1..18). Never trust context IDs
   or context dates blindly; reconcile with declared period facts. Never combine different
   `period_months`, scopes or profiles. TTM needs 4 same-scope quarters; YoY on TTM needs 8.
7. **Money is `DECIMAL(20,2)` rupees** (`decimal.Decimal` in Python). Never float for money.
   XBRL values are already absolute rupees; tolerances come from `LevelOfRounding`, never `decimals`.
8. **Prices** are adjusted only for splits, bonuses, rights bonus element and demergers. EPS only
   for share-count events. Dividends never adjust prices; they feed the total-return series.
   Absolute financials are never multiplied by any factor.
9. **Quarantine over auto-heal.** Unknown taxonomy, missing critical tag, failed identity, period
   conflict, unexplained >10% open gap or ISIN change → `quarantine_queue`; keep raw data, freeze
   derived data. A recurring defect may only be fixed by a named deterministic rule with its own fixture and test.
10. **Single writer.** Fetchers and parsers write vault files and staging Parquet only. Only the
    promoter opens `data/market.duckdb` for writing, and promotes atomically after gates G1–G5.
11. Timestamps are `TIMESTAMP` columns holding UTC; convert to/from IST only at parse and display boundaries.
12. IDs are deterministic (`stable_id`), so replays are idempotent. Never use random IDs for data rows.
13. Schema lives only in `src/financials/db/schema.sql`. No nullable `UNIQUE` columns (DuckDB `OR IGNORE` bug [I1]).
    Bulk inserts go through `financials.db.insert_rows` (Arrow), never row-by-row `executemany`.
14. **Scope cutoff.** Out-of-scope inputs are vaulted (blob + filing) and promoted as `OUT_OF_SCOPE`;
    nothing is parsed into canonical tables. Filter financials on period **end** (FY25 from the Q4 FY25
    filing is in scope). Any window needing history before the cutoff (3Y/5Y CAGR, 5Y dilution, 5Y valuation
    percentile, 3Y FCF conversion…) returns NULL via `min_periods_required`, never a partial-window number.

## Testing rules

- Tests are offline. No test may touch the network. Fetchers are tested against vault/fixture files.
- Every bug fix in parsing, corporate actions, periods or ratio math adds a regression test.
- Never loop a query per row/security on a hot path (promotion, materialisation, screens): batch it.
  `tests/test_benchmarks.py` guards this; refresh `docs/benchmarks.md` when timings change materially.
- New parser or profile work starts from a real fixture of that exact profile and period type.

## Fetching (local machine only for now)

- `nsearchives.nseindia.com`: archives (bhavcopy, delivery, XBRL files, RSS). `www.nseindia.com`
  needs session cookies and runs only locally.
- At least 1 s between requests per host, backoff with jitter on 403/429/5xx, never re-download a vaulted blob.
- Exchange terms prohibit automated access. Keep volume minimal and never redistribute data.

## Don'ts

- Don't commit `data/`, DuckDB files, Parquet or credentials.
- Don't add Cloudflare/R2/D1 or any second database engine without an explicit decision.
- Don't put dated facts (circulars, company examples) in this file. They belong in `docs/references.md`.
