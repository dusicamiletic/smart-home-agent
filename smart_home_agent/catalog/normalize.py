"""Stage 3 of the build pipeline (plan section 08): normalize raw German
strings -- from the Stage-2 attrs dict and the raw product record -- into
typed, derived facts.

Every derived fact carries a confidence tier (plan section "confidence tier
on every derived field"):

    DECLARED  the attributes blob (or another structured field) said so
    INFERRED  only a title/subtitle/description keyword implies it
    UNKNOWN   no signal at all

Never guess past what the tier allows.
"""

from __future__ import annotations

import re
from collections import namedtuple
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from urllib.parse import urlparse


class Confidence(str, Enum):
    DECLARED = "declared"
    INFERRED = "inferred"
    UNKNOWN = "unknown"


class Ecosystem(str, Enum):
    ALEXA = "alexa"
    GOOGLE_HOME = "google_home"
    APPLE_HOME = "apple_home"
    MATTER = "matter"


class PowerType(str, Enum):
    HARDWIRED = "hardwired"
    MAINS = "mains"
    BATTERY = "battery"


Tiered = namedtuple("Tiered", ["value", "confidence"])


@dataclass(frozen=True)
class EcosystemSignal:
    """Every fact traces to a field -- `source` is the real attrs key (or
    "title" for the keyword fallback) that produced this tag, not a
    guess reconstructed after the fact."""

    confidence: Confidence
    source: str


HubRequirement = namedtuple("HubRequirement", ["required", "confidence", "hint", "source"])


def parse_price(raw: str) -> Decimal | None:
    """German-formatted price string -> Decimal.

    "49,10 €" -> 49.10. ",-" means ".00" and may itself carry a "."
    thousands separator ("1.299,- €" -> 1299.00). Multi-line promo strings
    (e.g. "Ersparnis: 20,- €\\nStatt 159,95\\n139,95 €") carry the real
    price on the last line -- take it, not the first.
    """
    line = raw.strip().splitlines()[-1].strip()
    digits = line.replace("€", "").strip()
    if digits.endswith(",-"):
        digits = digits[:-2].replace(".", "") + ".00"
    else:
        digits = digits.replace(".", "").replace(",", ".")
    try:
        return Decimal(digits)
    except InvalidOperation:
        return None


def category_from_url(url: str) -> str:
    """The category slug is the first path segment: domain/<category>/<product
    slug>/p/<id>. Raw urls carry a trailing newline that must be stripped
    before parsing, not treated as part of the id."""
    path = urlparse(url.strip()).path
    return next(segment for segment in path.split("/") if segment)


# Multi-word brand/product-line prefixes that a naive first-token split
# would break -- curated by eye from a real frequency census of the first
# 2 and 3 title tokens across all 943 products (see docs/decisions.md),
# the same "look at the real data, judge, don't automate" discipline used
# for build/vocabulary.json.
KNOWN_MULTI_WORD_BRANDS = (
    "Bosch Smart Home",
    "Schellenberg Smart Home",
    "Gardena Smart system",
    "Philips Hue",
    "Homematic IP",
    "Ledvance Smart+",
    "Innr Lighting",
    "Philips Wiz",
    "Müller-Licht Tint",
    "Google Nest",
)


def brand_from_title(title: str) -> str:
    """Brand isn't a separate field -- parse it from the title's leading
    tokens. Defaults to the first token; a curated multi-word brand wins
    when the title starts with it."""
    for brand in KNOWN_MULTI_WORD_BRANDS:
        if title.startswith(brand + " ") or title == brand:
            return brand
    return title.split()[0]


# Unterstützte Sprachsteuerung is multi-valued and comma-separated (order
# varies between products) -- each value maps to exactly one ecosystem.
_VOICE_ECOSYSTEMS = {
    "Amazon Alexa": Ecosystem.ALEXA,
    "Apple Siri": Ecosystem.APPLE_HOME,
    "Google Assistant": Ecosystem.GOOGLE_HOME,
}


def _split_values(raw: str) -> list[str]:
    return [v.strip() for v in raw.split(",") if v.strip()]


