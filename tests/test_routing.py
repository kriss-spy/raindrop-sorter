from types import SimpleNamespace

import numpy as np
import pytest

from src.routing import (
    RouteEngine,
    RouteOutcome,
    TextEvidence,
    TextIdentifier,
    VisualEvidence,
    VisualVerifier,
)


def _text(destination=None, strength=None, kind="personal_interest_text"):
    return TextEvidence(kind=kind, destination=destination, strength=strength)


def _visual(status, destination=None):
    return VisualEvidence(status=status, destination=destination, method="test", explanation="test")


@pytest.mark.parametrize(
    ("text", "visual", "outcome", "destination"),
    [
        (_text("Art/TOUHOU", "strong"), _visual("pass", "Art/TOUHOU"), RouteOutcome.CONFIRMED, "Art/TOUHOU"),
        (_text("Art/TOUHOU", "strong"), _visual("inconclusive"), RouteOutcome.PROVISIONAL, "Art/TOUHOU"),
        (_text("Art/TOUHOU", "contextual"), _visual("unavailable"), RouteOutcome.PROVISIONAL, "Art/TOUHOU"),
        (_text("Art/TOUHOU", "weak"), _visual("inconclusive"), RouteOutcome.REVIEW, None),
        (_text("Art/TOUHOU", "weak"), _visual("pass", "Art/TOUHOU"), RouteOutcome.PROVISIONAL, "Art/TOUHOU"),
        (_text("Art/TOUHOU", "weak"), _visual("pass", "Art/GAMES/BA"), RouteOutcome.REVIEW, None),
        (_text("Art/TOUHOU", "strong"), _visual("pass", "Art/GAMES/BA"), RouteOutcome.PROVISIONAL, "Art/TOUHOU"),
        (_text(None, None, "no_match"), _visual("pass", "Art/GAMES/BA"), RouteOutcome.PROVISIONAL, "Art/GAMES/BA"),
        (_text(None, None, "no_match"), _visual("inconclusive"), RouteOutcome.REVIEW, None),
    ],
)
def test_route_engine_implements_decision_table(text, visual, outcome, destination):
    decision = RouteEngine().route(bookmark_id=123, text=text, visual=visual)
    assert decision.outcome is outcome
    assert decision.destination == destination


def test_user_confirmed_bookmark_bypasses_visual_requirement():
    decision = RouteEngine().route(
        bookmark_id=1860037727,
        text=_text("Art/GAMES/BA", "strong", "user_confirmed_rule"),
        visual=_visual("bypassed"),
    )
    assert decision.outcome is RouteOutcome.CONFIRMED
    assert decision.destination == "Art/GAMES/BA"
    assert "bypassed" in decision.summary


def test_visual_match_disambiguates_text_candidates_as_provisional():
    text = TextEvidence(
        kind="personal_interest_text",
        destination=None,
        strength="conflicting",
        candidates=("Art/TOUHOU", "Art/VTUBERS"),
    )

    decision = RouteEngine().route(
        bookmark_id=123,
        text=text,
        visual=_visual("pass", "Art/TOUHOU"),
    )

    assert decision.outcome is RouteOutcome.PROVISIONAL
    assert decision.destination == "Art/TOUHOU"
    assert "competing text candidates" in decision.summary


def test_strong_text_overrides_conflicting_visual_candidates_provisionally():
    decision = RouteEngine().route(
        bookmark_id=123,
        text=_text("Art/TOUHOU", "strong"),
        visual=VisualEvidence(
            status="conflict",
            destination=None,
            method="test",
            explanation="test",
            candidates=("Art/TOUHOU", "Art/VTUBERS"),
        ),
    )

    assert decision.outcome is RouteOutcome.PROVISIONAL
    assert decision.destination == "Art/TOUHOU"
    assert "strong text evidence" in decision.summary


