# Interface strategy: two surfaces, one agent, no duplicated logic

Every decision below is about presentation only. None of them touch
`smart_home_agent/tools/`, none of them touch the guardrail, none of them
change what the agent is allowed to say -- they change how what it
already says gets shown. That boundary was kept on purpose: the brief
grades the agent's behavior (compatibility checks, comparisons,
bilingual replies, upselling, refusals), and an interface bug should
never be able to look like an agent bug, or vice versa.

## Why two interfaces, not one

The brief asks for "a minimal interface via `adk web` or Streamlit" --
either alone would satisfy it. Both are shipped because they answer
different questions for different readers, and shipping both costs
almost nothing once one Docker image exists:

| | `adk web` | Streamlit |
|---|---|---|
| Audience | reviewer checking *how* it works | customer / demo audience |
| Shows | every tool call, raw arguments, raw return value | the conversation only |
| Built by | ADK itself, zero code | `streamlit_app.py`, ~140 lines |
| Good for | "did `check_compatibility` actually get called, and with what?" | "does this feel like a shopping assistant?" |

`docker-compose.yml` runs both as separate services from the same build
context (`smart-home-agent` on :8000, `streamlit` on :8501). Docker's
build cache means the second service costs seconds, not minutes, once
the first has built -- verified directly, not assumed: the second
`docker compose build` in this session's own history finished its
`pip install` and `COPY` layers as cache hits.

## Why Streamlit talks to `root_agent` directly, not through `adk web`'s API

`streamlit_app.py` imports `root_agent` and drives it with ADK's own
`Runner` + `InMemorySessionService`, in-process:

```python
runner = Runner(app_name=APP_NAME, agent=root_agent, session_service=session_service)
...
async for event in runner.run_async(user_id=USER_ID, session_id=..., new_message=message):
    ...
```

The alternative -- have Streamlit be an HTTP client hitting `adk web`'s
own `/run` endpoint -- would mean running a second server as a hidden
dependency of the first, plus a network hop, in exchange for nothing:
`Runner` is ADK's own supported way to drive an agent from plain Python,
built for exactly this. It also keeps a rule this project already
applies to the agent itself (one agent, not coordinator + sub-agents;
`docs/decisions.md`, 2026-08-05) consistent at the interface layer too:
don't add a second moving part when the one that exists already does the
job.

The payoff isn't just less code. Both interfaces run the *same* tool
layer, the *same* `before_model`/`after_model` guardrail, the *same*
`instruction.md` -- there is no "Streamlit build" of the agent's behavior
that could quietly drift from the "`adk web` build." A guardrail fix or
an instruction edit is live on both ports the moment the container
restarts, because there was only ever one `root_agent` to restart.

## Why the sidebar shows "what I've noted about you"

`remember_customer` already writes `user:ecosystem`, `user:budget`,
`user:rooms`, `user:owned_devices` into session state -- that state
existed before Streamlit did, built for the agent's own turn-to-turn
memory. The sidebar just reads it back and displays it:

```python
noted = {key.removeprefix("user:"): value for key, value in session.state.items() if key.startswith("user:")}
```

No new backend concept, no new field, no risk of the display drifting
from what the agent actually stored -- it's the same dictionary,
inspected, not a parallel copy kept in sync by hand. It exists because a
reviewer (or a customer) has no other way to tell that "I use Alexa" from
three turns ago is still being honored, short of asking again and hoping
the answer doesn't repeat the question.

The "New conversation" button clears `st.session_state` and lets a fresh
`session_id` get created on rerun -- the only way to start over cleanly
against `InMemorySessionService`, which has no other reset short of
restarting the process.

## Why product images are not embedded by the model

This took three rounds to get right, and the wrong turns are worth
keeping, not just the answer (full detail in `docs/decisions.md`,
2026-08-10 entries):

1. **First working version:** the model embedded `![title](image_url)`
   directly in its reply text. This worked, in the sense that a real
   image showed up. It was also wrong: Streamlit renders markdown images
   at native size inline in the chat flow, so a reply naming three
   products became three full-size product photos stacked in a column,
   forcing a scroll to see results a shopping assistant should surface
   immediately.

