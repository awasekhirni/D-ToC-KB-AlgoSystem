"""Sub-table-of-contents generator.

Given a parent topic, a categorization paradigm, and a list of theme
summaries (one per K-Means cluster), asks the LLM to propose 2-8 child
topics that partition the themes under the given paradigm.

This is the *only* place the main LLM sees cluster summaries -- it never
sees raw chunk text during restructure, keeping context usage bounded.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.config.settings import Settings
from src.core.enums import Paradigm
from src.core.llm.client import OpenAIClient
from src.observability.logging import get_logger

logger = get_logger(__name__)

_SYSTEM = (
    "You are a librarian proposing a sub-table-of-contents. You will receive "
    "a parent topic, a categorization paradigm, and N theme summaries that "
    "currently coexist mixed together. Propose 2-8 child topics that cleanly "
    "partition these themes under the given paradigm. Return JSON: "
    "{\"topics\": [{\"title\": \"...\", \"summary\": \"...\"}, ...]}. "
    "Titles <= 60 chars. Do NOT include a topic that merely renames the parent."
)

_PARADIGM_HINT = {
    Paradigm.THEMATIC: "organise by concept / subject matter",
    Paradigm.CHRONOLOGICAL: "organise by time period or sequence",
    Paradigm.GEOGRAPHICAL: "organise by place or region",
    Paradigm.PROCEDURAL: "organise by step / process phase",
}


@dataclass(frozen=True)
class ProposedTopic:
    """A proposed child node from the LLM.

    Attributes:
        title: Short label (<= 500 chars, enforced by caller).
        summary: One-sentence description.
    """

    title: str
    summary: str


class SubToCGenerator:
    """Generates child-topic proposals from cluster summaries."""

    def __init__(self, client: OpenAIClient, settings: Settings) -> None:
        self._client = client
        self._model = settings.llm_model

    async def generate(
        self,
        *,
        parent_title: str,
        paradigm: Paradigm,
        theme_summaries: list[str],
    ) -> list[ProposedTopic]:
        """Generate child topics from ``theme_summaries``.

        Args:
            parent_title: Title of the node being restructured.
            paradigm: Categorization paradigm to apply.
            theme_summaries: One summary per K-Means cluster.

        Returns:
            List of 1-8 ``ProposedTopic`` objects.

        Raises:
            ValueError: If ``theme_summaries`` is empty or the LLM returns
                no valid topics.
        """
        if not theme_summaries:
            raise ValueError("Need at least one theme summary")
        user = _build_user(parent_title, paradigm, theme_summaries)
        logger.info(
            "Generating sub-ToC for %r under %s paradigm (%d themes)",
            parent_title, paradigm.value, len(theme_summaries),
        )
        data = await self._client.chat_json(
            model=self._model, system=_SYSTEM, user=user, max_tokens=1500,
        )
        raw = data.get("topics", [])
        topics: list[ProposedTopic] = []
        for item in raw:
            title = str(item.get("title", "")).strip()
            summary = str(item.get("summary", "")).strip()
            if title and summary:
                topics.append(ProposedTopic(title=title[:500], summary=summary))
        if not topics:
            raise ValueError("LLM returned no valid topics")
        logger.info("LLM proposed %d child topics", len(topics))
        return topics


def _build_user(
    parent: str, paradigm: Paradigm, summaries: list[str]
) -> str:
    """Assemble the user prompt from parent + paradigm + summaries."""
    lines = [
        f"Parent topic: {parent}",
        f"Paradigm: {paradigm.value} -- {_PARADIGM_HINT[paradigm]}",
        "Theme summaries currently mixed under this parent:",
    ]
    for i, s in enumerate(summaries, 1):
        lines.append(f"  {i}. {s}")
    return "\n".join(lines)
