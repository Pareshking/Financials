"""Event-sparse storage of `screener_features_history` (architecture §4.1).

The history is read through the view `screener_features_history` (schema.sql, below VIEWS_MARKER): the same column
names, order and types as `screener_features`, one row per security and materialised day. It is stored in two tables:

- `features_daily` (as_of_date, security_id, the DAILY columns): every materialised day. DAILY = anything that
  depends on the day's price, volume, share count, market cap or EV, on a window that moves with the as-of date
  (90-day event counts, 365-day corporate-action flags, index inclusion), on inputs outside the fundamentals cache
  key (shareholding, NSE classification, supplemental KPIs, the Nifty 500 membership, corporate-action factors) or on
  the same-day cross-section (ranks, medians, hats; the refresh steps UPDATE only this table).
- `features_events` (security_id, valid_from_date, valid_to_date, the EVENT columns): one row per interval
  [valid_from_date, valid_to_date) of identical EVENT values; valid_to_date NULL = open. A day's write compares
  its EVENT values with the interval covering the day and, only when they differ, closes it and opens a new one.

EVENT_COLUMNS are exactly the columns computed from the per-entity fundamentals block (`features._fundamentals` and
the period values of features_pl / _bs / _gems / _extra / _more / _rpt) and from static inputs (the archetype
override and the curated CSVs). `features.FundamentalsCache` reuses that block for every day of a run whose key
(latest visible quarter, number of the entity's visibility timestamps, number of its structural ex-dates) did not
move, so these values can only change on a key change. The split was checked on the live database (docs/
architecture.md §4.1): no EVENT column ever changed on a day without a key change. The split does not decide
correctness: every write stores the values it was given, whatever their column; it only decides how many intervals
there are.

Invariants (tests/test_features_store.py): intervals of a security never overlap; two adjacent intervals
(a.valid_to_date = b.valid_from_date) never hold identical values; every features_daily row lies in exactly one
interval of its security. A write of day D for security s sets the values on [D, N), N = the next materialised day
of s after D (open when none): the days in between have no daily row, so nothing reads them.
Everything here runs inside the caller's transaction (the single writer, features.materialize / admin).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from financials.db import declared_columns

EVENT_COLUMNS = (
    "sales_ttm", "ebitda_ttm", "pat_ttm", "fcf_ttm", "net_debt", "total_equity", "opm", "sales_growth_yoy",
    "profit_growth_yoy", "roe", "roce", "roic", "croic", "debt_to_equity", "other_income_to_pbt", "altman_z_dd",
    "piotroski_f", "beneish_m", "scope_used", "fundamentals_end", "bs_as_of", "cf_as_of", "roe_continuing",
    "core_profit_ttm", "is_lending_nbfc", "nii_ttm", "ppop_ttm", "cost_to_income", "credit_cost", "nim_asset_proxy",
    "roa", "loans", "loans_as_of", "loans_avg_from", "gnpa_pct", "nnpa_pct", "pcr", "credit_to_deposit", "cet1_pct",
    "at1_pct", "roa_filed", "govt_holding_pct", "insurer_basis", "net_premium_earned_ttm", "insurance_revenue_ttm",
    "claims_ratio", "expense_ratio", "combined_ratio", "solvency_ratio", "investment_income_ttm", "scope_reason",
    "restatement_suspected", "default_quarterly_scope", "default_annual_scope", "sloan_accrual", "cfo_to_ebitda",
    "fcf_to_pat", "working_capital_intensity", "receivables_sales_divergence", "net_debt_to_fcf", "cost_of_debt",
    "dol", "gross_ebitda_spread", "valuation_archetype", "rule_of_40", "billings_growth_pct",
    "neg_working_capital_float_pct", "net_burn_multiple", "cash_runway_months", "esop_adj_fcf", "liquid_cash",
    "capex_to_depreciation", "cwip_to_gross_block", "rote", "rnd_and_royalty_intensity",
    "contingent_liabilities_to_net_worth", "annual_fy_end", "roce_screener", "debtor_days", "inventory_turnover",
    "working_capital", "inventory_days", "days_payable", "cash_conversion_cycle", "working_capital_days",
    "sales_growth_qoq_pct", "profit_growth_qoq_pct", "npm_pct", "interest_coverage", "opm_last_year_pct",
    "sales_latest_quarter", "sales_preceding_quarter", "sales_preceding_year_quarter",
    "operating_profit_latest_quarter", "operating_profit_preceding_quarter",
    "operating_profit_preceding_year_quarter", "other_income_latest_quarter", "other_income_preceding_quarter",
    "other_income_preceding_year_quarter", "depreciation_latest_quarter", "depreciation_preceding_quarter",
    "depreciation_preceding_year_quarter", "ebit_latest_quarter", "ebit_preceding_quarter",
    "ebit_preceding_year_quarter", "interest_latest_quarter", "interest_preceding_quarter",
    "interest_preceding_year_quarter", "pbt_latest_quarter", "pbt_preceding_quarter", "pbt_preceding_year_quarter",
    "tax_latest_quarter", "tax_preceding_quarter", "tax_preceding_year_quarter", "pat_latest_quarter",
    "pat_preceding_quarter", "pat_preceding_year_quarter", "net_profit_latest_quarter",
    "net_profit_preceding_quarter", "net_profit_preceding_year_quarter", "exceptional_items_latest_quarter",
    "exceptional_items_preceding_quarter", "exceptional_items_preceding_year_quarter", "sales_2quarters_back",
    "sales_3quarters_back", "operating_profit_2quarters_back", "operating_profit_3quarters_back",
    "net_profit_2quarters_back", "net_profit_3quarters_back", "sales_last_year", "sales_preceding_year",
    "operating_profit_last_year", "operating_profit_preceding_year", "other_income_last_year",
    "other_income_preceding_year", "depreciation_last_year", "depreciation_preceding_year", "ebit_last_year",
    "ebit_preceding_year", "interest_last_year", "interest_preceding_year", "pbt_last_year", "pbt_preceding_year",
    "tax_last_year", "tax_preceding_year", "pat_last_year", "pat_preceding_year", "net_profit_last_year",
    "net_profit_preceding_year", "exceptional_items_last_year", "exceptional_items_preceding_year",
    "sales_ttm_1y_back", "avg_earnings_5y", "avg_earnings_10y", "avg_ebit_5y", "avg_ebit_10y",
    "equity_capital_latest_quarter", "equity_capital_preceding_quarter", "equity_capital_preceding_year_quarter",
    "opm_latest_quarter_pct", "opm_preceding_quarter_pct", "opm_preceding_year_pct", "npm_latest_quarter_pct",
    "npm_preceding_quarter_pct", "npm_preceding_year_quarter_pct", "npm_last_year_pct", "npm_preceding_year_pct",
    "gpm_latest_quarter_pct", "gpm_last_year_pct", "gpm_preceding_year_pct", "sales_growth_yoy_quarter_pct",
    "profit_growth_yoy_quarter_pct", "operating_profit_growth_yoy_quarter_pct", "sales_growth_3y_pct",
    "sales_growth_5y_pct", "sales_growth_7y_pct", "sales_growth_10y_pct", "profit_growth_3y_pct",
    "profit_growth_5y_pct", "profit_growth_7y_pct", "profit_growth_10y_pct", "operating_profit_growth_3y_pct",
    "operating_profit_growth_5y_pct", "operating_profit_growth_7y_pct", "operating_profit_growth_10y_pct",
    "sales_growth_median_5y_pct", "sales_growth_median_10y_pct", "opm_5y_pct", "opm_10y_pct", "last_result_date",
    "last_annual_result_date", "opm_preceding_year_quarter_pct", "debt", "equity_capital", "reserves",
    "balance_sheet_total", "net_block", "cwip", "investments", "current_assets", "current_liabilities",
    "lease_liabilities", "inventory", "trade_receivables", "trade_payables", "cash_equivalents", "gross_block",
    "accumulated_depreciation", "contingent_liabilities", "advance_from_customers", "debt_preceding_year",
    "net_block_preceding_year", "gross_block_preceding_year", "cwip_preceding_year",
    "working_capital_preceding_year", "debt_3y_back", "debt_5y_back", "debt_7y_back", "debt_10y_back",
    "net_block_3y_back", "net_block_5y_back", "net_block_7y_back", "net_block_10y_back", "working_capital_3y_back",
    "working_capital_5y_back", "working_capital_7y_back", "working_capital_10y_back", "cash_3y_back",
    "cash_5y_back", "cash_7y_back", "cfo_last_year", "cfo_preceding_year", "cfi_last_year", "cfi_preceding_year",
    "cff_last_year", "cff_preceding_year", "net_cash_flow_last_year", "net_cash_flow_preceding_year",
    "cash_beginning_last_year", "cash_beginning_preceding_year", "cash_end_last_year", "cash_end_preceding_year",
    "fcf_last_year", "fcf_preceding_year", "fcf_3y", "fcf_5y", "fcf_7y", "fcf_10y", "cfo_3y", "cfo_5y", "cfo_7y",
    "cfo_10y", "cfi_3y", "cfi_5y", "cfi_7y", "cfi_10y", "face_value", "current_ratio", "quick_ratio",
    "net_debt_to_equity", "long_term_debt_to_equity", "debt_to_equity_preceding_year", "financial_leverage",
    "asset_turnover", "earning_power", "roe_preceding_year", "roce_preceding_year", "roa_preceding_year",
    "exports_pct", "exports_pct_3y_back", "exports_pct_5y_back", "inventory_turnover_3y_back",
    "inventory_turnover_5y_back", "inventory_turnover_7y_back", "inventory_turnover_10y_back",
    "debtor_days_3y_back", "debtor_days_5y_back", "avg_debtor_days_3y", "avg_working_capital_days_3y",
    "cfo_to_ebitda_last_year", "cfo_to_ebitda_preceding_year", "fcf_conversion_3y", "cfo_to_ebitda_3y",
    "net_debt_to_fcf_3y", "reinvestment_rate", "incremental_roic_1y", "incremental_roic_3y", "incremental_roic_5y",
    "net_debt_to_ebitda", "sales_growth_yoy_preceding_quarter_pct", "profit_growth_yoy_preceding_quarter_pct",
    "core_profit_latest_quarter", "core_profit_yoy_latest_q", "core_profit_yoy_preceding_q", "other_income_lift_pp",
    "growth_sustained", "growth_acceleration_pp", "opm_change_yoy_pp", "operating_leverage", "cash_conversion_ok",
    "capex_pay_off_signal", "roce_stability_5y", "opm_stability_5y", "opm_acceleration_pp", "gpm_change_yoy_pp",
    "profit_growth_acceleration_pp", "sales_growth_streak_quarters", "profit_growth_streak_quarters",
    "material_cost_latest_quarter_pct", "material_cost_last_year_pct", "employee_cost_latest_quarter_pct",
    "employee_cost_last_year_pct", "other_expenses_latest_quarter_pct", "other_expenses_last_year_pct",
    "power_fuel_latest_quarter_pct", "power_fuel_last_year_pct", "freight_latest_quarter_pct",
    "freight_last_year_pct", "ad_promo_latest_quarter_pct", "ad_promo_last_year_pct",
    "marketing_efficiency_latest_quarter", "marketing_efficiency_last_year", "material_cost_last_year",
    "material_cost_preceding_year", "employee_cost_last_year", "employee_cost_preceding_year",
    "minority_share_last_year", "minority_share_preceding_year", "dividends_paid_last_year",
    "dividends_paid_preceding_year", "acquisition_outflow_last_year", "acquisition_outflow_preceding_year",
    "acquisition_outflow_to_sales_last_year", "inorganic_growth_flag", "standalone_pat_ttm", "profit_leakage_pct",
    "profit_leakage_latest_quarter_pct", "incremental_asset_turnover_3y", "cfo_to_pat", "cash_tax_rate",
    "effective_tax_rate", "exceptional_to_pbt", "exceptional_quarters_4q", "capex_intensity", "rpt_to_sales",
    "intangibles_to_equity", "audit_fees_to_sales", "managerial_remuneration_to_pat",
    "capital_commitments_to_net_worth", "unquoted_investments", "quoted_investments_market_value",
    "revaluation_reserve", "rf_audit_qualified", "pe_denominator", "roe_numerator", "roe_denominator",
    "roce_numerator", "roce_denominator", "ev_ebitda_denominator", "opm_numerator", "opm_denominator",
    "beneish_dsri", "beneish_gmi", "beneish_aqi", "beneish_sgi", "beneish_depi", "beneish_sgai", "beneish_lvgi",
    "beneish_tata", "piotroski_roa_positive", "piotroski_cfo_positive", "piotroski_roa_up",
    "piotroski_cfo_above_pat", "piotroski_leverage_down", "piotroski_current_ratio_up", "piotroski_no_dilution",
    "piotroski_gross_margin_up", "piotroski_asset_turnover_up", "bs_accruals", "depreciation_rate",
    "asset_age_proxy", "debtor_days_change_yoy", "ccc_change_yoy", "h1_bs_as_of", "debtor_days_h1",
    "inventory_days_h1", "debtor_days_h1_change_yoy", "inventory_days_h1_change_yoy", "segment_period_end",
    "segment_count", "largest_segment_revenue_share", "fastest_growing_segment",
    "fastest_growing_segment_growth_yoy", "largest_segment_margin_change_yoy_pp", "rpt_fy_end",
    "rpt_counterparties", "rpt_leak_pct", "rpt_purchases_to_sales", "rpt_royalty_to_sales",
    "rpt_loans_given_to_net_worth", "insider_receivables_as_of", "insider_receivables",
    "insider_receivables_to_receivables", "has_insider_receivables", "subsidiary_fy_end", "parent_profit_share",
    "largest_subsidiary_profit_share", "largest_subsidiary_name", "consolidated_entities_count",
)  # fmt: skip

_DECLARED = declared_columns()
COLUMNS = tuple(c for c, _ in _DECLARED["screener_features"])  # the history view's columns, in order
DAILY_COLUMNS = tuple(c for c, _ in _DECLARED["features_daily"])
OPEN_END = "coalesce(e.valid_to_date, DATE '9999-12-31')"  # as the view: an OR with IS NULL defeats the join
_SAME = " AND ".join(f"a.{c} IS NOT DISTINCT FROM b.{c}" for c in EVENT_COLUMNS)


def write_day(con, as_of: date, rows: list[dict], *, entities=None) -> None:
    """Store the rows of `as_of` (dicts carrying every COLUMNS key). `entities=None`: they replace the whole day;
    otherwise only the day's rows of those entities and of the rows' securities are replaced (incremental, §11.10)."""
    if entities is None:
        con.execute("DELETE FROM features_daily WHERE as_of_date = ?", [as_of])
    else:
        from financials.fundamentals import in_list

        by_ent, by_sec = in_list("entity_id", entities), in_list("security_id", {r["security_id"] for r in rows})
        con.execute(
            f"DELETE FROM features_daily WHERE as_of_date = ? AND ({by_ent[0]} OR {by_sec[0]})",
            [as_of, *by_ent[1], *by_sec[1]],
        )
    if not rows:
        return
    _insert(con, "features_daily", rows, DAILY_COLUMNS)
    _set_events(con, as_of, rows)


def _insert(con, table: str, rows: list[dict], columns) -> None:
    """INSERT the `columns` of `rows` through Arrow, built column by column: `pa.table` of lists infers each
    column's type exactly as `db.insert_rows` (`Table.from_pylist`) does, without copying every row dict."""
    import pyarrow as pa

    src = pa.table({c: [r[c] for r in rows] for c in columns})
    name = f"_src_{table}"
    con.register(name, src)
    try:
        con.execute(f"INSERT INTO {table} BY NAME SELECT * FROM {name}")
    finally:
        con.unregister(name)


