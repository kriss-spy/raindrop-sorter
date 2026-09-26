"""Local execution path for one bookmark, independent of Modal."""

import argparse
import json
import os
import sys
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from typing import Any

from src.cover_cache import SQLiteCoverCache
from src.destinations import is_art_destination
from src.routing import RouteEngine, TextIdentifier, VisualVerifier
from src.run_journal import AttemptHandle, RunJournal, SQLiteRunJournal
from src.modality import bookmark_modality
from src.state_machine import (
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
DEFAULT_VISUAL_BATCH_SIZE = 8
DEFAULT_DOWNLOAD_WORKERS = 8
CLAIM_HEARTBEAT_SECONDS = 5 * 60


@contextmanager
def _automatic_claim_heartbeats(
    journal: RunJournal,
    claims: dict[int, AttemptHandle],
):
    """Keep batch claims live while model work is in progress."""
    stop = threading.Event()
    claims_lock = threading.Lock()
    failures: list[BaseException] = []

    def heartbeat() -> None:
        while not stop.wait(CLAIM_HEARTBEAT_SECONDS):
            with claims_lock:
                active_claims = list(claims.values())
            for claim in active_claims:
                try:
                    if not journal.renew_automatic_claim(claim):
                        # A newer manual/automatic attempt may legitimately take
                        # ownership after this worker's write. The synchronous
                        # fence immediately before mutation is authoritative;
                        # a missed heartbeat alone must not abort other claims.
                        continue
                except BaseException as error:
                    failures.append(error)
                    stop.set()
                    return

    def ensure_healthy() -> None:
        if failures:
            raise RuntimeError("automatic claim heartbeat failed") from failures[0]

    def finish(bookmark_id: int) -> None:
        with claims_lock:
            claims.pop(bookmark_id, None)

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        yield ensure_healthy, finish
    finally:
        stop.set()
        thread.join()
        if failures and sys.exc_info()[0] is None:
            ensure_healthy()


@dataclass(frozen=True)
class LocalRoutingArtifacts:
    folder_id_map: dict[str, int]
    tag_rules: dict[str, Any]
    series_rules: dict[str, Any]
    visual_index: Any | None


@dataclass(frozen=True)
class VisualAnalysis:
    tags: list[str]
    embedding: Any | None = None
    error: BaseException | None = None


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
    artifacts: dict[str, Any] = {}
    for filename in REQUIRED_INDEX_FILES:
        try:
            with open(os.path.join(db_path, filename), encoding="utf-8") as handle:
                artifacts[filename] = json.load(handle)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"Local index {db_path!r} is invalid: {filename} is not valid JSON. "
                "Run `uv run python bootstrap.py --db-path chroma_db` again."
            ) from error

    folder_map = artifacts["folder_id_map.json"]
    if not isinstance(folder_map, dict) or not folder_map or not all(
        isinstance(path, str)
        and path.strip()
        and isinstance(collection_id, int)
        and not isinstance(collection_id, bool)
        for path, collection_id in folder_map.items()
    ):
        raise ValueError(
            f"Local index {db_path!r} is invalid: folder_id_map.json must map "
            "collection paths to integer IDs. Run bootstrap again."
        )

    tag_rules = artifacts["tag_rules.json"]
    rules = tag_rules.get("rules") if isinstance(tag_rules, dict) else None
    mismatches = tag_rules.get("mismatches") if isinstance(tag_rules, dict) else None
    if not isinstance(rules, dict) or not isinstance(mismatches, dict):
        raise ValueError(
            f"Local index {db_path!r} is invalid: tag_rules.json must contain "
            "rules and mismatches objects. Run bootstrap again."
        )
    for target in rules.values():
        destinations = [target] if isinstance(target, str) else target
        if not isinstance(destinations, list) or not destinations or not all(
            isinstance(destination, str) and destination for destination in destinations
        ):
            raise ValueError(
                f"Local index {db_path!r} is invalid: a tag rule has no valid destination. "
                "Run bootstrap again."
            )
        for destination in destinations:
            if is_art_destination(destination) and destination not in folder_map:
                raise ValueError(
                    f"Local index {db_path!r} is inconsistent: tag rule targets unknown "
                    f"collection {destination}. Run bootstrap again."
                )


