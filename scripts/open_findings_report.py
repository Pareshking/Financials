"""Every open quarantine finding with one stated cause (work QZ, owner decision 2026-11-19), read-only.

    python scripts/open_findings_report.py data/market.duckdb [--out docs/open_findings.md] [--csv PATH]

Owner decision 2026-11-19 (docs/owner_requirements.md): Phases 1-2 are done when the random-sample accuracy is >= 98%
and every open finding carries a stated cause, even where it stays withheld. This script resolves nothing. It gives
each open finding (quarantine_queue, resolved_at IS NULL) exactly one cause from the closed taxonomy `CAUSES` below,
derived deterministically from the finding's own details and the stored data (annual reports, facts, corporate
actions, NSE Issue Size, identifier history, universe membership), all read in a few batched queries. Each cause names
the action that would settle it (`ACTIONS`). A finding no rule matches is UNCLASSIFIED; the report shows that row and it
must be 0. Cohorts as in the Phase 2 baseline: OLD = Nifty 500 seed (universe_membership.reason SEED_EXISTING),
PERM = admitted from a 'Permitted' mcap row, NEW = the other members, NONE = not a universe member (or unresolved).

The earlier reviews' verdicts are the evidence behind the causes: X236 / X308 (prior-year restatements without a stated
cause), X309 / X316 (YTD breaks: audited annual agrees with the YTD, 9M / FY columns inconsistent, no annual yet), X315
(YTD copied from the same period a year earlier: not decidable from values alone), X319 (attribution: owners 0 with NCI
beyond rounding, continuing-only split, before the JV share, OCI-shaped, gap below 0.5%, unexplained), X221 (Reg. 31 vs
paid-up vs Issue Size), X89 (wrong-template filings).
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb

MIN_PERIOD_END = date(2025, 3, 31)  # financials.scope.MIN_PERIOD_END_DATE (C9)
SHARE_TOL = Decimal("0.005")  # the share cross-check tolerance (X103 / X221): 0.5%
IMMATERIAL = Decimal("0.01")  # a YTD gap below 1% of the figure
ATTR_SMALL = Decimal("0.005")  # X319: gap below 0.5% of PAT
EVENT_DAYS = 92  # a share-count action within one quarter of the count's date
SHARE_EVENTS = ("SPLIT", "BONUS", "CONSOLIDATION", "RIGHTS", "BUYBACK")
COHORTS = ("OLD", "NEW", "PERM", "NONE")

ACTIONS = {
    "ACCEPT": "settled by an existing rule or review precedent: can be ACCEPTed with a note, no new evidence needed",
    "RESULTS_PDF": "needs the results PDF (the XBRL alone cannot decide)",
    "ANNUAL_PDF": "needs the annual report PDF (the restatement's cause is not in the XBRL)",
    "NEXT_ANNUAL": "waits for the next annual report (Reg. 34 XBRL of that fiscal year)",
    "OWNER": "needs an owner decision",
    "REFILE": "filer must re-file (nothing usable to parse or compare)",
    "TIMING": "timing difference around a share-count event or allotment: no action",
    "NO_ACTION": "out of universe or out of scope: no action",
    "OURS": "our defect: needs a code or data fix (not done)",
}

# cause -> (reason_code, action, plain-English description)
CAUSES: dict[str, tuple[str, str, str]] = {
    # CONSISTENCY / YTD_QUARTER_MISMATCH (X80): a filed YTD is not the sum of its filed quarters
    "YTD_FY_AUDITED_AGREES_YTD": (
        "YTD_QUARTER_MISMATCH",
        "ACCEPT",
        "The audited annual report states the same full-year figure as the Q4 results' FY column; the quarters as "
        "filed do not sum to it (X309 precedent: TTM uses the audited FY YTD, quarters stay as filed).",
    ),
    "YTD_FY_AUDITED_AGREES_QUARTERS": (
        "YTD_QUARTER_MISMATCH",
        "OWNER",
        "The audited annual report agrees with the sum of the quarters, not with the Q4 results' FY column: the FY "
        "column of the results filing is wrong.",
    ),
    "YTD_FY_AUDITED_AGREES_NEITHER": (
        "YTD_QUARTER_MISMATCH",
        "RESULTS_PDF",
        "The audited annual report states a third figure, equal neither to the FY column nor to the quarters.",
    ),
    "YTD_FY_AUDITED_EQUIV_AGREES_YTD": (
        "YTD_QUARTER_MISMATCH",
        "ACCEPT",
        "As YTD_FY_AUDITED_AGREES_YTD, compared through the annual's equivalent line: the Reg. 34 annual profile "
        "stores no pbt_incl_jv (compared with its pbt + share of associates / JVs) and some annuals file the owners' "
        "share only as the as-filed attribution line.",
    ),
    "YTD_FY_AUDITED_EQUIV_AGREES_QUARTERS": (
        "YTD_QUARTER_MISMATCH",
        "OWNER",
        "As YTD_FY_AUDITED_AGREES_QUARTERS, compared through the annual's equivalent line (see above).",
    ),
    "YTD_FY_CIRCULAR_ANNUAL": (
        "YTD_QUARTER_MISMATCH",
        "RESULTS_PDF",
        "The annual agrees with the FY figure only because that figure was itself taken from the annual (X309 review: "
        "circular, left open).",
    ),
    "YTD_FY_ANNUAL_NO_PBT_INCL_JV": (
        "YTD_QUARTER_MISMATCH",
        "OURS",
        "Full-year pbt_incl_jv break: the annual report is stored, but the Reg. 34 annual profile does not derive "
        "pbt_incl_jv and its pbt + share of associates / JVs agrees with neither side, so the X309 check cannot run.",
    ),
    "YTD_COPIES_SAME_PERIOD_PRIOR_YEAR": (
        "YTD_QUARTER_MISMATCH",
        "RESULTS_PDF",
        "The YTD equals, to the rupee, the same tag for the same period one year earlier: a copied column, but "
        "which column is the copy is not decidable from the values (X315, not covered).",
    ),
    "YTD_RESTATEMENT_IN_YEAR": (
        "YTD_QUARTER_MISMATCH",
        "NEXT_ANNUAL",
        "A discontinued operation, demerger or amalgamation falls inside the fiscal year: the YTD is re-presented "
        "and the earlier quarters are not (X309: settled by the annual report stating the scheme).",
    ),
    "YTD_GAP_UNDER_1PCT": (
        "YTD_QUARTER_MISMATCH",
        "OWNER",
        "The YTD and the sum of quarters differ by less than 1% (beyond rounding, X260); no annual decides it.",
    ),
    "YTD_FY_AWAITING_ANNUAL": (
        "YTD_QUARTER_MISMATCH",
        "NEXT_ANNUAL",
        "Full-year break of 1% or more and no audited annual report for that fiscal year is stored yet.",
    ),
    "YTD_FY_ANNUAL_LACKS_TAG": (
        "YTD_QUARTER_MISMATCH",
        "RESULTS_PDF",
        "Full-year break of 1% or more; the fiscal year's annual report is stored but does not state this line.",
    ),
    "YTD_INTERIM_NOT_SUM_OF_QUARTERS": (
        "YTD_QUARTER_MISMATCH",
        "RESULTS_PDF",
        "Half-year or nine-month YTD off by 1% or more from its quarters; no annual report states interim periods "
        "(X316: e.g. 9M not H1 + Q3).",
    ),
    # CONSISTENCY / ANNUAL_PRIOR_YEAR_DIFFERS (X110 / X182)
    "PY_BOTTOM_LINE_RESTATED": (
        "ANNUAL_PRIOR_YEAR_DIFFERS",
        "ANNUAL_PDF",
        "The annual report's prior-year PAT, equity or total assets differ from what was stored and its XBRL states "
        "no cause (X308: no amalgamation / Ind AS 8 sentence found).",
    ),
    "PY_CASH_FLOW_RESTATED": (
        "ANNUAL_PRIOR_YEAR_DIFFERS",
        "ANNUAL_PDF",
        "The prior-year net cash flow moved while PAT and equity agree, with no stated cause (X308).",
    ),
    "PY_UNIT_SLIP_DETAIL_LINES": (
        "ANNUAL_PRIOR_YEAR_DIFFERS",
        "RESULTS_PDF",
        "Only detail lines differ, by an exact power of ten: a unit slip in one of the two filings' lines (not a "
        "whole-filing unit error, so rule X201 cannot prove which).",
    ),
    "PY_UNIT_SLIP_WITH_TOTALS": (
        "ANNUAL_PRIOR_YEAR_DIFFERS",
        "RESULTS_PDF",
        "A power-of-ten line difference together with differing statement totals.",
    ),
    "PY_REGROUPED_PARTIAL_COMPARE": (
        "ANNUAL_PRIOR_YEAR_DIFFERS",
        "OWNER",
        "Totals agree (regrouped) but not every statement total was compared, so the X236 acceptance does not apply.",
    ),
    # SHARES / CROSS_CHECK_FAILED (X103): Reg. 31 total vs paid-up capital / face value of the same quarter end
    "CC_SHARE_EVENT_NEAR_DATE": (
        "CROSS_CHECK_FAILED",
        "TIMING",
        "A split, bonus, consolidation, rights issue or buyback has its ex-date within a quarter of the date: the "
        "counts are taken on different sides of it.",
    ),
    "CC_REG31_OUTLIER": (
        "CROSS_CHECK_FAILED",
        "ACCEPT",
        "NSE's Issue Size agrees with the results' paid-up / face value; the Reg. 31 total is the odd one (X221: "
        "market cap uses NSE's count).",
    ),
    "CC_PAIDUP_OUTLIER": (
        "CROSS_CHECK_FAILED",
        "ACCEPT",
        "NSE's Issue Size agrees with the Reg. 31 total; the results filing's paid-up capital / face value is the odd "
        "one (stale or mis-stated); market cap already uses Reg. 31.",
    ),
    "CC_ALL_DIFFER": (
        "CROSS_CHECK_FAILED",
        "RESULTS_PDF",
        "Reg. 31, paid-up / face value and NSE's Issue Size all differ (X221 verdict ALL_DIFFER).",
    ),
    "CC_NO_ISSUE_SIZE": (
        "CROSS_CHECK_FAILED",
        "RESULTS_PDF",
        "No NSE Issue Size within 14 days of the date to arbitrate (not in the PR-zip mcap file).",
    ),
    # SHARES / ANNUAL_SHARE_COUNT_DIFFERS: the annual report's share count vs Reg. 31 and paid-up / face value
    "ASC_SHARE_EVENT_NEAR_DATE": (
        "ANNUAL_SHARE_COUNT_DIFFERS",
        "TIMING",
        "A share-count action has its ex-date within a quarter of the balance-sheet date.",
    ),
    "ASC_ANNUAL_COUNT_OUTLIER": (
        "ANNUAL_SHARE_COUNT_DIFFERS",
        "ACCEPT",
        "Reg. 31 and paid-up / face value agree with each other; the annual report's count is the odd one (often an "
        "exact multiple: stated at another face value). Nothing stored uses it for market cap.",
    ),
    "ASC_REG31_OUTLIER": (
        "ANNUAL_SHARE_COUNT_DIFFERS",
        "ACCEPT",
        "The annual report agrees with paid-up / face value; only the Reg. 31 total differs (X221 pattern).",
    ),
    "ASC_PAIDUP_OUTLIER": (
        "ANNUAL_SHARE_COUNT_DIFFERS",
        "ACCEPT",
        "The annual report agrees with Reg. 31; only paid-up / face value differs.",
    ),
    "ASC_TIMING_ALLOTMENT": (
        "ANNUAL_SHARE_COUNT_DIFFERS",
        "TIMING",
        "The references themselves change around the date (two different counts filed) and the annual report "
        "agrees with one of them: an allotment around the year end.",
    ),
    "ASC_ALL_DIFFER": (
        "ANNUAL_SHARE_COUNT_DIFFERS",
        "ANNUAL_PDF",
        "The annual report, Reg. 31 and paid-up / face value all differ.",
    ),
    # IDENTITY / ATTRIBUTION_WITHHELD (X86 / X319): owners + NCI != PAT, the split is withheld
    "AW_OWNERS_ZERO_NCI_BEYOND_ROUNDING": (
        "ATTRIBUTION_WITHHELD",
        "RESULTS_PDF",
        "Owners' profit filed 0 with an NCI beyond rounding; EPS cannot verify PAT - NCI vs PAT + NCI (X319).",
    ),
    "AW_CONTINUING_ONLY": (
        "ATTRIBUTION_WITHHELD",
        "OWNER",
        "Owners + NCI equal the profit from continuing operations only; who takes the discontinued profit is not "
        "filed (X319: NAZARA's annual shows the NCI took part of it).",
    ),
    "AW_BEFORE_JV_SHARE": (
        "ATTRIBUTION_WITHHELD",
        "OWNER",
        "Owners + NCI equal PAT before the share of associates / JVs with a non-zero NCI (X189 covers NCI 0 only).",
    ),
    "AW_OCI_SHAPED": (
        "ATTRIBUTION_WITHHELD",
        "RESULTS_PDF",
        "The owners' line (or owners + NCI) carries the OCI or is near 0: the attribution rows were tagged with the "
        "OCI split (X214 / X319).",
    ),
    "AW_GAP_UNDER_HALF_PCT": (
        "ATTRIBUTION_WITHHELD",
        "OWNER",
        "Owners + NCI differ from PAT by less than 0.5% (beyond rounding); EPS cannot separate the candidates.",
    ),
    "AW_UNEXPLAINED": (
        "ATTRIBUTION_WITHHELD",
        "RESULTS_PDF",
        "No filed figure explains the gap (no EPS or shares to arbitrate, or every candidate off by > 0.5%).",
    ),
    # IDENTITY / AMBIGUOUS_ISIN, UNKNOWN_ISIN, UNKNOWN_SYMBOL
    "ID_DUPLICATE_ENTITY_FOR_ISIN": (
        "AMBIGUOUS_ISIN",
        "OURS",
        "The filed ISIN belongs to two of our entities with the same legal name: we created a second entity when the "
        "security came back in another series (e.g. BZ to BE after a suspension). Fixed by X320; repair with "
        "merge-duplicate-entity (X321), then quarantine reprocess.",
    ),
    "ID_ISIN_SHARED_BY_ENTITIES": (
        "AMBIGUOUS_ISIN",
        "OWNER",
        "The filed ISIN maps to more than one entity with different names.",
    ),
    "ID_ISIN_TYPO_SYMBOL_KNOWN": (
        "UNKNOWN_ISIN",
        "OWNER",
        "The filed ISIN is one character off the ISIN of the filed symbol's security (a typing error by the filer).",
    ),
    "ID_ISIN_UNKNOWN_SYMBOL_KNOWN": (
        "UNKNOWN_ISIN",
        "OWNER",
        "The filed ISIN is unknown but the filed symbol is a known security.",
    ),
    "ID_NOT_IN_UNIVERSE": (
        "*",
        "NO_ACTION",
        "Neither the filed ISIN nor the symbol is a security we track (SME, not listed in our window, or not a "
        "universe member).",
    ),
    "ID_SYMBOL_NOT_LISTED_AT_FILING": (
        "UNKNOWN_SYMBOL",
        "OWNER",
        "The symbol is a member, but its first identifier row starts after the filing's date (filed before listing / "
        "re-listing) and the filing states no ISIN.",
    ),
    # UNIVERSE / UNRESOLVED_SYMBOL
    "UN_SERIES_SWITCH_AHEAD_OF_BHAVCOPY": (
        "UNRESOLVED_SYMBOL",
        "NO_ACTION",
        "The mcap file lists the symbol in a new series and the security is already a member (no data is lost), but "
        "no bhavcopy switch within 5 sessions is on record, so rule X323 cannot settle it (e.g. no bar since).",
    ),
    "UN_SYMBOL_UNKNOWN": ("UNRESOLVED_SYMBOL", "NO_ACTION", "The symbol is not a security we track."),
    # PARSE / UNKNOWN_TAXONOMY, INVALID_XBRL
    "TX_OUT_OF_SCOPE_PERIOD": ("UNKNOWN_TAXONOMY", "NO_ACTION", "The filing's period ends before 2025-03-31 (C9)."),
    "TX_WRONG_TEMPLATE_NO_INDAS_REFILE": (
        "UNKNOWN_TAXONOMY",
        "REFILE",
        "An Ind AS results filing made on SEBI's non-Ind AS template (IntegratedFinance_OtherThanBank) with no Ind AS "
        "re-file for the same period (X89 closes it once one arrives).",
    ),
    "TX_NON_INDAS_RESULTS_MEMBER": (
        "UNKNOWN_TAXONOMY",
        "OWNER",
        "A member that files results on the non-Ind AS (Indian GAAP) template: we have no parser for it.",
    ),
    "TX_NON_INDAS_ANNUAL_MEMBER": (
        "UNKNOWN_TAXONOMY",
        "OWNER",
        "A member's Indian GAAP (non-Ind AS) annual report (AR_XBRL_NI): we have no parser for it.",
    ),
    "TX_NOT_IN_UNIVERSE": (
        "UNKNOWN_TAXONOMY",
        "NO_ACTION",
        "Unsupported template filed by a company that is not a universe member.",
    ),
    "PX_EMPTY_BLOB": (
        "INVALID_XBRL",
        "REFILE",
        "The vaulted file is 0 bytes because the archive serves it so (200, content-length 0; X322): nothing to parse "
        "until NSE replaces it; then fetch-results URL --refetch.",
    ),
    "PX_TRUNCATED_BLOB": (
        "INVALID_XBRL",
        "OWNER",
        "The vaulted file ends mid-token at a 4 KiB multiple. A body shorter than its Content-Length raises "
        "IncompleteRead and is retried, so the archive most likely served it so (X322); check its size on the live "
        "path and re-fetch with fetch-results URL --refetch.",
    ),
    "PX_DUPLICATE_FACT_CONFLICT": (
        "INVALID_XBRL",
        "REFILE",
        "The filing states the same fact twice with different values.",
    ),
    "PX_OTHER": ("INVALID_XBRL", "REFILE", "The file is not valid XBRL for another reason."),
    # PERIOD
    "PE_FIRST_PERIOD_OVER_12M": (
        "IRREGULAR_PERIOD",
        "OWNER",
        "A newly incorporated company's first financial year (13 to 18 months, e.g. a demerged company) in its annual "
        "report; the whole filing is held back.",
    ),
    "PE_PRE_CUTOFF_IRREGULAR_COMPARATIVE": (
        "IRREGULAR_PERIOD",
        "OWNER",
        "An irregular comparative period that ends before 2025-03-31 (out of scope, C9) in the same first-year annual "
        "report; it holds the whole filing back.",
    ),
    "PE_NO_DECLARED_PERIOD_IRREGULAR_FILING": (
        "NO_DECLARED_PERIOD",
        "OWNER",
        "The same annual report as an irregular first period: it declares no reporting period dates.",
    ),
    "PE_NO_DECLARED_PERIOD": ("NO_DECLARED_PERIOD", "REFILE", "The filing declares no reporting period dates."),
    "PE_DECLARED_DATE_DAY_MONTH_SWAPPED": (
        "CONTEXT_CONFLICT",
        "OWNER",
        "A declared date is the context date with day and month swapped (filer typo) in an out-of-scope (pre-C9) "
        "comparative, and the whole filing is held back for it.",
    ),
    "PE_OTHER": ("*PERIOD", "RESULTS_PDF", "Declared and context period dates disagree."),
    # CONSISTENCY / TAX_COPIED_FROM_PRIOR_YEAR (X94)
    "TAX_COPIED": (
        "TAX_COPIED_FROM_PRIOR_YEAR",
        "RESULTS_PDF",
        "Current and deferred tax equal the prior year's while PBT differs: copied lines, withheld (X94).",
    ),
    "UNCLASSIFIED": ("*", "OWNER", "No rule of this taxonomy matches (must be 0)."),
}

# Reason codes that were raised and all resolved before the QZ snapshot (2026-11-19): none is open there, so each gets
# one reason-level cause (code R_<reason>) until a finer rule is needed. Same (action, description) form.
REASON_LEVEL: dict[str, tuple[str, str]] = {
    "UNEXPLAINED_GAP": (
        "OWNER",
        "An open-price gap above 10% with no corporate action recorded (architecture 5.1): "
        "a missing action or a genuine market move.",
    ),
    "ISIN_CHANGE_WITHOUT_ACTION": (
        "OWNER",
        "The ISIN changed with a price gap and no recorded split / bonus / demerger to explain it.",
    ),
    "MISSING_SESSION": ("NO_ACTION", "A trading day of the calendar without a bhavcopy session."),
    "PLACEHOLDER_ISIN": ("NO_ACTION", "A source row carries a placeholder ISIN (not a real security)."),
    "ISIN_COLLISION": ("OWNER", "One ISIN arrives under two symbols / instrument ids that do not agree."),
    "STALE_ISIN_OTHER_ISSUER": ("NO_ACTION", "A corporate action names an ISIN that belongs to another issuer."),
    "AMBIGUOUS_SECURITY": ("OWNER", "A corporate action matches more than one security."),
    "UNPARSED_PURPOSE": ("OURS", "A corporate-action purpose text no parsing rule covers."),
    "VERIFY_FAILED": ("OWNER", "A corporate action's factor does not match the observed price gap."),
    "PARSE_ERROR": ("REFILE", "The filing cannot be parsed (structure the parser rejects)."),
    "MISSING_CRITICAL": ("REFILE", "A critical tag (e.g. a statement total) is missing from the filing."),
    "UNKNOWN_ROUNDING": ("OWNER", "The filing's LevelOfRounding value is not one the parser knows."),
    "YTD_NOT_FROM_FY_START": ("REFILE", "A declared YTD period does not start at the fiscal-year start."),
    "OWNERS_PLUS_NCI": ("RESULTS_PDF", "Owners + NCI do not equal PAT (before the X86 attribution rules)."),
    "EXPENSE_COMPONENTS": ("RESULTS_PDF", "Expense lines do not add up to total expenses."),
    "INS_SERVICE_EXPENSES": ("RESULTS_PDF", "An insurer's service-expense lines do not add up."),
    "ISIN_SYMBOL_CONFLICT": ("OWNER", "The filed ISIN and symbol resolve to different entities."),
    "BSE_SCRIP_CODE_CONFLICT": ("OWNER", "The filed BSE scrip code differs from the stored one (X111)."),
    "SEGMENT_SUM": ("RESULTS_PDF", "Segment figures do not add up to the filed total."),
    "SEGMENT_RECONCILING": ("RESULTS_PDF", "A segment reconciling item is larger than the segments it reconciles."),
    "GEOGRAPHY_FOREIGN_SUM": ("RESULTS_PDF", "Geographic revenue lines do not add up."),
    "SEGMENT_CONTEXT_OUTSIDE_DECLARED": ("REFILE", "Segment facts use contexts outside the declared period."),
    "NO_VISIBILITY": ("OWNER", "No broadcast time or board-meeting rule gives the filing a visibility timestamp."),
    "CLASSIFICATION_CONFLICT": ("OWNER", "Two sources classify the company differently."),
}
for _reason, (_action, _desc) in REASON_LEVEL.items():
    CAUSES[f"R_{_reason}"] = (_reason, _action, _desc)

# A per-finding verdict of an earlier review that the data alone cannot reproduce: (reason, symbol, derived cause) ->
# cause. X309: PAVNAIND C FY26 PBT agrees with the annual only because the results' FY figure itself comes from it.
REVIEW_OVERRIDES = {
    ("YTD_QUARTER_MISMATCH", "PAVNAIND", "YTD_FY_AUDITED_EQUIV_AGREES_YTD"): "YTD_FY_CIRCULAR_ANNUAL",
    ("YTD_QUARTER_MISMATCH", "PAVNAIND", "YTD_FY_AUDITED_AGREES_YTD"): "YTD_FY_CIRCULAR_ANNUAL",
}
PERIOD_REASONS = ("IRREGULAR_PERIOD", "NO_DECLARED_PERIOD", "CONTEXT_CONFLICT")
_VERSION_KEY = "list_transform(string_split(parser_version, '.'), x -> coalesce(try_cast(x AS INTEGER), 0))"


def _d(v) -> Decimal | None:
    return None if v is None or v == "" else Decimal(str(v))


def _agree(a: Decimal | None, b: Decimal | None, tol: Decimal = SHARE_TOL) -> bool:
    return a is not None and b is not None and b != 0 and abs(a - b) <= tol * abs(b)


def _load(con) -> list[dict]:
    con.execute(
        "CREATE OR REPLACE TEMP TABLE qz_open AS SELECT q.quarantine_id, q.stage, q.reason_code, q.entity_id, "
        "q.filing_id, q.details::VARCHAR AS details, f.source_url, f.broadcast_ts, f.sha256, b.byte_size "
        "FROM quarantine_queue q LEFT JOIN filings f USING (filing_id) LEFT JOIN blobs b USING (sha256) "
        "WHERE q.resolved_at IS NULL"
    )
    cols = ["quarantine_id", "stage", "reason_code", "entity_id", "filing_id", "details", "source_url",
            "broadcast_ts", "sha256", "byte_size"]  # fmt: skip
    rows = [
        dict(zip(cols, r, strict=True))
        for r in con.execute(f"SELECT {', '.join(cols)} FROM qz_open ORDER BY 1").fetchall()
    ]
    for r in rows:
        r["d"] = json.loads(r["details"] or "{}")
        r["file"] = (r["source_url"] or "").rsplit("/", 1)[-1]
    return rows


def _current_meta(con) -> None:
    con.execute(
        f"CREATE OR REPLACE TEMP TABLE qz_meta AS SELECT * FROM filing_meta "
        f"QUALIFY row_number() OVER (PARTITION BY filing_id ORDER BY {_VERSION_KEY} DESC) = 1"
    )


def _ytd_facts(con) -> dict[str, dict]:
    """Per YTD finding: annual report(s) of the fiscal year, their value of the tag, a same-period-a-year-earlier copy,
    and restatement signals in the fiscal year. One query."""
    sql = """
    WITH y AS (
        SELECT quarantine_id, entity_id, json_extract_string(details, '$.scope') AS scope,
               json_extract_string(details, '$.tag') AS tag,
               CAST(json_extract_string(details, '$.ytd_period[0]') AS DATE) AS ps,
               CAST(json_extract_string(details, '$.ytd_period[1]') AS DATE) AS pe,
               CAST(json_extract_string(details, '$.ytd') AS DECIMAL(38, 8)) AS ytd,
               CAST(json_extract_string(details, '$.quarters_sum') AS DECIMAL(38, 8)) AS qsum,
               CAST(json_extract_string(details, '$.tolerance') AS DECIMAL(38, 8)) AS tol
        FROM qz_open WHERE reason_code = 'YTD_QUARTER_MISMATCH'),
    fy AS (SELECT y.*, m.fy_start AS fys, m.fy_end AS fye FROM y
           LEFT JOIN (SELECT entity_id, scope, fy_start, fy_end FROM qz_meta GROUP BY ALL) m
             ON m.entity_id = y.entity_id AND m.scope = y.scope AND y.pe BETWEEN m.fy_start AND m.fy_end
           QUALIFY row_number() OVER (PARTITION BY y.quarantine_id ORDER BY m.fy_end) = 1),
    ann AS (SELECT fy.quarantine_id, count(DISTINCT m.filing_id) AS n_annual,
                   count(o.value_inr) AS n_tag,
                   bool_or(abs(o.value_inr - fy.ytd) <= fy.tol) AS agrees_ytd,
                   bool_or(abs(o.value_inr - fy.qsum) <= fy.tol) AS agrees_q,
                   max(o.value_inr) AS annual_value
            FROM fy JOIN qz_meta m ON m.entity_id = fy.entity_id AND m.scope = fy.scope
                 AND m.accounting_profile = 'REG34_ANNUAL' AND m.period_end = fy.fye
            LEFT JOIN fact_observations o ON o.filing_id = m.filing_id AND o.parser_version = m.parser_version
                 AND o.canonical_tag = fy.tag AND o.period_start = fy.ps AND o.period_end = fy.pe
            GROUP BY 1),
    eqv AS (SELECT fy.quarantine_id, max(e.v) AS eq_value,
                   bool_or(abs(e.v - fy.ytd) <= fy.tol) AS eq_ytd, bool_or(abs(e.v - fy.qsum) <= fy.tol) AS eq_q
            FROM fy JOIN qz_meta m ON m.entity_id = fy.entity_id AND m.scope = fy.scope
                 AND m.accounting_profile = 'REG34_ANNUAL' AND m.period_end = fy.fye
            JOIN (SELECT filing_id, parser_version, period_start, period_end,
                         sum(value_inr) FILTER (canonical_tag IN ('pbt', 'share_of_associates_jv')) AS pbt_jv,
                         max(value_inr) FILTER (
                             canonical_tag = 'asfiled_profit_or_loss_attributable_to_owners_of_parent')
                             AS owners
                  FROM fact_observations WHERE canonical_tag IN ('pbt', 'share_of_associates_jv',
                       'asfiled_profit_or_loss_attributable_to_owners_of_parent') GROUP BY ALL) a
              ON a.filing_id = m.filing_id AND a.parser_version = m.parser_version
                 AND a.period_start = fy.ps AND a.period_end = fy.pe,
            LATERAL (SELECT CASE fy.tag WHEN 'pbt_incl_jv' THEN a.pbt_jv WHEN 'pat_owners' THEN a.owners END AS v) e
            WHERE e.v IS NOT NULL GROUP BY 1),
    cp AS (SELECT DISTINCT fy.quarantine_id FROM fy JOIN qz_meta m ON m.entity_id = fy.entity_id AND m.scope = fy.scope
           JOIN fact_observations o ON o.filing_id = m.filing_id AND o.parser_version = m.parser_version
                AND o.canonical_tag = fy.tag AND o.period_start = CAST(fy.ps - INTERVAL 1 YEAR AS DATE)
                AND o.period_end = CAST(fy.pe - INTERVAL 1 YEAR AS DATE)
           WHERE fy.ytd <> 0 AND o.value_inr = fy.ytd),
    disc AS (SELECT DISTINCT fy.quarantine_id FROM fy JOIN qz_meta m ON m.entity_id = fy.entity_id
             AND m.scope = fy.scope
             JOIN fact_observations o ON o.filing_id = m.filing_id AND o.parser_version = m.parser_version
                  AND o.canonical_tag = 'pat_discontinued' AND o.period_start >= fy.ps AND o.period_end <= fy.pe
             WHERE o.value_inr <> 0),
    ev AS (SELECT DISTINCT fy.quarantine_id FROM fy JOIN corp_actions a ON a.entity_id = fy.entity_id
             AND a.action_type = 'DEMERGER' AND a.ex_date BETWEEN fy.ps AND fy.pe
           UNION SELECT DISTINCT fy.quarantine_id FROM fy JOIN entity_lineage l
             ON fy.entity_id IN (l.parent_entity_id, l.child_entity_id) AND l.effective_date BETWEEN fy.ps AND fy.pe)
    SELECT fy.quarantine_id, fy.ps, fy.pe, fy.ytd, fy.qsum, fy.tol, fy.fye, coalesce(ann.n_annual, 0),
           coalesce(ann.n_tag, 0), coalesce(ann.agrees_ytd, false), coalesce(ann.agrees_q, false), ann.annual_value,
           cp.quarantine_id IS NOT NULL, disc.quarantine_id IS NOT NULL OR ev.quarantine_id IS NOT NULL,
           eqv.eq_value, coalesce(eqv.eq_ytd, false), coalesce(eqv.eq_q, false)
    FROM fy LEFT JOIN ann USING (quarantine_id) LEFT JOIN cp USING (quarantine_id) LEFT JOIN eqv USING (quarantine_id)
    LEFT JOIN disc USING (quarantine_id) LEFT JOIN ev USING (quarantine_id)"""
    keys = ["ps", "pe", "ytd", "qsum", "tol", "fye", "n_annual", "n_tag", "agrees_ytd", "agrees_q", "annual_value",
            "copy", "restated", "eq_value", "eq_ytd", "eq_q"]  # fmt: skip
    return {r[0]: dict(zip(keys, r[1:], strict=True)) for r in con.execute(sql).fetchall()}


def _attr_facts(con) -> dict[str, dict]:
    sql = """
    WITH a AS (SELECT quarantine_id, filing_id,
                      CAST(json_extract_string(details, '$.period[0]') AS DATE) AS ps,
                      CAST(json_extract_string(details, '$.period[1]') AS DATE) AS pe
               FROM qz_open WHERE reason_code = 'ATTRIBUTION_WITHHELD')
    SELECT a.quarantine_id, o.canonical_tag, max(o.value_inr)
    FROM a JOIN qz_meta m ON m.filing_id = a.filing_id
    JOIN fact_observations o ON o.filing_id = m.filing_id AND o.parser_version = m.parser_version
         AND o.period_start = a.ps AND o.period_end = a.pe
         AND o.canonical_tag IN ('pat_discontinued', 'share_of_associates_jv', 'oci_net', 'pat_continuing')
    GROUP BY 1, 2"""
    out: dict[str, dict] = defaultdict(dict)
    for qid, tag, v in con.execute(sql).fetchall():
        out[qid][tag] = v
    return out


def _share_context(con) -> dict[str, dict]:
    """Per SHARES finding: NSE Issue Size (latest PR-zip row of the entity's listed security in (as_of - 14, as_of])
    and whether a share-count action has its ex-date within EVENT_DAYS of as_of."""
    sql = f"""
    WITH s AS (SELECT quarantine_id, entity_id, CAST(json_extract_string(details, '$.as_of') AS DATE) AS as_of
               FROM qz_open WHERE stage = 'SHARES'),
    ids AS (SELECT s.quarantine_id, s.as_of, h.symbol, h.series FROM s
            JOIN securities sec ON sec.entity_id = s.entity_id
            JOIN security_identifier_history h ON h.security_id = sec.security_id AND h.exchange = 'NSE'
                 AND h.valid_from <= s.as_of AND (h.valid_to IS NULL OR h.valid_to > s.as_of - INTERVAL 14 DAY)),
    iss AS (SELECT ids.quarantine_id, arg_max(m.issue_size, m.trade_date) AS issue_size
            FROM ids JOIN raw_nse_mcap m ON m.symbol = ids.symbol AND m.series IN ('EQ', 'BE', 'BZ')
                 AND m.trade_date > ids.as_of - INTERVAL 14 DAY AND m.trade_date <= ids.as_of
            GROUP BY 1),
    ev AS (SELECT s.quarantine_id, string_agg(DISTINCT a.action_type || ' ' || a.ex_date, ', ') AS events
           FROM s JOIN corp_actions a ON a.entity_id = s.entity_id AND a.action_type IN {SHARE_EVENTS}
                AND a.status <> 'REJECTED'
                AND a.ex_date BETWEEN s.as_of - INTERVAL {EVENT_DAYS} DAY AND s.as_of + INTERVAL {EVENT_DAYS} DAY
           GROUP BY 1)
    SELECT s.quarantine_id, iss.issue_size, ev.events FROM s LEFT JOIN iss USING (quarantine_id)
    LEFT JOIN ev USING (quarantine_id)"""
    return {q: {"issue_size": i, "events": e} for q, i, e in con.execute(sql).fetchall()}


def _identity_maps(con):
    isin_ents: dict[str, set] = defaultdict(set)
    sym_ents: dict[str, set] = defaultdict(set)
    sym_isins: dict[str, set] = defaultdict(set)
    sym_first: dict[str, date] = {}
    for sym, isin, ent, vf in con.execute(
        "SELECT h.symbol, h.isin, s.entity_id, h.valid_from FROM security_identifier_history h "
        "JOIN securities s USING (security_id)"
    ).fetchall():
        isin_ents[isin].add(ent)
        sym_ents[sym].add(ent)
        sym_isins[sym].add(isin)
        sym_first[sym] = min(vf, sym_first.get(sym, vf))
    names = dict(con.execute("SELECT entity_id, legal_name FROM entity_master").fetchall())
    cohort = dict(
        con.execute(
            "SELECT entity_id, any_value(CASE WHEN reason = 'SEED_EXISTING' THEN 'OLD' "
            "WHEN listing_category = 'Permitted' THEN 'PERM' ELSE 'NEW' END) FROM universe_membership GROUP BY 1"
        ).fetchall()
    )
    member_syms: dict[str, str] = {}
    for sym, ent in con.execute("SELECT symbol, entity_id FROM universe_membership").fetchall():
        member_syms[sym] = ent
    ent_symbol = dict(
        con.execute(
            "SELECT s.entity_id, arg_max(h.symbol, h.valid_from) FROM security_identifier_history h "
            "JOIN securities s USING (security_id) GROUP BY 1"
        ).fetchall()
    )
    listing = {
        u: (sym, pe)
        for u, sym, pe in con.execute(
            "SELECT xbrl_url, any_value(symbol), any_value(period_end) FROM raw_results_listing "
            "WHERE xbrl_url IN (SELECT source_url FROM qz_open WHERE source_url IS NOT NULL) GROUP BY 1"
        ).fetchall()
    }
    return isin_ents, sym_ents, sym_isins, sym_first, names, cohort, member_syms, ent_symbol, listing


def _hamming1(a: str, b: str) -> bool:
    return len(a) == len(b) and sum(x != y for x, y in zip(a, b, strict=True)) == 1


def _file_symbol(file: str) -> str | None:
    m = re.match(r"AR_XBRL_(?:NI_)?(.+)_\d{14}\.xml$", file)
    return m.group(1) if m else None


def _pct(a: Decimal, b: Decimal) -> Decimal:
    base = max(abs(a), abs(b))
    return abs(a - b) / base if base else Decimal(0)


def classify(con) -> list[dict]:
    """Every open finding with its cause, cohort, symbol, period and a short evidence string. Read-only (temp tables
    only)."""
    rows = _load(con)
    _current_meta(con)
    ytd = _ytd_facts(con)
    attr = _attr_facts(con)
    shares = _share_context(con)
    isin_ents, sym_ents, sym_isins, sym_first, names, cohort, member_syms, ent_symbol, listing = _identity_maps(con)
    period_files = Counter(r["filing_id"] for r in rows if r["reason_code"] == "IRREGULAR_PERIOD")
    out = []
    for r in rows:
        d, reason = r["d"], r["reason_code"]
        ent = r["entity_id"]
        sym = d.get("symbol") or (listing.get(r["source_url"]) or (None, None))[0] or _file_symbol(r["file"])
        if ent is None and sym:
            ents = sym_ents.get(sym, set()) | ({member_syms[sym]} if sym in member_syms else set())
            ent = next(iter(sorted(ents)), None) if len(ents) == 1 else None
            if ent is None and d.get("isin") in isin_ents:
                ents = isin_ents[d["isin"]] & set(cohort)
                ent = next(iter(sorted(ents)), None) if ents else None
        sym = sym or ent_symbol.get(ent)
        coh = cohort.get(ent, "NONE")
        period, evidence = "", ""
        cause = "UNCLASSIFIED"
        if reason == "YTD_QUARTER_MISMATCH" and r["quarantine_id"] in ytd:
            y = ytd[r["quarantine_id"]]
            months = (y["pe"].year - y["ps"].year) * 12 + y["pe"].month - y["ps"].month + 1
            period = f"{y['ps']}..{y['pe']} ({months}M)"
            gap = _pct(y["ytd"], y["qsum"])
            evidence = (f"{d.get('scope', '')[:1]} {d.get('tag')}: YTD {y['ytd']:.0f} vs quarters {y['qsum']:.0f} "
                        f"(gap Rs {abs(y['ytd'] - y['qsum']):.0f}, {100 * gap:.2f}%)")  # fmt: skip
            if y["n_tag"] and y["agrees_ytd"]:
                cause = "YTD_FY_AUDITED_AGREES_YTD"
            elif y["n_tag"] and y["agrees_q"]:
                cause = "YTD_FY_AUDITED_AGREES_QUARTERS"
            elif y["n_tag"] and months == 12:
                cause = "YTD_FY_AUDITED_AGREES_NEITHER"
                evidence += f"; annual {y['annual_value']:.0f}"
            elif months == 12 and y["eq_value"] is not None and (y["eq_ytd"] or y["eq_q"]):
                cause = "YTD_FY_AUDITED_EQUIV_AGREES_YTD" if y["eq_ytd"] else "YTD_FY_AUDITED_EQUIV_AGREES_QUARTERS"
                evidence += f"; annual equivalent {y['eq_value']:.0f}"
            elif months == 12 and y["n_annual"] and d.get("tag") == "pbt_incl_jv":
                cause = "YTD_FY_ANNUAL_NO_PBT_INCL_JV"
            elif y["copy"]:
                cause = "YTD_COPIES_SAME_PERIOD_PRIOR_YEAR"
            elif y["restated"]:
                cause = "YTD_RESTATEMENT_IN_YEAR"
            elif gap < IMMATERIAL:
                cause = "YTD_GAP_UNDER_1PCT"
            elif months == 12 and y["n_annual"] == 0:
                cause = "YTD_FY_AWAITING_ANNUAL"
            elif months == 12:
                cause = "YTD_FY_ANNUAL_LACKS_TAG"
            else:
                cause = "YTD_INTERIM_NOT_SUM_OF_QUARTERS"
        elif reason == "ANNUAL_PRIOR_YEAR_DIFFERS":
            diffs = d.get("differences") or [{}]
            period = "..".join(diffs[0].get("period") or [])
            evidence = f"{d.get('scope', '')[:1]} {d.get('class')}/{d.get('subclass')}: " + ", ".join(
                sorted({x.get("tag", "") for x in diffs})[:4]
            )
            cls, sub = d.get("class"), d.get("subclass")
            if cls == "RESTATED" and sub == "BOTTOM_LINE_RESTATED":
                cause = "PY_BOTTOM_LINE_RESTATED"
            elif cls == "RESTATED" and sub == "CASH_FLOW_RESTATED":
                cause = "PY_CASH_FLOW_RESTATED"
            elif cls == "SCALE":
                cause = "PY_UNIT_SLIP_WITH_TOTALS" if d.get("totals_differ") else "PY_UNIT_SLIP_DETAIL_LINES"
                evidence += "; scale lines " + ", ".join(d.get("scale_lines") or [])
            elif cls == "REGROUPED":
                cause = "PY_REGROUPED_PARTIAL_COMPARE"
        elif reason == "CROSS_CHECK_FAILED":
            s = shares.get(r["quarantine_id"], {})
            period = d.get("as_of", "")
            reg31, paid = _d(d.get("reg31_total")), _d(d.get("paid_up_over_face_value"))
            trust, iss = _d(d.get("employee_trust_shares")) or 0, _d(s.get("issue_size"))
            evidence = f"Reg31 {reg31:.0f}, paid-up/FV {paid:.0f}, NSE {iss if iss is not None else '-'}"
            if s.get("events"):
                cause, evidence = "CC_SHARE_EVENT_NEAR_DATE", evidence + f"; {s['events']}"
            elif iss is None:
                cause = "CC_NO_ISSUE_SIZE"
            elif _agree(paid, iss) and not _agree(reg31, iss):
                cause = "CC_REG31_OUTLIER"
            elif _agree(reg31, iss) or _agree(reg31 - trust, iss):
                cause = "CC_PAIDUP_OUTLIER"
            else:
                cause = "CC_ALL_DIFFER"
        elif reason == "ANNUAL_SHARE_COUNT_DIFFERS":
            s = shares.get(r["quarantine_id"], {})
            period = d.get("as_of", "")
            ac = _d((d.get("annual_counts") or {}).get("paid_up"))
            refs = d.get("references") or {}
            pu = [_d(x) for x in refs.get("paid_up_over_face_value", [])]
            rg = [_d(x) for x in refs.get("reg31_total", [])]
            evidence = f"annual {ac}, paid-up/FV {[str(x) for x in pu]}, Reg31 {[str(x) for x in rg]}"
            a_pu, a_rg = any(_agree(ac, x) for x in pu), any(_agree(ac, x) for x in rg)
            refs_agree = any(_agree(x, y) for x in pu for y in rg)
            if s.get("events"):
                cause, evidence = "ASC_SHARE_EVENT_NEAR_DATE", evidence + f"; {s['events']}"
            elif (len(pu) > 1 or len(rg) > 1) and (a_pu or a_rg):
                cause = "ASC_TIMING_ALLOTMENT"
            elif a_pu and not a_rg:
                cause = "ASC_REG31_OUTLIER"
            elif a_rg and not a_pu:
                cause = "ASC_PAIDUP_OUTLIER"
            elif refs_agree:
                cause = "ASC_ANNUAL_COUNT_OUTLIER"
            else:
                cause = "ASC_ALL_DIFFER"
        elif reason == "ATTRIBUTION_WITHHELD":
            f = attr.get(r["quarantine_id"], {})
            period = "..".join(d.get("period") or [])
            own, nci, pat, tol = (_d(d.get(k)) or Decimal(0) for k in ("owners", "nci", "pat", "tolerance"))
            disc, jv, oci = (f.get(k) or Decimal(0) for k in ("pat_discontinued", "share_of_associates_jv", "oci_net"))
            evidence = f"owners {own:.0f}, NCI {nci:.0f}, PAT {pat:.0f}, disc {disc:.0f}, JV {jv:.0f}, OCI {oci:.0f}"
            s = own + nci
            if own == 0 and abs(nci) > tol:
                cause = "AW_OWNERS_ZERO_NCI_BEYOND_ROUNDING"
            elif disc and abs(s - (pat - disc)) <= tol:
                cause = "AW_CONTINUING_ONLY"
            elif jv and nci and abs(s - (pat - jv)) <= tol:
                cause = "AW_BEFORE_JV_SHARE"
            elif (oci and min(abs(own - oci), abs(own + oci), abs(s - oci)) <= tol) or abs(own) <= tol:
                cause = "AW_OCI_SHAPED"
            elif pat and abs(s - pat) < ATTR_SMALL * abs(pat):
                cause = "AW_GAP_UNDER_HALF_PCT"
            else:
                cause = "AW_UNEXPLAINED"
        elif reason in ("AMBIGUOUS_ISIN", "UNKNOWN_ISIN", "UNKNOWN_SYMBOL"):
            isin = d.get("isin")
            evidence = f"filed ISIN {isin}, symbol {d.get('symbol')}, {r['file']}"
            period = str(r["broadcast_ts"].date()) if r["broadcast_ts"] else ""
            if reason == "AMBIGUOUS_ISIN":
                ents = sorted(isin_ents.get(isin, ()))
                ent = next((e for e in ents if e in cohort), ent)
                coh = cohort.get(ent, "NONE")
                same = len({names.get(e) for e in ents}) == 1
                cause = "ID_DUPLICATE_ENTITY_FOR_ISIN" if same else "ID_ISIN_SHARED_BY_ENTITIES"
                evidence += f"; entities {', '.join(ents)}"
            elif reason == "UNKNOWN_ISIN" and d.get("symbol") in sym_isins:
                known = sorted(sym_isins[d["symbol"]])
                typo = any(_hamming1(isin or "", k) for k in known)
                cause = "ID_ISIN_TYPO_SYMBOL_KNOWN" if typo else "ID_ISIN_UNKNOWN_SYMBOL_KNOWN"
                evidence += f"; symbol's ISIN {', '.join(known)}"
            elif (
                reason == "UNKNOWN_SYMBOL"
                and sym in member_syms
                and r["broadcast_ts"] is not None
                and (sym_first.get(sym, date.max) > r["broadcast_ts"].date())
            ):
                cause = "ID_SYMBOL_NOT_LISTED_AT_FILING"
                evidence += f"; first identifier row {sym_first[sym]}"
            elif coh == "NONE":
                cause = "ID_NOT_IN_UNIVERSE"
        elif reason == "UNRESOLVED_SYMBOL":
            period = str(r["broadcast_ts"].date()) if r["broadcast_ts"] else ""
            evidence = f"{d.get('symbol')} {d.get('series')} in {r['file']}"
            if sym in member_syms:
                cause = "UN_SERIES_SWITCH_AHEAD_OF_BHAVCOPY"
            elif sym not in sym_ents:
                cause = "UN_SYMBOL_UNKNOWN"
        elif reason == "UNKNOWN_TAXONOMY":
            ns = d.get("entity_namespace") or ""
            pe = (listing.get(r["source_url"]) or (None, None))[1]
            period = str(pe or "")
            evidence = f"{r['file']}; namespace {ns.split('/xbrl/')[-1] or 'none'}"
            if pe is not None and pe < MIN_PERIOD_END:
                cause = "TX_OUT_OF_SCOPE_PERIOD"
            elif coh == "NONE":
                cause = "TX_NOT_IN_UNIVERSE"
            elif "IntegratedFinance_OtherThanBank" in ns and "_NONINDAS_" not in r["file"]:
                cause = "TX_WRONG_TEMPLATE_NO_INDAS_REFILE"
            elif "_NONINDAS_" in r["file"]:
                cause = "TX_NON_INDAS_RESULTS_MEMBER"
            elif r["file"].startswith("AR_XBRL_NI_"):
                cause = "TX_NON_INDAS_ANNUAL_MEMBER"
        elif reason == "INVALID_XBRL":
            err = d.get("error") or ""
            evidence = f"{r['file']} ({r['byte_size']} bytes): {err}"
            if r["byte_size"] == 0:
                cause = "PX_EMPTY_BLOB"
            elif "unclosed token" in err and r["byte_size"] and r["byte_size"] % 4096 == 0:
                cause = "PX_TRUNCATED_BLOB"
            elif err.startswith("duplicate fact"):
                cause = "PX_DUPLICATE_FACT_CONFLICT"
            else:
                cause = "PX_OTHER"
        elif reason in PERIOD_REASONS:
            evidence = f"{r['file']}: {json.dumps(d)}"
            dates = d.get("dates") or d.get("context") or []
            period = "..".join(dates)
            if reason == "IRREGULAR_PERIOD" and len(dates) == 2 and date.fromisoformat(dates[1]) < MIN_PERIOD_END:
                cause = "PE_PRE_CUTOFF_IRREGULAR_COMPARATIVE"
            elif reason == "IRREGULAR_PERIOD" and len(dates) == 2:
                a, b = date.fromisoformat(dates[0]), date.fromisoformat(dates[1])
                months = (b.year - a.year) * 12 + b.month - a.month + (1 if b.day >= a.day - 1 else 0)
                cause = "PE_FIRST_PERIOD_OVER_12M" if 12 < months <= 18 or (b - a).days > 366 else "PE_OTHER"
            elif reason == "NO_DECLARED_PERIOD":
                cause = "PE_NO_DECLARED_PERIOD_IRREGULAR_FILING" if period_files[r["filing_id"]] else (
                    "PE_NO_DECLARED_PERIOD")  # fmt: skip
            elif reason == "CONTEXT_CONFLICT":
                ctx, dec = d.get("context") or [], d.get("declared") or []
                swapped = len(ctx) == len(dec) and any(
                    c != x and date.fromisoformat(x) == _swap(c) for c, x in zip(ctx, dec, strict=True)
                )
                early = bool(ctx) and date.fromisoformat(ctx[-1]) < MIN_PERIOD_END
                cause = "PE_DECLARED_DATE_DAY_MONTH_SWAPPED" if swapped and early else "PE_OTHER"
            else:
                cause = "PE_OTHER"
        elif reason == "TAX_COPIED_FROM_PRIOR_YEAR":
            period = "..".join(d.get("period") or [])
            evidence = (
                f"{d.get('scope', '')[:1]} tax {d.get('current_tax')}+{d.get('deferred_tax')}, PBT {d.get('pbt')}"
            )
            cause = "TAX_COPIED"
        if cause == "UNCLASSIFIED" and reason in REASON_LEVEL:
            cause = f"R_{reason}"
            evidence = evidence or json.dumps(d)[:200]
        if (reason, sym, cause) in REVIEW_OVERRIDES:
            cause = REVIEW_OVERRIDES[(reason, sym, cause)]
        if cause != "UNCLASSIFIED" and CAUSES[cause][0] not in (reason, "*", "*PERIOD"):
            cause = "UNCLASSIFIED"  # a cause is only valid for its own reason code
        out.append({"quarantine_id": r["quarantine_id"], "stage": r["stage"], "reason": reason,
                    "symbol": sym or "", "entity_id": ent or "", "cohort": coh, "period": period, "cause": cause,
                    "action": CAUSES[cause][1], "evidence": evidence})  # fmt: skip
    return out


def _swap(iso: str) -> date | None:
    d = date.fromisoformat(iso)
    try:
        return date(d.year, d.day, d.month)
    except ValueError:
        return None


def to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    keys = ["quarantine_id", "stage", "reason", "cause", "action", "cohort", "symbol", "period", "evidence"]
    w = csv.DictWriter(buf, keys, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for r in sorted(rows, key=lambda r: (r["reason"], r["cause"], r["symbol"], r["period"], r["quarantine_id"])):
        w.writerow(r)
    return buf.getvalue()


def to_markdown(rows: list[dict], db_label: str, csv_name: str) -> str:
    n = len(rows)
    by = Counter((r["stage"], r["reason"], r["cause"], r["cohort"]) for r in rows)
    lines = [
        "# Open findings: one stated cause each",
        "",
        f"Generated by `python scripts/open_findings_report.py {db_label}` (read-only; work QZ, owner decision "
        "2026-11-19: Phases 1-2 are done when every open finding carries a stated cause). Do not edit by hand.",
        "",
        f"Open findings: **{n}**. UNCLASSIFIED: **{sum(1 for r in rows if r['cause'] == 'UNCLASSIFIED')}** "
        "(must be 0). Cohorts: OLD = Nifty 500 seed, NEW = admitted at >= Rs 500 Cr (Listed), PERM = admitted from "
        "a Permitted row, NONE = not a universe member. Every finding with its cause and evidence: "
        f"[`{csv_name}`]({csv_name}).",
        "",
        "## By action",
        "",
        "| action | meaning | findings |",
        "|---|---|---:|",
    ]
    acts = Counter(r["action"] for r in rows)
    for a, desc in ACTIONS.items():
        lines.append(f"| {a} | {desc} | {acts.get(a, 0)} |")
    lines += ["", "## Reason x cause x cohort", "",
              "| stage / reason | cause | action | OLD | NEW | PERM | NONE | total |",
              "|---|---|---|---:|---:|---:|---:|---:|"]  # fmt: skip
    keys = sorted({(s, rs, c) for s, rs, c, _ in by}, key=lambda k: (k[0], k[1], k[2] == "UNCLASSIFIED", k[2]))
    for s, rs, c in keys:
        cnt = [by.get((s, rs, c, co), 0) for co in COHORTS]
        lines.append(f"| {s} / {rs} | {c} | {CAUSES[c][1]} | " + " | ".join(map(str, cnt)) + f" | {sum(cnt)} |")
    unc = [sum(1 for r in rows if r["cause"] == "UNCLASSIFIED" and r["cohort"] == co) for co in COHORTS]
    lines.append("| all | UNCLASSIFIED | - | " + " | ".join(map(str, unc)) + f" | {sum(unc)} |")
    tot = [sum(1 for r in rows if r["cohort"] == co) for co in COHORTS]
    lines.append("| **all** | | | " + " | ".join(f"**{x}**" for x in tot) + f" | **{n}** |")
    lines += ["", "## Cause taxonomy (closed)", "", "| cause | reason | action | description |", "|---|---|---|---|"]
    for c, (rs, a, desc) in CAUSES.items():
        lines.append(f"| {c} | {rs} | {a} | {desc} |")
    lines += ["", "## One example per cause", "", "| cause | example (symbol, period, evidence) |", "|---|---|"]
    seen = {}
    for r in sorted(rows, key=lambda r: (r["cause"], r["symbol"], r["period"])):
        seen.setdefault(r["cause"], r)
    for c, r in sorted(seen.items()):
        lines.append(f"| {c} | {r['symbol']} {r['period']}: {r['evidence']} |".replace("\n", " "))
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("db")
    ap.add_argument("--out", help="write the Markdown report here (and the CSV next to it)")
    ap.add_argument("--csv", help="CSV path (default: the --out path with .csv)")
    args = ap.parse_args(argv)
    con = duckdb.connect(args.db, read_only=True)
    try:
        con.execute("SET memory_limit='2GB'")
        rows = classify(con)
    finally:
        con.close()
    if args.out:
        out = Path(args.out)
        csv_path = Path(args.csv) if args.csv else out.with_suffix(".csv")
        out.write_text(to_markdown(rows, f"data/{Path(args.db).name}", csv_path.name))
        csv_path.write_text(to_csv(rows))
    else:
        sys.stdout.write(to_markdown(rows, f"data/{Path(args.db).name}", "open_findings.csv"))
    unc = sum(1 for r in rows if r["cause"] == "UNCLASSIFIED")
    print(f"{len(rows)} open findings, {unc} UNCLASSIFIED", file=sys.stderr)
    return 1 if unc else 0


if __name__ == "__main__":
    raise SystemExit(main())
