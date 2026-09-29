"""One installer for every kind of schema source (spec §4, §5).

inspect(folder) looks at an unpacked folder or zip and proposes what to install:
  * "package"  an ASTHRA package (asthra-package.json) -> install as is
  * "s1000d"   S1000D XSDs (schema annotations declare issue and root element); when the
               download holds several copies (original release, patches, data dictionary)
               every copy is offered, the latest patch preselected; ISO entity folders found
               alongside are offered too
  * "dtd"      DTDs (+ .ent/.mod + catalogs): ATA iSpec 2200 / ATA Spec 2300 / OEM
  * "xsd"      any other XSD set (S2000M, S3000L, OEM): document types are the global
               elements that no other element uses, in schemas no other schema includes
build(folder, choices) builds the package the user confirmed and returns its zip path.
Nothing is guessed silently: every value the user must decide is marked as required.
"""
from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path

from lxml import etree

from ..security.xml_safe import document_parser
from .builder import BuildError, build_s1000d_package, declared_issue
from .dtd_builder import build_dtd_package, dtd_roots, read_catalogs

XS = "{http://www.w3.org/2001/XMLSchema}"
SCHEMA_EXT = {".xsd", ".dtd", ".ent", ".mod", ".elm", ".cat", ".soc", ".dcl", ".decl"}
KNOWN_STANDARDS = ["S1000D", "S2000M", "S3000L", "S4000P", "S5000F", "S6000T", "ATA2200", "ATA2300", "OEM"]


def wanted(rel: str, size: int) -> bool:
    """Files worth uploading/keeping from a schema download (never manuals, images, PDFs)."""
    name = rel.replace("\\", "/").rsplit("/", 1)[-1]
    low = name.lower()
    if low in ("isoentities", "catalog", "asthra-package.json"):
        return True
    ext = Path(low).suffix
    if ext in SCHEMA_EXT:
        return size <= 20 * 1024 * 1024
    return ext == ".xml" and "catalog" in low and size <= 2 * 1024 * 1024


def new_staging(root: Path) -> tuple[str, Path]:
    sid = uuid.uuid4().hex
    d = root / sid / "src"
    d.mkdir(parents=True)
    return sid, d


def _annotation(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="ignore")[:8000]
    except OSError:
        return ""


def _s1000d_folders(src: Path) -> list[dict]:
    """Folders that contain S1000D document schemas (annotation 'Root element:' + S1000D URL)."""
    out = []
    dirs = sorted({p.parent for p in src.rglob("*.xsd")})
    for d in dirs:
        types = []
        for p in sorted(d.glob("*.xsd")):
            head = _annotation(p)
            if re.search(r"Root element:\s*\w+", head) and re.search(r"S1000D", head, re.I):
                types.append(p.stem.lower())
        if types:
            issue = declared_issue(d)
            rel = d.relative_to(src).as_posix() or "."
            m = re.search(r"patch[ _-]*[\d.]*([A-Z])\b", rel, re.I)
            out.append({"path": rel, "issue": issue, "doc_types": types, "files": len(list(d.glob('*.xsd'))),
                        "patch": m.group(1).upper() if m else ""})
    return out


def _entity_folders(src: Path) -> list[dict]:
    out = []
    for d in sorted({p.parent for p in src.rglob("*") if p.is_file() and
                     (p.name.lower() == "isoentities" or p.suffix.lower() == ".ent")}):
        n = sum(1 for p in d.iterdir() if p.is_file() and (p.name.lower() == "isoentities" or p.suffix.lower() == ".ent"))
        rel = d.relative_to(src).as_posix() or "."
        m = re.search(r"patch[ _-]*[\d.]*([A-Z])\b", rel, re.I)
        out.append({"path": rel, "files": n, "patch": m.group(1).upper() if m else ""})
    return out


def _pick(options: list[dict]) -> str | None:
    """Preselect the latest patch, else a folder named like the official schema folder."""
    if not options:
        return None
    patched = sorted((o for o in options if o.get("patch")), key=lambda o: o["patch"])
    if patched:
        return patched[-1]["path"]
    for o in options:
        if o["path"].lower().endswith(("xml_schema_flat", "schemas")):
            return o["path"]
    return options[0]["path"]


