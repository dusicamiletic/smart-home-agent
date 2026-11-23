import json
from decimal import Decimal
from pathlib import Path

from smart_home_agent.catalog.attributes import parse_attributes
from smart_home_agent.catalog.normalize import (
    Confidence,
    Ecosystem,
    EcosystemSignal,
    PowerType,
    brand_from_title,
    category_from_url,
    derive_ecosystems,
    derive_hub_requirement,
    derive_is_smart,
    derive_power_type,
    derive_vendor_platform,
    parse_price,
)
from smart_home_agent.catalog.normalize import _first_unnegated_trigger

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(product_id: str) -> dict:
    return json.loads((FIXTURES_DIR / f"{product_id}.json").read_text(encoding="utf-8"))


def test_parses_plain_price():
    assert parse_price("49,10 €") == Decimal("49.10")


def test_parses_comma_dash_price():
    assert parse_price("999,- €") == Decimal("999.00")


def test_parses_comma_dash_price_with_thousands_separator():
    """Found by running normalize_check.py against all 943 real products:
    four-digit ",-" prices ("1.299,- €") were falling through to None
    because the "." thousands separator survived into the Decimal string."""
    assert parse_price("1.299,- €") == Decimal("1299.00")


def test_parses_multiline_promo_price_from_last_line():
    """docs/decisions.md: 33208183.json's price field is a 3-line promo
    string; the real price is the last line, not the first."""
    product = _load_fixture("33208183")
    assert parse_price(product["price"]) == Decimal("139.95")


def test_category_from_url_strips_trailing_newline():
    """Real url fields end with a trailing newline (decisions.md, w03).
    Category is the first path segment after the domain."""
    product = _load_fixture("26745237")
    assert product["url"].endswith("\n")
    assert category_from_url(product["url"]) == "thermostatkoepfe"


def test_category_from_url_bosch_fixture():
    product = _load_fixture("32391327")
    assert category_from_url(product["url"]) == "smart-home-fensterkontakte-tuerkontakte"


def test_brand_from_title_single_word():
    assert brand_from_title("Nanoleaf Erweiterungskit Elements Hexagons 3 Panels") == "Nanoleaf"


def test_brand_from_title_known_two_word_brand():
    """Real census over all 943 titles (first-2/3-token frequency): 'Homematic
    IP' is a real sub-brand (156 titles), not brand 'Homematic' + generic word
    'IP'."""
    assert brand_from_title("Homematic IP Smart-Thermostatkopf HmIP-eTRV-2") == "Homematic IP"


def test_brand_from_title_known_three_word_brand():
    """'Bosch Smart Home' is Bosch's smart-home product line name, appearing
    on 28/943 titles verbatim -- not the generic brand 'Bosch' followed by an
    is_smart keyword collision."""
    title = "Bosch Smart Home Funk-Fensterkontakt II [+M] Matter"
    assert brand_from_title(title) == "Bosch Smart Home"


def test_ecosystems_homematic_declared_via_sprachsteuerung_only():
    """Unterstützte Systeme: Homematic IP System is Homematic's own walled
    garden, not a real ecosystem -- must not be unioned in here."""
    product = _load_fixture("26745237")
    attrs = parse_attributes(product["attributes"]).attrs
    assert derive_ecosystems(attrs, product["title"]) == {
        Ecosystem.ALEXA: EcosystemSignal(Confidence.DECLARED, "Unterstützte Sprachsteuerung"),
        Ecosystem.APPLE_HOME: EcosystemSignal(Confidence.DECLARED, "Unterstützte Sprachsteuerung"),
        Ecosystem.GOOGLE_HOME: EcosystemSignal(Confidence.DECLARED, "Unterstützte Sprachsteuerung"),
    }


def test_ecosystems_nanoleaf_unions_sprachsteuerung_and_systeme():
    """The regression test for the 'most damaging single bug': Apple HomeKit
    support comes ONLY from Unterstützte Systeme, not Sprachsteuerung, and
    must still appear in the union -- each with its own real source, not a
    shared/guessed one."""
    product = _load_fixture("28601371")
    attrs = parse_attributes(product["attributes"]).attrs
    assert derive_ecosystems(attrs, product["title"]) == {
        Ecosystem.ALEXA: EcosystemSignal(Confidence.DECLARED, "Unterstützte Sprachsteuerung"),
        Ecosystem.GOOGLE_HOME: EcosystemSignal(Confidence.DECLARED, "Unterstützte Sprachsteuerung"),
        Ecosystem.APPLE_HOME: EcosystemSignal(Confidence.DECLARED, "Unterstützte Systeme"),
    }


