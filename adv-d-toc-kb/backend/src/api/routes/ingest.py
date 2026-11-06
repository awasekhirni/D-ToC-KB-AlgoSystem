# Copyright 2025-26 Beta ORI Inc. Canada. All Rights Reserved.
### Syed,Awase Khirni##
"""Ingestion route -- accepts content and routes it into the tree.

After successful routing, enqueues a Celery restructure task (fire-and-
forget) so the post-ingestion restructure check runs asynchronously.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import provide_engine
from src.core.engine.routing import IngestRequest, RoutingEngine
from src.core.exceptions import BrokenAliasChain, ToCKBError
from src.db.repositories import ToCNodeRepository
from src.db.session import get_session
from src.observability.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/ingest", tags=["ingest"])


class IngestBody(BaseModel):
    """Request body for ``POST /ingest``."""

    root_id: UUID
    content: str = Field(min_length=1, max_length=1_000_000)
    title_hint: str | None = Field(default=None, max_length=500)
    summary_hint: str | None = Field(default=None, max_length=2_000)


class IngestResponse(BaseModel):
    """Response body for ``POST /ingest``."""

    node_id: UUID
    routed_path: list[UUID]
    spillover_created: bool
    pivot_triggered: bool
    duplicate: bool
    tokens_in_node: int


@router.post(
    "",
    response_model=IngestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ingest(
    body: IngestBody,
    session: AsyncSession = Depends(get_session),
    engine: RoutingEngine = Depends(provide_engine),
) -> IngestResponse:
    """Ingest ``body.content`` into the tree rooted at ``body.root_id``.

    Returns 201 on success, 404 if the root doesn't exist, 400 if the
    root is an alias, 409 on broken alias chain, 422 on other domain errors.
    """
    logger.info(
        "Ingest request root_id=%s content_len=%d",
        body.root_id, len(body.content),
    )
    node_repo = ToCNodeRepository(session)
    root = await node_repo.get(body.root_id)
    if root is None:
        raise HTTPException(status_code=404, detail="Root node not found")
    if root.is_alias:
        raise HTTPException(
            status_code=400, detail="Cannot ingest into an alias node"
        )

    try:
        result = await engine.ingest(
            root,
            IngestRequest(
                content=body.content,
                title_hint=body.title_hint,
                summary_hint=body.summary_hint,
            ),
        )
    except BrokenAliasChain as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "reason": exc.reason},
        ) from exc
    except ToCKBError as exc:
        raise HTTPException(
            status_code=422, detail={"code": exc.code}
        ) from exc

    # Fire-and-forget: the worker re-checks thresholds; harmless if below.
    if not result.duplicate:
        try:
            from src.workers.restructure_worker import restructure_node

            restructure_node.delay(str(result.node_id))
            logger.debug("Enqueued restructure for node %s", result.node_id)
        except Exception:
            # Celery unavailable -- log and continue; routing already succeeded.
            logger.warning(
                "Could not enqueue restructure for node %s",
                result.node_id,
                exc_info=True,
            )

    return IngestResponse(
        node_id=result.node_id,
        routed_path=list(result.routed_path),
        spillover_created=result.spillover_created,
        pivot_triggered=result.pivot_triggered,
        duplicate=result.duplicate,
        tokens_in_node=result.tokens_in_node,
    )
