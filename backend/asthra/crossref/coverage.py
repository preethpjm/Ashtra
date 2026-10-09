"""What ASTHRA has, and still needs, for each standard: schema (XSD / DTD), S-Series data model (XMI),
how many generic names it can place, which placements need a person's look — and what to do about it.

The standards listed are the ones ASTHRA has met: installed schemas, loaded data models, library sources and
the documents of the projects (recognised from their root element, namespace, schema location or DOCTYPE)."""
from __future__ import annotations

import re

from .names import in_context

# S-Series specifications publish their XML schemas and UML data models (XMI) on their download pages;
# S1000D and ATA have schemas (or DTDs) but no UML data model.
S_SERIES = {"SX000I", "S2000M", "S3000L", "S4000P", "S5000F", "S6000T"}
WHERE = {
    "S1000D": ("https://s1000d.org", "the S1000D schemas for your issue"),
    "ATA2200": ("https://publications.airlines.org", "the ATA iSpec 2200 DTDs for your manual type (licensed from A4A)"),
}
LABEL = {"ATA2200": "ATA iSpec 2200", "SX000I": "SX000i", "ENGINEERING BOM": "Engineering BOM"}
SOURCE_STANDARD = {"S1000D-DM": "S1000D", "S1000D": "S1000D", "ATA-CMM": "ATA2200", "ATA-AMM": "ATA2200", "ATA-IPC": "ATA2200",
                   "S2000M": "S2000M", "S3000L": "S3000L", "S4000P": "S4000P", "S5000F": "S5000F", "S6000T": "S6000T",
                   "SX000I": "SX000I", "ENG-BOM": "ENGINEERING BOM", "ENG-RECON": "ENGINEERING BOM"}


def norm_standard(s: str) -> str:
    s = (s or "").upper().replace(" ", "").replace("ISPEC", "").replace("_", "")
    if s.startswith("ATA"):
        return "ATA2200"
    if s in ("ENGINEERINGBOM", "ENG-BOM"):
        return "ENGINEERING BOM"
    return s


def download_page(std: str) -> tuple[str, str] | None:
    s = norm_standard(std)
    if s in S_SERIES:
        spec = "sx000i" if s == "SX000I" else s.lower()
        return f"https://www.s-series.org/{spec}/downloads/", f"the {LABEL.get(s, s)} XML schema and data model (XMI)"
    return WHERE.get(s)


def guess_standard(ident: dict, tags: set[str] | None = None, models: list[dict] | None = None) -> str | None:
    """The standard a document is written to, from what identification found (also when no schema matched)."""
    root = ident.get("root") or {}
    name = (root.get("local_name") or "").lower()
    hay = " ".join(str(root.get(k) or "") for k in ("namespace", "schema_location", "public_id", "system_id")).lower()
    for spec in ("s2000m", "s3000l", "s4000p", "s5000f", "s6000t", "sx000i", "s1000d"):
        if spec in hay:
            return spec.upper()
    if name in ("dmodule", "pm", "dml", "comrep", "scormcontentpackage", "icnmetadatafile", "ddn"):
        return "S1000D"
    from ..render.profiles import ATA_ROOTS
    if name in ATA_ROOTS or "ata" in hay.split("//")[1:2] or re.search(r"//ata[-\w]*//", hay):
        return "ATA2200"
    if name == "provisioningexchange":
        return "S2000M"
    if tags and models:                                   # an S-Series document: its tags are the model's XML names
        best, score = None, 0
        for m in models:
            xmls = {c["xml"] for c in m["classes"].values() if c["xml"]}
            n = len(tags & xmls)
            if n > score:
                best, score = m, n
        if best and score >= 3:
            return norm_standard(best["spec"])
    return None


def uncertain(placement: dict | None) -> bool:
    """A placement a person should look at: found by name only, or found in several places."""
    if not placement or placement.get("from") == "confirmed":
        return False
    return placement.get("from", "").startswith("name match") or bool(placement.get("others"))


GENERIC = {"identifier", "name", "type", "revision", "description", "value", "code", "text", "date", "set", "the",
           "element", "ref", "value", "number", "item", "status", "descr", "rev"}


# words schemas use for the library's terms (beyond the terms' own names), to suggest places to review
SYNONYMS = {
    "PartAsDesigned.partIdentifier": ["pnr", "partNumber", "partNo"],
    "PartAsDesigned.partIdentifier.identifierSetBy": ["cage", "mfr", "mfc", "manufacturer", "vendor"],
    "PartAsDesigned.partName": ["nomenclature", "kwd", "partName", "descr"],
    "ASTHRA:Part.unitOfIssue": ["uoi", "unitOfIssue", "unit"],
    "ASTHRA:CatalogueItem.figureNumber": ["fignbr", "figure"],
    "ASTHRA:CatalogueItem.itemNumber": ["itemnbr", "item"],
    "ASTHRA:CatalogueItem.indenture": ["indent", "indenture"],
    "ASTHRA:CatalogueItem.quantityPerNextHigherAssembly": ["upa", "quantity", "qty"],
    "PartAsDesignedPartsListEntry.partsListEntryQuantity": ["upa", "quantity", "qty"],
    "ASTHRA:CatalogueItem.usableOnCode": ["effcode", "effectivity", "usableOn", "applic"],
    "Task.taskIdentifier": ["taskCode", "taskId"],
    "Organization.organizationName": ["enterpriseName", "vendorName"],
}


def candidates(index, term: dict, limit: int = 8, strong_only: bool = False) -> list[str]:
    """Places in a schema where a term could sit, best first: its known tags, then similar names
    (with strong_only: only names equal to one of the term's words, not merely containing it)."""
    known: list[str] = []
    for n in term["names"].values():
        for c in ([n["path"]] if n.get("path") else list(n.get("all") or [n["tag"]])):
            for h in index.resolve(c):
                if h["path"] not in known:
                    known.append(h["path"])
    split = lambda s: re.findall(r"[a-z]{3,}", re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s).lower())
    leaf_of = lambda t: re.split(r"[/@ (]", t.strip("/@ "))[-1] if t else ""
    words = {w for n in term["names"].values() for w in split(leaf_of(n["tag"].split(" ")[0]))} | set(split(term["attr"]))
    words -= GENERIC
    words |= {w.lower() for w in SYNONYMS.get(term["id"], [])}
    scored = []
    for el, e in index.m["elements"].items():
        own = [(el, el)] if (e.get("text") or e.get("mixed")) else []          # only places that can hold a value
        for leaf, path_tail in own + [(a["name"], f"{el}/@{a['name']}") for a in e.get("attrs", [])]:
            low = leaf.lower()
            parts = set(split(leaf))
            s = sum(1 for w in words if w in low or low in w)
            # strong: the name is one of the term's words, or every word of it is (generic words aside)
            if low in words:
                s += 20
            elif parts and parts <= (words | GENERIC) and parts & words:
                s += 10
            if s:
                scored.append((s, path_tail))
    for sc, tail in sorted(scored, key=lambda x: -x[0]):
        if strong_only and sc < 10:
            break
        for h in index.resolve(tail if "/" in tail else tail):
            if h["path"] not in known and in_context(term["id"], h["path"]):
                known.append(h["path"])
        if len(known) >= limit:
            break
    return known[:limit]
