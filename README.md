# Smart Home Agent

A bilingual (DE/EN) shopping assistant for a German DIY retailer's
smart-home catalogue (943 real products). Built with Google's [ADK](https://google.github.io/adk-docs/).

It does four things, per the brief:

1. **Recommends products**, with an explicit compatibility check against
   the customer's stated ecosystem (Alexa / Google Home / Apple Home /
   Matter) — including when a product needs extra hardware to work.
2. **Compares products**, with category-aware spec rows and gaps shown
   as `unknown` rather than dropped.
3. **Answers in German or English**, matching the customer's own
   language, defaulting to German.
4. **Upsells** — required hardware, then a better-fitting variant, then
   a compatible companion — one offer per turn, always inside the
   compatible set. This is the project's named KPI, not an
   afterthought.

Plus two guardrails: it refuses electrical wiring/installation
instructions, and it deflects questions outside the smart-home domain.

## Requirements, and how each is satisfied

### Core functionality

**Product Recommendation, with an explicit compatibility check.**
`search_catalog` finds candidates matching what the customer asked for
(category, price, keywords). `check_compatibility` is then called on
the specific product and ecosystem the customer named, and returns one
of four explicit states — `direct`, `needs_hardware`, `incompatible`,
`unknown` — read straight from the product's own declared data, never
inferred. `prompts/instruction.md` enforces the order: the agent cannot
recommend anything until it knows the customer's ecosystem (Alexa /
Google Home / Apple Home / Matter), asking once if it doesn't. If a
thermostat needs a hub to work with Alexa, the agent says so by name,
with its price — not a bare "yes, compatible."

**Product Comparison.**
`compare_products` builds a side-by-side table across two or more
products, with spec rows chosen by category (a thermostat and a smart
plug are compared on different attributes). A field missing from either
product renders as `unknown` rather than being silently dropped, so a
real data gap stays visible instead of a table that quietly looks
complete.

**Bilingual Support (German/English).**
Enforced twice. `guardrail.py` detects the customer's language on every
turn and injects a per-turn "reply in [language]" directive into the
model's own instructions *before* it drafts a reply; a second pass
*after* the reply is drafted checks known reply shapes (refusals,
deflections) for the wrong language and corrects them. `instruction.md`
states the same rule directly — reply in the customer's language, using
formal *Sie* in German — and the assistant defaults to German only when
no language signal exists yet.

