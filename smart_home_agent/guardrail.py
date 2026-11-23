"""Guardrail plugin (plan §05): wiring/installation refusal and
off-domain deflection, enforced twice -- before the model runs (L2) and
after it drafts a reply (L4) -- because "a system instruction is a
request to a probabilistic system; a callback is a control flow
statement" (docs/decisions.md, 2026-08-05). L1 is `prompts/instruction.md`'s
own prose. L3 -- a cheap LLM judge for the ambiguous middle L2's regex
can't classify -- is deliberately cut for this build: a real gap, left
to L1 alone, not a silently-dropped requirement (see docs/decisions.md).

L2 and L4 are deliberately blunt and product-agnostic: they see only raw
text -- the latest customer message, or the model's own drafted reply --
never a resolved product or its `Installationshinweis`. The richer
refusal `instruction.md` describes (quote the product's own installation
note, then offer the install service and a no-wiring alternative) is the
model's job, produced with real tool results in hand, for whatever
reaches it. L2/L4 exist to guarantee a safe floor when L1 doesn't hold,
not to reproduce that richness -- a blunt, generic refusal that always
fires beats a nuanced one that sometimes doesn't.
"""

from __future__ import annotations

import re

from google.adk.models.llm_response import LlmResponse
from google.genai import types

# Procedural ("how do I", "which wire") is refused; requirement ("does it
# need") is a normal product question and must reach the model -- the
# split the plan names explicitly. Patterns are deliberately narrow: a
# false negative here still gets a chance to be caught by L4, or falls
# back to L1's prose; a false positive silently blocks an ordinary
# question with no recovery, which is the worse failure to court.
_WIRING_PATTERNS = [
    re.compile(r"\bhow (do|can|would) i (wire|connect|install|hook up|hardwire)\b", re.IGNORECASE),
    re.compile(r"\bwhich (wire|wires|terminal|terminals|screw|screws) (do i|goes|go|connects|should)\b", re.IGNORECASE),
    re.compile(r"\b(connect|attach|strip) the (live|neutral|earth|ground|phase) wire\b", re.IGNORECASE),
    re.compile(r"\bturn off the (breaker|fuse|power|mains) and\b", re.IGNORECASE),
    re.compile(r"\bwiring (instructions|diagram|steps)\b", re.IGNORECASE),
    re.compile(r"\bconnect (it |this )?(directly )?to (the )?mains\b", re.IGNORECASE),
    re.compile(r"\bwie (schlie(?:ß|ss)e ich|verkab(?:le|ele) ich|installiere ich)\b", re.IGNORECASE),
    re.compile(r"\bwelche[rs]? (kabel|ader|klemme|schraube) (kommt|geht|muss)\b", re.IGNORECASE),
    re.compile(r"\b(phase|nullleiter|schutzleiter|ader)\s+(an)?schlie(?:ß|ss)en\b", re.IGNORECASE),
    re.compile(r"\bsicherung (ausschalten|abschalten) und\b", re.IGNORECASE),
    re.compile(r"\bans?\s?stromnetz anschlie(?:ß|ss)en\b", re.IGNORECASE),
    re.compile(r"\bkabel abisolieren\b", re.IGNORECASE),
    re.compile(r"\bselbst (anschlie(?:ß|ss)en|verkabeln|installieren)\b", re.IGNORECASE),
]

# A small, deliberately conservative set of unmistakably-unrelated topics
# -- not an attempt at general topic classification (that's what the cut
# L3 judge would have done). Anything not this obvious falls through to
# L1's own scope prose, same acknowledged gap as above.
_OFF_DOMAIN_PATTERNS = [
    re.compile(r"\b(write|compose) (me )?an? (poem|song|story|essay)\b", re.IGNORECASE),
    re.compile(r"\bwhat(?:'s| is) the weather\b", re.IGNORECASE),
    re.compile(r"\btell me a joke\b", re.IGNORECASE),
    re.compile(r"\b(python|javascript|java|c\+\+)\s+code\b", re.IGNORECASE),
    re.compile(r"\bmedical advice\b", re.IGNORECASE),
    re.compile(r"\blegal advice\b", re.IGNORECASE),
    re.compile(r"\brecipe for\b", re.IGNORECASE),
    re.compile(r"\bwho won\b", re.IGNORECASE),
    re.compile(r"\bhelp (me )?with my homework\b", re.IGNORECASE),
    re.compile(r"\b(schreibe|schreib) (mir )?(ein|einen) (gedicht|lied|geschichte|aufsatz)\b", re.IGNORECASE),
    re.compile(r"\bwie ist das wetter\b", re.IGNORECASE),
    re.compile(r"\berz(?:ä|ae)hl(?:e)? mir einen witz\b", re.IGNORECASE),
    re.compile(r"\brezept f(?:ü|ue)r\b", re.IGNORECASE),
    re.compile(r"\bhausaufgaben\b", re.IGNORECASE),
    re.compile(r"\bmedizinischen? rat\b", re.IGNORECASE),
    re.compile(r"\brechtlichen? rat\b", re.IGNORECASE),
]

