"""Stage 5, scoped down to one task (plan §02, "Cross-reference resolution"):
match the free-text hub name regexed out of Hinweise/description against
real catalog titles. "Found -> store the id so you can quote its price.
Not found -> keep the text, id stays null. Both are fine; dropping it
isn't." Needs the whole built catalog, unlike the per-product Stage 3
functions -- run as a second pass once every Product exists.
"""

from __future__ import annotations

import re

# Filler words common in both hub_hint garbage (e.g. "ein Smartphone") and
# real titles alike -- excluded so they can't inflate a spurious match.
_STOPWORDS = {"ein", "eine", "der", "die", "das", "und", "mit", "für", "ist"}


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"\w+", text) if t.lower() not in _STOPWORDS}


def resolve_hub_reference(hint: str, products: list, exclude_id: str | None = None) -> str | None:
    """Every word in `hint` must appear somewhere in a candidate's title.
    Multiple real products can satisfy that (a standalone accessory and any
    bundle that happens to include one) -- prefer whichever title has the
    fewest words *beyond* the hint, since a bundle's extra hardware words
    are exactly what should count against it.

    `exclude_id` keeps a product from resolving to itself -- a real bug
    found validating against all 943: "Homematic IP Adapter Gira" declares
    `Passend für: "Gira"` (describing what it fits, not a companion product
    to buy), and its own title contains the word "Gira"."""
    hint_tokens = _tokens(hint)
    if not hint_tokens:
        return None

    candidates = []
    for product in products:
        if product.id == exclude_id:
            continue
        title_tokens = _tokens(product.title)
        if hint_tokens <= title_tokens:
            extra_words = len(title_tokens) - len(hint_tokens)
            candidates.append((extra_words, product.id))

    if not candidates:
        return None
    candidates.sort()
    return candidates[0][1]
