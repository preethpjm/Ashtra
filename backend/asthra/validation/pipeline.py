"""Layered validation (spec §11). Stages 1–3 are implemented in Milestone 1.
Stages 4–7 are reported explicitly as not implemented — never as passed."""
from __future__ import annotations

import re

from lxml import etree

from ..identify.service import Sniff, parse_xml, sniff
from ..registry.service import RegistryError, SchemaRegistry
from ..standards.base import Cap
from ..standards.registry import adapter_for
from .explain import explain
from .model import Diagnostic, Severity, Stage, StageResult, Status, ValidationReport

PLANNED = {
    Stage.BUSINESS_RULES: (3, "BREX / Schematron / project rule packages"),
    Stage.REFERENCES: (5, "cross-document reference validation"),
    Stage.ENGINEERING: (6, "engineering coherence against authoritative source data"),
    Stage.AI_EXPLANATION: (7, "optional local AI explanation"),
}


def _stage1(data: bytes, sn: Sniff, file: str, max_bytes: int, rep: ValidationReport) -> bool:
    ok = True
    if len(data) == 0:
        rep.diagnostics.append(Diagnostic(stage=Stage.INTEGRITY, severity=Severity.FATAL, rule_id="ASTHRA-INT-001",
                                          message="File is empty.", source_file=file))
        ok = False
    if len(data) > max_bytes:
        rep.diagnostics.append(Diagnostic(stage=Stage.INTEGRITY, severity=Severity.FATAL, rule_id="ASTHRA-INT-002",
                                          message=f"File exceeds the configured limit of {max_bytes} bytes.",
                                          source_file=file))
        ok = False
    for p in sn.problems:
        rep.diagnostics.append(Diagnostic(stage=Stage.INTEGRITY, severity=Severity.ERROR, rule_id="ASTHRA-INT-003",
                                          message=p, source_file=file))
        ok = False
    if sn.encoding and ok:
        try:
            text = data.decode(sn.encoding)
            if sn.encoding.startswith("utf-8") and "\x00" in text:
                raise UnicodeError("NUL character in UTF-8 text")
        except (UnicodeError, LookupError) as e:
            rep.diagnostics.append(Diagnostic(
                stage=Stage.INTEGRITY, severity=Severity.FATAL, rule_id="ASTHRA-INT-004",
                message=f"Content is not valid {sn.encoding}: {e}", source_file=file,
                suggestion="Check the XML declaration's encoding against the actual file encoding."))
            ok = False
    if sn.has_internal_subset:
        rep.diagnostics.append(Diagnostic(
            stage=Stage.INTEGRITY, severity=Severity.INFO, rule_id="ASTHRA-SEC-001", source_file=file,
            message="Document has an internal DTD subset. Entities are recorded but never expanded "
                    "or fetched (external-entity protection)."))
    rep.stages.append(StageResult(stage=Stage.INTEGRITY, status=Status.PASSED if ok else Status.FAILED))
    return ok


def validate_bytes(data: bytes, file: str, registry: SchemaRegistry, package_id: str | None,
                   doc_type_id: str | None, max_bytes: int = 200 * 1024 * 1024,
                   sniffed: Sniff | None = None) -> tuple[ValidationReport, etree._ElementTree | None]:
    from .diagnostics import finalize
    rep, tree = _validate_bytes(data, file, registry, package_id, doc_type_id, max_bytes, sniffed)
    finalize(rep)
    return rep, tree


