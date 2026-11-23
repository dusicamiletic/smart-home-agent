import dataclasses
import json
from decimal import Decimal
from pathlib import Path

from scripts.build_catalog import build_product, resolve_hub_references
from smart_home_agent.catalog.models import Product
from smart_home_agent.catalog.normalize import Confidence, Ecosystem, EcosystemSignal
from smart_home_agent.tools.compatibility import CompatibilityState, check_compatibility

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(product_id: str) -> dict:
    return json.loads((FIXTURES_DIR / f"{product_id}.json").read_text(encoding="utf-8"))


def _build(product_id: str) -> Product:
    return build_product(_load_fixture(product_id))


def _catalog(*product_ids: str) -> dict[str, Product]:
    products = {pid: _build(pid) for pid in product_ids}
    resolve_hub_references(list(products.values()))
    return products


def test_homematic_alexa_needs_hardware_with_resolved_access_point():
    """The headline scenario: declares Alexa support (MATCH), but genuinely
    needs an Access Point -- ecosystem is checked FIRST, hub_required is a
    modifier on top, so this must be NEEDS_HARDWARE, never a bare DIRECT
    that promises more than the product delivers."""
    catalog = _catalog("26745237", "26756327")
    result = check_compatibility(catalog["26745237"], Ecosystem.ALEXA, catalog)

    assert result.state == CompatibilityState.NEEDS_HARDWARE
    assert result.confidence == Confidence.DECLARED
    assert len(result.required_products) == 1
    required = result.required_products[0]
    assert required.id == "26756327"
    assert required.price == Decimal("49.10")


def test_hub_required_without_declared_ecosystem_is_unknown_not_needs_hardware():
    """The bug the naive 'hub_required short-circuits everything' design
    would have caused: this product's hub_required is genuinely true --
    its own description names "Philips Hue Bridge" directly -- but its
    ecosystems dict says nothing about Alexa at all (no Sprachsteuerung
    key). A hub does not create ecosystem support that isn't declared --
    the honest state is UNKNOWN, not NEEDS_HARDWARE. hub_required is still
    echoed, since it's a fact, not a compatibility claim."""
    catalog = _catalog("27670004")
    result = check_compatibility(catalog["27670004"], Ecosystem.ALEXA, catalog)

    assert result.state == CompatibilityState.UNKNOWN
    assert result.hub_required is True
    assert result.required_products
    assert result.required_products[0].name == "Philips Hue Bridge"


def test_alexa_only_product_queried_for_homekit_is_incompatible():
    """Ring declares Alexa support only -- querying HomeKit, which it
    explicitly does not list, must be INCOMPATIBLE. Ring's own
    hub_required is correctly None here (its Hinweise only mentions an
    optional subscription, no hub noun at all) -- a real, separate
    improvement from dropping vendor_platform as a signal, not something
    this test is about."""
    catalog = _catalog("28597364")
    result = check_compatibility(catalog["28597364"], Ecosystem.APPLE_HOME, catalog)

    assert result.state == CompatibilityState.INCOMPATIBLE
    assert result.confidence == Confidence.DECLARED
    assert result.hub_required is None
    assert result.required_products == []


def test_required_products_still_shown_for_a_mismatch_when_hub_required_is_genuinely_true():
    """The principle test_alexa_only_product_queried_for_homekit_is_incompatible
    used to cover incidentally (before Ring's own hub_required turned out
    to be None): required_products reflects hub_required regardless of
    state, even INCOMPATIBLE -- it's a fact about the product, not a
    compatibility claim. Constructed directly, since a real product with
    both a narrow declared ecosystem and a genuine hub noun wasn't at
    hand."""
    product = Product(
        id="synthetic-mismatch-with-hub",
        title="Synthetic Alexa-Only Device",
        brand="Synthetic",
        category="synthetic-category",
        url="https://x/synthetic-mismatch-with-hub",
        is_smart=True,
        is_smart_confidence=Confidence.DECLARED,
        ecosystems={Ecosystem.ALEXA: EcosystemSignal(Confidence.DECLARED, "Unterstützte Sprachsteuerung")},
        hub_required=True,
        hub_required_confidence=Confidence.DECLARED,
        hub_hint="Some Bridge",
        hub_required_source="Hinweise",
    )
    result = check_compatibility(product, Ecosystem.APPLE_HOME, {})

    assert result.state == CompatibilityState.INCOMPATIBLE
    assert result.required_products
    assert result.required_products[0].name == "Some Bridge"


