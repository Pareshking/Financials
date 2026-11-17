# Scheduling the daily run

Pick **one** scheduler. Each runs `run-day` then `materialize --incremental` (docs/architecture.md §13). Two at
once would race for the DuckDB write lock (single writer, CLAUDE.md invariant 10).

| Option | Files | When |
|---|---|---|
| systemd user timer | `systemd/financials-daily.service`, `systemd/financials-daily.timer` | 20:15 IST |
| cron | `cron/financials.cron` | 20:15 IST |
| Windows Task Scheduler | `windows/financials-daily.xml` | 20:15 IST |
| GitHub Actions, self-hosted runner | `.github/workflows/nightly-pipeline.yml` | 22:00 IST (cron `30 16 * * *` UTC) |

`.github/workflows/nightly-tests.yml` (offline lint + pytest on a GitHub-hosted runner, 22:00 IST) is independent of
the data and can run alongside any of them.

## Why the pipeline cannot run on a GitHub-hosted runner

- **No data there.** `data/` (vault, staging, `market.duckdb`, several GB) is gitignored and lives only on your disk. A
  hosted runner starts from an empty VM every time and has no persistent disk; rebuilding the database nightly would
  mean re-downloading every vaulted blob, which the fetch rules forbid.
- **NSE blocks datacenter IPs.** Archive and API requests from cloud ranges are refused, and `www.nseindia.com` needs
  session cookies from an ordinary connection.
- **No redistribution.** Exchange data copied to GitHub's machines, caches or artifacts is data on someone else's
  servers. The workflow uploads only its run log and never commits anything.

So the pipeline workflow only *schedules* your machine: GitHub sends the job at 22:00 IST to a runner process that you
run at home, and everything happens on your disk.

## Registering a self-hosted runner (one time, on the machine that holds `data/`)

1. Keep the repository **private**. A self-hosted runner executes the workflow's code on your machine; on a public
   repository a fork's pull request could target it. The pipeline workflow runs only on `schedule` and
   `workflow_dispatch`, never on `pull_request`.
2. On GitHub: repository → Settings → Actions → Runners → **New self-hosted runner**. Choose your OS and architecture
   and follow the shown download commands into a folder outside the checkout, e.g. `~/actions-runner`.
3. Configure it with the label the workflow asks for (the token is shown on that page; it expires within an hour and is
   never stored in the repository):

   ```bash
   cd ~/actions-runner
   ./config.sh --url https://github.com/<owner>/<repo> --token <TOKEN> --name financials-home \
       --labels financials --work _work --unattended
   ```

   `self-hosted` (and the OS / architecture labels) are added automatically; the job needs `[self-hosted, financials]`.
4. Tell the runner where the data and the virtualenv are. Create `~/actions-runner/.env` (read by the runner at start;
   it is outside the repository):

   ```
   FINANCIALS_DATA_DIR=/home/<you>/Financials/data
   FINANCIALS_VENV=/home/<you>/Financials/.venv
   ```

   The venv is the one you made with `python -m pip install -e ".[dev]"`; the workflow uses its interpreter and
   dependencies with the checked-out commit's code (`PYTHONPATH=<workspace>/src`), so it does not reinstall anything.
   The data directory must be outside the runner's `_work` folder: the first step fails otherwise.
5. Run it as a service so it survives reboots and logouts:

   ```bash
   sudo ./svc.sh install "$USER" && sudo ./svc.sh start      # Linux (systemd) / macOS (launchd)
   ```

   On Windows, answer "yes" to "run as service" during `config.cmd` and set the two variables as system environment
   variables (or in `.env` in the runner folder).
6. Disable any `ops/` scheduler you installed (`systemctl --user disable --now financials-daily.timer`, remove the
   crontab line, or delete the Windows task).
7. Test it: repository → Actions → **nightly-pipeline** → Run workflow. The run log is attached to the run as the
   `nightly-pipeline-log-<run id>` artifact (kept 14 days). The machine must be on and online at 22:00 IST; a missed
   night is caught up by the next `run-day` (its lookback window) and `materialize --incremental`.

GitHub-hosted schedules run on the default branch, can start late under load, and are paused after 60 days without
repository activity on public repositories.

## Storage maintenance (monthly, and after full rebuilds)

DuckDB never shrinks its file: re-materialised feature days and deleted rows stay as dead blocks
(docs/architecture.md §4.1). Run, with no other `financials` writer running:

```bash
python -m financials --data-dir data compact            # monthly (cron line in cron/financials.cron), keeps nothing
python -m financials --data-dir data compact --keep-old # keep the previous file as data/market.duckdb.bak
python -m financials --data-dir data prune-versions --dry-run   # rows of superseded parser versions, per table
python -m financials --data-dir data prune-versions             # archive to data/archive, delete, then compact
```

Once, on a database from before features `2026.11.16-17E` (every write command refuses it until then):

```bash
python -m financials --data-dir data migrate-sparse-history   # wide history -> features_daily + features_events + view
python -m financials --data-dir data materialize --from 2024-10-01 --to <last day>   # the FEATURES_VERSION bump
```

The migration runs in one transaction (the live database: ~2-3 minutes, the new tables reuse the file's free
blocks), verifies the view against the wide table row for row before dropping it, and rolls back on any difference.

A full `materialize --from/--to`, `rebuild-market`, `migrate-sparse-history` and `prune-versions` compact by
themselves when at least 20% (and 256 MB) of the file is dead space and the disk has room; otherwise they print the
`compact` command. `compact` needs
1.1 x the live size free next to the database and refuses otherwise. If a compaction is interrupted between its two
renames, `data/market.duckdb.bak` is the complete previous database: rename it back.

## The ops/ files

Paths assume the checkout at `~/Financials` with a `.venv`; edit them. `tests/test_batch_h_industry_peers.py` checks
that they call only existing CLI commands; `tests/test_nightly_workflows.py` does the same for the workflows.