def _guess_standard(text: str) -> str | None:
    t = text.lower()
    for std in ("s1000d", "s2000m", "s3000l", "s4000p", "s5000f", "s6000t"):
        if std in t:
            return std.upper()
    if re.search(r"\bata\b|ispec|ata2200|ata 2200", t):
        return "ATA2200"
    return None


def _xsd_candidates(src: Path) -> list[dict]:
    """Entry schemas (not included/imported by another) and their unreferenced global elements."""
    xsds = sorted(src.rglob("*.xsd"))
    referenced_files, refs, globals_ = set(), set(), {}
    for p in xsds:
        try:
            root = etree.parse(str(p), document_parser()).getroot()
        except etree.XMLSyntaxError:
            continue
        for el in root.iter(f"{XS}include", f"{XS}import", f"{XS}redefine"):
            loc = el.get("schemaLocation")
            if loc and not re.match(r"^[a-z][a-z0-9+.-]*://", loc, re.I):
                referenced_files.add((p.parent / loc).resolve())
            elif loc:
                referenced_files.update(q.resolve() for q in xsds if q.name == loc.rsplit("/", 1)[-1])
        for el in root.iter(f"{XS}element"):
            if el.get("ref"):
                refs.add(el.get("ref").split(":")[-1])
        tns = root.get("targetNamespace")
        globals_[p] = (tns, [e.get("name") for e in root.findall(f"{XS}element") if e.get("name")])
    out = []
    for p, (tns, names) in globals_.items():
        if p.resolve() in referenced_files:
            continue
        for n in names:
            if n not in refs:
                out.append({"id": n, "schema_file": p.relative_to(src).as_posix(), "root": n, "namespace": tns})
    return out


_SGML_MIN = re.compile(r"<!ELEMENT\s+(?:\([^)]*\)|[\w.:-]+)\s+[-Oo]\s+[-Oo]\s", re.I)


def is_sgml_dtd(src: Path) -> bool:
    """SGML DTDs carry tag-omission flags (<!ELEMENT para - O ...>) or come with an SGML declaration."""
    if any(p.suffix.lower() in (".dcl", ".decl") for p in src.rglob("*")):
        return True
    return any(_SGML_MIN.search(p.read_text(errors="ignore")) for p in src.rglob("*.dtd"))


_ISO_PUB = re.compile(r"ISO 8879[-:]1986//ENTITIES [^/\"]+//EN(?!//XML)", re.I)


def unwrap_doctype(text: str) -> tuple[str, str | None]:
    """Some DTDs (e.g. ATA distributions) are written as a whole document-type declaration,
    <!DOCTYPE cmm [ ...declarations... ]>, rather than as a DTD file to be referenced.
    -> (the declarations inside, document type name) or (text unchanged, None)."""
    i, n = 0, len(text)
    while i < n:                                             # first markup declaration outside comments
        j = text.find("<!", i)
        if j < 0:
            return text, None
        if text.startswith("<!--", j):
            k = text.find("-->", j + 4)
            i = n if k < 0 else k + 3
            continue
        m = re.match(r"<!DOCTYPE\s+([^\s\[>]+)\s*\[", text[j:], re.I)
        if not m:
            return text, None
        start = j + m.end()
        end = text.rfind("]")
        if end < start or not re.match(r"\]\s*>", text[end:]):
            return text, None
        return text[:j] + text[start:end] + text[end:].split(">", 1)[1], m.group(1)
    return text, None


