"""Tests for the ``AliasResolver``."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from src.core.engine.alias import AliasResolver
from src.core.exceptions import BrokenAliasChain
from tests.factories import make_node


class _FakeNodeRepo:
    """In-memory node repository for alias resolver tests."""

    def __init__(self, nodes: list[Any]) -> None:
        self._nodes: dict[UUID, Any] = {n.id: n for n in nodes}

    async def get(self, node_id: UUID) -> Any | None:
        return self._nodes.get(node_id)


@pytest.mark.asyncio
async def test_non_alias_returns_immediately() -> None:
    """A non-alias node resolves to itself with 0 hops."""
    target = make_node()
    resolver = AliasResolver(_FakeNodeRepo([target]), max_hops=3)
    resolved, hops = await resolver.resolve(target)
    assert resolved.id == target.id
    assert hops == 0


@pytest.mark.asyncio
async def test_one_hop_resolves() -> None:
    """A single-hop alias resolves to its primary."""
    primary = make_node()
    alias = make_node(is_alias=True, points_to_id=primary.id)
    resolver = AliasResolver(_FakeNodeRepo([primary, alias]), max_hops=3)
    resolved, hops = await resolver.resolve(alias)
    assert resolved.id == primary.id
    assert hops == 1


@pytest.mark.asyncio
async def test_three_hops_ok() -> None:
    """A 3-hop chain resolves within the budget."""
    primary = make_node()
    a2 = make_node(is_alias=True, points_to_id=primary.id)
    a1 = make_node(is_alias=True, points_to_id=a2.id)
    a0 = make_node(is_alias=True, points_to_id=a1.id)
    resolver = AliasResolver(
        _FakeNodeRepo([primary, a0, a1, a2]), max_hops=3
    )
    resolved, hops = await resolver.resolve(a0)
    assert resolved.id == primary.id
    assert hops == 3


@pytest.mark.asyncio
async def test_four_hops_raises() -> None:
    """A 4-hop chain exceeds the budget and raises."""
    primary = make_node()
    a3 = make_node(is_alias=True, points_to_id=primary.id)
    a2 = make_node(is_alias=True, points_to_id=a3.id)
    a1 = make_node(is_alias=True, points_to_id=a2.id)
    a0 = make_node(is_alias=True, points_to_id=a1.id)
    resolver = AliasResolver(
        _FakeNodeRepo([primary, a0, a1, a2, a3]), max_hops=3
    )
    with pytest.raises(BrokenAliasChain) as exc:
        await resolver.resolve(a0)
    assert "exceeded" in exc.value.reason


@pytest.mark.asyncio
async def test_cycle_detected() -> None:
    """A two-node cycle is detected."""
    a = make_node(is_alias=True)
    b = make_node(is_alias=True, points_to_id=a.id)
    a.points_to_id = b.id
    resolver = AliasResolver(_FakeNodeRepo([a, b]), max_hops=5)
    with pytest.raises(BrokenAliasChain) as exc:
        await resolver.resolve(a)
    assert "cycle" in exc.value.reason


@pytest.mark.asyncio
async def test_dangling_pointer_raises() -> None:
    """An alias pointing to a non-existent node raises."""
    primary = make_node()
    alias = make_node(is_alias=True, points_to_id=primary.id)
    # Repo is empty -> primary lookup returns None.
    resolver = AliasResolver(_FakeNodeRepo([alias]), max_hops=3)
    with pytest.raises(BrokenAliasChain) as exc:
        await resolver.resolve(alias)
    assert "dangling" in exc.value.reason
