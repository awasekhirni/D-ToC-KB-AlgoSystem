# ADR-0001: pgvector over in-memory embeddings

Status: Accepted
Date: Phase 1 (initial architecture)
Deciders: Principal Architect

## Context

The Adv-D-ToC-KB spec's pseudocode stores embeddings as parallel Python
lists on each `ToCNode`. This works for prototypes but does not survive a
restart, cannot be queried, and duplicates memory across workers.

## Decision

Store embeddings in a `content_chunks` table with a `vector(1536)` column
backed by the pgvector extension, with an IVFFlat cosine index.

## Consequences

Positive:
- Single source of truth: kill a worker, tree state survives.
- ANN search available for audit's cross-branch KNN.
- Centroid aggregation in one SQL round-trip.
- Transactions cover tree + embeddings + audit log together.

Negative:
- Requires the `vector` extension and a slightly larger Postgres image.
- Changing the embedding model requires a full re-index (dimension change).
- IVFFlat has recall trade-offs vs HNSW -- revisit if KNN quality degrades.

## Alternatives Considered

1. In-memory as spec suggests -- rejected: stateless API impossible.
2. External vector DB (Pinecone, Weaviate) -- rejected: distributed
   transaction complexity.
3. FAISS files on disk -- rejected: no transactional guarantees.
