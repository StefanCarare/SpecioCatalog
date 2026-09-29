"""Layer B — read-time normalization of species profiles (Specio Catalog).

The catalog database is never modified: variant or invented JSON keys are
mapped to the canonical schema, sentinel strings become ``None`` and enum
values are rewritten to the canonical vocabulary before display.

Canonical vocabulary (Layer C) lives in ``config/species_vocab.json`` of the
SpecioIdentify project pointed to by ``catalog_root``; ``DEFAULT_VOCAB`` below
mirrors that file so normalization still works when the JSON is missing.

NOTĂ: DEFAULT_VOCAB este oglinda lui <SpecioIdentify>/config/species_vocab.json
— la o schimbare de schemă (chei/sinonime/vocabular), actualizează AMBELE locuri.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

VOCAB_RELATIVE = Path("config") / "species_vocab.json"

DEFAULT_VOCAB: dict = {
    "version": 1,
    "field_order": [
        "raspandire", "dimensiuni", "habitat", "cuib", "oua", "hrana",
        "port", "tulpina", "frunza_dispozitie", "frunza_forma", "frunza_margine",
        "inflorescenta", "involucru", "petale", "simetrie", "stil", "ovar",
        "fruct", "inflorire", "culoare_floare", "polenizare", "fapt_divers",
        "acoperire", "comportament",
    ],
    "field_labels": {
        "raspandire": "Răspândire",
        "dimensiuni": "Dimensiuni",
        "habitat": "Habitat",
        "cuib": "Cuib",
        "oua": "Ouă",
        "hrana": "Hrană",
        "port": "Port",
        "tulpina": "Tulpina",
        "frunza_dispozitie": "Frunza — dispoziție",
        "frunza_forma": "Frunza — formă",
        "frunza_margine": "Frunza — margine",
        "inflorescenta": "Inflorescență",
        "involucru": "Involucru/Involucel",
        "petale": "Petale",
        "simetrie": "Simetrie",
        "stil": "Stil",
        "ovar": "Ovar",
        "fruct": "Fruct",
        "inflorire": "Înflorire",
        "culoare_floare": "Culoarea florii",
        "polenizare": "Polenizare",
        "fapt_divers": "Fapt divers",
        "acoperire": "Acoperire",
        "comportament": "Comportament",
        # chei vechi de profil pasăre (ex. Gavia arctica) — păstrate ca extra
        "silueta_si_postura": "Siluetă și postură",
        "penaj": "Penaj",
        "cioc": "Cioc",
        "picioare": "Picioare",
        "zbor_si_deplasare": "Zbor și deplasare",
        "vocalizari": "Vocalizări",
    },
    "prose_fields": ["descriere", "identificare"],
    "key_exclude_fields": ["fapt_divers"],  # prea prozaic pentru o întrebare
    "skip_fields": [
        "category", "kingdom", "genus", "species", "scientific_name",
        "ro_name", "en_name", "confidence", "is_uncertain",
    ],
    "sentinels": [
        "", "none", "null", "necunoscut", "necunoscuta", "absent", "absenta",
        "nu se aplic", "nu se aplica", "-", "—",
    ],
    "key_aliases": {
        "culoare_florii": "culoare_floare",
        "culoare_flori": "culoare_floare",
        "frunza_margin": "frunza_margine",
        "h_alimentara": "hrana",
        "infloire": "inflorire",
        "inflorescenta_perioada": "inflorire",
        "invohicru": "involucru",
        "involucel": "involucru",
        "protectie": "comportament",
    },
    "values": {
        "petale": {
            "canonical": [
                "Inexistente", "1", "2", "3", "4", "5", "6", "7",
                "Cel mult 4", "Cel mult 5", "Mai mult de 5", "Sub 5",
                "Peste 5", "5-7", "Reduse",
            ],
            "synonyms": {"inexistent": "Inexistente"},
        },
        "frunza_forma": {
            "canonical": [
                "Lanceolată", "Ovată", "Eliptică", "Cordată", "Palmată",
                "Pennată", "Fiorată", "Aciculară", "Liniară", "Trifoiolată",
                "Dintată", "Reniformă", "Obovată", "Lobată", "Simplă",
                "Compusă", "Triunghiulară", "Romboidală", "Acuminată",
                "Ascuțită", "Asimetrică", "Cuneată", "Deltoidă", "Disecată",
                "Divizată", "Elipsoidă", "Continuă", "Fir", "Hastată",
                "Carenată", "Ligulată", "Oblanceolată", "Oblongată", "Obtuză",
                "Orbiculară", "Ovală", "Pedată", "Penat-fidată",
                "Penat-sectată", "Rombică", "Rozetă", "Runcinată", "Sagitată",
                "Spatulată", "Fusoidală", "Îngustă", "Cordiformă", "Lujeri",
                "În formă de seceră", "Sub formă de suliță",
                "Sub formă de lingură", "Sub formă de sabie",
                "În formă de trifoi",
            ],
            "synonyms": {
                "ovala": "Ovată",
                "trifoliata": "Trifoiolată",
                "penata": "Pennată",
            },
        },
        "frunza_margine": {
            "canonical": [
                "Întreagă", "Dintată", "Serrată", "Crenată", "Lobată",
                "Franjurată", "Sinuată",
            ],
            "synonyms": {
                "dentata": "Dintată",
                "neteza": "Întreagă",
                "netezita": "Întreagă",
                "fin dintata": "Dintată",
                "zimtata": "Dintată",
            },
        },
        "frunza_dispozitie": {
            "canonical": [
                "Opusă", "Alternată", "Spiralată", "Verticilată", "Rozetă",
            ],
            "synonyms": {
                "alterne": "Alternată",
                "alternare": "Alternată",
                "altern": "Alternată",
                "opuse": "Opusă",
                "bazale": "Rozetă",
                "bazala": "Rozetă",
                "in roseta": "Rozetă",
                "roseta": "Rozetă",
                "spiralate": "Spiralată",
                "verticilate": "Verticilată",
            },
        },
        "simetrie": {
            "canonical": ["Actinomorfă", "Zigomorfă", "Nesimetrică"],
            "synonyms": {"asimetrica": "Nesimetrică"},
        },
        "culoare_floare": {
            "canonical": [
                "Alb", "Galben", "Roșu", "Roz", "Mov", "Portocaliu",
                "Albastru", "Verde", "Maro", "Negru", "Gri", "Crem", "Mixt",
                "Violet", "Purpuriu", "Turcoaz", "Visiniu", "Bordo",
                "Cărămiziu", "Auriu", "Alburiu", "Verzui", "Roșcat",
                "Multicolor", "Bicolor", "Indigo", "Liliachiu",
            ],
            "multi": True,
            "synonyms": {
                "alba": "Alb",
                "rosie": "Roșu",
                "galbena": "Galben",
                "albastra": "Albastru",
                "portocalie": "Portocaliu",
                "violeta": "Violet",
                "crema": "Crem",
                "neagra": "Negru",
                "maroniu": "Maro",
                "maronie": "Maro",
                "verzuie": "Verzui",
                "visinie": "Visiniu",
                "caramizie": "Cărămiziu",
                "liliachii": "Liliachiu",
                "roz pal": "Roz",
                "mov-deschis": "Mov",
                "purpurie": "Purpuriu",
                "rosiatice": "Roșu",
                "albastru-violet": "Albastru",
                "galben-portocalie": "Galben",
                "galben-verzui": "Galben",
                "galben-brun": "Galben",
                "roz-purpurie": "Roz",
                "roz-purpuriu": "Roz",
                "roz-violet": "Roz",
            },
        },
        "port": {
            "canonical": ["Plantă erbacee", "Arbust", "Copac", "Liană"],
            "synonyms": {
                "planta erbaceata": "Plantă erbacee",
                "planta erbacea": "Plantă erbacee",
                "planta erbaceana": "Plantă erbacee",
                "arbust sau copac": "Arbust",
            },
        },
        "fruct": {
            "canonical": [
                "Bacă", "Drupă", "Nucă", "Achenă", "Cariopsă", "Samară",
                "Foliculă", "Păstaie", "Silicvă", "Capsulă", "Pomic",
            ],
            "synonyms": {
                "achene": "Achenă",
                "patasa": "Păstaie",
                "nuca (glanda)": "Nucă",
                "nuca (maciulie)": "Nucă",
                "siliqua": "Silicvă",
            },
        },
        "inflorescenta": {
            "canonical": [
                "Floare solitară", "Spic", "Mănunchi", "Compus",
                "Umbeliformă", "Cimă", "Paniculă", "Racem", "Spiralată",
                "Corimb", "Umbelă", "Capitulă", "Spadix", "Calatidiu",
                "Umbelă compusă",
            ],
            "synonyms": {
                "floare solita": "Floare solitară",
                "spica": "Spic",
                "raceme": "Racem",
                "racelim": "Racem",
                "racema": "Racem",
                "ciorchine terminali": "Racem",
                "cime terminale": "Cimă",
                "umbela corimbiforma": "Umbelă",
                "panicul": "Paniculă",
            },
        },
        "involucru": {
            "canonical": ["Prezent", "Absent"],
            "synonyms": {"prezenta": "Prezent"},
        },
        "stil": {
            "canonical": ["1", "2", "3", "4", "5", "6"],
            "synonyms": {"unic": "1", "prezent": "1"},
        },
        "ovar": {
            "canonical": ["Superior", "Inferior"],
            "synonyms": {},
        },
        "habitat": {
            "canonical": [
                "Pajiști și stâncării alpine", "Păduri",
                "Pajiști moderat umede până la mlăștinoase",
                "Pajiști uscate, stepice, coaste și stâncării însorite",
                "Sărături", "Nisipuri", "Ape", "Ruderale și semănături",
            ],
            # „strict”: doar valorile canonice se oferă în filtre; textele
            # vechi nemapate rămân afișate în fișă, dar nu devin opțiuni
            "strict": True,
            "keywords": {
                "saratur": "Sărături",
                "sarat": "Sărături",
                "salin": "Sărături",
                "slatin": "Sărături",
                "nisip": "Nisipuri",
                "dune": "Nisipuri",
                "plaj": "Nisipuri",
                "alpin": "Pajiști și stâncării alpine",
                "subalpin": "Pajiști și stâncării alpine",
                "tundr": "Pajiști și stâncării alpine",
                "montan": "Pajiști și stâncării alpine",
                "curs de ap": "Ape",
                "lac": "Ape",
                "rau": "Ape",
                "parau": "Ape",
                "balt": "Ape",
                "iaz": "Ape",
                "izvor": "Ape",
                "apa": "Ape",
                "ape": "Ape",
                "bazin": "Ape",
                "lagun": "Ape",
                "estuar": "Ape",
                "delta": "Ape",
                "agricol": "Ruderale și semănături",
                "cultur": "Ruderale și semănături",
                "semanatur": "Ruderale și semănături",
                "gradin": "Ruderale și semănături",
                "urban": "Ruderale și semănături",
                "drum": "Ruderale și semănături",
                "ruderal": "Ruderale și semănături",
                "viran": "Ruderale și semănături",
                "abandonat": "Ruderale și semănături",
                "pasun": "Ruderale și semănături",
                "camp": "Ruderale și semănături",
                "parc": "Ruderale și semănături",
                "plantati": "Ruderale și semănături",
                "step": "Pajiști uscate, stepice, coaste și stâncării însorite",
                "savan": "Pajiști uscate, stepice, coaste și stâncării însorite",
                "arid": "Pajiști uscate, stepice, coaste și stâncării însorite",
                "uscat": "Pajiști uscate, stepice, coaste și stâncării însorite",
                "stanc": "Pajiști uscate, stepice, coaste și stâncării însorite",
                "pietroas": "Pajiști uscate, stepice, coaste și stâncării însorite",
                "prapast": "Pajiști uscate, stepice, coaste și stâncării însorite",
                "mlastin": "Pajiști moderat umede până la mlăștinoase",
                "turb": "Pajiști moderat umede până la mlăștinoase",
                "faneat": "Pajiști moderat umede până la mlăștinoase",
                "fane": "Pajiști moderat umede până la mlăștinoase",
                "stufaris": "Pajiști moderat umede până la mlăștinoase",
                "trestin": "Pajiști moderat umede până la mlăștinoase",
                "zone umede": "Pajiști moderat umede până la mlăștinoase",
                "padur": "Păduri",
                "lizier": "Păduri",
                "tufis": "Păduri",
                "tufaris": "Păduri",
                "maracinis": "Păduri",
                "marset": "Păduri",
                "poien": "Păduri",
                "mangrov": "Păduri",
            },
            "synonyms": {},
        },
        "inflorire": {
            # intervalul lunilor de înflorire (3 litere, cratimă lungă), în ordine
            # calendaristică; flagul „months” activează parserul de luni din Layer B
            "canonical": [
                "Ian–Mar", "Feb–Apr", "Mar–Apr", "Mar–Mai", "Mar–Iun",
                "Mar–Aug", "Mar–Sep", "Mar–Oct", "Apr–Mai", "Apr–Iun",
                "Apr–Sep", "Apr–Oct", "Mai", "Mai–Iun", "Mai–Iul",
                "Mai–Aug", "Mai–Sep", "Mai–Oct", "Iun–Aug", "Iun–Sep",
                "Iul–Sep", "Iul–Oct", "Sep–Dec", "Ian–Dec",
            ],
            "months": True,
            "strict": True,
            "synonyms": {},
        },
    },
}


# ------------------------------------------------------------------ helpers


def fold(value) -> str:
    """Lowercase + fără diacritice + spații compactate (comparare)."""
    text = unicodedata.normalize("NFD", str(value or "").casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip().strip(".:")


def fold_key(key: str) -> str:
    folded = fold(key).replace(" ", "_")
    return _active_vocab.get("key_aliases", {}).get(folded, folded)


def load_vocab(catalog_root) -> dict:
    """Layer C: <catalog_root>/config/species_vocab.json, altfel DEFAULT_VOCAB."""
    try:
        path = Path(catalog_root) / VOCAB_RELATIVE
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, ValueError):
        pass
    return DEFAULT_VOCAB


_active_vocab: dict = DEFAULT_VOCAB


def _sentinels(vocab: dict) -> set[str]:
    return {fold(s) for s in vocab.get("sentinels", ())}


def _is_sentinel(value, vocab: dict) -> bool:
    if value is None:
        return True
    return fold(value) in _sentinels(vocab)


def _value_spec(vocab: dict, field: str) -> dict | None:
    spec = vocab.get("values", {}).get(field)
    return spec if isinstance(spec, dict) else None


# ------------------------------------------------------- parser de luni

_MONTH_ABBR = [
    "Ian", "Feb", "Mar", "Apr", "Mai", "Iun", "Iul", "Aug", "Sep", "Oct",
    "Noi", "Dec",
]
_MONTH_ALIASES = {  # prescurtări românești + englezești (foldate) -> index lună
    "ian": 0, "jan": 0, "feb": 1, "mar": 2, "apr": 3, "mai": 4, "may": 4,
    "iun": 5, "jun": 5, "iul": 6, "jul": 6, "aug": 7, "sep": 8, "oct": 9,
    "noi": 10, "nov": 10, "dec": 11,
}
_MONTH_RE = re.compile(
    r"(?<!\w)(" + "|".join(sorted(_MONTH_ALIASES, key=len, reverse=True)) + r")"
)
_DASH = "\u2013"


def _normalize_months(value: str) -> str | None:
    """Orice text cu luni -> intervalul canonic („Mar–Mai”; luna unică „Mai”).

    Ex.: „Mai – Iunie”, „Iun–Sep”, „Apr–May”, „Marți–Iunie” (typo) sau „Pe tot
    parcursul anului” -> formă canonică; fără luni recunoscute -> None.
    """
    folded = fold(value)
    if "tot parcursul" in folded or "tot anul" in folded:
        return "Ian" + _DASH + "Dec"
    hits = [
        (m.start(), _MONTH_ALIASES[m.group(1)])
        for m in _MONTH_RE.finditer(folded)
    ]
    if not hits:
        return None
    start, end = hits[0][1], hits[-1][1]
    if end < start:
        start, end = end, start
    if start == end:
        return _MONTH_ABBR[start]
    return _MONTH_ABBR[start] + _DASH + _MONTH_ABBR[end]


def _normalize_scalar(field: str, value, spec: dict):
    if not isinstance(value, str):
        return value
    folded = fold(value)
    target = spec.get("synonyms", {}).get(folded)
    if target:
        return target
    for canon in spec.get("canonical", ()):
        if fold(canon) == folded:
            return canon
    if spec.get("months"):
        parsed = _normalize_months(value)
        if parsed:
            return parsed
    # cuvinte-cheie (ex. habitat): câștigă cel care apare CEL MAI DEVREME în text,
    # doar la început de cuvânt („prăpeli” nu trebuie să declanșeze „ape”)
    best: tuple[int, str] | None = None
    for needle, canon in (spec.get("keywords") or {}).items():
        match = re.search(r"(?<!\w)" + re.escape(needle), folded)
        if match and (best is None or match.start() < best[0]):
            best = (match.start(), canon)
    if best is not None:
        return best[1]
    return value


def _normalize_value(field: str, value, vocab: dict):
    """Sentinel -> None; sinonime/canonice pentru câmpurile enum; multi -> „A, B”."""
    if isinstance(value, bool):
        # ex. „involucru”: true/false din JSON -> „Prezent” / lipsă (None)
        return "Prezent" if value else None
    if _is_sentinel(value, vocab):
        return None
    spec = _value_spec(vocab, field)
    if spec is None or not isinstance(value, str):
        return value
    if spec.get("multi"):
        # profil stocat ca listă: „['Roșie', 'Albă']” -> „Roșie, Albă”
        cleaned = re.sub(r"[\[\]']", "", value)
        parts = [
            part for part in re.split(r"[,;/]+|\bsi\b|\bcu\b", fold(cleaned))
            if part.strip()
        ]
        normalized = []
        for part in parts:
            item = _normalize_scalar(field, part.strip(), spec)
            if item and item not in normalized:
                normalized.append(item)
        return ", ".join(normalized) if normalized else None
    return _normalize_scalar(field, value, spec)


# --------------------------------------------------------------- public API


def normalize_profile_fields(raw: dict, vocab: dict | None = None) -> dict:
    """Layer B: chei canonice (fold + aliasuri), sentinle -> None, valori canonice.

    Cheile necunoscute se păstrează ca atare (nu se pierd date); aliasurile
    care colisionează cu o cheie existentă se rezolvă prioritar pe cea non-null.
    """
    global _active_vocab
    _active_vocab = vocab or DEFAULT_VOCAB
    vocab = _active_vocab
    out: dict = {}
    for key, value in (raw or {}).items():
        canon = fold_key(key)
        norm_value = _normalize_value(canon, value, vocab)
        if canon in out:
            if out[canon] is None and norm_value is not None:
                out[canon] = norm_value
        else:
            out[canon] = norm_value
    return out


def format_structured_items(fields: dict, vocab: dict | None = None) -> list[tuple[str, str]]:
    """[(etichetă, valoare), ...] în ordinea canonică, fără sentinle/nule.

    Câmpurile de prosă (descriere/identificare) și metadatele sunt omise;
    cheile necunoscute apar la final, etichetizate din cheie.
    """
    vocab = vocab or _active_vocab
    order = list(vocab.get("field_order", DEFAULT_VOCAB["field_order"]))
    labels = {**DEFAULT_VOCAB["field_labels"], **vocab.get("field_labels", {})}
    skip = (
        {fold(s) for s in vocab.get("skip_fields", DEFAULT_VOCAB["skip_fields"])}
        | {fold(s) for s in vocab.get("prose_fields", DEFAULT_VOCAB["prose_fields"])}
    )
    order_set = set(order)
    seen: set[str] = set()
    items: list[tuple[str, str]] = []
    for field in order:
        if field in skip or field not in fields:
            continue
        value = fields[field]
        if _is_sentinel(value, vocab):
            continue
        items.append((labels.get(field, field), str(value)))
        seen.add(field)
    for field in sorted(fields):
        if field in seen or field in skip or field in order_set:
            continue
        value = fields[field]
        if _is_sentinel(value, vocab):
            continue
        label = labels.get(field) or field.replace("_", " ").capitalize()
        items.append((label, str(value)))
    return items

