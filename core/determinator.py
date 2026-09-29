"""Phase A — determinator: species filtered by observed traits.

Pure read-only logic on top of :class:`core.search.SpeciesResult` whose
``profile_fields`` are already normalized (Layer B). The catalog database
is never touched.

Rules:
* a constraint whose species value is unknown (``None`` after Layer B)
  does NOT exclude the species — it marks it "incomplete";
* a known value that does not match excludes the species (hard filter);
* "exact" = every constraint matched; "incomplete" = all known constraints
  matched but >=1 constraint unknown for that species.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field

from core.profile_normalize import fold
from core.search import SpeciesResult

__all__ = [
    "Constraint",
    "KeyStep",
    "MatchResult",
    "applicable_fields",
    "determine",
    "filter_field_labels",
    "key_step",
    "match_type_for",
    "resolve_field",
    "value_options",
]

_MULTI_SPLIT = re.compile(r"[;,/]")

# Guided dichotomous key: caps that keep a question readable.
KEY_MAX_TEXT_OPTIONS = 8    # observed states of a text field usable as a question
KEY_MAX_TEXT_OPTION_CHARS = 40  # mirrors the button label truncation in the GUI
KEY_MAX_ENUM_OPTIONS = 30   # enum/multi states (fixed vocabularies may be rich)
KEY_MAX_UNKNOWN_RATIO = 0.75  # skip questions mostly unknown for the candidates

_LIST_WRAP = re.compile(r"[\[\]'\"]")


def _strip_list_wrapper(text: str) -> str:
    """„['Roșie', 'Albă']” (profil stocat ca listă) -> „Roșie, Albă”."""
    return _LIST_WRAP.sub("", text)


def _any_canonical(values: list[str], spec: dict) -> bool:
    """True dacă măcar o valoare (deja foldată) e în vocabularul canonic.

    Month fields are the exception: their vocabulary lists spans ("Mar-Apr")
    but never the single months, so a bare "Mar" counts as canonical as soon
    as some listed span contains it. Without this, a real month the user
    typed was reported back as unknown and the filter was silently dropped.
    """
    canon = {fold(c) for c in (spec.get("canonical") or ())}
    for value in values:
        if value in canon:
            return True
    if spec.get("months"):
        for value in values:
            span = month_span(value)
            if span is None:
                continue
            for name in canon:
                other = month_span(name)
                if other and span <= other:
                    return True
    return False


@dataclass
class Constraint:
    field: str  # canonical key (Layer C)
    value: str  # user-chosen / typed value
    match: str = "text"  # "enum" | "multi" | "text"


@dataclass
class MatchResult:
    species: SpeciesResult
    status: str  # "exact" | "incomplete"
    matched: list[str] = dc_field(default_factory=list)
    unknown: list[str] = dc_field(default_factory=list)


@dataclass
class KeyStep:
    """One question of the guided dichotomous key.

    ``options`` pairs each observed value with the number of candidates that
    REMAIN when it is chosen (identical semantics to :func:`determine`);
    ``unknown`` counts candidates without a known value for the field — they
    survive any answer as "incomplete".
    """
    field: str              # canonical key
    label: str              # display label from vocab field_labels
    options: list[tuple[str, int]]  # (value, remaining candidates), best first
    unknown: int            # candidates with no known value for the field
    total: int              # candidates before answering this question


def match_type_for(field_name: str, vocab: dict) -> str:
    """How a constraint on ``field_name`` is compared against profile data."""
    spec = (vocab.get("values") or {}).get(field_name)
    if not spec:
        return "text"
    return "multi" if spec.get("multi") else "enum"


def applicable_fields(results: list[SpeciesResult], vocab: dict) -> list[str]:
    """Canonical fields holding >=1 real value, in vocab order + extras.

    Category filtering already happened in ``search_species``, so the
    fields present in ``results`` are exactly the ones offered to the user.
    """
    order = list(vocab.get("field_order") or [])
    prose = set(vocab.get("prose_fields") or [])
    skip = set(vocab.get("skip_fields") or [])
    key_skip = set(vocab.get("key_exclude_fields") or [])
    present: set[str] = set()
    for res in results:
        for key, val in (res.profile_fields or {}).items():
            if val is None or not str(val).strip():
                continue
            if key in prose or key in skip or key in key_skip:
                continue
            present.add(key)
    extras = sorted(present - set(order), key=str.lower)
    return [f for f in order if f in present] + extras


def value_options(
    results: list[SpeciesResult], field_name: str, vocab: dict
) -> list[str]:
    """Combo options: the values that REALLY occur in ``results``.

    Enum/multi fields keep the canonical order (only the canonical entries
    that occur, then any raw extras sorted); text fields keep the observed
    values sorted. Vocabulary-only values (e.g. a colour no species of the
    current group carries) are never offered — choosing them could only
    produce an empty result.
    """
    spec = (vocab.get("values") or {}).get(field_name)
    canonical = list(spec.get("canonical") or ()) if spec else []
    is_multi = bool(spec and spec.get("multi"))
    observed: dict[str, str] = {}  # folded display -> display
    for res in results:
        val = (res.profile_fields or {}).get(field_name)
        if val is None:
            continue
        text = str(val).strip()
        if not text:
            continue
        chunks = (
            _MULTI_SPLIT.split(_strip_list_wrapper(text))
            if is_multi
            else [text]
        )
        for chunk in chunks:
            chunk = chunk.strip()
            if not chunk:
                continue
            disp = _resolve(chunk, spec) if spec else chunk
            observed.setdefault(fold(disp), disp)
    canon_folds = {fold(c) for c in canonical}
    ordered = [c for c in canonical if fold(c) in observed]
    if spec and spec.get("strict"):
        return ordered  # vocabular fix: restul rămâne doar în fișă, nu în filtru
    extras = [observed[k] for k in sorted(observed) if k not in canon_folds]
    return ordered + extras


def filter_field_labels(typed: str, field_map: dict[str, str]) -> list[str]:
    """Labels whose text or canonical key contains ``typed`` (case-folded).

    ``field_map`` maps display label -> canonical key; insertion order is
    kept and empty input returns every label.
    """
    needle = fold(str(typed).strip())
    if not needle:
        return list(field_map)
    return [
        label
        for label, key in field_map.items()
        if needle in fold(label) or needle in fold(key)
    ]


def resolve_field(typed: str, field_map: dict[str, str]) -> str | None:
    """Canonical key when ``typed`` equals a label or key exactly, else None."""
    needle = fold(str(typed).strip())
    if not needle:
        return None
    for label, key in field_map.items():
        if fold(label) == needle or fold(key) == needle:
            return key
    return None


def _resolve(value: str, spec: dict | None) -> str:
    """Pass ``value`` through the field's synonyms (folded keys).

    Month fields have no synonym table and their vocabulary lists only spans
    ("Mar-Apr"), never the single months. A bare month is therefore left as it
    is and understood by the overlap test, which matches every span holding
    it rather than the one span spelled the same way.
    """
    if not spec:
        return value
    syn = spec.get("synonyms") or {}
    return syn.get(fold(value), value)


# Month values are written as spans ("Mar-Apr"), and the spans overlap: March
# sits inside Mar-Apr, Mar-Mai, Mar-Iun, Mar-Aug and Mar-Sep at once. Equality
# on the written string therefore answers a question nobody asked - "I saw it
# in March" was asking which species flower in March, not which ones are
# labelled exactly "Mar-Apr". Intervals are compared as sets of months instead,
# which is what the user actually means.
_MONTH_ORDER = (
    "ian", "feb", "mar", "apr", "mai", "iun",
    "iul", "aug", "sep", "oct", "noi", "dec",
)
_MONTH_INDEX = {m: i + 1 for i, m in enumerate(_MONTH_ORDER)}
_SPAN_SPLIT = re.compile(r"\s*[-–—]\s*")


def month_span(value: str | None) -> frozenset[int] | None:
    """The set of months a value covers, or None if it is not a month span.

    "Mar" is March, "Mar-Sep" is March through September, and a wrap like
    "Oct-Feb" is read the same way round as the calendar does, so it is
    returned as the two ends rather than a range that runs backwards.
    """
    if not value:
        return None
    text = fold(_strip_list_wrapper(str(value)))
    if not text:
        return None
    parts = [p for p in _SPAN_SPLIT.split(text) if p]
    if not parts or len(parts) > 2:
        return None
    months: set[int] = set()
    for part in parts:
        idx = _MONTH_INDEX.get(part[:3])
        if idx is None:
            return None
        months.add(idx)
    if len(months) == 2:
        start, end = sorted(months)
        months |= set(range(start, end + 1))
    return frozenset(months)


def _months_overlap(wanted: str, actual: str) -> bool | None:
    """Do two month values share at least one month? None if not comparable."""
    left = month_span(wanted)
    right = month_span(actual)
    if left is None or right is None:
        return None
    return bool(left & right)


def _matches(constraint: Constraint, species_value, vocab: dict) -> bool | None:
    """True = match, False = mismatch, None = unknown."""
    if species_value is None or not str(species_value).strip():
        return None
    text = str(species_value).strip()
    spec = (vocab.get("values") or {}).get(constraint.field)
    if constraint.match == "text":
        return fold(constraint.value) in fold(text)
    wanted = fold(_resolve(constraint.value, spec))
    strict = bool(spec and spec.get("strict"))
    if constraint.match == "multi":
        resolved = [
            fold(_resolve(tok, spec))
            for tok in _MULTI_SPLIT.split(_strip_list_wrapper(text))
        ]
        if strict and not _any_canonical(resolved, spec):
            return None  # valoare nemapată -> necunoscut, nu negație
        for item in resolved:
            overlap = _months_overlap(wanted, item)
            if overlap is not None:
                return overlap
        return any(item == wanted for item in resolved)
    resolved = fold(_resolve(text, spec))
    if strict and not _any_canonical([resolved], spec):
        return None  # ex. habitat vechi, doar note de sol -> necunoscut
    # Month fields are spans, so overlap decides, not string equality.
    overlap = _months_overlap(wanted, resolved)
    if overlap is not None:
        return overlap
    return resolved == wanted


def determine(
    results: list[SpeciesResult], constraints: list[Constraint], vocab: dict
) -> tuple[list[MatchResult], list[MatchResult]]:
    """Split ``results`` into (exact, incomplete) for the given constraints.

    Species with at least one hard mismatch are excluded; an empty
    constraint list returns every species as "exact".
    """
    active = [c for c in constraints if c.value and str(c.value).strip()]
    if not active:
        return [MatchResult(species=res, status="exact") for res in results], []
    exact: list[MatchResult] = []
    incomplete: list[MatchResult] = []
    for res in results:
        fields = res.profile_fields or {}
        matched: list[str] = []
        unknown: list[str] = []
        excluded = False
        for c in active:
            verdict = _matches(c, fields.get(c.field), vocab)
            if verdict is None:
                unknown.append(c.field)
            elif verdict:
                matched.append(c.field)
            else:
                excluded = True
                break
        if excluded:
            continue
        status = "incomplete" if unknown else "exact"
        match = MatchResult(
            species=res, status=status, matched=matched, unknown=unknown
        )
        (incomplete if status == "incomplete" else exact).append(match)
    return exact, incomplete


def key_step(
    results: list[SpeciesResult],
    constraints: list[Constraint],
    vocab: dict,
    used: set[str] | frozenset[str] = frozenset(),
) -> KeyStep | None:
    """Best next question of the guided dichotomous key over ``results``.

    Among the unused applicable fields, only those that actually split the
    remaining candidates into >=2 observed states are considered (text fields
    are skipped when they would offer too many near-unique options). The
    winner minimises the worst case: the largest number of candidates that
    can still remain after the BEST possible answer (minimax), ties broken
    by fewer options and vocab order. Returns ``None`` when no discriminating
    question is left (single candidate or all fields single-valued/used).

    Option counts use the very same :func:`_matches` rules as
    :func:`determine`, so what the button shows is what the filter keeps.
    """
    exact, incomplete = determine(results, constraints, vocab)
    candidates = [m.species for m in exact] + [m.species for m in incomplete]
    total = len(candidates)
    if total < 2:
        return None
    labels = vocab.get("field_labels") or {}
    fields = [
        f for f in applicable_fields(candidates, vocab) if f not in used
    ]
    best: tuple[tuple[int, int, int], str, list[tuple[str, int]], int] | None = None
    for idx, f in enumerate(fields):
        match = match_type_for(f, vocab)
        spec = (vocab.get("values") or {}).get(f)
        seen: dict[str, str] = {}  # group key -> display value
        unknown = 0
        for res in candidates:
            raw = (res.profile_fields or {}).get(f)
            if raw is None or not str(raw).strip():
                unknown += 1
                continue
            text = str(raw).strip()
            if match == "multi":
                for tok in _MULTI_SPLIT.split(_strip_list_wrapper(text)):
                    tok = tok.strip()
                    if not tok:
                        continue
                    disp = _resolve(tok, spec)
                    seen.setdefault(fold(disp), disp)
            else:
                disp = _resolve(text, spec) if match == "enum" else text
                if (
                    match == "enum"
                    and spec
                    and spec.get("strict")
                    and not _any_canonical([fold(disp)], spec)
                ):
                    unknown += 1  # nemapat -> necunoscut, nu devine întrebare
                    continue
                seen.setdefault(fold(disp), disp)
        n_states = len(seen)
        if n_states < 2:
            continue  # no split: asking would narrow nothing
        if match == "text" and n_states > KEY_MAX_TEXT_OPTIONS:
            continue  # near-unique sentences make a bad question
        if match == "text" and sum(
            1 for v in seen if len(v) > KEY_MAX_TEXT_OPTION_CHARS
        ) * 3 > n_states:
            continue  # too many options would be truncated on the button
        if match != "text" and n_states > KEY_MAX_ENUM_OPTIONS:
            continue  # rich fixed vocab, but keep the button grid sane
        if total and unknown / total > KEY_MAX_UNKNOWN_RATIO:
            continue  # e.g. a bird-only field surfacing on plants
        options: list[tuple[str, int]] = []
        worst = 0
        min_keep: int | None = None
        for disp in seen.values():
            probe = Constraint(field=f, value=disp, match=match)
            count = sum(
                1
                for res in candidates
                if _matches(
                    probe, (res.profile_fields or {}).get(f), vocab
                )
                is True
            )
            options.append((disp, count))
            keep = count + unknown  # candidates left after this answer
            worst = max(worst, keep)
            min_keep = keep if min_keep is None else min(min_keep, keep)
        if min_keep is None or min_keep >= total:
            # every offered answer would keep everyone (e.g. multi-token
            # overlap where all candidates carry all tokens) — useless
            continue
        options.sort(key=lambda item: (-item[1], item[0]))
        score = (worst, n_states, idx)
        if best is None or score < best[0]:
            best = (score, f, options, unknown)
    if best is None:
        return None
    _, field, options, unknown = best
    return KeyStep(
        field=field,
        label=labels.get(field, field),
        options=options,
        unknown=unknown,
        total=total,
    )
