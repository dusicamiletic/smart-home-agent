"""Runtime indices (plan §02): set intersection over category/ecosystem is
the entire deterministic gate for search_products -- "everything left of
the gate is a guarantee." No database, no query language, two dicts.
"""

from __future__ import annotations

from collections import defaultdict

from smart_home_agent.catalog.models import Product
from smart_home_agent.catalog.normalize import Ecosystem


def build_indices(products: list[Product]) -> tuple[dict[str, set[str]], dict[Ecosystem, set[str]]]:
    by_category: dict[str, set[str]] = defaultdict(set)
    by_ecosystem: dict[Ecosystem, set[str]] = defaultdict(set)
    for product in products:
        by_category[product.category].add(product.id)
        for ecosystem in product.ecosystems:
            by_ecosystem[ecosystem].add(product.id)
    return by_category, by_ecosystem
