"""ASTHRA command line. `python -m asthra.cli --help`"""
from __future__ import annotations

import argparse
import os
import json
import sys
from pathlib import Path

from .app_context import AppContext
from .config import Settings, default_settings


def etree_local(el) -> str:
    return el.tag.split("}")[-1] if isinstance(el.tag, str) else str(el.tag)


def _ctx(args) -> AppContext:
    s = Settings(data_root=Path(args.data)).ensure() if args.data else default_settings()
    return AppContext.open(s)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="asthra")
    ap.add_argument("--data", help="data root (default: %%LOCALAPPDATA%%\\ASTHRA or ~/.asthra)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("serve", help="run ASTHRA on 127.0.0.1")
    p.add_argument("--open", action="store_true", help="open the UI in the default browser")
    p.add_argument("--port", type=int, default=8765)
    p = sub.add_parser("install-schema"); p.add_argument("path")
    p = sub.add_parser("new-project"); p.add_argument("name")
    sub.add_parser("projects")
    p = sub.add_parser("import"); p.add_argument("project"); p.add_argument("file")
    p.add_argument("--package"); p.add_argument("--doc-type")
    p = sub.add_parser("validate"); p.add_argument("document")
    p = sub.add_parser("documents"); p.add_argument("project")
    p = sub.add_parser("make-dtd-package", help="build a package from a folder of DTDs (ATA iSpec 2200 XML, OEM)")
    p.add_argument("folder"); p.add_argument("--standard", required=True, help="ATA2200, ATA2300 or OEM")
    p.add_argument("--issue", required=True, help="revision, e.g. 2023.1"); p.add_argument("--name")
    p.add_argument("--root", action="append", default=[], help="DTD=element, when the top element is unclear")
    p.add_argument("--only", help="comma-separated DTD names to include")
    p.add_argument("--out"); p.add_argument("--install", action="store_true"); p.add_argument("--replace", action="store_true")
    p = sub.add_parser("add-schemas", help="install schemas from any folder or zip (S1000D, DTD sets, XSD sets, packages)")
    p.add_argument("path"); p.add_argument("--issue"); p.add_argument("--standard"); p.add_argument("--name")
    p.add_argument("--folder", help="which S1000D schema copy to use (path shown in the proposal)")
    p.add_argument("--types", help="comma-separated document types (default: proced,descript,ipd for S1000D)")
    p.add_argument("--entities", help="entity folder to bundle, or 'none' (default: the one found)")
    p.add_argument("--root", action="append", default=[], help="DOCTYPE=element for DTD sets")
    p.add_argument("--accept-public-id", action="append", default=[],
                   help="SGML/DTD sets: also validate documents declaring this public identifier (e.g. an older version)")
    p.add_argument("--replace", action="store_true"); p.add_argument("--yes", action="store_true", help="do not ask")
    p = sub.add_parser("schemas", help="list, remove or export installed schema packages")
    p.add_argument("action", choices=["list", "remove", "export", "export-all", "import-set"])
    p.add_argument("target", nargs="?"); p.add_argument("file", nargs="?"); p.add_argument("--force", action="store_true")
    p = sub.add_parser("export-opensp", help="pack the working OpenSP (programs + exactly the DLLs they need) into a zip for another PC")
    p.add_argument("out", nargs="?", default="opensp-bundle.zip")
    p = sub.add_parser("install-opensp", help="install OpenSP (for SGML) from a downloaded zip or folder into ASTHRA")
    p.add_argument("path")
    p = sub.add_parser("benchmark", help="score validation against planted-defect suites and known-good files")
    p.add_argument("suites", nargs="*", help="suite names or folders (default: all built-in suites)")
    p.add_argument("--corpus", help="folder of known-good files (e.g. the S1000D Bike data set): every error counts as a false positive")
    p.add_argument("--json", help="also write the full results to this JSON file")
    sub.add_parser("doctor", help="check this installation: Python, XML libraries, OpenSP, data folder, schemas")
    p = sub.add_parser("why", help="explain which installed schema matches an XML file, and why")
    p.add_argument("file")
    p = sub.add_parser("schema-issue", help="show which S1000D issue a schema folder contains")
    p.add_argument("folder")
    p = sub.add_parser("make-package", help="build an installable package from a folder of official S1000D schemas")
    p.add_argument("folder"); p.add_argument("--issue", required=True, help="e.g. 4.1")
    p.add_argument("--out", help="output .zip (default: s1000d-<issue>.zip)")
    p.add_argument("--only", help="comma-separated schema names to include, e.g. proced,descript,ipd")
    p.add_argument("--install", action="store_true", help="also install it into the data folder")
    p.add_argument("--replace", action="store_true", help="replace an already installed build of this issue")
    p.add_argument("--entities", action="append", default=[], help="folder of entity files to bundle (e.g. the ISO entity sets)")
    sub.add_parser("demo", help="install the synthetic S-Series fixtures, import and validate them")
    a = ap.parse_args(argv)

    if a.cmd == "serve":
        import uvicorn
        from .api.app import create_app
        s = Settings(data_root=Path(a.data), port=a.port).ensure() if a.data else \
            Settings(data_root=default_settings().data_root, port=a.port)
        url = f"http://127.0.0.1:{s.port}/"
        print(f"ASTHRA running at {url}  (data: {s.data_root})  — press Ctrl+C to stop")
        if a.open:
            import threading
            import webbrowser
            threading.Timer(1.2, lambda: webbrowser.open(url)).start()
        uvicorn.run(create_app(s), host=s.host, port=s.port, log_level="warning")
        return 0
    if a.cmd == "make-dtd-package":
        from .registry.builder import BuildError
        from .registry.dtd_builder import build_dtd_package
        from .registry.service import RegistryError
        out_zip = Path(a.out or f"{a.standard.lower()}-{a.issue}.zip")
        roots = dict(r.split("=", 1) for r in a.root if "=" in r)
        try:
            m = build_dtd_package(Path(a.folder), a.standard.upper(), a.issue, out_zip, a.name, roots,
                                  a.only.split(",") if a.only else None)
        except BuildError as e:
            print(f"Could not build the package: {e}")
            return 2
        print(f"Built {out_zip}: {a.standard.upper()} {a.issue}, document types: "
              + ", ".join(f"{d['id']} (<{d['match']['local_name']}>)" for d in m["doc_types"]))
        if not a.install:
            return 0
        ctx = _ctx(a)
        key = f"{a.standard.lower()}/{a.issue}/official"
        exists = any(p.manifest.key == key for p in ctx.registry.list())
        if exists and not a.replace:
            print(f"{key} is already installed. Re-run with --replace to update it.")
            return 2
        try:
            pkg = ctx.registry.replace(out_zip) if exists else ctx.registry.install(out_zip)
        except RegistryError as e:
            print(f"Could not install: {e}")
            return 2
        print(f"{'Replaced' if exists else 'Installed'} {pkg.manifest.key}")
        return 0
    if a.cmd == "schema-issue":
        from .registry.builder import declared_issue
        found = declared_issue(Path(a.folder))
        print(f"These schemas declare S1000D Issue {found}." if found else "No issue number found in these schemas.")
        return 0
    if a.cmd == "make-package":
        from .registry.builder import BuildError, build_s1000d_package
        out_zip = Path(a.out or f"s1000d-{a.issue}.zip")
        try:
            m = build_s1000d_package(Path(a.folder), a.issue, out_zip, a.only.split(",") if a.only else None,
                                     [Path(e) for e in a.entities])
        except BuildError as e:
            print(f"Could not build the package: {e}")
            return 2
        n_ent = sum(1 for f in m["files"] if f.startswith("ent/"))
        if n_ent:
            print(f"Bundled {n_ent} entity files.")
        print(f"Built {out_zip}: S1000D {a.issue}, {len(m['doc_types'])} document types "
              f"({', '.join(d['id'] for d in m['doc_types'])}), {len(m['files'])} schema files")
        for sk in m.get("_skipped", []):
            print(f"  skipped (missing dependency) {sk}")
        if not a.install:
            print("Install it in ASTHRA under Schemas > Install, or re-run with --install.")
            return 0
        ctx = _ctx(a)
        from .registry.service import RegistryError
        key = f"s1000d/{a.issue}/official"
        exists = any(p.manifest.key == key for p in ctx.registry.list())
        if exists and not a.replace:
            print(f"{key} is already installed. Re-run with --replace to update it "
                  "(documents stay linked to it).")
            return 2
        print("Installing (compiles every schema; this can take a minute)…")
        try:
            pkg = ctx.registry.replace(out_zip) if exists else ctx.registry.install(out_zip)
        except RegistryError as e:
            print(f"Could not install: {e}")
            return 2
        print(f"{'Replaced' if exists else 'Installed'} {pkg.manifest.key}: "
              f"{', '.join(d.id for d in pkg.manifest.doc_types)}")
        return 0
    if a.cmd == "export-opensp":
        return _export_opensp(a)
    if a.cmd == "install-opensp":
        return _install_opensp(a)
    if a.cmd == "benchmark":
        return _benchmark(a)
    if a.cmd == "doctor":
        return _doctor(a)
    if a.cmd == "add-schemas":
        return _add_schemas(a)
    if a.cmd == "schemas":
        return _schemas(a)
    if a.cmd == "why":
        from .identify.service import explain_match, identify, parse_xml, sniff
        data = Path(a.file).read_bytes()
        tree, errs = parse_xml(data)
        if tree is None:
            print("The file is not well-formed XML:", errs if isinstance(errs, str) else errs[0].message)
            return 2
        ctx = _ctx(a)
        root = tree.getroot()
        print(f"root <{etree_local(root)}>  declares: {root.get('{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation') or tree.docinfo.public_id or '(nothing)'}")
        for r in explain_match(root, ctx.registry.list()):
            flags = [("enabled" if r["enabled"] else "DISABLED"), f"root {'ok' if r['root_ok'] else 'expects <' + r['root_expected'] + '>'}",
                     f"declared {'YES' if r['declares'] else 'no'}"]
            if not r["declares"] and r["pattern"]:
                flags.append(f"rule {r['pattern']}")
            if r["discriminator"]:
                flags.append(f"content {r['discriminator']} {'ok' if r['discriminator_ok'] else 'NOT FOUND'}")
            print(f"  {r['package']:<40} {r['doc_type']:<10} " + " | ".join(flags))
        ident = identify(root, ctx.registry.list(False), sniff(data))
        print(f"result: {ident.status}" + (f" -> {ident.chosen.package_id} / {ident.chosen.doc_type}" if ident.chosen else ""))
        return 0
    ctx = _ctx(a)
    out = None
    if a.cmd == "demo":
        return _demo(ctx)
    if a.cmd == "documents":
        for d in ctx.documents.list(a.project):
            lv = d["last_validation"]
            print(f"{d['id']}  {d['original_name']:<34} {str(d['standard']):<7} {str(d['doc_type']):<13} "
                  f"{lv['structural_status'] if lv else 'not validated'}")
        return 0
    if a.cmd == "install-schema":
        out = ctx.registry.install(Path(a.path)).summary()
    elif a.cmd == "new-project":
        out = ctx.projects.create(a.name)
    elif a.cmd == "projects":
        out = ctx.projects.list()
    elif a.cmd == "import":
        out = ctx.documents.import_path(a.project, Path(a.file), package_id=a.package, doc_type_id=a.doc_type)
    elif a.cmd == "validate":
        rep = ctx.documents.validate(a.document)
        out = {"statuses": rep.statuses(), "counts": rep.counts(),
               "diagnostics": [d.model_dump(mode="json") for d in rep.diagnostics]}
        print(json.dumps(out, indent=2))
        return 0 if rep.structural_status.value == "passed" else 1
    print(json.dumps(out, indent=2, default=str))
    return 0


def _export_opensp(a) -> int:
    """For PCs that cannot download OpenSP (no internet, blocked mirrors): copy it from a PC
    where it works. The zip installs with `install-opensp <zip>` on the other PC."""
    import zipfile
    from .validation.sgml import find_tools, probe
    from .winpe import dll_closure
    tools = find_tools()
    if not tools:
        print("OpenSP is not available on this PC, so there is nothing to export. Check with: doctor")
        return 2
    ok, detail = probe(tools)
    if not ok:
        print(f"OpenSP was found but does not work here ({detail}); not exporting a broken copy.")
        return 2
    files = dll_closure([Path(tools[0]), Path(tools[1])])
    out = Path(a.out)
    share = Path(tools[0]).parent.parent / "share" / "licenses"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, f"OpenSP/usr/bin/{f.name}")          # MSYS2 layout: the runtime expects usr/bin
        for pkg in ("opensp", "msys2-runtime", "gcc-libs", "libiconv", "libintl"):
            if (share / pkg).is_dir():
                for lic in (share / pkg).iterdir():
                    if lic.is_file():
                        z.write(lic, f"OpenSP/LICENSES/{pkg}-{lic.name}")
        z.writestr("OpenSP/README.txt",
                   "OpenSP (onsgmls, osx) for ASTHRA, with the DLLs these programs import.\r\n"
                   f"Exported from a working installation ({detail}).\r\n\r\n"
                   "Install on the other PC (no internet needed):\r\n"
                   "    python -m asthra.cli install-opensp <this zip>\r\n"
                   "    python -m asthra.cli doctor\r\n\r\n"
                   "OpenSP is under a permissive MIT-style licence; the msys-*.dll files are the MSYS2 runtime\r\n"
                   "and GCC support libraries under their own open-source licences (see LICENSES).\r\n")
    print(f"Exported OpenSP ({detail}) to {out.resolve()}")
    for f in files:
        print(f"   {f.name}")
    print("On the other PC:  python -m asthra.cli install-opensp " + out.name)
    return 0


