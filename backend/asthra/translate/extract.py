"""Read records out of a document of any installed schema, using its binding: the reverse of generate.
This is how ASTHRA reads parts lists from standards it has no dedicated importer for."""
from __future__ import annotations

from lxml import etree

from .values import read


def _local(el) -> str:
    return etree.QName(el).localname.lower() if isinstance(el.tag, str) else ""


def _kids(el, name: str):
    return [c for c in el if _local(c) == name.lower()]


def _text(el) -> str:
    return " ".join("".join(el.itertext()).split())


def _containers(root, path: list[str]):
    if not path or _local(root) != path[0].lower():
        return []
    level = [[root]]
    for step in path[1:]:
        level = [chain + [c] for chain in level for c in _kids(chain[-1], step)]
    return level


def _values(rec, path: str) -> list[str]:
    steps = path.split("/")
    attr = steps[-1][1:] if steps[-1].startswith("@") else None
    els = [rec]
    for s in steps[:-1] if attr else steps:
        els = [c for e in els for c in _kids(e, s)]
    if attr:
        out = []
        for e in els:
            v = next((v for k, v in e.attrib.items() if etree.QName(k).localname.lower() == attr.lower()), None)
            if v is not None:
                out.append(v)
        return out
    return [_text(e) for e in els]


def extract(root, binding: dict) -> list[dict]:
    """-> neutral records (the same shape records.py produces)."""
    out = []
    group = binding.get("group")
    for chain in _containers(root, binding["container"]):
        fig = ""
        if group:
            holder = chain[group["level"]] if group["level"] < len(chain) else None
            fig = (holder.get(group["attr"]) or holder.get(group["attr"].lower()) or "") if holder is not None else ""
        for rec in _kids(chain[-1], binding["record"]):
            r: dict = {"figure": fig}
            for field, spec in binding["fields"].items():
                vals = [v for v in _values(rec, spec["path"]) if v.strip() != ""] if spec.get("format") != "presence" \
                    else _values(rec, spec["path"])
                if not vals:
                    continue
                if spec.get("format") == "split_kwd_adt":
                    adt = _values(rec, spec["path"].rsplit("/", 1)[0] + "/adt") if "/" in spec["path"] else []
                    r["name"] = ", ".join(x for x in (vals[0], adt[0] if adt else "") if x)
                    continue
                if field == "effectivity":
                    r["effectivity"] = ",".join(v.strip() for v in vals)
                    continue
                r.update(read(field, spec.get("format"), vals[0]))
            if r.get("part_number"):
                if r.get("top") is None:
                    r["top"] = r.get("indenture") == 1
                out.append(r)
    return out


def to_library(k, records: list[dict], kind: str, document: str, schema: str = "") -> dict:
    """Write extracted records into the knowledge library as a parts list (catalogue lines)."""
    for (sid,) in k.db.execute("SELECT id FROM source WHERE kind=? AND document=?", (kind, document)).fetchall():
        k.db.execute("DELETE FROM catalogue_item WHERE source_id=?", (sid,))
    src = k.source(kind, document, schema=schema, note="read through a schema binding")
    n = 0
    for r in records:
        pid = k.part(r["part_number"], r.get("cage") or "", r.get("name") or "", "part", source_id=src,
                     unit_of_issue=r.get("unit") or "EA")
        k.add("catalogue_item", bei=None, figure=str(r.get("figure") or ""), figure_variant="", item=r.get("item") or "",
              item_variant=r.get("item_variant") or "", indenture=r.get("indenture"), part_id=pid,
              qty_per_next_assy=r.get("quantity") or None,
              usable_on_code=r.get("effectivity") or None, smr_code=None, icn=None, source_id=src)
        n += 1
    k.db.commit()
    return {"imported": bool(n), "catalogue": n, "parts": n, "reason": "" if n else "no parts-list lines found by the binding"}
