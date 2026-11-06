# Copyright 2025-26 Beta ORI Inc. Canada. All Rights Reserved.
### Syed,Awase Khirni##
"""Bearer-token auth for admin routes.

Public: ``/health``, ``/docs``, ``/openapi.json``, ``/ingest``, ``/toc/``.
Protected: ``/audit/``, ``/alias/``. Token is opt-in via ``TOCKB_ADMIN_TOKEN``;
if unset, all routes are public (dev mode -- a warning is logged at startup).
"""

from __future__ import annotations

import hmac
import logging

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from src.config.settings import Settings
from src.observability.logging import get_logger

logger = get_logger(__name__)

_PROTECTED_PREFIXES = ("/audit", "/alias")
_PUBLIC_PREFIXES = ("/health", "/docs", "/openapi.json", "/redoc")


class AuthMiddleware(BaseHTTPMiddleware):
    """Bearer-token auth for admin routes.

    When ``TOCKB_ADMIN_TOKEN`` is unset, the middleware passes all requests
    through (dev mode) and logs a warning. When set, requests to
    ``/audit/*`` and ``/alias/*`` must include a matching ``Authorization:
    Bearer <token>`` header.
    """

    def __init__(self, app, settings: Settings) -> None:
        super().__init__(app)
        self._settings = settings
        if settings.admin_token is None:
            logger.warning(
                "TOCKB_ADMIN_TOKEN unset -- admin routes are UNPROTECTED. "
                "Do not deploy this configuration to production."
            )

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        # Only protected prefixes need auth.
        if not any(path.startswith(p) for p in _PROTECTED_PREFIXES):
            return await call_next(request)
        # Public prefixes are always allowed (defensive double-check).
        if any(path.startswith(p) for p in _PUBLIC_PREFIXES):
            return await call_next(request)

        expected = self._settings.admin_token
        if expected is None:
            return await call_next(request)  # dev mode

        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer "):
            return _unauthorized()
        provided = header[len("Bearer "):].strip()
        if not hmac.compare_digest(
            provided.encode(), expected.get_secret_value().encode()
        ):
            logger.warning(
                "Unauthorized admin request path=%s", path,
                extra={"path": path},
            )
            return _unauthorized()
        return await call_next(request)


def _unauthorized() -> Response:
    """Return a 401 JSON response."""
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=401,
        content={"error": {"code": "UNAUTHORIZED", "message": "Invalid token"}},
    )
