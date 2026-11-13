# Verification prompt: Screener.in residuals and ratio definitions

Paste everything below the line into Gemini (with web search on). All figures are Rs crore, FY = April–March.

---

I am building my own stock screener for Indian listed companies from NSE/BSE XBRL filings (Integrated Filing
quarterly results and Reg. 34 annual-report XBRL). I compare my numbers with Screener.in (data by CMOTS). Please
use web search (Screener.in help pages, "How Screener calculates" docs, forum posts, CMOTS methodology, annual
reports) to **confirm or refute** each item below. For every answer, cite a source URL, say whether it is
documented or your inference, and do not guess. If you cannot find evidence, say "not found".

## A. Screener website ratio definitions (Ratios table on a company page)

Observed on TCS consolidated (Screener page, 13-Nov-2026):

| FY | Debtor Days | Inventory Days | Days Payable | Cash Conversion Cycle | Working Capital Days | ROCE % |
|---|---|---|---|---|---|---|
| FY25 (Mar 2025) | 84 | blank | blank | 84 | 34 | 65% |
| FY26 (Mar 2026) | 93 | blank | blank | 93 | 38 | 63% (peer table 63.03) |

TCS FY26 filed figures: Sales 267,021; receivables 67,714; inventory 29; trade payables 14,808; cost of
materials 43, change in inventories −2 (COGS ≈ 41); current assets 135,705; current liabilities 60,914; cash &
bank 12,908; PBT 65,487 after exceptional items −4,526 (PBT before exceptional 70,013); interest 1,227; total
assets (DTA netted against DTL) 181,167; equity capital 362; reserves 106,878; borrowings incl. leases 11,283;
NCI 1,238. FY25: Sales 255,324; total assets 158,649; current liabilities 53,001; equity capital 362; reserves
94,394; borrowings 9,392; NCI 1,015. FY24: total assets 145,472; current liabilities 46,104; capital 98,510
(362 + 90,127 + 8,021); NCI 830.

1. **Debtor Days** = closing trade receivables / (Sales / 365)? (Mine: 92.6 / 84.4. Matches.)
2. **Inventory Days** and **Days Payable**: what are the exact formulas (denominator Sales, COGS, raw material
   cost or purchases? closing or average balance?) and **when does Screener leave them blank**? For TCS both are
   blank although inventory (29) and payables (14,808) are non-zero. A COGS denominator would give ~258 inventory
   days, so a plain COGS rule doesn't explain the blank. Is it blanked by sector, or below a threshold, or for
   another reason?
3. **Cash Conversion Cycle** = Debtor Days + Inventory Days − Days Payable, with blanks treated as 0? (TCS shows
   CCC = Debtor Days.)
4. **Working Capital Days**: my fit is (current assets − cash & bank − current investments − current
   liabilities) / (Sales / 365) = 38.4 (FY26) and 34.1 (FY25). Is that the documented definition? If not, what is?
5. **ROCE %** on the website: the Excel export template uses (PBT + Interest) × 2 / (opening + closing (Equity
   Capital + Reserves + Borrowings)), which gives 59.9% for FY26, not 63%. Which is it?
   - (PBT before exceptional items + interest) / average (total assets − current liabilities) gives 63.07% / 64.5%.
   - The same EBIT over average (capital + reserves + borrowings + NCI) gives 63.35% / 64.7%.
   - Or another definition: does the website exclude exceptional items or include minority interest?

## B. Statement residuals I could not explain from the XBRL

For each: is this a known Screener/CMOTS reclassification? Which line item does it move, and does the
company's annual report (notes to accounts) show an item of that amount?

1. **Reliance Industries, consolidated FY26.**
   - **P&L:** Screener Sales is 1,439 lower than mine and Other Income 116 lower. Its "other expense" sub-rows are
     1,555 (= 1,439 + 116) lower than the filed other expenses. The annual-report figures give the same pattern:
     1,255 + 116 = 1,371.
   - **Balance sheet:** Screener Borrowings 402,962 vs mine 398,000 (non-current borrowings 270,751 + current
     103,670 + lease liabilities 16,198 + 7,381). Other Liabilities is 4,962 lower by the same amount. This is
     identical in the Q4 filing and the annual report.
   - Which liability does Screener reclassify as borrowings (e.g. deferred payment liabilities, interest
     accrued, acceptances, spectrum dues)?
   - Is the 116 the loss on disposal of PPE? (It equals the filed amount, but for SRF a similar loss is not moved,
     so I doubt it.)
2. **ITC, consolidated FY26.** Screener Other Income 2,523.09 vs mine 2,134.10 (+388.99). Mine = reported other
   income 2,425.80 + exceptional items −291.70.
   - 377.08 of the gap is the share of profit of associates/JVs, which Screener adds to Other Income.
   - The remaining 11.91 is an amount Screener takes out of other expenses. What is it?
3. **Cummins India, standalone FY26.** Screener Other Income 701.86 vs mine 670.45 (+31.41). Screener PBT and
   Net Profit are also about 31.5 higher. Mine = reported other income 720.50 + exceptional items −50.05.
   - No filed figure equals ~31.4–31.6.
   - Does Screener treat part of the exceptional item (or a tax-effected exceptional, or discontinued
     operations) differently? Net Profit 2,361.75 vs filed PAT 2,330.18.
4. **Elin Electronics, consolidated Q4 FY26.** Screener Borrowings 0.54 higher and Other Liabilities 0.53 lower.
   **Standalone FY25** total liabilities 592.61 vs mine 591.75 (Other Liabilities −0.85, Investments −0.87). The
   FY26 annual-report XBRL is not filed yet.
5. **New India Assurance, FY26.** Screener Net Profit is 9.26 higher than the filed PAT. It equals "profit
   carried to balance sheet" − PAT. Confirm which line Screener uses for insurers.
6. **TCS, FY26.** An expense-netting residual of 2 (Screener's other-expense sub-rows vs filed other expenses).

Please answer A1–A5 and B1–B6 separately, with sources.
