# Hidden-gem ratios and investor-hat screens

Owner request (2026-11-15): ratios that find good companies "hiding in plain sight", seen through several investor
hats, kept in the ratio dictionary (feature columns + DSL aliases + saved screens) so they re-run every results season.
First manual run: 2026-11-13 data, Nifty 500 (results in the session log; not stored here).

Principles, learned from the first run:
1. **Forensic gate first.** Every hat starts from the same exclusions, or screens surface manipulators and value traps.
2. **Cyclicals are judged on the cycle, not PE.** A low PE at peak commodity margins topped the naive screens
   (copper, aluminium, refining, shipping). Cyclicals get their own hat.
3. **"Sustained" beats "high".** Growth must hold in each of the last two quarters, not one.
4. **"Hidden" means under-owned or mispriced**, measured by institutional ownership and valuation, not by obscurity.
5. **History-gated signals are built now and return NULL** until the window exists (C9), then switch on.
6. **Growth and PE are measured on core profit, never on reported PAT alone.** GSK Pharma Q2 FY27 reported PAT +30%
   YoY, but ~Rs 42 Cr of other income was interest on a tax refund; profit before tax excluding other income and
   exceptional items grew +22%, in line with revenue (+21%), and PE on core earnings is ~41, not 39.5. Across the
   Nifty 500 (Q2 FY27), other income or exceptional items lifted reported profit growth by >= 8pp for 40 of 364
   non-financial companies (e.g. Hexaware +16% reported vs -7% core, Birlasoft +38% vs -3%, Titan +114% vs +55%).
   The TTM `other_income_to_pbt` gate dilutes a one-quarter spike, so the spike is measured per quarter.

All `_pct` columns are fractions (DSL shows x100), money in rupees, PE on owners' profit.

## A. Signal columns (batch G)

| Column | Definition | Hat(s) | Data | Status |
|---|---|---|---|---|
| `sales_yoy_latest_q` / `sales_yoy_preceding_q` | Sales growth vs the same quarter a year earlier, for the latest and the preceding quarter | Growth, GARP, Core | quarterly results | batch A |
| `profit_yoy_latest_q` / `profit_yoy_preceding_q` | Same for owners' profit; NULL when the base is <= 0 | Growth, GARP | quarterly results | batch A |
| `core_profit_yoy_latest_q` / `core_profit_yoy_preceding_q` | YoY growth of PBT - other income - exceptional items (same quarter a year earlier); NULL when the base is <= 0 | all growth hats (replace PAT growth) | quarterly results | G |
| `other_income_lift_pp` | profit YoY minus core profit YoY (latest quarter); flags one-offs such as tax-refund interest | gate, all | the above | G |
| `pe_core` | market cap / (TTM PBT - other income - exceptional items, after the TTM effective tax rate); owners' share when NCI exists | Value, Core | TTM | G |
| `growth_sustained` | Both quarters' sales YoY >= 12% | Core | the two above | G |
| `growth_acceleration_pp` | sales YoY latest minus preceding quarter | Growth | the two above | G |
| `opm_change_yoy_pp` | Quarterly OPM minus OPM of the same quarter a year earlier | Turnaround, Core (stability) | quarterly results | G |
| `operating_leverage` | profit YoY / sales YoY (latest quarter); NULL if sales YoY <= 0 | GARP | the above | G |
| `peg` | pe_core / (100 x core profit YoY latest quarter); later TTM-on-TTM growth when 8 quarters exist | GARP | PE + growth | G (catalogue G168) |
| `earnings_yield` | EBIT TTM / EV | Value, Magic formula | built inputs | G |
| `magic_formula_rank` | Rank of earnings yield + rank of ROCE within the gated non-financial universe of the same as-of date (lower = better) | Value | cross-section | G |
| `inst_holding_pct` | FII + DII holding | Under-owned | Reg. 31 | G |
| `inst_holding_change_qoq_pp` | change vs previous quarter (back-to-back quarters only) | Under-owned, flows | Reg. 31 | batch 5 |
| `under_owned` | inst <= 15% and promoter >= 50% and pledge = 0 | Under-owned | Reg. 31 | G |
| `cyclical_flag` | industry in a cyclical set (Metals & Mining; Oil, Gas & Consumable Fuels; shipping; refining) — exact list in code with the industry source | all (exclusion / own hat) | industry from the Nifty 500 snapshot (coarse; 4-level classification is a new free source) | G |
| `forensic_clean` | other_income_lift_pp < 8 (per quarter); not restatement_suspected; Beneish M < -1.78 or NULL; pledge < 5%; no auditor resignation / fraud-default event in 90 days; other income < 30% of PBT | all | built inputs | G |
| `cash_conversion_ok` | CFO/EBITDA >= 0.7 | Core, Quality | built | G |
| `dist_52w_low`, `drawdown_from_52w_high` | price vs 52-week low / high | Contrarian | prices | batch B |
| `capex_pay_off_signal` | CWIP / gross block >= 25% and capex / depreciation >= 2 and D/E <= 1 | Capex cycle | Reg. 34 / half-year balance sheet | G |
| `roce_stability_5y`, `opm_stability_5y` | 1 - (std / mean) of annual ROCE / OPM over 5 fiscal years | Compounder | annual | WHEN HISTORY (FY2030) |
| `pe_vs_own_5y_median` | PE / own 5-year median PE | Value | daily PE history | WHEN HISTORY (2029-10) |
| `hat_*` booleans + `hats_passed` | one boolean per screen in section B; count of hats passed | all | the above | G |
| `gem_score` | z-score blend within the gated non-financial, non-cyclical universe: ROCE 1.0, sustained growth 1.0, earnings yield 1.2, under-ownership 0.8, cash conversion 0.6, margin trend 0.6 (inputs clipped) | Core | the above | G |

