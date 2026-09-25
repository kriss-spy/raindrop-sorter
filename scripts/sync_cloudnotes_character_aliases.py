"""Snapshot Art character aliases from the user's CloudNotes vault.

The vault is read-only. This script rewrites ``src/character_aliases.json`` with
file names, frontmatter names, and frontmatter aliases from the bounded sources
below while preserving other existing Art registries.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from src.destinations import is_art_destination


ANIME_ALIASES_PATH = (
    Path(__file__).parents[1] / "src" / "anime_character_aliases.json"
)


VOICEBANKS = Path("extracurricular/music/voice synthesizer/voicebanks")
PJSK = Path("extracurricular/ACG/games/rhythm game/pjsk")
TOUHOU = Path("extracurricular/ACG/Touhou/characters")
VTUBERS = Path("extracurricular/vtubers")
ANIME = Path("extracurricular/ACG/anime")
UMAMUSUME = Path(
    "extracurricular/ACG/media franchise/Umamusume Pretty Derby/characters/umamusume"
)

PJSK_CHARACTER_GROUPS = {"25H", "LND", "MMJ", "VBS", "WXS", "pjsk movie"}
VOICEBANK_DESTINATION_OVERRIDES = {
    "Otamachi Una": "Art/VOCALOID",
}
EXTRA_ALIASES_BY_SOURCE = {
    VOICEBANKS / "Otamachi Una.md": {"Otomachi Una"},
    PJSK / "VBS" / "shinonome akita.md": {"Shinonome Akito"},
    TOUHOU / "Aki Sizuha.md": {"Aki Shizuha"},
    TOUHOU / "Hiziri Byakuren.md": {"Hijiri Byakuren"},
    TOUHOU / "Hong Meirin.md": {"Hong Meiling"},
    TOUHOU / "Hoshiguma Yugi.md": {"Hoshiguma Yuugi"},
    TOUHOU / "Huziwara no Mokou.md": {"Fujiwara no Mokou"},
    TOUHOU / "Ibara Kasen.md": {"Ibaraki Kasen"},
    TOUHOU / "Inubashiri Momizi.md": {"Inubashiri Momiji"},
    TOUHOU / "Kawasiro Nitori.md": {"Kawashiro Nitori"},
    TOUHOU / "Kazami Yuka.md": {"Kazami Yuuka"},
    TOUHOU / "Kisin Sagume.md": {"Kishin Sagume"},
    TOUHOU / "Kotiya Sanae.md": {"Kochiya Sanae"},
    TOUHOU / "Lilywhite.md": {"Lily White"},
    TOUHOU / "Soga no Toziko.md": {"Soga no Tojiko"},
    TOUHOU / "Tenkyu Chimata.md": {"Tenkyuu Chimata"},
    TOUHOU / "Yorigami Jyoon.md": {"Yorigami Jo'on"},
}
TOUHOU_SUPPLEMENTS = {"Toramaru Shou", "寅丸星"}
ANIME_DESTINATIONS = {
    "ぼっち・ざ・ろっく！": "Art/ANIME/BocchiTheRock",
    "Chainsaw Man": "Art/ANIME/Chainsawman",
    "Date a Live": "Art/ANIME/Date a Live",
    "GIRLS und PANZER": "Art/ANIME/GUP",
    "響け！ユーフォニアム": "Art/ANIME/HIBIKEEUPHONIUM",
    "涼宮ハルヒの憂鬱": "Art/ANIME/Haruhi",
    "K-ON": "Art/ANIME/K-ON",
    "魔女の旅々": "Art/ANIME/MAJONOTABITABI",
    "のんのんびより": "Art/ANIME/Non Non Biyori",
    "やはり俺の青春ラブコメはまちがっている。": "Art/ANIME/Oregairu",
    "Sword Art Online": "Art/ANIME/SAO",
    "lucky star": "Art/ANIME/lucky star",
}
MANAGED_DESTINATIONS = {
    "Art/VOCALOID",
    "Art/VOICEBANKS",
    "Art/PJSK",
    "Art/TOUHOU",
    "Art/VTUBERS",
    "Art/GAMES/UMAMUSUME",
    "Art/ANIME",
    *ANIME_DESTINATIONS.values(),
}


def _frontmatter(path: Path) -> dict[str, Any]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    try:
        closing = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration:
        return {}
    result: dict[str, Any] = {}
    active_list: str | None = None
    for line in lines[1:closing]:
        item = re.match(r"^\s+-\s+(.+?)\s*$", line)
        if item and active_list:
            result.setdefault(active_list, []).append(_unquote(item.group(1)))
            continue
        field = re.match(r"^([A-Za-z0-9_-]+)\s*:\s*(.*?)\s*$", line)
        if not field:
            active_list = None
            continue
        key, value = field.group(1).casefold(), field.group(2)
        if not value:
            result[key] = []
            active_list = key
        else:
            result[key] = _unquote(value)
            active_list = None
    return result


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _values(value: Any) -> Iterable[str]:
    if isinstance(value, list):
        return (str(item) for item in value)
    if isinstance(value, str):
        return (value,)
    return ()


def _aliases(path: Path, vault: Path) -> set[str]:
    metadata = _frontmatter(path)
    values = {path.stem}
    values.update(_values(metadata.get("title")))
    values.update(_values(metadata.get("name")))
    values.update(_values(metadata.get("aliases") or metadata.get("alias")))
    values.update(EXTRA_ALIASES_BY_SOURCE.get(path.relative_to(vault), ()))
    return {value.strip() for value in values if value.strip()}


def _notes(directory: Path) -> list[Path]:
    return sorted(directory.rglob("*.md"), key=lambda path: path.as_posix().casefold())


def _add(
    registry: dict[str, set[str]], destination: str, path: Path, vault: Path
) -> None:
    registry[destination].update(_aliases(path, vault))


def _import_voicebanks(registry: dict[str, set[str]], vault: Path) -> None:
    for path in _notes(vault / VOICEBANKS):
        if path.stem.casefold() == "voicebanks":
            continue
        platforms = {
            value.casefold() for value in _values(_frontmatter(path).get("platforms"))
        }
        destination = VOICEBANK_DESTINATION_OVERRIDES.get(
            path.stem,
            "Art/VOCALOID" if "vocaloid" in platforms else "Art/VOICEBANKS",
        )
        _add(registry, destination, path, vault)


def _import_pjsk(registry: dict[str, set[str]], vault: Path) -> None:
    for path in _notes(vault / PJSK):
        relative = path.relative_to(vault / PJSK)
        if len(relative.parts) != 2 or relative.parts[0] not in PJSK_CHARACTER_GROUPS:
            continue
        if path.stem.casefold() != relative.parts[0].casefold():
            _add(registry, "Art/PJSK", path, vault)


def _import_touhou(registry: dict[str, set[str]], vault: Path) -> None:
    for path in _notes(vault / TOUHOU):
        if path.stem.casefold() != "characters":
            _add(registry, "Art/TOUHOU", path, vault)
    registry["Art/TOUHOU"].update(TOUHOU_SUPPLEMENTS)


def _import_vtubers(registry: dict[str, set[str]], vault: Path) -> None:
    for path in _notes(vault / VTUBERS):
        if path.stem.casefold() not in {"vtubers", path.parent.name.casefold()}:
            _add(registry, "Art/VTUBERS", path, vault)


def _import_anime(registry: dict[str, set[str]], vault: Path) -> None:
    for path in _notes(vault / ANIME):
        relative = path.relative_to(vault / ANIME)
        if "characters" not in relative.parts or path.stem.casefold() == "characters":
            continue
        anime = relative.parts[0]
        _add(registry, ANIME_DESTINATIONS.get(anime, "Art/ANIME"), path, vault)
    supplements: dict[str, list[str]] = json.loads(
        ANIME_ALIASES_PATH.read_text(encoding="utf-8")
    )
    for destination, aliases in supplements.items():
        registry[destination].update(aliases)


def _import_umamusume(registry: dict[str, set[str]], vault: Path) -> None:
    for path in _notes(vault / UMAMUSUME):
        if path.stem.casefold() != "umamusume":
            _add(registry, "Art/GAMES/UMAMUSUME", path, vault)


def build_registry(vault: Path, existing: dict[str, list[str]]) -> dict[str, list[str]]:
    registry: dict[str, set[str]] = defaultdict(set)
    for destination, aliases in existing.items():
        if is_art_destination(destination) and destination not in MANAGED_DESTINATIONS:
            registry[destination].update(aliases)

    _import_voicebanks(registry, vault)
    _import_pjsk(registry, vault)
    _import_touhou(registry, vault)
    _import_vtubers(registry, vault)
    _import_anime(registry, vault)
    _import_umamusume(registry, vault)

    return {
        destination: sorted(aliases, key=lambda alias: (alias.casefold(), alias))
        for destination, aliases in sorted(registry.items())
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parents[1] / "src" / "character_aliases.json",
    )
    args = parser.parse_args()
    existing = json.loads(args.output.read_text(encoding="utf-8"))
    registry = build_registry(args.vault.resolve(), existing)
    args.output.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({key: len(value) for key, value in registry.items()}, indent=2))


if __name__ == "__main__":
    main()
