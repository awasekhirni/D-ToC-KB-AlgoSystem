"""Tests for the ``RestructureEngine`` (post-ingest restructure + pivot)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.config.settings import Settings
from src.core.engine.restructure import RestructureEngine
from src.core.llm.sub_toc_generator import ProposedTopic
from src.db.models import ContentChunk
from tests.factories import FakeEmbedder, make_node


def _settings(**overrides: Any) -> Settings:
    defaults: dict[str, Any] = dict(
        database_url="postgresql+asyncpg://x:x@h/x",
        max_tokens_per_node=100,
        max_variance_threshold=0.75,
        kmeans_max_clusters=5,
        embedding_dimensions=1536,
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _chunk(
    node_id: Any, embedding: list[float], text: str = "content", tokens: int = 10
) -> ContentChunk:
    return ContentChunk(
        id=uuid4(),
        node_id=node_id,
        content=text,
        embedding=embedding,
        token_count=tokens,
        checksum=uuid4().hex,
    )


@pytest.fixture
def engine() -> Any:
    """Build a ``RestructureEngine`` with mocked collaborators."""
    settings = _settings()
    session = AsyncMock()
    node_repo = AsyncMock()
    chunk_repo = AsyncMock()
    audit_repo = AsyncMock()
    summarizer = AsyncMock()
    summarizer.summarize = AsyncMock(
        side_effect=lambda texts: f"S:{texts[0][:20]}"
    )
    sub_toc = AsyncMock()
    sub_toc.generate = AsyncMock(
        return_value=[
            ProposedTopic("A", "Summary A"),
            ProposedTopic("B", "Summary B"),
        ]
    )
    eng = RestructureEngine(
        session=session,
        settings=settings,
        node_repo=node_repo,
        chunk_repo=chunk_repo,
        audit_repo=audit_repo,
        summarizer=summarizer,
        sub_toc_generator=sub_toc,
        embedder=FakeEmbedder(),
    )
    return eng, chunk_repo, node_repo, summarizer, sub_toc


@pytest.mark.asyncio
async def test_maybe_restructure_noop_below_threshold(engine: Any) -> None:
    """Below thresholds, restructure is a no-op."""
    e, chunk_repo, _ = engine
    node = make_node(depth=1)
    chunk_repo.get_by_node.return_value = [
        _chunk(node.id, [1.0] * 8, tokens=1) for _ in range(5)
    ]
    outcome = await e.maybe_restructure(node)
    assert outcome.performed is False


@pytest.mark.asyncio
async def test_maybe_restructure_fires_on_high_variance(engine: Any) -> None:
    """High-variance embeddings trigger restructure."""
    e, chunk_repo, node_repo, summarizer, sub_toc = engine
    node = make_node(depth=1, title="Mixed")
    # Two widely different clusters, under token budget but over variance.
    chunk_repo.get_by_node.return_value = [
        _chunk(node.id, [1.0] + [0.0] * 7, tokens=1),
        _chunk(node.id, [1.0] + [0.0] * 7, tokens=1),
        _chunk(node.id, [-1.0] + [0.0] * 7, tokens=1),
        _chunk(node.id, [-1.0] + [0.0] * 7, tokens=1),
    ]
    node_repo.add = AsyncMock(side_effect=lambda c: c)
    outcome = await e.maybe_restructure(node)
    assert outcome.performed is True
    assert sub_toc.generate.await_count == 1
    assert summarizer.summarize.await_count >= 2


@pytest.mark.asyncio
async def test_maybe_restructure_skips_alias(engine: Any) -> None:
    """Alias nodes are skipped."""
    e, _, _ = engine
    node = make_node(depth=1, is_alias=True, points_to_id=uuid4())
    outcome = await e.maybe_restructure(node)
    assert outcome.performed is False
    assert outcome.reason == "alias node"


@pytest.mark.asyncio
async def test_maybe_restructure_skips_too_few_chunks(engine: Any) -> None:
    """Fewer than 3 chunks means nothing to cluster."""
    e, chunk_repo, _ = engine
    node = make_node(depth=1)
    chunk_repo.get_by_node.return_value = [
        _chunk(node.id, [1.0] * 8, tokens=1),
        _chunk(node.id, [0.5] * 8, tokens=1),
    ]
    outcome = await e.maybe_restructure(node)
    assert outcome.performed is False
    assert outcome.reason == "too few chunks"


@pytest.mark.asyncio
async def test_pivot_aborts_when_alias_referrer(engine: Any) -> None:
    """Pivot is skipped if an alias points into the children."""
    e, chunk_repo, node_repo, _ = engine
    parent = make_node(depth=3)
    child = make_node(depth=4, parent_id=parent.id)
    node_repo.get_children.return_value = [child]
    # Simulate alias referrer.
    e._has_alias_referrer = AsyncMock(return_value=True)

    assert await e.pivot_paradigm(parent) is False


@pytest.mark.asyncio
async def test_pivot_aborts_when_no_children(engine: Any) -> None:
    """Pivot with no children is a no-op."""
    e, _, node_repo, _ = engine
    parent = make_node(depth=3)
    node_repo.get_children.return_value = []
    assert await e.pivot_paradigm(parent) is False
