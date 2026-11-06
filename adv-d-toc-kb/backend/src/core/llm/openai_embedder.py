"""OpenAI embedding provider implementing ``EmbeddingProvider``."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from src.config.settings import Settings
from src.core.llm.client import OpenAIClient
from src.observability.logging import get_logger

logger = get_logger(__name__)


class OpenAIEmbedder:
    """Implements ``EmbeddingProvider`` against the OpenAI embeddings endpoint."""

    def __init__(self, client: OpenAIClient, settings: Settings) -> None:
        self._client = client
        self._model = settings.embedding_model
        self._dims = settings.embedding_dimensions

    @property
    def dimensions(self) -> int:
        return self._dims

    async def embed(self, text: str) -> list[float]:
        """Embed a single text. Raises ``ValueError`` on empty input."""
        if not text.strip():
            raise ValueError("Cannot embed empty text")
        result = await self._client.embed(
            [text], model=self._model, dimensions=self._dims
        )
        return result[0]

    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch of texts in one API call.

        Args:
            texts: Input strings (all must be non-empty).

        Returns:
            Embeddings in the same order as ``texts``.

        Raises:
            ValueError: If ``texts`` is empty or contains empty strings.
        """
        if not texts:
            return []
        if any(not t.strip() for t in texts):
            raise ValueError("Cannot embed empty text")
        logger.debug("Embedding batch of %d texts", len(texts))
        return await self._client.embed(
            list(texts), model=self._model, dimensions=self._dims
        )
