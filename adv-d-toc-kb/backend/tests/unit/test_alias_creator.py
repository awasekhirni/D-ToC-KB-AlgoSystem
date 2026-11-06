"""Tests for the ``AliasCreationEngine``."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from src.config.settings import Settings
from src.core.engine.alias_creator import AliasCreationEngine
from src.core.exceptions import AliasConsistencyError
from tests.factories import make_node


def _settings(**overrides: Any) -> Settings:
    defaults: dict[str, Any] = dict(
        database_url="postgresql+asyncpg://x:x@h/x", max_depth=5
    )
    defaults.update(overrides)
    return Settings(**defaults)


class _FakeNodeRepo:
    """In-memory repo with ancestor tracking."""

    def __init__(self) -> None:
        self.nodes: dict[UUID, Any] = {}
        self._ancestors: dict[UUID, set[UUID]] = {}

    def register(self, node: Any, ancestors: tuple[UUID, ...] = ()) -> None:
        self.nodes[node.id] = node
        self._ancestors[node.id] = set(ancestors)

    async def get(self, nid: UUID) -> Any | None:
        return self.nodes.get(nid)

    async def add(self, node: Any) -> Any:
        self.nodes[node.id] = node
        return node

    async def is_ancestor_of(
        self, potential_ancestor_id: UUID, node_id: UUID
    ) -> bool:
        return potential_ancestor_id in self._ancestors.get(node_id, set())


class _FakeAuditRepo:
    """Captures audit log calls."""

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    async def log(self, **kwargs: Any) -> dict[str, Any]:
        self.entries.append(kwargs)
        return kwargs


def _engine(node_repo: _FakeNodeRepo) -> AliasCreationEngine:
    return AliasCreationEngine(
        session=None,  # not used by creation flow
        settings=_settings(),
        node_repo=node_repo,
        audit_repo=_FakeAuditRepo(),
    )


@pytest.mark.asyncio
async def test_create_alias_happy_path() -> None:
    """A valid alias creation succeeds."""
    repo = _FakeNodeRepo()
    root = make_node(title="Root", depth=0)
    primary = make_node(title="Quantum", depth=1, parent_id=root.id)
    target = make_node(title="Physics", depth=1, parent_id=root.id)
    repo.register(root)
    repo.register(primary, ancestors=(root.id,))
    repo.register(target, ancestors=(root.id,))

    result = await _engine(repo).create(
        target_parent_id=target.id, primary_node_id=primary.id
    )
    alias = repo.nodes[result.alias_id]
    assert alias.is_alias is True
    assert alias.points_to_id == primary.id
    assert alias.parent_id == target.id


@pytest.mark.asyncio
async def test_rejects_ancestor_cycle() -> None:
    """An alias from a descendant back to an ancestor is rejected."""
    repo = _FakeNodeRepo()
    root = make_node(depth=0)
    child = make_node(depth=1, parent_id=root.id)
    grandchild = make_node(depth=2, parent_id=child.id)
    repo.register(root)
    repo.register(child, ancestors=(root.id,))
    repo.register(grandchild, ancestors=(root.id, child.id))

    with pytest.raises(AliasConsistencyError) as exc:
        await _engine(repo).create(
            target_parent_id=grandchild.id, primary_node_id=root.id
        )
    assert "cycle" in str(exc.value)


@pytest.mark.asyncio
async def test_rejects_self_parent() -> None:
    """An alias with ``target_parent == primary`` is rejected."""
    repo = _FakeNodeRepo()
    node = make_node(depth=1)
    repo.register(node, ancestors=(uuid4(),))
    with pytest.raises(AliasConsistencyError):
        await _engine(repo).create(
            target_parent_id=node.id, primary_node_id=node.id
        )


@pytest.mark.asyncio
async def test_rejects_primary_is_alias() -> None:
    """The primary node must not itself be an alias."""
    repo = _FakeNodeRepo()
    target = make_node(depth=1)
    alias = make_node(depth=1, is_alias=True, points_to_id=target.id)
    repo.register(target, ancestors=(uuid4(),))
    repo.register(alias, ancestors=(uuid4(),))
    with pytest.raises(AliasConsistencyError):
        await _engine(repo).create(
            target_parent_id=target.id, primary_node_id=alias.id
        )


@pytest.mark.asyncio
async def test_rejects_at_max_depth() -> None:
    """An alias at depth > max_depth is rejected."""
    repo = _FakeNodeRepo()
    deep = make_node(depth=5)
    other = make_node(depth=1)
    repo.register(deep, ancestors=())
    repo.register(other, ancestors=())
    with pytest.raises(AliasConsistencyError):
        await _engine(repo).create(
            target_parent_id=deep.id, primary_node_id=other.id
        )


@pytest.mark.asyncio
async def test_rejects_target_is_alias() -> None:
    """Cannot place an alias under another alias."""
    repo = _FakeNodeRepo()
    primary = make_node(depth=1)
    alias_parent = make_node(depth=1, is_alias=True, points_to_id=primary.id)
    repo.register(primary, ancestors=(uuid4(),))
    repo.register(alias_parent, ancestors=(uuid4(),))
    with pytest.raises(AliasConsistencyError):
        await _engine(repo).create(
            target_parent_id=alias_parent.id, primary_node_id=primary.id
        )
