"""K1: importing S1000D data modules into the shared library, and the Knowledge screen's API."""
import io
import zipfile

from fastapi.testclient import TestClient

from asthra.api.app import create_app
from asthra.config import Settings
from tests.conftest import DOCS, PKGS


def _zip(folder):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for p in folder.rglob("*"):
            if p.is_file():
                z.write(p, p.relative_to(folder).as_posix())
    return buf.getvalue()


def test_import_project_into_the_library(loaded, project):
    for name in ("s1000d_proced_valid.xml", "s1000d_proced_invalid.xml", "ata_cmm_valid.xml"):
        loaded.documents.import_bytes(project["id"], name, (DOCS / name).read_bytes())
    rep = loaded.knowledge.import_project(project["id"])
    assert [r["file"] for r in rep["imported"]] == ["s1000d_proced_valid.xml"]
    reasons = {r["file"]: r["reason"] for r in rep["skipped"]}
    assert "structure failed" in reasons["s1000d_proced_invalid.xml"]
    assert "not an identified S1000D" in reasons["ata_cmm_valid.xml"]
    dm = rep["imported"][0]
    assert dm["resources"] >= 2 and dm["safety"] >= 1
    detail = loaded.knowledge.data_module_detail(dm["dmc"])
    kinds = {r["kind"] for r in detail["resources"]}
    assert {"support-equipment", "consumable"} <= kinds
    assert any(s["kind"] == "warning" for s in detail["safety"])
    assert detail["item"]["bei"] and detail["item"]["bei"] in dm["dmc"]
    again = loaded.knowledge.import_project(project["id"])                    # re-import replaces, never duplicates
    assert len(loaded.knowledge.data_module_detail(dm["dmc"])["resources"]) == len(detail["resources"])
    assert len(again["imported"]) == 1


def test_knowledge_api_with_the_bike_example(tmp_path):
    app = create_app(Settings(data_root=tmp_path))
    c = TestClient(app, headers={"X-Asthra": "1"})
    assert c.post("/api/knowledge/examples/bike").json() == {"loaded": True}
    assert c.post("/api/knowledge/examples/bike").json()["loaded"] is False       # loaded once
    s = c.get("/api/knowledge/summary").json()
    assert s["counts"]["parts"] >= 18 and s["counts"]["tasks"] == 2 and s["findings"] == 1
    parts = c.get("/api/knowledge/parts", params={"q": "BP-0001"}).json()
    assert parts[0]["superseded_by"] == "BP-0002"
    d = c.get(f"/api/knowledge/parts/{parts[0]['id']}").json()
    assert "B5-A-A7-31-02-00A-921A-D" in d["impact"]["data_modules"]
    se = c.get("/api/knowledge/parts", params={"kind": "support-equipment"}).json()
    assert {p["part_number"] for p in se} == {"BST-001", "ALLKEY5MM", "PLI-001"}
    t = c.get("/api/knowledge/tasks/T00002/2.0").json()
    assert len(t["procedure"]["steps"]) == 8 and t["documented_by"][0]["dmc"] == "B5-A-A7-31-02-00A-921A-D"
    tree = c.get("/api/knowledge/breakdown").json()
    assert any(b["bei"] == "B5-A-A7-31-02-00A" and "BP-0002" in b["parts"] for b in tree)
    dm = c.get("/api/knowledge/data-modules/B5-A-A7-31-02-00A-921A-D").json()
    assert {"name": "maintenance_level", "value": "ML2"} in dm["properties"]
    assert c.get("/api/knowledge/findings").json()[0]["rule"] == "maintenance-level"
    assert c.delete("/api/knowledge").json() == {"ok": True}
    assert c.get("/api/knowledge/summary").json()["counts"]["parts"] == 0
