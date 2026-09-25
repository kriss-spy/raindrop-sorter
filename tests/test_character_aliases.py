import json
from pathlib import Path


REGISTRY = json.loads(
    (Path(__file__).parents[1] / "src" / "character_aliases.json").read_text(
        encoding="utf-8"
    )
)


def test_character_registry_only_targets_art_collections():
    assert REGISTRY
    assert all(destination.startswith("Art/") for destination in REGISTRY)


def test_character_registry_contains_cloudnotes_sources():
    expected = {
        "Art/VOCALOID": {"Hatsune Miku", "Yuzuki Yukari", "Otomachi Una"},
        "Art/VOICEBANKS": {"Kasane Teto", "Zundamon"},
        "Art/PJSK": {"akiyama mizuki", "kamishiro rui", "Shinonome Akito"},
        "Art/TOUHOU": {
            "Nazrin",
            "ナズーリン",
            "Toramaru Shou",
            "寅丸星",
            "Aki Shizuha",
            "Fujiwara no Mokou",
            "Inubashiri Momiji",
            "Kawashiro Nitori",
            "Lily White",
        },
        "Art/VTUBERS": {"Neuro-sama", "星街すいせい"},
        "Art/ANIME/K-ON": {"平沢唯", "Hirasawa Yui"},
        "Art/GAMES/UMAMUSUME": {"Special Week", "スペシャルウィーク"},
    }
    for destination, aliases in expected.items():
        assert aliases <= set(REGISTRY[destination])


def test_voicebank_with_vocaloid_support_is_not_generic_voicebank():
    assert "Yuzuki Yukari" in REGISTRY["Art/VOCALOID"]
    assert "Yuzuki Yukari" not in REGISTRY["Art/VOICEBANKS"]
