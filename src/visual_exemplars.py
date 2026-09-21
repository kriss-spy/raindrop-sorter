"""Local image exemplars learned from already-sorted bookmarks."""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import io
import os
from typing import Any

import numpy as np

VISUAL_EXEMPLARS_FILE = "visual_exemplars.npz"
DEFAULT_CLIP_MODEL = "openai/clip-vit-base-patch32"
DEFAULT_DINOV2_MODEL = "facebook/dinov2-small"
DEFAULT_CCIP_MODEL = "deepghs/ccip:ccip-caformer-24-randaug-pruned"
DEFAULT_VISUAL_MODEL = DEFAULT_CCIP_MODEL


@dataclass(frozen=True)
class VisualExemplarIndex:
    """Image embeddings and their user-defined destinations."""

    embeddings: np.ndarray
    folder_paths: list[str]
    bookmark_ids: list[int]
    min_similarity: float = 0.80
    min_margin: float = 0.03
    model_name: str = DEFAULT_VISUAL_MODEL
    neighbors_per_folder: int = 3


@dataclass(frozen=True)
class VisualMatch:
    """A visual route that cleared both confidence gates."""

    folder_path: str
    similarity: float
    margin: float


@dataclass(frozen=True)
class VisualDecision:
    """One holdout prediction for reporting and calibration."""

    bookmark_id: int
    expected_folder: str
    predicted_folder: str | None
    similarity: float | None
    margin: float | None


@dataclass(frozen=True)
class VisualEvaluation:
    """Read-only holdout results for an exemplar index."""

    exact: int
    wrong: int
    review: int
    decisions: list[VisualDecision]


