"""initial schema -- toc_nodes, content_chunks, audit_log

Revision ID: 0001
Revises:
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIM = 1536


def upgrade() -> None:
    """Create the initial schema.

    - Enables the ``vector`` extension (required for pgvector).
    - Creates ``toc_nodes`` with depth + alias-consistency CHECK constraints.
    - Creates ``content_chunks`` with a pgvector column and IVFFlat index.
    - Creates the append-only ``audit_log`` table.
    """
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "toc_nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("semantic_summary", sa.Text(), nullable=True),
        sa.Column(
            "parent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("toc_nodes.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("depth", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "categorization_paradigm",
            sa.String(50),
            nullable=False,
            server_default="Thematic",
        ),
        sa.Column(
            "is_alias",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "points_to_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("toc_nodes.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "last_audit_timestamp",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "depth >= 0 AND depth <= 10", name="ck_toc_nodes_depth_bounds"
        ),
        sa.CheckConstraint(
            "char_length(title) BETWEEN 1 AND 500",
            name="ck_toc_nodes_title_length",
        ),
        sa.CheckConstraint(
            "(is_alias = FALSE AND points_to_id IS NULL) OR "
            "(is_alias = TRUE AND points_to_id IS NOT NULL AND id <> points_to_id)",
            name="ck_toc_nodes_alias_consistency",
        ),
    )
    op.create_index("ix_toc_nodes_parent", "toc_nodes", ["parent_id"])
    op.create_index("ix_toc_nodes_depth", "toc_nodes", ["depth"])
    op.create_index(
        "ix_toc_nodes_alias",
        "toc_nodes",
        ["points_to_id"],
        postgresql_where=sa.text("is_alias"),
    )

    op.create_table(
        "content_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "node_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("toc_nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "token_count > 0", name="ck_content_chunks_token_count_positive"
        ),
    )
    op.create_index("ix_content_chunks_node", "content_chunks", ["node_id"])
    op.create_index(
        "uq_content_chunks_dedup",
        "content_chunks",
        ["node_id", "checksum"],
        unique=True,
    )
    # IVFFlat index on the vector column for ANN search.
    op.execute(
        "CREATE INDEX ix_content_chunks_embedding "
        "ON content_chunks USING ivfflat (embedding vector_cosine_ops) "
        "WITH (lists = 100)"
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "node_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("toc_nodes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("actor", sa.String(100), nullable=False, server_default="system"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_audit_log_node", "audit_log", ["node_id", "created_at"])


def downgrade() -> None:
    """Drop all tables. Leaves the ``vector`` extension installed."""
    op.drop_table("audit_log")
    op.drop_table("content_chunks")
    op.drop_table("toc_nodes")
    # Leave the ``vector`` extension installed; dropping it may break other schemas.