def _set_events(con, as_of: date, rows: list[dict]) -> None:
    """Set the EVENT values of `rows` (one per security) on [as_of, next materialised day): batched, a handful of
    statements per day whatever the number of securities."""
    con.execute(
        "CREATE OR REPLACE TEMP TABLE _ev_new AS SELECT security_id, "
        + ", ".join(EVENT_COLUMNS)
        + " FROM features_events LIMIT 0"
    )
    try:
        _insert(con, "_ev_new", rows, ("security_id", *EVENT_COLUMNS))  # the column types' cast, as a direct insert
        # The securities whose values differ from the interval covering as_of (or that have none), with the next
        # materialised day of each (the daily rows of as_of are already written).
        con.execute(
            "CREATE OR REPLACE TEMP TABLE _ev_chg AS SELECT a.security_id, nx.next_day FROM _ev_new a "
            "LEFT JOIN features_events b ON b.security_id = a.security_id AND b.valid_from_date <= ? "
            "AND ? < coalesce(b.valid_to_date, DATE '9999-12-31') "
            "LEFT JOIN (SELECT security_id, min(as_of_date) AS next_day FROM features_daily WHERE as_of_date > ? "
            "AND security_id IN (SELECT security_id FROM _ev_new) GROUP BY 1) nx ON nx.security_id = a.security_id "
            f"WHERE b.security_id IS NULL OR NOT ({_SAME})",
            [as_of, as_of, as_of],
        )
        if not con.execute("SELECT count(*) FROM _ev_chg").fetchone()[0]:
            return
        # Every interval overlapping [as_of, next_day) is cut out: its parts before as_of and from next_day stay.
        con.execute(
            "CREATE OR REPLACE TEMP TABLE _ev_ov AS SELECT e.*, g.next_day FROM features_events e JOIN _ev_chg g "
            "USING (security_id) WHERE (g.next_day IS NULL OR e.valid_from_date < g.next_day) "
            "AND (e.valid_to_date IS NULL OR e.valid_to_date > ?)",
            [as_of],
        )
        con.execute(
            "DELETE FROM features_events e USING _ev_ov o "
            "WHERE e.security_id = o.security_id AND e.valid_from_date = o.valid_from_date"
        )
        con.execute(
            "INSERT INTO features_events BY NAME SELECT * EXCLUDE (next_day, valid_to_date), "
            "CAST(? AS DATE) AS valid_to_date FROM _ev_ov WHERE valid_from_date < ?",
            [as_of, as_of],
        )
        con.execute(
            "INSERT INTO features_events BY NAME SELECT * EXCLUDE (next_day, valid_from_date), "
            "next_day AS valid_from_date FROM _ev_ov "
            "WHERE next_day IS NOT NULL AND (valid_to_date IS NULL OR valid_to_date > next_day)"
        )
        con.execute(
            "INSERT INTO features_events BY NAME SELECT a.*, CAST(? AS DATE) AS valid_from_date, "
            "g.next_day AS valid_to_date FROM _ev_new a JOIN _ev_chg g USING (security_id)",
            [as_of],
        )
        _merge_adjacent(con, as_of)
    finally:
        for t in ("_ev_new", "_ev_chg", "_ev_ov", "_ev_pairs", "_ev_isl"):
            con.execute(f"DROP TABLE IF EXISTS {t}")


