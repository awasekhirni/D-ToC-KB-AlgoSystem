# Copyright 2025-26 Beta ORI Inc. Canada. All Rights Reserved.
### Syed,Awase Khirni##
"""Tree retrieval route -- returns a full subtree via a recursive CTE.

Capped at 5,000 nodes per request to keep response sizes sane. The
``truncated`` flag in the response tells the client when the cap was hit.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_session
from src.observability.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/toc", tags=["toc"])

_MAX_TREE_NODES = 5_000


class NodeOut(BaseModel):
    """A node in the tree response."""

    id: UUID
    title: str
    semantic_summary: str | None = None
    depth: int
    categorization_paradigm: str
    is_alias: bool
    points_to_id: UUID | None = None
    children: list["NodeOut"] = Field(default_factory=list)


class TreeOut(BaseModel):
    """The full subtree response."""

    root: NodeOut
    truncated: bool


NodeOut.model_rebuild()


@router.get("/{root_id}", response_model=TreeOut)
async def get_tree(
    root_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> TreeOut:
    """Return the full subtree rooted at ``root_id``.

    Uses a single recursive CTE to load all descendants in one round-trip.
    The response is truncated at 5,000 nodes; ``truncated`` indicates this.
    """
    logger.info("Tree request for root %s", root_id)
    cte_sql = sql_text(
        """
        WITH RECURSIVE subtree AS (
            SELECT * FROM toc_nodes WHERE id = :root_id
            UNION ALL
            SELECT n.* FROM toc_nodes n
            JOIN subtree s ON n.parent_id = s.id
        )
        SELECT * FROM subtree LIMIT :limit
        """
    )
    rows = (
        await session.execute(
            cte_sql,
            {"root_id": str(root_id), "limit": _MAX_TREE_NODES + 1},
        )
    ).mappings().all()

    if not rows:
        raise HTTPException(status_code=404, detail="Node not found")

    truncated = len(rows) > _MAX_TREE_NODES
    if truncated:
        logger.info("Tree truncated at %d nodes", _MAX_TREE_NODES)

    by_id: dict[UUID, NodeOut] = {}
    for row in rows[:_MAX_TREE_NODES]:
        nid = UUID(str(row["id"]))
        by_id[nid] = NodeOut(
            id=nid,
            title=row["title"],
            semantic_summary=row["semantic_summary"],
            depth=row["depth"],
            categorization_paradigm=row["categorization_paradigm"],
            is_alias=row["is_alias"],
            points_to_id=(
                UUID(str(row["points_to_id"])) if row["points_to_id"] else None
            ),
            children=[],
        )
    for row in rows[:_MAX_TREE_NODES]:
        nid = UUID(str(row["id"]))
        pid = UUID(str(row["parent_id"])) if row["parent_id"] else None
        if pid is not None and pid in by_id:
            by_id[pid].children.append(by_id[nid])

    return TreeOut(root=by_id[UUID(str(root_id))], truncated=truncated)
