from scripts.build_character_partial_aliases import build_partial_registry


def test_partial_registry_retains_ambiguous_names_and_rejects_prose() -> None:
    registry = build_partial_registry(
        {
            "Art/A": ["Saki Hanami", "White Flower"],
            "Art/B": ["Saki Sorai", "March Seventh"],
            "Art/C": ["Evil Neuro"],
        }
    )

    assert "saki" in registry["Art/A"]
    assert "saki" in registry["Art/B"]
    assert not {"white", "flower", "march", "evil", "neuro"} & {
        alias
        for aliases in registry.values()
        for alias in aliases
    }


def test_partial_registry_preserves_manual_multilingual_ambiguity() -> None:
    registry = build_partial_registry({})

    assert "sanae" in registry["Art/TOUHOU"]
    assert "美鈴" in registry["Art/TOUHOU"]
    assert "美鈴" in registry["Art/IDOL@MASTER"]
