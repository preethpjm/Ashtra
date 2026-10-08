"""ATA iSpec 2200 manual (CMM; SGML rendered to XML by OpenSP, or XML) → knowledge facts.

Reads what the manual states in well-defined places; prose is not interpreted:
  identity       manual (chapter-section-subject, revision) and each TASK / SUBTASK identifier
  resources      <ted> tools and <con> consumables used in each task      → parts + information_resource
  safety         warnings and cautions in each task                       → safety_statement
  IPL            figure / itemdata: part number, vendor (V + CAGE), nomenclature, indent,
                 units per assembly, effectivity code                     → parts + catalogue_item
  vendors        vendata (V-code, name and address)                       → organization + organization_code
  bulletins      sbdata                                                   → service_bulletin

Conventions (so ATA lines compare with S1000D IPD and S2000M lines):
  item "50A" is stored as item "050" + variant "A"; indent 0/1/2 as indenture 1/2/3; "upa" as written
  ("RF" for a reference assembly); a part with no vendor code is stored without a CAGE (unqualified):
  ASTHRA suggests a match with the same part number elsewhere but never merges it on its own.
Re-importing a manual replaces what was imported from it before.
"""
from __future__ import annotations

import re

from .s1000d_import import _local, _text
from .store import KnowledgeStore

KIND = "ATA-CMM"


def _kids(el, name):
    return [c for c in el if _local(c).lower() == name]


def _first(el, name):
    for d in el.iter():
        if _local(d).lower() == name:
            return d
    return None


def _all(el, name):
    return [d for d in el.iter() if _local(d).lower() == name]


def ident(el, prefix: str) -> str:
    """TASK 25-21-71-000-801-A01 from the element's attributes (as printed in the manual)."""
    g = lambda a: (el.get(a) or "").strip()
    ch, se, su, seq, vn = g("chapnbr"), g("sectnbr"), g("subjnbr"), g("seq"), g("varnbr")
    if not (ch and se and su and seq):
        return ""
    p2 = lambda v: v.zfill(2) if v.isdigit() else v
    p3 = lambda v: v.zfill(3) if v.isdigit() else v
    tail = g("confltr").upper() + (p2(vn) if vn else "")
    parts = [p2(ch), p2(se), p2(su), g("func").upper(), p3(seq)]
    return f"{prefix} " + "-".join(p for p in parts if p) + (f"-{tail}" if tail else "")


def split_item(item: str) -> tuple[str, str]:
    """ATA / S2000M item "50A" → ("050", "A"); "-1" (not illustrated) → ("001", "")."""
    m = re.match(r"^\s*-?\s*0*(\d+)\s*([A-Za-z]*)\s*$", item or "")
    if not m:
        return (item or "").strip(), ""
    return m.group(1).zfill(3), m.group(2).upper()


def vendor_cage(code: str) -> str:
    """ATA vendor code "VZZV02" → CAGE "ZZV02" (the V prefix marks a vendor code)."""
    c = (code or "").strip().upper()
    return c[1:] if len(c) == 6 and c.startswith("V") else c


def _forget(k: KnowledgeStore, doc: str) -> None:
    old = [r[0] for r in k.db.execute("SELECT id FROM source WHERE kind=? AND document=?", (KIND, doc))]
    for sid in old:
        dmcs = [r[0] for r in k.db.execute("SELECT dmc FROM information_item WHERE source_id=?", (sid,))]
        for dmc in dmcs:
            for t in ("information_property", "information_resource", "information_ref", "information_link", "safety_statement"):
                k.db.execute(f"DELETE FROM {t} WHERE dmc=?", (dmc,))
        k.db.execute("DELETE FROM catalogue_item WHERE source_id=?", (sid,))
        k.db.execute("DELETE FROM information_item WHERE source_id=?", (sid,))