def _merge_adjacent(con, as_of: date) -> None:
    """Merge the changed securities' adjacent intervals that hold identical values (a re-materialised past day that
    now equals a neighbour), so an incremental run leaves the intervals a full run would. No two adjacent intervals
    were identical before the write, and it moved boundaries only at as_of and next_day: only the pairs meeting
    there can be identical."""
    con.execute(
        "CREATE OR REPLACE TEMP TABLE _ev_pairs AS SELECT b.security_id, b.valid_from_date FROM _ev_chg g "
        "JOIN features_events b ON b.security_id = g.security_id "
        "AND (b.valid_from_date = CAST(? AS DATE) OR b.valid_from_date = g.next_day) "
        "JOIN features_events a ON a.security_id = b.security_id AND a.valid_to_date = b.valid_from_date "
        f"WHERE {_SAME}",
        [as_of],
    )
    if not con.execute("SELECT count(*) FROM _ev_pairs").fetchone()[0]:
        return
    con.execute(
        """CREATE OR REPLACE TEMP TABLE _ev_isl AS
           SELECT security_id, valid_from_date, valid_to_date, cont,
                  last_value(valid_to_date) OVER (PARTITION BY security_id, isl ORDER BY valid_from_date
                      ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS isl_to
           FROM (SELECT *, sum(CASE WHEN cont THEN 0 ELSE 1 END) OVER (PARTITION BY security_id
                     ORDER BY valid_from_date) AS isl
                 FROM (SELECT e.security_id, e.valid_from_date, e.valid_to_date, p.security_id IS NOT NULL AS cont
                       FROM features_events e LEFT JOIN _ev_pairs p USING (security_id, valid_from_date)
                       WHERE e.security_id IN (SELECT security_id FROM _ev_pairs)))"""
    )
    con.execute(
        "DELETE FROM features_events e USING _ev_isl i "
        "WHERE i.cont AND e.security_id = i.security_id AND e.valid_from_date = i.valid_from_date"
    )
    con.execute(
        "UPDATE features_events e SET valid_to_date = i.isl_to FROM _ev_isl i WHERE NOT i.cont "
        "AND e.security_id = i.security_id AND e.valid_from_date = i.valid_from_date "
        "AND e.valid_to_date IS DISTINCT FROM i.isl_to"
    )