def _validate_bytes(data: bytes, file: str, registry: SchemaRegistry, package_id: str | None,
                    doc_type_id: str | None, max_bytes: int = 200 * 1024 * 1024,
                    sniffed: Sniff | None = None) -> tuple[ValidationReport, etree._ElementTree | None]:
    rep = ValidationReport(package_id=package_id)
    sn = sniffed or sniff(data)
    if not _stage1(data, sn, file, max_bytes, rep):
        _skip_rest(rep, from_stage=Stage.PARSE, reason="blocked by integrity failure")
        return rep, None

    # ---- SGML (e.g. legacy ATA iSpec 2200): parsed and validated together by OpenSP
    if sn.syntax_hint != "xml" and package_id and doc_type_id:
        try:
            _, spkg, sdt = registry.schema_for(package_id, doc_type_id)
        except RegistryError:
            spkg = sdt = None
        if sdt is not None and sdt.schema_kind == "sgml":
            return _sgml_stages(data, sn, file, registry, spkg, sdt, rep), None

    # ---- SGML whose DTD set is not installed or not chosen: never judged by the XML parser
    if sn.syntax_hint != "xml" and sn.doctype_name:
        probe_tree, _ = parse_xml(data)
        if probe_tree is None and _looks_sgml(data, sn):
            return _sgml_without_dtd(data, sn, file, rep), None

    # ---- SGML whose DTD is not installed (or not chosen): never checked as XML
    if sn.syntax_hint != "xml" and sn.doctype_name:
        probe_tree, _ = parse_xml(data)
        if probe_tree is None:
            return _sgml_without_dtd(data, sn, file, rep), None

    # ---- Stage 2: well-formedness
    tree, errors = parse_xml(data)
    if tree is None:
        if isinstance(errors, str):
            errors_iter = [(None, None, errors)]
        else:
            errors_iter = [(e.line, e.column, e.message) for e in errors]
        from .diagnostics import explain_well_formedness
        for line, col, msg in errors_iter:
            m = re.match(r"Entity '(\S+)' not defined", msg or "")
            raw_msg = msg
            msg, sugg = explain_well_formedness(msg or "")
            if m and not sn.doctype_name:
                sugg = (f"&{m[1]}; is a named entity, which is only allowed when the document has a DOCTYPE "
                        "pointing at the DTD that declares it. Add the DOCTYPE, or replace the entity with the character.")
            rep.diagnostics.append(Diagnostic(stage=Stage.PARSE, severity=Severity.FATAL, rule_id="XML-WF",
                                              category="not-well-formed", raw_message=raw_msg,
                                              message=msg, suggestion=sugg, source_file=file, line=line, column=col,
                                              reference="XML 1.0 well-formedness"))
        note = ""
        if sn.syntax_hint != "xml" and sn.doctype_name:
            note = "Possibly SGML: SGML parsing is Milestone 4 (OpenSP)."
        rep.stages.append(StageResult(stage=Stage.PARSE, status=Status.FAILED, note=note))
        if _partial_schema_check(data, errors_iter, registry, package_id, doc_type_id, file, rep):
            _skip_rest(rep, from_stage=Stage.BUSINESS_RULES, reason="document is not well-formed XML")
        else:
            _skip_rest(rep, from_stage=Stage.SCHEMA, reason="document is not well-formed XML")
        return rep, None
    rep.stages.append(StageResult(stage=Stage.PARSE, status=Status.PASSED))

    # ---- Stage 3: exact schema validation
    if not package_id or not doc_type_id:
        rep.stages.append(StageResult(stage=Stage.SCHEMA, status=Status.UNSUPPORTED,
                                      note="No installed schema package identified for this document."))
        _skip_rest(rep, from_stage=Stage.BUSINESS_RULES, reason="no schema")
        return rep, tree
    try:
        schema, pkg, dt = registry.schema_for(package_id, doc_type_id)
    except RegistryError as e:
        rep.diagnostics.append(Diagnostic(stage=Stage.SCHEMA, severity=Severity.ERROR, rule_id="ASTHRA-REG-001",
                                          message=str(e), source_file=file))
        rep.stages.append(StageResult(stage=Stage.SCHEMA, status=Status.FAILED, note="schema unavailable"))
        _skip_rest(rep, from_stage=Stage.BUSINESS_RULES, reason="schema unavailable")
        return rep, tree
    rep.package_checksum = pkg.checksum
    _chosen_schema_warning(tree, dt, pkg, file, rep)
    if dt.schema_kind == "dtd":
        ok = _dtd_stage(data, sn, tree, registry, pkg, dt, file, rep)
        _finish_schema_stage(ok, pkg, rep)
        return rep, tree
    # Documents whose DOCTYPE declares or imports entities (ISO entity sets, ICN notations...)
    # are validated in their expanded form, with entity files taken only from the package.
    if sn.has_internal_subset or any(isinstance(e, etree._Entity) for e in tree.iter()):
        from .dtd import entity_texts, explain_dtd
        from .entities import parse_with_entities
        roots, catalog = registry.dtd_context(pkg)
        expanded, errs, blocked = parse_with_entities(data, roots, catalog)
        ref = f"{pkg.manifest.standard} {pkg.manifest.issue} · {dt.schema_file}"
        # decided from the text itself: on some platforms the quick structural parse replaces
        # undeclared entity references with placeholders, so the tree cannot be trusted for this
        uses_entities = _uses_entities(data, sn)
        if blocked and not errs and not uses_entities:
            # typical S1000D boilerplate (%ISOEntities; pointing at ent/ISOEntities) in a document that
            # uses no entity at all: nothing depends on the missing file, so validation continues
            rep.diagnostics.append(Diagnostic(
                stage=Stage.SCHEMA, severity=Severity.WARNING, rule_id="ASTHRA-ENT-001", source_file=file,
                category="entity-set-missing",
                message="The DOCTYPE refers to an entity set that is not installed; the document uses none of its "
                        "entities, so it was validated without it.",
                suggestion=f"{blocked}. To install the entity files, add the schemas again from the issue folder "
                           "(Schemas → Manage → Choose folder…): the entity folder is found automatically.",
                reference=ref))
            blocked = None
            expanded = tree
        if blocked or errs:
            if blocked:
                rep.diagnostics.append(Diagnostic(
                    stage=Stage.SCHEMA, severity=Severity.ERROR, rule_id="ASTHRA-SEC-003", source_file=file,
                    category="entity-set-missing",
                    message="The document uses entities from a file that is not part of the installed schema package "
                            "(for S1000D usually the ISO entity set); it was not loaded, so the document cannot be validated.",
                    suggestion=f"{blocked}. Add the schemas again from the whole issue folder (Schemas → Manage → Choose "
                               "folder…): the ISO entity folder is found and bundled automatically. On the command line: "
                               "add-schemas \"<issue folder>\" --replace.", reference=ref))
            for e in errs:
                msg, sugg, attr, val, fix, _ = explain_dtd(e.message.strip(), None)
                rep.diagnostics.append(Diagnostic(
                    stage=Stage.SCHEMA, severity=Severity.ERROR, rule_id="XML-ENTITY", message=msg, source_file=file,
                    suggestion=sugg or "Declare the entity, or install the entity files with --entities.",
                    value=val, raw_message=e.message.strip(), line=e.line or None, reference=ref))
            rep.stages.append(StageResult(stage=Stage.SCHEMA, status=Status.FAILED, note="entities could not be resolved"))
            _skip_rest(rep, from_stage=Stage.BUSINESS_RULES, reason="schema stage failed")
            return rep, tree
        if expanded is not tree:
            rep.entities = entity_texts(expanded.docinfo.internalDTD)
        tree = expanded
    try:
        ok = schema.validate(tree)
    except etree.XMLSchemaValidateError as e:
        rep.diagnostics.append(Diagnostic(stage=Stage.SCHEMA, severity=Severity.FATAL, rule_id="ASTHRA-XSD-INTERNAL",
                                          message=f"Schema validator could not process this document: {e}",
                                          source_file=file))
        rep.stages.append(StageResult(stage=Stage.SCHEMA, status=Status.FAILED))
        _skip_rest(rep, from_stage=Stage.BUSINESS_RULES, reason="schema stage failed")
        return rep, tree
    from .diagnostics import ModelHelper
    from .partial import continue_after_skips
    helper = ModelHelper(registry, package_id, doc_type_id)
    entries = list(schema.error_log)
    # libxml2 stops checking an element's remaining content at the first element it does not expect;
    # validate those skipped parts too, so every error is reported (as Xerces does)
    entries += continue_after_skips(schema, tree, data, entries)
    if entries:
        ok = False
    _xsd_diagnostics(entries, tree, helper, pkg, dt, file, rep)
    from .diagnostics import document_duplicate_ids
    reported = {(d.value, d.line) for d in rep.diagnostics if d.category == "duplicate-id"}
    extra = document_duplicate_ids(tree, helper, reported, file, f"{pkg.manifest.standard} {pkg.manifest.issue} · {dt.schema_file}")
    rep.diagnostics.extend(extra)
    ok = not extra and ok
    ok = _idref_check(tree, registry, package_id, doc_type_id, file, pkg, dt, rep) and ok
    _finish_schema_stage(ok, pkg, rep, tree, registry, file, dt)
    return rep, tree


