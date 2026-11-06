"""Seed script -- creates a root ToC node and prints its ID.

Run via::

    python -c "import asyncio; from src.scripts.seed import main; asyncio.run(main())"
"""

from __future__ import annotations

import asyncio
import sys

from src.db.models import ToCNode
from src.db.session import _init
from src.observability.logging import configure_logging, get_logger

logger = get_logger(__name__)


async def main() -> None:
    """Create a root node if none exists, and print its UUID."""
    configure_logging(level="INFO", fmt="text")
    factory = _init()
    async with factory() as session:
        async with session.begin():
            root = ToCNode(
                title="Knowledge Root",
                depth=0,
                semantic_summary="Root of the knowledge base",
            )
            session.add(root)
            await session.flush()
            print(root.id)
            logger.info("Seeded root node %s", root.id)


if __name__ == "__main__":
    asyncio.run(main())
    sys.exit(0)