def write_rows(con, rows) -> int:
    """Store history rows of any days (each a dict of COLUMNS keys; a missing key is NULL): day by day, ascending,
    each row replacing its security's row of that day. For tools and tests that used to insert into the table."""
    by_day: dict[date, dict[str, dict]] = defaultdict(dict)
    rows = list(rows)
    unknown = {k for r in rows for k in r} - set(COLUMNS)
    if unknown:
        raise KeyError(f"screener_features_history: unknown columns {sorted(unknown)}")
    for r in rows:
        by_day[r["as_of_date"]][r["security_id"]] = {c: r.get(c) for c in COLUMNS}
    for d in sorted(by_day):
        day = list(by_day[d].values())
        write_day(con, d, day, entities=frozenset())  # replaces only these securities' rows of the day
    return len(rows)


def delete_from(con, from_date: date) -> int:
    """Remove every materialised day >= from_date (rebuild-market): the daily rows, the intervals that start on or
    after it; the interval still covering an earlier day becomes open again. Returns the daily rows removed."""
    n = len(con.execute("DELETE FROM features_daily WHERE as_of_date >= ? RETURNING 1", [from_date]).fetchall())
    con.execute("DELETE FROM features_events WHERE valid_from_date >= ?", [from_date])
    con.execute("UPDATE features_events SET valid_to_date = NULL WHERE valid_to_date >= ?", [from_date])
    return n


