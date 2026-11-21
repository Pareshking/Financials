"""Related-party leak columns (batch J, G236 / G99) from `related_party_transactions` [X113], for `features.py`.

One batched read per materialisation (never a query per security), point in time:
- the related-party rows of the latest visible annual filing per (entity, scope, fiscal-year end)
  (`visible_from_ts <= as_of`, then the latest broadcast, then the latest RPT parser version);
- the denominators from the SAME filing, scope and fiscal year in `fact_observations` (its current parser version):
  `revenue_from_operations` for the FY duration, `total_equity` at the FY end. Numerator and denominator therefore
  never mix filings, scopes or periods (invariant 6).

Per row: the latest fiscal-year end with a related-party schedule in the row's scope (`scope_used`), else the other
scope (consolidated first). Only DURATION rows of that FY count, and only counterparties outside the consolidated
group: category SUBSIDIARY is excluded (eliminated on consolidation; a standalone filing lists them too). Associates,
joint ventures, the parent / promoter group, KMP and others are outside the group and count.

- rpt_leak_pct = (purchases + loans given + royalties paid) / revenue from operations (G236). Purchases are goods
  plus property and other assets bought; royalties are licence transfers to the entity plus `OtherRelated...Expense`
  rows whose nature text names only royalties (NATURE_RULE).
- rpt_purchases_to_sales = purchases / revenue; rpt_royalty_to_sales = royalties paid / revenue;
  rpt_loans_given_to_net_worth = loans given (finance transfers from the entity) / total equity at the FY end.
- rpt_counterparties = distinct counterparty names outside the group with any non-zero FY transaction.
A filing with a schedule but no such transaction gives 0 (filed as nil); no schedule gives NULL. Revenue or equity
<= 0 or missing gives NULL. Fractions as DOUBLE, like the other `_pct` / `_to_` columns.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from financials.db import version_key
from financials.fundamentals import CURRENT_VERSION, entity_filter, safe_div
from financials.run_memo import by_visibility

RPT_COLUMNS = ("rpt_fy_end", "rpt_counterparties", "rpt_leak_pct", "rpt_purchases_to_sales", "rpt_royalty_to_sales",
               "rpt_loans_given_to_net_worth")  # fmt: skip
LEAK_TYPES = ("purchases", "loans_given", "royalty")
ZERO = Decimal(0)


@by_visibility  # read once per visibility interval of an incremental run (run_memo)
def rpt_inputs(con, as_of_ts: datetime, entities=None) -> dict[tuple[str, str], dict]:
    """(entity, scope) -> inputs of the latest visible fiscal year with a related-party schedule."""
    only, only_p = entity_filter("entity_id", entities)
    sums: dict[tuple[str, str, date], dict] = {}
    for ent, scope, fid, end, txn, outside, amount, names in con.execute(
        f"""WITH r AS (
              SELECT * FROM related_party_transactions
              WHERE visible_from_ts <= ? AND period_type = 'DURATION' {only}
              QUALIFY dense_rank() OVER (PARTITION BY entity_id, scope, period_end
                                         ORDER BY visible_from_ts DESC, filing_id DESC,
                                                  {version_key("parser_version")} DESC) = 1)
            SELECT entity_id, scope, filing_id, period_end, txn_type, category <> 'SUBSIDIARY',
                   sum(amount_inr), list(DISTINCT counterparty_name) FILTER (WHERE amount_inr <> 0)
            FROM r GROUP BY ALL""",
        [as_of_ts, *only_p],
    ).fetchall():
        s = sums.setdefault((ent, scope, end), {"filing_id": fid, "by_type": defaultdict(lambda: ZERO), "names": set()})
        if outside:
            s["by_type"][txn] += Decimal(amount)
            s["names"].update(names or ())
    latest: dict[tuple[str, str], tuple[date, dict]] = {}
    for (ent, scope, end), s in sums.items():
        if (ent, scope) not in latest or end > latest[(ent, scope)][0]:
            latest[(ent, scope)] = (end, s)
    if not latest:
        return {}
    import pyarrow as pa

    keys = sorted({(s["filing_id"], end) for end, s in latest.values()})
    denominators: dict[tuple[str, date], dict[str, Decimal]] = defaultdict(dict)
    con.register("_rpt_keys", pa.table({"filing_id": [k[0] for k in keys], "period_end": [k[1] for k in keys]}))
    try:
        found = con.execute(
            """SELECT f.filing_id, f.period_end, f.canonical_tag, f.value_inr
               FROM fact_observations f JOIN _rpt_keys k ON f.filing_id = k.filing_id AND f.period_end = k.period_end
               WHERE f.value_inr IS NOT NULL
                 AND ((f.canonical_tag = 'revenue_from_operations' AND f.period_type = 'DURATION'
                       AND f.period_months = 12) OR (f.canonical_tag = 'total_equity' AND f.period_type = 'INSTANT'))
                 AND """
            + CURRENT_VERSION.replace("fact_observations.", "f.")
        ).fetchall()
    finally:
        con.unregister("_rpt_keys")
    for fid, end, tag, value in found:
        denominators[(fid, end)][tag] = Decimal(value)
    out = {}
    for key, (end, s) in latest.items():
        d = denominators.get((s["filing_id"], end), {})
        out[key] = {"fy_end": end, "by_type": dict(s["by_type"]), "names": s["names"],
                    "revenue": d.get("revenue_from_operations"), "equity": d.get("total_equity")}  # fmt: skip
    return out


def _ratio(num: Decimal, den: Decimal | None) -> float | None:
    if den is None or den <= 0:
        return None
    r = safe_div(num, den)
    return None if r is None else float(r)


def rpt_columns(inputs: dict | None) -> dict:
    out = dict.fromkeys(RPT_COLUMNS)
    if inputs is None:
        return out
    t = inputs["by_type"]
    get = lambda k: t.get(k, ZERO)  # noqa: E731
    rev = inputs["revenue"]
    out["rpt_fy_end"] = inputs["fy_end"]
    out["rpt_counterparties"] = len(inputs["names"])
    out["rpt_leak_pct"] = _ratio(sum((get(k) for k in LEAK_TYPES), ZERO), rev)
    out["rpt_purchases_to_sales"] = _ratio(get("purchases"), rev)
    out["rpt_royalty_to_sales"] = _ratio(get("royalty"), rev)
    out["rpt_loans_given_to_net_worth"] = _ratio(get("loans_given"), inputs["equity"])
    return out


def add_columns(con, rows: list[dict], as_of_ts: datetime, entities=None) -> None:
    """The features.compute_rows hook (after batch I): one batched read, then each row's columns, in place."""
    inputs = rpt_inputs(con, as_of_ts, entities)
    for row in rows:
        ent, scope = row["entity_id"], row.get("scope_used")
        order = [scope] if scope else []
        order += [s for s in ("CONSOLIDATED", "STANDALONE") if s not in order]
        row.update(rpt_columns(next((inputs[(ent, s)] for s in order if (ent, s) in inputs), None)))


def dsl_aliases() -> dict[str, tuple[str, str]]:
    """Screener-style names for the numeric columns of this module (fractions shown x100); `rpt_fy_end` is a date,
    shown with `screen --columns`."""
    return {
        "rpt leak": ("(rpt_leak_pct * 100)", "%, related-party purchases + loans given + royalties / revenue, last FY"),
        "rpt leak pct": ("(rpt_leak_pct * 100)", "%, related-party purchases + loans given + royalties / revenue"),
        "rpt purchases to sales": ("(rpt_purchases_to_sales * 100)", "%, related-party purchases / revenue, last FY"),
        "rpt royalty to sales": ("(rpt_royalty_to_sales * 100)", "%, royalties paid to related parties / revenue"),
        "rpt loans given to net worth": (
            "(rpt_loans_given_to_net_worth * 100)",
            "%, loans given to related parties / total equity, last FY",
        ),
        "related party counterparties": ("rpt_counterparties", "count, outside the group, non-zero FY transactions"),
    }
