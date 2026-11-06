"""Vector similarity helpers.

All functions are pure and side-effect free, making them trivially testable.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Compute cosine similarity between two vectors.

    Returns a value in ``[-1.0, 1.0]``. Returns ``0.0`` for zero-norm
    vectors (avoids division-by-zero).

    Args:
        a: First vector (sequence of floats).
        b: Second vector (same length as ``a``).

    Returns:
        Cosine similarity in ``[-1, 1]``.

    Raises:
        ValueError: If the vectors have different shapes.
    """
    va = np.asarray(a, dtype=np.float64)
    vb = np.asarray(b, dtype=np.float64)
    if va.shape != vb.shape:
        raise ValueError(f"Vector shape mismatch: {va.shape} vs {vb.shape}")
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    if denom == 0.0:
        return 0.0
    return float(np.clip(float(np.dot(va, vb)) / denom, -1.0, 1.0))


def euclidean_distance(a: Sequence[float], b: Sequence[float]) -> float:
    """Compute Euclidean (L2) distance between two vectors.

    Args:
        a: First vector.
        b: Second vector (same length).

    Returns:
        Non-negative distance.

    Raises:
        ValueError: If shapes differ.
    """
    va = np.asarray(a, dtype=np.float64)
    vb = np.asarray(b, dtype=np.float64)
    if va.shape != vb.shape:
        raise ValueError(f"Vector shape mismatch: {va.shape} vs {vb.shape}")
    return float(np.linalg.norm(va - vb))
