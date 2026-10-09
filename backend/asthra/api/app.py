"""Local HTTP API consumed by the desktop UI. Bound to 127.0.0.1 only."""
from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import __version__
from ..app_context import AppContext
from ..config import Settings, default_settings
from ..documents.service import DocumentError
from ..projects.service import ProjectError
from ..registry.service import RegistryError
from ..standards.registry import all_adapters


class BrexSubstituteIn(BaseModel):
    named: str
    use: str


class ProjectIn(BaseModel):
    name: str
    description: str = ""


class EnableIn(BaseModel):
    enabled: bool


class TextIn(BaseModel):
    text: str


class IdsIn(BaseModel):
    ids: list[str]


class CommitIn(BaseModel):
    message: str = ""


class BuildIn(BaseModel):
    staging_id: str
    choice: dict
    replace: bool = False


class SchemaIn(BaseModel):
    package_id: str
    doc_type_id: str


# Windows registries often map .js to text/plain, which browsers refuse to run as
# module scripts (blank page). Force correct types regardless of the host OS.
import mimetypes  # noqa: E402

for _ext, _type in ((".js", "text/javascript"), (".mjs", "text/javascript"), (".css", "text/css"),
                    (".svg", "image/svg+xml"), (".ttf", "font/ttf"), (".woff2", "font/woff2"), (".json", "application/json")):
    mimetypes.add_type(_type, _ext)

WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
WRITE_HEADER = "x-asthra"
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "font-src 'self' data:; worker-src 'self' blob:; connect-src 'self' blob: data:; frame-ancestors 'none'; "
       "base-uri 'none'; form-action 'none'")


