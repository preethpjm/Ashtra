"""S1000D data module → knowledge facts (K1).

Reads what S1000D states in well-defined places; prose is not interpreted:
  identity       DMC, issue, title, info code, and the BEI (the SNS part of the DMC) linking it to the breakdown
  personnel      reqPersons: number, skill level, trade, estimated time  → information_property
  resources      supportEquipDescr / supplyDescr / spareDescr (name, identNumber, quantity) → parts + information_resource
  safety         warnings and cautions                                   → safety_statement
  references     dmRef                                                   → information_ref
  IPD            catalogSeqNumber / itemSeqNumber (figure, item, part, quantity) → catalogue_item
Re-importing a data module replaces what was imported from it before.
"""
from __future__ import annotations

import re

from lxml import etree

from .store import KnowledgeStore

RESOURCE_KINDS = {"supportEquipDescr": "support-equipment", "supplyDescr": "consumable", "spareDescr": "spare",
                  # shorter forms used by some issues/projects (and ASTHRA's synthetic test schema)
                  "supportEquip": "support-equipment", "supply": "consumable", "spare": "spare"}
PART_TYPES = {"support-equipment": "support-equipment", "consumable": "consumable", "spare": "part"}


def _local(el) -> str:
    return etree.QName(el).localname if isinstance(el.tag, str) else ""


def _find(el, name):
    for d in el.iter():
        if _local(d) == name:
            return d
    return None


def _all(el, name):
    return [d for d in el.iter() if _local(d) == name]


def _text(el) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip() if el is not None else ""


def dmc_parts(code) -> dict[str, str]:
    a = {k: code.get(k, "") for k in ("modelIdentCode", "systemDiffCode", "systemCode", "subSystemCode", "subSubSystemCode",
                                      "assyCode", "disassyCode", "disassyCodeVariant", "infoCode", "infoCodeVariant",
                                      "itemLocationCode")}
    head = f"{a['modelIdentCode']}-{a['systemDiffCode']}-{a['systemCode']}-{a['subSystemCode']}{a['subSubSystemCode']}-{a['assyCode']}"
    dmc = f"{head}-{a['disassyCode']}{a['disassyCodeVariant']}-{a['infoCode']}{a['infoCodeVariant']}-{a['itemLocationCode']}"
    ipd = a["infoCode"].startswith("94")
    bei = f"{head}-00A" if ipd else f"{head}-{a['disassyCode']}{a['disassyCodeVariant']}"   # IPD: disassy = figure number
    return {"dmc": dmc, "bei": bei, "info_code": a["infoCode"], "item_location": a["itemLocationCode"], **a}


def _minutes(el) -> str | None:
    if el is None:
        return None
    try:
        v = float(_text(el))
    except ValueError:
        return None
    unit = (el.get("unitOfMeasure") or "min").lower()
    return f"{v * 60:g}" if unit in ("h", "hr", "hour", "hours") else f"{v:g}"


def _forget(k: KnowledgeStore, dmc: str) -> None:
    for t in ("information_property", "information_resource", "information_ref", "information_link"):
        k.db.execute(f"DELETE FROM {t} WHERE dmc=?", (dmc,))
    k.db.execute("DELETE FROM safety_statement WHERE dmc=?", (dmc,))
    old = [r[0] for r in k.db.execute("SELECT id FROM source WHERE kind='S1000D-DM' AND document=?", (dmc,))]
    for sid in old:
        k.db.execute("DELETE FROM catalogue_item WHERE source_id=?", (sid,))
        k.db.execute("DELETE FROM information_item WHERE source_id=?", (sid,))


