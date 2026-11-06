"""Protocols decoupling the domain engine from concrete LLM/embedding vendors.

Every consumer in ``core/`` depends only on these Protocols, so the entire
engine test suite runs against deterministic fakes (see
``tests/factories.py``).
"""

from typing import Protocol, Sequence


class EmbeddingProvider(Protocol):
    """Abstracts embedding generation.

    Implementations: ``OpenAIEmbedder`` (production), ``FakeEmbedder`` (tests).
    """

    @property
    def dimensions(self) -> int:
        """The dimensionality of vectors produced by this provider."""
        ...

    async def embed(self, text: str) -> list[float]:
        """Embed a single text. Raises ``ValueError`` on empty input."""
        ...

    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch of texts. Returns embeddings in input order."""
        ...


class BranchNamer(Protocol):
    """Generates a new node's ``(title, semantic_summary)`` from raw content.

    Used by ``RoutingEngine`` when creating a new branch (no existing child
    matches the incoming content above the similarity threshold).
    """

    async def name(self, content: str) -> tuple[str, str]:
        """Return ``(title, summary)``. Both must be non-empty."""
        ...
