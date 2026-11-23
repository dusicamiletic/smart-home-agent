"""Root agent.

Two things happen here and nothing else: the catalogue is loaded once at
import, and the tool functions are given signatures the model can
actually fill.

The wrappers exist because ADK builds the tool schema from the signature.
The underlying functions in ``tools/`` take a catalogue, index dicts, and
typed enums/dataclasses, which the model must never see and can't
produce -- so each wrapper closes over module-level state, converts the
model's plain strings into the real types (`Ecosystem`, `Decimal`), calls
the tested tool function with its actual keyword names, and serializes
the dataclass/Pydantic result back into plain JSON (str, float, None --
no Enum, no Decimal, no dataclass) for the model to read.

Docstrings here are prompt engineering: ADK sends the whole docstring,
Args block included, to the model as the tool description.

Run from the PARENT directory of this package:  adk web
"""

from __future__ import annotations

import os
from decimal import Decimal
from itertools import combinations
from pathlib import Path

from google.adk.agents import Agent
from google.adk.tools.tool_context import ToolContext

from smart_home_agent.catalog.loader import load_catalog
from smart_home_agent.catalog.models import Product
from smart_home_agent.catalog.normalize import _HUB_NOUNS, Ecosystem
from smart_home_agent.guardrail import after_model_guardrail, before_model_guardrail
from smart_home_agent.tools import catalog_tools, comparison, compatibility, upsell

# Pinned deliberately: `gemini-flash-latest` is a moving alias, so a reviewer
# running this next week could get a different model than this was tested on.
# Overridable via GEMINI_MODEL -- free-tier daily quota is per model and can be
# far tighter on newer releases than on established Flash/Flash-Lite tiers
# (see docs/decisions.md); a reviewer who hits it needs a documented way out
# that doesn't require touching code.
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

_HERE = Path(__file__).parent
INSTRUCTION = (_HERE / "prompts" / "instruction.md").read_text(encoding="utf-8")

# Loaded once at import, not per request. Milliseconds, no parsing, no API calls.
CATALOG, BY_CATEGORY, BY_ECOSYSTEM = load_catalog()
# Orchestration note: the catalog is loaded once at import time and
# held as module-level state. The agent's tool wrappers and orchestration
# code below close over this state so ADK/LLM calls can operate without
# reloading or reparsing catalog data per request.

# Real category slugs this catalogue actually indexes on -- there is no
# coarser "lighting/camera/..." grouping at the search layer (compare_products
# and suggest_upsell each build their own grouping for their own purpose,
# see docs/decisions.md; search never needed one, since keywords already
# rank what survives). A handful of real examples, one per scope area named
# in the instruction, so the model has a fighting chance of guessing right
# without hallucinating a slug that doesn't exist.
_EXAMPLE_CATEGORIES = (
    "led-lampen, smart-home-thermostate, ueberwachungskameras-aussen, "
    "smart-home-fensterkontakte-tuerkontakte, smart-home-alarmanlagen, "
    "smart-home-tuerschloesser, smart-home-schalter, smart-home-steckdosen, "
    "smart-home-rollladensteuerung, smart-home-starter-kits-gateways, "
    "bewaesserungscomputer, e-auto-ladestationen"
)

# Only what the catalogue's own data can actually confirm -- Ecosystem has
# no SmartThings member because derive_ecosystems() never produces one (no
# structured field distinguishes it from the free-text "Systeme" list it
# would need to be parsed out of). Listing it as askable here would let the
# model promise a check it cannot perform.
_SUPPORTED_ECOSYSTEMS = "Alexa, Google Home, Apple Home, Matter"


def _ecosystem(value: str) -> Ecosystem | None:
    """Model sends 'ALEXA' / 'Alexa' / 'alexa'; the enum's own values are
    lowercase with underscores. Anything that doesn't map to a real member
    (including 'SMARTTHINGS' -- not representable, see above) comes back
    None rather than raising, so callers can turn that into an honest
    message instead of a stack trace."""
    if not value:
        return None
    try:
        return Ecosystem(value.strip().lower().replace(" ", "_"))
    except ValueError:
        return None


def _price(value: float) -> Decimal | None:
    """0.0 is the model's way of saying 'no limit' -- floats can't be None here."""
    return Decimal(str(value)) if value and value > 0 else None


