"""Integration test scaffold.

These tests require a real Postgres+pgvector instance via ``testcontainers``
and VCR-cassetted OpenAI calls. They are skipped by default in environments
without Docker. To run::

    pytest tests/integration -v
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skipif(
    True,  # set to False when Docker + testcontainers are available
    reason="Integration tests require Docker (testcontainers). Set "
    "INTEGRATION=1 to enable.",
)


@pytest.mark.asyncio
async def test_ingest_e2e_skeleton() -> None:
    """Skeleton: full ingest -> tree -> audit flow against real Postgres.

    To be implemented with testcontainers + VCR. See docs/architecture.md
    for the testing strategy.
    """
    # This test is a placeholder; full E2E lands when testcontainers is
    # wired into CI.
    pass
