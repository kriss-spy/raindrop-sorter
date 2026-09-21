"""Build and validate a bounded local visual exemplar index."""

import argparse
import html
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
from dotenv import load_dotenv

from src.raindrop_client import RaindropClient
from src.vision_worker import resolve_cover_url, run_visual_embedding_on_bookmark
from src.visual_exemplars import (
    DEFAULT_VISUAL_MODEL,
    LocalVisualEmbeddingCache,
    VisualDecision,
    VisualEvaluation,
    VisualExemplarIndex,
    create_visual_embedder,
    evaluate_visual_index,
    partition_visual_examples,
    save_visual_exemplar_index,
)

DEFAULT_FOLDERS = [
    "Art/GAMES/GFL2",
    "Art/GAMES/Arknights Endfield",
    "Art/GAMES/GENSHIN",
    "Art/GAMES/GALGAME",
    "Art/GAMES/BA/gaki",
]


def _load_folder_map(db_path: str) -> dict[str, int]:
    with open(
        os.path.join(db_path, "folder_id_map.json"),
        encoding="utf-8",
    ) as handle:
        return json.load(handle)


def _crawl_target_bookmarks(
    client: RaindropClient,
    folder_map: dict[str, int],
    folder_paths: list[str],
) -> list[dict[str, Any]]:
    bookmarks: list[dict[str, Any]] = []
    for folder in folder_paths:
        collection_id = folder_map.get(folder)
        if collection_id is None:
            raise ValueError(f"Target folder is missing from the local index: {folder}")
        items = client.get_all_raindrops(collection_id)
        for item in items:
            item["folder_path"] = folder
        bookmarks.extend(items)
        print(f"Fetched {len(items)} bookmarks from {folder}", flush=True)
    return bookmarks


def _make_index(
    bookmarks: list[dict[str, Any]],
    embeddings: dict[int, np.ndarray],
    *,
    min_similarity: float = 0.80,
    min_margin: float = 0.03,
    model_name: str = DEFAULT_VISUAL_MODEL,
    neighbors_per_folder: int = 3,
) -> VisualExemplarIndex:
    available = [item for item in bookmarks if int(item["_id"]) in embeddings]
    return VisualExemplarIndex(
        embeddings=np.asarray(
            [embeddings[int(item["_id"])] for item in available],
            dtype=np.float32,
        ),
        folder_paths=[str(item["folder_path"]) for item in available],
        bookmark_ids=[int(item["_id"]) for item in available],
        min_similarity=min_similarity,
        min_margin=min_margin,
        model_name=model_name,
        neighbors_per_folder=neighbors_per_folder,
    )


def _calibrate_thresholds(
    holdout: list[dict[str, Any]],
    holdout_embeddings: dict[int, np.ndarray],
    index: VisualExemplarIndex,
) -> tuple[float, float, int, VisualEvaluation]:
    """Choose the most useful threshold pair with zero holdout misroutes."""
    best: tuple[int, float, float, float, int, VisualEvaluation] | None = None
    similarity_thresholds = [
        *np.arange(0.0, 1.001, 0.025).round(3).tolist(),
        1.01,
    ]
    margin_thresholds = np.arange(0.0, 0.201, 0.01).round(3).tolist()
    embed = lambda item: holdout_embeddings.get(int(item["_id"]))
    for neighbors_per_folder in (1, 2, 3, 5, 8):
        raw = evaluate_visual_index(
            holdout,
            index,
            embed=embed,
            min_similarity=-1.0,
            min_margin=-1.0,
            neighbors_per_folder=neighbors_per_folder,
        )
        for min_similarity in similarity_thresholds:
            for min_margin in margin_thresholds:
                decisions: list[VisualDecision] = []
                exact = wrong = review = 0
                for decision in raw.decisions:
                    accepted = (
                        decision.predicted_folder is not None
                        and decision.similarity is not None
                        and decision.margin is not None
                        and decision.similarity >= min_similarity
                        and decision.margin >= min_margin
                    )
                    if not accepted:
                        review += 1
                        decisions.append(
                            VisualDecision(
                                decision.bookmark_id,
                                decision.expected_folder,
                                None,
                                decision.similarity,
                                decision.margin,
                            )
                        )
                    else:
                        decisions.append(decision)
                        if decision.predicted_folder == decision.expected_folder:
                            exact += 1
                        else:
                            wrong += 1
                if wrong:
                    continue
                evaluation = VisualEvaluation(exact, wrong, review, decisions)
                candidate = (
                    exact,
                    -float(min_similarity) - float(min_margin),
                    float(min_similarity),
                    float(min_margin),
                    neighbors_per_folder,
                    evaluation,
                )
                if best is None or candidate[:2] > best[:2]:
                    best = candidate
    if best is None:
        raise RuntimeError("Threshold calibration failed to produce a safe review policy")
    return best[2], best[3], best[4], best[5]