def _serialize_required_product(required: compatibility.RequiredProduct) -> dict:
    return {
        "name": required.name,
        "id": required.id,
        "price": float(required.price) if required.price is not None else None,
        "url": required.url,
        "image_url": required.image_url,
    }


def _is_hub(product: Product) -> bool:
    """A hub cannot require itself (the same invariant `derive_hub_requirement`'s
    self-reference gate protects at the data layer, docs/decisions.md w08) --
    checked again here, independently, by category group (upsell.py's own
    "hub" group: starter-kit/gateway/hub/Sprachassistent/Fernbedienung) and by
    the product's own title, rather than trusted from `hub_required` being
    `None` alone. Two signals, not one, because a hub-category product whose
    title happens not to match `_HUB_NOUNS` would otherwise fall through the
    data layer's own title-only gate."""
    return upsell.category_group(product.category) == "hub" or bool(_HUB_NOUNS.search(product.title))


def _serialize_product(product: Product) -> dict:
    return {
        "id": product.id,
        "title": product.title,
        "brand": product.brand,
        "category": product.category,
        "price": float(product.price) if product.price is not None else None,
        "url": product.url,
        "image_url": product.image or None,
        "ecosystems": sorted(e.value for e in product.ecosystems),
        "hub_required": product.hub_required,
        "power_type": product.power_type.value if product.power_type is not None else None,
        "is_smart": product.is_smart,
        # Independent of any ecosystem -- "does this need extra hardware to
        # function at all," the same fact check_compatibility's own
        # required_products exposes, just available here without a second
        # tool call, so every search result can render it (interface_strategy.md).
        "required_products": [_serialize_required_product(r) for r in compatibility.required_products_for(product, CATALOG)],
        # For the list view only: a hub showing "needs a hub" about itself
        # would be a category error, not a fact -- see _is_hub.
        "is_hub": _is_hub(product),
    }


def _serialize_compatibility(result: compatibility.CompatibilityResult) -> dict:
    return {
        "state": result.state.value,
        "confidence": result.confidence.value,
        "reason": result.reason,
        "ecosystem_source": result.ecosystem_source,
        "hub_required": result.hub_required,
        "hub_required_confidence": result.hub_required_confidence.value,
        "hub_required_source": result.hub_required_source,
        "required_products": [_serialize_required_product(r) for r in result.required_products],
        "declares_matter": result.declares_matter,
        "fit_notes": result.fit_notes,
    }


def _serialize_comparison(result: comparison.ComparisonResult) -> dict:
    return {
        "product_ids": result.product_ids,
        "rows": [{"field": row.field, "values": row.values, "differs": row.differs} for row in result.rows],
        "notes": result.notes,
    }


def _serialize_upsell(result: dict) -> dict:
    offer = result.get("offer")
    if offer is not None and offer.get("price") is not None:
        result = {**result, "offer": {**offer, "price": float(offer["price"])}}
    return result


def _emptied_by(filters: dict) -> str | None:
    """Only called once a search has already come back empty (see
    search_catalog).

    A fixed processing order ("add category, then ecosystem, then price,
    then keywords back one at a time, blame whichever addition first hits
    zero") looks reasonable but can name a misleading single culprit,
    because filters interact: two constraints can jointly empty the
    result set while neither does alone. Real example in this catalogue --
    category "kabelverbinder" has exactly one product and it declares no
    ecosystem at all, so *that* category combined with *any* ecosystem
    filter empties it, even though the category alone has a match and the
    ecosystem alone has hundreds elsewhere. Blaming "ecosystem" just
    because it happened to be processed last would be arbitrary, not
    diagnostic.

    So this tries leave-one-out first (does removing exactly one active
    filter, keeping every other one exactly as given, restore results?);
    if no single filter alone explains it, leave-two-out; and so on. The
    first filter (or combination) whose removal alone restores results is
    the honest answer -- reported as a joined name ("ecosystem" or
    "category and ecosystem") so the model can offer to loosen exactly
    that, not an arbitrary single guess. Every check is a real call to
    the public search_products, never a duplicated copy of its filter
    logic, so this can't silently drift out of sync with it.
    """
    active = {name: value for name, value in filters.items() if value}
    if len(active) <= 1:
        return next(iter(active), None)

    for drop_size in range(1, len(active)):
        for drop in combinations(sorted(active), drop_size):
            remaining = {name: value for name, value in active.items() if name not in drop}
            count = len(
                catalog_tools.search_products(catalog=CATALOG, by_category=BY_CATEGORY, by_ecosystem=BY_ECOSYSTEM, **remaining)
            )
            if count > 0:
                return " and ".join(sorted(drop))

    # Every proper subset of the active filters is independently empty too --
    # dropping any one, or any pair, ... of them alone would not actually
    # help. Name everything rather than pointing at a single filter that
    # wouldn't fix it.
    return " and ".join(sorted(active))


