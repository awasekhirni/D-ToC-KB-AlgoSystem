"""Alias detector -- decides whether content belongs under a second branch.

During audit, the engine uses KNN to find candidate cross-branch targets,
then asks this detector whether the content *naturally* belongs under both
branches (not merely topically related). A "yes" triggers alias creation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.config.settings import Settings
from src.core.llm.client import OpenAIClient
from src.observability.logging import get_logger

logger = get_logger(__name__)

_SYSTEM = (
    "You decide whether a piece of content that already lives at one location "
    "in a knowledge tree ALSO strongly belongs under a second, different "
    "branch -- such that users browsing that branch should find a pointer to "
    "it. Say yes only when the content would naturally be sought under BOTH "
    "branches (not merely be topically related). Return JSON: "
    "{\"belongs_elsewhere\": bool, \"reason\": str}."
)


@dataclass(frozen=True)
class AliasVerdict:
    """The outcome of an alias-detection check.

    Attributes:
        belongs_elsewhere: True if an alias should be created.
        reason: Human-readable explanation.
    """

    belongs_elsewhere: bool
    reason: str


class AliasDetector:
    """Asks the LLM whether content belongs under a second branch."""

    def __init__(self, client: OpenAIClient, settings: Settings) -> None:
        self._client = client
        self._model = settings.llm_model

    async def should_alias(
        self,
        *,
        content_excerpt: str,
        current_branch_title: str,
        candidate_branch_title: str,
        candidate_branch_summary: str,
    ) -> AliasVerdict:
        """Decide whether ``content_excerpt`` belongs under ``candidate_branch``.

        Args:
            content_excerpt: A sample of the content (trimmed to 2000 chars).
            current_branch_title: Where the content currently lives.
            candidate_branch_title: The candidate second branch.
            candidate_branch_summary: Summary of the candidate branch.

        Returns:
            ``AliasVerdict`` with ``belongs_elsewhere`` and ``reason``.
        """
        user = (
            f"Content (excerpt):\n{content_excerpt[:2_000]}\n\n"
            f"Current branch: {current_branch_title}\n"
            f"Candidate branch: {candidate_branch_title}\n"
            f"Candidate summary: {candidate_branch_summary}"
        )
        logger.debug(
            "Asking alias detector: %r -> %r",
            current_branch_title, candidate_branch_title,
        )
        data = await self._client.chat_json(
            model=self._model,
            system=_SYSTEM,
            user=user,
            temperature=0.0,
            max_tokens=200,
        )
        return AliasVerdict(
            belongs_elsewhere=bool(data.get("belongs_elsewhere", False)),
            reason=str(data.get("reason", "")).strip(),
        )
