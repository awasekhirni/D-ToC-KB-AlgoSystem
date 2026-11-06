# Copyright 2025-26 Beta ORI Inc. Canada. All Rights Reserved.
### Syed,Awase Khirni##

"""FastAPI application factory.

Wires middleware (auth + error envelope) and all route routers.
Configures structured logging at startup.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from src.api.middleware.auth import AuthMiddleware
from src.api.middleware.error_handler import ErrorEnvelopeMiddleware
from src.api.routes import alias, audit, health, ingest, toc
from src.config.settings import get_settings
from src.observability.logging import configure_logging, get_logger

logger = get_logger(__name__)


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = get_settings()

    # Configure logging before anything else.
    configure_logging(level=settings.log_level, fmt=settings.log_format)

    app = FastAPI(
        title="Adv-D-ToC-KB",
        version="0.1.0",
        description=(
            "A self-organising, LLM-orchestrated knowledge base. "
            "Ingests unstructured text, routes it into a depth-bounded tree, "
            "restructures overloaded nodes, audits for drift, and overlays "
            "aliases to form a navigable DAG."
        ),
    )

    # Order matters: error envelope wraps everything; auth runs on entry.
    # Middleware is applied in reverse order of addition, so add auth first
    # (it should be the outermost check).
    app.add_middleware(AuthMiddleware, settings=settings)
    app.add_middleware(ErrorEnvelopeMiddleware)

    app.include_router(health.router)
    app.include_router(ingest.router)
    app.include_router(toc.router)
    app.include_router(audit.router)
    app.include_router(alias.router)

    logger.info("FastAPI app created (version=0.1.0)")
    return app


app = create_app()
