"""Search engine for Specio Catalog.

Pure read-only logic: it receives an open ``CatalogDB`` and returns species
with their photos. It never writes to the database.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from core.catalog_db import CatalogDB
from core.profile_normalize import load_vocab, normalize_profile_fields

__all__ = [
    "normalize",
    "CRITERIA",
    "PhotoResult",
    "SpeciesResult",
    "list_categories",
    "search_species",
]

# --------------------------------------------------------------------- text


def normalize(text: str | None) -> str:
    """Lowercase and strip Romanian diacritics so 'Păpădie' matches 'papadie'."""
    if not text:
        return ""
    lower = text.lower()
    decomposed = unicodedata.normalize("NFD", lower)
    without = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    without = without.replace("\u021b", "t").replace("\u0163", "t")
    return re.sub(r"\s+", " ", without).strip()


def _split_names(raw: str | None) -> list[str]:
    """Split 'Brad; Brad argintiu' into individual name fragments."""
    if not raw:
        return []
    return [part.strip() for part in raw.split(";") if part.strip()]


# ------------------------------------------------------------------ criteria

CRITERIA = {
    "scientific": "Nume stiintific / Scientific name",
    "popular_ro": "Popular RO",
    "popular_en": "Popular EN",
    "any_name": "Oricare denumire / Any name",
    "profile_text": "Text profil / Profile text",
}


@dataclass
class PhotoResult:
    item_id: int | None
    catalog_path: str
    resolved: Path | None
    manual_location: str | None
    photo_date: str | None
    file_name: str = ""


@dataclass
class SpeciesResult:
    scientific_name: str
    category: str | None
    ro_name: str | None
    en_name: str | None
    profile_response: str | None
    photos: list[PhotoResult] = field(default_factory=list)
    # Layer B: profile_fields_json normalizat la citire (chei canonice,
    # sentinle -> None, sinonime de vocabular); dict gol daca lipsa coloanei.
    profile_fields: dict = field(default_factory=dict)


# ------------------------------------------------------------------ loading


def _parse_profile_fields(raw: str | None, vocab: dict) -> dict:
    """Parse + normalize profile_fields_json (Layer B); malformed -> {}."""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return normalize_profile_fields(data, vocab)


def _load_rows(db: CatalogDB) -> tuple[dict[str, dict], dict[str, list[dict]]]:
    vocab = load_vocab(db.catalog_root)
    columns = {
        r[1]
        for r in db.connection.execute("PRAGMA table_info(species_profiles)")
    }
    has_fields = "profile_fields_json" in columns
    select = (
        "SELECT scientific_name, category, ro_name, en_name, profile_response"
        + (", profile_fields_json" if has_fields else "")
        + " FROM species_profiles"
    )
    profiles: dict[str, dict] = {}
    for row in db.connection.execute(select):
        key = (row["scientific_name"] or "").strip()
        if not key:
            continue
        entry = dict(row)
        raw_fields = entry.pop("profile_fields_json", "") if has_fields else ""
        entry["profile_fields"] = _parse_profile_fields(raw_fields, vocab)
        profiles[key] = entry

    items: dict[str, list[dict]] = {}
    for row in db.connection.execute(
        "SELECT id, scientific_name, ro_name, en_name, category, catalog_path,"
        " manual_location, metadata_json FROM catalog_items"
    ):
        key = (row["scientific_name"] or "").strip()
        if key:
            items.setdefault(key, []).append(dict(row))
    return profiles, items


def _photo_from_item(db: CatalogDB, item: dict) -> PhotoResult:
    raw_meta = item.get("metadata_json")
    date = None
    if raw_meta:
        try:
            meta = json.loads(raw_meta)
            date = meta.get("photo_date") or meta.get("file_created") or None
        except (ValueError, TypeError):
            date = None
    catalog_path = item.get("catalog_path") or ""
    return PhotoResult(
        item_id=item.get("id"),
        catalog_path=catalog_path,
        resolved=db.resolve_photo(catalog_path),
        manual_location=item.get("manual_location"),
        photo_date=date,
        file_name=Path(catalog_path).name,
    )


# ------------------------------------------------------------------ searching


def list_categories(db: CatalogDB) -> list[str]:
    """Distinct categories (profiles + items), sorted, case-insensitive."""
    seen: dict[str, str] = {}
    for table in ("species_profiles", "catalog_items"):
        for (value,) in db.connection.execute(
            f"SELECT DISTINCT category FROM {table}"  # noqa: S608 - fixed table
        ):
            if value:
                key = value.strip()
                if key:
                    seen.setdefault(normalize(key), key)
    return sorted(seen.values(), key=str.lower)


def _name_match(query_norm: str, names: str | None) -> bool:
    """Substring match, both directions, per individual ';'-separated name."""
    for fragment in _split_names(names):
        frag_norm = normalize(fragment)
        if frag_norm and (query_norm in frag_norm or frag_norm in query_norm):
            return True
    return False


def _matches(
    sci: str,
    criterion: str,
    query_norm: str,
    profile: dict | None,
    item_list: list[dict],
) -> bool:
    if not query_norm:
        return True
    ro = profile.get("ro_name") if profile else None
    en = profile.get("en_name") if profile else None
    ro_items = [i.get("ro_name") for i in item_list if i.get("ro_name")]
    en_items = [i.get("en_name") for i in item_list if i.get("en_name")]
    ro_all = ro or (ro_items[0] if ro_items else None)
    en_all = en or (en_items[0] if en_items else None)
    sci_norm = normalize(sci)
    if criterion == "scientific":
        return query_norm in sci_norm
    if criterion == "popular_ro":
        return _name_match(query_norm, ro_all)
    if criterion == "popular_en":
        return _name_match(query_norm, en_all)
    if criterion == "profile_text":
        text = profile.get("profile_response") if profile else None
        if not text:
            return False
        haystack = normalize(text)
        if query_norm in haystack:
            return True
        # Text copied out of the profile rarely survives verbatim: a sentence
        # the user re-typed gains a full stop, the profile continues with a
        # comma, or a word is hyphenated differently. Falling back to "every
        # word is somewhere in the text" makes a pasted paragraph find its
        # own species. Only for longer queries, so ordinary one- or two-word
        # lookups keep their exact behaviour.
        words = [
            re.sub(r"[^\w]+$", "", w)
            for w in query_norm.split()
        ]
        words = [w for w in words if len(w) >= 3]
        if len(words) >= 4 and all(w in haystack for w in words):
            return True
        return False
    # any_name and unknown criteria fall back to any-name matching
    return (
        query_norm in sci_norm
        or _name_match(query_norm, ro_all)
        or _name_match(query_norm, en_all)
    )


def search_species(
    db: CatalogDB,
    query: str = "",
    criterion: str = "any_name",
    category: str | None = None,
) -> list[SpeciesResult]:
    """Return species matching the query, with their photos attached.

    An empty query matches everything (full catalog listing). Species that
    have photos but no profile are included, with ``profile_response=None``.
    """
    profiles, items = _load_rows(db)
    query_norm = normalize(query)
    category_norm = normalize(category) if category else None

    def category_ok(cat: str | None) -> bool:
        return not category_norm or normalize(cat) == category_norm

    results: list[SpeciesResult] = []
    for sci in sorted(set(profiles) | set(items), key=str.lower):
        profile = profiles.get(sci)
        item_list = items.get(sci, [])
        if not category_ok(profile.get("category") if profile else None) and not any(
            category_ok(i.get("category")) for i in item_list
        ):
            continue
        if not _matches(sci, criterion, query_norm, profile, item_list):
            continue
        photos = sorted(
            (_photo_from_item(db, it) for it in item_list),
            key=lambda p: (p.photo_date or "", p.file_name.lower()),
        )
        if profile is not None:
            cat = profile.get("category")
            ro, en = profile.get("ro_name"), profile.get("en_name")
        else:
            cat = item_list[0].get("category") if item_list else None
            ro = next((i.get("ro_name") for i in item_list if i.get("ro_name")), None)
            en = next((i.get("en_name") for i in item_list if i.get("en_name")), None)
        results.append(
            SpeciesResult(
                scientific_name=sci,
                category=cat,
                ro_name=ro,
                en_name=en,
                profile_response=profile.get("profile_response") if profile else None,
                photos=photos,
                profile_fields=profile.get("profile_fields") if profile else {},
            )
        )
    return results


def suggest_names(db: CatalogDB, prefix: str, limit: int = 10) -> list[str]:
    """Autocomplete suggestions for the search box.

    Accepts a prefix of >=3 characters and returns up to `limit` scientific
    names whose normalized form contains that prefix (case-insensitive).
    Falls back to `catalog_items` if no profile matches. Uses the existing
    `normalize()` helper for diacritic-insensitive matching.
    """
    if len(prefix) < 3:
        return []

    q = f"%{prefix}%"

    rows = db.connection.execute(
        "SELECT DISTINCT scientific_name FROM species_profiles "
        "WHERE scientific_name LIKE ? COLLATE NOCASE "
        "ORDER BY scientific_name LIMIT ?",
        (q, limit),
    ).fetchall()

    # If no profile matches, try raw catalog items:
    if not rows:
        rows = db.connection.execute(
            "SELECT DISTINCT scientific_name FROM catalog_items "
            "WHERE scientific_name LIKE ? COLLATE NOCASE "
            "ORDER BY scientific_name LIMIT ?",
            (q, limit),
        ).fetchall()

    return [row["scientific_name"] for row in rows if row["scientific_name"]]