def truncate(con) -> None:
    """Empty the history (a full rebuild from scratch, the benchmark)."""
    con.execute("DELETE FROM features_daily")
    con.execute("DELETE FROM features_events")


def check_invariants(con) -> dict[str, int]:
    """Counts of invariant breaches (all 0 on a healthy store): overlapping intervals, identical adjacent intervals,
    daily rows covered by no interval or by more than one."""
    overlaps = con.execute(
        "SELECT count(*) FROM features_events a JOIN features_events b ON a.security_id = b.security_id "
        "AND a.valid_from_date < b.valid_from_date AND (a.valid_to_date IS NULL OR a.valid_to_date > b.valid_from_date)"
    ).fetchone()[0]
    same = con.execute(
        "SELECT count(*) FROM features_events a JOIN features_events b ON a.security_id = b.security_id "
        f"AND a.valid_to_date = b.valid_from_date WHERE {_SAME}"
    ).fetchone()[0]
    cover = con.execute(
        "SELECT count(*) FILTER (WHERE n = 0), count(*) FILTER (WHERE n > 1) FROM (SELECT d.as_of_date, "
        "d.security_id, count(e.security_id) AS n FROM features_daily d LEFT JOIN features_events e "
        "ON e.security_id = d.security_id AND e.valid_from_date <= d.as_of_date "
        f"AND d.as_of_date < {OPEN_END} GROUP BY 1, 2)"
    ).fetchone()
    return {"overlaps": overlaps, "identical_neighbours": same, "uncovered": cover[0], "multiply_covered": cover[1]}


