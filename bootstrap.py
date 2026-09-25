"""Bootstrap script: crawl existing Raindrop library, build ChromaDB, compute centroids, upload to Modal Volume."""

import argparse
import json
import os
import shutil
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

import chromadb
from dotenv import load_dotenv

from src.centroids import compute_folder_centroids, save_centroids
from src.embeddings import Embedder, build_text_input
from src.raindrop_client import RaindropClient
from src.reindex import build_folder_hierarchy, build_folder_map
from src.tag_rules import (
    extract_candidate_tag_rules,
    extract_series_rules,
    save_series_rules,
    save_tag_rules,
)
from src.visual_learning import (
    VisualLearningConfig,
    learn_visual_rules,
)


def crawl_all_bookmarks(
    client: RaindropClient,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Crawl bookmarks and return them with collections and UI groups."""
    print("Fetching collections...")
    collections = client.get_collections()
    groups = client.get_collection_groups()
    print(f"Found {len(collections)} collections.")

    folder_map = build_folder_map(collections, groups)
    id_to_path_map = {cid: path for path, cid in folder_map.items()}

    all_bookmarks: list[dict[str, Any]] = []
    for coll in collections:
        cid = coll["_id"]
        # Skip special collections like Trash (-99) if present
        if cid == -99:
            continue
        path = id_to_path_map.get(cid, str(cid))
        print(f"  Crawling '{path}' (id={cid})...")
        items = client.get_all_raindrops(cid)
        for item in items:
            item["folder_path"] = path
            item["_collection_id"] = cid
        all_bookmarks.extend(items)

    print(f"Total bookmarks: {len(all_bookmarks)}")
    return all_bookmarks, collections, groups


def bootstrap(
    client: RaindropClient,
    db_path: str = "chroma_db",
    upload_to_modal: bool = False,
    visual_analyzer: Callable[[dict[str, Any]], list[str]] | None = None,
    visual_learning_config: VisualLearningConfig | None = None,
    visual_model_dir: str = ".scratch/wd14_model",
) -> None:
    """Main bootstrap routine."""
    # 1. Crawl
    bookmarks, collections, groups = crawl_all_bookmarks(client)

    if not bookmarks:
        print("No bookmarks found. Nothing to bootstrap.")
        return

    # 2. Learn character routes from a bounded historical cover sample.
    visual_learning_config = visual_learning_config or VisualLearningConfig()
    if visual_analyzer is None:
        from src.vision_worker import run_character_vision_on_bookmark
        from src.wd14_tagger import WD14Tagger

        tagger = WD14Tagger(model_dir=visual_model_dir)
        visual_analyzer = lambda bookmark: run_character_vision_on_bookmark(
            bookmark,
            tagger=tagger,
        )
    visual_result = learn_visual_rules(
        bookmarks,
        analyze=visual_analyzer,
        config=visual_learning_config,
    )
    bookmarks_by_id = {int(bookmark["_id"]): bookmark for bookmark in bookmarks}
    for bookmark_id, detected_tags in visual_result.tags_by_bookmark_id.items():
        bookmark = bookmarks_by_id[bookmark_id]
        tags = list(bookmark.get("tags", []))
        for tag in detected_tags:
            vision_tag = f"ai:wdtag-{tag}"
            if vision_tag not in tags:
                tags.append(vision_tag)
        bookmark["tags"] = tags
    print(
        "Visual learning: "
        f"samples={visual_result.samples_analyzed}, "
        f"rules={len(visual_result.rules)}, "
        f"stop={visual_result.stop_reason}"
    )

    # 3. Build embeddings
    print("Building text embeddings...")
    embedder = Embedder()
    texts = [build_text_input(bm) for bm in bookmarks]
    embeddings = embedder.embed(texts)

    # 4. Store in ChromaDB
    print(f"Storing embeddings in {db_path}...")
    if os.path.exists(db_path):
        shutil.rmtree(db_path)
    os.makedirs(db_path, exist_ok=True)
    with open(
        os.path.join(db_path, "visual_learning.json"),
        "w",
        encoding="utf-8",
    ) as handle:
        json.dump(
            {
                "samples_analyzed": visual_result.samples_analyzed,
                "analysis_failures": visual_result.analysis_failures,
                "eligible_candidates": visual_result.eligible_candidates,
                "folders_selected": visual_result.folders_selected,
                "rules_learned": len(visual_result.rules),
                "stop_reason": visual_result.stop_reason,
                "config": asdict(visual_learning_config),
            },
            handle,
            indent=2,
        )

    chroma_client = chromadb.PersistentClient(path=db_path)
    collection = chroma_client.get_or_create_collection(name="bookmarks")

    ids = [str(bm["_id"]) for bm in bookmarks]
    metadatas = []
    for bm in bookmarks:
        meta = {
            "title": bm.get("title", ""),
            "folder_path": bm.get("folder_path", ""),
            "last_seen_folder": bm.get("folder_path", ""),
            "domain": bm.get("domain", ""),
            "tags": ",".join(bm.get("tags", [])),
        }
        metadatas.append(meta)

    # Add in batches to avoid overwhelming ChromaDB
    batch_size = 100
    for i in range(0, len(ids), batch_size):
        end = i + batch_size
        collection.add(
            ids=ids[i:end],
            embeddings=embeddings[i:end].tolist(),
            metadatas=metadatas[i:end],
        )

    # 5. Compute centroids
    print("Computing folder centroids...")
    folders = [bm.get("folder_path", "") for bm in bookmarks]
    hierarchy = build_folder_hierarchy(collections, groups)
    centroids = compute_folder_centroids(embeddings, folders, hierarchy)
    save_centroids(centroids, db_path)
    print(f"  Computed {len(centroids)} centroids.")

    # 6. Extract candidate tag rules
    print("Extracting candidate tag rules...")
    candidate_rules = extract_candidate_tag_rules(bookmarks)
    candidate_rules.update(visual_result.rules)
    save_tag_rules(candidate_rules, {}, db_path)
    print(f"  Found {len(candidate_rules)} candidate rules.")

    # 7. Build folder ID map and save
    folder_id_map = build_folder_map(collections, groups)
    save_series_rules(extract_series_rules(list(folder_id_map)), db_path)
    with open(os.path.join(db_path, "folder_id_map.json"), "w", encoding="utf-8") as f:
        json.dump(folder_id_map, f, indent=2)

    print("Bootstrap complete.")

    if upload_to_modal:
        print("Uploading to Modal Volume...")
        upload_volume(db_path)
        print("Upload complete.")


def upload_volume(local_path: str) -> None:
    """Upload the local ChromaDB directory to Modal Volume."""
    import modal

    vol = modal.Volume.from_name("raindrop-sorter-vol", create_if_missing=True)

    try:
        vol.remove_file("/chroma_db", recursive=True)
    except FileNotFoundError:
        pass

    with vol.batch_upload() as upload:
        upload.put_directory(local_path, "/chroma_db")


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Bootstrap Raindrop Sorter")
    parser.add_argument("--db-path", default="chroma_db", help="Local ChromaDB path")
    parser.add_argument("--upload", action="store_true", help="Upload to Modal Volume after bootstrap")
    parser.add_argument(
        "--vision-max-samples",
        type=int,
        default=192,
        help="Hard ceiling for historical covers analyzed by WD14 (0 disables)",
    )
    parser.add_argument(
        "--vision-max-folders",
        type=int,
        default=32,
        help="Focus visual learning on this many image-heavy folders",
    )
    parser.add_argument("--vision-min-support", type=int, default=3)
    parser.add_argument("--vision-min-purity", type=float, default=0.9)
    parser.add_argument("--vision-stability-patience", type=int, default=48)
    parser.add_argument("--vision-min-folder-rounds", type=int, default=2)
    parser.add_argument(
        "--vision-model-dir",
        default=".cache/wd14",
        help="Reusable local WD14 model cache",
    )
    args = parser.parse_args()

    token = os.environ.get("RAINDROP_TOKEN")
    if not token:
        raise RuntimeError("RAINDROP_TOKEN environment variable is required.")

    client = RaindropClient(token=token)
    bootstrap(
        client,
        db_path=args.db_path,
        upload_to_modal=args.upload,
        visual_learning_config=VisualLearningConfig(
            max_samples=args.vision_max_samples,
            max_folders=args.vision_max_folders,
            min_tag_support=args.vision_min_support,
            min_tag_purity=args.vision_min_purity,
            stability_patience=args.vision_stability_patience,
            min_folder_rounds=args.vision_min_folder_rounds,
        ),
        visual_model_dir=args.vision_model_dir,
    )


if __name__ == "__main__":
    main()
