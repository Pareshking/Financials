"""Data catalogue: what every fixture file contains, and whether we ingest it -> docs/data_catalogue.md.

    python scripts/data_catalogue.py --write     # regenerate docs/data_catalogue.md
    python scripts/data_catalogue.py             # print it; exit 1 if the committed file differs

Walks tests/fixtures/ (every member of every zip too) and groups each file into a family of the hand-written FAMILIES
table below: pattern -> family, source (feed id of config/data_sources.yaml), status, tables (db/schema.sql), parser
and the open owner requirements (docs/owner_requirements.md) its columns could serve. A file that matches no family, or
more than one, fails the run. INGESTED / DISCOVERY_ONLY claims are checked against the code: every table must exist in
schema.sql and the parser function must be defined in its module and called from another module under src/financials.
Output is deterministic (sorted, no timestamps). XBRL instances are counted per directory only; their elements live in
docs/tag_registry.yaml.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import re
import sys
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

import yaml

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
MD_PATH = ROOT / "docs" / "data_catalogue.md"
SCHEMA = ROOT / "src" / "financials" / "db" / "schema.sql"
SOURCES_YAML = ROOT / "config" / "data_sources.yaml"
REQUIREMENTS = ROOT / "docs" / "owner_requirements.md"
MANIFEST = FIXTURES / "MANIFEST.md"

STATUSES = {
    "INGESTED": "parsed into the named table(s) by the named parser (checked against the code by this script)",
    "DISCOVERY_ONLY": "vaulted (blob + `filings` row) and parsed for links / broadcast times only; no table of its own",
    "VAULTED_RAW": "fetched and vaulted (blob + `filings` row) but never parsed",
    "NOT_INGESTED": "nothing fetches, stages or promotes it (a parser may exist; see the note)",
    "REFERENCE": "documentation or test metadata, not a data feed",
}
MAX_KEYS = 60


@dataclass(frozen=True)
class Family:
    name: str
    patterns: tuple[str, ...]  # regex, fullmatch on the path under tests/fixtures/ ("<zip>!<member>" for zip members)
    status: str
    note: str
    source: tuple[str, ...] = ()  # feed ids of config/data_sources.yaml
    tables: tuple[str, ...] = ()
    parser: str = ""  # "module:function" under src/
    serves: tuple[tuple[str, str], ...] = ()  # (requirement id, why), only where the columns plainly justify it
    xbrl: bool = False  # instance documents: counted per directory, elements in docs/tag_registry.yaml
    document: bool = False  # prose (PDF / pdftotext / markdown): listed with its line count only


def _pr(prefix: str) -> tuple[str, ...]:
    """Pattern of one member of NSE's daily PR zip, any case and either date width (ddmmyy before 2025, ddmmyyyy)."""
    return (rf"(?:pr_zip|series_switch)/PR\d{{6}}\.zip!(?i:{prefix})\d{{6,8}}\.(?i:csv|txt)",)