def sgml_header(text: str) -> dict:
    """Identity and version written in a DTD's header comment (ATA DTDs carry these)."""
    ref = re.search(r"DTD\s+Reference\s*:\s*([^\n>]+?)\s*-->", text, re.I)
    ver = re.search(r"DTD\s+Version\s*:\s*([^\n>]+?)\s*-->", text, re.I)
    rev = re.search(r"Rev(?:ision)?\s+Date\s*:\s*([^\n>]+?)\s*-->", text, re.I)
    out = {}
    stated = re.search(r"""<!DOCTYPE\s+\S+\s+PUBLIC\s+["']([^"']+)["']""", text, re.I)   # "may be referred to as ..."
    if ref:
        r = ref.group(1).strip()
        out["reference"] = r
        out["public_id"] = r if r.startswith(("-//", "+//")) else f"-//{r.strip('/')}//EN"
    if stated:
        out["public_id"] = stated.group(1).strip()
        out.setdefault("reference", out["public_id"])
    if ver:
        out["version"] = ver.group(1).strip()
    if rev:
        out["date"] = rev.group(1).strip()
    return out


def sgml_dependencies(src: Path) -> dict:
    """External entities the DTD set loads, and which of them are not in the folder."""
    cat = read_catalogs(src)
    files = {p.relative_to(src).as_posix().lower() for p in src.rglob("*") if p.is_file()}
    names = {p.name.lower() for p in src.rglob("*") if p.is_file()}
    iso_missing, files_missing, seen = [], [], set()
    for f in [p for p in src.rglob("*") if p.is_file() and p.suffix.lower() in (".dtd", ".ent", ".mod", ".elm")]:
        text = re.sub(r"<!--.*?-->", " ", f.read_text(encoding="utf-8", errors="ignore"), flags=re.S)
        for m in re.finditer(r"""<!ENTITY\s+%\s+[\w.:-]+\s+(?:PUBLIC\s+("[^"]*"|'[^']*')(?:\s+("[^"]*"|'[^']*'))?|SYSTEM\s+("[^"]*"|'[^']*'))""", text, re.I):
            pub = m.group(1)[1:-1] if m.group(1) else None
            sysid = (m.group(2) or m.group(3) or "")[1:-1] or None
            if pub and pub in cat:
                continue
            if sysid:
                rel = (f.parent / sysid).resolve()
                try:
                    relp = rel.relative_to(src.resolve()).as_posix().lower()
                except ValueError:
                    relp = sysid.lower()
                if relp in files or Path(sysid).name.lower() in names:
                    continue
            key = pub or sysid
            if not key or key in seen:
                continue
            seen.add(key)
            if pub and _ISO_PUB.fullmatch(pub):
                iso_missing.append(pub)
            elif sysid:
                files_missing.append(sysid)
            elif pub:
                files_missing.append(pub)
    decl = any(p.suffix.lower() in (".dcl", ".decl") for p in src.rglob("*"))
    return {"iso_missing": iso_missing, "files_missing": files_missing, "has_declaration": decl}


