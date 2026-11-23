# Handover (2026-11-23)

Read this first in a new session, then `CLAUDE.md`, `docs/phase_status.md`, `docs/owner_requirements.md`.

## 1. The database is not in git (read before anything else)

`data/` is gitignored and lives only in the container of session `session_016X4g5asrdYPvsJKyYVNYma`:
`data/market.duckdb` 5.5 GB, `data/vault/` 2.8 GB (the raw source of truth). A new cloud session starts from a fresh
clone **without them**. There is no off-container backup yet (owner 2026-11-21: "No R2 set up right now").

Ways forward, in order of preference:
1. **Back up first:** owner adds R2 credentials in the environment settings (not GitHub, never in chat):
   `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`. The old session then uploads
   `export-bundle` (0.64 GB zstd Parquet) + `data/vault/`; the new session downloads them and runs
   `python -m financials --data-dir data import-bundle --db data/market.duckdb <bundle>` (restore tested 21 Nov:
   ~4 min, 53 tables identical). Est. cost ~$0.05/month for 3.5 GB.
2. **Rebuild from the exchanges:** NSE/BSE runner workflows (`nse-fetch.yml`, `bse-fetch.yml`) without `since`,
   then local `fetch-days`/`fetch-mcap` from 2024-10-01, `promote`, full `materialize` (~39 min after the fetch).
   Hours of fetching and heavy exchange load: last resort.
3. Code-only work (no DB needed) is fine in a new session: the test suite is fully offline.

## 2. State at handover

- Branch `ccr-49d50339-exd8gh`, draft PR #5, CI green at 06049a5 (plus this note).
- Parser 0.10.12, features `2026.11.21-21N` (pinned hash in `tests/test_incremental_materialize.py`).
- **Phases 1-2 declared done** (owner condition: a clean weekly run; 21 Nov: 750 open findings, 0 UNCLASSIFIED).
  Only one clean week so far; 28 Nov is the second.
- Exchange rates (X354, measured): NSE archive 12 req/s, NSE API 2 req/s with 3 in flight, BSE 2-3 s.
- Universe 2,066 members (rule U1). Open findings 759 after 23 Nov's daily run.
- Run long CLI jobs through `scripts/promote_capped.py` (DuckDB memory capped at 6 GB; the container has ~8 GB).
- Tests: `pytest -n 4 --deselect tests/test_benchmarks.py && pytest tests/test_benchmarks.py` (~10 min). Do not pipe
  pytest into `tail` in a gated `&&` chain: the pipe hides its exit code.

## 3. Scheduled tasks bound to the OLD session

These fire into `session_016X4g5asrdYPvsJKyYVNYma` and use its scratchpad paths, so they only work there:

| id | name | schedule (IST) |
|---|---|---|
| trig_01ChGxtKrVz8qbceMoMEEGmj | Daily market update (evening) | Mon-Fri 18:53 |
| trig_01K3VKKJ6S4KsrZCFw6CK4aS | Daily late-filings catch-up | Mon-Fri 23:37 |
| trig_01RDmYxzcT33MmzU4hDEm31m | Weekly full sweep (NSE + BSE runners, audit-annual, findings report) | Sat 10:47 |

If the data moves to a new session: disable these, recreate them bound to the new session with paths updated
(`scripts/promote_capped.py`, a venv of the new container). Tasks for other sessions (tracker repo) are not ours.

## 4. Open work (no owner decision needed unless marked)

1. **Rights 5:9 (ex 2026-11-18):** quarantined `UNPARSED_PURPOSE` "no rule for 'RIGHTS 5:9'"; that company's adjusted
   prices from 18 Nov are not adjusted for the rights bonus element. Needs the real corp-action file as a fixture,
   then a named rule and test (evidence rules 1-2).
2. 23 Nov daily: 8 `UNKNOWN_ISIN` Reg. 30 events, 2 `UNEXPLAINED_GAP` on penny stocks (+11.7%, +16.3%): triage.
3. Task #24: root-cause + named rules for the expanded-universe quarantine; #25: statements and ratios vs industry
   practice for new members.
4. Optional: slim PK/ART indexes (DB 5.5 GB = ~1.8 GB data + ~3.3 GB indexes; target ~2.5 GB).
5. **Owner decision:** R2 backup (section 1); then read the tracker's stored Parquet (`R2_TRACKER_BUCKET`).
6. Phase 3: start from `docs/phase3_reuse_map.md` (owner's NSE-BSE-Insider-Tracker already has MF portfolios,
   PIT/SAST, deals, flows, buybacks, surveillance). Import its pure parsers; keep this repo's evidence rules.

## 5. Standing rules (owner)

Never commit `data/`, DuckDB, Parquet or credentials. Fixtures are real and unmodified. Single DB writer (promoter).
Never bypass an exchange block; keep volume minimal; never redistribute. Draft PRs only. Gated suite before every
push. No model identifiers in commits. Owner's private details stay private.
