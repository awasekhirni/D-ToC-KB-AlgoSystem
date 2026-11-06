"""Phase 2: Smart routing with alias resolution and max-depth handling.

Design notes
------------
1. The engine is pure async orchestration -- every external call
   (embeddings, naming, persistence) goes through an injected collaborator.
2. The engine never loops the main ``while`` more than
   ``2 * max_depth + 2`` iterations, guaranteeing termination.
3. Max-depth strategy is resolved per-ingest: pivot fires at most once
   per path, then falls back to spillover.
4. Idempotency: re-ingesting identical content (same checksum) at the same
   leaf is a no-op, controlled by the ``(node_id, checksum)`` unique index.
5. Comprehensive logging at every decision point for observability.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from src.config.settings import Settings
from src.core.enums import AuditEventType, MaxDepthStrategy, Paradigm
from src.core.exceptions import BrokenAliasChain
from src.core.invariants import assert_can_attach_child
from src.core.protocols import BranchNamer, EmbeddingProvider
from src.core.utils.similarity import cosine_similarity
from src.db.models import ContentChunk, ToCNode
from src.observability.logging import get_logger
from src.observability.metrics import (
    BROKEN_ALIAS_CHAIN_ERRORS,
    INGEST_DUPLICATES,
    INGEST_REQUESTS,
    ROUTING_BRANCHES_CREATED,
    ROUTING_PIVOTS,
    ROUTING_SPILLOVERS,
)

if TYPE_CHECKING:
    from src.core.engine.alias import AliasResolver
    from src.db.repositories import (
        AuditRepository,
        ContentChunkRepository,
        ToCNodeRepository,
    )

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IngestRequest:
    """Inbound content to be routed into the tree.

    Attributes:
        content: The raw text to ingest.
        title_hint: Optional pre-computed title (skips LLM naming).
        summary_hint: Optional pre-computed summary (skips LLM naming).
        embedding: Optional pre-computed embedding (skips embed call).
    """

    content: str
    title_hint: str | None = None
    summary_hint: str | None = None
    embedding: list[float] | None = None


@dataclass(frozen=True)
class IngestResult:
    """Outcome of an ingest operation.

    Attributes:
        node_id: The leaf node where content was placed.
        routed_path: Sequence of node IDs visited during routing.
        spillover_created: True if a spillover sibling was created.
        pivot_triggered: True if a paradigm pivot was attempted.
        duplicate: True if content was already present (idempotent skip).
        tokens_in_node: Total tokens in the target node after ingest.
    """

    node_id: UUID
    routed_path: tuple[UUID, ...]
    spillover_created: bool
    pivot_triggered: bool
    duplicate: bool
    tokens_in_node: int


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class RoutingEngine:
    """Routes content into the tree via centroid-based descent.

    The engine walks the tree from the root, scoring each child by cosine
    similarity between the incoming embedding and the child's centroid
    (mean of its chunk embeddings, or its summary embedding as fallback).
    It descends into the best child if similarity exceeds ``threshold``;
    otherwise it creates a new branch.

    At ``MAX_DEPTH``, it applies the configured strategy (spillover or
    pivot-then-spillover).
    """

    def __init__(
        self,
        *,
        settings: Settings,
        embedder: EmbeddingProvider,
        namer: BranchNamer,
        node_repo: "ToCNodeRepository",
        chunk_repo: "ContentChunkRepository",
        audit_repo: "AuditRepository",
        alias_resolver: "AliasResolver",
        restructure: "RestructureEngine | None" = None,
    ) -> None:
        self._settings = settings
        self._embedder = embedder
        self._namer = namer
        self._node_repo = node_repo
        self._chunk_repo = chunk_repo
        self._audit_repo = audit_repo
        self._alias_resolver = alias_resolver
        self._restructure = restructure

    # -- public ----------------------------------------------------------

    async def ingest(self, root: ToCNode, request: IngestRequest) -> IngestResult:
        """Route ``request.content`` into the tree rooted at ``root``.

        Args:
            root: The root node to start routing from. Must not be an alias.
            request: The content + optional hints.

        Returns:
            ``IngestResult`` describing where the content landed.

        Raises:
            ValueError: If content is empty or embedding dimension mismatches.
            BrokenAliasChain: If routing lands on a broken alias chain.
            RuntimeError: If the iteration budget is exhausted (defensive).
        """
        INGEST_REQUESTS.inc()
        if not request.content.strip():
            raise ValueError("Cannot ingest empty content")

        logger.info(
            "Ingesting content length=%d root=%s",
            len(request.content), root.id,
        )

        # Compute or reuse the embedding.
        embedding = request.embedding or await self._embedder.embed(
            request.content
        )
        if len(embedding) != self._settings.embedding_dimensions:
            raise ValueError(
                f"Embedding dim {len(embedding)} != "
                f"{self._settings.embedding_dimensions}"
            )

        # Idempotency key: SHA-256 of the content.
        checksum = hashlib.sha256(
            request.content.encode("utf-8")
        ).hexdigest()
        # Cheap token proxy (tiktoken lands in Phase 3+; this is good enough
        # for the restructure threshold check).
        token_count = max(1, len(request.content.split()))

        path: list[UUID] = [root.id]
        current = root
        spillover_created = False
        pivot_triggered = False
        pivot_budget = 1

        # Hard upper bound guarantees termination.
        max_iterations = 2 * self._settings.max_depth + 2
        for _ in range(max_iterations):
            if current.is_alias:
                current = await self._resolve_or_audit(current)
                path.append(current.id)
                continue

            children = await self._node_repo.get_children(current.id)
            if not children:
                break

            best_child, best_score = await self._best_child(embedding, children)

            if (
                best_child is None
                or best_score < self._settings.similarity_threshold
            ):
                current = await self._create_branch(
                    parent=current, request=request, embedding=embedding
                )
                path.append(current.id)
                break

            if best_child.depth >= self._settings.max_depth:
                if (
                    self._settings.max_depth_strategy == MaxDepthStrategy.PIVOT
                    and pivot_budget > 0
                    and self._restructure is not None
                ):
                    pivot_budget -= 1
                    pivot_triggered = True
                    ROUTING_PIVOTS.inc()
                    if await self._restructure.pivot_paradigm(current):
                        logger.info(
                            "Pivot succeeded on %s, re-evaluating children",
                            current.id,
                        )
                        continue
                    logger.info(
                        "Pivot failed on %s, falling back to spillover",
                        current.id,
                    )
                # Spillover (or pivot budget exhausted / pivot disabled).
                current = await self._create_spillover(
                    parent=current, original=best_child
                )
                path.append(current.id)
                spillover_created = True
                ROUTING_SPILLOVERS.inc()
                break

            current = best_child
            path.append(current.id)
        else:
            # Loop exhausted without break -> defensive bail-out.
            raise RuntimeError(
                "Routing did not terminate -- this indicates a bug in "
                "the iteration budget calculation."
            )

        # Idempotency: skip duplicate content at the same leaf.
        if await self._chunk_repo.exists_with_checksum(current.id, checksum):
            INGEST_DUPLICATES.inc()
            logger.info("Duplicate content at node %s, skipping insert", current.id)
            return IngestResult(
                node_id=current.id,
                routed_path=tuple(path),
                spillover_created=spillover_created,
                pivot_triggered=pivot_triggered,
                duplicate=True,
                tokens_in_node=await self._chunk_repo.total_tokens(current.id),
            )

        chunk = ContentChunk(
            node_id=current.id,
            content=request.content,
            embedding=embedding,
            token_count=token_count,
            checksum=checksum,
        )
        await self._chunk_repo.add(chunk)
        await self._audit_repo.log(
            node_id=current.id,
            event_type=AuditEventType.NODE_ROUTED,
            payload={
                "chunk_id": str(chunk.id),
                "checksum": checksum,
                "path": [str(pid) for pid in path],
                "tokens": token_count,
            },
        )

        logger.info(
            "Routed content to node %s path_len=%d spillover=%s pivot=%s",
            current.id, len(path), spillover_created, pivot_triggered,
        )

        return IngestResult(
            node_id=current.id,
            routed_path=tuple(path),
            spillover_created=spillover_created,
            pivot_triggered=pivot_triggered,
            duplicate=False,
            tokens_in_node=await self._chunk_repo.total_tokens(current.id),
        )

    # -- helpers ---------------------------------------------------------

    async def _resolve_or_audit(self, alias_node: ToCNode) -> ToCNode:
        """Resolve an alias, logging + flagging if the chain is broken."""
        try:
            resolved, _ = await self._alias_resolver.resolve(alias_node)
            return resolved
        except BrokenAliasChain as exc:
            BROKEN_ALIAS_CHAIN_ERRORS.inc()
            await self._audit_repo.log(
                node_id=exc.node_id,
                event_type=AuditEventType.BROKEN_ALIAS_CHAIN,
                payload={"reason": exc.reason, "phase": "routing"},
            )
            await self._node_repo.flag_for_audit(exc.node_id)
            raise

    async def _best_child(
        self, embedding: list[float], children: list[ToCNode]
    ) -> tuple[ToCNode | None, float]:
        """Score children via content centroids (fallback: summary embedding).

        Returns ``(best_child, best_score)``. ``best_child`` is None if no
        child could be scored (e.g. all aliases broken). ``best_score``
        is clamped to >= 0.0.
        """
        # Compute centroids for all non-alias children in one round-trip.
        non_alias_ids = [c.id for c in children if not c.is_alias]
        centroids = await self._chunk_repo.centroids_for(non_alias_ids)

        best: ToCNode | None = None
        best_score = -1.0

        for child in children:
            if child.is_alias:
                try:
                    target, _ = await self._alias_resolver.resolve(child)
                except BrokenAliasChain:
                    await self._audit_repo.log(
                        node_id=child.id,
                        event_type=AuditEventType.BROKEN_ALIAS_CHAIN,
                        payload={"reason": "during_scoring"},
                    )
                    await self._node_repo.flag_for_audit(child.id)
                    continue
                vec = centroids.get(target.id)
                if vec is None and target.semantic_summary:
                    vec = await self._embedder.embed(target.semantic_summary)
            else:
                vec = centroids.get(child.id)
                if vec is None and child.semantic_summary:
                    vec = await self._embedder.embed(child.semantic_summary)

            if vec is None:
                continue

            score = cosine_similarity(embedding, vec)
            if score > best_score:
                best, best_score = child, score

        return best, max(best_score, 0.0)

    async def _create_branch(
        self,
        *,
        parent: ToCNode,
        request: IngestRequest,
        embedding: list[float],
    ) -> ToCNode:
        """Create a new child branch under ``parent``.

        Uses caller-provided hints if available, otherwise asks the LLM namer.
        """
        if request.title_hint and request.summary_hint:
            title, summary = request.title_hint, request.summary_hint
        else:
            title, summary = await self._namer.name(request.content)

        child_depth = parent.depth + 1
        assert_can_attach_child(parent, child_depth, self._settings.max_depth)

        node = ToCNode(
            title=title[:500],
            semantic_summary=summary,
            parent_id=parent.id,
            depth=child_depth,
            categorization_paradigm=parent.categorization_paradigm,
            last_audit_timestamp=None,
        )
        await self._node_repo.add(node)
        ROUTING_BRANCHES_CREATED.inc()
        await self._audit_repo.log(
            node_id=node.id,
            event_type=AuditEventType.NODE_CREATED,
            payload={
                "parent_id": str(parent.id),
                "depth": child_depth,
                "paradigm": node.categorization_paradigm,
            },
        )
        return node

    async def _create_spillover(
        self, *, parent: ToCNode, original: ToCNode
    ) -> ToCNode:
        """Create a spillover sibling ("X (Part 2)") under ``parent``."""
        sibling_depth = original.depth
        assert_can_attach_child(parent, sibling_depth, self._settings.max_depth)
        node = ToCNode(
            title=f"{original.title} (Part 2)"[:500],
            semantic_summary=f"Overflow of {original.title}",
            parent_id=parent.id,
            depth=sibling_depth,
            categorization_paradigm=original.categorization_paradigm,
        )
        await self._node_repo.add(node)
        await self._audit_repo.log(
            node_id=node.id,
            event_type=AuditEventType.SPILLOVER_CREATED,
            payload={"original_id": str(original.id)},
        )
        return node


# Forward reference for type-checking only.
if TYPE_CHECKING:
    from src.core.engine.restructure import RestructureEngine  # noqa: F401
