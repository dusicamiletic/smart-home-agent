"""Two-pass blob parser (plan section 03, stage 2 of the build pipeline).

Pass 1, the vocabulary harvest, already happened by hand -- see
scripts/census.py, scripts/vocab_check.py and build/vocabulary.json. This
module is pass 2: parse one product's raw `attributes` blob against that
harvested vocabulary.

The load-bearing rule here (see docs/decisions.md, "Validated the header
list against all 943"): the line immediately after opening a section must
be forced to be a key, and never re-checked against the header set. Every
*subsequent* key-position within that section IS checked against the header
set, since that's how the next section's boundary is detected. Skipping this
rule breaks on the one real product where a header name is reused as its
own section's key (`Beständigkeit` used as both the header and, on that one
product, the key name for "Witterungsbeständig").
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

_VOCAB_PATH = Path(__file__).resolve().parent.parent.parent / "build" / "vocabulary.json"


def _load_headers() -> frozenset[str]:
    data = json.loads(_VOCAB_PATH.read_text(encoding="utf-8"))
    return frozenset(data["section_headers"])


SECTION_HEADERS = _load_headers()


@dataclass
class ParsedAttributes:
    """Stage-2 output: still raw German strings, not normalized yet."""

    tags: list[str] = field(default_factory=list)
    attrs: dict[str, str] = field(default_factory=dict)
    # Lines the parser couldn't place anywhere -- a dangling key with no
    # value, or (in theory) a line before the first header that somehow
    # collides with header text. Logged, never silently dropped: an
    # unparseable line is a data-absence bug we want visible in the build
    # report, not a crash.
    orphans: list[str] = field(default_factory=list)


def parse_attributes(blob: str) -> ParsedAttributes:
    """Parse one product's raw `attributes` blob.

    Splits off the variable-length tag preamble, then flattens every
    section's key/value pairs into one dict. Sections themselves carry no
    information this project needs once they've delimited their pairs, so
    they're discarded rather than kept as nested groups.
    """
    result = ParsedAttributes()
    lines = [line.strip() for line in (blob or "").split("\n") if line.strip()]
    if not lines:
        return result

    i = 0
    while i < len(lines) and lines[i] not in SECTION_HEADERS:
        result.tags.append(lines[i])
        i += 1

    while i < len(lines):
        if lines[i] not in SECTION_HEADERS:
            # A section should always open with a header at this point --
            # tolerate real-world weirdness rather than crash on it.
            result.orphans.append(lines[i])
            i += 1
            continue

        i += 1  # consume the header
        first_pair_in_section = True
        while i < len(lines):
            if not first_pair_in_section and lines[i] in SECTION_HEADERS:
                break  # next section starts here
            if i + 1 >= len(lines):
                result.orphans.append(lines[i])  # dangling key, no value
                i += 1
                break
            key, value = lines[i], lines[i + 1]
            result.attrs[key] = value
            i += 2
            first_pair_in_section = False

    return result
