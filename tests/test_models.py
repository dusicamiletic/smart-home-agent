import json
from decimal import Decimal

from smart_home_agent.catalog.models import Product
from smart_home_agent.catalog.normalize import Confidence, Ecosystem, EcosystemSignal, PowerType


def test_product_minimal_construction_uses_sensible_defaults():
    """Most fields are sparse in the real data (w04 census). A Product with
    only the always-present raw fields should still construct, with every
    derived/tiered field defaulting to its unknown state, not crashing on
    missing keys."""
    product = Product(id="1", title="Some Product", brand="Some", category="cat", url="https://x/1")
    assert product.price is None
    assert product.tags == []
    assert product.attrs == {}
    assert product.ecosystems == {}
    assert product.power_type is None
    assert product.power_type_confidence == Confidence.UNKNOWN
    assert product.hub_required is None
    assert product.hub_product_id is None
    assert product.is_smart is None


def test_product_json_round_trip_preserves_every_field():
    """catalog.json is read back at agent runtime (plan: 'the same relationship
    as compiling and running') -- a Product must survive a full dump-to-JSON,
    reload-from-JSON cycle with no field drift, including the Decimal price
    and the Enum-keyed ecosystems dict."""
    original = Product(
        id="26745237",
        title="Homematic IP Smart-Thermostatkopf HmIP-eTRV-2",
        brand="Homematic IP",
        category="thermostatkoepfe",
        url="https://www.bauhaus.info/thermostatkoepfe/.../p/26745237",
        image="https://media.cdn.bauhaus/m/191721-1/prod_large_square.webp",
        price=Decimal("49.10"),
        tags=["Nicht im Hausmüll entsorgen"],
        attrs={"Material": "Kunststoff"},
        orphans=[],
        ecosystems={
            Ecosystem.ALEXA: EcosystemSignal(Confidence.DECLARED, "Unterstützte Sprachsteuerung"),
            Ecosystem.APPLE_HOME: EcosystemSignal(Confidence.DECLARED, "Unterstützte Sprachsteuerung"),
            Ecosystem.GOOGLE_HOME: EcosystemSignal(Confidence.DECLARED, "Unterstützte Sprachsteuerung"),
        },
        vendor_platform="Homematic IP",
        vendor_platform_confidence=Confidence.DECLARED,
        power_type=PowerType.BATTERY,
        power_type_confidence=Confidence.DECLARED,
        hub_required=True,
        hub_required_confidence=Confidence.DECLARED,
        hub_hint="Homematic IP Access Point",
        hub_required_source="Hinweise",
        hub_product_id="26756327",
        is_smart=True,
        is_smart_confidence=Confidence.DECLARED,
    )

    raw_json = json.dumps(original.model_dump(mode="json"), ensure_ascii=False)
    reloaded = Product.model_validate(json.loads(raw_json))

    assert reloaded == original
    assert isinstance(reloaded.price, Decimal)
    assert reloaded.ecosystems[Ecosystem.APPLE_HOME].confidence == Confidence.DECLARED
