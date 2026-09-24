"""Local execution path for one bookmark, independent of Modal."""

import argparse
import json
import os
from collections.abc import Callable
from typing import Any

from src.routing import RouteEngine, TextIdentifier, VisualVerifier
from src.run_journal import AttemptHandle, RunJournal, SQLiteRunJournal
from src.modality import bookmark_modality
from src.state_machine import (
    NEEDS_REVIEW_PREFIX,
    PENDING_RESOLUTION,
    PENDING_VISION_PREFIX,
    REVIEWED_PREFIX,
    UNREVIEWED,
    tag_unreviewed,
    tags_for_decision,
)
from src.tag_rules import load_series_rules, load_tag_rules
from src.vision_worker import download_cover, resolve_cover_url
from src.visual_exemplars import create_visual_embedder, load_visual_exemplar_index
from src.wd14_tagger import WD14Tagger

REQUIRED_INDEX_FILES = (
    "folder_id_map.json",
    "tag_rules.json",
)
RUNNER_VERSION = "native-two-step-v1"


def _no_vision(_bookmark: dict[str, Any]) -> list[str]:
    return []


def validate_local_index(db_path: str) -> None:
    """Fail with an actionable message when local resolver state is missing."""
    missing = [
        filename
        for filename in REQUIRED_INDEX_FILES
        if not os.path.isfile(os.path.join(db_path, filename))
    ]
    if missing:
        names = ", ".join(missing)
        raise FileNotFoundError(
            f"Local index {db_path!r} is incomplete (missing: {names}). "
            "Run `uv run python bootstrap.py --db-path chroma_db` first."
        )


def find_local_work(client: Any, *, limit: int) -> list[dict[str, Any]]:
    """Select a bounded local batch in state-machine priority order."""
    if limit < 1:
        raise ValueError("limit must be at least 1")

    state_tags = {
        str(tag["_id"])
        for tag in client.get_tags(-1)
        if str(tag.get("_id", "")) == PENDING_RESOLUTION
        or str(tag.get("_id", "")) == UNREVIEWED
        or str(tag.get("_id", "")).startswith(PENDING_VISION_PREFIX)
        or str(tag.get("_id", "")).startswith(REVIEWED_PREFIX)
        or str(tag.get("_id", "")).startswith(NEEDS_REVIEW_PREFIX)
    }
    selected: list[dict[str, Any]] = []
    selected_ids: set[int] = set()

    def collect(search: str) -> None:
        remaining = limit - len(selected)
        if remaining <= 0:
            return
        items, _has_more = client.get_raindrops(
            -1,
            perpage=remaining,
            search=search,
        )
        for item in items:
            bookmark_id = item["_id"]
            if bookmark_id not in selected_ids:
                selected.append(item)
                selected_ids.add(bookmark_id)
            if len(selected) == limit:
                break

    pending_vision_tags = sorted(
        tag for tag in state_tags if tag.startswith(PENDING_VISION_PREFIX)
    )
    for tag in pending_vision_tags:
        collect(f'#"{tag}"')

    vision_exclusions = " ".join(f'-#"{tag}"' for tag in pending_vision_tags)
    pending_search = f'#"{PENDING_RESOLUTION}"'
    if vision_exclusions:
        pending_search = f"{pending_search} {vision_exclusions}"
    collect(pending_search)

    if UNREVIEWED in state_tags:
        collect(f'#"{UNREVIEWED}"')

    state_exclusions = " ".join(f'-#"{tag}"' for tag in sorted(state_tags))
    collect(state_exclusions)
    return selected


def _load_folder_map(db_path: str) -> dict[str, int]:
    with open(
        os.path.join(db_path, "folder_id_map.json"),
        "r",
        encoding="utf-8",
    ) as handle:
        return json.load(handle)


def _has_image_source(bookmark: dict[str, Any]) -> bool:
    return bool(bookmark.get("cover")) or any(
        str(item.get("type", "")).casefold() == "image" and item.get("link")
        for item in bookmark.get("media") or []
    )


