"""BREX (business rules): reading rule books, the chain, every kind of rule, and the validation stage."""
import io
import re
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from lxml import etree

from asthra.brex.engine import CompiledBrex, document_brex_ref
from asthra.brex.library import BrexLibrary
from asthra.brex.model import parse_brex
from tests.conftest import DOCS, FIX

B = FIX / "brex"
PROJECT_REF = ('<brexDmRef><dmRef><dmRefIdent><dmCode modelIdentCode="TESTPRJ" systemDiffCode="A" systemCode="00" '
               'subSystemCode="0" subSubSystemCode="0" assyCode="00" disassyCode="00" disassyCodeVariant="A" '
               'infoCode="022" infoCodeVariant="A" itemLocationCode="D"/></dmRefIdent></dmRef></brexDmRef>')


def test_reading_a_brex():
    b = parse_brex((B / "project-brex.xml").read_bytes())
    assert b.dmc == "TESTPRJ-A-00-00-00-00A-022A-D" and b.issue == "002-00" and b.schema_issue == "4.1"
    assert b.parent_dmc == "S1000D-E-04-10-0301-00A-022A-D"
    assert [r.rule_id for r in b.rules][:3] == ["BREX-TEST-00001", "BREX-TEST-00002", "BREX-TEST-00003"]
    assert {r.context for r in b.rules} == {None, "proced.xsd", "descript.xsd"}
    assert list(b.sns) == ["32"] and list(b.sns["32"].children) == ["1"]
    d = parse_brex((B / "default-brex.xml").read_bytes())
    assert d.parent_dmc is None                                   # refers to itself: top of the chain
    with pytest.raises(ValueError):
        parse_brex((DOCS / "s1000d_proced_valid.xml").read_bytes())


def _doc(text):
    return etree.fromstring(text.encode())


def test_every_kind_of_rule():
    cb = CompiledBrex(parse_brex((B / "project-brex.xml").read_bytes()))
    root = _doc('''<dmodule><identAndStatusSection><dmAddress><dmIdent>
      <dmCode modelIdentCode="bad code" systemDiffCode="A" systemCode="33" subSystemCode="1" subSubSystemCode="0"
              assyCode="00" disassyCode="00" disassyCodeVariant="A" infoCode="520" infoCodeVariant="A" itemLocationCode="Z"/>
      </dmIdent></dmAddress><dmStatus><security securityClassification="02"/></dmStatus></identAndStatusSection>
      <content><procedure><mainProcedure><proceduralStep><para>Do <emphasis emphasisType="em03">this</emphasis>.</para>
      </proceduralStep></mainProcedure></procedure></content></dmodule>''')
    res = cb.check(root, "proced.xsd")
    ids = sorted(f.rule.rule_id for f in res.findings)
    assert ids == ["BREX-SNS", "BREX-TEST-00001", "BREX-TEST-00002", "BREX-TEST-00003", "BREX-TEST-00004", "BREX-TEST-00010"]
    assert [r.rule_id for r, _ in res.not_checked] == ["BREX-TEST-00099"]          # never silently passed
    sec = next(f for f in res.findings if f.rule.rule_id == "BREX-TEST-00002")
    assert "'02'" in sec.detail and sec.line == 4
    assert all(f.rule.rule_id != "BREX-TEST-00011" for f in res.findings)           # descript-only rule skipped


def test_chain_and_missing_links(tmp_path):
    lib = BrexLibrary(tmp_path / "brex")
    lib.install((B / "project-brex.xml").read_bytes(), "project-brex.xml")
    chain, missing = lib.chain("TESTPRJ-A-00-00-00-00A-022A-D")
    assert [e["dmc"] for e in chain] == ["TESTPRJ-A-00-00-00-00A-022A-D"] and missing == "S1000D-E-04-10-0301-00A-022A-D"
    lib.install((B / "default-brex.xml").read_bytes(), "default-brex.xml")
    chain, missing = lib.chain("TESTPRJ-A-00-00-00-00A-022A-D")
    assert len(chain) == 2 and missing is None
    assert lib.default_for("4.1")["dmc"].startswith("S1000D-")
    assert lib.remove("TESTPRJ-A-00-00-00-00A-022A-D", "002-00") and lib.find("TESTPRJ-A-00-00-00-00A-022A-D") is None


