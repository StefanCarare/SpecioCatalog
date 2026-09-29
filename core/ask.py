"""Grounded question answering over the catalogue's own profiles.

The describe-and-find box turns a description into filters. This module is the
other half: once species are on screen, the model is handed their actual profile
texts and asked a question about them. It never searches the catalogue and it
never names a species it was not given, so the database stays the only source
of truth while the answer reads like a conversation.

Like core/describe.py this is pure prompt building plus parsing - no Tk, no
Ollama, no database - so the rules can be tested without a model.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field

from core.search import SpeciesResult, normalize

__all__ = [
    "QaTurn", "build_qa_prompt", "max_profiles", "detect_group", "GROUP_WORDS",
]

# How many profiles the answer phase is allowed to quote. Ten is not a
# guess: measured on this catalogue a profile averages ~3.2k characters, so
# ten is about 9k tokens - which needs a 16k context window, see
# describe_num_ctx. At five the model ran out of profiles mid-list and started
# answering about the tenth species from memory instead, with invented traits.
MAX_PROFILES = 10
MAX_PROFILE_CHARS = 4200

# Words that name a group, matched on the diacritic-stripped question so both
# "păsări" and "pasari" land on Bird. Stripping diacritics leaves several
# spellings people really type, so variants are listed side by side.
GROUP_WORDS: dict[str, tuple[str, ...]] = {
    "Plant": ("planta", "plante", "plant", "flori", "floare", "arbore",
              "arbori", "frunza", "frunze", "iarba", "ierburi", "raspadatura"),
    "Bird": ("pasare", "pasari", "plasanice", "plasanici", "randunica",
             "porumbel", "ciocrilie", "ciobanesc", "gaina", "gaini", "vrabie",
             "ciocarlie", "uliu", "corb", "bufnita"),
    "Mammal": ("mamifer", "mamifere", "caine", "pisica", "urs", "lup", "iepure",
               "capra", "mistret", "carabus", "vulpe", "jigane"),
    "Insect": ("insecta", "insecte", "fluture", "fluturi", "albine", "albina",
               "furnica", "furnici", "greiere", "libela", "tantar", "molia"),
    "Reptile": ("reptila", "reptile", "sarpe", "serpi", "broasca testoasa",
                "testoasa", "iguana", "crocodil"),
    "Amphibian": ("amfibian", "amfibieni", "broasca", "broasta", "broasa",
                  "broaste", "rana", "triton", "salamandra"),
}


def detect_group(question: str | None) -> str | None:
    """The catalogue group a question names, or None if it names none.

    The first group mentioned wins, because that is the one the sighting is
    about: "o planta si o pasare in gradina" is a plant question with a bird
    in passing, not the reverse. A longer phrase starting at the same spot
    ("broasca testoasa") beats a shorter one.
    """
    text = normalize(question)
    if not text:
        return None
    best: tuple[int, int, str] | None = None
    for group, words in GROUP_WORDS.items():
        for word in words:
            match = re.search(rf"\b{re.escape(word)}\b", text)
            if match is None:
                continue
            key = (match.start(), -len(word), group)
            if best is None or key < best:
                best = key
    return best[2] if best else None


@dataclass
class QaTurn:
    """One exchange, kept so follow-ups can refer back to earlier answers."""

    question: str
    answer: str
    species: list[str] = dc_field(default_factory=list)


def _profile_text(res: SpeciesResult) -> str:
    text = (res.profile_response or "").strip()
    if not text:
        return "(fără profil generat)"
    if len(text) > MAX_PROFILE_CHARS:
        text = text[:MAX_PROFILE_CHARS].rsplit(" ", 1)[0] + " […]"
    return text


def build_qa_prompt(
    species: list[SpeciesResult],
    question: str,
    history: list[QaTurn] | None = None,
    language: str = "ro",
) -> str:
    """The exact text sent to the model for one question.

    ``species`` are the candidates currently on screen - the database produced
    them, and only they are quoted, so the model has nothing else to speak of.
    """
    en = language == "en"
    chunks = []
    for res in species[:MAX_PROFILES]:
        chunks.append(
            f"### {res.scientific_name} ({(res.ro_name or res.en_name or '').strip()})\n"
            f"{_profile_text(res)}"
        )
    catalogue = "\n\n".join(chunks) or "(nicio specie)"

    if en:
        head = (
            "You answer questions about real species, using ONLY the species "
            "profiles quoted below. You cannot look anything up.\n"
        )
        rules = [
            "Rules:",
            "- Answer only from these profiles. If a profile does not state",
            "  something, say plainly that it does not.",
            "- Never use general knowledge to fill a gap, and never mention a",
            "  species that is not quoted here.",
            "- Be brief: a few sentences, or one line per species.",
            "- The reader may not know botanical terms. The first time you use",
            "  a technical word, add a short parenthesis in plain words, e.g.",
            "  'zigomorfă (flori cu simetrie bilaterală)'. Once per term, not",
            "  for every mention, and never define a species name.",
            "- If the question is about a species not in the list, say so and",
            "  name the ones you do have.",
        ]
    else:
        head = (
            "Răspunzi la întrebări despre specii reale, folosind DOAR "
            "profilele citate mai jos. Nu poți căuta nimic.\n"
        )
        rules = [
            "Reguli:",
            "- Răspunde doar din aceste profiluri. Dacă un profil nu spune",
            "  ceva, spune clar că nu spune.",
            "- Nu completa cu cunoștințe generale și nu menționa specii care",
            "  nu sunt citite aici.",
            "- Fii scurt: câteva propoziții sau un rând per specie.",
            "- Cititorul poate să nu cunoască termenii botanici. La prima",
            "  folosire a unui cuvânt tehnic, adaugă o paranteză scurtă în",
            "  limba obișnuită, de exemplu 'zigomorfă (flori cu simetrie",
            "  bilaterală)'. O dată pe termen, nu la fiecare apariție, și nu",
            "  defini niciodată numele unei specii.",
            "- Dacă întrebarea e despre o specie care nu e în listă, spune-o",
            "  și numește speciile pe care le ai.",
        ]
    parts = [head, ""]
    if history:
        lines = []
        for turn in history[-4:]:
            asked = turn.question.strip().replace("\n", " ")
            lines.append(f"Utilizator: {asked}\nTu: {turn.answer.strip()}")
        if en:
            parts += ["Earlier in this conversation:", "\n\n".join(lines), ""]
        else:
            parts += ["Conversația anterioară:", "\n\n".join(lines), ""]
    label = "Species profiles you may use" if en else "Profilurile speciilor pe care le poți folosi"
    parts += ["\n".join(rules), "", f"--- {label} ---", catalogue, ""]
    parts += [
        (f"Question: {question}" if en else f"Întrebare: {question}"),
        "",
        ("Answer:" if en else "Răspuns:"),
    ]
    return "\n".join(parts)