## B. Saved screens (one per hat)

Each starts with `forensic_clean`. Financials (lenders, insurers) are excluded unless the hat says otherwise.

| Hat | Rule |
|---|---|
| Core: hidden compounder | not cyclical; mcap 3,000-75,000 Cr; inst <= 35%; ROCE >= 18%; growth_sustained; OPM change >= -1.5pp; CFO/EBITDA >= 0.7; D/E <= 0.5; pe_core <= 40; 6m return <= 30%; ranked by gem_score |
| Quality at a fair price | ROCE >= 20%; ROE >= 15%; D/E <= 0.5; CFO/EBITDA >= 0.7; pe_core <= universe median; core profit YoY >= 10% |
| Magic formula | ROCE >= 15%; top 15 by magic_formula_rank |
| GARP | sales YoY >= 20% latest and >= 15% preceding; core profit YoY >= sales YoY; ROCE >= 15%; PEG (on core profit growth and pe_core) <= 1 |
| Turnaround / margin inflection | OPM change >= +3pp; sales YoY >= 10%; PE <= 40; 6m return <= 15% |
| Under-owned with promoter skin | under_owned; ROCE >= 18%; core profit YoY >= 15%; mcap below universe median |
| Cash machine | FCF/PAT >= 0.8; ROIC >= 25%; price/CFO <= 30; working-capital days <= 45 |
| Fallen quality (contrarian) | 52-week drawdown >= 30%; ROCE >= 18%; D/E <= 0.5; core profit YoY >= 0; Piotroski >= 6 or NULL |
| Capex about to pay off | capex_pay_off_signal; ROCE >= 15%; sales YoY >= 10% |
| Cyclicals at a sane price | cyclical; ROCE >= 15%; sales YoY >= 15%; judged by OPM vs its own history (WHEN HISTORY) — until then listed, never ranked by PE |
| Lenders | lender; ROA >= 1.5%; P/B <= 2.5; profit YoY >= 15%; GNPA <= 3% where filed |

## C. Known limits

- Universe is the Nifty 500 (fundamentals coverage); true small-cap discovery needs the universe widened.
- With six quarters of fundamentals, the screens find current quality, change and mispricing, not proven multi-cycle
  compounders; the WHEN HISTORY columns close that gap as data accumulates.
- Large YoY jumps (e.g. +50% sales) should be confirmed against the results PDF before analysis; commodity
  pass-through (copper in cables) inflates sales growth without volume growth.
- One-offs booked inside operating lines (a provision write-back in other expenses, a one-time export incentive in
  revenue) are not caught by the core-profit measure; they need the results PDF notes or Reg. 34 note disclosures.
- Industry labels are NSE's 20 sector groups; peer-relative ratios need the 4-level classification (new free source).