def find_local_work(
    client: Any,
    *,
    journal: RunJournal,
    limit: int,
    page_size: int = 100,
) -> list[dict[str, Any]]:
    """Select Unsorted work using the journal instead of remote lifecycle tags."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if page_size < 1 or page_size > 100:
        raise ValueError("page_size must be between 1 and 100")

    excluded_ids = journal.automatic_processing_exclusions()
    selected: list[dict[str, Any]] = []
    selected_ids: set[int] = set()
    page = 0
    while len(selected) < limit:
        items, has_more = client.get_raindrops(
            -1,
            page=page,
            perpage=page_size,
        )
        for item in items:
            bookmark_id = int(item["_id"])
            if bookmark_id not in excluded_ids and bookmark_id not in selected_ids:
                selected.append(item)
                selected_ids.add(bookmark_id)
            if len(selected) == limit:
                break
        if not has_more:
            break
        page += 1
    return selected


def _load_folder_map(db_path: str) -> dict[str, int]:
    with open(
        os.path.join(db_path, "folder_id_map.json"),
        "r",
        encoding="utf-8",
    ) as handle:
        return json.load(handle)


def _load_routing_artifacts(db_path: str) -> LocalRoutingArtifacts:
    validate_local_index(db_path)
    tag_rules, _mismatches = load_tag_rules(db_path)
    return LocalRoutingArtifacts(
        folder_id_map=_load_folder_map(db_path),
        tag_rules=tag_rules,
        series_rules=load_series_rules(db_path),
        visual_index=load_visual_exemplar_index(db_path),
    )


def _has_image_source(bookmark: dict[str, Any]) -> bool:
    return bool(bookmark.get("cover")) or any(
        str(item.get("type", "")).casefold() == "image" and item.get("link")
        for item in bookmark.get("media") or []
    )


class LocalBatchProcessor:
    """Keep local vision models warm while processing bounded applied batches."""

    def __init__(
        self,
        client: Any,
        *,
        db_path: str,
        model_dir: str,
        journal: RunJournal,
        apply: bool = True,
        mutation_lock: Any | None = None,
        visual_batch_size: int = DEFAULT_VISUAL_BATCH_SIZE,
        download_workers: int = DEFAULT_DOWNLOAD_WORKERS,
        cover_cache: SQLiteCoverCache | None = None,
    ):
        if visual_batch_size < 1:
            raise ValueError("visual_batch_size must be at least 1")
        if download_workers < 1:
            raise ValueError("download_workers must be at least 1")
        self.client = client
        self.db_path = db_path
        self.journal = journal
        self.apply = apply
        self.mutation_lock = mutation_lock
        self.visual_batch_size = visual_batch_size
        self.download_workers = download_workers
        self.cover_cache = cover_cache
        self.artifacts = _load_routing_artifacts(db_path)
        self.text_identifier = TextIdentifier(
            self.artifacts.tag_rules,
            self.artifacts.series_rules,
        )
        self.tagger = WD14Tagger(model_dir=model_dir)
        self.visual_index = self.artifacts.visual_index
        self.visual_embedder = (
            create_visual_embedder(self.visual_index.model_name)
            if self.visual_index is not None
            else None
        )

    def run_one(
        self,
        bookmark_id: int,
        *,
        attempt: AttemptHandle | None = None,
        expected_collection_ids: set[int | None] | None = None,
        bookmark_snapshot: dict[str, Any] | None = None,
        visual_analysis: VisualAnalysis | None = None,
    ) -> dict[str, Any]:
        image: bytes | None | object = _IMAGE_NOT_LOADED

        def image_bytes(bookmark: dict[str, Any]) -> bytes | None:
            nonlocal image
            if image is _IMAGE_NOT_LOADED:
                url = resolve_cover_url(bookmark)
                image = download_cover(url) if url else None
            return image if isinstance(image, bytes) else None

        def visual_embedding(bookmark: dict[str, Any]) -> Any | None:
            payload = image_bytes(bookmark)
            if self.visual_embedder is None or payload is None:
                return None
            return self.visual_embedder.embed_image(payload)

        def precomputed_vision(_bookmark: dict[str, Any]) -> list[str]:
            if visual_analysis is None:
                return []
            if visual_analysis.error is not None:
                raise visual_analysis.error
            return visual_analysis.tags

        analyze_vision = (
            precomputed_vision
            if visual_analysis is not None
            else (
                lambda bookmark: [
                    f"ai:wdtag-{tag}" for tag in self.tagger.predict(image_bytes(bookmark))
                ] if image_bytes(bookmark) is not None else []
            )
        )
        analyze_visual = (
            (lambda _bookmark: visual_analysis.embedding)
            if visual_analysis is not None
            else visual_embedding
        )

        return run_local_bookmark(
            self.client,
            bookmark_id=bookmark_id,
            db_path=self.db_path,
            analyze_vision=analyze_vision,
            analyze_visual=analyze_visual,
            apply=self.apply,
            journal=self.journal,
            attempt=attempt,
            mutation_lock=self.mutation_lock,
            expected_collection_ids=expected_collection_ids,
            bookmark=bookmark_snapshot,
            artifacts=self.artifacts,
            cover_cache=self.cover_cache,
        )

    def _batch_visual_analysis(
        self,
        work: list[dict[str, Any]],
    ) -> dict[int, VisualAnalysis]:
        analyses = {
            int(bookmark["_id"]): VisualAnalysis([])
            for bookmark in work
        }
        candidates = []
        for bookmark in work:
            text = self.text_identifier.identify(bookmark)
            if (
                text.kind != "user_confirmed_rule"
                and _has_image_source(bookmark)
                and bookmark_modality(bookmark) == "art"
            ):
                candidates.append(bookmark)
        if not candidates:
            return analyses

        def fetch(bookmark: dict[str, Any]) -> bytes | None:
            url = resolve_cover_url(bookmark)
            return download_cover(url) if url else None

        with ThreadPoolExecutor(
            max_workers=min(self.download_workers, len(candidates))
        ) as executor:
            downloaded = list(executor.map(fetch, candidates))
        available = [
            (bookmark, payload)
            for bookmark, payload in zip(candidates, downloaded)
            if payload is not None
        ]
        for start in range(0, len(available), self.visual_batch_size):
            chunk = available[start:start + self.visual_batch_size]
            payloads = [payload for _bookmark, payload in chunk]
            try:
                raw_tag_results: list[tuple[list[str], BaseException | None]] = [
                    (tags, None) for tags in self.tagger.predict_batch(payloads)
                ]
            except Exception:
                raw_tag_results = []
                for payload in payloads:
                    try:
                        raw_tag_results.append((self.tagger.predict(payload), None))
                    except Exception as error:
                        raw_tag_results.append(([], error))

            embeddings: list[Any | None] = [None] * len(chunk)
            embedding_errors: list[BaseException | None] = [None] * len(chunk)
            eligible_indexes = [
                index
                for index, (_tags, error) in enumerate(raw_tag_results)
                if error is None
            ]
            if self.visual_embedder is not None and eligible_indexes:
                embedding_payloads = [payloads[index] for index in eligible_indexes]
                try:
                    if hasattr(self.visual_embedder, "embed_images"):
                        batch_embeddings = list(
                            self.visual_embedder.embed_images(embedding_payloads)
                        )
                    else:
                        batch_embeddings = [
                            self.visual_embedder.embed_image(payload)
                            for payload in embedding_payloads
                        ]
                    for index, embedding in zip(eligible_indexes, batch_embeddings):
                        embeddings[index] = embedding
                except Exception:
                    for index in eligible_indexes:
                        try:
                            embeddings[index] = self.visual_embedder.embed_image(
                                payloads[index]
                            )
                        except Exception as error:
                            embedding_errors[index] = error

            for index, (bookmark, _payload) in enumerate(chunk):
                tags, tag_error = raw_tag_results[index]
                analyses[int(bookmark["_id"])] = VisualAnalysis(
                    [f"ai:wdtag-{tag}" for tag in tags],
                    embeddings[index],
                    tag_error or embedding_errors[index],
                )
        return analyses

    def __call__(
        self,
        limit: int,
        *,
        should_stop: Callable[[], bool] | None = None,
        on_progress: Callable[[bool], None] | None = None,
    ) -> dict[str, Any]:
        work = find_local_work(self.client, journal=self.journal, limit=limit)
        if self.cover_cache is not None:
            self.cover_cache.record_many(work)
        claims: dict[int, AttemptHandle] = {}
        results = []
        errors = []
        try:
            if self.apply:
                for item in work:
                    claim = self.journal.claim_automatic(
                        item,
                        pinned_index_version="native-local-index-v1",
                        runner_version=RUNNER_VERSION,
                    )
                    if claim is not None:
                        claims[int(item["_id"])] = claim
                work = [item for item in work if int(item["_id"]) in claims]
            with _automatic_claim_heartbeats(self.journal, claims) as heartbeat:
                ensure_claims, finish_claim = heartbeat
                visual_analyses = self._batch_visual_analysis(work)
                ensure_claims()
                for item in work:
                    if should_stop is not None and should_stop():
                        break
                    bookmark_id = int(item["_id"])
                    ensure_claims()
                    try:
                        result = self.run_one(
                            bookmark_id,
                            attempt=claims.get(bookmark_id),
                            bookmark_snapshot=item,
                            visual_analysis=visual_analyses[bookmark_id],
                        )
                        finish_claim(bookmark_id)
                        results.append(result)
                        if on_progress is not None:
                            on_progress(True)
                    except Exception as error:
                        finish_claim(bookmark_id)
                        errors.append({
                            "bookmark_id": bookmark_id,
                            "type": type(error).__name__,
                            "message": str(error),
                        })
                        if on_progress is not None:
                            on_progress(False)
        finally:
            primary_error = sys.exc_info()[1]
            cleanup_errors: list[BaseException] = []
            for claim in list(claims.values()):
                try:
                    self.journal.fail(
                        claim,
                        RuntimeError("automatic batch stopped before processing"),
                    )
                except BaseException as error:
                    cleanup_errors.append(error)
            if cleanup_errors and primary_error is None:
                raise cleanup_errors[0]
        return {
            "status": "ok",
            "mode": "batch",
            "count": len(results) + len(errors),
            "selected_count": len(work),
            "succeeded": len(results),
            "failed": len(errors),
            "progress_reported": on_progress is not None,
            "applied": self.apply,
            "results": results,
            "errors": errors,
        }


def rerun_latest_outcomes(
    processor: LocalBatchProcessor,
    journal: SQLiteRunJournal,
    *,
    outcomes: list[str],
    limit: int,
) -> dict[str, Any]:
    """Re-evaluate bookmarks whose latest journal outcome needs another pass."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    candidates: dict[int, dict[str, Any]] = {}
    for outcome in outcomes:
        for attempt in journal.recent(
            limit=limit,
            outcome=outcome,
            latest_per_bookmark=True,
            mode=("apply", "manual-review", "legacy-tag-migration"),
            exclude_phase="skipped_stale",
        ):
            candidates[int(attempt["bookmark_id"])] = attempt
    selected = sorted(
        candidates.values(),
        key=lambda attempt: (attempt["started_at"], attempt["attempt_id"]),
        reverse=True,
    )[:limit]
    results = []
    errors = []
    for attempt in selected:
        bookmark_id = int(attempt["bookmark_id"])
        expected_collection_ids = {attempt.get("collection_id")}
        destination = attempt.get("destination")
        if destination:
            destination_id = _load_folder_map(processor.db_path).get(destination)
            if destination_id is not None:
                expected_collection_ids.add(destination_id)
        try:
            results.append(processor.run_one(
                bookmark_id,
                expected_collection_ids=expected_collection_ids,
            ))
        except Exception as error:
            errors.append({
                "bookmark_id": bookmark_id,
                "type": type(error).__name__,
                "message": str(error),
            })
    return {
        "status": "ok",
        "mode": "rerun_outcomes",
        "outcomes": outcomes,
        "count": len(results) + len(errors),
        "succeeded": len(results),
        "failed": len(errors),
        "applied": processor.apply,
        "results": results,
        "errors": errors,
    }


