import json
from pathlib import Path

from scripts.build_catalog import build_product
from smart_home_agent.catalog.loader import load_all_json, load_catalog
from smart_home_agent.catalog.normalize import Ecosystem

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def test_loads_every_valid_json_file_in_the_directory(tmp_path):
    (tmp_path / "1.json").write_text(json.dumps({"id": "1"}), encoding="utf-8")
    (tmp_path / "2.json").write_text(json.dumps({"id": "2"}), encoding="utf-8")

    result = load_all_json(tmp_path)

    assert {r["id"] for r in result.records} == {"1", "2"}
    assert result.failures == []


def test_corrupt_file_does_not_crash_the_load(tmp_path):
    """Stage 0 (plan): 'Read all 943. Never crash. Collect unreadable files
    into the report.' A single malformed file must not stop the whole load."""
    (tmp_path / "good.json").write_text(json.dumps({"id": "good"}), encoding="utf-8")
    (tmp_path / "bad.json").write_text("{not valid json", encoding="utf-8")

    result = load_all_json(tmp_path)

    assert [r["id"] for r in result.records] == ["good"]
    assert len(result.failures) == 1
    assert result.failures[0].path.name == "bad.json"


def test_ignores_non_json_files(tmp_path):
    (tmp_path / "1.json").write_text(json.dumps({"id": "1"}), encoding="utf-8")
    (tmp_path / "README.md").write_text("not a product", encoding="utf-8")

    result = load_all_json(tmp_path)

    assert len(result.records) == 1
    assert result.failures == []


def _built_fixture(product_id: str) -> dict:
    raw = json.loads((FIXTURES_DIR / f"{product_id}.json").read_text(encoding="utf-8"))
    return build_product(raw).model_dump(mode="json")


def test_load_catalog_round_trips_the_written_build_output(tmp_path):
    """load_catalog reads exactly what build_catalog.py writes -- the
    parsing cost paid once at build time, not repeated at agent startup.
    Uses two real fixtures (Homematic thermostat + its real Access Point)
    so the round trip is checked against real Confidence/Ecosystem/Decimal
    values, not a hand-typed dict that might not match Product's own
    serialization."""
    catalog_json = [_built_fixture("26745237"), _built_fixture("26756327")]
    (tmp_path / "catalog.json").write_text(json.dumps(catalog_json, ensure_ascii=False), encoding="utf-8")

    catalog, by_category, by_ecosystem = load_catalog(build_dir=tmp_path)

    assert set(catalog) == {"26745237", "26756327"}
    thermostat = catalog["26745237"]
    assert thermostat.hub_required is True
    assert thermostat.ecosystems[Ecosystem.ALEXA].source == "Unterstützte Sprachsteuerung"
    assert by_category["thermostatkoepfe"] == {"26745237"}
    assert "26745237" in by_ecosystem[Ecosystem.ALEXA]
