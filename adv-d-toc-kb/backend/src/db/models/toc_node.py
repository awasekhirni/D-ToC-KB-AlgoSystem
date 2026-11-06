"""``ToCNode`` ORM model -- the tree vertex.

A node is either:
  - a *primary* node (``is_alias=False``, ``points_to_id`` is NULL) holding
    content chunks, or
  - an *alias* node (``is_alias=True``, ``points_to_id`` points to a
    primary node) forming the DAG overlay.

The DB enforces depth bounds (``0..10``, app-level ``MAX_DEPTH`` is stricter)
and alias consistency via CHECK constraints (see migration ``0001_initial``).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base

if TYPE_CHECKING:
    from src.db.models.content_chunk import ContentChunk


def _utcnow() -> datetime:
    """UTC now helper, used as a column default."""
    return datetime.now(timezone.utc)


class ToCNode(Base):
    """A node in the table-of-contents tree.

    Attributes:
        id: UUID primary key.
        title: Human-readable label (1-500 chars).
        semantic_summary: One-sentence description of the node's content.
        parent_id: FK to parent node (NULL for root).
        depth: 0 for root, ``parent.depth + 1`` for children.
        categorization_paradigm: How children are organised
            (``Thematic``, ``Chronological``, etc.).
        is_alias: True if this node is an alias pointer.
        points_to_id: If ``is_alias``, the primary node this points to.
        last_audit_timestamp: When the audit engine last visited this node.
            ``NULL`` means "flagged for immediate audit".
        created_at, updated_at: Timestamps.
        children: Child nodes (one-to-many self-referential).
    """

    __tablename__ = "toc_nodes"
    __table_args__ = (
        CheckConstraint("depth >= 0 AND depth <= 10", name="depth_bounds"),
        CheckConstraint(
            "char_length(title) BETWEEN 1 AND 500", name="title_length"
        ),
        CheckConstraint(
            "(is_alias = FALSE AND points_to_id IS NULL) OR "
            "(is_alias = TRUE AND points_to_id IS NOT NULL AND id <> points_to_id)",
            name="alias_consistency",
        ),
        Index("ix_toc_nodes_parent", "parent_id"),
        Index("ix_toc_nodes_depth", "depth"),
        Index(
            "ix_toc_nodes_alias",
            "points_to_id",
            postgresql_where="is_alias",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    semantic_summary: Mapped[Optional[str]] = mapped_column(Text)
    parent_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("toc_nodes.id", ondelete="RESTRICT"),
        nullable=True,
    )
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    categorization_paradigm: Mapped[str] = mapped_column(
        String(50), nullable=False, default="Thematic"
    )
    is_alias: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    points_to_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("toc_nodes.id", ondelete="RESTRICT"),
        nullable=True,
    )
    # Default to "just audited" so new nodes don't enter the next sweep
    # immediately. Flagged nodes (broken aliases) are reset to NULL.
    last_audit_timestamp: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=_utcnow
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )

    # Two self-referential FKs -> ``foreign_keys`` must be explicit.
    parent: Mapped[Optional["ToCNode"]] = relationship(
        back_populates="children",
        foreign_keys="ToCNode.parent_id",
        remote_side="ToCNode.id",
    )
    children: Mapped[list["ToCNode"]] = relationship(
        back_populates="parent",
        foreign_keys="ToCNode.parent_id",
        order_by="ToCNode.created_at",
    )
    content_chunks: Mapped[list["ContentChunk"]] = relationship(
        back_populates="node",
        cascade="all, delete-orphan",
        foreign_keys="ContentChunk.node_id",
    )

    def __repr__(self) -> str:
        kind = "alias" if self.is_alias else "node"
        return f"<ToCNode {kind} id={self.id} title={self.title!r} depth={self.depth}>"
