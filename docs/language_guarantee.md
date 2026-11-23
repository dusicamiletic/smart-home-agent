# How "reply in the customer's language" became an actual guarantee

The brief states this as an explicit requirement, not a nice-to-have:

> **Bilingual Support:** The assistant must support and respond in both
> English and German.

This document is the full path from "the instruction says so" to
"the code makes it true" — four real failures, found four different
ways, plus one structural gap caught by review before it became a
fifth. Each one moved the guarantee to a stronger foundation than the
last.

## Attempt 1: say it in the instruction (L1 only)

The first version of `prompts/instruction.md` said:

> Reply in the language of the customer's most recent message. Default
> to German.

Reasonable, and wrong to trust as a guarantee — a instruction is prose
competing with every other sentence in a 100+ line document for the
model's attention. `docs/decisions.md` had already named this exact
failure mode in a different context, days earlier:

> "a system instruction is a request to a probabilistic system; a
> callback is a control flow statement."

Language-matching was still sitting entirely in the "request" column.

## Failure 1: found by red-teaming, on refusal paths

Red-teaming the wiring/off-domain guardrails (`docs/red_team.md`) turned
up two cases where the *safety* decision was correct but the *language*
wasn't:

- An English wiring jailbreak, paraphrased to dodge the deterministic
  L2 patterns, got refused correctly — in German.
- An English off-domain request got the right decline-then-pivot shape
  — also in German.

Both go through L1, where the model composes its own text. The
hypothesis at the time: "Default to German" gets over-weighted the
moment the model enters a refusal path.

**First fix, instruction-only:** added an explicit line to the Language
section —

> This applies to refusals and deflections exactly as it does to normal
> answers. A refusal in the wrong language is a defect, not a safe
> default.

**Re-tested. Failed, unchanged.** Same English jailbreak, same German
refusal, word for word the same defect as before the edit. This was the
useful negative result: it proved the problem wasn't *missing prose*,
it was *prose as a mechanism*. Adding a more emphatic sentence to a
prompt doesn't change the fact that it's still a request.

## Fix, round 1: pattern-match known reply shapes at L4

Moved the decision into code instead: `after_model_guardrail` (L4, the
output scan) already reads the model's drafted reply. Added a language
check — compare the customer's message language against the reply's,
using the same word-overlap detector L2 already had — and when the two
disagreed, recognize the reply as one of our own fixed shapes and swap
in the correct-language version:

```python
_WIRING_REPLY_ANCHOR = re.compile(r"electrician|elektrofachkraft", re.IGNORECASE)
_DEFLECTION_REPLY_ANCHOR = re.compile(r"can'?t help|kann.{0,25}nicht helfen", re.IGNORECASE)
```

`"electrician"`/`"Elektrofachkraft"` never appears in a real product
answer — a safe, specific anchor. This closed both red-team cases,
verified against the exact captured strings, not paraphrases.

## Failure 2: found live, on an ordinary greeting

Then a real, live report: *"hey, can you help me?"* (English) came back
as a fully German greeting plus the ecosystem-clarifying question. Not a
refusal. Not a deflection. The single most common turn in the whole
system — the "ask once when the ecosystem is missing" opener every fresh
conversation goes through.

This mattered more than it looked: it proved the defect wasn't confined
to refusal paths at all, it was a general weakness on the model being
tested against (`gemini-3.5-flash-lite`, the free-tier fallback in use
while `gemini-3.6-flash`'s daily quota was exhausted — see
`docs/decisions.md`). The existing L4 check correctly detected the
mismatch and had nothing to do about it: neither anchor matched a
friendly greeting.

