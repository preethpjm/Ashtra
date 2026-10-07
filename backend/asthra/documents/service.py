"""Document import and validation (Milestone 1).

Import never modifies the original: bytes go into the project's immutable,
content-addressed store; everything else refers to them by SHA-256.
"""
from __future__ import annotations

import codecs
import json
import re
import uuid
from pathlib import Path

from ..identify.service import identify, parse_xml, sniff
from ..projects.service import ProjectService, now
from ..registry.service import SchemaRegistry
from ..standards.registry import adapter_for
from ..security.hashing import sha256_bytes
from ..security.paths import make_read_only
from ..storage.blobs import ImmutableStore, atomic_write
from ..storage.db import Database
from ..validation.model import Stage, Status, ValidationReport
from .outline import build_outline
from ..validation.pipeline import validate_bytes


_DECL_ENC = re.compile(r"""^<\?xml[^>]*?encoding\s*=\s*["']([A-Za-z0-9._-]+)["']""")


class DocumentError(Exception):
    pass


class DocumentService:
    def __init__(self, db: Database, projects: ProjectService, registry: SchemaRegistry, max_bytes: int):
        self.db, self.projects, self.registry, self.max_bytes = db, projects, registry, max_bytes

    def _store(self, project_id: str) -> ImmutableStore:
        return ImmutableStore(Path(self.projects.get(project_id)["root_path"]))

    # ------------------------------------------------------------------ import
    def import_bytes(self, project_id: str, filename: str, data: bytes,
                     package_id: str | None = None, doc_type_id: str | None = None) -> dict:
        self.projects.get(project_id)
        safe_name = Path(filename).name or "unnamed"
        if len(data) > self.max_bytes:
            raise DocumentError("file exceeds the configured import limit")
        digest, rel = self._store(project_id).put(data)

        existing = self.db.one("SELECT id FROM source_file WHERE project_id=? AND sha256=?", (project_id, digest))
        src_id = existing["id"] if existing else uuid.uuid4().hex

        sn = sniff(data)
        tree, _ = parse_xml(data) if sn.syntax_hint != "sgml" else (None, [])
        ident = identify(tree.getroot() if tree is not None else None, self.registry.list(False), sn, data)

        chosen_pkg, chosen_dt = package_id, doc_type_id
        if chosen_pkg or chosen_dt:
            if not (chosen_pkg and chosen_dt):
                raise DocumentError("explicit selection needs both package_id and doc_type_id")
            _, _pkg, _dt = self.registry.schema_for(chosen_pkg, chosen_dt)  # raises if unknown/disabled
            from ..identify.service import root_fits
            if tree is None or not root_fits(_dt, tree.getroot()):
                raise DocumentError(f"{_dt.label} does not fit this document's root element")
            ident.notes.append(f"Schema selected explicitly by user: {chosen_pkg} / {chosen_dt}")
        elif ident.chosen:
            chosen_pkg, chosen_dt = ident.chosen.package_id, ident.chosen.doc_type

        standard = issue = None
        identity: dict = {}
        if chosen_pkg:
            pkg = self.registry.get(chosen_pkg)
            standard, issue = pkg.manifest.standard, pkg.manifest.issue
            dt = next(d for d in pkg.manifest.doc_types if d.id == chosen_dt)
            adapter = adapter_for(standard)
            if adapter and tree is not None:
                di = adapter.extract_identity(tree.getroot(), pkg.manifest, dt)
                identity = {"fields": di.fields, "display": di.display, "warnings": di.warnings}

        doc_id = uuid.uuid4().hex
        with self.db.tx() as c:
            if not existing:
                c.execute("INSERT INTO source_file VALUES (?,?,?,?,?,?,?)",
                          (src_id, project_id, safe_name, digest, len(data), str(rel), now()))
            c.execute("INSERT INTO document VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (doc_id, project_id, src_id, ident.syntax, standard, issue, chosen_dt, chosen_pkg,
                       json.dumps(identity), json.dumps(ident.as_dict()), now()))
            c.execute("INSERT INTO audit_event(at,actor,action,subject,detail_json) VALUES (?,?,?,?,?)",
                      (now(), "local", "document.import", doc_id,
                       json.dumps({"sha256": digest, "name": safe_name})))
        return self.get(doc_id)

    def import_path(self, project_id: str, path: Path, **kw) -> dict:
        return self.import_bytes(project_id, path.name, path.read_bytes(), **kw)

    # ------------------------------------------------------------------ read
    def get(self, doc_id: str) -> dict:
        r = self.db.one("""SELECT d.*, s.original_name, s.sha256, s.size_bytes, s.blob_path
                           FROM document d JOIN source_file s ON s.id=d.source_file_id WHERE d.id=?""", (doc_id,))
        if not r:
            raise DocumentError(f"no such document: {doc_id}")
        d = dict(r)
        d["identity"] = json.loads(d.pop("identity_json"))
        d["identification"] = json.loads(d.pop("identification_json"))
        last = self.db.one("SELECT * FROM validation_run WHERE document_id=? ORDER BY started_at DESC LIMIT 1",
                           (doc_id,))
        d["last_validation"] = dict(last) if last else None
        d["has_working_copy"] = bool(self.db.one("SELECT 1 FROM working_copy WHERE document_id=?", (doc_id,)))
        d["revision_count"] = self.db.one("SELECT COUNT(*) n FROM revision WHERE document_id=?", (doc_id,))["n"]
        return d

    def list(self, project_id: str) -> list[dict]:
        return [self.get(r["id"]) for r in
                self.db.query("SELECT id FROM document WHERE project_id=? ORDER BY created_at", (project_id,))]

    def original_bytes(self, doc_id: str) -> bytes:
        d = self.get(doc_id)
        store = self._store(d["project_id"])
        return store.get(Path(d["blob_path"]), d["sha256"])   # verifies SHA-256 on every read

    # ------------------------------------------------------------------ current content
    def _root(self, doc_id: str) -> tuple[dict, Path]:
        d = self.get(doc_id)
        return d, Path(self.projects.get(d["project_id"])["root_path"])

    def current_bytes(self, doc_id: str) -> tuple[bytes, str]:
        """Working copy if one exists, otherwise the immutable original."""
        wc = self.db.one("SELECT * FROM working_copy WHERE document_id=?", (doc_id,))
        if wc:
            _, root = self._root(doc_id)
            data = (root / wc["rel_path"]).read_bytes()
            if sha256_bytes(data) != wc["sha256"]:
                raise IOError("working copy was modified outside ASTHRA (checksum mismatch)")
            return data, "working"
        return self.original_bytes(doc_id), "original"

    @staticmethod
    def decode(data: bytes) -> str:
        return data.decode(sniff(data).encoding or "utf-8", errors="replace")

    @staticmethod
    def encode(text: str) -> bytes:
        """Encode using the document's own XML declaration (default UTF-8)."""
        m = _DECL_ENC.match(text.lstrip("\ufeff").lstrip())
        enc = (m.group(1) if m else "utf-8").lower()
        try:
            codecs.lookup(enc)
        except LookupError as e:
            raise DocumentError(f"unknown encoding in XML declaration: {enc}") from e
        text = text.lstrip("\ufeff")
        try:
            return text.encode("utf-16" if enc in ("utf-16", "utf16") else enc)
        except UnicodeEncodeError as e:
            raise DocumentError(f"text contains characters that cannot be written as {enc}: {e.reason}") from e

    def source_text(self, doc_id: str) -> str:
        return self.decode(self.current_bytes(doc_id)[0])

    def reidentify(self, doc_id: str) -> dict:
        """Identify again against the schemas installed now (a document imported before its
        schema package was installed would otherwise keep its old result). A schema the
        user chose is never overridden."""
        d = self.get(doc_id)
        ident0 = d["identification"]
        if ident0.get("selection") == "user" or (d["package_id"] and ident0.get("status") == "identified"):
            return d
        data, _ = self.current_bytes(doc_id)
        sn = sniff(data)
        tree, _ = parse_xml(data) if sn.syntax_hint != "sgml" else (None, [])
        ident = identify(tree.getroot() if tree is not None else None, self.registry.list(False), sn, data)
        new = ident.as_dict()
        if new["status"] == ident0.get("status") and new["candidates"] == ident0.get("candidates") \
                and new.get("compatible") == ident0.get("compatible"):
            return d
        pkg_id = doc_type = standard = issue = None
        identity: dict = {}
        if ident.chosen:
            pkg_id, doc_type = ident.chosen.package_id, ident.chosen.doc_type
            pkg = self.registry.get(pkg_id)
            standard, issue = pkg.manifest.standard, pkg.manifest.issue
            dt = next(x for x in pkg.manifest.doc_types if x.id == doc_type)
            adapter = adapter_for(standard)
            if adapter and tree is not None:
                di = adapter.extract_identity(tree.getroot(), pkg.manifest, dt)
                identity = {"fields": di.fields, "display": di.display, "warnings": di.warnings}
            new["notes"].append("Identified again after schema packages changed.")
        with self.db.tx() as c:
            c.execute("""UPDATE document SET package_id=?, standard=?, issue=?, doc_type=?, identity_json=?,
                         identification_json=? WHERE id=?""",
                      (pkg_id, standard, issue, doc_type, json.dumps(identity), json.dumps(new), doc_id))
        return self.get(doc_id)

    def state(self, doc_id: str) -> dict:
        self.reidentify(doc_id)
        d = self.get(doc_id)
        data, origin = self.current_bytes(doc_id)
        wc = self.db.one("SELECT * FROM working_copy WHERE document_id=?", (doc_id,))
        return {"document": d, "origin": origin, "text": self.decode(data),
                "working_updated_at": wc["updated_at"] if wc else None,
                "revisions": self.revisions(doc_id), "render": self.render_profile(d)}

    def render_profile(self, d: dict) -> dict:
        from ..render.profiles import resolve
        overrides = {}
        if d.get("package_id"):
            try:
                overrides = self.registry.get(d["package_id"]).manifest.render_roles
            except Exception:
                overrides = {}
        root = (d.get("identification") or {}).get("root", {}).get("local_name")
        return resolve(d.get("standard"), root, overrides)

    # ------------------------------------------------------------------ schema choice
    def schema_options(self, doc_id: str) -> list[dict]:
        """Installed doc types whose root element fits this document (exact or not)."""
        from ..identify.service import declares, identify_sgml, root_fits
        data = self.current_bytes(doc_id)[0]
        tree, _ = parse_xml(data)
        if tree is None:
            sn = sniff(data)
            if not sn.doctype_name:
                return []
            ident = identify_sgml(data.decode(sn.encoding or "utf-8", errors="replace"), self.registry.list(False))
            out = []
            for c, declared in [(c, True) for c in ident.candidates] + [(c, False) for c in ident.compatible]:
                pkg = self.registry.get(c.package_id)
                dt = next(d for d in pkg.manifest.doc_types if d.id == c.doc_type)
                out.append({"package_id": c.package_id, "doc_type": c.doc_type, "label": dt.label,
                            "standard": pkg.manifest.standard, "issue": pkg.manifest.issue,
                            "provenance": pkg.manifest.provenance, "declared": declared})
            return out
        out = []
        for pkg in self.registry.list(include_disabled=False):
            for dt in pkg.manifest.doc_types:
                if root_fits(dt, tree.getroot()):
                    out.append({"package_id": pkg.manifest.key, "doc_type": dt.id, "label": dt.label,
                                "standard": pkg.manifest.standard, "issue": pkg.manifest.issue,
                                "provenance": pkg.manifest.provenance, "declared": declares(dt, tree.getroot(), pkg.manifest.standard, pkg.manifest.issue)})
        return out

    def choose_schema(self, doc_id: str, package_id: str, doc_type_id: str) -> dict:
        """Validate this document against a schema the user picks. Refused if the schema's
        root element does not fit; otherwise recorded, and every validation says so."""
        from ..identify.service import declares, root_fits
        d = self.get(doc_id)
        _, pkg, dt = self.registry.schema_for(package_id, doc_type_id)
        data = self.current_bytes(doc_id)[0]
        tree, _ = parse_xml(data)
        if tree is None and dt.schema_kind == "sgml":
            sn = sniff(data)
            if not sn.doctype_name or sn.doctype_name.lower() != dt.match.local_name.lower():
                raise DocumentError(f"{dt.label} is for DOCTYPE <{dt.match.local_name}>; this document's DOCTYPE is <{sn.doctype_name}>")
            ident = d["identification"]
            ident.setdefault("notes", []).append(f"Schema chosen by user: {pkg.manifest.standard} {pkg.manifest.issue} / {dt.label}")
            ident["selection"] = "user"
            with self.db.tx() as c:
                c.execute("""UPDATE document SET package_id=?, standard=?, issue=?, doc_type=?, identity_json='{}',
                             identification_json=? WHERE id=?""",
                          (package_id, pkg.manifest.standard, pkg.manifest.issue, dt.id, json.dumps(ident), doc_id))
                c.execute("INSERT INTO audit_event(at,actor,action,subject,detail_json) VALUES (?,?,?,?,?)",
                          (now(), "local", "document.schema.choose", doc_id,
                           json.dumps({"package_id": package_id, "doc_type": doc_type_id})))
            return self.get(doc_id)
        if tree is None:
            from ..identify.service import recover_root
            rec = recover_root(data) if data is not None else None
            if rec is None:
                raise DocumentError("the document is not well-formed XML and nothing of it can be read; fix it first")
            tree = rec.getroottree()             # not well-formed: choose from the part that can be read
        if not root_fits(dt, tree.getroot()):
            raise DocumentError(f"{dt.label} ({pkg.manifest.standard} {pkg.manifest.issue}) is for <{dt.match.local_name}>"
                                f"{' with ' + dt.discriminator if dt.discriminator else ''}; this document does not fit it")
        identity = {}
        adapter = adapter_for(pkg.manifest.standard)
        if adapter:
            di = adapter.extract_identity(tree.getroot(), pkg.manifest, dt)
            identity = {"fields": di.fields, "display": di.display, "warnings": di.warnings}
        ident = d["identification"]
        ident.setdefault("notes", []).append(
            f"Schema chosen by user: {pkg.manifest.standard} {pkg.manifest.issue} / {dt.label}"
            + ("" if declares(dt, tree.getroot(), pkg.manifest.standard, pkg.manifest.issue) else " (the document does not declare this schema)"))
        ident["selection"] = "user"
        with self.db.tx() as c:
            c.execute("""UPDATE document SET package_id=?, standard=?, issue=?, doc_type=?, identity_json=?,
                         identification_json=? WHERE id=?""",
                      (package_id, pkg.manifest.standard, pkg.manifest.issue, dt.id, json.dumps(identity),
                       json.dumps(ident), doc_id))
            c.execute("INSERT INTO audit_event(at,actor,action,subject,detail_json) VALUES (?,?,?,?,?)",
                      (now(), "local", "document.schema.choose", doc_id,
                       json.dumps({"package_id": package_id, "doc_type": doc_type_id})))
        return self.get(doc_id)

    # ------------------------------------------------------------------ check / save
    def check_text(self, doc_id: str, text: str) -> dict:
        """Validate candidate text without persisting anything."""
        d = self.get(doc_id)
        data = self.encode(text)
        rep, tree = validate_bytes(data, d["original_name"], self.registry, d["package_id"], d["doc_type"],
                                   self.max_bytes)
        rep.document_id = doc_id
        outline = None
        if tree is not None:
            outline = build_outline(tree.getroot())
        elif rep.rendered_xml:
            from lxml import etree as _et
            try:
                outline = build_outline(_et.fromstring(rep.rendered_xml.encode("utf-8"), _et.XMLParser(resolve_entities=False, no_network=True)))
            except _et.XMLSyntaxError:
                outline = None
        return {"report": _report_json(rep), "outline": outline}

    def save_working(self, doc_id: str, text: str) -> dict:
        d, root = self._root(doc_id)
        data = self.encode(text)
        rel = Path("working") / f"{doc_id}.xml"
        atomic_write(root / rel, data)
        with self.db.tx() as c:
            c.execute("""INSERT INTO working_copy(document_id, rel_path, sha256, updated_at) VALUES (?,?,?,?)
                         ON CONFLICT(document_id) DO UPDATE SET rel_path=excluded.rel_path,
                         sha256=excluded.sha256, updated_at=excluded.updated_at""",
                      (doc_id, str(rel), sha256_bytes(data), now()))
        return self.check_text(doc_id, text)

    def discard_working(self, doc_id: str) -> None:
        d, root = self._root(doc_id)
        wc = self.db.one("SELECT * FROM working_copy WHERE document_id=?", (doc_id,))
        if not wc:
            return
        with self.db.tx() as c:
            c.execute("DELETE FROM working_copy WHERE document_id=?", (doc_id,))
        try:
            (root / wc["rel_path"]).unlink()
        except FileNotFoundError:
            pass

    def outline(self, doc_id: str) -> dict | None:
        from ..identify.service import parse_xml
        tree, _ = parse_xml(self.current_bytes(doc_id)[0])
        return build_outline(tree.getroot()) if tree is not None else None

    # ------------------------------------------------------------------ validate
    def validate(self, doc_id: str) -> ValidationReport:
        """Full validation of the current content (working copy or original), persisted."""
        d = self.get(doc_id)
        data, _ = self.current_bytes(doc_id)
        rep, _ = validate_bytes(data, d["original_name"], self.registry, d["package_id"], d["doc_type"],
                                self.max_bytes)
        rep.document_id = doc_id
        self._persist(doc_id, rep)
        return rep

    def _persist(self, doc_id: str, rep: ValidationReport) -> str:
        run_id = uuid.uuid4().hex
        st = rep.statuses()
        with self.db.tx() as c:
            c.execute("INSERT INTO validation_run VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (run_id, doc_id, rep.package_id, rep.package_checksum, now(), st["structural"],
                       st["business_rules"], st["references"], st["engineering"],
                       json.dumps({"counts": rep.counts(), "stages": [s.model_dump(mode="json") for s in rep.stages]})))
            for dg in rep.diagnostics:
                c.execute("""INSERT INTO diagnostic(run_id,stage,severity,rule_id,source_file,element_path,line,col,
                             message,suggestion,reference) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                          (run_id, int(dg.stage), dg.severity.value, dg.rule_id, dg.source_file, dg.element_path,
                           dg.line, dg.column, dg.message, dg.suggestion, dg.reference))
        rep.__dict__["run_id"] = run_id
        return run_id

    def validation_history(self, doc_id: str) -> list[dict]:
        return [dict(r) for r in self.db.query(
            "SELECT * FROM validation_run WHERE document_id=? ORDER BY started_at DESC", (doc_id,))]

    # ------------------------------------------------------------------ revisions
    def revisions(self, doc_id: str) -> list[dict]:
        return [dict(r) for r in self.db.query(
            "SELECT * FROM revision WHERE document_id=? ORDER BY number DESC", (doc_id,))]

    def commit_revision(self, doc_id: str, message: str = "") -> dict:
        """Validate current content and store it as a new immutable revision.
        Documents that are not well-formed cannot be committed; schema errors are
        allowed but recorded on the revision, never hidden."""
        d, root = self._root(doc_id)
        data, _ = self.current_bytes(doc_id)
        rep, _ = validate_bytes(data, d["original_name"], self.registry, d["package_id"], d["doc_type"],
                                self.max_bytes)
        rep.document_id = doc_id
        if any(s.stage <= Stage.PARSE and s.status == Status.FAILED for s in rep.stages):
            raise DocumentError("cannot commit: the document is not well-formed XML. Fix the errors shown first.")
        run_id = self._persist(doc_id, rep)
        prev = self.db.one("SELECT id, number FROM revision WHERE document_id=? ORDER BY number DESC LIMIT 1",
                           (doc_id,))
        number = (prev["number"] + 1) if prev else 1
        rel = Path("revisions") / doc_id / f"{number:04d}.xml"
        full = root / rel
        if full.exists():
            raise DocumentError(f"revision file already exists: {rel}")
        atomic_write(full, data)
        make_read_only(full)
        rid = uuid.uuid4().hex
        with self.db.tx() as c:
            c.execute("INSERT INTO revision VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (rid, doc_id, number, prev["id"] if prev else None, str(rel), sha256_bytes(data),
                       message.strip()[:500], rep.structural_status.value, run_id, now()))
            c.execute("UPDATE working_copy SET based_on_revision=? WHERE document_id=?", (rid, doc_id))
            c.execute("INSERT INTO audit_event(at,actor,action,subject,detail_json) VALUES (?,?,?,?,?)",
                      (now(), "local", "revision.commit", doc_id, json.dumps({"number": number})))
        return dict(self.db.one("SELECT * FROM revision WHERE id=?", (rid,)))

    def revision_bytes(self, doc_id: str, rev_id: str) -> tuple[dict, bytes]:
        r = self.db.one("SELECT * FROM revision WHERE id=? AND document_id=?", (rev_id, doc_id))
        if not r:
            raise DocumentError("no such revision")
        _, root = self._root(doc_id)
        data = (root / r["rel_path"]).read_bytes()
        if sha256_bytes(data) != r["sha256"]:
            raise IOError(f"integrity failure: revision {r['number']} does not match its SHA-256")
        return dict(r), data

    def restore_revision(self, doc_id: str, rev_id: str) -> dict:
        _, data = self.revision_bytes(doc_id, rev_id)
        return self.save_working(doc_id, self.decode(data))


def _report_json(rep: ValidationReport) -> dict:
    return {"statuses": rep.statuses(), "counts": rep.counts(), **rep.model_dump(mode="json")}
