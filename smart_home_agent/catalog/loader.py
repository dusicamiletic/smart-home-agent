"""Stage 0 (plan): read every raw product file. "Never crash. Collect
unreadable files into the report." A single malformed file is a fact about
the export, not a reason to abort the other 942.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from smart_home_agent.catalog.index import build_indices
from smart_home_agent.catalog.models import Product
from smart_home_agent.catalog.normalize import Ecosystem

DEFAULT_BUILD_DIR = Path(__file__).resolve().parent.parent.parent / "build"


@dataclass
class LoadFailure:
    path: Path
    error: str


@dataclass
class LoadResult:
    records: list[dict] = field(default_factory=list)
    failures: list[LoadFailure] = field(default_factory=list)


def load_all_json(directory: Path) -> LoadResult:
    result = LoadResult()
    for path in sorted(Path(directory).glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            result.failures.append(LoadFailure(path=path, error=str(exc)))
            continue
        result.records.append(record)
    return result


def load_catalog(
    build_dir: Path | None = None,
) -> tuple[dict[str, Product], dict[str, set[str]], dict[Ecosystem, set[str]]]:
    """Read `build/catalog.json`, written once by scripts/build_catalog.py,
    and reconstruct the typed Products plus the runtime indices -- "the
    same relationship as compiling and running" (plan): the parsing and
    normalization cost was already paid offline; this just deserializes
    the result at agent startup, milliseconds, no parsing, no API calls.
    """
    path = (build_dir or DEFAULT_BUILD_DIR) / "catalog.json"
    records = json.loads(path.read_text(encoding="utf-8"))
    products = [Product.model_validate(record) for record in records]
    catalog = {product.id: product for product in products}
    by_category, by_ecosystem = build_indices(products)
    return catalog, by_category, by_ecosystem
