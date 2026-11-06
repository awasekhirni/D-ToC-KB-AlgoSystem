# ADR-0004: Spillover + pivot dual max-depth strategies

Status: Accepted
Date: Phase 2 (design), Phase 3 (pivot implemented)
Deciders: Principal Architect, user

## Context

The spec calls for handling infinite recursion at max depth with two
options: a "sibling spillover" node ("Topic Part 2") or a "paradigm pivot"
(regenerate children under a different categorization). The spec does not
choose between them.

## Decision

Implement both, selectable via `TOCKB_MAX_DEPTH_STRATEGY`. When
`pivot` is enabled, it fires at most once per routing path, then falls
back to spillover if the pivot doesn't help.

## Consequences

Positive:
- Spillover is cheap, deterministic, and always available.
- Pivot preserves semantic precision when it works.
- Termination is guaranteed: pivot budget = 1, spillover is a single node
  creation, loop is bounded by `2 * max_depth + 2`.

Negative:
- Spillover degrades precision at scale ("Part 2" siblings compete).
- Pivot is expensive (K-Means + K summaries + 1 sub-ToC call) and only fires
  once.
- Requires the caller (routing loop) to coordinate two engines.

## When to Prefer Which

- Small/medium trees (<1000 nodes): spillover is fine.
- Deep, content-heavy trees: enable pivot. Semantic drift from spillover
  compounds as the tree deepens.
