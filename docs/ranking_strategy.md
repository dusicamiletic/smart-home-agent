# Why `search_products` stopped sorting by price

`smart_home_agent/tools/catalog_tools.py` — `_sort_key`, used by `search_products`.

## The problem

With no keywords given, results sorted by price ascending: cheapest
product first, always.

That's a bad default twice over.

**Cheapest is often not the best advice.** Real fixtures prove it: a TCL
aircon at 999 € has no known hub requirement. A Hue product at 21.98 €
and a Homematic product at 49.10 € both need one. Price-ascending put
both "you'll need to buy extra hardware" products ahead of the one that
just works — for no better reason than being cheaper.

**It works directly against the brief's own KPI.** The stated priority
is upselling — basket value, not minimum spend. Leading with the
cheapest option every time has no good answer to "why does your agent
recommend the cheapest thing first?" in an interview about an agent
built to upsell.

## The fix

Ranking only ever reorders what the gate already let through. The gate
— category/ecosystem intersection, price ceiling, keyword membership —
decides who's in the room, and that part didn't change at all. Only the
order survivors come back in did.

One sort key, used unconditionally, replacing what used to be two
separate `.sort()` calls (one for the keyword branch, one for the
no-keyword branch):

```python
def _sort_key(product: Product, keywords: list[str] | None) -> tuple:
    return (
        product.hub_required is True,               # works out of the box first
        -_lexical_score(product, keywords or []),   # then keyword relevance
        product.price is None,                      # priced before unpriced
        product.price or Decimal(0),                # price only as a tiebreak
    )
```

Products that don't need extra hardware outrank ones that do. Keyword
relevance breaks ties within that. Price is the *last* tiebreak, not the
first — it only ever decides between two products that are otherwise
equally good advice.

**`hub_required is True`, not truthy `hub_required` — deliberate.** The
field is tri-state (`True` / `False` / `None` for unknown), and `None`
must rank with `False`, never get demoted into the "needs a hub" group
just because the data doesn't say. This is the same "absence isn't a
negative" rule the confidence tiers enforce everywhere else in this
codebase (see `docs/decisions.md`, `docs/deterministic_field_scope.md`)
— applied here to ranking instead of to what gets stated as fact. A
product doesn't get pushed down the list just for having thinner data
than its neighbor.

## What was deliberately left out

A "richer attribute data ranks higher" term was tempting — a product
with more filled-in attrs is easier for the agent to describe well. Not
added, on purpose: it's a sparsity bias, the identical failure mode
already rejected once when the semantic/embedding lane was cut entirely.
Products with genuinely thin source data would systematically never
surface, for a reason that has nothing to do with whether they actually
fit the customer's request. Ranking should reward fitness, not
completeness of the underlying export.

## The invariant that matters most

Ranking must never quietly become a second gate. That's the one failure
mode worth guarding against structurally, not just by inspection:

```
test_ranking_never_changes_which_products_are_returned
```

Checked against the real 943-product catalogue, across five different
queries, comparing `search_products`' actual result *set* to an
independently computed gate (index intersection + price + keyword
membership) — a version with no sort involved at all. If some future
edit ever folds a filter condition into the sort key by mistake (the
easiest way to reintroduce exactly the bug class this guards against),
this test is what catches it, immediately, rather than as a silent
ranking regression discovered later.

## Result

- `tests/test_catalog_tools.py`: 5 new tests (hub-free beats hub-required
  when otherwise equal; `None` ranks with `False`, not `True`; keyword
  score breaks ties when hub status matches; price breaks ties last; the
  result-set invariant above), plus one existing test renamed and its
  expected order corrected for the new behavior.
- 113/113 tests passing.