def create_app(settings: Settings | None = None) -> FastAPI:
    ctx = AppContext.open(settings or default_settings())
    app = FastAPI(title="ASTHRA local API", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.ctx = ctx
    # Only the local desktop shell / dev server may call the API.
    app.add_middleware(CORSMiddleware, allow_origin_regex=r"^(tauri://localhost|https?://(127\.0\.0\.1|localhost)(:\d+)?)$",
                       allow_methods=["*"], allow_headers=["*"])
    # DNS-rebinding protection: only loopback host names are accepted.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    @app.middleware("http")
    async def guard(request: Request, call_next):
        # CSRF protection: state-changing API calls must carry a custom header,
        # which a foreign web page cannot add without a CORS preflight we reject.
        if request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS") \
                and request.headers.get(WRITE_HEADER) != "1":
            return JSONResponse({"detail": "missing X-Asthra header"}, status_code=403)
        resp = await call_next(request)
        resp.headers.setdefault("Content-Security-Policy", CSP)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        return resp

    def fail(e: Exception, code: int = 400):
        raise HTTPException(status_code=code, detail=str(e))

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__, "network": "disabled", "ai": "not-configured"}

    @app.get("/api/standards")
    def standards():
        return [a.describe() for a in all_adapters()]

    # ---- projects
    @app.post("/api/projects", status_code=201)
    def create_project(body: ProjectIn):
        try:
            return ctx.projects.create(body.name, body.description)
        except ProjectError as e:
            fail(e)

    @app.get("/api/projects")
    def list_projects():
        return ctx.projects.list()

    @app.get("/api/projects/{pid}")
    def get_project(pid: str):
        try:
            return ctx.projects.get(pid)
        except ProjectError as e:
            fail(e, 404)

    # ---- schema registry
    @app.get("/api/registry/packages")
    def packages():
        return [{**p.summary(), "documents": ctx.registry.documents_using(p.manifest.key)} for p in ctx.registry.list()]

    @app.post("/api/registry/packages", status_code=201)
    async def install_package(file: UploadFile = File(...)):
        if not (file.filename or "").lower().endswith(".zip"):
            fail(ValueError("schema packages are uploaded as .zip"))
        with tempfile.TemporaryDirectory() as tmp:
            z = Path(tmp) / "pkg.zip"
            z.write_bytes(await file.read())
            try:
                return ctx.registry.install(z).summary()
            except RegistryError as e:
                fail(e)

    @app.get("/api/registry/packages/{key:path}/integrity")
    def integrity(key: str):
        try:
            return {"id": key, "intact": ctx.registry.verify_integrity(key)}
        except RegistryError as e:
            fail(e, 404)

    @app.post("/api/registry/packages/{key:path}/enabled")
    def enable(key: str, body: EnableIn):
        try:
            ctx.registry.set_enabled(key, body.enabled)
            return ctx.registry.get(key).summary()
        except RegistryError as e:
            fail(e, 404)

    # ---- schema installer (any folder or zip: S1000D, DTD sets, XSD sets, ASTHRA packages)
    from ..registry import installer
    from ..registry.builder import BuildError
    from ..security.paths import PathViolation, confine as _confine, safe_extract_zip
    staging_root = ctx.settings.data_root / "staging"

    @app.post("/api/registry/inspect")
    async def inspect_schemas(files: list[UploadFile] = File(...)):
        """Upload a folder (files carry their relative paths) or one .zip; get a proposal."""
        staging_root.mkdir(parents=True, exist_ok=True)
        installer.cleanup(staging_root)
        sid, src = installer.new_staging(staging_root)
        total = 0
        try:
            if len(files) == 1 and (files[0].filename or "").lower().endswith(".zip"):
                z = src.parent / "upload.zip"
                z.write_bytes(await files[0].read())
                safe_extract_zip(z, src)
            else:
                if len(files) > 20000:
                    fail(ValueError("too many files"))
                for f in files:
                    rel = (f.filename or "").replace("\\", "/").lstrip("/")
                    data = await f.read()
                    total += len(data)
                    if total > 500 * 1024 * 1024:
                        fail(ValueError("the upload is larger than 500 MB; choose the schema folder itself"))
                    if not rel or not installer.wanted(rel, len(data)):
                        continue
                    dest = _confine(src, rel)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(data)
            proposal = installer.inspect(src)
        except (BuildError, PathViolation) as e:
            fail(e)
        installed = {p.manifest.key for p in ctx.registry.list()}
        return {"staging_id": sid, "proposal": proposal, "installed": sorted(installed)}

    @app.post("/api/registry/build", status_code=201)
    def build_schemas(body: BuildIn):
        if not re.fullmatch(r"[0-9a-f]{32}", body.staging_id):
            fail(ValueError("bad staging id"))
        src = staging_root / body.staging_id / "src"
        if not src.is_dir():
            fail(ValueError("this upload has expired; add the schemas again"), 410)
        try:
            z = installer.build(src, body.choice, src.parent / "package.zip")
            try:
                pkg = ctx.registry.install(z)
                action = "installed"
            except RegistryError as e:
                if "already installed" not in str(e):
                    raise
                if not body.replace:
                    raise HTTPException(status_code=409, detail=str(e))
                pkg = ctx.registry.replace(z)
                action = "replaced"
        except (BuildError, RegistryError) as e:
            fail(e)
        brex = []
        if pkg.manifest.standard.upper() == "S1000D":
            brex = installer.install_brex_found(src, ctx.registry.brex, pkg.manifest.issue)
        installer.cleanup(staging_root)
        return {"action": action, **pkg.summary(), "brex_added": brex}

    @app.delete("/api/registry/packages/{key:path}")
    def remove_package(key: str, force: bool = False):
        try:
            return {"id": key, "unlinked_documents": ctx.registry.remove(key, force)}
        except RegistryError as e:
            fail(e, 409 if "document(s) use" in str(e) else 404)

    @app.get("/api/registry/packages/{key:path}/export")
    def export_package(key: str):
        with tempfile.TemporaryDirectory() as tmp:
            try:
                z = ctx.registry.export_package(key, Path(tmp) / "p.zip")
            except RegistryError as e:
                fail(e, 404)
            data = z.read_bytes()
        return Response(data, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{key.replace("/", "_")}.zip"'})

    @app.get("/api/registry/export-set")
    def export_set():
        with tempfile.TemporaryDirectory() as tmp:
            data = ctx.registry.export_set(Path(tmp) / "set.zip").read_bytes()
        return Response(data, media_type="application/zip",
                        headers={"Content-Disposition": 'attachment; filename="asthra-schema-set.zip"'})

    @app.post("/api/registry/import-set")
    async def import_set(file: UploadFile = File(...)):
        with tempfile.TemporaryDirectory() as tmp:
            z = Path(tmp) / "set.zip"
            z.write_bytes(await file.read())
            try:
                return {"results": ctx.registry.import_set(z)}
            except RegistryError as e:
                fail(e)

    # ---- documents
    @app.post("/api/projects/{pid}/documents", status_code=201)
    async def import_document(pid: str, file: UploadFile = File(...),
                              package_id: str | None = Form(None), doc_type_id: str | None = Form(None)):
        data = await file.read()
        try:
            return ctx.documents.import_bytes(pid, file.filename or "unnamed", data, package_id, doc_type_id)
        except (ProjectError, DocumentError, RegistryError) as e:
            fail(e)

    @app.get("/api/projects/{pid}/documents")
    def list_documents(pid: str):
        return ctx.documents.list(pid)

    @app.get("/api/documents/{did}")
    def get_document(did: str):
        try:
            return ctx.documents.get(did)
        except DocumentError as e:
            fail(e, 404)

    @app.get("/api/documents/{did}/source")
    def get_source(did: str):
        try:
            return {"id": did, "text": ctx.documents.source_text(did)}
        except (DocumentError, IOError) as e:
            fail(e, 404)

    @app.post("/api/documents/{did}/validate")
    def validate(did: str):
        try:
            rep = ctx.documents.validate(did)
        except DocumentError as e:
            fail(e, 404)
        return {"statuses": rep.statuses(), "counts": rep.counts(),
                **rep.model_dump(mode="json")}

    @app.get("/api/documents/{did}/validations")
    def history(did: str):
        return ctx.documents.validation_history(did)

    @app.post("/api/samples", status_code=201)
    def load_samples():
        """Install the synthetic S-Series test packages (if missing) and create a
        'Samples' project with every fixture document."""
        fixtures = Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures"
        if not (fixtures / "packages").is_dir():
            fail(ValueError("sample files are not included in this installation"), 404)
        installed = {p.manifest.key for p in ctx.registry.list()}
        for name in ("s1000d-synth", "s2000m-synth", "s3000l-synth"):
            m = json.loads((fixtures / "packages" / name / "asthra-package.json").read_text(encoding="utf-8"))
            key = f"{m['standard'].lower()}/{m['issue']}/{m['package_id']}"
            if key not in installed:
                ctx.registry.install(fixtures / "packages" / name)
        ata_key = "ata2200/synthetic-1/official"
        if ata_key not in installed and (fixtures / "dtd" / "ata-synth").is_dir():
            from ..registry.dtd_builder import build_dtd_package
            with tempfile.TemporaryDirectory() as tmp:
                z = Path(tmp) / "ata.zip"
                build_dtd_package(fixtures / "dtd" / "ata-synth", "ATA2200", "synthetic-1", z,
                                  name="SYNTHETIC ATA-style CMM DTD (test only)")
                ctx.registry.install(z)
        sg_key = "ata2200/synthetic-sgml-1/sgml"
        if sg_key not in installed and (fixtures / "sgml" / "ata-sgml-synth").is_dir():
            from ..registry import installer as _inst
            src = fixtures / "sgml" / "ata-sgml-synth"
            prop = _inst.inspect(src)
            prop["issue"] = "synthetic-sgml-1"
            prop["name"] = "SYNTHETIC ATA-style CMM SGML DTD (test only)"
            with tempfile.TemporaryDirectory() as tmp:
                ctx.registry.install(_inst.build(src, prop, Path(tmp) / "sg.zip"))
        proj = ctx.projects.create("Samples")
        for f in sorted((fixtures / "documents").iterdir()):
            if f.is_file():
                ctx.documents.import_path(proj["id"], f)
        for d in ctx.documents.list(proj["id"]):
            ctx.documents.validate(d["id"])
        return ctx.projects.get(proj["id"])

    # ---- editing (Milestone 2)
    docs = ctx.documents

    def guarded(fn, *a, code=400):
        try:
            return fn(*a)
        except (DocumentError, RegistryError, IOError) as e:
            fail(e, code)

    @app.get("/api/documents/{did}/state")
    def state(did: str):
        return guarded(docs.state, did, code=404)

    @app.get("/api/documents/{did}/outline")
    def outline(did: str):
        return guarded(docs.outline, did, code=404)

    @app.post("/api/documents/{did}/check")
    def check(did: str, body: TextIn):
        return guarded(docs.check_text, did, body.text)

    @app.put("/api/documents/{did}/working")
    def save_working(did: str, body: TextIn):
        return guarded(docs.save_working, did, body.text)

    @app.delete("/api/documents/{did}")
    def delete_document(did: str):
        return guarded(docs.delete, did)

    @app.post("/api/documents/delete")
    def delete_documents(body: IdsIn):
        return docs.delete_many(body.ids)

    @app.delete("/api/documents/{did}/working")
    def discard_working(did: str):
        guarded(docs.discard_working, did)
        return guarded(docs.state, did)

    @app.get("/api/documents/{did}/schema-model")
    def schema_model(did: str):
        d = guarded(docs.get, did, code=404)
        if not d["package_id"] or not d["doc_type"]:
            fail(ValueError("this document has no schema selected, so structure editing is not available"), 404)
        return guarded(ctx.registry.schema_model, d["package_id"], d["doc_type"])

    @app.get("/api/documents/{did}/schema-options")
    def schema_options(did: str):
        return guarded(docs.schema_options, did, code=404)

    @app.put("/api/documents/{did}/schema")
    def choose_schema(did: str, body: SchemaIn):
        guarded(docs.choose_schema, did, body.package_id, body.doc_type_id)
        return guarded(docs.state, did)

    @app.get("/api/documents/{did}/revisions")
    def revisions(did: str):
        return guarded(docs.revisions, did)

    @app.post("/api/documents/{did}/revisions", status_code=201)
    def commit(did: str, body: CommitIn):
        return guarded(docs.commit_revision, did, body.message)

    @app.get("/api/documents/{did}/revisions/{rid}/content")
    def revision_content(did: str, rid: str):
        r, data = guarded(docs.revision_bytes, did, rid, code=404)
        return {"revision": r, "text": docs.decode(data)}

    @app.post("/api/documents/{did}/revisions/{rid}/restore")
    def restore(did: str, rid: str):
        return guarded(docs.restore_revision, did, rid)

    # ---------------------------------------------------------------- knowledge library
    @app.get("/api/knowledge/summary")
    def knowledge_summary():
        return ctx.knowledge.summary()

    @app.post("/api/knowledge/import-project/{pid}")
    def knowledge_import_project(pid: str, include_invalid: bool = False):
        return ctx.knowledge.import_project(pid, include_invalid)

    @app.post("/api/knowledge/engineering")
    async def knowledge_engineering(file: UploadFile = File(...)):
        data = await file.read()
        try:
            return ctx.knowledge.import_engineering(file.filename or "bom.csv", data)
        except (ValueError, UnicodeDecodeError) as e:
            raise HTTPException(400, f"Could not read {file.filename}: {e}")

    @app.post("/api/knowledge/engineering-set")
    async def knowledge_engineering_set(files: list[UploadFile] = File(...)):
        got = [(f.filename or "file", await f.read()) for f in files]
        return ctx.knowledge.import_engineering_set(got)

    @app.post("/api/knowledge/models")
    async def knowledge_add_model(file: UploadFile = File(...)):
        data = await file.read()
        try:
            return ctx.knowledge.add_model(file.filename or "model.glb", data)
        except ValueError as e:
            raise HTTPException(400, f"Could not read {file.filename}: {e}")

    @app.get("/api/knowledge/models")
    def knowledge_models():
        return ctx.knowledge.models()

    @app.get("/api/knowledge/models/{mid}/file")
    def knowledge_model_file(mid: int):
        try:
            return FileResponse(ctx.knowledge.model_path(mid), media_type="model/gltf-binary")
        except KeyError:
            raise HTTPException(404, "no such model")

    @app.get("/api/knowledge/models/{mid}/status")
    def knowledge_model_status(mid: int):
        return ctx.knowledge.model_status(mid)

    @app.delete("/api/knowledge/models/{mid}")
    def knowledge_delete_model(mid: int):
        ctx.knowledge.delete_model(mid)
        return {"ok": True}

    @app.get("/api/knowledge/locate")
    def knowledge_locate(pn: str):
        return ctx.knowledge.locate(pn)

    # ---------------------------------------------------------------- translator (schema-driven parts lists)
    from ..translate.service import TranslateError

    def tr(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except (TranslateError, DocumentError, RegistryError) as e:
            raise HTTPException(400, str(e))

    @app.get("/api/translate/concepts")
    def translate_concepts():
        return ctx.translate.concepts()

    @app.get("/api/translate/schemas")
    def translate_schemas():
        return ctx.translate.schemas()

    @app.get("/api/translate/binding")
    def translate_binding(package_id: str, doc_type: str, concept: str = "parts_list", record: str | None = None):
        return tr(ctx.translate.binding, package_id, doc_type, concept, record)

    @app.put("/api/translate/binding")
    def translate_save_binding(body: dict):
        return tr(ctx.translate.save_binding, body.get("package_id", ""), body.get("doc_type", ""), body.get("binding") or {})

    @app.delete("/api/translate/binding")
    def translate_forget_binding(package_id: str, doc_type: str, concept: str = "parts_list"):
        ctx.translate.forget_binding(package_id, doc_type, concept)
        return {"ok": True}

    @app.get("/api/translate/rules")
    def translate_rules():
        return ctx.translate.rules()

    @app.put("/api/translate/rules")
    def translate_save_rules(body: dict):
        return ctx.translate.save_rules(body)

    @app.get("/api/translate/sources")
    def translate_sources():
        return ctx.translate.sources()

    @app.get("/api/translate/targets/{pid}")
    def translate_targets(pid: str):
        return tr(ctx.translate.targets, pid)

    @app.post("/api/translate/preview")
    def translate_preview(body: dict):
        return tr(ctx.translate.records, body.get("source") or {}, body.get("rules"))

    @app.post("/api/translate/generate")
    def translate_generate(body: dict):
        return tr(ctx.translate.generate, body.get("doc_id", ""), body.get("source") or {}, body.get("rules"), body.get("binding"))

    # ---------------------------------------------------------------- cross-reference (generic names for all standards)
    from ..crossref.service import CrossrefError

    def xr(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except (CrossrefError, RegistryError) as e:
            raise HTTPException(400, str(e))

    @app.get("/api/crossref/overview")
    def crossref_overview():
        return ctx.crossref.overview()

    @app.post("/api/crossref/models")
    async def crossref_add_model(file: UploadFile = File(...)):
        data = await file.read()
        return xr(ctx.crossref.add_model, file.filename or "model.xmi", data)

    @app.delete("/api/crossref/models")
    def crossref_delete_model(label: str):
        ctx.crossref.delete_model(label)
        return {"ok": True}

    @app.get("/api/crossref/terms")
    def crossref_terms(q: str = "", core: bool = False, common: bool = False, limit: int = 300):
        return ctx.crossref.terms(q, core, common, min(limit, 2000))

    @app.get("/api/crossref/term")
    def crossref_term(id: str):
        return xr(ctx.crossref.term, id)

    @app.put("/api/crossref/name")
    def crossref_confirm_name(body: dict):
        return xr(ctx.crossref.confirm_name, body.get("package_id", ""), body.get("doc_type", ""), body.get("term", ""), body.get("path", ""))

    @app.get("/api/crossref/subjects")
    def crossref_subjects(q: str = ""):
        return ctx.crossref.subjects(q)

    @app.get("/api/crossref/item")
    def crossref_item(subject: str, key: str, view: str = ""):
        return xr(ctx.crossref.item, subject, key, view)

    @app.get("/api/crossref/coverage")
    def crossref_coverage():
        return ctx.crossref.coverage()

    @app.get("/api/crossref/hints")
    def crossref_hints(standard: str = ""):
        return ctx.crossref.hints(standard)

    @app.get("/api/crossref/doc-hint/{did}")
    def crossref_doc_hint(did: str):
        try:
            return ctx.crossref.doc_hint(ctx.documents.get(did)) or {}
        except DocumentError as e:
            raise HTTPException(404, str(e))

    @app.get("/api/crossref/review")
    def crossref_review(view: str):
        return xr(ctx.crossref.review, view)

    @app.put("/api/crossref/review")
    def crossref_confirm_many(body: dict):
        return xr(ctx.crossref.confirm_many, body.get("package_id", ""), body.get("doc_type", ""), body.get("items") or [],
                  bool(body.get("whole_standard", True)))

    @app.post("/api/crossref/assign-schemas")
    def crossref_assign_schemas(body: dict):
        return ctx.crossref.assign_schemas(body.get("items") or [])

    @app.get("/api/crossref/names")
    def crossref_names(view: str, core: bool = True):
        terms = [t for t, x in ctx.crossref.vocab.terms.items() if x.get("core")] if core else None
        return xr(ctx.crossref.names_for, view, terms)

    @app.post("/api/knowledge/examples/bike")
    def knowledge_bike():
        return ctx.knowledge.load_bike_example()

    @app.delete("/api/knowledge")
    def knowledge_reset():
        ctx.knowledge.reset()
        return {"ok": True}

    @app.get("/api/knowledge/parts")
    def knowledge_parts(q: str = "", kind: str = ""):
        return ctx.knowledge.parts(q, kind)

    @app.get("/api/knowledge/parts/{part_id}")
    def knowledge_part(part_id: int):
        try:
            return ctx.knowledge.part_detail(part_id)
        except KeyError:
            raise HTTPException(404, "no such part in the library")

    @app.get("/api/knowledge/breakdown")
    def knowledge_breakdown():
        return ctx.knowledge.breakdown()

    @app.get("/api/knowledge/tasks")
    def knowledge_tasks():
        return ctx.knowledge.tasks()

    @app.get("/api/knowledge/tasks/{task_id}/{revision}")
    def knowledge_task(task_id: str, revision: str):
        try:
            return ctx.knowledge.task_detail(task_id, revision)
        except KeyError:
            raise HTTPException(404, "no such task")

    @app.get("/api/knowledge/data-modules")
    def knowledge_dms(q: str = ""):
        return ctx.knowledge.data_modules(q)

    @app.get("/api/knowledge/data-modules/{dmc}")
    def knowledge_dm(dmc: str):
        try:
            return ctx.knowledge.data_module_detail(dmc)
        except KeyError:
            raise HTTPException(404, "no such data module in the library")

    @app.get("/api/knowledge/findings")
    def knowledge_findings():
        return ctx.knowledge.findings()

    @app.get("/api/knowledge/sources")
    def knowledge_sources():
        return ctx.knowledge.sources()

    # ---------------------------------------------------------------- BREX library
    @app.get("/api/brex")
    def brex_list():
        return ctx.registry.brex.list()

    @app.post("/api/brex", status_code=201)
    async def brex_add(file: UploadFile = File(...)):
        data = await file.read()
        if len(data) > 50 * 1024 * 1024:
            fail(ValueError("BREX file larger than 50 MB"))
        try:
            return ctx.registry.brex.install(data, file.filename or "")
        except ValueError as e:
            fail(e)

    @app.get("/api/brex/substitutes")
    def brex_substitutes():
        return ctx.registry.brex.substitutes()

    @app.post("/api/brex/substitutes")
    def brex_set_substitute(body: BrexSubstituteIn):
        try:
            ctx.registry.brex.set_substitute(body.named, body.use)
        except ValueError as e:
            fail(e)
        return ctx.registry.brex.substitutes()

    @app.delete("/api/brex/substitutes/{named}")
    def brex_remove_substitute(named: str):
        if not ctx.registry.brex.remove_substitute(named):
            raise HTTPException(404, "no such substitute")
        return ctx.registry.brex.substitutes()

    @app.delete("/api/brex/{dmc}/{issue}")
    def brex_remove(dmc: str, issue: str):
        if not ctx.registry.brex.remove(dmc, issue):
            raise HTTPException(404, "no such BREX installed")
        return {"ok": True}

    @app.get("/api/documents/{did}/export")
    def export(did: str, what: str = "current", rid: str | None = None):
        d = guarded(docs.get, did, code=404)
        stem = Path(d["original_name"]).stem
        if what == "original":
            data, name = docs.original_bytes(did), d["original_name"]
        elif what == "revision" and rid:
            r, data = guarded(docs.revision_bytes, did, rid, code=404)
            name = f"{stem}.r{r['number']:04d}.xml"
        else:
            data, origin = guarded(docs.current_bytes, did)
            name = d["original_name"] if origin == "original" else f"{stem}.working.xml"
        return Response(data, media_type="application/xml",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    # ---- the desktop UI (pre-built; no Node.js needed at runtime)
    if (WEB_DIST / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404)
            f = (WEB_DIST / path).resolve()
            if path and f.is_file() and WEB_DIST.resolve() in f.parents:
                return FileResponse(f)
            return FileResponse(WEB_DIST / "index.html")
    else:
        @app.get("/", include_in_schema=False)
        def no_ui():
            return JSONResponse({"detail": "UI not built. API docs: /api/docs"})

    return app
