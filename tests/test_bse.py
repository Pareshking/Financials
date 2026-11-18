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


def test_ledger_imports_as_bse_filings(tmp_path):
    from datetime import datetime

    from conftest import Market

    from financials.promoter import promote

    shp = (BSE / "500488_14102026161949_SP.html").read_bytes()
    listing = (BSE / "bse_Corp_Shareholding_ng_500488_flag6_20261117.json").read_bytes()
    c, _ = client([Resp(200, listing), Resp(200, shp, "text/html")], tmp_path)
    c.shareholding_filings(6, scrip="500488")
    url = "/XBRLFILES/SHPXBRLDataXML/500488_14102026161949_SP.html"
    assert c.shareholding_xbrl(url) == shp
    (tmp_path / "m").mkdir()
    m = Market(tmp_path / "m")
    staged, errors = bse.import_ledger(m.vault, m.stage_root, tmp_path / "led")
    assert errors == [] and [p.parent.name for p in staged] == ["raw_only", "shareholding"]
    assert promote(m.con, staged[0]).status == "PROMOTED"
    # no NSE identifier rows in this database: the pattern parses but its ISIN resolves to nothing (quarantined)
    r = promote(m.con, staged[1])
    assert r.status == "QUARANTINED", r
    q = "SELECT exchange, category, source_url, broadcast_ts FROM filings WHERE exchange = 'BSE' ORDER BY 2"
    got = m.con.execute(q).fetchall()
    assert got == [("BSE", "BSE_SHP_LISTING", bse.API + "Corp_Shareholding_ng/w?scripcode=500488&flag=6&indtype=",
                    None),
                   ("BSE", "SHP_XBRL", bse.HOME.rstrip("/") + url, datetime(2026, 10, 14, 10, 49))]  # fmt: skip
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


# ── X169: BSE list of securities (probe run 2, group A) and rule BSE1 ──

LIST_A = BSE / "bse_ListofScripData_GroupA_20261117.json"
LIST_A_URL = bse.API + "ListofScripData/w?scripcode=&Group=A&industry=&segment=Equity&status=Active"


def test_x169_list_of_securities_group_a():
    from decimal import Decimal

    from financials.parsers.bse_securities import parse_list_securities

    rows = parse_list_securities(LIST_A.read_bytes())
    assert len(rows) == 705 and {(r.bse_group, r.status, r.segment) for r in rows} == {("A", "Active", "Equity")}
    by = {r.scrip_code: r for r in rows}
    a = by["500488"]
    assert (a.isin, a.ticker, a.face_value, a.market_cap_inr) == (
        "INE358A01014", "ABBOTINDIA", Decimal("10.00"), Decimal("552321400000.00"))  # Rs 55,232.14 Cr # fmt: skip
    assert (by["532540"].isin, by["534091"].isin) == ("INE467B01029", "INE745G01043")  # TCS (X111), MCX
    assert len({r.isin for r in rows}) == 705 and all(r.market_cap_inr for r in rows)
    # every ISIN -> code of the list equals the BSE bhavcopy's (X165), so both sources agree
    bhav = {r.isin: r for r in parse_udiff_cm((BSE / "BhavCopy_BSE_CM_0_0_0_20261113_F_0000.CSV").read_bytes(),
                                              exchange="BSE")}  # fmt: skip
    assert all(bhav[r.isin].fin_instrm_id == r.scrip_code and bhav[r.isin].symbol == r.ticker for r in rows)


