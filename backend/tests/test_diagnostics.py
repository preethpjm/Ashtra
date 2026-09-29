"""Phase 1 diagnostics: precise, actionable messages (synthetic S1000D schema)."""
import re

import pytest

from tests.conftest import DOCS


@pytest.fixture
def check(loaded, project):
    src = (DOCS / "s1000d_proced_valid.xml").read_text()

    def run(text, name="t.xml"):
        d = loaded.documents.import_bytes(project["id"], name, text.encode())
        rep = loaded.documents.validate(d["id"])
        return [x for x in rep.diagnostics if x.severity.value in ("error", "fatal")]
    run.src = src
    return run


def _block(src, tag):
    return re.search(rf"<{tag}>.*?</{tag}>\s*", src, re.S).group(0)


def test_duplicate_id_names_both_places(check):
    errs = check(check.src.replace('id="stp-0002"', 'id="stp-0001"', 1))
    [d] = errs
    assert d.category == "duplicate-id" and d.rule_id == "ASTHRA-DUPLICATE-ID"
    assert "already used at line 21 on <proceduralStep>" in d.message and d.line == 22


def test_malformed_id_is_not_called_a_duplicate(check):
    errs = check(check.src.replace('id="stp-0002"', 'id="2stp"', 1))
    assert errs[0].category == "value-invalid" and "Duplicate" not in errs[0].message


def test_missing_required_element_offers_insert(check):
    errs = check(check.src.replace(_block(check.src, "preliminaryRqmts"), ""))
    [d] = errs
    assert d.category == "missing-element"
    assert d.message == "A required <preliminaryRqmts> is missing before <mainProcedure>."
    assert d.fix.kind == "insert" and d.fix.element == "preliminaryRqmts" and d.fix.position == "before"


def test_wrong_order_points_to_the_element_instead_of_inserting_another(check):
    main, close = _block(check.src, "mainProcedure"), _block(check.src, "closeRqmts")
    [d] = check(check.src.replace(main + close, close + main))
    assert d.category == "wrong-position" and d.fix is None
    assert "comes too early: <mainProcedure> (line" in d.message


def test_unknown_element_is_not_allowed(check):
    errs = check(check.src.replace("<mainProcedure>", "<mainProcedure><bogusThing/>", 1))
    assert errs[0].category == "not-allowed" and "not allowed inside <mainProcedure>" in errs[0].message


def test_missing_last_element_offers_insert_at_end(check):
    [d] = check(check.src.replace(_block(check.src, "closeRqmts"), ""))
    assert d.category == "missing-element" and d.fix.position == "end" and d.fix.element == "closeRqmts"


def test_every_diagnostic_has_a_category(check):
    for text in (check.src.replace('itemLocationCode="A"', 'itemLocationCode="Z"'),
                 check.src.replace("<dmodule", "<dmodule bogusAttr='1'", 1),
                 "<dmodule><unclosed></dmodule>"):
        for d in check(text):
            assert d.category and d.category != "other", d.message


def test_dtd_duplicate_id_names_both_places(ctx, tmp_path):
    from asthra.registry.dtd_builder import build_dtd_package
    from tests.conftest import FIX
    build_dtd_package(FIX / "dtd" / "ata-synth", "ATA2200", "t", tmp_path / "d.zip")
    ctx.registry.install(tmp_path / "d.zip")
    p = ctx.projects.create("a")
    src = (DOCS / "ata_cmm_valid.xml").read_text()
    keys = re.findall(r'key="([^"]+)"', src)
    assert len(keys) >= 2
    d = ctx.documents.import_bytes(p["id"], "dup.xml", src.replace(f'key="{keys[1]}"', f'key="{keys[0]}"', 1).encode())
    errs = [x for x in ctx.documents.validate(d["id"]).diagnostics if x.severity.value == "error"]
    dup = [x for x in errs if x.category == "duplicate-id"]
    assert len(dup) == 1 and f"'{keys[0]}': already used at line" in dup[0].message
    assert not any("already defined" in (x.raw_message or x.message) for x in errs)   # no second, vaguer report
