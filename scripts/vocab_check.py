"""Validate the w05 header list against all 943 blobs (not just top-60).

For each product: strip the preamble tag list, then split the remaining
lines on known section headers. Each resulting chunk should have an EVEN
number of lines (key, value, key, value, ...). An odd chunk is direct
evidence of a missed header -- something in that chunk is acting as a
delimiter, not a key or a value.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VOCAB = json.loads((ROOT / "build" / "vocabulary.json").read_text(encoding="utf-8"))
HEADERS = set(VOCAB["section_headers"])


def split_sections(lines: list[str]) -> list[list[str]]:
    sections = []
    current: list[str] = []
    started = False
    for line in lines:
        if line in HEADERS:
            if started:
                sections.append(current)
            current = []
            started = True
        elif started:
            current.append(line)
    if started:
        sections.append(current)
    return sections


def main() -> None:
    anomalies = []
    for path in sorted((ROOT / "data" / "products").glob("*.json")):
        product = json.loads(path.read_text(encoding="utf-8"))
        blob = product.get("attributes") or ""
        lines = [l.strip() for l in blob.split("\n") if l.strip()]
        if not lines:
            continue
        for section in split_sections(lines):
            if len(section) % 2 != 0:
                anomalies.append((path.name, product.get("title", ""), section))

    print(f"{len(anomalies)} blobs with at least one odd-length section "
          f"(out of 943)\n")
    for name, title, section in anomalies[:25]:
        print(f"--- {name}  ({title}) ---")
        print(section)
        print()


if __name__ == "__main__":
    main()
