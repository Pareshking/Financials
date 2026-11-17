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
    got = {
        tag: Decimal(v)
        for tag, v in con.execute(
            "SELECT canonical_tag, value_other FROM fact_observations WHERE filing_id = ? AND period_end = ? "
            "AND period_type = 'INSTANT' AND value_other IS NOT NULL AND canonical_tag IN (SELECT unnest(?)) AND "
            + CURRENT_VERSION,
            [filing_id, fy_end, list(ANNUAL_COUNT_TAGS)],
        ).fetchall()
    }
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


def annual_share_disagreement(con, filing_id: str, entity_id: str, fy_end: date) -> dict | None:
    """Finding details when the annual counts disagree with the Reg. 31 total or paid-up / face value, else None
    (agreement, or no annual count, or no reference for that date)."""
    from financials.promoter import SHARE_CROSS_CHECK_TOLERANCE, treasury_totals

    counts = annual_share_counts(con, filing_id, fy_end)
    if not counts:
        return None
    refs: dict[str, list[Decimal]] = {}
    shp = con.execute(
        "SELECT o.shares, o.filing_id FROM shareholding_observations o WHERE o.entity_id = ? AND o.as_of_date = ? "
        "AND o.category = 'TOTAL' ORDER BY o.visible_from_ts DESC, "
        + version_key("o.parser_version")
        + " DESC LIMIT 1",
        [entity_id, fy_end],
    ).fetchone()
    shp_filing = None
    if shp is not None and shp[0]:
        shp_filing = shp[1]
        total = Decimal(shp[0])
        trust = con.execute(
            "SELECT max(shares) FROM shareholding_observations WHERE filing_id = ? AND category = 'EMPLOYEE_TRUSTS'",
            [shp_filing],
        ).fetchone()[0]
        refs["reg31_total"] = treasury_totals(con, shp_filing, total, trust)  # X103, X213
    sql = (
        "SELECT DISTINCT value_other FROM fact_observations WHERE entity_id = ? AND period_end = ? "
        "AND canonical_tag = 'shares_from_paid_up' AND value_other > 0 AND filing_id <> ? AND "
    )
    paid_up = con.execute(sql + CURRENT_VERSION, [entity_id, fy_end, filing_id]).fetchall()
    if paid_up:
        refs["paid_up_over_face_value"] = sorted(Decimal(v) for (v,) in paid_up)
    if not refs:
        return None
    rel = lambda v: min(abs(c - v) / v for c in counts.values())  # noqa: E731
    diffs = {}
    if "reg31_total" in refs:  # the total, or the total less trust-held treasury shares (X103, X213)
        diffs["reg31_total"] = min(rel(v) for v in refs["reg31_total"])
    if "paid_up_over_face_value" in refs:  # every results filing of that date must agree
        diffs["paid_up_over_face_value"] = max(rel(v) for v in refs["paid_up_over_face_value"])
    decided_by = "reg31_total" if "reg31_total" in diffs else "paid_up_over_face_value"  # X181
    if diffs[decided_by] <= SHARE_CROSS_CHECK_TOLERANCE:
        return None
    return {
        "as_of": fy_end,
        "annual_filing": filing_id,
        "annual_counts": {k: _count(v) for k, v in sorted(counts.items())},
        "references": {k: [_count(v) for v in vs] for k, vs in sorted(refs.items())},
        "relative_diff": {k: str(v) for k, v in sorted(diffs.items())},
        "decided_by": decided_by,
        "shp_filing": shp_filing,
    }