def derive_ecosystems(attrs: dict[str, str], title: str) -> dict[Ecosystem, EcosystemSignal]:
    """Union real third-party ecosystems across Unterstützte Sprachsteuerung,
    Unterstützte Systeme and a title keyword fallback. Unterstützte Systeme
    holds two different things (plan section on the field): a real ecosystem
    (Apple HomeKit, Matter) or a vendor's own walled garden (e.g. "Homematic
    IP System") -- only the former belongs here; the latter is a vendor
    platform (see derive_vendor_platform), never unioned in as a fake
    ecosystem.

    Each tag records the real attrs key (or "title") it came from -- never
    reconstructed after the fact from a lossier derived value."""
    ecosystems: dict[Ecosystem, EcosystemSignal] = {}

    for value in _split_values(attrs.get("Unterstützte Sprachsteuerung", "")):
        ecosystem = _VOICE_ECOSYSTEMS.get(value)
        if ecosystem is not None:
            ecosystems[ecosystem] = EcosystemSignal(Confidence.DECLARED, "Unterstützte Sprachsteuerung")

    for value in _split_values(attrs.get("Unterstützte Systeme", "")):
        if "Apple HomeKit" in value:
            ecosystems[Ecosystem.APPLE_HOME] = EcosystemSignal(Confidence.DECLARED, "Unterstützte Systeme")
        elif "Matter" in value:
            ecosystems[Ecosystem.MATTER] = EcosystemSignal(Confidence.DECLARED, "Unterstützte Systeme")

    if Ecosystem.MATTER not in ecosystems and re.search(r"\bMatter\b", title):
        ecosystems[Ecosystem.MATTER] = EcosystemSignal(Confidence.INFERRED, "title")

    return ecosystems


def derive_vendor_platform(attrs: dict[str, str], brand: str | None = None) -> Tiered:
    """The strongest signal for which vendor walled garden a product belongs
    to -- a value in Unterstützte Systeme that names the vendor's own
    platform rather than a real third-party ecosystem (e.g. "Homematic IP
    System" -> vendor platform "Homematic IP", vs. "Apple HomeKit System"
    which is a real ecosystem, not a vendor platform). Not a hub-required
    signal: derive_hub_requirement deliberately never reads this field --
    "vendor platform exists" and "hub required" are different facts (a
    plain Hue bulb can work over Bluetooth without the Bridge).

    Some products list several such platforms at once (e.g. a Philips Hue
    light also tagged "Razer Chroma System" for a PC-gaming lighting-sync
    feature) -- picking whichever comes first in the list picked "Razer
    Chroma" for a Hue product, a real bug found sampling the data. When a
    brand is given, prefer the candidate that shares a word with it."""
    candidates = []
    for value in _split_values(attrs.get("Unterstützte Systeme", "")):
        if "Apple HomeKit" in value or "Matter" in value:
            continue
        platform = value[: -len(" System")] if value.endswith(" System") else value
        candidates.append(platform)

    if not candidates:
        return Tiered(None, Confidence.UNKNOWN)

    if brand:
        brand_words = set(brand.lower().split())
        for platform in candidates:
            if brand_words & set(platform.lower().split()):
                return Tiered(platform, Confidence.DECLARED)

    return Tiered(candidates[0], Confidence.DECLARED)


_POWER_TYPE_KEYWORDS = {
    "Festverdrahtet": PowerType.HARDWIRED,
    "Netzbetrieben": PowerType.MAINS,
    "Batteriebetrieben": PowerType.BATTERY,
}


def derive_power_type(attrs: dict[str, str], subtitle: str) -> Tiered:
    """Stromversorgung then Betriebsart (attrs, DECLARED), then a subtitle
    keyword (INFERRED). Stromversorgung wins over a contradicting Betriebsart
    -- real data has products (the Ring doorbell) carrying Stromversorgung:
    Festverdrahtet and Betriebsart: Netzbetrieben at once, and Stromversorgung
    is the specific field for the wiring question the safety guardrail cares
    about."""
    for key in ("Stromversorgung", "Betriebsart"):
        power_type = _POWER_TYPE_KEYWORDS.get(attrs.get(key, ""))
        if power_type is not None:
            return Tiered(power_type, Confidence.DECLARED)

    for keyword, power_type in _POWER_TYPE_KEYWORDS.items():
        if keyword in subtitle:
            return Tiered(power_type, Confidence.INFERRED)

    return Tiered(None, Confidence.UNKNOWN)


