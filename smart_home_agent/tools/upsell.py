"""suggest_upsell (plan §02, tools/upsell.py): one offer per turn, always
inside the compatible set.

Three offer types, strict priority order -- each is a separate function
tried in order, first non-None result wins:

1. required_hardware -- the anchor genuinely can't work without it (the
   Homematic Access Point case). Always wins when present: a customer who
   hasn't bought the mandatory hub yet shouldn't be upsold an optional
   accessory ahead of it.
2. completion -- a variant matching a stated customer constraint (room
   size for climate, pack size for sensors). Not implemented yet: the
   current tool signature carries no such constraint (no room_size,
   pack_size, or similar). That's a conversation-state concept the agent
   instruction layer owns, not something to fake here -- same principle as
   never inventing a `source` field elsewhere in this codebase (see
   docs/decisions.md). `_completion_offer` is kept as a real, always-None
   stage so the priority order is structurally correct and the slot is
   obvious once that state exists.
3. companion -- same brand, compatible, is_smart, and in an adjacent
   category group. The adjacency map is explicit and small on purpose:
   "any different group" would offer a garage door opener to someone
   buying a thermostat.

Every candidate for offer types 2 and 3 is re-checked through
check_compatibility for the *given* ecosystem -- only DIRECT or
NEEDS_HARDWARE may be offered, never INCOMPATIBLE or UNKNOWN. The anchor
product itself is checked the same way before anything else runs: an
anchor that isn't confirmed compatible gets no upsell of any kind, since
recommending accessories for a base recommendation that's already shaky
would compound the uncertainty, not use it.
"""

from __future__ import annotations

from decimal import Decimal

from smart_home_agent.catalog.models import Product
from smart_home_agent.catalog.normalize import Ecosystem
from smart_home_agent.tools.compatibility import CompatibilityState, check_compatibility, required_products_for

# Deliberately smaller and more specific than comparison.py's category
# groups: upselling needs to distinguish sensor/alarm/camera/doorbell/lock
# from each other (they're different points in the adjacency map below),
# where compare_products was free to lump them into one "sensor_safety"
# bucket. Checked in order -- first match wins -- so e.g. a video doorbell
# ("...mit-kamera") lands in "doorbell", not "camera", and a mower with a
# camera ("maehrobotor-mit-kamera") lands in "garden", not "camera".
_GROUP_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("heating", ("thermostat", "fussbodenheizung")),
    ("climate", ("klima",)),
    ("alarm", ("alarmanlage", "alarmsirene", "fensteralarm", "tueralarm")),
    ("sensor", ("sensor", "melder", "fensterkontakt", "tuerkontakt", "fenstersicherung")),
    ("doorbell", ("tuerklingel", "tuersprechanlage", "tuergong", "tuerspion", "klingeltaster")),
    ("lock", ("tuerschloss", "tuerschloesser", "garagentor")),
    (
        "garden",
        (
            "garten",
            "maehroboter",
            "maehrobotor",
            "bewaesserung",
            "sprinkler",
            "wegeleuchte",
            "aussenleuchte",
            "aussenwandleuchte",
            "aussenbeleuchtung",
        ),
    ),
    ("camera", ("kamera",)),
    ("lighting_indoor", ("led-", "leucht", "lampen", "lampe", "strahler", "beleuchtung", "licht", "dimmer")),
    ("switch", ("schalter", "funkstecker", "schaltrelais")),
    ("hub", ("starter-kit", "gateway", "hub", "sprachassistent", "fernbedienung")),
    ("power", ("steckdose", "ladestation", "mobility", "stromzaehler", "messgeraet")),
]

# Explicit and small on purpose -- a group with no entry here (climate,
# alarm, camera as a *source*, doorbell as a *source*, hub, power, switch,
# or anything falling through to "other") simply has no companion offer.
# "No offer" is the correct answer for those, not a guess at what might be
# adjacent.
_ADJACENT_GROUPS: dict[str, tuple[str, ...]] = {
    "heating": ("sensor",),
    "sensor": ("alarm", "hub"),
    "camera": ("alarm", "hub"),
    "lighting_indoor": ("switch", "hub"),
    "lock": ("camera", "doorbell"),
    "doorbell": ("camera",),
    "garden": ("power",),
}


def category_group(category: str) -> str:
    for group, keywords in _GROUP_KEYWORDS:
        if any(keyword in category for keyword in keywords):
            return group
    return "other"


