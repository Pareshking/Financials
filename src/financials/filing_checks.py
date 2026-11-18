"""Per-filing consistency and identity checks run by the promoter after a results / annual filing is promoted.

- G328 [X110]: a Reg. 34 annual report's prior-year columns are compared with the figures already stored for that
  fiscal year (what a point-in-time reader saw just before the annual report became visible). A difference beyond
  the rounding of the two filings is a non-blocking CONSISTENCY / ANNUAL_PRIOR_YEAR_DIFFERS finding: the restated
  comparative is kept as filed (it is that filing's fact, visible from its broadcast), nothing is corrected.
  X182: every such finding carries a deterministic class for triage (`prior_year_class`): SCALE (a line differs by
  an exact power of ten: a unit error in one of the two filings), RESTATED (a statement total differs), else
  REGROUPED (the totals agree; detail lines moved between captions, Schedule III "regrouped / reclassified").
  X233-X234: a RESTATED finding carries a sub-class: RECLASSIFIED / DISCONTINUED_REPRESENTED when PAT, total equity
  and net cash flow all agree (the totals moved, the bottom lines did not), else CASH_FLOW_RESTATED or
  BOTTOM_LINE_RESTATED. X235: the annual's own active corrections (rule X201 rescale, decision B) replace its filed
  values in the comparison.
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
from financials.money import ROUNDING_UNITS, rounding_only_tolerance

PRIOR_YEAR_REASON = "ANNUAL_PRIOR_YEAR_DIFFERS"
SCRIP_CONFLICT_REASON = "BSE_SCRIP_CODE_CONFLICT"
# `oth_*` tags are free-text "Others" rows keyed by per-filing member ids (`…Subsidiaries16Member` is another company
# in another year's report), so the same tag is not the same line across two filings; never compared.
_NOT_COMPARABLE_PREFIX = "oth\\_%"
# X182: the statement totals whose change makes a comparative a restatement rather than a regrouping.
PRIOR_YEAR_TOTALS = frozenset({
    "total_assets", "total_equity_and_liabilities", "total_equity", "total_income", "total_expenses", "pbt", "pat",
    "cfo", "cfi", "cff", "net_cash_flow",
})  # fmt: skip
# X233-X234: the bottom lines whose agreement proves a RESTATED finding is a reclassification; the sub-classes a
# reviewer may accept on that proof (owner decision 2026-11-18, delegated).
BOTTOM_LINES = ("pat", "total_equity", "net_cash_flow")
DISCONTINUED_PROFIT_TAG = "pat_discontinued"
RESTATED_ACCEPTABLE = frozenset({"RECLASSIFIED", "DISCONTINUED_REPRESENTED"})
_SCALE_FACTORS = tuple(Decimal(10) ** k for k in range(1, 8))
_SCALE_SLACK = Decimal("0.001")  # relative: 40,197,100,000 vs 401,971,000 is exactly 100x (KUANTUM FY26 vs FY25)


def annual_prior_year_comparison(
    con,
    *,
    filing_id: str,
    parser_version: str,
    entity_id: str,
    scope: str,
    fy_start: date,
    level_of_rounding: str,
    visible_from_ts: datetime,
) -> tuple[list[dict], dict]:
    """Rupee facts of this annual filing for periods ending before its own fiscal year (the prior-year columns),
    each compared with the value a reader had for that tag and period one microsecond before this filing became
    visible (`load_factbook`: results outrank the annual report on P&L lines [X100], latest version wins). Tolerance:
    half a LevelOfRounding unit of each side (this filing's unit, the coarsest unit among the stored filings): rule
    ROUNDING_ONLY [X260] for two figures.
    The filing's own active corrections (decision B, rule X201) replace its filed values (X235): a rescaled annual is
    compared at its corrected scale. Returns (differences, context): context holds the tags compared on both sides
    (`compared`) and whether the filing states a non-zero prior-year profit from discontinued operations
    (`discontinued_filed`), which `prior_year_class` needs for the RESTATED sub-classes."""
    from financials.fundamentals import load_factbook

    filed = con.execute(
        "SELECT canonical_tag, period_type, period_start, period_end, value_inr FROM fact_observations "
        "WHERE filing_id = ? AND parser_version = ? AND value_inr IS NOT NULL AND period_end < ? "
        "AND canonical_tag NOT LIKE ? ESCAPE '\\' ORDER BY canonical_tag, period_type, period_start, period_end",
        [filing_id, parser_version, fy_start, _NOT_COMPARABLE_PREFIX],
    ).fetchall()
    context: dict = {"compared": set(), "discontinued_filed": False}
    if not filed:
        return [], context
    values = {(t, p, s, e): v for t, p, s, e, v in filed}
    for t, p, s, e, v in con.execute(
        "SELECT canonical_tag, period_type, period_start, period_end, value_inr FROM fact_corrections "
        "WHERE filing_id = ? AND revoked_at IS NULL AND period_end < ? ORDER BY created_at, correction_id",
        [filing_id, fy_start],
    ).fetchall():
        if (t, p, s, e) in values:
            values[(t, p, s, e)] = v  # None: the correction withdraws the value
    book = load_factbook(con, entity_id, scope, visible_from_ts - timedelta(microseconds=1))
    tol = rounding_only_tolerance([book.rounding_unit, ROUNDING_UNITS[level_of_rounding]])  # X260: one figure each
    out = []
    for (tag, ptype, start, end), value in sorted(
        values.items(), key=lambda x: (*x[0][:2], x[0][2] or date.min, x[0][3])
    ):
        if value is None:
            continue
        if tag == DISCONTINUED_PROFIT_TAG and value:
            context["discontinued_filed"] = True
        stored = (
            book.instants.get(tag, {}).get(end) if ptype == "INSTANT" else book.durations.get(tag, {}).get((start, end))
        )
        if stored is None:
            continue
        context["compared"].add(tag)
        diff = Decimal(value) - stored
        if abs(diff) > tol:
            out.append({"tag": tag, "period_type": ptype, "period": [str(start), str(end)], "annual": str(value),
                        "stored": str(stored), "difference": str(diff), "tolerance": str(tol)})  # fmt: skip
    return out, context


def annual_prior_year_differences(con, **kwargs) -> list[dict]:
    """The differences of `annual_prior_year_comparison` alone."""
    return annual_prior_year_comparison(con, **kwargs)[0]


SC0_RULE = "SC0"


def scrip_code(text: str | None) -> str | None:
    """Rule SC0 [X171]: a BSE scrip code as sent, or None when blank, not all digits, or all zeros (a placeholder)."""
    code = (text or "").strip()
    return code if code.isdigit() and code.strip("0") else None


def _is_scale(annual: Decimal, stored: Decimal) -> bool:
    if not annual or not stored or (annual > 0) != (stored > 0):
        return False
    big, small = max(abs(annual), abs(stored)), min(abs(annual), abs(stored))
    return any(abs(big / small - f) <= _SCALE_SLACK * f for f in _SCALE_FACTORS)


def prior_year_class(differences: list[dict], context: dict | None = None) -> dict:
    """X182: triage class of one ANNUAL_PRIOR_YEAR_DIFFERS finding, from its own differences only. SCALE when any
    line differs by an exact power of ten (10..10^7), RESTATED when a statement total (PRIOR_YEAR_TOTALS) differs,
    else REGROUPED. The tags behind the class are listed; nothing is suppressed.

    A RESTATED finding also carries a `subclass` (X233-X234), from the comparison context of
    `annual_prior_year_comparison` (without one nothing counts as compared):
      - RECLASSIFIED: every bottom line (PAT, total equity, net cash flow) was compared and agrees, so the totals
        that differ moved between captions or statements (income and expenses grossed up or netted, assets and
        liabilities offset, cash flows moved between activities): a Schedule III reclassification, not a restatement.
      - DISCONTINUED_REPRESENTED: as RECLASSIFIED, and the annual files a non-zero prior-year profit from discontinued
        operations that the stored figures do not have (Ind AS 105 re-presentation of the comparatives: PAT is the
        same, the continuing-operations lines shrink).
      - CASH_FLOW_RESTATED: PAT and total equity agree, net cash flow differs or was not compared.
      - BOTTOM_LINE_RESTATED: PAT or total equity differs or was not compared (merger, Ind AS 8 correction, ...)."""
    scale = sorted({d["tag"] for d in differences if _is_scale(Decimal(d["annual"]), Decimal(d["stored"]))})
    totals = sorted({d["tag"] for d in differences if d["tag"] in PRIOR_YEAR_TOTALS})
    cls = "SCALE" if scale else "RESTATED" if totals else "REGROUPED"
    out = {"class": cls, "scale_lines": scale, "totals_differ": totals}
    if cls == "RESTATED":
        out["subclass"] = restated_subclass(differences, context)
    return out


def restated_subclass(differences: list[dict], context: dict | None) -> str:
    """X233-X234: why the totals of a RESTATED finding differ, as far as the two filings prove it (see
    `prior_year_class`)."""
    compared = (context or {}).get("compared", set())
    differ = {d["tag"] for d in differences}
    ok = {t: t in compared and t not in differ for t in BOTTOM_LINES}
    if not (ok["pat"] and ok["total_equity"]):
        return "BOTTOM_LINE_RESTATED"
    if not ok["net_cash_flow"]:
        return "CASH_FLOW_RESTATED"
    represented = (context or {}).get("discontinued_filed") and (
        DISCONTINUED_PROFIT_TAG in differ or DISCONTINUED_PROFIT_TAG not in compared
    )
    return "DISCONTINUED_REPRESENTED" if represented else "RECLASSIFIED"


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
