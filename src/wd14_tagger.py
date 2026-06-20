"""WD14 Tagger ONNX inference wrapper.

Downloads the WD14 Moat Tagger v2 model from HuggingFace and runs
inference via ONNX Runtime. Supports both CPU and GPU providers.
"""

import io
import os
from typing import Any

import numpy as np
from PIL import Image

DEFAULT_MODEL_REPO = "SmilingWolf/wd-v1-4-moat-tagger-v2"
MODEL_FILENAME = "model.onnx"
LABEL_FILENAME = "selected_tags.csv"
DEFAULT_THRESHOLD = 0.35


def _ensure_model(model_dir: str) -> None:
    """Download ONNX model and label CSV from HuggingFace if absent."""
    from huggingface_hub import hf_hub_download

    os.makedirs(model_dir, exist_ok=True)
    hf_hub_download(DEFAULT_MODEL_REPO, MODEL_FILENAME, local_dir=model_dir)
    hf_hub_download(DEFAULT_MODEL_REPO, LABEL_FILENAME, local_dir=model_dir)


def _load_labels(model_dir: str) -> list[str]:
    """Load tag names from the CSV label file."""
    import csv

    label_path = os.path.join(model_dir, LABEL_FILENAME)
    tags: list[str] = []
    with open(label_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        for row in reader:
            tags.append(row[1])  # tag name is second column
    return tags


def _preprocess(image: Image.Image) -> np.ndarray:
    """Resize to 448x448, keep raw [0, 255] pixel values, add batch dimension.

    WD14 ONNX models expect float inputs in the original 0-255 range; do not
    divide by 255.
    """
    image = image.convert("RGB")
    image = image.resize((448, 448))
    arr = np.array(image, dtype=np.float32)
    return np.expand_dims(arr, axis=0)


def normalize_tag(raw_tag: str) -> str:
    """Normalize a WD14 tag: lowercase, spaces to underscores."""
    return raw_tag.lower().replace(" ", "_")


class WD14Tagger:
    """ONNX-based WD14 tagger with lazy model loading."""

    def __init__(self, model_dir: str | None = None, threshold: float = DEFAULT_THRESHOLD):
        self.model_dir = model_dir or "/tmp/wd14_model"
        self.threshold = threshold
        self._session: Any | None = None
        self._tags: list[str] | None = None

    def _load(self) -> None:
        """Lazy-load the ONNX session and tag list, falling back to CPU."""
        if self._session is not None:
            return

        import onnxruntime as ort

        _ensure_model(self.model_dir)
        model_path = os.path.join(self.model_dir, MODEL_FILENAME)
        providers = ort.get_available_providers()
        try:
            self._session = ort.InferenceSession(model_path, providers=providers)
        except Exception:
            # Some execution provider shared libraries may be missing locally;
            # CPU is always available.
            self._session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        self._tags = _load_labels(self.model_dir)

    def predict(
        self,
        image_input: bytes | Image.Image | str,
    ) -> list[str]:
        """Run WD14 inference and return tags above threshold.

        Args:
            image_input: Raw image bytes, a PIL Image, or a file path.

        Returns:
            List of normalized tag strings.
        """
        self._load()
        if self._session is None or self._tags is None:
            raise RuntimeError("WD14 model failed to load")

        if isinstance(image_input, str):
            image = Image.open(image_input)
        elif isinstance(image_input, bytes):
            image = Image.open(io.BytesIO(image_input))
        else:
            image = image_input

        input_arr = _preprocess(image)
        outputs = self._session.run(None, {self._session.get_inputs()[0].name: input_arr})
        probs = outputs[0][0]  # shape: (num_tags,)

        tags = []
        for tag, prob in zip(self._tags, probs):
            if prob >= self.threshold:
                tags.append(normalize_tag(tag))
        return tags
