"""load-kpis: KPI file -> staging -> promote -> supplemental_kpis -> screener_features -> DSL, point in time.

The KPI values are test inputs (not company data); the symbols are real so identity resolves on the 12 Nov 2026
bhavcopy.
"""

from __future__ import annotations

import io
import json

import pytest
from conftest import Market

from financials.cli import main
from financials.parsers.kpis import parse_kpis

SRC = "https://example.invalid/"
HEADER = "symbol,kpi,period_start,period_end,value,unit,source_kind,source_url,visible_from_utc,notes"
P = "INVESTOR_PRESENTATION"
Q2 = ("2026-07-01", "2026-09-30")
H1 = ("2026-04-01", "2026-09-30")


def _row(sym, kpi, period, value, unit, kind, doc, seen, note=""):
    return ",".join([sym, kpi, *period, value, unit, kind, SRC + doc, seen, note])


CSV = (
    "\n".join(
        [
            HEADER,
            _row("ETERNAL", "gov", Q2, "250000000000", "INR", P, "q2.pdf", "2026-10-21T12:00:00"),
            _row("ETERNAL", "net_take_rate", Q2, "0.21", "RATIO", P, "q2.pdf", "2026-10-21T12:00:00", "alias"),
            _row(
                "ETERNAL",
                "take_rate",
                ("2026-04-01", "2026-06-30"),
                "0.19",
                "RATIO",
                P,
                "q1.pdf",
                "2026-07-21T12:00:00",
                "older",
            ),
            _row("HDFCLIFE", "vnb_margin", H1, "0.255", "RATIO", P, "h1.pdf", "2026-10-15T12:00:00"),
            _row(
                "HDFCLIFE",
                "persistency_13m",
                H1,
                "0.87",
                "RATIO",
                "IRDAI_PUBLIC_DISCLOSURE",
                "pd.pdf",
                "2026-11-15T12:00:00",
                "after as-of",
            ),
            _row(
                "HDFCLIFE",
                "embedded_value",
                H1,
                "600000000000",
                "RATIO",
                P,
                "h1.pdf",
                "2026-10-15T12:00:00",
                "wrong unit",
            ),
            _row("NOSUCHCO", "nrr", H1, "1.1", "RATIO", "MANUAL", "x", "2026-10-01T00:00:00", "unknown symbol"),
        ]
    )
    + "\n"
)


def test_parser_validates_units_names_and_visibility():
    rows = parse_kpis(CSV.encode())
    assert [r.issue for r in rows] == [None, None, None, None, None, "WRONG_UNIT", None]
    assert rows[1].kpi == "take_rate"  # net_take_rate alias
    bad = parse_kpis(b"[{\"symbol\": \"X\", \"kpi\": \"nrr\", \"period_start\": \"2026-04-01\", \"period_end\": "
                     b"\"2026-09-30\", \"value\": \"1\", \"unit\": \"RATIO\", \"source_kind\": \"MANUAL\", "
                     b"\"source_url\": \"u\", \"visible_from_utc\": \"2026-09-01T00:00:00\"}]")  # fmt: skip
    assert bad[0].issue == "VISIBLE_BEFORE_PERIOD_END"


@pytest.fixture
def kpi_db(tmp_path):
    m = Market(tmp_path)
    m.stage_day("20261112")
    m.con.close()
    path = tmp_path / "kpis.csv"
    path.write_text(CSV, encoding="utf-8")
    out = io.StringIO()
    assert main(["--data-dir", str(tmp_path), "load-kpis", str(path)], out=out) == 0
    assert "staged kpis/" in out.getvalue()
    assert main(["--data-dir", str(tmp_path), "promote"], out=(log := io.StringIO())) == 0, log.getvalue()
    assert "PROMOTED         kpis" in log.getvalue() and "5 KPI rows" in log.getvalue()
    assert main(["--data-dir", str(tmp_path), "materialize", "2026-11-12"], out=io.StringIO()) == 0
    return tmp_path


def screen(data, query, *extra):
    out = io.StringIO()
    assert main(["--data-dir", str(data), "screen", query, *extra], out=out) == 0, out.getvalue()
    return json.loads(out.getvalue())


def test_round_trip_into_features_and_screens(kpi_db):
    rows = screen(kpi_db, "Net take rate > 20 AND GOV > 1000")
    assert [(r["symbol"], r["net take rate"], r["gov"]) for r in rows] == [("ETERNAL", 21.0, 25000)]  # latest quarter
    (hdfc,) = screen(kpi_db, "VNB margin > 25")
    assert hdfc["symbol"] == "HDFCLIFE"
    assert screen(kpi_db, "Persistency 13m > 0") == []  # published 15 Nov: not visible on 12 Nov
    assert screen(kpi_db, "Embedded value > 0") == []  # its row was quarantined (wrong unit)
    assert screen(kpi_db, "NRR > 0") == []  # unknown symbol: quarantined


def test_rejected_rows_are_quarantined(kpi_db):
    out = io.StringIO()
    main(["--data-dir", str(kpi_db), "quarantine", "list", "--stage", "KPI"], out=out)
    assert sorted(r["reason_code"] for r in json.loads(out.getvalue())) == ["UNKNOWN_SYMBOL", "WRONG_UNIT"]
