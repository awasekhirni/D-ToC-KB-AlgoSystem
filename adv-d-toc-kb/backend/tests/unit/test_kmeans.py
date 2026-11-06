"""Tests for K-Means clustering + semantic variance."""

from __future__ import annotations

import numpy as np
import pytest

from src.core.clustering.kmeans import cluster_embeddings, semantic_variance


def _cluster_of(
    n: int, center: float, noise: float = 0.01
) -> list[list[float]]:
    """Generate ``n`` 8-dim vectors near ``center``."""
    rng = np.random.default_rng(0)
    return [
        [center + rng.uniform(-noise, noise) for _ in range(8)]
        for _ in range(n)
    ]


def test_empty_raises() -> None:
    """Empty input raises ValueError."""
    with pytest.raises(ValueError):
        cluster_embeddings([], max_k=5)


def test_single_item_degenerate() -> None:
    """A single embedding collapses to one cluster."""
    result = cluster_embeddings([[1.0] * 8], max_k=5)
    assert result.k == 1
    assert result.labels == [0]
    assert result.silhouette is None


def test_all_identical_collapses() -> None:
    """All-identical vectors collapse to one cluster."""
    embeddings = [[0.3] * 8 for _ in range(10)]
    result = cluster_embeddings(embeddings, max_k=5)
    assert result.k == 1
    assert len(result.clusters) == 1


def test_two_clear_clusters() -> None:
    """Two well-separated clusters are detected."""
    a = _cluster_of(10, center=0.0)
    b = _cluster_of(10, center=1.0, noise=0.005)
    result = cluster_embeddings(a + b, max_k=5)
    assert result.k >= 2
    assert result.silhouette is not None
    assert result.silhouette > 0.5  # well-separated


def test_fewer_samples_than_max_k() -> None:
    """When n < max_k, the effective k is clamped."""
    embeddings = _cluster_of(3, center=0.5)
    result = cluster_embeddings(embeddings, max_k=10)
    assert 1 <= result.k <= 3


def test_semantic_variance_cohesive() -> None:
    """Identical vectors have zero variance."""
    cohesive = [[1.0, 0.0]] * 5
    assert semantic_variance(cohesive) == pytest.approx(0.0, abs=1e-6)


def test_semantic_variance_spread() -> None:
    """Opposite vectors have high variance."""
    spread = [[1.0, 0.0], [-1.0, 0.0]]
    v = semantic_variance(spread)
    assert v > 1.0  # near max for opposite vectors


def test_semantic_variance_single_item() -> None:
    """A single item has zero variance by definition."""
    assert semantic_variance([[1.0, 2.0]]) == 0.0
