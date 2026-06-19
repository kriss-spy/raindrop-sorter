"""Text embedding logic using sentence-transformers."""

from typing import Any

import numpy as np

MODEL_NAME = "sentence-transformers/all-mpnet-base-v2"


def build_text_input(bookmark: dict[str, Any]) -> str:
    """Build the embedding input string from a bookmark.

    Template (truncated bottom-up — description is truncated first):
        Title: {title}
        Domain: {domain}
        Tags: {wd14_tags} {user_tags}
        Description: {description}
    """
    title = bookmark.get("title", "")
    domain = bookmark.get("domain", "")
    tags = bookmark.get("tags", [])
    # Filter out AI/transient tags for embedding input
    user_tags = [t for t in tags if not t.startswith(("ai:", "sorter-"))]
    description = bookmark.get("excerpt", "") or bookmark.get("note", "") or ""

    parts = [
        f"Title: {title}",
        f"Domain: {domain}",
        f"Tags: {' '.join(user_tags)}",
    ]
    if description:
        parts.append(f"Description: {description}")

    return "\n".join(parts)


class Embedder:
    """Wrapper around sentence-transformers for consistent embedding generation."""

    def __init__(self, model_name: str = MODEL_NAME):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name)

    def embed(self, texts: list[str]) -> np.ndarray:
        """Return a (N, D) numpy array of embeddings."""
        return self.model.encode(texts, convert_to_numpy=True, show_progress_bar=False)

    def embed_one(self, text: str) -> np.ndarray:
        """Return a 1-D numpy array embedding."""
        return self.embed([text])[0]