def _xsd_diagnostics(entries, tree, helper, pkg, dt, file: str, rep: ValidationReport, note: str = "") -> None:
    """Schema errors → precise diagnostics (explanations, missing/wrong position/not allowed, duplicate IDs)."""
    from .diagnostics import duplicate_of, refine_missing_child, refine_not_expected
    from .explain import _MISSING_CHILD, _NOT_EXPECTED, _names
    seen = set()
    for e in entries:
        path = _nice_path(tree, getattr(e, "path", None))
        key = (e.line, path, e.message)
        if key in seen:              # libxml2 sometimes repeats the same error
            continue
        seen.add(key)
        msg, sugg, attr, val, fix = explain(e.message)
        rule, category = f"XSD-{e.type_name}", None
        node = getattr(e, "node", None)             # the xmlschema engine hands over the element itself
        if node is None:
            try:
                hit = tree.xpath(e.path) if getattr(e, "path", None) else []
                node = hit[0] if hit and isinstance(hit[0], etree._Element) else None
            except etree.XPathError:
                node = None
        if node is not None:
            if attr and val is not None and "'xs:ID'" in e.message:
                first = duplicate_of(node, attr, val)
                if first is not None:
                    ln = etree.QName(node).localname
                    fl = etree.QName(first).localname
                    msg = (f"Duplicate ID '{val}': already used at line {first.sourceline} on <{fl}>; "
                           f"used again here on <{ln}>.")
                    sugg = "IDs must be unique within the document. Give one of them a new ID and update any references to it."
                    rule, category, fix = "ASTHRA-DUPLICATE-ID", "duplicate-id", None
            elif (m := _NOT_EXPECTED.search(e.message)):
                r = refine_not_expected(node, _names(m.group("exp") or ""), helper)
                if r:
                    msg, sugg, fix, category = r
            elif (m := _MISSING_CHILD.search(e.message)):
                r = refine_missing_child(node, _names(m.group("exp")), helper)
                if r:
                    msg, sugg, fix, category = r
        rep.diagnostics.append(Diagnostic(
            stage=Stage.SCHEMA, severity=Severity.ERROR, rule_id=rule, category=category,
            message=msg + note, suggestion=sugg, attribute=attr, value=val, fix=fix, raw_message=e.message,
            source_file=file, element_path=path, line=e.line or None, column=e.column or None,
            reference=f"{pkg.manifest.standard} {pkg.manifest.issue} · {dt.schema_file}"))


def _finish_schema_stage(ok: bool, pkg, rep: ValidationReport, tree=None, registry=None, file: str = "",
                         dt=None) -> None:
    note = ""
    if pkg.manifest.provenance == "synthetic":
        note = "Validated against a SYNTHETIC test schema, not an official issue of the standard."
    rep.stages.append(StageResult(stage=Stage.SCHEMA, status=Status.PASSED if ok else Status.FAILED, note=note))
    adapter = adapter_for(pkg.manifest.standard)
    for st, (ms, what) in PLANNED.items():
        if st == Stage.BUSINESS_RULES and tree is not None and getattr(registry, "brex", None) is not None \
                and pkg.manifest.standard.upper() == "S1000D":
            _brex_stage(tree, registry.brex, pkg, dt, file, rep)
            continue
        cap_note = ""
        if st == Stage.BUSINESS_RULES and adapter and adapter.capabilities.get(Cap.VALIDATE_RULES):
            cap_note = f" ({adapter.capabilities[Cap.VALIDATE_RULES].note})"
        rep.stages.append(StageResult(stage=st, status=Status.NOT_IMPLEMENTED,
                                      note=f"{what}{cap_note} — Milestone {ms}"))


