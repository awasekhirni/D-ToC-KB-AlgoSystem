# ADR-0003: Alias DAG overlay via is_alias + points_to_id

Status: Accepted
Date: Phase 2
Deciders: Principal Architect

## Context

Content sometimes belongs under multiple branches. A rigid tree forces one
location. The spec addresses this with alias nodes.

## Decision

Aliases are physical tree nodes with `is_alias=true` and `points_to_id`
pointing to the primary data node. They participate in traversal but hold no
chunks. Creation is via `AliasCreationEngine`, which enforces 5 invariants.

## Consequences

Positive:
- Two logical paths to the same data, no duplication.
- Traversal stays simple: `if node.is_alias: node = resolver.resolve(node)`.
- DB CHECK constraint enforces consistency.

Negative:
- Two representations of "found here" (physical child vs. alias pointer).
- Multi-hop alias chains are possible but bounded (`max_alias_hops=3`).
- Broken aliases (target deleted, cycle) require repair; automated via audit.

## Alternatives Considered

1. Multi-parent tree -- rejected: breaks `parent_id` FK.
2. Tag-based cross-referencing -- rejected: tags are flat, aliases are structural.
3. Read-only DAG view with separate write path -- rejected: consistency nightmare.
