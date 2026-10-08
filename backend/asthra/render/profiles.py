"""Display profiles: which element plays which role in the document view.

Roles are display-only; they never change validation or the saved XML. Built-in
profiles cover the common element names of each family; any schema package can
override or extend them through `render_roles` in its manifest (e.g. an OEM DTD).
Element names not in a profile fall back to a structural heuristic in the editor.

ATA iSpec 2200 names below follow common usage across the ATA DTDs (task/subtask,
list1..list7 with l1item..l7item, CALS tables). Verify against the DTD you install
and override in the package where yours differ.
"""
from __future__ import annotations

ROLES = {
    # document furniture
    "meta", "doc-title", "doc-subtitle", "hidden",
    # structure
    "section", "section-labeled", "title", "para",
    # procedures
    "step-seq", "step", "none",
    # lists (container roles decide numbering style)
    "list-bullet", "list-num", "list-alpha", "list-paren-num", "list-paren-alpha", "list-num-paren",
    "list-alpha-paren", "item",
    "deflist", "term", "definition",
    # admonitions
    "warning", "caution", "note",
    # tables & figures (CALS)
    "table", "tgroup", "thead", "tbody", "tfoot", "row", "entry", "figure", "graphic",
    # data-exchange style content
    "record", "field",
    # ATA procedure lists (numbered by depth, see NUMBERING) and transparent wrappers
    "proc-list", "proc-item", "wrap",
    # change marks (revst / revend): shown as revision bars, never as text
    "change-mark",
    # rows of data shown as a ruled table (IPL detailed parts list, vendor and SB lists)
    "row-list", "data-row",
}

S1000D = {
    "roles": {
        "identAndStatusSection": "meta", "techName": "doc-title", "infoName": "doc-subtitle",
        "levelledPara": "section", "title": "title",
        "para": "para", "simplePara": "para", "notePara": "para", "warningAndCautionPara": "para",
        "mainProcedure": "step-seq", "proceduralStep": "step",
        "preliminaryRqmts": "section-labeled", "closeRqmts": "section-labeled", "refs": "section-labeled",
        "reqCondGroup": "section-labeled", "reqPersons": "section-labeled", "reqSupportEquips": "section-labeled",
        "reqSupplies": "section-labeled", "reqSpares": "section-labeled", "reqSafety": "section-labeled",
        "noConds": "none", "noSupportEquips": "none", "noSupplies": "none", "noSpares": "none", "noSafety": "none",
        "reqCondNoRef": "record", "supportEquipDescr": "record", "supplyDescr": "record", "spareDescr": "record",
        "reqCond": "para", "name": "field", "reqQuantity": "field", "partNumber": "field", "manufacturerCode": "field",
        "randomList": "list-bullet", "sequentialList": "list-num", "listItem": "item",
        "definitionList": "deflist", "listItemTerm": "term", "listItemDefinition": "definition",
        "warning": "warning", "caution": "caution", "note": "note",
        "table": "table", "tgroup": "tgroup", "thead": "thead", "tbody": "tbody", "tfoot": "tfoot",
        "row": "row", "entry": "entry", "colspec": "hidden", "spanspec": "hidden",
        "figure": "figure", "graphic": "graphic",
        "illustratedPartsCatalog": "row-list", "catalogSeqNumber": "data-row", "itemSeqNumber": "wrap",
        "description": "section", "procedure": "section",
    },
    "columns": {"illustratedPartsCatalog": ["Fig. item", "Part number", "Nomenclature", "Usable on", "Qty per assy"]},
    # S1000D: decimal numbering 1, 1.1, 1.1.1 in a fixed left column
    "numbering": {"scheme": "decimal", "elements": ["levelledPara", "proceduralStep"],
                  "resets": ["description", "mainProcedure", "content", "procedure"]},
    "labels": {
        "preliminaryRqmts": "Preliminary requirements", "closeRqmts": "Requirements after job completion",
        "refs": "References", "reqCondGroup": "Required conditions", "reqPersons": "Required persons",
        "reqSupportEquips": "Support equipment", "reqSupplies": "Consumables, materials and expendables",
        "reqSpares": "Spares", "reqSafety": "Safety conditions", "mainProcedure": "Procedure",
        "illustratedPartsCatalog": "Illustrated parts data",
    },
    "default_text": "para",
}

