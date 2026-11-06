"""OpenAI branch namer implementing ``BranchNamer``.

When the routing engine creates a new branch (no existing child matches
above threshold), it asks the namer to produce a ``(title, summary)``
pair from the raw content. The LLM sees only the trimmed excerpt, never
the full corpus.
"""

from __future__ import annotations

import logging

from src.config.settings import Settings
from src.core.llm.client import OpenAIClient
from src.observability.logging import get_logger

logger = get_logger(__name__)

_SYSTEM = (
    "You name knowledge-base tree nodes. Given a document excerpt, produce a "
    "concise title (<= 60 chars) and a one-sentence semantic summary that "
    "captures the document's core topic. Return JSON with keys 'title' and "
    "'summary'."
)

_MAX_EXCERPT_CHARS = 4000


class OpenAINamer:
    """Implements ``BranchNamer`` -- proposes (title, summary) for new leaves."""

    def __init__(self, client: OpenAIClient, settings: Settings) -> None:
        self._client = client
        self._model = settings.llm_model

    async def name(self, content: str) -> tuple[str, str]:
        """Generate a ``(title, summary)`` pair for ``content``.

        Args:
            content: Raw text to name (trimmed to 4000 chars).

        Returns:
            Tuple of ``(title, summary)``. Both are non-empty; if the LLM
            omits one, we fall back to the first line of the content.

        Raises:
            ValueError: If ``content`` is empty.
        """
        excerpt = content.strip()[:_MAX_EXCERPT_CHARS]
        if not excerpt:
            raise ValueError("Cannot name empty content")
        logger.debug("Naming branch (excerpt %d chars)", len(excerpt))
        data = await self._client.chat_json(
            model=self._model, system=_SYSTEM, user=excerpt,
        )
        title = str(data.get("title", "")).strip()[:500]
        summary = str(data.get("summary", "")).strip()
        if not title:
            title = excerpt.split("\n", 1)[0][:100]
        if not summary:
            summary = title
        return title, summary
