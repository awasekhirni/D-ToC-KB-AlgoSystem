"""Phase 4: DAG overlay -- creates alias nodes with cycle prevention.

Invariants enforced at creation time:

1. ``target_parent_id`` must exist and not be an alias.
2. ``primary_node_id`` must exist and not be an alias.
3. ``primary_node_id`` must not be an ancestor of ``target_parent_id``
   (would create an upward-pointing cycle).
4. ``target_parent_id.depth < max_depth`` (room for a new child).
5. ``primary_node_id != target_parent_id`` (no self-reference).

Multi-hop cycles (A->descendant, D->C) are prevented by invariant 3 at each
step, by induction. The routing engine's iteration budget is the final
safety net.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import Settings
from src.core.enums import AuditEventType
from src.core.exceptions import AliasConsistencyError, InvalidDepthError
from src.core.invariants import assert_alias_consistent, assert_depth_in_bounds
from src.db.models import ToCNode
from src.observability.logging import get_logger

if TYPE_CHECKING:
    from src.db.repositories import AuditRepository, ToCNodeRepository

logger = get_logger(__name__)


@dataclass(frozen=True)
class AliasResult:
    """Outcome of alias creation.

    Attributes:
        alias_id: The newly created alias node's ID.
        target_parent_id: The parent under which the alias was placed.
        primary_node_id: The primary node the alias points to.
    """

    alias_id: UUID
    target_parent_id: UUID
    primary_node_id: UUID


class AliasCreationEngine:
    """Creates alias nodes after enforcing all 5 invariants."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        settings: Settings,
        node_repo: "ToCNodeRepository",
        audit_repo: "AuditRepository",
    ) -> None:
        self._session = session
        self._settings = settings
        self._node_repo = node_repo
        self._audit_repo = audit_repo

    async def create(
        self, *, target_parent_id: UUID, primary_node_id: UUID
    ) -> AliasResult:
        """Create an alias node pointing from ``target_parent_id`` to ``primary_node_id``.

        Args:
            target_parent_id: The parent under which to place the alias.
            primary_node_id: The primary node the alias points to.

        Returns:
            ``AliasResult`` with the new alias's ID.

        Raises:
            AliasConsistencyError: If any invariant is violated.
        """
        logger.info(
            "Creating alias: target_parent=%s primary=%s",
            target_parent_id, primary_node_id,
        )

        target_parent = await self._node_repo.get(target_parent_id)
        if target_parent is None:
            raise AliasConsistencyError(
                f"Target parent {target_parent_id} not found"
            )
        if target_parent.is_alias:
            raise AliasConsistencyError(
                f"Cannot place alias under another alias {target_parent_id}"
            )

        primary = await self._node_repo.get(primary_node_id)
        if primary is None:
            raise AliasConsistencyError(
                f"Primary node {primary_node_id} not found"
            )
        if primary.is_alias:
            raise AliasConsistencyError(
                f"Primary node {primary_node_id} is itself an alias"
            )

        # Invariant 3: primary must not be an ancestor of target_parent.
        if primary.id == target_parent.id or await self._node_repo.is_ancestor_of(
            potential_ancestor_id=primary.id, node_id=target_parent.id
        ):
            raise AliasConsistencyError(
                f"Alias would create a cycle: {primary.id} is an ancestor "
                f"of {target_parent.id}"
            )

        # Invariant 4: room for one more child.
        alias_depth = target_parent.depth + 1
        try:
            assert_depth_in_bounds(alias_depth, self._settings.max_depth)
        except InvalidDepthError as exc:
            raise AliasConsistencyError(
                f"Cannot add alias at depth {alias_depth}: {exc}"
            ) from exc

        alias = ToCNode(
            title=primary.title[:500],
            semantic_summary=(
                f"Alias: {primary.semantic_summary or primary.title}"
            ),
            parent_id=target_parent.id,
            depth=alias_depth,
            categorization_paradigm=primary.categorization_paradigm,
            is_alias=True,
            points_to_id=primary.id,
        )
        # last_audit_timestamp defaults to now() in the model.
        assert_alias_consistent(alias)
        await self._node_repo.add(alias)

        await self._audit_repo.log(
            node_id=alias.id,
            event_type=AuditEventType.ALIAS_CREATED,
            payload={
                "target_parent_id": str(target_parent.id),
                "primary_node_id": str(primary.id),
                "alias_depth": alias_depth,
            },
        )
        logger.info(
            "Created alias %s under %s -> primary %s",
            alias.id, target_parent.id, primary.id,
        )
        return AliasResult(
            alias_id=alias.id,
            target_parent_id=target_parent.id,
            primary_node_id=primary.id,
        )
