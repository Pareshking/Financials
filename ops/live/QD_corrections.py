"""QD PDF corrections (owner decision B, X107): HGS Q2 FY27 other intangible assets read from the filing's own
signed results PDF.

Usage: python ops/live/QD_corrections.py data/market.duckdb [--dry-run]
The Q2 FY27 XBRL files OtherIntangibleAssets including the right-of-use assets the balance sheet prints on its own
line (consolidated 1,321.71 = 391.40 + 930.31 Cr; standalone 676.87 = 37.40 + 639.47 Cr). Total assets are unaffected;
`other_intangibles` feeds intangibles_to_equity. The right-of-use line has no canonical tag, so nothing else changes."""

import sys

from financials.admin import correct_from_pdf
from financials.db import connect

PDF = "https://nsearchives.nseindia.com/corporate/HGSN_12112026212120_HGSSEOUTCOME12NOV2026.pdf"
# (filing, value_inr, page, printed text, reads, note)
R = [
    ("fil_b36eacacc3dfb68558135ad6", "3914000000.00", 13,
     "Balance Sheet (Rs. in crore) As at 30.09.2026 | 31.03.2026: Right of use assets | 930.31 | 963.54 / "
     "Other Intangible assets | 391.40 | 426.35",
     "TEXT+PAGE_IMAGE",
     "HGS Q2 FY27 consolidated balance sheet 30.09.2026: other intangible assets 391.40 Cr; XBRL 1,321.71 Cr = "
     "391.40 + right of use 930.31"),
    ("fil_66440ad92631e4266320c3d4", "374000000.00", 9,
     "Balance Sheet (Rs. in Crore) As at 30.09.2026 | 31.03.2026: Right of use assets | 639.47 | 704.84 / "
     "Other Intangible assets | 37.40 | 45.43",
     "PAGE_IMAGE+XBRL_MINUS_PRINTED_ROU",
     "HGS Q2 FY27 standalone balance sheet 30.09.2026: other intangible assets 37.40 Cr; XBRL 676.87 Cr = "
     "37.40 + right of use 639.47"),
]


def main(db: str, dry: bool) -> None:
    con = connect(db)
    try:
        for fid, value, page, text, reads, note in R:
            print(fid, "other_intangibles", "2026-09-30", value)
            if dry:
                continue
            ids = correct_from_pdf(
                con, fid,
                [{"canonical_tag": "other_intangibles", "period_start": "2026-09-30", "period_end": "2026-09-30",
                  "value_inr": value}],
                evidence_url=PDF, evidence_page=page, evidence_text=text, reads=reads, note="QD: " + note,
            )  # fmt: skip
            print("  corrections", ids)
    finally:
        con.close()


if __name__ == "__main__":
    main(sys.argv[1], "--dry-run" in sys.argv)
