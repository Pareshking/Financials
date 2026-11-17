"""BSE for the Permitted members of rule U1-P [X165-X168]: NSE has no financials for them (fixtures), the BSE
bhavcopy maps ISIN -> scrip code, the ported BSE client (financials.fetch.bse) keeps the source's method, and its
ledger imports into the vault as BSE filings (raw only). Offline: fake HTTP session and fake in-page driver."""

from __future__ import annotations

import gzip
import json
from datetime import date

import pytest

from _fixture_helpers import FIXTURES
from financials.fetch import bse
from financials.parsers.discovery import parse_integrated_filing_listing
from financials.parsers.reg34_annual import parse_annual_listing
from financials.parsers.shareholding import parse_shp_master
from financials.parsers.udiff import parse_udiff_cm

DISC = FIXTURES / "discovery"
BSE = FIXTURES / "bse"
PERMITTED = ("ABBOTINDIA", "MCX", "BAYERCROP", "HAWKINCOOK", "GOODYEAR")


# ── X166: Permitted securities have no financials on NSE ──


def test_x176_permitted_symbols_have_no_nse_financials():
    for sym in PERMITTED:
        res = (DISC / f"nse_integrated-filing-results_equities_{sym}_20261117.json").read_bytes()
        assert parse_integrated_filing_listing(res) == []  # no Integrated Filing - Financials row
        assert parse_annual_listing((DISC / f"nse_annual-reports-xbrl_equities_{sym}_20261117.json").read_bytes()) == []
        assert parse_shp_master(
            (DISC / f"nse_corporate-share-holdings-master_equities_{sym}_20261117.json").read_bytes()
        ) == []  # fmt: skip
    # GOODYEAR: the only NSE row is a Governance filing (Q4 FY26), never financials
    g = json.loads((DISC / "nse_integrated-filing-results_equities_GOODYEAR_20261117.json").read_bytes())
    assert g["totalCount"] == 1 and [r["type"] for r in g["data"]] == ["Integrated Filing- Governance"]
    assert len(parse_integrated_filing_listing(json.dumps(g).encode(), results_only=False)) == 1


# ── X165: BSE UDiFF bhavcopy, FinInstrmId = BSE scrip code ──


def test_x175_bse_bhavcopy_is_udiff_and_maps_isin_to_scrip_code():
    rows = parse_udiff_cm((BSE / "BhavCopy_BSE_CM_0_0_0_20261113_F_0000.CSV").read_bytes(), exchange="BSE")
    assert (
        len(rows) == 5141
        and {r.exchange for r in rows} == {"BSE"}
        and {r.trade_date for r in rows} == {date(2026, 11, 13)}
    )
    by_isin = {r.isin: r for r in rows}
    assert len(by_isin) == len(rows) == len({r.fin_instrm_id for r in rows})  # one row per ISIN and per code
    assert all(r.fin_instrm_id.isdigit() for r in rows)
    # TCS 532540 equals the ScripCode inside its own filing (X111): FinInstrmId is the BSE scrip code
    assert (by_isin["INE467B01029"].fin_instrm_id, by_isin["INE467B01029"].symbol) == ("532540", "TCS")
    assert (by_isin["INE358A01014"].fin_instrm_id, by_isin["INE358A01014"].symbol) == ("500488", "ABBOTINDIA")
    assert by_isin["INE745G01043"].fin_instrm_id == "534091"  # MCX
    assert by_isin["INE533A01012"].fin_instrm_id == "500168"  # GOODYEAR
    assert by_isin["INE467B01029"].series == "A"  # SctySrs is the BSE group, not an NSE series
    with pytest.raises(Exception, match="Sgmt/Src"):
        parse_udiff_cm((BSE / "BhavCopy_BSE_CM_0_0_0_20261113_F_0000.CSV").read_bytes())  # NSE is the default


# ── A17: the source repo's fixtures (real BSE answers, trimmed there) ──


