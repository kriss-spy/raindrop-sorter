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
        (_text("Art/TOUHOU", "strong"), _visual("pass", "Art/GAMES/BA"), RouteOutcome.CONFLICT, None),
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


def test_text_identifier_uses_user_tags_but_ignores_ai_tags():
    identifier = TextIdentifier({"touhou": "Art/TOUHOU", "miku": "Art/MIKU"}, {})
    evidence = identifier.identify(
        {"_id": 999, "type": "image", "tags": ["touhou", "ai:wdtag-miku"]}
    )
    assert evidence.destination == "Art/TOUHOU"
    assert evidence.strength == "strong"
    assert evidence.source == "user_tag_or_hashtag"


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
