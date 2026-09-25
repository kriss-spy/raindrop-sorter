import json
from pathlib import Path


REGISTRY = json.loads(
    (Path(__file__).parents[1] / "src" / "character_aliases.json").read_text(
        encoding="utf-8"
    )
)
ANIME_SUPPLEMENTS = json.loads(
    (Path(__file__).parents[1] / "src" / "anime_character_aliases.json").read_text(
        encoding="utf-8"
    )
)


def test_character_registry_only_targets_art_collections():
    assert REGISTRY
    assert all(destination.startswith("Art/") for destination in REGISTRY)


def test_anime_supplements_are_nonempty_art_destinations():
    assert ANIME_SUPPLEMENTS
    assert all(
        destination.startswith("Art/") and aliases
        for destination, aliases in ANIME_SUPPLEMENTS.items()
    )
    assert all(
        len(aliases) == len(set(aliases)) for aliases in ANIME_SUPPLEMENTS.values()
    )


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


def test_anime_registry_fills_main_cast_gaps_in_sparse_vault_notes():
    expected = {
        "Art/ANIME/Non Non Biyori": {
            "Renge Miyauchi",
            "Hotaru Ichijou",
            "Natsumi Koshigaya",
            "Komari Koshigaya",
        },
        "Art/ANIME/Oregairu": {
            "Hachiman Hikigaya",
            "Yukino Yukinoshita",
            "Yui Yuigahama",
            "Iroha Isshiki",
        },
        "Art/ANIME/Date a Live": {
            "Shidou Itsuka",
            "Tohka Yatogami",
            "Origami Tobiichi",
            "Kotori Itsuka",
            "Yoshino",
            "Kurumi Tokisaki",
            "Kaguya Yamai",
            "Yuzuru Yamai",
            "Miku Izayoi",
            "Natsumi",
            "Nia Honjou",
            "Mukuro Hoshimiya",
            "Mio Takamiya",
        },
    }
    for destination, aliases in expected.items():
        assert aliases <= set(REGISTRY[destination])


def test_audited_anime_main_rosters_are_complete():
    expected = {
        "Art/ANIME": {
            # Angel Beats
            "Nakamura Yuri", "Tachibana Kanade", "Otonashi Yuzuru",
            "Yui", "Hideki Hinata", "Ayato Naoi",
            # Charlotte
            "Tomori Nao", "Yuu Otosaka", "Joujirou Takajou",
            "Yusa Kurobane", "Misa Kurobane", "Ayumi Otosaka",
            # Onimai
            "Mahiro Oyama", "Mihari Oyama", "Momiji Hozuki",
            "Kaede Hozuki", "Asahi Ouka", "Miyo Murosaki",
            # Konosuba
            "Kazuma Satou", "Aqua", "Megumin", "Darkness",
            # Sakurasou
            "Mashiro Shiina", "Misaki Kamiigusa", "Nanami Aoyama",
            "Sorata Kanda", "Jin Mitaka", "Ryuunosuke Akasaka",
            # Toradora
            "Taiga Aisaka", "Ryuuji Takasu", "Minori Kushieda",
            "Yuusaku Kitamura", "Ami Kawashima",
            # Ryuuou
            "Ai Hinatsuru", "Yaichi Kuzuryuu", "Ai Yashajin",
            "Ginko Sora", "Keika Kiyotaki",
            # Hayate
            "Sanzenin Nagi", "Katsura Hinagiku", "Hayate Ayasaki", "Maria",
            # Quintuplets
            "Fuutarou Uesugi", "Nakano Ichika", "Nakano Nino",
            "Nakano Miku", "Nakano Yotsuba", "Nakano Itsuki",
            # Saekano
            "Tomoya Aki", "Megumi Katou", "Eriri Sawamura Spencer",
            "Kasumigaoka Utaha", "Michiru Hyoudou",
            # Alya, Shana, Aharen, Elaina
            "Alisa Mikhailovna Kujō", "Masachika Kuze",
            "Shana", "Yuuji Sakai", "Yoshida Kazumi",
            "Aharen Reina", "Raido",
            # Yuru Camp
            "Kagamihara Nadeshiko", "Inuyama Aoi", "Oogaki Chiaki",
            "Saito Ena", "Shima Rin",
        },
        "Art/ANIME/GUP": {
            "Nishizumi Miho", "Takebe Saori", "Isuzu Hana",
            "Akiyama Yukari", "Reizei Mako",
        },
        "Art/ANIME/K-ON": {
            "Hirasawa Yui", "Akiyama Mio", "Tainaka Ritsu",
            "Kotobuki Tsumugi", "Nakano Azusa",
        },
        "Art/ANIME/lucky star": {
            "Izumi Konata", "Hiiragi Tsukasa", "Hiiragi Kagami", "Takara Miyuki",
        },
        "Art/ANIME/BocchiTheRock": {
            "Gotou Hitori", "Ijichi Nijika", "Yamada Ryo", "Kita Ikuyo",
        },
        "Art/ANIME/MAJONOTABITABI": {"Elaina"},
    }
    for destination, aliases in expected.items():
        assert aliases <= set(REGISTRY[destination])