_DE_HINT_WORDS = {
    "ich", "wie", "und", "das", "der", "die", "brauche", "kann", "bitte",
    "danke", "funktioniert", "mit", "für", "ein", "eine", "nicht", "heute",
    "etwas", "mehr", "interessant", "ja", "nein", "sicher", "toll", "gut",
    "schön", "möchte", "suche", "gibt", "andere", "auch", "noch", "gerne",
    "ist", "sind", "haben", "sehr", "vielleicht", "hier", "sonst",
}
_EN_HINT_WORDS = {
    "i", "how", "the", "and", "can", "need", "please", "thanks", "works",
    "with", "for", "a", "not", "today", "do", "does",
    "something", "more", "interesting", "yes", "no", "sure", "great",
    "good", "nice", "want", "looking", "other", "also", "still", "thank",
    "is", "are", "have", "very", "just", "maybe", "here", "else",
    "recommend", "anything",
}

REFUSAL_WIRING_EN = (
    "I can't advise on electrical installation -- that's work for a qualified electrician. Many of our smart "
    "products need no electrical work at all, though: battery-powered devices and plug-in adapters install "
    "without one. Ask me whether that applies to the product you're looking at, or about our installation service."
)
REFUSAL_WIRING_DE = (
    "Zur Elektroinstallation kann ich Sie leider nicht beraten -- das gehört in die Hände einer Elektrofachkraft. "
    "Viele unserer smarten Produkte lassen sich allerdings ganz ohne Elektroarbeiten montieren: batteriebetriebene "
    "Geräte und Zwischenstecker brauchen keinen Elektriker. Fragen Sie mich gern, ob das auf Ihr Wunschprodukt "
    "zutrifft -- oder nach unserem Montageservice."
)
DEFLECTION_OFF_DOMAIN_EN = (
    "I'm the shopping assistant for our smart home range, so I can't help with that. "
    "Happy to help you find the right smart home product, though!"
)
DEFLECTION_OFF_DOMAIN_DE = (
    "Ich bin der Einkaufsberater für unser Smart-Home-Sortiment und kann dabei leider nicht helfen. "
    "Gerne helfe ich Ihnen aber bei der Suche nach einem passenden Smart-Home-Produkt!"
)


_EN_SUFFIX_SIGNAL = re.compile(r"\b\w+'(?:s|t|re|ll|ve|d)\b|\b\w+ing\b", re.IGNORECASE)


def _language_scores(text: str) -> tuple[int, int]:
    """Word-list overlap is the primary signal; two cheap, high-precision
    fallbacks catch ordinary words the curated lists don't happen to
    include -- found via a real gap: "something more interesting" scored
    0-0 despite being unambiguous English, and (having no confident
    signal) inherited a stale language from an earlier turn. German
    umlauts/ß are near-exclusive to German; English gerunds ("-ing") and
    contractions ("it's", "don't") are near-exclusive to English. Each
    contributes at most one point -- a cheap tiebreak, never enough alone
    to overrule real word-list evidence pointing the other way."""
    lowered = text.lower()
    words = set(re.findall(r"[a-zäöüß]+", lowered))
    de_score = len(words & _DE_HINT_WORDS)
    en_score = len(words & _EN_HINT_WORDS)
    if re.search(r"[äöüß]", lowered):
        de_score += 1
    if _EN_SUFFIX_SIGNAL.search(lowered):
        en_score += 1
    return de_score, en_score


def _looks_german(text: str) -> bool:
    """A tiny word-overlap heuristic, not a language detector -- good
    enough to pick which of two fixed strings to return. Defaults to
    German on a tie or no signal at all, matching instruction.md's own
    documented default. Used only for picking *our own* reply's language
    once we already know we're answering with a fixed string (L2/L4) --
    see `_confident_language` below for detecting the *customer's*
    language, where a tie must NOT default to anything."""
    de_score, en_score = _language_scores(text)
    return de_score >= en_score


def _confident_language(text: str) -> str | None:
    """Strict, unlike `_looks_german` above: returns None on a tie or no
    signal at all (e.g. "ok", a bare product id) instead of defaulting to
    German, so the per-turn language directive can fall back to whatever
    language the conversation was already confidently in rather than
    resetting every ambiguous turn."""
    de_score, en_score = _language_scores(text)
    if de_score > en_score:
        return "German"
    if en_score > de_score:
        return "English"
    return None