**Upselling (the brief's named business KPI).**
`suggest_upsell` is a dedicated tool, not something assembled from
search results. It tries three offer types in a fixed priority —
required hardware first (the product genuinely doesn't work without
it), then a better-fitting variant (grounded in something the customer
actually said, e.g. room size), then a compatible companion product —
and returns at most one. `instruction.md`'s Offers section requires that
only what this tool returns gets offered, never invented, at most once
per turn. Search ranking itself was tuned for the same KPI: products
that work without extra hardware rank ahead of cheaper ones that need a
hub, since price-first ranking actively worked against basket value.

### Guardrails

**Safety: refusing wiring/installation advice.**
Enforced in three independent layers, so no single check has to hold on
its own: the system instruction states the rule; a deterministic pattern
check runs *before* the model is even called, directly on the
customer's message, and can end the turn immediately with a fixed
refusal (`before_model_guardrail`); a second pattern check scans the
model's own drafted reply afterwards for wiring content that slipped
through anyway (`after_model_guardrail`). The line the agent holds:
*"does this need a neutral wire?"* is a normal product question and
gets answered; *"which wire goes where?"* is a procedural request and is
always refused, regardless of phrasing or who the customer claims to be.

**Domain restriction: deflecting off-topic questions.**
The same before-and-after defense as the wiring guardrail, with a
separate, deliberately narrow set of patterns for unmistakably
off-topic requests (weather, poems, jokes, homework, legal/medical
advice). Exactly where the in-scope line sits is drawn out explicitly in
["The domain boundary, as a decision"](#the-domain-boundary-as-a-decision)
below, rather than left implicit.

## Setup

### Option A: Docker (no local Python needed)

```bash
cp .env.example .env
# edit .env, set GOOGLE_API_KEY

docker compose up --build
```

Starts both interfaces at once, same agent, same catalogue:

- **http://localhost:8501** — Streamlit chat, the polished front-end.
- **http://localhost:8000** — `adk web`, the ADK dev UI (pick
  `smart_home_agent` from the dropdown). Slower to read, but shows every
  tool call and its raw arguments/return value, which is worth having open
  side-by-side with Streamlit while reviewing.

The only manual step is the API key — everything else (venv, dependencies,
the pre-built catalogue) is already handled by the image. `Ctrl+C` to stop,
`docker compose down` to remove the containers.

### Option B: Local Python

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env, set GOOGLE_API_KEY
```

Build the catalogue once (writes `build/catalog.json` and
`build/build_report.md` from the 943 raw records in `data/products/`):

```bash
python3 scripts/build_catalog.py
```

`build/` is committed, so this step isn't required to run the agent —
only if `data/products/` changes.

## Running it (Option B — local Python)

Skip this section if you're running via Docker (Option A above); `docker
compose up` already starts both interfaces.

Streamlit, the polished front-end:

```bash
streamlit run streamlit_app.py
```

Opens http://localhost:8501 automatically. It talks to `root_agent`
in-process through ADK's own `Runner` — no separate server to start first.

`adk web`, the ADK dev UI (shows every tool call and its raw
arguments/return value — useful for reviewing, not needed to use the
assistant):

**`adk web` must be run from this directory** (`smart-home-agent/`, the
parent of the `smart_home_agent` package) — not from one level above
it. This isn't a style preference: launched from the wrong directory,
`adk web`'s own agent-discovery joins this folder's name onto the
package name (`smart-home-agent.smart_home_agent`), and the hyphen in
that string is not a valid identifier — the app *shows up* in the
dropdown but every message to it 422s the moment you send one.

```bash
cd smart-home-agent      # this directory
adk web
```

Open the printed URL, pick `smart_home_agent` from the dropdown.

Run the test suite (161 tests, no API key needed — everything below the
agent wiring is pure Python against real fixtures and the real 943-product
catalogue):

```bash
pytest
```

## Architecture

The system is built in three layers, plus two interfaces on top.

```
data/products/*.json  →  build_catalog.py  →  build/catalog.json
  (943 raw records)        (run once, offline)   (typed, cleaned, committed)
                                                        │
                                                        ▼
                                    tools/ (search, compatibility,
                                            comparison, upsell)
                                                        │
                                                        ▼
                                   agent.py  →  root_agent + guardrail.py
                                                        │
                                        ┌───────────────┴───────────────┐
                                        ▼                               ▼
                                streamlit_app.py                   adk web
```

1. **Data pipeline (offline, run once).** `scripts/build_catalog.py`
   reads the 943 raw product files, extracts and cleans up their
   attributes (which ecosystems they support, price, whether they need
   a hub, etc.), and writes the result to `build/catalog.json` — a
   single, typed file that's committed to the repo. The agent never
   parses raw product text at runtime; it just loads this file.

2. **Tools (plain Python, no AI).** `smart_home_agent/tools/` has one
   function per capability — `search_products`, `check_compatibility`,
   `compare_products`, `suggest_upsell` — each independently tested,
   each unaware that an LLM or ADK exists.

3. **The agent (`smart_home_agent/agent.py`).** Loads the catalog once
   at startup, wraps each tool so Gemini can call it, and combines them
   into one ADK agent (`root_agent`) guided by a single system prompt
   (`prompts/instruction.md`). `guardrail.py` runs two safety checks
   before and after every model call: refusing wiring/installation
   advice, and declining questions outside the smart-home domain.

Both interfaces — the Streamlit chat UI (`streamlit_app.py`) and `adk
web` (ADK's own developer UI) — talk to the same `root_agent`, so the
assistant behaves identically no matter which one you open.

## Key design decisions

Summary of the decisions that shape the system — each one links to a
deeper write-up with the full reasoning:

- **Confidence tiers, not extraction perfection.** Every derived fact
  (`hub_required`, `is_smart`, `power_type`, ecosystem tags) carries
  `declared` / `inferred` / `unknown`. Heuristics are allowed to be
  imperfect because the tier — not the heuristic — is what stops a guess
  from being stated as settled fact. See `docs/deterministic_field_scope.md`.
- **Single agent, not coordinator + sub-agents.** Recommendation and
  comparison share every piece of business logic; a routing layer would
  buy presentation polish at the cost of a new failure mode, on a
  compressed timeline. The tool layer doesn't change either way, so this
  is reversible.
- **No embeddings, no semantic search lane, ever** — a permanent cut,
  not a deferral. Retrieval is index intersection (a guarantee) plus
  lexical keyword scoring (a ranking signal only). Two direct
  consequences of this cut, both handled explicitly rather than left as
  gaps: `search_catalog`'s `emptied_by` diagnostic
  (`docs/emptied_by_strategy.md`) tells the customer which constraint to
  loosen when a query returns nothing, since there's no fuzzy fallback
  to paper over it; and ranking (`docs/ranking_strategy.md`) puts
  products that work without extra hardware ahead of cheaper ones that
  need a hub, because price-first ranking actively worked against the
  upselling KPI.
- **Upselling is three answers to three different questions**, tried in
  a fixed priority order (required hardware, then a better-fitting
  variant, then a compatible companion), never ranked by price or
  margin. See `docs/upsell_strategy.md`.
- **The interface owns presentation, the model owns facts.** Product
  images are matched and rendered by `streamlit_app.py` from the turn's
  actual tool results, never embedded by the model itself — three rounds
  to get there, including a version that technically worked but rendered
  far too large. Every named product is a link by default, since a
  customer needing to ask twice for it works against the same upselling
  KPI above. See `docs/interface_strategy.md`.
- **Guardrail: four layers named, three built.** L1 (instruction prose),
  L2 (deterministic regex, before any tool call), L4 (output scan on the
  model's own drafted reply). **L3 — a cheap LLM judge for the
  ambiguous middle L2's regex can't classify — is deliberately cut**
  for this build. That's a real, acknowledged gap: anything not caught
  by L2's clear patterns relies on L1 alone, which is a soft default,
  not a guarantee. See `docs/wiring_refusal_recovery.md` for a real case
  this gap produced (a battery-powered product's wiring question,
  correctly refused by L2 for the wrong reason, fixed by making the
  refusal text recoverable rather than by loosening the pattern).

## The domain boundary, as a decision

The brief asks for the assistant to "deflect questions unrelated to the
smart home domain" without saying where that line sits. Rather than
leaving it implicit, it's drawn here explicitly:

**In scope:** connected products in this catalogue — lighting, heating,
cameras, sensors, alarms, locks, switches, sockets, shading, hubs,
garden equipment, EV charging — plus whether a specific product in that
set is compatible with the customer's ecosystem, and its price,
specifications, and installation *requirements* (not instructions).

**Out of scope:** anything else, including general smart-home advice
not tied to a product in this catalogue, and — deliberately — the
retailer's non-connected inventory. If a customer asks about a plain
(non-smart) version of something the shop also sells, the agent may say
so, but doesn't recommend it; recommending non-connected products isn't
what this assistant is for, even where the shop stocks them.

**Why draw it there:** a narrower boundary is easier to guarantee (L2's
deterministic patterns only need to cover a short, real deny-list, not
general topic classification), and a shopping assistant that confidently
opines outside its own catalogue is a worse outcome than one that says
"I can't help with that" and returns to what it can.

## Known limitations

Stated plainly, not smoothed over — each of these is a deliberate,
logged trade-off, not an oversight:

- **`hub_required` is a floor, not a ceiling.** 307/943 products are
  currently flagged `True`; the true number is almost certainly higher,
  since detection only fires on a curated set of hardware nouns inside
  free text. Confidence tiering means the gap fails safe (`unknown`),
  not silently wrong.
- **SmartThings isn't a supported ecosystem**, on purpose. Nothing in
  the source data's structured fields distinguishes it from the rest of
  a free-text "supported systems" list, so claiming to check it would be
  a check the data can't back up. Alexa, Google Home, Apple Home and
  Matter are.
- **L3 (the ambiguous-middle judge) is cut.** See above.
- **One domain-boundary behavior is L1-only and unverified on the shipped
  model.** Red team (`docs/red_team.md`, 10/10 cases) confirms the agent
  declines before pivoting to a product suggestion on off-domain
  requests — but that specific behavior was only measured on
  `gemini-3.5-flash-lite`, not the shipped `gemini-3.6-flash`, because of
  the quota limit below. (A related language-consistency defect found by
  the same red team is now closed at the source — a per-turn language
  directive injected into every request in `before_model_guardrail`,
  with the L4 pattern checks kept on as a backstop — so it holds
  regardless of model.)
- **Free-tier API quota is tight and model-dependent.** `gemini-3.6-flash`
  is capped at 20 requests/day on the free tier — enough to hit mid-way
  through a normal test session, not just a red-team run. If you see a
  `429 RESOURCE_EXHAUSTED` error, set `GEMINI_MODEL=gemini-3.5-flash-lite`
  in `.env` (a higher free-tier allowance) and re-run; no code change
  needed.

## Project layout

```
smart-home-agent/
├── README.md                  ← this file
├── Dockerfile
├── docker-compose.yml            starts both interfaces (8000 + 8501)
├── streamlit_app.py               chat front-end, same root_agent
├── streamlit_helpers.py           pure presentation logic, unit-tested
├── requirements.txt
├── .env.example
├── data/products/              943 raw product JSON files
├── build/
│   ├── catalog.json             943 normalized products (committed)
│   └── build_report.md          coverage + failures + staleness hash
├── scripts/
│   └── build_catalog.py         Stage 0-5 pipeline, run once offline
├── smart_home_agent/
│   ├── agent.py                  root_agent ← adk web / Streamlit entry point
│   ├── guardrail.py               L2/L4 callbacks
│   ├── prompts/instruction.md     L1, the agent's system instruction
│   ├── catalog/                   loader, models, normalize, index, resolve
│   └── tools/                     search, compatibility, comparison, upsell
├── tests/                        161 tests, real fixtures + full catalogue
└── docs/
    ├── deterministic_field_scope.md
    ├── upsell_strategy.md
    ├── emptied_by_strategy.md
    ├── ranking_strategy.md
    ├── interface_strategy.md      why the two UIs are built the way they are
    └── wiring_refusal_recovery.md
```