def test_ecosystems_bosch_inferred_from_title_matter_keyword_only():
    """attrs is completely empty; the only signal anywhere is the '[+M]
    Matter' title keyword, so it must land as INFERRED, never DECLARED,
    with its source honestly labeled 'title' rather than an attrs key."""
    product = _load_fixture("32391327")
    attrs = parse_attributes(product["attributes"]).attrs
    assert derive_ecosystems(attrs, product["title"]) == {
        Ecosystem.MATTER: EcosystemSignal(Confidence.INFERRED, "title"),
    }


def test_vendor_platform_homematic():
    product = _load_fixture("26745237")
    attrs = parse_attributes(product["attributes"]).attrs
    assert derive_vendor_platform(attrs) == ("Homematic IP", Confidence.DECLARED)


def test_vendor_platform_absent_when_systeme_is_a_real_ecosystem():
    """Nanoleaf's only Unterstützte Systeme value is Apple HomeKit System --
    a real ecosystem, not a vendor walled garden, so there is no vendor
    platform signal here."""
    product = _load_fixture("28601371")
    attrs = parse_attributes(product["attributes"]).attrs
    assert derive_vendor_platform(attrs) == (None, Confidence.UNKNOWN)


def test_vendor_platform_prefers_the_value_matching_the_products_own_brand():
    """Real bug found sampling vendor_platform values across all 943: this
    Philips Hue spotlight declares 'Unterstützte Systeme: Razer Chroma
    System, Philips Hue System, Samsung Smart Things System' -- Razer
    Chroma is a PC-gaming lighting-sync feature, not a purchasable hub, and
    picking whichever value comes first in the list picked exactly that.
    The product's own brand should break the tie."""
    product = _load_fixture("32478752")
    attrs = parse_attributes(product["attributes"]).attrs
    assert attrs["Unterstützte Systeme"] == "Razer Chroma System, Philips Hue System, Samsung Smart Things System"
    assert derive_vendor_platform(attrs, brand="Philips Hue") == ("Philips Hue", Confidence.DECLARED)


def test_vendor_platform_falls_back_to_first_value_when_brand_matches_none():
    """No candidate matches the brand -- keep the old, simple behavior
    rather than returning nothing just because the tie-break didn't fire."""
    product = _load_fixture("32478752")
    attrs = parse_attributes(product["attributes"]).attrs
    assert derive_vendor_platform(attrs, brand="Some Unrelated Brand") == (
        "Razer Chroma",
        Confidence.DECLARED,
    )


def test_power_type_homematic_declared_via_betriebsart():
    product = _load_fixture("26745237")
    attrs = parse_attributes(product["attributes"]).attrs
    assert derive_power_type(attrs, product["subtitle"]) == (
        PowerType.BATTERY,
        Confidence.DECLARED,
    )


def test_power_type_ring_prefers_stromversorgung_over_contradicting_betriebsart():
    """Real data (docs/decisions.md-worthy contradiction, plan section on
    power type): this product carries both Stromversorgung: Festverdrahtet
    and Betriebsart: Netzbetrieben at once. Stromversorgung is the more
    specific field for the wiring question the guardrail actually cares
    about, so it wins over the coarser, contradicting Betriebsart."""
    product = _load_fixture("28597364")
    attrs = parse_attributes(product["attributes"]).attrs
    assert attrs["Stromversorgung"] == "Festverdrahtet"
    assert attrs["Betriebsart"] == "Netzbetrieben"
    assert derive_power_type(attrs, product["subtitle"]) == (
        PowerType.HARDWIRED,
        Confidence.DECLARED,
    )


def test_power_type_bosch_inferred_from_subtitle_keyword():
    """attrs is empty; the only signal is the subtitle keyword, so this must
    land as INFERRED, not DECLARED."""
    product = _load_fixture("32391327")
    attrs = parse_attributes(product["attributes"]).attrs
    assert derive_power_type(attrs, product["subtitle"]) == (
        PowerType.BATTERY,
        Confidence.INFERRED,
    )