def test_bosch_matter_title_only_queried_for_alexa_is_unknown_declares_matter_false():
    """Bosch's ecosystems is {MATTER: INFERRED} -- present, but not
    DECLARED, so it doesn't qualify as a confident MISMATCH either; the
    honest state is UNKNOWN. declares_matter must be False here, since the
    title token is inferred, not a declared certification -- the flag
    should not overclaim just because the tag exists at all."""
    catalog = _catalog("32391327")
    result = check_compatibility(catalog["32391327"], Ecosystem.ALEXA, catalog)

    assert result.state == CompatibilityState.UNKNOWN
    assert result.declares_matter is False


def test_non_smart_product_is_incompatible():
    """A real padlock: is_smart is FALSE (curated non-connected category),
    so this must be INCOMPATIBLE with the not-connected reason, before the
    ecosystem check ever runs."""
    catalog = _catalog("30040720")
    result = check_compatibility(catalog["30040720"], Ecosystem.ALEXA, catalog)

    assert result.state == CompatibilityState.INCOMPATIBLE
    assert "not a connected product" in result.reason.lower()
    assert result.required_products == []


def test_thomson_alexa_hub_name_present_unresolved():
    """Thomson's ecosystems is empty (no Sprachsteuerung/Systeme key at
    all), so the verdict is UNSURE -> UNKNOWN -- but the hub fact must
    still surface: a real companion is named, even though it can't be
    resolved to a catalog id (Thombox doesn't exist in this catalog)."""
    catalog = _catalog("23197671")
    result = check_compatibility(catalog["23197671"], Ecosystem.ALEXA, catalog)

    assert result.required_products
    required = result.required_products[0]
    assert required.name == "Thombox"
    assert required.id is None
    assert required.price is None


def test_is_smart_unknown_queried_for_any_ecosystem_is_unknown_never_incompatible():
    """Absence of a signal is UNKNOWN everywhere else in this codebase --
    it must not become a denial here either. A product in an unlisted
    category with no signal at all (is_smart stays UNKNOWN, not FALSE)
    must never come back INCOMPATIBLE, for any ecosystem asked about."""
    product = Product(
        id="synthetic-unknown-smart",
        title="Generic Accessory",
        brand="Generic",
        category="some-unlisted-category",
        url="https://x/synthetic-unknown-smart",
    )
    assert product.is_smart is None

    for ecosystem in Ecosystem:
        result = check_compatibility(product, ecosystem, {})
        assert result.state == CompatibilityState.UNKNOWN
        assert result.state != CompatibilityState.INCOMPATIBLE


def test_unknown_state_result_never_has_a_compatible_looking_field():
    """Structural guard, not just a value check: the result must not even
    expose a field like `is_compatible` that a naive caller could read as
    true when the honest answer is 'we don't know'."""
    product = Product(
        id="synthetic-guard",
        title="Generic Accessory",
        brand="Generic",
        category="some-unlisted-category",
        url="https://x/synthetic-guard",
    )
    result = check_compatibility(product, Ecosystem.ALEXA, {})

    assert result.state == CompatibilityState.UNKNOWN
    field_names = {f.name for f in dataclasses.fields(result)}
    suspicious = {name for name in field_names if "compat" in name.lower() or name in {"ok", "success", "is_ok"}}
    assert suspicious == set()


def test_nanoleaf_direct_for_all_three_declared_ecosystems():
    """No hub_required, ecosystem declared -> DIRECT, for every ecosystem
    it actually lists -- including Apple HomeKit, which the Nanoleaf
    fixture exists specifically to prove comes from Unterstützte Systeme,
    not Sprachsteuerung."""
    catalog = _catalog("28601371")
    for ecosystem in (Ecosystem.ALEXA, Ecosystem.GOOGLE_HOME, Ecosystem.APPLE_HOME):
        result = check_compatibility(catalog["28601371"], ecosystem, catalog)
        assert result.state == CompatibilityState.DIRECT
        assert result.required_products == []


def test_direct_result_reports_the_real_ecosystem_source():
    """Real provenance, not approximated: Apple HomeKit support on this
    product comes from Unterstützte Systeme, not Unterstützte
    Sprachsteuerung -- the exact distinction the Nanoleaf fixture exists
    to prove."""
    catalog = _catalog("28601371")
    result = check_compatibility(catalog["28601371"], Ecosystem.APPLE_HOME, catalog)
    assert result.ecosystem_source == "Unterstützte Systeme"


def test_fit_notes_present_but_never_changes_the_state():
    """Physical fit is surfaced alongside the verdict, never inside it."""
    catalog = _catalog("26745237", "26756327")
    result = check_compatibility(catalog["26745237"], Ecosystem.ALEXA, catalog)

    assert result.fit_notes is not None
    assert "Ventilanschluss" in result.fit_notes
    assert result.state == CompatibilityState.NEEDS_HARDWARE
