"""Cluster summariser -- produces a one-sentence theme for a cluster of chunks.

Used by ``RestructureEngine`` during restructure and pivot. The LLM sees
only cluster texts (head + tail sampling if over budget), never the full
node content.
"""

from __future__ import annotations

import logging

from src.config.settings import Settings
from src.core.llm.client import OpenAIClient
from src.observability.logging import get_logger

logger = get_logger(__name__)

_SYSTEM = (
    "You summarise thematic clusters of document excerpts into a single "
    "sentence. Return JSON: {\"summary\": \"...\"}. Focus on the through-line "
    "that unites the excerpts, not on any single one."
)

_MAX_CHARS = 8_000  # ~2k tokens, conservative


class ClusterSummarizer:
    """Summarises a cluster of chunk texts into a one-sentence theme."""

    def __init__(self, client: OpenAIClient, settings: Settings) -> None:
        self._client = client
        self._model = settings.llm_model

    async def summarize(self, texts: list[str]) -> str:
        """Summarise ``texts`` into a single sentence.

        Args:
            texts: Cluster member texts (must be non-empty).

        Returns:
            One-sentence summary. Falls back to the first text (truncated)
            on any LLM error.
        """
        if not texts:
            raise ValueError("Cannot summarize empty cluster")
        joined = _sample(texts, _MAX_CHARS)
        logger.debug("Summarising cluster of %d texts", len(texts))
        data = await self._client.chat_json(
            model=self._model, system=_SYSTEM, user=joined, max_tokens=200,
        )
        return str(data.get("summary", "")).strip() or texts[0][:200]


def _sample(texts: list[str], budget: int) -> str:
    """Join ``texts`` with separators, head-and-tail sampling if over budget.

    Keeps both breadth (head) and specificity (tail) when the total length
    exceeds ``budget``.
    """
    if sum(len(t) for t in texts) <= budget:
        return "\n\n---\n\n".join(texts)
    head_budget = budget // 2
    tail_budget = budget - head_budget
    head, used = [], 0
    for t in texts:
        if used + len(t) > head_budget:
            break
        head.append(t)
        used += len(t)
    tail, used = [], 0
    for t in reversed(texts):
        if used + len(t) > tail_budget:
            break
        tail.insert(0, t)
        used += len(t)
    return "\n\n---\n\n".join(head + tail)
