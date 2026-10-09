"""The generic layer: one name for each piece of product data, whatever standard it came from.

A *term* is named after the S-Series common data model (SX002D) wherever it defines the data —
`PartAsDesigned.partIdentifier`, `BreakdownElement.breakdownElementIdentifier`, `Task.taskIdentifier` — so the
names mean what the S-Series community means by them. Each term knows what every standard calls it:

* S-Series specifications whose UML data model is loaded (XMI): the XML name the model gives it
  (`hwPart` / `partId` / `id` in S3000L and SX000i);
* standards that are not modelled in UML (S1000D, ATA iSpec 2200, engineering BOMs): ASTHRA's crosswalk,
  shown as such and editable;
* any installed schema: where that name actually sits in the schema (see names.py).

Data ASTHRA needs that the S-Series model does not define (the IPD figure / item numbering of S1000D and
ATA, units of issue) are ASTHRA terms, prefixed "ASTHRA:".
"""
from __future__ import annotations

import re

from .xmi import inherited_attrs


def humanize(name: str) -> str:
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", name).strip()
    return (s[:1].upper() + s[1:].lower()) if s else name


def model_label(m: dict) -> str:
    return f"{m.get('spec') or 'Model'} {m.get('issue') or ''}".strip()


# ------------------------------------------------------------------ ASTHRA terms (not in the S-Series model)
ASTHRA_TERMS = {
    "ASTHRA:CatalogueItem.figureNumber": ("Catalogue item", "Figure number", "The illustration (figure) a parts-list line belongs to."),
    "ASTHRA:CatalogueItem.itemNumber": ("Catalogue item", "Item number", "Item number of the line in the figure (with its variant letter)."),
    "ASTHRA:CatalogueItem.indenture": ("Catalogue item", "Indenture", "Level in the parts list: 1 for the assembly the list is of."),
    "ASTHRA:CatalogueItem.quantityPerNextHigherAssembly": ("Catalogue item", "Quantity per next higher assembly", "How many are fitted in the assembly one level up (RF for the top)."),
    "ASTHRA:CatalogueItem.usableOnCode": ("Catalogue item", "Usable on code (effectivity)", "Code of the configurations a line applies to."),
    "ASTHRA:CatalogueItem.sourceMaintenanceRecoverability": ("Catalogue item", "SMR code", "Source, maintenance and recoverability code."),
    "ASTHRA:Part.unitOfIssue": ("Part", "Unit of issue", "Unit in which the part is supplied (EA, M, KG …)."),
    "ASTHRA:Part.nationalStockNumber": ("Part", "NSN", "NATO / national stock number."),
}

# ASTHRA terms that a specification's own model defines under its own names
EQUIVALENT = {
    "ASTHRA:CatalogueItem.figureNumber": ["Figure.figureIdentifier"],
    "ASTHRA:CatalogueItem.itemNumber": ["FigureItem.figureItemIdentifier"],
    "ASTHRA:CatalogueItem.indenture": ["FigureItem.figureItemIndentureLevel"],
    "ASTHRA:CatalogueItem.quantityPerNextHigherAssembly": ["FigureItemRealizationContextData.quantityInNextHigherAssembly"],
    "ASTHRA:CatalogueItem.usableOnCode": ["FigureItemRealizationContextData.figureItemUsableOnCode"],
    "ASTHRA:Part.unitOfIssue": ["HardwarePartAsDesignedSupportData.hardwarePartUnitOfIssue"],
}

