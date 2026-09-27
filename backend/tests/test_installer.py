"""The one-step installer: any folder or zip -> proposal -> package."""
import io
import shutil
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from asthra.api.app import create_app
from asthra.app_context import AppContext
from asthra.config import Settings
from asthra.registry import installer
from asthra.registry.builder import BuildError
from tests.conftest import DOCS, FIX, PKGS
from tests.test_builder import ANNOT, ISO_DOCTYPE, _ent_folder, _iso_doc, fake_official


def fake_download(tmp_path):
    """Shaped like the real 'Issue 4.1' download: original schemas, a patch, entities, a PDF."""
    root = tmp_path / "Issue 4.1"
    orig = fake_official(tmp_path / "o")
    shutil.copytree(orig, root / "XML Schema package" / "Schemas")
    shutil.copytree(orig, root / "Patches" / "Patch 4.1.A" / "xml_schema_flat")
    shutil.copytree(_ent_folder(tmp_path), root / "Patches" / "Patch 4.1.A" / "ent")
    (root / "Specification").mkdir(parents=True)
    (root / "Specification" / "S1000D.PDF").write_bytes(b"%PDF-1.4 not a schema")
    return root


def copy_wanted(src, dest):
    for f in src.rglob("*"):
        if f.is_file() and installer.wanted(f.relative_to(src).as_posix(), f.stat().st_size):
            d = dest / f.relative_to(src); d.parent.mkdir(parents=True, exist_ok=True); shutil.copy(f, d)


def test_s1000d_download_is_recognised_with_latest_patch_and_entities(ctx, tmp_path):
    src = tmp_path / "staged"; copy_wanted(fake_download(tmp_path), src)
    assert not list(src.rglob("*.PDF"))                         # manuals are never taken
    prop = installer.inspect(src)
    assert prop["kind"] == "s1000d" and prop["issue"] == "4.1"
    assert len(prop["folders"]) == 2 and "Patch 4.1.A" in prop["folder"]
    assert prop["entity_folder"].endswith("ent") and prop["notes"]
    prop["types"] = ["proced"]
    z = installer.build(src, prop, tmp_path / "p.zip")
    ctx.registry.install(z)
    p = ctx.projects.create("x")
    d = ctx.documents.import_bytes(p["id"], "iso.xml", _iso_doc().encode())
    assert d["package_id"] == "s1000d/4.1/official"
    assert ctx.documents.validate(d["id"]).structural_status.value == "passed"


def test_dtd_set_requires_issue_and_roots(ctx, tmp_path):
    src = tmp_path / "dtd"; shutil.copytree(FIX / "dtd" / "ata-synth", src)
    prop = installer.inspect(src)
    assert prop["kind"] == "dtd" and prop["doc_types"][0]["root"] == "cmm"
    with pytest.raises(BuildError, match="issue"):
        installer.build(src, prop, tmp_path / "d.zip")
    prop["issue"] = "2023.1"; prop["standard"] = "ATA2200"
    ctx.registry.install(installer.build(src, prop, tmp_path / "d.zip"))
    assert any(p.manifest.key == "ata2200/2023.1/official" for p in ctx.registry.list())


def test_generic_xsd_set_for_s2000m(ctx, tmp_path):
    src = tmp_path / "xsd"; shutil.copytree(PKGS / "s2000m-synth" / "xsd", src)
    prop = installer.inspect(src)
    assert prop["kind"] == "xsd" and prop["standard"] == "S2000M"
    roots = {t["root"]: t for t in prop["doc_types"]}
    assert roots["provisioningExchange"]["namespace"] == "urn:asthra:synthetic:s2000m"
    prop["issue"] = "6.1"
    ctx.registry.install(installer.build(src, prop, tmp_path / "x.zip"))
    p = ctx.projects.create("m")
    d = ctx.documents.import_path(p["id"], DOCS / "s2000m_provisioning_valid.xml")
    assert d["identification"]["status"] == "identified" and d["issue"] == "6.1"
    assert ctx.documents.validate(d["id"]).structural_status.value == "passed"


