import codecs
import json

import pytest

from asthra.identify.service import sniff
from tests.conftest import DOCS, PKGS, copy_pkg

CASES = [
    ("s1000d_descript_valid.xml", "S1000D", "descript", "description"),
    ("s1000d_proced_valid.xml", "S1000D", "proced", "procedure"),
    ("s1000d_ipd_valid.xml", "S1000D", "ipd", "ipd"),
    ("s2000m_provisioning_valid.xml", "S2000M", "provisioning", "provisioning"),
    ("s2000m_provisioning_utf16.xml", "S2000M", "provisioning", "provisioning"),
    ("s3000l_lsa_valid.xml", "S3000L", "lsa", "maintenance-task"),
]


@pytest.mark.parametrize("fname,std,dt,family", CASES)
def test_identifies_exact_schema(project, loaded, fname, std, dt, family):
    d = loaded.documents.import_path(project["id"], DOCS / fname)
    ident = d["identification"]
    assert ident["status"] == "identified"
    assert (d["standard"], d["doc_type"]) == (std, dt)
    assert ident["candidates"][0]["content_family"] == family
    assert ident["candidates"][0]["evidence"]


def test_s1000d_identity_is_dmc(project, loaded):
    d = loaded.documents.import_path(project["id"], DOCS / "s1000d_ipd_valid.xml")
    assert d["identity"]["display"] == "DMC-ASTHRA-A-32-10-00-00A-941A-A issue 001-00"


def test_identity_never_fabricates_missing_values(project, loaded):
    d = loaded.documents.import_path(project["id"], DOCS / "s1000d_proced_invalid.xml")
    assert d["identity"]["display"].endswith("issue 1-??")
    assert any("inWork" in w for w in d["identity"]["warnings"])


def test_unknown_root_not_guessed(project, loaded):
    d = loaded.documents.import_path(project["id"], DOCS / "unknown_root.xml")
    assert d["identification"]["status"] == "unidentified" and d["standard"] is None


def test_unidentified_without_packages(ctx):
    p = ctx.projects.create("empty")
    d = ctx.documents.import_path(p["id"], DOCS / "s3000l_lsa_valid.xml")
    assert d["identification"]["status"] == "unidentified"


def test_ambiguous_when_two_packages_match(loaded, tmp_path):
    pkg = copy_pkg("s3000l-synth", tmp_path)
    m = json.loads((pkg / "asthra-package.json").read_text()); m["package_id"] = "second-copy"
    (pkg / "asthra-package.json").write_text(json.dumps(m))
    loaded.registry.install(pkg)
    p = loaded.projects.create("amb")
    d = loaded.documents.import_path(p["id"], DOCS / "s3000l_lsa_valid.xml")
    assert d["identification"]["status"] == "ambiguous"
    assert len(d["identification"]["candidates"]) == 2 and d["package_id"] is None
    # explicit selection resolves it
    d2 = loaded.documents.import_path(p["id"], DOCS / "s3000l_lsa_valid.xml",
                                      package_id="s3000l/synthetic-2-subset/second-copy", doc_type_id="lsa")
    assert d2["package_id"].endswith("second-copy")


def test_sgml_detected_and_deferred(project, loaded):
    d = loaded.documents.import_path(project["id"], DOCS / "sgml_like.sgm")
    assert d["syntax"] == "sgml" and d["identification"]["status"] == "unidentified"
    assert "Install its DTD set" in " ".join(d["identification"]["notes"])


def test_sniff_bom_and_declaration():
    s = sniff(codecs.BOM_UTF8 + b'<?xml version="1.0" encoding="UTF-8"?><a/>')
    assert s.bom == "utf-8" and s.declared_encoding == "utf-8" and not s.problems
    bad = sniff(codecs.BOM_UTF8 + b'<?xml version="1.0" encoding="ISO-8859-1"?><a/>')
    assert bad.problems


def test_synthetic_schema_never_claims_a_real_issue(project, loaded):
    """Regression: a real S1000D 4.1 procedure must not be validated against the
    synthetic test schema just because its URL ends in proced.xsd."""
    src = (DOCS / "s1000d_proced_valid.xml").read_text().replace(
        'xsi:noNamespaceSchemaLocation="proced.xsd"',
        'xsi:noNamespaceSchemaLocation="http://www.s1000d.org/S1000D_4-1/xml_schema_flat/proced.xsd"')
    d = loaded.documents.import_bytes(project["id"], "real41.xml", src.encode())
    # it fits the synthetic schema structurally, so it is offered as compatible, but never selected
    assert d["identification"]["status"] == "needs-choice" and d["package_id"] is None
    assert [c["doc_type"] for c in d["identification"]["compatible"]] == ["proced"]



ISO_HEADER = ('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE dmodule[\n<!ENTITY % ISOEntities PUBLIC '
              '"ISO 8879-1986//ENTITIES ISO Character Entities 20030531//EN//XML" "ent/ISOEntities">\n%ISOEntities;\n]>\n')


def test_iso_boilerplate_does_not_stop_the_structural_parse_on_any_build(monkeypatch):
    """Regression (Windows): with the S1000D %ISOEntities; header the document could not be read,
    without it it could. Some libxml2 builds try to load ent/ISOEntities in the quick parse and fail."""
    import asthra.identify.service as ident
    real = ident._strict_parse
    def like_windows(data):
        if b"%ISOEntities;" in data:
            class E:
                message = 'failed to load external entity "ent/ISOEntities"'; line = 4; column = 1
            return None, [E()]
        return real(data)
    monkeypatch.setattr(ident, "_strict_parse", like_windows)
    src = (DOCS / "s1000d_proced_valid.xml").read_text()
    doc = (ISO_HEADER + src[src.index("<dmodule"):]).encode()
    tree, errs = ident.parse_xml(doc)
    assert tree is not None and tree.getroot().tag == "dmodule" and errs == []
    assert tree.getroot().sourceline == doc[:doc.index(b"<dmodule")].count(b"\n") + 1     # lines kept


def test_structural_parse_never_reads_external_files(tmp_path):
    """Even a parser that would load the DTD gets empty content from the structural resolver."""
    from lxml import etree
    from asthra.security.xml_safe import NoExternalResolver
    secret = tmp_path / "secret.ent"
    secret.write_text('<!ENTITY leak "TOP-SECRET">')
    doc = (f'<!DOCTYPE d [<!ENTITY % s SYSTEM "{secret.as_uri()}"> %s;]><d>&leak;</d>').encode()
    p = etree.XMLParser(load_dtd=True, resolve_entities=True, no_network=True)
    p.resolvers.add(NoExternalResolver())
    try:
        root = etree.fromstring(doc, p)
        assert "TOP-SECRET" not in etree.tostring(root).decode()
    except etree.XMLSyntaxError as e:
        assert "TOP-SECRET" not in str(e)                          # refused: the entity stays undefined
