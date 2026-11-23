# Did we go too far putting `hub_required` / `power_type` into deterministic fields?

A question worth having a written answer to, since it's the kind of thing a
reviewer will ask directly: *"stating something deterministically wrong is
much worse than just not trying to put that into a deterministic field —
did normalize.py overreach anywhere?"*

Short answer: **mostly no, with one real exception, and we caught it.**

## The numbers back this up, not against it

Look at what both fields actually settled on in the final build:

- `power_type`: 227/943 have a value, **716/943 (76%) are `UNKNOWN`**.
- `hub_required`: 307/943 are `True`, **636/943 (67%) are `UNKNOWN`**.

Neither field forces an answer where the data doesn't support one. Both
default to "we don't know" for the large majority of the catalog. If we'd
actually overreached, these numbers would be much closer to 100%.

## The distinction that matters: structured keys vs. free-text claims

`power_type` comes from *structured* keys — `Stromversorgung` /
`Betriebsart` are attrs fields with a small, fixed vocabulary
(`Festverdrahtet` / `Netzbetrieben` / `Batteriebetrieben`). That's just a
lookup table. It worked correctly on the first attempt, no iteration
needed — because it's genuinely closer in kind to `price` or `category`
than to a hard NLP problem.

`hub_required` is different in kind, not just degree: the build plan
itself says outright, *"there is no hub field."* The information only
exists as a sentence someone wrote in free-text prose (`Hinweise` /
`description`). That's a real natural-language extraction problem, and it
was always going to take real iteration to get right — the fact that it
did isn't evidence of overreach, it's evidence we were honest about how
hard the problem actually was, instead of shipping the first regex that
compiled.

## Where we did overreach — twice, and caught both

1. **`vendor_platform` (declaring an ecosystem) feeding `hub_required`.**
   Wrong, removed. A Hue bulb declaring "Philips Hue" doesn't mean it
   needs the Bridge — some Hue products work over Bluetooth alone.
2. **`Passend für` feeding `hub_required`.** Wrong, removed. The field
   means "fits X," and X is as often a room size as a real dependency
   ("Räume bis ca. 52 m²" on an aircon flagged a hub requirement).

Both were genuine instances of exactly the failure being worried about
here — asserting a deterministic fact the data didn't actually support.
The important part: both were caught by validating the derived field
against all 943 real products (cross-tabs against `is_smart`, against
`Datenübertragung`, against the hub-product category itself) *before*
being called done, not shipped and left wrong. That's the process working
as intended — but it's fair to note it happened, twice, before landing on
the current version.

## Why it was worth pushing through rather than leaving `hub_required` mostly unbuilt

It isn't a nice-to-have field — it's directly load-bearing for two of the
four core requirements in the brief:

- **Product recommendation with an explicit compatibility check.** The
  brief's own example — "ensuring a recommended thermostat works with the
  user's stated ecosystem" — *is* the Homematic-needs-an-Access-Point case.
  Without `hub_required`, that compatibility check can't be honest.
- **Upselling, the named business KPI.** The agent can't recommend the
  Access Point at all if nothing in the catalog says one is needed.

Leaving the field entirely unbuilt because it's hard would have meant
failing two requirements outright, not just accepting some risk on a
minor feature.

## The mechanism that actually provides the protection

The safety here comes from the **confidence tier**, not from the
correctness of any single heuristic. Even when `hub_required` was
overcounting (628/943, 67%, before the fixes), those extra flags were
landing in `INFERRED`, whose entire contract is "surface it, but hedge —
never state it as settled fact." The two things that would have been
genuinely dangerous — a wrong `DECLARED`, or a customer being told a
product needs hardware it never actually needed as a plain fact — didn't
happen; the noise was contained in exactly the bucket designed to absorb
noise. Tiering is what turns "the heuristic is imperfect" into "the
imperfection is bounded and labeled," which is the actual goal, not
perfect extraction.

## What to watch going forward

Don't treat the current numbers as fully settled. `hub_required` only
catches a hardware word from a fixed, curated list, inside free text — it
fails safe (→ `UNKNOWN`) on phrasing never seen before, so **33% is a
floor, not a ceiling.** If this needs to go further, the plan's own answer
isn't "add more regex" — it's the same LLM-proposes / catalog-verifies
pattern already used in `resolve.py` (a model suggests a candidate name,
the catalog checks whether it actually exists, and the model is never
trusted blindly). That preserves the same protection this field already
has; chasing more edge cases with regex would not, and has already shown
diminishing, then negative, returns twice.

**Bottom line:** keep the architecture as it is. The one framing to avoid
is calling this "done and solid" — the more accurate claim is "honestly
hedged, and probably still under-counting," and those are different
things to put in front of a reviewer.