def _install_opensp(a) -> int:
    """Make OpenSP available to ASTHRA without PATH changes.
    - a small folder or zip (e.g. an OpenSP download) is copied into <data folder>/tools/opensp
    - a large shared folder (e.g. MSYS2's usr\\bin, where the programs need the DLLs around
      them) is registered in place instead of copied
    Either way it is tested on a tiny SGML document before ASTHRA relies on it."""
    import shutil as _sh
    import tempfile
    from .security.paths import safe_extract_zip
    from .validation.sgml import _in_tree, probe, tools_dir
    src = Path(a.path)
    dest = tools_dir()
    reg_file = dest.parent / "opensp.path"
    with tempfile.TemporaryDirectory() as tmp:
        zipped = src.is_file() and src.suffix.lower() == ".zip"
        if zipped:
            safe_extract_zip(src, Path(tmp) / "x")
            src = Path(tmp) / "x"
            if os.name != "nt":            # zips do not keep the executable flag
                for f in src.rglob("*"):
                    if f.is_file() and f.name in ("onsgmls", "osx", "nsgmls", "spam", "spent", "sx"):
                        f.chmod(f.stat().st_mode | 0o111)
        if not src.is_dir():
            print(f"Not found: {a.path}")
            return 2
        hit = _in_tree(src)
        if not hit:
            print("No onsgmls and osx programs were found there. Windows: install MSYS2 (msys2.org), run "
                  "'pacman -S opensp' in the MSYS2 shell, then: install-opensp C:\\msys64\\usr\\bin")
            return 2
        ok, detail = probe(hit)
        if not ok:
            print(f"Found OpenSP at {Path(hit[0]).parent}, but {detail}")
            print("Nothing was installed.")
            _remove_opensp(dest, reg_file)
            return 2
        tool_folder = Path(hit[0]).parent
        n_files = sum(1 for _ in tool_folder.iterdir())
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not zipped and n_files > 60:
            # a shared folder such as MSYS2's usr\bin: use it where it is
            if dest.exists():
                _sh.rmtree(dest)
            reg_file.write_text(str(tool_folder.resolve()), encoding="utf-8")
            print(f"OpenSP works ({detail}). Using it in place: {tool_folder}")
            return 0
        if dest.exists():
            _sh.rmtree(dest)
        # copy the whole download (programs, DLL folders, licence), not just the programs' folder
        _sh.copytree(src if (zipped or n_files <= 60) else tool_folder, dest)
        reg_file.unlink(missing_ok=True)
    installed = _in_tree(dest)
    ok, detail = probe(installed) if installed else (False, "the copied programs were not found")
    if not ok:
        print(f"Copied to {dest}, but {detail}")
        _remove_opensp(dest, reg_file)
        print("The copy was removed, so ASTHRA will not try to use it.")
        return 2
    print(f"OpenSP installed in {dest} ({detail})")
    return 0


