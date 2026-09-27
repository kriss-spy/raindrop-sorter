from pathlib import Path

from scripts.generate_ai_sort_report import load_review_sample, render_report
from src.cover_cache import SQLiteCoverCache
from src.routing import RouteDecision, RouteOutcome, VisualEvidence
from src.run_journal import SQLiteRunJournal


def _record_review(
    journal: SQLiteRunJournal,
    cover_cache: SQLiteCoverCache,
    bookmark_id: int,
    title: str,
    labels: tuple[str, ...],
) -> None:
    bookmark = {
        "_id": bookmark_id,
        "title": title,
        "link": f"https://example.test/{bookmark_id}",
        "cover": f"https://cdn.test/{bookmark_id}.webp",
    }
    attempt = journal.start_attempt(bookmark, mode="apply")
    journal.record_decision(
        attempt,
        RouteDecision(
            bookmark_id=bookmark_id,
            outcome=RouteOutcome.REVIEW,
            destination=None,
            text_evidence=(),
            visual_evidence=(VisualEvidence(
                status="inconclusive",
                destination=None,
                method="wd14+visual_exemplar",
                explanation="Review visual labels.",
                labels=labels,
            ),),
            summary="Needs review.",
        ),
    )
    journal.complete(attempt)
    cover_cache.record(bookmark)


def test_ai_sort_report_samples_review_apply_records_and_loads_images_smartly(
    tmp_path: Path,
) -> None:
    journal_path = tmp_path / "run-journal.sqlite"
    cover_path = tmp_path / "cover-cache.sqlite"
    journal = SQLiteRunJournal(journal_path)
    covers = SQLiteCoverCache(cover_path)
    _record_review(journal, covers, 1, "Halo one", ("1girl", "halo", "blue_hair"))
    _record_review(journal, covers, 2, "Red dress", ("1girl", "red_hair", "dress"))
    _record_review(
        journal,
        covers,
        3,
        "Halo two",
        ("1girl", "halo", "blue_hair", "school_uniform"),
    )

    records = load_review_sample(
        journal_path,
        cover_path,
        sample_size=3,
        seed=7,
    )
    page = render_report(records, seed=7, candidate_count=3)

    assert {record["bookmark_id"] for record in records} == {1, 2, 3}
    assert [record["title"] for record in records[:2]] == ["Halo two", "Halo one"]
    assert 'data-src="https://cdn.test/' in page
    assert ' src="https://cdn.test/' not in page
    assert "IntersectionObserver" in page
    assert "MAX_CONCURRENT_IMAGES=4" in page
    assert "outcome:review mode:apply" in page
    assert "Random seed 7" in page