def test_a17_source_fixtures_shapes():
    ann = json.loads((BSE / "announcements.json").read_text(encoding="utf-8"))
    assert len(ann) == 68 and all(r["NEWSID"] and isinstance(r["SCRIP_CD"], int) for r in ann)
    assert {r["CATEGORYNAME"] for r in ann} >= {"Result", "Company Update", "Board Meeting"}
    assert all(r["ATTACHMENTNAME"].endswith(".pdf") for r in ann if r["ATTACHMENTNAME"])
    shp = json.loads((BSE / "shareholding_listing_20261012.json").read_text(encoding="utf-8"))["Table"]
    assert len(shp) == 15
    assert all(r["XBRLAttachment"].startswith("/XBRLFILES/SHPXBRLDataXML/") for r in shp if r["IsXBRL"] == 1)
    nse_shp = (FIXTURES / "xbrl" / "SHP_1739151_15102026054406_WEB.xml").read_text(encoding="utf-8")
    for code in ("500014", "542117", "542910"):
        html = gzip.decompress((BSE / f"shp_{code}_20260930.html.gz").read_bytes()).decode("utf-8")
        # inline XBRL (XHTML + ix:) of the same SEBI shareholding taxonomy NSE's SHP XML instances use
        assert "xmlns:ix='http://www.xbrl.org/2013/inlineXBRL'" in html
        assert "http://www.bseindia.com/xbrl/shp/2025-10-31/in-bse-shp" in html
    assert "http://www.bseindia.com/xbrl/shp/2025-10-31/in-bse-shp" in nse_shp


# ── the ported client: same headers, pacing, retries, hard stop, in-page fallback, raw first ──


class Resp:
    def __init__(self, status: int, body: bytes, ctype: str = "application/json") -> None:
        self.status_code, self.content, self.headers = status, body, {"Content-Type": ctype}


class FakeSession:
    def __init__(self, answers: list) -> None:
        self.headers: dict = {}
        self.answers, self.calls = list(answers), []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a


class FakeDriver:
    def __init__(self, answers: list) -> None:
        self.answers, self.urls, self.home = list(answers), [], None

    def get(self, url):
        self.home = url

    def execute_async_script(self, script, url):
        self.urls.append(url)
        return self.answers.pop(0)

    def quit(self):
        pass


def client(answers, tmp_path, driver=None, **kw):
    sleeps: list[float] = []
    in_page = bse.InPage(lambda: driver) if driver is not None else None
    c = bse.BseClient(FakeSession(answers), sleep=sleeps.append, ledger=bse.Ledger(tmp_path / "led"), **kw)
    if in_page is not None:
        c.in_page = in_page  # available for the fallback; plain requests still come first
    return c, sleeps


def test_client_headers_pace_and_raw_first(tmp_path):
    ann = (BSE / "announcements.json").read_bytes()
    payload = json.dumps({"Table": json.loads(ann), "Table1": [{"ROWCNT": 68}]}).encode()
    c, sleeps = client([Resp(200, payload), Resp(200, b'{"Table": []}')], tmp_path)
    assert c.session.headers["Origin"] == "https://www.bseindia.com" and c.session.headers["Referer"] == bse.HOME
    assert c.session.headers["Sec-Fetch-Site"] == "same-site" and "Chrome/" in c.session.headers["User-Agent"]
    rows, total = c.announcements(date(2026, 10, 12), date(2026, 10, 12), scrip="500488", category="Result")
    assert len(rows) == 68 and total == 68
    url, params = c.session.calls[0]
    assert url == bse.API + "AnnSubCategoryGetData/w" and params["strScrip"] == "500488"
    assert params["strCat"] == "Result" and params["strPrevDate"] == "20261012" and params["strType"] == "C"
    c.shareholding_filings(6, scrip="500488")
    assert len(sleeps) == 1 and 4.0 <= sleeps[0] <= 6.0  # 4-6 s between calls, none before the first
    recs = c.ledger.records()
    assert [r["dataset"] for r in recs] == ["announcements", "shareholding_filings"]
    assert c.ledger.read(recs[0]["sha256"]) == payload and recs[0]["via"] == "requests"
    assert recs[0]["url"].startswith(bse.API + "AnnSubCategoryGetData/w?pageno=1&")


