"""Async restructure job -- invoked after each ingest.

Kept deliberately narrow: fetch node, delegate to ``RestructureEngine``,
log. The engine owns all business logic; the worker is a thin adapter.
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from src.config.settings import get_settings
from src.core.engine.restructure import RestructureEngine
from src.core.llm.client import build_client
from src.core.llm.cluster_summarizer import ClusterSummarizer
from src.core.llm.openai_embedder import OpenAIEmbedder
from src.core.llm.sub_toc_generator import SubToCGenerator
from src.db.repositories import (
    AuditRepository,
    ContentChunkRepository,
    ToCNodeRepository,
)
from src.db.session import _init
from src.observability.logging import get_logger
from src.workers.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(
    name="workers.restructure_worker.restructure_node",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def restructure_node(self, node_id: str) -> dict:
    """Celery task: restructure node ``node_id`` if it's overloaded.

    Retries up to 3 times with 30s delay on failure.
    """
    try:
        return asyncio.run(_restructure_async(UUID(node_id)))
    except Exception as exc:
        logger.exception("Restructure failed for %s", node_id)
        raise self.retry(exc=exc)


async def _restructure_async(node_id: UUID) -> dict:
    """Run the restructure check against a real DB session."""
    settings = get_settings()
    factory = _init()
    client = build_client(settings)
    try:
        async with factory() as session:
            async with session.begin():
                node_repo = ToCNodeRepository(session)
                node = await node_repo.get(node_id)
                if node is None:
                    logger.warning("Restructure target %s not found", node_id)
                    return {"status": "not_found"}

                engine = RestructureEngine(
                    session=session,
                    settings=settings,
                    node_repo=node_repo,
                    chunk_repo=ContentChunkRepository(session),
                    audit_repo=AuditRepository(session),
                    summarizer=ClusterSummarizer(client, settings),
                    sub_toc_generator=SubToCGenerator(client, settings),
                    embedder=OpenAIEmbedder(client, settings),
                )
                outcome = await engine.maybe_restructure(node)
            return {
                "status": "ok" if outcome.performed else "skipped",
                "reason": outcome.reason,
                "new_children": [str(c) for c in outcome.new_child_ids],
            }
    finally:
        await client.aclose()
