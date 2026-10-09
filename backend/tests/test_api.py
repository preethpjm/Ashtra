import re
import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from asthra.api.app import create_app
from asthra.config import Settings
from tests.conftest import DOCS, PKGS


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(data_root=tmp_path / "d"))
    with TestClient(app, headers={"X-Asthra": "1"}) as c:
        yield c
    app.state.ctx.close()


def _zip(folder):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for f in folder.rglob("*"):
            if f.is_file():
                zf.write(f, str(f.relative_to(folder)))
    return buf.getvalue()


def test_end_to_end_over_http(client):
    h = client.get("/api/health").json()
    assert h["network"] == "disabled"
    std = {s["family"]: s for s in client.get("/api/standards").json()}
    assert {"S1000D", "S2000M", "S3000L"} <= set(std)
    assert std["S2000M"]["capabilities"]["extract-canonical"]["status"] == "planned"

    for n in ("s1000d-synth", "s2000m-synth", "s3000l-synth"):
        r = client.post("/api/registry/packages", files={"file": (f"{n}.zip", _zip(PKGS / n))})
        assert r.status_code == 201, r.text
    assert len(client.get("/api/registry/packages").json()) == 3

    pid = client.post("/api/projects", json={"name": "HTTP"}).json()["id"]
    r = client.post(f"/api/projects/{pid}/documents",
                    files={"file": ("p.xml", (DOCS / "s1000d_proced_invalid.xml").read_bytes())})
    assert r.status_code == 201
    did = r.json()["id"]
    v = client.post(f"/api/documents/{did}/validate").json()
    assert v["statuses"]["structural"] == "failed" and v["counts"]["error"] == 3
    assert client.get(f"/api/documents/{did}/source").json()["text"].startswith("<?xml")
    assert len(client.get(f"/api/documents/{did}/validations").json()) == 1

    key = "s1000d/synthetic-5.0-subset/asthra-fixture"
    assert client.get(f"/api/registry/packages/{key}/integrity").json()["intact"] is True
    assert client.post(f"/api/registry/packages/{key}/enabled", json={"enabled": False}).json()["enabled"] is False


def test_errors_are_clean(client):
    assert client.get("/api/documents/nope").status_code == 404
    assert client.post("/api/projects", json={"name": "../x"}).status_code == 400
    assert client.post("/api/registry/packages", files={"file": ("a.txt", b"x")}).status_code == 400


def test_writes_require_header_and_hosts_are_checked(tmp_path):
    app = create_app(Settings(data_root=tmp_path / "d2"))
    with TestClient(app) as c:
        assert c.post("/api/projects", json={"name": "x"}).status_code == 403
        assert c.get("/api/health").status_code == 200
        assert c.get("/api/health", headers={"host": "evil.example"}).status_code == 400
        assert "default-src 'self'" in c.get("/api/health").headers["content-security-policy"]
    app.state.ctx.close()


def test_edit_save_commit_restore_cycle(client):
    for n in ("s1000d-synth",):
        client.post("/api/registry/packages", files={"file": (f"{n}.zip", _zip(PKGS / n))})
    pid = client.post("/api/projects", json={"name": "Edit"}).json()["id"]
    src = (DOCS / "s1000d_proced_invalid.xml").read_bytes()
    did = client.post(f"/api/projects/{pid}/documents", files={"file": ("p.xml", src)}).json()["id"]
    st = client.get(f"/api/documents/{did}/state").json()
    assert st["origin"] == "original" and st["revisions"] == []
    fixed = st["text"].replace('issueNumber="1"', 'issueNumber="001" inWork="00"')
    # swap the two lines whatever the line endings are (Git on Windows checks files out with CRLF)
    fixed = re.sub(r"(<para>Disconnect the hydraulic line\.</para>)(\r?\n\s*)(<caution><para>Do not damage the seal\.</para></caution>)",
                   r"\3\2\1", fixed, count=1)
    assert "<caution><para>Do not damage the seal.</para></caution>" in fixed.split("Disconnect the hydraulic line")[0]
    chk = client.post(f"/api/documents/{did}/check", json={"text": fixed}).json()
    assert chk["report"]["statuses"]["structural"] == "passed"
    assert chk["outline"]["root"]["name"] == "dmodule"
    client.put(f"/api/documents/{did}/working", json={"text": fixed})
    assert client.get(f"/api/documents/{did}/state").json()["origin"] == "working"
    # the original is untouched
    orig = client.get(f"/api/documents/{did}/export?what=original")
    assert orig.content == src
    r1 = client.post(f"/api/documents/{did}/revisions", json={"message": "fix issue info and caution order"}).json()
    assert r1["number"] == 1 and r1["structural_status"] == "passed"
    # broken XML cannot be committed
    client.put(f"/api/documents/{did}/working", json={"text": "<dmodule>"})
    assert client.post(f"/api/documents/{did}/revisions", json={}).status_code == 400
    # restore revision 1
    client.post(f"/api/documents/{did}/revisions/{r1['id']}/restore")
    assert client.get(f"/api/documents/{did}/state").json()["text"] == fixed
    cur = client.get(f"/api/documents/{did}/export")
    assert "attachment" in cur.headers["content-disposition"] and cur.content == fixed.encode()
    client.delete(f"/api/documents/{did}/working")
    assert client.get(f"/api/documents/{did}/state").json()["origin"] == "original"


