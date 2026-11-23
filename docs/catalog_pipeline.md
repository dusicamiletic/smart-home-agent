# Catalog Build Pipeline

This document summarizes how the product catalog is built from raw JSON exports.
It explains the pipeline stages, the normalization rules, and the final model shape.

## Pipeline overview

The catalog build is an offline "compile once" process:

1. `scripts/census.py` inspects the raw dataset and discovers the data shapes.
2. `smart_home_agent/catalog/attributes.py` parses the free-form `attributes` blob.
3. `smart_home_agent/catalog/normalize.py` derives typed facts and confidence tiers.
4. `smart_home_agent/catalog/models.py` defines the final product record schema.
5. `scripts/build_catalog.py` reads raw products, applies parsing and normalization, and writes `build/catalog.json`.

This gives the agent a ready-to-use catalog instead of raw text.

---

## Stage 1: Raw data census

The census script is not part of the final build runtime.
It is a discovery tool that reads all `data/products/*.json` and reports:

- how many files load successfully,
- how many prices are parseable,
- how many `attributes` blobs are non-empty,
- how many products mention `Hinweise`,
- how many products declare ecosystem support,
- and the most frequent lines in `attributes`.

That output is used to decide parsing rules and vocabulary.

---

## Stage 2: Attributes parsing

Raw product `attributes` are semi-structured German text.
The parser in `smart_home_agent/catalog/attributes.py` breaks it into:

- `tags`: preamble lines before the first known section header,
- `attrs`: flat key/value pairs inside sections,
- `orphans`: any lines that do not fit the expected structure.

Important rule:
- the line immediately after a section header is always treated as a key,
  even if that line itself matches a known header.

This stage preserves the raw German strings for inspectability while turning the blob into structured fields.

---

## Stage 3: Normalization

`smart_home_agent/catalog/normalize.py` derives typed facts from parsed `attrs`, plus title/subtitle/description.
Every derived fact carries a confidence tier:

- `DECLARED` for explicit signals from `attrs`,
- `INFERRED` for weaker title/subtitle/description clues,
- `UNKNOWN` when no signal exists.

### Ecosystem rules

- `Unterstützte Sprachsteuerung` maps exact values to ecosystems:
  - `Amazon Alexa` → `ALEXA`
  - `Google Assistant` → `GOOGLE_HOME`
  - `Apple Siri` → `APPLE_HOME`
- `Unterstützte Systeme` may contain:
  - real ecosystems like `Apple HomeKit` or `Matter`
  - or vendor platforms like `Homematic IP System`
- only real ecosystems are included in `ecosystems`.

### Vendor platform rules

- `Unterstützte Systeme` values that are not HomeKit or Matter are treated as vendor-owned platforms.
- If a value ends with ` System`, the suffix is stripped.
- Example: `Homematic IP System` → vendor platform `Homematic IP`.

### Power type rules

- Prefer `Stromversorgung` if present.
- Otherwise use `Betriebsart`.
- Otherwise infer from subtitle keywords.
- Mappings:
  - `Festverdrahtet` → hardwired
  - `Netzbetrieben` → mains-powered
  - `Batteriebetrieben` → battery-powered

### Hub requirement rules

- `Passend für` is the strongest declared hub signal.
- `Hinweise` prose is the next best declared hub signal.
- Free-text product `description` is the weakest inferred signal.
- Negated trigger phrases like `kein Gateway benötigt` are ignored.

### Smart capability rules

- `Smart Home-fähig: Ja` declares the product is smart.
- Presence of `Datenübertragung`, `Unterstützte Sprachsteuerung`, or `Unterstützte Systeme` infers smart capability.
- Title keywords such as `Smart`, `WiFi`, `WLAN`, or `App` infer smart only after known brand prefixes are stripped.

### Other normalization rules

- `brand` is extracted from the title using a curated list of known multi-word brand prefixes.
- `category` is derived from the first path segment of the product URL.
- `price` parsing normalizes German formatting and handles multi-line promo strings by taking the last line.

---

## Final model: `smart_home_agent/catalog/models.py`

`Product` is the final catalog record shape.
It includes:

- raw stage-1 fields: `id`, `title`, `url`, `image`
- always-computable derived fields: `brand`, `category`
- optional parsed fields: `price`, `tags`, `attrs`, `orphans`
- normalized fields with confidence:
  - `ecosystems`
  - `vendor_platform` + `vendor_platform_confidence`
  - `power_type` + `power_type_confidence`
  - `hub_required` + `hub_required_confidence`
  - `hub_hint`
  - `is_smart` + `is_smart_confidence`

Sparsity is expected, so missing derived data defaults to `None`, `[]`, `{}`, or `UNKNOWN`.

---

## Build process: `scripts/build_catalog.py`

The build script does the following:

- loads all raw JSON products using `smart_home_agent/catalog/loader.py`,
- parses `attributes` with `parse_attributes`,
- derives normalized fields with `normalize.py`,
- constructs a `Product` for each record,
- writes the resulting list to `build/catalog.json`,
- writes a build report to `build/build_report.md`.

Key tactics:

- keep the build offline and hand-run only when data or parser logic changes.
- do not crash on a single bad file.
- record load failures and build failures.
- hash the raw input contents to detect staleness reliably.

---

## Why this is useful

This pipeline gives you:

- a repeatable, inspectable catalog build,
- a clear separation between data discovery, parsing, and normalization,
- a typed output record that the agent can load directly,
- and confidence information for every derived fact.

If you forget the flow later, this is the canonical summary of the catalog build stages and the rules behind them.