XBRL_DIRS = r"[a-z0-9_]+"
FAMILIES: tuple[Family, ...] = (
    # ── NSE market data ──────────────────────────────────────────────────────────────────────────────────────────
    Family(
        "NSE UDiFF CM bhavcopy",
        (
            r"(?:bhavcopy|identity|series_switch)/BhavCopy_NSE_CM_0_0_0_\d{8}_F_0000\.csv\.zip"
            r"!BhavCopy_NSE_CM_0_0_0_\d{8}_F_0000\.csv",
        ),
        "INGESTED",
        "End-of-day OHLC, volume, value, trades per instrument (ISIN, FinInstrmId, series) of the cash "
        "market; the price, identity and calendar spine.",
        ("F01",),
        ("raw_cm_bhavcopy", "ohlcv", "security_identifier_history", "trading_calendar"),
        "financials.parsers.udiff:parse_udiff_cm",
    ),
    Family(
        "NSE security-wise delivery (sec_bhavdata_full)",
        (r"bhavcopy/sec_bhavdata_full_\d{8}\.csv",),
        "INGESTED",
        "Per symbol / series: prices, traded quantity and deliverable quantity / percentage.",
        ("F02",),
        ("raw_delivery", "ohlcv"),
        "financials.parsers.delivery:parse_sec_bhavdata_full",
    ),
    # ── NSE daily PR zip (one zip, 14 members; NSE's own readme sentence per member) ──────────────────────────────
    Family(
        "NSE PR zip: mcap market capitalisation",
        _pr("mcap"),
        "INGESTED",
        "Market cap, issue size, face value, category (Listed / Permitted) per symbol and series; rule U1 universe.",
        ("F31",),
        ("raw_nse_mcap", "universe_membership"),
        "financials.parsers.pr_mcap:parse_pr_mcap",
    ),
    Family(
        "NSE PR zip: bh price-band hits",
        _pr("bh"),
        "INGESTED",
        "Securities that hit their upper (H) or lower (L) price band during the day. The band itself and whether the "
        "stock stayed locked are not in the file (circuit days read the close from our own bar, X359).",
        ("F31",),
        ("raw_price_band_hits",),
        "financials.parsers.pr_bands:parse_price_band_hits",
        serves=(
            ("G207", "circuit days: one H / L row per security per day that touched its band"),
            ("G140", "band hits per day; the band percentage itself is not in the file"),
        ),
    ),
    Family(
        "NSE PR zip: bm board meetings",
        _pr("bm"),
        "NOT_INGESTED",
        "Board meetings intimated: company, symbol, meeting date and purpose (financial results, dividend, fund "
        "raising, re-scheduling).",
        ("F31",),
        serves=(("G193", "board-meeting intimations with the meeting date (forward calendar)"),),
    ),
    Family(
        "NSE PR zip: bc corporate actions (equity and debt series)",
        _pr("bc"),
        "NOT_INGESTED",
        "Record / book-closure / ex / no-delivery dates and purpose per series, including debt series (interest "
        "payment, redemption, call).",
        ("F31",),
        serves=(("G195", "scheduled interest / redemption record dates of listed debt series (not defaults)"),),
    ),
    Family(
        "NSE PR zip: an announcements",
        _pr("an"),
        "NOT_INGESTED",
        "One line per announcement: company, symbol, subject category and the summary text.",
        ("F31",),
        serves=(("G193", "subject lines such as 'Shareholders meeting' (text only, no structured date)"),),
    ),
    Family(
        "NSE PR zip: corpbond corporate bond trades",
        _pr("corpbond"),
        "NOT_INGESTED",
        "Prices, traded value / quantity and 52-week range of corporate bonds traded on the day (coupon and "
        "maturity only inside the security name).",
        ("F31",),
        serves=(
            (
                "G136",
                "secondary-market bond prices; a yield would have to be computed from the name's coupon and maturity",
            ),
        ),
    ),
    Family(
        "NSE PR zip: etf ETF market data",
        _pr("etf"),
        "NOT_INGESTED",
        "Prices, traded value / quantity and underlying index of every ETF traded.",
        ("F31",),
    ),
    Family(
        "NSE PR zip: gl gainers and losers",
        _pr("gl"),
        "NOT_INGESTED",
        "Top gainers / losers of Nifty 50, Nifty Next 50 and other securities (close, previous close, % change).",
        ("F31",),
    ),
    Family(
        "NSE PR zip: hl new 52-week highs / lows",
        _pr("hl"),
        "NOT_INGESTED",
        "Securities (equity and ETFs) at a new high or low: new and previous value, H / L.",
        ("F31",),
    ),
    Family(
        "NSE PR zip: pd security-wise market data with symbol",
        _pr("pd"),
        "NOT_INGESTED",
        "Index rows then security rows: prices, traded value / quantity, trades, 52-week range (unadjusted), with "
        "symbol and series.",
        ("F31",),
    ),
    Family(
        "NSE PR zip: pr security-wise market data",
        _pr("pr"),
        "NOT_INGESTED",
        "The pd file without symbol and series columns.",
        ("F31",),
    ),
    Family(
        "NSE PR zip: sme SME market data",
        _pr("sme"),
        "NOT_INGESTED",
        "Market data of SME securities (SME is outside the universe).",
        ("F31",),
    ),
    Family(
        "NSE PR zip: tt top 25 by traded value",
        _pr("tt"),
        "NOT_INGESTED",
        "The day's 25 securities with the highest traded value.",
        ("F31",),
    ),
    Family(
        "NSE PR zip: PE_ symbol P/E (2024 zips only)",
        _pr("PE_"),
        "NOT_INGESTED",
        "NSE's Symbol P/E and Adjusted P/E per symbol (four quarters' profit; adjusted excludes exceptional items "
        "net of tax). Present in the 2024 zips only, absent from 2025 on.",
        ("F31",),
    ),
    Family(
        "NSE PR zip: readme",
        (r"(?:pr_zip|series_switch)/PR\d{6}\.zip!(?i:readme)\.txt",),
        "REFERENCE",
        "NSE's own description of every member; the source of the per-member sentences in this catalogue.",
        ("F31",),
        document=True,
    ),
    # ── NSE corporate data (APIs, archives) ──────────────────────────────────────────────────────────────────────
    Family(
        "NSE corporate actions API",
        (r"corp_actions/nse_corporateActions_equities_[0-9-]+_[0-9-]+\.json",),
        "INGESTED",
        "Equity corporate actions of a date window: symbol, series, ISIN, face value, subject text, "
        "ex / record dates; the subject is parsed into typed components.",
        ("F03",),
        ("corp_actions", "quarantine_queue"),
        "financials.parsers.nse_corp_actions:parse_nse_corp_actions_json",
    ),
    Family(
        "NSE corporate actions RSS",
        (r"corp_actions/RSS_Corporate_action_\d{8}\.xml",),
        "NOT_INGESTED",
        "RSS items of recent corporate actions. parse_corp_action_rss exists (tests only); nothing fetches it.",
        ("F03",),
    ),
    Family(
        "NSE holiday master",
        (r"calendar/nse_holiday-master_trading_\d{8}\.json",),
        "INGESTED",
        "Trading holidays per segment (CM used).",
        ("F04",),
        ("trading_calendar",),
        "financials.calendar:parse_holiday_master",
    ),
    Family(
        "NSE Nifty 500 constituents list",
        (r"indices/ind_nifty500list_\d{8}\.csv",),
        "INGESTED",
        "Current Nifty 500 members: company, industry, symbol, series, ISIN.",
        ("F05",),
        ("raw_index_snapshot", "index_constituents_history"),
        "financials.parsers.indices:parse_index_list",
    ),
    Family(
        "NSE Indices change notices (PDF + pdftotext)",
        (r"index_changes/(?:pdf|text)/ind_prs[0-9_]+\.(?:pdf|txt)",),
        "INGESTED",
        "Index inclusion / exclusion press releases; the text is pdftotext of the PDF. Parsed into "
        "reference/nifty500_changes.csv, which backfill-index replays.",
        ("F05",),
        ("index_constituents_history",),
        "financials.index_changes:parse_change_notice",
        document=True,
    ),
    Family(
        "NSE daily index closes (ind_close_all)",
        (r"indices/ind_close_all_\d{8}\.csv",),
        "INGESTED",
        "OHLC, change, volume, turnover, P/E, P/B, dividend yield of every NSE price index.",
        ("F27",),
        ("index_ohlcv",),
        "financials.parsers.indices:parse_index_closes",
    ),
    Family(
        "NSE equity master (EQUITY_L)",
        (r"indices/nse_EQUITY_L_\d{8}\.csv",),
        "INGESTED",
        "Every listed equity: symbol, name, series, listing date, paid-up value, market lot, ISIN, face value.",
        ("F28",),
        ("raw_equity_master",),
        "financials.parsers.indices:parse_equity_master",
    ),
    Family(
        "NSE quote API industry classification",
        (r"classification/GetQuoteApi_getSymbolData_[A-Z_&]+\.json",),
        "INGESTED",
        "Quote API symbol data at fetch time: order book, trade info, price band, margins and the "
        "4-level industry classification; only the classification fields are stored.",
        ("F30",),
        ("raw_quote_classification", "entity_classification_history"),
        "financials.parsers.classification:parse_quote_classification",
        serves=(
            (
                "G207",
                "orderBook buyPrice1..5 / sellPrice1..5 and tradeInfo.impactCost (bid-ask), a snapshot "
                "at fetch time, not stored",
            ),
            ("G140", "priceInfo.priceBand, a snapshot at fetch time, not stored"),
            ("G141", "secInfo.varMargin / extremelossMargin / securityvar, a snapshot at fetch time, not stored"),
            ("G129", "tradeInfo.ffmc (free-float market cap), a snapshot at fetch time, not stored"),
        ),
    ),
    Family(
        "NSE Integrated Filing listing API",
        (
            r"discovery/nse_integrated-filing-results_equities_[A-Z]+(?:_page2)?_"
            r"\d{8}\.json",
        ),
        "INGESTED",
        "Integrated Filing rows of one symbol (Financials and Governance): period, scope, XBRL / iXBRL / "
        "PDF links, broadcast and creation times.",
        ("F06",),
        ("raw_results_listing",),
        "financials.parsers.discovery:parse_integrated_filing_listing",
    ),
    Family(
        "NSE annual report XBRL listing API",
        (
            r"(?:annual|discovery)/nse_annual-reports-xbrl_(?:equities_)?[A-Z]+_"
            r"\d{8}\.json",
        ),
        "DISCOVERY_ONLY",
        "Reg. 34 annual XBRL rows of one symbol: file link, year, broadcast time.",
        ("F07",),
        parser="financials.parsers.reg34_annual:parse_annual_listing",
    ),
    Family(
        "NSE shareholding master API",
        (
            r"(?:shareholding|discovery)/nse_corporate-share-holdings-master_"
            r"(?:equities_)?[A-Z]+_\d{8}\.json",
        ),
        "DISCOVERY_ONLY",
        "Reg. 31 filings of one symbol: as-of date, promoter / public %, XBRL link, broadcast "
        "time (the broadcast time of the SHP filing).",
        ("F08",),
        parser="financials.parsers.shareholding:parse_shp_master",
    ),
    Family(
        "NSE announcements RSS (Online_announcements)",
        (r"events/nse_Online_announcements_\d{8}\.xml",),
        "DISCOVERY_ONLY",
        "Every announcement of the day: company, attachment link (Reg. 30 XBRL for structured "
        "events), subject, broadcast time.",
        ("F21",),
        parser="financials.parsers.reg30_events:parse_announcements_rss",
    ),
    # ── NSE XBRL instances ───────────────────────────────────────────────────────────────────────────────────────
    Family(
        "NSE Integrated Filing results XBRL (Reg. 33)",
        (rf"{XBRL_DIRS}/(?:INTEGRATED_FILING_[A-Z_]+|IF_INS_COM_IND_AS_\d+_WebXMLFile|GI)_[0-9_]+(?:_WEB)?\.xml",),
        "INGESTED",
        "Quarterly / annual results of every profile (Ind AS corporate, NBFC, bank, insurers, non-Ind "
        "AS corporate; legacy GI), with segments, Reg. 23(9) RPT and disclosures.",
        ("F06", "F10"),
        (
            "filing_meta",
            "fact_observations",
            "segment_observations",
            "reg23_related_party_transactions",
            "disclosure_facts",
            "audit_opinions",
        ),
        "financials.parsers.integrated:parse_integrated_results",
        xbrl=True,
    ),
    Family(
        "NSE Reg. 34 annual report XBRL",
        (rf"{XBRL_DIRS}/AR_XBRL_[A-Z]+_\d+\.xml",),
        "INGESTED",
        "Annual report XBRL (MCA Ind AS taxonomy): statements, AOC-1 group structure, related parties, audit report.",
        ("F07",),
        (
            "filing_meta",
            "fact_observations",
            "group_structure",
            "related_party_transactions",
            "disclosure_facts",
            "audit_opinions",
        ),
        "financials.parsers.reg34_annual:parse_reg34_annual",
        xbrl=True,
    ),
    Family(
        "NSE Reg. 31 shareholding pattern XBRL",
        (rf"{XBRL_DIRS}/SHP_[0-9_]+_WEB\.xml",),
        "INGESTED",
        "Shareholding pattern: categories, holders above 1%, pledges, share counts.",
        ("F08",),
        (
            "shareholding_meta",
            "shareholding_line_items",
            "shareholding_major_holders",
            "shareholding_observations",
            "disclosure_facts",
        ),
        "financials.parsers.shareholding:parse_shareholding",
        xbrl=True,
    ),
    Family(
        "NSE Reg. 30 structured event XBRL",
        (r"events/[A-Z0-9_]+_\d+_WebXMLFile_\d{8}_\d+\.xml",),
        "INGESTED",
        "Reg. 30 events (orders, capital changes, resignations, fraud / default, litigation).",
        ("F21",),
        ("corporate_events", "disclosure_facts"),
        "financials.parsers.reg30_events:parse_reg30_event",
        xbrl=True,
    ),
    # ── BSE ──────────────────────────────────────────────────────────────────────────────────────────────────────
    Family(
        "BSE equity UDiFF bhavcopy",
        (r"bse/BhavCopy_BSE_CM_0_0_0_\d{8}_F_0000\.CSV",),
        "NOT_INGESTED",
        "BSE end-of-day prices in the UDiFF layout (FinInstrmId = BSE scrip code, ISIN per row). "
        "parse_udiff_cm(data, exchange='BSE') reads it; nothing fetches or promotes it.",
        ("F34",),
    ),
    Family(
        "BSE list of securities (ListofScripData)",
        (r"bse/bse_ListofScripData_[A-Za-z0-9_]+_\d{8}\.json",),
        "INGESTED",
        "BSE scrip code, ISIN, name, group, face value, status, industry per security (rule BSE1).",
        ("F35",),
        ("raw_bse_securities",),
        "financials.parsers.bse_securities:parse_list_securities",
    ),
    Family(
        "BSE announcements API (AnnSubCategoryGetData)",
        (r"bse/announcements\.json", r"bse/bse_AnnSubCategoryGetData_[A-Za-z0-9]+_\d{8}(?:_\d{8}|_p\d+)\.json"),
        "VAULTED_RAW",
        "Announcements: NEWSID, scrip, subject, category / subcategory, attachment name, broadcast times.",
        ("F36",),
        serves=(("G193", "categories 'Board Meeting' and 'AGM/EGM' (subject text, no structured date)"),),
    ),
    Family(
        "BSE announcement attachments (AttachLive)",
        (r"bse/AttachLive_[0-9a-f-]+\.pdf",),
        "VAULTED_RAW",
        "The PDF attached to an announcement.",
        ("F36",),
        serves=(("G62", "the announcement PDFs a keyword watcher would read"),),
    ),
    Family(
        "BSE shareholding filings listing (Corp_Shareholding_ng)",
        (r"bse/bse_Corp_Shareholding_ng_\d+_flag\d_\d{8}\.json", r"bse/shareholding_listing_\d{8}\.json"),
        "DISCOVERY_ONLY",
        "Reg. 31 filings per scrip: quarter, inline-XBRL link, broadcast time (used as the "
        "broadcast time of the BSE SHP filing).",
        ("F36",),
        parser="financials.fetch.bse:_shp_broadcast_times",
    ),
    Family(
        "BSE Reg. 31 shareholding inline XBRL",
        (r"bse/shp_\d+_\d{8}\.html\.gz", r"bse/\d+_\d+_SP\.html"),
        "INGESTED",
        "BSE's inline XBRL of the SEBI in-bse-shp taxonomy, same tables as NSE Reg. 31.",
        ("F36",),
        (
            "shareholding_meta",
            "shareholding_line_items",
            "shareholding_major_holders",
            "shareholding_observations",
            "disclosure_facts",
        ),
        "financials.parsers.shareholding:parse_shareholding",
        xbrl=True,
    ),
    Family(
        "BSE results listing (Corp_FinanceResult_ng_new)",
        (
            r"bse/bse_Corp_FinanceResult_ng_new_[a-z0-9]+_flagdur\d"
            r"_\d{8}\.json",
        ),
        "DISCOVERY_ONLY",
        "Results rows per scrip: quarter code, standalone / consolidated file names (XMLName, "
        "Consol_XMLName), creation time (the broadcast time of the BSE results filing).",
        ("F36",),
        parser="financials.fetch.bse:_results_broadcast_times",
    ),
    Family(
        "BSE results XBRL (inline .html, NBFC plain .xml)",
        (
            rf"{XBRL_DIRS}/(?:Integrated_Finance_(?:Ind_As|NBFC)|IFOtherthan)_\d+_\d+_(?:IFIndAs|IFNBFC|IFOtherthan)"
            r"\.(?:html|xml)",
        ),
        "INGESTED",
        "BSE copies of Integrated Filing results (SEBI in-capmkt taxonomy), read by the NSE path; several "
        "fixtures pin the repairs of malformed XHTML (see MANIFEST).",
        ("F36",),
        (
            "filing_meta",
            "fact_observations",
            "segment_observations",
            "reg23_related_party_transactions",
            "disclosure_facts",
            "audit_opinions",
        ),
        "financials.parsers.integrated:parse_integrated_results",
        xbrl=True,
    ),
    Family(
        "BSE announcement XBRL (CorpXbrlGen)",
        (r"bse/CorpXbrlGen_\d+_[0-9a-f-]+\.(?:xml|html)",),
        "NOT_INGESTED",
        "BSE's per-announcement XBRL (in-bse-co namespace), and its 21-byte error answer; seen by the reach probe "
        "only.",
        xbrl=True,
    ),
    Family(
        "BSE legacy results page (Comp_Resultsnew)",
        (r"bse/beta_Comp_Resultsnew_expandable\d_\d{8}\.html",),
        "NOT_INGESTED",
        "ASP.NET results search page (form fields only); seen by the reach probe only.",
    ),
    Family(
        "BSE results dropdown lists (Corp_GetFINANCE_DRDOWN_ng)",
        (r"bse/bse_Corp_GetFINANCE_DRDOWN_ng_flag\d_\d{8}\.json",),
        "NOT_INGESTED",
        "Code lists of the results page (broadcast periods, result periods); seen by the reach probe only.",
    ),
    # ── Reference ────────────────────────────────────────────────────────────────────────────────────────────────
    Family(
        "SEBI circulars (PDF + pdftotext)",
        (r"circulars/sebi_cir_\d{4}_\d+\.(?:pdf|txt)",),
        "REFERENCE",
        "Regulatory text cited as evidence (Integrated Filing format).",
        document=True,
    ),
    Family(
        "Fixture manifest",
        (r"MANIFEST\.md",),
        "REFERENCE",
        "sha256 and source URL of every fixture; per-file descriptions in this catalogue come from it.",
        document=True,
    ),
)