@pytest.mark.parametrize(
    "text",
    [
        _text(None, None, "no_match"),
        _text("Art/TOUHOU", "contextual"),
        _text("Art/TOUHOU", "weak"),
        TextEvidence(
            kind="personal_interest_text",
            destination=None,
            strength="conflicting",
            source="multiple_weak_partial",
            candidates=("Art/TOUHOU", "Art/VTUBERS"),
        ),
    ],
)
def test_halo_routes_to_blue_archive_when_no_strong_text_candidate(text):
    decision = RouteEngine().route(
        bookmark_id=123,
        text=text,
        visual=VisualEvidence(
            status="pass",
            destination="Art/TOUHOU",
            method="wd14+visual_exemplar",
            explanation="test",
            labels=("1girl", "halo"),
        ),
    )

    assert decision.outcome is RouteOutcome.PROVISIONAL
    assert decision.destination == "Art/GAMES/BA"
    assert "halo" in decision.summary


@pytest.mark.parametrize(
    "text",
    [
        _text("Art/TOUHOU", "strong"),
        TextEvidence(
            kind="personal_interest_text",
            destination=None,
            strength="conflicting",
            source="multiple",
            candidates=("Art/TOUHOU", "Art/VTUBERS"),
        ),
    ],
)
def test_halo_does_not_override_strong_text_candidates(text):
    decision = RouteEngine().route(
        bookmark_id=123,
        text=text,
        visual=VisualEvidence(
            status="inconclusive",
            destination=None,
            method="wd14+visual_exemplar",
            explanation="test",
            labels=("halo",),
        ),
    )

    assert decision.destination != "Art/GAMES/BA"


def test_parenthetical_halo_series_is_not_the_standalone_halo_feature():
    visual = VisualVerifier({}, {}, None).verify(
        {"_id": 123, "type": "image", "cover": "https://example.test/a.jpg"},
        labels=["master_chief_(halo)"],
        embedding=None,
    )

    assert visual.labels == ("master_chief_(halo)",)
    decision = RouteEngine().route(
        bookmark_id=123,
        text=_text(None, None, "no_match"),
        visual=visual,
    )
    assert decision.outcome is RouteOutcome.REVIEW
    assert decision.destination is None


def test_text_identifier_uses_user_tags_but_ignores_ai_tags():
    identifier = TextIdentifier({"touhou": "Art/TOUHOU", "miku": "Art/MIKU"}, {})
    evidence = identifier.identify(
        {"_id": 999, "type": "image", "tags": ["touhou", "ai:wdtag-miku"]}
    )
    assert evidence.destination == "Art/TOUHOU"
    assert evidence.strength == "strong"
    assert evidence.source == "user_tag_or_hashtag"


def test_text_identifier_bypasses_visual_for_review_confirmed_signal():
    identifier = TextIdentifier(
        {},
        {},
        review_feedback={
            "tag_rules": {
                "date_a_live": {
                    "destination": "Art/ANIME/Date a Live",
                    "support": 3,
                    "observations": 3,
                    "purity": 1.0,
                }
            },
            "alias_rules": {},
        },
    )

    evidence = identifier.identify(
        {
            "_id": 999,
            "type": "image",
            "title": "day 31 #date_a_live",
            "tags": [],
        }
    )

    assert evidence.kind == "user_confirmed_rule"
    assert evidence.destination == "Art/ANIME/Date a Live"
    assert evidence.source == "review_feedback"


def test_distinct_voicebank_characters_collapse_to_vocaloid_with_learning():
    identifier = TextIdentifier(
        {},
        {},
        review_feedback={
            "tag_rules": {},
            "alias_rules": {
                "重音テト": {
                    "destination": "Art/VOICEBANKS/TETO",
                    "support": 6,
                    "observations": 6,
                    "purity": 1.0,
                }
            },
        },
    )

    evidence = identifier.identify({
        "_id": 1744707640,
        "type": "image",
        "title": "初音ミク メズマライザーVer. 重音テト メズマライザーVer.",
        "tags": [],
    })

    assert evidence.kind == "user_confirmed_rule"
    assert evidence.destination == "Art/VOCALOID"
    assert evidence.source == "multiple_voicebank_characters"
    assert evidence.candidates == ("Art/MIKU", "Art/VOICEBANKS/TETO")


