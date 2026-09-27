"""Build a portable ASTHRA folder for Windows: unzip and double-click, no installer, no admin.

    python tools\\make_portable.py                         (downloads what it needs)
    python tools\\make_portable.py --python-zip C:\\dl\\python-3.10.11-embed-amd64.zip --wheels C:\\dl\\wheels
                                                          (offline: use files you downloaded)

Result: dist\\ASTHRA\\ (the folder) and dist\\ASTHRA-portable-<version>-win64.zip

Contents
  python\\      the official embeddable Python from python.org (signed python.exe), same version
               as the Python running this script, so the compiled libraries match
  app\\asthra\\  ASTHRA with its built interface; app\\tests\\fixtures holds the sample documents
  app\\asthra\\vendor\\opensp\\  OpenSP (onsgmls, osx) and exactly the DLLs they import, if found
  data\\        your schemas and projects (portable: they travel with the folder)
  ASTHRA.bat, ASTHRA-cli.bat, README-PORTABLE.txt

Run it on Windows, with the same Python version you want inside the bundle.
"""
from __future__ import annotations

import argparse
import compileall
import os
import shutil
import struct
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"


# ------------------------------------------------------------------ PE import table (which DLLs a .exe needs)
def pe_imports(path: Path) -> list[str]:
    """Names of the DLLs a Windows executable/DLL imports (normal and delay-loaded)."""
    data = path.read_bytes()
    if data[:2] != b"MZ":
        return []
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        return []
    nsec = struct.unpack_from("<H", data, pe + 6)[0]
    opt_size = struct.unpack_from("<H", data, pe + 20)[0]
    opt = pe + 24
    magic = struct.unpack_from("<H", data, opt)[0]
    dd = opt + (112 if magic == 0x20B else 96)          # data directories (PE32+ / PE32)
    sections = []
    sec = opt + opt_size
    for i in range(nsec):
        # IMAGE_SECTION_HEADER: Name[8], VirtualSize, VirtualAddress, SizeOfRawData, PointerToRawData
        vsize, va, raw_size, raw_ptr = struct.unpack_from("<IIII", data, sec + i * 40 + 8)
        sections.append((va, max(vsize, raw_size), raw_ptr))

    def off(rva: int) -> int | None:
        for va, size, raw in sections:
            if va <= rva < va + size:
                return rva - va + raw
        return None

    def cstr(rva: int) -> str:
        o = off(rva)
        if o is None:
            return ""
        end = data.find(b"\0", o, o + 260)          # DLL names are short; never read past that
        if end < 0:
            return ""
        return data[o:end].decode("ascii", "replace")

    names: list[str] = []
    imp_rva = struct.unpack_from("<I", data, dd + 8 * 1)[0]
    if imp_rva and (o := off(imp_rva)) is not None:
        for _ in range(512):                             # guard against malformed tables
            desc = struct.unpack_from("<IIIII", data, o)
            if not any(desc):
                break
            names.append(cstr(desc[3]))
            o += 20
    dly_rva = struct.unpack_from("<I", data, dd + 8 * 13)[0]
    if dly_rva and (o := off(dly_rva)) is not None:
        for _ in range(512):
            desc = struct.unpack_from("<IIIIIIII", data, o)
            if not any(desc):
                break
            names.append(cstr(desc[1]))
            o += 32
    return [n for n in names if n and n.lower().endswith((".dll", ".drv", ".sys", ".exe"))]


def dll_closure(programs: list[Path]) -> list[Path]:
    """The programs plus every DLL they need that sits in the same folder (system DLLs excluded)."""
    folder = programs[0].parent
    local = {p.name.lower(): p for p in folder.iterdir() if p.suffix.lower() == ".dll"}
    todo, done = list(programs), {}
    while todo:
        p = todo.pop()
        if p.name.lower() in done:
            continue
        done[p.name.lower()] = p
        for dep in pe_imports(p):
            hit = local.get(dep.lower())
            if hit and hit.name.lower() not in done:
                todo.append(hit)
    return sorted(done.values())


