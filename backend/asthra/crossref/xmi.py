"""Read an S-Series UML data model exported from Enterprise Architect as XMI 2.1 (SX000i, S3000L, S2000M,
S5000F, S6000T … all publish one) into a plain model:

    {"spec": "S3000L", "issue": "2.0", "classes": {name: {name, uof, xml, xml_ref, doc, abstract, common,
                                                           supers: [...], attrs: [...], relations: [...]}},
     "datatypes": {name: {xml, doc}}}

    attr     = {name, xml, type, doc, key, lower, upper}
    relation = {role, xml, target, lower, upper, doc}

`xml` is the element name the specification's XML schema uses for the class / attribute (EA tag "xmlName"):
that is what connects the conceptual model to the tags in documents. Classes in packages named "CDM …" are
the Common Data Model (SX002D) shared by all S-Series specifications."""
from __future__ import annotations

import html
import re
from pathlib import Path

from lxml import etree

XMI = "http://schema.omg.org/spec/XMI/2.1"
_X = "{%s}" % XMI


def _doc(s: str | None) -> str:
    """EA stores documentation escaped twice ("&amp;lt;&amp;lt;class&amp;gt;&amp;gt;") and with RTF-ish tags."""
    if not s:
        return ""
    s = html.unescape(html.unescape(s))
    s = re.sub(r"<<\s*([\w -]+?)\s*>>", r"«\1»", s)                 # UML stereotypes: <<class>> → «class»
    s = re.sub(r"</?[a-zA-Z][^>]*>", "", s)
    return " ".join(s.split())


def _mult(el, which: str) -> int | None:
    v = el.find(which)
    if v is None:
        return None
    val = v.get("value")
    if val in (None, ""):
        return 0 if which == "lowerValue" else None
    try:
        n = int(val)
    except ValueError:
        return None
    return None if n < 0 else n


def _spec_of(names: list[str]) -> tuple[str, str]:
    found = ("", "")
    for n in names:
        m = re.search(r"\b(SX0\d\d[A-Za-z]|S[1-6]000[A-Z])[ _]?(\d+-\d+|\d+\.\d+)?", n.replace("_Data", " Data"))
        if m:
            if m.group(2):
                return m.group(1), m.group(2).replace("-", ".")
            found = found if found[0] else (m.group(1), "")
    return found


