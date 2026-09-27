"""SGML validation and rendering through OpenSP (onsgmls, osx), e.g. legacy ATA iSpec 2200.

Safety: OpenSP runs on a private copy of the document in a temporary folder, in restricted
mode (-R): it may only read that folder and the installed package (-D). Remote addresses in
the document's DOCTYPE are removed from the copy (OpenSP would otherwise try the network),
and the DOCTYPE is pointed at the package's own DTD. Line numbers are kept exact.

Rendering: osx converts the SGML to XML (names lower-cased, ISO SDATA characters kept as
markers and mapped to Unicode). The document view shows that XML read-only; the SGML source
stays the authority and is what is edited and saved.
"""
from __future__ import annotations

import difflib
import html.entities
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .model import Fix

OPEN_SP_HELP = ("Install OpenSP (onsgmls and osx) to validate and render SGML. Windows: install MSYS2 (msys2.org), "
                "run 'pacman -S opensp' in the MSYS2 MSYS shell, then 'python -m asthra.cli install-opensp "
                "C:\\msys64\\usr\\bin' and restart ASTHRA. Linux: install the 'opensp' package. "
                "(sourceforge.net/projects/openjade also has an old Win32 build, which often needs missing DLLs.)")
_URL = re.compile(r"""(["'])(?:https?|ftp)://[^"']*\1""", re.I)
# messages start with the program path as invoked, e.g. /usr/bin/onsgmls: or C:\\osp\\onsgmls.exe:
_PROG = r"^(?:.*[\\/])?(?:onsgmls|osx)(?:\.exe)?:"
_MSG = re.compile(_PROG + r"(.*?):(\d+):(\d+):([EWXIQ]):\s*(.*)$", re.I)
_GLOBAL = re.compile(_PROG + r"([EWXIQ]):\s*(.*)$", re.I)


VENDOR_DIR = Path(__file__).resolve().parent.parent / "vendor" / "opensp"     # shipped with an installer


def tools_dir() -> Path:
    """Where `asthra install-opensp` puts OpenSP (inside the data folder, so it survives updates)."""
    from ..config import default_data_root
    return default_data_root() / "tools" / "opensp"


def _in_tree(folder: Path) -> tuple[str, str] | None:
    """onsgmls and osx side by side anywhere under folder (zips often nest a bin folder)."""
    if not folder.is_dir():
        return None
    for d in [folder, *sorted(p for p in folder.rglob("*") if p.is_dir())]:
        a, b = shutil.which("onsgmls", path=str(d)), shutil.which("osx", path=str(d))
        if a and b:
            return a, b
    return None


def registered_dir() -> Path | None:
    """A folder registered in place (e.g. MSYS2's usr\\bin), recorded by install-opensp."""
    f = tools_dir().parent / "opensp.path"
    try:
        p = Path(f.read_text(encoding="utf-8").strip())
        return p if p.is_dir() else None
    except OSError:
        return None


def find_tools() -> tuple[str, str] | None:
    """OpenSP, looked for in this order:
      1. ASTHRA_OPENSP (a folder), if set
      2. the data folder: a copy made by `install-opensp`, or a folder it registered in place
      3. vendor/opensp inside the program (for packaged installers)
      4. the system PATH"""
    env = os.environ.get("ASTHRA_OPENSP")
    if env:
        return _in_tree(Path(env))
    reg = registered_dir()
    if reg:
        found = [shutil.which(n, path=str(reg)) for n in ("onsgmls", "osx")]
        if all(found):
            return found[0], found[1]
    for folder in (tools_dir(), VENDOR_DIR):
        hit = _in_tree(folder)
        if hit:
            return hit
    found = [shutil.which(n) for n in ("onsgmls", "osx")]
    return (found[0], found[1]) if all(found) else None


def redirect_doctype(text: str, root: str, dtd_rel: str) -> tuple[str, int]:
    """Point the copy at the package DTD and drop remote addresses; keep line numbers."""
    m = re.search(r"<!DOCTYPE\s+([^\s\[>]+)", text, re.I)
    removed = 0
    if m:
        after = m.end()
        ext = re.compile(r"""\s+(?:PUBLIC\s+("[^"]*"|'[^']*')(?:\s+("[^"]*"|'[^']*'))?|SYSTEM(?:\s+("[^"]*"|'[^']*'))?)""", re.I).match(text, after)
        new = f' SYSTEM "{dtd_rel}"'
        if ext:
            new += "\n" * text.count("\n", ext.start(), ext.end())
            text = text[:ext.start()] + new + text[ext.end():]
        else:
            text = text[:after] + new + text[after:]
        # remote addresses inside the internal subset
        end = text.find(">", after) if "[" not in text[after:after + 400].split(">")[0] else text.find("]", after)
        head, tail = text[:max(end, after)], text[max(end, after):]
        head, removed = _URL.subn('""', head)
        text = head + tail
    else:
        i = re.search(r"<[A-Za-z]", text)
        if i:
            text = text[:i.start()] + f'<!DOCTYPE {root} SYSTEM "{dtd_rel}">' + text[i.start():]
    return text, removed


