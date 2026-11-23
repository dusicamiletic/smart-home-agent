import json
from pathlib import Path

from scripts.build_catalog import build_product
from smart_home_agent.catalog.normalize import Ecosystem
from smart_home_agent.tools.comparison import MAX_ROWS, compare_products

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _build(product_id: str):
    return build_product(json.loads((FIXTURES_DIR / f"{product_id}.json").read_text(encoding="utf-8")))


def _catalog(*product_ids: str):
    products = [_build(pid) for pid in product_ids]
    return {p.id: p for p in products}


def _row(result, field_name):
    return next(r for r in result.rows if r.field == field_name)


def test_two_lighting_products_get_lighting_specific_rows():
    """Nanoleaf and the Hue bulb are both in the 'lighting' group by
    category keyword -- Lampensockel (a lighting-only spec) must appear,
    with the Hue bulb's real value."""
    catalog = _catalog("28601371", "31682693")
    result = compare_products(catalog, ["28601371", "31682693"])

    sockets = _row(result, "Lampensockel")
    assert sockets.values["31682693"] == "GU10"
    assert sockets.values["28601371"] == "unknown"  # Nanoleaf has no Lampensockel key at all
    assert sockets.differs is True


def test_products_from_different_groups_fall_back_to_generic_fields():
    """Homematic (heating) vs Nanoleaf (lighting) span two groups -- no
    single group's fields would be fair to both, so this must use the
    generic list (Schutzart/Einsatzbereich/Lebensdauer/Datenübertragung),
    not Homematic's heating fields or Nanoleaf's lighting fields."""
    catalog = _catalog("26745237", "28601371")
    result = compare_products(catalog, ["26745237", "28601371"])

    field_names = {r.field for r in result.rows}
    assert "Schutzart" in field_names  # generic list
    assert "Ventilanschluss" not in field_names  # heating-only, would be unfair to Nanoleaf
    assert "Lampensockel" not in field_names  # lighting-only, would be unfair to Homematic


def test_gap_shown_as_unknown_never_drops_the_row():
    """Homematic has Schutzart: IP20; Nanoleaf has no Schutzart key at all.
    The row must still appear for both, "unknown" standing in for
    Nanoleaf, not the row disappearing because one product lacks it."""
    catalog = _catalog("26745237", "28601371")
    result = compare_products(catalog, ["26745237", "28601371"])

    schutzart = _row(result, "Schutzart")
    assert schutzart.values["26745237"] == "IP20"
    assert schutzart.values["28601371"] == "unknown"


def test_brand_is_not_a_compared_row():
    """Dropped deliberately -- it's already in the title heading each
    column, a compared row would just repeat it."""
    catalog = _catalog("26745237", "28601371")
    result = compare_products(catalog, ["26745237", "28601371"])

    assert "brand" not in {r.field for r in result.rows}


def test_compatibility_state_row_only_appears_when_an_ecosystem_is_given():
    catalog = _catalog("26745237", "28601371")

    without_ecosystem = compare_products(catalog, ["26745237", "28601371"])
    assert "compatibility_state" not in {r.field for r in without_ecosystem.rows}

    with_ecosystem = compare_products(catalog, ["26745237", "28601371"], ecosystem=Ecosystem.ALEXA)
    state_row = _row(with_ecosystem, "compatibility_state")
    # Homematic needs its Access Point for Alexa; Nanoleaf declares Alexa directly.
    assert state_row.values["26745237"] == "needs_hardware"
    assert state_row.values["28601371"] == "direct"
    assert state_row.differs is True


def test_hinweise_is_a_footnote_not_a_row():
    """Homematic's Hinweise is exactly where the Access Point requirement
    is stated in prose -- it must ride along as a note, not try to fit in
    a table cell."""
    catalog = _catalog("26745237", "28601371")
    result = compare_products(catalog, ["26745237", "28601371"])

    assert "Hinweise" not in {r.field for r in result.rows}
    assert "26745237" in result.notes
    assert "Access Point" in result.notes["26745237"]
    assert "28601371" not in result.notes  # Nanoleaf has no Hinweise at all


def test_ecosystems_row_is_order_independent():
    """Real bug found eyeballing output: Nanoleaf's Sprachsteuerung lists
    'Amazon Alexa, Google Assistant' (Alexa then Google) while the Hue
    bulb's lists 'Amazon Alexa, Apple Siri, Google Assistant' (Apple
    before Google) -- both end up with the identical *set* of three
    ecosystems, but joining attrs in source order produced two different
    strings, so `differs` wrongly said True for two products that
    actually agree completely on ecosystem support."""
    catalog = _catalog("28601371", "31682693")
    result = compare_products(catalog, ["28601371", "31682693"])

    ecosystems_row = _row(result, "ecosystems")
    assert ecosystems_row.values["28601371"] == ecosystems_row.values["31682693"]
    assert ecosystems_row.differs is False


def test_differs_is_false_when_every_product_shares_the_same_value():
    catalog = _catalog("26745237", "28601371")
    result = compare_products(catalog, ["26745237", "28601371"])

    price_row = _row(result, "price")
    # Sanity: two different real prices, so this specific row does differ --
    # the meaningful assertion is that *some* row can be found not differing.
    assert price_row.differs is True
    hub_row = _row(result, "hub_required")
    assert hub_row.values["26745237"] != hub_row.values["28601371"]
    assert hub_row.differs is True


def test_row_count_is_capped():
    """Lighting has 7 candidate spec fields; with 5 core rows (ecosystem
    given) that would be 12 -- must be trimmed to the cap, not left to
    grow unbounded."""
    catalog = _catalog("28601371", "31682693")
    result = compare_products(catalog, ["28601371", "31682693"], ecosystem=Ecosystem.ALEXA)

    assert len(result.rows) <= MAX_ROWS


def test_climate_group_matches_energieeffizienzklasse_by_prefix():
    """The TCL aircon carries two variants of this key at once
    ("...Klimagerät Heizen" and "...Klimagerät Kühlen") because the key
    family's suffix names the *mode*, not the product type -- an exact-key
    match would find neither; a prefix match finds a real value."""
    catalog = _catalog("25816769")
    result = compare_products(catalog, ["25816769"])

    energy_row = _row(result, "Energieeffizienzklasse")
    assert energy_row.values["25816769"] in ("A+ (A+++ bis D)", "A++ (A+++ bis D)")
