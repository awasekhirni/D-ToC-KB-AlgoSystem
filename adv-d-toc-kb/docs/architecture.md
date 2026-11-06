# Architecture Walkthrough

This document explains *why* the system is shaped the way it is. For the
"what", see `README.md`. For point-in-time decisions, see `docs/adr/`.

---

## The Invariant Stack

Every read or write to the tree passes through four layers of guarantees,
ordered from cheapest to most expensive:

1. **Protocol contracts** (`core/protocols.py`) -- engines never depend on a
   concrete LLM. Test seams are designed in, not bolted on.
2. **Python invariants** (`core/invariants.py`) -- fail-fast with context
   before touching the DB. Property-tested.
3. **DB CHECK constraints** -- survive concurrent writes and raw SQL.
4. **`audit_log`** -- append-only record of every structural mutation.

If layers 2 and 3 ever disagree, that's a bug in the migration, and the
integration suite will catch it (constraints are asserted via raw SQL).

---

## Ingestion Data Flow

```
POST /ingest
    |
    +- validate body (Pydantic) --------> 422 on malformed input
    +- resolve root node                -> 404 if missing, 400 if alias
    |
    v
RoutingEngine.ingest(root, request)
    |
    +- embed content (OpenAI, once)
    +- checksum = sha256(content)      # idempotency key
    |
    +- loop:
    |    +- if current.is_alias -> AliasResolver.resolve
    |    +- children = repo.get_children(current)
    |    +- centroids = repo.centroids_for(children)   # 1 SQL round-trip
    |    +- best_child, score = cosine_sim vs centroids
    |    |
    |    +- if score < threshold -> create new branch, done
    |    +- if best_child.depth == MAX_DEPTH:
    |    |    +- pivot (once) -> RestructureEngine.pivot_paradigm
    |    |    |    +- if successful -> re-evaluate children
    |    |    |    +- if failed/disabled -> spillover
    |    |    +- spillover -> create sibling "X (Part 2)", done
    |    +- descend into best_child
    |
    +- dedup check (checksum at leaf)  # skip insert if duplicate
    +- insert ContentChunk
    +- log NODE_ROUTED
    +- fire-and-forget: restructure_node.delay(node_id)
```

**Termination proof**: the loop runs at most `2 * max_depth + 2` iterations.
Pivot has a per-call budget of 1. Once exhausted, the only option is
spillover, which terminates. If the loop exits without a break, we
`raise RuntimeError` rather than returning silently -- that indicates a
bug, and we want it loud.

---

## Restructuring Data Flow

```
Celery task: restructure_node(node_id)
    |
    v
RestructureEngine.maybe_restructure(node)
    |
    +- fetch chunks (may be empty -> skip)
    +- if len < 3 -> skip (nothing to cluster)
    |
    +- over_tokens  = sum(token_count) > MAX_TOKENS_PER_NODE
    +- over_variance = semantic_variance(embeddings) > MAX_VARIANCE_THRESHOLD
    +- if not (over_tokens or over_variance) -> skip
    |
    +- cluster_embeddings(embeddings, max_k)
    |    +- silhouette-based k selection (n>k+1)
    |    +- collapse to k=1 if all-identical or n too small
    |    +- deterministic seed (42)
    |
    +- for each cluster:
    |    +- ClusterSummarizer.summarize(chunks_in_cluster) -> 1 sentence
    |       (the ONLY thing the main LLM sees per cluster)
    |
    +- SubToCGenerator.generate(parent_title, paradigm, summaries)
    |    +- returns ProposedTopic[] (2-8 children)
    |
    +- create new children under node
    +- for each chunk: assign to nearest child by cosine(chunk.emb, child_summary_emb)
    +- bulk UPDATE content_chunks.node_id
    +- log SUMMARY_UPDATED (action=restructure)
```

**Context-window budget**: the restructure prompt receives K x ~200
tokens (K cluster summaries) plus a fixed instruction template (~300
tokens). With `K <= 7`, the ceiling is ~2k tokens regardless of how much
content the node holds. This is the whole point of RAG-clustering per the
spec.

---

## Pivot Data Flow (max-depth fallback)

Triggered synchronously by `RoutingEngine` when `best_child.depth ==
MAX_DEPTH` and `max_depth_strategy == pivot`.

```
RestructureEngine.pivot_paradigm(parent)
    |
    +- precondition: children exist, all at depth == parent.depth+1
    +- precondition: no alias points into any child
    |    +- if any -> log PARADIGM_PIVOT{skipped} and return False
    |
    +- collect all chunks across children
    +- if total chunks < 2 -> return False (can't meaningfully re-cluster)
    |
    +- K-Means -> summaries -> sub-ToC (under new paradigm)
    +- create new children
    +- move chunks (cosine to child summary)
    +- delete old children (now empty)
    +- update parent.categorization_paradigm
    +- log PARADIGM_PIVOT{success, from, to, new_children, removed_children}
    +- return True
```

Failure modes are all safe:

- Alias referrer -> abort, routing falls back to spillover.
- Clustering produces 1 cluster -> abort, spillover.
- LLM timeout -> exception caught, logged, spillover.
- Chunk move fails -> transaction rolls back, spillover.

In every case, the tree stays consistent and forward progress is made.

---

## Audit Flow

