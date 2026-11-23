# Why `emptied_by` exists, and why it's leave-one-out, not fixed-order

`_emptied_by` (`smart_home_agent/agent.py`, used by the `search_catalog`
tool) exists so the agent can say something useful when a search returns
nothing.

Without it: *"Ich habe leider nichts gefunden."* Dead end.

With it: *"Unter 40 € gibt es nichts mit Alexa — soll ich bis 60 €
schauen?"* The conversation continues.

To say that second sentence, the agent has to know *which constraint
killed the search*. That's what `emptied_by` reports back alongside an
empty `results` list.

## Why this tool needed to exist at all

This matters more here than it would for most builds, precisely because
the plan cut the semantic/embedding lane permanently (see
`docs/decisions.md`). Structured filters plus lexical keyword ranking is
the whole retrieval story — no fuzzy fallback softens a query that's a
little too specific. That makes empty results a **routine outcome, not
an edge case**. `emptied_by` is the fallback that covers that gap; without
it, the "no semantic lane" decision would leak a dead end straight to the
customer every time a query was slightly over-constrained.

## What was broken: the first version

The first version applied filters back one at a time in a fixed,
hardcoded order — category, then ecosystem, then price, then keywords —
and blamed whichever addition first made the running set empty.

The bug: **the blame depended on the order the code happened to check
filters in, not on anything true about the query.**

Take a real query: `category=kabelverbinder` (a real category with
exactly one product) plus `ecosystem=MATTER`.

- Filter category first: 943 → 1 → then Matter → 0. **Blames ecosystem.**
- Filter ecosystem first: 943 → many → then category → 0. **Blames category.**

Same query, opposite answer, and neither is more true than the other —
the code's own processing order was doing the reasoning, not the data.

Worse, this design couldn't handle a case where dropping any *single*
filter still leaves the result empty, but dropping *two together* would
fix it. It would just report whichever filter happened to zero the
cumulative set first and stop there — never checking whether that
diagnosis, on its own, actually restores anything at all once the rest
of the filters are put back.

## What it does now: leave-one-out, then leave-two-out

`_emptied_by` asks a better question for every filter the customer
actually gave: **if I dropped just this one filter and kept every other
one exactly as given, would the search return anything?**

For the query above, both single removals work — drop the category and
the six Matter products come back; drop the ecosystem and the one cable
connector comes back. Since one removal is enough on its own, it reports
one name (`"category"`, chosen deterministically when more than one
single fix exists). It does not manufacture a pair just because two
filters happened to be active — see
`test_emptied_by_picks_a_single_filter_when_dropping_either_one_alone_would_have_worked`
in `tests/test_agent.py`.

Now add `max_price=5` to the same two filters. Every single removal
still returns nothing: Matter products under €5 — empty (cheapest is
11.70 €). Cable connectors under €5 — empty (the one product is 6.95 €).
Cable connectors that are also Matter — empty (that's the original,
unrelated problem). No single drop explains it, so the function
escalates to pairs: dropping category **and** ecosystem together, leaving
just the €5 cap on its own, returns real (unrelated, cheap) products.
Reported as `"category and ecosystem"` — see
`test_emptied_by_reports_the_pair_when_no_single_filter_alone_would_have_emptied_it`.

```python
def _emptied_by(filters: dict) -> str | None:
    active = {name: value for name, value in filters.items() if value}
    if len(active) <= 1:
        return next(iter(active), None)

    for drop_size in range(1, len(active)):
        for drop in combinations(sorted(active), drop_size):
            remaining = {name: value for name, value in active.items() if name not in drop}
            count = len(catalog_tools.search_products(
                catalog=CATALOG, by_category=BY_CATEGORY, by_ecosystem=BY_ECOSYSTEM, **remaining
            ))
            if count > 0:
                return " and ".join(sorted(drop))

    return " and ".join(sorted(active))  # every proper subset is independently empty too
```

Every check is a **real call to the public `search_products`** — the
same function `search_catalog` already calls for the real query — never
a second, hand-written copy of its filter logic that could silently
drift out of sync with it. `search_catalog` only calls `_emptied_by` at
all once the real, full-filter search has already come back empty, so
the common (non-empty) case pays nothing extra.

## Why this was worth getting right

The agent's suggestion has to actually work. If it says *"soll ich bis
60 € schauen?"* and raising the budget still returns nothing, the
customer loses confidence immediately — and it's a self-inflicted wound,
because the agent volunteered that specific suggestion. Leave-one-out
guarantees whatever it proposes will succeed, because the tool already
tested it before saying it, rather than guessing from processing order
and hoping.

**Cost:** a handful of extra set intersections over an in-memory,
943-product catalogue, and only on the empty-result path. Effectively
free.

## Left for later, not now

When several single removals would each work on their own, the function
currently picks one alphabetically — arbitrary among equally-valid
options. The better rule: prefer suggesting the *soft* constraint over
the *hard* one. "Under €5" is usually negotiable; "cable connectors" is
what the customer actually came in for. Relaxing price is a better offer
than relaxing intent, since it doesn't ask the customer to reconsider
what they wanted, only what they're willing to pay.

This needs a notion of which filters are "soft" (price, maybe keywords)
versus "hard" (category, ecosystem — things the customer stated as an
identity, not a preference) that the function doesn't have today.
Low priority — noted here so the reasoning isn't lost, not because it's
broken as it stands.