def test_ready_made_package_installs_as_is(ctx, tmp_path):
    prop = installer.inspect(PKGS / "s3000l-synth")
    assert prop["kind"] == "package"
    ctx.registry.install(installer.build(PKGS / "s3000l-synth", prop, tmp_path / "unused.zip"))
    assert ctx.registry.list()[0].manifest.standard == "S3000L"


def test_nothing_useful_is_reported(tmp_path):
    (tmp_path / "e").mkdir(); (tmp_path / "e" / "readme.txt").write_text("hi")
    with pytest.raises(BuildError, match="No schema files"):
        installer.inspect(tmp_path / "e")


def test_remove_needs_confirmation_when_in_use(loaded, project):
    key = "s2000m/synthetic-6-subset/asthra-fixture"
    d = loaded.documents.import_path(project["id"], DOCS / "s2000m_provisioning_valid.xml")
    from asthra.registry.service import RegistryError
    with pytest.raises(RegistryError, match="1 document"):
        loaded.registry.remove(key)
    assert loaded.registry.remove(key, force=True) == 1
    doc = loaded.documents.get(d["id"])
    assert doc["package_id"] is None and doc["identification"]["status"] == "unidentified"
    assert not any(p.manifest.key == key for p in loaded.registry.list())


def test_schema_set_moves_to_a_new_system(loaded, tmp_path):
    z = loaded.registry.export_set(tmp_path / "set.zip")
    fresh = AppContext.open(Settings(data_root=tmp_path / "new-system"))
    try:
        res = fresh.registry.import_set(z)
        assert {r["result"] for r in res} == {"installed"} and len(res) == 3
        assert {p.checksum for p in fresh.registry.list()} == {p.checksum for p in loaded.registry.list()}
        assert {r["result"] for r in fresh.registry.import_set(z)} == {"already installed"}
    finally:
        fresh.close()


def test_browser_flow_over_http(tmp_path):
    app = create_app(Settings(data_root=tmp_path / "d"))
    with TestClient(app, headers={"X-Asthra": "1"}) as c:
        root = fake_download(tmp_path)
        files = [("files", (f.relative_to(root.parent).as_posix(), f.read_bytes()))
                 for f in root.rglob("*") if f.is_file()]
        r = c.post("/api/registry/inspect", files=files).json()
        prop = r["proposal"]
        assert prop["kind"] == "s1000d" and "Patch 4.1.A" in prop["folder"]
        prop["types"] = ["proced"]
        b = c.post("/api/registry/build", json={"staging_id": r["staging_id"], "choice": prop})
        assert b.status_code == 201 and b.json()["action"] == "installed"
        # the same again is a conflict unless replace is asked for
        r2 = c.post("/api/registry/inspect", files=files).json()
        p2 = r2["proposal"]; p2["types"] = ["proced"]
        assert c.post("/api/registry/build", json={"staging_id": r2["staging_id"], "choice": p2}).status_code == 409
        r3 = c.post("/api/registry/inspect", files=files).json()
        p3 = r3["proposal"]; p3["types"] = ["proced"]
        rep = c.post("/api/registry/build", json={"staging_id": r3["staging_id"], "choice": p3, "replace": True}).json()
        assert rep["action"] == "replaced"
        key = "s1000d/4.1/official"
        ex = c.get(f"/api/registry/packages/{key}/export")
        assert ex.status_code == 200 and zipfile.ZipFile(io.BytesIO(ex.content)).read("asthra-package.json")
        s = c.get("/api/registry/export-set")
        assert s.status_code == 200
        assert c.delete(f"/api/registry/packages/{key}").json()["unlinked_documents"] == 0
        imp = c.post("/api/registry/import-set", files={"file": ("set.zip", s.content)}).json()
        assert imp["results"][0]["result"] == "installed"
        # path traversal in uploaded names is refused
        bad = c.post("/api/registry/inspect", files=[("files", ("../../evil.xsd", b"<x/>"))])
        assert bad.status_code == 400
    app.state.ctx.close()