```
Celery beat (03:00 UTC) -> sweep_due_nodes()
    |
    +- due = repo.due_for_audit(interval_days, limit=BATCH_SIZE)
    |    +- includes: last_audit_timestamp IS NULL (flagged) OR older than N days
    |    +- NULLS FIRST (flagged nodes go first)
    |
    +- for each node in due:
    |    +- AuditEngine.audit_node(node)
    |    |    +- if is_alias -> _repair_alias:
    |    |    |    +- try AliasResolver.resolve
    |    |    |    +- if BrokenAliasChain -> delete + log, mark audited
    |    |    |    +- else -> mark audited
    |    |    +- sample = random(chunks, SAMPLE_SIZE)
    |    |    +- _audit_summary:
    |    |    |    +- DriftVerifier.verify(current_summary, samples)
    |    |    |    +- if not accurate and updated_summary -> rewrite + log DRIFT_CORRECTED
    |    |    |    +- else no-op
    |    |    +- _discover_alias:
    |    |    |    +- subtree_ids = repo.get_subtree_ids(node)
    |    |    |    +- for each chunk in sample:
    |    |    |    |    +- candidates = chunk_repo.knn_excluding_subtree(...)
    |    |    |    |    +- for candidate with sim >= threshold:
    |    |    |    |    |    +- AliasDetector.should_alias(...)
    |    |    |    |    |    +- if yes -> AliasCreationEngine.create(...) -> done
    |    +- session.commit()   # per-node commit (ADR-0005)
    |    +- append to results
    +- return sweep summary
```

**Idempotency**: committed nodes have a fresh timestamp and won't re-enter
the queue until stale. Uncommitted nodes re-enter -- that's correct, they
weren't audited.

---

## Alias Overlay

Aliases are physical tree nodes with `is_alias=true` and a
`points_to_id`. They participate in traversal (routing resolves them via
`AliasResolver`) but hold no chunks of their own.

**Invariants at creation** (enforced in `AliasCreationEngine`):

1. `target_parent` exists and is not an alias.
2. `primary` exists and is not an alias.
3. `primary` is not an ancestor of `target_parent` (prevents tree cycles).
4. `target_parent.depth < MAX_DEPTH` (room for a new child).
5. `primary.id != target_parent.id` (no self-reference).

**Why only ancestor check?** Any alias that would close a physical tree
cycle must point to an ancestor of its target parent -- we reject that.
Multi-branch nested cycles are theoretically possible but require
multiple coordinated aliases; the routing loop's bounded iteration count
prevents hangs.

**Broken chains**: if an alias points to a node that no longer exists, or a
cycle is detected, `AliasResolver` raises `BrokenAliasChain` with a reason.
Callers `flag_for_audit(node_id)` -- setting `last_audit_timestamp = NULL`
guarantees the next sweep picks it up first. The repair routine deletes the
broken alias; if the association was legitimate, KNN discovery will re-create
it under a healthier parent.

---

## Failure Modes and Their Blast Radius

| Failure | Effect | Recovery |
|---|---|---|
| OpenAI 5xx | Ingest fails, worker retries 3x | Automatic with backoff |
| OpenAI timeout | Same as 5xx | Automatic |
| Postgres down | All writes fail, `/toc` also fails | Standard HA |
| Redis down | Ingest works, workers stop | Restart Redis; tasks resume |
| Broken alias on path | `BrokenAliasChain` -> `flag_for_audit` -> next sweep deletes | Automatic |
| Broken alias on non-path | Logged during scoring, skipped | Automatic |
| LLM returns malformed JSON | `ValueError` in `chat_json` | Retry via worker; safe to fail |
| Cluster all-same embeddings | `k=1` -> restructure skips | Correct -- nothing to split |
| LLM returns 0 topics | `ValueError` in `SubToCGenerator` | Restructure aborts, keeps node |
| DB constraint violation | 500 with error envelope; no data written | Bug in Python invariants; add test |

---

## Why These Technology Choices

- **Postgres over a graph DB.** The tree is a tree -- the alias overlay is a
  DAG but small enough that recursive CTEs handle it in one round-trip.
- **pgvector over Pinecone/Weaviate.** Embeddings are 1:1 with
  `content_chunks`; the join back to the tree is the primary access pattern.
- **Celery over FastAPI BackgroundTasks.** Restructure and audit are long-
  running and need retries with backoff.
- **`asyncio` over LangGraph.** Our state machine has ~6 states and one
  shared session per request.

---

## Testing Strategy

Three tiers, each with a specific scope:

1. **Unit** (`tests/unit/`) -- pure logic against fakes. No DB, no network.
   Target: <5 s total.
2. **Integration** (`tests/integration/`) -- real Postgres via
   `testcontainers`, real Alembic migrations, VCR-cassetted OpenAI calls.
   Target: <60 s.
3. **E2E** (deferred) -- full docker-compose up, browser console, multi-ingest
   session.

What we do *not* test with mocks: the SQL itself. The integration tier
exists specifically because the ORM can lie about what constraint fired.

---

## Logging & Observability

The system emits structured JSON logs by default. Every function logs:

- **Entry/exit** at DEBUG with function name and key parameters.
- **Errors** at ERROR with full context (request_id, node_id, etc.).
- **Audit events** at INFO (also persisted to `audit_log`).

The metrics module (`src/observability/metrics.py`) exposes counters for
every domain event: ingest requests, duplicates, branches created,
spillovers, pivots, restructure runs, audit drift corrections, aliases
created, broken aliases, LLM calls, and LLM errors.