# Hub dependency hides in free text (plan: "there is no hub field"). These
# requirement *verbs* were the original signal -- and, checking hub_required
# against real cross-tabs (is_smart, Datenübertragung, the hub-category
# group itself), turned out to be far too generic: "erfordert/benötigt/
# notwendig/erforderlich" are just German words for "necessary," and fire
# on battery-inclusion notes, tool-free mounting, LED lifespan, room size,
# and subscription text just as readily as on an actual hub. Kept, but
# demoted: see _HUB_NOUNS below, which is now the real signal.
_HUB_TRIGGER = re.compile(
    r"erfordert|benötigt|erforderlich|notwendig|nur in Verbindung mit", re.IGNORECASE
)

# The actual signal, inverted from the verb: a real hub/companion product
# named by type, checking real data (docs/decisions.md) that a hub-shaped
# noun is a far more specific claim than a generic requirement verb --
# "Benötigt Homematic IP Access Point" and "Thombox" both name real
# hardware without needing a verb at all. Word-boundaried, case-sensitive
# (these are always capitalized in German retail copy).
_HUB_NOUNS = re.compile(
    r"\b(Access Point|Bridge|Gateway|Steuerzentrale|Zentrale|Basisstation|"
    r"Smart Home Controller|Hub|Thombox)\b"
)
# German negates a requirement both before the trigger ("...kein Gateway
# benötigt wird") and after it ("...erfordert keine Verkabelung"), and a
# modifying adjective between the negation and the noun ("kein zusätzliches
# Werkzeug erforderlich" -- "no additional tool required") routinely pushes
# the gap past what looks like a generous window. Found via full-corpus
# validation (scripts/normalize_check.py and, later, check_compatibility's
# own test fixtures) at real distances up to the high 40s. The window has
# to be wide enough to catch that, but bounded to the current clause --
# stopped at the nearest sentence-ending period or newline -- so it can't
# reach into an unrelated *following* bullet point and wrongly suppress a
# real requirement two sentences later.
_NEGATION = re.compile(r"\b(kein|keine|keinen|nicht|ohne)\b", re.IGNORECASE)
_NEGATION_WINDOW_BEFORE = 50
_NEGATION_WINDOW_AFTER = 20


def _clause_before(text: str, pos: int, max_chars: int) -> str:
    window = text[max(0, pos - max_chars) : pos]
    boundary = max(window.rfind("."), window.rfind("\n"))
    return window[boundary + 1 :] if boundary != -1 else window


def _clause_after(text: str, pos: int, max_chars: int) -> str:
    window = text[pos : pos + max_chars]
    ends = [i for i in (window.find("."), window.find("\n")) if i != -1]
    return window[: min(ends)] if ends else window


def _first_unnegated_trigger(text: str) -> re.Match | None:
    """First trigger occurrence not negated in the same clause, checking
    both directions -- a bare keyword match on 'benötigt' fires just as
    readily on '...kein Gateway benötigt wird' (no hub needed) or
    'erfordert keine Verkabelung' (requires no wiring) as on a real
    requirement."""
    for match in _HUB_TRIGGER.finditer(text):
        before = _clause_before(text, match.start(), _NEGATION_WINDOW_BEFORE)
        after = _clause_after(text, match.end(), _NEGATION_WINDOW_AFTER)
        if _NEGATION.search(before) or _NEGATION.search(after):
            continue
        return match
    return None


def _first_unnegated_noun(text: str) -> re.Match | None:
    """First hub-noun occurrence not negated in the same clause -- the
    primary hub signal. A verb trigger nearby is optional corroboration,
    never required: "Benötigt Homematic IP Access Point" and "wird eine
    Thombox benötigt" both name real hardware, and the noun alone is a far
    more specific claim than the generic verb ever was on its own.
    Self-reference (a hub product describing itself) is handled one level
    up, in derive_hub_requirement -- see _product_identifies_as_hub."""
    for match in _HUB_NOUNS.finditer(text):
        before = _clause_before(text, match.start(), _NEGATION_WINDOW_BEFORE)
        after = _clause_after(text, match.end(), _NEGATION_WINDOW_AFTER)
        if _NEGATION.search(before) or _NEGATION.search(after):
            continue
        return match
    return None


