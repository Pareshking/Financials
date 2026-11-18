"""Batch H: NSE industry classification [IC1-IC3], peer columns (G96, G112, G199, G334), AOC-1 group structure
[X112], and the scheduling files (G40, G60, G289)."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from decimal import Decimal

import pytest
from conftest import Market

from _fixture_helpers import FIXTURES, XBRL_DIR
from financials import features_peers as P
from financials.cli import build_parser, main
from financials.db import declared_columns
from financials.features_store import write_rows as write_history
from financials.fetch.jobs import Jobs, quote_url
from financials.group_structure import backfill_group_structure, pending_filings
from financials.parsers import ParseError
from financials.parsers.aoc1 import parse_group_structure
from financials.parsers.classification import parse_quote_classification
from financials.parsers.reg34_annual import parse_reg34_annual
from financials.parsers.xbrl import parse_instance
from financials.promoter import promote
from financials.sources import ROOT
from financials.staging import stage_classification, stage_results_xbrl

CLS = FIXTURES / "classification"
OBSERVED = datetime(2026, 11, 13, 9, 0)  # UTC -> IST 2026-11-13


def _fixture(sym: str) -> bytes:
    return (CLS / f"GetQuoteApi_getSymbolData_{sym}.json").read_bytes()


# ── IC1 / IC2: the quote answer carries four levels (characterisation of real answers) ──────────────────────────────


@pytest.mark.parametrize(
    ("sym", "symbol", "isin", "levels"),
    [
        ("TCS", "TCS", "INE467B01029",
         ("Information Technology", "Information Technology", "IT - Software", "Computers - Software & Consulting")),
        ("HDFCBANK", "HDFCBANK", "INE040A01034",
         ("Financial Services", "Financial Services", "Banks", "Private Sector Bank")),
        ("M_M", "M&M", "INE101A01026",
         ("Consumer Discretionary", "Automobile and Auto Components", "Automobiles",
          "Passenger Cars & Utility Vehicles")),
    ],
)  # fmt: skip
def test_quote_answer_carries_the_four_level_classification(sym, symbol, isin, levels):
    c = parse_quote_classification(_fixture(sym))
    assert (c.symbol, c.series, c.isin) == (symbol, "EQ", isin)
    assert c.levels == levels
    assert c.last_update_ist == datetime(2026, 11, 13, 16, 0)


def test_quote_answer_without_sec_info_is_a_parse_error():
    with pytest.raises(ParseError):
        parse_quote_classification(b'{"equityResponse": [{"metaData": {"symbol": "X"}}]}')
    with pytest.raises(ParseError):
        parse_quote_classification(b"<HTML>Access Denied</HTML>")


def test_quote_url_encodes_the_symbol():
    assert quote_url("M&M").endswith("series=EQ&symbol=M%26M")
    assert "functionName=getSymbolData&marketType=N" in quote_url("TCS")


# ── promotion: date-bounded, point in time from the fetch ───────────────────────────────────────────────────────


def _synthetic(sym_file: str, **sec) -> bytes:
    """A real answer with secInfo levels replaced (to exercise the history rules; fixtures stay untouched)."""
    doc = json.loads(_fixture(sym_file))
    doc["equityResponse"][0]["secInfo"].update(sec)
    return json.dumps(doc).encode()


@pytest.fixture(scope="module")
def cls_market(tmp_path_factory):
    m = Market(tmp_path_factory.mktemp("cls_market"))
    assert promote(m.con, m.stage_day("20261112")).status == "PROMOTED"
    for sym in ("TCS", "HDFCBANK", "M_M"):
        url = f"https://www.nseindia.com/api/fixture/{sym}"
        r = promote(m.con, stage_classification(m.vault, m.stage_root, data=_fixture(sym), source_url=url,
                                                fetched_at=OBSERVED))  # fmt: skip
        assert r.status == "PROMOTED", r
    yield m
    m.con.close()


def _history(m: Market, symbol: str) -> list[tuple]:
    return m.con.execute(
        "SELECT c.industry, c.basic_industry, c.valid_from, c.valid_to FROM entity_classification_history c "
        "WHERE c.entity_id = (SELECT DISTINCT s.entity_id FROM securities s JOIN security_identifier_history h "
        "USING (security_id) WHERE h.symbol = ?) ORDER BY c.valid_from", [symbol]).fetchall()  # fmt: skip


def test_classification_is_promoted_with_raw_row_and_history(cls_market):
    m = cls_market
    raw = m.con.execute("SELECT symbol, isin, basic_industry, observed_date, quote_update_ts FROM "
                        "raw_quote_classification ORDER BY symbol").fetchall()  # fmt: skip
    assert [r[0] for r in raw] == ["HDFCBANK", "M&M", "TCS"]
    assert raw[2][2:] == ("Computers - Software & Consulting", date(2026, 11, 13), datetime(2026, 11, 13, 10, 30))
    assert _history(m, "M&M") == [("Automobiles", "Passenger Cars & Utility Vehicles", date(2026, 11, 13), None)]


def test_classification_is_point_in_time_from_its_first_fetch(cls_market):
    m = cls_market
    ts = datetime(2026, 11, 13, 18, 30)  # end of 13 Nov IST
    on = P.classifications(m.con, date(2026, 11, 13), ts)
    assert len(on) == 3
    assert P.classifications(m.con, date(2026, 11, 12), datetime(2026, 11, 12, 18, 30)) == {}  # never backdated


def test_same_answer_again_changes_nothing_and_a_new_one_closes_the_interval(tmp_path):
    m = Market(tmp_path)
    promote(m.con, m.stage_day("20261112"))
    url = "https://www.nseindia.com/api/fixture/TCS"

    def put(data: bytes, ts: datetime):
        return promote(m.con, stage_classification(m.vault, m.stage_root, data=data, source_url=url, fetched_at=ts))

    assert put(_fixture("TCS"), OBSERVED).status == "PROMOTED"
    assert "unchanged" in put(_synthetic("TCS"), datetime(2026, 11, 14, 9)).message  # same levels, new bytes
    moved = _synthetic("TCS", industryInfo="IT - Services", basicIndustry="IT Enabled Services")
    assert put(moved, datetime(2026, 11, 20, 9)).status == "PROMOTED"
    assert _history(m, "TCS") == [
        ("IT - Software", "Computers - Software & Consulting", date(2026, 11, 13), date(2026, 11, 20)),
        ("IT - Services", "IT Enabled Services", date(2026, 11, 20), None),
    ]
    # A different answer on the open interval's own date (or older) is a conflict for a human, not a silent rewrite.
    other = _synthetic("TCS", basicIndustry="Something Else")
    r = put(other, datetime(2026, 11, 20, 11))
    assert r.status == "QUARANTINED"
    assert m.con.execute("SELECT reason_code FROM quarantine_queue WHERE stage = 'CLASSIFICATION'").fetchall() == [
        ("CLASSIFICATION_CONFLICT",)
    ]
    assert len(_history(m, "TCS")) == 2
    assert m.con.execute("SELECT count(*) FROM materialize_dirty WHERE reason = 'CLASSIFICATION'").fetchone()[0] == 2
    m.con.close()


def test_unknown_isin_is_quarantined(tmp_path):
    m = Market(tmp_path)  # no market day: nothing to resolve against
    url = "https://www.nseindia.com/api/fixture/TCS"
    r = promote(m.con, stage_classification(m.vault, m.stage_root, data=_fixture("TCS"), source_url=url,
                                            fetched_at=OBSERVED))  # fmt: skip
    assert r.status == "QUARANTINED"
    assert m.con.execute("SELECT count(*) FROM entity_classification_history").fetchone()[0] == 0
    m.con.close()


def test_fetch_job_vaults_and_stages_one_answer_per_symbol(tmp_path):
    from financials.fetch.http import PoliteFetcher, Response
    from financials.vault import Vault

    class Fake:
        def __init__(self):
            self.urls = []

        def get(self, url, headers, timeout):
            self.urls.append(url)
            if "symbol=NOPE" in url:
                return Response(404, b"")
            sym = "M_M" if "M%26M" in url else url.rsplit("=", 1)[1]
            return Response(200, _fixture(sym))

    t = Fake()
    jobs = Jobs(PoliteFetcher(t, sleep=lambda s: None, max_attempts=1), Vault(tmp_path / "v"), tmp_path / "s")
    staged, errors = jobs.classification(["TCS", "M&M", "NOPE"], {"TCS": "EQ"})
    assert len(staged) == 2 and len(errors) == 1 and "NOPE" in errors[0]
    assert all(u.startswith("https://www.nseindia.in/api/NextApi/apiClient/GetQuoteApi?") for u in t.urls)
    assert {p.parent.name for p in staged} == {"classification"}


# ── peer columns ──────────────────────────────────────────────────────────────────────────────────────────────


def _row(sid, ent, ind, basic, mcap, pe, pb=None, roce=None, growth=None, pg=None, group=None):
    return {"security_id": sid, "entity_id": ent, "nse_industry": ind, "nse_basic_industry": basic, "industry": group,
            "market_cap": None if mcap is None else Decimal(mcap), "pe": pe, "pb": pb, "roce": roce,
            "sales_growth_yoy": growth, "profit_growth_yoy_quarter_pct": pg}  # fmt: skip


def _day() -> list[dict]:
    return [
        _row("a", "A", "Banks", "Private Sector Bank", 900, 20.0, 3.0, 0.10, 0.10, 0.20, "Financial Services"),
        _row("b", "B", "Banks", "Private Sector Bank", 500, 10.0, 1.0, 0.20, 0.30, 0.05, "Financial Services"),
        _row("c", "C", "Banks", "Private Sector Bank", 300, -5.0, 0.5, 0.05, 0.20, None, "Financial Services"),
        _row("c2", "C", "Banks", "Private Sector Bank", 100, -5.0, 0.5, 0.05, 0.20, None, "Financial Services"),
        _row("d", "D", "Banks", "Public Sector Bank", 800, 8.0, 1.2, 0.15, 0.05, 0.10, "Financial Services"),
        _row("e", "E", "Banks", "Public Sector Bank", 50, 12.0, 0.9, None, 0.15, 0.30, None),
        _row("x", "X", None, None, 100, 30.0, 4.0, 0.30, 0.25, 0.10, "Financial Services"),
    ]


def test_industry_and_basic_industry_medians_premiums_and_ranks():
    rows = _day()
    P.cross_section(rows)
    by = {r["security_id"]: r for r in rows}
    a = by["a"]
    # industry Banks: companies A, B, C, D, E (C once, by its larger security). PE > 0: 20, 10, 8, 12 -> 11
    assert a["industry_pe_median"] == 11.0
    assert a["industry_pb_median"] == 1.0  # 3, 1, 0.5, 1.2, 0.9
    assert a["industry_roce_median"] == pytest.approx(0.125)  # 0.10, 0.20, 0.05, 0.15 (E has none)
    assert a["industry_sales_growth_median"] == 0.15
    # basic industry Private Sector Bank: A, B, C; PE > 0 only 20 and 10 -> fewer than MIN_PEERS -> NULL
    assert a["basic_industry_pe_median"] is None
    assert a["basic_industry_pb_median"] == 1.0
    assert a["pe_premium_to_industry"] == pytest.approx(20 / 11 - 1)
    assert a["pb_premium_to_basic_industry"] == pytest.approx(2.0)
    assert by["c"]["pe_premium_to_industry"] is None  # a loss-maker has no PE premium
    assert (a["peer_count"], by["c2"]["peer_count"], by["d"]["peer_count"]) == (3, 3, 2)
    assert (a["peer_rank_market_cap"], by["b"]["peer_rank_market_cap"], by["c"]["peer_rank_market_cap"]) == (1, 2, 3)
    assert by["c2"]["peer_rank_market_cap"] == 3  # its own company's other class is not a peer
    assert (a["peer_rank_pe"], by["b"]["peer_rank_pe"], by["c"]["peer_rank_pe"]) == (2, 1, None)
    assert (a["peer_rank_roce"], by["b"]["peer_rank_roce"]) == (2, 1)
    assert (a["peer_rank_profit_growth"], by["d"]["peer_rank_profit_growth"]) == (1, 2)
    # unclassified: NULL NSE columns, but the Nifty 500 industry-group fallback is computed separately
    x = by["x"]
    assert x["industry_pe_median"] is None and x["peer_count"] is None and x["peer_rank_pe"] is None
    assert x["industry_group_pe_median"] == 15.0  # Financial Services: A 20, B 10, D 8, X 30 (C < 0, E no group)
    assert x["pe_premium_to_industry_group"] == pytest.approx(1.0)
    assert by["e"]["industry_group_pe_median"] is None  # not in the Nifty 500 file: no fallback either


def test_columns_are_declared_as_one_block_in_both_feature_tables():
    cols = declared_columns()
    for table in ("screener_features",):  # the history view has its columns (test_features_store)
        names = [c for c, _ in cols[table]]
        start = min(names.index(c) for c in P.COLUMNS)  # one contiguous block (later batches append after it)
        assert set(names[start : start + len(P.COLUMNS)]) == set(P.COLUMNS), table


def test_refresh_ranks_the_stored_day(tmp_path):
    from financials.db import apply_schema, connect

    con = connect(tmp_path / "x.duckdb")
    apply_schema(con)
    day = date(2026, 11, 13)
    stored = [{**r, "as_of_date": day, "symbol": r["security_id"].upper(), "series": "EQ"} for r in _day()]
    write_history(con, stored)
    P.refresh_cross_section(con, day)
    got = dict(con.execute("SELECT security_id, peer_rank_market_cap FROM screener_features_history").fetchall())
    expected = _day()
    P.cross_section(expected)
    assert got == {r["security_id"]: r["peer_rank_market_cap"] for r in expected}
    assert con.execute("SELECT industry_pe_median FROM screener_features_history WHERE security_id = 'a'").fetchone()[
        0
    ] == pytest.approx(11.0)
    con.close()


def test_compute_rows_reads_the_classification_point_in_time(cls_market):
    from financials.features import compute_rows

    rows = {r["symbol"]: r for r in compute_rows(cls_market.con, date(2026, 11, 13))}
    assert rows["HDFCBANK"]["nse_basic_industry"] == "Private Sector Bank"
    assert rows["M&M"]["nse_sector"] == "Automobile and Auto Components"
    assert rows["TCS"]["nse_macro_sector"] == "Information Technology"
    assert rows["TCS"]["peer_count"] == 1 and rows["TCS"]["industry_pe_median"] is None  # one company: no median
    assert rows["INFY"]["nse_industry"] is None and rows["INFY"]["peer_rank_market_cap"] is None
    before = {r["symbol"]: r for r in compute_rows(cls_market.con, date(2026, 11, 12))}
    assert before["TCS"]["nse_industry"] is None


# ── AOC-1 group structure [X112] ────────────────────────────────────────────────────────────────────────────────

CUMMINS = "AR_XBRL_CUMMINSIND_04092026113534.xml"
TCS_FY26 = "AR_XBRL_TCS_09082026012216.xml"


def _group(name: str):
    data = (XBRL_DIR / name).read_bytes()
    parsed = parse_reg34_annual(data, name)
    return parse_group_structure(parse_instance(data), set(parsed.meta["in_scope_instants"]))


def test_aoc1_subsidiary_associate_and_joint_venture_rows():
    rows = _group(CUMMINS)
    fy25, fy26 = date(2025, 3, 31), date(2026, 3, 31)
    by = {(g.relation, g.period_end): g for g in rows}
    assert sorted(by) == sorted([("SUBSIDIARY", fy25), ("ASSOCIATE", fy25), ("ASSOCIATE", fy26),
                                 ("JOINT_VENTURE", fy25), ("JOINT_VENTURE", fy26)])  # fmt: skip
    sub = by[("SUBSIDIARY", fy25)]  # FY26: WhetherCompanyHasSubsidiaryCompanies = false, no row
    assert (sub.name, sub.cin, sub.country) == ("PAL JAY POWER SOLUTIONS PRIVATE LIMITED", "U29190DL2012PTC230162",
                                                "INDIA")  # fmt: skip
    assert sub.holding_fraction == Decimal("1")
    assert sub.net_worth_inr == Decimal("120000000") + Decimal("315800000")
    assert (sub.turnover_inr, sub.pat_inr) == (Decimal("2004000000"), Decimal("81900000"))
    assoc = by[("ASSOCIATE", fy26)]
    assert (assoc.name, assoc.cin, assoc.holding_fraction, assoc.investment_inr) == (
        "CUMMINS GENERATOR TECHNOLOGIES INDIA PRIVATE LIMITED", "U31101PN1991PTC061456", Decimal("0.4874"),
        Decimal("172000000"))  # fmt: skip
    jv = by[("JOINT_VENTURE", fy26)]
    assert (jv.name, jv.cin, jv.holding_fraction) == ("VALVOLINE CUMMINS PRIVATE LIMITED", "U74899DL1994PTC062425",
                                                      None)  # no ownership element filed  # fmt: skip


def test_aoc1_rows_are_per_year_and_keep_the_filed_member():
    rows = _group(TCS_FY26)
    assert sum(g.period_end == date(2026, 3, 31) for g in rows) == 67
    assert sum(g.period_end == date(2025, 3, 31) for g in rows) == 53  # FY24 comparatives are out of scope (C9)
    apt = next(g for g in rows if g.name == "APTOnline Limited" and g.period_end == date(2025, 3, 31))
    assert (apt.row_member, apt.cin, apt.holding_fraction) == ("Subsidiaries 01 [Member]", "U75142TG2002PLC039671",
                                                               Decimal("0.89"))  # fmt: skip
    assert all(g.relation == "SUBSIDIARY" for g in rows)


def test_group_structure_is_promoted_with_the_annual_filing_and_backfilled(market):
    for day in ("20251023", "20261112"):  # CUMMINSIND must be known on the broadcast date
        promote(market.con, market.stage_day(day))
    r = promote(market.con, stage_results_xbrl(
        market.vault, market.stage_root, data=(XBRL_DIR / CUMMINS).read_bytes(),
        source_url="https://nsearchives.nseindia.com/corporate/xbrl/" + CUMMINS, fetched_at=datetime(2026, 11, 14, 6),
        broadcast_ts=datetime(2026, 9, 4, 6, 5), broadcast_ts_source="API_FIELD"))  # fmt: skip
    assert r.status == "PROMOTED"
    rows = market.con.execute(
        "SELECT g.relation, g.period_end, g.name, g.holding_fraction, g.scope, g.visible_from_ts = m.visible_from_ts "
        "FROM group_structure g JOIN filing_meta m USING (filing_id, entity_id) ORDER BY 2, 1").fetchall()  # fmt: skip
    assert len(rows) == 5 and all(r[4] == "CONSOLIDATED" and r[5] for r in rows)
    assert pending_filings(market.con) == []
    market.con.execute("DELETE FROM group_structure")  # as if promoted before batch H
    assert len(pending_filings(market.con)) == 1
    result = backfill_group_structure(market.con, market.vault)
    assert (result["filings"], result["rows"], result["error_count"]) == (1, 5, 0)
    assert market.con.execute("SELECT count(*) FROM group_structure").fetchone()[0] == 5
    assert backfill_group_structure(market.con, market.vault)["filings"] == 0  # idempotent


# ── scheduling (G40, G60, G289) ───────────────────────────────────────────────────────────────────────────────

OPS = ROOT / "ops"


def test_schedule_files_call_existing_cli_commands():
    commands = set(build_parser()._subparsers._group_actions[0].choices)
    files = sorted(p for p in OPS.rglob("*") if p.is_file() and p.suffix in (".service", ".timer", ".xml", ".cron"))
    assert {p.suffix for p in files} == {".service", ".timer", ".xml", ".cron"}
    used = set()
    for p in files:
        text = p.read_text(encoding="utf-16" if p.suffix == ".xml" else "utf-8")
        used |= set(re.findall(r"-m financials (?:--data-dir \S+ )?([a-z][a-z-]+)", text))
    assert used and used <= commands, used - commands
    assert {"run-day", "materialize"} <= used
    for p in files:
        text = p.read_text(encoding="utf-16" if p.suffix == ".xml" else "utf-8")
        if "materialize" in text:
            assert "--incremental" in text, p


def test_run_day_without_a_date_is_allowed_and_skips_publishing_a_holiday(tmp_path):
    from conftest import FETCHED_AT

    from financials.staging import stage_holidays

    assert build_parser().parse_args(["run-day"]).date is None
    m = Market(tmp_path)
    hol = FIXTURES / "calendar" / "nse_holiday-master_trading_20261113.json"
    promote(m.con, stage_holidays(m.vault, m.stage_root, data=hol.read_bytes(), source_url="h", fetched_at=FETCHED_AT))
    m.con.close()

    class Offline:
        def get(self, url, headers, timeout):
            from financials.fetch.http import Response

            if "holiday-master" in url:
                return Response(200, hol.read_bytes())
            return Response(404, b"")

    import io

    out = io.StringIO()
    main(["--data-dir", str(tmp_path), "run-day", "--date", "2026-11-14", "--lookback-days", "0"],
         transport=Offline(), out=out)  # fmt: skip
    assert "2026-11-14: not a trading day; nothing to materialise" in out.getvalue()


def test_quote_answer_without_metadata_is_a_parse_error_not_a_crash():
    """STLTECH's quote answer had `metaData: null` (2026-11-16): ParseError, not AttributeError."""
    import json

    from financials.parsers import ParseError
    from financials.parsers.classification import parse_quote_classification

    doc = json.loads((FIXTURES / "classification" / "GetQuoteApi_getSymbolData_TCS.json").read_bytes())
    doc["equityResponse"][0]["metaData"] = None
    with pytest.raises(ParseError):
        parse_quote_classification(json.dumps(doc).encode())