def test_rule_bse1_fills_scrip_codes_by_isin(tmp_path):
    from datetime import datetime

    from conftest import Market

    from financials.promoter import promote

    (tmp_path / "m").mkdir()
    m = Market(tmp_path / "m")
    assert promote(m.con, m.stage_day("20261112")).status == "PROMOTED"
    # a code already stored differently is kept and raised, never overwritten
    m.con.execute("UPDATE security_identifier_history SET bse_scrip_code = '999999' WHERE symbol = 'MCX'")
    led = bse.Ledger(tmp_path / "led")
    led.put(dataset="list_securities", url=LIST_A_URL, status=200, body=LIST_A.read_bytes(),
            content_type="application/json; charset=utf-8", via="requests",
            fetched_at=datetime.fromisoformat("2026-11-17T06:09:21.319543+00:00"))  # fmt: skip
    staged, errors = bse.import_ledger(m.vault, m.stage_root, tmp_path / "led")
    assert errors == [] and [p.parent.name for p in staged] == ["bse_securities"]
    r = promote(m.con, staged[0])
    assert r.status == "PROMOTED" and len(r.quarantined) == 1, r
    code = dict(m.con.execute("SELECT symbol, bse_scrip_code FROM security_identifier_history "
                              "WHERE symbol IN ('ABBOTINDIA', 'TCS', 'MCX', 'RELIANCE')").fetchall())  # fmt: skip
    assert code == {"ABBOTINDIA": "500488", "TCS": "532540", "MCX": "999999", "RELIANCE": "500325"}
    q = m.con.execute("SELECT stage, reason_code, details FROM quarantine_queue").fetchall()
    assert [(s, c) for s, c, _ in q] == [("IDENTIFIER", "BSE_SCRIP_CODE_CONFLICT")]
    assert json.loads(q[0][2])["filed"] == "534091" and json.loads(q[0][2])["rule"] == "BSE1"
    n = m.con.execute("SELECT count(*) FROM raw_bse_securities").fetchone()[0]
    assert n == 705 and m.con.execute("SELECT DISTINCT observed_date FROM raw_bse_securities").fetchall() == [
        (date(2026, 11, 17),)
    ]
    assert promote(m.con, staged[0]).status == "PROMOTED"  # replay: nothing added
    assert m.con.execute("SELECT count(*) FROM raw_bse_securities").fetchone()[0] == 705
    assert m.con.execute("SELECT count(*) FROM quarantine_queue").fetchone()[0] == 1
    m.con.close()


def test_cli_import_bse_promote_and_bse_members(tmp_path):
    """Owner's machine, in order: update-universe (U1-P) and import-bse + promote (BSE1), then bse-members prints
    the Permitted members with their scrip codes for the bse-fetch workflow input."""
    import io
    from datetime import datetime

    from conftest import FETCHED_AT
    from test_mcap_universe import URL, raw

    from financials.cli import main
    from financials.staging import stage_holidays, stage_mcap_day
    from financials.vault import Vault

    data = tmp_path / "data"
    assert main(["--data-dir", str(data), "init-db"], out=io.StringIO()) == 0
    from conftest import Market

    m = Market.__new__(Market)  # stage into the CLI's own vault / staging
    m.vault, m.stage_root = Vault(data / "vault"), data / "staging"
    Market.stage_day(m, "20261112")
    hol = FIXTURES / "calendar" / "nse_holiday-master_trading_20261113.json"
    stage_holidays(m.vault, m.stage_root, data=hol.read_bytes(), source_url="nse-hol", fetched_at=FETCHED_AT)
    stage_mcap_day(m.vault, m.stage_root, data=raw("PR131126"), source_url=URL.format("PR131126"),
                   fetched_at=FETCHED_AT)  # fmt: skip
    led = bse.Ledger(tmp_path / "led")
    led.put(dataset="list_securities", url=LIST_A_URL, status=200, body=LIST_A.read_bytes(),
            content_type="application/json", via="requests",
            fetched_at=datetime.fromisoformat("2026-11-17T06:09:21+00:00"))  # fmt: skip
    out = io.StringIO()
    assert main(["--data-dir", str(data), "import-bse", str(tmp_path / "led")], out=out) == 0
    assert "staged 1 BSE file(s)" in out.getvalue()
    assert main(["--data-dir", str(data), "promote"], out=io.StringIO()) == 0
    assert main(["--data-dir", str(data), "update-universe", "--from", "2026-11-09", "--to", "2026-11-15"],
                out=io.StringIO()) == 0  # fmt: skip
    out = io.StringIO()
    assert main(["--data-dir", str(data), "bse-members", "--as-of", "2026-11-13"], out=out) == 0
    last = out.getvalue().strip().splitlines()[-1]
    assert "500488" in last and "534091" in last and "Permitted members" in last
    abbott = [json.loads(x) for x in out.getvalue().splitlines() if x.startswith("{") and "ABBOTINDIA" in x]
    assert abbott[0]["bse_scrip_code"] == "500488" and abbott[0]["isin"] == "INE358A01014"


# ── A18: probe run 3 answers (plain requests from a GitHub runner, 2026-11-17) ──