def _no_offer(reason: str) -> dict:
    return {"offer": None, "offer_type": "none", "reason": reason, "grounded_in": None}


def _offer_dict(
    offer_type: str,
    product_id: str,
    name: str,
    price: Decimal | None,
    reason: str,
    grounded_in: str,
    url: str | None = None,
    image_url: str | None = None,
) -> dict:
    return {
        "offer": {"id": product_id, "name": name, "price": price, "url": url, "image_url": image_url},
        "offer_type": offer_type,
        "reason": reason,
        "grounded_in": grounded_in,
    }


def _within_budget(price: Decimal | None, max_budget: Decimal | None) -> bool:
    if max_budget is None:
        return True
    return price is not None and price <= max_budget


def _required_hardware_offer(
    anchor: Product, catalog: dict[str, Product], max_budget: Decimal | None, exclude_ids: set[str]
) -> dict | None:
    required = required_products_for(anchor, catalog)
    if not required:
        return None
    hardware = required[0]
    # Not found in the catalog, or (a data bug) resolves back to the
    # anchor/basket -- nothing concrete to actually offer.
    if hardware.id is None or hardware.id in exclude_ids:
        return None
    if not _within_budget(hardware.price, max_budget):
        return None
    return _offer_dict(
        "required_hardware",
        hardware.id,
        hardware.name,
        hardware.price,
        reason=f"{anchor.title} needs {hardware.name} to work.",
        grounded_in=f"hub_required (source: {anchor.hub_required_source or 'unknown'})",
        url=hardware.url,
        image_url=hardware.image_url,
    )


def _completion_offer(
    anchor: Product, catalog: dict[str, Product], max_budget: Decimal | None, exclude_ids: set[str]
) -> dict | None:
    # No stated constraint reaches this function -- see module docstring.
    return None


def _companion_offer(
    anchor: Product,
    catalog: dict[str, Product],
    ecosystem: Ecosystem | None,
    max_budget: Decimal | None,
    exclude_ids: set[str],
) -> dict | None:
    if ecosystem is None:
        return None
    anchor_group = category_group(anchor.category)
    target_groups = _ADJACENT_GROUPS.get(anchor_group, ())
    if not target_groups:
        return None

    candidates = []
    for candidate in catalog.values():
        if candidate.id in exclude_ids:
            continue
        if candidate.brand != anchor.brand:
            continue
        if candidate.is_smart is not True:
            continue
        if category_group(candidate.category) not in target_groups:
            continue
        if not _within_budget(candidate.price, max_budget):
            continue
        state = check_compatibility(candidate, ecosystem, catalog).state
        if state not in (CompatibilityState.DIRECT, CompatibilityState.NEEDS_HARDWARE):
            continue
        candidates.append(candidate)

    if not candidates:
        return None
    chosen = min(candidates, key=lambda p: p.id)
    return _offer_dict(
        "companion",
        chosen.id,
        chosen.title,
        chosen.price,
        reason=f"Also works with your {anchor.brand} setup: {chosen.title}.",
        grounded_in=f"same brand ({chosen.brand}), category group {anchor_group} -> {category_group(chosen.category)}",
        url=chosen.url,
        image_url=chosen.image or None,
    )


def suggest_upsell(
    catalog: dict[str, Product],
    product_id: str,
    ecosystem: Ecosystem | None = None,
    max_budget: Decimal | None = None,
    basket: tuple[str, ...] = (),
    declined: bool = False,
) -> dict:
    if declined:
        return _no_offer("Customer already declined an offer this session.")

    anchor = catalog.get(product_id)
    if anchor is None:
        return _no_offer("Unknown product.")

    exclude_ids = set(basket) | {product_id}

    if ecosystem is not None:
        anchor_state = check_compatibility(anchor, ecosystem, catalog).state
        if anchor_state in (CompatibilityState.INCOMPATIBLE, CompatibilityState.UNKNOWN):
            return _no_offer("The anchor product itself isn't a confirmed fit for this ecosystem.")

    for offer_fn in (_required_hardware_offer, _completion_offer):
        offer = offer_fn(anchor, catalog, max_budget, exclude_ids)
        if offer is not None:
            return offer

    offer = _companion_offer(anchor, catalog, ecosystem, max_budget, exclude_ids)
    if offer is not None:
        return offer

    return _no_offer("No genuinely fitting upsell found.")
