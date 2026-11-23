import json
from decimal import Decimal
from pathlib import Path

from scripts.build_catalog import build_product
from smart_home_agent.catalog.index import build_indices
from smart_home_agent.catalog.loader import load_catalog
from smart_home_agent.catalog.models import Product
from smart_home_agent.catalog.normalize import Ecosystem
from smart_home_agent.tools.catalog_tools import _lexical_score, get_product, search_products

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _synthetic(product_id: str, **overrides) -> Product:
    defaults = dict(
        id=product_id,
        title=f"Synthetic Product {product_id}",
        brand="Synthetic",
        category="synthetic-category",
        url=f"https://x/{product_id}",
    )
    defaults.update(overrides)
    return Product(**defaults)


def _build(product_id: str):
    return build_product(json.loads((FIXTURES_DIR / f"{product_id}.json").read_text(encoding="utf-8")))


def _setup(*product_ids: str):
    products = [_build(pid) for pid in product_ids]
    catalog = {p.id: p for p in products}
    by_category, by_ecosystem = build_indices(products)
    return catalog, by_category, by_ecosystem


def test_headline_scenario_alexa_thermostat_under_budget():
    """"Ich habe Alexa, ein Thermostat unter 60 €" (plan's own headline
    example): ecosystem=ALEXA, category=thermostatkoepfe, max_price=60 --
    the Homematic thermostat survives the gate; a Hue bulb (different
    category) and an aircon (over budget) must not."""
    catalog, by_category, by_ecosystem = _setup("26745237", "31682693", "25816769")

    results = search_products(
        catalog, by_category, by_ecosystem, category="thermostatkoepfe", ecosystem=Ecosystem.ALEXA, max_price=Decimal(60)
    )

    assert [p.id for p in results] == ["26745237"]


def test_category_and_ecosystem_are_both_required_a_guarantee_not_a_preference():
    """Set intersection, not union -- a product matching only one of the
    two filters must not survive the gate."""
    catalog, by_category, by_ecosystem = _setup("26745237", "31682693")

    results = search_products(catalog, by_category, by_ecosystem, category="led-lampen", ecosystem=Ecosystem.ALEXA)

    assert [p.id for p in results] == ["31682693"]


def test_max_price_excludes_products_over_budget():
    catalog, by_category, by_ecosystem = _setup("26745237", "25816769")

    results = search_products(catalog, by_category, by_ecosystem, max_price=Decimal(100))

    assert [p.id for p in results] == ["26745237"]


def test_keyword_lexical_match_on_a_socket_type():
    """Exact-identifier matching, not semantic similarity: "GU10" only
    appears verbatim in one product's attrs (Lampensockel), and dense
    vectors were explicitly cut for this build."""
    catalog, by_category, by_ecosystem = _setup("26745237", "31682693")

    results = search_products(catalog, by_category, by_ecosystem, keywords=["GU10"])

    assert [p.id for p in results] == ["31682693"]


def test_keyword_with_no_match_returns_nothing_rather_than_the_whole_catalog():
    catalog, by_category, by_ecosystem = _setup("26745237", "31682693")

    results = search_products(catalog, by_category, by_ecosystem, keywords=["Ventilanschluss existiert nicht"])

    assert results == []


def test_no_filters_ranks_hub_free_products_before_hub_required_ones_then_by_price():
    """Real fixtures: the TCL aircon (25816769, hub_required unknown/None)
    outranks both Homematic products (26745237, 31682693 -- both
    hub_required True) despite costing far more -- price used to be the
    whole story and put the aircon last; "works without extra hardware"
    now outranks "cheap but needs a hub." Within the hub-required group,
    price still breaks the tie (31682693 at 21.98 EUR before 26745237 at
    49.10 EUR)."""
    catalog, by_category, by_ecosystem = _setup("26745237", "31682693", "25816769")

    results = search_products(catalog, by_category, by_ecosystem)

    assert [p.id for p in results] == ["25816769", "31682693", "26745237"]


def test_get_product_found_and_missing():
    catalog, _, _ = _setup("26745237")

    assert get_product(catalog, "26745237").title.startswith("Homematic")
    assert get_product(catalog, "does-not-exist") is None