def backfill_unreviewed(
    client: Any,
    *,
    limit: int,
    apply: bool = False,
) -> dict[str, Any]:
    """Boundedly migrate untagged Unsorted bookmarks to explicit lifecycle state."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    lifecycle_tags = sorted(
        str(tag["_id"])
        for tag in client.get_tags(-1)
        if str(tag.get("_id", "")) == UNREVIEWED
        or str(tag.get("_id", "")) == PENDING_RESOLUTION
        or str(tag.get("_id", "")).startswith(
            (PENDING_VISION_PREFIX, REVIEWED_PREFIX, NEEDS_REVIEW_PREFIX)
        )
    )
    search = " ".join(f'-#"{tag}"' for tag in lifecycle_tags)
    bookmarks, _has_more = client.get_raindrops(
        -1,
        perpage=limit,
        search=search,
    )
    migrated = []
    for bookmark in bookmarks:
        tags = tag_unreviewed(bookmark)
        if apply:
            client.update_raindrop(bookmark["_id"], tags=tags)
        migrated.append({"bookmark_id": bookmark["_id"], "tags": tags})
    return {
        "status": "ok",
        "mode": "backfill_unreviewed",
        "count": len(migrated),
        "applied": apply,
        "items": migrated,
    }


def run_local_bookmark(
    client: Any,
    *,
    bookmark_id: int,
    db_path: str,
    analyze_vision: Callable[[dict[str, Any]], list[str]] = _no_vision,
    analyze_visual: Callable[[dict[str, Any]], Any | None] | None = None,
    apply: bool = False,
    journal: RunJournal | None = None,
) -> dict[str, Any]:
    """Run the native two-step route; writes require ``apply=True``."""
    validate_local_index(db_path)
    bookmark = client.get_raindrop(bookmark_id)
    attempt: AttemptHandle | None = None
    if journal is not None:
        attempt = journal.start_attempt(
            bookmark,
            mode="apply" if apply else "dry-run",
            pinned_index_version="native-local-index-v1",
            runner_version=RUNNER_VERSION,
        )

    try:
        candidate = dict(bookmark)
        folder_id_map = _load_folder_map(db_path)
        tag_rules, _mismatches = load_tag_rules(db_path)
        series_rules = load_series_rules(db_path)
        visual_index = load_visual_exemplar_index(db_path)
        text = TextIdentifier(tag_rules, series_rules).identify(candidate)
        if journal is not None and attempt is not None:
            journal.record_event(
                attempt,
                "marked_unreviewed",
                {"tags": tag_unreviewed(candidate)},
            )
            journal.record_event(attempt, "text_identified", text.to_dict())

        verifier = VisualVerifier(tag_rules, series_rules, visual_index)
        vision_tags: list[str] = []
        visual_embedding = None
        bypass = text.kind == "user_confirmed_rule"
        if not bypass and _has_image_source(candidate) and bookmark_modality(candidate) == "art":
            if journal is not None and attempt is not None:
                journal.record_event(attempt, "visual_queued")
            vision_tags = analyze_vision(candidate)
            if visual_index is not None and analyze_visual is not None:
                visual_embedding = analyze_visual(candidate)
        visual = verifier.verify(
            candidate,
            labels=vision_tags,
            embedding=visual_embedding,
            bypass=bypass,
        )
        if journal is not None and attempt is not None:
            journal.record_event(attempt, "visual_completed", visual.to_dict())

        decision = RouteEngine().route(bookmark_id=bookmark_id, text=text, visual=visual)
        target_folder = decision.destination
        target_id = folder_id_map.get(target_folder) if target_folder else None
        if target_folder is not None and target_id is None:
            raise ValueError(f"decision targets missing collection: {target_folder}")
        new_tags = tags_for_decision(candidate, decision.outcome.value)
        if journal is not None and attempt is not None:
            journal.record_decision(attempt, decision)

        action_kind = "move" if decision.destination is not None else "keep_unsorted"
        if apply:
            try:
                client.update_raindrop(
                    bookmark_id,
                    collection_id=target_id,
                    tags=new_tags,
                )
            except BaseException as error:
                if journal is not None and attempt is not None:
                    journal.record_action(
                        attempt,
                        action_kind=action_kind,
                        status="failed",
                        destination=target_folder,
                        request_count=1,
                        error_classification=type(error).__name__,
                        payload={"message": str(error)},
                    )
                raise
            if journal is not None and attempt is not None:
                journal.record_action(
                    attempt,
                    action_kind=action_kind,
                    status="succeeded",
                    destination=target_folder,
                    request_count=1,
                )
                journal.complete(attempt)
        elif journal is not None and attempt is not None:
            journal.record_action(
                attempt,
                action_kind=action_kind,
                status="planned",
                destination=target_folder,
            )
            journal.complete(attempt, phase="dry_run_completed")

        return {
            "status": "ok",
            "bookmark_id": bookmark_id,
            "attempt_id": attempt.attempt_id if attempt is not None else None,
            "action": "move" if target_id is not None else "review",
            "target_collection_id": target_id,
            "target_folder": target_folder,
            "decision": decision.to_dict(),
            "vision_tag_count": len(vision_tags),
            "applied": apply,
        }
    except BaseException as error:
        if journal is not None and attempt is not None:
            journal.fail(attempt, error)
        raise


def main(argv: list[str] | None = None) -> None:
    """Run one bookmark locally, defaulting to a safe read-only dry run."""
    from dotenv import load_dotenv

    from src.raindrop_client import RaindropClient

    parser = argparse.ArgumentParser(
        description="Resolve one Raindrop bookmark locally without Modal",
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--bookmark-id", type=int)
    target.add_argument(
        "--batch-size",
        type=int,
        help="Process a bounded queue batch (vision, resolution, then new)",
    )
    target.add_argument(
        "--backfill-unreviewed",
        type=int,
        metavar="LIMIT",
        help="Mark a bounded set of untagged Unsorted bookmarks as sorter-unreviewed",
    )
    parser.add_argument("--db-path", default="chroma_db")
    parser.add_argument(
        "--journal-path",
        help="SQLite journal path (default: <db-path>/run-journal.sqlite)",
    )
    parser.add_argument("--model-dir", default="/tmp/raindrop-sorter-wd14")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the proposed tags and destination to Raindrop",
    )
    args = parser.parse_args(argv)

    load_dotenv()
    token = os.environ.get("RAINDROP_TOKEN")
    if not token:
        parser.error("RAINDROP_TOKEN is required in the environment or .env")

    client = RaindropClient(token=token)
    if args.backfill_unreviewed is not None:
        result = backfill_unreviewed(
            client,
            limit=args.backfill_unreviewed,
            apply=args.apply,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    tagger = WD14Tagger(model_dir=args.model_dir)
    visual_index = load_visual_exemplar_index(args.db_path)
    visual_embedder = (
        create_visual_embedder(visual_index.model_name)
        if visual_index is not None
        else None
    )
    journal = SQLiteRunJournal(
        args.journal_path or os.path.join(args.db_path, "run-journal.sqlite")
    )
    image_cache: dict[int, bytes | None] = {}

    def image_bytes(bookmark: dict[str, Any]) -> bytes | None:
        bookmark_id = int(bookmark["_id"])
        if bookmark_id not in image_cache:
            url = resolve_cover_url(bookmark)
            image_cache[bookmark_id] = download_cover(url) if url else None
        return image_cache[bookmark_id]

    def visual_embedding(bookmark: dict[str, Any]) -> Any | None:
        payload = image_bytes(bookmark)
        if visual_embedder is None or payload is None:
            return None
        return visual_embedder.embed_image(payload)

    run_one = lambda bookmark_id: run_local_bookmark(
        client,
        bookmark_id=bookmark_id,
        db_path=args.db_path,
        analyze_vision=lambda bookmark: [
            f"ai:wdtag-{tag}" for tag in tagger.predict(image_bytes(bookmark))
        ] if image_bytes(bookmark) is not None else [],
        analyze_visual=visual_embedding,
        apply=args.apply,
        journal=journal,
    )
    if args.bookmark_id is not None:
        result: dict[str, Any] = run_one(args.bookmark_id)
    else:
        work = find_local_work(client, limit=args.batch_size)
        results = [run_one(item["_id"]) for item in work]
        result = {
            "status": "ok",
            "mode": "batch",
            "count": len(results),
            "applied": args.apply,
            "results": results,
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