_IMAGE_NOT_LOADED = object()


def run_local_bookmark(
    client: Any,
    *,
    bookmark_id: int,
    db_path: str,
    analyze_vision: Callable[[dict[str, Any]], list[str]] = _no_vision,
    analyze_visual: Callable[[dict[str, Any]], Any | None] | None = None,
    apply: bool = False,
    journal: RunJournal | None = None,
    attempt: AttemptHandle | None = None,
    mutation_lock: Any | None = None,
    expected_collection_ids: set[int | None] | None = None,
    bookmark: dict[str, Any] | None = None,
    artifacts: LocalRoutingArtifacts | None = None,
    cover_cache: SQLiteCoverCache | None = None,
) -> dict[str, Any]:
    """Run the native two-step route; writes require ``apply=True``."""
    if apply and journal is None:
        raise ValueError("journal is required for applied lifecycle state")
    artifacts = artifacts or _load_routing_artifacts(db_path)
    bookmark = (
        dict(bookmark)
        if bookmark is not None
        else client.get_raindrop(bookmark_id)
    )
    if cover_cache is not None:
        cover_cache.record(bookmark)
    if attempt is not None and journal is None:
        raise ValueError("journal is required for a claimed attempt")
    if attempt is not None and attempt.bookmark_id != int(bookmark["_id"]):
        raise ValueError("claimed attempt does not match bookmark")
    claimed_attempt = attempt is not None
    if journal is not None and attempt is None:
        attempt = journal.start_attempt(
            bookmark,
            mode="apply" if apply else "dry-run",
            pinned_index_version="native-local-index-v1",
            runner_version=RUNNER_VERSION,
        )

    try:
        candidate = dict(bookmark)
        folder_id_map = artifacts.folder_id_map
        tag_rules = artifacts.tag_rules
        series_rules = artifacts.series_rules
        visual_index = artifacts.visual_index
        text = TextIdentifier(tag_rules, series_rules).identify(candidate)
        if journal is not None and attempt is not None:
            journal.record_event(attempt, "queued_in_journal", {"source": "unsorted"})
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
            def ensure_claim_ownership() -> None:
                if (
                    claimed_attempt
                    and journal is not None
                    and attempt is not None
                    and not journal.renew_automatic_claim(attempt)
                ):
                    raise RuntimeError("automatic claim ownership was lost")

            try:
                if mutation_lock is not None or expected_collection_ids is not None:
                    with mutation_lock if mutation_lock is not None else nullcontext():
                        ensure_claim_ownership()
                        current = client.get_raindrop(bookmark_id)
                        current_collection = (current.get("collection") or {}).get("$id")
                        allowed_collections = (
                            expected_collection_ids
                            if expected_collection_ids is not None
                            else {None, -1}
                        )
                        if current_collection not in allowed_collections:
                            if journal is not None and attempt is not None:
                                journal.record_action(
                                    attempt,
                                    action_kind="skip_stale",
                                    status="succeeded",
                                    destination=target_folder,
                                    request_count=1,
                                    payload={"current_collection_id": current_collection},
                                )
                                journal.complete(attempt, phase="skipped_stale")
                            return {
                                "status": "skipped",
                                "bookmark_id": bookmark_id,
                                "attempt_id": attempt.attempt_id if attempt is not None else None,
                                "action": "skip",
                                "target_collection_id": None,
                                "target_folder": None,
                                "decision": decision.to_dict(),
                                "vision_tag_count": len(vision_tags),
                                "applied": False,
                            }
                        client.update_raindrop(
                            bookmark_id,
                            collection_id=target_id,
                            tags=tags_for_decision(current, decision.outcome.value),
                        )
                else:
                    ensure_claim_ownership()
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

    def positive_integer(value: str) -> int:
        parsed = int(value)
        if parsed < 1:
            raise argparse.ArgumentTypeError("must be at least 1")
        return parsed

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
        "--migrate-sorter-tags", "--migrate-lifecycle-tags",
        dest="migrate_sorter_tags",
        action="store_true",
        help="Persist legacy lifecycle state, then remove all sorter-owned Raindrop tags",
    )
    target.add_argument(
        "--migrate-covers",
        action="store_true",
        help="Cache current Raindrop cover URLs for fast dashboard previews",
    )
    target.add_argument(
        "--rerun-outcomes",
        nargs="+",
        choices=("provisional", "review", "conflict"),
        help="Re-evaluate bookmarks whose latest journal outcome needs another pass",
    )
    parser.add_argument(
        "--migration-batch-size",
        type=positive_integer,
        default=100,
        help="Maximum bookmarks cleaned by one sorter-tag migration run (default: 100)",
    )
    parser.add_argument(
        "--rerun-limit",
        type=positive_integer,
        default=100,
        help="Maximum bookmarks selected by --rerun-outcomes (default: 100)",
    )
    parser.add_argument("--db-path", default="chroma_db")
    parser.add_argument(
        "--journal-path",
        help="SQLite journal path (default: <db-path>/run-journal.sqlite)",
    )
    parser.add_argument("--model-dir", default=".cache/wd14")
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
    journal = SQLiteRunJournal(
        args.journal_path or os.path.join(args.db_path, "run-journal.sqlite")
    )
    cover_cache = SQLiteCoverCache(os.path.join(args.db_path, "cover-cache.sqlite"))
    if args.migrate_sorter_tags:
        from src.lifecycle_migration import migrate_remote_sorter_tags

        folder_map = _load_folder_map(args.db_path)
        result = migrate_remote_sorter_tags(
            client,
            journal,
            apply=args.apply,
            batch_size=args.migration_batch_size,
            destination_paths={
                collection_id: path for path, collection_id in folder_map.items()
            },
            progress=(
                lambda item: print(
                    json.dumps({"migration_progress": item}),
                    flush=True,
                )
            ) if args.apply else None,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if args.migrate_covers:
        from src.cover_cache_migration import migrate_cover_cache

        result = migrate_cover_cache(
            client,
            journal,
            cover_cache,
            progress=lambda item: print(
                json.dumps({"cover_migration_progress": item}),
                flush=True,
            ),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    processor = LocalBatchProcessor(
        client,
        db_path=args.db_path,
        model_dir=args.model_dir,
        journal=journal,
        cover_cache=cover_cache,
        apply=args.apply,
    )
    if args.rerun_outcomes is not None:
        result = rerun_latest_outcomes(
            processor,
            journal,
            outcomes=args.rerun_outcomes,
            limit=args.rerun_limit,
        )
    elif args.bookmark_id is not None:
        result: dict[str, Any] = processor.run_one(args.bookmark_id)
    else:
        result = processor(args.batch_size)
    print(json.dumps(result, ensure_ascii=False, indent=2))