def _write_report(
    path: str,
    holdout: list[dict[str, Any]],
    evaluation: VisualEvaluation,
    *,
    exemplar_count: int,
    min_similarity: float,
    min_margin: float,
    model_name: str,
    neighbors_per_folder: int,
) -> None:
    by_id = {int(item["_id"]): item for item in holdout}
    rows = []
    for decision in evaluation.decisions:
        item = by_id[decision.bookmark_id]
        predicted = decision.predicted_folder or "Review"
        status = (
            "exact"
            if predicted == decision.expected_folder
            else "review" if decision.predicted_folder is None else "wrong"
        )
        cover = resolve_cover_url(item) or str(item.get("cover", ""))
        rows.append(
            "<article class='card {status}'>"
            "<img src='{cover}' loading='lazy' referrerpolicy='no-referrer'>"
            "<div><strong>{title}</strong><p>{expected} ← {predicted}</p>"
            "<small>similarity={similarity} margin={margin}</small></div></article>".format(
                status=status,
                cover=html.escape(cover, quote=True),
                title=html.escape(str(item.get("title", "") or "Untitled")),
                expected=html.escape(decision.expected_folder),
                predicted=html.escape(predicted),
                similarity=(
                    f"{decision.similarity:.3f}"
                    if decision.similarity is not None
                    else "—"
                ),
                margin=f"{decision.margin:.3f}" if decision.margin is not None else "—",
            )
        )
    document = f"""<!doctype html><meta charset='utf-8'>
<title>Visual exemplar holdout</title>
<style>
body{{font:14px system-ui;background:#111;color:#eee;margin:24px}} .summary{{display:flex;gap:24px}}
.gallery{{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:14px;margin-top:24px}}
.card{{border:2px solid #555;border-radius:10px;overflow:hidden;background:#1c1c1c}} .exact{{border-color:#31b46c}}
.wrong{{border-color:#e45858}} .review{{border-color:#d4a72c}} img{{width:100%;height:220px;object-fit:cover}}
.card div{{padding:10px}} p{{overflow-wrap:anywhere}} small{{color:#aaa}}
</style><h1>Frozen visual exemplar holdout</h1>
<p>Read-only; latest 10 per folder remain excluded from {exemplar_count} older exemplars.</p>
<div class='summary'><b>Exact {evaluation.exact}</b><b>Wrong {evaluation.wrong}</b><b>Review {evaluation.review}</b>
<span>similarity ≥ {min_similarity:.3f}; margin ≥ {min_margin:.3f}; top {neighbors_per_folder}</span></div>
<p>Frozen model: {html.escape(model_name)}</p>
<section class='gallery'>{''.join(rows)}</section>"""
    Path(path).write_text(document, encoding="utf-8")