def is_legacy(con) -> bool:
    """The database still holds the wide screener_features_history table (before event-sparse storage)."""
    from financials.db import _LEGACY_HISTORY

    return bool(con.execute(_LEGACY_HISTORY).fetchone()[0])


LEGACY_TABLE = "screener_features_history_legacy"
_MIGRATE_CHUNK = 40  # EVENT columns compared per window pass (bounded memory on a 1.3 M-row history)


def migrate_legacy(con) -> dict:
    """One-off `migrate-sparse-history` (the single writer; architecture §4.1): convert a database whose
    screener_features_history is still the wide table into features_daily + features_events + the view, in one
    transaction: the wide table is renamed, apply_schema creates the new tables and the view, `convert_wide` fills
    and verifies them, and the wide table is dropped; any failure rolls the whole migration back. Run `compact`
    afterwards: the dropped table leaves dead blocks in the file."""
    from financials.db import apply_schema

    if not is_legacy(con):
        return {"status": "NOTHING", "message": "screener_features_history is already a view"}
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(f"ALTER TABLE screener_features_history RENAME TO {LEGACY_TABLE}")
        apply_schema(con)
        out = convert_wide(con, LEGACY_TABLE)
        con.execute(f"DROP TABLE {LEGACY_TABLE}")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    con.execute("COMMIT")
    return {"status": "MIGRATED", **out}