class SgmlToolError(Exception):
    """OpenSP itself failed to run (as opposed to reporting problems in the document)."""


def tool_env(tools: tuple[str, str]) -> dict:
    """Environment for running OpenSP: its folder and any DLL folders from the same download are
    put first on PATH, because Windows looks for DLLs there, not in sibling folders."""
    tool_dir = Path(tools[0]).parent
    root = tool_dir.parent if tool_dir.name.lower() in ("bin", "release", "debug") else tool_dir
    dirs = [tool_dir]
    try:
        if root != tool_dir and sum(1 for _ in root.rglob("*")) < 2000:
            dirs += sorted({p.parent for p in root.rglob("*.dll")} - {tool_dir})[:20]
    except OSError:
        pass
    env = dict(os.environ, SP_CHARSET_FIXED="YES", SP_ENCODING="UTF-8", SGML_CATALOG_FILES="", SGML_SEARCH_PATH="")
    env["PATH"] = os.pathsep.join([str(d) for d in dirs] + [env.get("PATH", "")])
    return env


@dataclass
class SgmlResult:
    messages: list[tuple[int | None, int | None, str, str]] = field(default_factory=list)   # line, col, type, text
    xml: str | None = None
    removed_urls: int = 0
    refused: list[str] = field(default_factory=list)
    entities: dict[str, str] = field(default_factory=dict)


def sdata_char(name: str) -> str:
    cp = html.entities.name2codepoint.get(name)
    if cp:
        return chr(cp)
    return html.entities.html5.get(name + ";") or f"[{name}]"


def _sdata_to_entities(xml: str) -> tuple[str, dict[str, str]]:
    """Keep ISO SDATA characters as entity references (&deg;), declared in a DOCTYPE with the
    character they stand for. The view shows the character; writing SGML back keeps &deg;."""
    names: dict[str, str] = {}
    def rep(m):
        n = m.group(1)
        names[n] = sdata_char(n)
        return f"&{n};"
    body = re.sub(r"<\?sdataEntity\s+([A-Za-z0-9._-]+)\s[^?]*\?>", rep, xml)
    decl_end = body.find("?>") + 2 if body.startswith("<?xml") else 0
    root = re.search(r"<([A-Za-z][\w.:-]*)", body[decl_end:])
    if names and root:
        esc = lambda v: v.replace("&", "&#38;").replace('"', "&#34;").replace("%", "&#37;")
        subset = "".join(f'<!ENTITY {n} "{esc(v)}">' for n, v in sorted(names.items()))
        body = body[:decl_end] + f"\n<!DOCTYPE {root.group(1)} [{subset}]>" + body[decl_end:]
    return body, names


MAX_PACKAGE_BYTES = 100 * 1024 * 1024


def _copy_package(pkg_dir: Path, dest: Path) -> None:
    total = 0
    for f in pkg_dir.rglob("*"):
        if not f.is_file() or f.name == "asthra-package.json":
            continue
        total += f.stat().st_size
        if total > MAX_PACKAGE_BYTES:
            raise SgmlToolError("the DTD set is too large to run OpenSP on (over 100 MB)")
        target = dest / f.relative_to(pkg_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, target)