def test_a18_announcements_have_no_xbrl_link_and_attachment_is_the_pdf():
    one = json.loads((BSE / "bse_AnnSubCategoryGetData_500488_20261015_20261117.json").read_bytes())
    day = json.loads((BSE / "bse_AnnSubCategoryGetData_all_20261113_p1.json").read_bytes())
    assert one["Table1"] == [{"ROWCNT": 4}] and len(one["Table"]) == 4
    assert {r["SCRIP_CD"] for r in one["Table"]} == {500488}  # strScrip narrows to the scrip
    assert len(day["Table"]) == 50 and day["Table1"] == [{"ROWCNT": 2704}]  # 50 a page, BSE's count for the day
    res = [r for r in one["Table"] if r["CATEGORYNAME"] == "Result"]
    assert [(r["SUBCATNAME"], r["ATTACHMENTNAME"], r["Fld_Attachsize"]) for r in res] == [
        ("Financial Results", "e334e776-71a5-4afd-adf3-ad10a11505cf.pdf", 1884669)
    ]
    pdf = (BSE / "AttachLive_e334e776-71a5-4afd-adf3-ad10a11505cf.pdf").read_bytes()
    assert pdf[:5] == b"%PDF-" and len(pdf) == res[0]["Fld_Attachsize"]  # the attachment is the results PDF
    # No field of any row links an XBRL / XML file: XML_NAME is ANN_<scrip>_<NEWSID upper>, not a file (X168)
    for r in one["Table"] + day["Table"]:
        assert r["XML_NAME"] == f"ANN_{r['SCRIP_CD']}_{r['NEWSID'].upper()}"
        others = {k: v for k, v in r.items() if k not in ("XML_NAME", "NSURL")}
        assert "xbrl" not in json.dumps(others).lower() and ".xml" not in json.dumps(others).lower()
    assert all(r["ATTACHMENTNAME"].endswith(".pdf") for r in one["Table"] + day["Table"] if r["ATTACHMENTNAME"])


def test_a18_list_of_securities_one_scrip_and_shareholding_listing():
    from financials.parsers.bse_securities import parse_list_securities

    (a,) = parse_list_securities((BSE / "bse_ListofScripData_A_500488_20261117.json").read_bytes())
    assert (a.scrip_code, a.isin, a.ticker, str(a.market_cap_inr)) == ("500488", "INE358A01014", "ABBOTINDIA",
                                                                       "552321400000.00")  # fmt: skip
    shp = json.loads((BSE / "bse_Corp_Shareholding_ng_500488_flag6_20261117.json").read_bytes())["Table"]
    assert [(r["EndDate"][:10], r["D"], r["XBRLAttachment"].rsplit("/", 1)[-1]) for r in shp][:2] == [
        ("2026-09-30", "2026-10-14T16:19:00", "500488_14102026161949_SP.html"),
        ("2026-06-30", "2026-07-17T10:47:00", "500488_1772026104730_SP.html"),
    ]
    assert len(shp) == 4 and all(r["IsXBRL"] == 1 and r["FLD_ScripCode"] == 500488 for r in shp)


# ── X170: BSE inline-XBRL shareholding through the existing parser ──


def _shp_files() -> dict[str, bytes]:
    out = {"500488": (BSE / "500488_14102026161949_SP.html").read_bytes()}
    for c in ("500014", "542117", "542910"):
        out[c] = gzip.decompress((BSE / f"shp_{c}_20260930.html.gz").read_bytes())
    return out


def test_x170_inline_shareholding_reaches_the_shareholding_parser():
    from decimal import Decimal

    from financials.parsers.ixbrl import inline_to_instance, is_inline
    from financials.parsers.pr_mcap import parse_pr_mcap
    from financials.parsers.shareholding import parse_shareholding, shp_instance

    files = _shp_files()
    for code, data in files.items():
        assert is_inline(data)
        p = parse_shareholding(data)
        assert p.ok, (code, p.issues)
        assert p.meta["stated_scrip_code"] == code and p.meta["stated_symbol"] == "NOTLISTED"
        assert p.meta["as_of_date"] == date(2026, 9, 30) and p.categories["TOTAL"]["pct"] == 1  # fractions
        assert p.meta["rules_applied"][:2] == ["IXBRL_INLINE_SHP", "IXBRL1_BOOLEAN_TEXT"]
    inst = shp_instance(files["500488"])[0]
    assert len(inst.facts) == 707 + 64 and len(inst.contexts) == 68
    assert is_inline(inline_to_instance(files["500488"])) is False
    p = parse_shareholding(files["500488"])
    assert p.meta["stated_isin"] == "INE358A01014" and p.categories["PROMOTER"]["pct"] == Decimal("0.7499")
    # the BSE pattern's total equals NSE's Issue Size for ABBOTINDIA on the same date (mcap file, X133)
    mcap = {(r.symbol, r.series): r for r in parse_pr_mcap((FIXTURES / "pr_zip" / "PR300926.zip").read_bytes())}
    assert p.categories["TOTAL"]["shares"] == mcap[("ABBOTINDIA", "EQ")].issue_size == 21249302
    assert (p.meta["has_partly_paid"], p.meta["promoter_pledge_flag"]) == (False, False)  # "No" -> false (IXBRL1)
    # IXBRL1: "Yes" is true where the figures say so (542910 locked-in shares)
    lock = shp_instance(files["542910"])[0]
    assert lock.first_text("WhetherTheListedEntityHasAnySharesInLockedIn") == "true"
    assert lock.first_text("WhetherTheListedEntityHasIssuedAnyPartlyPaidUpShares") == "false"


