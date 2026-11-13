"""NSE corporate actions: JSON API records and the Corporate_action RSS feed.

Evidence (docs/references.md, CA1-CA8):
- API `symbol` is the **current** symbol (Tata Motors' demerger is listed under TMPV);
  `isin` is the ISIN in force before the action (ADANIPOWER shows INE814H01011). Resolve by ISIN.
- `faceVal` is the current face value, not the one at the action date.
- Rights are quoted as `Rights A:B @ Premium Rs X/-`; issue price = face value + premium.
- Bonus `A:B` = A new shares for every B held (GODFRYPHLP 2:1 opened at 0.342 x prior close).
- Two actions on one day arrive as two records (NAZARA split + bonus on 2025-09-26).
- RSS items carry company name and purpose but **no symbol or ISIN**: discovery only.

Anything not matched by an explicit rule is UNPARSED and must be quarantined, never guessed.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from financials.parsers import ParseError

UNIVERSE_SERIES = frozenset({"EQ", "BE", "BZ"})

_RS = r"R[SE]\.?\s*"
_NUM = r"(\d+(?:\.\d+)?)"
RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("DIVIDEND", re.compile(rf"^(?:INTERIM |FINAL |SPECIAL )?DIVIDEND\s*-\s*{_RS}{_NUM}\s*PER\s*SH(?:ARE)?$")),
    ("BONUS", re.compile(r"^BONUS\s+(\d+)\s*:\s*(\d+)$")),
    (
        "SPLIT",
        re.compile(
            rf"^FACE VALUE SPLIT \(SUB-DIVISION\)\s*-\s*"
            rf"FROM\s+{_RS}{_NUM}\s*/-\s*PER SHARE\s+TO\s+{_RS}{_NUM}\s*/-\s*PER SHARE$"
        ),
    ),
    ("RIGHTS", re.compile(rf"^RIGHTS\s+(\d+)\s*:\s*(\d+)\s*@\s*PREMIUM\s+{_RS}{_NUM}\s*/-$")),
    ("DEMERGER", re.compile(r"^DEMERGER$")),
)


@dataclass(frozen=True)
class ParsedComponent:
    action_type: str
    ratio_num: Decimal | None = None
    ratio_den: Decimal | None = None
    issue_price: Decimal | None = None
    cash_per_share: Decimal | None = None


@dataclass(frozen=True)
class CorpActionRecord:
    seq: int
    symbol: str
    series: str
    isin: str
    ex_date: date
    record_date: date | None
    face_value: Decimal | None
    subject: str
    parse_status: str  # PARSED | UNPARSED | IGNORED
    parse_reason: str | None
    components: tuple[ParsedComponent, ...]


def _date(text: str | None) -> date | None:
    t = (text or "").strip()
    if t in ("", "-"):
        return None
    return datetime.strptime(t, "%d-%b-%Y").date()


def parse_purpose(subject: str, face_value: Decimal | None) -> tuple[str, str | None, tuple[ParsedComponent, ...]]:
    """Return (status, reason, components) for one Purpose/subject string."""
    parts = [p.strip() for p in re.split(r"\s+/\s+|\s+AND\s+", subject.strip().upper()) if p.strip()]
    if not parts:
        return "UNPARSED", "empty purpose", ()
    out: list[ParsedComponent] = []
    for part in parts:
        norm = re.sub(r"\s+", " ", part)
        for kind, rx in RULES:
            m = rx.match(norm)
            if not m:
                continue
            g = [Decimal(x) for x in m.groups()]
            if kind == "DIVIDEND":
                out.append(ParsedComponent("DIVIDEND", cash_per_share=g[0]))
            elif kind == "BONUS":
                out.append(ParsedComponent("BONUS", ratio_num=g[0], ratio_den=g[1]))
            elif kind == "SPLIT":
                out.append(ParsedComponent("SPLIT", ratio_num=g[1], ratio_den=g[0]))  # new FV / old FV
            elif kind == "RIGHTS":
                if face_value is None:
                    return "UNPARSED", "rights premium without face value", ()
                out.append(ParsedComponent("RIGHTS", ratio_num=g[0], ratio_den=g[1], issue_price=face_value + g[2]))
            else:
                out.append(ParsedComponent("DEMERGER"))
            break
        else:
            return "UNPARSED", f"no rule for {norm!r}", ()
    if any(c.ratio_num is not None and c.ratio_num <= 0 for c in out) or any(
        c.ratio_den is not None and c.ratio_den <= 0 for c in out
    ):
        return "UNPARSED", "non-positive ratio", ()
    return "PARSED", None, tuple(out)


def parse_nse_corp_actions_json(data: bytes) -> list[CorpActionRecord]:
    try:
        rows = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ParseError(f"corporate actions: invalid JSON: {exc}") from exc
    if not isinstance(rows, list):
        raise ParseError("corporate actions: expected a JSON list")
    out: list[CorpActionRecord] = []
    for i, r in enumerate(rows):
        try:
            symbol, series, isin, subject = (
                r["symbol"].strip(),
                r["series"].strip(),
                r["isin"].strip(),
                r["subject"].strip(),
            )
            ex_date = _date(r["exDate"])
            fv_text = (r.get("faceVal") or "").strip()
            face_value = Decimal(fv_text) if fv_text not in ("", "-") else None
            record_date = _date(r.get("recDate"))
        except (KeyError, AttributeError, ValueError, ArithmeticError) as exc:
            raise ParseError(f"corporate actions record {i}: {exc}") from exc
        if ex_date is None:
            raise ParseError(f"corporate actions record {i}: missing exDate")
        if series not in UNIVERSE_SERIES:
            status, reason, comps = "IGNORED", f"series {series} outside universe", ()
        else:
            status, reason, comps = parse_purpose(subject, face_value)
        out.append(
            CorpActionRecord(i, symbol, series, isin, ex_date, record_date, face_value, subject, status, reason, comps)
        )
    return out


@dataclass(frozen=True)
class RssCorpActionItem:
    company: str
    ex_date: date | None
    series: str | None
    purpose: str | None
    face_value: str | None
    record_date: date | None
    pub_date: datetime | None


def parse_corp_action_rss(data: bytes) -> list[RssCorpActionItem]:
    """Discovery only: items have no symbol/ISIN, so they cannot be recorded directly."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ParseError(f"corporate action RSS: {exc}") from exc
    items = []
    for it in root.iter("item"):
        title = " ".join((it.findtext("title") or "").split())
        company, _, ex_part = title.partition(" - Ex-Date:")
        fields = {}
        for chunk in (it.findtext("description") or "").split("|"):
            k, _, v = chunk.partition(":")
            fields[k.strip().upper()] = v.strip()
        pub = (it.findtext("pubDate") or "").strip()
        items.append(
            RssCorpActionItem(
                company=company.strip(),
                ex_date=_date(ex_part),
                series=fields.get("SERIES"),
                purpose=fields.get("PURPOSE"),
                face_value=fields.get("FACE VALUE"),
                record_date=_date(fields.get("RECORD DATE")),
                pub_date=datetime.strptime(pub, "%d-%b-%Y %H:%M:%S") if pub else None,
            )
        )
    return items