def _iso_entity_file() -> str:
    """The ISO 8879 character entities as SDATA (names up to 8 characters, as in the ISO sets)."""
    import html.entities
    names = sorted({n.rstrip(";") for n in list(html.entities.html5) + list(html.entities.name2codepoint)
                    if re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,7};?", n)})
    head = ("<!-- ISO 8879:1986 character entities as SDATA, generated by ASTHRA because the DTD set did not\n"
            "     include them. One file serves all the ISO sets; each name maps to its standard character. -->\n")
    return head + "".join(f'<!ENTITY {n} SDATA "[{n}]">\n' for n in names)


def sgml_roots(text: str) -> list[str]:
    """Declared elements that no content model uses (read from the DTD text; SGML DTDs cannot
    be loaded by the XML parser)."""
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    declared, used = set(), set()
    for m in re.finditer(r"<!ELEMENT\s+(\([^)]*\)|[\w.:-]+)\s+(?:[-Oo]\s+[-Oo]\s+)?(.*?)>", text, re.S | re.I):
        names = re.findall(r"[\w.:-]+", m.group(1))
        declared.update(n.lower() for n in names)
        model = re.sub(r"--.*?--", " ", m.group(2), flags=re.S)
        for w in re.findall(r"[A-Za-z][\w.:-]*", model):
            if w.upper() not in ("EMPTY", "CDATA", "RCDATA", "ANY", "PCDATA"):
                used.add(w.lower())
    return sorted(declared - used)


def build_sgml_package(src: Path, standard: str, issue: str, out: Path, name: str | None,
                       roots: dict[str, str], only: list[str], public_ids: dict[str, str] | None = None,
                       aliases: list[str] | None = None) -> dict:
    """public_ids: doc type -> public identifier of its DTD (added to the catalog if missing).
    aliases: other public identifiers whose documents are validated with this DTD (e.g. an
    older version); every such validation is flagged."""
    import shutil
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / "src"
        shutil.copytree(src, stage)
        generated, placeholders = [], []
        for dtd in stage.rglob("*.dtd"):
            raw = dtd.read_text(encoding="utf-8", errors="ignore")
            inner, wrapped = unwrap_doctype(raw)
            if wrapped:
                dtd.write_text(inner, encoding="utf-8")
                generated.append(f"{dtd.relative_to(stage).as_posix()} (declarations taken out of <!DOCTYPE {wrapped} [...]>)")
        deps = sgml_dependencies(stage)
        cat_lines = []
        for dt_id, pub in (public_ids or {}).items():
            dtd = next((p for p in stage.rglob("*.dtd") if p.stem == dt_id), None)
            if dtd and pub and pub not in read_catalogs(stage):
                cat_lines.append(f'PUBLIC "{pub}" "{dtd.relative_to(stage).as_posix()}"')
                for al in aliases or []:
                    cat_lines.append(f'PUBLIC "{al}" "{dtd.relative_to(stage).as_posix()}"')
        if deps["iso_missing"]:
            (stage / "asthra-iso8879.ent").write_text(_iso_entity_file(), encoding="ascii")
            generated.append("asthra-iso8879.ent")
            cat_lines += [f'PUBLIC "{pub}" "asthra-iso8879.ent"' for pub in deps["iso_missing"]]
        for missing in deps["files_missing"]:
            if re.match(r"^[-+]//|^ISO", missing):
                continue                                      # a public id we cannot supply: left as reported
            target = stage / missing
            try:
                target.resolve().relative_to(stage.resolve())
            except ValueError:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"<!-- PLACEHOLDER written by ASTHRA: {missing} was not supplied with the DTD.\n"
                              "     Entities it defines are reported as undefined where documents use them. -->\n",
                              encoding="ascii")
            placeholders.append(missing)
        if cat_lines:
            cat = next((p for p in stage.rglob("*") if p.is_file() and p.name.lower() == "catalog"), stage / "CATALOG")
            old = cat.read_text(encoding="utf-8", errors="ignore") if cat.exists() else "OVERRIDE YES\n"
            cat.write_text(old.rstrip("\n") + "\n-- added by ASTHRA --\n" + "\n".join(cat_lines) + "\n", encoding="utf-8")
            if not old.strip() or "added by ASTHRA" not in old:
                generated.append(cat.relative_to(stage).as_posix() + " (entries)")
        if not deps["has_declaration"]:
            from ..validation.sgml import PREVIEW_DECL
            (stage / "asthra-default.dcl").write_text(PREVIEW_DECL, encoding="ascii")
            generated.append("asthra-default.dcl")
        manifest = _build_sgml_from(stage, standard, issue, out, name, roots, only, aliases or [])
        manifest["sgml"].update({"generated": generated, "placeholders": placeholders, "aliases": aliases or []})
        _rewrite_manifest(out, manifest)
        return manifest


