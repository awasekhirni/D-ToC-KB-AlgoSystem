"""Prometheus-style metrics counters.

This is a minimal in-process metrics module. For production, replace the
backing store with ``prometheus_client`` and expose ``/metrics`` via a
FastAPI route. The interface here is intentionally compatible.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import DefaultDict


class _Counter:
    """Thread-safe monotonic counter."""

    def __init__(self, name: str, help_text: str = "") -> None:
        self.name = name
        self.help_text = help_text
        self._value = 0
        self._lock = threading.Lock()
        self._labels: DefaultDict[tuple, int] = defaultdict(int)

    def inc(self, amount: int = 1, **labels: str) -> None:
        """Increment by ``amount``, optionally with label values."""
        with self._lock:
            self._value += amount
            if labels:
                key = tuple(sorted(labels.items()))
                self._labels[key] += amount

    @property
    def value(self) -> int:
        return self._value

    def snapshot(self) -> dict:
        """Return a dict snapshot suitable for logging or /metrics."""
        with self._lock:
            return {
                "name": self.name,
                "help": self.help_text,
                "total": self._value,
                "by_label": {
                    ",".join(f"{k}={v}" for k, v in label_tuple): count
                    for label_tuple, count in self._labels.items()
                },
            }


# Global registry of counters.
_counters: dict[str, _Counter] = {}
_registry_lock = threading.Lock()


def counter(name: str, help_text: str = "") -> _Counter:
    """Get or create a named counter."""
    with _registry_lock:
        if name not in _counters:
            _counters[name] = _Counter(name, help_text)
        return _counters[name]


# Pre-registered domain metrics.
INGEST_REQUESTS = counter("tockb_ingest_requests_total", "Ingest API calls")
INGEST_DUPLICATES = counter("tockb_ingest_duplicates_total", "Idempotent duplicate ingests")
ROUTING_BRANCHES_CREATED = counter(
    "tockb_routing_branches_created_total", "New child branches created by routing"
)
ROUTING_SPILLOVERS = counter(
    "tockb_routing_spillovers_total", "Spillover siblings created"
)
ROUTING_PIVOTS = counter("tockb_routing_pivots_total", "Paradigm pivots triggered")
RESTRUCTURE_RUNS = counter(
    "tockb_restructure_runs_total", "Restructure engine invocations"
)
RESTRUCTURE_PERFORMED = counter(
    "tockb_restructure_performed_total", "Restructure engine actually restructured a node"
)
AUDIT_RUNS = counter("tockb_audit_runs_total", "Audit node invocations")
AUDIT_DRIFT_CORRECTED = counter(
    "tockb_audit_drift_corrected_total", "Summaries rewritten by audit"
)
AUDIT_ALIASES_CREATED = counter(
    "tockb_audit_aliases_created_total", "Aliases discovered and created by audit"
)
AUDIT_BROKEN_ALIASES = counter(
    "tockb_audit_broken_aliases_total", "Broken alias chains detected"
)
BROKEN_ALIAS_CHAIN_ERRORS = counter(
    "tockb_broken_alias_chain_errors_total",
    "BrokenAliasChain exceptions raised",
)
LLM_CALLS = counter("tockb_llm_calls_total", "Outbound LLM API calls")
LLM_ERRORS = counter("tockb_llm_errors_total", "LLM API call failures")


def snapshot_all() -> dict:
    """Return a snapshot of all registered counters (for /metrics or logs)."""
    with _registry_lock:
        return {name: c.snapshot() for name, c in _counters.items()}