def _chosen_schema_warning(tree, dt, pkg, file: str, rep: ValidationReport) -> None:
    """If the document does not itself declare the schema it is validated against (it was
    chosen by the user), say so on every run so results are never mistaken for the declared one."""
    from ..identify.service import XSI, declares
    root = tree.getroot()
    if declares(dt, root, pkg.manifest.standard, pkg.manifest.issue):
        return
    info = tree.docinfo
    declared = root.get(f"{{{XSI}}}noNamespaceSchemaLocation") or root.get(f"{{{XSI}}}schemaLocation") \
        or info.public_id or info.system_url
    rep.diagnostics.append(Diagnostic(
        stage=Stage.SCHEMA, severity=Severity.WARNING, rule_id="ASTHRA-SCHEMA-CHOSEN", source_file=file,
        message=f"Validated against {pkg.manifest.standard} {pkg.manifest.issue} ({dt.label}), chosen by you. "
                + (f"The document itself declares '{declared}'." if declared else "The document does not declare a schema."),
        suggestion="Results reflect the chosen schema, not necessarily the one the document was written for."))


def _dtd_stage(data: bytes, sn, tree, registry, pkg, dt, file: str, rep: ValidationReport) -> bool:
    from .dtd import entity_texts, explain_dtd, validate_dtd
    text = data.decode(sn.encoding or "utf-8", errors="strict")
    root = tree.getroot()
    qname = f"{root.prefix}:{etree.QName(root).localname}" if root.prefix else etree.QName(root).localname
    roots, catalog = registry.dtd_context(pkg)
    vtree, entries, dtd, blocked = validate_dtd(text, qname, roots, catalog, dt.schema_file)
    ref = f"{pkg.manifest.standard} {pkg.manifest.issue} · {dt.schema_file}"
    if blocked:
        rep.diagnostics.append(Diagnostic(
            stage=Stage.SCHEMA, severity=Severity.ERROR, rule_id="ASTHRA-SEC-003", source_file=file,
            message="The document tries to load a file that is not part of the installed schema package; it was blocked.",
            suggestion=blocked, reference=ref))
        return False
    rep.entities = entity_texts(dtd)
    before = len(rep.diagnostics)
    seen = set()
    for e in entries:
        key = (e.line, e.message)
        if key in seen:
            continue
        seen.add(key)
        if re.match(r"IDREFS? attribute", e.message.strip()) or re.match(r"ID \S+ already defined", e.message.strip()):
            continue                 # references and duplicate IDs are checked by ASTHRA itself below
        msg, sugg, attr, val, fix, elname = explain_dtd(e.message.strip(), dtd)
        rep.diagnostics.append(Diagnostic(
            stage=Stage.SCHEMA, severity=Severity.ERROR, rule_id=f"DTD-{e.type_name}", message=msg,
            suggestion=sugg, attribute=attr, value=val, fix=fix, raw_message=e.message.strip(), source_file=file,
            element_path=_locate(tree, e.line, elname, attr, val), line=e.line or None, reference=ref))
    _dtd_idrefs(vtree, dtd, file, ref, rep)
    return len(rep.diagnostics) == before          # passed only if the DTD reported no errors


def _dtd_idrefs(tree, dtd, file: str, ref: str, rep: ValidationReport) -> None:
    """ID/IDREF integrity from the DTD's own attribute declarations. libxml2 reports this
    only on some builds, so ASTHRA checks it directly, like the XSD path does."""
    if tree is None or dtd is None:
        return
    id_attrs, ref_attrs = {}, {}
    for el in dtd.iterelements():
        for a in el.iterattributes():
            if a.type == "id":
                id_attrs.setdefault(el.name, []).append(a.name)
            elif a.type in ("idref", "idrefs"):
                ref_attrs.setdefault(el.name, []).append(a.name)
    ids: dict[str, object] = {}
    for e in tree.iter():
        if isinstance(e.tag, str):
            for a in id_attrs.get(e.tag, ()):
                v = e.get(a)
                if v is None:
                    continue
                if v in ids:
                    first = ids[v]
                    rep.diagnostics.append(Diagnostic(
                        stage=Stage.SCHEMA, severity=Severity.ERROR, rule_id="ASTHRA-DUPLICATE-ID", category="duplicate-id",
                        message=(f"Duplicate ID '{v}': already used at line {first.sourceline} on <{first.tag}>; "
                                 f"used again here on <{e.tag}>."),
                        suggestion="IDs must be unique within the document. Give one of them a new ID and update any references to it.",
                        attribute=a, value=v, source_file=file, element_path=readable_path(e), line=e.sourceline, reference=ref))
                else:
                    ids[v] = e
    for e in tree.iter():
        if not isinstance(e.tag, str):
            continue
        for a in ref_attrs.get(e.tag, ()):
            for v in (e.get(a) or "").split():
                if v not in ids:
                    rep.diagnostics.append(Diagnostic(
                        stage=Stage.SCHEMA, severity=Severity.ERROR, rule_id="DTD-IDREF",
                        message=f"Reference '{v}' (attribute {a}) does not match any ID in this document.",
                        suggestion="Correct the reference or add the referenced element.", attribute=a, value=v,
                        source_file=file, element_path=readable_path(e), line=e.sourceline, reference=ref))


