"""Stdlib-only readers for fixture evidence tests (not production parsers)."""

from __future__ import annotations

import csv
import io
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
XBRL_DIR = FIXTURES / "xbrl"
BHAV_DIR = FIXTURES / "bhavcopy"

XBRLI = "http://www.xbrl.org/2003/instance"

CORP = XBRL_DIR / "INTEGRATED_FILING_INDAS_1753867_05112026061857_WEB.xml"
NBFC = XBRL_DIR / "INTEGRATED_FILING_NBFC_INDAS_1757118_13112026023256_WEB.xml"
BANK = XBRL_DIR / "INTEGRATED_FILING_BANKING_1699494_22072026061940_WEB.xml"
GEN_INS = XBRL_DIR / "GI_117901_1363602_28012025065616.xml"


@dataclass(frozen=True)
class Context:
    id: str
    start: str | None
    end: str | None
    instant: str | None
    has_dimensions: bool


@dataclass
class Instance:
    namespaces: dict[str, str]
    contexts: dict[str, Context]
    numeric: dict[tuple[str, str], Decimal]  # (local element name, contextRef) -> value
    text: dict[tuple[str, str], str]


def load_instance(path: Path) -> Instance:
    namespaces = {p: u for _, (p, u) in ET.iterparse(path, events=("start-ns",))}
    root = ET.parse(path).getroot()
    contexts: dict[str, Context] = {}
    for c in root.findall(f"{{{XBRLI}}}context"):
        period = c.find(f"{{{XBRLI}}}period")
        assert period is not None

        def txt(tag: str, period: ET.Element = period) -> str | None:
            el = period.find(f"{{{XBRLI}}}{tag}")
            return el.text.strip() if el is not None and el.text else None

        contexts[c.get("id")] = Context(
            id=c.get("id"),
            start=txt("startDate"),
            end=txt("endDate"),
            instant=txt("instant"),
            has_dimensions=c.find(f".//{{{XBRLI}}}segment") is not None,
        )
    numeric: dict[tuple[str, str], Decimal] = {}
    text: dict[tuple[str, str], str] = {}
    for el in root:
        ctx = el.get("contextRef")
        if not ctx:
            continue
        name = el.tag.split("}", 1)[1]
        value = (el.text or "").strip()
        if el.get("unitRef"):
            numeric[(name, ctx)] = Decimal(value)
        else:
            text[(name, ctx)] = value
    return Instance(namespaces, contexts, numeric, text)


def load_udiff(yyyymmdd: str) -> dict[str, dict[str, str]]:
    """UDiFF CM bhavcopy rows for EQ/BE/BZ series, keyed by ticker symbol."""
    path = BHAV_DIR / f"BhavCopy_NSE_CM_0_0_0_{yyyymmdd}_F_0000.csv.zip"
    with zipfile.ZipFile(path) as zf:
        (name,) = zf.namelist()
        reader = csv.DictReader(io.TextIOWrapper(zf.open(name), encoding="utf-8"))
        return {r["TckrSymb"]: r for r in reader if r["SctySrs"] in ("EQ", "BE", "BZ")}


def load_sec_bhavdata_full(ddmmyyyy: str) -> tuple[list[str], dict[tuple[str, str], dict[str, str]]]:
    path = BHAV_DIR / f"sec_bhavdata_full_{ddmmyyyy}.csv"
    with path.open(encoding="utf-8") as fh:
        reader = csv.reader(fh, skipinitialspace=True)
        header = [h.strip() for h in next(reader)]
        rows = {}
        for raw in reader:
            row = dict(zip(header, (v.strip() for v in raw), strict=False))
            rows[(row["SYMBOL"], row["SERIES"])] = row
    return header, rows
