# The upselling strategy: three answers, not three tiers

`suggest_upsell` (`smart_home_agent/tools/upsell.py`) mentions a second
product for exactly one of three reasons. It's tempting to read them as a
ladder — mild, medium, aggressive — but that's the wrong mental model.
They're not degrees of the same thing. They answer three different
questions a customer could be asking, and each has its own trigger, its
own honesty test, and its own place in the priority order.

| # | Type | Question it answers | Fires on |
|---|------|----------------------|----------|
| 1 | `required_hardware` | "Does this even work?" | a fact already in the data |
| 2 | `completion` | "Is this the right variant for me?" | something the customer said |
| 3 | `companion` | "What else would help?" | brand + ecosystem + adjacency |

## 1. `required_hardware` — "this doesn't work without X"

The customer wants the Homematic thermostat. It talks over 868 MHz radio,
not WiFi, so their phone and Alexa cannot reach it directly. Without the
Access Point it's a dial on a radiator.

This isn't really an upsell — it's the truth about what they're buying.
Withholding it produces an angry customer and a refund, not a sale. It
always fires first when it applies, and — this is what makes it safe to
put first — the trigger is never a guess. `check_compatibility` already
computes `required_products` from `hub_required` / `hub_hint` /
`hub_product_id` (real fields, real provenance, see `docs/decisions.md`);
`suggest_upsell` just reads that fact off and refuses to offer it if the
hardware couldn't be resolved to a real catalog id (no filler item, see
the shared rule below).

> "Das funktioniert mit Alexa, benötigt aber den Homematic IP Access
> Point (54,95 €). Soll ich ihn dazulegen?"

**Implementation status: live.** `_required_hardware_offer` in
`upsell.py`, covered by
`test_required_hardware_outranks_companion_when_both_are_available`.

## 2. `completion` — "the version you actually need is a different one"

Same product line, different variant, and the customer's own words tell
you which one. They said their room is 48 m²; the TCL aircon comes in
26 / 35 / 52 / 70. The 52 is correct — not because it costs more, but
because the 35 would run flat out and the 70 is money wasted on capacity
they don't need. It can point down just as easily as up: if they'd said
20 m², suggesting the 26 is the exact same rule doing its job, and it
happens to be the cheaper item.

It only fires when the customer stated the constraint that makes one
variant clearly right — no stated room size, no offer. This is precisely
the property that keeps it from being a pricing trick: the recommendation
is anchored to something the customer said, not to what's more expensive
or more available.

> "Bei 48 m² würde ich das 52er-Modell nehmen — das 35er wäre dauerhaft
> am Limit."

**Implementation status: designed, not wired up.** `suggest_upsell`'s
current signature (`catalog, product_id, ecosystem, max_budget, basket,
declined`) carries no room size, no pack-size count — no stated
constraint of any kind. That's conversation state (the customer said "48
m²" three turns ago), which belongs to the agent instruction layer, not
to a stateless catalog-lookup tool. Rather than fake a plausible-looking
match without a real constraint to anchor it to — the same discipline
that kept `hub_required`'s `source` field from ever being reconstructed
after the fact — `_completion_offer` is a real function, kept in the
priority chain, that honestly returns `None` until that state exists.
Building it further means threading a stated constraint into the tool
call, not adding more regex to this repo.

## 3. `companion` — "people buying this usually need that too"

A different product that works alongside the one they're buying. They
bought a thermostat; a window contact stops the heating running while a
window is open. Genuinely useful, genuinely optional — which is exactly
why this is the only one of the three that's a real upsell in the
traditional sense, and why it's ranked last and fenced hardest.

The fence: same brand, compatible with their stated ecosystem (checked
through `check_compatibility` again, not assumed), and in a category the
adjacency map explicitly lists as related. Without that fence you'd
offer a garage door opener to someone buying a light bulb, on the
grounds that both are technically smart-home products.

> "Dazu passt der Fensterkontakt — die Heizung schaltet dann automatisch
> ab, wenn Sie lüften."

**Implementation status: live.** `_companion_offer` in `upsell.py`, using
the plan's adjacency map verbatim:

```
heating         → sensor
sensor          → alarm, hub
camera          → alarm, hub
lighting_indoor → switch, hub
lock            → camera, doorbell
doorbell        → camera
garden          → power
```

The map is deliberately not symmetric (`doorbell → camera` exists,
`camera → doorbell` doesn't) and deliberately not closed — a category
with no entry (climate, hub, power, switch, alarm-as-a-source) simply
never produces a companion offer. That's the "explicit adjacency map, not
'any different group'" rule taken literally: an edge that isn't listed
doesn't exist, rather than being inferred as probably fine. Covered by
`test_every_non_none_offer_has_a_non_empty_grounded_in`'s companion case
(a real Ring doorbell → real Ring camera, both declaring Alexa).

## Why the order is fixed

Only one offer per turn, so priority decides which one survives contact
with a real customer who has one question and limited patience.

- **Type 1 prevents a broken purchase.** If they don't hear about the
  Access Point, they go home with a radiator dial.
- **Type 2 corrects a wrong choice** before it's made — the 35er would
  have worked, technically, just badly.
- **Type 3 adds something nice**, but nothing breaks and nothing was
  wrong if they never hear it.

If a customer needs an Access Point *and* there's a matching window
sensor sitting right there, they need to hear about the Access Point —
the sensor can wait for the next turn. `suggest_upsell` enforces this
with control flow, not a priority number attached after the fact: three
functions tried in a fixed order, first non-`None` result wins
(`test_required_hardware_outranks_companion_when_both_are_available`
proves this with a catalog where both a real required hub and a real
compatible companion exist at once).

One gate sits in front of all three: if the customer's stated ecosystem
doesn't match the product they're already looking at
(`check_compatibility` says `INCOMPATIBLE` or `UNKNOWN`), `suggest_upsell`
returns no offer of any type. Recommending accessories on top of a base
recommendation that isn't itself confirmed to work would compound the
uncertainty, not use it.

## The rule underneath all three

Every offer traces to something real: a field in the data
(`required_hardware`), a constraint the customer stated
(`completion`), or a brand-plus-ecosystem-plus-adjacency match already
filtered through `check_compatibility` (`companion`). Never price, never
margin, never what's overstocked or slow-moving — the tool has no
concept of any of those and never will.

That's also why "nothing fits" is a valid, expected answer, not a bug to
route around:

- `declined=True` returns no offer immediately, for the rest of the
  session — the agent instruction layer is responsible for remembering
  that a customer said no and never asking again.
- If no candidate survives the filters (no required hardware, no stated
  constraint, no compatible same-brand companion in an adjacent group),
  `suggest_upsell` returns `offer: None` — not a fallback product picked
  to fill the slot. `test_nothing_suitable_returns_none_not_a_fallback_product`
  exists specifically to keep this honest: a Nanoleaf panel with nothing
  else to say gets nothing else said about it.
- The anchor is never offered back to itself, even under a constructed
  data bug where a hub's own `hub_product_id` points at its own id —
  checked inside `suggest_upsell` directly, not just assumed from
  `resolve.py`'s own self-match guard upstream.

Session-level bookkeeping (`state["upsell:declined"]`,
`offers_made`/`offers_accepted` for attach-rate reporting) is explicitly
the agent/session layer's job, not this tool's — `suggest_upsell` has no
`state` parameter and structurally can't know whether an offer was
*accepted*, since that only becomes known on the customer's next turn,
after this call has already returned.

The one line worth saying out loud in an interview: **each of these three
offers is advice, not a sales pitch, because each one is grounded in
something the data or the customer already told you — never in what's
more profitable to sell.**