def _locate(tree, line: int | None, elname: str | None, attr: str | None, val: str | None) -> str | None:
    """Best element for a DTD error (libxml2 gives only a line): the named element that starts
    on that line, else the last one opened before it; for references, the element holding the value."""
    if not line:
        return None
    els = [e for e in tree.iter() if isinstance(e.tag, str) and e.sourceline and e.sourceline <= line]
    if attr and val:
        hit = [e for e in els if e.sourceline == line and e.get(attr) == val] or \
              [e for e in els if e.get(attr) == val]
        if hit:
            return readable_path(hit[-1])
    if elname:
        local = elname.split(":")[-1]
        same = [e for e in els if etree.QName(e).localname == local]
        exact = [e for e in same if e.sourceline == line]
        pick = (exact or same)
        if pick:
            return readable_path(pick[-1] if not exact else exact[0])
    on_line = [e for e in els if e.sourceline == line]
    return readable_path(on_line[0]) if on_line else None


def _skip_rest(rep: ValidationReport, from_stage: Stage, reason: str) -> None:
    for st in Stage:
        if st >= from_stage and not any(s.stage == st for s in rep.stages):
            rep.stages.append(StageResult(stage=st, status=Status.NOT_RUN, note=reason))


def readable_path(el) -> str:
    """/local/names[n] path; positions counted among same-name siblings."""
    parts = []
    while el is not None and isinstance(el.tag, str):
        q = etree.QName(el)
        parent = el.getparent()
        if parent is None:
            parts.append(q.localname)
        else:
            same = [c for c in parent if isinstance(c.tag, str) and c.tag == el.tag]
            parts.append(f"{q.localname}[{same.index(el) + 1}]" if len(same) > 1 else q.localname)
        el = parent
    return "/" + "/".join(reversed(parts))


def _nice_path(tree, raw: str | None) -> str | None:
    """libxml2 reports /*/*[3]/*[2] for namespaced documents; make it readable."""
    if not raw:
        return None
    try:
        hit = tree.xpath(raw)
        if hit and isinstance(hit[0], etree._Element):
            return readable_path(hit[0])
    except etree.XPathError:
        pass
    return raw


_IDREF = re.compile(r"IDREF '([^']+)' not found")


def _idref_check(tree, registry, key, dt_id, file, pkg, dt, rep: ValidationReport) -> bool:
    """Deterministic ID/IDREF integrity within one document."""
    try:
        checker = registry.identity_checker(key, dt_id)
    except Exception as e:  # never silently pass: surface why the check could not run
        rep.diagnostics.append(Diagnostic(stage=Stage.SCHEMA, severity=Severity.WARNING,
                                          rule_id="ASTHRA-IDREF-UNAVAILABLE", source_file=file,
                                          message=f"ID/IDREF integrity check could not run: {e}"))
        return True
    ok = True
    for err in checker.iter_errors(tree):
        m = _IDREF.search(err.reason or "")
        if not m:
            continue   # all other constraints are already reported by the primary validator
        ok = False
        missing = m.group(1)
        hits = [(el, a) for el in tree.iter() if isinstance(el.tag, str)
                for a, v in el.attrib.items() if missing in v.split()]
        for el, attr in hits or [(tree.getroot(), None)]:
            where = f" (attribute {etree.QName(attr).localname})" if attr else ""
            rep.diagnostics.append(Diagnostic(
                stage=Stage.SCHEMA, severity=Severity.ERROR, rule_id="XSD-IDREF",
                message=f"Reference '{missing}'{where} does not match any ID in this document.",
                attribute=etree.QName(attr).localname if attr else None, value=missing,
                source_file=file, element_path=readable_path(el), line=el.sourceline,
                suggestion="Correct the reference or add the referenced element.",
                reference=f"{pkg.manifest.standard} {pkg.manifest.issue} · {dt.schema_file} · xs:IDREF"))
    return ok


