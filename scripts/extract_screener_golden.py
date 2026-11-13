"""Extract the 'Data Sheet' tab of Screener Excel exports into JSON goldens for the parity harness.

    python scripts/extract_screener_golden.py EXPORT.xlsx [...] --out data/screener_golden

Output stays under data/ (gitignored): the repository is public and Screener's data must not be
redistributed. Only the sha256 of each export and of each JSON is recorded in tests/fixtures/MANIFEST.md.
The extraction is verbatim: every non-empty Data Sheet row, numbers as stored, dates as ISO strings.
Requires openpyxl (not a project dependency; local use only).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

SECTIONS = {"META", "PROFIT & LOSS", "Quarters", "BALANCE SHEET", "CASH FLOW:", "PRICE:", "DERIVED:"}


def extract(path: Path) -> dict:
    import openpyxl

    ws = openpyxl.load_workbook(path, data_only=False)["Data Sheet"]
    out: dict = {"company": ws["B1"].value, "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                 "sections": {}}  # fmt: skip
    section = None
    for row in ws.iter_rows(values_only=True):
        if row[0] is None:
            continue
        key = str(row[0]).strip()
        cells = [v.date().isoformat() if isinstance(v, dt.datetime) else v for v in row[1:]]
        if key in SECTIONS:
            section = key
            out["sections"][section] = {"PRICE": cells} if key == "PRICE:" else {}
        elif section is not None:
            out["sections"][section][key] = cells
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("files", nargs="+", type=Path)
    p.add_argument("--out", type=Path, default=Path("data/screener_golden"))
    args = p.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    for f in args.files:
        d = extract(f)
        name = "".join(c if c.isalnum() else "_" for c in d["company"]).strip("_")
        target = args.out / f"{name}.json"
        target.write_text(json.dumps(d, indent=1, sort_keys=True, default=str), encoding="utf-8")
        print(f"{d['source_sha256']}  {hashlib.sha256(target.read_bytes()).hexdigest()}  {target.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
