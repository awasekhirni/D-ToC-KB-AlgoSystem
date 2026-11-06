"""Test factories -- deterministic fakes for unit tests.

These let the entire engine test suite run in milliseconds without any
external dependencies (no DB, no OpenAI, no Redis).
"""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import uuid4

from src.db.models import ToCNode


def make_node(**overrides: Any) -> ToCNode:
    """Create a ``ToCNode`` with sensible defaults + caller overrides.

    Common overrides: ``title``, ``depth``, ``parent_id``, ``is_alias``,
    ``points_to_id``, ``semantic_summary``, ``categorization_paradigm``.
    """
    defaults: dict[str, Any] = dict(
        title="Test Node",
        semantic_summary="A test node",
        depth=0,
        parent_id=None,
        categorization_paradigm="Thematic",
        is_alias=False,
        points_to_id=None,
    )
    defaults.update(overrides)
    return ToCNode(id=defaults.pop("id", uuid4()), **defaults)


class FakeEmbedder:
    """Deterministic 1536-d embeddings derived from a text hash.

    Implements the ``EmbeddingProvider`` protocol. Two calls with the same
    text return the same vector (cached). Different texts return
    different vectors. This is enough for the routing/clustering tests
    to be deterministic.
    """

    def __init__(self, dims: int = 1536) -> None:
        self._dims = dims
        self._cache: dict[str, list[float]] = {}

    @property
    def dimensions(self) -> int:
        return self._dims

    async def embed(self, text: str) -> list[float]:
        if text in self._cache:
            return self._cache[text]
        h = hashlib.sha256(text.encode()).digest()
        # Build a deterministic, normalised vector from the hash bytes.
        vec = [((h[i % len(h)] / 255.0) - 0.5) for i in range(self._dims)]
        norm = (sum(v * v for v in vec) ** 0.5) or 1.0
        vec = [v / norm for v in vec]
        self._cache[text] = vec
        return vec

    async def embed_batch(self, texts):
        return [await self.embed(t) for t in texts]


class FakeNamer:
    """Deterministic branch namer -- uses the first line as the title."""

    async def name(self, content: str) -> tuple[str, str]:
        head = content.strip().split("\n", 1)[0][:100]
        return head or "Untitled", head
