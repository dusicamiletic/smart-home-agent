"""The Stage-2 (attributes.py) + Stage-3 (normalize.py) outputs, assembled
into one typed record. This is what gets written to `build/catalog.json` and
read back at agent runtime -- "the same relationship as compiling and
running" (plan): build_catalog.py pays the parsing cost once, offline; the
agent just loads the finished JSON.

Sparsity is the default here, not the exception (w04 census: only 93% of
products even have a non-empty `attributes` blob) -- every derived field is
`Optional`, defaulting to the unknown state rather than requiring a value
the source data may simply not contain.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel

from smart_home_agent.catalog.normalize import Confidence, Ecosystem, EcosystemSignal, PowerType


class Product(BaseModel):
    # Stage 1 -- always present in the raw record (w04 census: id, title,
    # url and image are non-empty on all 943).
    id: str
    title: str
    url: str
    image: str = ""

    # Derived from title/url, always computable -- no confidence tier, since
    # there's no absence case to hedge about (see docs/decisions.md, w08).
    brand: str
    category: str

    price: Decimal | None = None

    # Stage 2 (attributes.py) -- still raw German strings, kept for
    # inspectability (plan: "store the text in catalog.json so it's
    # inspectable").
    tags: list[str] = []
    attrs: dict[str, str] = {}
    orphans: list[str] = []

    # Stage 3 (normalize.py) -- every field below carries a confidence tier.
    # ecosystems also carries a real source per tag (the attrs key, or
    # "title" for the keyword fallback) -- "every fact traces to a field."
    ecosystems: dict[Ecosystem, EcosystemSignal] = {}

    vendor_platform: str | None = None
    vendor_platform_confidence: Confidence = Confidence.UNKNOWN

    power_type: PowerType | None = None
    power_type_confidence: Confidence = Confidence.UNKNOWN

    hub_required: bool | None = None
    hub_required_confidence: Confidence = Confidence.UNKNOWN
    hub_hint: str | None = None
    hub_required_source: str | None = None
    # Resolved by a global second pass (catalog/resolve.py) once every
    # Product exists -- null means "named but not found in this catalog",
    # a real outcome (plan: "Both are fine; dropping it isn't"), not a bug.
    hub_product_id: str | None = None

    is_smart: bool | None = None
    is_smart_confidence: Confidence = Confidence.UNKNOWN
