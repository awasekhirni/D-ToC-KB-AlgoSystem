"""``AuditLog`` ORM model -- append-only event log.

Every structural mutation (route, split, alias, summary rewrite, drift
correction) writes a row here. The log is the source of truth for
"what happened" and supports replayability and the audit dashboard.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base
from src.db.models.toc_node import _utcnow


class AuditLog(Base):
    """An immutable audit event.

    Attributes:
        id: Bigserial primary key.
        node_id: FK to ``toc_nodes.id`` (SET NULL on delete so the log
            survives the node it references).
        event_type: One of ``AuditEventType``.
        payload: JSONB with event-specific details.
        actor: ``"system"`` or a user identifier.
        created_at: Timestamp.
    """

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_node", "node_id", "created_at"),)

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    node_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("toc_nodes.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    actor: Mapped[str] = mapped_column(String(100), nullable=False, default="system")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog id={self.id} event={self.event_type} "
            f"node={self.node_id}>"
        )
