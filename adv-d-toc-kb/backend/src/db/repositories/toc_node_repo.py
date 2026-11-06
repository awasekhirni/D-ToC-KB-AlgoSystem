"""Repository for ``ToCNode`` persistence.

Repositories are the only place SQL is written. The engines depend on
these interfaces (not on ``AsyncSession`` directly), which keeps them
testable against in-memory fakes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db.models import ToCNode
from src.observability.logging import get_logger

logger = get_logger(__name__)


class ToCNodeRepository:
    """CRUD + tree-aware queries for ``ToCNode``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, node_id: UUID) -> Optional[ToCNode]:
        """Fetch a single node by ID. Returns ``None`` if not found."""
        logger.debug("Fetching node %s", node_id)
        return await self._session.get(ToCNode, node_id)

    async def get_with_children(self, node_id: UUID) -> Optional[ToCNode]:
        """Fetch a node and eagerly load its direct children."""
        logger.debug("Fetching node %s with children", node_id)
        stmt = (
            select(ToCNode)
            .where(ToCNode.id == node_id)
            .options(selectinload(ToCNode.children))
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_root(self) -> Optional[ToCNode]:
        """Fetch the (first) root node -- a non-alias node with no parent."""
        stmt = (
            select(ToCNode)
            .where(ToCNode.parent_id.is_(None), ToCNode.is_alias.is_(False))
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_children(self, parent_id: UUID) -> list[ToCNode]:
        """Return all direct children of ``parent_id``, ordered by creation."""
        logger.debug("Fetching children of %s", parent_id)
        stmt = (
            select(ToCNode)
            .where(ToCNode.parent_id == parent_id)
            .order_by(ToCNode.created_at)
        )
        return list((await self._session.execute(stmt)).scalars())

    async def add(self, node: ToCNode) -> ToCNode:
        """Add a new node and flush to assign it an ID."""
        logger.info(
            "Adding node title=%r depth=%d alias=%s",
            node.title, node.depth, node.is_alias,
        )
        self._session.add(node)
        await self._session.flush()
        return node

    async def count_children(self, parent_id: UUID) -> int:
        """Count direct children of ``parent_id``."""
        stmt = (
            select(func.count())
            .select_from(ToCNode)
            .where(ToCNode.parent_id == parent_id)
        )
        return int((await self._session.execute(stmt)).scalar_one())

    # -- Audit helpers ---------------------------------------------------

    async def due_for_audit(
        self, interval_days: int, limit: int = 100
    ) -> list[ToCNode]:
        """Return nodes flagged (NULL timestamp) or stale by ``interval_days``.

        ``NULLS FIRST`` ordering ensures flagged nodes (e.g. broken aliases)
        are audited before merely-stale ones.
        """
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=interval_days)
        stmt = (
            select(ToCNode)
            .where(
                or_(
                    ToCNode.last_audit_timestamp.is_(None),
                    ToCNode.last_audit_timestamp < cutoff,
                )
            )
            .order_by(ToCNode.last_audit_timestamp.asc().nulls_first())
            .limit(limit)
        )
        nodes = list((await self._session.execute(stmt)).scalars())
        logger.info("Found %d nodes due for audit", len(nodes))
        return nodes

    async def flag_for_audit(self, node_id: UUID) -> None:
        """Flag a node for immediate audit by setting ``last_audit_timestamp=NULL``."""
        logger.info("Flagging node %s for immediate audit", node_id)
        node = await self.get(node_id)
        if node is None:
            logger.warning("Cannot flag non-existent node %s", node_id)
            return
        node.last_audit_timestamp = None
        await self._session.flush()

    async def get_subtree_ids(self, node_id: UUID) -> list[UUID]:
        """Return IDs of ``node_id`` and all its descendants (single CTE)."""
        logger.debug("Computing subtree of %s", node_id)
        stmt = text(
            """
            WITH RECURSIVE subtree AS (
                SELECT id FROM toc_nodes WHERE id = :root
                UNION ALL
                SELECT n.id FROM toc_nodes n
                JOIN subtree s ON n.parent_id = s.id
            )
            SELECT id FROM subtree
            """
        )
        rows = await self._session.execute(stmt, {"root": str(node_id)})
        return [UUID(str(r[0])) for r in rows]

    async def is_ancestor_of(
        self, potential_ancestor_id: UUID, node_id: UUID
    ) -> bool:
        """Return True if ``potential_ancestor_id`` is an ancestor of ``node_id``.

        Uses a recursive CTE that walks the ``parent_id`` chain upward from
        ``node_id``. Used by ``AliasCreationEngine`` to reject cycles.
        """
        logger.debug(
            "Checking if %s is an ancestor of %s",
            potential_ancestor_id, node_id,
        )
        stmt = text(
            """
            WITH RECURSIVE ancestors AS (
                SELECT id, parent_id FROM toc_nodes WHERE id = :of
                UNION ALL
                SELECT n.id, n.parent_id FROM toc_nodes n
                JOIN ancestors a ON n.id = a.parent_id
            )
            SELECT 1 FROM ancestors WHERE id = :pot LIMIT 1
            """
        )
        result = await self._session.execute(
            stmt,
            {
                "of": str(node_id),
                "pot": str(potential_ancestor_id),
            },
        )
        return result.first() is not None