def import_dm(k: KnowledgeStore, root, schema: str = "", file: str = "") -> dict:
    """root: the dmodule element (lxml). -> summary of what was imported."""
    code = _find(root, "dmCode")
    if code is None:
        return {"imported": False, "reason": "no dmCode (not an S1000D data module)"}
    d = dmc_parts(code)
    dmc = d["dmc"]
    issue_el = _find(root, "issueInfo")
    issue = f"{issue_el.get('issueNumber', '')}-{issue_el.get('inWork', '')}" if issue_el is not None else ""
    title = " - ".join(x for x in (_text(_find(root, "techName")), _text(_find(root, "infoName"))) if x)
    _forget(k, dmc)
    src = k.source("S1000D-DM", dmc, issue=issue, schema=schema, note=file)
    k.add("information_item", dmc=dmc, issue=issue, title=title, bei=d["bei"], info_code=d["info_code"],
          item_location=d["item_location"], source_id=src)
    counts = {"resources": 0, "parts": 0, "safety": 0, "references": 0, "catalogue": 0}

    # personnel
    pers = _find(root, "personnel")
    if pers is not None:
        props = {"persons": pers.get("numRequired"),
                 "skill_level": (_find(pers, "personSkill").get("skillLevelCode") if _find(pers, "personSkill") is not None else None),
                 "trade": _text(_find(pers, "trade")) or None,
                 "estimated_minutes": _minutes(_find(pers, "estimatedTime"))}
        for n, v in props.items():
            if v:
                k.add("information_property", dmc=dmc, name=n, value=str(v))

    # resources
    content = _find(root, "content")
    for tag, kind in RESOURCE_KINDS.items():
        for r in _all(content if content is not None else root, tag):
            name = _text(_find(r, "name"))
            ident = _find(r, "identNumber")
            pn = _text(_find(ident, "partNumber")) if ident is not None else ""
            cage = _text(_find(ident, "manufacturerCode")) if ident is not None else ""
            if not pn and _find(r, "toolRef") is not None:          # a tool referenced by its number
                tr = _find(r, "toolRef")
                pn = tr.get("toolNumber") or _text(tr)
            qel = _find(r, "reqQuantity")
            pid = None
            if pn:
                pid = k.part(pn, cage, name, PART_TYPES[kind], source_id=src)
                counts["parts"] += 1
            k.add("information_resource", dmc=dmc, kind=kind, part_id=pid, name=name or pn,
                  quantity=_text(qel) or None, unit=(qel.get("unitOfMeasure") if qel is not None else None))
            counts["resources"] += 1

    # warnings and cautions
    for tag in ("warning", "caution"):
        for w in _all(content if content is not None else root, tag):
            txt = _text(w)
            if txt:
                k.add("safety_statement", kind=tag, text=txt, dmc=dmc, bei=d["bei"], source_id=src)
                counts["safety"] += 1

    # references to other data modules
    for ref in _all(content if content is not None else root, "dmRef"):
        rc = _find(ref, "dmCode")
        if rc is not None:
            k.add("information_ref", dmc=dmc, ref_dmc=dmc_parts(rc)["dmc"])
            counts["references"] += 1

    # IPD catalogue lines
    for csn in _all(root, "catalogSeqNumber"):
        fig, item = csn.get("figureNumber", ""), csn.get("item", "")
        for isn in [x for x in csn if _local(x) == "itemSeqNumber"] or [csn]:
            ref = _find(isn, "partRef")
            pn = (ref.get("partNumberValue") if ref is not None else None) or _text(_find(isn, "partNumber"))
            cage = (ref.get("manufacturerCodeValue") if ref is not None else None) or _text(_find(isn, "manufacturerCode"))
            if not pn:
                continue
            name = _text(_find(isn, "descrForPart"))
            pid = k.part(pn, cage, name, "part", source_id=src)
            k.add("catalogue_item", bei=d["bei"], figure=fig, figure_variant=csn.get("figureNumberVariant", ""),
                  item=item, item_variant=csn.get("itemVariant", ""),
                  indenture=int(csn.get("indenture")) if (csn.get("indenture") or "").isdigit() else None,
                  part_id=pid, qty_per_next_assy=_text(_find(isn, "quantityPerNextHigherAssy")) or None, source_id=src)
            counts["catalogue"] += 1
    k.db.commit()
    return {"imported": True, "dmc": dmc, "title": title, **counts}
