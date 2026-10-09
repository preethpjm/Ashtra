"""Write records into a document of any installed schema, using its binding and its schema model:
each record becomes one record element with its children in schema order, required attributes and children
filled from the schema (defaults, fixed values, generated IDs), and everything else in the document untouched."""
from __future__ import annotations

from . import schema_graph as g
from .markup import attrs_of, existing_ids, replace_records, scan, tags_in
from .values import write


def _esc(s: str, attr: bool = False) -> str:
    s = str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return s.replace('"', "&quot;") if attr else s


class _Node:
    def __init__(self, name: str):
        self.name, self.attrs, self.kids, self.text = name, {}, [], None

    def child(self, name: str) -> "_Node":
        for k in self.kids:
            if k.name == name:
                return k
        n = _Node(name)
        self.kids.append(n)
        return n


class Renderer:
    def __init__(self, model: dict, binding: dict, rules: dict, syntax: str, taken_ids: set[str]):
        self.m, self.b, self.rules, self.sgml = model, binding, rules, syntax == "sgml"
        self.ids = set(taken_ids)
        self.warnings: list[str] = []
        self.required = {s["path"] for s in g.slots(model, binding["record"]) if s.get("required")}
        self.learned: dict[tuple[str, str], str] = {}     # (element, attribute) -> the value existing records all use

    def _new_id(self, base: str) -> str:
        n = 1
        while f"{base}-{n}".lower() in self.ids:
            n += 1
        v = f"{base}-{n}"
        self.ids.add(v.lower())
        return v

    def _place(self, root: _Node, path: str, values: list[str]):
        steps = path.split("/")
        attr = steps[-1][1:] if steps[-1].startswith("@") else None
        els = steps[:-1] if attr else steps
        node = root
        for s in els[:-1] if not attr else els:
            node = node.child(s)
        if attr:
            node.attrs[attr] = values[0]
            return
        leaf = els[-1]
        for v in values:                                   # a repeating slot gets one element per value
            n = _Node(leaf)
            n.text = v
            node.kids.append(n)

    def record(self, rec: dict, n: int) -> str:
        r = _Node(self.b["record"])
        from .concepts import CONCEPTS
        canon = list(CONCEPTS[self.b.get("concept", "parts_list")]["fields"])
        for f, spec in sorted(self.b["fields"].items(), key=lambda kv: canon.index(kv[0]) if kv[0] in canon else 99):
            vals = write(f, spec.get("format"), rec, self.rules)
            if vals is None and f == "cage" and rec.get("cage") and spec["path"] in self.required:
                vals = write(f, spec.get("format"), rec, {})          # the schema needs it: the omit list does not apply
            if vals is None:
                continue
            if spec.get("format") == "split_kwd_adt":
                kw, _, mod = vals[0].partition(", ")
                self._place(r, spec["path"], [kw])
                if mod:
                    adt = spec["path"].rsplit("/", 1)[0] + "/adt"
                    if "adt" in g.order(self.m, spec["path"].split("/")[-2] if "/" in spec["path"] else self.b["record"]):
                        self._place(r, adt, [mod])
                continue
            self._place(r, spec["path"], vals)
        for path, val in (self.b.get("constants") or {}).items():
            self._place(r, path, [val])
        self._complete(r, f"{self.b['record']} {rec.get('item', '')}{rec.get('item_variant', '')}".strip())
        return self._text(r)

    def _complete(self, node: _Node, where: str):
        for a in g.attrs(self.m, node.name):
            if a["name"] in node.attrs or not a.get("required"):
                continue
            if a.get("fixed") is not None:
                node.attrs[a["name"]] = a["fixed"]
            elif a.get("default") not in (None, ""):
                node.attrs[a["name"]] = a["default"]
            elif a.get("kind") == "id":
                node.attrs[a["name"]] = self._new_id(f"{node.name}-{where.split()[-1] if where.split() else 'x'}".lower())
            elif (node.name.lower(), a["name"].lower()) in self.learned:
                node.attrs[a["name"]] = self.learned[(node.name.lower(), a["name"].lower())]
            elif a.get("kind") == "enum" and a.get("values"):
                node.attrs[a["name"]] = a["values"][0]
            else:
                node.attrs[a["name"]] = ""
                self.warnings.append(f"{where}: required attribute {node.name}/@{a['name']} has no value")
        present = {k.name for k in node.kids}
        for c in g.required_children(self.m, node.name, present):
            if c not in present:
                child = node.child(c)
                if g.is_text(self.m, c):
                    child.text = ""
                    self.warnings.append(f"{where}: required element {c} has no value")
        for k in node.kids:
            self._complete(k, where)
        content = (g.el(self.m, node.name) or {}).get("content") or {}
        if not (content.get("k") == "choice" and content.get("max") is None):       # (a | b | c)*: any order, keep ours
            order = g.order(self.m, node.name)
            node.kids.sort(key=lambda k: order.index(k.name) if k.name in order else len(order))

    def _text(self, n: _Node) -> str:
        at = "".join(f' {k}="{_esc(v, True)}"' for k, v in n.attrs.items())
        if g.is_empty(self.m, n.name) or (not n.kids and n.text is None and not g.is_text(self.m, n.name)
                                          and not g.children(self.m, n.name)):
            return f"<{n.name}{at}>" if self.sgml else f"<{n.name}{at}/>"
        inner = _esc(n.text) if n.text is not None else ""
        inner += "".join(self._text(k) for k in n.kids)
        return f"<{n.name}{at}>{inner}</{n.name}>"


