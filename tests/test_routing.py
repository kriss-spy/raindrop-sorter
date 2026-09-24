from src.routing import EvidenceKind, RouteOutcome, decision_from_legacy_result


def test_legacy_visual_result_becomes_structured_evidence():
    decision = decision_from_legacy_result(
        bookmark_id=123,
        destination="Art/GAMES/GFL2",
        reason="visual_exemplar:similarity=0.820,margin=0.110",
        resulting_tags=["ai:sorted:2026-09-24"],
    )

    assert decision.outcome is RouteOutcome.CONFIRMED
    assert decision.destination == "Art/GAMES/GFL2"
    assert decision.text_evidence == ()
    assert decision.visual_evidence[0].kind is EvidenceKind.VISUAL_EXEMPLAR
    assert decision.visual_evidence[0].details == {
        "similarity": 0.82,
        "margin": 0.11,
    }


def test_legacy_review_result_retains_review_tag():
    decision = decision_from_legacy_result(
        bookmark_id=123,
        destination=None,
        reason="low_confidence:gap=0.080",
        resulting_tags=["sorter-reviewed:2026-09-24"],
    )

    assert decision.outcome is RouteOutcome.REVIEW
    assert decision.review_tag == "sorter-reviewed:2026-09-24"
    assert decision.text_evidence[0].details == {"gap": 0.08}


def test_calibrated_visual_tag_does_not_claim_vision_was_bypassed():
    decision = decision_from_legacy_result(
        bookmark_id=123,
        destination="Art/GAMES/BA",
        reason="calibrated_tag:blue_archive",
        resulting_tags=["ai:sorted:2026-09-24"],
    )

    assert decision.text_evidence == ()
    assert decision.visual_evidence[0].kind is EvidenceKind.VISUAL_CLASSIFIER
    assert "visual_verification" not in decision.visual_evidence[0].details