def test_load_samples(client):
    p = client.post("/api/samples").json()
    assert p["name"] == "Samples" and p["document_count"] >= 17
    stds = {d["standard"] for d in client.get(f"/api/projects/{p['id']}/documents").json()}
    assert {"S1000D", "S2000M", "S3000L", "ATA2200"} <= stds
    assert client.post("/api/samples").status_code == 201      # idempotent for packages


def test_ui_is_served_with_correct_types(client):
    from asthra.api.app import WEB_DIST
    if not (WEB_DIST / "index.html").is_file():
        pytest.skip("UI not built")
    r = client.get("/")
    assert r.status_code == 200 and "<div id=\"root\">" in r.text
    js = next((WEB_DIST / "assets").glob("index-*.js")).name
    assert client.get(f"/assets/{js}").headers["content-type"].startswith("text/javascript")
    assert client.get("/some/deep/link").status_code == 200          # SPA fallback
    assert client.get("/api/nope").status_code == 404



def test_schema_chooser_over_http(client):
    client.post("/api/samples")
    pid = client.get("/api/projects").json()[-1]["id"]
    docs = {d["original_name"]: d for d in client.get(f"/api/projects/{pid}/documents").json()}
    nd = docs["ata_cmm_nodoctype.xml"]
    assert nd["identification"]["status"] == "needs-choice"
    opts = client.get(f"/api/documents/{nd['id']}/schema-options").json()
    assert opts and opts[0]["doc_type"] == "cmm" and opts[0]["declared"] is False
    st = client.put(f"/api/documents/{nd['id']}/schema", json={"package_id": opts[0]["package_id"], "doc_type_id": "cmm"}).json()
    assert st["document"]["standard"] == "ATA2200" and st["render"]["roles"]["list1"] == "list-alpha"
    v = client.post(f"/api/documents/{nd['id']}/validate").json()
    assert v["statuses"]["structural"] == "passed"
    assert any(d["rule_id"] == "ASTHRA-SCHEMA-CHOSEN" for d in v["diagnostics"])
    s1 = client.get(f"/api/documents/{docs['s1000d_proced_valid.xml']['id']}/state").json()
    assert s1["render"]["roles"]["proceduralStep"] == "step"


def test_delete_documents_over_http(client):
    pid = client.post("/api/projects", json={"name": "Del"}).json()["id"]
    src = (DOCS / "s1000d_proced_valid.xml").read_bytes()
    ids = [client.post(f"/api/projects/{pid}/documents", files={"file": (f"p{i}.xml", src)}).json()["id"] for i in range(3)]
    assert client.delete(f"/api/documents/{ids[0]}").json()["id"] == ids[0]
    assert client.delete(f"/api/documents/{ids[0]}").status_code == 400
    r = client.post("/api/documents/delete", json={"ids": ids[1:]}).json()
    assert len(r["deleted"]) == 2 and client.get(f"/api/projects/{pid}/documents").json() == []
