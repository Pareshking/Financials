# Process audit (2026-11-19)

Owner, 2026-11-19: "Why so much time is going on ... something in our process must be wrong, slow" and "if 10 companies
reported results tomorrow, we can't run for hours for each update". Measured on the live database (2,065 members,
526 market days, 5.5 GB) and the 4-CPU cloud container.

## Where the hours went

| Step | Before | Now | When it runs |
|---|---|---|---|
| Full test suite (2,165 tests) | 38 min, one CPU | ~17 min (`pytest -n 4`, benchmarks alone) | before every push |
| Test temp files | ~5.6 GB per run (two runs died "no space left") | ~0.2 GB (`tmp_path_retention_policy = failed`) | every run |
| Full materialize (every day since 2024-10-01) | ~40 min + compact | unchanged | only after a FEATURES_VERSION bump (code that changes numbers) |
| Incremental materialize, 2-12 changed companies x ~370 days | ~6 min (1.1 s fixed cost per day) | ~28 s (0.075 s per unchanged day); 10-50 companies with new results ~10-15 s | every results update |
| Promote, results-only day | 0.3 s per file + ~9.5 s fixed (6.8 s is the X103 share re-check loop) | unchanged | every results update |

The 60 slowest tests (3% of tests) took 59% of the suite: storage / compaction, incremental-equivalence and
end-to-end tests that build whole databases. They run in parallel now instead of being cut.

## Daily update path (10 companies report results)

fetch (polite rate limits: ~1 request/s on www.nseindia.in, BSE 4-6 s apart) -> `promote` (~15 s) ->
`materialize --incremental` (~15 s). Minutes, dominated by the polite fetch, not by computation. Hours were only ever
spent on code changes: each rule that changes stored numbers bumps FEATURES_VERSION and forces one full rebuild.

## Why Phases 1-2 took days

1. Each rule paid the whole chain alone (suite ~40 min, full materialize ~40 min, apply, baseline): ~2 h per rule.
   Fix: batch rules, one suite and one full rebuild per batch.
2. No finish line: open findings are mostly filers' own errors that XBRL cannot settle; each review closed 30-60% of
   a class and the tail never reaches zero. Fix (owner decision 2026-11-19): done = sample accuracy >= 98% (QD2
   99.54%) and every open finding has a stated cause (`docs/open_findings.md`, UNCLASSIFIED 0).
3. Self-inflicted churn: finding ids hashed the differences, so re-runs reopened accepted findings (X312 fixed).
4. Environment: the container suspends without a tracked job, background jobs stop at 2 h, ~10 GB free disk, and
   agent usage limits (2.7 h idle on 2026-11-18).

## Next speed items (not done)

- X103 share re-check in promote: one query per open CROSS_CHECK_FAILED finding (6.8 s per run); batch it.
- A changed day still costs ~0.6 s in incremental; a version bump still needs the ~40 min full rebuild.
