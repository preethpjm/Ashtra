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

    # ---- Stage 2: well-formedness
    tree, errors = parse_xml(data)
    if tree is None:
        if isinstance(errors, str):
            errors_iter = [(None, None, errors)]
        else:
            errors_iter = [(e.line, e.column, e.message) for e in errors]
        for line, col, msg in errors_iter:
            m = re.match(r"Entity '(\S+)' not defined", msg or "")
            sugg = None
            if m and not sn.doctype_name:
                sugg = (f"&{m[1]}; is a named entity, which is only allowed when the document has a DOCTYPE "
                        "pointing at the DTD that declares it. Add the DOCTYPE, or replace the entity with the character.")
            rep.diagnostics.append(Diagnostic(stage=Stage.PARSE, severity=Severity.FATAL, rule_id="XML-WF",
                                              message=msg, suggestion=sugg, source_file=file, line=line, column=col,
                                              reference="XML 1.0 well-formedness"))
        note = ""
        if sn.syntax_hint != "xml" and sn.doctype_name:
            note = "Possibly SGML: SGML parsing is Milestone 4 (OpenSP)."
        rep.stages.append(StageResult(stage=Stage.PARSE, status=Status.FAILED, note=note))
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
        if blocked or errs:
            if blocked:
                rep.diagnostics.append(Diagnostic(
                    stage=Stage.SCHEMA, severity=Severity.ERROR, rule_id="ASTHRA-SEC-003", source_file=file,
                    message="The document's DOCTYPE refers to a file that is not part of the installed schema package; it was not loaded.",
                    suggestion=f"{blocked}. If this is an entity set (e.g. the S1000D ISO entities), rebuild the package "
                               "with --entities <folder> so a local copy is used.", reference=ref))
            for e in errs:
                msg, sugg, attr, val, fix, _ = explain_dtd(e.message.strip(), None)
                rep.diagnostics.append(Diagnostic(
                    stage=Stage.SCHEMA, severity=Severity.ERROR, rule_id="XML-ENTITY", message=msg, source_file=file,
                    suggestion=sugg or "Declare the entity, or install the entity files with --entities.",
                    value=val, raw_message=e.message.strip(), line=e.line or None, reference=ref))
            rep.stages.append(StageResult(stage=Stage.SCHEMA, status=Status.FAILED, note="entities could not be resolved"))
            _skip_rest(rep, from_stage=Stage.BUSINESS_RULES, reason="schema stage failed")
            return rep, tree
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
    seen = set()
    for e in schema.error_log:
        path = _nice_path(tree, getattr(e, "path", None))
        key = (e.line, path, e.message)
        if key in seen:              # libxml2 sometimes repeats the same error
            continue
        seen.add(key)
        msg, sugg, attr, val, fix = explain(e.message)
        rep.diagnostics.append(Diagnostic(
            stage=Stage.SCHEMA, severity=Severity.ERROR, rule_id=f"XSD-{e.type_name}",
            message=msg, suggestion=sugg, attribute=attr, value=val, fix=fix, raw_message=e.message,
            source_file=file, element_path=path, line=e.line or None, column=e.column or None,
            reference=f"{pkg.manifest.standard} {pkg.manifest.issue} · {dt.schema_file}"))
    ok = _idref_check(tree, registry, package_id, doc_type_id, file, pkg, dt, rep) and ok
    _finish_schema_stage(ok, pkg, rep)
    return rep, tree


def _finish_schema_stage(ok: bool, pkg, rep: ValidationReport) -> None:
    note = ""
    if pkg.manifest.provenance == "synthetic":
        note = "Validated against a SYNTHETIC test schema, not an official issue of the standard."
    rep.stages.append(StageResult(stage=Stage.SCHEMA, status=Status.PASSED if ok else Status.FAILED, note=note))
    adapter = adapter_for(pkg.manifest.standard)
    for st, (ms, what) in PLANNED.items():
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
        if re.match(r"IDREFS? attribute", e.message.strip()):
            continue                 # references are checked by ASTHRA itself below (same on every platform)
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
    if not ref_attrs:
        return
    ids = set()
    for e in tree.iter():
        if isinstance(e.tag, str):
            for a in id_attrs.get(e.tag, ()):
                if e.get(a) is not None:
                    ids.add(e.get(a))
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
