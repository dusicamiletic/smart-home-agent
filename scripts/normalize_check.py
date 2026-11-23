"""Validate catalog/normalize.py against the full real catalog (w08), same
discipline as scripts/vocab_check.py for w05/w07: fixtures prove correctness
on hand-picked cases, this proves the derivation doesn't crash or silently
misbehave across all 943 real products, and reports the confidence-tier
distribution per field for docs/decisions.md.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from smart_home_agent.catalog.attributes import parse_attributes
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

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "products"


def main() -> None:
    files = sorted(DATA_DIR.glob("*.json"))
    total = len(files)
    crashes: list[tuple[str, str]] = []

    price_failures = 0
    ecosystem_tiers = Counter()  # per-ecosystem-tag confidence, across all products
    products_with_any_ecosystem = 0
    vendor_platform_tiers = Counter()
    power_type_tiers = Counter()
    hub_required_tiers = Counter()
    is_smart_tiers = Counter()

    for path in files:
        product = json.loads(path.read_text(encoding="utf-8"))
        try:
            attrs = parse_attributes(product["attributes"]).attrs
            price = parse_price(product["price"])
            category = category_from_url(product["url"])
            brand = brand_from_title(product["title"])
            ecosystems = derive_ecosystems(attrs, product["title"])
            vendor_platform = derive_vendor_platform(attrs, brand)
            power_type = derive_power_type(attrs, product["subtitle"])
            hub_req = derive_hub_requirement(attrs, product["description"], product["title"])
            is_smart = derive_is_smart(attrs, product["title"], category, ecosystems, hub_req.required)
        except Exception as exc:  # noqa: BLE001 -- census script, not production code
            crashes.append((product.get("id", path.stem), repr(exc)))
            continue

        if price is None:
            price_failures += 1
        if ecosystems:
            products_with_any_ecosystem += 1
            for signal in ecosystems.values():
                ecosystem_tiers[signal.confidence] += 1
        else:
            ecosystem_tiers[Confidence.UNKNOWN] += 1
        vendor_platform_tiers[vendor_platform.confidence] += 1
        power_type_tiers[power_type.confidence] += 1
        hub_required_tiers[hub_req.confidence] += 1
        is_smart_tiers[is_smart.confidence] += 1

    print(f"Total: {total}")
    print(f"Crashes: {len(crashes)}")
    for product_id, err in crashes[:20]:
        print(f"  {product_id}: {err}")
    print(f"Price parse failures: {price_failures}")
    print(f"Products with >=1 ecosystem signal: {products_with_any_ecosystem}")
    print(f"Ecosystem-tag confidence distribution: {dict(ecosystem_tiers)}")
    print(f"Vendor platform confidence distribution: {dict(vendor_platform_tiers)}")
    print(f"Power type confidence distribution: {dict(power_type_tiers)}")
    print(f"Hub requirement confidence distribution: {dict(hub_required_tiers)}")
    print(f"is_smart confidence distribution: {dict(is_smart_tiers)}")


if __name__ == "__main__":
    main()