2. **The fix:** ownership of image *presentation* moved from the model to
   the interface. The model's job shrank back down to what it's actually
   good at -- naming the right products and linking to them
   (`[title](url)`) -- and stopped being asked to also make a UI layout
   decision (image size, placement) it has no way to get right
   consistently, because markdown gives it exactly one size: native.

   `streamlit_app.py` recovers the images itself, after the model has
   already answered, using the pure helpers in `streamlit_helpers.py`:

   ```python
   catalog = {}  # url -> product dict, built while walking this turn's events
   for part in event.content.parts:
       if part.function_response:
           catalog.update(find_products(part.function_response.response))

   products = products_in_reply(reply, catalog)  # only products the reply actually links to
   ```

   `find_products` recursively scans whatever JSON a tool actually
   returned this turn for anything shaped like a product (`url` +
   `image_url` present); `products_in_reply` then keeps only the ones
   whose `url` the model's own final text links to, in the order named.
   That second filter matters: `search_catalog` routinely returns more
   candidates than the model chooses to mention (ranking, the
   3-vs-20 browse/recommend split in `instruction.md`) -- thumbnailing
   every candidate the tools *saw*, instead of every product the
   customer was actually *told about*, would show images with no
   matching text next to them.

3. **What this bought for free:** each match renders inside `st.image`,
   whose own built-in toolbar gives "click the corner to expand
   fullscreen, drag to pan, scroll to zoom, then exit" without any of it
   being built here. Switching *how* images render (from inline markdown
   to a real Streamlit element) bought the correct UX as a side effect of
   fixing the sizing bug, not as separate work.

4. **Round 4, user-driven: compact stacked rows, not a row of columns.**
   The first `st.image` version rendered every matched product as its own
   column in one horizontal row -- fine at 3 products, unreadable at 20.
   Compared three real layouts (built with actual catalogue photos and
   prices, not placeholders) via the brainstorming visual companion: a
   card grid, a numbered thumbnail strip, and stacked rows. Rows won,
   decisively -- the other two either buried `hub_required` in a
   footnote (the grid) or asked the customer to match numbers between a
   thumbnail strip and separate text (the strip), both actively working
   against the point of showing hardware requirements at all. In the
   chosen layout, thumbnail and text share one row, so there's no
   separate "which image is which" step; a colored badge
   (`:orange[⚠ needs {name}]`) renders only when there's an actual
   warning, never a green "confirmed fine" and never a gray "not
   stated" -- an absent badge in a list of twenty is not read as a
   guarantee either way, so there's no badge for anything but the one
   positive fact worth flagging; and when hardware is required, it gets
   its own indented sub-row -- its own thumbnail, its own link, its own
   price, not just a name inside the badge text. See `docs/decisions.md`,
   2026-08-10, "Compact stacked rows" for the layout choice and the real
   bracket-matching bug it surfaced, and "Hub badge: absence is not a
   claim" for why the badge dropped its green/gray states and why a hub
   (checked independently, via category group and title, not trusted
   from `hub_required` alone) never warns about needing itself.

## Why every named product is a link, by default, not on request

A user asked, reasonably: shouldn't the customer get the product link
without having to ask for it separately? Yes -- and this is the one
interface decision that's also a business decision. The brief's named
KPI is upselling; a shopping assistant that makes the customer ask twice
for the thing that gets them to checkout is working against its own
stated goal. `instruction.md`'s Style section now requires it
unconditionally: `[title](url)`, using only a `url` a tool actually
returned, never a bare title, no exception carved out for compatibility
mentions or upsell offers (both of those needed a matching data fix --
`docs/decisions.md`, "`required_products` and upsell offers couldn't be
linked or thumbnailed either" -- since their tool contracts didn't carry
a `url` at all until this was traced through).

## What's deliberately *not* here

- **How many products to show, and how many offers to make** is an agent
  *response-shape* decision, not an interface one -- it lives entirely in
  `instruction.md` and `agent.py`'s `search_catalog` clamp, with no
  Streamlit-specific code at all. See `docs/decisions.md`, "Two limits
  were being conflated," for that reasoning; it's cross-referenced here
  because it does affect what a customer sees, but the decision itself
  has nothing to do with either UI.
- **A `compare_products` thumbnail row.** `compare_products`'s return
  shape (`product_ids`, spec `rows`, `notes`) never carried `url` or
  `image_url` for the compared products, and extending it wasn't part of
  what any of these rounds actually needed to fix -- worth flagging as a
  real, current gap rather than a decision, since a comparison reply
  currently gets no thumbnails at all, unlike a recommendation reply.
