"""Alias chain resolver -- follows ``points_to_id`` up to ``max_hops``.

Guarantees:

1. Returns a non-alias terminal node.
2. Detects cycles (self-reference, two-node loops, any repeat).
3. Raises ``BrokenAliasChain`` with a machine-readable ``reason`` so the
   caller can persist the audit entry and flag the node for repair.

The resolver is the only place that walks alias chains. The routing engine
and audit engine both delegate to it, ensuring consistent behaviour and
cycle detection.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from src.core.exceptions import BrokenAliasChain
from src.observability.logging import get_logger

if TYPE_CHECKING:
    from src.db.models import ToCNode
    from src.db.repositories import ToCNodeRepository

logger = get_logger(__name__)


class AliasResolver:
    """Follows an alias chain up to ``max_hops`` links.

    Args:
        repo: Repository for fetching nodes by ID.
        max_hops: Maximum number of alias links to follow before raising
            ``BrokenAliasChain``. Must be >= 1.
    """

    def __init__(self, repo: "ToCNodeRepository", max_hops: int) -> None:
        if max_hops < 1:
            raise ValueError("max_hops must be >= 1")
        self._repo = repo
        self._max_hops = max_hops

    async def resolve(self, node: "ToCNode") -> tuple["ToCNode", int]:
        """Resolve ``node`` to its primary target.

        If ``node`` is not an alias, returns it unchanged with hop count 0.
        Otherwise follows the ``points_to_id`` chain up to ``max_hops``
        times, detecting cycles and dangling pointers.

        Args:
            node: The starting node (alias or primary).

        Returns:
            Tuple of ``(terminal_node, hop_count)``. ``terminal_node`` is
            always a non-alias node.

        Raises:
            BrokenAliasChain: If the chain is too long, contains a cycle,
                or points to a non-existent node.
        """
        if not node.is_alias:
            return node, 0

        visited: set[UUID] = {node.id}
        current = node
        logger.debug("Resolving alias chain from %s", node.id)

        for hop in range(1, self._max_hops + 1):
            if current.points_to_id is None:
                # Should be impossible given the CHECK constraint, but defend.
                raise BrokenAliasChain(
                    node_id=current.id,
                    reason="missing points_to_id",
                )
            target = await self._repo.get(current.points_to_id)
            if target is None:
                raise BrokenAliasChain(
                    node_id=current.id,
                    reason="dangling points_to_id",
                )
            if target.id in visited:
                raise BrokenAliasChain(
                    node_id=current.id,
                    reason="cycle detected",
                )
            if not target.is_alias:
                logger.debug(
                    "Resolved %s -> %s in %d hops", node.id, target.id, hop
                )
                return target, hop
            visited.add(target.id)
            current = target

        raise BrokenAliasChain(
            node_id=node.id,
            reason=f"exceeded max alias hops ({self._max_hops})",
        )