def test_repeated_miku_aliases_stay_in_miku():
    evidence = TextIdentifier({}, {}).identify({
        "_id": 999,
        "type": "image",
        "title": "Hatsune Miku 初音ミク 初音ミク",
        "tags": [],
    })

    assert evidence.destination == "Art/MIKU"
    assert evidence.candidates == ("Art/MIKU",)


def test_distinct_generic_voicebank_characters_collapse_to_vocaloid():
    evidence = TextIdentifier({}, {}).identify({
        "_id": 999,
        "type": "image",
        "title": "Zundamon and Tohoku Kiritan",
        "tags": [],
    })

    assert evidence.destination == "Art/VOCALOID"
    assert evidence.source == "multiple_voicebank_characters"
    assert evidence.candidates == ("Art/VOICEBANKS",)


@pytest.mark.parametrize(
    "title",
    [
        "Yuzuki Yukari 結月ゆかり",
        "Otomachi Una 音街ウナ",
        "Kasane Teto 重音テト",
        "Kasane / Teto",
        "Teto / Kasane",
        "Koharu / Rikka",
    ],
)
def test_bilingual_aliases_for_one_voicebank_character_are_not_an_ensemble(title):
    evidence = TextIdentifier({}, {}).identify({
        "_id": 999,
        "type": "image",
        "title": title,
        "tags": [],
    })

    assert evidence.source != "multiple_voicebank_characters"


def test_short_alias_is_weak_and_uses_unicode_boundaries():
    evidence = TextIdentifier({}, {}).identify(
        {"_id": 999, "type": "image", "title": "Leva portrait", "tags": []}
    )
    assert evidence.destination == "Art/GAMES/GFL2"
    assert evidence.strength == "weak"


def test_visual_verifier_marks_non_visual_bookmark_not_applicable():
    evidence = VisualVerifier({}, {}, None).verify(
        {"_id": 999, "type": "article", "tags": []}, labels=[], embedding=None
    )
    assert evidence.status == "not_applicable"


def test_visual_verifier_uses_confirmed_wd14_assignment():
    evidence = VisualVerifier({}, {}, None).verify(
        {"_id": 999, "type": "image", "cover": "https://example.test/a.jpg"},
        labels=["ai:wdtag-blue_archive"],
        embedding=None,
    )
    assert evidence.status == "pass"
    assert evidence.destination == "Art/GAMES/BA"
    assert "blue_archive" in evidence.labels


def test_visual_distinct_voicebank_characters_collapse_to_vocaloid():
    evidence = VisualVerifier({}, {}, None).verify(
        {"_id": 999, "type": "image", "cover": "https://example.test/a.jpg"},
        labels=["ai:wdtag-hatsune_miku", "ai:wdtag-kasane_teto"],
        embedding=None,
    )

    assert evidence.status == "pass"
    assert evidence.destination == "Art/VOCALOID"
    assert evidence.candidates == ("Art/MIKU", "Art/VOICEBANKS")


def test_visual_multiple_miku_labels_stay_in_miku():
    evidence = VisualVerifier({}, {}, None).verify(
        {"_id": 999, "type": "image", "cover": "https://example.test/a.jpg"},
        labels=["ai:wdtag-hatsune_miku", "ai:wdtag-hatsune_miku"],
        embedding=None,
    )

    assert evidence.status == "pass"
    assert evidence.destination == "Art/MIKU"


def test_visual_distinct_generic_voicebank_characters_collapse_to_vocaloid():
    evidence = VisualVerifier({}, {}, None).verify(
        {"_id": 999, "type": "image", "cover": "https://example.test/a.jpg"},
        labels=["ai:wdtag-yuzuki_yukari", "ai:wdtag-otomachi_una"],
        embedding=None,
    )

    assert evidence.status == "pass"
    assert evidence.destination == "Art/VOCALOID"


