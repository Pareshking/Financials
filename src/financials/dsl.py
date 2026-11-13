"""Screener DSL → parameterised DuckDB SQL (architecture §14).

    query      := or_expr
    or_expr    := and_expr ("OR" and_expr)*
    and_expr   := not_expr ("AND" not_expr)*
    not_expr   := "NOT" not_expr | comparison | "(" or_expr ")"
    comparison := arith ("<" | "<=" | ">" | ">=" | "=" | "!=") arith
    arith      := term (("+" | "-") term)*
    term       := factor (("*" | "/") factor)*
    factor     := NUMBER | ALIAS | "(" arith ")" | "-" factor

Safety: user text never reaches SQL. Aliases resolve to fixed SQL expressions from ALIASES (or to
saved custom ratios, themselves parsed by this grammar); numbers become bound parameters. Division
compiles to `x / NULLIF(y, 0)`; any NULL comparison is not TRUE, so missing data never passes a filter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from financials.timeutil import utc_now

# alias (lower-case, single-spaced) -> (SQL over screener_features columns, unit note)
ALIASES: dict[str, tuple[str, str]] = {
    "current price": ("close", "INR"),
    "market capitalization": ("(market_cap / 10000000)", "INR crore"),
    "market cap": ("(market_cap / 10000000)", "INR crore"),
    "enterprise value": ("(enterprise_value / 10000000)", "INR crore"),
    "sales": ("(sales_ttm / 10000000)", "INR crore, TTM"),
    "ebitda": ("(ebitda_ttm / 10000000)", "INR crore, TTM"),
    "net profit": ("(pat_ttm / 10000000)", "INR crore, TTM"),
    "free cash flow": ("(fcf_ttm / 10000000)", "INR crore, TTM (H1/FY bridge)"),
    "net debt": ("(net_debt / 10000000)", "INR crore"),
    "book value": ("(total_equity / 10000000)", "INR crore"),
    "price to earning": ("pe", "x"),
    "pe": ("pe", "x"),
    "price to book value": ("pb", "x"),
    "pb": ("pb", "x"),
    "ev to ebitda": ("ev_ebitda", "x"),
    "opm": ("(opm * 100)", "%"),
    "sales growth": ("(sales_growth_yoy * 100)", "% YoY on TTM"),
    "profit growth": ("(profit_growth_yoy * 100)", "% YoY on TTM"),
    "roe": ("(roe * 100)", "%"),
    "roce": ("(roce * 100)", "%"),
    "roic": ("(roic * 100)", "%"),
    "croic": ("(croic * 100)", "%"),
    "debt to equity": ("debt_to_equity", "x"),
    "fcf yield": ("(fcff_yield * 100)", "% of EV (unlevered)"),
    "other income to pbt": ("(other_income_to_pbt * 100)", "%"),
    "altman z": ("altman_z_dd", "Z'' score"),
    "piotroski score": ("piotroski_f", "0..9 (NULL without two fiscal years)"),
    "piotroski f score": ("piotroski_f", "0..9 (NULL without two fiscal years)"),
    "beneish m": ("beneish_m", "score (NULL without two fiscal years)"),
    "beneish m score": ("beneish_m", "score (NULL without two fiscal years)"),
    "capex to depreciation": ("capex_to_depreciation", "x"),
    "cwip to gross block": ("(cwip_to_gross_block * 100)", "%"),
    "rote": ("(rote * 100)", "%"),
    "roce screener": ("(roce_screener * 100)", "% (Screener: PBT + interest over average capital)"),
    "debtor days": ("debtor_days", "days (closing debtors)"),
    "inventory turnover": ("inventory_turnover", "x (sales / closing inventory)"),
    "working capital": ("(working_capital / 10000000)", "Rs Cr (Other Assets - Other Liabilities)"),
    "inventory days": ("inventory_days", "days (closing inventory / sales)"),
    "vnb margin": ("(vnb_margin * 100)", "%, life insurers (supplemental KPI)"),
    "embedded value": ("(embedded_value / 10000000)", "Rs Cr, life insurers (supplemental KPI)"),
    "ape growth": ("(ape_growth * 100)", "%, life insurers (supplemental KPI)"),
    "gov": ("(gov / 10000000)", "Rs Cr, gross order value (supplemental KPI)"),
    "take rate": ("(take_rate * 100)", "% (supplemental KPI)"),
    "net take rate": ("(take_rate * 100)", "% (supplemental KPI)"),
    "contribution margin": ("(contribution_margin * 100)", "% (supplemental KPI)"),
    "nrr": ("(nrr * 100)", "%, net revenue retention (supplemental KPI)"),
    "cac payback": ("cac_payback", "months (supplemental KPI)"),
    "days payable": ("days_payable", "days (closing trade payables / sales)"),
    "payable days": ("days_payable", "days (closing trade payables / sales)"),
    "cash conversion cycle": ("cash_conversion_cycle", "days (debtor + inventory - payable)"),
    "working capital days": ("working_capital_days", "days ((CA - cash - current investments - CL) / sales)"),
    "return on tangible equity": ("(rote * 100)", "%"),
    "rnd royalty intensity": ("(rnd_and_royalty_intensity * 100)", "% of revenue"),
    "order wins 90d": ("order_wins_90d", "count, Reg. 30 order wins in 90 days"),
    "order value 90d": ("(order_value_90d / 10000000)", "Rs Cr, Reg. 30 order wins in 90 days"),
    "kmp resignations 90d": ("kmp_resignations_90d", "count"),
    "auditor resignations 90d": ("auditor_resignations_90d", "count"),
    "fraud default 90d": ("fraud_or_default_90d", "count"),
    "penalties 90d": ("penalties_90d", "count (NULL: no verified penalty event yet)"),
    "contingent liabilities to net worth": ("(contingent_liabilities_to_net_worth * 100)", "%"),
    "return 1m": ("(return_1m * 100)", "%"),
    "return 3m": ("(return_3m * 100)", "%"),
    "return 6m": ("(return_6m * 100)", "%"),
    "return 12m": ("(return_12m * 100)", "%"),
    "price to 50dma": ("price_to_dma50", "x"),
    "price to 200dma": ("price_to_dma200", "x"),
    "distance from 52w high": ("(dist_52w_high * 100)", "% (<= 0)"),
    "delivery 5d": ("deliv_avg_5d", "shares/day"),
    "delivery 20d": ("deliv_avg_20d", "shares/day"),
    "delivery velocity": ("delivery_velocity", "x (5D / 20D)"),
    "float turnover": ("float_turnover_pct", "% of public shares per day (5D)"),
    "promoter holding": ("(promoter_holding_pct * 100)", "%"),
    "promoter pledge": ("(promoter_pledge_pct * 100)", "% of promoter shares pledged"),
    "pledged percentage": ("(promoter_pledge_pct * 100)", "% of promoter shares pledged"),
    "promoter encumbered": ("(promoter_encumbered_pct * 100)", "% of promoter shares encumbered (pledge+NDU+other)"),
    "fii holding": ("(fii_holding_pct * 100)", "% (SEBI Institutions (Foreign), incl. FDI)"),
    "fpi holding": ("(fpi_holding_pct * 100)", "% (FPI Category I + II)"),
    "dii holding": ("(dii_holding_pct * 100)", "%"),
    "public holding": ("(public_holding_pct * 100)", "%"),
    "change in fii dii holding": ("(fii_dii_qoq_change_pct * 100)", "percentage points, QoQ"),
    "fii dii qoq change": ("(fii_dii_qoq_change_pct * 100)", "percentage points, QoQ"),
    "in nifty 500": ("CAST(in_nifty500 AS INTEGER)", "1/0"),
    "eps": ("eps_ttm", "INR per share, TTM owners' profit / current shares"),
    "eps continuing": ("eps_continuing_ttm", "INR per share, TTM, ex discontinued"),
    "roe continuing": ("(roe_continuing * 100)", "%, ex discontinued"),
    "core profit": ("(core_profit_ttm / 10000000)", "INR crore, TTM, ex discontinued and exceptional (net of tax)"),
    "lending nbfc": ("CAST(is_lending_nbfc AS INTEGER)", "1/0 (NULL if not an NBFC)"),
    "nii": ("(nii_ttm / 10000000)", "INR crore, TTM, lenders"),
    "ppop": ("(ppop_ttm / 10000000)", "INR crore, TTM, lenders"),
    "cost to income": ("(cost_to_income * 100)", "%, lenders"),
    "credit cost": ("(credit_cost * 100)", "% of avg loans, TTM"),
    "nim": ("(nim_asset_proxy * 100)", "% of avg total assets (proxy), TTM"),
    "roa": ("(roa * 100)", "%, lenders, avg total assets"),
    "gnpa": ("(gnpa_pct * 100)", "% (NULL for NBFCs: not in taxonomy)"),
    "nnpa": ("(nnpa_pct * 100)", "% (NULL for NBFCs: not in taxonomy)"),
    "pcr": ("(pcr * 100)", "% (NULL for NBFCs: not in taxonomy)"),
    "credit to deposit": ("(credit_to_deposit * 100)", "%, banks"),
    "cet1": ("(cet1_pct * 100)", "%, banks (standalone, filed)"),
    "at1": ("(at1_pct * 100)", "%, banks (standalone, filed)"),
    "roa filed": ("(roa_filed * 100)", "%, as filed (annualisation varies by bank)"),
    "government holding": ("(govt_holding_pct * 100)", "%, banks (PSU marker)"),
    "claims ratio": ("(claims_ratio * 100)", "%, general insurers (basis in insurer_basis)"),
    "expense ratio": ("(expense_ratio * 100)", "%, insurers"),
    "combined ratio": ("(combined_ratio * 100)", "%, general insurers (IRDAI and Ind AS 117 bases differ)"),
    "solvency ratio": ("solvency_ratio", "x (times)"),
    "net premium earned": ("(net_premium_earned_ttm / 10000000)", "INR crore, TTM"),
    "insurance revenue": ("(insurance_revenue_ttm / 10000000)", "INR crore, TTM, Ind AS 117"),
    "investment income": ("(investment_income_ttm / 10000000)", "INR crore, TTM, insurers"),
    "persistency 13m": ("(persistency_13m * 100)", "%, life insurers"),
    "persistency 61m": ("(persistency_61m * 100)", "%, life insurers"),
    "sloan accrual": ("(sloan_accrual * 100)", "% of avg total assets"),
    "cfo to ebitda": ("(cfo_to_ebitda * 100)", "%"),
    "fcf to pat": ("(fcf_to_pat * 100)", "%"),
    "working capital intensity": ("(working_capital_intensity * 100)", "% of TTM revenue"),
    "receivables sales divergence": ("(receivables_sales_divergence * 100)", "percentage points (needs 8 quarters)"),
    "net debt to fcf": ("net_debt_to_fcf", "years"),
    "cost of debt": ("(cost_of_debt * 100)", "%"),
    "effective cost of debt": ("(cost_of_debt * 100)", "%"),
    "degree of operating leverage": ("dol", "x (needs 8 quarters, |revenue change| >= 5%)"),
    "unlevered fcf yield": ("(fcff_yield * 100)", "% of EV"),
    "dol": ("dol", "x (needs 8 quarters, |revenue change| >= 5%)"),
    "gross ebitda spread": ("(gross_ebitda_spread * 100)", "percentage points"),
    "reverse dcf growth": ("(reverse_dcf_implied_g * 100)", "% p.a. FCFF growth implied (WACC 12%, terminal 4%)"),
    "pe percentile": ("(pe_percentile * 100)", "percentile of own quarterly history (>= 4 quarters)"),
    "ev to ebitda percentile": ("(ev_ebitda_percentile * 100)", "percentile of own quarterly history (>= 4 quarters)"),
    "new gen tech": ("CAST(valuation_archetype = 'NEW_GEN_TECH' AS INTEGER)", "1/0"),
    "ev to gross profit": ("ev_to_gross_profit", "x"),
    "ex cash pe": ("ex_cash_pe", "x"),
    "ev to billings": ("ev_to_billings", "x"),
    "ev to esop adjusted ebitda": ("ev_to_esop_adj_ebitda", "x"),
    "price to cfo": ("price_to_cfo", "x"),
    "rule of 40": ("(rule_of_40 * 100)", "% (needs 8 quarters)"),
    "billings growth": ("(billings_growth_pct * 100)", "% YoY (needs 8 quarters)"),
    "working capital float": ("(neg_working_capital_float_pct * 100)", "% of TTM revenue"),
    "net burn multiple": ("net_burn_multiple", "x (cash burners, needs 8 quarters)"),
    "cash runway": ("cash_runway_months", "months (cash burners)"),
    "esop adjusted fcf": ("(esop_adj_fcf / 10000000)", "INR crore"),
    "liquid cash": ("(liquid_cash / 10000000)", "INR crore"),
}

KEYWORDS = {"and", "or", "not"}
COMPARATORS = {"<", "<=", ">", ">=", "=", "!="}
NAME_RE = re.compile(r"^[a-z][a-z0-9 ]{0,62}$")


class DslError(ValueError):
    pass


# ── tokens ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Tok:
    kind: str  # NUM | NAME | OP | KW | END
    text: str
    pos: int


_TOKEN = re.compile(
    r"\s*(?:(?P<num>\d+(?:\.\d+)?)(?![A-Za-z0-9_%])|(?P<op><=|>=|!=|[<>=+\-*/()])|(?P<word>[A-Za-z0-9_%]+))"
)


def tokenize(text: str) -> list[Tok]:
    if len(text) > 2000:
        raise DslError("query too long")
    toks: list[Tok] = []
    pos = 0
    while pos < len(text):
        if text[pos:].strip() == "":
            break
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise DslError(f"unexpected character {text[pos:].lstrip()[:1]!r} at {pos}")
        if m.group("num") and toks and toks[-1].kind == "NAME":  # "in nifty 500": a number ends an alias
            prev = toks.pop()
            toks.append(Tok("NAME", f"{prev.text} {m.group('num')}", prev.pos))
        elif m.group("num"):
            toks.append(Tok("NUM", m.group("num"), m.start("num")))
        elif m.group("op"):
            toks.append(Tok("OP", m.group("op"), m.start("op")))
        else:
            w = m.group("word")
            if w.lower() in KEYWORDS:
                toks.append(Tok("KW", w.lower(), m.start("word")))
            elif toks and toks[-1].kind == "NAME":  # multi-word alias
                prev = toks.pop()
                toks.append(Tok("NAME", f"{prev.text} {w}", prev.pos))
            else:
                toks.append(Tok("NAME", w, m.start("word")))
        pos = m.end()
    toks.append(Tok("END", "", len(text)))
    return toks


# ── AST ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Num:
    value: Decimal


@dataclass(frozen=True)
class Ref:
    name: str  # normalised alias


@dataclass(frozen=True)
class Neg:
    operand: object


@dataclass(frozen=True)
class Bin:
    op: str
    left: object
    right: object


@dataclass(frozen=True)
class Cmp:
    op: str
    left: object
    right: object


@dataclass(frozen=True)
class Bool:
    op: str  # and | or
    left: object
    right: object


@dataclass(frozen=True)
class Not:
    operand: object


def normalise(name: str) -> str:
    return " ".join(name.lower().split())


class _Parser:
    def __init__(self, text: str) -> None:
        self.toks = tokenize(text)
        self.i = 0

    def peek(self) -> Tok:
        return self.toks[self.i]

    def take(self, kind: str | None = None, text: str | None = None) -> Tok:
        t = self.peek()
        if (kind and t.kind != kind) or (text and t.text != text):
            want = text or kind
            raise DslError(f"expected {want} at {t.pos}, found {t.text or 'end of query'!r}")
        self.i += 1
        return t

    def done(self) -> None:
        if self.peek().kind != "END":
            raise DslError(f"unexpected {self.peek().text!r} at {self.peek().pos}")

    # boolean level
    def or_expr(self):
        node = self.and_expr()
        while self.peek().kind == "KW" and self.peek().text == "or":
            self.take()
            node = Bool("or", node, self.and_expr())
        return node

    def and_expr(self):
        node = self.not_expr()
        while self.peek().kind == "KW" and self.peek().text == "and":
            self.take()
            node = Bool("and", node, self.not_expr())
        return node

    def not_expr(self):
        t = self.peek()
        if t.kind == "KW" and t.text == "not":
            self.take()
            return Not(self.not_expr())
        if t.kind == "OP" and t.text == "(" and self._paren_is_boolean():
            self.take()
            node = self.or_expr()
            self.take("OP", ")")
            return node
        left = self.arith()
        op = self.peek()
        if op.kind != "OP" or op.text not in COMPARATORS:
            raise DslError(f"expected a comparison at {op.pos}")
        self.take()
        return Cmp(op.text, left, self.arith())

    def _paren_is_boolean(self) -> bool:
        """Does the parenthesis opened here contain a comparison/keyword at its own depth?"""
        depth = 0
        for t in self.toks[self.i :]:
            if t.kind == "OP" and t.text == "(":
                depth += 1
            elif t.kind == "OP" and t.text == ")":
                depth -= 1
                if depth == 0:
                    return False
            elif depth == 1 and (t.kind == "KW" or (t.kind == "OP" and t.text in COMPARATORS)):
                return True
        return False

    # arithmetic level
    def arith(self):
        node = self.term()
        while self.peek().kind == "OP" and self.peek().text in "+-":
            op = self.take().text
            node = Bin(op, node, self.term())
        return node

    def term(self):
        node = self.factor()
        while self.peek().kind == "OP" and self.peek().text in "*/":
            op = self.take().text
            node = Bin(op, node, self.factor())
        return node

    def factor(self):
        t = self.peek()
        if t.kind == "NUM":
            self.take()
            return Num(Decimal(t.text))
        if t.kind == "NAME":
            self.take()
            return Ref(normalise(t.text))
        if t.kind == "OP" and t.text == "(":
            self.take()
            node = self.arith()
            self.take("OP", ")")
            return node
        if t.kind == "OP" and t.text == "-":
            self.take()
            return Neg(self.factor())
        raise DslError(f"expected a number or metric at {t.pos}, found {t.text or 'end of query'!r}")


def parse_query(text: str):
    p = _Parser(text)
    node = p.or_expr()
    p.done()
    return node


def parse_arith(text: str):
    p = _Parser(text)
    node = p.arith()
    p.done()
    return node


# ── compilation ─────────────────────────────────────────────────────────


class Compiler:
    def __init__(self, custom: dict[str, str] | None = None) -> None:
        self.custom = {normalise(k): v for k, v in (custom or {}).items()}
        self.params: list[Decimal] = []
        self.refs: set[str] = set()
        self._stack: list[str] = []

    def compile(self, node) -> str:
        if isinstance(node, Num):
            self.params.append(node.value)
            return "?"
        if isinstance(node, Ref):
            return self._ref(node.name)
        if isinstance(node, Neg):
            return f"(-{self.compile(node.operand)})"
        if isinstance(node, Bin):
            left, right = self.compile(node.left), self.compile(node.right)
            if node.op == "/":
                return f"({left} / NULLIF({right}, 0))"
            return f"({left} {node.op} {right})"
        if isinstance(node, Cmp):
            op = "<>" if node.op == "!=" else node.op
            return f"({self.compile(node.left)} {op} {self.compile(node.right)})"
        if isinstance(node, Bool):
            return f"({self.compile(node.left)} {node.op.upper()} {self.compile(node.right)})"
        if isinstance(node, Not):
            return f"(NOT {self.compile(node.operand)})"  # NULL stays NULL: missing data never passes
        raise DslError(f"unsupported node {node!r}")

    def _ref(self, name: str) -> str:
        if name in ALIASES:
            self.refs.add(name)
            return ALIASES[name][0]
        if name in self.custom:
            if name in self._stack:
                raise DslError(f"custom ratio cycle: {' -> '.join([*self._stack, name])}")
            self._stack.append(name)
            try:
                return f"({self.compile(parse_arith(self.custom[name]))})"
            finally:
                self._stack.pop()
        close = [a for a in ALIASES if a.startswith(name.split()[0])][:5]
        hint = f"; did you mean {', '.join(close)}?" if close else ""
        raise DslError(f"unknown metric {name!r}{hint}")


def load_custom_ratios(con) -> dict[str, str]:
    return dict(con.execute("SELECT name, expression FROM user_custom_ratios").fetchall())


def save_custom_ratio(con, name: str, expression: str) -> None:
    key = normalise(name)
    if not NAME_RE.match(key) or key in KEYWORDS or key.split()[0] in KEYWORDS:
        raise DslError(f"invalid custom ratio name {name!r}")
    if key in ALIASES:
        raise DslError(f"{name!r} is a built-in metric")
    custom = {**load_custom_ratios(con), key: expression}
    Compiler(custom).compile(Ref(key))  # validates syntax, metrics and cycles
    con.execute("INSERT OR REPLACE INTO user_custom_ratios VALUES (?, ?, ?)", [key, expression, utc_now()])


@dataclass
class CompiledScreen:
    where_sql: str
    params: list[Decimal]
    metrics: list[str]


def compile_screen(query: str, custom: dict[str, str] | None = None) -> CompiledScreen:
    node = parse_query(query)
    c = Compiler(custom)
    where = c.compile(node)
    return CompiledScreen(where, c.params, sorted(c.refs))


def run_screen(con, query: str, as_of: date | None = None, limit: int = 500) -> list[dict]:
    """Run against the live table, or point-in-time against history when `as_of` is given."""
    cs = compile_screen(query, load_custom_ratios(con))
    extra = ", ".join(f'{ALIASES[m][0]} AS "{m}"' for m in cs.metrics)
    select = "as_of_date, symbol, series, close" + (f", {extra}" if extra else "")
    if as_of is None:
        sql = f"SELECT {select} FROM screener_features WHERE {cs.where_sql} ORDER BY symbol LIMIT {int(limit)}"
        params = cs.params
    else:
        sql = (
            f"SELECT {select} FROM screener_features_history WHERE as_of_date = ? AND {cs.where_sql} "
            f"ORDER BY symbol LIMIT {int(limit)}"
        )
        params = [as_of, *cs.params]
    cur = con.execute(sql, params)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]
