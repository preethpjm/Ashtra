"""Read an SGML document WITHOUT its DTD, for a read-only preview.

Only the DTD says exactly where an omitted end tag belongs, so this is never validation and
never used for editing. It follows rules taken from the document itself:

  * an element type that is never closed anywhere in the file is EMPTY
    (typical: revision marks <REVST>/<REVEND>, <COLSPEC>, <GRAPHIC ...>);
  * an element that is open when its parent closes is closed there (implied end tag);
  * an element type that is closed only sometimes is closed when the next element of the
    same type starts at the same level (the usual <ITEM>..<ITEM>.. pattern);
  * a stray end tag with no open element of that type is ignored;
  * everything still open at the end of the file is closed.

Entities: SDATA/ISO character entities become their characters (kept as &name; references
declared in the XML DOCTYPE, like the OpenSP path), internal text entities are expanded,
graphics (NDATA) references are left out of the text. Names are lower-cased.
"""
from __future__ import annotations

import html.entities
import re
from collections import Counter
from dataclasses import dataclass, field

_DOCTYPE = re.compile(r"<!DOCTYPE\s+([^\s\[>]+)", re.I)
_TOKEN = re.compile(
    r"(?P<comment><!--.*?-->)"
    r"|(?P<msopen><!\[\s*(?P<mskey>[A-Za-z%][\w.%;-]*)?\s*\[)"
    r"|(?P<msclose>\]\]>)"
    r"|(?P<decl><![A-Za-z][^>]*>)"
    r"|(?P<pi><\?[^>]*>)"
    r"|(?P<end></(?P<ename>[A-Za-z][\w.:-]*)?\s*>)"
    r"|(?P<start><(?P<sname>[A-Za-z][\w.:-]*)(?P<attrs>(?:\s+(?:[\w.:-]+\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>\"']+)|\"[^\"]*\"|'[^']*'|[^\s>\"'=]+))*)\s*/?>)"
    r"|(?P<ent>&(?P<ename2>#?[\w.-]+);?)"
    r"|(?P<text>[^<&\]]+|[<&\]])",
    re.S)
_ATTR = re.compile(r"([\w.:-]+)\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>\"']+)|(\"[^\"]*\"|'[^']*')|([^\s>\"'=]+)")
_ENTITY_DECL = re.compile(
    r"<!ENTITY\s+(?!%)([\w.-]+)\s+(?:(SDATA|CDATA|PI|STARTTAG|ENDTAG|MS|MD)\s+)?"
    r"(?:\"([^\"]*)\"|'([^']*)'|(SYSTEM|PUBLIC)\s+(\"[^\"]*\"|'[^']*')(?:\s+(\"[^\"]*\"|'[^']*'))?(?:\s+(NDATA|CDATA|SDATA|SUBDOC)\s+([\w.-]+))?)",
    re.I | re.S)


# Element types that are EMPTY by long-standing convention in ATA iSpec 2200, S1000D and CALS tables.
KNOWN_EMPTY = {"colspec", "spanspec", "revst", "revend", "refint", "xref", "sheet", "graphic", "gdesc",
               "symbol", "anchor", "pgbrk", "chgdesc", "isempty", "ftnref", "fnref", "dmref-empty"}
# CALS table model (the same in every DTD that uses it): starting one of these ends the open
# ones listed, back to the enclosing container.
CALS_ENDS = {"thead": {"thead", "tbody", "tfoot", "row", "entry"}, "tfoot": {"thead", "tbody", "tfoot", "row", "entry"},
             "tbody": {"thead", "tbody", "tfoot", "row", "entry"}, "row": {"row", "entry"}, "entry": {"entry"}}


def _char_for(name: str, sdata_text: str | None = None) -> str:
    cp = html.entities.name2codepoint.get(name)
    if cp:
        return chr(cp)
    h5 = html.entities.html5.get(name + ";")
    if h5:
        return h5
    if sdata_text:
        m = re.fullmatch(r"\[\s*([\w.-]+)\s*\]", sdata_text.strip())
        if m and m.group(1) != name:
            return _char_for(m.group(1))
    return f"[{name}]"


