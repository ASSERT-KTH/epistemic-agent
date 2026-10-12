"""Small statistics helpers for the experiment analyses (standard library only)."""
from __future__ import annotations

from collections import Counter
from math import sqrt


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a proportion k/n (95% by default).
    Returns (0, 0) when n == 0."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, (centre - half) / denom), min(1.0, (centre + half) / denom))


def cohen_kappa(a: list[str], b: list[str]) -> float | None:
    """Cohen's kappa between two raters' labels on the same items, over all
    categories that appear. None when undefined (no items, or chance
    agreement is 1)."""
    if len(a) != len(b):
        raise ValueError("raters labelled a different number of items")
    n = len(a)
    if n == 0:
        return None
    observed = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[c] * cb[c] for c in set(ca) | set(cb)) / (n * n)
    if expected == 1:
        return None
    return (observed - expected) / (1 - expected)


def pct(k: int, n: int) -> str:
    return f"{100 * k / n:.0f}" if n else "n/a"
