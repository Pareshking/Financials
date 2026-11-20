"""BSE request-gap probe (owner 2026-11-20: approved; GitHub runner only, BSE refuses the cloud container).

For each gap (seconds between requests, fixed), asks the results listing of N Permitted scrips (the same call the
weekly bse-fetch makes) and stops that gap at the first refusal (Blocked / non-200) or when the median latency of the
last 5 answers is over 3x the first 5. No in-page fallback, no retries. Nothing is vaulted: answers are discarded.
Prints one JSON summary per gap, and writes per-request lines to --out.

    python scripts/bse_rate_probe.py --scrips 500488,530499,... --gaps 4,2 --n 20 --out bse_probe.jsonl
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from financials.fetch import bse


def probe(scrips: list[str], gap: float, out) -> dict:
    bse.RETRIES = 0  # one try per request: a refusal is a result, not something to retry around
    c = bse.BseClient(pace=(gap, gap), allow_in_page=False)
    lat, rows, stop = [], 0, None
    t0 = time.monotonic()
    for s in scrips:
        t = time.monotonic()
        try:
            c.finance_results(s, 6)
            status = 200
        except bse.Blocked as exc:
            status = f"blocked: {str(exc)[:100]}"
        except Exception as exc:  # any failure ends the phase
            status = f"{type(exc).__name__}: {str(exc)[:100]}"
        dt = time.monotonic() - t - (gap if rows else 0.0)  # the client's own wait is not latency
        rows += 1
        lat.append(max(dt, 0.0))
        out.write(json.dumps({"gap_s": gap, "scrip": s, "status": status, "latency_s": round(lat[-1], 3)}) + "\n")
        out.flush()
        if status != 200:
            stop = f"after {rows} requests: {status}"
            break
        if len(lat) >= 10 and statistics.median(lat[-5:]) > 3 * statistics.median(lat[:5]):
            stop = f"latency x3 after {rows} requests"
            break
    c.close()
    wall = time.monotonic() - t0
    return {
        "gap_s": gap,
        "requests": rows,
        "wall_s": round(wall, 1),
        "median_latency_s": round(statistics.median(lat), 3) if lat else None,
        "stopped": stop,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scrips", required=True)
    ap.add_argument("--gaps", default="4,2")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    scrips = [x for x in a.scrips.split(",") if x]
    gaps = [float(g) for g in a.gaps.split(",")]
    with a.out.open("w") as out:
        for i, g in enumerate(gaps):
            r = probe(scrips[i * a.n : (i + 1) * a.n], g, out)
            print(json.dumps(r), flush=True)
            if r["stopped"]:
                break
            time.sleep(30)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
