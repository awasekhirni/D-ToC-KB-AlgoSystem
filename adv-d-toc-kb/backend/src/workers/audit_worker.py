"""Scheduled audit sweep + single-node audit tasks.

The sweep processes ``audit_batch_size`` due nodes per tick, committing
per-node so partial progress survives (ADR-0005). All errors are logged
and rolled into the task result for observability.
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from src.config.settings import get_settings
from src.core.engine.alias import AliasResolver
from src.core.engine.alias_creator import AliasCreationEngine
from src.core.engine.audit import AuditEngine, AuditOutcome
from src.core.llm.alias_detector import AliasDetector
from src.core.llm.client import build_client
from src.core.llm.drift_verifier import DriftVerifier
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
    name="workers.audit_worker.sweep_due_nodes",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
)
def sweep_due_nodes(self, batch_size: int | None = None) -> dict:
    """Celery task: audit all due nodes (up to ``batch_size``).

    Retries up to 2 times with 60s delay on failure.
    """
    try:
        return asyncio.run(_sweep_async(batch_size))
    except Exception as exc:
        logger.exception("Audit sweep failed")
        raise self.retry(exc=exc)


@celery_app.task(
    name="workers.audit_worker.audit_single_node",
    bind=True,
    max_retries=3,
    default_retry_delay=15,
)
def audit_single_node(self, node_id: str) -> dict:
    """Celery task: audit a single node by ID."""
    try:
        return asyncio.run(_audit_single_async(UUID(node_id)))
    except Exception as exc:
        logger.exception("Single audit failed for %s", node_id)
        raise self.retry(exc=exc)


async def _sweep_async(batch_size: int | None) -> dict:
    """Run the audit sweep against due nodes."""
    settings = get_settings()
    limit = batch_size or settings.audit_batch_size
    factory = _init()
    client = build_client(settings)
    results: list[dict] = []
    try:
        async with factory() as session:
            node_repo = ToCNodeRepository(session)
            due = await node_repo.due_for_audit(
                interval_days=settings.audit_interval_days, limit=limit
            )
            if not due:
                logger.info("Audit sweep: no due nodes")
                return {
                    "total": 0,
                    "processed": 0,
                    "errors": 0,
                    "results": [],
                }

            logger.info("Audit sweep: %d due nodes", len(due))
            engine = _build_engine(session, settings, client)
            for node in due:
                try:
                    outcome = await engine.audit_node(node)
                    await session.commit()
                    results.append(_to_dict(outcome))
                except Exception:
                    logger.exception("Audit failed for %s", node.id)
                    await session.rollback()
                    results.append(
                        {
                            "node_id": str(node.id),
                            "status": "error",
                            "reason": "exception",
                        }
                    )
        return {
            "total": len(due),
            "processed": sum(1 for r in results if r["status"] == "ok"),
            "errors": sum(1 for r in results if r["status"] == "error"),
            "results": results,
        }
    finally:
        await client.aclose()


async def _audit_single_async(node_id: UUID) -> dict:
    """Audit one node by ID."""
    settings = get_settings()
    factory = _init()
    client = build_client(settings)
    try:
        async with factory() as session:
            node_repo = ToCNodeRepository(session)
            node = await node_repo.get(node_id)
            if node is None:
                logger.warning("Audit target %s not found", node_id)
                return {"status": "not_found", "node_id": str(node_id)}
            engine = _build_engine(session, settings, client)
            outcome = await engine.audit_node(node)
            await session.commit()
            return _to_dict(outcome)
    finally:
        await client.aclose()


def _build_engine(session, settings, client) -> AuditEngine:
    """Construct an ``AuditEngine`` with all collaborators wired."""
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


def _to_dict(o: AuditOutcome) -> dict:
    """Serialise an ``AuditOutcome`` to a JSON-safe dict."""
    return {
        "node_id": str(o.node_id),
        "status": o.status,
        "reason": o.reason,
        "summary_updated": o.summary_updated,
        "alias_created": o.alias_created,
    }
