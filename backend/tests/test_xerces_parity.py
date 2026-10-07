"""Every schema error is reported, as Oxygen's Xerces does (regression: real S1000D 4.2 descript/proced).

libxml2 stops checking an element's remaining content at the first element it does not expect, and
cannot validate a document that is not well-formed. ASTHRA checks the skipped parts and validates a
broken file up to the point where it breaks."""
import pytest

from asthra.registry import installer
from tests.conftest import DOCS, FIX


@pytest.fixture
def flat(ctx, tmp_path):
    prop = installer.inspect(FIX / "xsd-flat")
    prop["standard"], prop["issue"] = "S1000D", "flat-test"
    prop["doc_types"] = [dict(t, selected=(t["root"] == "dmodule")) for t in prop["doc_types"]]
    ctx.registry.install(installer.build(FIX / "xsd-flat", prop, tmp_path / "f.zip"))
    key = ctx.registry.list(False)[0].manifest.key
    p = ctx.projects.create("f")

    def run(name):
        d = ctx.documents.import_bytes(p["id"], name, (DOCS / name).read_bytes())
        opts = ctx.documents.schema_options(d["id"])
        if d["identification"]["status"] != "identified":
            ctx.documents.choose_schema(d["id"], key, "dmodule")
        rep = ctx.documents.validate(d["id"])
        return rep, [x for x in rep.diagnostics if x.severity.value in ("error", "fatal")]
    return run


def test_errors_inside_and_after_a_misplaced_element_are_reported(flat):
    rep, errs = flat("flat_descript_errors.xml")
    by_line = {}
    for e in errs:
        by_line.setdefault(e.line, []).append(e)
    msgs = " | ".join(e.message for e in errs)
    assert len(errs) == 9, msgs                                             # libxml2 alone: 2
    assert {7, 10, 12, 13, 14, 15, 16, 20} <= set(by_line)
    assert "<levelled> is not allowed inside <description>" in msgs
    assert "<Para> is not allowed inside <levelledPara>" in msgs            # inside the misplaced element
    assert any(e.category == "missing-attribute" for e in by_line[15])
    assert "'ICN-NOT-DECLARED', which is not declared as an entity in the document's DOCTYPE" in msgs
    assert all("ICN-OK" not in e.message for e in errs)                     # the declared one is fine
    assert "<internal> is not allowed inside <para>" in msgs                # after the misplaced element


def test_a_broken_file_is_still_checked_up_to_the_break(flat):
    rep, errs = flat("flat_truncated.xml")
    fatal = [e for e in errs if e.severity.value == "fatal"]
    schema = [e for e in errs if e.stage == 3]
    assert fatal and fatal[0].category == "not-well-formed"
    assert len(schema) == 4, [e.message for e in schema]                    # Xerces-style: errors before the break
    assert all("found before the file breaks off" in e.message for e in schema)
    assert not any("incomplete" in e.message for e in schema)              # nothing caused by the missing end tags
    stages = {s.stage: s for s in rep.stages}
    assert stages[3].status.value == "failed" and "up to line" in stages[3].note


def test_utf16_files_like_the_real_ones(flat):
    """Regression: the real descript.xml / proced.xml are UTF-16 (BOM, CRLF); the proced one ends with
    its root end tag commented out (<!--</dmodule>-->)."""
    _, errs = flat("flat_descript_errors_utf16.xml")
    assert len(errs) == 9
    rep, errs = flat("flat_truncated_utf16.xml")
    schema = [e for e in errs if e.stage == 3]
    assert len(schema) == 4, [e.message for e in schema]
    assert not any("incomplete" in e.message for e in schema)
    assert {e.line for e in schema} == {3, 5, 6}