def test_hub_not_required_ranks_before_hub_required_when_otherwise_identical():
    """Ranking, not the gate: both survive; order is what changes. This is
    the KPI-relevant case the plan called out -- "why does your agent
    lead with the cheapest option" has no good answer when the cheap one
    needs a 60 EUR Access Point and an equally-priced alternative doesn't."""
    no_hub = _synthetic("a", price=Decimal("50"), hub_required=False)
    needs_hub = _synthetic("b", price=Decimal("50"), hub_required=True)
    catalog = {"a": no_hub, "b": needs_hub}
    by_category, by_ecosystem = build_indices([no_hub, needs_hub])

    results = search_products(catalog, by_category, by_ecosystem)

    assert [p.id for p in results] == ["a", "b"]


def test_hub_required_none_ranks_with_false_not_with_true():
    """Tri-state, not boolean: unknown must not be demoted just for
    missing data -- the same "absence isn't a negative" rule normalize.py
    enforces for the fields themselves, applied here to their ranking."""
    unknown = _synthetic("unknown", price=Decimal("50"), hub_required=None)
    no_hub = _synthetic("no_hub", price=Decimal("50"), hub_required=False)
    needs_hub = _synthetic("needs_hub", price=Decimal("50"), hub_required=True)
    catalog = {p.id: p for p in (unknown, no_hub, needs_hub)}
    by_category, by_ecosystem = build_indices([unknown, no_hub, needs_hub])

    results = search_products(catalog, by_category, by_ecosystem)

    assert [p.id for p in results][-1] == "needs_hub"
    assert {p.id for p in results[:2]} == {"unknown", "no_hub"}


def test_higher_keyword_score_outranks_lower_when_hub_status_is_equal():
    """Two keywords, so score can actually differ (`_lexical_score` counts
    matched keywords, not occurrences): "gadget" matches both products,
    "special" only the second. Same hub_required on both, so this isolates
    the score term of the sort key on its own."""
    one_match = _synthetic("one_match", title="Gadget", hub_required=False)
    two_matches = _synthetic("two_matches", title="Special Gadget", hub_required=False)
    catalog = {p.id: p for p in (one_match, two_matches)}
    by_category, by_ecosystem = build_indices([one_match, two_matches])

    results = search_products(catalog, by_category, by_ecosystem, keywords=["gadget", "special"])

    assert [p.id for p in results] == ["two_matches", "one_match"]


def test_price_breaks_the_tie_when_hub_status_and_keyword_score_are_equal():
    cheaper = _synthetic("cheaper", price=Decimal("10"), hub_required=False)
    pricier = _synthetic("pricier", price=Decimal("20"), hub_required=False)
    catalog = {p.id: p for p in (cheaper, pricier)}
    by_category, by_ecosystem = build_indices([cheaper, pricier])

    results = search_products(catalog, by_category, by_ecosystem)

    assert [p.id for p in results] == ["cheaper", "pricier"]


def test_ranking_never_changes_which_products_are_returned():
    """The structural guard: ranking is a `.sort()` over what the gate
    already selected, never a second filter. Checked against the real
    943-product catalogue for a few different queries, comparing the
    actual result set to an independently computed gate (index
    intersection + price + keyword membership, with no sort involved at
    all) -- if a future change ever folds a filter into the sort key by
    mistake, this is what catches it."""
    catalog, by_category, by_ecosystem = load_catalog()

    queries = [
        {},
        {"category": "smart-home-thermostate"},
        {"ecosystem": Ecosystem.ALEXA, "max_price": Decimal(60)},
        {"keywords": ["Homematic"]},
        {"category": "led-lampen", "ecosystem": Ecosystem.ALEXA, "keywords": ["dimmbar"]},
    ]
    for query in queries:
        category = query.get("category")
        ecosystem = query.get("ecosystem")
        max_price = query.get("max_price")
        keywords = query.get("keywords")

        gate_ids = set(by_category.get(category, set())) if category is not None else None
        if ecosystem is not None:
            eco_ids = by_ecosystem.get(ecosystem, set())
            gate_ids = eco_ids if gate_ids is None else gate_ids & eco_ids
        if gate_ids is None:
            gate_ids = set(catalog)
        if max_price is not None:
            gate_ids = {i for i in gate_ids if catalog[i].price is not None and catalog[i].price <= max_price}
        if keywords:
            gate_ids = {i for i in gate_ids if _lexical_score(catalog[i], keywords) > 0}

        result_ids = {p.id for p in search_products(catalog, by_category, by_ecosystem, **query)}
        assert result_ids == gate_ids, query
