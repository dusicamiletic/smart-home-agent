"""compare_products (plan §02, tools/comparison.py): a normalized
attribute matrix, gaps marked unknown rather than the row being dropped --
"the model narrates the matrix; it never invents a cell."

Which spec rows are worth showing depends on what kind of product this
is: Batterielaufzeit means nothing on a ceiling lamp, lumens mean nothing
on a door lock. Category slugs are grouped by keyword (validated against
all 943: 122/943, 13%, fall to "generic" -- starter kits/hubs, blinds/
rollladen motors, irrigation, weather stations, brand-umbrella categories
-- none of which fit the six named groups below) and the spec-row list is
looked up per group. Comparing across groups falls back to the generic
list, since no single group's fields would be fair to every product in
the comparison.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from smart_home_agent.catalog.models import Product
from smart_home_agent.catalog.normalize import Ecosystem
from smart_home_agent.tools.compatibility import check_compatibility

UNKNOWN = "unknown"
MAX_ROWS = 10

_GROUP_KEYWORDS: dict[str, tuple[str, ...]] = {
    "lighting": ("led-", "leucht", "lampen", "lampe", "strahler", "beleuchtung", "licht", "dimmer"),
    "heating": ("thermostat", "heizung", "heizkoerper", "fussbodenheizung"),
    "camera": ("kamera", "tuerklingel", "tuerspion", "tuersprechanlage"),
    "sensor_safety": ("sensor", "melder", "alarm", "kontakt", "tuerschloss", "schloesser", "sicherung", "gong", "vorhaengeschloss"),
    "power": ("steckdose", "schalter", "stecker", "stromzaehler", "kabel", "ladestation", "mobility", "messgeraet", "relais"),
    "climate": ("klima",),
}


def _category_group(category: str) -> str:
    for group, keywords in _GROUP_KEYWORDS.items():
        if any(keyword in category for keyword in keywords):
            return group
    return "generic"


# Per-group spec rows, in priority order (highest first) -- real key names,
# and checked for real per-field coverage within each group against all
# 943 (not just that the category grouping itself was sound). climate is
# essentially perfect (93.8-100%, EU energy-label fields are mandated);
# lighting -- the biggest group at 413/943 -- ranges 39-85%, every field
# genuinely earning its place. "Anzahl Steckdosen Schuko" (5.8%) and
# "Anschlüsse" (1.4%) were dropped from power after checking: nearly
# always blank. "Lebensdauer" (3.3%) was dropped from generic the same
# way -- checked "Material" as a replacement (46.7% coverage) and
# rejected it anyway, since coverage alone doesn't make a field
# comparison-worthy: nobody chooses between two smart devices on plastic
# vs. steel. Three rows that always say something beats four where one is
# blank 97% of the time. "Betriebsart" was checked as a generic
# replacement too (51.6%) and rejected for a different reason: it's the
# exact raw text that already feeds the power_type core row, so showing
# it again would tell the customer "power_type: battery" and
# "Betriebsart: Batteriebetrieben" as if they were two separate facts.
# Rule going forward: never add a spec row that just restates a core row
# in the original German.
#
# "Energieeffizienzklasse" is a prefix match, not an exact key: the same
# product can carry more than one variant at once (a split-unit aircon has
# both "...Klimagerät Heizen" and "...Klimagerät Kühlen") because the
# suffix names the *mode*, not the product type the way it does elsewhere
# (Lichtquelle vs Klimagerät). First matching key wins -- a representative
# value, not a claim it's the single correct one.
_GROUP_FIELDS: dict[str, tuple[str, ...]] = {
    "lighting": ("Lichtstrom", "Farbtemperatur", "Lampensockel", "Dimmbarkeit", "Leistung", "Lebensdauer", "Farbe"),
    "heating": ("Ventilanschluss", "Batterielaufzeit", "Batterietyp", "Funktionen"),
    "camera": ("Auflösung", "Erfassungswinkel", "Nachtsichtreichweite", "Schutzart", "Stromversorgung"),
    "sensor_safety": ("Batterielaufzeit", "Batterietyp", "Reichweite Funk", "Schutzart"),
    "power": ("Max. Anschlussleistung", "Nennspannung", "Nennstrom"),
    "climate": ("Energieeffizienzklasse", "Kühlleistung", "Schalldruckpegel", "Raumgröße"),
    "generic": ("Schutzart", "Einsatzbereich", "Datenübertragung"),
}
_PREFIX_FIELDS = {"Energieeffizienzklasse"}


@dataclass
class ComparisonRow:
    field: str
    values: dict[str, str]
    differs: bool


@dataclass
class ComparisonResult:
    product_ids: list[str]
    rows: list[ComparisonRow] = field(default_factory=list)
    # Hinweise is prose (and where a subscription/wiring caveat like the
    # Ring's lives) -- it doesn't fit a table cell, so it rides along as a
    # footnote per product instead of a row.
    notes: dict[str, str] = field(default_factory=dict)


def _row(field_name: str, products: list[Product], getter) -> ComparisonRow:
    values = {p.id: getter(p) for p in products}
    differs = len(set(values.values())) > 1
    return ComparisonRow(field_name, values, differs)


def _core_rows(products: list[Product], catalog: dict[str, Product], ecosystem: Ecosystem | None) -> list[ComparisonRow]:
    rows = [
        _row("price", products, lambda p: str(p.price) if p.price is not None else UNKNOWN),
        # Sorted, not source order: two products can declare the identical
        # set of ecosystems but list them in a different order in their own
        # Sprachsteuerung text, which produced two different-looking
        # strings for the same fact and made `differs` wrongly say True.
        _row("ecosystems", products, lambda p: ", ".join(sorted(e.value for e in p.ecosystems)) or UNKNOWN),
    ]
    if ecosystem is not None:
        # The single most decision-relevant row a comparison can show: two
        # otherwise-identical thermostats where one is direct and the
        # other needs_hardware for *this customer's* stated ecosystem.
        rows.append(
            _row("compatibility_state", products, lambda p: check_compatibility(p, ecosystem, catalog).state.value)
        )
    rows.append(
        _row(
            "hub_required",
            products,
            lambda p: UNKNOWN if p.hub_required is None else ((p.hub_hint or "yes") if p.hub_required else "no"),
        )
    )
    rows.append(_row("power_type", products, lambda p: p.power_type.value if p.power_type is not None else UNKNOWN))
    return rows


def _prefix_getter(prefix: str):
    def getter(product: Product) -> str:
        for key, value in product.attrs.items():
            if key.startswith(prefix):
                return value
        return UNKNOWN

    return getter


def _exact_getter(key: str):
    return lambda product: product.attrs.get(key, UNKNOWN)


def _spec_rows(products: list[Product], budget: int) -> list[ComparisonRow]:
    groups = {_category_group(p.category) for p in products}
    group = groups.pop() if len(groups) == 1 else "generic"

    rows = []
    for key in _GROUP_FIELDS[group]:
        if budget <= 0:
            break
        is_prefix = key in _PREFIX_FIELDS
        present = any(
            (any(k.startswith(key) for k in p.attrs) if is_prefix else key in p.attrs) for p in products
        )
        if not present:
            continue
        getter = _prefix_getter(key) if is_prefix else _exact_getter(key)
        rows.append(_row(key, products, getter))
        budget -= 1
    return rows


def _hinweise_notes(products: list[Product]) -> dict[str, str]:
    return {p.id: p.attrs["Hinweise"] for p in products if p.attrs.get("Hinweise")}


def compare_products(
    catalog: dict[str, Product],
    product_ids: list[str],
    ecosystem: Ecosystem | None = None,
) -> ComparisonResult:
    products = [catalog[product_id] for product_id in product_ids if product_id in catalog]
    core_rows = _core_rows(products, catalog, ecosystem)
    spec_rows = _spec_rows(products, budget=max(0, MAX_ROWS - len(core_rows)))
    return ComparisonResult(
        product_ids=[p.id for p in products],
        rows=core_rows + spec_rows,
        notes=_hinweise_notes(products),
    )
