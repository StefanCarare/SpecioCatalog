"""Phase 3 — the "describe and find" box.

The model NEVER names a species. It only picks ``(field, value)`` pairs from a
closed menu built from the candidates that are actually on screen, and
:func:`core.determinator.determine` does the filtering against real profile
data. A value the model paraphrases is snapped to the closest real value above
:data:`SNAP_THRESHOLD`; anything further away is dropped and reported.

That makes an invented species structurally impossible: the candidate set comes
from ``search_species()`` and never from the reply. The only thing the model
controls is which of the real filters to switch on.

Everything here is pure logic — no Tk, no Ollama, no database — so the gate can
be tested without a model or a catalogue.
"""
from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field as dc_field

from core.determinator import Constraint, match_type_for, value_options
from core.profile_normalize import fold
from core.search import normalize

__all__ = [
    "SNAP_THRESHOLD",
    "DescribeReply",
    "build_menu",
    "build_prompt",
    "parse_reply",
    "snap_value",
]

# A paraphrased value is accepted only when it is this close to a real one.
# Tuned against the catalogue's Romanian labels: "rosii" -> "Rosii" is handled
# by fold() exactly; this threshold is for looser phrasings such as
# "padure de fagi" -> "Paduri de fag".
SNAP_THRESHOLD = 0.68

# The reply must be JSON; a bare list is accepted as {"constraints": [...]}.
_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)
_OBJECT = re.compile(r"\{.*\}", re.DOTALL)

# ---------------------------------------------------------------- numbers
#
# Fields like "dimensiuni" hold free prose ("30-90 cm inaltime, 2-5 cm
# diametru"). Lexical similarity cannot judge those: "30 cm" scores 0.77
# against "30-90 cm" purely because the digits line up, which is meaningless.
# So measurements are compared numerically instead, and the comparison is
# self-gating: it only takes over when the typed text and the option both
# contain a number, and when it does it is the final word (no difflib
# fallback) rather than a hint.

# Longest alternative first, so "metri" is never read as the bare "m" that
# would follow it. Without "metri|metru" the unit is dropped, "1-3 metri"
# parses as 1-3 cm, and a 30 cm plant then appears to match "pana la 30 metri".
_UNIT = r"(mm|cm|metri|metru|m)\b"
_RANGE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*[-–—]\s*(\d+(?:[.,]\d+)?)\s*" + _UNIT,
    re.IGNORECASE,
)
_SINGLE = re.compile(r"(\d+(?:[.,]\d+)?)\s*" + _UNIT, re.IGNORECASE)


def _to_cm(value: str, unit: str | None) -> float:
    number = float(value.replace(",", "."))
    unit = (unit or "cm").lower()
    if unit.startswith("mm"):
        return number / 10.0
    if unit.startswith("m"):
        return number * 100.0
    return number


def extract_ranges(text: str) -> list[tuple[float, float]]:
    """Every measurement in ``text`` as a ``(min, max)`` pair in centimetres.

    "30-90 cm" -> [(30.0, 90.0)]; "10-20 cm inaltime, 2-5 cm" -> two ranges;
    "30 cm" -> [(30.0, 30.0)] (an exact claim, not an interval).

    Intervals are consumed first and blanked out before the single-number
    scan. Without that, "30-90 cm" would also yield the exact claims 30 and
    90, and a plant said to be 30 cm would appear to match that range.
    """
    if not text:
        return []
    ranges: list[tuple[float, float]] = []
    for lo, hi, unit in _RANGE.findall(text):
        a, b = sorted((_to_cm(lo, unit), _to_cm(hi, unit)))
        ranges.append((a, b))
    remainder = _RANGE.sub(" ", text)
    for value, unit in _SINGLE.findall(remainder):
        cm = _to_cm(value, unit)
        ranges.append((cm, cm))
    return ranges


def _numeric_match(typed: str, option: str) -> bool | None:
    """Does ``typed`` fall inside what ``option`` actually claims?

    A single figure and a range mean different things, so they are judged
    differently:

    - "30 cm" is a claim of certainty. It is confirmed by an exact figure, or
      by an interval that strictly contains it. An interval that merely
      *starts* at 30 (30-90 cm) does not confirm it: a plant described as
      30-90 cm tall is not thereby known to be 30 cm tall.
    - "13-15 cm" is a request for candidates. Any interval that intersects it
      qualifies, so 12-14, 13-14 and 14-16 all count. Requiring containment
      here would hide real matches whenever the catalogue documents a slightly
      different range for the same bird.

    Both the typed text and the option must contain numbers for this to decide
    anything; otherwise the caller falls back to lexical matching.
    """
    claimed = extract_ranges(typed)
    if not claimed:
        return None
    offered = extract_ranges(option)
    if not offered:
        return None
    for tmin, tmax in claimed:
        is_point = tmin == tmax
        matched = False
        for omin, omax in offered:
            if is_point:
                if omin == omax:
                    matched = matched or tmin == omin
                else:
                    matched = matched or (omin < tmin and tmax < omax)
            else:
                matched = matched or (omin <= tmax and tmin <= omax)
        if not matched:
            return False
    return True


