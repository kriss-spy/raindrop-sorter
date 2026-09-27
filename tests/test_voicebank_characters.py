import json
from pathlib import Path

from src.voicebank_characters import voicebank_identity


def test_voicebank_identity_unifies_multilingual_aliases():
    groups = [
        ("hatsune_miku", ("Hatsune Miku", "Hatsune", "Miku", "初音ミク", "初音未来")),
        ("kasane_teto", ("Kasane Teto", "Kasane", "Teto", "重音テト")),
        ("koharu_rikka", ("Koharu Rikka", "Koharu", "Rikka", "小春六花")),
        ("yuzuki_yukari", ("Yuzuki Yukari", "結月ゆかり")),
        ("otomachi_una", ("Otamachi Una", "Otomachi Una", "音街ウナ")),
        ("zundamon", ("Zundamon", "俊达萌")),
    ]

    for identity, aliases in groups:
        assert {voicebank_identity(alias) for alias in aliases} == {identity}


def test_every_routable_voicebank_alias_has_a_canonical_identity():
    registry = json.loads(
        (Path(__file__).parents[1] / "src" / "character_aliases.json").read_text(
            encoding="utf-8"
        )
    )
    aliases = [
        *registry["Art/VOCALOID"],
        *registry["Art/VOICEBANKS"],
    ]

    assert [alias for alias in aliases if voicebank_identity(alias) is None] == []