def _esc_text(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _esc_attr(s: str) -> str:
    return _esc_text(s).replace('"', "&quot;")


@dataclass
class Preview:
    xml: str | None
    entities: dict[str, str] = field(default_factory=dict)
    root: str | None = None
    empty_types: list[str] = field(default_factory=list)
    implied_ends: int = 0
    stray_ends: int = 0
    error: str | None = None
    mode: str = "normalized"                       # "normalized" (end tags written) or "minimized" (approximated)


def _internal_subset(text: str, start: int) -> tuple[str, int]:
    """Internal subset text and the offset just after the DOCTYPE declaration."""
    i, depth, q, sub_start = start, 0, "", None
    while i < len(text):
        c = text[i]
        if q:
            if c == q:
                q = ""
        elif c in "\"'":
            q = c
        elif c == "[":
            depth += 1
            if depth == 1:
                sub_start = i + 1
        elif c == "]":
            depth -= 1
            if depth == 0 and sub_start is not None:
                sub = text[sub_start:i]
                j = text.find(">", i)
                return sub, (j + 1 if j >= 0 else len(text))
        elif c == ">" and depth == 0:
            return "", i + 1
        i += 1
    return "", len(text)


def preview(text: str) -> Preview:
    m = _DOCTYPE.search(text)
    if not m:
        return Preview(None, error="no DOCTYPE")
    root = m.group(1).lower()
    subset, body_start = _internal_subset(text, m.end())
    sdata: dict[str, str] = {}
    textents: dict[str, str] = {}
    ndata: set[str] = set()
    for d in _ENTITY_DECL.finditer(subset):
        name, kind = d.group(1), (d.group(2) or "").upper()
        literal = d.group(3) if d.group(3) is not None else d.group(4)
        if d.group(8) and d.group(8).upper() == "NDATA":
            ndata.add(name)
        elif kind == "SDATA":
            sdata[name] = literal or ""
        elif literal is not None and kind in ("", "CDATA"):
            textents[name] = literal
    body = text[body_start:]

    # 1. what the document itself says about each element type
    starts, ends = Counter(), Counter()
    for t in _TOKEN.finditer(body):
        if t.group("start"):
            starts[t.group("sname").lower()] += 1
        elif t.group("end") and t.group("ename"):
            ends[t.group("ename").lower()] += 1
    never = {n for n, c in starts.items() if ends[n] == 0}
    partial = {n for n, c in starts.items() if 0 < ends[n] < c}
    total = sum(starts.values()) or 1
    # "normalized" files (Arbortext and most modern tools write every end tag): the few types
    # never closed are EMPTY elements. "minimized" files leave many end tags out.
    minimized = bool(partial) or sum(starts[n] for n in never) / total > 0.05
    if minimized:
        followed_by_text = Counter()
        toks = list(_TOKEN.finditer(body))
        for i, t in enumerate(toks):
            if t.group("start") and t.group("sname").lower() in never:
                nxt = toks[i + 1] if i + 1 < len(toks) else None
                if nxt is not None and (nxt.group("ent") or (nxt.group("text") and nxt.group("text").strip())):
                    followed_by_text[t.group("sname").lower()] += 1
        empty_types = {n for n in never if n in KNOWN_EMPTY}
        omittable = (never - empty_types) | partial
    else:
        empty_types, omittable = never, partial

    # 2. rebuild the tree
    out: list[str] = []
    stack: list[str] = []
    had_text: list[bool] = []                     # per open element: text directly inside it
    at_line_start = True
    used_ents: dict[str, str] = {}
    implied = stray = 0
    ignore_depth = 0
    ms_stack: list[bool] = []
    for t in _TOKEN.finditer(body):
        if t.group("msopen"):
            key = (t.group("mskey") or "").upper()
            ign = key == "IGNORE"
            ms_stack.append(ign)
            ignore_depth += 1 if ign else 0
            continue
        if t.group("msclose"):
            if ms_stack:
                if ms_stack.pop():
                    ignore_depth -= 1
            else:
                out.append("]]&gt;")
            continue
        if ignore_depth or t.group("comment") or t.group("decl") or t.group("pi"):
            continue
        if t.group("start"):
            name = t.group("sname").lower()
            if minimized and at_line_start:
                # a new line starting with a tag ends open text elements (paragraphs, titles ...)
                while stack and stack[-1] in omittable and had_text[-1]:
                    out.append(f"</{stack.pop()}>"); had_text.pop(); implied += 1
            if minimized and name in CALS_ENDS:
                closing = CALS_ENDS[name]
                while stack and stack[-1] in closing and stack[-1] in omittable:
                    out.append(f"</{stack.pop()}>"); had_text.pop(); implied += 1
            if name in omittable and name in stack:
                i = len(stack) - 1 - stack[::-1].index(name)
                if all(x in omittable for x in stack[i + 1:]):      # next item of the same kind: siblings
                    while len(stack) > i:
                        out.append(f"</{stack.pop()}>"); had_text.pop(); implied += 1
            attrs = []
            seen = set()
            for a in _ATTR.finditer(t.group("attrs") or ""):
                if a.group(1):
                    an, av = a.group(1).lower(), a.group(2)
                    av = av[1:-1] if av[:1] in "\"'" else av
                else:
                    token = (a.group(3) or a.group(4) or "").strip("\"'")
                    an, av = re.sub(r"[^\w.-]", "_", token.lower()) or "value", token
                    if not re.match(r"[A-Za-z_]", an):
                        an = "v_" + an
                if an in seen:
                    continue
                seen.add(an)
                attrs.append(f' {an}="{_esc_attr(av)}"')
            if name in empty_types:
                out.append(f"<{name}{''.join(attrs)}/>")
            else:
                out.append(f"<{name}{''.join(attrs)}>")
                stack.append(name); had_text.append(False)
            at_line_start = False
            continue
        if t.group("end"):
            name = (t.group("ename") or "").lower()
            at_line_start = False
            if not name:                                   # </> closes the current element
                if stack:
                    out.append(f"</{stack.pop()}>"); had_text.pop()
                continue
            if name in stack:
                while stack and stack[-1] != name:
                    out.append(f"</{stack.pop()}>"); had_text.pop()
                    implied += 1
                out.append(f"</{stack.pop()}>"); had_text.pop()
            else:
                stray += 1
            continue
        if t.group("ent"):
            at_line_start = False
            if had_text:
                had_text[-1] = True
            n = t.group("ename2")
            if n.startswith("#"):
                num = n[1:]
                try:
                    cp = int(num[1:], 16) if num[:1] in "xX" else int(num)
                    out.append(f"&#{cp};")
                except ValueError:
                    out.append(_esc_text(t.group(0)))
            elif n in textents:
                out.append(_esc_text(textents[n]))
            elif n in ndata:
                pass
            else:
                used_ents[n] = _char_for(n, sdata.get(n))
                out.append(f"&{n};")
            continue
        txt = t.group("text")
        if txt is not None:
            if txt.strip():
                if had_text:
                    had_text[-1] = True
                at_line_start = txt.rstrip(" \t").endswith("\n")
            elif "\n" in txt:
                at_line_start = True
            if stack:
                out.append(_esc_text(txt))
    while stack:
        out.append(f"</{stack.pop()}>")
        implied += 1
    implied_note = "minimized" if minimized else "normalized"
    body_xml = "".join(out)
    # the root element must be the only top-level element
    first = re.search(r"<([a-z][\w.:-]*)", body_xml)
    if first and first.group(1) != root:
        body_xml = f"<{root}>{body_xml}</{root}>"
    esc = lambda v: v.replace("&", "&#38;").replace('"', "&#34;").replace("%", "&#37;")
    subset_xml = "".join(f'<!ENTITY {n} "{esc(v)}">' for n, v in sorted(used_ents.items()))
    xml = f'<?xml version="1.0"?>\n<!DOCTYPE {root} [{subset_xml}]>\n{body_xml}\n'
    return Preview(xml, used_ents, root, sorted(empty_types), implied, stray, mode=implied_note)