def convert_wide(con, source: str) -> dict:
    """Fill the (empty) features_daily / features_events from a wide history table `source` (any name DuckDB
    resolves, e.g. an attached read-only database's table) inside the caller's transaction: every row's DAILY
    columns are copied, and each security's EVENT values become one interval per run of identical consecutive rows
    (exact IS DISTINCT FROM comparisons, never a hash). Then the view is checked against `source` (row count, and
    every row identical through EXCEPT ALL both ways, 20 days at a time); a difference raises. Columns `source`
    lacks are NULL (as the column upgrade would have added them)."""
    old = {d[0] for d in con.execute(f"SELECT * FROM {source} LIMIT 0").description}
    src = lambda c: c if c in old else f"NULL AS {c}"  # noqa: E731
    daily = ", ".join(map(src, DAILY_COLUMNS))
    con.execute(f"INSERT INTO features_daily BY NAME SELECT {daily} FROM {source}")
    w = "WINDOW w AS (PARTITION BY security_id ORDER BY as_of_date)"
    con.execute(
        "CREATE OR REPLACE TEMP TABLE _mig_starts AS SELECT security_id, as_of_date FROM (SELECT security_id, "
        f"as_of_date, lag(as_of_date) OVER w IS NULL AS first FROM {source} {w}) WHERE first"
    )
    present = [c for c in EVENT_COLUMNS if c in old]
    for i in range(0, len(present), _MIGRATE_CHUNK):
        chg = " OR ".join(f"{c} IS DISTINCT FROM lag({c}) OVER w" for c in present[i : i + _MIGRATE_CHUNK])
        con.execute(
            "INSERT INTO _mig_starts SELECT security_id, as_of_date FROM (SELECT security_id, as_of_date, "
            f"lag(as_of_date) OVER w IS NOT NULL AND ({chg}) AS chg FROM {source} {w}) WHERE chg"
        )
    con.execute(
        "INSERT INTO features_events BY NAME SELECT s.security_id, s.as_of_date AS valid_from_date, "
        "lead(s.as_of_date) OVER (PARTITION BY s.security_id ORDER BY s.as_of_date) AS valid_to_date, "
        + ", ".join(f"h.{c}" if c in old else f"NULL AS {c}" for c in EVENT_COLUMNS)
        + f" FROM (SELECT DISTINCT security_id, as_of_date FROM _mig_starts) s JOIN {source} h "
        "USING (security_id, as_of_date)"
    )
    con.execute("DROP TABLE _mig_starts")
    n_old = con.execute(f"SELECT count(*) FROM {source}").fetchone()[0]
    n_new = con.execute("SELECT count(*) FROM screener_features_history").fetchone()[0]
    cols = ", ".join(map(src, COLUMNS))
    diff = 0
    if n_old == n_new:
        days = [d for (d,) in con.execute(f"SELECT DISTINCT as_of_date FROM {source} ORDER BY 1").fetchall()]
        for i in range(0, len(days), 20):  # bounded memory: 20 days per comparison
            lo, hi = days[i], days[min(i + 19, len(days) - 1)]
            a = f"SELECT {cols} FROM {source} WHERE as_of_date BETWEEN ? AND ?"
            b = f"SELECT {', '.join(COLUMNS)} FROM screener_features_history WHERE as_of_date BETWEEN ? AND ?"
            diff += sum(n for (n,) in con.execute(
                f"SELECT count(*) FROM (({a}) EXCEPT ALL ({b})) UNION ALL "
                f"SELECT count(*) FROM (({b}) EXCEPT ALL ({a}))",
                [lo, hi, lo, hi, lo, hi, lo, hi],
            ).fetchall())  # fmt: skip
    if n_old != n_new or diff:
        raise RuntimeError(f"migrate-sparse-history: view differs from the wide table ({n_new} vs {n_old} rows, "
                           f"{diff} differing rows); rolled back")  # fmt: skip
    return {
        "rows": n_old,
        "daily_rows": con.execute("SELECT count(*) FROM features_daily").fetchone()[0],
        "event_intervals": con.execute("SELECT count(*) FROM features_events").fetchone()[0],
    }