_HINT_PREFIX_MAX_WORDS = 2


def _extract_noun_hint(text: str, noun: re.Match) -> str:
    """The noun match itself, plus up to two capitalized brand-prefix words
    immediately before it in the same clause ("Homematic IP" before
    "Access Point", "Bosch" before "Smart Home Controller"). Capped at two
    words deliberately, not walked until the first lowercase word: German
    capitalizes every common noun, not just brand names, so an unbounded
    walk swept up the *sentence's own scaffolding* -- "eine der folgenden
    Lösungen: Homematic IP Access Point" produced "Lösungen Homematic IP
    Access Point", because "Lösungen" ("solutions") is capitalized too."""
    prefix_words = _clause_before(text, noun.start(), 40).split()
    kept: list[str] = []
    for word in reversed(prefix_words):
        if len(kept) >= _HINT_PREFIX_MAX_WORDS:
            break
        cleaned = word.strip(",;:")
        if cleaned and (cleaned[0].isupper() or cleaned.isupper()):
            kept.insert(0, cleaned)
        else:
            break
    prefix = " ".join(kept)
    return f"{prefix} {noun.group()}".strip() if prefix else noun.group()


def derive_hub_requirement(attrs: dict[str, str], description: str, title: str = "") -> HubRequirement:
    """Hub dependency is scattered across free text (plan: "there is no
    hub field"), but the sources don't all deserve the same trust, and the
    real signal within each is a named piece of hardware, not a generic
    requirement verb (see _HUB_NOUNS).

    Hinweise names hardware in prose about *this* product directly
    ("Der Betrieb erfordert... Homematic IP Access Point") -- DECLARED.

    Passend für is not used here at all -- dropped entirely, not merely
    demoted. It was never a hub signal to begin with: the key means "fits
    X," and X can just as easily be a room size ("Räume bis ca. 52 m²"),
    a valve thread, or a companion product -- a field misuse, not an
    ambiguous-but-real signal worth tuning further. A real dependency
    named in Passend für (e.g. "Thomson Thombox") has consistently also
    shown up in Hinweise or description in every case checked, so nothing
    real is lost by dropping it -- confirmed after the fact by re-running
    the full 943 and finding the same headline products still resolve
    True through those sources alone.

    description prose is the weakest source structurally (not part of the
    attributes blob at all) but not ambiguous the way Passend für is --
    also INFERRED, gated the same way as Hinweise: a named hub noun, not a
    bare verb.

    Two things this version deliberately does NOT do, checking real data
    first found both wrong: (1) fire on a bare requirement verb with no
    named hardware nearby -- checking cross-tabs against is_smart,
    Datenübertragung and the hub-category group itself showed this firing
    on battery-inclusion notes, tool-free mounting, LED lifespan, room
    size and subscription text, none of it about a hub; landed on
    hub_required=True for 67% of the catalog, including hub products
    needing themselves. (2) treat Unterstützte Systeme naming a vendor
    platform as a hub signal at all -- "vendor platform exists" and "hub
    required" are different facts (a plain Hue bulb works over Bluetooth
    without the Bridge); that was an inference, not a reading, and it was
    wrong. vendor_platform stays a stored field (useful for "you'll want
    the Hue app"), just not a hub_required input.

    Two self-reference shapes, both found by the hub-category invariant
    test (products in the starter-kit/gateway category must never require
    a hub -- a hub cannot require itself), and both gated the same way,
    at the whole-product level, before checking any source:

    1. The product's own title identifies it as hub-type hardware
       ("Homematic IP Steuerzentrale Access Point", "Gardena Gateway...").
       Its own Hinweise/description then talk about themselves in the
       third person ("Der Homematic IP Access Point dient als Basis
       für..."), and its own Passend für describes what it manages, not a
       companion it needs ("Passend für: Homematic IP Smart Home
       Geräte"). A per-match "does this exact phrase appear in the title"
       check isn't enough here -- German's case rules mean "Zentrale"
       (capitalized, standalone) and the embedded "-zentrale" inside
       "Steuerzentrale" don't string-match, even though they're the same
       self-reference. Checking the *product* rather than the *match*
       closes that gap in one place instead of chasing each spelling.
    2. Starter-kits describe their own *bundled* hub in passing --
       "Starter-Set mit Temperatursender und Gateway" names the Gateway
       as part of what's already in the box. "Set" in the title
       (Starter-Set, Starterset, "... MA10029 SET") is a simple, well-
       scoped signal for this.
    """
    skip_self_reference = "Set" in title or bool(_HUB_NOUNS.search(title))

    if not skip_self_reference:
        hinweise = attrs.get("Hinweise", "")
        noun = _first_unnegated_noun(hinweise)
        if noun is not None:
            return HubRequirement(True, Confidence.DECLARED, _extract_noun_hint(hinweise, noun), "Hinweise")

        noun = _first_unnegated_noun(description)
        if noun is not None:
            return HubRequirement(True, Confidence.INFERRED, _extract_noun_hint(description, noun), "description")

    return HubRequirement(None, Confidence.UNKNOWN, None, None)


