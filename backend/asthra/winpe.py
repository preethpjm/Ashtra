"""Windows executables: which DLLs a program needs (read from its import tables).

Used to copy OpenSP with exactly the DLLs it depends on (export-opensp, portable build),
without guessing and without copying a whole MSYS2 installation.
"""
from __future__ import annotations

import struct
from pathlib import Path


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
