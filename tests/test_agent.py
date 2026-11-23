from decimal import Decimal

from smart_home_agent import agent
from smart_home_agent.catalog.normalize import Ecosystem


def test_emptied_by_reports_the_single_filter_responsible():
    """Thermostat category + Alexa both have real matches (15, then 11);
    adding a 1-euro price cap on top empties it. The other two filters
    are innocent -- only max_price should be named."""
    filters = {
        "category": "smart-home-thermostate",
        "ecosystem": Ecosystem.ALEXA,
        "max_price": Decimal("1"),
        "keywords": None,
    }
    assert len(agent.catalog_tools.search_products(catalog=agent.CATALOG, by_category=agent.BY_CATEGORY, by_ecosystem=agent.BY_ECOSYSTEM, **filters)) == 0

    assert agent._emptied_by(filters) == "max_price"


def test_emptied_by_picks_a_single_filter_when_dropping_either_one_alone_would_have_worked():
    """Two active filters, and *either one alone* would already restore
    results (category='kabelverbinder' alone has its one product;
    ecosystem=MATTER alone has six elsewhere) -- this is not the "joint"
    case, it's two independently valid fixes, so naming just one
    (deterministically, the alphabetically-first) is the honest, minimal
    answer -- not a reason to name a pair when a single filter already
    suffices."""
    filters = {"category": "kabelverbinder", "ecosystem": Ecosystem.MATTER, "max_price": None, "keywords": None}

    assert agent._emptied_by(filters) == "category"


def test_emptied_by_reports_the_pair_when_no_single_filter_alone_would_have_emptied_it():
    """Three active filters where every 'drop just one' combination is
    still empty, but dropping a specific pair (leaving one filter active)
    is not: category='kabelverbinder' (one product, 6.95 EUR, no
    ecosystem) + ecosystem=MATTER (six products, cheapest 11.70 EUR) +
    max_price=5 (below both). category+ecosystem alone is already zero
    (see the single-filter test above); category+price is zero (the one
    kabelverbinder product costs more than 5 EUR); ecosystem+price is
    zero (every Matter product costs more than 5 EUR) -- so no single
    drop restores anything. Dropping category and ecosystem together,
    leaving only the 5 EUR price cap, does. Real fixed-order 'blame
    whichever filter was added last' logic can't reach this at all: it
    would report on category+ecosystem going to zero and stop, never
    trying price on its own."""
    filters = {
        "category": "kabelverbinder",
        "ecosystem": Ecosystem.MATTER,
        "max_price": Decimal("5"),
        "keywords": None,
    }
    search = agent.catalog_tools.search_products
    assert len(search(catalog=agent.CATALOG, by_category=agent.BY_CATEGORY, by_ecosystem=agent.BY_ECOSYSTEM, category="kabelverbinder", max_price=Decimal("5"))) == 0
    assert len(search(catalog=agent.CATALOG, by_category=agent.BY_CATEGORY, by_ecosystem=agent.BY_ECOSYSTEM, ecosystem=Ecosystem.MATTER, max_price=Decimal("5"))) == 0

    assert agent._emptied_by(filters) == "category and ecosystem"


def test_emptied_by_with_a_single_active_filter_names_it_directly_without_searching_again():
    filters = {"category": "definitely-not-a-real-category-slug", "ecosystem": None, "max_price": None, "keywords": None}

    assert agent._emptied_by(filters) == "category"


def test_search_catalog_only_computes_emptied_by_when_results_are_actually_empty():
    result = agent.search_catalog(ecosystem="ALEXA")

    assert result["total_matches"] > 0
    assert result["emptied_by"] is None


def test_search_catalog_reports_a_joint_emptied_by_end_to_end():
    result = agent.search_catalog(category="kabelverbinder", ecosystem="MATTER", max_price=5.0)

    assert result["total_matches"] == 0
    assert result["emptied_by"] == "category and ecosystem"


def test_search_catalog_clamps_a_limit_above_twenty_to_twenty():
    """Browsing ("show me all") legitimately wants more than 3 results, but
    the model is never trusted to self-limit -- the wrapper clamps
    regardless of what it asks for."""
    result = agent.search_catalog(ecosystem="ALEXA", limit=50)

    assert len(result["results"]) == 20


def test_search_catalog_total_matches_is_the_true_count_not_the_returned_slice():
    """The browse-mode instruction ('143 Produkte passen -- hier sind die
    ersten 20') depends on total_matches staying the full count even when
    the slice sent back is capped -- this is what makes that statement
    possible instead of a guess."""
    result = agent.search_catalog(ecosystem="ALEXA", limit=3)

    assert result["total_matches"] > len(result["results"])
    assert len(result["results"]) == 3


def test_search_catalog_never_returns_more_than_the_clamped_limit():
    for limit in (1, 3, 20, 21, 100):
        result = agent.search_catalog(ecosystem="ALEXA", limit=limit)
        assert len(result["results"]) <= 20


def test_is_hub_true_for_a_real_hub_category_product():
    """Bosch Smart Home Controller II -- category smart-home-starter-kits-
    gateways, and "Smart Home Controller" is itself in _HUB_NOUNS. Real
    catalog data, not a constructed fixture: this is the exact product a
    live transcript surfaced (docs/decisions.md, 2026-08-10)."""
    controller = agent.CATALOG.get("30490042")

    assert controller is not None
    assert agent._is_hub(controller) is True


def test_is_hub_false_for_a_product_that_merely_needs_a_hub():
    steckdose = agent.CATALOG.get("33401900")

    assert steckdose is not None
    assert steckdose.hub_required is True
    assert agent._is_hub(steckdose) is False


def test_serialize_product_carries_is_hub_for_the_list_view():
    controller = agent.CATALOG.get("30490042")

    assert agent._serialize_product(controller)["is_hub"] is True
