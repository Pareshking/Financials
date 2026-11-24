"""QD2 PDF corrections (owner decision B, X107): filer XBRL values read from the filing's own signed results PDF.

Usage: python ops/live/QD2_corrections.py data/market.duckdb [--dry-run]

1. NPST (Network People Services) Q2 FY27, H1 FY27 cash flow: the XBRL classifies the bank deposits (Rs 17,729 /
   17,724 lakh) and part of financing differently from the printed statement; every version ties to the same net
   change ((21,225) standalone, (21,833) consolidated lakh), the PDF is the signed statement.
2. MIDHANI Q2 FY27 paid-up equity share capital: the XBRL P&L section files 18,374 lakh (183.74 Cr) for the printed
   18,734.00 lakh (digit transposition; the balance-sheet equity share capital in the same XBRL is 18,734 lakh and
   Reg. 31 has 18.734 Cr shares of Rs 10).
Pages and lines were read twice (page image + text / crop at 160 dpi)."""

import sys

from financials.admin import correct_from_pdf
from financials.db import connect

NPST = "https://nsearchives.nseindia.com/corporate/NPST_12112026153921_BM_Outcome_11112026_signed.pdf"
MIDHANI = "https://nsearchives.nseindia.com/corporate/MIDHANI_11112026174041_MDN_Outcome_BM_11112026.pdf"
H1 = ("2026-04-01", "2026-09-30")
Q2 = ("2026-07-01", "2026-09-30")
# (filing, evidence url, page, printed text, reads, note, [(tag, (start, end), value_inr)])
R = [
    (
        "fil_c365e142a7eb4005dd189272",
        NPST,
        9,
        "Unaudited Standalone Statement of Cash Flow for the Half Year ended September 30, 2026 (Figures in Lakhs), "
        "Half year ended September 30, 2026: Cash Generated from Operations 2 / Direct Tax (550) / Net Cash From/(Used "
        "In) "
        "Operating Activities (A) (548) / Net Cash From/(Used In) Investing Activities (B) (19,972) / Net Cash From "
        "Financing Activities (C) (705) / Net Increase/(Decrease) in Cash (A)+(B)+(C) (21,225)",
        "PAGE_IMAGE+CROP",
        "NPST H1 FY27 standalone cash flow: XBRL CFO (18,245) / CFI (2,581) / CFF (399) / CGO (18,267) lakh; "
        "the signed statement prints (548) / (19,972) / (705) / 2 (net change (21,225) in both)",
        [
            ("cfo", H1, "-54800000.00"),
            ("cfi", H1, "-1997200000.00"),
            ("cff", H1, "-70500000.00"),
            ("cash_generated_from_operations", H1, "200000.00"),
        ],
    ),
    (
        "fil_24e8366c361f4931ed6e6771",
        NPST,
        16,
        "Consolidated Statement of Cash Flow for the Half Year ended September 30, 2026 (Figures in Lakhs), Half year "
        "ended September 30, 2026: Cash Generated from Operations (1,041) / Direct Tax (550) / Net Cash From/(Used In) "
        "Operating Activities (A) (1,591) / Net Cash From/(Used In) Investing Activities (B) (19,536) / Net Cash From "
        "Financing Activities (c) (706) / Net Increase/(Decrease) in Cash (A)+(B)+(C) (21,833)",
        "PAGE_IMAGE+CROP",
        "NPST H1 FY27 consolidated cash flow: XBRL CFO (23,286) / CFI 1,849 / CFF (396) / CGO (22,736) lakh; "
        "the signed statement prints (1,591) / (19,536) / (706) / (1,041) (net change (21,833) in both)",
        [
            ("cfo", H1, "-159100000.00"),
            ("cfi", H1, "-1953600000.00"),
            ("cff", H1, "-70600000.00"),
            ("cash_generated_from_operations", H1, "-104100000.00"),
        ],
    ),
    (
        "fil_3acaaa0439a8aea4516ae06c",
        MIDHANI,
        7,
        "(i) Standalone Results (Rs in lakh): 12 Paid-up equity share capital (Face value of Rs 10/- each) 18,734.00 "
        "in "
        "every column (30.09.2026 ... 31.03.2026)",
        "TEXT+PAGE_IMAGE",
        "MIDHANI Q2 FY27 standalone paid-up capital 18,734.00 lakh; XBRL 18,374 lakh (digit transposition; "
        "balance-sheet equity share capital in the same XBRL 18,734 lakh)",
        [("paid_up_equity_capital", Q2, "1873400000.00"), ("paid_up_equity_capital", H1, "1873400000.00")],
    ),
    (
        "fil_b6d3b03bc367744402d18751",
        MIDHANI,
        8,
        "(ii) Consolidated Results (Rs in lakh): 14 Paid-up equity share capital (Face value of Rs 10/- each) "
        "18,734.00 "
        "in every column",
        "PAGE_IMAGE+TEXT",
        "MIDHANI Q2 FY27 consolidated paid-up capital 18,734.00 lakh; XBRL 18,374 lakh (digit transposition)",
        [("paid_up_equity_capital", Q2, "1873400000.00"), ("paid_up_equity_capital", H1, "1873400000.00")],
    ),
]


# MIDHANI 30-Sep-2026 share cross-check (paid-up / face value 183,740,000 vs Reg. 31 187,340,000): CORRECTED
QID = {"fil_b6d3b03bc367744402d18751": "q_848209141a5a4f34d0c95423"}


def main(db: str, dry: bool) -> None:
    con = connect(db)
    try:
        for fid, url, page, text, reads, note, rows in R:
            for tag, (s, e), v in rows:
                print(fid, tag, s, e, v)
            if dry:
                continue
            ids = correct_from_pdf(
                con, fid,
                [{"canonical_tag": tag, "period_start": s, "period_end": e, "value_inr": v} for tag, (s, e), v in rows],
                evidence_url=url, evidence_page=page, evidence_text=text, reads=reads, note="QD2: " + note,
                quarantine_id=QID.get(fid),
            )  # fmt: skip
            print("  corrections", ids)
    finally:
        con.close()


if __name__ == "__main__":
    main(sys.argv[1], "--dry-run" in sys.argv)
