# Census Explanation

This document explains the purpose of `scripts/census.py`, how it analyzed the product JSON files, what it discovered, and the important heuristics it used.

## Purpose of the census

The census is a first-pass data audit for the raw product JSON files in `data/products`.
It is not meant to fully parse or normalize the data.
Instead, it is designed to:

- verify that the JSON files are readable,
- measure how complete some important fields are,
- infer a simple category signal from product URLs,
- detect voice-assistant / smart-home ecosystem mentions,
- and collect repeated lines from the raw `attributes` field.

This gives a broad overview of the dataset and helps decide what to parse more carefully next.

## What the script reads and counts

For every JSON file in `data/products`, the script:

1. loads the file as JSON,
2. records any files that fail to decode,
3. extracts a few fields from the loaded product object,
4. counts and reports coverage for key signals.

The main coverage checks are:

- parseable `price`
- non-empty `attributes`
- ecosystem/voice-assistant signal
- presence of the word `Hinweise` in `attributes`

It also collects:

- category counts inferred from the URL,
- the 60 most frequent lines across all `attributes` blobs.

## How the census determines each signal

### Price parsing

The script does not use regex to parse price.
Instead, it applies a simple cleanup process to the raw price string:

- remove the euro symbol `€`,
- remove dot thousand separators `.`,
- convert `,-` to `,00`,
- convert the comma decimal separator to a dot,
- then attempt to convert the cleaned string to a numeric `Decimal`.

If conversion succeeds, the price is counted as parseable.
Otherwise it is treated as unparseable.

### Category extraction from URL

The script assumes a category hint exists in the product URL.
It looks for the first path segment after `bauhaus.info/`.
For example:

- `https://www.bauhaus.info/smart-home-schalter/...` → category `smart-home-schalter`
- `https://www.bauhaus.info/led-lampen/...` → category `led-lampen`

If the URL does not match that pattern, the product is counted under `UNKNOWN`.
This is a heuristic based on the observed URL structure, not a guaranteed taxonomy.

### Ecosystem / voice-assistant detection

The script uses a simple heuristic to decide whether a product declares a smart-home ecosystem signal.
It checks two places:

1. the `attributes` text for exact phrases:
   - `Unterstützte Sprachsteuerung`
   - `Unterstützte Systeme`
2. the product `title` for any of these keywords:
   - `Alexa`
   - `Google Assistant`
   - `Google Home`
   - `HomeKit`
   - `Matter`
   - `SmartThings`

If any of those matches, the product is counted as signaling a voice-assistant / ecosystem mention.

### `Hinweise` detection

The script also checks whether the raw `attributes` blob contains the substring `Hinweise`.
This is a simple inclusion check, not a structured parse.

## What the `attributes` field is and how the script uses it

The `attributes` field is treated as a raw text blob.
It is not handled as a structured object in this census.

In the data, it typically contains:

- section headers such as `Technische Daten`,
- attribute labels such as `Farbe`, `Material`, `EAN`,
- values and product facts such as `Weiß`, `230 V`, `IP20`,
- notes and warnings such as `Nicht im Hausmüll entsorgen`,
- feature markers such as `Smart Home-fähig`.

The script processes `attributes` by:

- splitting the text into lines,
- trimming each line,
- skipping empty lines,
- counting how often each distinct line appears across all products.

This means the output mixes headings, keys, and values.
The resulting line-frequency list is intentionally noisy and meant for manual judgment later.
It is a discovery step to help distinguish:

- repeated section headers,
- repeated attribute keys,
- repeated values.

## Why vocabulary is built from `attributes` only

The vocabulary is based on `attributes` because that field is the one semi-structured text blob in the JSON files.
It contains repeated section headers and key/value-like lines that a parser can learn from.

Other fields such as `title`, `description`, `price`, `url`, `id`, `image`, and `variants` are already either simple explicit fields or free-form prose.
They do not need the same header vocabulary, so they are not included in this step.

## What the census discovered in this dataset

From the current run, the script found:

- 943 product files were read successfully.
- 0 files failed to parse.
- 942 products had a price string the script could parse.
- 876 products had non-empty `attributes`.
- 613 products declared an ecosystem/voice-assistant signal by the heuristic.
- 668 products contained `Hinweise` in their attributes.

It also counted category slugs from product URLs and reported the counts for each inferred category.
The largest categories were:

- `led-lampen`: 140 products
- `smart-home-schalter`: 75 products
- `ueberwachungskameras-aussen`: 41 products
- `smart-home-leuchtmittel`: 38 products
- `smart-home-starter-kits-gateways`: 36 products

Finally, it listed the 60 most frequent lines in `attributes`.
The top lines included:

- `Weiterführende Produktinformationen`
- `Gewicht (Netto)`
- `EAN`
- `Technische Daten`
- `Farbe, Optik & Gestalt`
- `Anwendungs-, Montage- & Verarbeitungshinweise`
- `Nicht im Hausmüll entsorgen`
- `Maße, Volumen- & Gewichtsangaben`
- `Smart Home-fähig`
- `Ja`

## Important limitations and caveats

This census is not a final parsing step.
It is a diagnostic inventory with several simple heuristics.

Key caveats:

- ecosystem detection is only based on a few exact strings and title keywords,
- category extraction is based on a URL pattern and may be wrong for nonstandard URLs,
- price parsing only supports a limited German-style format,
- `attributes` are not normalized or split into structured fields,
- line-frequency counts are noisy and require manual interpretation.

## Summary

The census is meant to answer: "What does the raw product data look like, and how complete are the important fields?"

It discovers the dataset’s overall coverage, the apparent category distribution, the frequency of repeated `attributes` lines, and simple ecosystem signals.

It does this by reading every JSON file, applying a few heuristics to the raw fields, and writing a report of counts rather than transforming the product data into a clean schema.
