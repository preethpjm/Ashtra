"""Find where records live in a document's source text (XML or SGML) and replace them, leaving every other
byte as it was. A small tag scanner: comments, processing instructions, marked sections and the DOCTYPE are
skipped; an end tag closes any elements left open inside it (SGML empty elements, omitted end tags)."""
from __future__ import annotations

import re

_TAG = re.compile(r"""<(/?)([A-Za-z_][\w.:-]*)((?:[^>"']|"[^"]*"|'[^']*')*?)(/?)>""")
_ATTR = re.compile(r"""([A-Za-z_][\w.:-]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""")


def _skip(text: str, i: int) -> int | None:
    """End of a non-element construct starting at i, or None."""
    if text.startswith("<!--", i):
        j = text.find("-->", i + 4)
        return len(text) if j < 0 else j + 3
    if text.startswith("<![CDATA[", i):
        j = text.find("]]>", i)
        return len(text) if j < 0 else j + 3
    if text.startswith("<?", i):
        j = text.find(">", i)
        return len(text) if j < 0 else j + 1
    if text.startswith("<!", i):                       # DOCTYPE (with an internal subset) or a marked section
        depth, j, q = 0, i + 2, ""
        while j < len(text):
            c = text[j]
            if q:
                if c == q:
                    q = ""
            elif c in "\"'":
                q = c
            elif c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
            elif c == ">" and depth <= 0:
                return j + 1
            j += 1
        return len(text)
    return None


def attrs_of(tag_text: str) -> dict[str, str]:
    return {m.group(1).lower(): m.group(2) if m.group(2) is not None else (m.group(3) if m.group(3) is not None else m.group(4))
            for m in _ATTR.finditer(tag_text)}


def _trim(text: str, i: int) -> int:
    while i > 0 and text[i - 1] in " \t\r\n":
        i -= 1
    return i


def scan(text: str, container: list[str], record: str, empty: set[str] = frozenset(),
         allowed: dict[str, set[str]] | None = None) -> list[dict]:
    """Every instance of the container path: its span, the attributes of each element on the path, and the spans
    of the record elements directly inside it. With `allowed` (element -> the children its content model
    permits, lower case), a start tag the open element cannot contain ends that element first, as SGML end-tag
    omission does (<ITEMDATA>…<ITEMDATA> are siblings)."""
    want = [c.lower() for c in container]
    rec = record.lower()
    empty = {e.lower() for e in empty}
    stack: list[dict] = []
    found: list[dict] = []
    i = 0
    while True:
        i = text.find("<", i)
        if i < 0:
            break
        sk = _skip(text, i)
        if sk is not None:
            i = sk
            continue
        m = _TAG.match(text, i)
        if not m:
            i += 1
            continue
        closing, name, rest, selfclose = m.group(1), m.group(2).lower(), m.group(3), m.group(4)
        if not closing:
            if allowed:
                k = len(stack) - 1
                while k >= 0 and stack[k]["name"] in allowed and name not in allowed[stack[k]["name"]]:
                    k -= 1
                if 0 <= k < len(stack) - 1:
                    while len(stack) > k + 1:
                        node = stack.pop()
                        node["end"] = node["inner_end"] = _trim(text, i)
                        _closed(node, stack, found, want, rec)
            node = {"name": name, "start": i, "tag_end": m.end(), "attrs": attrs_of(rest), "records": []}
            if selfclose or name in empty:
                node["end"] = m.end()
                _closed(node, stack, found, want, rec)
            else:
                stack.append(node)
        else:
            k = len(stack) - 1
            while k >= 0 and stack[k]["name"] != name:
                k -= 1
            if k >= 0:
                while len(stack) > k:
                    node = stack.pop()
                    node["end"] = m.end() if len(stack) == k else _trim(text, i)   # elements left open end where their parent ends
                    node["inner_end"] = i if len(stack) == k else node["end"]
                    _closed(node, stack, found, want, rec)
        i = m.end()
    return found


def _closed(node: dict, stack: list[dict], found: list[dict], want: list[str], rec: str) -> None:
    names = [s["name"] for s in stack]
    if node["name"] == rec and names == want and stack:
        stack[-1]["records"].append((node["start"], node["end"]))
    if names + [node["name"]] == want:
        found.append({"start": node["start"], "tag_end": node["tag_end"], "inner_end": node.get("inner_end", node["end"]),
                      "end": node["end"], "path_attrs": [s["attrs"] for s in stack] + [node["attrs"]], "records": node["records"]})


def tags_in(snippet: str) -> list[tuple[str, dict[str, str]]]:
    """(element name in lower case, attributes) of every start tag in a piece of markup."""
    return [(m.group(2).lower(), attrs_of(m.group(3))) for m in _TAG.finditer(snippet) if not m.group(1)]


def _indent_at(text: str, i: int) -> str:
    j = text.rfind("\n", 0, i)
    lead = text[j + 1:i]
    return lead if lead.strip() == "" else ""


def replace_records(text: str, inst: dict, new_records: list[str]) -> str:
    """Replace the record elements of one container instance (or add them before its end tag), one per line at
    the indentation the first record had."""
    recs = inst["records"]
    if recs:
        a, b = recs[0][0], recs[-1][1]
        ind = _indent_at(text, a)
        return text[:a] + ("\n" + ind).join(new_records) + text[b:]
    at = inst["inner_end"]
    ind = _indent_at(text, at)
    inner = ind + "  " if ind or text[inst["tag_end"]:at].startswith("\n") else ""
    lead = "" if text[:at].endswith("\n" + ind) and ind else ("\n" if not text[:at].endswith("\n") else "")
    body = "".join(("" if i == 0 and not lead and text[:at].endswith("\n") else "") + inner + r + "\n" for i, r in enumerate(new_records))
    if text[:at].endswith("\n" + ind) and ind:          # the end tag is on its own line: insert before its indentation
        at -= len(ind)
        return text[:at] + body + text[at:]
    return text[:at] + lead + body + ind + text[at:]


def existing_ids(text: str) -> set[str]:
    return {m.group(2).lower() for m in re.finditer(r"""\b(id|key)\s*=\s*["']([^"']+)["']""", text)}