def _numeric_decides(typed: str, options: list[str]) -> bool:
    """True when numbers must decide this field, with no fuzzy fallback."""
    if not extract_ranges(typed):
        return False
    return any(extract_ranges(option) for option in options)


@dataclass
class DescribeReply:
    """Outcome of one turn: what was used, what was corrected, what was lost."""

    constraints: list[Constraint] = dc_field(default_factory=list)
    # Free phrases that could not be mapped to a catalogue value. They are
    # NOT thrown away: they get searched as text inside the profile, which is
    # what "describe and find" is really for. Birds have almost no enum
    # fields (90 distinct cuib values across 98 species), so a closed menu on
    # its own cannot answer a plain description.
    keywords: list[str] = dc_field(default_factory=list)
    # canonical value -> the value the model actually wrote
    snapped: dict[str, str] = dc_field(default_factory=dict)
    # free text the model invented that matched nothing; shown to the user
    dropped: list[str] = dc_field(default_factory=list)
    # field names the model used that are not on the menu
    unknown_fields: list[str] = dc_field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.constraints and not self.keywords


def keep_asked_keywords(keywords, question: str) -> list[str]:
    """Drop keywords that are not in the question.

    The model is asked to expand a description into search terms, and it does
    that well - until it answers a question instead of reading a description.
    Asking about "a deer" once produced the search terms "Cosmopolita" and
    "frequent in areas with fresh water", lifted straight out of a profile.
    Those match nothing the user asked and quietly dilute the ranking.

    A keyword survives if one of its words was actually said, so the model may
    still rephrase, group and singularise - it just may not invent the subject.
    """
    asked = set(normalize(question).split())
    if not asked:
        return list(keywords)
    kept = []
    for keyword in keywords:
        words = normalize(keyword).split()
        if words and any(word in asked for word in words):
            kept.append(keyword)
    return kept


def build_menu(results, vocab: dict) -> dict[str, list[str]]:
    """``{field: [values...]}`` for the fields the user could actually filter on.

    Built with the same :func:`core.determinator.applicable_fields` and
    :func:`core.determinator.value_options` the guided key uses, so the model
    sees exactly the choices the deterministic panel offers — never a value
    that occurs in no candidate.
    """
    from core.determinator import applicable_fields

    menu: dict[str, list[str]] = {}
    for name in applicable_fields(results, vocab):
        options = value_options(results, name, vocab)
        if options:
            menu[name] = options
    return menu


def _menu_block(menu: dict[str, list[str]], vocab: dict) -> str:
    """Render the closed menu as a compact, copy-pasteable list for the model."""
    labels = vocab.get("field_labels") or {}
    lines = []
    for name, options in menu.items():
        label = labels.get(name, name)
        shown = ", ".join(options[:40])
        if len(options) > 40:
            shown += f", ... (+{len(options) - 40})"
        lines.append(f"- {name} ({label}): {shown}")
    return "\n".join(lines)