def learn(text: str, insts: list[dict], binding: dict) -> dict:
    """Attribute values that every existing record of the document uses alike (e.g. S1000D itemSeqNumberValue
    "00A"): a required attribute the binding does not fill takes that value rather than staying empty. Attributes
    the binding writes, and identifiers, are not learned."""
    mapped = {p.split("/")[-1][1:].lower() for p in [f["path"] for f in binding["fields"].values()] if p.split("/")[-1].startswith("@")}
    seen: dict[tuple[str, str], set[str]] = {}
    n = 0
    for inst in insts:
        for a, b in inst["records"]:
            n += 1
            for name, attrs in tags_in(text[a:b]):
                for k, v in attrs.items():
                    if k not in mapped and k not in ("id", "key"):
                        seen.setdefault((name, k), set()).add(v)
    return {k: next(iter(v)) for k, v in seen.items() if len(v) == 1 and n}


def generate(text: str, syntax: str, model: dict, binding: dict, records: list[dict], rules: dict) -> dict:
    """-> {text, report}: the document's parts list replaced by the records (grouped by figure where the
    binding puts the figure on a container element)."""
    empty = {n for n, e in model["elements"].items() if e.get("empty")}
    allowed = {n.lower(): {c.lower() for c in g.order(model, n)} for n in model["elements"]} if syntax == "sgml" else None
    insts = scan(text, binding["container"], binding["record"], empty, allowed)
    report = {"written": 0, "groups": [], "warnings": [], "problems": []}
    if not insts:
        report["problems"].append(f"The document has no {'/'.join(binding['container'])}: add it (with its heading "
                                  "elements) and generate again.")
        return {"text": text, "report": report}
    r = Renderer(model, binding, rules, syntax, existing_ids(text))
    r.learned = learn(text, insts, binding)
    group = binding.get("group")
    if group:
        by_fig: dict[str, list[dict]] = {}
        for rec in records:
            by_fig.setdefault(str(rec.get("figure") or rules.get("figure") or "1"), []).append(rec)
        # replace from the end of the text so earlier offsets stay valid
        plan = []
        for fig, recs in by_fig.items():
            inst = next((x for x in insts if str(x["path_attrs"][group["level"]].get(group["attr"].lower(), "")).lower().lstrip("0")
                         == fig.lower().lstrip("0")), None)
            if inst is None:
                report["problems"].append(f"Figure {fig} is not in the document: add the figure ({group['element']} with "
                                          f"{group['attr']}=\"{fig}\") and generate again; its {len(recs)} line(s) were not written.")
                continue
            plan.append((inst, fig, recs))
        for inst, fig, recs in sorted(plan, key=lambda p: -p[0]["start"]):
            text = replace_records(text, inst, [r.record(x, i) for i, x in enumerate(recs, 1)])
            report["written"] += len(recs)
            report["groups"].append({"figure": fig, "lines": len(recs), "replaced": len(inst["records"])})
    else:
        inst = insts[0]
        recs = [dict(x, figure=x.get("figure") or rules.get("figure") or "01") for x in records]
        fpath = (binding["fields"].get("figure") or {}).get("path", "")
        if fpath.startswith("@"):                      # write the figure number the way the document already does ("01")
            have = {tags_in(text[a:b])[0][1].get(fpath[1:].lower()) for a, b in inst["records"]} - {None}
            if len(have) == 1:
                h = next(iter(have))
                recs = [dict(x, figure=h) if str(x["figure"]).lstrip("0") == h.lstrip("0") else x for x in recs]
        text = replace_records(text, inst, [r.record(x, i) for i, x in enumerate(recs, 1)])
        report["written"] = len(recs)
        report["groups"].append({"figure": rules.get("figure") or "", "lines": len(recs), "replaced": len(inst["records"])})
        if len(insts) > 1:
            report["warnings"].append(f"The document has {len(insts)} {binding['container'][-1]} elements; the first was used.")
    report["warnings"] += r.warnings
    return {"text": text, "report": report}
