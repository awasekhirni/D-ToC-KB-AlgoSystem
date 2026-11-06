"""Tests for the ``AuditEngine`` (drift + alias discovery + alias repair)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.config.settings import Settings
from src.core.engine.audit import AuditEngine
from src.core.llm.alias_detector import AliasVerdict
from src.core.llm.drift_verifier import DriftVerdict
from src.db.models import ContentChunk
from tests.factories import make_node


def _settings(**overrides: Any) -> Settings:
    defaults: dict[str, Any] = dict(
        database_url="postgresql+asyncpg://x:x@h/x",
        audit_sample_size=5,
        alias_discovery_enabled=True,
        alias_similarity_threshold=0.8,
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _chunk(
    node_id: Any, text: str = "x", embedding: list[float] | None = None
) -> ContentChunk:
    return ContentChunk(
        id=uuid4(),
        node_id=node_id,
        content=text,
        embedding=embedding or [0.1] * 8,
        token_count=1,
        checksum=uuid4().hex,
    )


def _engine(
    settings: Settings,
    *,
    drift_return: DriftVerdict,
    alias_return: bool = False,
    knn_return: list[tuple[Any, float]] | None = None,
) -> tuple[AuditEngine, dict[str, AsyncMock]]:
    """Build an ``AuditEngine`` with mocked collaborators."""
    session = AsyncMock()
    node_repo = AsyncMock()
    node_repo.get_subtree_ids = AsyncMock(return_value=[uuid4()])
    node_repo.is_ancestor_of = AsyncMock(return_value=False)
    node_repo.add = AsyncMock(side_effect=lambda n: n)
    node_repo.get = AsyncMock(return_value=make_node(title="cand", depth=2))
    chunk_repo = AsyncMock()
    chunk_repo.get_by_node = AsyncMock()
    chunk_repo.knn_excluding_subtree = AsyncMock(return_value=knn_return or [])
    audit_repo = AsyncMock()
    drift = AsyncMock()
    drift.verify = AsyncMock(return_value=drift_return)
    detector = AsyncMock()
    detector.should_alias = AsyncMock(
        return_value=AliasVerdict(alias_return, "test")
    )
    creator = AsyncMock()
    creator.create = AsyncMock()
    resolver = AsyncMock()
    eng = AuditEngine(
        session=session,
        settings=settings,
        node_repo=node_repo,
        chunk_repo=chunk_repo,
        audit_repo=audit_repo,
        drift_verifier=drift,
        alias_detector=detector,
        alias_creator=creator,
        alias_resolver=resolver,
    )
    return eng, {
        "node_repo": node_repo,
        "chunk_repo": chunk_repo,
        "audit_repo": audit_repo,
        "drift": drift,
        "detector": detector,
        "creator": creator,
        "resolver": resolver,
    }


@pytest.mark.asyncio
async def test_no_content_skips() -> None:
    """A node with no chunks is skipped."""
    settings = _settings()
    engine, mocks = _engine(settings, drift_return=DriftVerdict(True, None))
    node = make_node(depth=1)
    mocks["chunk_repo"].get_by_node.return_value = []
    outcome = await engine.audit_node(node)
    assert outcome.status == "skipped"
    assert outcome.reason == "no_content"
    assert node.last_audit_timestamp is not None


@pytest.mark.asyncio
async def test_accurate_summary_no_update() -> None:
    """An accurate summary is not updated."""
    settings = _settings()
    engine, mocks = _engine(settings, drift_return=DriftVerdict(True, None))
    node = make_node(depth=1, semantic_summary="initial")
    mocks["chunk_repo"].get_by_node.return_value = [_chunk(node.id)]
    outcome = await engine.audit_node(node)
    assert outcome.status == "ok"
    assert outcome.summary_updated is False
    assert node.semantic_summary == "initial"


@pytest.mark.asyncio
async def test_drift_updated() -> None:
    """A drifted summary is rewritten."""
    settings = _settings()
    engine, mocks = _engine(
        settings, drift_return=DriftVerdict(False, "refined summary")
    )
    node = make_node(depth=1, semantic_summary="old")
    mocks["chunk_repo"].get_by_node.return_value = [_chunk(node.id)]
    outcome = await engine.audit_node(node)
    assert outcome.summary_updated is True
    assert node.semantic_summary == "refined summary"
    mocks["audit_repo"].log.assert_awaited()


@pytest.mark.asyncio
async def test_alias_created_on_strong_match() -> None:
    """A strong KNN match with a positive LLM verdict creates an alias."""
    settings = _settings()
    engine, mocks = _engine(
        settings,
        drift_return=DriftVerdict(True, None),
        alias_return=True,
        knn_return=[(uuid4(), 0.05)],  # very close => sim 0.95
    )
    node = make_node(depth=1)
    mocks["chunk_repo"].get_by_node.return_value = [_chunk(node.id)]
    outcome = await engine.audit_node(node)
    assert outcome.alias_created is True
    mocks["creator"].create.assert_awaited_once()


@pytest.mark.asyncio
async def test_alias_not_created_below_threshold() -> None:
    """A weak KNN match (below threshold) does not create an alias."""
    settings = _settings()
    engine, mocks = _engine(
        settings,
        drift_return=DriftVerdict(True, None),
        alias_return=True,
        knn_return=[(uuid4(), 0.5)],  # sim 0.5 < 0.8
    )
    node = make_node(depth=1)
    mocks["chunk_repo"].get_by_node.return_value = [_chunk(node.id)]
    outcome = await engine.audit_node(node)
    assert outcome.alias_created is False
    mocks["creator"].create.assert_not_awaited()


@pytest.mark.asyncio
async def test_alias_discovery_disabled() -> None:
    """When alias discovery is disabled, no aliases are created."""
    settings = _settings(alias_discovery_enabled=False)
    engine, mocks = _engine(
        settings,
        drift_return=DriftVerdict(True, None),
        alias_return=True,
        knn_return=[(uuid4(), 0.05)],
    )
    node = make_node(depth=1)
    mocks["chunk_repo"].get_by_node.return_value = [_chunk(node.id)]
    outcome = await engine.audit_node(node)
    assert outcome.alias_created is False
    mocks["detector"].should_alias.assert_not_awaited()