def import_manual(k: KnowledgeStore, root, schema: str = "", file: str = "") -> dict:
    """root: the manual's top element (cmm, amm, ipc …) as lxml."""
    g = lambda a: (root.get(a) or "").strip()
    ch, se, su = g("chapnbr"), g("sectnbr"), g("subjnbr")
    if not (ch and se and su):
        return {"imported": False, "reason": "no chapter-section-subject on the top element (not an ATA manual)"}
    p2 = lambda v: v.zfill(2) if v.isdigit() else v
    number = f"{p2(ch)}-{p2(se)}-{p2(su)}"
    kind = _local(root).upper()
    doc = f"{kind} {number}"
    issue = " ".join(x for x in (f"rev {g('tsn')}" if g("tsn") else "", g("revdate")) if x)
    bei = f"ATA {number}"
    _forget(k, doc)
    src = k.source(KIND, doc, issue=issue, schema=schema, note=file)
    title = _text(_first(root, "title"))
    comp = _text(_first(root, "cmpnom"))
    k.add("information_item", dmc=doc, issue=issue, title=" - ".join(x for x in (comp, title) if x), info_name=title,
          bei=bei, info_code=kind, item_location=None, source_id=src)
    counts = {"tasks": 0, "resources": 0, "parts": 0, "safety": 0, "catalogue": 0, "vendors": 0, "bulletins": 0}

    # top assembly part numbers and the manufacturer (partinfo / mfrpnr)
    for mp in _all(root, "mfrpnr"):
        pn, mfr = _text(_first(mp, "pnr")), _text(_first(mp, "mfr"))
        if pn:
            k.part(pn, mfr, comp, "part", source_id=src)

    # tasks: identity, page block, tools, consumables, warnings, cautions
    for task in _all(root, "task"):
        tid = ident(task, "TASK")
        if not tid:
            continue
        ttitle = next((_text(c) for c in task if _local(c).lower() == "title"), "")
        pg = task.getparent()
        pgt = next((_text(c) for c in pg if _local(c).lower() == "title"), "") if pg is not None else ""
        k.add("information_item", dmc=tid, issue=issue, title=f"{ttitle} ({pgt})" if pgt else ttitle, info_name=pgt or None,
              bei=bei, info_code=(task.get("func") or "").upper() or None, item_location=task.get("pgblknbr"), source_id=src)
        k.add("information_ref", dmc=tid, ref_dmc=doc)
        counts["tasks"] += 1
        seen = set()
        for tag, rkind, ptype, num_tag, name_tag in (("ted", "support-equipment", "support-equipment", "toolnbr", "toolname"),
                                                      ("con", "consumable", "consumable", "connbr", "conname")):
            for r in _all(task, tag):
                pn, name = _text(_first(r, num_tag)), _text(_first(r, name_tag))
                if not pn or (rkind, pn) in seen:
                    continue
                seen.add((rkind, pn))
                pid = k.part(pn, "", name, ptype, source_id=src)
                k.add("information_resource", dmc=tid, kind=rkind, part_id=pid, name=name or pn, quantity=None, unit=None)
                counts["resources"] += 1
                counts["parts"] += 1
        for tag in ("warning", "caution"):
            for w in _all(task, tag):
                txt = _text(w)
                if txt:
                    k.add("safety_statement", kind=tag, text=txt, dmc=tid, bei=bei, source_id=src)
                    counts["safety"] += 1

    # IPL
    for fig in _all(root, "figure"):
        fn = (fig.get("fignbr") or "").strip()
        sheet = _first(fig, "sheet")
        icn = (sheet.get("gnbr") if sheet is not None else None) or None
        for it in _all(fig, "itemdata"):
            pn = _text(_first(it, "pnr"))
            if not pn:
                continue
            nom = _first(it, "nom")
            name = ", ".join(x for x in (_text(_first(nom, "kwd")), _text(_first(nom, "adt"))) if x) if nom is not None else ""
            iplnom = _first(it, "iplnom")
            mfr = next((_text(c) for c in iplnom if _local(c).lower() == "mfr"), "") if iplnom is not None else ""
            pid = k.part(pn, vendor_cage(mfr), name, "part", source_id=src, unit_of_issue="EA")
            item, var = split_item(it.get("itemnbr") or "")
            ind = (it.get("indent") or "").strip()
            effs = [_text(e) for e in _kids(it, "effcode") if _text(e)]
            k.add("catalogue_item", bei=bei, figure=fn, figure_variant="", item=item, item_variant=var,
                  indenture=int(ind) + 1 if ind.isdigit() else None, part_id=pid,
                  qty_per_next_assy=_text(_first(it, "upa")) or None, usable_on_code=",".join(effs) or None,
                  smr_code=None, icn=icn, source_id=src)
            counts["catalogue"] += 1
            counts["parts"] += 1

    # vendors and service bulletins
    for v in _all(root, "vendata"):
        cage = vendor_cage(_text(_first(v, "mfr")))
        if cage:
            addr = _text(_first(v, "mad"))
            k.add("organization", id=cage, name=addr.split(",")[0].strip() or cage, description=addr, source_id=src, layer="shared")
            k.add("organization_code", code=cage, organization_id=cage, site=None)
            counts["vendors"] += 1
    for sb in _all(root, "sbdata"):
        num = _text(_first(sb, "sbnbr"))
        if num:
            k.add("service_bulletin", id=num, change_id=None, title=_text(_first(sb, "sbtitle")) or None,
                  description=_text(_first(sb, "effect")) or None, status=None, issued=_text(_first(sb, "issdate")) or None,
                  sb_type=None, priority=None, embodiment_limit=None, cost=None)
            counts["bulletins"] += 1
    k.db.commit()
    return {"imported": True, "dmc": doc, "title": title, **counts}
