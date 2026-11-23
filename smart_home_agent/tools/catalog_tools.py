"""search_products / get_product (plan §02, tools/catalog_tools.py).

The plan's own retrieval design has three lanes -- structured filters,
lexical matching on exact identifiers (model numbers, sockets, EAN), and
semantic scoring -- but "no embeddings, no semantic lane, no vector
anything" is a permanent cut for this build (see docs/decisions.md).
That leaves two: index intersection is the gate ("everything left of the
gate is a guarantee"), lexical scoring ranks what's left.
"""

from __future__ import annotations

from decimal import Decimal

from smart_home_agent.catalog.models import Product
from smart_home_agent.catalog.normalize import Ecosystem


def get_product(catalog: dict[str, Product], product_id: str) -> Product | None:
    return catalog.get(product_id)


def _lexical_score(product: Product, keywords: list[str]) -> int:
    """Exact-identifier matching (GU10, HmIP-eTRV-2, an EAN) -- the customer
    knows precisely what they want, and these are character-level tokens a
    semantic lane would blur anyway, so a plain substring count is
    sufficient and needs no vector store."""
    haystack = " ".join([product.title, *product.attrs.values()]).lower()
    return sum(1 for keyword in keywords if keyword.lower() in haystack)


def _sort_key(product: Product, keywords: list[str] | None) -> tuple:
    """Ranking only ever reorders what the gate above already let through --
    it must never decide who's in the room. hub_required is checked with
    `is True` because it's tri-state: `None` (unknown) sorts with `False`
    (no known requirement), never demoted into the hub group just for
    missing data -- "never guess past what the tier allows" applies to
    ranking too, not only to what gets stated as fact. Deliberately no
    "richer attrs rank higher" term: that's a sparsity bias, the same
    failure mode rejected when cutting embeddings -- thin-data products
    would systematically never surface, for a reason that has nothing to
    do with fitness for the customer's request."""
    return (
        product.hub_required is True,  # works out of the box first
        -_lexical_score(product, keywords or []),  # then keyword relevance
        product.price is None,  # priced before unpriced
        product.price or Decimal(0),  # price only as a tiebreak
    )


def search_products(
    catalog: dict[str, Product],
    by_category: dict[str, set[str]],
    by_ecosystem: dict[Ecosystem, set[str]],
    category: str | None = None,
    ecosystem: Ecosystem | None = None,
    max_price: Decimal | None = None,
    keywords: list[str] | None = None,
) -> list[Product]:
    """Structured filters are a guarantee, applied as set intersection over
    the indices; keywords only rank what survives the gate, they never
    substitute for it."""
    candidate_ids: set[str] | None = None

    def _intersect(ids: set[str]) -> None:
        nonlocal candidate_ids
        candidate_ids = set(ids) if candidate_ids is None else candidate_ids & ids

    if category is not None:
        _intersect(by_category.get(category, set()))
    if ecosystem is not None:
        _intersect(by_ecosystem.get(ecosystem, set()))

    ids = candidate_ids if candidate_ids is not None else set(catalog.keys())
    candidates = [catalog[product_id] for product_id in ids if product_id in catalog]

    if max_price is not None:
        candidates = [p for p in candidates if p.price is not None and p.price <= max_price]

    if keywords:
        candidates = [p for p in candidates if _lexical_score(p, keywords) > 0]

    candidates.sort(key=lambda p: _sort_key(p, keywords))
    return candidates
