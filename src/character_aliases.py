"""Committed multilingual character-name registry for deterministic routing."""

from __future__ import annotations

import json
from pathlib import Path
import unicodedata

from src.destinations import is_art_destination


ALIASES_PATH = Path(__file__).with_name("character_aliases.json")
PARTIAL_ALIASES_PATH = Path(__file__).with_name("character_partial_aliases.json")


def _load_alias_routes(path: Path) -> dict[str, tuple[str, ...]]:
    by_folder: dict[str, list[str]] = json.loads(
        path.read_text(encoding="utf-8")
    )
    folders_by_alias: dict[str, set[str]] = {}
    for folder, aliases in by_folder.items():
        if not is_art_destination(folder):
            continue
        for alias in aliases:
            normalized_alias = unicodedata.normalize("NFKC", alias).casefold()
            folders_by_alias.setdefault(normalized_alias, set()).add(folder)
    return {
        alias: tuple(sorted(folders))
        for alias, folders in folders_by_alias.items()
    }


def load_character_alias_routes() -> dict[str, tuple[str, ...]]:
    """Return normalized full alias -> possible destination folders."""
    return _load_alias_routes(ALIASES_PATH)


def load_character_partial_alias_routes() -> dict[str, tuple[str, ...]]:
    """Return explicitly audited partial name -> possible destination folders."""
    return _load_alias_routes(PARTIAL_ALIASES_PATH)


CHARACTER_ALIAS_ROUTES = load_character_alias_routes()
CHARACTER_PARTIAL_ALIAS_ROUTES = load_character_partial_alias_routes()
