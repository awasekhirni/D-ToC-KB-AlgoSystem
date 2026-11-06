# Copyright 2025-26 Beta ORI Inc. Canada. All Rights Reserved.
### Syed,Awase Khirni##
"""Catch-all error envelope -- never leak stack traces to clients.

Every error response is::

    {"error": {"code": str, "message": str, "request_id": str}}

- ``ToCKBError`` subclasses become 422 with the domain error code.
- Unknown exceptions become 500 with a generic message (full traceback in logs).
- ``x-request-id`` is echoed on every response for log correlation.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.core.exceptions import ToCKBError
from src.observability.logging import get_logger

logger = get_logger(__name__)


class ErrorEnvelopeMiddleware(BaseHTTPMiddleware):
    """Wraps all responses in a structured error envelope on failure."""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        except ToCKBError as exc:
            logger.info(
                "Domain error: %s (code=%s)",
                exc, exc.code,
                extra={"request_id": request_id, "code": exc.code},
            )
            return JSONResponse(
                status_code=422,
                content=_envelope(exc.code, str(exc), request_id),
            )
        except Exception:
            logger.exception(
                "Unhandled error",
                extra={"request_id": request_id},
            )
            return JSONResponse(
                status_code=500,
                content=_envelope(
                    "INTERNAL_ERROR", "Unexpected error", request_id
                ),
            )
        response.headers["x-request-id"] = request_id
        return response


def _envelope(code: str, message: str, request_id: str) -> dict:
    """Build the structured error envelope."""
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id,
        }
    }