# ------------------------------------------------------------------ build steps
def say(msg: str) -> None:
    print(f"  {msg}", flush=True)


def get_python_zip(args, work: Path) -> Path:
    if args.python_zip:
        return Path(args.python_zip)
    v = ".".join(map(str, sys.version_info[:3]))
    name = f"python-{v}-embed-amd64.zip"
    url = f"https://www.python.org/ftp/python/{v}/{name}"
    dest = work / name
    if not dest.exists():
        say(f"downloading {url}")
        try:
            urllib.request.urlretrieve(url, dest)
        except Exception as e:                              # noqa: BLE001
            sys.exit(f"Could not download the embeddable Python ({e}).\n"
                     f"Download {name} from python.org yourself and run again with --python-zip <file>.")
    return dest


def setup_python(zip_path: Path, target: Path) -> None:
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(target)
    pth = next(target.glob("python3*._pth"), None)
    if pth is None:
        sys.exit("This does not look like the embeddable Python zip (no python3*._pth inside).")
    lines = [l for l in pth.read_text().splitlines() if l.strip() and not l.strip().startswith("#")]
    # the standard library zip and '.', then the libraries and the app; 'import site' enables .pth files
    lines = [l for l in lines if l.strip() != "import site"] + ["Lib\\site-packages", "..\\app", "import site"]
    pth.write_text("\n".join(lines) + "\n")
    (target / "Lib" / "site-packages").mkdir(parents=True, exist_ok=True)


def install_libraries(args, site: Path, work: Path) -> None:
    v = f"{sys.version_info[0]}.{sys.version_info[1]}"
    cmd = [sys.executable, "-m", "pip", "install", "--quiet", "--no-compile", "--target", str(site),
           "--only-binary=:all:", "--platform", "win_amd64", "--python-version", v, "--implementation", "cp",
           "-r", str(BACKEND / "requirements-runtime.txt")]
    if args.wheels:
        cmd += ["--no-index", "--find-links", args.wheels]
    say("installing libraries: " + ("from " + args.wheels if args.wheels else "from PyPI"))
    r = subprocess.run(cmd)
    if r.returncode:
        sys.exit("pip could not install the libraries (see above). Offline? Download them first with:\n"
                 f"  pip download --only-binary=:all: --platform win_amd64 --python-version {v} "
                 f"-d wheels -r backend\\requirements-runtime.txt\nthen run again with --wheels wheels")
    for junk in ("bin", "__pycache__"):
        shutil.rmtree(site / junk, ignore_errors=True)


def copy_app(app: Path, pyc_only: bool) -> None:
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", "demo")
    shutil.copytree(BACKEND / "asthra", app / "asthra", ignore=ignore)
    shutil.copytree(BACKEND / "tests" / "fixtures", app / "tests" / "fixtures")   # sample documents
    if pyc_only:
        compileall.compile_dir(app / "asthra", quiet=1, legacy=True, optimize=0)
        for py in (app / "asthra").rglob("*.py"):
            py.unlink()


def find_opensp(args) -> tuple[Path, Path] | None:
    if args.opensp_dir:
        d = Path(args.opensp_dir)
        a, b = shutil.which("onsgmls", path=str(d)), shutil.which("osx", path=str(d))
        return (Path(a), Path(b)) if a and b else None
    sys.path.insert(0, str(BACKEND))
    try:
        from asthra.validation.sgml import find_tools
        t = find_tools()
        return (Path(t[0]), Path(t[1])) if t else None
    finally:
        sys.path.pop(0)


