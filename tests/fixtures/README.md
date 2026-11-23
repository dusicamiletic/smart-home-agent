# Fixtures (w06)

8 real products, copied verbatim from `data/products/`, picked to cover the
edge cases documented in `docs/decisions.md` and the battle plan's section 03.

| File | Role | Why this one |
|---|---|---|
| `26745237.json` | Homematic | The headline demo. Ecosystem declared via `Unterstützte Sprachsteuerung`, but `Datenübertragung: Funk` + `Hinweise` means it needs a Homematic IP Access Point. `check_compatibility` must return `needs_hardware`, not `direct`. |
| `28597364.json` | Ring | `Ring Türklingel mit Kamera Video Doorbell Pro 2 Hardwired`. Power-type derivation test: hardwired 24V doorbell. Sibling `28563648.json` (Plug-in variant) exists in the full catalog for the wiring-refusal-with-safe-alternative case later. |
| `28601371.json` | Nanoleaf | **The ecosystem-union test.** `Unterstützte Sprachsteuerung: Amazon Alexa, Google Assistant` AND `Unterstützte Systeme: Apple HomeKit System` are both present. Reading only the first key silently drops HomeKit support — this is the "most damaging single bug" the plan calls out, made concrete. Also carries the 4-tag preamble (`Mit Leuchtmittel, Dimmbar, LED, Nicht im Hausmüll entsorgen`) and the `Beständigkeit` header with exactly one pair inside. |
| `23197671.json` | Thomson | `Thomson Wassermelder` — functionally inert without a Thombox. Tests the `needs_hardware` / `incompatible` distinction and `Passend für` resolution. |
| `31682693.json` | Hue | `Philips Hue Smart-LED-Lampe White`. GU10-socket + Bridge-conditional compatibility case. |
| `25816769.json` | Rich | `TCL Inverter-Klimasplitgerät TAC-18CHSD/TPG11`. 4-way capacity variant ladder (26/35/52/70 m²) — genuine tier-up, not a pack-size upsell. |
| `32391327.json` | Empty attributes + description | `Bosch Smart Home Funk-Fensterkontakt II [+M] Matter`, €124.95. Both `attributes` and `description` are `""`. Only signal is the `[+M] Matter` title keyword and the subtitle. Confidence-tier stress test — nearly everything must come out `UNKNOWN` or `INFERRED`, never guessed as `DECLARED`. |
| `24977715.json` | Empty description only | `Gardena Smart system Hauswasserautomat smart Pressure Pump`. Non-empty, real `attributes` blob but `description: ""` — the opposite sparsity pattern from the Bosch fixture. |
| `31698195.json` | 9th, special case | Not one of the original 8 — added after `scripts/vocab_check.py` found it's the one product in all 943 where a section header (`Beständigkeit`) is reused as its own section's key name. Permanent regression test for the forced-key-after-header parser rule (see `docs/decisions.md`). |
| `33208183.json` | Multi-line promo price (w08) | `price` is a 3-line promo string (`"Ersparnis: 20,- €\nStatt 159,95\n139,95 €"`); the real price is the last line. Found during the w04 census, fixture added when `normalize.py`'s `parse_price` needed a real regression case. |
| `26582753.json` | Negated hub-requirement trigger (w08) | `REV WiFi-Türsprechanlage L2H` — description says `"...wodurch kein Gateway benötigt wird"` ("no Gateway needed"). Found by running `scripts/normalize_check.py` against all 943: a bare keyword match on `benötigt` without checking for the preceding negation wrongly claimed `hub_required=True`. |

Hand-derived expected parser output for three of these (Homematic, Nanoleaf,
Bosch — chosen to cover the rich case, the union-bug case, and the sparsity
case) is in `expected.py`, to check the parser against once it's written
(w07).