def build_local_visual_index(
    client: RaindropClient,
    *,
    db_path: str,
    folder_paths: list[str],
    holdout_per_folder: int,
    max_exemplars_per_folder: int,
    step_per_folder: int,
    plateau_patience: int,
    report_path: str,
    model_name: str = DEFAULT_VISUAL_MODEL,
) -> dict[str, Any]:
    folder_map = _load_folder_map(db_path)
    bookmarks = _crawl_target_bookmarks(client, folder_map, folder_paths)
    training, holdout = partition_visual_examples(
        bookmarks,
        folder_paths=folder_paths,
        holdout_per_folder=holdout_per_folder,
        max_exemplars_per_folder=max_exemplars_per_folder,
    )
    cache = LocalVisualEmbeddingCache(db_path, model_name=model_name)
    embedder = create_visual_embedder(model_name)
    embeddings: dict[int, np.ndarray] = {}

    def embed_bookmark(bookmark: dict[str, Any]) -> np.ndarray | None:
        bookmark_id = int(bookmark["_id"])
        if bookmark_id in embeddings:
            return embeddings[bookmark_id]
        cached = cache.get(bookmark)
        if cached is not None:
            embeddings[bookmark_id] = cached
            return cached
        try:
            embedding = run_visual_embedding_on_bookmark(bookmark, embedder)
        except Exception as exc:
            print(f"Embedding failed for {bookmark_id}: {exc}", flush=True)
            return None
        if embedding is not None:
            embeddings[bookmark_id] = embedding
            cache.put(bookmark, embedding)
            cache.save()
        return embedding

    print(f"Embedding {len(holdout)} untouched holdout images", flush=True)
    for position, bookmark in enumerate(holdout, start=1):
        embed_bookmark(bookmark)
        print(f"Holdout embedding {position}/{len(holdout)}", flush=True)
    holdout_embeddings = dict(embeddings)

    training_by_folder = {
        folder: [item for item in training if item["folder_path"] == folder]
        for folder in folder_paths
    }
    best: tuple[int, VisualExemplarIndex, VisualEvaluation] | None = None
    stale_rounds = 0
    for per_folder in range(
        step_per_folder,
        max_exemplars_per_folder + 1,
        step_per_folder,
    ):
        current = [
            item
            for folder in folder_paths
            for item in training_by_folder[folder][:per_folder]
        ]
        print(f"Building round with up to {per_folder} exemplars per folder", flush=True)
        for bookmark in current:
            embed_bookmark(bookmark)
        index = _make_index(current, embeddings, model_name=model_name)
        if not index.bookmark_ids:
            continue
        min_similarity, min_margin, neighbors_per_folder, evaluation = _calibrate_thresholds(
            holdout,
            holdout_embeddings,
            index,
        )
        index = VisualExemplarIndex(
            embeddings=index.embeddings,
            folder_paths=index.folder_paths,
            bookmark_ids=index.bookmark_ids,
            min_similarity=min_similarity,
            min_margin=min_margin,
            model_name=model_name,
            neighbors_per_folder=neighbors_per_folder,
        )
        print(
            f"Round result: exact={evaluation.exact}, wrong={evaluation.wrong}, "
            f"review={evaluation.review}, exemplars={len(index.bookmark_ids)}",
            flush=True,
        )
        if best is None or evaluation.exact > best[0]:
            best = (evaluation.exact, index, evaluation)
            stale_rounds = 0
        else:
            stale_rounds += 1
            if stale_rounds >= plateau_patience:
                print("Stopping after holdout accuracy plateaued", flush=True)
                break

    if best is None:
        raise RuntimeError("No visual exemplars could be embedded")
    _exact, index, evaluation = best
    save_visual_exemplar_index(index, db_path)
    _write_report(
        report_path,
        holdout,
        evaluation,
        exemplar_count=len(index.bookmark_ids),
        min_similarity=index.min_similarity,
        min_margin=index.min_margin,
        model_name=index.model_name,
        neighbors_per_folder=index.neighbors_per_folder,
    )
    result = {
        "status": "ok",
        "exemplars": len(index.bookmark_ids),
        "holdout": len(holdout),
        "exact": evaluation.exact,
        "wrong": evaluation.wrong,
        "review": evaluation.review,
        "min_similarity": index.min_similarity,
        "min_margin": index.min_margin,
        "model_name": index.model_name,
        "neighbors_per_folder": index.neighbors_per_folder,
        "report": report_path,
    }
    Path(os.path.join(db_path, "visual_exemplar_metrics.json")).write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default="chroma_db")
    parser.add_argument("--folder", action="append", dest="folders")
    parser.add_argument("--holdout-per-folder", type=int, default=10)
    parser.add_argument("--max-exemplars-per-folder", type=int, default=24)
    parser.add_argument("--step-per-folder", type=int, default=4)
    parser.add_argument("--plateau-patience", type=int, default=2)
    parser.add_argument("--report", default="explicit-art-50-report.html")
    parser.add_argument("--model", default=DEFAULT_VISUAL_MODEL)
    args = parser.parse_args()
    load_dotenv()
    token = os.environ.get("RAINDROP_TOKEN")
    if not token:
        parser.error("RAINDROP_TOKEN is required in the environment or .env")
    result = build_local_visual_index(
        RaindropClient(token=token),
        db_path=args.db_path,
        folder_paths=args.folders or DEFAULT_FOLDERS,
        holdout_per_folder=args.holdout_per_folder,
        max_exemplars_per_folder=args.max_exemplars_per_folder,
        step_per_folder=args.step_per_folder,
        plateau_patience=args.plateau_patience,
        report_path=args.report,
        model_name=args.model,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
