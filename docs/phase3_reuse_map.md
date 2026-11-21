# Phase 3 reuse map: the owner's NSE-BSE-Insider-Tracker

Owner 2026-11-21: "Many of next phase requirements you can find from here already built". Source: public repo
`Pareshking/NSE-BSE-Insider-Tracker` at `ed0e459` (2026-11-17), its `docs/DATA_INVENTORY.md` (23 Oct 2026).
Read only; nothing copied. Rule for Phase 3: import or port from the tracker before building a feed here, and keep
this repo's evidence rules (real fixture, MANIFEST row, test) for anything that lands in this engine.

## Already built in the tracker (reuse)

| Our item | Tracker inventory row | Notes |
|---|---|---|
| G100 insider trading PIT Reg. 7(2) | A1 insider trades (NSE + BSE) | person, role, mode, shares, value, holdings before / after, filing time |
| G100 SAST Reg. 29 | A4 SAST Reg 29 (NSE + BSE) | acquirer, 29(1) / 29(2), % moved, stake after |
| G92 SAST Reg. 31 encumbrance events | A5 (NSE, from 22 Oct 2026) | created / released / invoked, lender, shares, % |
| G102 bulk and block deals | A2, A3 | participant type derived from names (MF, insurer, FPI, PMS / AIF ...) |
| G194 investor graph (part) | A3 + F27 investor alias list | one investor across spellings |
| G193 forward event calendar | B7 board meetings (60 days ahead) | purpose: results, dividend, buyback, bonus, fund raising |
| G142 daily buyback report | B8 tender offers, B9 daily buyback reports, B10 buybacks | open-market max price only in PDFs (tracker gap) |
| G163 IPO / lock-in calendar (part) | D14-D19 preferential issues, allottees, lock-in lines, rights, QIPs | not IPO subscription |
| G139 ASM / GSM lists, G140 price band / circuit, G207 circuit-lock days | E23 tradability (from 12 Oct 2026) | warning flags only in the tracker |
| G62 announcement keyword watch (part), G118 penalties (part) | G28-G30 announcements + text cache + AI reader | PDF text with quote-checked values |
| Later item 31: BSE-only companies >= Rs 500 Cr | `scripts/bse_market_cap.py`, C12 shareholding of BSE-only companies | universe there is Rs 100 Cr |

## Not built there (Phase 3 here)

F&O (G125-G128, G184), AMFI scheme portfolios (G122, G179), BRSR (G109), governance XBRL (G121), RBI / macro
(G135, G147, G148), index weights (G129), NSDL FPI (G123, G124), bond / CP yields (G136), credit ratings XBRL (G98),
the point-in-time backtester (G191), Excel exporter (G165), natural-language to DSL (G188). The tracker mentions some
of these in its docs; its inventory lists no collector for them (keyword check 2026-11-21).
