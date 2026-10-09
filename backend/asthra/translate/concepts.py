"""Neutral record types and the words schemas commonly use for their fields.

A record is a plain dict. Values are neutral: item "050" + variant "A"; indenture 1 = top of the list;
quantity as a number string; top = True for the assembly the list is of (ATA writes its quantity "RF").
"""
from __future__ import annotations

PARTS_LIST = {
    "id": "parts_list",
    "label": "Parts list (IPL / IPD / catalogue lines)",
    "record_hint": ["catalogSeqNumber", "itemdata", "ipdItem", "catalogueItem", "partsListItem", "csn", "item", "iplItem"],
    "fields": {
        # field: (label, synonyms — leaf names as schemas write them; first ones are the strongest)
        "figure": ("Figure", ["figureNumber", "fignbr", "figNumber", "figure", "figNo"]),
        "item": ("Item", ["item", "itemnbr", "itemNumber", "itemNo", "findNumber", "findNo", "itemNbr"]),
        "item_variant": ("Item variant", ["itemVariant", "itemVar", "variant"]),
        "indenture": ("Indenture", ["indenture", "indent", "indentureLevel", "level"]),
        "part_number": ("Part number", ["partNumberValue", "partNumber", "pnr", "partNo", "pn", "partNbr", "partIdentifier"]),
        "name": ("Name", ["descrForPart", "nomenclature", "kwd", "partName", "nom", "name", "description", "shortName"]),
        "cage": ("CAGE / manufacturer", ["manufacturerCodeValue", "manufacturerCode", "cage", "cageCode", "mfr", "mfc", "vendorCode"]),
        "quantity": ("Quantity per assembly", ["quantityPerNextHigherAssy", "quantityPerAssembly", "upa", "qpa", "quantity", "qty"]),
        "unit": ("Unit of issue", ["unitOfIssue", "uoi", "unitOfMeasure", "unit"]),
        "effectivity": ("Effectivity", ["usableOnCodeAssy", "effcode", "effectivity", "usableOnCode", "applicability", "eff"]),
        "not_illustrated": ("Not illustrated", ["notIllustrated", "illusind"]),
        "attaching": ("Attaching part", ["attach", "attachingPart", "attachStoreShipPart"]),
    },
}

CONCEPTS = {PARTS_LIST["id"]: PARTS_LIST}
