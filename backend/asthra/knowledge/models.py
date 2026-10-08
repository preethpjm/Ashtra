"""3D models (GLB) in the knowledge library: kept in the data folder, their node names indexed, and parts located
in them by part number (directly, or through the 3D ↔ MBOM reconciliation links).

A node is taken to show a part when its name is the part number (or the 3D item name the reconciliation linked to
the part), optionally followed by an instance suffix (_1, .001, :2, " (3)"), or contains it as a whole token
("F6137-C75930" shows C75930). Part numbers shorter than 4 characters are only matched exactly.
"""
from __future__ import annotations

import json
import re
import struct

_NORM = re.compile(r"\s+")
_INSTANCE = re.compile(r"^(?:[.:#-]+\d{1,4}|\(\d+\)|<\d+>)$")   # after norm(): _1 → -1, " (3)" → (3)


def norm(s: str) -> str:
    return _NORM.sub("", str(s or "")).upper().replace("_", "-").replace("/", "-")


def node_shows(node: str, cand: str) -> bool:
    n, c = norm(node), norm(cand)
    if not n or not c:
        return False
    if n == c or (n.startswith(c) and _INSTANCE.match(n[len(c):])):
        return True
    if len(c) < 4:
        return False
    i = n.find(c)
    while i >= 0:
        before_ok = i == 0 or not n[i - 1].isalnum()
        rest = n[i + len(c):]
        if before_ok and (not rest or not rest[0].isalnum() and (_INSTANCE.match(rest) or rest[0] in "-.:#(")):
            return True
        i = n.find(c, i + 1)
    return False


def glb_json(data: bytes) -> dict:
    """The JSON chunk of a binary glTF (GLB) file."""
    if len(data) < 20 or data[:4] != b"glTF":
        raise ValueError("not a GLB file (binary glTF)")
    _, _, length = struct.unpack_from("<4sII", data, 0)
    clen, ctype = struct.unpack_from("<II", data, 12)
    if ctype != 0x4E4F534A:            # 'JSON'
        raise ValueError("GLB file without a JSON chunk")
    return json.loads(data[20:20 + clen].decode("utf-8"))


def glb_node_names(data: bytes) -> list[str]:
    g = glb_json(data)
    out = []
    meshes = g.get("meshes") or []
    for n in g.get("nodes") or []:
        name = n.get("name") or ""
        if not name and "mesh" in n and n["mesh"] < len(meshes):
            name = meshes[n["mesh"]].get("name") or ""
        out.append(name)
    return out