def _remove_opensp(dest: Path, reg_file: Path) -> None:
    import shutil as _sh
    if dest.exists():
        _sh.rmtree(dest, ignore_errors=True)
    reg_file.unlink(missing_ok=True)


def _benchmark(a) -> int:
    from .benchmark.runner import SUITES, print_report, run_corpus, run_suite, summary, to_json
    ctx = _ctx(a)
    results = []
    if a.suites or not a.corpus:
        folders = [Path(x) if Path(x).is_dir() else SUITES / x for x in a.suites] if a.suites else \
            sorted(p for p in SUITES.iterdir() if (p / "suite.json").is_file())
        for f in folders:
            if not (f / "suite.json").is_file():
                print(f"Not a benchmark suite: {f}")
                return 2
            results += run_suite(f, ctx.registry)
    if a.corpus:
        results += run_corpus(ctx.registry, Path(a.corpus))
    print_report(results)
    if a.json:
        Path(a.json).write_text(json.dumps(to_json(results), indent=2), encoding="utf-8")
        print(f"\nFull results: {a.json}")
    s = summary(results)
    return 0 if s["missed"] == 0 and s["false_positives"] == 0 else 1


def _doctor(a) -> int:
    import platform
    import subprocess
    import lxml.etree as et
    from .validation.sgml import OPEN_SP_HELP, find_tools
    ok = True
    print(f"Python      {platform.python_version()} ({platform.system()})")
    print(f"lxml        {et.__version__}  libxml2 {'.'.join(map(str, et.LIBXML_VERSION))}")
    tools = find_tools()
    if tools:
        from .validation.sgml import VENDOR_DIR, probe, registered_dir, tools_dir
        works, detail = probe(tools)
        reg = registered_dir()
        where = ("ASTHRA_OPENSP" if os.environ.get("ASTHRA_OPENSP") else
                 "registered in place" if reg and str(reg) in tools[0] else
                 "data folder" if str(tools_dir()) in tools[0] else
                 "bundled with ASTHRA" if str(VENDOR_DIR) in tools[0] else "system PATH")
        print(f"OpenSP      {tools[0]}  [{where}]  " + (detail if works else f"NOT WORKING: {detail}"))
        ok = ok and works
    else:
        print("OpenSP      NOT FOUND - SGML (legacy ATA iSpec 2200) cannot be validated or rendered.")
        print("            " + OPEN_SP_HELP)
    ctx = _ctx(a)
    print(f"Data folder {ctx.settings.data_root}")
    pkgs = ctx.registry.list()
    print(f"Schemas     {len(pkgs)} installed" + ("" if pkgs else " - add them: Schemas > Manage, or add-schemas <folder>"))
    for p in pkgs:
        intact = ctx.registry.verify_integrity(p.manifest.key)
        ok = ok and intact
        kinds = sorted({d.schema_kind for d in p.manifest.doc_types})
        print(f"            {p.manifest.key:<36} {'/'.join(kinds):<5} {'ok' if intact else 'DAMAGED - reinstall'}"
              f"{'' if p.enabled else '  (disabled)'}")
    return 0 if ok else 1


