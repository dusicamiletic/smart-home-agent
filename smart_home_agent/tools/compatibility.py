"""check_compatibility (plan §02): returns a state, not a boolean.

The ecosystem verdict is checked first; hub_required is a modifier applied
*on top* of a match, never a substitute for one. A hub does not create
ecosystem support that was never declared -- a Zigbee bulb that needs a
Hue Bridge and never mentions Alexa is not "compatible once you buy the
Bridge," it's simply not Alexa-compatible, full stop. Getting this order
backwards was the first design of this tool, caught before it shipped:
short-circuiting on hub_required alone would have told a customer "buy the
hub and you're fine" for a product that doesn't even claim to work with
their ecosystem.

Every fact traces to a real field -- no source is ever reconstructed by
guessing after the fact (see docs/decisions.md). Where a real source
would be ambiguous (MISMATCH can involve several declared tags at once),
the field is left null rather than approximated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from smart_home_agent.catalog.models import Product
from smart_home_agent.catalog.normalize import Confidence, Ecosystem

_TIER_RANK = {Confidence.DECLARED: 2, Confidence.INFERRED: 1, Confidence.UNKNOWN: 0}


def _weaker(a: Confidence, b: Confidence) -> Confidence:
    return a if _TIER_RANK[a] <= _TIER_RANK[b] else b


class CompatibilityState(str, Enum):
    DIRECT = "direct"
    NEEDS_HARDWARE = "needs_hardware"
    INCOMPATIBLE = "incompatible"
    UNKNOWN = "unknown"


@dataclass
class RequiredProduct:
    """A companion product this one needs. `id`/`price` are null when the
    name couldn't be resolved to a real catalog product -- the plan's own
    rule: "Not found -> keep the text, id stays null. Both are fine;
    dropping it isn't." """

    name: str
    id: str | None
    price: Decimal | None
    url: str | None = None
    image_url: str | None = None


@dataclass
class CompatibilityResult:
    state: CompatibilityState
    confidence: Confidence
    reason: str

    # Real provenance for the ecosystem verdict -- only ever set for a
    # single, unambiguous tag (a MATCH). MISMATCH can involve several
    # declared tags at once, so there's no one field to honestly name;
    # left null rather than picking one arbitrarily.
    ecosystem_source: str | None

    # Echoed regardless of state -- a fact about the product, not a claim
    # about compatibility. Whether it's worth *saying* to the customer for
    # a given state (e.g. staying quiet about it when INCOMPATIBLE, so as
    # not to imply a hub would fix a real mismatch) is the agent
    # instruction's call, not this tool's -- the tool returns everything.
    hub_required: bool | None
    hub_required_confidence: Confidence
    hub_required_source: str | None
    required_products: list[RequiredProduct] = field(default_factory=list)

    # Matter is generally cross-ecosystem in the real world, but that's not
    # something our data confirms -- surfaced as a separate, honest flag
    # rather than folded into the state itself.
    declares_matter: bool = False

    # Physical fit (socket type, valve thread, etc.) -- informational only,
    # alongside the verdict, never inside it. A GU10 bulb isn't
    # "incompatible with Alexa" because of its socket.
    fit_notes: str | None = None


_FIT_KEYS = ("Lampensockel", "Ventilanschluss", "Geeignet für")


def _fit_notes(product: Product) -> str | None:
    parts = [f"{key}: {product.attrs[key]}" for key in _FIT_KEYS if key in product.attrs]
    return "; ".join(parts) if parts else None


def required_products_for(product: Product, catalog: dict[str, Product]) -> list[RequiredProduct]:
    if not product.hub_required:
        return []
    name = product.hub_hint or "additional hardware"
    resolved = catalog.get(product.hub_product_id) if product.hub_product_id else None
    if resolved is not None:
        return [
            RequiredProduct(
                name=resolved.title, id=resolved.id, price=resolved.price, url=resolved.url, image_url=resolved.image or None
            )
        ]
    return [RequiredProduct(name=name, id=None, price=None)]


def check_compatibility(product: Product, ecosystem: Ecosystem, catalog: dict[str, Product]) -> CompatibilityResult:
    declares_matter = (
        Ecosystem.MATTER in product.ecosystems and product.ecosystems[Ecosystem.MATTER].confidence == Confidence.DECLARED
    )
    fit_notes = _fit_notes(product)
    required_products = required_products_for(product, catalog)

    if product.is_smart is False:
        return CompatibilityResult(
            state=CompatibilityState.INCOMPATIBLE,
            confidence=product.is_smart_confidence,
            reason="Not a connected product.",
            ecosystem_source=None,
            hub_required=product.hub_required,
            hub_required_confidence=product.hub_required_confidence,
            hub_required_source=product.hub_required_source,
            required_products=required_products,
            declares_matter=declares_matter,
            fit_notes=fit_notes,
        )

    # Step 1: ecosystem verdict, independent of hub_required.
    signal = product.ecosystems.get(ecosystem)
    if signal is not None:
        verdict = "MATCH"
    elif product.ecosystems and all(s.confidence == Confidence.DECLARED for s in product.ecosystems.values()):
        verdict = "MISMATCH"
    else:
        verdict = "UNSURE"

    # Step 2: combine with hub_required as a modifier on top of a match.
    if verdict == "MATCH":
        ecosystem_source = signal.source
        if product.hub_required:
            state = CompatibilityState.NEEDS_HARDWARE
            confidence = _weaker(signal.confidence, product.hub_required_confidence)
            reason = (
                f"Declares {ecosystem.value} support ({signal.source}), "
                f"but also needs {product.hub_hint or 'additional hardware'} ({product.hub_required_source})."
            )
        else:
            state = CompatibilityState.DIRECT
            confidence = signal.confidence
            reason = f"Declares {ecosystem.value} support via {signal.source}."
    elif verdict == "MISMATCH":
        ecosystem_source = None
        state = CompatibilityState.INCOMPATIBLE
        confidence = Confidence.DECLARED
        declared = ", ".join(sorted(e.value for e in product.ecosystems))
        reason = f"Declares support for {declared}, not {ecosystem.value}. Additional hardware would not change this."
    else:
        ecosystem_source = None
        state = CompatibilityState.UNKNOWN
        confidence = Confidence.UNKNOWN
        reason = f"No ecosystem information available for {ecosystem.value}."

    return CompatibilityResult(
        state=state,
        confidence=confidence,
        reason=reason,
        ecosystem_source=ecosystem_source,
        hub_required=product.hub_required,
        hub_required_confidence=product.hub_required_confidence,
        hub_required_source=product.hub_required_source,
        required_products=required_products,
        declares_matter=declares_matter,
        fit_notes=fit_notes,
    )
