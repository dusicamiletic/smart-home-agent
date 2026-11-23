"""The build script (plan §01): reads the raw 943-product export and writes
`build/catalog.json` (typed, normalized, agent-ready) and
`build/build_report.md` (coverage + failures + a staleness-detection hash).

Two programs, not one (plan): this one runs by hand, from the terminal, only
when the raw data changes or a parser bug gets fixed. The agent reads the
finished `catalog.json` at startup -- "the same relationship as compiling
and running."

No embeddings, no banding, no reference resolution here -- explicitly out of
scope for this stage (see docs/decisions.md).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from smart_home_agent.catalog.attributes import parse_attributes
from smart_home_agent.catalog.loader import LoadFailure, load_all_json
from smart_home_agent.catalog.models import Product
from smart_home_agent.catalog.normalize import (
    Confidence,
    brand_from_title,
    category_from_url,
    derive_ecosystems,
    derive_hub_requirement,
    derive_is_smart,
    derive_power_type,
    derive_vendor_platform,
    parse_price,
)
from smart_home_agent.catalog.resolve import resolve_hub_reference

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = ROOT / "data" / "products"
DEFAULT_BUILD_DIR = ROOT / "build"


def build_product(raw: dict) -> Product:
    """Assemble one Product from one raw record: Stage 2 (blob -> tags/attrs)
    then Stage 3 (attrs + raw fields -> tiered facts)."""
    title = raw["title"]
    url = raw["url"].strip()
    brand = brand_from_title(title)
    category = category_from_url(url)
    parsed = parse_attributes(raw.get("attributes", ""))
    attrs = parsed.attrs

    ecosystems = derive_ecosystems(attrs, title)
    vendor_platform = derive_vendor_platform(attrs, brand)
    power_type = derive_power_type(attrs, raw.get("subtitle", ""))
    hub = derive_hub_requirement(attrs, raw.get("description", ""), title)
    is_smart = derive_is_smart(attrs, title, category, ecosystems, hub.required)

    return Product(
        id=raw["id"],
        title=title,
        url=url,
        image=raw.get("image", ""),
        brand=brand,
        category=category,
        price=parse_price(raw.get("price", "")),
        tags=parsed.tags,
        attrs=attrs,
        orphans=parsed.orphans,
        ecosystems=ecosystems,
        vendor_platform=vendor_platform.value,
        vendor_platform_confidence=vendor_platform.confidence,
        power_type=power_type.value,
        power_type_confidence=power_type.confidence,
        hub_required=hub.required,
        hub_required_confidence=hub.confidence,
        hub_hint=hub.hint,
        hub_required_source=hub.source,
        is_smart=is_smart.value,
        is_smart_confidence=is_smart.confidence,
    )


def _content_hash(data_dir: Path) -> str:
    """Staleness detection (plan): hash file contents, not mtimes, so a
    checkout that doesn't change any bytes doesn't look stale."""
    hasher = hashlib.sha256()
    for path in sorted(data_dir.glob("*.json")):
        hasher.update(path.name.encode("utf-8"))
        hasher.update(path.read_bytes())
    return hasher.hexdigest()


def _tier_counts(products: list[Product], field: str) -> dict[str, int]:
    counts = {tier.value: 0 for tier in Confidence}
    for product in products:
        counts[getattr(product, field).value] += 1
    return counts


def _ecosystem_tag_counts(products: list[Product]) -> dict[str, int]:
    counts = {tier.value: 0 for tier in Confidence}
    for product in products:
        if not product.ecosystems:
            counts[Confidence.UNKNOWN.value] += 1
            continue
        for signal in product.ecosystems.values():
            counts[signal.confidence.value] += 1
    return counts


def build_report(
    products: list[Product],
    load_failures: list[LoadFailure],
    build_failures: list[tuple[str, str]],
    data_dir: Path,
) -> str:
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    hub_needed = [p for p in products if p.hub_required]
    hub_resolved = [p for p in hub_needed if p.hub_product_id is not None]
    lines = [
        "# Build Report",
        "",
        f"- Generated: {generated_at}",
        f"- Source: `{data_dir}` (content hash `{_content_hash(data_dir)[:16]}…`)",
        f"- Products built: {len(products)}",
        f"- Load failures: {len(load_failures)}",
        f"- Build failures: {len(build_failures)}",
        f"- Hub references: {len(hub_resolved)} / {len(hub_needed)} resolved to a catalog id",
        "",
    ]

    if load_failures:
        lines.append("## Load failures")
        lines += [f"- `{f.path.name}`: {f.error}" for f in load_failures]
        lines.append("")

    if build_failures:
        lines.append("## Build failures")
        lines += [f"- `{product_id}`: {error}" for product_id, error in build_failures]
        lines.append("")

    lines += ["## Confidence-tier coverage", "", "| Field | Declared | Inferred | Unknown |", "|---|---|---|---|"]
    fields = {
        "ecosystem tags": _ecosystem_tag_counts(products),
        "vendor_platform": _tier_counts(products, "vendor_platform_confidence"),
        "power_type": _tier_counts(products, "power_type_confidence"),
        "hub_required": _tier_counts(products, "hub_required_confidence"),
        "is_smart": _tier_counts(products, "is_smart_confidence"),
    }
    for name, counts in fields.items():
        lines.append(
            f"| {name} | {counts['declared']} | {counts['inferred']} | {counts['unknown']} |"
        )
    lines.append("")

    return "\n".join(lines)


def resolve_hub_references(products: list[Product]) -> int:
    """Stage 5, scoped to one task (plan §02): needs every product to exist
    first, so it runs as a second pass over the whole built list rather than
    inside build_product(). Mutates each product's hub_product_id in place;
    returns how many resolved.

    Skips hints that are exactly the vendor_platform value: a bare brand
    name (e.g. "Philips Hue") matches every product from that brand by
    token subset -- real data showed the *wrong* short-titled product
    beating the actual hub on the fewest-extra-words rule, with no
    available tie-break that recovers the right answer. vendor_platform is
    built by stripping " System" off a brand name, so it structurally never
    names a specific product -- there's nothing precise enough here to
    resolve, only an ecosystem to mention."""
    resolved_count = 0
    for product in products:
        if not (product.hub_required and product.hub_hint):
            continue
        if product.hub_hint == product.vendor_platform:
            continue
        product.hub_product_id = resolve_hub_reference(product.hub_hint, products, exclude_id=product.id)
        if product.hub_product_id is not None:
            resolved_count += 1
    return resolved_count


@dataclass
class BuildSummary:
    products_built: int
    load_failures: int
    build_failures: int
    hub_references_resolved: int


def run_build(data_dir: Path = DEFAULT_DATA_DIR, build_dir: Path = DEFAULT_BUILD_DIR) -> BuildSummary:
    load_result = load_all_json(data_dir)

    products: list[Product] = []
    build_failures: list[tuple[str, str]] = []
    for record in load_result.records:
        try:
            products.append(build_product(record))
        except Exception as exc:  # noqa: BLE001 -- tolerant build, never crash on one bad record
            build_failures.append((record.get("id", "?"), repr(exc)))

    hub_references_resolved = resolve_hub_references(products)

    build_dir.mkdir(parents=True, exist_ok=True)

    catalog_path = build_dir / "catalog.json"
    catalog_json = [p.model_dump(mode="json") for p in products]
    catalog_path.write_text(json.dumps(catalog_json, ensure_ascii=False, indent=2), encoding="utf-8")

    report = build_report(products, load_result.failures, build_failures, data_dir)
    (build_dir / "build_report.md").write_text(report, encoding="utf-8")

    return BuildSummary(
        products_built=len(products),
        load_failures=len(load_result.failures),
        build_failures=len(build_failures),
        hub_references_resolved=hub_references_resolved,
    )


def main() -> None:
    summary = run_build()
    print(
        f"Built {summary.products_built} products "
        f"({summary.load_failures} load failures, {summary.build_failures} build failures, "
        f"{summary.hub_references_resolved} hub references resolved) "
        f"-> {DEFAULT_BUILD_DIR / 'catalog.json'}"
    )


if __name__ == "__main__":
    main()
