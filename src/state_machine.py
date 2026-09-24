"""Tag-based state machine using Raindrop tags as the sole ledger."""

from datetime import datetime, timezone
from typing import Any

# Tag prefixes
PENDING_VISION_PREFIX = "sorter-pending-vision"
PENDING_RESOLUTION = "sorter-pending-resolution"
REVIEWED_PREFIX = "sorter-reviewed"
SORTED_PREFIX = "ai:sorted"
NEW_RULE_PREFIX = "ai:new-rule"
VISION_ATTEMPTED = "sorter-vision-attempted"
UNREVIEWED = "sorter-unreviewed"
NEEDS_REVIEW_PREFIX = "sorter-needs-review"
EDGE_CASE_PREFIX = "sorter-edge-case"
CONFLICT_TAG = "sorter-edge-case:conflict"
LIFECYCLE_PREFIXES = (
    UNREVIEWED,
    PENDING_VISION_PREFIX,
    PENDING_RESOLUTION,
    REVIEWED_PREFIX,
    NEEDS_REVIEW_PREFIX,
)


def _today_tag(prefix: str) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"{prefix}:{today}"


def get_clean_tags(bookmark: dict[str, Any]) -> list[str]:
    """Return the bookmark's tags with transient AI tags stripped."""
    tags = bookmark.get("tags", [])
    return cleanup_transient_tags(tags)


def cleanup_transient_tags(tags: list[str]) -> list[str]:
    """Remove transient extraction tags so the Raindrop tag cloud stays clean."""
    return [t for t in tags if not t.startswith(("ai:wdtag-", "ai:sauce-"))]


def add_tag(tags: list[str], new_tag: str) -> list[str]:
    """Add a tag if not already present."""
    if new_tag in tags:
        return tags
    return tags + [new_tag]


def remove_tag(tags: list[str], tag_to_remove: str) -> list[str]:
    """Remove a specific tag."""
    return [t for t in tags if t != tag_to_remove]


def remove_tags_by_prefix(tags: list[str], prefix: str) -> list[str]:
    """Remove all tags starting with a prefix."""
    return [t for t in tags if not t.startswith(prefix)]


def tag_pending_vision(bookmark: dict[str, Any]) -> list[str]:
    """Tag a bookmark as awaiting vision worker."""
    tags = get_clean_tags(bookmark)
    tags = remove_tags_by_prefix(tags, PENDING_VISION_PREFIX)
    tags = remove_tags_by_prefix(tags, PENDING_RESOLUTION)
    return add_tag(tags, _today_tag(PENDING_VISION_PREFIX))


def tag_pending_resolution(bookmark: dict[str, Any]) -> list[str]:
    """Tag a bookmark as awaiting resolver."""
    tags = get_clean_tags(bookmark)
    tags = remove_tags_by_prefix(tags, PENDING_VISION_PREFIX)
    tags = remove_tags_by_prefix(tags, REVIEWED_PREFIX)
    return add_tag(tags, PENDING_RESOLUTION)


def tag_after_vision(bookmark: dict[str, Any]) -> list[str]:
    """Transition from pending-vision to pending-resolution, preserving WD14 tags."""
    tags = bookmark.get("tags", [])
    tags = remove_tags_by_prefix(tags, PENDING_VISION_PREFIX)
    tags = remove_tags_by_prefix(tags, REVIEWED_PREFIX)
    tags = add_tag(tags, VISION_ATTEMPTED)
    return add_tag(tags, PENDING_RESOLUTION)


def tag_reviewed(bookmark: dict[str, Any]) -> list[str]:
    """Tag a bookmark as reviewed (stayed in Unsorted).

    Preserves ai:wdtag-* tags so vision results are not lost on review.
    """
    tags = bookmark.get("tags", [])
    tags = remove_tags_by_prefix(tags, PENDING_VISION_PREFIX)
    tags = remove_tags_by_prefix(tags, PENDING_RESOLUTION)
    tags = remove_tags_by_prefix(tags, REVIEWED_PREFIX)
    tags = remove_tag(tags, VISION_ATTEMPTED)
    return add_tag(tags, _today_tag(REVIEWED_PREFIX))