**Fix, round 2:** recognized a third safe-to-replace shape — the
ecosystem question itself, detected by requiring all four ecosystem
names together (a pattern the instruction structurally forces every
time it asks this question, so it's specific, not a guess):

```python
_ECOSYSTEM_NAMES = ("alexa", "google home", "apple home", "matter")

def _asks_about_ecosystem(text: str) -> bool:
    lowered = text.lower()
    return all(name in lowered for name in _ECOSYSTEM_NAMES)
```

Verified against the literal reported input/output pair. Fixed.

## The pattern behind the pattern

Three fixes in a row, each individually correct, each pointed at the
same structural ceiling: **pattern-matching known reply shapes doesn't
scale.** The wiring refusal, the deflection, the ecosystem question —
three known shapes, three anchors. The *next* shape a reviewer triggers
— "recommend me a smart plug," any real product answer with real prices
and product names — hits the fallback branch by construction, because
there is no fixed string to substitute for arbitrary correct content
without a translator. Chasing this bug one reply shape at a time would
never converge; it would just accumulate anchors forever.

## Fix, round 3 (the real one): move the decision upstream

Instead of correcting the *reply* after the fact, the language is now
decided *before the model ever drafts one* — in `before_model_guardrail`
(L2), on the pass-through path, after the wiring/off-domain patterns
have already declined to block:

```python
def _inject_language_directive(callback_context, llm_request, text: str) -> None:
    state = getattr(callback_context, "state", None)
    if state is None:
        state = {}

    detected = _confident_language(text)
    if detected is not None:
        state["user:language"] = detected
        lang = detected
    else:
        lang = state.get("user:language", "German")

    directive = (
        "\n\n## Language for this turn\n"
        f"The customer's current message is in {lang}. Reply in {lang}. This overrides any default."
    )
    llm_request.config.system_instruction = (llm_request.config.system_instruction or "") + directive
```

Verified directly against the installed ADK (2.6.2): `llm_request.config`
is always a real, non-`None` `GenerateContentConfig`, `system_instruction`
starts `None`, and appending in place before returning `None` is exactly
how a pass-through callback is meant to augment a request rather than
replace it.

**Why this is a different kind of fix, not just a bigger instruction
edit:** a general "default to German," stated once, competes with every
other sentence in the instruction for the model's attention across the
entire conversation. A directive re-stated fresh on *every single turn*,
scoped to *that turn only*, naming the *specific detected language*, is
a much narrower, much harder signal to out-weigh — still technically a
request to the model, but a minimal, single-purpose one instead of one
clause buried in a large document doing several other jobs at once.

### Ambiguous input doesn't get a fixed guess

`_confident_language` is deliberately stricter than the detector L2/L4
already used for picking *our own* reply's language:

```python
def _confident_language(text: str) -> str | None:
    de_score, en_score = _language_scores(text)
    if de_score > en_score:
        return "German"
    if en_score > de_score:
        return "English"
    return None
```

`"ok"`, a bare product id, or anything else with no real signal either
way returns `None` here — deliberately, so the directive can fall back
to `state["user:language"]`, the last *confidently* detected language
this session, rather than resetting to a fixed guess on every low-signal
turn. Defaults to German only when nothing has been confidently detected
yet this session at all — the one place a fixed default still exists,
and only as a true last resort.

### The instruction no longer competes with itself

`prompts/instruction.md`'s Language section no longer states a default:

> Reply in the language of the customer's most recent message. Use
> formal *Sie*.
>
> This applies to refusals and deflections exactly as it does to normal
> answers. A refusal in the wrong language is a defect.

"Default to German." is gone entirely, along with the "not a safe
default" phrasing from the round-1 fix — the per-turn directive is now
the actual mechanism, and a competing fixed default left sitting in the
instruction would work against it, not reinforce it.

### L4 stays on, explicitly as a backstop

The three pattern-based corrections at L4 (wiring refusal, deflection,
ecosystem question) were **not removed**. If the upstream directive is
ever ignored — it's still a request to the model, just a much narrower
one — these three known shapes still get corrected deterministically.
Cheap insurance, not redundant work.

## Failure 3: the ambiguous-input fallback was too eager

Round 3 shipped, and the very next live report found a fourth failure —
a different bug in the *new* mechanism, not a recurrence of the old one.
After a German turn, the customer switched to English with *"something
more interesting."* The reply came back German again.

Confirmed directly: `_confident_language("something more interesting")`
returned `None`. None of "something," "more," or "interesting" were in
the ~16-word hint lists, so it scored a 0-0 tie — and per the round-3
design, a tie means "no real signal, inherit whatever language the
conversation was last confidently in." That inherited language was
German, from the previous turn. **The fallback logic did exactly what
it was built to do** — the input was *mis-scored* as signal-free, when
it was actually an ordinary, unambiguous English sentence that simply
didn't happen to use one of a small curated set of words.

**Fixed two ways, both additive, neither touching the fallback logic
itself:**

```python
_EN_SUFFIX_SIGNAL = re.compile(r"\b\w+'(?:s|t|re|ll|ve|d)\b|\b\w+ing\b", re.IGNORECASE)

def _language_scores(text: str) -> tuple[int, int]:
    lowered = text.lower()
    words = set(re.findall(r"[a-zäöüß]+", lowered))
    de_score = len(words & _DE_HINT_WORDS)
    en_score = len(words & _EN_HINT_WORDS)
    if re.search(r"[äöüß]", lowered):
        de_score += 1
    if _EN_SUFFIX_SIGNAL.search(lowered):
        en_score += 1
    return de_score, en_score
```

1. **Expanded the word lists** with common conversational words
   ("something," "more," "interesting," "recommend," "yes" / "etwas,"
   "möchte," "gerne," "ist," ...) — the direct fix for the reported
   phrase.
2. **Added two cheap, high-precision fallback signals** for words not
   in either list: German umlauts/`ß` (near-exclusive to German) and
   English gerunds/contractions (near-exclusive to English), each worth
   at most one point — a tiebreak, never enough to overrule real
   word-list evidence pointing the other way. This is the more durable
   half of the fix: the curated list will always be incomplete (this bug
   is the proof), and these two signals catch a wide class of *future*
   thin-signal sentences no fixed list was ever going to fully enumerate.

Every existing test phrase was checked by hand against the expanded
lists and new signals before trusting the suite alone — no previously
confident classification flipped; several became more confidently
correct instead (e.g. "können" now also trips the umlaut signal).

One non-code lesson worth recording: if a defect appears to persist
after a fix ships, check whether the change actually reached a running
process first — a long-lived `adk web` server won't pick up edited
source until restarted. Not what happened here (this was a genuine new
bug, confirmed by reproducing it directly against the function), but
worth ruling out before assuming a fix failed.

## A structural gap, not a bug: explicit requests were still at the mercy of the detector

Flagged by review, not found by testing: *"can you answer in English?"*
is a stated preference, not something to infer from vocabulary. As
built after round 4, `_inject_language_directive` had two tiers — the
detector, then stored session state — so a direct request rode on the
same heuristic that had just failed twice. A message like *"Auf
Englisch bitte, ich möchte mehr Details."* is, by word count, mostly
German ("ich," "möchte" are strong German hints) — the detector alone
would confidently call the whole message German and silently ignore the
explicit ask embedded in it.

**Fixed by adding a third, higher-priority tier ahead of the
detector:**

```python
_EXPLICIT_ENGLISH_REQUEST = re.compile(r"\b(?:in|auf)\s+englisch\b|\bin\s+english\b|\bantworte\w*.*englisch\b", re.IGNORECASE)
_EXPLICIT_GERMAN_REQUEST = re.compile(r"\b(?:in|auf)\s+deutsch\b|\bin\s+german\b|\banswer\w*.*german\b", re.IGNORECASE)

def _explicit_language_request(text: str) -> str | None:
    if _EXPLICIT_ENGLISH_REQUEST.search(text):
        return "English"
    if _EXPLICIT_GERMAN_REQUEST.search(text):
        return "German"
    return None
```

```python
detected = _explicit_language_request(text) or _confident_language(text)
```

The same layering principle already used everywhere else in this
codebase — structured signal outranks heuristic, heuristic outranks
stored fallback:

```
explicit request  >  word/signal detector  >  last-confident session state  >  German (last resort)
```

Verified with the test that actually proves *priority*, not just
presence: a message the detector alone would confidently score German,
that also explicitly asks for English — must resolve to English. And
the mirror case, an English-scored message explicitly asking for
German. Both would have resolved to the wrong language one tier down;
both are exactly the tests added.

## What's actually guaranteed now, and what isn't

**Guaranteed, by code, independent of model behavior:**
- The three known reply shapes (wiring refusal, off-domain deflection,
  ecosystem question) are always corrected to the customer's language if
  they're ever drafted in the wrong one — L4, deterministic pattern
  match, no model call involved in the correction.

**Strongly reinforced, per-turn, but still technically a request:**
- Every other reply's language — the upstream L2 directive, re-injected
  fresh on every turn, naming the specific detected (or inherited)
  language. This is what closed the general case (an ordinary product
  answer in the wrong language) that L4 could never safely fix on its
  own. Three deterministic tiers decide what that language *is*, each
  one only consulted if the tier above found nothing: an explicit
  request the customer stated outright, then the word/signal detector,
  then the last language the conversation was confidently in.

**Not fully guaranteed, and not claimed to be:**
- If a model ignores the per-turn directive on a reply that isn't one of
  the three known L4 shapes, there's no deterministic backstop for it —
  no general translator exists to safely rewrite arbitrary content. This
  is the honest remaining edge, not smoothed over.
- The language *detector* itself (`_language_scores`) is a curated word
  list plus two suffix/character signals, not a real language
  classifier. Round 3's own bug is the proof it can still mis-score a
  perfectly ordinary sentence with thin vocabulary overlap. Each real
  failure found this way gets fixed additively (more words, more
  signals) rather than assumed complete — 33% coverage on `hub_required`
  taught the same lesson earlier in this project: a curated list is a
  floor, not a ceiling, and the honest claim is "handles what's been
  found so far," not "solved."

## The honest long-term fix: stop hand-rolling a detector

Five rounds in, the pattern is worth naming plainly: every failure so
far (rounds 3, 4, and the explicit-request gap) has been a symptom of
the same root cause — `_language_scores` is a hand-rolled keyword
detector, and keyword detectors are exactly the kind of thing that keeps
needing one more word, one more signal, one more round. That's not a
criticism of the fixes themselves (each one was real, verified, and
closed a real defect) — it's a diagnosis of the tool, not the effort:
**this is a solved problem with mature, purpose-built libraries, and a
hand-rolled heuristic was never going to be the last word on it.**

The fix that actually ends the pattern, rather than extending it again,
is a real language-identification library — `lingua-py` is built
specifically for accuracy on short text, which is precisely the hard
case here ("ok", "something more interesting"); fastText's language
model is the other standard option. This is a planned follow-up, not
implemented in this pass — **the user is taking this on directly.**

**Why this is easy, structurally:** language detection already lives in
exactly one place. Every caller — the per-turn directive, the L4
mismatch check — goes through `_confident_language`, which is the only
seam that needs to change:

```python
from lingua import Language, LanguageDetectorBuilder

_detector = (LanguageDetectorBuilder
             .from_languages(Language.GERMAN, Language.ENGLISH)
             .with_minimum_relative_distance(0.9)   # abstain when unsure
             .build())

def _confident_language(text: str) -> str | None:
    result = _detector.detect_language_of(text)
    if result is None:
        return None                      # ambiguous → caller falls back to state
    return "German" if result == Language.GERMAN else "English"
```

One dependency, roughly ten lines, and the entire hint-word apparatus
(`_DE_HINT_WORDS`, `_EN_HINT_WORDS`, `_language_scores`, the umlaut and
`-ing`/contraction signals) disappears — no more word lists to expand,
no more one-off signals, no fourth (or sixth) failure to log.
Constraining the detector to exactly the two languages this system
supports is what makes it strong on short text; `with_minimum_relative_distance`
is what makes it *abstain* rather than guess on something like "ok" —
which matters, because the session-state fallback it hands off to is
genuinely better than a coin flip there. `_looks_german` (used only for
picking *our own* reply's language once we already know we're answering
with a fixed string) stays exactly as-is; it was never the problem.

`_explicit_language_request` also stays exactly as-is and keeps its
priority ahead of the detector — a stated preference should outrank a
classifier just as much as it outranks a heuristic; swapping the
detector's accuracy doesn't reduce the value of asking directly.

**The regression suite already exists.** Every phrase collected across
all five rounds of this document — "something more interesting", "ok",
"Auf Englisch bitte, ich möchte mehr Details.", every red-team case —
is already a test in `tests/test_guardrail.py`. That whole suite becomes
the acceptance test for the classifier swap: same inputs, same expected
outputs, different mechanism underneath.

**The deeper product point, beyond the library swap:** in a real
deployment, language shouldn't be inferred from message text at all when
better signal exists — a UI toggle, a stored account preference, the
browser's `Accept-Language` header. Detection is what you fall back to
when none of those are available, not the primary mechanism. Guessing
from a two-word message is solving a problem a real product would design
away entirely. Worth stating in "what I'd do next," not just the library
choice: *"replace the heuristic language detector with a trained
classifier such as lingua-py; in production, take the language from an
explicit user preference rather than inferring it at all."*

## Verification

Every stage of this was checked against something real, not assumed:

- Round 1's instruction-only fix was **re-tested and shown to fail**,
  not just theorized about — the actual reason the fix moved to code.
- Round 1 and round 2's L4 corrections were verified against the
  **exact captured strings** from the red team and the live bug report,
  not hand-written approximations.
- Round 3's upstream directive was verified two ways: unit tests
  (`tests/test_guardrail.py` — English/German injection, appends rather
  than replaces an existing system instruction, a blocked message never
  reaches the injection, ambiguous input inherits the stored language),
  and a live run on `gemini-3.5-flash-lite` with the exact greeting that
  previously failed plus a real product question — both returned fully
  in English, full tool-calling flow included, with no L4 intervention
  needed on either.
- Round 4's word-list/signal fix was checked against the **exact
  two-turn scenario reported live** (a German turn, then the real
  English phrase that failed) as a permanent regression test, not a
  paraphrase — and every previously-passing test phrase was re-checked
  by hand for an unintended classification flip before trusting the
  suite alone.
- The explicit-request priority fix was verified with the test that
  actually proves *ordering*, not just presence: a message the detector
  alone would confidently score one language, that also explicitly
  requests the other — and its mirror. A weaker test (an explicit
  request in an otherwise-neutral message) wouldn't have distinguished
  "priority works" from "the detector happened to agree."

141/141 tests passing at the point this was closed.
