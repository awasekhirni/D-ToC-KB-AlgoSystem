"""``ContentChunk`` ORM model -- raw text + embedding for a node.

Chunks are stored separately from ``ToCNode`` so that:
  - the tree (metadata) can be loaded without pulling embeddings,
  - pgvector ANN search joins back to the tree via ``node_id``,
  - re-parenting chunks during restructure is a cheap UPDATE.

The ``(node_id, checksum)`` unique index enforces idempotent ingestion:
re-ingesting identical content under the same node is a no-op.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base
from src.db.models.toc_node import _utcnow

if TYPE_CHECKING:
    from src.db.models.toc_node import ToCNode

# Default embedding dimension; the migration creates the column with this
# size. Changing it requires a full re-index (see DEF-001 in ERROR_INVENTORY).
EMBEDDING_DIM = 1536


class ContentChunk(Base):
    """A chunk of raw content stored against a ``ToCNode``.

    Attributes:
        id: UUID primary key.
        node_id: FK to ``toc_nodes.id``.
        content: Raw text.
        embedding: pgvector embedding (dimension = ``EMBEDDING_DIM``).
        token_count: Number of tokens in ``content`` (used for restructure
            thresholds and audit sampling budgets).
        checksum: SHA-256 hex of ``content``; part of the dedup key.
        created_at: Timestamp.
    """

    __tablename__ = "content_chunks"
    __table_args__ = (
        CheckConstraint("token_count > 0", name="token_count_positive"),
        Index("ix_content_chunks_node", "node_id"),
        Index("uq_content_chunks_dedup", "node_id", "checksum", unique=True),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    node_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("toc_nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(
        Vector(EMBEDDING_DIM), nullable=False
    )
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    node: Mapped["ToCNode"] = relationship(
        back_populates="content_chunks",
        foreign_keys=[node_id],
    )

    def __repr__(self) -> str:
        return (
            f"<ContentChunk id={self.id} node_id={self.node_id} "
            f"tokens={self.token_count}>"
        )