_IS_SMART_TITLE_KEYWORDS = re.compile(r"\b(Smart|WiFi|WLAN|App|Matter|Zigbee)\b")
_CONNECTIVITY_PROTOCOLS = ("WLAN", "Bluetooth", "Zigbee", "Z-Wave", "Funk")

# No signal, but the category itself rules out connectivity -- curated by
# eye, the same discipline as KNOWN_MULTI_WORD_BRANDS. FALSE is a real
# tri-state value, not a fallback: it's earned by category membership, not
# assumed from silence -- everywhere else in this codebase, silence means
# UNKNOWN, never a guessed negative.
_NON_SMART_CATEGORIES = {
    "kabelverbinder",  # cable connectors
    "verlaengerungskabel",  # extension cables
    "vorhaengeschloesser",  # padlocks
    "warmwasserspeicher",  # water heaters
    "hauswasserwerke-hauswasserautomaten",  # domestic water pressure booster pumps
    "kuechenventilatoren",  # kitchen ventilation fans
}


def derive_is_smart(
    attrs: dict[str, str],
    title: str,
    category: str,
    ecosystems: dict[Ecosystem, EcosystemSignal],
    hub_required: bool | None,
) -> Tiered:
    """A union of every connectivity signal this module already computes,
    not an independent re-derivation with its own narrower keyword set.

    The real defect this replaces: the old version only scanned the title
    for Smart/WiFi/WLAN/App, so a product whose only signal was a '[+M]
    Matter' tag -- which derive_ecosystems *does* catch -- came back
    UNKNOWN here while ecosystems was non-empty. The two disagreed about
    the same product. Folding "ecosystems non-empty" (and hub_required,
    and the real Datenübertragung protocols) into this union makes that
    disagreement structurally impossible: ecosystems non-empty now always
    implies is_smart is truthy, by construction.

    Tri-state, like everything else here: TRUE from a real signal, FALSE
    only for a curated non-connected category (never guessed from mere
    silence), UNKNOWN otherwise."""
    if attrs.get("Smart Home-fähig") == "Ja":
        return Tiered(True, Confidence.DECLARED)

    if ecosystems:
        return Tiered(True, Confidence.INFERRED)

    datenuebertragung = attrs.get("Datenübertragung", "")
    if any(protocol in datenuebertragung for protocol in _CONNECTIVITY_PROTOCOLS):
        return Tiered(True, Confidence.INFERRED)

    if hub_required:
        return Tiered(True, Confidence.INFERRED)

    brand = brand_from_title(title)
    remainder = title[len(brand) :]
    if _IS_SMART_TITLE_KEYWORDS.search(remainder):
        return Tiered(True, Confidence.INFERRED)

    if category in _NON_SMART_CATEGORIES:
        return Tiered(False, Confidence.INFERRED)

    return Tiered(None, Confidence.UNKNOWN)
