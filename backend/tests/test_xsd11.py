"""XSD 1.1 schemas (S-Series 2021 block release style): libxml2 cannot compile them; ASTHRA validates
with the xmlschema library, with the same precise diagnostics."""
import shutil

import pytest
from lxml import etree

from asthra.registry import installer
from tests.conftest import FIX

SRC = FIX / "xsd11-synth"
NS = "urn:asthra:synthetic:s3000l-2"
VALID = f"""<?xml version="1.0"?>
<n:lsaDataset xmlns:n="{NS}">
  <partDefinition uid="p1" unitOfIssue="EA"><partNumber>TW-100</partNumber><manufacturerCode>F0111</manufacturerCode><quantity>1</quantity></partDefinition>
  <partDefinition uid="p2" alternateOf="p1"><partNumber>TW-110</partNumber><manufacturerCode>F0111</manufacturerCode><quantity>2</quantity></partDefinition>
</n:lsaDataset>
"""


@pytest.fixture
def x11(ctx, tmp_path):
    with pytest.raises(etree.XMLSchemaParseError):          # the reason for all this
        etree.XMLSchema(etree.parse(str(SRC / "lsaDataset.xsd")))
    prop = installer.inspect(SRC)
    assert prop["kind"] == "xsd"
    prop["standard"], prop["issue"] = "S3000L", "2.0"
    ctx.registry.install(installer.build(SRC, prop, tmp_path / "x.zip"))
    return ctx


def _errors(ctx, text):
    p = ctx.projects.create("x")
    d = ctx.documents.import_bytes(p["id"], "x.xml", text.encode())
    assert d["identification"]["status"] == "identified", d["identification"]
    rep = ctx.documents.validate(d["id"])
    return rep, [x for x in rep.diagnostics if x.severity.value in ("error", "fatal")]


def test_valid_document_passes(x11):
    rep, errs = _errors(x11, VALID)
    assert rep.structural_status.value == "passed", [e.message for e in errs]


def test_each_problem_is_precise(x11):
    bad = (VALID.replace('unitOfIssue="EA"', 'unitOfIssue="XX" bogus="1"')
                .replace("<manufacturerCode>F0111</manufacturerCode><quantity>1</quantity>",
                         "<manufacturerCode>f01</manufacturerCode><quantity>-3</quantity>")
                .replace('uid="p2" alternateOf="p1"', 'alternateOf="p9"')
                .replace("<partNumber>TW-110</partNumber>", ""))
    rep, errs = _errors(x11, bad)
    cats = sorted(e.category for e in errs)
    msgs = " | ".join(e.message for e in errs)
    assert rep.structural_status.value == "failed"
    assert "value-invalid" in cats and "attribute-not-allowed" in cats and "missing-attribute" in cats
    assert "schema-rule" in cats and "Quantity must not be negative" in msgs          # the assertion, in words
    assert "missing-element" in cats and "<partNumber>" in msgs                      # missing before manufacturerCode
    assert "broken-reference" in cats and "p9" in msgs
    assert all(e.line for e in errs)


def test_duplicate_ids_and_the_model(x11):
    _, errs = _errors(x11, VALID.replace('uid="p2"', 'uid="p1"'))
    assert [e.category for e in errs] == ["duplicate-id"] and "already used at line 3" in errs[0].message
    m = x11.registry.schema_model("s3000l/2.0/official", "lsaDataset")
    assert "partDefinition" in m["elements"] and {a["name"]: a for a in m["elements"]["partDefinition"]["attrs"]}["uid"]["kind"] == "id"


def test_remote_import_is_still_refused(ctx, tmp_path):
    src = tmp_path / "remote"; shutil.copytree(SRC, src)
    xsd = (src / "lsaDataset.xsd").read_text().replace(
        '<xs:element name="lsaDataset">', '<xs:import namespace="urn:x" schemaLocation="http://example.invalid/x.xsd"/>\n  <xs:element name="lsaDataset">')
    (src / "lsaDataset.xsd").write_text(xsd)
    prop = installer.inspect(src); prop["standard"], prop["issue"] = "S3000L", "2.0"
    from asthra.registry.service import RegistryError
    with pytest.raises(RegistryError):
        ctx.registry.install(installer.build(src, prop, tmp_path / "r.zip"))


def test_w3c_signature_import_resolves_offline(ctx, tmp_path):
    """Regression (S2000M 7.0): the schema imports XML Signature from www.w3.org; ASTHRA never goes
    online, so the address resolves to the official local copy — other remote imports stay blocked."""
    src = tmp_path / "dsig"; shutil.copytree(SRC, src)
    xsd = (src / "lsaDataset.xsd").read_text()
    xsd = xsd.replace('xmlns="urn:asthra:synthetic:s3000l-2"',
                      'xmlns="urn:asthra:synthetic:s3000l-2" xmlns:ds="http://www.w3.org/2000/09/xmldsig#"')
    xsd = xsd.replace('<xs:element name="lsaDataset">',
                      '<xs:import namespace="http://www.w3.org/2000/09/xmldsig#" '
                      'schemaLocation="http://www.w3.org/TR/2008/REC-xmldsig-core-20080610/xmldsig-core-schema.xsd"/>\n'
                      '  <xs:element name="lsaDataset">')
    xsd = xsd.replace('''        <xs:element name="partDefinition" maxOccurs="unbounded">''',
                      '''        <xs:element ref="ds:Signature" minOccurs="0"/>
        <xs:element name="partDefinition" maxOccurs="unbounded">''')
    (src / "lsaDataset.xsd").write_text(xsd)
    prop = installer.inspect(src); prop["standard"], prop["issue"] = "S2000M", "7.0"
    ctx.registry.install(installer.build(src, prop, tmp_path / "d.zip"))
    p = ctx.projects.create("d")
    d = ctx.documents.import_bytes(p["id"], "v.xml", VALID.encode())
    assert ctx.documents.validate(d["id"]).structural_status.value == "passed"
