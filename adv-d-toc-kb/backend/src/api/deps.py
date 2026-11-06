# Copyright 2025-26 Beta ORI Inc. Canada. All Rights Reserved.
### Syed,Awase Khirni##
"""FastAPI dependency injection wiring.

Each ``provide_*`` function is a FastAPI dependency. Providers that
hold process-level state (like the OpenAI client) cache it at module
level so each Uvicorn worker reuses one client.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import Settings, get_settings
from src.core.engine.alias import AliasResolver
from src.core.engine.alias_creator import AliasCreationEngine
from src.core.engine.audit import AuditEngine
from src.core.engine.restructure import RestructureEngine
from src.core.engine.routing import RoutingEngine
from src.core.llm.alias_detector import AliasDetector
from src.core.llm.client import OpenAIClient, build_client
from src.core.llm.cluster_summarizer import ClusterSummarizer
from src.core.llm.drift_verifier import DriftVerifier
from src.core.llm.openai_embedder import OpenAIEmbedder
from src.core.llm.openai_namer import OpenAINamer
from src.core.llm.sub_toc_generator import SubToCGenerator
from src.db.repositories import (
    AuditRepository,
    ContentChunkRepository,
    ToCNodeRepository,
)
from src.db.session import get_session
from src.observability.logging import get_logger

logger = get_logger(__name__)


def provide_settings() -> Settings:
    """Return cached application settings."""
    return get_settings()


_openai_client: OpenAIClient | None = None


def provide_llm_client(
    settings: Settings = Depends(provide_settings),
) -> OpenAIClient:
    """Singleton -- one pooled HTTP client per process."""
    global _openai_client
    if _openai_client is None:
        _openai_client = build_client(settings)
        logger.info("Initialised OpenAI client singleton")
    return _openai_client


def provide_embedder(
    client: OpenAIClient = Depends(provide_llm_client),
    settings: Settings = Depends(provide_settings),
) -> OpenAIEmbedder:
    """Provide the ``EmbeddingProvider`` implementation."""
    return OpenAIEmbedder(client, settings)


def provide_namer(
    client: OpenAIClient = Depends(provide_llm_client),
    settings: Settings = Depends(provide_settings),
) -> OpenAINamer:
    """Provide the ``BranchNamer`` implementation."""
    return OpenAINamer(client, settings)


async def provide_restructure(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(provide_settings),
    client: OpenAIClient = Depends(provide_llm_client),
    embedder: OpenAIEmbedder = Depends(provide_embedder),
) -> RestructureEngine:
    """Provide the ``RestructureEngine``."""
    node_repo = ToCNodeRepository(session)
    return RestructureEngine(
        session=session,
        settings=settings,
        node_repo=node_repo,
        chunk_repo=ContentChunkRepository(session),
        audit_repo=AuditRepository(session),
        summarizer=ClusterSummarizer(client, settings),
        sub_toc_generator=SubToCGenerator(client, settings),
        embedder=embedder,
    )


async def provide_audit_engine(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(provide_settings),
    client: OpenAIClient = Depends(provide_llm_client),
) -> AuditEngine:
    """Provide the ``AuditEngine``."""
    node_repo = ToCNodeRepository(session)
    audit_repo = AuditRepository(session)
    return AuditEngine(
        session=session,
        settings=settings,
        node_repo=node_repo,
        chunk_repo=ContentChunkRepository(session),
        audit_repo=audit_repo,
        drift_verifier=DriftVerifier(client, settings),
        alias_detector=AliasDetector(client, settings),
        alias_creator=AliasCreationEngine(
            session=session,
            settings=settings,
            node_repo=node_repo,
            audit_repo=audit_repo,
        ),
        alias_resolver=AliasResolver(node_repo, settings.max_alias_hops),
    )


async def provide_engine(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(provide_settings),
    embedder: OpenAIEmbedder = Depends(provide_embedder),
    namer: OpenAINamer = Depends(provide_namer),
    restructure: RestructureEngine = Depends(provide_restructure),
) -> AsyncIterator[RoutingEngine]:
    """Provide the ``RoutingEngine`` (yields because it doesn't own resources)."""
    node_repo = ToCNodeRepository(session)
    yield RoutingEngine(
        settings=settings,
        embedder=embedder,
        namer=namer,
        node_repo=node_repo,
        chunk_repo=ContentChunkRepository(session),
        audit_repo=AuditRepository(session),
        alias_resolver=AliasResolver(node_repo, settings.max_alias_hops),
        restructure=restructure,
    )