class CLIPImageEmbedder:
    """Frozen local CLIP image encoder with lazy model initialization."""

    def __init__(self, model_name: str = DEFAULT_CLIP_MODEL, device: str | None = None):
        self.model_name = model_name
        self.device = device
        self._model: Any | None = None
        self._processor: Any | None = None

    def _load(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import CLIPImageProcessor, CLIPModel

        self.device = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
        # CLIP's published preprocessing constants are the constructor defaults;
        # using them avoids a second network artifact beyond the model itself.
        self._processor = CLIPImageProcessor()
        self._model = CLIPModel.from_pretrained(self.model_name)
        self._model.eval()
        self._model.to(self.device)

    def embed_image(self, image_bytes: bytes) -> np.ndarray:
        """Return one normalized image embedding."""
        import torch
        from PIL import Image

        self._load()
        if self._model is None or self._processor is None:
            raise RuntimeError("CLIP image encoder failed to load")
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        inputs = self._processor(images=image, return_tensors="pt")
        pixel_values = inputs["pixel_values"].to(self.device)
        with torch.inference_mode():
            features = self._model.get_image_features(pixel_values=pixel_values)
        return _normalized(features[0].detach().cpu().numpy())


class DINOv2ImageEmbedder:
    """Frozen local DINOv2 encoder for image-neighbor retrieval."""

    def __init__(self, model_name: str = DEFAULT_DINOV2_MODEL, device: str | None = None):
        self.model_name = model_name
        self.device = device
        self._model: Any | None = None
        self._processor: Any | None = None

    def _load(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import AutoImageProcessor, AutoModel

        self.device = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
        self._processor = AutoImageProcessor.from_pretrained(self.model_name)
        self._model = AutoModel.from_pretrained(self.model_name)
        self._model.eval()
        self._model.to(self.device)

    def embed_image(self, image_bytes: bytes) -> np.ndarray:
        """Return the normalized DINOv2 class-token representation."""
        import torch
        from PIL import Image

        self._load()
        if self._model is None or self._processor is None:
            raise RuntimeError("DINOv2 image encoder failed to load")
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        inputs = self._processor(images=image, return_tensors="pt")
        pixel_values = inputs["pixel_values"].to(self.device)
        with torch.inference_mode():
            output = self._model(pixel_values=pixel_values)
        return _normalized(output.last_hidden_state[0, 0].detach().cpu().numpy())


class CCIPImageEmbedder:
    """Anime-character identity features from the frozen CCIP encoder."""

    def __init__(self, model_name: str = DEFAULT_CCIP_MODEL):
        self.model_name = model_name
        self.ccip_model = model_name.partition(":")[2]

    def embed_image(self, image_bytes: bytes) -> np.ndarray:
        from imgutils.metrics import ccip_extract_feature

        return np.asarray(
            ccip_extract_feature(io.BytesIO(image_bytes), model=self.ccip_model),
            dtype=np.float32,
        )


def create_visual_embedder(model_name: str) -> Any:
    """Create the frozen encoder recorded in a visual exemplar index."""
    if model_name.startswith("deepghs/ccip:"):
        return CCIPImageEmbedder(model_name=model_name)
    if model_name.startswith("openai/clip"):
        return CLIPImageEmbedder(model_name=model_name)
    return DINOv2ImageEmbedder(model_name=model_name)


class LocalVisualEmbeddingCache:
    """Resumable image embeddings keyed by bookmark ID and cover URL."""

    def __init__(self, base_path: str, model_name: str = DEFAULT_VISUAL_MODEL):
        self.base_path = base_path
        model_key = hashlib.sha256(model_name.encode("utf-8")).hexdigest()[:12]
        self.path = os.path.join(base_path, f"visual_embedding_cache-{model_key}.npz")
        self._entries: dict[int, tuple[str, str, np.ndarray]] = {}
        if not os.path.isfile(self.path):
            return
        with np.load(self.path, allow_pickle=False) as data:
            for bookmark_id, cover, folder, embedding in zip(
                data["bookmark_ids"],
                data["cover_urls"],
                data["folder_paths"],
                data["embeddings"],
            ):
                self._entries[int(bookmark_id)] = (
                    str(cover),
                    str(folder),
                    np.asarray(embedding, dtype=np.float32),
                )

    def get(self, bookmark: dict[str, Any]) -> np.ndarray | None:
        entry = self._entries.get(int(bookmark["_id"]))
        if entry is None or entry[0] != str(bookmark.get("cover", "")):
            return None
        return entry[2]

    def put(self, bookmark: dict[str, Any], embedding: np.ndarray) -> None:
        self._entries[int(bookmark["_id"])] = (
            str(bookmark.get("cover", "")),
            str(bookmark.get("folder_path", "")),
            np.asarray(embedding, dtype=np.float32),
        )

    def save(self) -> None:
        if not self._entries:
            return
        os.makedirs(self.base_path, exist_ok=True)
        ordered = sorted(self._entries.items())
        np.savez_compressed(
            self.path,
            bookmark_ids=np.asarray([item[0] for item in ordered], dtype=np.int64),
            cover_urls=np.asarray([item[1][0] for item in ordered], dtype=np.str_),
            folder_paths=np.asarray([item[1][1] for item in ordered], dtype=np.str_),
            embeddings=np.asarray([item[1][2] for item in ordered], dtype=np.float32),
        )


def save_visual_exemplar_index(
    index: VisualExemplarIndex,
    base_path: str,
) -> None:
    """Persist a portable, non-pickle visual exemplar index."""
    os.makedirs(base_path, exist_ok=True)
    path = os.path.join(base_path, VISUAL_EXEMPLARS_FILE)
    np.savez_compressed(
        path,
        embeddings=np.asarray(index.embeddings, dtype=np.float32),
        folder_paths=np.asarray(index.folder_paths, dtype=np.str_),
        bookmark_ids=np.asarray(index.bookmark_ids, dtype=np.int64),
        min_similarity=np.asarray(index.min_similarity, dtype=np.float32),
        min_margin=np.asarray(index.min_margin, dtype=np.float32),
        model_name=np.asarray(index.model_name, dtype=np.str_),
        neighbors_per_folder=np.asarray(index.neighbors_per_folder, dtype=np.int64),
    )


def load_visual_exemplar_index(base_path: str) -> VisualExemplarIndex | None:
    """Load visual exemplars, returning ``None`` before local initialization."""
    path = os.path.join(base_path, VISUAL_EXEMPLARS_FILE)
    if not os.path.isfile(path):
        return None
    with np.load(path, allow_pickle=False) as data:
        return VisualExemplarIndex(
            embeddings=np.asarray(data["embeddings"], dtype=np.float32),
            folder_paths=[str(path) for path in data["folder_paths"].tolist()],
            bookmark_ids=[int(bookmark_id) for bookmark_id in data["bookmark_ids"]],
            min_similarity=float(data["min_similarity"]),
            min_margin=float(data["min_margin"]),
            model_name=str(data["model_name"]),
            neighbors_per_folder=(
                int(data["neighbors_per_folder"])
                if "neighbors_per_folder" in data.files
                else 3
            ),
        )


def _normalized(vector: np.ndarray) -> np.ndarray:
    array = np.asarray(vector, dtype=np.float32)
    norm = np.linalg.norm(array, axis=-1, keepdims=True)
    return np.divide(array, norm, out=np.zeros_like(array), where=norm != 0)


def classify_visual_embedding(
    embedding: np.ndarray,
    index: VisualExemplarIndex,
    *,
    min_similarity: float,
    min_margin: float,
    neighbors_per_folder: int = 3,
) -> VisualMatch | None:
    """Match an image using calibrated mean top-k similarity per destination."""
    match = score_visual_embedding(
        embedding,
        index,
        neighbors_per_folder=neighbors_per_folder,
    )
    if match is None:
        return None
    if match.similarity < min_similarity or match.margin < min_margin:
        return None
    return match


def score_visual_embedding(
    embedding: np.ndarray,
    index: VisualExemplarIndex,
    *,
    neighbors_per_folder: int = 3,
) -> VisualMatch | None:
    """Return the strongest visual destination before confidence gates."""
    if len(index.folder_paths) == 0 or index.embeddings.size == 0:
        return None
    if len(index.embeddings) != len(index.folder_paths):
        raise ValueError("visual exemplar embeddings and folders must align")
    if neighbors_per_folder < 1:
        raise ValueError("neighbors_per_folder must be at least 1")

    if index.model_name.startswith("deepghs/ccip:"):
        from imgutils.metrics import ccip_batch_differences

        ccip_model = index.model_name.partition(":")[2]
        features = [
            np.asarray(embedding, dtype=np.float32),
            *[np.asarray(row, dtype=np.float32) for row in index.embeddings],
        ]
        differences = ccip_batch_differences(features, model=ccip_model)[0, 1:]
        similarities = 1.0 - differences
    else:
        similarities = _normalized(index.embeddings) @ _normalized(embedding)
    scores_by_folder: dict[str, list[float]] = defaultdict(list)
    for folder, similarity in zip(index.folder_paths, similarities):
        scores_by_folder[folder].append(float(similarity))

    scores = []
    for folder, folder_scores in scores_by_folder.items():
        strongest = sorted(folder_scores, reverse=True)[:neighbors_per_folder]
        scores.append((folder, sum(strongest) / len(strongest)))
    scores.sort(key=lambda item: (-item[1], item[0]))

    folder, similarity = scores[0]
    runner_up = scores[1][1] if len(scores) > 1 else -1.0
    margin = similarity - runner_up
    return VisualMatch(folder, similarity, margin)


def evaluate_visual_index(
    holdout: list[dict[str, Any]],
    index: VisualExemplarIndex,
    *,
    embed: Callable[[dict[str, Any]], np.ndarray | None],
    min_similarity: float,
    min_margin: float,
    neighbors_per_folder: int = 3,
) -> VisualEvaluation:
    """Evaluate untouched holdout images without adding them to the index."""
    decisions: list[VisualDecision] = []
    exact = wrong = review = 0
    for bookmark in holdout:
        embedding = embed(bookmark)
        match = None
        if embedding is not None:
            match = classify_visual_embedding(
                embedding,
                index,
                min_similarity=min_similarity,
                min_margin=min_margin,
                neighbors_per_folder=neighbors_per_folder,
            )
        expected = str(bookmark.get("folder_path", ""))
        predicted = match.folder_path if match is not None else None
        if predicted is None:
            review += 1
        elif predicted == expected:
            exact += 1
        else:
            wrong += 1
        decisions.append(
            VisualDecision(
                bookmark_id=int(bookmark["_id"]),
                expected_folder=expected,
                predicted_folder=predicted,
                similarity=match.similarity if match is not None else None,
                margin=match.margin if match is not None else None,
            )
        )
    return VisualEvaluation(exact, wrong, review, decisions)


def partition_visual_examples(
    bookmarks: list[dict[str, Any]],
    *,
    folder_paths: list[str],
    holdout_per_folder: int = 10,
    max_exemplars_per_folder: int = 24,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Reserve each folder's latest images and bound older training examples."""
    if holdout_per_folder < 0:
        raise ValueError("holdout_per_folder must be non-negative")
    if max_exemplars_per_folder < 0:
        raise ValueError("max_exemplars_per_folder must be non-negative")

    selected = set(folder_paths)
    by_folder: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for bookmark in bookmarks:
        folder = str(bookmark.get("folder_path", ""))
        if folder in selected and bookmark.get("cover"):
            by_folder[folder].append(bookmark)

    training: list[dict[str, Any]] = []
    holdout: list[dict[str, Any]] = []
    for folder in folder_paths:
        ordered = sorted(
            by_folder.get(folder, []),
            key=lambda item: (str(item.get("created", "")), int(item.get("_id", 0))),
            reverse=True,
        )
        folder_holdout = ordered[:holdout_per_folder]
        folder_training = ordered[
            holdout_per_folder:holdout_per_folder + max_exemplars_per_folder
        ]
        holdout.extend(folder_holdout)
        training.extend(folder_training)
    return training, holdout