def tag_sorted(bookmark: dict[str, Any], by_rule: str | None = None) -> list[str]:
    """Tag a bookmark as successfully sorted."""
    tags = cleanup_transient_tags(bookmark.get("tags", []))
    tags = remove_tags_by_prefix(tags, PENDING_VISION_PREFIX)
    tags = remove_tags_by_prefix(tags, PENDING_RESOLUTION)
    tags = remove_tags_by_prefix(tags, REVIEWED_PREFIX)
    tags = remove_tag(tags, VISION_ATTEMPTED)
    tags = add_tag(tags, _today_tag(SORTED_PREFIX))
    if by_rule:
        tags = add_tag(tags, f"{NEW_RULE_PREFIX}-{by_rule}")
    return tags


def is_pending_resolution(bookmark: dict[str, Any]) -> bool:
    """Check if a bookmark is tagged as pending resolution."""
    tags = bookmark.get("tags", [])
    return PENDING_RESOLUTION in tags


def is_pending_vision(bookmark: dict[str, Any]) -> bool:
    """Check if a bookmark is tagged as awaiting vision worker."""
    tags = bookmark.get("tags", [])
    return any(t.startswith(PENDING_VISION_PREFIX) for t in tags)


def has_vision_tags(bookmark: dict[str, Any]) -> bool:
    """Check if a bookmark has WD14 extraction tags."""
    tags = bookmark.get("tags", [])
    return any(t.startswith("ai:wdtag-") for t in tags)


def has_completed_vision(bookmark: dict[str, Any]) -> bool:
    """Check whether vision ran, even when it detected no usable tags."""
    return VISION_ATTEMPTED in bookmark.get("tags", []) or has_vision_tags(bookmark)


def is_reviewed(bookmark: dict[str, Any]) -> bool:
    """Check if a bookmark has been reviewed (low confidence)."""
    tags = bookmark.get("tags", [])
    return any(t.startswith(REVIEWED_PREFIX) for t in tags)


def strip_reviewed_tags(tags: list[str]) -> list[str]:
    """Remove sorter-reviewed tags so the Watcher retries the bookmark."""
    return remove_tags_by_prefix(tags, REVIEWED_PREFIX)


def has_sorter_lifecycle(bookmark: dict[str, Any]) -> bool:
    """Whether a bookmark has any explicit sorter lifecycle state."""
    return any(
        str(tag).startswith(LIFECYCLE_PREFIXES)
        for tag in bookmark.get("tags", [])
    )


def tag_unreviewed(bookmark: dict[str, Any]) -> list[str]:
    """Mark a newly discovered Unsorted bookmark without deciding it."""
    tags = _without_final_lifecycle(bookmark.get("tags", []))
    return add_tag(tags, UNREVIEWED)


def tags_for_decision(bookmark: dict[str, Any], outcome: str) -> list[str]:
    """Render the revised decision policy into mutually exclusive Raindrop tags."""
    tags = cleanup_transient_tags(bookmark.get("tags", []))
    tags = [
        tag
        for tag in tags
        if not str(tag).startswith((*LIFECYCLE_PREFIXES, EDGE_CASE_PREFIX))
        and tag != VISION_ATTEMPTED
    ]
    if outcome == "confirmed":
        return add_tag(tags, _today_tag(SORTED_PREFIX))
    if outcome == "provisional":
        return add_tag(tags, _today_tag(NEEDS_REVIEW_PREFIX))
    tags = add_tag(tags, _today_tag(REVIEWED_PREFIX))
    if outcome == "conflict":
        tags = add_tag(tags, CONFLICT_TAG)
    return tags


def _without_final_lifecycle(tags: list[str]) -> list[str]:
    return [
        tag
        for tag in cleanup_transient_tags(tags)
        if not str(tag).startswith(
            (REVIEWED_PREFIX, NEEDS_REVIEW_PREFIX, SORTED_PREFIX, EDGE_CASE_PREFIX)
        )
    ]
