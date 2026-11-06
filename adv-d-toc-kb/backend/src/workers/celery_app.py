"""Celery application + beat schedule.

The beat schedule drives the nightly audit sweep. Restructure tasks are
enqueued on-demand by the ingest route.
"""

from __future__ import annotations

import logging

from celery import Celery
from celery.schedules import crontab

from src.config.settings import get_settings
from src.observability.logging import configure_logging, get_logger

settings = get_settings()

# Configure logging for the worker process.
configure_logging(level=settings.log_level, fmt=settings.log_format)

logger = get_logger(__name__)

celery_app = Celery(
    "tockb",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "nightly-audit-sweep": {
            "task": "workers.audit_worker.sweep_due_nodes",
            "schedule": crontab(hour=3, minute=0),
        },
    },
)

logger.info("Celery app configured broker=%s", settings.redis_url)
