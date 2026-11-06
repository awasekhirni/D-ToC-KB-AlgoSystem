# ADR-0006: Postgres is the only source of truth

Status: Accepted
Date: Phase 2
Deciders: Principal Architect

## Context

We use Redis for Celery, and the console could use a caching layer. Where is
"the" tree?

## Decision

Postgres. Redis is a broker only -- no tree, no chunks, no audit log, no
session state. FastAPI holds no in-memory cache of tree data.

## Consequences

Positive:
- Kill any process -> restart -> state is intact.
- Horizontal scaling of API and workers is trivial.
- Transactions cover the full write path.
- Standard `pg_dump` covers everything.

Negative:
- Every read hits Postgres. The `/toc/{id}` recursive CTE handles 5k nodes
  in <30 ms -- acceptable, but not free.
- No session caching; login state must go through a token (we use a token).

## When to Reconsider

If tree reads exceed ~500 req/s per pod, add a read-through cache keyed by
`(root_id, updated_at_max)` -- but do not introduce a second write path.
