"""Vectorised structural features of combinations.

All functions take an (M, k) integer array of *sorted* combinations and return
(M,) arrays, so that tens of thousands of candidates can be scored at once.
"""
from __future__ import annotations

import numpy as np


def max_multiplicity(keys: np.ndarray) -> np.ndarray:
    """Largest number of equal values per row (e.g. same last digit)."""
    s = np.sort(keys, axis=1)
    best = np.ones(len(s), dtype=np.int16)
    cur = np.ones(len(s), dtype=np.int16)
    for j in range(1, s.shape[1]):
        same = s[:, j] == s[:, j - 1]
        cur = np.where(same, cur + 1, 1)
        best = np.maximum(best, cur)
    return best


def max_consecutive_run(c: np.ndarray) -> np.ndarray:
    """Length of the longest run of consecutive numbers (1 = no two consecutive)."""
    d = np.diff(c, axis=1)
    best = np.ones(len(c), dtype=np.int16)
    cur = np.ones(len(c), dtype=np.int16)
    for j in range(d.shape[1]):
        cur = np.where(d[:, j] == 1, cur + 1, 1)
        best = np.maximum(best, cur)
    return best


def consecutive_pairs(c: np.ndarray) -> np.ndarray:
    return (np.diff(c, axis=1) == 1).sum(axis=1)


def longest_equal_step(c: np.ndarray) -> np.ndarray:
    """Longest arithmetic progression made of adjacent sorted numbers."""
    d = np.diff(c, axis=1)
    best = np.full(len(c), 2, dtype=np.int16)
    cur = np.full(len(c), 2, dtype=np.int16)
    for j in range(1, d.shape[1]):
        cur = np.where(d[:, j] == d[:, j - 1], cur + 1, 2)
        best = np.maximum(best, cur)
    return best


def slip_alignment(c: np.ndarray, columns: tuple[int, ...]) -> np.ndarray:
    """Max numbers aligned on one row/column/diagonal of a paper slip.

    The exact layout of the official slip may vary over time, so several
    plausible column counts are evaluated and the maximum is kept.
    """
    best = np.zeros(len(c), dtype=np.int16)
    z = c - 1
    for w in columns:
        r, col = z // w, z % w
        for key in (r, col, r - col, r + col):
            best = np.maximum(best, max_multiplicity(key))
    return best


def overlap_with(c: np.ndarray, ref: np.ndarray) -> np.ndarray:
    """Number of values each combination shares with a reference set."""
    if ref is None or len(ref) == 0:
        return np.zeros(len(c), dtype=np.int16)
    return np.isin(c, ref).sum(axis=1)


def structure(c: np.ndarray, high: int) -> dict[str, np.ndarray]:
    """Classic descriptive features (sum, parity, low/high...)."""
    return {
        "sum": c.sum(axis=1),
        "odd": (c % 2 == 1).sum(axis=1),
        "low": (c <= high // 2).sum(axis=1),  # "small" numbers: 1..22 (Lotto), 1..25 (EuroMillions)
        "le31": (c <= 31).sum(axis=1),
        "max_run": max_consecutive_run(c),
    }
