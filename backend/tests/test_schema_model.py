"""The unified schema model, from XSD, XML DTD and SGML DTD."""
import pytest

from asthra.registry import installer
from tests.conftest import DOCS, FIX, PKGS


def el(model, name):
    return model["elements"][name]


def names(p):
    if not p:
        return []
    if p["k"] == "el":
        return [p["n"]]
    return [n for i in p.get("items", []) for n in names(i)]


def test_xsd_model(loaded):
    m = loaded.registry.schema_model("s1000d/synthetic-5.0-subset/asthra-fixture", "proced")
    assert m["root"] == "dmodule" and m["kind"] == "xsd"
    proc = el(m, "procedure")["content"]
    assert proc["k"] == "seq" and names(proc) == ["preliminaryRqmts", "mainProcedure", "closeRqmts"]
    step = el(m, "proceduralStep")
    assert {"para", "figure", "proceduralStep", "warning", "caution", "note"} <= set(names(step["content"]))
    assert el(m, "para")["mixed"] and "internalRef" in names(el(m, "para")["content"])
    fig = {a["name"]: a for a in el(m, "figure")["attrs"]}
    assert fig["id"]["required"] and fig["id"]["kind"] == "id"
    ilc = {a["name"]: a for a in el(m, "dmCode")["attrs"]}["itemLocationCode"]
    assert ilc["kind"] == "enum" and ilc["values"] == ["A", "B", "C", "D", "T"]
    assert {a["name"]: a for a in el(m, "internalRef")["attrs"]}["internalRefId"]["kind"] == "idref"
    assert "issueInfo" in m["elements"]                     # local (non-global) elements are reached too
    content = el(m, "content")["content"]                   # substitution group expanded
    assert names(content) == ["procedure"]


def test_xml_dtd_model(ctx, tmp_path):
    from asthra.registry.dtd_builder import build_dtd_package
    build_dtd_package(FIX / "dtd" / "ata-synth", "ATA2200", "t", tmp_path / "d.zip")
    ctx.registry.install(tmp_path / "d.zip")
    m = ctx.registry.schema_model("ata2200/t/official", "cmm")
    assert m["kind"] == "dtd" and names(el(m, "cmm")["content"]) == ["title", "pgblk"]
    assert el(m, "refint")["empty"]
    assert {a["name"]: a for a in el(m, "torque")["attrs"]}["unit"]["values"] == ["lbf.in", "lbf.ft", "N.m"]
    assert el(m, "para")["mixed"] and set(names(el(m, "para")["content"])) == {"refint", "torque"}


def test_sgml_dtd_model(ctx, tmp_path):
    src = FIX / "sgml" / "ata-sgml-synth"
    prop = installer.inspect(src); prop["issue"] = "t"
    ctx.registry.install(installer.build(src, prop, tmp_path / "s.zip"))
    m = ctx.registry.schema_model("ata2200/t/sgml", "cmm")
    assert m["kind"] == "sgml"
    for n in ("warning", "caution", "note"):                # declared together as a name group
        assert names(el(m, n)["content"]) == ["para"]
    assert el(m, "refint")["empty"] and el(m, "title")["text"]
    attrs = {a["name"]: a for a in el(m, "refint")["attrs"]}
    assert attrs["refid"]["required"] and attrs["refid"]["kind"] == "idref"
    assert attrs["reftype"]["values"] == ["figure", "table", "task"] and attrs["reftype"]["default"] == "task"


def test_model_over_http(loaded, project):
    from fastapi.testclient import TestClient
    from asthra.api.app import create_app
    d = loaded.documents.import_path(project["id"], DOCS / "s1000d_proced_valid.xml")
    app = create_app(loaded.settings)
    with TestClient(app, headers={"X-Asthra": "1"}) as c:
        m = c.get(f"/api/documents/{d['id']}/schema-model").json()
        assert m["root"] == "dmodule" and "proceduralStep" in m["elements"]
    app.state.ctx.close()
