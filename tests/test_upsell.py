import json
from pathlib import Path

from scripts.build_catalog import build_product, resolve_hub_references
from smart_home_agent.catalog.models import Product
from smart_home_agent.catalog.normalize import Confidence, Ecosystem, EcosystemSignal
from smart_home_agent.tools.upsell import category_group, suggest_upsell

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(product_id: str) -> dict:
    return json.loads((FIXTURES_DIR / f"{product_id}.json").read_text(encoding="utf-8"))


def _build(product_id: str) -> Product:
    return build_product(_load_fixture(product_id))


def _catalog(*product_ids: str) -> dict[str, Product]:
    products = {pid: _build(pid) for pid in product_ids}
    resolve_hub_references(list(products.values()))
    return products


def test_required_hardware_outranks_companion_when_both_are_available():
    """Homematic thermostat needs its Access Point (real dependency) *and*
    a real same-brand, adjacent-group companion (a temperature sensor) is
    genuinely available and compatible -- required_hardware must still win,
    since a customer who hasn't bought the mandatory hub yet shouldn't be
    upsold an optional accessory first."""
    catalog = _catalog("26745237", "26756327", "26756910")
    result = suggest_upsell(catalog, "26745237", ecosystem=Ecosystem.ALEXA)

    assert result["offer_type"] == "required_hardware"
    assert result["offer"]["id"] == "26756327"


def test_incompatible_product_is_never_offered_under_any_type():
    """Ring's doorbell only declares Alexa -- queried for Apple HomeKit it's
    INCOMPATIBLE. A real same-brand camera (the kind of thing that would
    otherwise be a valid doorbell->camera companion) is in the catalog too,
    proving this isn't just 'no companion existed', it's the anchor's own
    incompatibility blocking every offer type outright."""
    catalog = _catalog("28597364", "27256662")
    result = suggest_upsell(catalog, "28597364", ecosystem=Ecosystem.APPLE_HOME)

    assert result["offer"] is None
    assert result["offer_type"] == "none"


def test_declined_returns_none_immediately():
    catalog = _catalog("26745237", "26756327")
    result = suggest_upsell(catalog, "26745237", ecosystem=Ecosystem.ALEXA, declined=True)

    assert result["offer"] is None
    assert result["offer_type"] == "none"


def test_nothing_suitable_returns_none_not_a_fallback_product():
    """Nanoleaf has no hub_required and no same-brand product in an
    adjacent group anywhere in the catalog -- the honest answer is no
    offer, not some unrelated product picked to fill the slot."""
    catalog = _catalog("28601371")
    result = suggest_upsell(catalog, "28601371", ecosystem=Ecosystem.ALEXA)

    assert result["offer"] is None
    assert result["offer_type"] == "none"


def test_anchor_is_never_offered_back_to_itself():
    """Constructed directly to simulate a data bug slipping past
    resolve.py's own self-match guard: hub_product_id points at the
    product's own id. suggest_upsell must not trust that blindly -- the
    hard rule is enforced here too, not just upstream."""
    product = Product(
        id="synthetic-self-reference",
        title="Synthetic Self-Referencing Hub",
        brand="Synthetic",
        category="synthetic-category",
        url="https://x/synthetic-self-reference",
        is_smart=True,
        is_smart_confidence=Confidence.DECLARED,
        ecosystems={Ecosystem.ALEXA: EcosystemSignal(Confidence.DECLARED, "Unterstützte Sprachsteuerung")},
        hub_required=True,
        hub_required_confidence=Confidence.DECLARED,
        hub_hint="Self Bridge",
        hub_required_source="Hinweise",
        hub_product_id="synthetic-self-reference",
    )
    catalog = {product.id: product}
    result = suggest_upsell(catalog, product.id, ecosystem=Ecosystem.ALEXA)

    assert result["offer"] is None


def test_every_non_none_offer_has_a_non_empty_grounded_in():
    hardware_catalog = _catalog("26745237", "26756327", "26756910")
    hardware_result = suggest_upsell(hardware_catalog, "26745237", ecosystem=Ecosystem.ALEXA)
    assert hardware_result["offer"] is not None
    assert hardware_result["grounded_in"]

    companion_catalog = _catalog("28597364", "27256662")
    companion_result = suggest_upsell(companion_catalog, "28597364", ecosystem=Ecosystem.ALEXA)
    assert companion_result["offer"] is not None
    assert companion_result["offer_type"] == "companion"
    assert companion_result["grounded_in"]


def test_category_group_classifies_known_category_keywords():
    assert category_group("smart-home-thermostate") == "heating"
    assert category_group("led-lampen") == "lighting_indoor"
    assert category_group("smart-home-starter-kits-gateways") == "hub"
    assert category_group("some-unmapped-category") == "other"
