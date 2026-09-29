"""Taxonomic tree for Specio Catalog.

Builds a Regn → Încrengătură → Clasă → Ordin → Familie → Gen → Specie
hierarchy restricted to the species actually present in the catalog.
Lineages are read from the SpecioIdentify ``col/taxonomy.db`` (read-only);
results are cached in Specio Catalog's own ``cache/`` folder so the 900 MB
taxonomy database is only queried for species not seen before.

Resolution strategy per species name:
1. exact ``rank='species'`` match (unique only);
2. genus fallback: resolve the first word as ``rank='genus'`` and hang the
   species under that genus (covers names missing from the CoL snapshot,
   e.g. ornamental cultivars and recent splits);
3. unresolvable names go under the "other" branch (``None`` key).

Ambiguous genus names (e.g. ``Iris`` — insect or plant) are disambiguated
with the catalog category when provided (Plant → kingdom Plantae, animal
groups → Animalia, ...).
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from core.catalog_db import CatalogDB

__all__ = [
    "find_taxonomy_db",
    "get_lineages",
    "build_tree",
    "KINGDOM_FOR_CATEGORY",
]

# Rank columns in taxonomy.db, from the top of the hierarchy down to genus.
LINEAGE_COLS = (
    "lineage_kingdom",
    "lineage_phylum",
    "lineage_class",
    "lineage_order",
    "lineage_family",
    "lineage_genus",
)

KINGDOM_FOR_CATEGORY = {
    "plant": "plantae",
    "fungus": "fungi",
    "fungi": "fungi",
    "bird": "animalia",
    "mammal": "animalia",
    "fish": "animalia",
    "insect": "animalia",
    "arachnid": "animalia",
    "mollusc": "animalia",
}

CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"
CACHE_FILE = CACHE_DIR / "lineage_cache_v2.json"

_CAMEL_RE = re.compile(r"(?<=[a-z])(?=[A-Z])")


def _load_cache() -> dict:
    if CACHE_FILE.is_file():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(
            json.dumps(cache, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
    except OSError:
        pass  # cache is best-effort; the app works without it


def _clean_chain(raw: tuple) -> list[str]:
    """Lineage columns → non-empty, de-duplicated chain."""
    chain: list[str] = []
    for value in raw:
        text = (value or "").strip()
        if text and text not in chain:
            chain.append(text)
    return chain


def _resolve(con: sqlite3.Connection, name: str, category: str | None) -> list[str]:
    cols = ", ".join(LINEAGE_COLS)
    wanted = KINGDOM_FOR_CATEGORY.get((category or "").strip().lower())

    # 1. exact species match
    rows = con.execute(
        f"SELECT rank, {cols} FROM taxa WHERE name = ? LIMIT 6", (name,)
    ).fetchall()
    species = [r for r in rows if str(r[0] or "").strip().lower() == "species"]
    if len(species) == 1:
        return _clean_chain(tuple(species[0][1:]))

    # "ConcatenatedName" → "Concatenated Name" (data-entry slips)
    if " " not in name:
        fixed = _CAMEL_RE.sub(" ", name)
        if fixed != name:
            rows = con.execute(
                f"SELECT rank, {cols} FROM taxa WHERE name = ? LIMIT 6", (fixed,)
            ).fetchall()
            species = [
                r for r in rows if str(r[0] or "").strip().lower() == "species"
            ]
            if len(species) == 1:
                return _clean_chain(tuple(species[0][1:]))

    # 2. genus fallback — chain of the genus row, species hung under it
    genus = name.split()[0] if " " in name else _CAMEL_RE.split(name)[0]
    rows = con.execute(
        f"SELECT rank, {cols} FROM taxa WHERE name = ? LIMIT 12", (genus,)
    ).fetchall()
    genera = [r for r in rows if str(r[0] or "").strip().lower() == "genus"]
    if genera:
        chosen = genera[0]
        if len(genera) > 1 and wanted:
            for row in genera:
                kingdom = str(row[1] or "").strip().lower()
                if kingdom == wanted:
                    chosen = row
                    break
        chain = _clean_chain(tuple(chosen[1:]))
        if genus not in chain:
            chain.append(genus)
        return chain
    return []


def find_taxonomy_db(catalog_root: Path) -> Path | None:
    """Taxonomy database of the SpecioIdentify project (``col/taxonomy.db``)."""
    candidate = Path(catalog_root) / "col" / "taxonomy.db"
    return candidate if candidate.is_file() else None


def get_lineages(
    catalog_root: Path,
    names: list[str],
    categories: dict[str, str] | None = None,
) -> dict[str, list[str]]:
    """Lineage chain (kingdom..genus) for each cataloged species name.

    ``categories`` maps scientific name → catalog category (used only to
    disambiguate genus names shared across kingdoms). Names that cannot be
    resolved map to an empty chain (the "other" branch of the tree).
    """
    categories = categories or {}
    cache = _load_cache()
    missing = [n for n in names if n not in cache]
    if missing:
        tax_db = find_taxonomy_db(catalog_root)
        if tax_db is not None:
            uri = tax_db.resolve().as_uri() + "?mode=ro"
            try:
                con = sqlite3.connect(uri, uri=True)
            except sqlite3.OperationalError:
                con = None
            if con is not None:
                try:
                    for name in missing:
                        # Name-only WHERE (never add rank: SQLite would pick
                        # idx_taxa_rank and scan millions of rows).
                        cache[name] = _resolve(con, name, categories.get(name))
                finally:
                    con.close()
                _save_cache(cache)
        else:
            for name in missing:
                cache[name] = []
    return {name: cache.get(name, []) for name in names}


def build_tree(
    catalog_root: Path,
    names: list[str],
    categories: dict[str, str] | None = None,
) -> dict:
    """Nested dict ``{kingdom: {...: {genus: {species: {}}}}}``.

    Species without a resolvable lineage go under the ``None`` key
    (displayed as "other groups" in the GUI).
    """
    lineages = get_lineages(catalog_root, names, categories)
    root: dict = {}
    for name in sorted(names, key=str.lower):
        node = root
        for level in lineages.get(name, []):
            node = node.setdefault(level, {})
        node.setdefault(None, []).append(name)
    return root