def test_power_type_unknown_when_no_signal_anywhere():
    assert derive_power_type({}, "Weiß, 3 Stk.") == (None, Confidence.UNKNOWN)


def test_hub_requirement_homematic_declared_via_hinweise():
    """The headline demo scenario: Hinweise names the Access Point by name,
    buried in free text -- 'Der Betrieb erfordert die Anbindung an eine der
    folgenden Lösungen: Homematic IP Access Point mit ...'."""
    product = _load_fixture("26745237")
    attrs = parse_attributes(product["attributes"]).attrs
    result = derive_hub_requirement(attrs, product["description"])
    assert result.required is True
    assert result.confidence == Confidence.DECLARED
    assert result.hint == "Homematic IP Access Point"


def test_hub_requirement_thomson_still_true_after_dropping_passend_fuer():
    """Thomson's real dependency was always stated twice: Passend für names
    "Thomson Thombox" directly, but the description separately says "...
    funktioniert nur in Verbindung mit einer Thombox" -- and also mentions
    "Thombox" earlier, unnegated, on its own. Dropping Passend für entirely
    costs nothing here: this still resolves True via description's own
    noun match. The hint is shorter than before ("Thombox", not "Thomson
    Thombox") since the brand prefix isn't textually adjacent to the noun
    in this sentence -- a known, accepted hint-quality limitation, not a
    correctness issue (the boolean is what matters and it's still right)."""
    product = _load_fixture("23197671")
    attrs = parse_attributes(product["attributes"]).attrs
    result = derive_hub_requirement(attrs, product["description"], product["title"])
    assert result.required is True
    assert result.confidence == Confidence.INFERRED
    assert result.hint == "Thombox"
    assert result.source == "description"


def test_hub_requirement_ignores_passend_fuer_entirely():
    """Passend für is dropped as a hub source entirely, not merely demoted:
    it was never a hub signal to begin with -- the key means "fits X," and
    X is just as often a room size or a controlled category as a real
    companion. This Homematic RGB controller declares "Passend für: LED
    Stripes" (what it controls, not a dependency) -- correctly ignored --
    but still resolves True, because its own description separately and
    genuinely names "Homematic IP Access Point" as required. Nothing real
    is lost by dropping Passend für; the actual dependency was always
    stated in the description too."""
    product = _load_fixture("30678802")
    attrs = parse_attributes(product["attributes"]).attrs
    assert attrs["Passend für"] == "LED Stripes"
    result = derive_hub_requirement(attrs, product["description"], product["title"])
    assert result.confidence == Confidence.INFERRED
    assert result.hint == "Homematic IP Access Point"
    assert result.source == "description"


def test_hub_requirement_noun_extraction_beats_the_old_bare_trigger_fallback():
    """Same fixture that used to need a Passend-für fallback for a decent
    hint (Hinweise's old verb-anchored extraction produced the bare
    fragment "nur in Verbindung"). Noun-based extraction reads the real
    hardware name directly out of the same Hinweise text -- "Bosch Smart
    Home Controller" -- which is not only better text, it's the actually
    correct answer; the old Passend-für fallback ("Berker-Schalter
    Arsys/K1") was itself just fitment info for a different feature, not
    a hub at all."""
    product = _load_fixture("25641420")
    attrs = parse_attributes(product["attributes"]).attrs
    assert attrs["Hinweise"] == "Steuerung nur in Verbindung mit dem Bosch Smart Home Controller möglich"
    result = derive_hub_requirement(attrs, product["description"])
    assert result.confidence == Confidence.DECLARED
    assert result.hint == "Bosch Smart Home Controller"


def test_hub_requirement_noun_alone_is_sufficient_without_any_trigger_verb():
    """Inverted design, checking real text: 'Sie benötigt keinen Hub' shows
    the verb doesn't guarantee a real hub claim, and conversely a hub noun
    alone -- no verb needed nearby at all in the matched clause -- is
    itself sufficient. Isolated here with a synthetic sentence carrying
    only a noun, no requirement verb anywhere."""
    result = derive_hub_requirement({}, "Diese Lampe funktioniert mit der Hue Bridge wunderbar.")
    assert result.required is True
    assert result.confidence == Confidence.INFERRED
    assert result.hint == "Hue Bridge"