def build_prompt(
    menu: dict[str, list[str]],
    vocab: dict,
    question: str,
    history: list[tuple[str, list[Constraint]]] | None = None,
    language: str = "ro",
) -> str:
    """The exact text sent to the model for one turn.

    ``history`` is the list of ``(user text, constraints it produced)`` so far,
    which is what makes "e mai inalta" a refinement rather than a fresh search.
    """
    en = language == "en"
    if en:
        head = (
            "You turn a user's plain description of a plant or animal into "
            "filters over a fixed catalogue.\n"
            "Answer with JSON only, no prose:\n"
            '{"constraints": [{"field": "<field>", "value": "<value>"}],'
            ' "keywords": ["<phrase>"]}\n'
        )
        rules = [
            "Rules:",
            "- Use ONLY the fields and values listed below for constraints.",
            "  Copy values exactly as written, including diacritics.",
            "- Only put a trait in constraints if the user stated it EXPLICITLY.",
            "  If you are guessing or inferring, put it in keywords instead.",
            "  An invented habitat can remove perfectly good species.",
            "- Put anything else the user described into keywords: short phrases",
            "  that will be searched as text inside the species profiles.",
            "  Use keywords for things the field list does not cover at all",
            "  (colours of parts, behaviour, markings, habitat detail).",
            "- Only put in keywords words the user actually wrote. Never invent",
            "  details they did not mention.",
            "- A SHORT description is enough. Do not refuse because details are",
            "  missing: extract whatever it does contain, however little.",
            "- If nothing in the description matches, return an empty list.",
            "- Do not name, guess or rank species. You only choose filters.",
        ]
        hist_head, add_head = "Earlier in this conversation:", "The new description adds these filters:"
        menu_head = "Available filters (use these exact fields and values):"
        q_head = f"User's new description: \"{question}\""
    else:
        head = (
            "Transformi descrierea în cuvinte simple a utilizatorului în "
            "filtre peste un catalog fix.\n"
            "Răspunde doar cu JSON, fără explicații:\n"
            '{"constraints": [{"field": "<camp>", "value": "<valoare>"}],'
            ' "keywords": ["<fraza>"]}\n'
        )
        rules = [
            "Reguli:",
            "- Pentru constraints folosește DOAR câmpurile și valorile de mai jos.",
            "  Copiază valorile exact, cu diacritice.",
            "- Pune în constraints doar trăsături pe care utilizatorul le-a spus",
            "  EXPLICIT. Dacă presupui sau deduci ceva, pune în keywords.",
            "  Un habitat inventat poate elimina specii corecte.",
            "- Tot ce nu acoperă lista de câmpuri pune în keywords: fraze scurte",
            "  care vor fi căutate ca text în profilurile speciilor.",
            "  Folosește keywords pentru părți ale corpului, comportament,",
            "  modele de penaj, detalii de habitat.",
            "- Pune în keywords doar cuvinte pe care utilizatorul le-a scris",
            "  efectiv. Nu inventa detalii pe care nu le-a menționat.",
            "- O descriere SCURTĂ e suficientă. Nu refuza pentru că lipsesc",
            "  detalii: extrage ce conține, oricât de puțin ar fi.",
            "- Dacă nimic nu se potrivește, întoarce o listă goală.",
            "- Nu numi, nu ghici și nu ordona specii. Alegi doar filtre.",
        ]
        hist_head, add_head = "Mai devreme în această conversație:", "Descrierea nouă adaugă aceste filtre:"
        menu_head = "Filtre disponibile (folosește exact aceste câmpuri și valori):"
        q_head = f"Descrierea nouă: \"{question}\""

    parts = [head, ""]
    if history:
        lines = []
        for text, constraints in history:
            used = (
                ", ".join(f"{c.field}={c.value}" for c in constraints)
                if constraints
                else "(nothing usable)"
            )
            lines.append(f'- "{text}" -> {used}')
        parts += [hist_head, "\n".join(lines), "", add_head, ""]
    parts += ["\n".join(rules), "", menu_head, _menu_block(menu, vocab), "", q_head, "", "JSON:"]
    return "\n".join(parts)


def snap_value(
    value: str, options: list[str], threshold: float = SNAP_THRESHOLD
) -> tuple[str | None, float]:
    """Closest real option to ``value``, or ``(None, best_ratio)``.

    An exact match after folding wins outright. Otherwise the best
    :class:`difflib.SequenceMatcher` ratio is returned so the caller decides
    whether it is close enough — that decision is never made here.
    """
    needle = fold(value)
    if not needle:
        return None, 0.0
    for option in options:
        if fold(option) == needle:
            return option, 1.0
    if not options:
        return None, 0.0
    # Measurements are decided numerically, never by string similarity, and
    # there is no difflib fallback: "30 cm" must not fall back onto "30-90 cm"
    # just because the digits line up.
    if _numeric_decides(value, options):
        for option in options:
            if _numeric_match(value, option):
                return option, 1.0
        return None, 0.0
    matches = difflib.get_close_matches(
        needle, [fold(o) for o in options], n=1, cutoff=0.0
    )
    if not matches:
        return None, 0.0
    best_folded = matches[0]
    ratio = difflib.SequenceMatcher(None, needle, best_folded).ratio()
    for option in options:
        if fold(option) == best_folded:
            return option, ratio
    return None, ratio


def _field_by_name(field_name: str, menu: dict[str, list[str]]) -> str | None:
    """The menu field whose key sits inside the name the model wrote.

    Models translate or expand the canonical key rather than inventing it:
    "numar_petale" for "petale", "culoarea_florii" for "culoare_floare". One
    key being contained in the other is a strong signal, and far more reliable
    than string similarity, which rates "numar_petale" against "petale" at
    only 0.63.
    """
    needle = fold(field_name)
    if not needle:
        return None
    contained = [name for name in menu if name != field_name and (
        fold(name) in needle or needle in fold(name)
    )]
    if len(contained) == 1:
        return contained[0]
    if contained:
        # Several keys are inside the name ("inflorire" inside "perioada_inflorire"
        # and "inflorire_culori"); take the longest, the most specific one.
        return max(contained, key=lambda n: len(fold(n)))
    return None


