"""Inline XBRL (iXBRL 1.1) -> an equivalent XBRL instance, for BSE's shareholding files [X167, X170].

BSE publishes each Reg. 31 pattern as XHTML with `ix:` facts (`XBRLFILES/SHPXBRLDataXML/<code>_<ts>_SP.html`), of the
same `in-bse-shp` taxonomy that NSE's SHP XML instances use. This module rebuilds the instance those facts denote, so
the existing shareholding parser reads them unchanged. Only what the committed BSE files use is supported; anything
else raises ParseError (never guessed):

- `ix:header/ix:resources`: `xbrli:context` and `xbrli:unit`, copied as filed.
- `ix:nonFraction`: `name`, `contextRef`, `unitRef`, `decimals`; `scale` (value x 10^scale: BSE writes percentages as
  points with scale -2, giving NSE's fractions, 74.99 -> 0.7499); `sign="-"`; no `format` (plain digits and one
  decimal point) or `ixt:num-dot-decimal` / `ixt2:numdotdecimal` (thousands commas removed).
- `ix:nonNumeric`: the text content; `ixt2:datedaymonthyear` (DD-MM-YYYY -> ISO date); `ixt2:booleantrue` /
  `ixt2:booleanfalse` under rule IXBRL1_BOOLEAN_TEXT (below).
- `ix:continuation`, `ix:exclude`, `ix:footnote`, `ix:tuple`, `ix:fraction` and nested facts: ParseError.

Rule IXBRL1_BOOLEAN_TEXT [X170]: BSE tags every Yes / No answer `ixt2:booleantrue`, whatever it says (all 4 committed
files: 151 such facts, 146 "No" and 5 "Yes"). The registry transform would make every one of them true; the displayed
word is the filer's answer and agrees with the figures (542910: "Yes" to locked-in shares and 10,361,783 locked-in
shares; ABBOTINDIA: "No" and no locked-in figure). So "Yes" -> true, "No" -> false, any other text -> ParseError.
"""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation

from financials.parsers import ParseError

IX = "http://www.xbrl.org/2013/inlineXBRL"
XHTML = "http://www.w3.org/1999/xhtml"
XBRLI = "http://www.xbrl.org/2003/instance"
IXBRL1_RULE = "IXBRL1_BOOLEAN_TEXT"
NUM_FORMATS = {None, "num-dot-decimal", "numdotdecimal"}
BOOL_FORMATS = {"booleantrue", "booleanfalse"}
UNSUPPORTED = ("continuation", "exclude", "footnote", "tuple", "fraction")
_NUM = re.compile(r"^\d+(\.\d+)?$")
_DMY = re.compile(r"^(\d{2})-(\d{2})-(\d{4})$")


def is_inline(data: bytes) -> bool:
    head = data[:4096].lstrip()
    return head[:5].lower() == b"<html" and IX.encode() in data[:8192]


def _local(fmt: str | None) -> str | None:
    return None if fmt is None else fmt.split(":")[-1]


def _number(el: ET.Element, name: str) -> str:
    fmt = _local(el.get("format"))
    if fmt not in NUM_FORMATS:
        raise ParseError(f"{name}: unsupported number format {el.get('format')!r}")
    text = "".join(el.itertext()).strip()
    if fmt is not None:
        text = text.replace(",", "")
    if not _NUM.match(text):
        raise ParseError(f"{name}: not a plain number {text!r}")
    try:
        v = Decimal(text).scaleb(int(el.get("scale") or 0))
    except (InvalidOperation, ValueError) as exc:
        raise ParseError(f"{name}: bad value / scale") from exc
    if el.get("sign") == "-":
        v = -v
    elif el.get("sign") not in (None, ""):
        raise ParseError(f"{name}: sign {el.get('sign')!r}")
    s = format(v, "f")
    return s.rstrip("0").rstrip(".") if "." in s else s


def _text(el: ET.Element, name: str) -> str:
    fmt = _local(el.get("format"))
    text = "".join(el.itertext())
    if fmt is None:
        return text
    t = text.strip()
    if fmt in BOOL_FORMATS:  # IXBRL1_BOOLEAN_TEXT
        if t == "Yes":
            return "true"
        if t == "No":
            return "false"
        raise ParseError(f"{name}: boolean text {t!r} is neither Yes nor No")
    if fmt == "datedaymonthyear":
        m = _DMY.match(t)
        if not m:
            raise ParseError(f"{name}: date {t!r} is not DD-MM-YYYY")
        return f"{m[3]}-{m[2]}-{m[1]}"
    raise ParseError(f"{name}: unsupported format {el.get('format')!r}")


def inline_to_instance(data: bytes) -> bytes:
    """The XBRL instance an inline XBRL document denotes (facts in document order; contexts and units as filed)."""
    try:
        namespaces: dict[str, str] = {}
        for _, (prefix, uri) in ET.iterparse(io.BytesIO(data), events=("start-ns",)):
            namespaces.setdefault(prefix, uri)
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ParseError(f"inline XBRL: invalid XHTML: {exc}") from exc
    for bad in UNSUPPORTED:
        if root.find(f".//{{{IX}}}{bad}") is not None:
            raise ParseError(f"inline XBRL: ix:{bad} is not supported")
    resources = root.findall(f".//{{{IX}}}resources")
    if len(resources) != 1:
        raise ParseError(f"inline XBRL: {len(resources)} ix:resources")
    out = ET.Element(f"{{{XBRLI}}}xbrl")
    for el in resources[0]:
        if el.tag in (f"{{{XBRLI}}}context", f"{{{XBRLI}}}unit"):
            out.append(el)
    for el in root.iter():
        kind = el.tag[len(IX) + 2 :] if el.tag.startswith(f"{{{IX}}}") else None
        if kind not in ("nonFraction", "nonNumeric"):
            continue
        qname = el.get("name") or ""
        prefix, _, local = qname.partition(":")
        if not local or prefix not in namespaces:
            raise ParseError(f"inline XBRL: fact name {qname!r} has no declared prefix")
        if el.find(f".//{{{IX}}}nonFraction") is not None or el.find(f".//{{{IX}}}nonNumeric") is not None:
            raise ParseError(f"inline XBRL: nested facts in {qname}")
        fact = ET.SubElement(out, f"{{{namespaces[prefix]}}}{local}", {"contextRef": el.get("contextRef", "")})
        if kind == "nonFraction":
            fact.set("unitRef", el.get("unitRef", ""))
            if el.get("decimals") is not None:
                fact.set("decimals", el.get("decimals"))
            fact.text = _number(el, qname)
        else:
            fact.text = _text(el, qname)
    for prefix, uri in namespaces.items():
        if prefix and uri not in (IX, XHTML):
            ET.register_namespace(prefix, uri)
    return ET.tostring(out, encoding="utf-8", xml_declaration=True)
