"""How a neutral value is written in a slot and read back (the binding's "format" of a field)."""
from __future__ import annotations

import re

FORMATS = {
    "": "as is",
    "pad3": "item as 3 digits (050), variant written separately",
    "join_variant": "item and variant together without leading zeros (50A)",
    "pad3_join": "item as 3 digits with the variant appended (050A)",
    "zero_based": "indenture counted from 0 (top = 0)",
    "rf_top": "quantity; RF for the assembly the list is of",
    "vendor_v": "vendor code: V + CAGE (left out for the CAGEs the rules list)",
    "invert01": "0 when true, 1 when false",
    "bool01": "1 when true, 0 when false",
    "presence": "an empty element when true",
    "split_kwd_adt": "name split into keyword and modifier at the first comma",
}


def split_item(item: str) -> tuple[str, str]:
    m = re.match(r"^\s*-?\s*0*(\d+)\s*([A-Za-z]*)\s*$", str(item or ""))
    return (m.group(1).zfill(3), m.group(2).upper()) if m else (str(item or "").strip(), "")


def write(field: str, fmt: str | None, rec: dict, rules: dict) -> list[str] | None:
    """-> values to write (several for a repeating slot), or None to leave the slot out."""
    v = rec.get(field)
    fmt = fmt or ""
    if field == "item":
        base, var = rec.get("item") or "", rec.get("item_variant") or ""
        if fmt == "join_variant":
            return [(base.lstrip("0") or "0") + var]
        if fmt == "pad3_join":
            return [base + var]
        return [base]
    if field == "item_variant":
        return [v] if v else None
    if field == "indenture":
        if v in (None, ""):
            return None
        return [str(int(v) - 1 if fmt == "zero_based" else int(v))]
    if field == "quantity":
        if fmt == "rf_top" and rec.get("top"):
            return ["RF"]
        return [str(v)] if v not in (None, "") else None
    if field == "cage":
        if not v or v in (rules.get("omit_cage") or []):
            return None
        return ["V" + v] if fmt == "vendor_v" else [v]
    if field in ("not_illustrated", "attaching"):
        b = bool(v)
        if fmt == "invert01":
            return ["0" if b else "1"]
        if fmt == "bool01":
            return ["1" if b else "0"]
        if fmt == "presence":
            return [""] if b else None
        return ["1" if b else "0"]
    if field == "unit":
        return None if not v or v in (rules.get("omit_unit") if rules.get("omit_unit") is not None else ["EA"]) else [str(v)]
    if field == "effectivity":
        if not v:
            return None
        parts = [p.strip() for p in str(v).split(",") if p.strip()]
        return parts or None
    if v in (None, ""):
        return None
    if field == "name" and rules.get("uppercase_names"):
        return [str(v).upper()]
    return [str(v)]


def read(field: str, fmt: str | None, text: str) -> dict:
    """-> neutral fields from one slot's text."""
    t = (text or "").strip()
    fmt = fmt or ""
    if field == "item":
        base, var = split_item(t)
        return {"item": base, "item_variant": var} if fmt in ("join_variant", "pad3_join") or var else {"item": base}
    if field == "indenture":
        try:
            return {"indenture": int(t) + (1 if fmt == "zero_based" else 0)}
        except ValueError:
            return {}
    if field == "quantity":
        if t.upper() in ("RF", "REF"):
            return {"quantity": "1", "top": True}
        return {"quantity": t}
    if field == "cage":
        return {"cage": t[1:] if fmt == "vendor_v" and len(t) == 6 and t.upper().startswith("V") else t}
    if field in ("not_illustrated", "attaching"):
        if fmt == "invert01":
            return {field: t == "0"}
        if fmt == "presence":
            return {field: True}
        return {field: t in ("1", "true", "yes", "y")}
    return {field: t}
