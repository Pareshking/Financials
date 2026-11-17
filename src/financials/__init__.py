"""Indian equity research, screening and point-in-time backtesting engine."""

# 0.10.5: X150-X156 quarantine rules (annual "Actual" rounding, undeclared pre-cutoff contexts, comparative stub
#         periods, E&P face line, exchange-specific SHP taxonomy, insurer service-expense adjustments);
# 0.10.4: SHP20 2022-09-30 SHP taxonomy mutual-fund member / holder axis (re-parses Q3-Q4 FY25 Reg. 31 files);
# 0.10.3: X105 missing / zero NCI in the attribution rules;
# 0.10.2: X104 declared dates with day and month swapped (re-parses 4 life-insurer filings);
# 0.10.1: X101 ISIN of another issuer (re-promotes Gillette Q1 FY26 under its symbol); X100 is a reader change;
# 0.10.0: X95 owners/NCI swapped, X96 missing NCI element; segment and geography rows (segment_observations, X97-X99);
#         parser versions now compare numerically (0.10.0 > 0.9.0), see db.version_key;
# 0.9.0: X84-X87, X91-X93 attribution recovery / withholding and stale context dates (re-parses those filings);
# 0.8.0: X83 visibility from listing creation / file-name time (re-promotes backdated re-filings);
# 0.7.0: SHP16-SHP18 (old SHP taxonomy, event dates, percent scale); 0.6.0: zero-drop line items (C24);
# 0.5.0: REG34_ANNUAL; audit mappings
PARSER_VERSION = "0.10.5"
