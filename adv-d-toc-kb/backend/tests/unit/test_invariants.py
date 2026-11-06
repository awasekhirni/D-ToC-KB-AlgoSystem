"""Tests for the invariant assertions."""

from __future__ import annotations

import pytest

from src.core.exceptions import AliasConsistencyError, InvalidDepthError
from src.core.invariants import (
    assert_alias_consistent,
    assert_can_attach_child,
    assert_depth_in_bounds,
)
from tests.factories import make_node


def test_alias_node_without_target_fails() -> None:
    """An alias node with no ``points_to_id`` violates consistency."""
    node = make_node(is_alias=True, points_to_id=None)
    with pytest.raises(AliasConsistencyError):
        assert_alias_consistent(node)


def test_alias_node_self_reference_fails() -> None:
    """An alias pointing to itself violates consistency."""
    node = make_node(is_alias=False)
    node.points_to_id = node.id
    with pytest.raises(AliasConsistencyError):
        assert_alias_consistent(node)


def test_non_alias_with_points_to_fails() -> None:
    """A non-alias node with ``points_to_id`` set violates consistency."""
    node = make_node(points_to_id=make_node().id)
    with pytest.raises(AliasConsistencyError):
        assert_alias_consistent(node)


def test_depth_out_of_bounds() -> None:
    """Negative depths and depths over max are rejected."""
    with pytest.raises(InvalidDepthError):
        assert_depth_in_bounds(6, max_depth=5)
    with pytest.raises(InvalidDepthError):
        assert_depth_in_bounds(-1, max_depth=5)


def test_depth_in_bounds_ok() -> None:
    """Valid depths pass."""
    assert_depth_in_bounds(0, max_depth=5)
    assert_depth_in_bounds(5, max_depth=5)


def test_can_attach_child_rejects_wrong_depth() -> None:
    """A child whose depth isn't ``parent.depth + 1`` is rejected."""
    parent = make_node(depth=2)
    with pytest.raises(InvalidDepthError):
        assert_can_attach_child(parent, child_depth=4, max_depth=5)


def test_can_attach_child_ok() -> None:
    """Correct depth relationships pass."""
    parent = make_node(depth=2)
    assert_can_attach_child(parent, child_depth=3, max_depth=5)
