"""Read-only access to a SpecioIdentify catalog database.

Specio Catalog never modifies the database it reads: connections are opened
with mode=ro, so any accidental write raises immediately.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

__all__ = [
    "CatalogNotReady",
    "CatalogDB",
    "find_default_catalog_roots",
    "resolve_db",
]

REQUIRED_TABLES = ("species_profiles", "catalog_items")


class CatalogNotReady(Exception):
    """The catalog database is missing or has an unexpected schema."""


def resolve_db(catalog_root: str | Path) -> Path:
    """Path of the catalog database for a given SpecioIdentify project root."""
    return Path(catalog_root) / "output" / "catalog.db"


def find_default_catalog_roots() -> list[Path]:
    """Where the Specio Identify project is expected, most likely first.

    The sibling folder wins: the two projects are meant to sit next to each
    other, and ``..\\SpecioIdentify`` says that without hardcoding anybody's
    user name or drive. Specio Identify is the only supported source - it is
    the application that writes ``output\\catalog.db`` - so the fallback list
    stays short on purpose rather than guessing at other project names.
    ``Path.home()`` and the Desktop come last, for a catalogue kept elsewhere.
    """
    from core.config import APP_ROOT

    found: list[Path] = []

    def add(candidate: Path) -> None:
        if candidate.is_dir() and candidate not in found:
            found.append(candidate)

    add(APP_ROOT.parent / "SpecioIdentify")
    for base in (Path.home() / "Desktop", Path.home()):
        add(base / "SpecioIdentify")
    return found


class CatalogDB:
    """Read-only wrapper over ``output/catalog.db`` of a SpecioIdentify project."""

    def __init__(self, catalog_root: str | Path):
        self.catalog_root = Path(catalog_root).expanduser().resolve()
        self.db_path = resolve_db(self.catalog_root)
        if not self.db_path.is_file():
            raise CatalogNotReady(f"Catalog database not found: {self.db_path}")
        uri = (
            "file:"
            + self.db_path.as_posix().replace("?", "%3f").replace("#", "%23")
            + "?mode=ro"
        )
        try:
            self._con = sqlite3.connect(uri, uri=True)
        except sqlite3.OperationalError as exc:
            raise CatalogNotReady(f"Cannot open {self.db_path}: {exc}") from exc
        self._con.row_factory = sqlite3.Row
        # Belt and suspenders: block writes even if the connection were
        # re-opened read-write somewhere (query_only is per-connection).
        self._con.execute("PRAGMA query_only = 1")
        self._check_schema()

    def _check_schema(self) -> None:
        try:
            names = {
                r[0]
                for r in self._con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        except sqlite3.DatabaseError as exc:
            self._con.close()
            raise CatalogNotReady(
                f"Cannot read catalog database {self.db_path}: {exc}"
            ) from exc
        missing = [t for t in REQUIRED_TABLES if t not in names]
        if missing:
            self._con.close()
            raise CatalogNotReady(
                f"Unexpected database at {self.db_path}: "
                f"missing tables {', '.join(missing)}"
            )

    # ------------------------------------------------------------------ paths
    def resolve_photo(self, catalog_path: str | None) -> Path | None:
        """Resolve a stored catalog_path to an existing file, or None.

        Stored paths are relative to the project root (``input/...``) or to
        the output folder (``Plant/...``); older entries may be absolute.
        """
        if not catalog_path:
            return None
        raw = Path(catalog_path)
        if raw.is_absolute():
            candidates = [raw]
        else:
            candidates = [
                self.catalog_root / raw,
                self.catalog_root / "output" / raw,
            ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None

    # ------------------------------------------------------------- lifecycle
    @property
    def connection(self) -> sqlite3.Connection:
        return self._con

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> "CatalogDB":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