@pytest.mark.parametrize(
    "label",
    [
        "nazrin",
        "toramaru_shou",
        "aki_shizuha",
        "hijiri_byakuren",
        "hong_meiling",
        "hoshiguma_yuugi",
        "fujiwara_no_mokou",
        "ibaraki_kasen",
        "inubashiri_momiji",
        "kawashiro_nitori",
        "kazami_yuuka",
        "kishin_sagume",
        "kochiya_sanae",
        "lily_white",
        "soga_no_tojiko",
        "tenkyuu_chimata",
        "yorigami_jo'on",
    ],
)
def test_visual_verifier_uses_vault_character_registry(label):
    evidence = VisualVerifier({}, {}, None).verify(
        {"_id": 999, "type": "image", "cover": "https://example.test/a.jpg"},
        labels=[f"ai:wdtag-{label}"],
        embedding=None,
    )
    assert evidence.status == "pass"
    assert evidence.destination == "Art/TOUHOU"


@pytest.mark.parametrize("title", ["ナズーリン fanart", "#東方LW 絵札イラスト"])
def test_text_identifier_uses_touhou_vault_aliases(title):
    evidence = TextIdentifier({}, {}).identify(
        {"_id": 999, "type": "image", "title": title, "tags": []}
    )
    assert evidence.destination == "Art/TOUHOU"


def test_text_identifier_uses_safe_partial_character_names():
    evidence = TextIdentifier({}, {}).identify(
        {
            "_id": 1611241180,
            "type": "image",
            "title": "Since regular Sanae is evil, what about good Sanae?",
            "tags": [],
        }
    )

    assert evidence.destination == "Art/TOUHOU"
    assert evidence.strength == "weak"
    assert evidence.matched_value == "sanae"


def test_agreeing_visual_evidence_corroborates_weak_partial_name():
    decision = RouteEngine().route(
        bookmark_id=999,
        text=TextEvidence(
            kind="personal_interest_text",
            destination="Art/TOUHOU",
            strength="weak",
            source="character_alias_partial",
        ),
        visual=_visual("pass", "Art/TOUHOU"),
    )

    assert decision.outcome is RouteOutcome.PROVISIONAL
    assert "corroborated a weak partial-name match" in decision.summary


@pytest.mark.parametrize("title", ["Evil Neuro is cute", "#heartheartart sketch"])
def test_text_identifier_requires_specific_evil_neuro_signal(title):
    evidence = TextIdentifier({}, {}).identify(
        {"_id": 999, "type": "image", "title": title, "tags": []}
    )

    assert evidence.destination == "Art/NEUROVERSE/EVIL"
    assert evidence.source == "curated_text"


def test_text_identifier_does_not_treat_generic_evil_as_character_name():
    evidence = TextIdentifier({}, {}).identify(
        {"_id": 999, "type": "image", "title": "Sanae is evil", "tags": []}
    )

    assert evidence.destination == "Art/TOUHOU"
    assert "EVIL" not in evidence.candidates


def test_partial_character_matching_does_not_derive_ordinary_words():
    evidence = TextIdentifier({}, {}).identify(
        {
            "_id": 999,
            "type": "image",
            "title": "white flower love march",
            "tags": [],
        }
    )

    assert evidence.kind == "no_match"


def test_unmatched_weak_partial_stays_in_review_instead_of_becoming_conflict():
    text = TextIdentifier({}, {}).identify(
        {
            "_id": 999,
            "type": "image",
            "title": "Ford announces a solemn rite at the opera",
            "tags": [],
        }
    )

    assert text.strength == "conflicting"
    assert text.source == "multiple_weak_partial"
    decision = RouteEngine().route(
        bookmark_id=999,
        text=text,
        visual=_visual("pass", "Art/GAMES/BA"),
    )
    assert decision.outcome is RouteOutcome.REVIEW
    assert decision.destination is None
    assert "did not agree" in decision.summary


def test_unmatched_weak_exact_alias_is_not_described_as_partial():
    text = TextIdentifier({}, {}).identify(
        {"_id": 999, "type": "image", "title": "霞", "tags": []}
    )

    assert text.source == "character_alias"
    decision = RouteEngine().route(
        bookmark_id=999,
        text=text,
        visual=_visual("pass", "Art/TOUHOU"),
    )
    assert decision.outcome is RouteOutcome.REVIEW
    assert "weak text evidence" in decision.summary
    assert "partial-name" not in decision.summary


