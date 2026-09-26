"""Canonical identities for voice-synth characters and their known aliases."""

from __future__ import annotations

import unicodedata

from src.destinations import canonical_destination


_CHARACTER_ALIASES: dict[str, tuple[str, ...]] = {
    "hatsune_miku": ("Hatsune Miku", "miku", "初音ミク", "初音未来"),
    "ia": ("IA",),
    "kasukabe_tsumugi": ("Kasukabe Tsumugi", "春日部つむぎ"),
    "kizuna_akari": ("Kizuna Akari", "紲星あかり"),
    "otomachi_una": ("Otamachi Una", "Otomachi Una", "Una", "音街ウナ"),
    "yuzuki_yukari": ("Yuzuki Yukari", "結月ゆかり"),
    "adachi_rei": ("Adachi Rei", "足立レイ"),
    "amaharu_hau": ("Amaharu Hau", "雨晴はう"),
    "kasane_teto": ("Kasane Teto", "重音テト"),
    "koharu_rikka": ("Koharu Rikka", "小春六花"),
    "meimei_himari": ("Meimei Himari", "冥鳴ひまり"),
    "shikoku_metan": ("Shikoku Metan", "四国めたん"),
    "tohoku_kiritan": ("Tohoku Kiritan", "東北きりたん"),
    "whitecul": ("WhiteCUL", "雪さん"),
    "zundamon": ("Zundamon", "俊达萌"),
}

_CHARACTER_DESTINATIONS = {
    "hatsune_miku": "Art/MIKU",
}


def _alias_key(value: str) -> str:
    return " ".join(
        unicodedata.normalize("NFKC", value).casefold().replace("_", " ").split()
    )


_IDENTITY_BY_ALIAS = {
    _alias_key(alias): identity
    for identity, aliases in _CHARACTER_ALIASES.items()
    for alias in aliases
}


def voicebank_identity(alias: str) -> str | None:
    """Return one stable character identity for a multilingual alias."""
    return _IDENTITY_BY_ALIAS.get(_alias_key(alias))


def voicebank_character_destination(alias: str) -> str | None:
    """Return a dedicated collection when a character has one."""
    identity = voicebank_identity(alias)
    return _CHARACTER_DESTINATIONS.get(identity) if identity is not None else None


def is_voicebank_destination(destination: str) -> bool:
    """Return whether a collection belongs to the voice-synth family."""
    canonical = canonical_destination(destination)
    return canonical in {"Art/MIKU", "Art/VOCALOID", "Art/VOICEBANKS"} or canonical.startswith(
        "Art/VOICEBANKS/"
    )
