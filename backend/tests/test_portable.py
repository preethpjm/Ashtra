"""The portable Windows build script (tools/make_portable.py): the parts that can be tested anywhere."""
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import make_portable as mp  # noqa: E402


def tiny_pe(imports: list[str]) -> bytes:
    """A minimal PE32+ file with an import table naming the given DLLs."""
    b = bytearray(0x400)
    b[0:2] = b"MZ"
    struct.pack_into("<I", b, 0x3C, 0x40)
    b[0x40:0x44] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", b, 0x44, 0x8664, 1, 0, 0, 0, 240, 0x22)
    opt = 0x58
    struct.pack_into("<H", b, opt, 0x20B)
    dd = opt + 112
    struct.pack_into("<II", b, dd + 8, 0x1000, 20 * (len(imports) + 1))         # import directory
    sec = opt + 240
    b[sec:sec + 8] = b".idata\0\0"
    struct.pack_into("<IIII", b, sec + 8, 0x200, 0x1000, 0x200, 0x200)         # VirtualSize, VA, raw size, raw ptr
    name_off = 0x100
    for i, name in enumerate(imports):
        struct.pack_into("<IIIII", b, 0x200 + 20 * i, 0, 0, 0, 0x1000 + name_off, 0)
        b[0x200 + name_off:0x200 + name_off + len(name) + 1] = name.encode() + b"\0"
        name_off += len(name) + 1
    return bytes(b)


def test_pe_imports_are_read():
    p = Path(__file__).parent / "_tmp_a.exe"
    try:
        p.write_bytes(tiny_pe(["msys-2.0.dll", "KERNEL32.dll"]))
        assert mp.pe_imports(p) == ["msys-2.0.dll", "KERNEL32.dll"]
    finally:
        p.unlink(missing_ok=True)


def test_dll_closure_takes_only_what_is_needed(tmp_path):
    (tmp_path / "onsgmls.exe").write_bytes(tiny_pe(["msys-osp-5.dll", "KERNEL32.dll"]))
    (tmp_path / "osx.exe").write_bytes(tiny_pe(["msys-osp-5.dll"]))
    (tmp_path / "msys-osp-5.dll").write_bytes(tiny_pe(["msys-2.0.dll", "msys-stdc++-6.dll"]))
    (tmp_path / "msys-2.0.dll").write_bytes(tiny_pe(["KERNEL32.dll"]))
    (tmp_path / "msys-stdc++-6.dll").write_bytes(tiny_pe(["msys-2.0.dll"]))
    (tmp_path / "msys-unrelated.dll").write_bytes(tiny_pe([]))
    got = {p.name for p in mp.dll_closure([tmp_path / "onsgmls.exe", tmp_path / "osx.exe"])}
    assert got == {"onsgmls.exe", "osx.exe", "msys-osp-5.dll", "msys-2.0.dll", "msys-stdc++-6.dll"}


def test_non_pe_files_are_ignored(tmp_path):
    (tmp_path / "x.dll").write_text("not a program")
    assert mp.pe_imports(tmp_path / "x.dll") == []


def test_embedded_python_path_file(tmp_path):
    import zipfile
    z = tmp_path / "py.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("python310._pth", "python310.zip\n.\n\n# Uncomment to run site.main() automatically\n#import site\n")
        f.writestr("python.exe", "stub")
    mp.setup_python(z, tmp_path / "python")
    lines = (tmp_path / "python" / "python310._pth").read_text().split()
    assert lines == ["python310.zip", ".", "Lib\\site-packages", "..\\app", "import", "site"]
    assert (tmp_path / "python" / "Lib" / "site-packages").is_dir()


def test_launchers_are_plain_windows_text():
    assert "\r" not in mp.BAT_MAIN                       # written with CRLF at build time
    assert "python\\python.exe\" -m asthra.cli serve --open" in mp.BAT_MAIN
    assert "ASTHRA_DATA=%~dp0data" in mp.BAT_MAIN and "ASTHRA_DATA=%~dp0data" in mp.BAT_CLI