def read_xmi(path: str | Path | bytes) -> dict:
    parser = etree.XMLParser(huge_tree=True, recover=True, resolve_entities=False, no_network=True)
    root = etree.fromstring(path, parser) if isinstance(path, bytes) else etree.parse(str(path), parser).getroot()
    xid = lambda e: e.get(_X + "id")
    xtype = lambda e: e.get(_X + "type") or ""

    # ---- stereotype applications: xml names and key flags, keyed by the element id
    xml_name: dict[str, str] = {}
    xml_ref: dict[str, str] = {}
    keyed: set[str] = set()
    for el in root.iter():
        if not isinstance(el.tag, str) or "/profiles/" not in el.tag:
            continue
        tag = etree.QName(el).localname
        base = next((v for k, v in el.attrib.items() if k.startswith("base_")), None)
        if not base:
            continue
        if tag == "xmlName" and el.get("xmlName"):
            xml_name[base] = el.get("xmlName")
        elif tag == "xmlRefName" and el.get("xmlRefName"):
            xml_ref[base] = el.get("xmlRefName")
        elif tag in ("key", "compositeKey", "relationshipKey"):
            keyed.add(base)

    # ---- documentation from the EA extension
    docs: dict[str, str] = {}
    ext_types: dict[str, str] = {}
    ext = root.find(_X + "Extension")
    if ext is not None:
        for e in ext.iter("element"):
            i = e.get(_X + "idref")
            p = e.find("properties")
            if i and p is not None and p.get("documentation"):
                docs[i] = _doc(p.get("documentation"))
            for a in e.iter("attribute"):
                ai = a.get(_X + "idref")
                d = a.find("documentation")
                if ai and d is not None and d.get("value"):
                    docs[ai] = _doc(d.get("value"))
                pr = a.find("properties")
                if ai and pr is not None and pr.get("type"):
                    ext_types[ai] = pr.get("type")
                st = a.find("stereotype")
                if ai and st is not None and st.get("stereotype") in ("key", "compositeKey", "relationshipKey"):
                    keyed.add(ai)
                t = a.find("tags")
                if ai and t is not None and ai not in xml_name:
                    for tg in t.findall("tag"):
                        if tg.get("name") == "xmlName" and tg.get("value"):
                            xml_name[ai] = tg.get("value")
        for c in ext.iter("connector"):
            i = c.get(_X + "idref")
            d = c.find("documentation")
            if i and d is not None and d.get("value"):
                docs[i] = _doc(d.get("value"))

    # ---- classifiers with their package path
    model = root.find("{*}Model") if root.find("{*}Model") is not None else root
    classifiers: dict[str, tuple[etree._Element, list[str]]] = {}
    pkg_names: list[str] = []

    def walk(el, path: list[str]):
        for c in el:
            if not isinstance(c.tag, str) or etree.QName(c).localname != "packagedElement":
                continue
            t = xtype(c)
            if t == "uml:Package":
                pkg_names.append(c.get("name") or "")
                walk(c, path + [c.get("name") or ""])
            elif t in ("uml:Class", "uml:Interface", "uml:PrimitiveType", "uml:DataType", "uml:Enumeration"):
                classifiers[xid(c)] = (c, path)

    walk(model, [])
    name_of = {i: (c.get("name") or "") for i, (c, _) in classifiers.items()}
    spec, issue = _spec_of(pkg_names)

    out = {"spec": spec, "issue": issue, "classes": {}, "datatypes": {}}
    for i, (c, path) in classifiers.items():
        name = c.get("name") or ""
        t = xtype(c)
        uof = next((p for p in reversed(path) if re.search(r"UoF|CDM|SX000i |S\d000[A-Z] ", p)), path[-1] if path else "")
        attrs, rels = [], []
        for a in c.findall("ownedAttribute"):
            ti = a.find("type")
            aid = xid(a)
            target = name_of.get(ti.get(_X + "idref"), "") if ti is not None else ""
            target = target or ext_types.get(aid, "")         # a type of another model (S-Series primitives)
            entry = {"xml": xml_name.get(aid, ""), "doc": docs.get(aid, ""),
                     "lower": _mult(a, "lowerValue"), "upper": _mult(a, "upperValue")}
            if a.get("association"):
                rels.append({"role": a.get("name") or "", "target": target, **entry,
                             "xml": entry["xml"] or xml_name.get(a.get("association"), "")})
            else:
                attrs.append({"name": a.get("name") or "", "type": target, "key": aid in keyed, **entry})
        if t != "uml:Class":                    # S-Series primitives: IdentifierType = id + classifier + …
            out["datatypes"][name] = {"xml": xml_name.get(i, ""), "doc": docs.get(i, ""), "kind": t.split(":")[1],
                                      "attrs": attrs}
            continue
        supers = [name_of.get(g.get("general"), "") for g in c.findall("generalization")]
        out["classes"][name] = {
            "name": name, "uof": uof, "package": " / ".join(path[2:]) if len(path) > 2 else " / ".join(path),
            "xml": xml_name.get(i, ""), "xml_ref": xml_ref.get(i, ""), "doc": docs.get(i, ""),
            "abstract": c.get("isAbstract") == "true", "common": any(p.startswith("CDM") for p in path),
            "supers": [s for s in supers if s], "attrs": attrs, "relations": rels,
        }
    # associations owned by the association element itself (navigable from one end only in some exports)
    return out


def inherited_attrs(model: dict, cls: str, seen: set | None = None) -> list[dict]:
    """A class's attributes including those of its superclasses (S-Series base objects, abstract parents)."""
    seen = seen or set()
    c = model["classes"].get(cls)
    if not c or cls in seen:
        return []
    seen.add(cls)
    out = list(c["attrs"])
    for s in c["supers"]:
        out += [dict(a, inherited_from=s) for a in inherited_attrs(model, s, seen) if a["name"] not in {x["name"] for x in out}]
    return out