ATA2200 = {
    "roles": {
        "title": "title", "para": "para",
        "pgblk": "section", "task": "section", "subtask": "section", "topic": "section", "subtopic": "section",
        "list1": "list-alpha", "list2": "list-paren-num", "list3": "list-paren-alpha", "list4": "list-num-paren",
        "list5": "list-alpha-paren", "list6": "list-bullet", "list7": "list-bullet",
        "l1item": "item", "l2item": "item", "l3item": "item", "l4item": "item", "l5item": "item",
        "l6item": "item", "l7item": "item",
        "unlist": "list-bullet", "unlitem": "item", "numlist": "list-num", "numlitem": "item",
        "warning": "warning", "caution": "caution", "note": "note",
        "table": "table", "tgroup": "tgroup", "thead": "thead", "tbody": "tbody", "tfoot": "tfoot",
        "row": "row", "entry": "entry", "colspec": "hidden", "spanspec": "hidden",
        "figure": "figure", "graphic": "figure", "sheet": "graphic", "effect": "meta",
        **{f"prclist{i}": "proc-list" for i in range(1, 8)},
        **{f"prcitem{i}": "proc-item" for i in range(1, 8)},
        "prcitem": "wrap",
        "revst": "change-mark", "revend": "change-mark",
        "prtlist": "row-list", "itemdata": "data-row",
        "vendlist": "section", "vendata": "data-row",
        "sblist": "section", "sbdata": "data-row",
        "trlist": "section", "trdata": "data-row",
    },
    # ATA iSpec 2200: TASK 1. / SUBTASK A. / (1) / (a) / 1 / a, indented one step per level
    "numbering": {"scheme": "ata", "elements": ["task", "subtask"] + [f"prcitem{i}" for i in range(1, 8)],
                  "resets": ["pgblk"], "ident": {"task": "TASK", "subtask": "SUBTASK"}},
    # column headings of row lists (one heading per child element, in order)
    "columns": {
        "prtlist": ["Fig. item", "Part number", "Nomenclature", "Eff. code", "Units per assy"],
        "vendlist": ["Code", "Name and address"],
        "sblist": ["Effect", "Service bulletin", "Title", "Issue date"],
        "trlist": ["Revision", "Status", "Location"],
    },
    "labels": {},
    "default_text": "para",
}

DATA_EXCHANGE = {       # S2000M / S3000L style: records with labelled fields
    "roles": {
        "header": "meta", "part": "record", "ipdItem": "record", "task": "record", "subtask": "record",
        "breakdownElement": "record", "parts": "section-labeled", "ipdRecords": "section-labeled",
        "productBreakdown": "section-labeled", "tasks": "section-labeled", "step": "item",
    },
    "labels": {"parts": "Parts", "ipdRecords": "IPD records", "productBreakdown": "Product breakdown", "tasks": "Tasks"},
    "default_text": "field",
}

GENERIC = {"roles": {"title": "title", "para": "para", "p": "para", "warning": "warning", "caution": "caution",
                     "note": "note", "table": "table", "tgroup": "tgroup", "thead": "thead", "tbody": "tbody",
                     "row": "row", "entry": "entry", "colspec": "hidden"},
           "labels": {}, "default_text": "para"}

BY_STANDARD = {"S1000D": ("S1000D", S1000D), "ATA2200": ("ATA iSpec 2200", ATA2200),
               "ATA2300": ("ATA Spec 2300", ATA2200), "S2000M": ("S2000M", DATA_EXCHANGE),
               "S3000L": ("S3000L", DATA_EXCHANGE)}
S1000D_ROOTS = {"dmodule", "pm", "dml", "comment", "ddn"}


# top-level elements of ATA iSpec 2200 / Spec 2300 manuals (CMM, AMM, IPC, SRM, EM, FIM, TSM, WDM ...)
ATA_ROOTS = {"cmm", "amm", "ipc", "cmmipl", "srm", "em", "emm", "fim", "tsm", "wdm", "wm", "sdm", "ssm", "nsm",
             "mm", "om", "fcom", "mel", "cmp", "epc", "ipl", "eipc"}


def resolve(standard: str | None, root_name: str | None, overrides: dict[str, str] | None = None) -> dict:
    """Profile for a document: its standard's profile (or a guess from the root element
    when no schema is selected), plus the package's own overrides."""
    name, base = BY_STANDARD.get((standard or "").upper(), (None, None))
    if base is None:
        if root_name in S1000D_ROOTS:
            name, base = "S1000D (from root element)", S1000D
        elif (root_name or "").lower() in ATA_ROOTS:
            name, base = "ATA iSpec 2200 (from root element)", ATA2200
        else:
            name, base = "generic", GENERIC
    roles = dict(base["roles"])
    for k, v in (overrides or {}).items():
        if v in ROLES:
            roles[k] = v
    return {"profile": name, "roles": roles, "labels": dict(base["labels"]), "default_text": base["default_text"],
            "numbering": base.get("numbering"), "columns": dict(base.get("columns", {}))}
