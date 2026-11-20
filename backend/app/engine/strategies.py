"""Number-level indicators and combination scores used by the strategies.

All indicators are computed from a `History` that only contains past draws.

Methods (see docs/CADRAGE.md for interest / limits of each):

* freq      — weighted frequency over the last ~year (104 draws), standardised
              (z-score vs. the binomial expectation).
* recent    — exponentially weighted moving average (half-life 12 draws):
              recent draws weigh more ("trend").
* overdue   — draws since last appearance, standardised. Kept only as a
              control in the backtest: it embodies the gambler's fallacy.
* pairs     — co-occurrence of number pairs vs. expectation (correlations).
* composite — 0.4 freq + 0.4 recent + 0.2 pairs.

A combination score is the mean of its numbers' indicators; it is converted to
a 0..100 percentile against uniform random combinations. A percentile measures
*agreement with past trends*, not a probability of being drawn: every
combination has exactly the same probability.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .data import History
from .stats import ewma_scores, gaps

FREQ_WINDOW = 104
HALF_LIFE = 12.0
OBJECTIVES = ("freq", "recent", "pairs", "overdue", "composite")
COMPOSITE_WEIGHTS = {"freq": 0.4, "recent": 0.4, "pairs": 0.2}


def _z(x: np.ndarray) -> np.ndarray:
    sd = x.std()
    return (x - x.mean()) / sd if sd > 0 else np.zeros_like(x, dtype=float)


@dataclass
class PoolIndicators:
    freq: np.ndarray       # (H,) z-score
    recent: np.ndarray     # (H,) z-score
    overdue: np.ndarray    # (H,) z-score
    counts: np.ndarray     # (H,) raw counts in the window
    gap: np.ndarray        # (H,) draws since last appearance
    pair_z: np.ndarray | None  # (H, H) standardised co-occurrence (main pool only)
    window: int


def pool_indicators(h: History, pool: str) -> PoolIndicators:
    p = h.game.main if pool == "main" else h.game.extra
    assert p is not None
    w = h.last(FREQ_WINDOW)
    n = len(w)
    ind = w.indicator(pool).astype(float)
    counts = ind.sum(0) if n else np.zeros(p.size)
    pr = p.picks / p.size
    sd = np.sqrt(max(n, 1) * pr * (1 - pr))
    freq = (counts - n * pr) / sd if n else np.zeros(p.size)
    recent = _z(ewma_scores(h, HALF_LIFE, pool)) if len(h) else np.zeros(p.size)
    g = gaps(h, pool)["current"] if len(h) else np.zeros(p.size)
    overdue = _z(g)
    pair_z = None
    if pool == "main" and n:
        co = ind.T @ ind
        exp_pair = n * p.picks * (p.picks - 1) / (p.size * (p.size - 1))
        pair_z = (co - exp_pair) / np.sqrt(max(exp_pair, 1e-9))
        np.fill_diagonal(pair_z, 0.0)
    return PoolIndicators(freq, recent, overdue, counts, g, pair_z, n)


@dataclass
class Indicators:
    main: PoolIndicators
    extra: PoolIndicators | None


def compute_indicators(h: History) -> Indicators:
    return Indicators(pool_indicators(h, "main"), pool_indicators(h, "extra") if h.game.extra else None)


def number_vector(pi: PoolIndicators, objective: str) -> np.ndarray:
    """Per-number tilt used to *propose* candidates for an objective."""
    if objective == "freq":
        return pi.freq
    if objective == "recent":
        return pi.recent
    if objective == "overdue":
        return pi.overdue
    return 0.5 * pi.freq + 0.5 * pi.recent  # composite / pairs


def _pairs_score(pz: np.ndarray, c: np.ndarray) -> np.ndarray:
    k = c.shape[1]
    idx = c - 1
    tot = np.zeros(len(c))
    for i in range(k):
        for j in range(i + 1, k):
            tot += pz[idx[:, i], idx[:, j]]
    return tot / (k * (k - 1) / 2)


def combo_scores(ind: Indicators, c: np.ndarray, e: np.ndarray | None, low_main: int = 1,
                 low_extra: int = 1) -> dict[str, np.ndarray]:
    """Raw (un-normalised) score of each combination for every objective."""
    m = ind.main
    ci = c - low_main
    out = {
        "freq": m.freq[ci].mean(1),
        "recent": m.recent[ci].mean(1),
        "overdue": m.overdue[ci].mean(1),
        "pairs": _pairs_score(m.pair_z, c - low_main + 1) if m.pair_z is not None else np.zeros(len(c)),
    }
    if e is not None and ind.extra is not None:
        # Stars contribute in proportion to their share of the picks (2 of 7).
        x = ind.extra
        ei = e - low_extra
        share = e.shape[1] / (e.shape[1] + c.shape[1])
        for key in ("freq", "recent", "overdue"):
            out[key] = (1 - share) * out[key] + share * getattr(x, key)[ei].mean(1)
    out["composite"] = sum(COMPOSITE_WEIGHTS[k] * out[k] for k in COMPOSITE_WEIGHTS)
    return out