# A stated preference outranks a heuristic, always -- "can you answer in
# English?" is a direct request, not something to leave to vocabulary
# overlap. Checked before `_confident_language`, not folded into its
# scoring: a request for English should win even when the rest of the
# same message is otherwise confidently German (or vice versa), which a
# shared score could never guarantee.
_EXPLICIT_ENGLISH_REQUEST = re.compile(r"\b(?:in|auf)\s+englisch\b|\bin\s+english\b|\bantworte\w*.*englisch\b", re.IGNORECASE)
_EXPLICIT_GERMAN_REQUEST = re.compile(r"\b(?:in|auf)\s+deutsch\b|\bin\s+german\b|\banswer\w*.*german\b", re.IGNORECASE)


def _explicit_language_request(text: str) -> str | None:
    if _EXPLICIT_ENGLISH_REQUEST.search(text):
        return "English"
    if _EXPLICIT_GERMAN_REQUEST.search(text):
        return "German"
    return None


def _latest_user_text(contents: list[types.Content]) -> str:
    """`contents` carries the whole conversation so far, not just the new
    turn -- scanning all of it would let a wiring question from three
    turns ago keep blocking every later, unrelated message."""
    for content in reversed(contents):
        if content.role == "user":
            return " ".join(part.text for part in (content.parts or []) if part.text)
    return ""


def _matches_any(patterns: list[re.Pattern], text: str) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def _classify(text: str) -> str | None:
    """Detects a *customer's* wiring/off-domain request by its known
    trigger phrasing. Distinct from `_reply_category` below, which
    recognizes our own two refusal *shapes* in the model's already-drafted
    text -- a customer's request and a refusal about that request don't
    share vocabulary, so one classifier can't do both jobs."""
    if _matches_any(_WIRING_PATTERNS, text):
        return "wiring"
    if _matches_any(_OFF_DOMAIN_PATTERNS, text):
        return "off_domain"
    return None


def _reply_for(category: str, is_de: bool) -> types.Content:
    if category == "wiring":
        return types.Content(role="model", parts=[types.Part(text=REFUSAL_WIRING_DE if is_de else REFUSAL_WIRING_EN)])
    return types.Content(role="model", parts=[types.Part(text=DEFLECTION_OFF_DOMAIN_DE if is_de else DEFLECTION_OFF_DOMAIN_EN)])


def _guardrail_reply(text: str) -> types.Content | None:
    if not text:
        return None
    category = _classify(text)
    return None if category is None else _reply_for(category, _looks_german(text))


# Anchors words/phrases unique to our own two canned refusal shapes --
# "electrician"/"Elektrofachkraft" never appears in a genuine product
# answer, and a "kann ... nicht helfen" / "can't help" decline is what
# every deflection says regardless of phrasing. Deliberately not reused
# from _WIRING_PATTERNS/_OFF_DOMAIN_PATTERNS: those detect a *customer's*
# request; this recognizes the *model's own refusal prose*, which never
# contains the customer-style trigger verbs those patterns look for.
_WIRING_REPLY_ANCHOR = re.compile(r"electrician|elektrofachkraft", re.IGNORECASE)
_DEFLECTION_REPLY_ANCHOR = re.compile(r"can'?t help|kann.{0,25}nicht helfen", re.IGNORECASE)


def _reply_category(text: str) -> str | None:
    if _WIRING_REPLY_ANCHOR.search(text):
        return "wiring"
    if _DEFLECTION_REPLY_ANCHOR.search(text):
        return "off_domain"
    return None


# The one clarifying question instruction.md requires ("ask once, when
# the ecosystem is missing") is safe to recognize and safe to replace,
# unlike arbitrary free text: the instruction always makes the model list
# all four ecosystem names together when asking it, so requiring all four
# is a specific, low-false-positive signal, and the question itself never
# carries product-specific facts that a template could accidentally
# discard. Real, user-reported case: an English "hey, can you help me?"
# got a fully German version of exactly this question back -- not a
# refusal, so neither _classify nor _reply_category had anything to
# anchor on, and it fell through to being flagged instead of fixed.
_ECOSYSTEM_NAMES = ("alexa", "google home", "apple home", "matter")

ASK_ECOSYSTEM_EN = "Sure, happy to help! Which smart home ecosystem do you use: Alexa, Google Home, Apple Home, or Matter?"
ASK_ECOSYSTEM_DE = "Gerne helfe ich Ihnen! Welches Smart-Home-System nutzen Sie: Alexa, Google Home, Apple Home oder Matter?"