_MAX_SEARCH_LIMIT = 20


def search_catalog(
    category: str = "",
    ecosystem: str = "",
    max_price: float = 0.0,
    keywords: str = "",
    limit: int = 8,
) -> dict:
    # Tool exposed to the LLM: ADK will use this function's name and
    # docstring as the tool schema/description. The Agent registers this
    # in `root_agent.tools` so the model can request it as a structured
    # tool call.
    """Find products matching hard constraints, ranked by keyword relevance.

    Ecosystem, category and price are exact filters -- a product that fails
    any of them is never returned, not even ranked low. Keywords only order
    what survives.

    Args:
        category: This catalogue's own category slug, exactly. Examples:
            {examples}. Leave empty and rely on keywords if you're not sure
            of the exact slug -- an unmatched slug returns zero results, it
            does not fuzzy-match.
        ecosystem: {ecosystems}. Leave empty only if the customer has not
            stated one yet.
        max_price: Upper limit in euros. 0 means no limit.
        keywords: Space-separated terms for ranking, e.g. "GU10 dimmbar".
            Use exact identifiers where the customer gave one.
        limit: How many products to return, capped at 20 regardless of what
            you ask for. Use 3 for a recommendation; use 20 when the
            customer wants to browse or see everything -- `total_matches`
            tells you the real count so you can say how many more exist.

    Returns:
        results, total_matches, filters_applied, and emptied_by -- which
        constraint eliminated the last candidates, when nothing matched.
    """
    eco = _ecosystem(ecosystem)
    price = _price(max_price)
    kw = keywords.split() if keywords else None
    filters = {"category": category or None, "ecosystem": eco, "max_price": price, "keywords": kw}
    capped_limit = max(1, min(limit, _MAX_SEARCH_LIMIT))

    results = catalog_tools.search_products(catalog=CATALOG, by_category=BY_CATEGORY, by_ecosystem=BY_ECOSYSTEM, **filters)
    total_matches = len(results)

    return {
        "results": [_serialize_product(p) for p in results[:capped_limit]],
        "total_matches": total_matches,
        "filters_applied": {
            "category": category or None,
            "ecosystem": eco.value if eco is not None else None,
            "max_price": float(price) if price is not None else None,
            "keywords": kw,
        },
        "emptied_by": _emptied_by(filters) if total_matches == 0 else None,
    }


search_catalog.__doc__ = search_catalog.__doc__.format(examples=_EXAMPLE_CATEGORIES, ecosystems=_SUPPORTED_ECOSYSTEMS)


def check_compatibility(product_id: str, ecosystem: str) -> dict:
    """Check whether one product works with the customer's ecosystem.

    Call this before recommending anything. The verdict is derived from the
    product's own declared fields, never inferred.

    Args:
        product_id: The product id from a search result.
        ecosystem: {ecosystems}.

    Returns:
        state -- one of direct, needs_hardware, incompatible, unknown --
        plus confidence, reason, required_products and fit_notes.
        `unknown` means the data does not say. Report it as such; do not guess.
    """
    product = CATALOG.get(product_id)
    if product is None:
        return {"error": f"No product with id '{product_id}' in this catalogue."}
    eco = _ecosystem(ecosystem)
    if eco is None:
        return {"error": f"'{ecosystem}' isn't an ecosystem this catalogue's data can confirm. Supported: {_SUPPORTED_ECOSYSTEMS}."}
    result = compatibility.check_compatibility(product=product, ecosystem=eco, catalog=CATALOG)
    return _serialize_compatibility(result)


check_compatibility.__doc__ = check_compatibility.__doc__.format(ecosystems=_SUPPORTED_ECOSYSTEMS)


