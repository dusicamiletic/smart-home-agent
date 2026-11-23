"""Hand-derived expected output of the Stage-2 blob parser (w06), written
before the parser exists (w07). Not normalized values yet -- this is the
"tags + flat key/value dict" shape from Stage 2 of the pipeline, still in
raw German strings. See README.md in this directory for why these three.

Cross-check these by hand against tests/fixtures/<id>.json before trusting
attributes.py's output against them.
"""

HOMEMATIC_26745237 = {
    "id": "26745237",
    "tags": ["Nicht im Hausmüll entsorgen"],
    "attrs": {
        "Material": "Kunststoff",
        "Farbe": "Weiß",
        "Länge": "97 mm",
        "Breite": "58 mm",
        "Höhe": "71 mm",
        "Gewicht (Netto)": "241 g",
        "Ausstattung": "Display",
        "Datenübertragung": "Funk",
        "Funktionen": (
            "Automatische Temperaturregelung, Fenster-auf-Funktion, "
            "Flüsterbetrieb, Boost-Funktion, Eco-Modus, Frostschutz, "
            "Bedienung per App oder am Gerät, Sprachsteuerung"
        ),
        "Anzahl benötigte Batterien": "2 Stk.",
        "Batterielaufzeit": "2 Jahre",
        "Batterien": "Mit Batterien",
        "Batteriespannung": "1,5 V",
        "Batterietyp": "Mignon AA",
        "Reichweite Funk": "300 m",
        "Smart Home-fähig": "Ja",
        "Smarte Steuerung": "Homematic IP App",
        "Unterstützte Sprachsteuerung": "Amazon Alexa, Apple Siri, Google Assistant",
        "Unterstützte Systeme": "Homematic IP System",
        "Anwendungsbereich": "Innen",
        "Einsatzbereich": "Wohnraum, Schlafzimmer",
        "Geeignet für": "Heizkörper",
        "Unterstützte Betriebssysteme": "iOS 8.0 oder höher, Android 5.0 oder höher",
        "Betriebstemperatur": "0 - 50 °C",
        "Schutzart": "IP20",
        "Betriebsart": "Batteriebetrieben",
        "Funkfrequenz": "868 MHz - 869,4 MHz",
        "Gesamtstückzahl": "1 Stk.",
        "Hinweise": (
            "Der Betrieb erfordert die Anbindung an eine der folgenden "
            "Lösungen: Homematic IP Access Point mit kostenloser "
            "Smartphone-App und gebührenfreiem Cloud-Service;Zentrale CCU3 "
            "mit lokaler Bedienoberfläche WebUI (nicht mehr kompatibel mit "
            "der Zentrale CCU2); Partnerlösungen von Drittanbietern"
        ),
        "Ventilanschluss": "M30 x 1,5 mm",
        "EAN": "4047976402809",
    },
    "post_normalize_notes": (
        "Ecosystems = {ALEXA, APPLE_HOME, GOOGLE_HOME} from Sprachsteuerung "
        "alone here -- Unterstützte Systeme says 'Homematic IP System', "
        "which is a VENDOR PLATFORM (Homematic's own walled garden), not a "
        "third-party ecosystem, so it must NOT be unioned in. "
        "vendor_platform = 'Homematic IP'. hub_required=True, "
        "hub_hint='Homematic IP Access Point' (from Hinweise). "
        "power_type=BATTERY. check_compatibility(ecosystem=ALEXA) must "
        "return needs_hardware, not direct -- Datenübertragung is Funk "
        "(868 MHz), not WLAN."
    ),
}

NANOLEAF_28601371 = {
    "id": "28601371",
    "tags": ["Mit Leuchtmittel", "Dimmbar", "LED", "Nicht im Hausmüll entsorgen"],
    "attrs": {
        "Material Leuchtengehäuse": "Kunststoff",
        "Farbe Gehäuse": "Holzoptik",
        "Lichtfarbe": "Mehrfarbig",
        "Stilrichtung": "Trend",
        "Länge": "21 cm",
        "Breite": "23 cm",
        "Gewicht (Netto)": "1 kg",
        "Inkl. Leuchtmittel": "Mit Leuchtmittel",
        "Dimmbarkeit": "Dimmbar",
        "Farbtemperatur": "1.500 K - 4.000 K",
        "Leuchtmittel": "LED",
        "Lichtstrom": "22 lm",
        "Max. Systemleistung": "42 W",
        "Nennspannung": "100 V - 240 V",
        "Smart Home-fähig": "Ja",
        "Smarte Steuerung": "App und Sprachassistenten",
        "Unterstützte Sprachsteuerung": "Amazon Alexa, Google Assistant",
        "Unterstützte Systeme": "Apple HomeKit System",
        "Anwendungsbereich": "Innen",
        "Einsatzbereich": "Esszimmer, Schlafzimmer, Wohnzimmer",
        "Lebensdauer": "25.000 h",
        "Ausführungseigenschaft": "Hexagons",
        "EAN": "840102701661",
    },
    "post_normalize_notes": (
        "THE regression test for the ecosystem-union bug. Ecosystems must "
        "= {ALEXA, GOOGLE_HOME, APPLE_HOME} -- ALEXA and GOOGLE_HOME come "
        "from Unterstützte Sprachsteuerung, APPLE_HOME comes ONLY from "
        "Unterstützte Systeme. A parser that reads just the first key "
        "produces {ALEXA, GOOGLE_HOME} and silently drops HomeKit support. "
        "Also note 'Beständigkeit' header here has exactly ONE pair "
        "(Lebensdauer: 25.000 h) -- confirms the header-detection logic "
        "handles single-pair sections, not just multi-pair ones."
    ),
}

BOSCH_32391327 = {
    "id": "32391327",
    "tags": [],
    "attrs": {},
    "post_normalize_notes": (
        "attributes == '' and description == '' -- the sparsity stress "
        "case. Title is 'Bosch Smart Home Funk-Fensterkontakt II [+M] "
        "Matter': the '[+M] Matter' keyword is the ONLY ecosystem signal "
        "anywhere, so ecosystems={MATTER} at confidence=INFERRED, never "
        "DECLARED (nothing in attrs says so). Subtitle 'Weiß, "
        "Batteriebetrieben, 23 x 22 x 75 mm, 3 Stk.' gives power_type="
        "BATTERY at confidence=INFERRED (keyword match, not a declared "
        "Betriebsart key) and color=Weiß at INFERRED. variants=['1 Stk.', "
        "'3 Stk.'] is a PACK-SIZE ladder (upsell type=volume), not a "
        "tier-up -- must be classified as such, not treated like the TCL's "
        "capacity ladder. Everything else (is_smart, hub_required, fit) "
        "must come out UNKNOWN, not guessed."
    ),
}
