"""S2000M provisioning data → knowledge facts.

Reads the provisioning exchange of ASTHRA's S2000M test schema (urn:asthra:synthetic:s2000m):
  part        part number, CAGE, nomenclature, unit of issue      → part
  ipdItem     figure, item, indenture, quantity per assembly, effectivity → catalogue_item
Element names are matched without their namespace. The official S2000M XML (issue 6.x / 7.x) needs its own
mapping, added when that schema is installed; the facts land in the same tables.
Re-importing an exchange replaces what was imported from it before.
"""
from __future__ import annotations

from .ata_import import split_item
from .s1000d_import import _local, _text
from .store import KnowledgeStore

KIND = "S2000M"


def _child(el, name):
    return next((c for c in el if _local(c) == name), None)


def _ctext(el, name) -> str:
    return _text(_child(el, name))


def import_exchange(k: KnowledgeStore, root, schema: str = "", file: str = "") -> dict:
    header = _child(root, "header")
    doc = (_ctext(header, "exchangeId") if header is not None else "") or file or "S2000M exchange"
    issue = _ctext(header, "issue") if header is not None else ""
    product = _ctext(header, "productIdentifier") if header is not None else ""
    for sid in [r[0] for r in k.db.execute("SELECT id FROM source WHERE kind=? AND document=?", (KIND, doc))]:
        k.db.execute("DELETE FROM catalogue_item WHERE source_id=?", (sid,))
    src = k.source(KIND, doc, issue=issue, schema=schema, note=file)
    counts = {"parts": 0, "catalogue": 0}
    by_id: dict[str, int] = {}
    for p in [d for d in root.iter() if _local(d) == "part"]:
        pn = _ctext(p, "partNumber")
        if not pn:
            continue
        by_id[p.get("id", "")] = k.part(pn, _ctext(p, "cage"), _ctext(p, "nomenclature"), "part", source_id=src,
                                         unit_of_issue=_ctext(p, "unitOfIssue") or None)
        counts["parts"] += 1
    for it in [d for d in root.iter() if _local(d) == "ipdItem"]:
        pid = by_id.get(it.get("partRef", ""))
        if pid is None:
            continue
        item, var = split_item(_ctext(it, "itemNumber"))
        ind = _ctext(it, "indenture")
        k.add("catalogue_item", bei=f"S2000M {product}" if product else None, figure=_ctext(it, "figureNumber"), figure_variant="",
              item=item, item_variant=var, indenture=int(ind) if ind.isdigit() else None, part_id=pid,
              qty_per_next_assy=_ctext(it, "quantityPerAssembly") or None, usable_on_code=_ctext(it, "effectivity") or None,
              smr_code=None, icn=None, source_id=src)
        counts["catalogue"] += 1
    k.db.commit()
    return {"imported": True, "dmc": doc, "title": f"S2000M provisioning {doc}" + (f" ({product})" if product else ""), **counts}