def test_unmatched_multiple_weak_exact_aliases_stay_in_review():
    text = TextIdentifier({}, {}).identify(
        {"_id": 999, "type": "image", "title": "Miku", "tags": []}
    )

    assert text.strength == "conflicting"
    assert text.source == "multiple_weak"
    decision = RouteEngine().route(
        bookmark_id=999,
        text=text,
        visual=_visual("pass", "Art/VTUBERS"),
    )
    assert decision.outcome is RouteOutcome.REVIEW
    assert "weak text evidence" in decision.summary
    assert "partial-name" not in decision.summary


@pytest.mark.parametrize(
    ("title", "destination"),
    [
        ("Renge Miyauchi fanart", "Art/ANIME/Non Non Biyori"),
        ("Hachiman Hikigaya fanart", "Art/ANIME/Oregairu"),
        ("Kurumi Tokisaki fanart", "Art/ANIME/Date a Live"),
    ],
)
def test_text_identifier_uses_audited_anime_aliases(title, destination):
    evidence = TextIdentifier({}, {}).identify(
        {"_id": 999, "type": "image", "title": title, "tags": []}
    )
    assert evidence.destination == destination


def test_text_identifier_preserves_independent_character_conflicts():
    evidence = TextIdentifier({}, {}).identify(
        {
            "_id": 999,
            "type": "image",
            "title": "Renge Miyauchi and Kurumi Tokisaki fanart",
            "tags": [],
        }
    )
    assert evidence.strength == "conflicting"
    assert evidence.candidates == (
        "Art/ANIME/Date a Live",
        "Art/ANIME/Non Non Biyori",
    )


def test_explicit_work_name_beats_ambiguous_collaboration_character():
    evidence = TextIdentifier({}, {}).identify(
        {
            "_id": 1850572932,
            "type": "image",
            "title": "VOCALOID, hatsune miku, MIKU / 2016 MIKU EXPO china tour - pixiv",
            "tags": [],
        }
    )

    assert evidence.destination == "Art/VOCALOID"
    assert evidence.strength == "strong"
    assert evidence.source == "curated_text"
    assert evidence.candidates == ("Art/VOCALOID",)


def test_text_identifier_recognizes_honkai_star_rail_phrase():
    evidence = TextIdentifier({}, {}).identify(
        {
            "_id": 1600936639,
            "type": "image",
            "title": "To celebrate Honkai: Star Rail Ver.4.0,",
            "excerpt": "Hatsune Miku × Pom-Pom by KEI",
            "tags": [],
        }
    )

    assert evidence.destination == "Art/GAMES/STARRAIL"
    assert evidence.source == "curated_text"
    assert evidence.strength == "strong"


@pytest.mark.parametrize("title", ["学園アイドルマスター", "学マス fanart", "gkmas"])
def test_text_identifier_recognizes_gakuen_idolmaster(title):
    evidence = TextIdentifier({}, {}).identify(
        {"_id": 999, "type": "image", "title": title, "tags": []}
    )

    assert evidence.destination == "Art/IDOL@MASTER"
    assert evidence.source == "curated_text"


def test_text_identifier_uses_partial_gakumas_character_name():
    evidence = TextIdentifier({}, {}).identify(
        {"_id": 999, "type": "image", "title": "Temari fanart", "tags": []}
    )

    assert evidence.destination == "Art/IDOL@MASTER"
    assert evidence.source == "character_alias_partial"
    assert evidence.strength == "weak"


def test_visual_candidate_disambiguates_ambiguous_partial_character_name():
    text = TextIdentifier({}, {}).identify(
        {"_id": 999, "type": "image", "title": "Saki fanart", "tags": []}
    )

    assert text.strength == "conflicting"
    assert set(text.candidates) == {
        "Art/GAMES/BA",
        "Art/IDOL@MASTER",
        "Art/PJSK",
    }

    decision = RouteEngine().route(
        bookmark_id=999,
        text=text,
        visual=_visual("pass", "Art/IDOL@MASTER"),
    )
    assert decision.outcome is RouteOutcome.PROVISIONAL
    assert decision.destination == "Art/IDOL@MASTER"


