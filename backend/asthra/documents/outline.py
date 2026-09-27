"""Document outline for the structure tree. Paths use the same readable form as
diagnostics (/a/b[2]/c) so the UI can link tree, diagnostics and editor views."""
from __future__ import annotations

from lxml import etree

MAX_NODES = 20000
_LABEL_ATTRS = ("id", "item", "itemSeqNumberValue", "partNumberValue", "infoEntityIdent",
                "internalRefId", "seq", "kind", "ref", "partRef", "breakdownElement")


def _label(el: etree._Element) -> str:
    for a in _LABEL_ATTRS:
        if a in el.attrib:
            return f"{a}={el.get(a)}"
    if len(el) == 0 and el.text and el.text.strip():
        t = " ".join(el.text.split())
        return t[:60] + ("…" if len(t) > 60 else "")
    for child in el:
        if isinstance(child.tag, str) and etree.QName(child).localname in ("title", "techName", "name", "descrForPart"):
            t = " ".join("".join(child.itertext()).split())
            return t[:60] + ("…" if len(t) > 60 else "")
    return ""


def build_outline(root: etree._Element) -> dict:
    count = 0

    def walk(el, path):
        nonlocal count
        count += 1
        kids, seen = [], {}
        elems = [c for c in el if isinstance(c.tag, str)]
        totals = {}
        for c in elems:
            totals[c.tag] = totals.get(c.tag, 0) + 1
        for c in elems:
            if count >= MAX_NODES:
                break
            seen[c.tag] = seen.get(c.tag, 0) + 1
            name = etree.QName(c).localname
            seg = f"{name}[{seen[c.tag]}]" if totals[c.tag] > 1 else name
            kids.append(walk(c, f"{path}/{seg}"))
        return {"name": etree.QName(el).localname, "path": path, "line": el.sourceline,
                "label": _label(el), "children": kids}

    tree = walk(root, "/" + etree.QName(root).localname)
    return {"root": tree, "truncated": count >= MAX_NODES, "count": count}