def _sgml_stages(data: bytes, sn, file: str, registry, pkg, dt, rep: ValidationReport) -> ValidationReport:
    from .sgml import OPEN_SP_HELP, explain_sgml, find_tools, run
    tools = find_tools()
    ref = f"{pkg.manifest.standard} {pkg.manifest.issue} · {dt.schema_file}"
    rep.package_checksum = pkg.checksum
    if not tools:
        rep.stages.append(StageResult(stage=Stage.PARSE, status=Status.UNSUPPORTED, note="OpenSP is not installed"))
        rep.diagnostics.append(Diagnostic(stage=Stage.PARSE, severity=Severity.ERROR, rule_id="ASTHRA-SGML-001",
                                          source_file=file, message="This is an SGML document; validating and rendering "
                                          "SGML needs OpenSP, which was not found.", suggestion=OPEN_SP_HELP))
        _skip_rest(rep, from_stage=Stage.SCHEMA, reason="OpenSP not installed")
        return rep
    text = data.decode(sn.encoding or "utf-8", errors="replace")
    from .sgml import SgmlToolError
    try:
        res = run(text, dt.match.local_name, pkg.path, dt.schema_file, pkg.manifest.sgml.get("catalogs", []),
                  pkg.manifest.sgml.get("declaration"), tools)
    except SgmlToolError as e:
        # OpenSP did not run, so nothing was checked: this must never read as "passed"
        rep.stages.append(StageResult(stage=Stage.PARSE, status=Status.FAILED, note="OpenSP could not run"))
        rep.diagnostics.append(Diagnostic(stage=Stage.PARSE, severity=Severity.ERROR, rule_id="ASTHRA-SGML-002",
                                          source_file=file, message="The document was NOT checked: OpenSP could not run.",
                                          suggestion=f"{e} Check it with: python -m asthra.cli doctor. {OPEN_SP_HELP}"))
        _skip_rest(rep, from_stage=Stage.SCHEMA, reason="OpenSP could not run")
        return rep
    rep.rendered_xml = res.xml
    rep.entities = res.entities
    from .sgml import doctype_ids
    _, doc_pub, _ = doctype_ids(text)
    sg = pkg.manifest.sgml or {}
    if doc_pub and doc_pub in (sg.get("aliases") or []):
        rep.diagnostics.append(Diagnostic(
            stage=Stage.SCHEMA, severity=Severity.WARNING, rule_id="ASTHRA-SGML-ALIAS", category="version-alias",
            source_file=file, reference=ref,
            message=f"The document declares '{doc_pub}' but was validated with {pkg.manifest.standard} "
                    f"{pkg.manifest.issue} ({dt.schema_file}), which was set to accept it when installed.",
            suggestion="Errors can come from differences between the two DTD versions. Install the DTD version the "
                       "document declares to validate it exactly."))
    if sg.get("placeholders"):
        rep.diagnostics.append(Diagnostic(
            stage=Stage.SCHEMA, severity=Severity.WARNING, rule_id="ASTHRA-SGML-004", category="dtd-incomplete",
            source_file=file, reference=ref,
            message="The installed DTD set is incomplete: " + ", ".join(sg["placeholders"])
                    + " was not supplied (an empty placeholder is used).",
            suggestion="Entities defined in it are reported as undefined where used. Add the real file and install "
                       "the DTD set again."))
    if res.removed_urls:
        rep.diagnostics.append(Diagnostic(stage=Stage.INTEGRITY, severity=Severity.WARNING, rule_id="ASTHRA-SEC-004",
                                          source_file=file, message=f"{res.removed_urls} remote address(es) in the DOCTYPE "
                                          "were ignored; ASTHRA never goes online.", reference=ref))
    rep.stages.append(StageResult(stage=Stage.PARSE, status=Status.PASSED, note="parsed as SGML by OpenSP"))
    errors = 0
    for line, col, typ, msg in res.messages:
        # OpenSP reports an undeclared entity three times; keep the clear "not defined" message
        if msg.startswith("cannot generate system identifier for general entity") or \
                re.match(r'reference to entity "\S+" for which no system identifier could be generated', msg):
            continue
        sev = Severity.ERROR if typ in "EX" else Severity.WARNING
        if msg.startswith("cannot find") and line is not None:
            m, sugg, attr, val, fix = explain_sgml(msg)
            rule = "ASTHRA-SEC-003"
        else:
            m, sugg, attr, val, fix = explain_sgml(msg)
            rule = "SGML-" + {"E": "ERROR", "X": "REFERENCE", "W": "WARNING", "Q": "QUERY"}[typ]
        if sev == Severity.ERROR:
            errors += 1
        # one-click fixes edit XML; for SGML the suggestion is shown instead
        rep.diagnostics.append(Diagnostic(stage=Stage.SCHEMA, severity=sev, rule_id=rule, message=m, suggestion=sugg,
                                          attribute=attr, value=val, fix=None, raw_message=msg, source_file=file,
                                          line=line, column=col, reference=ref))
    _finish_schema_stage(errors == 0, pkg, rep)
    return rep


def _looks_sgml(data: bytes, sn) -> bool:
    """An SGML document (not broken XML): no XML declaration, and SGML-only syntax such as an
    external identifier without a system literal, SDATA/NDATA-without-quotes entity declarations,
    omitted end tags or upper-case markup."""
    head = data[:200000].decode(sn.encoding or "utf-8", errors="replace")
    if head.lstrip("\ufeff").startswith("<?xml"):
        return False
    return bool(re.search(r"<!DOCTYPE\s+\S+\s+PUBLIC\s+(\"[^\"]*\"|'[^']*')\s*[\[>]", head, re.I)
                or re.search(r"<!ENTITY\s+\S+\s+(SDATA|CDATA|STARTTAG|ENDTAG)\b", head)
                or re.search(r"<[A-Z][A-Z0-9]+[\s>]", head))


def _sgml_without_dtd(data: bytes, sn, file: str, rep: ValidationReport) -> ValidationReport:
    from .sgml_preview import preview
    text = data.decode(sn.encoding or "utf-8", errors="replace")
    m = re.search(r"<!DOCTYPE\s+([^\s\[>]+)(?:\s+PUBLIC\s+(\"[^\"]*\"|'[^']*'))?", text, re.I)
    name = m.group(1) if m else "?"
    pub = m.group(2)[1:-1] if m and m.group(2) else None
    rep.stages.append(StageResult(stage=Stage.PARSE, status=Status.UNSUPPORTED,
                                  note="SGML: its DTD set is not installed or not selected"))
    rep.diagnostics.append(Diagnostic(
        stage=Stage.PARSE, severity=Severity.WARNING, rule_id="ASTHRA-SGML-003", category="other", source_file=file,
        message=(f"This SGML document was NOT validated: its DTD set is not installed or not selected "
                 f"(DOCTYPE <{name}>" + (f", public identifier \"{pub}\"" if pub else "") + ")."),
        suggestion=("Install that DTD set (Schemas \u2192 Manage \u2192 Choose folder\u2026), or choose an installed one in the "
                    "panel on the right. SGML is validated and edited with its DTD, through OpenSP.")))
    try:
        pv = preview(text)
    except Exception as e:                                  # noqa: BLE001 - a preview is optional
        pv = None
        rep.diagnostics.append(Diagnostic(stage=Stage.PARSE, severity=Severity.INFO, rule_id="ASTHRA-SGML-004",
                                          source_file=file, message=f"No preview could be built: {e}"))
    if pv is not None and pv.xml:
        rep.rendered_xml, rep.rendered_preview, rep.entities = pv.xml, True, pv.entities
        how = ("every element is closed in the file, so the structure is exact"
               if pv.mode == "normalized" and pv.implied_ends == 0 else
               f"{pv.implied_ends} end tags were left out in the file and were placed by rule, so the structure may be approximate")
        rep.diagnostics.append(Diagnostic(
            stage=Stage.PARSE, severity=Severity.INFO, rule_id="ASTHRA-SGML-004", category="other", source_file=file,
            message=f"Showing a read-only preview built without the DTD: {how}.",
            suggestion=("Treated as empty elements because they are never closed: " + ", ".join(f"<{x}>" for x in pv.empty_types[:12])
                        + ("…" if len(pv.empty_types) > 12 else "") + ".") if pv.empty_types else None))
    _skip_rest(rep, from_stage=Stage.SCHEMA, reason="SGML DTD set not installed or not selected")
    return rep


