import json
from pathlib import Path

from scripts.build_catalog import build_product
from smart_home_agent.catalog.index import build_indices
from smart_home_agent.catalog.normalize import Ecosystem

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _build(product_id: str):
    return build_product(json.loads((FIXTURES_DIR / f"{product_id}.json").read_text(encoding="utf-8")))


def test_build_indices_groups_by_category_and_ecosystem():
    homematic = _build("26745237")  # category thermostatkoepfe, ALEXA/APPLE_HOME/GOOGLE_HOME
    nanoleaf = _build("28601371")  # category smarte-led-panels, same three ecosystems

    by_category, by_ecosystem = build_indices([homematic, nanoleaf])

    assert by_category["thermostatkoepfe"] == {"26745237"}
    assert by_category["smarte-led-panels"] == {"28601371"}
    assert by_ecosystem[Ecosystem.ALEXA] == {"26745237", "28601371"}


def test_build_indices_product_with_no_ecosystems_is_absent_from_every_ecosystem_bucket():
    bosch = _build("32391327")  # ecosystems = {MATTER: INFERRED}

    _, by_ecosystem = build_indices([bosch])

    assert by_ecosystem[Ecosystem.MATTER] == {"32391327"}
    assert by_ecosystem[Ecosystem.ALEXA] == set()
