"""Offline, rule-based reading of ``symptom_text`` for rule D5.

Two detectors, both deliberately conservative and explainable:

1. ``find_safety_hazards`` -- sparks, smoke, fire/burning, gas smell, electric
   shock (the D5 list), with common wording variants. A mention is ignored when
   it is *negated* ("no sparks or smoke"), using a NegEx-style rule: a negation
   cue governs a hazard term if only "filler" tokens (any, visible, signs, of,
   commas, "or", other hazard words...) sit between them. Any other word ends the
   negation scope, so "not cooling, sparks from plug" still reports sparks.

2. ``find_contradictions`` -- symptom text that conflicts with structured fields:
   * fault: the text clearly describes a different fault family from
     ``fault_category`` and says nothing that supports the declared one (the
     brief's example: not_cooling + "door will not close");
   * product: the text names a different appliance and never the declared one;
   * warranty: the text says the warranty expired while the field says
     in_warranty/extended, or vice versa.
   Text that matches no vocabulary at all is never a contradiction: unfamiliar
   wording is not evidence of conflict.

No LLM, no network, no external NLP library. Limitations are listed in
NOTES.md and EXPLANATION.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Optional, Pattern, Tuple

# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------

_CONTRACTIONS = [
    (r"\bwon'?t\b", "will not"),
    (r"\bcan'?t\b", "cannot"),
    (r"\bain'?t\b", "is not"),
    (r"\b(\w+)n't\b", r"\1 not"),  # doesn't/isn't/didn't/don't -> does not ...
]


# Common misspellings of hazard words, mapped to the spelling the detectors
# know. An explicit list, not fuzzy matching: each entry is a whole word, so
# "sparkling" or "smoker" are never rewritten. Applied before detection.
_SPELLING_VARIANTS = {
    "sparkes": "sparks", "sparkz": "sparks", "spraks": "sparks", "sprak": "spark",
    "sparkin": "sparking", "sparkng": "sparking", "sparkign": "sparking", "sprking": "sparking",
    "smok": "smoke", "smoek": "smoke", "smoak": "smoke", "somke": "smoke", "smokin": "smoking",
    "shok": "shock", "shcok": "shock", "shoked": "shocked", "shokd": "shocked",
    "electic": "electric", "elecrtic": "electric", "electrik": "electric", "eletric": "electric",
    "burnig": "burning", "buring": "burning", "brning": "burning",
    "flams": "flames", "flmaes": "flames",
}

# Documented Hinglish (romanised Hindi) phrases common in Indian service tickets,
# rewritten to English the detectors already understand. Phrase-level on
# purpose: "current lag raha hai" (getting a shock) is mapped, but "current"
# alone is not. A negated phrase ("current nahi lag raha") does not match, and
# "nahi" after a hazard word becomes post-negation ("dhuan nahi" -> "smoke no").
_HINGLISH = [
    (r"\bcurrent (lag|maar|aa) (raha|rahi|rahe|gaya|gayi)( hai| tha| thi)?\b", "getting current"),
    (r"\bcurrent (lagta|lagti|lagte|marta|maarta)( hai)?\b", "getting current"),
    (r"\bdhu+a+n?\b|\bdhoo?an\b", "smoke"),
    (r"\bching(a|aa)ri(yan|yaan|ya)?\b", "sparks"),
    (r"\baag (lag gayi|lag gai|lag gaya|lagi|lag|pakad\w*)\b", "caught fire"),
    (r"\baag\b", "fire"),
    (r"\bgas ki (smell|badbu|boo|bu)\b", "smell of gas"),
    (r"\bjal(ne|ane) ki (smell|badbu|boo|bu)\b", "burning smell"),
    (r"\b(nahi|nahin|nahee|nai)( hai| tha| thi)?\b", "no"),
]


def normalise(text: str) -> str:
    t = (text or "").lower()
    t = t.replace("’", "'").replace("‘", "'").replace("`", "'")
    t = re.sub(r"\bdish\s+washer", "dishwasher", t)
    for pattern, repl in _CONTRACTIONS:
        t = re.sub(pattern, repl, t)
    # "doesnt"/"isnt"/"wont" typed without apostrophes
    t = re.sub(r"\b(does|is|did|was|were|has|have|had|are|could|would|should)nt\b", r"\1 not", t)
    t = re.sub(r"\bwont\b", "will not", t)
    t = re.sub(r"\bcant\b", "cannot", t)
    t = re.sub(r"[a-z]+", lambda m: _SPELLING_VARIANTS.get(m.group(0), m.group(0)), t)
    for pattern, repl in _HINGLISH:
        t = re.sub(pattern, repl, t)
    return re.sub(r"\s+", " ", t).strip()


def _c(*patterns: str) -> List[Pattern[str]]:
    return [re.compile(p) for p in patterns]


# --------------------------------------------------------------------------
# 1. Safety hazards
# --------------------------------------------------------------------------

# Product categories where "gas leak" in a service ticket almost always means
# refrigerant (a cooling fault), not a flammable fuel-gas leak. A gas *smell* is
# still treated as a hazard for every category.
_REFRIGERANT_CATEGORIES = {"air_conditioner", "refrigerator"}

_HAZARDS: Dict[str, List[Pattern[str]]] = {
    "sparks": _c(
        r"\bspark(s|ing|ed|y)?\b",
        r"\barc(ing|ed|s)\b",
    ),
    "smoke": _c(r"\bsmok(e|es|ing|ed|y)\b"),
    "fire": _c(
        r"\bfire\b",
        r"\bflames?\b",
        r"\bablaze\b",
        r"\bburn(ing|t|ed)? (smell|odou?r)\b",
        r"\bsmell(s|ed|ing)? (of |like )?(something )?burn(ing|t|ed)\b",
        r"\bscorch(ed|ing|es|marks?)?\b",
        r"\bmelt(ed|ing) (wire|wires|wiring|plug|cable|insulation|socket)\b",
    ),
    "gas smell": _c(
        r"\b(smell|smells|smelled|smelt|smelling|odou?r|stench|whiff) (of|like) (lpg |cooking |natural )?gas\b",
        r"\b(gas|lpg) (smell|odou?r)\b",
        r"\bcarbon monoxide\b",
        r"\b(smell|smells|odou?r) (of|like) rotten eggs?\b",
        r"\brotten eggs? (smell|odou?r)\b",
    ),
    "gas leak": _c(
        r"\b(gas|lpg) leak(s|ing|age|ed)?\b",
        r"\bleak(s|ing|ed)? (lpg|gas)\b",
    ),
    "electric shock": _c(
        r"\b(electric|electrical|electricity) shocks?\b",
        r"\bshock(s|ed|ing)? (me|him|her|them|us|my|someone|anyone|the (user|customer|tech|technician)|when|whenever|if|on touch)\b",
        # verb + up to three words + shock: "gave my son a shock", "felt a mild shock"
        r"\b(got|get|gets|getting|gave|give|gives|giving|received|receiving|felt|feel|feels|feeling)"
        r"( [a-z']+){0,3} shocks?\b(?! absorb)",
        r"\belectrocut\w*",
        r"\b(getting|gets|got|gives|giving|passing) current\b",
        r"\bcurrent (in|on|through|from) (the )?(body|door|handle|metal|frame|tap|cabinet|body of|unit|machine|appliance)\b",
        r"\btingl(e|es|ing)\b",
        r"\bzap(s|ped|ping)?\b",
    ),
}

_HAZARD_LABEL = {
    "sparks": "sparks",
    "smoke": "smoke",
    "fire": "fire or burning",
    "gas smell": "a gas smell",
    "gas leak": "a gas leak",
    "electric shock": "an electric shock",
}

_NEGATION_CUES = {"no", "not", "never", "without", "none", "nor", "neither", "nothing", "cannot"}
# Tokens allowed between a negation cue and the hazard it governs.
_FILLERS = {
    ",", "or", "any", "visible", "sign", "signs", "of", "evidence", "trace", "traces",
    "the", "a", "an", "see", "seen", "saw", "notice", "noticed", "observe", "observed",
    "detect", "detected", "smell", "smelled", "smelt", "there", "is", "was", "were",
    "are", "been", "obvious", "apparent", "other", "from", "like", "did", "does", "do",
    "has", "have", "had", "found", "report", "reported", "mention", "mentioned",
    "burning", "electric", "electrical", "gas", "spark", "sparks", "sparking", "smoke",
    "smoking", "fire", "flames", "flame", "shock", "shocks", "odour", "odor", "signal",
    "real", "actual", "such", "as", "longer", "at", "all", "whatsoever", "caught",
    "on", "it", "ever", "evidence",
}
# "smoke: none", "sparks? no", and Hinglish "chingari bhi nahi" (-> "sparks bhi no")
_POST_NEGATION = re.compile(r"^\s*[:\-?]*\s*(bhi )?(no|none|nil|negative|not (seen|observed|present|reported))\b")
_TOKEN = re.compile(r"[a-z0-9']+|[,;.!?:()\-]")
_SCOPE_WINDOW = 8
_CONTEXT_CHARS = 400  # comfortably more than _SCOPE_WINDOW tokens


@dataclass(frozen=True)
class Hazard:
    kind: str
    phrase: str

    @property
    def label(self) -> str:
        return _HAZARD_LABEL[self.kind]


def _is_negated(norm: str, start: int, end: int) -> bool:
    """NegEx-style check: is the hazard mention at [start, end) negated?

    Walk backwards from the mention over filler tokens until a negation cue
    (negated) or any other word (not negated). Crossing a comma is allowed only
    for a coordinated list ("no sparks, smoke or flames"): an "or"/"nor" must sit
    between cue and mention, or follow the mention. Otherwise a comma starts a new
    clause ("no smoke, burning smell from the back" still reports burning).
    """
    # Post-negation first: "smoke: none", "sparks? no", "chingari bhi nahi".
    if _POST_NEGATION.match(norm[end:]):
        return True
    # Only the nearest tokens matter (scope window), so scan a bounded slice
    # instead of the whole text: keeps detection linear in text length.
    lo = max(0, start - _CONTEXT_CHARS)
    window = norm[lo:start]
    if lo > 0:  # drop a word the slice may have cut in half ("pia|no" must not read as "no")
        window = window.split(" ", 1)[1] if " " in window else ""
    before = _TOKEN.findall(window)
    after = _TOKEN.findall(norm[end:end + 40])
    crossed: List[str] = []
    for tok in reversed(before):
        if tok in _NEGATION_CUES:
            if "," in crossed:
                return any(t in {"or", "nor"} for t in crossed) or (
                    bool(after) and after[0] in {"or", "nor", ","}
                )
            return True
        if tok not in _FILLERS or len(crossed) >= _SCOPE_WINDOW:
            break
        crossed.append(tok)
    return False


def find_safety_hazards(text: str, product_category: Optional[str] = None) -> List[Hazard]:
    norm = normalise(text)
    found: Dict[str, Hazard] = {}
    for kind, patterns in _HAZARDS.items():
        if kind == "gas leak" and product_category in _REFRIGERANT_CATEGORIES:
            continue
        for pattern in patterns:
            for m in pattern.finditer(norm):
                if _is_negated(norm, m.start(), m.end()):
                    continue
                found.setdefault(kind, Hazard(kind, m.group(0)))
                break
            if kind in found:
                break
    return list(found.values())


# --------------------------------------------------------------------------
# 2. Contradictions
# --------------------------------------------------------------------------

# Vocabulary that indicates the text is *about* a fault family. Negation is
# deliberately not applied here: "door will not close" and "not cooling" are
# both topic mentions.
_FAULT_TOPICS: Dict[str, List[Pattern[str]]] = {
    "no_power": _c(
        r"\bno power\b",
        r"\b(dead|lifeless)\b",
        r"\b(will not|does not|did not|cannot|can not|not|never|fails? to|refuses? to) "
        r"(turn(ing)? on|switch(ing)? on|power(ing)? (on|up)|start(s|ing)?|boot(s|ing)?)\b",
        r"\bnothing (happens|works|lights)\b",
        r"\bno (lights?|display|response)\b",
        r"\bpower (failure|problem|issue|loss)\b",
    ),
    "not_heating": _c(
        r"\bheat\w*", r"\bhot\b", r"\bwarm(s|ing)? up\b", r"\b(cold|lukewarm|tepid)\b",
        r"\belement\b", r"\bthermostat\b", r"\bboil\w*", r"\b(cook|cooks|cooking|bake|baking)\b",
    ),
    "not_cooling": _c(
        r"\bcool\w*", r"\bcold\w*", r"\bchill\w*", r"\bfreez\w*", r"\bfrost\w*",
        r"\b(ice|icing|iced)\b", r"\bwarm\w*", r"\bspoil\w*", r"\bcompressor\b",
        r"\brefrigerant\b", r"\bgas (refill|charge|top ?up|filling|leak\w*)\b",
        r"\btemperature\b", r"\bmelt\w*", r"\bthaw\w*", r"\bdefrost\w*",
    ),
    "water_leak": _c(
        r"\bleak\w*", r"\bdrip\w*", r"\bpuddle\w*", r"\bflood\w*", r"\bseep\w*",
        r"\bwater (on|under|around|all over|across|onto) (the )?(floor|ground|kitchen|base|counter)\b",
        r"\bwet (floor|carpet|base|counter)\b", r"\b(pouring|spilling|gushing|overflow\w*)\b",
        r"\bwater (coming|comes|pouring|escaping|spraying|spills|spilling) out\b",
    ),
    "drainage_or_blockage": _c(
        r"\bdrain\w*", r"\bblock\w*", r"\bclog\w*", r"\bchok\w*", r"\bstanding water\b",
        r"\bwater (left|remains|remaining|sitting|stays|stuck|collects)\b",
        r"\b(not|will not|does not) empty\w*", r"\bback(s|ing)? up\b", r"\bpump\b",
    ),
    "noise_or_vibration": _c(
        r"\bnois\w*", r"\bloud\w*", r"\brattl\w*", r"\bvibrat\w*", r"\bbang\w*", r"\bgrind\w*",
        r"\bsqueal\w*", r"\bsqueak\w*", r"\bhum(s|ming)?\b", r"\bbuzz\w*", r"\bknock\w*",
        r"\bclank\w*", r"\bthud\w*", r"\bwhin(e|es|ing)\b", r"\bshak(e|es|ing|y)\b",
        r"\b(walks|walking|moves|moving) (across|around|on)\b", r"\bsound\w*", r"\bclick\w*",
        r"\bscreech\w*",
    ),
    "door_seal_or_latch": _c(
        r"\bdoors?\b", r"\blid\b", r"\blatch\w*", r"\bgasket\w*", r"\bseal\w*", r"\bhinge\w*",
    ),
    "control_panel_or_display": _c(
        r"\bdisplay\w*", r"\bscreen\b", r"\bbuttons?\b", r"\bkey ?pad\b",
        r"\btouch ?(pad|panel|screen|controls?)\b", r"\bpanel\b", r"\bknobs?\b",
        r"\b(lights?|leds?|indicators?) (flash|blink)\w*", r"\b(flashing|blinking)\b",
        r"\bunresponsive\b", r"\btimer\b", r"\bsettings?\b",
    ),
    "electrical_or_control_board": _c(
        r"\b(control|main|circuit|pcb|power|mother) ?board\b", r"\bpcb\b", r"\bwir(e|es|ing)\b",
        r"\bfuses?\b", r"\btrip(s|ped|ping)?\b", r"\b(breaker|mcb|rcd|rccb|elcb)\b",
        r"\bshort(ed)?[ -]circuit\w*", r"\bshorted\b", r"\brelay\b", r"\bcapacitor\b",
        r"\bvoltage\b", r"\belectric\w*", r"\b(socket|outlet|plug)\b",
    ),
    "motor_or_drive": _c(
        r"\bmotor\w*", r"\bdrum\b", r"\bspin\w*", r"\bbelts?\b", r"\bdrive\b",
        r"\b(not|will not|does not|did not|cannot) (turn|turning|rotat\w*|agitat\w*)\b(?! on)",
        r"\bagitat\w*", r"\bbearings?\b", r"\bfan\b", r"\bblower\b", r"\bturntable\b", r"\brotat\w*",
    ),
    "installation_or_setup": _c(
        r"\binstall\w*", r"\bset ?up\b", r"\buneven\b", r"\bwobbl\w*", r"\bnot level\b",
        r"\bmount\w*", r"\bbracket\w*", r"\bduct\w*", r"\bvent(ing)? pipe\b", r"\bflue\b",
        r"\b(inlet|outlet|supply) (hose|pipe)\b", r"\b(hose|pipe) (connect\w*|fitting|kink\w*|loose)\b",
        r"\bconnect(ed|ion|ing)?\b", r"\bnew(ly)? (unit|machine|appliance|delivered|installed)\b",
        r"\bdemo\b", r"\bdeliver\w*", r"\bplumb\w*", r"\b(how to|instructions|manual)\b",
        r"\bfirst (use|time)\b",
    ),
}

# Fault families that legitimately describe the same physical symptom under a
# different label. Undirected. "other" and "installation_or_setup" are
# compatible with everything (installation faults can surface as any symptom).
_COMPATIBLE_PAIRS = [
    ("no_power", "electrical_or_control_board"),
    ("no_power", "control_panel_or_display"),
    ("control_panel_or_display", "electrical_or_control_board"),
    ("not_heating", "not_cooling"),
    ("not_heating", "electrical_or_control_board"),
    ("not_cooling", "electrical_or_control_board"),
    ("not_cooling", "motor_or_drive"),
    ("water_leak", "drainage_or_blockage"),
    ("drainage_or_blockage", "motor_or_drive"),
    ("noise_or_vibration", "motor_or_drive"),
]
_WILDCARD_FAULTS = {"other", "installation_or_setup"}


def _compatible(a: str, b: str) -> bool:
    if a == b or a in _WILDCARD_FAULTS or b in _WILDCARD_FAULTS:
        return True
    return (a, b) in _COMPATIBLE_PAIRS or (b, a) in _COMPATIBLE_PAIRS


_PRODUCT_MENTIONS: Dict[str, List[Pattern[str]]] = {
    "washing_machine": _c(r"\bwashing ?machines?\b", r"\bwasher[ -]?dryer\b", r"\b(front|top)[ -]?loader\b"),
    "refrigerator": _c(r"\bfridges?\b", r"\brefri?d?gerators?\b", r"\bfreezers?\b"),
    "dishwasher": _c(r"\bdishwashers?\b"),
    "oven_or_cooktop": _c(
        r"(?<!microwave )\bovens?\b", r"\bcooktops?\b", r"\bstoves?\b", r"\bhobs?\b",
        r"\bcookers?\b", r"\bburners?\b", r"\bcooking range\b", r"\botg\b",
    ),
    "air_conditioner": _c(r"\bair ?condition\w*", r"\ba/?c\b", r"\baircon\b", r"\b(split|indoor|outdoor) unit\b"),
    "water_heater": _c(r"\bwater ?heaters?\b", r"\bgeysers?\b", r"\bboilers?\b", r"\bimmersion\b"),
    "microwave": _c(r"\bmicrowaves?\b"),
}

_WARRANTY_OUT = _c(
    r"\b(out of|outside|no longer (under|in)|not (under|in|covered by)|expired|without) "
    r"(the |my |its )?(manufacturer'?s? )?warranty\b",
    r"\bwarranty (has |had |is |was )?(expired|ended|lapsed|over|run out|ran out|finished|void(ed)?)\b",
    r"\bno warranty\b",
)
_WARRANTY_IN = _c(
    r"\b(under|in|within|covered by) (the |my |its )?(manufacturer'?s? |extended )?warranty\b",
    r"\bextended warranty\b",
    r"\bwarranty (is )?(valid|active) (till|until|through)\b",
)


@dataclass(frozen=True)
class Contradiction:
    field: str   # "fault_category" | "product_category" | "warranty_status"
    detail: str  # short phrase for the reason sentence


def detect_fault_topics(norm: str) -> List[str]:
    return [fault for fault, pats in _FAULT_TOPICS.items() if any(p.search(norm) for p in pats)]


def _spans(patterns: List[Pattern[str]], norm: str) -> List[Tuple[int, int]]:
    return [m.span() for p in patterns for m in p.finditer(norm)]


def find_contradictions(
    text: str,
    fault_category: Optional[str],
    product_category: Optional[str],
    warranty_status: Optional[str],
) -> List[Contradiction]:
    norm = normalise(text)
    if not norm:
        return []
    out: List[Contradiction] = []

    # Fault family
    if fault_category and fault_category not in _WILDCARD_FAULTS:
        topics = detect_fault_topics(norm)
        if topics and not any(_compatible(fault_category, t) for t in topics):
            described = ", ".join(t.replace("_", " ") for t in topics)
            out.append(Contradiction(
                "fault_category",
                f"text describes {described} but fault_category is {fault_category}",
            ))

    # Appliance named in the text
    if product_category:
        mentioned = [p for p, pats in _PRODUCT_MENTIONS.items() if any(x.search(norm) for x in pats)]
        if mentioned and product_category not in mentioned:
            out.append(Contradiction(
                "product_category",
                f"text refers to a {mentioned[0].replace('_', ' ')} but product_category is {product_category}",
            ))

    # Warranty stated in the text
    if warranty_status in {"in_warranty", "extended", "out_of_warranty"}:
        out_spans = _spans(_WARRANTY_OUT, norm)
        in_spans = [
            s for s in _spans(_WARRANTY_IN, norm)
            if not any(o[0] <= s[0] < o[1] or s[0] <= o[0] < s[1] for o in out_spans)
        ]
        says_out, says_in = bool(out_spans), bool(in_spans)
        if says_out and not says_in and warranty_status in {"in_warranty", "extended"}:
            out.append(Contradiction(
                "warranty_status", f"text says the warranty has ended but warranty_status is {warranty_status}"
            ))
        elif says_in and not says_out and warranty_status == "out_of_warranty":
            out.append(Contradiction(
                "warranty_status", "text says the unit is under warranty but warranty_status is out_of_warranty"
            ))
    return out


ALL_FAULT_TOPICS: FrozenSet[str] = frozenset(_FAULT_TOPICS)
