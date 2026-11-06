# ADR-0002: Plain asyncio state machine over LangGraph

Status: Accepted
Date: Phase 2
Deciders: Principal Architect, user

## Context

The spec recommends LangGraph or AutoGen for LLM orchestration. Our
orchestration has three agents (router, restructurer, auditor) with tightly
scoped responsibilities and no multi-turn reasoning -- each is a single
LLM call within a well-typed flow.

## Decision

Implement orchestration as explicit Python state machines in `core/engine/`,
with LLM interactions hidden behind `Protocol` interfaces
(`EmbeddingProvider`, `BranchNamer`, `ClusterSummarizer`, `SubToCGenerator`,
`DriftVerifier`, `AliasDetector`).

## Consequences

Positive:
- Full unit testability -- every engine runs against fakes in milliseconds.
- No framework lock-in: swapping LangGraph in later is an internal change.
- Failure modes are inspectable Python stack traces.
- Zero additional dependency; smaller attack surface.

Negative:
- No graph visualisation for debugging (LangGraph provides this).
- If a future feature needs multi-turn agent loops, we'd hand-roll what
  LangGraph gives free.

## When to Revisit

If we add: (a) a "root cause analysis" agent that reasons over multiple
audit failures, (b) a multi-step alias reconciliation agent, or (c) a
routing agent that re-queries the tree several times.
