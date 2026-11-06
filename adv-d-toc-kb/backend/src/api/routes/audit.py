# Copyright 2025-26 Beta ORI Inc. Canada. All Rights Reserved.
### Syed,Awase Khirni##
"""Audit routes -- trigger sweeps and read the audit log.

Admin-only (requires ``TOCKB_ADMIN_TOKEN`` when set).
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import AuditLog
from src.db.session import get_session
from src.observability.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditLogEntry(BaseModel):
    """One audit event."""

    id: int
    node_id: UUID | None
    event_type: str
    payload: dict
    actor: str
    created_at: str


class AuditLogResponse(BaseModel):
    """Response for the audit log endpoint."""

    entries: list[AuditLogEntry]


class RunAuditResponse(BaseModel):
    """Response for the audit-run endpoint (just an ack)."""

    total: int
    processed: int
    errors: int


@router.post("/run", response_model=RunAuditResponse)
async def run_audit(
    node_id: UUID | None = Query(default=None),
    batch_size: int | None = Query(default=None, ge=1, le=1000),
) -> RunAuditResponse:
    """Trigger an audit.

    With ``node_id`` set, audits a single node. Without it, triggers a
    sweep of due nodes. Dispatches to Celery and returns immediately --
    the HTTP request does not block on the (potentially long) audit work.
    """
    from src.workers.audit_worker import audit_single_node, sweep_due_nodes

    if node_id is not None:
        logger.info("Enqueuing single-node audit for %s", node_id)
        audit_single_node.delay(str(node_id))
        return RunAuditResponse(total=1, processed=0, errors=0)

    logger.info("Enqueuing audit sweep batch_size=%s", batch_size)
    sweep_due_nodes.delay(batch_size)
    return RunAuditResponse(total=0, processed=0, errors=0)


@router.get("/log/{node_id}", response_model=AuditLogResponse)
async def get_audit_log(
    node_id: UUID,
    limit: int = Query(default=50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> AuditLogResponse:
    """Return the audit timeline for ``node_id``, newest first."""
    logger.info("Fetching audit log for %s (limit=%d)", node_id, limit)
    stmt = (
        select(AuditLog)
        .where(AuditLog.node_id == node_id)
        .order_by(desc(AuditLog.created_at))
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return AuditLogResponse(
        entries=[
            AuditLogEntry(
                id=r.id,
                node_id=r.node_id,
                event_type=r.event_type,
                payload=r.payload,
                actor=r.actor,
                created_at=r.created_at.isoformat(),
            )
            for r in rows
        ]
    )