# ── Reading the files ────────────────────────────────────────────────────────────────────────────────────────────


@dataclass
class Entry:
    path: str  # under tests/fixtures/; "<zip>!<member>" for a zip member
    data: bytes = field(repr=False)
    gz: bool = False


def walk(root: Path = FIXTURES) -> list[Entry]:
    out: list[Entry] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        data = p.read_bytes()
        if p.suffix.lower() == ".zip":
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                out += [Entry(f"{rel}!{n}", z.read(n)) for n in sorted(z.namelist()) if not n.endswith("/")]
        elif p.suffix == ".gz":
            out.append(Entry(rel, gzip.decompress(data), gz=True))
        else:
            out.append(Entry(rel, data))
    return out


def classify(entries: list[Entry]) -> dict[str, list[Entry]]:
    """Family name -> entries; raises listing every path that matches no family or more than one."""
    groups: dict[str, list[Entry]] = {f.name: [] for f in FAMILIES}
    compiled = [(f, [re.compile(p) for p in f.patterns]) for f in FAMILIES]
    unmatched, ambiguous = [], []
    for e in entries:
        hits = [f.name for f, pats in compiled if any(p.fullmatch(e.path) for p in pats)]
        if not hits:
            unmatched.append(e.path)
        elif len(hits) > 1:
            ambiguous.append(f"{e.path}: {hits}")
        else:
            groups[hits[0]].append(e)
    if unmatched or ambiguous:
        raise ValueError(f"unclassified fixture files {unmatched}; in several families {ambiguous}")
    return groups


