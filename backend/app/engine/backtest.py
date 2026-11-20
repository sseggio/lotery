"""Walk-forward backtest of the generation strategies.

For each test draw t (chronological order):
    history = draws strictly before t        <- History.before(t), asserted
    engine  = indicators (+ popularity model) built from `history` only
    for each strategy: generate G grids, compare with the real draw t

No information from draw t or later can reach the strategies: the engine is
rebuilt from the truncated history at every step, and the popularity model is
refitted every `refit_every` draws on the truncated history as well.

Metrics per strategy
    * mean number of correct main numbers per grid, vs. the exact theoretical
      expectation k*k/H (0.8 for Lotto, 0.5 for EuroMillions) and vs. the
      uniform random strategy;
    * z-test of the difference to theory (two-sided p-value), 95 % CI;
    * distribution of correct numbers, prize ranks reached;
    * money actually won using the *real* per-winner amounts of each draw
      (pari-mutuel amounts published by the operator), cost and return;
    * mean anti-sharing score and expected jackpot share (model estimate).
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np
from scipy import stats as sps

from . import popularity
from .data import History
from .generator import BACKTEST_STRATEGIES, STRATEGIES, Engine

MAX_TEST_DRAWS = 300
MAX_GRIDS_PER_DRAW = 20


def theoretical(h: History) -> dict[str, Any]:
    g = h.game
    p = g.main
    rv = sps.hypergeom(p.size, p.picks, p.picks)
    out = {
        "mean_main": p.picks * p.picks / p.size,
        "sd_main": float(rv.std()),
        "dist_main": [float(rv.pmf(i)) for i in range(p.picks + 1)],
        "tier_probabilities": g.tier_probabilities(),
    }
    if g.extra:
        rve = sps.hypergeom(g.extra.size, g.extra.picks, g.extra.picks)
        out["mean_extra"] = g.extra.picks ** 2 / g.extra.size
        out["dist_extra"] = [float(rve.pmf(i)) for i in range(g.extra.picks + 1)]
    return out


def run_backtest(h: History, n_test: int = 100, grids_per_draw: int = 10, balance: float = 0.5,
                 seed: int = 2024, refit_every: int = 10, min_history: int = 150,
                 strategies: tuple[str, ...] = BACKTEST_STRATEGIES) -> dict[str, Any]:
    g = h.game
    n_test = int(min(max(n_test, 10), MAX_TEST_DRAWS, len(h) - min_history))
    grids_per_draw = int(min(max(grids_per_draw, 1), MAX_GRIDS_PER_DRAW))
    if n_test < 10:
        raise ValueError("Historique insuffisant pour un backtest")
    t0 = time.time()
    rng = np.random.default_rng(seed)
    k = g.main.picks
    th = theoretical(h)
    first = len(h) - n_test

    acc = {s: {"hits": [], "extra_hits": [], "won": 0, "tiers": {}, "anti": [], "share": [],
               "timeline": []} for s in strategies}
    model = None
    for step, t in enumerate(range(first, len(h))):
        past = h.before(t)
        assert len(past) == t and (len(past) == 0 or past.times[-1] < h.times[t]), "look-ahead leak"
        if model is None or step % refit_every == 0:
            model = popularity.fit(past, ref_size=8000, seed=seed + step)
        else:
            model.last_draw = past.mains[-1]  # the "replay last draw" feature must follow time
        eng = Engine(past, model=model, ref_size=4000, seed=seed + step)
        actual = set(int(x) for x in h.mains[t])
        actual_extra = set(int(x) for x in h.extras[t]) if h.extras is not None else set()
        bonus = int(h.bonus[t]) if h.bonus is not None else None
        tiers_real = h.tiers.get(int(h.ids[t]), {})
        for s in strategies:
            strat = STRATEGIES[s]
            a = acc[s]
            step_hits = []
            for res in eng.pick_many(rng, strat, balance, grids_per_draw, m=1500):
                nums = res["numbers"]
                hits = len(actual & set(nums))
                xh = len(actual_extra & set(res["extras"] or [])) if g.extra else int(bonus in nums)
                a["hits"].append(hits)
                step_hits.append(hits)
                if g.extra:
                    a["extra_hits"].append(xh)
                tier = g.tier_name(hits, xh)
                if tier:
                    a["tiers"][tier] = a["tiers"].get(tier, 0) + 1
                    a["won"] += tiers_real.get(tier, (0, 0, None))[1]
                a["anti"].append(res["anti_score"])
                a["share"].append(res["expected_share"])
            a["timeline"].append(float(np.mean(step_hits)))

    mu, sd = th["mean_main"], th["sd_main"]
    n_grids = n_test * grids_per_draw
    price = g.base_price_cents
    results = []
    base = np.array(acc["aleatoire"]["timeline"]) if "aleatoire" in acc else None
    for s in strategies:
        a = acc[s]
        hits = np.array(a["hits"])
        mean = float(hits.mean())
        # The G grids of one draw face the same outcome and share numbers, so they
        # are NOT independent: inference is done on per-draw means (cluster-robust).
        per_draw = np.array(a["timeline"])
        se = float(per_draw.std(ddof=1) / np.sqrt(len(per_draw))) if len(per_draw) > 1 else sd
        se = float(max(se, sd / np.sqrt(len(hits))))  # never below the independent-grids bound
        z = float((mean - mu) / se)
        p = float(2 * sps.norm.sf(abs(z)))
        p_vs_random = None
        if base is not None and s != "aleatoire":
            diff = per_draw - base
            if diff.std(ddof=1) > 0:
                p_vs_random = float(sps.ttest_rel(per_draw, base).pvalue)
        dist = np.bincount(hits, minlength=k + 1)[: k + 1]
        cum = np.cumsum(a["timeline"]) / np.arange(1, len(a["timeline"]) + 1)
        cost = n_grids * price
        results.append({
            "strategy": s,
            "label": STRATEGIES[s].label,
            "mean_hits": round(mean, 4),
            "ci95": [round(mean - 1.96 * se, 4), round(mean + 1.96 * se, 4)],
            "delta_vs_theory_pct": round((mean / mu - 1) * 100, 2),
            "z": round(float(z), 2),
            "p_value": round(p, 4),
            "significant": p < 0.05,
            "p_value_vs_random": None if p_vs_random is None else round(p_vs_random, 4),
            "mean_extra_hits": round(float(np.mean(a["extra_hits"])), 4) if a["extra_hits"] else None,
            "distribution": [{"hits": i, "count": int(dist[i]), "pct": round(dist[i] / len(hits) * 100, 2),
                              "theoretical_pct": round(th["dist_main"][i] * 100, 2)} for i in range(k + 1)],
            "at_least_3_pct": round(float((hits >= 3).mean() * 100), 2),
            "tiers": a["tiers"],
            "won_eur": round(a["won"] / 100, 2),
            "cost_eur": round(cost / 100, 2),
            "return_pct": round(a["won"] / cost * 100, 1) if cost else 0.0,
            "mean_anti_score": round(float(np.mean(a["anti"])), 1),
            "mean_expected_jackpot_share": round(float(np.mean(a["share"])), 4),
            "cumulative_mean": [round(float(x), 4) for x in cum],
        })
    # Multiple comparisons: Bonferroni on the non-random strategies.
    n_cmp = max(1, len([r for r in results if r["strategy"] != "aleatoire"]))
    for r in results:
        r["significant_bonferroni"] = r["p_value"] < 0.05 / n_cmp

    return {
        "game": g.key,
        "n_test_draws": n_test,
        "grids_per_draw": grids_per_draw,
        "n_grids_per_strategy": n_grids,
        "balance": balance,
        "first_test_date": h.dates[first],
        "last_test_date": h.dates[-1],
        "test_dates": list(h.dates[first:]),
        "min_history": first,
        "theoretical_mean_hits": round(mu, 4),
        "theoretical_distribution": [round(x * 100, 2) for x in th["dist_main"]],
        "results": results,
        "duration_s": round(time.time() - t0, 1),
        "method": (
            "Walk-forward : pour chaque tirage testé, le moteur est reconstruit uniquement avec les tirages "
            "antérieurs (aucune donnée future). Le modèle de popularité est réajusté tous les "
            f"{refit_every} tirages sur l'historique tronqué."
        ),
    }
