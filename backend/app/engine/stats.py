"""Descriptive statistics of past draws.

Every observed quantity is returned next to its *theoretical* value under a
fair, uniform draw, so the UI can show whether a "trend" is larger than what
pure chance produces. Reminder: draws are independent; these statistics
describe the past and do not predict the next draw.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
from itertools import combinations
from math import comb

import numpy as np
from scipy import stats as sps

from .data import History
from .features import consecutive_pairs, max_consecutive_run

WINDOWS = ("year", "30", "60", "90", "all")


def window_slice(h: History, window: str) -> History:
    if window == "year":
        sub = h.since_date(f"{date.today().year}-01-01")
        if len(sub) >= 5:
            return sub
        # Early January (or stale data): fall back to the last ~year of draws.
        return h.last(104)
    if window == "all":
        return h
    return h.last(int(window))


def _pool(h: History, pool: str):
    return (h.game.main, h.mains) if pool == "main" else (h.game.extra, h.extras)


def gaps(h: History, pool: str = "main") -> dict[str, np.ndarray]:
    """Draws since last appearance, mean / max gap and gap regularity per number."""
    p, _ = _pool(h, pool)
    ind = h.indicator(pool)
    n = len(ind)
    current = np.full(p.size, n, dtype=float)
    mean_gap = np.full(p.size, np.nan)
    max_gap = np.zeros(p.size)
    cv = np.full(p.size, np.nan)
    last_idx = np.full(p.size, -1)
    for j in range(p.size):
        idx = np.flatnonzero(ind[:, j])
        if len(idx):
            last_idx[j] = idx[-1]
            current[j] = n - 1 - idx[-1]
            g = np.diff(idx)
            if len(g):
                mean_gap[j] = g.mean()
                max_gap[j] = max(g.max(), current[j])
                cv[j] = g.std() / g.mean() if g.mean() else np.nan
    return {"current": current, "mean": mean_gap, "max": max_gap, "cv": cv, "last_idx": last_idx}


def ewma_scores(h: History, half_life: float = 12.0, pool: str = "main") -> np.ndarray:
    """Exponentially weighted appearance rate (recent draws weigh more)."""
    ind = h.indicator(pool).astype(float)
    if not len(ind):
        p, _ = _pool(h, pool)
        return np.zeros(p.size)
    age = np.arange(len(ind))[::-1]
    w = 0.5 ** (age / half_life)
    return (w[:, None] * ind).sum(0) / w.sum()


def chi_square_uniformity(counts: np.ndarray) -> dict:
    """Chi-square goodness-of-fit test of the frequencies against uniformity."""
    if counts.sum() == 0:
        return {"statistic": 0.0, "df": len(counts) - 1, "p_value": 1.0}
    res = sps.chisquare(counts)
    return {"statistic": float(res.statistic), "df": len(counts) - 1, "p_value": float(res.pvalue)}


def frequency_table(h: History, full: History, pool: str = "main") -> list[dict]:
    p, _ = _pool(h, pool)
    n = len(h)
    counts = h.indicator(pool).sum(0) if n else np.zeros(p.size)
    pr = p.picks / p.size
    expected = n * pr
    sd = np.sqrt(n * pr * (1 - pr)) if n else 1.0
    g = gaps(full, pool)
    ew = ewma_scores(full, pool=pool)
    windows = {w: full.last(int(w)).indicator(pool).sum(0) for w in ("30", "60", "90")}
    # Rolling-30 frequency over the analysed window: high / low periods.
    ind_full = full.indicator(pool)
    start = len(full) - n
    roll = None
    if len(ind_full) >= 30:
        cs = np.vstack([np.zeros((1, p.size)), np.cumsum(ind_full, 0)])
        r = cs[30:] - cs[:-30]  # r[i] = appearances in draws i..i+29
        lo = max(0, start - 29)
        roll = r[lo:] if len(r[lo:]) else None
    out = []
    for j in range(p.size):
        li = int(g["last_idx"][j])
        out.append({
            "number": j + p.low,
            "count": int(counts[j]),
            "expected": round(float(expected), 2),
            "z": round(float((counts[j] - expected) / sd), 2) if n else 0.0,
            "pct": round(float(counts[j] / n * 100), 1) if n else 0.0,
            "count_30": int(windows["30"][j]),
            "count_60": int(windows["60"][j]),
            "count_90": int(windows["90"][j]),
            "gap": int(g["current"][j]),
            "mean_gap": None if np.isnan(g["mean"][j]) else round(float(g["mean"][j]), 1),
            "max_gap": int(g["max"][j]),
            "regularity_cv": None if np.isnan(g["cv"][j]) else round(float(g["cv"][j]), 2),
            "ewma": round(float(ew[j] * 100), 2),
            "last_date": full.dates[li] if li >= 0 else None,
            "rolling30_max": int(roll[:, j].max()) if roll is not None else None,
            "rolling30_min": int(roll[:, j].min()) if roll is not None else None,
        })
    return out


def evolution(h: History, full: History, pool: str = "main", span: int = 30) -> dict:
    """Rolling `span`-draw frequency of every number at each draw of the window."""
    p, _ = _pool(h, pool)
    ind = full.indicator(pool)
    cs = np.vstack([np.zeros((1, p.size), dtype=int), np.cumsum(ind, 0)])
    start = len(full) - len(h)
    dates, series = [], {str(j + p.low): [] for j in range(p.size)}
    for i in range(start, len(full)):
        lo = max(0, i + 1 - span)
        vals = cs[i + 1] - cs[lo]
        dates.append(full.dates[i])
        for j in range(p.size):
            series[str(j + p.low)].append(int(vals[j]))
    return {"span": span, "dates": dates, "series": series,
            "expected": round(span * p.picks / p.size, 2)}


def monthly_heatmap(h: History, pool: str = "main") -> dict:
    p, arr = _pool(h, pool)
    months = sorted({d[:7] for d in h.dates})
    idx = {m: i for i, m in enumerate(months)}
    mat = np.zeros((len(months), p.size), dtype=int)
    draws_per_month = np.zeros(len(months), dtype=int)
    for d, row in zip(h.dates, arr):
        mi = idx[d[:7]]
        draws_per_month[mi] += 1
        mat[mi, row - p.low] += 1
    return {"months": months, "draws": draws_per_month.tolist(), "matrix": mat.tolist()}


def top_tuples(h: History, size: int, top: int = 15) -> list[dict]:
    p = h.game.main
    cnt: Counter = Counter()
    for row in h.mains:
        cnt.update(combinations(row.tolist(), size))
    # P(a given tuple is entirely in one draw) = C(H-size, k-size) / C(H, k)
    pr = comb(p.size - size, p.picks - size) / comb(p.size, p.picks)
    expected = len(h) * pr
    # Under the null the max of C(H, size) Poisson-ish counts is naturally high:
    # report the expected maximum via simulation-free Poisson approximation.
    n_tuples = comb(p.size, size)
    exp_max = float(sps.poisson.ppf(1 - 1 / n_tuples, expected)) if expected > 0 else 0.0
    return [
        {"numbers": list(t), "count": c, "expected": round(expected, 2), "expected_max_by_chance": exp_max}
        for t, c in cnt.most_common(top)
    ]


def _hypergeom_pmf(total: int, good: int, picks: int) -> list[float]:
    rv = sps.hypergeom(total, good, picks)
    return [float(rv.pmf(i)) for i in range(picks + 1)]


def distributions(h: History) -> dict:
    p = h.game.main
    c = h.mains
    n = len(c)
    k, H = p.picks, p.size
    rng = np.random.default_rng(12345)
    sim = np.sort(np.argsort(rng.random((40000, H)), axis=1)[:, :k] + 1, axis=1)

    def obs_vs_theory(values: np.ndarray, theory: list[float]) -> list[dict]:
        bc = np.bincount(values, minlength=k + 1)
        return [{"value": i, "observed": int(bc[i]), "observed_pct": round(bc[i] / n * 100, 1) if n else 0,
                 "theoretical_pct": round(theory[i] * 100, 1)} for i in range(k + 1)]

    n_odd = (H + 1) // 2
    odd = obs_vs_theory((c % 2 == 1).sum(1), _hypergeom_pmf(H, n_odd, k))
    low = obs_vs_theory((c <= H // 2).sum(1), _hypergeom_pmf(H, H // 2, k))

    sums = c.sum(1)
    lo_s, hi_s = k * (k + 1) // 2, sum(range(H - k + 1, H + 1))
    edges = np.linspace(lo_s, hi_s + 1, 16).astype(int)
    oh, _ = np.histogram(sums, edges)
    th, _ = np.histogram(sim.sum(1), edges)
    sum_hist = [{"from": int(edges[i]), "to": int(edges[i + 1] - 1), "observed_pct": round(oh[i] / max(n, 1) * 100, 1),
                 "theoretical_pct": round(th[i] / len(sim) * 100, 1)} for i in range(len(oh))]
    central = np.percentile(sim.sum(1), [10, 90])

    dec_edges = list(range(0, H, 10))
    decades = []
    for d0 in dec_edges:
        lo_n, hi_n = max(1, d0), min(H, d0 + 9)
        size = hi_n - lo_n + 1
        obs = int(((c >= lo_n) & (c <= hi_n)).sum())
        decades.append({"label": f"{lo_n}-{hi_n}", "observed": obs,
                        "expected": round(n * k * size / H, 1)})

    cons_obs = float((consecutive_pairs(c) > 0).mean() * 100) if n else 0.0
    cons_th = float((consecutive_pairs(sim) > 0).mean() * 100)
    return {
        "odd_even": odd,
        "low_high": low,
        "low_threshold": H // 2,
        "sum_histogram": sum_hist,
        "sum_mean_observed": round(float(sums.mean()), 1) if n else None,
        "sum_mean_theoretical": round(k * (H + 1) / 2, 1),
        "sum_central_80": [int(central[0]), int(central[1])],
        "decades": decades,
        "consecutive_pct_observed": round(cons_obs, 1),
        "consecutive_pct_theoretical": round(cons_th, 1),
        "max_run_observed": int(max_consecutive_run(c).max()) if n else 0,
    }


def recurring_combinations(h: History) -> dict:
    """Exact repeats of full combinations, and repeats from one draw to the next."""
    seen = Counter(tuple(r) for r in h.mains.tolist())
    repeats = [{"numbers": list(t), "count": c} for t, c in seen.items() if c > 1]
    carry = [int(len(set(a) & set(b))) for a, b in zip(h.mains[:-1].tolist(), h.mains[1:].tolist())]
    bc = np.bincount(carry, minlength=h.game.main.picks + 1) if carry else np.zeros(1)
    p = h.game.main
    th = _hypergeom_pmf(p.size, p.picks, p.picks)
    return {
        "exact_repeats": repeats,
        "carry_over": [{"shared": i, "observed_pct": round(bc[i] / max(len(carry), 1) * 100, 1),
                        "theoretical_pct": round(th[i] * 100, 1)} for i in range(min(len(bc), 4))],
    }
