# Copyright 2025-26 Beta ORI Inc. Canada. All Rights Reserved.
### Syed,Awase Khirni##
"""Alias route -- manually create an alias node.

Admin-only (requires ``TOCKB_ADMIN_TOKEN`` when set).
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import Settings
from src.core.engine.alias_creator import AliasCreationEngine
from src.core.exceptions import AliasConsistencyError
from src.db.repositories import AuditRepository, ToCNodeRepository
from src.db.session import get_session
from src.observability.logging import get_logger
from src.api.deps import provide_settings

logger = get_logger(__name__)

router = APIRouter(prefix="/alias", tags=["alias"])


class CreateAliasBody(BaseModel):
    """Request body for ``POST /alias``."""

    target_parent_id: UUID
    primary_node_id: UUID


class CreateAliasResponse(BaseModel):
    """Response body for ``POST /alias``."""

    alias_id: UUID
    target_parent_id: UUID
    primary_node_id: UUID


@router.post("", response_model=CreateAliasResponse, status_code=201)
async def create_alias(
    body: CreateAliasBody,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(provide_settings),
) -> CreateAliasResponse:
    """Manually create an alias from ``target_parent_id`` to ``primary_node_id``.

    Returns 201 on success, 422 on invariant violation.
    """
    logger.info(
        "Manual alias request: target_parent=%s primary=%s",
        body.target_parent_id, body.primary_node_id,
    )
    engine = AliasCreationEngine(
        session=session,
        settings=settings,
        node_repo=ToCNodeRepository(session),
        audit_repo=AuditRepository(session),
    )
    try:
        result = await engine.create(
            target_parent_id=body.target_parent_id,
            primary_node_id=body.primary_node_id,
        )
    except AliasConsistencyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return CreateAliasResponse(
        alias_id=result.alias_id,
        target_parent_id=result.target_parent_id,
        primary_node_id=result.primary_node_id,
    )
