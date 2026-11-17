"""BSE probe through the ported client (financials.fetch.bse: the owner's production method, plain requests with BSE's
own headers, 4-6 s apart, in-page XHR in headless Chrome only after a refusal). Five to seven calls:

  1. list of securities, group A, scrip 500488 (run 2: group A answered 200, A18)    ListofScripData
  2. announcements of ABBOTINDIA (500488, NSE `Permitted`), 15 Oct - 17 Nov 2026     AnnSubCategoryGetData
     (strCat -1; Result rows picked by CATEGORYNAME), and the source client's exact one-day call (13 Nov, page 1)
  3. one of those announcements' attachment                                           xml-data/corpfiling/AttachLive
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

from financials.fetch.bse import BadRequest, Blocked, BseClient, Failed, Ledger, Missing

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
    found: dict = {}

    def step(label: str, fn) -> None:
        """One call; a 400 (BadRequest) or a 404 file ends that call only, a refusal (Blocked) ends the probe."""
        try:
            fn()
        except (BadRequest, Missing) as exc:
            print(f"SKIP  {label}: {type(exc).__name__}: {exc}")

    def securities() -> None:
        sec = c.list_securities("A", scrip=SCRIP)
        _show("list of securities, group A, scrip 500488", None,
              f"{len(sec)} rows: {[(r.get('ISIN_NUMBER'), r.get('Mktcap')) for r in sec[:3]]}")  # fmt: skip

    def announcements() -> None:
        # strCat -1 (every category, as the source client) with strScrip; results are picked by CATEGORYNAME. Run 2:
        # strCat=Result with strScrip=500488 answered 400.
        ann, total = c.announcements(date(2026, 10, 15), date(2026, 11, 17), scrip=SCRIP)
        res = [r for r in ann if str(r.get("CATEGORYNAME", "")).strip() == "Result"]
        found["ann"] = res or ann
        top = [(r.get("NEWS_DT"), r.get("SUBCATNAME"), r.get("ATTACHMENTNAME")) for r in res[:4]]
        _show("announcements 500488 (15 Oct - 17 Nov)", None,
              f"{len(ann)} rows (BSE count {total}), {len(res)} Result: {top}")  # fmt: skip

    def announcements_day() -> None:  # the source client's exact call: one day, every company
        ann, total = c.announcements(date(2026, 11, 13), date(2026, 11, 13))
        mine = [r for r in ann if str(r.get("SCRIP_CD")) == SCRIP]
        found.setdefault("ann", mine or ann[:1])
        _show("announcements 13 Nov, page 1 (source client's exact call)", None, f"{len(ann)} rows (BSE count "
              f"{total}); {len(mine)} for 500488")  # fmt: skip

    def attachment() -> None:
        att = next((r for r in found.get("ann", []) if r.get("ATTACHMENTNAME")), None)
        if att:
            body = c.attachment(att["ATTACHMENTNAME"], {"news_id": att.get("NEWSID"), "scrip": str(att["SCRIP_CD"])})
            _show("one announcement attachment", body, f"Fld_Attachsize {att.get('Fld_Attachsize')}")

    def shareholding() -> None:
        shp = c.shareholding_filings(6, scrip=SCRIP)
        mine = [r for r in shp if str(r.get("FLD_ScripCode")) == SCRIP] or shp
        found["shp"] = mine
        _show("shareholding filings (flag 6) 500488", None, f"{len(shp)} rows, {len(mine)} for 500488; "
              f"{[(r.get('EndDate'), r.get('IsXBRL'), r.get('XBRLAttachment')) for r in mine[:4]]}")  # fmt: skip

    def shp_xbrl() -> None:
        x = next((r for r in found.get("shp", []) if r.get("IsXBRL") == 1 and r.get("XBRLAttachment")), None)
        if x:
            body = c.shareholding_xbrl(x["XBRLAttachment"], {"scrip": str(x.get("FLD_ScripCode")),
                                                             "end": x.get("EndDate")})  # fmt: skip
            _show("one shareholding inline XBRL", body)

    try:
        for label, fn in (("securities", securities), ("announcements", announcements),
                          ("announcements (day)", announcements_day), ("attachment", attachment),
                          ("shareholding", shareholding), ("shareholding XBRL", shp_xbrl)):  # fmt: skip
            step(label, fn)
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
