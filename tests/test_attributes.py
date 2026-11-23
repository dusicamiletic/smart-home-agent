import json
from pathlib import Path

from smart_home_agent.catalog.attributes import parse_attributes
from tests.fixtures import expected

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(product_id: str) -> dict:
    return json.loads((FIXTURES_DIR / f"{product_id}.json").read_text(encoding="utf-8"))


def test_homematic_matches_hand_derived_expectation():
    exp = expected.HOMEMATIC_26745237
    product = _load_fixture(exp["id"])
    result = parse_attributes(product["attributes"])
    assert result.tags == exp["tags"]
    assert result.attrs == exp["attrs"]
    assert result.orphans == []


def test_nanoleaf_unions_both_ecosystem_keys():
    """The regression test for the union bug: both ecosystem-bearing keys
    must survive the parse untouched, so normalize.py has both to union."""
    exp = expected.NANOLEAF_28601371
    product = _load_fixture(exp["id"])
    result = parse_attributes(product["attributes"])
    assert result.tags == exp["tags"]
    assert result.attrs == exp["attrs"]
    assert result.attrs["Unterstützte Sprachsteuerung"] == "Amazon Alexa, Google Assistant"
    assert result.attrs["Unterstützte Systeme"] == "Apple HomeKit System"
    assert result.orphans == []


def test_bosch_empty_attributes_parses_to_nothing_not_a_crash():
    exp = expected.BOSCH_32391327
    product = _load_fixture(exp["id"])
    assert product["attributes"] == ""
    result = parse_attributes(product["attributes"])
    assert result.tags == []
    assert result.attrs == {}
    assert result.orphans == []


def test_header_reused_as_key_does_not_orphan_the_value():
    """The one real collision found while validating the header list
    (docs/decisions.md): 'Beständigkeit' is both the section header and,
    on this one product, the key name. The forced-key-after-header rule
    must consume it as a key, not misread it as an empty second section."""
    product = _load_fixture("31698195")
    result = parse_attributes(product["attributes"])
    assert result.attrs["Beständigkeit"] == "Witterungsbeständig"
    assert result.orphans == []


def test_tolerates_empty_blob():
    result = parse_attributes("")
    assert result.tags == []
    assert result.attrs == {}
    assert result.orphans == []
