"""Repository for ``ContentChunk`` persistence.

The notable method here is ``centroids_for``, which computes the mean
embedding per node in a single SQL round-trip (pgvector's ``avg`` returns
a vector). This avoids an N+1 when scoring children during routing.
"""

from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import ContentChunk
from src.observability.logging import get_logger

logger = get_logger(__name__)

EMBEDDING_DIM = 1536


class ContentChunkRepository:
    """CRUD + vector-aware queries for ``ContentChunk``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, chunk: ContentChunk) -> ContentChunk:
        """Add a new chunk and flush to assign it an ID."""
        logger.info(
            "Adding chunk node_id=%s tokens=%d checksum=%s",
            chunk.node_id, chunk.token_count, chunk.checksum[:12],
        )
        self._session.add(chunk)
        await self._session.flush()
        return chunk

    async def get_by_node(self, node_id: UUID) -> list[ContentChunk]:
        """Return all chunks for ``node_id``, ordered by creation time."""
        logger.debug("Fetching chunks for node %s", node_id)
        stmt = (
            select(ContentChunk)
            .where(ContentChunk.node_id == node_id)
            .order_by(ContentChunk.created_at)
        )
        return list((await self._session.execute(stmt)).scalars())

    async def fetch_embeddings(self, node_id: UUID) -> list[list[float]]:
        """Return just the embedding vectors for ``node_id`` (no text)."""
        stmt = select(ContentChunk.embedding).where(
            ContentChunk.node_id == node_id
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [list(row) for row in rows]

    async def exists_with_checksum(
        self, node_id: UUID, checksum: str
    ) -> bool:
        """Return True if a chunk with ``checksum`` already exists for ``node_id``.

        Used for idempotent ingestion: re-ingesting identical content is
        a no-op.
        """
        stmt = (
            select(func.count())
            .select_from(ContentChunk)
            .where(
                ContentChunk.node_id == node_id,
                ContentChunk.checksum == checksum,
            )
        )
        return int((await self._session.execute(stmt)).scalar_one()) > 0

    async def centroids_for(
        self, node_ids: list[UUID]
    ) -> dict[UUID, list[float]]:
        """Return one centroid (mean embedding) per node, computed in-database.

        pgvector's ``avg`` returns a vector; grouping by ``node_id`` gives us
        all child centroids in one round-trip regardless of child count.
        Nodes with no chunks are omitted from the result.
        """
        if not node_ids:
            return {}
        logger.debug("Computing centroids for %d nodes", len(node_ids))
        stmt = (
            select(
                ContentChunk.node_id,
                func.avg(ContentChunk.embedding).cast(Vector(EMBEDDING_DIM)),
            )
            .where(ContentChunk.node_id.in_(node_ids))
            .group_by(ContentChunk.node_id)
        )
        rows = (await self._session.execute(stmt)).all()
        return {row[0]: list(row[1]) for row in rows}

    async def total_tokens(self, node_id: UUID) -> int:
        """Return the total token count across all chunks for ``node_id``."""
        stmt = select(
            func.coalesce(func.sum(ContentChunk.token_count), 0)
        ).where(ContentChunk.node_id == node_id)
        return int((await self._session.execute(stmt)).scalar_one())

    async def reparent_many(
        self, chunk_ids: list[UUID], new_node_id: UUID
    ) -> None:
        """Bulk-update the ``node_id`` of the given chunks.

        Used during restructure/pivot to move chunks from old children to
        new ones in a single UPDATE.
        """
        if not chunk_ids:
            return
        logger.info(
            "Reparenting %d chunks to node %s", len(chunk_ids), new_node_id
        )
        await self._session.execute(
            update(ContentChunk)
            .where(ContentChunk.id.in_(chunk_ids))
            .values(node_id=new_node_id)
        )
        await self._session.flush()

    async def knn_excluding_subtree(
        self,
        embedding: list[float],
        exclude_node_ids: list[UUID],
        limit: int = 5,
    ) -> list[tuple[UUID, float]]:
        """Return top-K other nodes by minimum cosine distance from ``embedding``.

        Returns ``[(node_id, distance), ...]`` where ``distance`` is in
        ``[0, 2]`` and ``similarity == 1 - distance``.

        Used by the audit engine to find candidate alias targets outside
        the current subtree (self-references aren't useful).
        """
        logger.debug(
            "KNN search limit=%d excluding %d nodes", limit, len(exclude_node_ids)
        )
        stmt = (
            select(
                ContentChunk.node_id,
                func.min(
                    ContentChunk.embedding.cosine_distance(embedding)
                ).label("dist"),
            )
            .where(ContentChunk.node_id.notin_(exclude_node_ids))
            .group_by(ContentChunk.node_id)
            .order_by("dist")
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).all()
        return [(r[0], float(r[1])) for r in rows]