def _add_schemas(a) -> int:
    import tempfile
    from .registry import installer
    from .registry.builder import BuildError
    from .registry.service import RegistryError
    from .security.paths import safe_extract_zip
    src_path = Path(a.path)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src"
        if src_path.is_file() and src_path.suffix.lower() == ".zip":
            safe_extract_zip(src_path, src)
        elif src_path.is_dir():
            src.mkdir()
            for f in src_path.rglob("*"):
                if f.is_file() and installer.wanted(f.relative_to(src_path).as_posix(), f.stat().st_size):
                    dest = src / f.relative_to(src_path)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(f.read_bytes())
        else:
            print(f"Not found: {src_path}")
            return 2
        try:
            prop = installer.inspect(src)
        except BuildError as e:
            print(e)
            return 2
        kind = prop["kind"]
        labels = dict(package="an ASTHRA package", s1000d="S1000D schemas", dtd="a DTD set",
                      sgml="an SGML DTD set", xsd="an XSD set")
        print(f"Found: {labels.get(kind, kind)}")
        for n in prop.get("notes", []):
            print("  " + n)
        choice = dict(prop)
        if kind == "s1000d":
            for f in prop["folders"]:
                mark = "*" if f["path"] == prop["folder"] else " "
                print(f"  {mark} {f['path']}  (issue {f['issue'] or '?'}, {len(f['doc_types'])} document types)")
            if a.folder:
                choice["folder"] = a.folder
                choice["issue"] = next((f["issue"] for f in prop["folders"] if f["path"] == a.folder), prop["issue"])
            choice["types"] = [t.strip() for t in (a.types or "proced,descript,ipd").split(",")]
            if a.entities == "none":
                choice["entity_folder"] = None
            elif a.entities:
                choice["entity_folder"] = a.entities
            print(f"Using: {choice['folder']}  issue {a.issue or choice['issue']}  types {', '.join(choice['types'])}"
                  f"  entities {choice.get('entity_folder') or 'none'}")
        elif kind in ("dtd", "sgml", "xsd"):
            if a.standard:
                choice["standard"] = a.standard.upper()
            roots = dict(r.split("=", 1) for r in a.root if "=" in r)
            wanted_types = set(t.strip() for t in a.types.split(",")) if a.types else None
            for t in choice["doc_types"]:
                if t["id"] in roots:
                    t["root"] = roots[t["id"]]
                if wanted_types is not None:
                    t["selected"] = t["id"] in wanted_types
                print(f"  [{'x' if t.get('selected') else ' '}] {t['id']:<24} root <{t.get('root') or '?'}>"
                      + (f"   {t['problem']}" if t.get("problem") else ""))
            print(f"Standard: {choice['standard']}")
            if a.accept_public_id:
                choice["aliases"] = a.accept_public_id
                print("Also accepting: " + "; ".join(a.accept_public_id))
        if a.issue:
            choice["issue"] = a.issue
        if a.name:
            choice["name"] = a.name
        if kind != "package" and not choice.get("issue"):
            print("The issue/revision is required: add --issue <value>.")
            return 2
        if not a.yes and input("Install? [y/N] ").strip().lower() != "y":
            print("Nothing installed.")
            return 1
        ctx = _ctx(a)
        try:
            z = installer.build(src, choice, Path(tmp) / "package.zip")
            try:
                pkg = ctx.registry.install(z); action = "Installed"
            except RegistryError as e:
                if "already installed" not in str(e):
                    raise
                if not a.replace:
                    print(f"{e}. Re-run with --replace to update it (documents stay linked).")
                    return 2
                pkg = ctx.registry.replace(z); action = "Replaced"
        except (BuildError, RegistryError) as e:
            print(f"Could not install: {e}")
            return 2
        print(f"{action} {pkg.manifest.key}: {', '.join(d.id for d in pkg.manifest.doc_types)}")
        return 0


