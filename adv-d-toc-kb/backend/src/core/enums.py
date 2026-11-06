"""Domain enumerations used throughout the system."""

from enum import StrEnum


class Paradigm(StrEnum):
    """Categorization paradigm for a tree node.

    The paradigm controls how children are organised when a node is
    restructured. The ``next_paradigm`` cycle is used by the pivot
    strategy (see ``RoutingEngine``).
    """

    THEMATIC = "Thematic"
    CHRONOLOGICAL = "Chronological"
    GEOGRAPHICAL = "Geographical"
    PROCEDURAL = "Procedural"

    def next_paradigm(self) -> "Paradigm":
        """Return the next paradigm in the deterministic pivot cycle.

        The cycle is: Thematic -> Chronological -> Geographical ->
        Procedural -> Thematic.
        """
        order = (
            Paradigm.THEMATIC,
            Paradigm.CHRONOLOGICAL,
            Paradigm.GEOGRAPHICAL,
            Paradigm.PROCEDURAL,
        )
        idx = order.index(self)
        return order[(idx + 1) % len(order)]


class MaxDepthStrategy(StrEnum):
    """How to handle content that routes to a node at ``MAX_DEPTH``.

    - ``SPILLOVER``: create a sibling "Part 2" node (cheap, always works).
    - ``PIVOT``: regenerate the parent's children under a new paradigm
      (expensive, fires at most once per ingest path then falls back to
      spillover).
    """

    SPILLOVER = "spillover"
    PIVOT = "pivot"


class AuditEventType(StrEnum):
    """Event types recorded in the append-only ``audit_log`` table.

    Every structural mutation (route, split, alias, summary rewrite, drift
    correction) writes one of these.
    """

    NODE_CREATED = "NODE_CREATED"
    NODE_ROUTED = "NODE_ROUTED"
    SPILLOVER_CREATED = "SPILLOVER_CREATED"
    PARADIGM_PIVOT = "PARADIGM_PIVOT"
    ALIAS_CREATED = "ALIAS_CREATED"
    BROKEN_ALIAS_CHAIN = "BROKEN_ALIAS_CHAIN"
    SUMMARY_UPDATED = "SUMMARY_UPDATED"
    DRIFT_CORRECTED = "DRIFT_CORRECTED"
