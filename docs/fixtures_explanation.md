# Fixtures Explanation

This document explains the purpose of `tests/fixtures/*.json`, why the specific fixture files were chosen, and what `tests/fixtures/expected.py` is for.

## Why these fixtures exist

The fixtures are a small, focused set of real product examples from the catalog.
They are not random samples.
Their purpose is to capture the important parsing and business-rule edge cases the project must handle.

## What the fixtures are for

The fixture JSON files serve as:

- **concrete parser inputs**: real raw product data from `data/products`
- **targeted regression cases**: selected examples that exercise risky or important behavior
- **documentation of real data shapes**: useful when the parser is being written and reviewed

They are meant to make sure the parser handles the catalog’s real complexity, not just an ideal case.

## Why these 8 files were selected

The chosen fixtures cover distinct categories of behavior:

- `26745237.json` — a rich product with many declared attributes and a compatibility/hub requirement.
- `28597364.json` — a power / wiring variant case for doorbells.
- `28601371.json` — the Nanoleaf ecosystem-union regression case, where ecosystem support is split across different keys.
- `23197671.json` — a water detector that needs hardware dependency logic and "Passend für" resolution.
- `31682693.json` — a Hue product, useful for bridge-required and socket compatibility handling.
- `25816769.json` — a climate device with real tier-up variant logic.
- `32391327.json` — a sparsity stress case: both `attributes` and `description` are empty, so the parser must infer from title/subtitle only.
- `24977715.json` — the opposite sparsity case: description is empty but `attributes` is present.

## What `tests/fixtures/expected.py` is for

`tests/fixtures/expected.py` contains hand-derived expected parser outputs for a subset of the fixtures.
It is not production parser code.
It is a ground-truth reference used to verify the parser’s behavior once the parser is implemented.

The file contains:

- expected `tags` extracted from the raw product data
- expected flat `attrs` dictionaries of parsed attribute name/value pairs
- `post_normalize_notes` describing the parsing and compatibility semantics a correct implementation must preserve

## What a tag is and why it matters

A `tag` is a standalone line that appears before the first recognized section header in the raw `attributes` blob.
It is not a section header itself, and it is not part of a key/value pair.

We invented `tags` because the raw data often starts with a loose preamble of product facts that do not belong in the structured sectioned metadata.
That preamble includes things like `Nicht im Hausmüll entsorgen`, `Mit Leuchtmittel`, `Dimmbar`, or `LED`.

These lines are important because they carry useful product-level attributes, but forcing them into `header` or `key:value` semantics would be incorrect.
Keeping them as `tags` preserves the original meaning while still allowing the parser to treat the rest of the attributes as structured sections.

## What we are trying to achieve with this setup

The goal is to make the parser robust and aligned with the project’s requirements.
Specifically, this fixture setup aims to:

- catch regressions in ecosystem detection,
- ensure sparse and incomplete products are handled safely,
- verify that real-world `attributes` text is parsed correctly,
- lock in the expected output for the most important edge cases early,
- and avoid writing the parser against only synthetic or simplified examples.

## Why this is clearer than docstrings alone

The explanation here is intentionally higher-level and structured around intent:

- what each fixture is meant to test,
- why those specific products were chosen,
- how `expected.py` functions as a specification,
- and how the fixtures support parser development.

This is meant to supplement, not replace, code-level documentation and test coverage.