def compare_products(product_ids: list[str], ecosystem: str = "") -> dict:
    """Build a side-by-side comparison of two or more products.

    Rows are chosen for the products' category. Missing values appear as
    "unknown" rather than being dropped, and rows that differ are flagged so
    you can narrate the differences instead of reading the whole table.

    Args:
        product_ids: Two or more product ids.
        ecosystem: Include a compatibility row for this ecosystem, if known.
    """
    result = comparison.compare_products(catalog=CATALOG, product_ids=product_ids, ecosystem=_ecosystem(ecosystem))
    return _serialize_comparison(result)


def suggest_upsell(
    product_id: str,
    ecosystem: str = "",
    tool_context: ToolContext = None,
) -> dict:
    # Tool exposed to the LLM: suggestion/upsell logic. It reads and
    # updates `tool_context.state` when offers are made so the agent
    # can persist per-session signals deterministically.
    """Find at most one product worth mentioning alongside this one.

    Returns required hardware first (the product does not function without it),
    then a variant better matching what the customer said, then a compatible
    companion. Returns nothing when nothing genuinely fits -- that is a valid
    result and you should make no offer.

    Args:
        product_id: The product the customer is considering.
        ecosystem: The customer's ecosystem, so offers stay compatible.

    Returns:
        offer, offer_type, reason and grounded_in -- the field or customer
        statement that justifies the offer. Use that reason; never substitute
        price or popularity.
    """
    state = tool_context.state if tool_context else {}
    result = upsell.suggest_upsell(
        catalog=CATALOG,
        product_id=product_id,
        ecosystem=_ecosystem(ecosystem),
        declined=bool(state.get("upsell:declined")),
    )
    if tool_context and result.get("offer"):
        state["upsell:offers_made"] = state.get("upsell:offers_made", 0) + 1
    return _serialize_upsell(result)


def remember_customer(
    ecosystem: str = "",
    budget: float = 0.0,
    rooms: str = "",
    owned_devices: str = "",
    tool_context: ToolContext = None,
) -> dict:
    # Tool exposed to the LLM: lightweight session-state storage via
    # `ToolContext.state`. The agent relies on this to persist simple
    # conversational facts (language, budget, ecosystem) across turns.
    """Store what the customer has told you so they never repeat themselves.

    Call this as soon as the customer states any of these. Pass only the fields
    they actually mentioned; leave the rest empty.

    Args:
        ecosystem: {ecosystems}.
        budget: Stated budget in euros.
        rooms: Rooms or room sizes they mentioned, e.g. "Schlafzimmer, 48 m²".
        owned_devices: Products or brands they already own.
    """
    state = tool_context.state if tool_context else {}
    stored = {}
    for key, value in (
        ("user:ecosystem", ecosystem),
        ("user:rooms", rooms),
        ("user:owned_devices", owned_devices),
    ):
        if value:
            state[key] = value
            stored[key] = value
    if budget and budget > 0:
        state["user:budget"] = budget
        stored["user:budget"] = budget
    return {"stored": stored}


remember_customer.__doc__ = remember_customer.__doc__.format(ecosystems=_SUPPORTED_ECOSYSTEMS)


# Agent registration / tool wiring
# `root_agent` is the single entry ADK expects when importing this
# package. ADK imports `smart_home_agent` (see
# `smart_home_agent/__init__.py`) and looks for `root_agent` to
# instantiate the runtime. The `tools` list below is how these Python
# functions are exposed to the LLM as callable tools; docstrings are
# used for tool descriptions. The `before_model_callback` and
# `after_model_callback` hook up deterministic guardrails defined in
# `smart_home_agent.guardrail` which run pre- and post-LLM respectively.
root_agent = Agent(
    name="smart_home_assistant",
    model=MODEL,
    description=(
        "Bilingual smart home shopping assistant for a German retailer. "
        "Recommends and compares connected products, verifies ecosystem "
        "compatibility against declared product data, and refuses electrical "
        "installation advice."
    ),
    instruction=INSTRUCTION,
    tools=[
        search_catalog,
        check_compatibility,
        compare_products,
        suggest_upsell,
        remember_customer,
    ],
    before_model_callback=before_model_guardrail,
    after_model_callback=after_model_guardrail,
)
