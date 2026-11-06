"""Repository for the append-only ``AuditLog``.

The audit log is written-only from the application's perspective; rows
are never updated or deleted (only read for the dashboard). This makes
it safe for replay and forensic analysis.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import AuditLog
from src.observability.logging import get_logger

logger = get_logger(__name__)


class AuditRepository:
    """Append-only writer for ``AuditLog`` events."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def log(
        self,
        *,
        node_id: UUID | None,
        event_type: str,
        payload: dict[str, Any],
        actor: str = "system",
    ) -> AuditLog:
        """Persist an audit event.

        Args:
            node_id: The node this event concerns (None if N/A).
            event_type: One of ``AuditEventType``.
            payload: Event-specific details (JSONB).
            actor: ``"system"`` or a user identifier.

        Returns:
            The persisted ``AuditLog`` row (with ``id`` set).
        """
        logger.info(
            "Audit event type=%s node=%s actor=%s",
            event_type, node_id, actor,
        )
        entry = AuditLog(
            node_id=node_id,
            event_type=event_type,
            payload=payload,
            actor=actor,
        )
        self._session.add(entry)
        await self._session.flush()
        return entry