def test_hub_requirement_thombox_named_in_description_alone():
    """Real product, no Hinweise, no Passend für -- 'In Kombination mit
    der Thombox zu verwenden' names the companion by type with no
    requirement verb in the same clause at all. Under the old verb-first
    design this relied on a later, separate 'wird eine Thombox benötigt'
    sentence; the noun-first design catches it immediately, from the very
    first mention."""
    product = _load_fixture("23197918")
    attrs = parse_attributes(product["attributes"]).attrs
    assert attrs.get("Hinweise") is None
    assert attrs.get("Passend für") is None
    assert "In Kombination mit der Thombox zu verwenden" in product["description"]
    result = derive_hub_requirement(attrs, product["description"])
    assert result.required is True
    assert result.confidence == Confidence.INFERRED
    assert result.hint == "Thombox"
    assert result.source == "description"


def test_hub_requirement_bare_verb_without_any_hub_noun_no_longer_fires():
    """The false-positive class the redesign exists to kill: a real product
    whose description says 'erfordert ein kompatibles Smart-Home-System' --
    a genuine requirement verb, but naming a generic category, not any
    specific hardware from the noun list. Must now resolve UNKNOWN, not a
    guessed True."""
    product = _load_fixture("28980292")
    attrs = parse_attributes(product["attributes"]).attrs
    assert "erfordert ein kompatibles Smart-Home-System" in product["description"]
    result = derive_hub_requirement(attrs, product["description"])
    assert result.required is None
    assert result.confidence == Confidence.UNKNOWN


def test_hub_requirement_keeps_a_genuinely_informative_hinweise_hint():
    """The fix above must not blindly prefer Passend für whenever it's
    present -- this product's Hinweise hint ("Homematic IP Access Point")
    is already the real answer, while its unrelated Passend für value
    ("Busch-Jaeger, Gira, Merten...") names compatible switch-frame brands
    for a completely different feature. Overwriting a good hint with
    unrelated noise would be a regression, not an improvement."""
    product = _load_fixture("26745246")
    attrs = parse_attributes(product["attributes"]).attrs
    assert attrs["Passend für"].startswith("Busch-Jaeger")
    result = derive_hub_requirement(attrs, product["description"])
    assert result.hint == "Homematic IP Access Point"


def test_hub_requirement_vendor_platform_alone_is_no_longer_a_signal():
    """Real cross-tab check against all 943 (hub_required x is_smart, x
    Datenübertragung, x the hub-category group itself) proved the 4th
    source wrong at scale, not just for WiZ: "declares a vendor platform"
    and "needs a hub" are different facts (a plain Hue bulb can work over
    Bluetooth without the Bridge), and treating the first as evidence for
    the second was an unverified inference, not a reading of the data.
    This Schellenberg timer has no Hinweise, no Passend für, and no hub
    noun anywhere in its description -- its only signal was ever the
    vendor platform, which no longer counts. vendor_platform itself is
    unaffected -- still a stored fact, just not a hub_required input.

    (Note: many real Philips Hue products carry boilerplate description
    text that *does* genuinely name the Bridge as required for Alexa/
    Google control specifically -- that's a real noun-based signal, not
    this case, and correctly still fires; see the Hue fixtures used
    elsewhere in this file and in test_compatibility.py.)"""
    product = _load_fixture("22893505")
    attrs = parse_attributes(product["attributes"]).attrs
    assert attrs.get("Hinweise") is None
    assert attrs.get("Passend für") is None
    assert derive_vendor_platform(attrs, brand="Schellenberg") == ("Schellenberg Smart Home", Confidence.DECLARED)
    result = derive_hub_requirement(attrs, product["description"])
    assert result.required is None
    assert result.confidence == Confidence.UNKNOWN


def test_hub_requirement_bosch_unknown_not_guessed():
    """No Hinweise, no Passend für, no description -- nothing to go on, so
    this must come out UNKNOWN, never guessed as either True or False."""
    product = _load_fixture("32391327")
    attrs = parse_attributes(product["attributes"]).attrs
    result = derive_hub_requirement(attrs, product["description"])
    assert result.required is None
    assert result.confidence == Confidence.UNKNOWN
    assert result.hint is None