@pytest.fixture
def brex_ctx(loaded, project):
    src = (DOCS / "s1000d_proced_valid.xml").read_text()
    def run(text):
        d = loaded.documents.import_bytes(project["id"], "p.xml", text.encode())
        return loaded.documents.validate(d["id"])
    run.src = src
    return run, loaded


def _with_ref(src):
    return re.sub(r"(<dmStatus[^>]*>)", r"\1" + "", src, count=1).replace("</dmStatus>", PROJECT_REF + "</dmStatus>", 1) \
        if "</dmStatus>" in src else src


def test_business_rules_stage_in_validation(brex_ctx):
    run, ctx = brex_ctx
    src = _with_ref(run.src)
    assert "TESTPRJ" in src and document_brex_ref(etree.fromstring(src.encode())) == "TESTPRJ-A-00-00-00-00A-022A-D"
    rep = run(src)                                                  # nothing installed yet
    assert rep.business_rule_status.value == "not-run"
    miss = [d for d in rep.diagnostics if d.rule_id == "ASTHRA-BREX-MISSING"]
    assert miss and miss[0].value == "TESTPRJ-A-00-00-00-00A-022A-D" and "not checked" in miss[0].message
    # the synthetic test schema's dmStatus has no brexDmRef: the only structural error is about that,
    # and business rules are checked independently of structure
    struct = [d for d in rep.diagnostics if d.stage == 3 and d.severity.value == "error"]
    assert struct and all("brexDmRef" in (d.raw_message or d.message) for d in struct)
    ctx.registry.brex.install((B / "project-brex.xml").read_bytes())
    rep = run(src)
    stage = next(s for s in rep.stages if s.stage == 4)
    assert "DMC-S1000D-E-04-10-0301-00A-022A-D missing" in stage.note          # partly checked: chain incomplete
    ctx.registry.brex.install((B / "default-brex.xml").read_bytes())
    rep = run(src.replace('itemLocationCode="A"', 'itemLocationCode="Z"', 1))
    br = [d for d in rep.diagnostics if d.stage == 4 and d.severity.value == "error"]
    assert rep.business_rule_status.value == "failed"
    assert any(d.rule_id == "BREX-TEST-00004" and d.line for d in br)
    assert any(d.rule_id == "BREX-TEST-00010" for d in br)          # proced-only rule applies
    assert all(not d.message.startswith("BREX-TEST") for d in br)   # the rule id is not repeated in the text
    assert any(d.rule_id == "ASTHRA-BREX-NOT-CHECKED" for d in rep.diagnostics)
    assert any(d.rule_id == "ASTHRA-BREX-ISSUE" for d in rep.diagnostics)      # 4.1 BREX, synthetic-5.0 document
    assert "→" in next(s for s in rep.stages if s.stage == 4).note


def test_brex_api_and_cli(tmp_path, capsys):
    from asthra.api.app import create_app
    from asthra.cli import main
    from asthra.config import Settings
    c = TestClient(create_app(Settings(data_root=tmp_path / "d")), headers={"X-Asthra": "1"})
    r = c.post("/api/brex", files={"file": ("p.xml", (B / "project-brex.xml").read_bytes())})
    assert r.status_code == 201 and r.json()["rules"] == 7
    assert c.post("/api/brex", files={"file": ("x.xml", (DOCS / "s1000d_proced_valid.xml").read_bytes())}).status_code == 400
    assert [e["dmc"] for e in c.get("/api/brex").json()] == ["TESTPRJ-A-00-00-00-00A-022A-D"]
    assert c.delete("/api/brex/TESTPRJ-A-00-00-00-00A-022A-D/002-00").json() == {"ok": True}
    assert main(["--data", str(tmp_path / "c"), "brex", "add", str(B / "project-brex.xml")]) == 0
    assert main(["--data", str(tmp_path / "c"), "brex", "list"]) == 0
    out = capsys.readouterr().out
    assert "7 rules" in out and "not installed" in out