def _schemas(a) -> int:
    from .registry.service import RegistryError
    ctx = _ctx(a)
    try:
        if a.action == "list":
            for p in ctx.registry.list():
                print(f"{p.manifest.key:<36} {'enabled ' if p.enabled else 'DISABLED'} {p.manifest.provenance:<9} "
                      f"{ctx.registry.documents_using(p.manifest.key):>4} docs  {', '.join(d.id for d in p.manifest.doc_types)}")
        elif a.action == "remove":
            n = ctx.registry.remove(a.target, a.force)
            print(f"Removed {a.target}" + (f"; {n} document(s) unlinked" if n else ""))
        elif a.action == "export":
            print(ctx.registry.export_package(a.target, Path(a.file or a.target.replace("/", "_") + ".zip")))
        elif a.action == "export-all":
            print(ctx.registry.export_set(Path(a.target or "asthra-schema-set.zip")))
        elif a.action == "import-set":
            for r in ctx.registry.import_set(Path(a.target)):
                print(f"{r['id']:<36} {r['result']}")
    except RegistryError as e:
        print(e)
        return 2
    return 0


def _demo(ctx: AppContext) -> int:
    fixtures = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
    installed = {p.manifest.standard for p in ctx.registry.list()}
    for name, std in (("s1000d-synth", "S1000D"), ("s2000m-synth", "S2000M"), ("s3000l-synth", "S3000L")):
        if std not in installed:
            ctx.registry.install(fixtures / "packages" / name)
            print(f"installed synthetic {std} schema package")
    proj = ctx.projects.create("ASTHRA demo")
    print(f"\nproject {proj['id']}  ({proj['root_path']})\n")
    for f in sorted((fixtures / "documents").iterdir()):
        d = ctx.documents.import_path(proj["id"], f)
        rep = ctx.documents.validate(d["id"])
        c = rep.counts()
        print(f"{f.name:<34} {str(d['standard']):<7} {str(d['doc_type']):<13} "
              f"structural={rep.structural_status.value:<12} errors={c['error'] + c['fatal']}")
        for dg in rep.diagnostics[:3]:
            if dg.severity.value in ("error", "fatal"):
                print(f"    L{dg.line} {dg.element_path or ''}: {dg.message[:100]}")
    print(f"\nNext: python -m asthra.cli documents {proj['id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
