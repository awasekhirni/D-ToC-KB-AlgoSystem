"""Tests for the ``RoutingEngine`` against in-memory fakes.

These tests verify the routing loop's logic (descent, branch creation,
spillover, pivot delegation, idempotency) without touching a database
or the LLM.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from src.config.settings import Settings
from src.core.engine.alias import AliasResolver
from src.core.engine.restructure import RestructureEngine
from src.core.engine.routing import IngestRequest, RoutingEngine
from src.core.enums import MaxDepthStrategy
from src.db.models import ContentChunk, ToCNode
from tests.factories import FakeEmbedder, FakeNamer, make_node


class _MemNodeRepo:
    """In-memory ``ToCNodeRepository``."""

    def __init__(self) -> None:
        self.nodes: dict[UUID, ToCNode] = {}

    async def get(self, node_id: UUID) -> ToCNode | None:
        return self.nodes.get(node_id)

    async def get_children(self, parent_id: UUID) -> list[ToCNode]:
        return sorted(
            (n for n in self.nodes.values() if n.parent_id == parent_id),
            key=lambda n: n.created_at,
        )

    async def add(self, node: ToCNode) -> ToCNode:
        if node.id is None:
            node.id = uuid4()
        self.nodes[node.id] = node
        return node

    async def flag_for_audit(self, node_id: UUID) -> None:
        node = self.nodes.get(node_id)
        if node is not None:
            node.last_audit_timestamp = None


class _MemChunkRepo:
    """In-memory ``ContentChunkRepository``."""

    def __init__(self) -> None:
        self.chunks: list[ContentChunk] = []

    async def add(self, chunk: ContentChunk) -> ContentChunk:
        self.chunks.append(chunk)
        return chunk

    async def exists_with_checksum(
        self, node_id: UUID, checksum: str
    ) -> bool:
        return any(
            c.node_id == node_id and c.checksum == checksum for c in self.chunks
        )

    async def centroids_for(
        self, node_ids: list[UUID]
    ) -> dict[UUID, list[float]]:
        return {}

    async def total_tokens(self, node_id: UUID) -> int:
        return sum(c.token_count for c in self.chunks if c.node_id == node_id)

    async def reparent_many(
        self, chunk_ids: list[UUID], new_node_id: UUID
    ) -> None:
        for chunk in self.chunks:
            if chunk.id in chunk_ids:
                chunk.node_id = new_node_id


class _MemAuditRepo:
    """In-memory ``AuditRepository``."""

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    async def log(self, **kwargs: Any) -> dict[str, Any]:
        self.entries.append(kwargs)
        return kwargs


def _build_engine(
    settings: Settings,
    *,
    restructure: RestructureEngine | None = None,
) -> tuple[RoutingEngine, _MemNodeRepo, _MemChunkRepo, _MemAuditRepo]:
    node_repo = _MemNodeRepo()
    chunk_repo = _MemChunkRepo()
    audit_repo = _MemAuditRepo()
    resolver = AliasResolver(node_repo, settings.max_alias_hops)
    engine = RoutingEngine(
        settings=settings,
        embedder=FakeEmbedder(),
        namer=FakeNamer(),
        node_repo=node_repo,
        chunk_repo=chunk_repo,
        audit_repo=audit_repo,
        alias_resolver=resolver,
        restructure=restructure,
    )
    return engine, node_repo, chunk_repo, audit_repo


@pytest.mark.asyncio
async def test_ingest_into_empty_tree(settings: Settings) -> None:
    """Ingesting into a tree with no children creates a new branch."""
    engine, node_repo, chunk_repo, _ = _build_engine(settings)
    root = make_node(title="Root", depth=0)
    node_repo.nodes[root.id] = root

    result = await engine.ingest(
        root, IngestRequest(content="Quantum entanglement explained")
    )

    assert not result.duplicate
    assert result.node_id != root.id  # a child branch was created
    assert result.spillover_created is False
    assert len(chunk_repo.chunks) == 1


@pytest.mark.asyncio
async def test_duplicate_content_is_idempotent(settings: Settings) -> None:
    """Re-ingesting identical content is a no-op."""
    engine, node_repo, _, _ = _build_engine(settings)
    root = make_node(title="Root", depth=0)
    node_repo.nodes[root.id] = root

    req = IngestRequest(content="Same text")
    first = await engine.ingest(root, req)
    second = await engine.ingest(root, req)

    assert first.duplicate is False
    assert second.duplicate is True
    assert second.node_id == first.node_id


@pytest.mark.asyncio
async def test_spillover_when_max_depth_reached(settings: Settings) -> None:
    """Reaching MAX_DEPTH on the best child triggers spillover."""
    engine, node_repo, _, _ = _build_engine(settings)
    root = make_node(title="Root", depth=0)
    node_repo.nodes[root.id] = root

    # Manually build a chain down to max_depth.
    parent = root
    for d in range(1, settings.max_depth + 1):
        child = make_node(
            title=f"L{d}",
            depth=d,
            parent_id=parent.id,
            semantic_summary="topic",
        )
        node_repo.nodes[child.id] = child
        parent = child

    # Ingest content that will route down to the leaf.
    # We provide an embedding that won't match "topic" well enough to
    # create a branch, forcing descent all the way to max_depth.
    embedding = [0.0] * settings.embedding_dimensions
    result = await engine.ingest(
        root,
        IngestRequest(content="topic", embedding=embedding),
    )

    assert result.spillover_created is True
    assert result.pivot_triggered is False


@pytest.mark.asyncio
async def test_pivot_calls_restructure_once(settings: Settings) -> None:
    """When pivot strategy is on, ``RestructureEngine`` is called once."""
    settings = settings.model_copy(
        update={"max_depth_strategy": MaxDepthStrategy.PIVOT}
    )
    restructure = AsyncMock(spec=RestructureEngine)
    restructure.pivot_paradigm = AsyncMock(return_value=False)

    engine, node_repo, _, audit_repo = _build_engine(
        settings, restructure=restructure
    )
    root = make_node(title="Root", depth=0)
    node_repo.nodes[root.id] = root
    parent = root
    for d in range(1, settings.max_depth + 1):
        child = make_node(
            title=f"L{d}",
            depth=d,
            parent_id=parent.id,
            semantic_summary="topic",
        )
        node_repo.nodes[child.id] = child
        parent = child

    result = await engine.ingest(
        root,
        IngestRequest(
            content="topic",
            embedding=[0.0] * settings.embedding_dimensions,
        ),
    )
    # Pivot attempted once, then spillover.
    assert restructure.pivot_paradigm.await_count == 1
    assert result.spillover_created is True
    assert result.pivot_triggered is True


@pytest.mark.asyncio
async def test_empty_content_raises(settings: Settings) -> None:
    """Empty content is rejected."""
    engine, node_repo, _, _ = _build_engine(settings)
    root = make_node(title="Root", depth=0)
    node_repo.nodes[root.id] = root

    with pytest.raises(ValueError, match="empty"):
        await engine.ingest(root, IngestRequest(content=""))
