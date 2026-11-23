"""Day-1 census (plan section 03 / task w04).

Reads all raw product exports and reports, without parsing or deriving
anything yet:
  - line-frequency across every `attributes` blob (which lines recur enough
    to be section headers/keys -- feeds the vocabulary harvest in w05)
  - category counts from the URL's first path segment
  - four coverage numbers: parseable price, non-empty attributes, declares
    a voice-assistant / ecosystem signal in any of the three known fields,
    has a `Hinweise` key in the attributes blob

Output is printed and also written to docs/data_notes.md so it survives
this one run.
"""

import json
import re
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "products"
REPORT_PATH = ROOT / "docs" / "data_notes.md"

ECOSYSTEM_KEYS = ("Unterstützte Sprachsteuerung", "Unterstützte Systeme")
ECOSYSTEM_TITLE_KEYWORDS = (
    "Alexa",
    "Google Assistant",
    "Google Home",
    "HomeKit",
    "Matter",
    "SmartThings",
)


def load_all(data_dir: Path) -> list[dict]:
    products = []
    failed = []
    for path in sorted(data_dir.glob("*.json")):
        try:
            products.append(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            failed.append((path.name, str(exc)))
    return products, failed


def parse_price(raw: str) -> Decimal | None:
    if not raw:
        return None
    # "999,- €" / "10,- €" / "1.299,99 €" -> Decimal
    cleaned = raw.replace("€", "").strip()
    cleaned = cleaned.replace(".", "").replace(",-", ",00").replace(",", ".")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def category_from_url(url: str) -> str | None:
    if not url:
        return None
    url = url.strip()
    match = re.search(r"bauhaus\.info/([^/]+)/", url)
    return match.group(1) if match else None


def declares_ecosystem(attributes: str, title: str) -> bool:
    for key in ECOSYSTEM_KEYS:
        if key in (attributes or ""):
            return True
    return any(kw in (title or "") for kw in ECOSYSTEM_TITLE_KEYWORDS)


def main() -> None:
    products, failed = load_all(DATA_DIR)
    n = len(products)

    # line-frequency across every attributes blob
    line_counts: Counter[str] = Counter()
    for p in products:
        blob = p.get("attributes") or ""
        for line in blob.split("\n"):
            line = line.strip()
            if line:
                line_counts[line] += 1

    # category counts from URL slug
    category_counts: Counter[str] = Counter()
    for p in products:
        cat = category_from_url(p.get("url", ""))
        category_counts[cat or "UNKNOWN"] += 1

    # coverage numbers
    n_price = sum(1 for p in products if parse_price(p.get("price", "")) is not None)
    n_attrs = sum(1 for p in products if (p.get("attributes") or "").strip())
    n_ecosystem = sum(
        1
        for p in products
        if declares_ecosystem(p.get("attributes", ""), p.get("title", ""))
    )
    n_hinweise = sum(1 for p in products if "Hinweise" in (p.get("attributes") or ""))

    lines = []
    lines.append(f"# Data census — {n} products read, {len(failed)} failed\n")
    if failed:
        lines.append("Failed files:\n")
        for name, err in failed:
            lines.append(f"- `{name}`: {err}")
        lines.append("")

    lines.append("## Coverage (out of {})\n".format(n))
    lines.append(f"- Parseable price: **{n_price}** ({n_price/n:.0%})")
    lines.append(f"- Non-empty `attributes`: **{n_attrs}** ({n_attrs/n:.0%})")
    lines.append(
        f"- Declares a voice-assistant / ecosystem signal "
        f"(any of `{'`, `'.join(ECOSYSTEM_KEYS)}`, or a title keyword): "
        f"**{n_ecosystem}** ({n_ecosystem/n:.0%})"
    )
    lines.append(f"- Has a `Hinweise` field: **{n_hinweise}** ({n_hinweise/n:.0%})")
    lines.append("")

    lines.append(f"## Category counts from URL slug ({len(category_counts)} categories)\n")
    for cat, count in category_counts.most_common():
        lines.append(f"- `{cat}`: {count}")
    lines.append("")

    lines.append(f"## Top 60 most frequent lines in `attributes` blobs\n")
    lines.append(
        "Manual judgement call next (w05): which of these are **section "
        "headers** (recur across many unrelated products) vs. **keys** "
        "(recur within one category) vs. **values**.\n"
    )
    lines.append("| Line | Count |")
    lines.append("|---|---|")
    for line, count in line_counts.most_common(60):
        escaped = line.replace("|", "\\|")
        lines.append(f"| {escaped} | {count} |")
    lines.append("")

    report = "\n".join(lines)
    print(report)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"\n--- written to {REPORT_PATH} ---")


if __name__ == "__main__":
    main()