def _sgml_without_dtd(data: bytes, sn, file: str, rep: ValidationReport) -> ValidationReport:
    """An SGML document with no installed DTD set chosen: say clearly that it was not validated,
    and offer a preview built from a DTD inferred from its own tags (display only)."""
    from .sgml import OPEN_SP_HELP, SgmlToolError, doctype_ids, find_tools, preview
    text = data.decode(sn.encoding or "utf-8", errors="replace")
    name, pub, sysid = doctype_ids(text)
    what = f"'{pub}'" if pub else (f"'{sysid}'" if sysid else f"for DOCTYPE <{name}>")
    rep.stages.append(StageResult(stage=Stage.PARSE, status=Status.NOT_RUN, note="SGML: DTD not installed"))
    rep.stages.append(StageResult(stage=Stage.SCHEMA, status=Status.UNSUPPORTED, note="no installed SGML DTD set"))
    _skip_rest(rep, from_stage=Stage.BUSINESS_RULES, reason="not validated")
    rep.diagnostics.append(Diagnostic(
        stage=Stage.SCHEMA, severity=Severity.ERROR, rule_id="ASTHRA-SGML-003", category="schema-not-installed",
        source_file=file,
        message=f"This SGML document was NOT validated: its DTD {what} is not installed.",
        suggestion=("Install the DTD set that provides it (Schemas → Manage → Choose folder…, pick the folder with the "
                    ".dtd, entity files and catalog), then reopen the document. If an installed DTD set is listed on "
                    "the right as compatible, you can choose it instead; results then only mean something if it is "
                    "the same DTD.")))
    tools = find_tools()
    if not tools:
        rep.diagnostics.append(Diagnostic(stage=Stage.PARSE, severity=Severity.WARNING, rule_id="ASTHRA-SGML-001",
                                          source_file=file, message="A preview needs OpenSP, which was not found.",
                                          suggestion=OPEN_SP_HELP))
        return rep
    try:
        res = preview(text, name, tools)
    except SgmlToolError as e:
        rep.diagnostics.append(Diagnostic(stage=Stage.PARSE, severity=Severity.WARNING, rule_id="ASTHRA-SGML-002",
                                          source_file=file, message=f"No preview: OpenSP could not run ({e})."))
        return rep
    rep.rendered_xml, rep.entities, rep.render_note = res.xml, res.entities, res.note
    return rep


_PREDEFINED = {"amp", "lt", "gt", "quot", "apos"}


def _uses_entities(data: bytes, sn) -> bool:
    """Does the document body (after the DOCTYPE) reference any named entity other than XML's own?"""
    text = data.decode(sn.encoding or "utf-8", errors="replace")
    m = re.search(r"<!DOCTYPE", text, re.I)
    if m:
        depth, q, i = 0, "", m.end()
        while i < len(text):
            c = text[i]
            if q:
                if c == q:
                    q = ""
            elif c in "\"'":
                q = c
            elif c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
            elif c == ">" and depth <= 0:
                break
            i += 1
        text = text[i + 1:]
    text = re.sub(r"<!--.*?-->|<!\[CDATA\[.*?\]\]>", " ", text, flags=re.S)
    return any(n not in _PREDEFINED for n in re.findall(r"&([A-Za-z_:][\w.:-]*);", text))



def _partial_schema_check(data: bytes, errors_iter, registry, package_id, doc_type_id, file: str,
                          rep: ValidationReport) -> bool:
    """A document that is not well-formed is still checked against its schema up to the point where it
    breaks (as a streaming validator does). True if the schema stage was recorded."""
    if not package_id or not doc_type_id:
        return False
    try:
        schema, pkg, dt = registry.schema_for(package_id, doc_type_id)
    except RegistryError:
        return False
    if dt.schema_kind != "xsd":
        return False
    from .diagnostics import ModelHelper
    from .partial import partial_check
    lines = [l for l, _, _ in errors_iter if l]
    break_line = min(lines) if lines else None
    entries, tree = partial_check(schema, data, break_line)
    if tree is None:
        return False
    where = f" (found before the file breaks off at line {break_line})" if break_line else ""
    _xsd_diagnostics(entries, tree, ModelHelper(registry, package_id, doc_type_id), pkg, dt, file, rep, note=where)
    rep.stages.append(StageResult(stage=Stage.SCHEMA, status=Status.FAILED if entries else Status.NOT_RUN,
                                  note=f"checked only up to line {break_line}, where the file is not well-formed"
                                  if break_line else "partial check"))
    return True



