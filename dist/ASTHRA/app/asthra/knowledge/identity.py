"""Identity rules for product facts: how two records are recognised as the same thing.

Decisions (docs/06-KNOWLEDGE-MODEL.md §10):
  * Part = manufacturer code (CAGE / NCAGE) + part number. A part number without a manufacturer code
    is "unqualified": it can be *suggested* as a match, never merged automatically.
  * A CAGE/NCAGE code identifies a facility (a site), not a company: one organisation may have several.
    Codes are 5 characters; US codes start with a digit, NATO (NCAGE) codes of other countries are
    assigned by their national codification bureau (France: starting with F or M).
  * NSN (NATO stock number) = 4-digit supply class + 9-character NIIN (2-digit country code + 7).
    A secondary identifier: used to confirm, not to merge.
  * Breakdown elements carry typed identifiers (scheme + value [+ set by]), as S3000L does:
    SNS (from an S1000D DMC or IPD), ATA (chapter-section-subject of an iSpec 2200 manual), LCN (LSA).
  * CSN (catalogue sequence number) = SNS + figure + figure variant + item + item variant; stored
    structured (as S1000D 4.x+ attributes), written as the 13-character (6-character SNS) or
    16-character (9-character SNS) string of S2000M when needed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


# ------------------------------------------------------------------ parts and manufacturers
def normalize_part_number(pn: str | None) -> str:
    """Comparison form: trimmed, inner whitespace removed, upper case. Punctuation is kept
    (dashes and slashes are significant in part numbers)."""
    return re.sub(r"\s+", "", pn or "").upper()


@dataclass(frozen=True)
class CageCheck:
    code: str
    ok: bool
    origin: str          # "US" | "NATO/other" | "unknown"
    note: str = ""


def check_cage(code: str | None) -> CageCheck:
    c = (code or "").strip().upper()
    if not c:
        return CageCheck("", False, "unknown", "no manufacturer code")
    if not re.fullmatch(r"[0-9A-Z]{5}", c):
        return CageCheck(c, False, "unknown", "a CAGE/NCAGE code has exactly 5 letters or digits")
    if c[0].isdigit():
        note = "" if not re.search(r"[IO]", c) else "US CAGE codes do not use the letters I and O"
        return CageCheck(c, not note, "US", note)
    return CageCheck(c, True, "NATO/other")


@dataclass(frozen=True)
class PartKey:
    manufacturer: str        # CAGE/NCAGE, "" if unknown
    part_number: str         # normalised

    @property
    def qualified(self) -> bool:
        return bool(self.manufacturer)

    def __str__(self) -> str:
        return f"{self.manufacturer or '?????'}:{self.part_number}"


def part_key(manufacturer: str | None, part_number: str | None) -> PartKey:
    return PartKey((manufacturer or "").strip().upper(), normalize_part_number(part_number))


def same_part(a: PartKey, b: PartKey) -> str:
    """'same' (qualified keys equal), 'possible' (same part number, a manufacturer missing on one side),
    or 'different'. Only 'same' may merge records automatically."""
    if a.part_number != b.part_number or not a.part_number:
        return "different"
    if a.qualified and b.qualified:
        return "same" if a.manufacturer == b.manufacturer else "different"
    return "possible"


# ------------------------------------------------------------------ NSN
@dataclass(frozen=True)
class Nsn:
    supply_class: str     # 4 digits (NSC/FSC)
    niin: str             # 9 characters
    @property
    def country(self) -> str:
        return self.niin[:2]
    def __str__(self) -> str:
        return f"{self.supply_class}-{self.niin[:2]}-{self.niin[2:5]}-{self.niin[5:]}"


def parse_nsn(text: str | None) -> Nsn | None:
    t = re.sub(r"[\s-]", "", text or "")
    if not re.fullmatch(r"\d{4}[0-9A-Z]{9}", t):
        return None
    return Nsn(t[:4], t[4:])


# ------------------------------------------------------------------ breakdown identifiers
@dataclass(frozen=True)
class BreakdownId:
    scheme: str           # "SNS" | "ATA" | "LCN" | project-defined
    value: str
    set_by: str = ""      # organisation that assigned it (S3000L identifierSetBy)
    def __str__(self) -> str:
        return f"{self.scheme}:{self.value}" + (f"@{self.set_by}" if self.set_by else "")


def sns_from_dmcode(attrs: dict[str, str]) -> BreakdownId:
    """SNS from S1000D dmCode attributes: system-subsystem subsubsystem-assy (e.g. 25-30-12 or 72-58-26)."""
    return BreakdownId("SNS", f"{attrs.get('systemCode', '')}-{attrs.get('subSystemCode', '')}"
                              f"{attrs.get('subSubSystemCode', '')}-{attrs.get('assyCode', '')}")


def ata_from_ispec(chapnbr: str, sectnbr: str, subjnbr: str) -> BreakdownId:
    """ATA chapter-section-subject of an iSpec 2200 manual (e.g. CMM 25-26-62)."""
    return BreakdownId("ATA", f"{chapnbr}-{sectnbr}-{subjnbr}")


def ata_chapter(b: BreakdownId) -> str:
    """The ATA chapter an SNS or ATA identifier belongs to (civil aircraft SNS follow ATA chapters)."""
    return b.value.split("-")[0] if b.scheme in ("SNS", "ATA") else ""


# ------------------------------------------------------------------ CSN
@dataclass(frozen=True)
class Csn:
    system: str
    subsystem: str
    subsubsystem: str
    assy: str
    figure: str
    figure_variant: str = ""
    item: str = ""
    item_variant: str = ""

    @classmethod
    def from_s1000d(cls, a: dict[str, str]) -> "Csn":
        """From S1000D (4.x and later) catalogSeqNumber attributes."""
        return cls(a.get("systemCode", ""), a.get("subSystemCode", ""), a.get("subSubSystemCode", ""),
                   a.get("assyCode", ""), a.get("figureNumber", ""), a.get("figureNumberVariant", ""),
                   a.get("item", ""), a.get("itemVariant", ""))

    @property
    def sns(self) -> str:
        return f"{self.system}{self.subsystem}{self.subsubsystem}{self.assy}"

    def s2000m(self) -> str:
        """The fixed-length S2000M string: SNS (6 or 9 characters) + figure (2) + figure variant (1)
        + item (3) + item variant (1) = 13 or 16 characters. Variants that are not used are spaces."""
        sns = self.sns
        if len(sns) not in (6, 9):
            raise ValueError(f"SNS '{sns}' is neither 6 nor 9 characters; the S2000M form cannot be written")
        return (sns + self.figure.rjust(2, "0")[:2] + (self.figure_variant or " ")[:1]
                + self.item.rjust(3, "0")[-3:] + (self.item_variant or " ")[:1])

    def __str__(self) -> str:
        fv = self.figure_variant or ""
        iv = self.item_variant or ""
        return f"{self.system}-{self.subsystem}{self.subsubsystem}-{self.assy} fig {self.figure}{fv} item {self.item}{iv}"
