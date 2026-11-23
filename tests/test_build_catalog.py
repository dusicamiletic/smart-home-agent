import json
from decimal import Decimal
from pathlib import Path

from scripts.build_catalog import DEFAULT_DATA_DIR, build_product, resolve_hub_references, run_build
from smart_home_agent.catalog.models import Product
from smart_home_agent.catalog.normalize import Confidence, Ecosystem, EcosystemSignal, PowerType

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(product_id: str) -> dict:
    return json.loads((FIXTURES_DIR / f"{product_id}.json").read_text(encoding="utf-8"))


def test_build_product_homematic_end_to_end():
    """Capstone test: raw JSON in, a fully-assembled Product out, matching
    every derived fact this session hand-verified in test_normalize.py."""
    product = build_product(_load_fixture("26745237"))

    assert product.id == "26745237"
    assert not product.url.endswith("\n"), "raw urls carry a trailing newline (w03) -- catalog.json should be clean"
    assert product.brand == "Homematic IP"
    assert product.category == "thermostatkoepfe"
    assert product.price == Decimal("49.10")
    assert product.ecosystems == {
        Ecosystem.ALEXA: EcosystemSignal(Confidence.DECLARED, "Unterstützte Sprachsteuerung"),
        Ecosystem.APPLE_HOME: EcosystemSignal(Confidence.DECLARED, "Unterstützte Sprachsteuerung"),
        Ecosystem.GOOGLE_HOME: EcosystemSignal(Confidence.DECLARED, "Unterstützte Sprachsteuerung"),
    }
    assert product.vendor_platform == "Homematic IP"
    assert product.power_type == PowerType.BATTERY
    assert product.hub_required is True
    assert product.hub_hint == "Homematic IP Access Point"
    assert product.hub_required_source == "Hinweise"
    assert product.is_smart is True
    assert product.is_smart_confidence == Confidence.DECLARED


def test_build_product_bosch_sparsity_stays_unknown_except_is_smart():
    """attrs is empty, so hub_required and power_type correctly stay
    UNKNOWN -- nothing there to derive from. is_smart is the one exception,
    and deliberately so: it's a union that includes "ecosystems non-empty",
    and the title's '[+M] Matter' tag already makes ecosystems non-empty
    via derive_ecosystems' own Matter check. Real defect this fixed: the
    old is_smart had a narrower keyword list than derive_ecosystems and
    disagreed with it for this exact product."""
    product = build_product(_load_fixture("32391327"))

    assert product.attrs == {}
    assert product.ecosystems == {Ecosystem.MATTER: EcosystemSignal(Confidence.INFERRED, "title")}
    assert product.power_type_confidence == Confidence.INFERRED
    assert product.hub_required is None
    assert product.hub_required_confidence == Confidence.UNKNOWN
    assert product.is_smart is True
    assert product.is_smart_confidence == Confidence.INFERRED


def test_run_build_resolves_hub_references_across_the_whole_catalog(tmp_path):
    """Cross-reference resolution (plan §02) needs every product to exist
    first -- it's the one global second pass in this build, unlike the
    per-product build_product() step. Disambiguating a standalone accessory
    from a bundle that also matches is proven separately, with real catalog
    ids, in test_resolve.py -- this test just proves the pass is wired into
    run_build() and doesn't crash. The Thomson water sensor's description
    names a "Thombox" that genuinely doesn't exist as a titled product
    anywhere in the real catalog -- true regardless of which subset of
    products is being resolved against."""
    summary = run_build(data_dir=FIXTURES_DIR, build_dir=tmp_path / "build")
    catalog = {p["id"]: p for p in json.loads((tmp_path / "build" / "catalog.json").read_text(encoding="utf-8"))}

    assert summary.hub_references_resolved >= 0
    assert catalog["23197671"]["hub_hint"] == "Thombox"
    assert catalog["23197671"]["hub_product_id"] is None