def test_hub_requirement_hub_product_does_not_require_itself():
    """Real regression found by the hub-category invariant test: this IS
    the Homematic IP Access Point, and its own description describes
    itself in the third person -- "Die Homematic IP Steuerzentrale Access
    Point... Der Homematic IP Access Point dient als Basis für..." -- both
    "Steuerzentrale" and "Access Point" are noun matches, but both words
    are also literally in this product's own title. A hub cannot require
    itself; self-description is not a dependency."""
    product = _load_fixture("26756327")
    assert product["title"] == "Homematic IP Steuerzentrale Access Point HmIP-HAP"
    attrs = parse_attributes(product["attributes"]).attrs
    result = derive_hub_requirement(attrs, product["description"], product["title"])
    assert result.required is None
    assert result.confidence == Confidence.UNKNOWN


def test_hub_requirement_bundled_companion_is_not_a_dependency():
    """A second real regression from the same invariant test, a different
    shape: 'Starter-Set mit Temperatursender und Gateway' names the
    Gateway as *included in this purchase*, not something to separately
    buy -- the opposite of what hub_required is supposed to mean. Several
    Mobile-Alerts/Technoline starter-sets in the real catalog share this
    exact template."""
    product = _load_fixture("25974001")
    assert "Starter-Set mit Temperatursender und Gateway" in product["description"]
    attrs = parse_attributes(product["attributes"]).attrs
    result = derive_hub_requirement(attrs, product["description"], product["title"])
    assert result.required is None
    assert result.confidence == Confidence.UNKNOWN


def test_hub_requirement_not_fooled_by_negated_trigger_word():
    """Found by running normalize_check.py against all 943 real products:
    this description says '...wodurch kein Gateway benötigt wird' -- 'no
    Gateway is needed'. A bare keyword match on 'benötigt' without checking
    for the preceding negation ('kein') would wrongly claim required=True
    for a product that explicitly does NOT need a hub."""
    product = _load_fixture("26582753")
    attrs = parse_attributes(product["attributes"]).attrs
    assert "kein Gateway benötigt" in product["description"]
    result = derive_hub_requirement(attrs, product["description"])
    assert result.required is None
    assert result.confidence == Confidence.UNKNOWN


def test_hub_requirement_negation_window_reaches_past_25_chars():
    """Found writing check_compatibility tests: the 25-char backward window
    missed the extremely common German construction 'kein <adjective> <noun>
    erforderlich' -- 'kein zusätzliches Werkzeug erforderlich' ("no
    additional tool required") puts 27 characters between the negation and
    the trigger. Both occurrences in this real description are this exact
    phrase, and there is no other trigger word anywhere in it -- so once
    negation is detected correctly, hub_required must fall all the way
    through to UNKNOWN, not just to a different (still wrong) True."""
    product = _load_fixture("28601371")
    attrs = parse_attributes(product["attributes"]).attrs
    assert "kein zusätzliches Werkzeug erforderlich" in product["description"]
    result = derive_hub_requirement(attrs, product["description"])
    assert result.required is None
    assert result.confidence == Confidence.UNKNOWN


def test_hub_requirement_does_not_cross_a_sentence_boundary_to_find_negation():
    """The fix for the case above must not overreach: this real product's
    first trigger is 'Hue Bridge und Hue Sync Box erforderlich', and the
    *next* bullet point happens to start with 'Nicht verlängerbar...' --
    an unrelated sentence, not a negation of the requirement. Extending
    the window blindly would wrongly suppress a real, later-confirmed
    requirement ('die Hue Bridge... wird... benötigt')."""
    product = _load_fixture("30431476")
    attrs = parse_attributes(product["attributes"]).attrs
    assert "erforderlich\nNicht verlängerbar" in product["description"]
    result = derive_hub_requirement(attrs, product["description"])
    assert result.required is True
    assert result.confidence == Confidence.INFERRED


def test_first_unnegated_trigger_rejects_forward_negation():
    """A second, distinct real pattern found the same way: German also
    negates *after* the trigger verb -- 'Sie benötigt keinen Hub' ("it
    doesn't need a Hub"). The old backward-only window couldn't see this
    at all, in either direction."""
    product = _load_fixture("32052615")
    assert "Sie benötigt keinen Hub" in product["description"]
    match = _first_unnegated_trigger("Sie benötigt keinen Hub und lässt sich einrichten.")
    assert match is None
    product = _load_fixture("26745237")
    attrs = parse_attributes(product["attributes"]).attrs
    ecosystems = derive_ecosystems(attrs, product["title"])
    assert derive_is_smart(attrs, product["title"], "thermostatkoepfe", ecosystems, hub_required=True) == (
        True,
        Confidence.DECLARED,
    )