def test_x170_inline_reader_refuses_what_it_does_not_know():
    from financials.parsers import ParseError
    from financials.parsers.ixbrl import inline_to_instance

    data = _shp_files()["500488"]
    with pytest.raises(ParseError, match="neither Yes nor No"):
        inline_to_instance(data.replace(b">No<", b">Maybe<", 1))
    with pytest.raises(ParseError, match="unsupported number format"):
        inline_to_instance(data.replace(b"decimals='INF'", b"decimals='INF' format='ixt:numcommadecimal'", 1)
                           if b"decimals='INF'" in data else data.replace(b'decimals="INF"',
                           b'decimals="INF" format="ixt:numcommadecimal"', 1))  # fmt: skip


def test_bse_shareholding_promotes_for_the_nse_security(tmp_path):
    """A Permitted member's BSE pattern lands in the shareholding tables of the security NSE trades (by ISIN),
    visible from BSE's broadcast time."""
    from conftest import Market

    from financials.promoter import promote

    (tmp_path / "m").mkdir()
    m = Market(tmp_path / "m")
    assert promote(m.con, m.stage_day("20261112")).status == "PROMOTED"
    c, _ = client([Resp(200, (BSE / "bse_Corp_Shareholding_ng_500488_flag6_20261117.json").read_bytes()),
                   Resp(200, (BSE / "500488_14102026161949_SP.html").read_bytes(), "text/html")], tmp_path)  # fmt: skip
    c.shareholding_filings(6, scrip="500488")
    c.shareholding_xbrl("/XBRLFILES/SHPXBRLDataXML/500488_14102026161949_SP.html")
    staged, errors = bse.import_ledger(m.vault, m.stage_root, tmp_path / "led")
    assert errors == []
    results = [promote(m.con, s) for s in staged]
    assert [r.status for r in results] == ["PROMOTED", "PROMOTED"], results
    row = m.con.execute(
        "SELECT s.entity_id, o.shares, o.visible_from_ts, f.exchange FROM shareholding_observations o "
        "JOIN filings f USING (filing_id) JOIN securities s ON s.entity_id = o.entity_id "
        "JOIN security_identifier_history h ON h.security_id = s.security_id AND h.symbol = 'ABBOTINDIA' "
        "WHERE o.category = 'TOTAL'"
    ).fetchall()
    from datetime import datetime

    assert [(r[1], r[2], r[3]) for r in row] == [(21249302, datetime(2026, 10, 14, 10, 49), "BSE")]
    m.con.close()


def test_bse2_rows_without_an_isin_are_skipped_and_other_defects_still_reject():
    """Rule BSE2 [X200]: BSE group Y (2026-11-17) lists two securities with ISIN "" and "NA"; they are skipped."""
    from financials.parsers import ParseError
    from financials.parsers.bse_securities import parse_list_securities

    data = (FIXTURES / "bse" / "bse_ListofScripData_GroupY_20261117.json").read_bytes()
    assert b'"ISIN_NUMBER":""' in data and b'"ISIN_NUMBER":"NA"' in data
    assert parse_list_securities(data) == []
    bad = data.replace(b'"ISIN_NUMBER":"NA"', b'"ISIN_NUMBER":"INE12"')
    with pytest.raises(ParseError, match="malformed"):
        parse_list_securities(bad)


def test_bse_fetch_windows_a_scrip_around_a_date():
    """BSE answered HTTP 400 to a 19-month announcements range for one scrip (2026-11-18); CODE@DATE asks +-3 days."""
    import importlib.util

    from financials.sources import ROOT

    spec = importlib.util.spec_from_file_location("bse_fetch", ROOT / "scripts" / "bse_fetch.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    since, today = date(2025, 4, 1), date(2026, 11, 18)
    assert m._window("500488", since, today) == ("500488", since, today)
    assert m._window("500488@2026-05-20", since, today) == ("500488", date(2026, 5, 17), date(2026, 5, 23))
    assert m._window("500488@2026-11-17", since, today) == ("500488", date(2026, 11, 14), today)
