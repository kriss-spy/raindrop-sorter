"""Read-only local canary for the vision-to-resolution pipeline."""

import argparse
import json
import os
from collections.abc import Callable
from typing import Any

from src.centroids import load_centroids
from src.resolver import resolve_bookmark
from src.state_machine import is_pending_vision, tag_after_vision
from src.tag_rules import load_series_rules, load_tag_rules
from src.vision_worker import run_vision_on_bookmark
from src.wd14_tagger import WD14Tagger


def run_local_canary(
    client: Any,
    *,
    bookmark_id: int,
    db_path: str,
    analyze_vision: Callable[[dict[str, Any]], list[str]] = run_vision_on_bookmark,
    embedder: Any | None = None,
) -> dict[str, Any]:
    """Evaluate one pending-vision bookmark end to end without writing it."""
    bookmark = client.get_raindrop(bookmark_id)
    if not is_pending_vision(bookmark):
        raise ValueError(f"Bookmark {bookmark_id} is not pending vision")

    vision_tags = analyze_vision(bookmark)
    transitioned_tags = tag_after_vision(bookmark)
    for tag in vision_tags:
        if tag not in transitioned_tags:
            transitioned_tags.append(tag)

    candidate = dict(bookmark)
    candidate["tags"] = transitioned_tags

    with open(
        os.path.join(db_path, "folder_id_map.json"),
        "r",
        encoding="utf-8",
    ) as handle:
        folder_id_map = json.load(handle)
    candidate["_folder_id_map"] = folder_id_map

    centroids = load_centroids(db_path)
    rules, _mismatches = load_tag_rules(db_path)
    series_rules = load_series_rules(db_path)
    target_id, new_tags, reason = resolve_bookmark(
        candidate,
        centroids,
        rules,
        embedder=embedder,
        series_rules=series_rules,
    )
    folder_by_id = {collection_id: path for path, collection_id in folder_id_map.items()}

    return {
        "status": "ok",
        "dry_run": True,
        "bookmark_id": bookmark_id,
        "vision_tag_count": len(vision_tags),
        "target_collection_id": target_id,
        "target_folder": folder_by_id.get(target_id),
        "reason": reason,
        "result_state_tags": [
            tag
            for tag in new_tags
            if tag.startswith(("sorter-", "ai:sorted:"))
        ],
    }


def main(argv: list[str] | None = None) -> None:
    """Run one real bookmark through the local pipeline without updating it."""
    from dotenv import load_dotenv

    from src.raindrop_client import RaindropClient

    parser = argparse.ArgumentParser(
        description="Dry-run one pending-vision bookmark through WD14 and Resolver",
    )
    parser.add_argument("--bookmark-id", type=int, required=True)
    parser.add_argument("--db-path", default="chroma_db")
    parser.add_argument("--model-dir", default="/tmp/raindrop-sorter-wd14")
    args = parser.parse_args(argv)

    load_dotenv()
    token = os.environ.get("RAINDROP_TOKEN")
    if not token:
        parser.error("RAINDROP_TOKEN is required in the environment or .env")

    tagger = WD14Tagger(model_dir=args.model_dir)
    result = run_local_canary(
        RaindropClient(token=token),
        bookmark_id=args.bookmark_id,
        db_path=args.db_path,
        analyze_vision=lambda bookmark: run_vision_on_bookmark(bookmark, tagger=tagger),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
