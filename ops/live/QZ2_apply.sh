#!/usr/bin/env bash
# Owner 2026-11-19 ("Yes for all"): ACCEPT the share-count findings where two of the three counts agree
# (docs/open_findings.md causes CC_PAIDUP_OUTLIER, ASC_REG31_OUTLIER, ASC_ANNUAL_COUNT_OUTLIER; decision S practice:
# the odd count is the filer's, market cap already uses the agreeing pair). Run with no other writer.
set -euo pipefail
DATA=${DATA:-data}
python - "$DATA" <<'PY'
import collections, sys
sys.path.insert(0, "scripts")
import open_findings_report as ofr
from financials.admin import AdminError, resolve_quarantine
from financials.db import connect

CAUSES = {"CC_PAIDUP_OUTLIER", "ASC_REG31_OUTLIER", "ASC_ANNUAL_COUNT_OUTLIER"}
con = connect(f"{sys.argv[1]}/market.duckdb")
done, skipped = collections.Counter(), collections.Counter()
try:
    rows = [r for r in ofr.classify(con) if r["cause"] in CAUSES]
    print("to accept", collections.Counter(r["cause"] for r in rows))
    for r in rows:
        note = (f"Owner 2026-11-19 (yes for all): two of three share counts agree; cause {r['cause']} "
                f"(docs/open_findings.md): {ofr.CAUSES[r['cause']][2] if len(ofr.CAUSES[r['cause']]) > 2 else ''} "
                f"Evidence: {r['evidence']}")[:1900]
        try:
            resolve_quarantine(con, r["quarantine_id"], action="ACCEPT", note=note)
            done[r["cause"]] += 1
        except AdminError as exc:
            skipped[r["cause"]] += 1
            print("skip", r["quarantine_id"], exc)
finally:
    con.close()
print("resolved", dict(done))
print("skipped", dict(skipped))
PY