def _field_by_value(
    value: str, menu: dict[str, list[str]], vocab: dict, threshold: float
) -> str | None:
    """The one menu field whose options contain ``value``, if it is unique.

    Only enum/multi fields count. A prose field could match by accident, and
    picking one of those would pin a whole sentence as a filter.
    """
    hits = []
    for name, options in menu.items():
        if match_type_for(name, vocab) == "text":
            continue
        if any(fold(option) == fold(value) for option in options):
            hits.append(name)
    return hits[0] if len(hits) == 1 else None


def _extract_json(raw: str) -> dict | list | None:
    """Pull the JSON out of a reply that may be fenced or chatty."""
    if not raw:
        return None
    text = _FENCE.sub("", raw.strip())
    try:
        return json.loads(text)
    except ValueError:
        pass
    match = _OBJECT.search(text)
    if match:
        try:
            return json.loads(match.group(0))
        except ValueError:
            return None
    return None


def parse_reply(
    raw: str,
    menu: dict[str, list[str]],
    vocab: dict,
    threshold: float = SNAP_THRESHOLD,
) -> DescribeReply:
    """The gate. Turns a model reply into constraints that exist in the data.

    A pair survives only if its field is on the menu AND its value snaps to a
    real option above ``threshold``. Everything else is recorded in the result
    so the UI can say what was ignored — dropping a filter silently would make
    the results look wrong for no visible reason.
    """
    reply = DescribeReply()
    payload = _extract_json(raw)
    if payload is None:
        return reply
    items = payload.get("constraints") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        items = []

    def _keep_phrase(phrase: str) -> None:
        text = str(phrase or "").strip()
        # A lone number or a stop-word would match noise; phrases only.
        if len(text) >= 3 and text.casefold() not in reply.keywords:
            if not any(text.casefold() == k.casefold() for k in reply.keywords):
                reply.keywords.append(text)

    # Keywords the model offered up front are searched as free text.
    raw_keywords = payload.get("keywords") if isinstance(payload, dict) else None
    if isinstance(raw_keywords, list):
        for word in raw_keywords:
            if isinstance(word, str):
                _keep_phrase(word)

    seen: set[tuple[str, str]] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        field_name = str(item.get("field") or "").strip()
        value = str(item.get("value") or "").strip()
        if not value:
            continue
        if not field_name:
            # No field at all: the model plainly meant a text search.
            _keep_phrase(value)
            continue
        options = menu.get(field_name)
        if options is None:
            # The model often translates the key ("numar_petale" for "petale").
            # The value survives the mistranslation even when the field name
            # does not, and a value that exists in exactly one menu field
            # identifies that field unambiguously - "5" belongs to petale and
            # to nothing else. Losing the petal count that way turned a good
            # description into an empty result.
            guess = _field_by_name(field_name, menu)
            if guess is None:
                guess = _field_by_value(value, menu, vocab, threshold)
            if guess:
                canonical, ratio = snap_value(value, menu[guess], threshold)
                if canonical and ratio >= threshold:
                    if canonical != value:
                        reply.snapped[canonical] = value
                    reply.constraints.append(Constraint(
                        field=guess, value=canonical,
                        match=match_type_for(guess, vocab),
                    ))
                    continue
            reply.unknown_fields.append(field_name)
            # The field is unknown, but the words may still be in a profile.
            _keep_phrase(value)
            continue
        # Enum and multi fields hold a short fixed vocabulary, so snapping to
        # the nearest entry is meaningful. A prose field ("dimensiuni" has 93
        # different sentences for 98 birds) does not: pinning one arbitrary
        # overlapping sentence would exclude the very species being asked for,
        # so those phrases stay keywords and are ranked against the text.
        if match_type_for(field_name, vocab) == "text":
            _keep_phrase(value)
            continue
        canonical, ratio = snap_value(value, options, threshold)
        if canonical is None or ratio < threshold:
            reply.dropped.append(f"{field_name}={value}")
            # Not a catalogue value - but "13-15 cm lungime" is exactly the
            # kind of phrase the profile text does contain.
            _keep_phrase(value)
            continue
        if canonical != value:
            reply.snapped[canonical] = value
        key = (field_name, canonical)
        if key in seen:
            continue
        seen.add(key)
        reply.constraints.append(
            Constraint(
                field=field_name,
                value=canonical,
                match=match_type_for(field_name, vocab),
            )
        )
    return reply

    return "\n".join(parts)

    menu: dict[str, list[str]] = {}
    for name in applicable_fields(results, vocab):
        options = value_options(results, name, vocab)
        if options:
            menu[name] = options
    return menu