def test_visual_identity_label_beats_generic_learned_tag_and_exemplar(monkeypatch):
    exemplar = SimpleNamespace(
        folder_path="Art/GAMES/Arknights Endfield",
        similarity=0.84,
        margin=0.14,
        runner_up_folder="Art/GAMES/GFL2",
        runner_up_similarity=0.70,
    )
    monkeypatch.setattr("src.routing.score_visual_embedding", lambda *_args, **_kwargs: exemplar)
    index = SimpleNamespace(min_similarity=0.0, min_margin=0.05, neighbors_per_folder=3)

    evidence = VisualVerifier(
        {"scarf": "Art/TOUHOU"},
        {},
        index,
    ).verify(
        {"_id": 1851809656, "type": "image", "cover": "https://example.test/a.jpg"},
        labels=["scarf", "shiroko_(blue_archive)", "blue_archive"],
        embedding=np.array([1.0], dtype=np.float32),
    )

    assert evidence.status == "pass"
    assert evidence.destination == "Art/GAMES/BA"
    assert evidence.candidates == ("Art/GAMES/BA",)
    assert evidence.winner == "Art/GAMES/Arknights Endfield"


def test_visual_learned_tag_remains_a_last_resort():
    evidence = VisualVerifier({"distinctive_tag": "Art/TOUHOU"}, {}, None).verify(
        {"_id": 999, "type": "image", "cover": "https://example.test/a.jpg"},
        labels=["distinctive_tag"],
        embedding=None,
    )

    assert evidence.status == "pass"
    assert evidence.destination == "Art/TOUHOU"


def test_text_identifier_prunes_only_overlapping_short_alias_occurrences():
    evidence = TextIdentifier({}, {}).identify(
        {
            "_id": 999,
            "type": "image",
            "title": "Yui and Yuigahama Yui fanart",
            "tags": [],
        }
    )
    assert evidence.strength == "conflicting"
    assert evidence.candidates == ("Art/ANIME", "Art/ANIME/Oregairu")


@pytest.mark.parametrize(
    ("label", "destination"),
    [
        ("tainaka_ritsu", "Art/ANIME/K-ON"),
        ("tokisaki_kurumi", "Art/ANIME/Date a Live"),
    ],
)
def test_visual_verifier_uses_audited_anime_aliases(label, destination):
    evidence = VisualVerifier({}, {}, None).verify(
        {"_id": 999, "type": "image", "cover": "https://example.test/a.jpg"},
        labels=[label],
        embedding=None,
    )
    assert evidence.status == "pass"
    assert evidence.destination == destination


def test_native_routing_ignores_non_art_destinations():
    text = TextIdentifier({"vocaloid": "Music/VOCALOID"}, {}).identify(
        {"_id": 999, "type": "audio", "tags": ["vocaloid"]}
    )
    visual = VisualVerifier({}, {"vocaloid": "Video/VOCALOID"}, None).verify(
        {"_id": 999, "type": "image", "cover": "https://example.test/a.jpg"},
        labels=["vocaloid"],
        embedding=None,
    )
    assert text.kind == "no_match"
    assert visual.status == "inconclusive"


def test_art_alias_does_not_route_a_nonvisual_article():
    evidence = TextIdentifier({}, {}).identify(
        {"_id": 999, "type": "article", "title": "Genshin release notes", "tags": []}
    )
    assert evidence.kind == "no_match"


def test_katakana_alias_does_not_match_inside_a_longer_name():
    evidence = TextIdentifier({}, {}).identify(
        {
            "_id": 999,
            "type": "image",
            "title": "『アリサ・ミハイロヴナ・九条』fanart",
            "tags": [],
        }
    )

    assert evidence.kind == "no_match"


def test_work_alias_can_match_inside_unsegmented_cjk_text():
    evidence = TextIdentifier({}, {}).identify(
        {"_id": 999, "type": "image", "title": "原神壁紙", "tags": []}
    )

    assert evidence.destination == "Art/GAMES/GENSHIN"