# the terms the knowledge library holds today, and the record they belong to
CORE = {
    "PartAsDesigned.partIdentifier": "Part",
    "PartAsDesigned.partIdentifier.identifierSetBy": "Part",
    "PartAsDesigned.partName": "Part",
    "ASTHRA:Part.unitOfIssue": "Part",
    "ASTHRA:Part.nationalStockNumber": "Part",
    "PartAsDesignedPartsListEntry.partsListEntryIdentifier": "Parts list entry",
    "PartAsDesignedPartsListEntry.partsListEntryQuantity": "Parts list entry",
    "ASTHRA:CatalogueItem.figureNumber": "Catalogue item",
    "ASTHRA:CatalogueItem.itemNumber": "Catalogue item",
    "ASTHRA:CatalogueItem.indenture": "Catalogue item",
    "ASTHRA:CatalogueItem.quantityPerNextHigherAssembly": "Catalogue item",
    "ASTHRA:CatalogueItem.usableOnCode": "Catalogue item",
    "ASTHRA:CatalogueItem.sourceMaintenanceRecoverability": "Catalogue item",
    "BreakdownElement.breakdownElementIdentifier": "Breakdown element",
    "BreakdownElement.breakdownElementName": "Breakdown element",
    "BreakdownElementRevision.breakdownElementRevisionIdentifier": "Breakdown element",
    "Task.taskIdentifier": "Task",
    "TaskRevision.taskName": "Task",
    "TaskRevision.taskRevisionIdentifier": "Task",
    "TaskRevision.taskDuration": "Task",
    "MaintenanceLevel.maintenanceLevelIdentifier": "Task",
    "TaskRequirement.taskRequirementIdentifier": "Task requirement",
    "TaskRequirementRevision.taskRequirementDescription": "Task requirement",
    "Subtask.subtaskIdentifier": "Task",
    "WarningCautionNote.warningCautionNoteDescription": "Warning / caution",
    "WarningCautionNote.warningCautionNoteType": "Warning / caution",
    "Organization.organizationIdentifier": "Organization",
    "Organization.organizationName": "Organization",
    "Document.documentIdentifier": "Document",
    "Document.documentTitle": "Document",
    "Product.productIdentifier": "Product",
    "Product.productName": "Product",
}

# ------------------------------------------------------------------ crosswalk for standards without a UML model
# term -> the element / attribute names the standard uses (first = preferred). Paths use "/" for nesting and
# "@" for attributes. These are ASTHRA's reading of the standards: shown as "crosswalk" and editable.
CROSSWALK: dict[str, dict[str, list[str]]] = {
    "S1000D": {
        "PartAsDesigned.partIdentifier": ["partRef/@partNumberValue", "partNumber", "partIdent/@partNumberValue"],
        "PartAsDesigned.partIdentifier.identifierSetBy": ["partRef/@manufacturerCodeValue", "manufacturerCode", "partIdent/@manufacturerCodeValue"],
        "PartAsDesigned.partName": ["descrForPart", "partKeyword", "name"],
        "ASTHRA:Part.unitOfIssue": ["unitOfIssue"],
        "ASTHRA:Part.nationalStockNumber": ["natoStockNumber"],
        "ASTHRA:CatalogueItem.figureNumber": ["catalogSeqNumber/@figureNumber"],
        "ASTHRA:CatalogueItem.itemNumber": ["catalogSeqNumber/@item"],
        "ASTHRA:CatalogueItem.indenture": ["catalogSeqNumber/@indenture"],
        "ASTHRA:CatalogueItem.quantityPerNextHigherAssembly": ["quantityPerNextHigherAssy"],
        "ASTHRA:CatalogueItem.usableOnCode": ["usableOnCodeAssy", "applicabilitySegment/usableOnCodeAssy"],
        "ASTHRA:CatalogueItem.sourceMaintenanceRecoverability": ["sourceMaintRecoverability"],
        "BreakdownElement.breakdownElementIdentifier": ["dmCode (SNS: systemCode-subSystemCode-subSubSystemCode-assyCode)"],
        "Task.taskIdentifier": ["dmCode", "taskCode"],
        "TaskRevision.taskName": ["dmTitle/techName"],
        "TaskRevision.taskDuration": ["reqTechInfoGroup/estimatedTime", "estimatedTime"],
        "WarningCautionNote.warningCautionNoteDescription": ["warning/warningAndCautionPara", "caution/warningAndCautionPara"],
        "WarningCautionNote.warningCautionNoteType": ["warning | caution | note"],
        "Organization.organizationIdentifier": ["@enterpriseCode", "enterpriseIdent/@manufacturerCodeValue"],
        "Organization.organizationName": ["enterpriseName"],
        "Document.documentIdentifier": ["dmCode"],
        "Document.documentTitle": ["dmTitle"],
        "Product.productIdentifier": ["dmCode/@modelIdentCode"],
    },
    "ATA iSpec 2200": {
        "PartAsDesigned.partIdentifier": ["pnr"],
        "PartAsDesigned.partIdentifier.identifierSetBy": ["iplnom/mfr", "mfrpnr/mfr"],
        "PartAsDesigned.partName": ["nom/kwd", "cmpnom"],
        "ASTHRA:Part.unitOfIssue": ["uoi"],
        "ASTHRA:CatalogueItem.figureNumber": ["figure/@fignbr"],
        "ASTHRA:CatalogueItem.itemNumber": ["itemdata/@itemnbr"],
        "ASTHRA:CatalogueItem.indenture": ["itemdata/@indent"],
        "ASTHRA:CatalogueItem.quantityPerNextHigherAssembly": ["upa"],
        "ASTHRA:CatalogueItem.usableOnCode": ["effcode"],
        "PartAsDesignedPartsListEntry.partsListEntryQuantity": ["upa"],
        "Task.taskIdentifier": ["pgblk/task/@key", "task"],
        "TaskRevision.taskName": ["task/title"],
        "Subtask.subtaskIdentifier": ["subtask"],
        "WarningCautionNote.warningCautionNoteDescription": ["task/warning", "warning", "caution"],
        "Organization.organizationIdentifier": ["vendata/mfr", "cmm/@spl"],
        "Organization.organizationName": ["vendata/mad"],
        "Document.documentIdentifier": ["cmm/@docnbr", "@docnbr"],
        "Document.documentTitle": ["cmm/title"],
    },
    "Engineering BOM": {
        "PartAsDesigned.partIdentifier": ["Part Number", "P/N"],
        "PartAsDesigned.partIdentifier.identifierSetBy": ["CAGE", "Manufacturer"],
        "PartAsDesigned.partName": ["Description", "Name"],
        "ASTHRA:Part.unitOfIssue": ["Unit", "UoM"],
        "PartAsDesignedPartsListEntry.partsListEntryIdentifier": ["Find No"],
        "PartAsDesignedPartsListEntry.partsListEntryQuantity": ["Qty"],
    },
}