def bundle_opensp(tools: tuple[Path, Path], dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    files = dll_closure([tools[0], tools[1]])
    for f in files:
        shutil.copy2(f, dest / f.name)
    say(f"OpenSP: {', '.join(f.name for f in files)}")
    notes = dest / "LICENSES"
    notes.mkdir(exist_ok=True)
    share = tools[0].parent.parent / "share" / "licenses"          # MSYS2 layout: usr\bin, usr\share\licenses
    copied = 0
    for pkg in ("opensp", "msys2-runtime", "gcc-libs", "libiconv", "libintl"):
        for lic in (share / pkg).glob("*") if (share / pkg).is_dir() else []:
            shutil.copy2(lic, notes / f"{pkg}-{lic.name}")
            copied += 1
    (notes / "README.txt").write_text(
        "OpenSP (onsgmls, osx) is distributed under a permissive MIT-style licence that requires keeping its\n"
        "copyright notice. When taken from MSYS2, the msys-*.dll files are the MSYS2 runtime and GCC support\n"
        "libraries, under their own open-source licences (see the files in this folder, copied from\n"
        "MSYS2's usr\\share\\licenses). Keep this folder when you share the bundle.\n")
    if not copied:
        say("note: no licence files found next to OpenSP; add OpenSP's COPYING to vendor\\opensp\\LICENSES")


BAT_MAIN = r"""@echo off
rem ASTHRA portable launcher: starts ASTHRA on this computer only (127.0.0.1) and opens the browser.
setlocal
cd /d "%~dp0"
if not exist "%~dp0python\python.exe" (
  echo python\python.exe is missing. Extract the whole ASTHRA folder first.
  pause & exit /b 1
)
rem Portable data: schemas and projects stay in the "data" folder next to this file.
if not defined ASTHRA_DATA set "ASTHRA_DATA=%~dp0data"
echo Starting ASTHRA ... (data: %ASTHRA_DATA%)
echo Close this window or press Ctrl+C to stop ASTHRA.
"%~dp0python\python.exe" -m asthra.cli serve --open %*
if errorlevel 1 pause
"""

BAT_CLI = r"""@echo off
rem ASTHRA command line, e.g.:  ASTHRA-cli doctor   |   ASTHRA-cli add-schemas "C:\path\to\schemas"
setlocal
if not defined ASTHRA_DATA set "ASTHRA_DATA=%~dp0data"
"%~dp0python\python.exe" -m asthra.cli %*
"""

README = """ASTHRA {version} - portable edition for Windows
==============================================

No installation and no administrator rights are needed. Nothing is written outside this folder.

START
  1. If you downloaded the zip: right-click it > Properties > tick "Unblock" > OK   (before extracting)
  2. Extract the whole zip to a folder you can write to, e.g. C:\\Users\\<you>\\ASTHRA
     (not Program Files, and not inside the zip viewer)
  3. Double-click ASTHRA.bat. The browser opens at http://127.0.0.1:8765
     Keep the black window open while you work; closing it stops ASTHRA.

COMMAND LINE (optional)
  Open a Command Prompt in this folder and use ASTHRA-cli.bat, for example:
    ASTHRA-cli doctor
    ASTHRA-cli add-schemas "C:\\path\\to\\Issue 4.1"
    ASTHRA-cli schemas list

YOUR DATA
  Schemas, projects and documents are kept in the "data" folder here, so copying this folder copies
  everything. To use your Windows profile instead, set ASTHRA_DATA before starting, e.g.
    set ASTHRA_DATA=%LOCALAPPDATA%\\ASTHRA

SHARING
  - Whole setup: zip this folder (with or without "data") and send it.
  - Schemas only: in ASTHRA, Schemas > Manage > Export all schemas; the other person imports that file.

WHAT IS INSIDE (all readable, nothing packed or obfuscated)
  python\\          official embeddable Python {pyver} from python.org (python.exe is signed by the PSF)
  app\\asthra\\      ASTHRA; app\\asthra\\web\\dist is the interface; app\\tests\\fixtures are the samples
  app\\asthra\\vendor\\opensp\\  {opensp}
  ASTHRA.bat       launcher (plain text - open it in Notepad to see exactly what it does)

SECURITY
  ASTHRA only listens on 127.0.0.1 (this computer), never goes online, and reads schema and entity
  files only from what you install. See docs in the project for details.

IF IT DOES NOT START
  - "Windows protected your PC" (SmartScreen): More info > Run anyway, or ask IT to allow the folder.
  - Nothing happens / "not recognized": IT policy (AppLocker) may block programs in your user folders;
    ask IT to allow python\\python.exe in this folder.
  - "address already in use": another ASTHRA is running, or start on another port:
      ASTHRA.bat --port 8800
  - Run  ASTHRA-cli doctor  and send its output when asking for help.
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--python-zip", help="the embeddable Python zip (python-X.Y.Z-embed-amd64.zip), if already downloaded")
    ap.add_argument("--wheels", help="folder of pre-downloaded wheels (offline build)")
    ap.add_argument("--opensp-dir", help="folder with onsgmls.exe and osx.exe (default: the OpenSP ASTHRA uses)")
    ap.add_argument("--no-opensp", action="store_true", help="build without SGML support")
    ap.add_argument("--pyc-only", action="store_true", help="ship compiled .pyc files instead of .py sources")
    ap.add_argument("--out", default=str(ROOT / "dist"))
    ap.add_argument("--allow-non-windows", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()
    if os.name != "nt" and not args.allow_non_windows:
        sys.exit("Run this on Windows, with the Python version you want inside the bundle.")
    sys.path.insert(0, str(BACKEND))
    from asthra import __version__
    sys.path.pop(0)
    if not (BACKEND / "asthra" / "web" / "dist" / "index.html").is_file():
        sys.exit("The interface is not built (backend\\asthra\\web\\dist is missing).")

    out = Path(args.out)
    bundle = out / "ASTHRA"
    work = out / "_downloads"
    work.mkdir(parents=True, exist_ok=True)
    if bundle.exists():
        shutil.rmtree(bundle)
    bundle.mkdir(parents=True)
    print(f"Building portable ASTHRA {__version__} in {bundle}")

    setup_python(get_python_zip(args, work), bundle / "python")
    say("python: embeddable interpreter unpacked")
    install_libraries(args, bundle / "python" / "Lib" / "site-packages", work)
    copy_app(bundle / "app", args.pyc_only)
    say("app: ASTHRA copied" + (" (compiled .pyc only)" if args.pyc_only else ""))
    opensp_note = "not included (build with OpenSP to validate SGML)"
    if not args.no_opensp:
        tools = find_opensp(args)
        if tools:
            bundle_opensp(tools, bundle / "app" / "asthra" / "vendor" / "opensp")
            opensp_note = "OpenSP for SGML, with the DLLs it needs and its licences"
        else:
            say("OpenSP not found: the bundle works, but SGML cannot be validated (use --opensp-dir)")
    (bundle / "data").mkdir()
    (bundle / "ASTHRA.bat").write_text(BAT_MAIN.replace("\n", "\r\n"), encoding="ascii")
    (bundle / "ASTHRA-cli.bat").write_text(BAT_CLI.replace("\n", "\r\n"), encoding="ascii")
    pyver = ".".join(map(str, sys.version_info[:3]))
    (bundle / "README-PORTABLE.txt").write_text(
        README.format(version=__version__, pyver=pyver, opensp=opensp_note).replace("\n", "\r\n"), encoding="utf-8")

    zip_path = out / f"ASTHRA-portable-{__version__}-win64.zip"
    say(f"zipping {zip_path.name}")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(bundle.rglob("*")):
            if f.is_file():
                z.write(f, Path("ASTHRA") / f.relative_to(bundle))
    size = zip_path.stat().st_size / 1e6
    print(f"\nDone: {bundle}\n      {zip_path} ({size:.0f} MB)\n"
          f"Test it: double-click {bundle / 'ASTHRA.bat'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
