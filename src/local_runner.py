"""Local execution path for one bookmark, independent of Modal."""

import argparse
import json
import os
from collections.abc import Callable
from typing import Any

from src.centroids import load_centroids
from src.resolver import decide_folder_by_rule, resolve_bookmark
from src.routing import decision_from_legacy_result
from src.run_journal import AttemptHandle, RunJournal, SQLiteRunJournal
from src.state_machine import (
    PENDING_RESOLUTION,
    PENDING_VISION_PREFIX,
    REVIEWED_PREFIX,
    has_completed_vision,
    is_pending_vision,
    tag_after_vision,
)
from src.tag_rules import load_series_rules, load_tag_rules
from src.vision_worker import run_vision_on_bookmark, run_visual_embedding_on_bookmark
from src.visual_exemplars import create_visual_embedder, load_visual_exemplar_index
from src.wd14_tagger import WD14Tagger

REQUIRED_INDEX_FILES = (
    "centroids.json",
    "folder_id_map.json",
    "tag_rules.json",
)
RUNNER_VERSION = "local-structured-journal-v1"


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
        or str(tag.get("_id", "")).startswith(PENDING_VISION_PREFIX)
        or str(tag.get("_id", "")).startswith(REVIEWED_PREFIX)
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


def run_local_bookmark(
    client: Any,
    *,
    bookmark_id: int,
    db_path: str,
    analyze_vision: Callable[[dict[str, Any]], list[str]] = run_vision_on_bookmark,
    analyze_visual: Callable[[dict[str, Any]], Any | None] | None = None,
    embedder: Any | None = None,
    apply: bool = False,
    journal: RunJournal | None = None,
) -> dict[str, Any]:
    """Resolve one live bookmark locally; writes require ``apply=True``."""
    validate_local_index(db_path)
    bookmark = client.get_raindrop(bookmark_id)
    attempt: AttemptHandle | None = None
    if journal is not None:
        attempt = journal.start_attempt(
            bookmark,
            mode="apply" if apply else "dry-run",
            pinned_index_version="legacy-local-index",
            runner_version=RUNNER_VERSION,
        )

    try:
        candidate = dict(bookmark)
        folder_id_map = _load_folder_map(db_path)
        candidate["_folder_id_map"] = folder_id_map
        centroids = load_centroids(db_path)
        tag_rules, _mismatches = load_tag_rules(db_path)
        series_rules = load_series_rules(db_path)
        visual_index = load_visual_exemplar_index(db_path)
        vision_tags: list[str] = []
        visual_event_recorded = False

        initial_rule_folder, initial_rule_reason = decide_folder_by_rule(
            candidate,
            tag_rules,
            series_rules=series_rules,
        )
        if journal is not None and attempt is not None:
            journal.record_event(
                attempt,
                "text_identified",
                {
                    "destination": initial_rule_folder,
                    "legacy_reason": initial_rule_reason,
                },
            )

        def run_vision() -> None:
            nonlocal candidate, vision_tags, visual_event_recorded
            if journal is not None and attempt is not None:
                journal.record_event(attempt, "visual_queued")
            vision_tags = analyze_vision(candidate)
            transitioned_tags = tag_after_vision(candidate)
            for tag in vision_tags:
                if tag not in transitioned_tags:
                    transitioned_tags.append(tag)
            candidate = dict(candidate)
            candidate["tags"] = transitioned_tags
            if visual_index is not None and analyze_visual is not None:
                visual_embedding = analyze_visual(candidate)
                if visual_embedding is not None:
                    candidate["_visual_embedding"] = visual_embedding
            if journal is not None and attempt is not None:
                journal.record_event(
                    attempt,
                    "visual_completed",
                    {"status": "available", "labels": vision_tags},
                )
                visual_event_recorded = True

        if is_pending_vision(candidate):
            if initial_rule_folder is None:
                run_vision()

        target_id, new_tags, reason = resolve_bookmark(
            candidate,
            centroids,
            tag_rules,
            embedder=embedder,
            series_rules=series_rules,
            visual_index=visual_index,
        )

        if (
            visual_index is not None
            and analyze_visual is not None
            and candidate.get("cover")
            and candidate.get("_visual_embedding") is None
            and (reason == "visual_art_fallback" or reason.startswith("low_confidence"))
        ):
            if journal is not None and attempt is not None:
                journal.record_event(attempt, "visual_queued", {"kind": "exemplar"})
            visual_embedding = analyze_visual(candidate)
            if visual_embedding is not None:
                candidate["_visual_embedding"] = visual_embedding
                target_id, new_tags, reason = resolve_bookmark(
                    candidate,
                    centroids,
                    tag_rules,
                    embedder=embedder,
                    series_rules=series_rules,
                    visual_index=visual_index,
                )
            if journal is not None and attempt is not None:
                journal.record_event(
                    attempt,
                    "visual_completed",
                    {"kind": "exemplar", "embedding_available": visual_embedding is not None},
                )
                visual_event_recorded = True

        if (
            target_id is None
            and reason.startswith("low_confidence")
            and candidate.get("cover")
            and not has_completed_vision(candidate)
        ):
            run_vision()
            target_id, new_tags, reason = resolve_bookmark(
                candidate,
                centroids,
                tag_rules,
                embedder=embedder,
                series_rules=series_rules,
                visual_index=visual_index,
            )

        if journal is not None and attempt is not None and not visual_event_recorded:
            existing_labels = [
                tag for tag in candidate.get("tags", []) if tag.startswith("ai:wdtag-")
            ]
            if has_completed_vision(candidate):
                visual_status = "preexisting"
            elif initial_rule_reason.startswith(
                ("user_calibration:", "calibrated_tag:", "calibrated_source:")
            ):
                visual_status = "bypassed_by_user_confirmed_rule"
            elif not candidate.get("cover"):
                visual_status = "not_applicable"
            else:
                visual_status = "not_run_by_legacy_policy"
            journal.record_event(
                attempt,
                "visual_completed",
                {"status": visual_status, "labels": existing_labels},
            )

        folder_by_id = {
            collection_id: path for path, collection_id in folder_id_map.items()
        }
        target_folder = folder_by_id.get(target_id)
        decision = decision_from_legacy_result(
            bookmark_id=bookmark_id,
            destination=target_folder,
            reason=reason,
            resulting_tags=new_tags,
        )
        if journal is not None and attempt is not None:
            journal.record_decision(attempt, decision)

        action_kind = "move" if target_id is not None else "keep_unsorted"
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
            "reason": reason,
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

    from src.embeddings import Embedder
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

    tagger = WD14Tagger(model_dir=args.model_dir)
    visual_index = load_visual_exemplar_index(args.db_path)
    visual_embedder = (
        create_visual_embedder(visual_index.model_name)
        if visual_index is not None
        else None
    )
    client = RaindropClient(token=token)
    embedder = Embedder()
    journal = SQLiteRunJournal(
        args.journal_path or os.path.join(args.db_path, "run-journal.sqlite")
    )
    run_one = lambda bookmark_id: run_local_bookmark(
        client,
        bookmark_id=bookmark_id,
        db_path=args.db_path,
        analyze_vision=lambda bookmark: run_vision_on_bookmark(bookmark, tagger=tagger),
        analyze_visual=(
            lambda bookmark: run_visual_embedding_on_bookmark(
                bookmark,
                visual_embedder,
            )
            if visual_embedder is not None
            else None
        ),
        embedder=embedder,
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
