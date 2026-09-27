from asthra.validation.model import Stage, Status
from tests.conftest import DOCS


def _val(loaded, project, name):
    d = loaded.documents.import_path(project["id"], DOCS / name)
    return loaded.documents.validate(d["id"])


def test_valid_documents_pass_structurally_only(loaded, project):
    for n in ("s1000d_descript_valid.xml", "s1000d_proced_valid.xml", "s1000d_ipd_valid.xml",
              "s2000m_provisioning_valid.xml", "s2000m_provisioning_utf16.xml", "s3000l_lsa_valid.xml"):
        rep = _val(loaded, project, n)
        assert rep.structural_status == Status.PASSED, (n, rep.diagnostics)
        # An XSD pass is never reported as rule, reference or engineering approval.
        for s in (rep.business_rule_status, rep.reference_status, rep.engineering_status):
            assert s != Status.PASSED
        assert any("SYNTHETIC" in s.note for s in rep.stages if s.stage == Stage.SCHEMA)


def test_invalid_procedure_reports_located_errors(loaded, project):
    rep = _val(loaded, project, "s1000d_proced_invalid.xml")
    assert rep.structural_status == Status.FAILED
    msgs = [(d.line, d.element_path, d.raw_message or d.message) for d in rep.diagnostics]
    assert any("inWork" in m and "required" in m for _, _, m in msgs)          # mandatory attribute
    assert any("pattern" in m for _, _, m in msgs)                              # facet
    order = [x for x in msgs if "caution" in x[2] and "not expected" in x[2]]   # content-model order
    assert order and order[0][0] == 24 and "proceduralStep[2]/caution" in order[0][1]
    assert all(d.reference and "proced.xsd" in d.reference for d in rep.diagnostics)


def test_invalid_provisioning(loaded, project):
    rep = _val(loaded, project, "s2000m_provisioning_invalid.xml")
    assert rep.structural_status == Status.FAILED
    assert any("four" in d.message for d in rep.diagnostics)


def test_malformed_xml_is_fatal_with_location(loaded, project):
    rep = _val(loaded, project, "malformed.xml")
    assert rep.structural_status == Status.FAILED
    f = [d for d in rep.diagnostics if d.stage == Stage.PARSE]
    assert f and f[0].severity.value == "fatal" and f[0].line
    assert next(s for s in rep.stages if s.stage == Stage.SCHEMA).status == Status.NOT_RUN


def test_unknown_document_is_unsupported_not_passed(loaded, project):
    rep = _val(loaded, project, "unknown_root.xml")
    assert rep.structural_status == Status.UNSUPPORTED


def test_all_seven_stages_reported(loaded, project):
    rep = _val(loaded, project, "s3000l_lsa_valid.xml")
    assert [s.stage for s in rep.stages] == list(Stage)


def test_empty_file(loaded, project):
    d = loaded.documents.import_bytes(project["id"], "empty.xml", b"")
    rep = loaded.documents.validate(d["id"])
    assert rep.diagnostics[0].rule_id == "ASTHRA-INT-001"


def test_history_persisted(loaded, project):
    d = loaded.documents.import_path(project["id"], DOCS / "s1000d_proced_invalid.xml")
    loaded.documents.validate(d["id"]); loaded.documents.validate(d["id"])
    h = loaded.documents.validation_history(d["id"])
    assert len(h) == 2 and h[0]["structural_status"] == "failed" and h[0]["package_checksum"]
    n = loaded.db.one("SELECT COUNT(*) n FROM diagnostic WHERE run_id=?", (h[0]["id"],))["n"]
    assert n == 3


def test_dangling_idref_detected_and_located(loaded, project):
    """libxml2 alone does not enforce ID/IDREF; the second engine must catch it."""
    rep = _val(loaded, project, "s2000m_provisioning_invalid.xml")
    ref = [d for d in rep.diagnostics if d.rule_id == "XSD-IDREF"]
    assert len(ref) == 1 and "'p9'" in ref[0].message and "partRef" in ref[0].message
    assert ref[0].line == 9 and ref[0].element_path.endswith("ipdItem[1]")


def test_valid_internal_refs_pass_in_s1000d(loaded, project):
    rep = _val(loaded, project, "s1000d_descript_valid.xml")   # internalRef -> fig-0001
    assert not [d for d in rep.diagnostics if d.rule_id.startswith("ASTHRA-IDREF")]
    assert rep.structural_status == Status.PASSED


def test_parse_errors_do_not_leak_between_documents(loaded, project):
    a = _val(loaded, project, "malformed.xml")
    b = loaded.documents.validate(loaded.documents.import_path(project["id"], DOCS / "sgml_like.sgm")["id"])
    msgs_a = {d.message for d in a.diagnostics}
    assert not msgs_a & {d.message for d in b.diagnostics}
    assert len(msgs_a) == len([d for d in a.diagnostics if d.stage == Stage.PARSE])   # no duplicates


def test_namespaced_schema_error_paths_are_readable(loaded, project):
    rep = _val(loaded, project, "s2000m_provisioning_invalid.xml")
    d = next(x for x in rep.diagnostics if "four" in x.message)
    assert d.element_path == "/provisioningExchange/ipdRecords/ipdItem[2]/quantityPerAssembly"
