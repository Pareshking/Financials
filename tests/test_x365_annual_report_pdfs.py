"""RULES25 X365: the NSE `annual-reports` listing (annual report PDFs) and `fetch-annual-reports`, offline.

Fixture `annual/nse_annual-reports_AEGISVOPAK_20261125.json`: one answer of
`https://www.nseindia.in/api/annual-reports?index=equities&symbol=AEGISVOPAK` (after the session warm-up), saved
unmodified: two rows, FY 2025-26 and FY 2024-25, each `fileName` a full `nsearchives.nseindia.in/annual_reports/` URL.
The PDFs are vaulted and promoted raw only (category ANNUAL_REPORT_PDF); the fake transport serves stand-in bytes.
"""

from __future__ import annotations

import io
from datetime import datetime

import pytest

from _fixture_helpers import FIXTURES
from financials.cli import main
from financials.db import connect
from financials.fetch.http import Response
from financials.fetch.jobs import WARMUP, annual_report_listing_url
from financials.parsers import ParseError
from financials.parsers.annual_report_pdf import parse_annual_report_listing
from financials.timeutil import IST

LISTING = FIXTURES / "annual" / "nse_annual-reports_AEGISVOPAK_20261125.json"
FY26 = "https://nsearchives.nseindia.in/annual_reports/AR_29781_AEGISVOPAK_2025_2026_A_6055215_14072026154806.pdf"
FY25 = "https://nsearchives.nseindia.in/annual_reports/AR_27054_AEGISVOPAK_2024_2025_A_21072025191219.pdf"


def test_listing_fixture_facts():
    e26, e25 = parse_annual_report_listing(LISTING.read_bytes())
    assert (e26.company_name, e26.from_year, e26.to_year, e26.submission_type) == (
        "Aegis Vopak Terminals Limited", 2025, 2026, "New",
    )  # fmt: skip
    assert e26.broadcast_ts_ist == datetime(2026, 7, 14, 15, 48, 6, tzinfo=IST)
    assert e26.disseminated_ts_ist == datetime(2026, 7, 14, 15, 48, 7, tzinfo=IST)
    assert e26.file_url == FY26 and e26.ext == "pdf" and e26.listed_size == "5.77 MB"
    assert (e25.to_year, e25.file_url, e25.listed_size) == (2025, FY25, None)
    with pytest.raises(ParseError):
        parse_annual_report_listing(b'{"data": [{"fileName": "x.pdf"}]}')
    with pytest.raises(ParseError):
        parse_annual_report_listing(b"<html>blocked</html>")


class FakeNse:
    def __init__(self):
        self.urls: list[str] = []

    def get(self, url, headers, timeout):
        self.urls.append(url)
        if url == WARMUP["www.nseindia.in"]:
            return Response(200, b"<html></html>")
        if url == annual_report_listing_url("AEGISVOPAK"):
            return Response(200, LISTING.read_bytes())
        if url in (FY26, FY25):
            return Response(200, b"%PDF-1.7 stand-in for " + url.encode() + b"\n%%EOF\n")  # complete: X362
        return Response(404, b"")


def _run(tmp_path, transport, *extra):
    import financials.cli as cli_mod

    out, orig = io.StringIO(), cli_mod.PoliteFetcher
    cli_mod.PoliteFetcher = lambda transport, **kw: orig(transport, sleep=lambda s: None, **kw)
    try:
        rc = main(["--data-dir", str(tmp_path), "fetch-annual-reports", "--symbols", "AEGISVOPAK", *extra],
                  transport=transport, out=out)  # fmt: skip
    finally:
        cli_mod.PoliteFetcher = orig
    return rc, out.getvalue()


def test_fetch_annual_reports_vaults_raw_only_and_never_downloads_twice(tmp_path):
    t = FakeNse()
    rc, out = _run(tmp_path, t)
    assert rc == 0, out
    assert t.urls.count(FY26) == 1 and t.urls.count(FY25) == 1
    assert out.count("staged raw_only/") == 3  # the listing and two PDFs
    assert main(["--data-dir", str(tmp_path), "init-db"], out=io.StringIO()) == 0
    assert main(["--data-dir", str(tmp_path), "promote"], out=io.StringIO()) == 0
    con = connect(tmp_path / "market.duckdb", read_only=True)
    try:
        rows = con.execute(
            "SELECT f.category, f.source_url, f.stated_symbol, f.broadcast_ts, f.broadcast_ts_source, b.media_type "
            "FROM filings f JOIN blobs b USING (sha256) WHERE f.category LIKE 'ANNUAL_REPORT%' ORDER BY 1, 2"
        ).fetchall()
        canonical = con.execute("SELECT count(*) FROM filing_meta").fetchone()[0]
    finally:
        con.close()
    assert rows == [
        ("ANNUAL_REPORT_PDF", FY25, "AEGISVOPAK", datetime(2025, 7, 21, 13, 42, 19), "API_FIELD", "application/pdf"),
        ("ANNUAL_REPORT_PDF", FY26, "AEGISVOPAK", datetime(2026, 7, 14, 10, 18, 6), "API_FIELD", "application/pdf"),
        ("ANNUAL_REPORT_PDF_LISTING", annual_report_listing_url("AEGISVOPAK"), None, None, "UNKNOWN",
         "application/json"),
    ]  # fmt: skip
    assert canonical == 0  # nothing parsed into canonical tables
    # a second run lists again (listings change) but downloads no vaulted PDF
    t2 = FakeNse()
    rc, out = _run(tmp_path, t2)
    assert rc == 0 and FY26 not in t2.urls and FY25 not in t2.urls
    assert t2.urls.count(annual_report_listing_url("AEGISVOPAK")) == 1
    # --min-to-year 2026 skips FY 2024-25
    t3 = FakeNse()
    rc, _ = _run(tmp_path / "fresh", t3, "--min-to-year", "2026")
    assert rc == 0 and FY26 in t3.urls and FY25 not in t3.urls


def test_fetch_annual_reports_reports_a_bad_listing(tmp_path):
    class Blocked(FakeNse):
        def get(self, url, headers, timeout):
            if "annual-reports" in url:
                self.urls.append(url)
                return Response(200, b"<html>no</html>")
            return super().get(url, headers, timeout)

    rc, out = _run(tmp_path, Blocked())
    assert rc == 1 and "AEGISVOPAK annual report PDFs" in out and "staged" not in out
