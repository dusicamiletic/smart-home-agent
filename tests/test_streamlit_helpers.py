from streamlit_helpers import find_products, format_price, hub_badge, needs_hardware, products_in_reply


def test_markdown_link_matches_a_title_containing_its_own_brackets():
    """Real regression: several Bosch titles carry a literal "[+M]" suffix.
    A naive `[^\\]]+` link-text class terminates at that inner "]" and never
    finds the real "](" that follows the actual title -- the row for that
    product silently never rendered. Two links on one line, one of them
    bracketed, is the exact shape that broke."""
    reply = (
        "- [Bosch Smart Home Smart-Steckdose Kompakt [+M] Matter]"
        "(https://example.com/steckdose) - 44.95, and "
        "[Bosch Smart Home Controller II](https://example.com/controller) for 77.99."
    )
    catalog = {
        "https://example.com/steckdose": {"title": "Steckdose", "url": "https://example.com/steckdose", "image_url": "x"},
        "https://example.com/controller": {"title": "Controller", "url": "https://example.com/controller", "image_url": "x"},
    }

    matched = products_in_reply(reply, catalog)

    assert [p["title"] for p in matched] == ["Steckdose", "Controller"]


def test_find_products_normalizes_name_to_title_and_keeps_other_fields():
    payload = {"offer": {"name": "Hub", "url": "https://example.com/hub", "image_url": "x", "price": 9.99}}

    found = find_products(payload)

    assert found["https://example.com/hub"] == {
        "name": "Hub",
        "url": "https://example.com/hub",
        "image_url": "x",
        "price": 9.99,
        "title": "Hub",
    }


def test_find_products_recurses_into_nested_required_products():
    payload = {
        "results": [
            {
                "title": "Plug",
                "url": "https://example.com/plug",
                "image_url": "x",
                "required_products": [{"name": "Hub", "url": "https://example.com/hub", "image_url": "y", "price": 9.99}],
            }
        ]
    }

    found = find_products(payload)

    assert set(found) == {"https://example.com/plug", "https://example.com/hub"}


def test_find_products_skips_a_dict_missing_any_of_the_three_fields():
    assert find_products({"url": "https://example.com/x", "image_url": "y"}) == {}
    assert find_products({"title": "Plug", "image_url": "y"}) == {}


def test_products_in_reply_dedupes_and_preserves_first_seen_order():
    reply = "[B](https://example.com/b) then [A](https://example.com/a) then [B](https://example.com/b) again"
    catalog = {
        "https://example.com/a": {"title": "A", "url": "https://example.com/a", "image_url": "x"},
        "https://example.com/b": {"title": "B", "url": "https://example.com/b", "image_url": "x"},
    }

    matched = products_in_reply(reply, catalog)

    assert [p["title"] for p in matched] == ["B", "A"]


def test_products_in_reply_ignores_a_link_not_in_the_catalog():
    reply = "[Unrelated](https://example.com/unrelated)"

    assert products_in_reply(reply, {}) == []


def test_format_price_formats_two_decimals_with_euro_sign():
    assert format_price(44.95) == "44.95 €"
    assert format_price(44.9) == "44.90 €"


def test_format_price_is_empty_for_none():
    assert format_price(None) == ""


def test_hub_badge_true_names_the_required_hardware():
    product = {"hub_required": True, "required_products": [{"name": "Bosch Smart Home Controller II"}]}

    assert hub_badge(product) == ":orange[⚠ needs Bosch Smart Home Controller II]"


def test_hub_badge_true_falls_back_to_a_generic_name_with_no_resolved_hardware():
    product = {"hub_required": True, "required_products": []}

    assert hub_badge(product) == ":orange[⚠ needs extra hardware]"


def test_hub_badge_is_empty_for_false_not_a_green_guarantee():
    """An absent badge is not a claim either way -- there is no "works on
    its own" badge, only silence, so a customer never reads "no badge" as
    a confirmed guarantee the way they'd never read a missing warning sign
    as a safety certificate."""
    assert hub_badge({"hub_required": False}) == ""


def test_hub_badge_is_empty_for_unknown_not_a_not_stated_label():
    assert hub_badge({"hub_required": None}) == ""


def test_hub_badge_is_empty_for_a_hub_even_if_hub_required_is_somehow_true():
    """A hub cannot require itself -- checked independently of whatever
    hub_required happens to hold, since that field being wrong here would
    otherwise render a self-contradictory warning."""
    product = {"hub_required": True, "is_hub": True, "required_products": [{"name": "Some Hub"}]}

    assert hub_badge(product) == ""


def test_needs_hardware_true_only_for_hub_required_true_and_not_a_hub():
    assert needs_hardware({"hub_required": True, "is_hub": False}) is True
    assert needs_hardware({"hub_required": True, "is_hub": True}) is False
    assert needs_hardware({"hub_required": False, "is_hub": False}) is False
    assert needs_hardware({"hub_required": None, "is_hub": False}) is False
