"""Domain exception hierarchy.

Every domain error subclasses ``ToCKBError`` and carries a stable ``code``
that is surfaced in the API error envelope. The middleware translates these
into structured HTTP responses (see ``api/middleware/error_handler.py``).
"""

from uuid import UUID


class ToCKBError(Exception):
    """Base error. ``code`` is stable and surfaced in the API error envelope.

    All domain errors subclass this so that the error-envelope middleware
    can catch them in one place and translate to a structured 422 response.
    """

    code: str = "TOCKB_ERROR"


class BrokenAliasChain(ToCKBError):
    """Raised when an alias chain cannot be resolved (cycle, dangling, too long).

    The ``node_id`` identifies where resolution stopped; ``reason`` is a
    machine-readable string suitable for persisting in the audit log.
    """

    code = "BROKEN_ALIAS_CHAIN"

    def __init__(self, node_id: UUID, reason: str) -> None:
        self.node_id = node_id
        self.reason = reason
        super().__init__(f"Broken alias chain at {node_id}: {reason}")


class AliasConsistencyError(ToCKBError):
    """Raised when an alias node's state violates the consistency invariant.

    E.g. ``is_alias=True`` but ``points_to_id`` is None, or a non-alias
    node has ``points_to_id`` set.
    """

    code = "ALIAS_INCONSISTENCY"


class InvalidDepthError(ToCKBError):
    """Raised when a depth value is out of bounds or inconsistent."""

    code = "INVALID_DEPTH"


class MaxDepthExceededError(ToCKBError):
    """Raised when routing would exceed ``MAX_DEPTH`` and no strategy helps."""

    code = "MAX_DEPTH_EXCEEDED"
