"""BSE runner job (GitHub-hosted runner only; never the database): fetch the BSE side of the Permitted members of
rule U1-P into a ledger (blobs/<sha256> + ledger.jsonl, bytes as sent, financials.fetch.bse), which the workflow
uploads as an artifact and `python -m financials --data-dir data import-bse DIR` then vaults and stages on the owner's
machine; `promote` (the single writer) promotes it.

    python scripts/bse_fetch.py --scrips 500488,534091 --since 2026-10-01 --out bse_fetch

Calls, through the ported client (4-6 s apart, in-page XHR only after a refusal, Blocked stops the job):
- list of securities for every BSE group (`bse` package groups): ISIN <-> scrip code (rule BSE1) and BSE market cap;
- per scrip: announcements since --since (every category, `strScrip`; pages until BSE's count) and each attachment of
  a `Result` announcement (PDF; vaulted raw: no BSE results XBRL endpoint is known, X168);
- shareholding filings of the last 3 months (flag 5) and the inline XBRL of each filing of a listed scrip (vaulted
  raw: X167).
`--scrips` comes from `python -m financials --data-dir data bse-members` (the codes of the Permitted members).
Every endpoint here is UNVERIFIED until a run returns it (A18).
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

from financials.fetch.bse import BadRequest, Blocked, BseClient, Failed, Ledger, Missing

GROUPS = ("A", "B", "E", "F", "FC", "G", "GC", "I", "IF", "IT", "M", "MS", "MT", "P", "R", "T", "TS", "W", "X",
          "XD", "XT", "Y", "Z", "ZP", "ZY")  # fmt: skip  # the `bse` package's valid_groups (3.3.4)
MAX_PAGES = 40


WINDOW_DAYS = 3  # CODE@YYYY-MM-DD: announcements from 3 days before to 3 days after that date


def _window(entry: str, since: date, today: date) -> tuple[str, date, date]:
    """`CODE` uses --since..--to; `CODE@YYYY-MM-DD` asks only around that date. BSE answers HTTP 400 to a 19-month
    range for one scrip (bse-fetch runs of 2026-11-18, strPrevDate 20250401), so results PDFs are fetched around each
    filing's NSE broadcast date instead."""
    code, _, day = entry.partition("@")
    if not day:
        return code, since, today
    d = date.fromisoformat(day)
    return code, d - timedelta(days=WINDOW_DAYS), min(d + timedelta(days=WINDOW_DAYS), today)


def run(c: BseClient, scrips: list[str], since: date, today: date, log) -> int:
    skipped = 0
    for g in GROUPS:
        try:
            log(f"group {g}: {len(c.list_securities(g))} securities")
        except BadRequest as exc:
            skipped += 1
            log(f"SKIP group {g}: {exc}")
    for entry in scrips:
        s, lo, hi = _window(entry, since, today)
        rows: list[dict] = []
        try:
            for page in range(1, MAX_PAGES + 1):
                got, total = c.announcements(lo, hi, page=page, scrip=s)
                rows += got
                if not got or total is None or len(rows) >= total:
                    break
        except BadRequest as exc:
            skipped += 1
            log(f"SKIP announcements {s}: {exc}")
        results = [r for r in rows if str(r.get("CATEGORYNAME", "")).strip() == "Result" and r.get("ATTACHMENTNAME")]
        log(f"{s}: {len(rows)} announcements, {len(results)} Result attachments")
        for r in results:
            try:
                c.attachment(r["ATTACHMENTNAME"], {"news_id": r.get("NEWSID"), "scrip": s})
            except (Missing, BadRequest) as exc:
                skipped += 1
                log(f"SKIP attachment {r['ATTACHMENTNAME']}: {exc}")
    wanted = {_window(e, since, today)[0] for e in scrips}
    try:
        shp = [r for r in c.shareholding_filings(5) if str(r.get("FLD_ScripCode")) in wanted]
    except BadRequest as exc:
        shp = []
        skipped += 1
        log(f"SKIP shareholding filings: {exc}")
    log(f"shareholding filings of the listed scrips (3 months): {len(shp)}")
    for r in shp:
        if r.get("IsXBRL") == 1 and r.get("XBRLAttachment"):
            try:
                c.shareholding_xbrl(r["XBRLAttachment"], {"scrip": str(r["FLD_ScripCode"]), "end": r.get("EndDate")})
            except (Missing, BadRequest) as exc:
                skipped += 1
                log(f"SKIP {r['XBRLAttachment']}: {exc}")
    return skipped


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scrips", required=True, help="comma-separated BSE scrip codes, or CODE@YYYY-MM-DD windows")
    ap.add_argument("--since", type=date.fromisoformat, required=True)
    ap.add_argument("--to", type=date.fromisoformat, default=date.today())
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    scrips = [s.strip() for s in a.scrips.split(",") if s.strip()]
    if not all(s.partition("@")[0].isdigit() for s in scrips):
        ap.error("--scrips: BSE scrip codes are digits (optionally CODE@YYYY-MM-DD)")
    led = Ledger(a.out)
    c = BseClient(ledger=led)
    rc = 0
    try:
        skipped = run(c, scrips, a.since, a.to, print)
        print(f"done: {len(led.records())} answers in the ledger, {skipped} calls skipped")
    except (Blocked, Failed) as exc:
        print(f"STOP  {type(exc).__name__}: {exc} ({len(led.records())} answers kept in the ledger)")
        rc = 1
    finally:
        c.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