def run(text: str, root: str, pkg_dir: Path, dtd_rel: str, catalogs: list[str], decl: str | None,
        tools: tuple[str, str], render: bool = True, timeout: int = 90) -> SgmlResult:
    onsgmls, osx = tools
    pkg_dir = Path(pkg_dir).resolve()        # OpenSP runs in a temporary folder
    res = SgmlResult()
    copy, res.removed_urls = redirect_doctype(text, root, dtd_rel)
    env = tool_env(tools)
    with tempfile.TemporaryDirectory() as tmp:
        # OpenSP only ever sees relative names inside its private working folder: the DTD set is
        # copied next to the document. No absolute path is passed, which matters because some
        # Windows builds (e.g. MSYS2's, a POSIX-style program) do not read C:\\ paths as absolute.
        _copy_package(pkg_dir, Path(tmp))
        (Path(tmp) / "doc.sgm").write_text(copy, encoding="utf-8")
        common = ["-R", "-D", "."]
        for c in catalogs:
            common += ["-c", Path(c).as_posix()]
        files = ([decl] if decl else []) + ["doc.sgm"]
        try:
            p = subprocess.run([onsgmls, "-s", *common, *files], cwd=tmp, env=env, capture_output=True, timeout=timeout,
                               stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise SgmlToolError(f"OpenSP could not be run: {e}") from e
        why = explain_exit(p.returncode)
        if why:
            raise SgmlToolError(f"{why} (exit code 0x{p.returncode & 0xFFFFFFFF:08X})")
        stderr = p.stderr.decode("utf-8", "replace")
        if p.returncode != 0 and not any(_MSG.match(l) or _GLOBAL.match(l) for l in stderr.splitlines()):
            # onsgmls exits 1 when a document has errors, but always says what they are
            raise SgmlToolError(f"OpenSP failed without reporting why (exit code {p.returncode}). "
                                f"{stderr.strip()[:300]}")
        pkg_missing = [l for l in stderr.splitlines()
                       if (_GLOBAL.match(l) or _MSG.match(l)) and "cannot find" in l and "doc.sgm:" not in l.replace("\\", "/")]
        if pkg_missing:
            # OpenSP could not open the installed DTD set's own files: a setup problem, not a document error
            raise SgmlToolError("OpenSP could not open the installed DTD set's files: " + pkg_missing[0].split(":", 1)[-1].strip())
        for line in stderr.splitlines():
            m = _MSG.match(line)
            if m:
                fname, ln, col, typ, msg = m.groups()
                if typ in "EXWQ":
                    in_doc = fname.replace("\\", "/").endswith("doc.sgm")
                    res.messages.append((int(ln) if in_doc else None, int(col) if in_doc else None, typ, msg.strip()))
                    if msg.startswith("cannot find") and in_doc:
                        res.refused.append(msg)
                continue
            g = _GLOBAL.match(line)
            if g and g.group(1) in "EX":
                res.messages.append((None, None, g.group(1), g.group(2).strip()))
        if render:
            o = subprocess.run([osx, *common, "-xlower", "-xempty", "-xno-nl-in-tag", "-xsdata-as-pis", "-xcomment", *files],
                               cwd=tmp, env=env, capture_output=True, timeout=timeout,
                           stdin=subprocess.DEVNULL)
            out = o.stdout.decode("utf-8", "replace")
            if "<" in out and out.strip() != '<?xml version="1.0"?>':
                res.xml, res.entities = _sdata_to_entities(out)
    return res


def explain_sgml(raw: str) -> tuple[str, str | None, str | None, str | None, Fix | None]:
    """-> (message, suggestion, attribute, value, fix). OpenSP folds names to upper case."""
    if (m := re.match(r'element "(\S+)" undefined', raw)):
        return f"<{m[1].lower()}> is not defined in this DTD.", "Check the spelling, or remove it.", None, None, None
    if (m := re.match(r'document type does not allow element "(\S+)" here(.*)', raw)):
        rest = m[2]
        miss = re.findall(r'"(\S+)"', rest)
        sugg = ("The DTD expects " + " or ".join(f"<{x.lower()}>" for x in miss) + " first.") if miss else "Move or remove it."
        return f"<{m[1].lower()}> is not allowed at this position.", sugg, None, None, None
    if (m := re.match(r'required attribute "(\S+)" not specified', raw)):
        a = m[1].lower()
        return f"A required attribute {a} is missing.", f'Add {a}="…".', a, None, None
    if (m := re.match(r'there is no attribute "(\S+)"', raw)):
        a = m[1].lower()
        return f"Attribute {a} is not allowed here.", f"Remove {a}, or check its spelling.", a, None, None
    if (m := re.match(r'value of attribute "(\S+)" cannot be "(.*)"; must be one of (.*)$', raw)):
        a, v = m[1].lower(), m[2]
        allowed = re.findall(r'"([^"]*)"', m[3])
        ci = [x for x in allowed if x.lower() == v.lower()]
        close = ci or difflib.get_close_matches(v.lower(), [x.lower() for x in allowed], n=3, cutoff=0.7)
        close = [next((x for x in allowed if x.lower() == c.lower()), c) for c in close]
        sugg = ("Did you mean " + " or ".join(f"'{c}'" for c in close) + "?") if close else "Allowed: " + ", ".join(allowed) + "."
        fix = Fix(label=f"Replace with '{close[0]}'", kind="attr", attribute=a, value=close[0]) if len(close) == 1 else None
        return f"'{v}' is not an allowed value for attribute {a}.", sugg, a, v, fix
    if (m := re.match(r'general entity "(\S+)" not defined', raw)):
        return f"&{m[1]}; is not declared in the DTD or its entity sets.", "Check the name, or install the entity files with the DTD set.", None, m[1], None
    if (m := re.match(r'reference to non-existent ID "(\S+)"', raw)):
        return f"Reference '{m[1]}' does not match any ID in this document.", "Correct the reference or add the referenced element.", None, m[1], None
    if (m := re.match(r'ID "(\S+)" already defined', raw)):
        return f"ID '{m[1]}' is used more than once.", "Every id must be unique in the document.", None, m[1], None
    if (m := re.match(r'end tag for element "(\S+)" which is not open', raw)):
        return f"There is an end tag </{m[1].lower()}> without a matching start tag.", "Remove it or add the start tag.", None, None, None
    if (m := re.match(r'end tag for "(\S+)" omitted, but OMITTAG NO was specified', raw)):
        return f"</{m[1].lower()}> is missing; this DTD does not allow end tags to be left out.", f"Add </{m[1].lower()}>.", None, None, None
    if (m := re.match(r'end tag for "(\S+)" which is not finished', raw)):
        return f"<{m[1].lower()}> ends before its required content is complete.", "Add the missing content, or check the lines above.", None, None, None
    if raw.startswith("character data is not allowed here"):
        return "Text is not allowed at this position.", "Put the text inside an element that allows text.", None, None, None
    if (m := re.match(r'cannot find "(.*)"', raw)):
        return ("The document refers to a file that is outside the document and the installed DTD set; it was not read.",
                m[1], None, None, None)
    return raw, None, None, None, None


# Windows NTSTATUS codes a program returns when it cannot even start
_NT_EXIT = {
    0xC0000135: "Windows could not start it: a required DLL is missing (for the old SourceForge build this is usually "
                "the Visual C++ 2003 runtime, msvcr71.dll / msvcp71.dll). Use the MSYS2 build instead.",
    0xC000007B: "Windows could not start it: a DLL is for the wrong architecture (32/64-bit mismatch) or damaged.",
    0xC0000142: "Windows could not start it: a DLL failed to initialise.",
    0xC0000139: "Windows could not start it: a DLL is too old or does not match (entry point not found).",
}


def explain_exit(code: int) -> str | None:
    return _NT_EXIT.get(code & 0xFFFFFFFF)


def probe(tools: tuple[str, str]) -> tuple[bool, str]:
    """Does this OpenSP actually work? Runs onsgmls on a tiny SGML document with an inline DTD."""
    onsgmls = tools[0]
    try:
        v = subprocess.run([onsgmls, "--version"], capture_output=True, timeout=20, stdin=subprocess.DEVNULL,
                           env=tool_env(tools))
    except OSError as e:
        return False, f"it could not be started: {e}"
    except subprocess.TimeoutExpired:
        return False, "it did not respond within 20 seconds"
    why = explain_exit(v.returncode)
    if why:
        return False, f"{why} (exit code 0x{v.returncode & 0xFFFFFFFF:08X})"
    out = (v.stderr + v.stdout).decode("utf-8", "replace").strip()
    version = next((l for l in out.splitlines() if "version" in l.lower()), "")
    with tempfile.TemporaryDirectory() as tmp:
        # same way ASTHRA really runs it: restricted mode, a catalog, a DTD found through it
        (Path(tmp) / "t.dtd").write_text('<!ELEMENT a - - (#PCDATA)>\n', encoding="ascii")
        (Path(tmp) / "CATALOG").write_text('PUBLIC "-//ASTHRA//DTD probe//EN" "t.dtd"\n', encoding="ascii")
        (Path(tmp) / "t.sgm").write_text('<!DOCTYPE a PUBLIC "-//ASTHRA//DTD probe//EN">\n<a>ok</a>\n', encoding="ascii")
        try:
            r = subprocess.run([onsgmls, "-s", "-R", "-D", ".", "-c", "CATALOG", "t.sgm"], cwd=tmp,
                               capture_output=True, timeout=20, stdin=subprocess.DEVNULL, env=tool_env(tools))
        except (OSError, subprocess.TimeoutExpired) as e:
            return False, f"it started but could not parse a test document: {e}"
        why = explain_exit(r.returncode)
        if why:
            return False, f"{why} (exit code 0x{r.returncode & 0xFFFFFFFF:08X})"
        if r.returncode != 0:
            msg = (r.stderr + r.stdout).decode("utf-8", "replace").strip() or "no message"
            return False, f"it failed on a tiny valid SGML test document (exit code {r.returncode}): {msg[:300]}"
    return True, version.split(":", 2)[-1].strip() if version else "works (no version reported)"
