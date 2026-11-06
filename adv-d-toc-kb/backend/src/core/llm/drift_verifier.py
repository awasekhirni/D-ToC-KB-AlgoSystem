"""Drift verifier -- audits a node's summary against sampled content.

Implements the spec's ``verify_and_update_summary`` LLM call. The verifier
receives the current summary and a random sample of the node's chunks;
it returns whether the summary is accurate and, if not, a rewritten one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.config.settings import Settings
from src.core.llm.client import OpenAIClient
from src.observability.logging import get_logger

logger = get_logger(__name__)

_SYSTEM = (
    "You audit knowledge-base node summaries against a random sample of the "
    "node's actual content. Determine two things: (1) does the current "
    "summary accurately describe the sampled content? (2) if not, produce a "
    "rewritten one-sentence summary that does. Return JSON: "
    "{\"accurate\": bool, \"updated_summary\": str}. If the current summary "
    "is already accurate, set \"updated_summary\" to an empty string."
)

_MAX_CHARS_PER_DOC = 1_500
_MAX_DOCS = 12


@dataclass(frozen=True)
class DriftVerdict:
    """The outcome of a drift check.

    Attributes:
        accurate: True if the current summary describes the content well.
        updated_summary: A rewritten summary if inaccurate, else None.
    """

    accurate: bool
    updated_summary: str | None


class DriftVerifier:
    """Implements the spec's ``verify_and_update_summary`` LLM call."""

    def __init__(self, client: OpenAIClient, settings: Settings) -> None:
        self._client = client
        self._model = settings.llm_model

    async def verify(
        self, *, current_summary: str, sample_docs: list[str]
    ) -> DriftVerdict:
        """Verify ``current_summary`` against ``sample_docs``.

        Args:
            current_summary: The node's current semantic summary.
            sample_docs: A random sample of chunk texts.

        Returns:
            ``DriftVerdict``. If ``accurate`` is True, ``updated_summary``
            is None. Otherwise it holds a rewritten one-sentence summary.

        Note:
            If the LLM returns both ``accurate=True`` and a non-empty
            ``updated_summary``, we trust the rewrite (stronger signal).
        """
        if not sample_docs:
            return DriftVerdict(accurate=True, updated_summary=None)
        docs = sample_docs[:_MAX_DOCS]
        joined = "\n\n---\n\n".join(d[:_MAX_CHARS_PER_DOC] for d in docs)
        user = (
            f"Current summary: {current_summary or '(none)'}\n\n"
            f"Sampled content:\n\n{joined}"
        )
        logger.debug("Verifying summary against %d docs", len(docs))
        data = await self._client.chat_json(
            model=self._model,
            system=_SYSTEM,
            user=user,
            temperature=0.0,
            max_tokens=400,
        )
        accurate = bool(data.get("accurate", True))
        updated = str(data.get("updated_summary", "")).strip() or None
        # Defensive: if LLM says accurate but also returns a rewrite,
        # trust the rewrite (stronger signal than the boolean).
        if updated is not None and updated != current_summary:
            accurate = False
        return DriftVerdict(accurate=accurate, updated_summary=updated)
