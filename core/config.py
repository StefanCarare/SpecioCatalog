"""Settings loading for Specio Catalog.

The project is read-only by design: these settings only point Specio Catalog
to the SpecioIdentify project that holds the catalog database.
"""
from __future__ import annotations

from pathlib import Path

__all__ = ["APP_ROOT", "SETTINGS_PATH", "load_settings", "configured_catalog_root", "auto_detect_root", "save_setting", "save_catalog_root"]

APP_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = APP_ROOT / "config" / "settings.txt"


def load_settings() -> dict[str, str]:
    """Parse ``config/settings.txt`` (key = value, '#' comments)."""
    data: dict[str, str] = {}
    if SETTINGS_PATH.is_file():
        for raw in SETTINGS_PATH.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            data[key.strip()] = value.strip()
    return data


def configured_catalog_root() -> Path | None:
    """Root from settings.txt, only if its catalog database actually exists."""
    from core.catalog_db import resolve_db

    root = load_settings().get("catalog_root", "")
    if root and resolve_db(Path(root)).is_file():
        return Path(root)
    return None


def save_setting(key: str, value: str) -> None:
    """Persist one key in settings.txt, keeping every comment in place.

    Used for choices the user makes in the interface (currently the model
    behind the describe-and-find box), so the next launch starts with the
    same setting instead of silently reverting to the file's value.
    """
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if SETTINGS_PATH.is_file():
        lines = SETTINGS_PATH.read_text(encoding="utf-8").splitlines()
    kept = [
        line
        for line in lines
        if not line.strip().lower().startswith(key.strip().lower())
    ]
    kept.append(f"{key.strip()} = {value}")
    SETTINGS_PATH.write_text("\n".join(kept) + "\n", encoding="utf-8")


def save_catalog_root(root: Path) -> None:
    """Persist ``catalog_root`` in settings.txt (Specio Catalog's own config)."""
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if SETTINGS_PATH.is_file():
        lines = SETTINGS_PATH.read_text(encoding="utf-8").splitlines()
    kept = [
        line
        for line in lines
        if not line.strip().lower().startswith("catalog_root")
    ]
    kept.append(f"catalog_root = {root}")
    SETTINGS_PATH.write_text("\n".join(kept) + "\n", encoding="utf-8")


def auto_detect_root() -> Path | None:
    """First SpecioIdentify project found: the sibling folder, then the Desktop."""
    from core.catalog_db import find_default_catalog_roots, resolve_db

    for candidate in find_default_catalog_roots():
        if resolve_db(candidate).is_file():
            return candidate
    return None
