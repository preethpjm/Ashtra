"""3D: the STEP ↔ MBOM reconciliation result and a GLB model in the knowledge library."""
import json
from collections import Counter
from pathlib import Path

from fastapi.testclient import TestClient

from asthra.api.app import create_app
from asthra.config import Settings
from asthra.knowledge.engineering import import_bom, is_reconciliation
from asthra.knowledge.models import glb_node_names, node_shows
from asthra.knowledge.store import KnowledgeStore

F = Path(__file__).parent / "fixtures" / "knowledge" / "ra7100"
GLB = F / "3D" / "RA-7100-01.glb"
REC = F / "3D" / "RA-7100-01_reconciliation_result.json"
BOM = F / "BOM" / "RA-7100_engineering-BOM.csv"


def test_node_names_and_matching():
    names = glb_node_names(GLB.read_bytes())
    assert "RA-7110-1" in names and "NAS1352C3-8_4" in names and "M83248/1-210_2" in names
    assert node_shows("NAS1352C3-8_4", "NAS1352C3-8") and node_shows("F6137-C75930", "C75930")
    assert not node_shows("C759301", "C75930") and not node_shows("RA-7110-10", "RA-7110-1")
    assert node_shows("F6137-M83461/1-142 (AS5857)", "M83461-1-142")


def test_reconciliation_import():
    k = KnowledgeStore()
    obj = json.loads(REC.read_text())
    assert is_reconciliation(obj)
    r = import_bom(k, REC.read_bytes(), REC.name)
    assert r["links"] == 13 and r["lines"] == 16
    rules = Counter(f["rule"] for f in k.consistency())
    assert rules["3d-mbom-only"] == 1 and rules["3d-quantity"] == 0       # the modelled -01 agrees with the MBOM
    # MBOM part numbers lose their level dots
    assert k.db.execute("SELECT COUNT(*) FROM part WHERE part_number='RA-7150-2'").fetchone()[0] == 1


def test_reconciliation_flags_become_findings():
    obj = json.loads(REC.read_text())
    obj["matched"][0].update(step_qty=2, quantity_match=False)
    obj["matched"][1].update(status="fuzzy_candidate", confidence=0.8, flags=["one character different"])
    obj["unmatched_step"] = [{"step_part_number": "X-1", "step_name": "SHIM", "step_qty": 1, "status": "unmatched", "flags": []}]
    k = KnowledgeStore()
    import_bom(k, json.dumps(obj).encode(), "rec.json")
    rules = Counter(f["rule"] for f in k.consistency())
    assert rules["3d-quantity"] == 1 and rules["3d-fuzzy"] == 1 and rules["3d-unmatched"] == 1


def test_models_api(tmp_path):
    c = TestClient(create_app(Settings(data_root=tmp_path)), headers={"X-Asthra": "1"})
    c.post("/api/knowledge/engineering", files={"file": (BOM.name, BOM.read_bytes(), "text/csv")})
    c.post("/api/knowledge/engineering", files={"file": (REC.name, REC.read_bytes(), "application/json")})
    m = c.post("/api/knowledge/models", files={"file": (GLB.name, GLB.read_bytes(), "model/gltf-binary")}).json()
    assert m["nodes"] == 21 and m["linked"] >= 20
    assert c.get(f"/api/knowledge/models/{m['id']}/file").content[:4] == b"glTF"
    st = c.get(f"/api/knowledge/models/{m['id']}/status").json()
    assert st["NAS1352C3-8_3"]["status"] == "matched" and st["RA-7110-1"]["part_number"] == "RA-7110-1"
    loc = c.get("/api/knowledge/locate", params={"pn": "NAS1352C3-8"}).json()
    assert loc[0]["nodes"] == ["NAS1352C3-8_1", "NAS1352C3-8_2", "NAS1352C3-8_3", "NAS1352C3-8_4"]
    assert c.get("/api/knowledge/locate", params={"pn": "RA-7150-2"}).json() == []      # not modelled
    pid = c.get("/api/knowledge/parts", params={"q": "RA-7160-1"}).json()[0]["id"]
    d = c.get(f"/api/knowledge/parts/{pid}").json()
    assert d["models"][0]["nodes"] == ["RA-7160-1"] and d["impact"]["cad"][0]["status"] == "matched"
    bad = c.post("/api/knowledge/models", files={"file": ("x.glb", b"not a model", "model/gltf-binary")})
    assert bad.status_code == 400
    assert c.delete(f"/api/knowledge/models/{m['id']}").json() == {"ok": True}
    assert c.get("/api/knowledge/models").json() == []


def test_engineering_folder_and_zip(tmp_path):
    import io
    import zipfile
    c = TestClient(create_app(Settings(data_root=tmp_path)), headers={"X-Asthra": "1"})
    folder = [("files", (f"RA-7100/{p.name}", p.read_bytes(), "application/octet-stream")) for p in (GLB, REC, BOM)]
    folder.append(("files", ("RA-7100/RA-7100-01.stp", b"ISO-10303-21;", "application/octet-stream")))
    r = c.post("/api/knowledge/engineering-set", files=folder).json()
    kinds = [x["kind"] for x in r["imported"]]
    assert kinds == ["Engineering BOM", "3D ↔ MBOM reconciliation", "3D model"]       # BOM, then JSON, then GLB
    assert "STEP" in r["skipped"][0]["reason"]
    m = c.get("/api/knowledge/models").json()[0]
    assert m["reconciliation"] == REC.name                                          # coloured by its own reconciliation
    assert c.get(f"/api/knowledge/models/{m['id']}/status").json()["RA-7130-1"]["status"] == "matched"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.write(GLB, "out/RA-7100-01.glb")
        z.write(REC, "out/RA-7100-01_reconciliation_result.json")
    r = c.post("/api/knowledge/engineering-set", files=[("files", ("tool-output.zip", buf.getvalue(), "application/zip"))]).json()
    assert [x["kind"] for x in r["imported"]] == ["3D ↔ MBOM reconciliation", "3D model"]
    assert len(c.get("/api/knowledge/models").json()) == 2
