# Copyright 2025-26 Beta ORI Inc. Canada. All Rights Reserved.
### Syed,Awase Khirni##
"""Health endpoint -- liveness probe for Docker / load balancers."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    """Return ``{"status": "ok"}`` if the process is alive."""
    return {"status": "ok"}
