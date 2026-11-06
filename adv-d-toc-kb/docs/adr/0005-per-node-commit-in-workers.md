# ADR-0005: Per-node commit in the audit sweep

Status: Accepted
Date: Phase 4
Deciders: Principal Architect

## Context

The audit sweep processes up to `audit_batch_size` nodes per tick. Two commit
strategies:

1. Batch commit: one transaction covers the whole sweep.
2. Per-node commit: one transaction per node.

## Decision

Per-node commit.

## Consequences

Positive:
- A single bad node cannot poison the other 99.
- Progress is visible in real-time via `audit_log`.
- Partial failures mean "some nodes audited," not "no nodes audited."

Negative:
- 100 round-trip commits per sweep vs. 1. At ~5ms per commit, this is 500ms
  overhead on a task that takes 30-90s.
- Interrupted sweeps leave the batch partially audited; the next sweep
  re-processes uncommitted nodes (correct behaviour).

## Alternatives Considered

1. Batch commit with savepoints per node -- rejected: complexity without
   the failure-isolation benefit.
2. Per-node commit with a covering transaction -- rejected: no way to have
   both "all-or-nothing" and "partial progress."
