"""SHP16-SHP18 on real Reg. 31 filings (docs/references.md):

- SHP16: the 2022-09-30 taxonomy (RELIANCE Q4 FY25) references the entity contexts `OneD` / `OneI` without declaring
  them; only those two ids under that namespace are read, as period-less entity facts; the 5-row FPI-limit table
  flattened into `OneI` stays in raw but is not reachable by key.
- SHP17: pre-listing / allotment patterns date every category context on DateOfListing (CMPDI) / DateOfAllotment
  (ECLERX), not on DateOfReport.
- SHP18: percentages are percent points when the filing's TOTAL pct is 100 (old taxonomy, and RELIANCE Jun 2025 in
  the 2025-05-31 taxonomy), fractions when it is 1; stored as fractions either way.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from _fixture_helpers import XBRL_DIR
from financials.parsers import ParseError
from financials.parsers.shareholding import SHP16_CONTEXTS, parse_shareholding, shp_instance
from financials.parsers.xbrl import parse_instance

REL_Q4FY25 = "SHP_198754_1421266_21042025041033_WEB.xml"
REL_JUN25 = "SHP_1489727_21072025081003_WEB.xml"
CMPDI_LISTING = "SHP_1643664_30032026100841_WEB.xml"
ECLERX_ALLOTMENT = "SHP_1600790_14012026043343_WEB.xml"


def _read(name: str) -> bytes:
    return (XBRL_DIR / name).read_bytes()


def test_shp16_old_taxonomy_undeclared_contexts_only_under_the_rule():
    data = _read(REL_Q4FY25)
    with pytest.raises(ParseError, match="unknown context OneD"):
        parse_instance(data)
    inst, applied = shp_instance(data)
    assert applied
    for cid in SHP16_CONTEXTS:
        c = inst.contexts[cid]
        assert c.dimensions == () and c.instant is None and c.start is None and c.end is None
    assert inst.first_text("ISIN") == "INE002A01018" and inst.first_text("DateOfReport") == "2025-03-31"
    rows = [f for f in inst.facts if f.name == "PercentageOfLimitsUtilized" and f.context_id == "OneI"]
    assert len(rows) == 5 and inst.get("PercentageOfLimitsUtilized", "OneI") is None  # raw keeps all 5 rows


def test_shp16_is_not_granted_to_other_namespaces():
    data = _read(REL_JUN25).replace(b'contextRef="MainD"', b'contextRef="OneD"', 1)  # in-memory only
    with pytest.raises(ParseError, match="unknown context OneD"):
        shp_instance(data)


def test_reliance_q4_fy25_parses_with_percent_scale():
    p = parse_shareholding(_read(REL_Q4FY25))
    assert p.ok and p.meta["as_of_date"] == date(2025, 3, 31)
    assert p.meta["rules_applied"] == ["SHP16_UNDECLARED_ENTITY_CONTEXTS", "SHP18_PERCENT_SCALE"]
    c = p.categories
    assert c["TOTAL"]["shares"] == 13_532_372_898 and c["TOTAL"]["pct"] == 1
    assert c["PROMOTER"]["shares"] == 6_645_496_096 and c["PROMOTER"]["pct"] == Decimal("0.5011")
    assert c["PUBLIC"]["pct"] == Decimal("0.4989") and c["FPI_CAT1"]["pct"] == Decimal("0.1825")  # "Catergory" member
    # SHP9 denominator holds: 6,645,496,096 / (13,532,372,898 - 269,806,428 DR shares) = 0.50107
    den = c["TOTAL"]["shares"] - c["DR_CUSTODIAN"]["shares"]
    assert abs(c["PROMOTER"]["shares"] / den - c["PROMOTER"]["pct"]) < Decimal("0.0001")
    gic = next(h for h in p.major_holders if h["holder_name"] == "Government of Singapore")
    assert gic["pct"] == Decimal("0.0122")


def test_shp18_percent_scale_inside_the_2025_05_31_taxonomy():
    p = parse_shareholding(_read(REL_JUN25))
    assert p.ok and p.meta["rules_applied"] == ["SHP18_PERCENT_SCALE"]
    assert p.categories["TOTAL"]["pct"] == 1 and p.categories["PROMOTER"]["pct"] == Decimal("0.5007")
    lic = next(h for h in p.major_holders if h["holder_name"] == "Life Insurance Corporation of India")
    assert lic["pct"] == Decimal("0.0693")


@pytest.mark.parametrize(
    ("name", "event", "reported", "promoter_pct"),
    [
        (CMPDI_LISTING, date(2026, 3, 30), "2026-03-25", Decimal("0.85")),  # DateOfListing
        (ECLERX_ALLOTMENT, date(2026, 1, 7), "2026-01-09", Decimal("0.5452")),  # DateOfAllotment
    ],
)
def test_shp17_event_dated_patterns(name, event, reported, promoter_pct):
    p = parse_shareholding(_read(name))
    assert p.ok, p.issues
    assert p.meta["as_of_date"] == event and p.meta["stated_date_of_report"] == reported
    assert p.meta["rules_applied"] == ["SHP17_EVENT_DATED"]
    assert p.categories["PROMOTER"]["pct"] == promoter_pct


def test_shp17_needs_the_declared_event_date():
    data = _read(CMPDI_LISTING).replace(b">2026-03-30</in-bse-shp:DateOfListing>",
                                        b">2026-03-31</in-bse-shp:DateOfListing>")  # fmt: skip
    p = parse_shareholding(data)
    assert {i.reason_code for i in p.issues} >= {"CONTEXT_CONFLICT"}
