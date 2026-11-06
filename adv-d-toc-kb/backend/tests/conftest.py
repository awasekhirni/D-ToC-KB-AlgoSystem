"""Test configuration and shared fixtures.

Unit tests run against in-memory fakes (no DB, no network).
Integration tests use ``testcontainers`` to spin up a real
Postgres+pgvector instance (skipped if Docker is unavailable).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from src.config.settings import Settings
from src.observability.logging import configure_logging


@pytest.fixture(scope="session", autouse=True)
def _configure_logging() -> None:
    """Use text logging during tests for readability."""
    configure_logging(level="WARNING", fmt="text")


@pytest.fixture
def settings() -> Settings:
    """Default test settings (no DB connection required for unit tests)."""
    return Settings(
        database_url="postgresql+asyncpg://x:x@localhost/x",
        max_depth=5,
        similarity_threshold=0.65,
        max_alias_hops=3,
        embedding_dimensions=1536,
        max_tokens_per_node=50_000,
        max_variance_threshold=0.75,
        kmeans_max_clusters=7,
        audit_sample_size=10,
        alias_discovery_enabled=True,
        alias_similarity_threshold=0.80,
    )
