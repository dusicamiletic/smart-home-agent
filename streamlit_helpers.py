"""Pure presentation logic for `streamlit_app.py`, kept in its own module
specifically so it's importable and testable without executing a Streamlit
script run -- `streamlit_app.py` itself has top-level `st.*` calls that only
work inside one. Nothing here touches `st`; the rendering that does stays
in `streamlit_app.py`.
"""

from __future__ import annotations

import re

# Non-greedy `.*?` for the link text, not `[^\]]+` -- several real product
# titles in this catalogue contain their own literal "[...]" (Bosch's "[+M]"
# suffix), which a hard "no ']' allowed" class breaks on: it terminates at
# the inner "]" and never finds the real "](" that follows the actual title.
MARKDOWN_LINK = re.compile(r"\[(.*?)\]\((https?://[^)\s]+)\)")


def find_products(value) -> dict[str, dict]:
    """Recursively pulls every {url, image_url, title-or-name} triple out of
    a tool's raw JSON return value -- generic over which tool it came from.
    search_catalog results use "title"; upsell offers and required_products
    use "name" for the same thing, so both are normalized to "title" here.
    Everything else on the dict (price, hub_required, required_products, ...)
    is kept as-is, since the row renderer needs it. Keyed by url so a
    reply's markdown links can look products up directly."""
    found: dict[str, dict] = {}
    if isinstance(value, dict):
        title = value.get("title") or value.get("name")
        if value.get("url") and value.get("image_url") and title:
            found[value["url"]] = {**value, "title": title}
        for child in value.values():
            found.update(find_products(child))
    elif isinstance(value, list):
        for child in value:
            found.update(find_products(child))
    return found


def products_in_reply(reply: str, catalog: dict[str, dict]) -> list[dict]:
    """The thumbnails shown are exactly the products the model actually
    linked to, in the order it named them -- not every raw search hit,
    which would show results the customer was never told about."""
    matched, seen = [], set()
    for _title, url in MARKDOWN_LINK.findall(reply):
        product = catalog.get(url)
        if product and url not in seen:
            seen.add(url)
            matched.append(product)
    return matched


def format_price(price: float | None) -> str:
    return f"{price:.2f} €" if price is not None else ""


def needs_hardware(product: dict) -> bool:
    """List-view rule: render a hub warning only on a positive fact, never
    as a guarantee and never as a shrug. False and unknown both mean
    "nothing to warn about here" in a list -- an absent badge isn't read as
    "confirmed no hub needed" the way an absent warning sign isn't read as
    a safety certificate, so there's no separate "works on its own" badge
    either, only silence. `is_hub` is checked independently of
    `hub_required`'s value -- a hub cannot require itself, so even a data
    anomaly that left `hub_required` truthy on hub-type hardware must not
    render as a warning about itself. This governs the list view only;
    a direct question in conversation still gets a real answer, including
    "the product data doesn't state it" -- that's instruction.md's job,
    unaffected by this."""
    return product.get("hub_required") is True and not product.get("is_hub", False)


def hub_badge(product: dict) -> str:
    """hub_required is a fact about the product itself, independent of any
    ecosystem -- "does this need extra hardware to work" -- not the
    ecosystem-specific verdict check_compatibility gives, so this never
    says "compatible": that word is reserved for the real per-ecosystem
    check elsewhere."""
    if not needs_hardware(product):
        return ""
    required = product.get("required_products") or []
    name = required[0]["name"] if required else "extra hardware"
    return f":orange[⚠ needs {name}]"
