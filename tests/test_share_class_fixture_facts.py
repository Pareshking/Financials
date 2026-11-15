"""P17 (R10 corrected): DVR and partly-paid securities in the committed UDiFF bhavcopy of 2026-11-12 (all series).

- Partly paid: `IN9` ISINs in series E1, named "... PPD UP" (6 securities); E1 is outside the v1 universe
  (EQ/BE/BZ), so the identity registry never creates them. Every E1 row is one of them.
- DVR: symbol contains "DVR"; two carry `IN9` ISINs (JISLDVREQS EQ, FELDVR BZ), one an `INE` ISIN (GATECHDVR EQ),
  so "DVR shares use INE ISINs" (R10, owner review G306) does not hold.
- Every one of these 9 secondary securities shares the issuer code (ISIN characters 4-7) with the issuer's
  ordinary share listed the same day, where that share trades on the mainboard or SME segment.
"""

from __future__ import annotations

import csv
import io
import zipfile

from _fixture_helpers import BHAV_DIR
from financials.identity import UNIVERSE_SERIES


def _rows() -> list[dict[str, str]]:
    with zipfile.ZipFile(BHAV_DIR / "BhavCopy_NSE_CM_0_0_0_20261112_F_0000.csv.zip") as zf:
        (name,) = zf.namelist()
        return list(csv.DictReader(io.TextIOWrapper(zf.open(name), encoding="utf-8")))


def test_partly_paid_and_dvr_isins_and_series():
    rows = _rows()
    in9 = {r["TckrSymb"]: (r["ISIN"], r["SctySrs"]) for r in rows if r["ISIN"].startswith("IN9")}
    partly = {s for s, (_, series) in in9.items() if series == "E1"}
    assert partly == {"ATLPP", "CENTEXTPP", "JAYKAYPP", "OLAPP", "PARTYPP", "ROCKPP"}
    assert {r["TckrSymb"] for r in rows if r["SctySrs"] == "E1"} == partly
    assert all("PPD UP" in r["FinInstrmNm"] for r in rows if r["SctySrs"] == "E1")
    dvr = {r["TckrSymb"]: (r["ISIN"], r["SctySrs"]) for r in rows if "DVR" in r["TckrSymb"]}
    assert dvr == {
        "JISLDVREQS": ("IN9175A01010", "EQ"),
        "FELDVR": ("IN9623B01058", "BZ"),
        "GATECHDVR": ("INE224E01036", "EQ"),
    }
    assert set(in9) == partly | {"JISLDVREQS", "FELDVR"}
    assert "E1" not in UNIVERSE_SERIES


def test_secondary_classes_share_the_issuer_code_of_the_ordinary_share():
    rows = _rows()
    secondary = [r for r in rows if r["ISIN"].startswith("IN9") or "DVR" in r["TckrSymb"]]
    ordinary = {r["ISIN"][3:7]: r for r in rows if r["ISIN"].startswith("INE") and "DVR" not in r["TckrSymb"]}
    pairs = {r["TckrSymb"]: ordinary[r["ISIN"][3:7]]["TckrSymb"] for r in secondary if r["ISIN"][3:7] in ordinary}
    assert pairs == {
        "ATLPP": "ATL", "CENTEXTPP": "CENTEXT", "JAYKAYPP": "JAYKAY", "OLAPP": "OLAELEC", "PARTYPP": "PARTYCRUS",
        "ROCKPP": "ROCKINGDCE", "JISLDVREQS": "JISLJALEQS", "FELDVR": "FEL", "GATECHDVR": "GATECH",
    }  # fmt: skip
