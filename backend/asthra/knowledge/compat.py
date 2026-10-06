"""Which issues of the S-Series belong together, and which installed issue to use.

The S-Series (except S1000D, which has its own release cycle) is published in coordinated block
releases. The table is data: a project can add its own pairings (e.g. an agreed S1000D issue for
an S2000M issue) in the project's compat file.
"""
from __future__ import annotations

from dataclasses import dataclass

# Published block releases (issue numbers as published by the S-Series steering committees).
BLOCK_RELEASES: list[dict[str, str]] = [
    {"name": "S-Series 2021 block release", "S2000M": "7.0", "S3000L": "2.0", "SX002D": "2.1"},
]


@dataclass
class Pick:
    standard: str
    issue: str | None
    how: str            # "block release" | "only installed issue" | "choose" | "not installed" | "project rule"
    options: list[str]
    note: str = ""


def pick_counterpart(installed: list[tuple[str, str]], have: tuple[str, str], want: str,
                     project_pairs: list[dict[str, str]] | None = None) -> Pick:
    """installed: (standard, issue) pairs of installed schema packages; have: the document's (standard,
    issue); want: the standard to fill (e.g. "S3000L"). Chooses automatically only when unambiguous."""
    std, iss = have[0].upper(), have[1]
    want = want.upper()
    options = sorted({i for s, i in installed if s.upper() == want})
    if not options:
        return Pick(want, None, "not installed", [], f"No {want} schemas are installed.")
    for table, how in ((project_pairs or [], "project rule"), (BLOCK_RELEASES, "block release")):
        for row in table:
            if row.get(std) == iss and row.get(want) in options:
                return Pick(want, row[want], how, options, row.get("name", ""))
    if len(options) == 1:
        return Pick(want, options[0], "only installed issue", options,
                    f"{std} {iss} and {want} {options[0]} are not listed together in a block release; "
                    "check that they are compatible for this project.")
    return Pick(want, None, "choose", options, f"Several {want} issues are installed; choose one.")