def _text(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _squash(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _keys(obj: dict) -> str:
    """Keys of one record, one level of nesting: `k{a, b}` for an object, `k[{a, b}]` for a list of objects."""
    parts = []
    for k, v in obj.items():
        if isinstance(v, dict) and v:
            parts.append(f"{k}{{{', '.join(map(str, v))}}}")
        elif isinstance(v, list) and v and isinstance(v[0], dict):
            parts.append(f"{k}[{{{', '.join(map(str, v[0]))}}}]")
        else:
            parts.append(str(k))
    if len(parts) > MAX_KEYS:
        parts = [*parts[:MAX_KEYS], f"… (+{len(parts) - MAX_KEYS} more)"]
    return ", ".join(parts)


def _shape(v) -> str:
    if isinstance(v, list):
        return f"list of {len(v)}"
    if isinstance(v, dict):
        return "object"
    return "scalar"


def describe(e: Entry, fam: Family) -> tuple[str, str, str]:
    """(format, rows, columns) of one entry."""
    name = e.path.rsplit("!", 1)[-1].lower()
    ext = name.rsplit(".", 1)[-1]
    if name.endswith(".html.gz"):
        ext = "html"
    fmt = {"csv": "CSV", "txt": "TXT", "json": "JSON", "xml": "XML", "html": "HTML", "pdf": "PDF", "md": "Markdown"}[
        ext
    ]
    if "!" in e.path:
        fmt += " in ZIP"
    if e.gz:
        fmt += " (gzip)"
    if fam.document or ext in ("html", "pdf"):
        if ext in ("txt", "md"):
            return fmt, f"{len(_text(e.data).splitlines())} lines", "—"
        return fmt, f"{len(e.data):,} bytes", "listed only"
    if ext == "csv":
        rows = [r for r in csv.reader(io.StringIO(_text(e.data))) if any(c.strip() for c in r)]
        return fmt, str(len(rows) - 1), ", ".join(f"`{c.strip()}`" for c in rows[0])
    if ext == "txt":
        lines = [ln for ln in _text(e.data).splitlines() if ln.strip()]
        return fmt, str(len(lines) - 1), f"header line `{_squash(lines[0])}`"
    if ext == "json":
        d = json.loads(_text(e.data))
        if isinstance(d, list):
            first = next((r for r in d if isinstance(r, dict)), None)
            return fmt, str(len(d)), f"list; record: {_keys(first)}" if first else "list"
        lists = {k: v for k, v in d.items() if isinstance(v, list)}
        top = ", ".join(f"{k} ({_shape(v)})" for k, v in d.items())
        first = next((v[0] for v in lists.values() if v and isinstance(v[0], dict)), None)
        rows = "; ".join(f"{k}: {len(v)}" for k, v in lists.items()) or "1"
        rec = _keys(first) if first is not None else _keys(d)
        return fmt, rows, f"object: {top}; record: {rec}"
    if ext == "xml":
        root = ET.fromstring(e.data)
        items = root.findall(".//item")
        if items:
            tags = list(dict.fromkeys(local(c.tag) for c in items[0]))
            return fmt + " (RSS)", str(len(items)), f"root `{local(root.tag)}`; item: {', '.join(tags)}"
        tags = list(dict.fromkeys(local(c.tag) for c in root))
        return fmt, str(len(root)), f"root `{local(root.tag)}`; children: {', '.join(tags)}"
    raise ValueError(f"no reader for {e.path}")


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


# ── Evidence the catalogue is checked against ────────────────────────────────────────────────────────────────────


def schema_tables() -> set[str]:
    return set(re.findall(r"CREATE TABLE (?:IF NOT EXISTS )?(\w+)", SCHEMA.read_text(encoding="utf-8")))


def feed_names() -> dict[str, str]:
    return {f["feed_id"]: f["name"] for f in yaml.safe_load(SOURCES_YAML.read_text(encoding="utf-8"))["feeds"]}


def requirement_status() -> dict[str, str]:
    rows = re.findall(r"^\| (G\d+) \|[^|]*\| ([A-Z_]+) \|", REQUIREMENTS.read_text(encoding="utf-8"), flags=re.M)
    return dict(rows)


def manifest_notes() -> dict[str, str]:
    """File -> the MANIFEST's second cell when it describes the file (not a bare source URL)."""
    out: dict[str, str] = {}
    for m in re.finditer(r"^\| `([^`]+)` \| (.+?) \|", MANIFEST.read_text(encoding="utf-8"), flags=re.M):
        note = m[2].strip()
        if not note.startswith("`http"):
            out.setdefault(m[1], note)
    return out


def pr_readme_sentences(entries: list[Entry]) -> dict[str, str]:
    """Member prefix (lower case: an, bc, …, pe_, readme) -> NSE's readme.txt sentence; the newest zip wins."""

    def zip_date(e: Entry) -> str:
        d = re.search(r"PR(\d\d)(\d\d)(\d\d)\.zip", e.path)
        return f"{d[3]}{d[2]}{d[1]}" if d else ""

    out: dict[str, str] = {}
    readmes = sorted((e for e in entries if e.path.lower().endswith("!readme.txt")), key=zip_date, reverse=True)
    for e in readmes:
        for line in _text(e.data).splitlines():
            m = re.match(r"^([A-Za-z_]+?)(?:ddmmyyyy|ddmmyy)\.(?:txt|csv) (?:file )?(.+)$", line.strip(), flags=re.I)
            m = m or re.match(r"^(readme)\.txt (.+)$", line.strip(), flags=re.I)
            if m:
                out.setdefault(m[1].lower(), _squash(m[0]))
    return out


def _wired(fn: str) -> bool:
    """True when `fn` is called somewhere under src/financials (any mention besides its own `def` line)."""
    uses = 0
    for p in sorted((ROOT / "src" / "financials").rglob("*.py")):
        text = p.read_text(encoding="utf-8")
        uses += len(re.findall(rf"\b{re.escape(fn)}\b", text)) - len(
            re.findall(rf"^\s*def {re.escape(fn)}\(", text, re.M)
        )
    return uses > 0


def verify() -> list[str]:
    """Problems with the hand-written FAMILIES table (empty when every claim holds)."""
    problems: list[str] = []
    tables, feeds, reqs = schema_tables(), feed_names(), requirement_status()
    names = [f.name for f in FAMILIES]
    if len(names) != len(set(names)):
        problems.append("duplicate family names")
    for f in FAMILIES:
        if f.status not in STATUSES:
            problems.append(f"{f.name}: bad status {f.status}")
        problems += [f"{f.name}: feed {s} not in data_sources.yaml" for s in f.source if s not in feeds]
        problems += [f"{f.name}: table {t} not in schema.sql" for t in f.tables if t not in tables]
        problems += [f"{f.name}: requirement {g} not in owner_requirements.md" for g, _ in f.serves if g not in reqs]
        if f.status == "INGESTED" and not (f.tables and f.parser):
            problems.append(f"{f.name}: INGESTED needs tables and a parser")
        if f.status in ("DISCOVERY_ONLY", "VAULTED_RAW", "NOT_INGESTED", "REFERENCE") and f.tables:
            problems.append(f"{f.name}: {f.status} names tables")
        if f.parser:
            module, fn = f.parser.split(":")
            path = ROOT / "src" / Path(*module.split(".")).with_suffix(".py")
            if not path.exists() or not re.search(rf"^def {re.escape(fn)}\(", path.read_text(encoding="utf-8"), re.M):
                problems.append(f"{f.name}: {f.parser} not defined")
            elif not _wired(fn):
                problems.append(f"{f.name}: {f.parser} is called from nowhere else in src/financials")
    return problems


# ── Rendering ────────────────────────────────────────────────────────────────────────────────────────────────────


def _cell(v: str) -> str:
    return (v or "—").replace("|", "\\|").replace("\n", " ")


def _serves(f: Family, reqs: dict[str, str], *, short: bool) -> str:
    if not f.serves:
        return "none identified"
    if short:
        return ", ".join(f"{g} ({reqs[g]})" for g, _ in f.serves)
    return "; ".join(f"{g} ({reqs[g]}): {why}" for g, why in f.serves)


def _anchor(name: str) -> str:
    """GitHub's heading anchor: lower case, punctuation other than `-` and `_` dropped, spaces to hyphens."""
    return re.sub(r"[^a-z0-9 _-]", "", name.lower()).replace(" ", "-")


def render(entries: list[Entry] | None = None) -> str:
    entries = walk() if entries is None else entries
    problems = verify()
    if problems:
        raise ValueError("FAMILIES table disagrees with the code: " + "; ".join(problems))
    groups = classify(entries)
    feeds, reqs, notes = feed_names(), requirement_status(), manifest_notes()
    readme = pr_readme_sentences(entries)
    files = sorted({e.path.split("!", 1)[0] for e in entries})

    out = [
        "# Data catalogue",
        "",
        "<!-- GENERATED from tests/fixtures/ by `python scripts/data_catalogue.py --write`. Do not edit. -->",
        "",
        "What every committed fixture file contains (every zip member too), which feed it belongs to, whether the "
        "pipeline ingests it, and which open owner requirement (`docs/owner_requirements.md`) its columns could serve. "
        "Check here before saying data is unavailable. Feeds: `docs/data_sources.md`; XBRL elements: "
        "`docs/tag_registry.yaml`; sha256 and source URLs: `tests/fixtures/MANIFEST.md`.",
        "",
        f"{len(files)} fixture files ({len(entries)} entries counting zip members) in {len(FAMILIES)} families; "
        "0 unclassified (the generator fails on a file that matches no family).",
        "",
        "Status: " + "; ".join(f"**{k}** {v}" for k, v in STATUSES.items()) + ".",
        "",
        "## Summary",
        "",
        "| Family | Example fixture | Source | Status | Table | Could serve |",
        "|---|---|---|---|---|---|",
    ]
    for f in FAMILIES:
        ex = groups[f.name][0].path
        out.append(
            f"| [{_cell(f.name)}](#{_anchor(f.name)}) | `{_cell(ex)}` | {_cell(', '.join(f.source))} | {f.status} | "
            f"{_cell(', '.join(f.tables))} | {_cell(_serves(f, reqs, short=True))} |"
        )
    for f in FAMILIES:
        es = groups[f.name]
        out += ["", f"## {f.name}", "", "| Field | Value |", "|---|---|"]
        out.append(f"| Content | {_cell(f.note)} |")
        prefix = None
        m = re.search(r"\(\?i:([A-Za-z_]+)\)", f.patterns[0]) if "PR\\d" in f.patterns[0] else None
        if m:
            prefix = m[1].lower()
            out.append(f"| NSE readme.txt | {_cell(readme.get(prefix, 'not described in any readme.txt'))} |")
        out.append(f"| Source | {_cell('; '.join(f'{s} ({feeds[s]})' for s in f.source))} |")
        out.append(f"| Status | {f.status} |")
        out.append(f"| Tables | {_cell(', '.join(f'`{t}`' for t in f.tables))} |")
        out.append(f"| Parser | {_cell(f'`{f.parser}`' if f.parser else '')} |")
        out.append(f"| Could serve | {_cell(_serves(f, reqs, short=False))} |")
        out.append(f"| Files | {len(es)} |")
        if f.xbrl:
            by_dir: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
            for e in es:
                d, _, name = e.path.rpartition("/")
                by_dir[d][describe(e, f)[0] if not name.endswith(".xml") else "XML"] += 1
            out += ["", "XBRL instances: elements are not listed here; see `docs/tag_registry.yaml`.", "",
                    "| Directory | Files | Formats |", "|---|---|---|"]  # fmt: skip
            out += [
                f"| `{d}/` | {sum(c.values())} | {', '.join(f'{k} {n}' for k, n in sorted(c.items()))} |"
                for d, c in sorted(by_dir.items())
            ]
            continue
        described = [(e, *describe(e, f)) for e in es]
        by_cols: dict[str, list] = defaultdict(list)
        for row in described:
            by_cols[row[3]].append(row)
        for cols, rows in sorted(by_cols.items(), key=lambda kv: kv[1][0][0].path):
            if cols not in ("—", "listed only"):
                lead = "Columns" if len(by_cols) == 1 else f"Columns ({len(rows)} of {len(es)} files)"
                out += ["", f"{lead}: {cols}"]
        out += ["", "| File | Format | Rows | Description |", "|---|---|---|---|"]
        for e, fmt, rows, _cols in described:
            desc = notes.get(e.path.split("!", 1)[0], "")
            pr = re.search(r"PR(\d\d)(\d\d)(\d\d)\.zip!", e.path)
            if pr:  # the MANIFEST row describes the whole zip (mostly its mcap member), not this member
                desc = f"member of the PR zip of trade date 20{pr[3]}-{pr[2]}-{pr[1]}"
            out.append(f"| `{_cell(e.path)}` | {fmt} | {rows} | {_cell(desc)} |")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="data_catalogue", description=__doc__.splitlines()[0])
    p.add_argument("--write", action="store_true", help="write docs/data_catalogue.md")
    args = p.parse_args(argv)
    text = render()
    if args.write:
        MD_PATH.write_text(text, encoding="utf-8")
        return 0
    sys.stdout.write(text)
    current = MD_PATH.read_text(encoding="utf-8") if MD_PATH.exists() else ""
    if current != text:
        print("docs/data_catalogue.md is stale: run python scripts/data_catalogue.py --write", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
