"""Facts under generic names: every value ASTHRA knows about an item, from every source, keyed by term.

Two kinds of facts:
* the knowledge library (S1000D, ATA, S2000M, engineering BOM … already imported): read through an adapter
  that says which library column is which term — nothing is copied;
* documents of any S-Series specification whose data model is loaded (S3000L, SX000i, S2000M, S5000F …):
  read generically through the model's XML names into the table `xr_fact`.

Subjects (what a fact is about) are the S-Series key classes: Part (part number + CAGE), BreakdownElement
(BEI), Task, TaskRequirement, Organization (CAGE), Document (DMC / document number), Product.
"""
from __future__ import annotations

from datetime import datetime, timezone

from lxml import etree

from .xmi import inherited_attrs

SUBJECTS = {"PartAsDesigned": "Part", "BreakdownElement": "BreakdownElement", "Task": "Task",
            "TaskRequirement": "TaskRequirement", "Organization": "Organization", "Document": "Document",
            "Product": "Product"}
SUBJECT_LABEL = {"Part": "Part", "BreakdownElement": "Breakdown element", "Task": "Task", "TaskRequirement": "Task requirement",
                 "Organization": "Organization", "Document": "Document / data module", "Product": "Product"}
# which vocabulary column a library source was written in (to show the tag the value was read from)
SOURCE_COLUMN = {"S1000D-DM": "S1000D", "S1000D": "S1000D", "ATA-CMM": "ATA iSpec 2200", "ATA-AMM": "ATA iSpec 2200", "ATA-IPC": "ATA iSpec 2200",
                 "ENG-BOM": "Engineering BOM", "ENG-RECON": "Engineering BOM"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS xr_fact (           -- facts read generically from S-Series documents
  id INTEGER PRIMARY KEY, subject TEXT NOT NULL, subject_key TEXT NOT NULL, term TEXT NOT NULL, value TEXT,
  context TEXT, source_id INTEGER, path TEXT);
CREATE INDEX IF NOT EXISTS xr_fact_subject ON xr_fact(subject, subject_key);
CREATE TABLE IF NOT EXISTS xr_name (           -- where a term sits in an installed schema, as confirmed by a person
  package_id TEXT NOT NULL, doc_type TEXT NOT NULL, term TEXT NOT NULL, path TEXT NOT NULL, tag TEXT,
  saved_at TEXT NOT NULL, PRIMARY KEY (package_id, doc_type, term));
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def subject_of_class(model: dict, cls: str, seen=None) -> str | None:
    if cls in SUBJECTS:
        return SUBJECTS[cls]
    seen = seen or set()
    c = model["classes"].get(cls)
    if not c or cls in seen:
        return None
    seen.add(cls)
    for s in c["supers"]:
        r = subject_of_class(model, s, seen)
        if r:
            return r
    return None


# ------------------------------------------------------------------ the knowledge library, as facts
def _rows(db, sql, *a):
    return [dict(r) for r in db.execute(sql, a)]


def _src(db, sid) -> dict:
    if not sid:
        return {"kind": "library", "document": ""}
    r = db.execute("SELECT kind, document, schema FROM source WHERE id=?", (sid,)).fetchone()
    return {"kind": r["kind"], "document": r["document"], "schema": r["schema"]} if r else {"kind": "library", "document": ""}


def library_facts(db, subject: str, key: str) -> list[dict]:
    """[{term, value, source:{kind, document}, context}] for one subject, from the knowledge library."""
    out: list[dict] = []
    add = lambda term, value, sid, context="": value not in (None, "") and out.append(
        {"term": term, "value": str(value) if not isinstance(value, float) else f"{value:g}", "source": _src(db, sid), "context": context})
    if subject == "Part":
        from ..knowledge.identity import normalize_part_number
        pn, _, cage = key.partition("|")
        parts = _rows(db, "SELECT * FROM part WHERE part_number_key=?" + (" AND manufacturer_code=?" if cage else ""),
                      *([normalize_part_number(pn)] + ([cage] if cage else [])))
        for p in parts:
            add("PartAsDesigned.partIdentifier", p["part_number"], p["source_id"])
            add("PartAsDesigned.partIdentifier.identifierSetBy", p["manufacturer_code"], p["source_id"])
            add("PartAsDesigned.partName", p["name"], p["source_id"])
            add("ASTHRA:Part.unitOfIssue", p["unit_of_issue"], p["source_id"])
            add("ASTHRA:Part.nationalStockNumber", p["nsn"], p["source_id"])
            for c in _rows(db, "SELECT * FROM catalogue_item WHERE part_id=?", p["id"]):
                ctx = f"figure {c['figure']} item {c['item']}{c['item_variant'] or ''}"
                add("ASTHRA:CatalogueItem.figureNumber", c["figure"], c["source_id"], ctx)
                add("ASTHRA:CatalogueItem.itemNumber", f"{c['item']}{c['item_variant'] or ''}", c["source_id"], ctx)
                add("ASTHRA:CatalogueItem.indenture", c["indenture"], c["source_id"], ctx)
                add("ASTHRA:CatalogueItem.quantityPerNextHigherAssembly", c["qty_per_next_assy"], c["source_id"], ctx)
                add("ASTHRA:CatalogueItem.usableOnCode", c["usable_on_code"], c["source_id"], ctx)
                add("ASTHRA:CatalogueItem.sourceMaintenanceRecoverability", c["smr_code"], c["source_id"], ctx)
                add("BreakdownElement.breakdownElementIdentifier", c["bei"], c["source_id"], ctx)
            for b in _rows(db, """SELECT b.*, a.part_number AS parent FROM bom_line b LEFT JOIN part a ON a.id=b.parent_id
                                  WHERE b.child_id=?""", p["id"]):
                ctx = f"in {b['parent']}" if b["parent"] else "top"
                add("PartAsDesignedPartsListEntry.partsListEntryIdentifier", b["find_no"], b["source_id"], ctx)
                add("PartAsDesignedPartsListEntry.partsListEntryQuantity", b["quantity"], b["source_id"], ctx)
            for r in _rows(db, "SELECT bei FROM breakdown_realization WHERE part_id=?", p["id"]):
                add("BreakdownElement.breakdownElementIdentifier", r["bei"], p["source_id"], "realises")
            for t in _rows(db, "SELECT task_id, kind, quantity, unit FROM task_resource WHERE part_id=?", p["id"]):
                add("Task.taskIdentifier", t["task_id"], None, f"used by the task as {t['kind']}")
            for r in _rows(db, "SELECT dmc, kind FROM information_resource WHERE part_id=?", p["id"]):
                add("Document.documentIdentifier", r["dmc"], None, f"required by the data module as {r['kind']}")
    elif subject == "BreakdownElement":
        for b in _rows(db, "SELECT * FROM breakdown_element WHERE bei=?", key):
            add("BreakdownElement.breakdownElementIdentifier", b["bei"], b.get("source_id"))
            add("BreakdownElement.breakdownElementName", b["name"], b.get("source_id"))
            add("BreakdownElementRevision.breakdownElementRevisionIdentifier", b["revision"], b.get("source_id"))
        for p in _rows(db, "SELECT p.part_number, p.source_id FROM breakdown_realization r JOIN part p ON p.id=r.part_id WHERE r.bei=?", key):
            add("PartAsDesigned.partIdentifier", p["part_number"], p["source_id"], "realised by")
        for t in _rows(db, "SELECT id, source_id FROM task WHERE bei=?", key):
            add("Task.taskIdentifier", t["id"], t["source_id"], "task on this element")
        for d in _rows(db, "SELECT dmc, source_id FROM information_item WHERE bei=?", key):
            add("Document.documentIdentifier", d["dmc"], d["source_id"], "data module for this element")
    elif subject == "Task":
        for t in _rows(db, "SELECT * FROM task WHERE id=?", key):
            add("Task.taskIdentifier", t["id"], t["source_id"])
            add("TaskRevision.taskName", t["name"], t["source_id"])
            add("TaskRevision.taskRevisionIdentifier", t["revision"], t["source_id"])
            add("TaskRevision.taskDuration", f"{t['estimated_minutes']:g} min" if t["estimated_minutes"] else None, t["source_id"])
            add("MaintenanceLevel.maintenanceLevelIdentifier", t["maintenance_level"], t["source_id"])
            add("BreakdownElement.breakdownElementIdentifier", t["bei"], t["source_id"], "task on")
        for r in _rows(db, "SELECT requirement_id FROM task_covers WHERE task_id=?", key):
            add("TaskRequirement.taskRequirementIdentifier", r["requirement_id"], None, "covers")
        for s in _rows(db, "SELECT id, description FROM subtask WHERE task_id=? ORDER BY seq", key):
            add("Subtask.subtaskIdentifier", s["id"], None, s["description"][:60])
        for w in _rows(db, "SELECT kind, text, source_id FROM safety_statement WHERE task_id=?", key):
            add("WarningCautionNote.warningCautionNoteDescription", w["text"], w["source_id"], w["kind"])
        for r in _rows(db, """SELECT r.kind, p.part_number FROM task_resource r JOIN part p ON p.id=r.part_id WHERE r.task_id=?""", key):
            add("PartAsDesigned.partIdentifier", r["part_number"], None, r["kind"])
        for d in _rows(db, "SELECT dmc FROM information_link WHERE target_kind='task' AND target_id=?", key):
            add("Document.documentIdentifier", d["dmc"], None, "documented in")
    elif subject == "TaskRequirement":
        for r in _rows(db, "SELECT * FROM task_requirement WHERE id=?", key):
            add("TaskRequirement.taskRequirementIdentifier", r["id"], r["source_id"])
            add("TaskRequirementRevision.taskRequirementDescription", r["description"], r["source_id"])
            add("BreakdownElement.breakdownElementIdentifier", r["bei"], r["source_id"], "requirement on")
        for t in _rows(db, "SELECT task_id FROM task_covers WHERE requirement_id=?", key):
            add("Task.taskIdentifier", t["task_id"], None, "covered by")
    elif subject == "Organization":
        orgs = _rows(db, "SELECT o.* FROM organization o LEFT JOIN organization_code c ON c.organization_id=o.id WHERE o.id=? OR c.code=?", key, key)
        for o in orgs:
            add("Organization.organizationIdentifier", o["id"], o["source_id"])
            add("Organization.organizationName", o["name"], o["source_id"])
        for p in _rows(db, "SELECT part_number, source_id FROM part WHERE manufacturer_code=? LIMIT 50", key):
            add("PartAsDesigned.partIdentifier", p["part_number"], p["source_id"], "manufactures")
    elif subject == "Document":
        for d in _rows(db, "SELECT * FROM information_item WHERE dmc=?", key):
            add("Document.documentIdentifier", d["dmc"], d["source_id"])
            add("Document.documentTitle", d["title"], d["source_id"])
            add("BreakdownElement.breakdownElementIdentifier", d["bei"], d["source_id"], "about")
        for l in _rows(db, "SELECT target_kind, target_id FROM information_link WHERE dmc=?", key):
            term = {"task": "Task.taskIdentifier", "part": "PartAsDesigned.partIdentifier",
                    "breakdown": "BreakdownElement.breakdownElementIdentifier", "requirement": "TaskRequirement.taskRequirementIdentifier"}.get(l["target_kind"])
            if term:
                add(term, l["target_id"], None, "documents")
    elif subject == "Product":
        for p in _rows(db, "SELECT * FROM product WHERE id=?", key):
            add("Product.productIdentifier", p["id"], p["source_id"])
            add("Product.productName", p["name"], p["source_id"])
    keys = [key]
    if subject == "Part" and "|" not in key:          # a part number without CAGE: every CAGE's facts
        keys += [r["subject_key"] for r in _rows(db, "SELECT DISTINCT subject_key FROM xr_fact WHERE subject='Part' AND subject_key LIKE ?", key + "|%")]
    elif subject == "Part":                           # facts written without the CAGE belong to it too
        keys.append(key.split("|")[0])
    for f in [r for k in keys for r in _rows(db, "SELECT * FROM xr_fact WHERE subject=? AND subject_key=?", subject, k)]:
        add(f["term"], f["value"], f["source_id"], f["context"] or "")
    return out


def find_subjects(db, q: str, limit: int = 40) -> list[dict]:
    """Items to look at: parts, breakdown elements, tasks … whose key or name matches."""
    like = f"%{q.strip()}%"
    out = []
    for r in _rows(db, """SELECT part_number, manufacturer_code, MAX(name) AS name FROM part WHERE part_number LIKE ? OR name LIKE ?
                           GROUP BY part_number_key, manufacturer_code LIMIT ?""", like, like, limit):
        out.append({"subject": "Part", "key": f"{r['part_number']}|{r['manufacturer_code']}" if r["manufacturer_code"] else r["part_number"],
                    "label": r["part_number"], "name": r["name"], "detail": r["manufacturer_code"]})
    for r in _rows(db, "SELECT bei, name FROM breakdown_element WHERE bei LIKE ? OR name LIKE ? GROUP BY bei LIMIT ?", like, like, limit):
        out.append({"subject": "BreakdownElement", "key": r["bei"], "label": r["bei"], "name": r["name"]})
    for r in _rows(db, "SELECT id, name FROM task WHERE id LIKE ? OR name LIKE ? GROUP BY id LIMIT ?", like, like, limit):
        out.append({"subject": "Task", "key": r["id"], "label": r["id"], "name": r["name"]})
    for r in _rows(db, "SELECT id, description FROM task_requirement WHERE id LIKE ? OR description LIKE ? LIMIT ?", like, like, limit):
        out.append({"subject": "TaskRequirement", "key": r["id"], "label": r["id"], "name": r["description"]})
    for r in _rows(db, "SELECT id, name FROM organization WHERE id LIKE ? OR name LIKE ? LIMIT ?", like, like, limit):
        out.append({"subject": "Organization", "key": r["id"], "label": r["id"], "name": r["name"]})
    for r in _rows(db, "SELECT dmc, MAX(title) AS title FROM information_item WHERE dmc LIKE ? OR title LIKE ? GROUP BY dmc LIMIT ?", like, like, limit):
        out.append({"subject": "Document", "key": r["dmc"], "label": r["dmc"], "name": r["title"]})
    seen = {(o["subject"], o["key"]) for o in out}
    for r in _rows(db, "SELECT subject, subject_key, MAX(value) AS v FROM xr_fact WHERE subject_key LIKE ? OR value LIKE ? GROUP BY subject, subject_key LIMIT ?",
                   like, like, limit):
        if (r["subject"], r["subject_key"]) not in seen:
            out.append({"subject": r["subject"], "key": r["subject_key"], "label": r["subject_key"].split("|")[0], "name": ""})
    return out[: limit * 2]


# ------------------------------------------------------------------ any S-Series document, through its data model
def _local(el) -> str:
    return etree.QName(el).localname if isinstance(el.tag, str) else ""


def _value(el, path: str, strict: bool = False) -> str | None:
    """Text at a relative path of XML names ("partId/id"), tolerating a missing component level (not strict)."""
    cur = el
    steps = [s for s in path.split("/") if s]
    for i, s in enumerate(steps):
        nxt = next((c for c in cur if _local(c) == s), None)
        if nxt is None:
            if s and cur.get(s) is not None:
                return cur.get(s)
            if not strict and i == len(steps) - 1 and i > 0 and not any(isinstance(c.tag, str) for c in cur):
                break                                  # "partId" holding the text directly
            return None
        cur = nxt
    t = " ".join("".join(cur.itertext()).split())
    return t or None


# the key term that makes an element an item of its own (and which kind)
SUBJECT_KEYS = {"PartAsDesigned.partIdentifier": "Part", "BreakdownElement.breakdownElementIdentifier": "BreakdownElement",
                "Task.taskIdentifier": "Task", "TaskRequirement.taskRequirementIdentifier": "TaskRequirement",
                "Organization.organizationIdentifier": "Organization", "Document.documentIdentifier": "Document",
                "Product.productIdentifier": "Product"}


def tag_index(vocab, label: str) -> dict[str, list[tuple[str, str]]]:
    """class XML name -> [(term, path below the class element)] for one specification's column."""
    idx: dict[str, list[tuple[str, str]]] = {}
    for tid, t in vocab.terms.items():
        n = t["names"].get(label)
        if not n or not n.get("path") or "/" not in n["path"] or not n.get("class_tag"):
            continue
        if t.get("same_as"):                         # read under the ASTHRA term it equals (S2000M figure item)
            continue
        idx.setdefault(n["class_tag"], []).append((tid, n["path"].split("/", 1)[1]))
    return idx


def read_document(model: dict, vocab, root) -> list[dict]:
    """Facts from an S-Series XML document (S3000L, SX000i, S2000M … with the spec's model loaded), read through
    the vocabulary's names for that specification — including the common-model classes it only references:
    [{subject, key, term, value, context, path}]."""
    label = f"{model.get('spec')} {model.get('issue')}".strip()
    idx = tag_index(vocab, label)
    cls_of = {}
    for cname, c in sorted(model["classes"].items(), key=lambda kv: kv[1]["abstract"]):
        if c["xml"]:
            cls_of.setdefault(c["xml"], cname)
    # a subclass element (hwPart) carries its superclasses' attributes (PartAsDesigned: partId, partName)
    hub = getattr(vocab, "hub", None)

    def supers(cname, seen=()):
        c = model["classes"].get(cname) or {}
        sup = c.get("supers") or ((hub or {}).get("classes", {}).get(cname, {}).get("supers") if hub else []) or []
        for x in sup:
            if x not in seen:
                yield x
                yield from supers(x, seen + (x,))
    for tag, cname in list(cls_of.items()):
        for sup in supers(cname):
            sc = model["classes"].get(sup) or (hub or {}).get("classes", {}).get(sup) or {}
            for tid, rel in idx.get(sc.get("xml", ""), []) if sc.get("xml") != tag else []:
                if (tid, rel) not in idx.setdefault(tag, []):
                    idx[tag].append((tid, rel))
    out = []
    stack: list[tuple[str, str]] = []                 # (subject, key) of enclosing items
    pushes = [0]

    def visit(el, pending):
        """pending: values of enclosing elements that are not items themselves (an S2000M figure item around
        the part it lists), given to the first item found inside."""
        tag = _local(el)
        entries = idx.get(tag)
        pushed = False
        mine = []
        if entries:
            vals = {}
            for tid, rel in entries:
                v = _value(el, rel, strict=tid.endswith((".identifierSetBy", ".identifierClassifier")))
                if v is not None:
                    vals[tid] = v
            keyed = [t for t in vals if t in SUBJECT_KEYS]
            if not keyed and cls_of.get(tag):
                subj = subject_of_class(model, cls_of[tag])
                keyed = [t for t in vals if subj and vocab.terms.get(t, {}).get("key") and SUBJECT_KEYS.get(t, subj) == subj]
            if keyed:
                subj, key = SUBJECT_KEYS.get(keyed[0]) or subject_of_class(model, cls_of.get(tag, "")), vals[keyed[0]]
                if subj == "Part":
                    sb = vals.get(f"{keyed[0]}.identifierSetBy")
                    key = f"{key}|{sb}" if sb else key
                if subj:
                    stack.append((subj, key))
                    pushed = True
                    pushes[0] += 1
            ctx = "" if pushed else model["classes"].get(cls_of.get(tag, ""), {}).get("name", tag)
            target = stack[-1] if stack else None
            if pushed and pending:
                ctx_p = ", ".join(sorted({p[2] for p in pending}))
                for tid, v, c in pending:
                    out.append({"subject": target[0], "key": target[1], "term": tid, "value": v, "context": c or ctx_p, "path": tag})
                pending = []
            if target:
                for tid, v in vals.items():
                    out.append({"subject": target[0], "key": target[1], "term": tid, "value": v, "context": ctx, "path": tag})
            else:
                mine = [(tid, v, ctx) for tid, v in vals.items()]
            if target and pushed and len(stack) > 1:          # an item inside another: link both ways
                    parent = stack[-2]
                    out.append({"subject": parent[0], "key": parent[1], "term": keyed[0], "value": vals[keyed[0]],
                                "context": f"contains ({cls_of.get(tag, tag)})", "path": tag})
        below = pending + mine
        leftover = list(mine)
        before = pushes[0]
        for c in el:
            if isinstance(c.tag, str):
                rest = visit(c, below)
                below = below + rest                    # a sibling's values (figReaContxt) reach the part beside it
                leftover += rest
        if pushed:
            stack.pop()
        if pushed or pushes[0] > before:                # given to an item in here: they go no further
            return []
        return leftover

    visit(root, [])
    return out


def store_document_facts(db, facts: list[dict], source_id: int) -> int:
    db.executemany("INSERT INTO xr_fact(subject, subject_key, term, value, context, source_id, path) VALUES (?,?,?,?,?,?,?)",
                   [(f["subject"], f["key"], f["term"], f["value"], f["context"], source_id, f["path"]) for f in facts])
    db.commit()
    return len(facts)
