# Deployment plan: GitHub Actions + Cloudflare R2 + Cloudflare site (decision K, PROPOSED)

Status: proposal for the owner (2026-11-16). Nothing here is built. CLAUDE.md's "no Cloudflare/R2 without an explicit
decision" holds until decision K is taken. Limits below were checked on 2026-11-16 (sources at the end); re-check them
before building, they change.

## 1. Roles (one job each)

| Part | Does | Never |
|---|---|---|
| GitHub Actions `nightly` | the only writer: restore DB, fetch the day, promote, materialize incrementally, check, publish | two runs at once (`concurrency: pipeline`, no cancel) |
| GitHub Actions cache | fast copy of the latest DB next to the runner (restored first) | source of truth (evicted after 7 days unused or over 10 GB) |
| R2 bucket `fin-private` | vault blobs, dated DB snapshots + manifests, site files | public access or a public URL |
| Cloudflare Pages + Functions | site behind Cloudflare Access login; reads site files from R2 through a binding | writes data, computes ratios |
| Gemini (free) | question -> DSL text | numbers; it never sees the database |
| Owner PC | read-only; fallback fetcher if NSE blocks runners | writing while `nightly` can run |

## 2. Nightly run (daily data only)

Runs 00:15 IST (cron `45 18 * * *` UTC) plus a 07:15 IST catch-up for late filings; each run is incremental.

1. **Restore**: Actions cache hit -> use it; else download `db/latest` from R2. Verify sha256 against its manifest, then
   row counts per table. Mismatch -> stop.
2. **Vault sync**: only blobs whose sha256 is not in the runner's vault (`url_index.jsonl` is the ledger); vault blobs
   are immutable, so this is a delta, never a full copy.
3. **Fetch the day only**: `run-day --date D` (bhavcopy, delivery, index, corporate actions, RSS-hinted filings;
   archive host 8 req/s, www 1 req/s as today). New blobs go to R2 first, then into staging.
4. **Promote + `materialize --incremental`** (dirty rows only, architecture §11.10). A full rebuild only when
   FEATURES_VERSION changes; that is a separate manual workflow.
5. **Health checks** (any failure stops the run before publishing; GitHub emails the failure):
   gates G1-G5 and new quarantine rows (reported, not fatal); row counts vs the previous snapshot within tolerance;
   no feature column that was populated yesterday is now all NULL; the latest trading day present for >= 95% of
   yesterday's securities; `screener_golden` values recomputed; `pytest -q tests/test_docs_sync.py` style invariants.
6. **Publish**: `compact` if dead space >= 20%; upload `db/YYYY-MM-DD.duckdb` (multipart) + manifest (sha256, rows per
   table, FEATURES_VERSION, git sha); write site files (`site/latest/*.parquet`: today's screener table, saved screen
   results, company pages); **last** move `db/latest` and `site/latest` pointers. A run that dies before this step
   changes nothing anyone reads.
7. **Retention**: 3 daily + 4 weekly snapshots; older ones deleted by the same job.

The whole database file is uploaded each night because DuckDB rewrites blocks in place (no file-level delta). After
decision J the file is ~1 GB: ~12 multipart writes a night.

## 3. Site

- Cloudflare Access in front of the Pages project (email one-time code or Google login), no self-made password page.
- Read-only pages from precomputed `site/latest` files: saved screens, company page, breadth.
- Custom screens: a Function compiles the DSL with our `dsl.py` (Python Workers) to SQL; the browser runs it with
  DuckDB-WASM on `site/latest/screener.parquet` (~3,000 rows, a few MB). History/backtests stay on the runner or PC.
- Gemini: the Function sends the question + the column catalogue (`docs/ratio_catalogue.md` names only), receives DSL,
  compiles it with `dsl.py`; anything that does not compile is rejected; the DSL is shown before it runs. API key in
  a Worker secret, never in the page.

## 4. Free limits and our expected use

