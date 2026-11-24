"""QC2 PDF corrections (owner decision B, X107): owners / NCI read from Beta Drugs' signed consolidated results PDFs.

Usage: python ops/live/QC2_corrections.py data/market.duckdb [--dry-run]
The XBRL files owners 0 and the NCI with a negative sign (the PDF prints the NCI share in brackets because it is
deducted: owners = PAT - NCI). X214 cannot settle Beta: EPS is on weighted shares after the Q2 allotment (paid-up
10.69 -> 11.12 Cr), 0.5-1.5% away from period-end shares. Each correction resolves its ATTRIBUTION_WITHHELD finding."""

import sys

from financials.admin import correct_from_pdf
from financials.db import connect

C = "https://nsearchives.nseindia.com/corporate/"
Q1_TEXT = (
    "XV. Net Profit/(Loss) for the period before NCI (XI+XIV) | 16,48,57,255.03 / "
    "XVI. Non-Controlling Interests | (68,39,006.75) / "
    "XVII. Net Profit/(Loss) for the period after NCI (XV+XVI) | 15,80,18,248.27"
)
Q2_TEXT = (
    "XV. Net Profit/(Loss) for the period before NCI (XI+XIV) | 19,28,44,738.41 | 16,48,57,255.03 | "
    "12,21,79,453.80 | 35,77,01,993.43 / "
    "XVI. Non-Controlling Interests | (73,37,663.58) | (68,39,006.75) | - | (1,41,76,670.34) / "
    "XVII. Net Profit/(Loss) for the period after NCI (XV+XVI) | 18,55,07,074.82 | 15,80,18,248.27 | "
    "12,21,79,453.80 | 34,35,25,323.10"
)
READS = "PAGE_IMAGE+PRINTED_OWNERS_PLUS_NCI_EQUALS_PAT"
# (filing, period start, end, owners, NCI, pdf, page, text, note)
R = [
    ("fil_61627b3a118949e9d202a08e", "2026-04-01", "2026-06-30", "158018248.27", "6839006.75",
     "BETA_20072026133909_financial_results_30_june_2026.pdf", 6, Q1_TEXT,
     "Beta Drugs Q1 FY27 consolidated (3 months ended 30.06.2026, col 1), rupees; XBRL owners 0, NCI -6,839,000; the "
     "Q2 FY27 PDF prints the same Q1 column"),
    ("fil_2330d3d2c9942ad496f03204", "2026-07-01", "2026-09-30", "185507074.82", "7337663.58",
     "BETA_22102026172849_financial_results_sept.pdf", 7, Q2_TEXT,
     "Beta Drugs Q2 FY27 consolidated (3 months ended 30.09.2026, col 1), rupees; XBRL owners 0, NCI -7,337,000"),
    ("fil_2330d3d2c9942ad496f03204", "2026-04-01", "2026-09-30", "343525323.10", "14176670.34",
     "BETA_22102026172849_financial_results_sept.pdf", 7, Q2_TEXT,
     "Beta Drugs H1 FY27 consolidated (6 months ended 30.09.2026, col 4), rupees; XBRL owners 0, NCI -14,176,000; "
     "the press release in the same PDF: H1 PAT 'excluding minority interest' INR 34.3 Crs"),
]


def main(db: str, dry: bool) -> None:
    con = connect(db)
    try:
        for fid, a, b, own, nci, pdf, page, text, note in R:
            q = con.execute(
                "SELECT quarantine_id FROM quarantine_queue WHERE filing_id = ? "
                "AND reason_code = 'ATTRIBUTION_WITHHELD' AND resolved_at IS NULL "
                "AND json_extract_string(details, '$.period[0]') = ? "
                "AND json_extract_string(details, '$.period[1]') = ?",
                [fid, a, b],
            ).fetchone()
            print(fid, a, b, own, nci, "finding", q)
            if dry:
                continue
            ids = correct_from_pdf(
                con, fid,
                [{"canonical_tag": "pat_owners", "period_start": a, "period_end": b, "value_inr": own},
                 {"canonical_tag": "pat_nci", "period_start": a, "period_end": b, "value_inr": nci}],
                evidence_url=C + pdf, evidence_page=page, evidence_text=text, reads=READS, note="QC2: " + note,
                quarantine_id=q[0] if q else None,
            )  # fmt: skip
            print("  corrections", ids)
    finally:
        con.close()


if __name__ == "__main__":
    main(sys.argv[1], "--dry-run" in sys.argv)
