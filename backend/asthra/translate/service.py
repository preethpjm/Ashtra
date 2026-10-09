"""The translator as the application uses it: bindings proposed from the installed schemas and saved once
confirmed, parts lists built from engineering data or from another standard's parts list, and written into a
document of the project as a new, validated document."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import PurePosixPath

from . import schema_graph as g
from .concepts import CONCEPTS
from .extract import extract, to_library
from .generate import generate
from .propose import candidates, propose
from .records import DEFAULT_RULES, assemblies, from_catalogue, from_engineering, parts_lists, rules_with_defaults
from .values import FORMATS


class TranslateError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def check_binding(model: dict, b: dict) -> list[str]:
    """Problems with a (user-edited) binding against the schema."""
    out = []
    rec = b.get("record")
    if not rec or rec not in model["elements"]:
        return [f"The record element “{rec}” is not in this schema."]
    cont = b.get("container") or []
    if not cont or cont[0] != model["root"]:
        out.append(f"The path to the records must start at the document's root element <{model['root']}>.")
    for a, c in zip(cont, cont[1:] + [rec]):
        if c not in g.order(model, a):
            out.append(f"<{c}> cannot be inside <{a}> in this schema.")
            break
    paths = {s["path"] for s in g.slots(model, rec)}
    for f, spec in (b.get("fields") or {}).items():
        if spec.get("path") and spec["path"] not in paths:
            out.append(f"{CONCEPTS[b.get('concept', 'parts_list')]['fields'].get(f, (f,))[0]}: “{spec['path']}” is not a place "
                       f"in <{rec}> this schema allows.")
        if spec.get("format") and spec["format"] not in FORMATS:
            out.append(f"{f}: unknown format “{spec['format']}”.")
    grp = b.get("group")
    if grp:
        if not (0 <= int(grp.get("level", -1)) < len(cont)) or cont[int(grp["level"])] != grp.get("element"):
            out.append("The figure number's element is not on the path to the records.")
        elif grp.get("attr") not in [a["name"] for a in g.attrs(model, grp["element"])]:
            out.append(f"<{grp.get('element')}> has no attribute “{grp.get('attr')}”.")
    for need in ("part_number",):
        if need not in (b.get("fields") or {}):
            out.append("A binding needs at least the part number.")
    return out


class TranslateService:
    def __init__(self, registry, documents, projects, knowledge):
        self.registry, self.documents, self.projects, self.k = registry, documents, projects, knowledge

    @property
    def db(self):
        return self.k.store.db

    # ------------------------------------------------------------------ concepts and bindings
    def concepts(self) -> list[dict]:
        return [{"id": c["id"], "label": c["label"], "fields": [{"id": f, "label": v[0]} for f, v in c["fields"].items()]}
                for c in CONCEPTS.values()]

    def _model(self, package_id: str, doc_type: str) -> dict:
        try:
            return self.registry.schema_model(package_id, doc_type)
        except Exception as e:                                   # noqa: BLE001 - shown to the user
            raise TranslateError(f"The schema of {package_id} / {doc_type} could not be read: {e}") from e

    def saved_binding(self, package_id: str, doc_type: str, concept: str = "parts_list") -> dict | None:
        r = self.db.execute("SELECT json, saved_at FROM binding WHERE package_id=? AND doc_type=? AND concept=?",
                            (package_id, doc_type, concept)).fetchone()
        return {**json.loads(r["json"]), "saved_at": r["saved_at"]} if r else None

    def binding(self, package_id: str, doc_type: str, concept: str = "parts_list", record: str | None = None) -> dict:
        """The saved binding (or a fresh proposal), with what the editor needs: the record candidates, the places
        in the record a field can go, and the formats."""
        if concept not in CONCEPTS:
            raise TranslateError(f"unknown concept {concept}")
        model = self._model(package_id, doc_type)
        saved = None if record else self.saved_binding(package_id, doc_type, concept)
        b = saved or propose(model, concept, record)
        rec = b.get("record")
        cands = [{"record": c["record"], "score": c["score"], "fields": len(c["fields"])} for c in candidates(model, concept)[:8]]
        slots = g.slots(model, rec) if rec else []
        cont = b.get("container") or []
        group_options = [{"level": i, "element": e, "attr": a["name"]} for i, e in enumerate(cont) for a in g.attrs(model, e)]
        return {"package_id": package_id, "doc_type": doc_type, "binding": b, "saved": bool(saved),
                "check": check_binding(model, b) if rec else b.get("problems", []),
                "candidates": cands, "slots": slots, "group_options": group_options,
                "formats": [{"id": k, "label": v} for k, v in FORMATS.items()], "concept": next(c for c in self.concepts() if c["id"] == concept), "schema_kind": model.get("kind")}

    def save_binding(self, package_id: str, doc_type: str, b: dict) -> dict:
        concept = b.get("concept") or "parts_list"
        model = self._model(package_id, doc_type)
        b = {k: v for k, v in b.items() if k in ("concept", "root", "record", "container", "group", "fields", "constants")}
        b["concept"] = concept
        b["fields"] = {f: {k: v for k, v in s.items() if k in ("path", "format", "confidence")}
                       for f, s in (b.get("fields") or {}).items() if s and s.get("path")}
        problems = check_binding(model, b)
        if problems:
            raise TranslateError(" ".join(problems))
        with self.k.lock:
            self.db.execute("""INSERT INTO binding(package_id, doc_type, concept, json, saved_at) VALUES (?,?,?,?,?)
                               ON CONFLICT(package_id, doc_type, concept) DO UPDATE SET json=excluded.json, saved_at=excluded.saved_at""",
                            (package_id, doc_type, concept, json.dumps(b), _now()))
            self.db.commit()
        return self.binding(package_id, doc_type, concept)

    def forget_binding(self, package_id: str, doc_type: str, concept: str = "parts_list") -> None:
        with self.k.lock:
            self.db.execute("DELETE FROM binding WHERE package_id=? AND doc_type=? AND concept=?", (package_id, doc_type, concept))
            self.db.commit()

    def bindings(self) -> list[dict]:
        return [{"package_id": r["package_id"], "doc_type": r["doc_type"], "concept": r["concept"], "saved_at": r["saved_at"],
                 "record": json.loads(r["json"]).get("record")}
                for r in self.db.execute("SELECT * FROM binding ORDER BY package_id, doc_type")]

    # ------------------------------------------------------------------ schemas a parts list can be written to
    def schemas(self) -> list[dict]:
        out = []
        for p in self.registry.list():
            for d in p.manifest.doc_types:
                row = {"package_id": p.manifest.key, "doc_type": d.id, "label": d.label, "standard": p.manifest.standard,
                       "issue": p.manifest.issue, "saved": bool(self.saved_binding(p.manifest.key, d.id))}
                try:
                    c = candidates(self._model(p.manifest.key, d.id))
                    row["record"] = c[0]["record"] if c else None
                except TranslateError as e:
                    row["record"], row["error"] = None, str(e)
                out.append(row)
        return out

    # ------------------------------------------------------------------ rules and sources
    def rules(self) -> dict:
        r = self.db.execute("SELECT json FROM translate_setting WHERE key='rules'").fetchone()
        return rules_with_defaults(json.loads(r["json"]) if r else None)

    def save_rules(self, rules: dict) -> dict:
        clean = {k: rules[k] for k in DEFAULT_RULES if k in rules}
        with self.k.lock:
            self.db.execute("INSERT OR REPLACE INTO translate_setting(key, json) VALUES ('rules', ?)", (json.dumps(clean),))
            self.db.commit()
        return self.rules()

    def sources(self) -> dict:
        with self.k.lock:
            return {"assemblies": assemblies(self.db), "parts_lists": parts_lists(self.db)}

    def records(self, source: dict, rules: dict | None) -> dict:
        rules = rules_with_defaults(rules if rules is not None else self.rules())
        with self.k.lock:
            if source.get("kind") == "engineering":
                tops = [t for t in source.get("tops") or [] if t]
                if not tops:
                    raise TranslateError("Choose the assembly (or assemblies) the parts list is of.")
                try:
                    recs, excluded = from_engineering(self.db, tops, rules)
                except ValueError as e:
                    raise TranslateError(str(e)) from e
            elif source.get("kind") == "catalogue":
                recs, excluded = from_catalogue(self.db, int(source["source_id"]), str(source.get("figure") or "")), []
                if source.get("renumber_figure"):
                    recs = [dict(r, figure=rules["figure"]) for r in recs]
            else:
                raise TranslateError("Choose where the parts list comes from.")
        if not recs:
            raise TranslateError("The source has no lines.")
        return {"records": recs, "excluded": excluded, "rules": rules}

    # ------------------------------------------------------------------ generate
    def targets(self, project_id: str) -> list[dict]:
        out = []
        for d in self.documents.list(project_id):
            if not d.get("package_id") or d.get("syntax") not in ("xml", "sgml"):
                continue
            out.append({"id": d["id"], "name": d["original_name"], "package_id": d["package_id"], "doc_type": d["doc_type"],
                        "syntax": d["syntax"], "standard": d.get("standard"),
                        "saved": bool(self.saved_binding(d["package_id"], d["doc_type"]))})
        return out

    def generate(self, doc_id: str, source: dict, rules: dict | None = None, binding: dict | None = None,
                 save: bool = True) -> dict:
        d = self.documents.get(doc_id)
        if not d.get("package_id"):
            raise TranslateError("The document has no schema: choose its schema first.")
        model = self._model(d["package_id"], d["doc_type"])
        b = binding or self.saved_binding(d["package_id"], d["doc_type"]) or propose(model)
        problems = check_binding(model, b) if b.get("record") else (b.get("problems") or ["No parts list in this schema."])
        if problems:
            raise TranslateError(" ".join(problems))
        got = self.records(source, rules)
        text = self.documents.source_text(doc_id)
        res = generate(text, d["syntax"], model, b, got["records"], got["rules"])
        out = {"report": res["report"], "excluded": got["excluded"], "records": len(got["records"]), "document": None}
        if not res["report"]["written"] or not save:
            out["text"] = res["text"] if not save else None
            return out
        name = PurePosixPath(d["original_name"])
        stem = name.stem[:-10] if name.stem.endswith("-generated") else name.stem
        new = self.documents.import_bytes(d["project_id"], f"{stem}-generated{name.suffix}", self.documents.encode(res["text"]),
                                          package_id=d["package_id"], doc_type_id=d["doc_type"]) if d["syntax"] == "xml" else \
            self.documents.import_bytes(d["project_id"], f"{stem}-generated{name.suffix}", self.documents.encode(res["text"]))
        if d["syntax"] == "sgml" and new.get("package_id") != d["package_id"]:
            try:
                new = self.documents.choose_schema(new["id"], d["package_id"], d["doc_type"])
            except Exception:                                    # noqa: BLE001 - reported through validation
                pass
        rep = self.documents.validate(new["id"])
        errors = [dg for dg in rep.diagnostics if dg.severity.value in ("error", "fatal")]
        out["document"] = {"id": new["id"], "name": new["original_name"], "structural": rep.structural_status.value,
                           "errors": [f"{dg.line or ''}{':' if dg.line else ''} {dg.message}".strip() for dg in errors[:20]]}
        return out

    # ------------------------------------------------------------------ read back
    def read_document(self, d: dict, root) -> dict | None:
        """Parts-list lines of a document ASTHRA has no dedicated importer for, through its saved binding."""
        if not d.get("package_id"):
            return None
        b = self.saved_binding(d["package_id"], d["doc_type"])
        if not b:
            return None
        recs = extract(root, b)
        pkg = self.registry.get(d["package_id"])
        res = to_library(self.k.store, recs, pkg.manifest.standard or d["package_id"], d.get("original_name") or d["id"],
                         schema=d["package_id"])
        res["kind"] = f"{pkg.manifest.standard} (binding)"
        return res
