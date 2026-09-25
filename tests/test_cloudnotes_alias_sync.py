from pathlib import Path

from scripts.sync_cloudnotes_character_aliases import build_registry


def _note(vault: Path, relative: str, frontmatter: str = "") -> None:
    path = vault / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    body = f"---\n{frontmatter}---\n" if frontmatter else ""
    path.write_text(body, encoding="utf-8")


def test_build_registry_imports_bounded_art_aliases(tmp_path: Path) -> None:
    _note(
        tmp_path,
        "extracurricular/music/voice synthesizer/voicebanks/Hatsune Miku.md",
        "platforms:\n  - Vocaloid\naliases:\n  - 初音ミク\n",
    )
    _note(
        tmp_path,
        "extracurricular/music/voice synthesizer/voicebanks/Kasane Teto.md",
        "platforms:\n  - Synth V\naliases:\n  - 重音テト\n",
    )
    _note(
        tmp_path,
        "extracurricular/music/voice synthesizer/voicebanks/Otamachi Una.md",
        "aliases:\n  - 音街ウナ\n",
    )
    _note(
        tmp_path,
        "extracurricular/ACG/games/rhythm game/pjsk/25H/akiyama mizuki.md",
    )
    _note(
        tmp_path,
        "extracurricular/ACG/games/rhythm game/pjsk/VBS/shinonome akita.md",
    )
    _note(
        tmp_path,
        "extracurricular/ACG/Touhou/characters/Nazrin.md",
        "aliases:\n  - ナズーリン\n",
    )
    _note(tmp_path, "extracurricular/ACG/Touhou/characters/Aki Sizuha.md")
    _note(tmp_path, "extracurricular/ACG/Touhou/characters/Lilywhite.md")
    _note(tmp_path, "extracurricular/vtubers/vedalverse/Neuro-sama.md")
    _note(tmp_path, "extracurricular/ACG/anime/K-ON/characters/平沢唯.md")
    _note(
        tmp_path,
        "extracurricular/ACG/media franchise/Umamusume Pretty Derby/characters/umamusume/Special Week.md",
        "aliases:\n  - スペシャルウィーク\n",
    )

    registry = build_registry(
        tmp_path,
        {
            "Art/GAMES/GENSHIN": ["Paimon"],
            "Music/VOCALOID": ["must disappear"],
        },
    )

    assert {"Hatsune Miku", "初音ミク"} <= set(registry["Art/VOCALOID"])
    assert {"Otamachi Una", "Otomachi Una", "音街ウナ"} <= set(
        registry["Art/VOCALOID"]
    )
    assert {"Kasane Teto", "重音テト"} <= set(registry["Art/VOICEBANKS"])
    assert "akiyama mizuki" in registry["Art/PJSK"]
    assert "Shinonome Akito" in registry["Art/PJSK"]
    assert {"Nazrin", "ナズーリン", "Toramaru Shou", "寅丸星"} <= set(
        registry["Art/TOUHOU"]
    )
    assert "Aki Shizuha" in registry["Art/TOUHOU"]
    assert "Lily White" in registry["Art/TOUHOU"]
    assert "Neuro-sama" in registry["Art/VTUBERS"]
    assert "平沢唯" in registry["Art/ANIME/K-ON"]
    assert {"Ritsu Tainaka", "Tsumugi Kotobuki"} <= set(
        registry["Art/ANIME/K-ON"]
    )
    assert {"Renge Miyauchi", "Hotaru Ichijou", "Komari Koshigaya"} <= set(
        registry["Art/ANIME/Non Non Biyori"]
    )
    assert {"Hachiman Hikigaya", "Yukino Yukinoshita"} <= set(
        registry["Art/ANIME/Oregairu"]
    )
    assert {"Shidou Itsuka", "Kurumi Tokisaki", "時崎狂三"} <= set(
        registry["Art/ANIME/Date a Live"]
    )
    assert {"Special Week", "スペシャルウィーク"} <= set(
        registry["Art/GAMES/UMAMUSUME"]
    )
    assert registry["Art/GAMES/GENSHIN"] == ["Paimon"]
    assert all(destination.startswith("Art/") for destination in registry)


def test_build_registry_ignores_catalogs_and_non_character_notes(tmp_path: Path) -> None:
    _note(tmp_path, "extracurricular/ACG/games/rhythm game/pjsk/pjsk.md")
    _note(tmp_path, "extracurricular/ACG/games/rhythm game/pjsk/music/Song.md")
    _note(tmp_path, "extracurricular/ACG/Touhou/characters/characters.md")
    _note(tmp_path, "extracurricular/vtubers/vedalverse/vedalverse.md")
    _note(tmp_path, "extracurricular/ACG/anime/K-ON/K-ON.md")
    _note(
        tmp_path,
        "extracurricular/ACG/media franchise/Umamusume Pretty Derby/characters/umamusume/umamusume.md",
    )

    aliases = {
        alias
        for destination_aliases in build_registry(tmp_path, {}).values()
        for alias in destination_aliases
    }

    assert not {"pjsk", "Song", "characters", "vedalverse", "K-ON", "umamusume"} & aliases