def test_client_retries_5xx_and_stops_on_refusal(tmp_path):
    c, _ = client([Resp(503, b""), OSError("reset"), Resp(200, b"[]")], tmp_path)
    assert c.list_securities("A") == []
    assert len(c.session.calls) == 3
    c, _ = client([Resp(500, b"")] * 4, tmp_path)
    with pytest.raises(bse.Failed, match="after 3 retries"):
        c.list_securities("A")
    c, _ = client([Resp(403, b"Access Denied", "text/html")], tmp_path / "refused", allow_in_page=False)
    with pytest.raises(bse.Blocked, match="HTTP 403"):
        c.list_securities("A")
    assert c.ledger.records() == []  # a refusal is never stored as data
    c, _ = client([Resp(404, b"")], tmp_path)
    with pytest.raises(bse.Missing):
        c.attachment("x.pdf")


def test_client_moves_to_in_page_xhr_after_a_refusal(tmp_path):
    drv = FakeDriver([[200, "application/json", '{"Table": [{"SCRIP_CD": 500488}]}'], [403, "text/html", "no"]])
    c, _ = client([Resp(403, b"Access Denied", "text/html")], tmp_path, driver=drv)
    assert c.list_securities("A", scrip="500488") == [{"SCRIP_CD": 500488}]
    assert c.via == "in_page_xhr" and drv.home == bse.HOME and "ListofScripData/w?scripcode=500488" in drv.urls[0]
    assert c.ledger.records()[0]["via"] == "in_page_xhr"
    with pytest.raises(bse.Blocked, match="in_page_xhr"):  # the rest of the run stays in the page; 403 there stops
        c.list_securities("B")
    assert len(c.session.calls) == 1


def test_ledger_imports_as_bse_raw_filings(tmp_path):
    from conftest import Market

    from financials.promoter import promote

    shp = (BSE / "shp_542910_20260930.html.gz").read_bytes()
    c, _ = client([Resp(200, b'{"Table": []}'), Resp(200, shp, "text/html")], tmp_path)
    c.shareholding_filings(6)
    url = "/XBRLFILES/SHPXBRLDataXML/542910_12102026182749_SP.html"
    assert c.shareholding_xbrl(url) == shp
    (tmp_path / "m").mkdir()
    m = Market(tmp_path / "m")
    staged, errors = bse.import_ledger(m.vault, m.stage_root, tmp_path / "led")
    assert errors == [] and len(staged) == 2
    for s in staged:
        assert promote(m.con, s).status == "PROMOTED"
    got = m.con.execute(
        "SELECT exchange, category, source_url FROM filings WHERE exchange = 'BSE' ORDER BY 2"
    ).fetchall()
    assert got == [("BSE", "BSE_SHP_LISTING", bse.API + "Corp_Shareholding_ng/w?scripcode=&flag=6&indtype="),
                   ("BSE", "BSE_SHP_XBRL", bse.HOME.rstrip("/") + url)]  # fmt: skip
    again, _ = bse.import_ledger(m.vault, m.stage_root, tmp_path / "led")
    for s in again:
        promote(m.con, s)
    assert m.con.execute("SELECT count(*) FROM filings WHERE exchange = 'BSE'").fetchone()[0] == 2
    # a blob whose bytes do not match the ledger is refused, never vaulted
    sha = bse.Ledger(tmp_path / "led").records()[1]["sha256"]
    (tmp_path / "led" / "blobs" / sha).write_bytes(b"tampered")
    _, errors = bse.import_ledger(m.vault, m.stage_root, tmp_path / "led")
    assert len(errors) == 1 and "sha256" in errors[0]
    m.con.close()