def _brex_stage(tree, library, pkg, dt, file: str, rep: ValidationReport) -> None:
    """Stage 4: the document against the BREX it names (brexDmRef) and every BREX that one builds on."""
    from ..brex.engine import Result, document_brex_ref
    from ..brex.model import XSI
    from .diagnostics import _local
    root = tree.getroot()
    if _local(root) not in ("dmodule", "pm"):
        rep.stages.append(StageResult(stage=Stage.BUSINESS_RULES, status=Status.NOT_RUN,
                                      note="BREX applies to S1000D data modules and publication modules"))
        return
    named = document_brex_ref(root)
    start, how = named, "named by the document (brexDmRef)"
    if not named:
        d = library.default_for(pkg.manifest.issue)
        if d is None:
            rep.stages.append(StageResult(stage=Stage.BUSINESS_RULES, status=Status.NOT_RUN,
                                          note=f"the document names no BREX, and no default BREX for S1000D {pkg.manifest.issue} is installed"))
            return
        start, how = d["dmc"], f"the S1000D {pkg.manifest.issue} default BREX (the document names none)"
    chain, missing = library.chain(start)
    if missing:
        first = not chain
        rep.diagnostics.append(Diagnostic(
            stage=Stage.BUSINESS_RULES, severity=Severity.WARNING, rule_id="ASTHRA-BREX-MISSING", category="brex-missing",
            value=missing, source_file=file,
            message=(f"Business rules not checked: the BREX DMC-{missing} is not installed." if first else
                     f"Business rules only partly checked: DMC-{missing}, which DMC-{chain[-1]['dmc']} builds on, is not installed."),
            suggestion="Add the BREX file, or choose an installed BREX to use instead (“Add or choose BREX…”, or Schemas → Manage → BREX). The document is checked again right away."))
        if first:
            rep.stages.append(StageResult(stage=Stage.BUSINESS_RULES, status=Status.NOT_RUN, note=f"BREX DMC-{missing} not installed"))
            return
    dm_type = (root.get(f"{XSI}noNamespaceSchemaLocation") or (dt.schema_file if dt else "") or "").replace("\\", "/").split("/")[-1] or None
    result = Result()
    for e in chain:
        if e.get("substitute_for"):
            rep.diagnostics.append(Diagnostic(
                stage=Stage.BUSINESS_RULES, severity=Severity.WARNING, rule_id="ASTHRA-BREX-SUBSTITUTE", category="brex-substitute",
                source_file=file, value=e["substitute_for"],
                message=f"Business rules checked with DMC-{e['dmc']} instead of DMC-{e['substitute_for']}, which is not installed "
                        "(a substitute you chose).",
                suggestion="Results reflect the substitute, not necessarily the document's own BREX. Change or remove the "
                           "substitute under Schemas → Manage → BREX, or add the real BREX."))
        if e.get("schema_issue") and e["schema_issue"] != pkg.manifest.issue:
            rep.diagnostics.append(Diagnostic(
                stage=Stage.BUSINESS_RULES, severity=Severity.WARNING, rule_id="ASTHRA-BREX-ISSUE", category="brex-issue",
                source_file=file, value=e["dmc"],
                message=f"The BREX DMC-{e['dmc']} was written for S1000D {e['schema_issue']}; this document is S1000D {pkg.manifest.issue}.",
                suggestion="Rules about elements that differ between the issues may not apply as intended. Check which issue the project requires."))
        library.compiled(e).check(root, dm_type, result)
    for f in result.findings:
        text = re.sub(r"^\s*" + re.escape(f.rule.rule_id) + r"\s*(\([^)]*\))?\s*:\s*", "", f.rule.use) or f.rule.use
        rep.diagnostics.append(Diagnostic(
            stage=Stage.BUSINESS_RULES, severity=Severity.ERROR, rule_id=f.rule.rule_id, category="business-rule",
            message=text + (f" — {f.detail}" if f.detail and f.detail not in text else ""),
            suggestion=f"Business rule from {f.brex.title or 'BREX'} (DMC-{f.brex.dmc}, issue {f.brex.issue}).",
            source_file=file, line=f.line, element_path=readable_path(f.element) if f.element is not None else None,
            reference=f"BREX DMC-{f.brex.dmc} issue {f.brex.issue}"))
    if result.not_checked:
        ids = ", ".join(r.rule_id for r, _ in result.not_checked[:5])
        rep.diagnostics.append(Diagnostic(
            stage=Stage.BUSINESS_RULES, severity=Severity.WARNING, rule_id="ASTHRA-BREX-NOT-CHECKED", category="brex-not-checked",
            source_file=file,
            message=f"{len(result.not_checked)} business rule(s) could not be evaluated and were NOT checked.",
            suggestion=f"First: {ids}{' …' if len(result.not_checked) > 5 else ''}. Their paths use expressions ASTHRA cannot evaluate yet."))
    names = " → ".join(f"DMC-{e['dmc']}" + (f" (instead of DMC-{e['substitute_for']})" if e.get("substitute_for") else "") for e in chain)
    note = f"{result.checked} rules checked ({how}): {names}"
    if missing:
        note += f"; DMC-{missing} missing"
    if result.not_checked:
        note += f"; {len(result.not_checked)} not checked"
    rep.stages.append(StageResult(stage=Stage.BUSINESS_RULES, status=Status.FAILED if result.findings else Status.PASSED, note=note))
