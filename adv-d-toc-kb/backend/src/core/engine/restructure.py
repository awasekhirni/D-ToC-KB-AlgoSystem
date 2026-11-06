"""Phase 3 engine: context-aware restructuring + paradigm pivot.

Two entry points:

1. ``maybe_restructure(node)`` -- post-ingestion, run K-Means over the node's
   chunks, summarise clusters with a lightweight LLM, and ask the main LLM
   for a sub-ToC from summaries only. This is the spec's RAG-clustering phase.

2. ``pivot_paradigm(parent)`` -- invoked by routing when a leaf is at
   ``MAX_DEPTH`` and the pivot strategy is enabled. Regenerates the parent's
   children under a new paradigm. Returns ``True`` on success so routing can
   re-attempt descent; ``False`` triggers the caller to fall back to
   spillover.

Data safety for pivot: old children are only deleted AFTER their chunks have
been re-parented to the new children. Aliases pointing at old children are
checked up-front and the pivot aborts (spillover fallback) if any exist.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import Settings
from src.core.clustering.kmeans import cluster_embeddings, semantic_variance
from src.core.enums import AuditEventType, Paradigm
from src.core.llm.cluster_summarizer import ClusterSummarizer
from src.core.llm.sub_toc_generator import ProposedTopic, SubToCGenerator
from src.core.protocols import EmbeddingProvider
from src.core.utils.similarity import cosine_similarity
from src.db.models import ContentChunk, ToCNode
from src.observability.logging import get_logger
from src.observability.metrics import (
    RESTRUCTURE_PERFORMED,
    RESTRUCTURE_RUNS,
)

if TYPE_CHECKING:
    from src.db.repositories import (
        AuditRepository,
        ContentChunkRepository,
        ToCNodeRepository,
    )

logger = get_logger(__name__)


@dataclass(frozen=True)
class RestructureOutcome:
    """Outcome of a restructure or pivot operation.

    Attributes:
        performed: True if the tree was actually modified.
        reason: Machine-readable reason string.
        new_child_ids: IDs of children created (empty if ``performed`` is False).
    """

    performed: bool
    reason: str
    new_child_ids: tuple[UUID, ...] = ()


class RestructureEngine:
    """K-Means restructuring + paradigm pivot."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        settings: Settings,
        node_repo: "ToCNodeRepository",
        chunk_repo: "ContentChunkRepository",
        audit_repo: "AuditRepository",
        summarizer: ClusterSummarizer,
        sub_toc_generator: SubToCGenerator,
        embedder: EmbeddingProvider,
    ) -> None:
        self._session = session
        self._settings = settings
        self._node_repo = node_repo
        self._chunk_repo = chunk_repo
        self._audit_repo = audit_repo
        self._summarizer = summarizer
        self._sub_toc_gen = sub_toc_generator
        self._embedder = embedder

    # -- public: post-ingest restructure ---------------------------------

    async def maybe_restructure(self, node: ToCNode) -> RestructureOutcome:
        """Check if ``node`` needs restructuring and do it if so.

        Triggers when the node is over the token budget OR over the
        semantic-variance threshold. Otherwise returns a no-op outcome.

        Args:
            node: The node to check. Must not be an alias.

        Returns:
            ``RestructureOutcome`` describing what happened.
        """
        RESTRUCTURE_RUNS.inc()
        if node.is_alias:
            return RestructureOutcome(False, "alias node")

        chunks = await self._chunk_repo.get_by_node(node.id)
        if len(chunks) < 3:
            return RestructureOutcome(False, "too few chunks")

        total_tokens = sum(c.token_count for c in chunks)
        over_tokens = total_tokens > self._settings.max_tokens_per_node
        variance = semantic_variance([c.embedding for c in chunks])
        over_variance = variance > self._settings.max_variance_threshold

        if not (over_tokens or over_variance):
            return RestructureOutcome(
                False,
                f"below threshold (tokens={total_tokens}, "
                f"variance={variance:.3f})",
            )

        logger.info(
            "Restructuring node %s (tokens=%d variance=%.3f over_tokens=%s "
            "over_variance=%s)",
            node.id, total_tokens, variance, over_tokens, over_variance,
        )
        return await self._restructure(
            node,
            chunks,
            paradigm=Paradigm(node.categorization_paradigm),
        )

    # -- public: pivot for max-depth handling ----------------------------

    async def pivot_paradigm(self, parent: ToCNode) -> bool:
        """Regenerate ``parent``'s children under the next paradigm.

        Returns ``True`` if children were successfully replaced, ``False``
        if the pivot was skipped (alias referrer, mixed depths, too few
        chunks, or LLM failure). The caller (routing) falls back to
        spillover on ``False``.
        """
        if parent.is_alias:
            return False

        children = await self._node_repo.get_children(parent.id)
        if not children:
            return False

        # Precondition: all children at same depth (== parent.depth + 1).
        expected_depth = parent.depth + 1
        if any(c.depth != expected_depth for c in children):
            logger.info(
                "Pivot skipped: parent %s has children at mixed depths",
                parent.id,
            )
            return False

        # Precondition: no alias points at any child.
        if await self._has_alias_referrer([c.id for c in children]):
            logger.info(
                "Pivot skipped: an alias points into %s's children", parent.id
            )
            await self._audit_repo.log(
                node_id=parent.id,
                event_type=AuditEventType.PARADIGM_PIVOT,
                payload={"status": "skipped", "reason": "alias_referrer"},
            )
            return False

        # Collect all chunks across the leaf children.
        all_chunks: list[ContentChunk] = []
        for child in children:
            all_chunks.extend(await self._chunk_repo.get_by_node(child.id))

        if len(all_chunks) < 2:
            logger.info("Pivot skipped: too few chunks (%d)", len(all_chunks))
            return False

        new_paradigm = Paradigm(parent.categorization_paradigm).next_paradigm()
        logger.info(
            "Pivoting %s from %s to %s",
            parent.id, parent.categorization_paradigm, new_paradigm.value,
        )

        try:
            outcome = await self._regenerate_children(
                parent=parent,
                old_children=children,
                chunks=all_chunks,
                paradigm=new_paradigm,
            )
        except Exception as exc:
            logger.exception("Pivot failed for %s", parent.id)
            await self._audit_repo.log(
                node_id=parent.id,
                event_type=AuditEventType.PARADIGM_PIVOT,
                payload={"status": "error", "error": str(exc)},
            )
            return False

        await self._audit_repo.log(
            node_id=parent.id,
            event_type=AuditEventType.PARADIGM_PIVOT,
            payload={
                "status": "success",
                "from": parent.categorization_paradigm,
                "to": new_paradigm.value,
                "new_children": [str(c) for c in outcome.new_child_ids],
                "removed_children": [str(c.id) for c in children],
            },
        )
        return True

    # -- internals ------------------------------------------------------

    async def _restructure(
        self,
        node: ToCNode,
        chunks: list[ContentChunk],
        *,
        paradigm: Paradigm,
    ) -> RestructureOutcome:
        """Full restructure: cluster -> summarise -> propose -> move."""
        cluster_result = cluster_embeddings(
            [c.embedding for c in chunks],
            max_k=self._settings.kmeans_max_clusters,
        )
        if cluster_result.k < 2:
            return RestructureOutcome(False, "single cluster")

        summaries: list[str] = []
        for cluster in cluster_result.clusters:
            cluster_texts = [chunks[i].content for i in cluster.indices]
            try:
                summary = await self._summarizer.summarize(cluster_texts)
            except Exception:
                logger.warning(
                    "Cluster summarization failed on node %s; using fallback",
                    node.id,
                    exc_info=True,
                )
                summary = cluster_texts[0][:200]
            summaries.append(summary)

        try:
            topics = await self._sub_toc_gen.generate(
                parent_title=node.title,
                paradigm=paradigm,
                theme_summaries=summaries,
            )
        except Exception:
            logger.warning(
                "Sub-ToC generation failed for node %s", node.id, exc_info=True
            )
            return RestructureOutcome(False, "generator failure")

        new_children = await self._create_children(
            parent=node, topics=topics, paradigm=paradigm
        )

        await self._move_chunks(chunks, new_children)

        RESTRUCTURE_PERFORMED.inc()
        await self._audit_repo.log(
            node_id=node.id,
            event_type=AuditEventType.SUMMARY_UPDATED,
            payload={
                "action": "restructure",
                "new_children": [str(c.id) for c in new_children],
                "chunk_count": len(chunks),
                "cluster_k": cluster_result.k,
            },
        )
        return RestructureOutcome(
            True, "restructured", tuple(c.id for c in new_children)
        )

    async def _regenerate_children(
        self,
        *,
        parent: ToCNode,
        old_children: list[ToCNode],
        chunks: list[ContentChunk],
        paradigm: Paradigm,
    ) -> RestructureOutcome:
        """Pivot-specific restructure that also deletes old children."""
        cluster_result = cluster_embeddings(
            [c.embedding for c in chunks],
            max_k=self._settings.kmeans_max_clusters,
        )
        if cluster_result.k < 2:
            raise RuntimeError("Cannot pivot: clustering produced 1 cluster")

        summaries: list[str] = []
        for cluster in cluster_result.clusters:
            cluster_texts = [chunks[i].content for i in cluster.indices]
            summaries.append(await self._summarizer.summarize(cluster_texts))

        topics = await self._sub_toc_gen.generate(
            parent_title=parent.title,
            paradigm=paradigm,
            theme_summaries=summaries,
        )

        new_children = await self._create_children(
            parent=parent, topics=topics, paradigm=paradigm
        )

        await self._move_chunks(chunks, new_children)

        # Update parent's paradigm marker AFTER chunk moves succeeded.
        parent.categorization_paradigm = paradigm.value
        await self._session.flush()

        # Delete old children (now empty). Cascade-delete of content_chunks
        # is a no-op because chunks were re-parented above.
        for old in old_children:
            await self._session.delete(old)
        await self._session.flush()

        return RestructureOutcome(
            True, "pivoted", tuple(c.id for c in new_children)
        )

    async def _create_children(
        self,
        *,
        parent: ToCNode,
        topics: list[ProposedTopic],
        paradigm: Paradigm,
    ) -> list[ToCNode]:
        """Create new child nodes under ``parent`` from LLM-proposed topics."""
        created: list[ToCNode] = []
        for topic in topics:
            child = ToCNode(
                title=topic.title[:500],
                semantic_summary=topic.summary,
                parent_id=parent.id,
                depth=parent.depth + 1,
                categorization_paradigm=paradigm.value,
            )
            await self._node_repo.add(child)
            created.append(child)
        return created

    async def _move_chunks(
        self, chunks: list[ContentChunk], children: list[ToCNode]
    ) -> None:
        """Assign each chunk to the child whose summary-embedding is nearest.

        ERR-001 resolution: we embed each child's summary ONCE (N calls,
        N in [2, 8]), then do pure-vector matching per chunk. This is
        fully decoupled from the LLM's proposal count.
        """
        if not children:
            raise RuntimeError("Cannot move chunks: no children")

        if len(children) == 1:
            await self._chunk_repo.reparent_many(
                [c.id for c in chunks], children[0].id
            )
            return

        summaries = [c.semantic_summary or c.title for c in children]
        child_vectors = await self._embedder.embed_batch(summaries)
        if len(child_vectors) != len(children):
            raise RuntimeError("Embedding count mismatch for child summaries")

        # Build assignment buckets without per-chunk DB round-trips.
        buckets: dict[UUID, list[UUID]] = {c.id: [] for c in children}
        for chunk in chunks:
            best_idx = max(
                range(len(child_vectors)),
                key=lambda i: cosine_similarity(
                    chunk.embedding, child_vectors[i]
                ),
            )
            buckets[children[best_idx].id].append(chunk.id)

        for child_id, chunk_ids in buckets.items():
            if not chunk_ids:
                continue
            await self._chunk_repo.reparent_many(chunk_ids, child_id)

    async def _has_alias_referrer(self, node_ids: list[UUID]) -> bool:
        """Return True if any alias points to any node in ``node_ids``."""
        if not node_ids:
            return False
        stmt = (
            select(ToCNode.id)
            .where(ToCNode.is_alias.is_(True))
            .where(ToCNode.points_to_id.in_(node_ids))
            .limit(1)
        )
        result = (await self._session.execute(stmt)).first()
        return result is not None