def test_installer_finds_the_default_brex(tmp_path):
    from asthra.registry import installer
    (tmp_path / "Patches").mkdir()
    (tmp_path / "Patches" / "DMC-S1000D-E-04-10-0301-00A-022A-D_013-00_EN-US.XML").write_bytes((B / "default-brex.xml").read_bytes())
    found = installer.find_brex(tmp_path)
    assert found and found[0]["dmc"] == "S1000D-E-04-10-0301-00A-022A-D" and found[0]["schema_issue"] == "4.1"
    assert installer.wanted("Patches/DMC-S1000D-E-04-10-0301-00A-022A-D_013-00_EN-US.XML", 5000)
    lib = BrexLibrary(tmp_path / "lib")
    assert len(installer.install_brex_found(tmp_path, lib, "4.1")) == 1
    assert installer.install_brex_found(tmp_path, BrexLibrary(tmp_path / "lib2"), "4.2") == []   # other issue's default


def test_substitute_for_a_brex_that_is_not_installed(brex_ctx):
    """Regression: the document names its own project BREX (not available); the user chooses an
    installed BREX to use instead, and every result says so."""
    run, ctx = brex_ctx
    lib = ctx.registry.brex
    src = _with_ref(run.src)
    lib.install((B / "default-brex.xml").read_bytes())
    with pytest.raises(ValueError):
        lib.set_substitute("TESTPRJ-A-00-00-00-00A-022A-D", "NOT-INSTALLED")
    lib.set_substitute("TESTPRJ-A-00-00-00-00A-022A-D", "S1000D-E-04-10-0301-00A-022A-D")
    rep = run(src.replace("<dmStatus>", "<dmStatus>", 1).replace('</dmCode>', '</dmCode>'))
    sub = [d for d in rep.diagnostics if d.rule_id == "ASTHRA-BREX-SUBSTITUTE"]
    assert sub and "instead of DMC-TESTPRJ" in sub[0].message
    assert not any(d.rule_id == "ASTHRA-BREX-MISSING" for d in rep.diagnostics)
    assert rep.business_rule_status.value in ("passed", "failed")
    assert "(instead of DMC-TESTPRJ-A-00-00-00-00A-022A-D)" in next(s for s in rep.stages if s.stage == 4).note
    assert lib.remove_substitute("TESTPRJ-A-00-00-00-00A-022A-D")
    assert any(d.rule_id == "ASTHRA-BREX-MISSING" for d in run(src).diagnostics)


def test_substitute_api(tmp_path):
    from asthra.api.app import create_app
    from asthra.config import Settings
    c = TestClient(create_app(Settings(data_root=tmp_path / "d")), headers={"X-Asthra": "1"})
    c.post("/api/brex", files={"file": ("d.xml", (B / "default-brex.xml").read_bytes())})
    r = c.post("/api/brex/substitutes", json={"named": "B7772S11MON-A-00-00-00-10A-022A-D", "use": "S1000D-E-04-10-0301-00A-022A-D"})
    assert r.status_code == 200 and r.json() == {"B7772S11MON-A-00-00-00-10A-022A-D": "S1000D-E-04-10-0301-00A-022A-D"}
    assert c.post("/api/brex/substitutes", json={"named": "X", "use": "NOT-THERE"}).status_code == 400
    assert c.delete("/api/brex/substitutes/B7772S11MON-A-00-00-00-10A-022A-D").json() == {}


def test_xml_schema_class_subtraction_in_patterns():
    """Regression (ATA BREX-CMMST-00007): '^[-A-Z0-9-[O]]{1,15}$' means A-Z except O, digits, hyphen.
    Python has no class subtraction; untranslated, every part number failed."""
    from asthra.brex.engine import _value_ok, XPATH2
    v = [("pattern", "^[-A-Z0-9-[O]]{1,15}$", "")]
    assert _value_ok("2S11ZD0011L", v) and _value_ok("AB-12", v)
    assert not _value_ok("O123", v) and not _value_ok("TOOLONG123456789", v)
    assert XPATH2["matches"](None, "B7", "^[A-Z-[O]][0-9]$") and not XPATH2["matches"](None, "O7", "^[A-Z-[O]][0-9]$")
