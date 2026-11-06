"""Deterministic K-Means wrapper with explicit edge-case handling.

The spec's ``check_and_restructure`` depends on finding natural groupings.
We take pains to make degenerate inputs (all-same vectors, fewer samples
than clusters) deterministic and correct rather than relying on sklearn's
defaults.

Key design choices:
- Deterministic seed (42) for reproducibility.
- Silhouette-based k selection when ``n > k+1``; otherwise fixed ``k=2``.
- Single-cluster collapse when all vectors are identical or n is too small.
- ``semantic_variance`` for the restructure threshold check.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

from src.observability.logging import get_logger

logger = get_logger(__name__)

_RANDOM_STATE = 42


@dataclass(frozen=True)
class Cluster:
    """A single K-Means cluster: member indices + centroid."""

    indices: list[int]
    centroid: list[float]


@dataclass(frozen=True)
class ClusterResult:
    """The outcome of a clustering run.

    Attributes:
        k: Number of clusters found (may be 1 for degenerate inputs).
        labels: Cluster label per input vector.
        clusters: One ``Cluster`` per label (in label order).
        silhouette: Silhouette score, or None when ``k == 1`` or
            degenerate input.
    """

    k: int
    labels: list[int]
    clusters: list[Cluster]
    silhouette: float | None


def cluster_embeddings(
    embeddings: list[list[float]],
    *,
    max_k: int,
    min_k: int = 2,
) -> ClusterResult:
    """Cluster ``embeddings``, picking ``k`` from silhouette when feasible.

    Args:
        embeddings: List of embedding vectors (all same dimension).
        max_k: Maximum number of clusters to consider.
        min_k: Minimum k to consider (default 2).

    Returns:
        ``ClusterResult`` with labels, clusters, and silhouette score.

    Raises:
        ValueError: If ``embeddings`` is empty.
    """
    n = len(embeddings)
    if n == 0:
        raise ValueError("No embeddings to cluster")

    if n == 1:
        logger.debug("Single embedding -> degenerate single cluster")
        return ClusterResult(
            k=1,
            labels=[0],
            clusters=[Cluster(indices=[0], centroid=list(embeddings[0]))],
            silhouette=None,
        )

    arr = np.asarray(embeddings, dtype=np.float64)
    if arr.ndim != 2:
        raise ValueError(f"Expected 2-D embeddings, got shape {arr.shape}")

    if np.allclose(arr, arr[0]):
        # All identical -> single cluster is the only honest answer.
        logger.debug("All embeddings identical -> single cluster")
        return ClusterResult(
            k=1,
            labels=[0] * n,
            clusters=[
                Cluster(indices=list(range(n)), centroid=arr[0].tolist())
            ],
            silhouette=None,
        )

    effective_min = max(2, min_k)
    effective_max = min(max_k, n)
    if effective_max < effective_min:
        # Can't make a meaningful split -- collapse.
        return ClusterResult(
            k=1,
            labels=[0] * n,
            clusters=[
                Cluster(indices=list(range(n)), centroid=arr.mean(0).tolist())
            ],
            silhouette=None,
        )

    # Silhouette-based k selection needs n > k+1; when too small, just k=2.
    if n <= effective_min + 1:
        best_k = effective_min
        best_labels = _fit(arr, best_k)
        best_sil = None
    else:
        best_k, best_labels, best_sil = _pick_k(arr, effective_min, effective_max)

    clusters = _build_clusters(arr, best_labels, best_k)
    logger.info(
        "Clustered %d embeddings into k=%d (silhouette=%s)",
        n, best_k,
        f"{best_sil:.3f}" if best_sil is not None else "n/a",
    )
    return ClusterResult(
        k=best_k,
        labels=best_labels.tolist(),
        clusters=clusters,
        silhouette=best_sil,
    )


def _fit(arr: np.ndarray, k: int) -> np.ndarray:
    """Fit K-Means with the deterministic seed."""
    model = KMeans(n_clusters=k, random_state=_RANDOM_STATE, n_init=10)
    return model.fit_predict(arr)


def _pick_k(
    arr: np.ndarray, lo: int, hi: int
) -> tuple[int, np.ndarray, float]:
    """Try each k in ``[lo, hi]`` and pick the one with the best silhouette."""
    best_k, best_labels, best_score = lo, None, -1.0
    for k in range(lo, hi + 1):
        labels = _fit(arr, k)
        if len(set(labels.tolist())) < 2:
            continue
        score = float(silhouette_score(arr, labels, metric="cosine"))
        if score > best_score:
            best_k, best_labels, best_score = k, labels, score
    if best_labels is None:
        # Couldn't find a valid split -- collapse to single cluster.
        labels = np.zeros(len(arr), dtype=int)
        return 1, labels, -1.0
    return best_k, best_labels, best_score


def _build_clusters(
    arr: np.ndarray, labels: np.ndarray, k: int
) -> list[Cluster]:
    """Build ``Cluster`` objects from labels."""
    out: list[Cluster] = []
    for label in range(k):
        idx = np.where(labels == label)[0].tolist()
        if not idx:
            continue
        centroid = arr[idx].mean(axis=0).tolist()
        out.append(Cluster(indices=idx, centroid=centroid))
    return out


def semantic_variance(embeddings: list[list[float]]) -> float:
    """Mean cosine distance from the centroid.

    Returns a value in ``[0, 2]`` where 0 means perfectly cohesive (all
    vectors identical) and 2 means maximally spread (opposite directions).

    Used by ``RestructureEngine`` as a restructure trigger: when variance
    exceeds ``max_variance_threshold``, the node is overloaded and should
    be split.
    """
    n = len(embeddings)
    if n < 2:
        return 0.0
    arr = np.asarray(embeddings, dtype=np.float64)
    centroid = arr.mean(axis=0)
    denom = np.linalg.norm(arr, axis=1) * np.linalg.norm(centroid)
    denom = np.where(denom == 0, 1.0, denom)
    cos = (arr @ centroid) / denom
    return float(np.clip(np.mean(1.0 - cos), 0.0, 2.0))
