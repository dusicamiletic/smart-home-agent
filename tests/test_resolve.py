from smart_home_agent.catalog.models import Product
from smart_home_agent.catalog.resolve import resolve_hub_reference


def _product(id: str, title: str) -> Product:
    return Product(id=id, title=title, brand="x", category="x", url=f"https://x/{id}")


# Real titles from data/products/ -- the standalone accessory plus the three
# bundle products that also happen to contain every word in the hub_hint.
STANDALONE = _product("26756327", "Homematic IP Steuerzentrale Access Point HmIP-HAP")
ACCESS_POINT_2 = _product("33081825", "Homematic IP Steuerzentrale Access Point 2")
BUNDLE_THERMOSTAT = _product(
    "33208183", "Homematic IP Starter-Set 2x Heizkörperthermostat Pure mit Access Point 2 HmIP-SK28"
)
BUNDLE_SMOKE = _product("33208174", "Homematic IP Starter-Set 2x Rauchmelder mit Access Point 2 HmIP-SK27")
UNRELATED = _product("1", "Philips Hue Steuerzentrale Bridge")


def test_resolves_to_the_standalone_accessory_not_a_bundle():
    """Real ambiguity found in data/products/: three other titles also
    contain every word of the hint ('Homematic', 'IP', 'Access', 'Point'),
    because they're starter-set bundles that happen to include an access
    point alongside unrelated hardware. The standalone accessory -- the
    fewest extra words beyond the hint -- is the right recommendation, not
    a bundle the customer didn't ask for."""
    catalog = [BUNDLE_THERMOSTAT, BUNDLE_SMOKE, STANDALONE, UNRELATED]

    resolved_id = resolve_hub_reference("Homematic IP Access Point", catalog)

    assert resolved_id == "26756327"


def test_returns_none_when_hint_matches_nothing_in_the_catalog():
    """Real finding: 'Thomson Thombox' -- named directly in Passend für on
    several Thomson sensors -- does not exist as a titled product anywhere
    in the 943-product export. Not found must stay null, never a guess."""
    catalog = [STANDALONE, ACCESS_POINT_2, UNRELATED]

    assert resolve_hub_reference("Thomson Thombox", catalog) is None


def test_returns_none_for_a_hint_with_no_catalog_match_at_all():
    assert resolve_hub_reference("ein Smartphone", [UNRELATED]) is None


def test_never_resolves_a_product_to_itself():
    """Real bug found validating against all 943: 'Homematic IP Adapter Gira
    HmIP-ADA-GN' (id 32391558) declares Passend für: "Gira" -- describing
    what it fits, not a companion product to buy -- and its own title
    contains the word "Gira", so it resolved to itself. A product can never
    be its own required hub."""
    gira_adapter = _product("32391558", "Homematic IP Adapter Gira HmIP-ADA-GN")

    resolved_id = resolve_hub_reference("Gira", [gira_adapter, UNRELATED], exclude_id="32391558")

    assert resolved_id is None