| Service | Free limit (checked 2026-11-16) | Our use (estimate) | Headroom / risk |
|---|---|---|---|
| R2 storage | 10 GB-month | vault 0.7 + 7 snapshots x ~1 GB + site 0.1 = ~8 GB after J; with the raw table kept (5.3 GB file) it does not fit | keep J; at 1,500 companies drop to 2 daily + 2 weekly |
| R2 Class A (writes, lists) | 1 M / month | ~100 / night (new blobs, 12 parts, manifests, site files) = ~3 k | ample |
| R2 Class B (reads) | 10 M / month | runner restore misses + site reads, ~1 k / day | ample |
| R2 egress | free | — | — |
| Workers / Pages Functions | 100 k requests / day, 10 ms CPU per request | personal use, < 1 k / day | the 10 ms CPU cap is the risk for Python `dsl.py` (spike P0.3) |
| Pages static assets | free, unlimited requests | — | — |
| Cloudflare Access | free for small teams | 1 user | — |
| GitHub Actions (public repo) | unlimited minutes; job <= 6 h; runner 4 vCPU / 16 GB RAM / ~14 GB disk | nightly ~10-20 min; CI 6 shards x ~5 min per push | disk is enough after J |
| Actions cache | 10 GB / repo, evicted after 7 days unused | one ~1 GB DB entry, refreshed nightly | eviction is harmless (R2 fallback) |
| Gemini free tier | per-model RPM / RPD, not all published; free-tier prompts may be used to improve Google products | a few queries / day | send only the question + column names, never data |

R2 asks for a payment method even on the free tier; set a Cloudflare billing notification so an overage (cents) is
seen, not discovered.

## 5. Phases and acceptance checks

| Phase | Work | Done when |
|---|---|---|
| P0.1 NSE from runners | `nse-reach` workflow (built) | 5/5 on 2026-11-16 (sha256 of the bhavcopy equals the container's). Then nightly for 7 days at the planned hour: >= 6/7 nights 5/5, else the fallback below |
| P0.2 R2 round trip | upload / download / sha256 of a 1 GB file from a runner | identical sha256, time measured |
| P0.3 Python Worker | `dsl.py` compiles 20 saved + random screens inside the CPU limit | all compile, output SQL equals the Python run's |
| P0.4 DuckDB-WASM | browser query of `screener.parquet` from R2 through the Function | rows equal `financials screen` on the same snapshot |
| P1 Nightly writer | sections 2 + 4 | 14 consecutive green nights; a forced failure (bad manifest) leaves `latest` unchanged |
| P2 Read-only site | saved screens, company page | Playwright parity test in Actions (Access service token): 10 screens identical to Python |
| P3 Custom screens | DSL in the browser | parity test on 100 generated screens |
| P4 Gemini | question -> DSL | 30 sample questions: every accepted DSL compiles; wrong-column answers rejected |
| Ops | monthly restore drill: rebuild from the R2 vault on a runner, compare with the snapshot | identical (scripts/compare_materialize.py) |

## 6. Failure modes

| Failure | Effect | Handling |
|---|---|---|
| NSE blocks runner IPs | no new data | PC runs `fetch-*` only and uploads blobs to the R2 vault; the runner promotes from them |
| Run dies midway | nothing published | `latest` pointers move last; next run starts from the last good snapshot |
| Corrupt snapshot | restore fails sha256 | previous dated snapshot |
| Two writers | lost update | `concurrency` group; PC is read-only by rule |
| Cache evicted | slower restore | R2 download |
| Free limit exceeded | small bill or Function error 1027 for the day | usage notification; retention shrink |
| Gemini changes limits / terms | assistant unavailable | screens still work without it |

## Sources (2026-11-16)

- R2 pricing: https://developers.cloudflare.com/r2/pricing/
- Workers limits and pricing: https://developers.cloudflare.com/workers/platform/limits/ ,
  https://developers.cloudflare.com/workers/platform/pricing/ ; Pages Functions count against the Workers quota:
  https://developers.cloudflare.com/pages/functions/pricing/
- Actions cache 10 GB / 7 days: https://github.blog/changelog/2025-11-20-github-actions-cache-size-can-now-exceed-10-gb-per-repository/ ;
  Actions limits: https://docs.github.com/en/actions/reference/limits
- Gemini free tier (secondary sources; confirm on ai.google.dev): https://pecollective-com.pages.dev/tools/gemini-free-tier-guide/