def _rewrite_manifest(zip_path: Path, manifest: dict) -> None:
    import json
    import zipfile
    tmp = zip_path.with_suffix(".tmp")
    with zipfile.ZipFile(zip_path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = json.dumps(manifest, indent=2).encode() if item.filename == "asthra-package.json" else zin.read(item)
            zout.writestr(item, data)
    tmp.replace(zip_path)


def _build_sgml_from(src: Path, standard: str, issue: str, out: Path, name: str | None,
                     roots: dict[str, str], only: list[str], aliases: list[str]) -> dict:
    import json
    import zipfile
    src = src.resolve()
    files = sorted(p.relative_to(src).as_posix() for p in src.rglob("*") if p.is_file() and
                   (p.suffix.lower() in SCHEMA_EXT or p.name.lower() == "catalog"))
    catalogs = [f for f in files if Path(f).name.lower() == "catalog" or Path(f).suffix.lower() in (".cat", ".soc")]
    decl = next((f for f in files if Path(f).suffix.lower() in (".dcl", ".decl")), None)
    cat = read_catalogs(src)
    doc_types = []
    for rel in (f for f in files if f.lower().endswith(".dtd")):
        stem = Path(rel).stem
        if only and stem not in only:
            continue
        pubs = [k for k, v in cat.items() if v == rel and re.match(r"^([-+]//|ISO[ /])", k)]
        pubs += [a for a in aliases if a not in pubs]
        match = {"local_name": roots[stem].lower(), "system_id_pattern": rf"(?i)(^|[/\\]){re.escape(Path(rel).name)}$"}
        if pubs:
            match["public_id_pattern"] = "^(" + "|".join(re.escape(x) for x in pubs) + ")$"
        doc_types.append({"id": stem, "label": stem, "content_family": "other", "schema_file": rel,
                          "schema_kind": "sgml", "match": match})
    if not doc_types:
        raise BuildError("Select at least one document type.")
    # SGML and XML DTD sets of the same revision can both be installed: SGML sets get their own id
    manifest = {"package_id": "sgml", "name": name or f"{standard} {issue} SGML DTDs", "standard": standard,
                "issue": issue, "provenance": "synthetic" if "synthetic" in issue.lower() else
                ("official" if standard != "OEM" else "oem"),
                "licence_note": "DTDs used under their owner's licence. Not redistributed by ASTHRA.",
                "doc_types": doc_types, "files": files, "catalog": {k: v for k, v in cat.items()},
                "sgml": {"catalogs": catalogs, "declaration": decl}}
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("asthra-package.json", json.dumps(manifest, indent=2))
        for rel in files:
            zf.write(src / rel, rel)
    return manifest


def inspect(src: Path) -> dict:
    src = src.resolve()
    pkgs = list(src.rglob("asthra-package.json"))
    if len(pkgs) == 1:
        import json
        m = json.loads(pkgs[0].read_text(encoding="utf-8"))
        return {"kind": "package", "path": pkgs[0].parent.relative_to(src).as_posix() or ".",
                "standard": m.get("standard"), "issue": m.get("issue"), "name": m.get("name"),
                "doc_types": [{"id": d["id"], "label": d.get("label", d["id"]), "selected": True} for d in m.get("doc_types", [])],
                "notes": ["This is a ready-made ASTHRA schema package; it installs as it is."]}
    s1 = _s1000d_folders(src)
    if s1:
        pick = _pick(s1)
        ents = _entity_folders(src)
        issues = sorted({f["issue"] for f in s1 if f["issue"]})
        notes = []
        if len(s1) > 1:
            notes.append(f"{len(s1)} copies of the S1000D schemas were found (original release, patches, documentation). "
                         f"The latest patch is preselected.")
        if len(issues) > 1:
            notes.append(f"The copies declare different issues ({', '.join(issues)}); choose the one you need.")
        return {"kind": "s1000d", "standard": "S1000D", "folders": s1, "folder": pick,
                "issue": next((f["issue"] for f in s1 if f["path"] == pick), None),
                "entity_folders": ents, "entity_folder": _pick(ents),
                "default_types": ["proced", "descript", "ipd"], "notes": notes}
    dtds = sorted(src.rglob("*.dtd"))
    if dtds and is_sgml_dtd(src):
        from ..validation.sgml import find_tools
        types = []
        for p in dtds:
            cands = sgml_roots(p.read_text(errors="ignore"))
            root = cands[0] if len(cands) == 1 else (p.stem.lower() if p.stem.lower() in cands else None)
            types.append({"id": p.stem, "schema_file": p.relative_to(src).as_posix(), "root": root,
                          "root_candidates": cands[:40], "selected": root is not None,
                          "problem": None if root else "The top element could not be determined; choose it."})
        cat = read_catalogs(src)
        notes = ["These are SGML DTDs (legacy ATA iSpec 2200 or OEM). Enter the revision of this DTD set."]
        header = {}
        for t, p in zip(types, dtds):
            h = sgml_header(p.read_text(encoding="utf-8", errors="ignore"))
            if h:
                header = header or h
                if h.get("public_id") and not any(v == t["schema_file"] for v in cat.values()):
                    t["public_id"] = h["public_id"]
        if header:
            notes.insert(0, f"The DTD identifies itself as {header.get('reference', '?')}"
                         + (f", version {header['version']}" if header.get("version") else "")
                         + (f" ({header['date']})" if header.get("date") else "") + ".")
        wrapped = [p.name for p in dtds if unwrap_doctype(p.read_text(encoding="utf-8", errors="ignore"))[1]]
        if wrapped:
            notes.append(f"{', '.join(wrapped)} is written as a complete <!DOCTYPE … [ … ]> declaration; ASTHRA uses the "
                         "declarations inside it (your file is not changed).")
        deps = sgml_dependencies(src)
        if deps["iso_missing"]:
            notes.append(f"The {len(deps['iso_missing'])} ISO 8879 character-entity sets it uses are not in the folder; "
                         "ASTHRA will supply them (standard entities such as &deg; and &plusmn;).")
        if deps["files_missing"]:
            notes.append("Missing files the DTD loads: " + ", ".join(deps["files_missing"])
                         + ". Get them from whoever supplied the DTD. Until then an empty placeholder is installed, "
                           "and entities they define are reported as undefined where documents use them.")
        if not deps["has_declaration"]:
            notes.append("No SGML declaration (.dcl) is included; ASTHRA's default declaration is used "
                         "(long names and processing instructions allowed, tag omission on).")
        if not find_tools():
            notes.append("OpenSP (onsgmls, osx) is not installed, so SGML documents cannot be validated or rendered "
                         "yet. You can install the DTDs now and OpenSP later.")
        guess = _guess_standard(" ".join(cat.keys()))
        return {"kind": "sgml", "standard": guess if guess in ("ATA2200", "ATA2300") else "ATA2200",
                "issue": header.get("version"), "aliases": [], "missing_files": deps["files_missing"],
                "doc_types": types, "public_ids": sorted(k for k in cat if re.match(r"^([-+]//|ISO[ /])", k))[:50],
                "notes": notes}
    if dtds:
        cat = read_catalogs(src)
        for f in (p.relative_to(src).as_posix() for p in src.rglob("*") if p.is_file()):
            cat.setdefault(Path(f).name, f)
        types = []
        for p in dtds:
            rel = p.relative_to(src).as_posix()
            try:
                cands = dtd_roots(src, rel, cat)
            except BuildError as e:
                types.append({"id": p.stem, "schema_file": rel, "root": None, "root_candidates": [], "problem": str(e), "selected": False})
                continue
            root = cands[0] if len(cands) == 1 else (p.stem if p.stem in cands else None)
            types.append({"id": p.stem, "schema_file": rel, "root": root, "root_candidates": cands[:40],
                          "selected": root is not None,
                          "problem": None if root else "The top element could not be determined; choose it."})
        guess = _guess_standard(" ".join(cat.keys()) + " " + " ".join(p.read_text(errors="ignore")[:2000] for p in dtds[:5]))
        return {"kind": "dtd", "standard": guess if guess in ("ATA2200", "ATA2300") else "OEM", "issue": None,
                "doc_types": types, "public_ids": sorted(k for k in cat if re.match(r"^([-+]//|ISO[ /])", k))[:50],
                "notes": ["Enter the revision of this DTD set (for example 2023.1). It cannot be read from the files."]}
    xsds = list(src.rglob("*.xsd"))
    if xsds:
        cands = _xsd_candidates(src)
        text = " ".join((c["namespace"] or "") + " " + c["schema_file"] for c in cands)
        guess = _guess_standard(text) or "OEM"
        return {"kind": "xsd", "standard": guess, "issue": None,
                "doc_types": [{**c, "label": c["id"], "selected": len(cands) <= 5} for c in cands],
                "notes": ["Enter the issue/revision of this schema set. Tick the elements that are document roots "
                          "(files you will import start with one of them)."]}
    raise BuildError("No schema files were found (.xsd, .dtd, or an ASTHRA package).")


def build_xsd_package(src: Path, standard: str, issue: str, out: Path, name: str | None,
                      types: list[dict]) -> dict:
    import json
    import zipfile
    src = src.resolve()
    files = sorted(p.relative_to(src).as_posix() for p in src.rglob("*") if p.is_file() and p.suffix.lower() in (".xsd", ".ent", ".dtd", ".mod"))
    catalog = {Path(f).name: f for f in files}
    doc_types = [{"id": t["id"], "label": t.get("label") or t["id"], "content_family": "other",
                  "schema_file": t["schema_file"], "match": {"local_name": t["root"], "namespace": t.get("namespace")}}
                 for t in types]
    if not doc_types:
        raise BuildError("Select at least one document type.")
    manifest = {"package_id": "official" if standard != "OEM" else "oem", "name": name or f"{standard} {issue} schemas",
                "standard": standard, "issue": issue, "provenance": "official" if standard != "OEM" else "oem",
                "licence_note": "Schemas used under their owner's licence. Not redistributed by ASTHRA.",
                "doc_types": doc_types, "files": files, "catalog": catalog}
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("asthra-package.json", json.dumps(manifest, indent=2))
        for rel in files:
            zf.write(src / rel, rel)
    return manifest


def build(src: Path, choice: dict, out: Path) -> Path:
    """Build the package the user confirmed. choice = inspect() result edited by the user."""
    kind = choice["kind"]
    src = src.resolve()
    if kind == "package":
        return src / choice.get("path", ".")
    issue = (choice.get("issue") or "").strip()
    if not issue:
        raise BuildError("The issue/revision is required.")
    selected = [t for t in choice.get("doc_types", []) if t.get("selected")] if kind != "s1000d" else None
    if kind == "s1000d":
        folder = src / choice["folder"]
        ent = [src / choice["entity_folder"]] if choice.get("entity_folder") else None
        build_s1000d_package(folder, issue, out, choice.get("types") or None, ent)
    elif kind == "dtd":
        if not selected:
            raise BuildError("Select at least one document type.")
        missing = [t["id"] for t in selected if not t.get("root")]
        if missing:
            raise BuildError(f"Choose the top element for: {', '.join(missing)}")
        build_dtd_package(src, choice.get("standard") or "OEM", issue, out, choice.get("name"),
                          {t["id"]: t["root"] for t in selected}, [t["id"] for t in selected])
    elif kind == "sgml":
        if not selected:
            raise BuildError("Select at least one document type.")
        missing = [t["id"] for t in selected if not t.get("root")]
        if missing:
            raise BuildError(f"Choose the top element for: {', '.join(missing)}")
        build_sgml_package(src, choice.get("standard") or "ATA2200", issue, out, choice.get("name"),
                           {t["id"]: t["root"] for t in selected}, [t["id"] for t in selected],
                           {t["id"]: t.get("public_id") for t in selected if t.get("public_id")},
                           [a.strip() for a in choice.get("aliases", []) if a and a.strip()])
    elif kind == "xsd":
        std = (choice.get("standard") or "OEM").upper()
        if std not in KNOWN_STANDARDS:
            raise BuildError(f"Unknown standard {std}.")
        build_xsd_package(src, std, issue, out, choice.get("name"), selected or [])
    else:
        raise BuildError(f"Unknown source kind: {kind}")
    return out


def cleanup(staging_root: Path, keep: str | None = None) -> None:
    for d in staging_root.glob("*"):
        if d.is_dir() and d.name != keep:
            shutil.rmtree(d, ignore_errors=True)
