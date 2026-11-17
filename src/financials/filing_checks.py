"""Per-filing consistency and identity checks run by the promoter after a results / annual filing is promoted.

- G328 [X110]: a Reg. 34 annual report's prior-year columns are compared with the figures already stored for that
  fiscal year (what a point-in-time reader saw just before the annual report became visible). A difference beyond
  the rounding of the two filings is a non-blocking CONSISTENCY / ANNUAL_PRIOR_YEAR_DIFFERS finding: the restated
  comparative is kept as filed (it is that filing's fact, visible from its broadcast), nothing is corrected.
- G79 [X111]: the BSE scrip code stated inside a results filing (`ScripCode`, X7; from disclosure_facts) fills
  `security_identifier_history.bse_scrip_code` of the NSE identifier rows that match the filing's own ISIN and
  symbol. A different code already on such a row is an IDENTIFIER / BSE_SCRIP_CODE_CONFLICT finding; nothing is
  overwritten.
- Rule SC0 [X171]: an all-zero scrip code (`000000`, what a filer types when it states no BSE code) is no code: a
  filed one fills nothing and raises nothing, and a stored one (written before SC0) counts as empty, so the next real
  code fills it without a conflict.

The promoter (single writer) owns the transaction; these helpers return findings for it to queue.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from financials.db import version_key
from financials.money import ROUNDING_UNITS

PRIOR_YEAR_REASON = "ANNUAL_PRIOR_YEAR_DIFFERS"
SCRIP_CONFLICT_REASON = "BSE_SCRIP_CODE_CONFLICT"
# `oth_*` tags are free-text "Others" rows keyed by per-filing member ids (`…Subsidiaries16Member` is another company
# in another year's report), so the same tag is not the same line across two filings; never compared.
_NOT_COMPARABLE_PREFIX = "oth\\_%"


def annual_prior_year_differences(
    con,
    *,
    filing_id: str,
    parser_version: str,
    entity_id: str,
    scope: str,
    fy_start: date,
    level_of_rounding: str,
    visible_from_ts: datetime,
) -> list[dict]:
    """Rupee facts of this annual filing for periods ending before its own fiscal year (the prior-year columns),
    each compared with the value a reader had for that tag and period one microsecond before this filing became
    visible (`load_factbook`: results outrank the annual report on P&L lines [X100], latest version wins). Tolerance:
    half a LevelOfRounding unit of each side (this filing's unit, the coarsest unit among the stored filings)."""
    from financials.fundamentals import load_factbook

    rows = con.execute(
        "SELECT canonical_tag, period_type, period_start, period_end, value_inr FROM fact_observations "
        "WHERE filing_id = ? AND parser_version = ? AND value_inr IS NOT NULL AND period_end < ? "
        "AND canonical_tag NOT LIKE ? ESCAPE '\\' ORDER BY canonical_tag, period_type, period_start, period_end",
        [filing_id, parser_version, fy_start, _NOT_COMPARABLE_PREFIX],
    ).fetchall()
    if not rows:
        return []
    book = load_factbook(con, entity_id, scope, visible_from_ts - timedelta(microseconds=1))
    tol = (book.rounding_unit + ROUNDING_UNITS[level_of_rounding]) / 2
    out = []
    for tag, ptype, start, end, value in rows:
        stored = (
            book.instants.get(tag, {}).get(end) if ptype == "INSTANT" else book.durations.get(tag, {}).get((start, end))
        )
        if stored is None:
            continue
        diff = Decimal(value) - stored
        if abs(diff) > tol:
            out.append({"tag": tag, "period_type": ptype, "period": [str(start), str(end)], "annual": str(value),
                        "stored": str(stored), "difference": str(diff), "tolerance": str(tol)})  # fmt: skip
    return out


SC0_RULE = "SC0"


def scrip_code(text: str | None) -> str | None:
    """Rule SC0 [X171]: a BSE scrip code as sent, or None when blank, not all digits, or all zeros (a placeholder)."""
    code = (text or "").strip()
    return code if code.isdigit() and code.strip("0") else None


def filed_scrip_code(con, filing_id: str) -> str | None:
    """The filing's non-dimensional `ScripCode` as sent, when it is one all-digit value. Read from disclosure_facts
    (X116: no other clean table holds the element; the filing's highest disclosure parser version)."""
    vals = {
        (v or "").strip()
        for (v,) in con.execute(
            f"""SELECT value_text FROM disclosure_facts WHERE filing_id = ? AND element = 'ScripCode'
                AND dimensions IS NULL
                QUALIFY dense_rank() OVER (ORDER BY {version_key()} DESC) = 1""",
            [filing_id],
        ).fetchall()
    }
    vals.discard("")
    if len(vals) != 1:
        return None
    return scrip_code(vals.pop())


def apply_bse_scrip_code(
    con, *, exchange: str, entity_id: str, isin: str | None, symbol: str | None, code: str | None
) -> list[dict]:
    """Fill `bse_scrip_code` on the entity's identifier rows whose ISIN and symbol both equal the filing's (identity
    already resolved on both keys); returns the conflicting rows (a different code already stored)."""
    if not code or not isin or not symbol:
        return []
    rows = con.execute(
        "SELECT h.security_id, h.valid_from, h.bse_scrip_code FROM security_identifier_history h "
        "JOIN securities s USING (security_id) WHERE s.entity_id = ? AND h.exchange = ? AND h.isin = ? "
        "AND h.symbol = ? ORDER BY h.security_id, h.valid_from",
        [entity_id, exchange, isin, symbol],
    ).fetchall()
    conflicts = [
        {"security_id": sec, "valid_from": str(vf), "stored": old, "filed": code, "isin": isin, "symbol": symbol}
        for sec, vf, old in rows
        if scrip_code(old) is not None and old != code
    ]
    if any(scrip_code(old) is None for _, _, old in rows):  # SC0: a stored all-zero code is empty
        con.execute(
            "UPDATE security_identifier_history SET bse_scrip_code = ? WHERE exchange = ? AND isin = ? AND symbol = ? "
            f"AND {_EMPTY_CODE} AND security_id IN (SELECT security_id FROM securities WHERE entity_id = ?)",
            [code, exchange, isin, symbol, entity_id],
        )
    return conflicts


BSE1_RULE = "BSE1"
# SC0 in SQL: no code stored, or an all-zero placeholder (any length)
_EMPTY_CODE = "(bse_scrip_code IS NULL OR NOT regexp_matches(bse_scrip_code, '[1-9]'))"


def apply_bse_scrip_codes_by_isin(con, filing_id: str) -> tuple[int, list[dict]]:
    """Rule BSE1 [X169]: a BSE list-of-securities filing (raw_bse_securities) fills `bse_scrip_code` on every non-BSE
    identifier row whose ISIN equals a listed row's ISIN and whose interval covers the list's observed date. An ISIN
    listed with two codes in the filing is skipped; a different code already stored is kept and returned as a
    conflict (IDENTIFIER / BSE_SCRIP_CODE_CONFLICT, as G79). Keyed on ISIN + scrip code, never on a ticker: works for a
    BSE-only company too once it has identifier rows. Batched: one read, one update."""
    rows = con.execute(
        """WITH b AS (
             SELECT isin, any_value(scrip_code) AS code, any_value(observed_date) AS d, count(DISTINCT scrip_code) AS n
             FROM raw_bse_securities WHERE filing_id = ? GROUP BY isin)
           SELECT h.security_id, h.exchange, h.valid_from, h.symbol, h.isin, h.bse_scrip_code, b.code
           FROM b JOIN security_identifier_history h ON h.isin = b.isin AND h.exchange <> 'BSE'
                AND h.valid_from <= b.d AND (h.valid_to IS NULL OR h.valid_to > b.d)
           WHERE b.n = 1 ORDER BY h.security_id, h.valid_from""",
        [filing_id],
    ).fetchall()
    conflicts = [
        {"security_id": sec, "valid_from": str(vf), "stored": old, "filed": code, "isin": isin, "symbol": sym,
         "rule": BSE1_RULE}
        for sec, _ex, vf, sym, isin, old, code in rows if scrip_code(old) is not None and old != code
    ]  # fmt: skip
    todo = sum(scrip_code(old) is None for *_, old, _code in rows)
    if todo:
        con.execute(
            """UPDATE security_identifier_history h SET bse_scrip_code = b.code
               FROM (SELECT isin, any_value(scrip_code) AS code, any_value(observed_date) AS d
                     FROM raw_bse_securities WHERE filing_id = ? GROUP BY isin
                     HAVING count(DISTINCT scrip_code) = 1) b
               WHERE h.isin = b.isin AND h.exchange <> 'BSE' AND (h.bse_scrip_code IS NULL
                     OR NOT regexp_matches(h.bse_scrip_code, '[1-9]'))
                 AND h.valid_from <= b.d AND (h.valid_to IS NULL OR h.valid_to > b.d)""",
            [filing_id],
        )
    return todo, conflicts