def test_vendor_platform_only_hub_hints_are_never_resolved():
    """Originally a real bug: a bare brand name like "Philips Hue" (once
    fed into hub_required from vendor_platform) matches 166 real titles by
    token subset, and the *wrong* one (a motion sensor, 1 extra word) beat
    the real Bridge (2 extra words) on the fewest-extra-words rule -- no
    tie-break rescues this, because the metric stops correlating with "is
    this a hub" once the hint is just a brand name.

    vendor_platform no longer feeds hub_required at all (a separate later
    fix), so this exact scenario can't occur from real data anymore -- but
    the guard in resolve_hub_references (skip when hub_hint == vendor_
    platform) is cheap, still correct in principle, and worth keeping as a
    defensive backstop. Verified directly here with a constructed case,
    since it no longer arises naturally."""
    gartenspot = build_product(_load_fixture("26371368"))
    bridge = build_product(_load_fixture("26010740"))
    assert gartenspot.hub_hint != gartenspot.vendor_platform  # confirms the natural case no longer occurs
    gartenspot.hub_required = True
    gartenspot.hub_hint = gartenspot.vendor_platform  # force the defensive scenario

    resolve_hub_references([gartenspot, bridge])

    assert gartenspot.hub_product_id is None


def test_run_build_writes_catalog_and_report(tmp_path):
    """A small, controlled data dir (the fixtures, not all 943) stands in for
    the real catalog so this test runs in milliseconds -- scripts/build_catalog.py
    itself is exercised for real, against all 943, separately."""
    build_dir = tmp_path / "build"

    summary = run_build(data_dir=FIXTURES_DIR, build_dir=build_dir)

    catalog_path = build_dir / "catalog.json"
    report_path = build_dir / "build_report.md"
    assert catalog_path.exists()
    assert report_path.exists()

    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert len(catalog) == summary.products_built
    assert summary.products_built > 0
    assert summary.load_failures == 0
    assert summary.build_failures == 0

    report = report_path.read_text(encoding="utf-8")
    assert "Build Report" in report
    assert str(summary.products_built) in report

    # Round-trips through Product, same as the agent will do at runtime.
    reloaded = [Product.model_validate(p) for p in catalog]
    assert {p.id for p in reloaded} == {json.loads(f.read_text(encoding="utf-8"))["id"] for f in FIXTURES_DIR.glob("*.json")}


def test_ecosystems_non_empty_never_implies_is_smart_falsy_across_all_943(tmp_path):
    """The invariant that stops the is_smart/ecosystems disagreement class
    of bug from returning: derive_is_smart is a union that includes
    "ecosystems non-empty", so by construction no product can have a real
    ecosystem tag while is_smart is False (or, before the fix, UNKNOWN).
    Checked against the real 943, not a hand-picked fixture -- a fixture
    proves one case; this proves the invariant holds everywhere."""
    summary = run_build(data_dir=DEFAULT_DATA_DIR, build_dir=tmp_path / "build")
    catalog = json.loads((tmp_path / "build" / "catalog.json").read_text(encoding="utf-8"))
    assert summary.products_built == 943

    violations = [p["id"] for p in catalog if p["ecosystems"] and p["is_smart"] is not True]
    assert violations == []


def test_hub_category_products_never_require_a_hub_across_all_943(tmp_path):
    """A hub cannot require itself. Real regression this guards against:
    before dropping vendor_platform as a hub_required signal, 25 of the 36
    products in this category were flagged hub_required=True, including
    the Homematic Access Point, the CCU3 controller, and the Bosch Smart
    Home Controller II -- the hub products, needing a hub. Checked against
    the real 943, not a fixture, so the next regression here fails a test
    instead of shipping."""
    summary = run_build(data_dir=DEFAULT_DATA_DIR, build_dir=tmp_path / "build")
    catalog = json.loads((tmp_path / "build" / "catalog.json").read_text(encoding="utf-8"))
    assert summary.products_built == 943

    hub_category = [p for p in catalog if p["category"] == "smart-home-starter-kits-gateways"]
    assert len(hub_category) > 0  # the category itself must still exist in the data

    violations = [(p["id"], p["title"]) for p in hub_category if p["hub_required"]]
    assert violations == []
