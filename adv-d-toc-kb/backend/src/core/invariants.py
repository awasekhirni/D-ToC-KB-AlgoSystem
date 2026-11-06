"""Pure functions that assert tree/graph invariants before persistence.

The DB enforces the same invariants via CHECK constraints; these functions
give us fail-fast errors with context *before* we touch the DB, and are
the primary target for property-based tests.

Each assertion has a matching DB constraint (see migration ``0001_initial``).
The Python assertions provide better error messages and are testable
without a database; the DB constraints are the last line of defence against
concurrent writes.
"""

from uuid import UUID

from src.core.exceptions import AliasConsistencyError, InvalidDepthError
from src.db.models import ToCNode


def assert_alias_consistent(node: ToCNode) -> None:
    """Assert that ``node.is_alias`` and ``node.points_to_id`` agree.

    Rules:
        - If ``is_alias`` is True, ``points_to_id`` must be set and not
          equal to ``node.id``.
        - If ``is_alias`` is False, ``points_to_id`` must be None.

    Raises:
        AliasConsistencyError: If the invariant is violated.
    """
    if node.is_alias:
        if node.points_to_id is None:
            raise AliasConsistencyError(
                f"Alias node {node.id} has no points_to_id"
            )
        if node.points_to_id == node.id:
            raise AliasConsistencyError(
                f"Alias node {node.id} points to itself"
            )
    elif node.points_to_id is not None:
        raise AliasConsistencyError(
            f"Non-alias node {node.id} has points_to_id set"
        )


def assert_depth_in_bounds(depth: int, max_depth: int) -> None:
    """Assert that ``depth`` is in ``[0, max_depth]``.

    Raises:
        InvalidDepthError: If depth is negative or exceeds ``max_depth``.
    """
    if depth < 0:
        raise InvalidDepthError(f"Negative depth {depth}")
    if depth > max_depth:
        raise InvalidDepthError(
            f"Depth {depth} exceeds max depth {max_depth}"
        )


def assert_can_attach_child(
    parent: ToCNode, child_depth: int, max_depth: int
) -> None:
    """Assert that a child with ``child_depth`` can be attached to ``parent``.

    The child's depth must be exactly ``parent.depth + 1`` and within bounds.

    Raises:
        InvalidDepthError: If the depth relationship is wrong.
    """
    expected = parent.depth + 1
    if child_depth != expected:
        raise InvalidDepthError(
            f"Child depth {child_depth} != parent depth+1 ({expected})"
        )
    assert_depth_in_bounds(child_depth, max_depth)


def assert_no_self_parent(parent_id: UUID | None, child_id: UUID) -> None:
    """Assert that ``parent_id`` is not equal to ``child_id``.

    Raises:
        AliasConsistencyError: If a node would be its own parent.
    """
    if parent_id is not None and parent_id == child_id:
        raise AliasConsistencyError(
            f"Node {child_id} cannot be its own parent"
        )
