# Why the wiring refusal had to become recoverable

`smart_home_agent/guardrail.py` — `REFUSAL_WIRING_EN` / `REFUSAL_WIRING_DE`.

## The scenario that exposed it

```
Turn 1 — "Ich habe Alexa, empfehlen Sie mir ein Thermostat"
         → agent recommends the Homematic IP thermostat

Turn 2 — "Danke, das nehme ich. Wie schließe ich es an?"
         → refused
```

The Homematic thermostat from turn 1 is `Betriebsart: Batteriebetrieben`
with `Ventilanschluss: M30 x 1,5 mm` — two AA batteries, screwed onto a
radiator valve. There is no electrical work involved at all. The honest
answer to "wie schließe ich es an?" is *"there's nothing to wire."*

The identical sentence, asked about a Ring Doorbell Pro 2
(`Stromversorgung: Festverdrahtet`, hardwired), is a *correct* refusal.

**Same words, opposite correct answers.**

## Why the guardrail can't tell them apart — and shouldn't try to, here

`before_model_guardrail` (L2, see `docs/decisions.md`) is a deterministic
regex pre-filter that fires *before any tool call*. That's the whole
point of L2 — it has to be able to block a request before the model ever
sees it, which means it runs with nothing in hand but the raw text of
the latest message. It has no product in context, no session state, no
idea that "es" in turn 2 refers to the battery-powered thermostat from
turn 1.

Verified this was really L2 and not L1 before changing anything: ran the
exact two-turn conversation through `InMemoryRunner`. Turn 2 produced
**zero tool calls** before the refusal text appeared — proof the turn
never reached the model at all, which only happens at L2.

Building product-awareness into L2 would mean either giving it access to
session state and a `power_type` lookup (a real logic change, out of
scope for this pass and arguably its own design decision — see "left for
later" below) or loosening the trigger patterns until they miss real
wiring questions. Both were explicitly out of bounds for this fix: *keep
failing safe, don't touch the logic.*

## The fix: make the refusal recoverable, not smarter

Nothing about *when* the guardrail fires changed. What changed is what
it says when it does. Both refusal strings now end with an explicit
invitation instead of just a dead-end apology:

> *(DE)* "...Viele unserer smarten Produkte lassen sich allerdings ganz
> ohne Elektroarbeiten montieren: batteriebetriebene Geräte und
> Zwischenstecker brauchen keinen Elektriker. Fragen Sie mich gern, ob
> das auf Ihr Wunschprodukt zutrifft — oder nach unserem
> Montageservice."

> *(EN)* "...Many of our smart products need no electrical work at all,
> though: battery-powered devices and plug-in adapters install without
> one. Ask me whether that applies to the product you're looking at, or
> about our installation service."

The customer's natural next question — *"ist das Homematic
batteriebetrieben?"* — contains no wiring-procedure language at all, so
L2 doesn't block it, and the agent answers it correctly straight from
the product's own `Betriebsart` field. The conversation recovers in one
turn instead of dead-ending mid-purchase.

This is guarded with a real test
(`test_wiring_refusal_invites_the_follow_up_question_that_resolves_it`),
not left as copy that could drift: it asserts both language variants
actually contain the recovery language (battery-powered/plug-in, and the
installation service). This is behavior the customer depends on to
escape the refusal, not decoration.

## A false positive, found and deliberately left alone

While checking the patterns: **`"Wie schließe ich es an die App an?"`** —
pairing a device with its app, nothing electrical — also matches, and
gets refused. `anschließen` / `schließe ... an` is a general-purpose
German verb (connect to the app, connect to the WiFi — not only connect
to the mains), and the pattern matches on the verb phrase alone, not on
what it's connecting *to*.

Not fixed. Fixing it would mean loosening the pattern — for example,
requiring an electrical-sounding object nearby — which trades this false
positive for a real risk of missing an actual wiring question phrased
slightly differently. Failing safe wins that trade every time; a
customer occasionally getting an unnecessary refusal is a much smaller
cost than a customer getting real electrical installation instructions
they shouldn't have. And this exact fix is what makes the false positive
survivable now: the customer gets redirected to "ist das Gerät
batteriebetrieben?" or "wie verbinde ich es mit der App?" instead of a
dead end — one extra turn instead of a wrong answer.

## What this does and doesn't fix

**Fixed:** the refusal is no longer a dead end. Whatever triggered L2 —
correctly or as a false positive — now hands the customer the exact
follow-up that resolves it in one more turn.

**Not fixed, and not in scope here:** L2 still refuses a battery-powered
product's wiring question exactly as it would a hardwired one's. That's
accepted deliberately — failing safe beats failing open. The natural
real fix is a context-aware L2 that reads the last-discussed product
from session state and checks its `power_type` before deciding whether
there's anything to refuse at all. That's a genuine logic change (more
state, more surface area to test) and was explicitly kept out of this
pass, which was scoped to text and documentation only.

## Result

- `guardrail.py`: two string constants changed, nothing else.
- `tests/test_guardrail.py`: 1 new test, 13 total, no existing test
  changed.
- 126/126 passing.