def _asks_about_ecosystem(text: str) -> bool:
    lowered = text.lower()
    return all(name in lowered for name in _ECOSYSTEM_NAMES)


def _user_message_text(callback_context) -> str:
    content = getattr(callback_context, "user_content", None)
    if content is None or not content.parts:
        return ""
    return " ".join(part.text for part in content.parts if part.text)


def _inject_language_directive(callback_context, llm_request, text: str) -> None:
    """Moves "reply in the customer's language" upstream, into the
    request, instead of only patrolling the response downstream.
    Pattern-matching every possible reply shape at L4 (the wiring
    refusal, the off-domain deflection, the ecosystem question, ...)
    doesn't scale -- the next reply shape a reviewer triggers just needs
    a new pattern, and general product answers are exactly the shape L4
    can't safely correct at all (no fixed string to fall back on). A
    directive scoped to *this turn only*, appended fresh each time, is
    far narrower and harder to out-weigh than a general "default to
    German" competing against the rest of the instruction.

    Three-way priority, deterministic signal outranking heuristic each
    step down: an explicit request ("answer in English") always wins,
    since a stated preference isn't something to leave to vocabulary
    overlap; failing that, the word/signal-based detector; failing that
    (no confident signal either way), whatever language the conversation
    was last confidently in, stored in session state, defaulting to
    German only when nothing has been confidently detected yet this
    session at all."""
    state = getattr(callback_context, "state", None)
    if state is None:
        state = {}

    detected = _explicit_language_request(text) or _confident_language(text)
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


def before_model_guardrail(callback_context, llm_request) -> LlmResponse | None:
    """L2: deterministic pre-filter. Fires before the LLM is invoked at
    all; returning a value here short-circuits the turn in ADK, so a
    clear violation never reaches the model -- not even to be told not to
    answer it.

    On the pass-through path (nothing blocked), also injects a per-turn
    language directive -- see `_inject_language_directive`. A blocked
    request returns immediately, before the injection ever runs: there's
    no model turn for a directive to attach to."""
    text = _latest_user_text(llm_request.contents)
    content = _guardrail_reply(text)
    if content is not None:
        return LlmResponse(content=content)

    _inject_language_directive(callback_context, llm_request, text)
    return None


def after_model_guardrail(callback_context, llm_response) -> LlmResponse | None:
    """L4: output scan, the floor for whatever L1+L2 didn't catch. Only
    scans actual drafted text -- a response that's purely a tool call
    (no text parts yet) has nothing to scan, and treating that as "no
    match" (rather than skipping it) would otherwise be indistinguishable
    from a clean response -- either way nothing gets replaced, but the
    reasoning matters for anyone reading this later.

    Also closes a class of real defect: L1 can compose an otherwise
    *correct* reply in the *wrong* language -- first found in the red
    team (docs/red_team.md, cases 7 and 9, a refusal and a deflection),
    then again live in a plain "can you help me?" greeting that came back
    fully in German. "Default to German" gets over-weighted often enough
    that this isn't one bug, it's a pattern -- and a callback shouldn't
    depend on prompt-following for anything this checkable. Three reply
    shapes are recognized and corrected deterministically because we
    already know their fixed, known-language text: the two refusals
    above, and the ecosystem-clarifying question every fresh conversation
    goes through. Anything else -- real, variable, product-specific
    content -- is flagged, not guessed at; there's no general translator
    here, and guessing risks discarding a real answer.
    """
    content = llm_response.content
    if content is None or not content.parts:
        return None
    text = " ".join(part.text for part in content.parts if part.text)
    if not text:
        return None

    category = _classify(text)
    if category is not None:
        return LlmResponse(content=_reply_for(category, _looks_german(text)))

    user_text = _user_message_text(callback_context)
    if not user_text or _looks_german(user_text) == _looks_german(text):
        return None

    reply_category = _reply_category(text)
    if reply_category is not None:
        return LlmResponse(content=_reply_for(reply_category, _looks_german(user_text)))

    if _asks_about_ecosystem(text):
        is_de = _looks_german(user_text)
        return LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text=ASK_ECOSYSTEM_DE if is_de else ASK_ECOSYSTEM_EN)])
        )

    # A language mismatch on an ordinary, substantively correct answer --
    # not a refusal or deflection in substance, just in the wrong
    # language. There's no general translator here, so there's no safe
    # replacement text; overwriting it would trade a language slip for a
    # worse regression (losing real product information). Flagged, not
    # silently dropped, and not rewritten on a guess.
    return llm_response.model_copy(
        update={"custom_metadata": {**(llm_response.custom_metadata or {}), "language_mismatch": True}}
    )
