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

# Audit-opinion evidence (MANIFEST.md "Audit opinions", X121-X124): read by tests/test_audit_opinions.py and the
# per-file coverage / registry tests; the end-to-end fixture market (test_phase1_phase2_e2e) leaves them out so its
# pinned counts and screens stay those of the filings it was built for.
AUDIT_OPINION_FIXTURES = frozenset({
    "AR_XBRL_BEML_13012026164812.xml",
    "AR_XBRL_CONCOR_11022026153323.xml",
    "AR_XBRL_IDEA_19092025180318.xml",
    "AR_XBRL_JPPOWER_13012026113224.xml",
    "AR_XBRL_MFSL_17102025125715.xml",
    "AR_XBRL_MMTC_11022026110533.xml",
    "AR_XBRL_MTARTECH_13012026142914.xml",
    "AR_XBRL_OIL_17102025191837.xml",
    "AR_XBRL_RELINFRA_06092025221939.xml",
    "AR_XBRL_RELINFRA_18092026172005.xml",
    "AR_XBRL_RKFORGE_24102025122553.xml",
    "AR_XBRL_RPOWER_06092025221905.xml",
    "AR_XBRL_SUNTV_13012026154758.xml",
    "AR_XBRL_SWANCORP_13012026103454.xml",
    "AR_XBRL_TITAGARH_13012026105336.xml",
    "AR_XBRL_VARROC_02092026142002.xml",
    "AR_XBRL_VENTIVE_23092025192320.xml",
    "INTEGRATED_FILING_INDAS_1449896_24052025124314_WEB.xml",
    "INTEGRATED_FILING_INDAS_1461165_30052025115826_WEB.xml",
    "INTEGRATED_FILING_INDAS_1461904_01062025070430_WEB.xml",
    "INTEGRATED_FILING_INDAS_1672152_23052026112720_WEB.xml",
    "INTEGRATED_FILING_INDAS_1707551_04082026041230_WEB.xml",
    "INTEGRATED_FILING_INDAS_1758732_14112026091104_WEB.xml",
})  # fmt: skip


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
