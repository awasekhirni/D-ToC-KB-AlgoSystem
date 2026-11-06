"""Phase 4: background audit agent.

Performs three functions per node:

1. **Summary drift check**: sample chunks, ask the LLM if the current
   summary is accurate, rewrite if not.
2. **Alias discovery**: KNN-search for cross-branch candidates, ask the
   LLM if the content belongs elsewhere, create an alias if yes.
3. **Broken-alias repair**: resolve the alias chain; if broken, delete
   the alias (the next sweep may re-create it via discovery).

Runs per-node; the Celery sweep drives it. Each node commits independently
(ADR-0005) so one bad node cannot poison the batch.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import Settings
from src.core.engine.alias import AliasResolver
from src.core.engine.alias_creator import AliasCreationEngine
from src.core.enums import AuditEventType
from src.core.exceptions import AliasConsistencyError, BrokenAliasChain
from src.core.llm.alias_detector import AliasDetector
from src.core.llm.drift_verifier import DriftVerifier
from src.db.models import ContentChunk, ToCNode
from src.observability.logging import get_logger
from src.observability.metrics import (
    AUDIT_ALIASES_CREATED,
    AUDIT_BROKEN_ALIASES,
    AUDIT_DRIFT_CORRECTED,
    AUDIT_RUNS,
)

if TYPE_CHECKING:
    from src.db.repositories import (
        AuditRepository,
        ContentChunkRepository,
        ToCNodeRepository,
    )

logger = get_logger(__name__)


@dataclass(frozen=True)
class AuditOutcome:
    """Outcome of auditing a single node.

    Attributes:
        node_id: The audited node's ID.
        status: ``"ok"`` | ``"skipped"`` | ``"error"``.
        reason: Machine-readable reason string.
        summary_updated: True if the summary was rewritten.
        alias_created: True if an alias was created.
    """

    node_id: UUID
    status: str
    reason: str
    summary_updated: bool = False
    alias_created: bool = False


class AuditEngine:
    """Per-node audit: drift check, alias discovery, broken-alias repair."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        settings: Settings,
        node_repo: "ToCNodeRepository",
        chunk_repo: "ContentChunkRepository",
        audit_repo: "AuditRepository",
        drift_verifier: DriftVerifier,
        alias_detector: AliasDetector,
        alias_creator: AliasCreationEngine,
        alias_resolver: AliasResolver,
    ) -> None:
        self._session = session
        self._settings = settings
        self._node_repo = node_repo
        self._chunk_repo = chunk_repo
        self._audit_repo = audit_repo
        self._drift = drift_verifier
        self._alias_detector = alias_detector
        self._alias_creator = alias_creator
        self._alias_resolver = alias_resolver

    async def audit_node(self, node: ToCNode) -> AuditOutcome:
        """Audit a single node.

        For alias nodes: resolve the chain; if broken, delete + log.
        For primary nodes: check summary drift, discover aliases.

        Args:
            node: The node to audit.

        Returns:
            ``AuditOutcome`` describing what happened.
        """
        AUDIT_RUNS.inc()
        logger.info("Auditing node %s (is_alias=%s)", node.id, node.is_alias)

        if node.is_alias:
            return await self._repair_alias(node)

        chunks = await self._chunk_repo.get_by_node(node.id)
        if not chunks:
            node.last_audit_timestamp = _now()
            logger.info("Node %s has no content; skipping", node.id)
            return AuditOutcome(node.id, "skipped", "no_content")

        sample = _sample(chunks, self._settings.audit_sample_size)

        summary_updated = await self._audit_summary(node, sample)
        alias_created = await self._discover_alias(node, sample)

        node.last_audit_timestamp = _now()
        logger.info(
            "Audit complete for %s: summary_updated=%s alias_created=%s",
            node.id, summary_updated, alias_created,
        )
        return AuditOutcome(
            node_id=node.id,
            status="ok",
            reason="audited",
            summary_updated=summary_updated,
            alias_created=alias_created,
        )

    # -- summary drift ---------------------------------------------------

    async def _audit_summary(
        self, node: ToCNode, sample: list[ContentChunk]
    ) -> bool:
        """Check and optionally rewrite ``node.semantic_summary``.

        Returns True if the summary was updated.
        """
        try:
            verdict = await self._drift.verify(
                current_summary=node.semantic_summary or "",
                sample_docs=[c.content for c in sample],
            )
        except Exception:
            logger.exception("Drift verification failed for %s", node.id)
            return False

        if verdict.accurate or not verdict.updated_summary:
            return False

        AUDIT_DRIFT_CORRECTED.inc()
        await self._audit_repo.log(
            node_id=node.id,
            event_type=AuditEventType.DRIFT_CORRECTED,
            payload={
                "old_summary": node.semantic_summary,
                "new_summary": verdict.updated_summary,
            },
        )
        node.semantic_summary = verdict.updated_summary
        logger.info("Corrected summary drift on node %s", node.id)
        return True

    # -- alias discovery -------------------------------------------------

    async def _discover_alias(
        self, node: ToCNode, sample: list[ContentChunk]
    ) -> bool:
        """KNN-search for cross-branch candidates and create aliases.

        Returns True if an alias was created.
        """
        if not self._settings.alias_discovery_enabled:
            return False

        # Skip the whole subtree as candidates -- self-references aren't useful.
        subtree_ids = await self._node_repo.get_subtree_ids(node.id)
        logger.debug(
            "Alias discovery for %s, excluding %d subtree nodes",
            node.id, len(subtree_ids),
        )

        for chunk in sample:
            candidates = await self._chunk_repo.knn_excluding_subtree(
                chunk.embedding, subtree_ids, limit=3
            )
            for candidate_id, distance in candidates:
                similarity = 1.0 - distance
                if similarity < self._settings.alias_similarity_threshold:
                    continue
                candidate = await self._node_repo.get(candidate_id)
                if candidate is None or candidate.is_alias:
                    continue

                try:
                    verdict = await self._alias_detector.should_alias(
                        content_excerpt=chunk.content,
                        current_branch_title=node.title,
                        candidate_branch_title=candidate.title,
                        candidate_branch_summary=(
                            candidate.semantic_summary or ""
                        ),
                    )
                except Exception:
                    logger.exception(
                        "Alias detection failed for %s -> %s",
                        node.id, candidate_id,
                    )
                    continue

                if not verdict.belongs_elsewhere:
                    continue

                try:
                    await self._alias_creator.create(
                        target_parent_id=candidate.id,
                        primary_node_id=node.id,
                    )
                    AUDIT_ALIASES_CREATED.inc()
                    return True
                except AliasConsistencyError as exc:
                    logger.info("Alias rejected (invariant): %s", exc)
        return False

    # -- alias repair ----------------------------------------------------

    async def _repair_alias(self, alias: ToCNode) -> AuditOutcome:
        """Resolve an alias chain; delete if broken."""
        try:
            await self._alias_resolver.resolve(alias)
        except BrokenAliasChain as exc:
            AUDIT_BROKEN_ALIASES.inc()
            await self._audit_repo.log(
                node_id=alias.id,
                event_type=AuditEventType.BROKEN_ALIAS_CHAIN,
                payload={"action": "delete", "reason": exc.reason},
            )
            await self._session.delete(alias)
            await self._session.flush()
            logger.warning(
                "Deleted broken alias %s: %s", alias.id, exc.reason
            )
            return AuditOutcome(
                alias.id, "ok", f"alias_deleted:{exc.reason}"
            )
        alias.last_audit_timestamp = _now()
        logger.info("Alias %s chain healthy", alias.id)
        return AuditOutcome(alias.id, "ok", "alias_chain_healthy")


# ---------------------------------------------------------------------------


def _sample(chunks: list[ContentChunk], n: int) -> list[ContentChunk]:
    """Random sample of up to ``n`` chunks (deterministic per call via system entropy)."""
    if len(chunks) <= n:
        return chunks
    return random.sample(chunks, n)


def _now() -> datetime:
    """UTC now helper."""
    return datetime.now(tz=timezone.utc)