def test_is_smart_bosch_true_via_ecosystems_not_the_brand_name():
    """The real defect this replaces: derive_is_smart used to look at a
    narrower keyword set than derive_ecosystems (Matter wasn't in its
    keyword list), so the two disagreed about the same product -- Bosch's
    '[+M] Matter' title token made derive_ecosystems return {MATTER:
    INFERRED} while derive_is_smart returned UNKNOWN. is_smart is now a
    union that includes "ecosystems non-empty", so the two can't disagree
    by construction: True, INFERRED, via the ecosystems signal, not by
    matching 'Smart' inside the brand name 'Bosch Smart Home' (attrs is
    still empty, so the declared flag and connectivity keys are absent)."""
    product = _load_fixture("32391327")
    attrs = parse_attributes(product["attributes"]).attrs
    ecosystems = derive_ecosystems(attrs, product["title"])
    assert ecosystems == {Ecosystem.MATTER: EcosystemSignal(Confidence.INFERRED, "title")}
    assert derive_is_smart(attrs, product["title"], "smart-home-fensterkontakte-tuerkontakte", ecosystems, hub_required=None) == (
        True,
        Confidence.INFERRED,
    )


def test_is_smart_true_via_ecosystems_alone():
    """Isolates the new union member: no declared flag, no connectivity
    key, no hub, no title keyword -- only a non-empty ecosystems dict."""
    ecosystems = {Ecosystem.ALEXA: EcosystemSignal(Confidence.DECLARED, "Unterstützte Sprachsteuerung")}
    assert derive_is_smart({}, "Irgendein Gerät", "some-category", ecosystems, hub_required=None) == (
        True,
        Confidence.INFERRED,
    )


def test_is_smart_true_via_hub_required_alone():
    """'A product needing a hub is by definition connected' -- isolates
    this specific union member, with every other signal absent."""
    assert derive_is_smart({}, "Irgendein Gerät", "some-category", {}, hub_required=True) == (
        True,
        Confidence.INFERRED,
    )


def test_is_smart_true_via_connectivity_protocol():
    """Datenübertragung must match a real transport protocol, not just be
    present -- narrower and more specific than the old blanket check."""
    assert derive_is_smart({"Datenübertragung": "WLAN"}, "Irgendein Gerät", "some-category", {}, hub_required=None) == (
        True,
        Confidence.INFERRED,
    )


def test_is_smart_inferred_from_title_keyword_outside_brand():
    """A genuine title keyword outside the brand prefix should still count,
    proving the brand-stripping isn't just suppressing the whole fallback,
    with every other union member absent."""
    assert derive_is_smart({}, "Hama WiFi Steckdose", "some-category", {}, hub_required=None) == (
        True,
        Confidence.INFERRED,
    )


def test_is_smart_false_for_a_known_non_connected_category():
    """Tri-state, not binary: absence of a signal is UNKNOWN everywhere
    else in this codebase, so is_smart must not treat 'no signal' as a
    denial either. FALSE is reserved for a curated, evidence-based
    category list -- a real padlock, confirmed to have no attrs signal and
    no ecosystems, in a category that is definitively not a connected
    product."""
    product = _load_fixture("30040720")
    attrs = parse_attributes(product["attributes"]).attrs
    assert product["title"] == "Abus Vorhängeschloss Touch 57/50"
    ecosystems = derive_ecosystems(attrs, product["title"])
    assert ecosystems == {}
    assert derive_is_smart(attrs, product["title"], "vorhaengeschloesser", ecosystems, hub_required=None) == (
        False,
        Confidence.INFERRED,
    )


def test_is_smart_unknown_when_no_signal_and_category_not_on_the_false_list():
    """The genuine 'we don't know' case: no signal anywhere, but the
    category isn't on the curated non-connected list either -- must stay
    UNKNOWN, not fall through to a guessed False."""
    assert derive_is_smart({}, "Irgendein Zubehör", "some-unlisted-category", {}, hub_required=None) == (
        None,
        Confidence.UNKNOWN,
    )
