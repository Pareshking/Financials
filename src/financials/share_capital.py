"""Annual share capital cross-check (G93 stand-in for the Reg. 76 audit) [X114].

The Reg. 76 reconciliation of share capital audit (issued vs listed vs demat) has no verified source (F09, A15). The
Reg. 34 annual XBRL states the year-end share counts of the equity share capital note, non-dimensional, and the
zero-drop pass already stores them as facts of the annual filing (C24): `li_number_of_shares_issued`,
`li_number_of_shares_subscribed_and_fully_paid`, `li_number_of_shares_subscribed_but_not_fully_paid`,
`li_number_of_shares_paid_up` (unit COUNT, `value_other`, at each in-scope fiscal-year end).

`annual_share_disagreement` compares them with the two share counts the engine already has for that date: the
Reg. 31 total (latest visible shareholding filing; X103: or the total less employee-trust shares) and paid-up / face
value of the results filings (`shares_from_paid_up`). The annual side agrees when ANY of its counts (issued,
subscribed = fully + partly paid, paid-up) is within SHARE_CROSS_CHECK_TOLERANCE of the reference: issued counts
legitimately include trust / forfeited shares that subscribed or paid-up exclude (SRF FY26: issued 300,481,580,
subscribed 296,424,825; SPARC: paid-up 324,521,588 vs subscribed 324,530,000). A disagreement is a non-blocking
finding ANNUAL_SHARE_COUNT_DIFFERS (stage SHARES): the annual filing is promoted, nothing is corrected.

X181 (Reg. 31 precedence): when a Reg. 31 total exists for the FY end it alone decides. Paid-up / face value is a
derived count that breaks on a mistyped face value or a stale / rounded paid-up line of one results filing
(GREENPLY Q4 FY25: face value 10 filed, paid-up 12.49 Cr, so 12,487,300 shares, while the annual report and the Reg. 31
filing both state 124,873,295 shares of Re 1); that disagreement is the results filing's own SHARES /
CROSS_CHECK_FAILED finding against the same Reg. 31 total, not evidence against the annual report. Paid-up / face
value decides only when no Reg. 31 total of that date is stored; both references stay in the details.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from financials.db import version_key
from financials.fundamentals import CURRENT_VERSION

REASON = "ANNUAL_SHARE_COUNT_DIFFERS"
ANNUAL_COUNT_TAGS = (
    "li_number_of_shares_issued",
    "li_number_of_shares_subscribed_and_fully_paid",
    "li_number_of_shares_subscribed_but_not_fully_paid",
    "li_number_of_shares_paid_up",
)


def _count(v: Decimal) -> str:
    return str(int(v)) if v == v.to_integral_value() else str(v.normalize())


def annual_share_counts(con, filing_id: str, fy_end: date) -> dict[str, Decimal]:
    """{issued, subscribed, paid_up} filed by one annual filing at `fy_end` (current parser version); absent = left out.
    subscribed = fully paid + not fully paid (0 when only the fully paid count is filed)."""
    return _annual_counts(con, [(filing_id, fy_end)]).get(filing_id, {})


def _counts(got: dict[str, Decimal]) -> dict[str, Decimal]:
    out = {}
    if "li_number_of_shares_issued" in got:
        out["issued"] = got["li_number_of_shares_issued"]
    if "li_number_of_shares_subscribed_and_fully_paid" in got:
        out["subscribed"] = got["li_number_of_shares_subscribed_and_fully_paid"] + got.get(
            "li_number_of_shares_subscribed_but_not_fully_paid", Decimal(0)
        )
    if "li_number_of_shares_paid_up" in got:
        out["paid_up"] = got["li_number_of_shares_paid_up"]
    return {k: v for k, v in out.items() if v > 0}


def _register(con, name: str, columns: dict[str, list]) -> None:
    import pyarrow as pa

    con.register(name, pa.table(columns))


def _annual_counts(con, items: list[tuple[str, date]]) -> dict[str, dict[str, Decimal]]:
    """`_counts` of every (annual filing, fy_end) in one query."""
    _register(con, "_sc_annual", {"f": [f for f, _ in items], "d": [d for _, d in items]})
    try:
        got: dict[str, dict[str, Decimal]] = {}
        for fid, tag, v in con.execute(
            "SELECT filing_id, canonical_tag, value_other FROM fact_observations JOIN _sc_annual k "
            "ON filing_id = k.f AND period_end = k.d WHERE period_type = 'INSTANT' AND value_other IS NOT NULL "
            "AND canonical_tag IN (SELECT unnest(?)) AND " + CURRENT_VERSION,
            [list(ANNUAL_COUNT_TAGS)],
        ).fetchall():
            got.setdefault(fid, {})[tag] = Decimal(v)
    finally:
        con.unregister("_sc_annual")
    return {fid: _counts(g) for fid, g in got.items()}


def annual_share_disagreement(con, filing_id: str, entity_id: str, fy_end: date) -> dict | None:
    """Finding details when the annual counts disagree with the Reg. 31 total or paid-up / face value, else None
    (agreement, or no annual count, or no reference for that date)."""
    return annual_share_disagreements(con, [(filing_id, entity_id, fy_end)])[filing_id]


def annual_share_disagreements(con, items: list[tuple[str, str, date]]) -> dict[str, dict | None]:
    """X349 ANNUAL_CHECKS_BATCHED: `annual_share_disagreement` of many (annual filing, entity, fy_end) at once, in a
    fixed number of queries (audit-annual re-checks every annual: 4,365 filings at ~86 ms each, one query per input
    row). The single-filing check is this function on one row, so both give the same answer by construction. Reg. 31
    total: the latest visible TOTAL row of that date (then latest parser version, then filing id)."""
    from financials.promoter import SHARE_CROSS_CHECK_TOLERANCE, TREASURY_TRUST_CATEGORY, treasury_candidates

    out: dict[str, dict | None] = {f: None for f, _, _ in items}
    if len({(f, d) for f, _, d in items}) != len(out):
        raise ValueError("annual_share_disagreements: one fy_end per filing")
    counts = _annual_counts(con, [(f, d) for f, _, d in items])
    todo = [(f, e, d) for f, e, d in items if counts.get(f)]
    if not todo:
        return out
    keys = sorted({(e, d) for _, e, d in todo})
    _register(con, "_sc_keys", {"e": [e for e, _ in keys], "d": [d for _, d in keys]})
    try:
        shp = {
            (e, d): (shares, f)
            for e, d, shares, f in con.execute(
                "SELECT o.entity_id, o.as_of_date, o.shares, o.filing_id FROM shareholding_observations o "
                "JOIN _sc_keys k ON o.entity_id = k.e AND o.as_of_date = k.d WHERE o.category = 'TOTAL' "
                "QUALIFY row_number() OVER (PARTITION BY o.entity_id, o.as_of_date ORDER BY o.visible_from_ts DESC, "
                + version_key("o.parser_version")
                + " DESC, o.filing_id DESC) = 1"
            ).fetchall()
        }
        paid: dict[tuple[str, date], list[tuple[str, Decimal]]] = {}
        for e, d, f, v in con.execute(
            "SELECT DISTINCT entity_id, period_end, filing_id, value_other FROM fact_observations JOIN _sc_keys k "
            "ON entity_id = k.e AND period_end = k.d WHERE canonical_tag = 'shares_from_paid_up' AND value_other > 0 "
            "AND " + CURRENT_VERSION
        ).fetchall():
            paid.setdefault((e, d), []).append((f, Decimal(v)))
    finally:
        con.unregister("_sc_keys")
    shp_filings = sorted({f for shares, f in shp.values() if shares})
    trust, held = {}, {}
    if shp_filings:
        _register(con, "_sc_shp", {"f": shp_filings})
        try:
            trust = dict(con.execute(
                "SELECT filing_id, max(shares) FROM shareholding_observations JOIN _sc_shp k ON filing_id = k.f "
                "WHERE category = 'EMPLOYEE_TRUSTS' GROUP BY 1"
            ).fetchall())  # fmt: skip
            held = dict(con.execute(
                "SELECT filing_id, sum(shares) FROM (SELECT DISTINCT filing_id, row_member, holder_name, shares "
                "FROM shareholding_major_holders JOIN _sc_shp k ON filing_id = k.f WHERE holder_category = ? AND "
                "regexp_matches(holder_name, '(?i)\\btrust\\b')) GROUP BY 1",
                [TREASURY_TRUST_CATEGORY],
            ).fetchall())  # fmt: skip
        finally:
            con.unregister("_sc_shp")
    for filing_id, entity_id, fy_end in todo:
        c = counts[filing_id]
        refs: dict[str, list[Decimal]] = {}
        shp_filing = None
        row = shp.get((entity_id, fy_end))
        if row is not None and row[0]:
            shp_filing = row[1]
            refs["reg31_total"] = treasury_candidates(Decimal(row[0]), trust.get(shp_filing),
                                                      held.get(shp_filing))  # fmt: skip  # X103, X213
        paid_up = {v for f, v in paid.get((entity_id, fy_end), []) if f != filing_id}
        if paid_up:
            refs["paid_up_over_face_value"] = sorted(paid_up)
        if not refs:
            continue
        rel = lambda v, c=c: min(abs(x - v) / v for x in c.values())  # noqa: E731
        diffs = {}
        if "reg31_total" in refs:  # the total, or the total less trust-held treasury shares (X103, X213)
            diffs["reg31_total"] = min(rel(v) for v in refs["reg31_total"])
        if "paid_up_over_face_value" in refs:  # every results filing of that date must agree
            diffs["paid_up_over_face_value"] = max(rel(v) for v in refs["paid_up_over_face_value"])
        decided_by = "reg31_total" if "reg31_total" in diffs else "paid_up_over_face_value"  # X181
        if diffs[decided_by] <= SHARE_CROSS_CHECK_TOLERANCE:
            continue
        out[filing_id] = {
            "as_of": fy_end,
            "annual_filing": filing_id,
            "annual_counts": {k: _count(v) for k, v in sorted(c.items())},
            "references": {k: [_count(v) for v in vs] for k, vs in sorted(refs.items())},
            "relative_diff": {k: str(v) for k, v in sorted(diffs.items())},
            "decided_by": decided_by,
            "shp_filing": shp_filing,
        }
    return out
