"""Committed multilingual character-name registry for deterministic routing."""

from __future__ import annotations

import json
from pathlib import Path
import unicodedata

from src.destinations import is_art_destination


ALIASES_PATH = Path(__file__).with_name("character_aliases.json")


def load_character_alias_routes() -> dict[str, tuple[str, ...]]:
    """Return normalized alias -> possible destination folders."""
    by_folder: dict[str, list[str]] = json.loads(
        ALIASES_PATH.read_text(encoding="utf-8")
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


CHARACTER_ALIAS_ROUTES = load_character_alias_routes()