class Vocabulary:
    """Terms from the loaded S-Series data models, ASTHRA's own terms and the crosswalk."""

    def __init__(self, models: list[dict]):
        self.models = models
        self.terms: dict[str, dict] = {}
        self.classes: dict[str, dict] = {}
        # datatypes of all models: a specification's model uses the S-Series primitives (IdentifierType …)
        # that only the common data model defines
        self.datatypes: dict[str, dict] = {}
        for m in models:
            for k, v in m.get("datatypes", {}).items():
                if v.get("attrs") or k not in self.datatypes:
                    self.datatypes[k] = v
        # the reference (hub) model: the one carrying the common data model (SX000i), else the largest
        self.hub = max(models, key=lambda m: (sum(c["common"] for c in m["classes"].values()), len(m["classes"])), default=None)
        for m in sorted(models, key=lambda m: m is not self.hub):      # the hub first: its definitions win
            self._add_model(m)
        for tid, (cls, label, doc) in ASTHRA_TERMS.items():
            self.terms.setdefault(tid, {"id": tid, "class": cls, "attr": tid.split(".")[-1], "component": "",
                                        "label": label, "doc": doc, "type": "", "key": False, "common": True,
                                        "origin": "ASTHRA", "names": {}})
        for fam, table in CROSSWALK.items():
            for tid, names in table.items():
                t = self.terms.get(tid)
                if t is None:          # crosswalk for a term no loaded model defines: keep it, from the crosswalk
                    cls, _, attr = tid.rpartition(".")
                    t = self.terms[tid] = {"id": tid, "class": cls, "attr": attr, "component": "", "label": humanize(attr),
                                           "doc": "", "type": "", "key": attr.endswith("Identifier"), "common": True,
                                           "origin": "crosswalk", "names": {}}
                t["names"][fam] = {"tag": names[0], "all": names, "from": "crosswalk"}
        for m in models:
            self._adopt_common(m)
        self._equivalents()
        for tid, group in CORE.items():
            if tid in self.terms:
                self.terms[tid]["core"] = group

    def _add_model(self, m: dict):
        label = model_label(m)
        dts = self.datatypes
        for cname, c in m["classes"].items():
            cl = self.classes.setdefault(cname, {"name": cname, "label": humanize(cname), "doc": c["doc"], "uof": c["uof"],
                                                 "common": False, "names": {}, "keys": []})
            cl["common"] = cl["common"] or c["common"]
            cl["doc"] = cl["doc"] or c["doc"]
            if c["xml"]:
                cl["names"][label] = c["xml"]
            for a in c["attrs"]:
                tid = f"{cname}.{a['name']}"
                dt = dts.get(a["type"], {})
                comps = dt.get("attrs") or []
                primary = next((x for x in comps if (x.get("lower") or 0) >= 1 and x.get("xml")), None)
                path = a["xml"] + ("/" + primary["xml"] if primary and a["xml"] else "")
                self._term(tid, cname, a["name"], "", a["doc"], a["type"], a["key"], c["common"], label, c["xml"], a["xml"], path)
                if a["key"] and tid not in cl["keys"]:
                    cl["keys"].append(tid)
                if a["type"] == "IdentifierType":     # who issued the identifier: for parts, the manufacturer (CAGE)
                    for comp in comps:
                        if comp["name"] in ("identifierSetBy", "identifierClassifier") and comp.get("xml") and a["xml"]:
                            self._term(f"{tid}.{comp['name']}", cname, a["name"], comp["name"], comp["doc"], "", False,
                                       c["common"], label, c["xml"], comp["xml"], f"{a['xml']}/{comp['xml']}")
        for cname in self.classes:
            pass

    def _adopt_common(self, m: dict):
        """A specification model that only *references* a common-data-model class (S2000M 7.0: HardwarePartAsDesigned
        with no attributes of its own) uses that class as the common model defines it: its attributes, inherited ones
        included, get this specification's column, under its own XML name for the class."""
        hub = self.hub
        if not hub or m is hub:
            return
        label = model_label(m)
        from .xmi import inherited_attrs
        for cname, c in m["classes"].items():
            hc = hub["classes"].get(cname)
            if c["attrs"] or not hc or not (hc["attrs"] or hc["supers"]):
                continue
            cxml = c["xml"] or hc["xml"]
            for a in inherited_attrs(hub, cname):
                owner = a.get("inherited_from") or cname
                tid = f"{owner}.{a['name']}"
                t = self.terms.get(tid)
                if not t or label in t["names"]:
                    continue
                hn = t["names"].get(model_label(hub)) or {}
                rel = hn.get("path", "").split("/", 1)[1] if "/" in hn.get("path", "") else a.get("xml", "")
                t["names"][label] = {"tag": hn.get("tag", a.get("xml", "")), "path": f"{cxml}/{rel}", "class_tag": cxml,
                                     "from": "data model (common model)"}
                for comp in ("identifierSetBy", "identifierClassifier"):
                    st = self.terms.get(f"{tid}.{comp}")
                    sn = st and st["names"].get(model_label(hub))
                    if sn and label not in st["names"]:
                        st["names"][label] = {**sn, "path": f"{cxml}/{sn['path'].split('/', 1)[1]}", "class_tag": cxml,
                                              "from": "data model (common model)"}

    def _equivalents(self):
        """ASTHRA terms a specification models under its own names (S2000M figure items = IPD lines)."""
        for tid, model_terms in EQUIVALENT.items():
            t = self.terms.get(tid)
            if not t:
                continue
            for mt in model_terms:
                src = self.terms.get(mt)
                if not src:
                    continue
                for col, n in src["names"].items():
                    if col not in t["names"] and n.get("from", "").startswith("data model"):
                        t["names"][col] = {**n, "from": f"data model ({mt})"}
                src.setdefault("same_as", tid)

    def _term(self, tid, cls, attr, comp, doc, typ, key, common, label, cxml, xml, path):
        t = self.terms.get(tid)
        if t is None:
            lab = humanize(attr) + (f" — {humanize(comp.replace('identifier', ''))}" if comp else "")
            t = self.terms[tid] = {"id": tid, "class": cls, "attr": attr, "component": comp, "label": lab, "doc": doc,
                                   "type": typ, "key": key, "common": common, "origin": "model", "names": {}}
        t["common"] = t["common"] or common
        t["doc"] = t["doc"] or doc
        if xml:
            t["names"][label] = {"tag": xml, "path": f"{cxml}/{path}" if cxml else path, "class_tag": cxml, "from": "data model"}

    # ------------------------------------------------------------------ queries
    def standards(self) -> list[str]:
        return [model_label(m) for m in self.models] + list(CROSSWALK)

    def search(self, q: str = "", core_only: bool = False, common_only: bool = False, limit: int = 300) -> list[dict]:
        ql = q.lower().strip()
        out = []
        for t in self.terms.values():
            if core_only and not t.get("core"):
                continue
            if common_only and not t["common"]:
                continue
            if ql:
                hay = " ".join([t["id"], t["label"], t["doc"]] + [n["tag"] for n in t["names"].values()]).lower()
                if not all(w in hay for w in ql.split()):
                    continue
            out.append(t)
        out.sort(key=lambda t: (not t.get("core"), not t["common"], t["id"]))
        return out[:limit]

    def class_of_tag(self, standard: str, tag: str) -> str | None:
        for c in self.classes.values():
            if c["names"].get(standard) == tag:
                return c["name"]
        return None
