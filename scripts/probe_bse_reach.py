"""BSE probe through the ported client (financials.fetch.bse: the owner's production method, plain requests with BSE's
own headers, 4-6 s apart, in-page XHR in headless Chrome only after a refusal). Five to seven calls:

  1. list of securities, group A (ISIN_NUMBER <-> SCRIP_CD map, BSE market cap)       ListofScripData
  2. results announcements of ABBOTINDIA (500488, NSE `Permitted`), Aug-Nov 2026     AnnSubCategoryGetData
  3. the latest of those announcements' attachment                                    xml-data/corpfiling/AttachLive
  4. the shareholding filings of the last year for 500488                             Corp_Shareholding_ng
  5. the latest of those filings' inline XBRL                                         XBRLFILES/SHPXBRLDataXML

Every answer is written byte for byte to the ledger (--out DIR: blobs/<sha256> + ledger.jsonl) before it is read; the
workflow uploads DIR as an artifact, which `python -m financials --data-dir data import-bse DIR` vaults and stages on
the owner's machine. The log prints status, size and sha256 only. A refusal (`Blocked`) ends the probe: no retries
around it (CLAUDE.md, owner decision).

    python scripts/probe_bse_reach.py --out bse_probe
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import date
from pathlib import Path

from financials.fetch.bse import Blocked, BseClient, Failed, Ledger

SCRIP = "500488"  # ABBOTINDIA: BSE bhavcopy of 2026-11-13, FinInstrmId for ISIN INE358A01014 [X165]


def _show(label: str, body: bytes | None, extra: str = "") -> None:
    sha = hashlib.sha256(body).hexdigest()[:16] if body is not None else ""
    print(f"OK    {label}: {len(body or b'')} bytes sha256 {sha} {extra}".rstrip())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    led = Ledger(a.out)
    c = BseClient(ledger=led)
    try:
        sec = c.list_securities("A")
        hit = [r for r in sec if str(r.get("SCRIP_CD", "")).strip() == SCRIP]
        _show("list of securities, group A", None, f"{len(sec)} rows; 500488: "
              f"{[(r.get('ISIN_NUMBER'), r.get('Mktcap')) for r in hit]}")  # fmt: skip
        ann, total = c.announcements(date(2026, 8, 1), date(2026, 11, 17), scrip=SCRIP, category="Result")
        _show("results announcements 500488", None, f"{len(ann)} rows (BSE count {total}); "
              f"{[(r.get('NEWS_DT'), r.get('SUBCATNAME'), r.get('ATTACHMENTNAME')) for r in ann[:5]]}")  # fmt: skip
        att = next((r for r in ann if r.get("ATTACHMENTNAME")), None)
        if att:
            body = c.attachment(att["ATTACHMENTNAME"], {"news_id": att.get("NEWSID"), "scrip": SCRIP})
            _show("latest results attachment", body, f"Fld_Attachsize {att.get('Fld_Attachsize')}")
        shp = c.shareholding_filings(6, scrip=SCRIP)
        mine = [r for r in shp if str(r.get("FLD_ScripCode")) == SCRIP] or shp
        _show("shareholding filings (flag 6) 500488", None, f"{len(shp)} rows, {len(mine)} for 500488; "
              f"{[(r.get('EndDate'), r.get('IsXBRL'), r.get('XBRLAttachment')) for r in mine[:4]]}")  # fmt: skip
        x = next((r for r in mine if r.get("IsXBRL") == 1 and r.get("XBRLAttachment")), None)
        if x:
            body = c.shareholding_xbrl(x["XBRLAttachment"], {"scrip": str(x.get("FLD_ScripCode")),
                                                             "end": x.get("EndDate")})  # fmt: skip
            _show("latest shareholding inline XBRL", body)
    except (Blocked, Failed) as exc:
        print(f"STOP  {type(exc).__name__}: {exc}")
    finally:
        c.close()
    recs = led.records()
    print(f"{len(recs)} answers in the ledger (via {sorted({r['via'] for r in recs}) or '-'}):")
    for r in recs:
        print(f"  {r['status']} {r['bytes']:>9} {r['sha256'][:16]} {r['via']:<12} {r['url']}")
    return 0  # a probe: the log is the result


if __name__ == "__main__":
    sys.exit(main())
