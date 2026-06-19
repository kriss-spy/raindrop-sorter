"""Bootstrap script: crawl existing Raindrop library, build ChromaDB, compute centroids, upload to Modal Volume."""

import argparse
import os
import shutil
from typing import Any

import chromadb
from dotenv import load_dotenv

from src.centroids import compute_folder_centroids, save_centroids
from src.embeddings import Embedder, build_text_input
from src.raindrop_client import RaindropClient
from src.tag_rules import extract_candidate_tag_rules, save_tag_rules


def build_folder_map(collections: list[dict[str, Any]]) -> dict[str, int]:
    """Map folder path -> collection ID."""
    # Build lookup by id first
    by_id: dict[int, dict[str, Any]] = {c["_id"]: c for c in collections}

    def path_for(cid: int) -> str:
        c = by_id[cid]
        name = c.get("title", "")
        parent = c.get("parent", {}).get("$id")
        if parent and parent in by_id:
            return f"{path_for(parent)}/{name}"
        return name

    return {path_for(c["_id"]): c["_id"] for c in collections}


def build_folder_hierarchy(collections: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Build parent -> [children] mapping using folder paths."""
    by_id = {c["_id"]: c for c in collections}
    folder_map = build_folder_map(collections)

    def path_for(cid: int) -> str:
        c = by_id[cid]
        name = c.get("title", "")
        parent = c.get("parent", {}).get("$id")
        if parent and parent in by_id:
            return f"{path_for(parent)}/{name}"
        return name

    hierarchy: dict[str, list[str]] = {}
    for c in collections:
        parent = c.get("parent", {}).get("$id")
        if parent and parent in by_id:
            parent_path = path_for(parent)
            child_path = path_for(c["_id"])
            hierarchy.setdefault(parent_path, []).append(child_path)

    return hierarchy


def crawl_all_bookmarks(client: RaindropClient) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Crawl all collections and their bookmarks. Returns (bookmarks, collections)."""
    print("Fetching collections...")
    collections = client.get_collections()
    print(f"Found {len(collections)} collections.")

    folder_map = build_folder_map(collections)

    all_bookmarks: list[dict[str, Any]] = []
    for coll in collections:
        cid = coll["_id"]
        # Skip special collections like Trash (-99) if present
        if cid == -99:
            continue
        path = folder_map.get(cid, str(cid))
        print(f"  Crawling '{path}' (id={cid})...")
        items = client.get_all_raindrops(cid)
        for item in items:
            item["folder_path"] = path
            item["_collection_id"] = cid
        all_bookmarks.extend(items)

    print(f"Total bookmarks: {len(all_bookmarks)}")
    return all_bookmarks, collections


def bootstrap(
    client: RaindropClient,
    db_path: str = "chroma_db",
    upload_to_modal: bool = False,
) -> None:
    """Main bootstrap routine."""
    # 1. Crawl
    bookmarks, collections = crawl_all_bookmarks(client)

    if not bookmarks:
        print("No bookmarks found. Nothing to bootstrap.")
        return

    # 2. Build embeddings
    print("Building text embeddings...")
    embedder = Embedder()
    texts = [build_text_input(bm) for bm in bookmarks]
    embeddings = embedder.embed(texts)

    # 3. Store in ChromaDB
    print(f"Storing embeddings in {db_path}...")
    if os.path.exists(db_path):
        shutil.rmtree(db_path)
    os.makedirs(db_path, exist_ok=True)

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

    # 4. Compute centroids
    print("Computing folder centroids...")
    folders = [bm.get("folder_path", "") for bm in bookmarks]
    hierarchy = build_folder_hierarchy(collections)
    centroids = compute_folder_centroids(embeddings, folders, hierarchy)
    save_centroids(centroids, db_path)
    print(f"  Computed {len(centroids)} centroids.")

    # 5. Extract candidate tag rules
    print("Extracting candidate tag rules...")
    candidate_rules = extract_candidate_tag_rules(bookmarks)
    save_tag_rules(candidate_rules, {}, db_path)
    print(f"  Found {len(candidate_rules)} candidate rules.")

    # 6. Build folder ID map and save
    folder_id_map = build_folder_map(collections)
    import json
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

    # Assumes a Modal Volume named 'raindrop-sorter-vol' exists
    vol = modal.Volume.from_name("raindrop-sorter-vol", create_if_missing=True)

    # Modal Volume operations happen inside a function context
    @modal.function(volumes={"/data": vol})
    def _upload():
        import shutil
        dest = "/data/chroma_db"
        if os.path.exists(dest):
            shutil.rmtree(dest)
        shutil.copytree(local_path, dest)
        return f"Uploaded to {dest}"

    result = _upload.remote()
    print(result)


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Bootstrap Raindrop Sorter")
    parser.add_argument("--db-path", default="chroma_db", help="Local ChromaDB path")
    parser.add_argument("--upload", action="store_true", help="Upload to Modal Volume after bootstrap")
    args = parser.parse_args()

    token = os.environ.get("RAINDROP_TOKEN")
    if not token:
        raise RuntimeError("RAINDROP_TOKEN environment variable is required.")

    client = RaindropClient(token=token)
    bootstrap(client, db_path=args.db_path, upload_to_modal=args.upload)


if __name__ == "__main__":
    main()
