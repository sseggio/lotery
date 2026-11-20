"""Estimated popularity of a combination among other players (anti-sharing).

Why it matters
--------------
Every combination has exactly the same probability of being drawn. But the
upper prize ranks are *pari-mutuel*: the pool is split between winners. A
combination that many people play wins less when it comes out. Choosing
unpopular combinations does not change the probability of winning; it can only
increase the expected amount *if* you win.

Model (log-linear)
------------------
    log popularity(c) = sum_{n in c} theta_n            (number preferences)
                      + beta_consec * consecutive_pairs  (estimated)
                      + beta_dates  * [all numbers <= 31] (estimated)
                      + pattern priors (very regular patterns, see PRIORS)

1. *Estimated part* — calibrated on official Belgian data. For each past draw
   we know how many Belgian boards won the middle ranks (3 and 4 correct numbers)
   and how many boards were sold. Under uniform play the expected count is
   boards * P(rank). The ratio observed/expected tells how popular the drawn
   numbers were. A ridge-regularised, weighted least-squares fit of
   log(observed/expected) on the drawn numbers gives theta_n. Because a winner at
   rank m only shares m of the k numbers, the fitted coefficients are rescaled by
   k / m (first-order approximation of the multiplicative model).
2. *Prior part* — patterns that are (almost) never drawn, such as 1-2-3-4-5-6 or
   whole slip rows, cannot be estimated from draws. Their weights are
   conservative orders of magnitude taken from published studies of player
   choices (e.g. UK/Canadian/Swiss lotto analyses reporting thousands of
   players for 1-2-3-4-5-6, birthday bias toward 1..31, overplay of the
   previous draw's numbers). They are explicit hypotheses, shown as such.

This is an *estimate*: the operator does not publish which combinations are
played. The model quality (out-of-sample R^2 on later draws) is reported.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import comb

import numpy as np

from .data import History
from .features import (
    consecutive_pairs,
    longest_equal_step,
    max_consecutive_run,
    max_multiplicity,
    overlap_with,
    slip_alignment,
)

# Conservative log-lift priors for patterns that cannot be estimated.
PRIORS = {
    "run": {3: 0.25, 4: 1.0, 5: 2.5, 6: 6.0},   # longest run of consecutive numbers
    "arith_full": 3.0,                          # whole combination is an arithmetic progression
    "arith_4": 0.6,                             # 4+ adjacent numbers with the same step
    "all_le12": 1.0,                            # every number <= 12 (months)
    "aligned_full": 2.0,                        # all numbers on one slip row/column/diagonal
    "aligned_most": 0.7,                        # all but one aligned
    "same_digit_4": 0.8,                        # 4+ numbers with the same last digit
    "mult5_4": 0.6,                             # 4+ multiples of 5 ("round" numbers)
    "repeat_last_4": 1.0,                       # 4+ numbers of the previous draw
    "repeat_last_all": 4.0,                     # previous draw replayed entirely
}

PRIOR_LABELS = {
    "run": "Suite de numéros consécutifs",
    "arith_full": "Progression arithmétique complète",
    "arith_4": "4 numéros ou plus en progression régulière",
    "all_le12": "Tous les numéros ≤ 12 (mois)",
    "aligned_full": "Tous les numéros alignés sur le bulletin",
    "aligned_most": "Presque tous alignés sur le bulletin",
    "same_digit_4": "4 numéros ou plus avec le même chiffre des unités",
    "mult5_4": "4 multiples de 5 ou plus",
    "repeat_last_4": "4 numéros ou plus du dernier tirage",
    "repeat_last_all": "Copie du dernier tirage",
}

RIDGE = 8.0
# Cap on the summed pattern priors: about 5,000x an average combination, the order
# of magnitude reported for 1-2-3-4-5-6 in large national lotteries.
PATTERN_CAP = 8.5
# Causal detrending window (draws): removes slow level drifts (sales accounting,
# jackpot-driven player mix) so that only draw-to-draw popularity differences remain.
DETREND_WINDOW = 20


@dataclass
class PopularityModel:
    game_key: str
    theta: np.ndarray                 # (H,) main numbers, log-popularity on the full-combination scale
    theta_extra: np.ndarray | None    # (E,) stars
    beta_consec: float
    beta_dates: float
    last_draw: np.ndarray | None      # previous draw (for the "replay" pattern)
    columns: tuple[int, ...]
    high: int
    k: int
    diagnostics: dict = field(default_factory=dict)
    # Reference distribution (uniform random combinations) for normalisation.
    ref_logpop: np.ndarray | None = None
    mean_pop: float = 1.0
    boards_typical: float = 0.0
    n_combinations: int = 1

    # ---- scoring --------------------------------------------------------
    def pattern_terms(self, c: np.ndarray) -> tuple[np.ndarray, dict[str, np.ndarray]]:
        k = self.k
        run = max_consecutive_run(c)
        step = longest_equal_step(c)
        align = slip_alignment(c, self.columns)
        digit = max_multiplicity(c % 10)
        mult5 = (c % 5 == 0).sum(1)
        rep = overlap_with(c, self.last_draw)
        flags = {
            "run": np.vectorize(lambda r: PRIORS["run"].get(int(min(r, 6)), 0.0))(run) if len(c) else np.zeros(0),
            # step 1 is already counted as a consecutive run
            "arith_full": np.where((step >= k) & (run < k), PRIORS["arith_full"], 0.0),
            "arith_4": np.where((step >= 4) & (step < k), PRIORS["arith_4"], 0.0),
            "all_le12": np.where((c <= 12).all(1), PRIORS["all_le12"], 0.0),
            "aligned_full": np.where(align >= k, PRIORS["aligned_full"], 0.0),
            "aligned_most": np.where(align == k - 1, PRIORS["aligned_most"], 0.0),
            "same_digit_4": np.where(digit >= 4, PRIORS["same_digit_4"], 0.0),
            "mult5_4": np.where(mult5 >= 4, PRIORS["mult5_4"], 0.0),
            "repeat_last_4": np.where((rep >= 4) & (rep < k), PRIORS["repeat_last_4"], 0.0),
            "repeat_last_all": np.where(rep >= k, PRIORS["repeat_last_all"], 0.0),
        }
        total = np.zeros(len(c))
        for v in flags.values():
            total = total + v
        return np.minimum(total, PATTERN_CAP), flags

    def log_popularity(self, c: np.ndarray, e: np.ndarray | None = None) -> np.ndarray:
        lp = self.theta[c - 1].sum(1)
        lp = lp + self.beta_consec * consecutive_pairs(c)
        lp = lp + self.beta_dates * (c <= 31).all(1)
        lp = lp + self.pattern_terms(c)[0]
        if e is not None and self.theta_extra is not None:
            lp = lp + self.theta_extra[e - 1].sum(1)
        return lp

    def anti_score(self, logpop: np.ndarray) -> np.ndarray:
        """0..100: share of random combinations MORE popular than this one."""
        assert self.ref_logpop is not None
        return 100.0 * (1.0 - np.searchsorted(self.ref_logpop, logpop, side="right") / len(self.ref_logpop))

    def relative(self, logpop: np.ndarray) -> np.ndarray:
        """Popularity relative to an average combination (1 = average)."""
        return np.exp(logpop) / self.mean_pop

    def expected_share(self, logpop: np.ndarray) -> np.ndarray:
        """Expected fraction of the jackpot kept if this combination wins.

        Other winners K ~ Poisson(lambda), lambda = boards * P(someone plays c);
        E[1 / (1 + K)] = (1 - exp(-lambda)) / lambda.
        """
        lam = self.boards_typical * self.relative(logpop) / self.n_combinations
        lam = np.maximum(lam, 1e-12)
        return (1 - np.exp(-lam)) / lam

    def explain(self, c: np.ndarray, e: np.ndarray | None = None) -> dict:
        """Human-readable breakdown for one combination (1-D arrays)."""
        c2 = c.reshape(1, -1)
        e2 = None if e is None else e.reshape(1, -1)
        lp = self.log_popularity(c2, e2)
        _, flags = self.pattern_terms(c2)
        patterns = [PRIOR_LABELS[k] for k, v in flags.items() if v[0] > 0]
        rel = float(self.relative(lp)[0])
        share = float(self.expected_share(lp)[0])
        avg_share = float(self.expected_share(np.log(np.array([self.mean_pop])))[0])
        return {
            "relative_popularity": round(rel, 3),
            "anti_score": round(float(self.anti_score(lp)[0]), 1),
            "expected_jackpot_share": round(share, 4),
            "average_jackpot_share": round(avg_share, 4),
            "gain_vs_average_pct": round((share / avg_share - 1) * 100, 1) if avg_share else 0.0,
            "patterns": patterns,
            "number_effects": {int(n): round(float(np.exp(self.theta[n - 1])), 3) for n in c},
            "all_le31": bool((c <= 31).all()),
            "consecutive_pairs": int(consecutive_pairs(c2)[0]),
        }


def _design(h: History, idx: np.ndarray) -> np.ndarray:
    p = h.game.main
    k = p.picks
    cols = [h.indicator("main")[idx].astype(float)]
    if h.extras is not None:
        cols.append(h.indicator("extra")[idx].astype(float))
    c = h.mains[idx]
    cols.append(consecutive_pairs(c)[:, None].astype(float))
    cols.append((c <= 31).all(1)[:, None].astype(float))
    return np.hstack(cols)


def _calibration_targets(h: History) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """Per draw: log(observed / expected) winners on middle ranks, weight, index, mean hits."""
    g = h.game
    probs = g.tier_probabilities()
    if g.key == "lotto":
        tiers = ["4+1", "4", "3+1", "3"]
        hits = {"4+1": 4, "4": 4, "3+1": 3, "3": 3}
    else:
        tiers = ["4+0", "3+2", "3+1", "3+0", "2+2", "2+1", "2+0"]
        hits = {t: int(t[0]) + int(t[2]) * 0.5 for t in tiers}  # stars count roughly half a number
    p_tot = sum(probs[t] for t in tiers)
    z, w, idx = [], [], []
    for i, did in enumerate(h.ids):
        tr = h.tiers.get(int(did))
        b = h.boards[i]
        if not tr or not np.isfinite(b) or b <= 0 or any(t not in tr for t in tiers):
            continue
        y = sum(tr[t][0] for t in tiers)
        if y <= 0:
            continue
        z.append(np.log((y + 0.5) / (b * p_tot)))
        w.append(y)
        idx.append(i)
    m_bar = sum(probs[t] * hits[t] for t in tiers) / p_tot
    z_arr = np.array(z)
    # Causal detrending: subtract the median of the previous DETREND_WINDOW draws
    # (only past values, so the calibration itself never looks ahead).
    det = np.empty_like(z_arr)
    for j in range(len(z_arr)):
        prev = z_arr[max(0, j - DETREND_WINDOW):j]
        det[j] = z_arr[j] - (np.median(prev) if len(prev) >= 5 else np.median(z_arr[: max(j, 1)]))
    keep = np.arange(len(z_arr)) >= 5  # drop the warm-up draws
    return det[keep], np.array(w, dtype=float)[keep], np.array(idx, dtype=int)[keep], float(m_bar)


def _wls_ridge(X: np.ndarray, z: np.ndarray, w: np.ndarray, ridge: float) -> tuple[np.ndarray, float, np.ndarray]:
    """Weighted ridge regression with an unpenalised intercept. Returns coef, intercept, std errors."""
    sw = np.sqrt(w / w.mean())
    Xc = np.hstack([np.ones((len(X), 1)), X])
    A = Xc * sw[:, None]
    b = z * sw
    P = np.eye(Xc.shape[1]) * ridge
    P[0, 0] = 0.0
    M = A.T @ A + P
    beta = np.linalg.solve(M, A.T @ b)
    resid = b - A @ beta
    dof = max(len(b) - Xc.shape[1], 1)
    sigma2 = float(resid @ resid) / dof
    cov = sigma2 * np.linalg.inv(M)
    se = np.sqrt(np.clip(np.diag(cov), 0, None))
    return beta[1:], float(beta[0]), se[1:]


def fit(h: History, ref_size: int = 30000, seed: int = 7) -> PopularityModel:
    """Calibrate the model on the history `h` (only past draws are used)."""
    g = h.game
    p, k = g.main, g.main.picks
    E = g.extra.size if g.extra else 0
    z, w, idx, m_bar = _calibration_targets(h)
    n_params = p.size + E + 2
    diagnostics: dict = {"n_draws_used": int(len(z)), "estimated": len(z) >= 60}
    theta = np.zeros(p.size)
    theta_e = np.zeros(E) if E else None
    beta_consec = 0.0
    beta_dates = 0.0
    if len(z) >= 60:
        X = _design(h, idx)
        scale = k / m_bar  # rank-m winners share m of the k numbers
        coef, _, se = _wls_ridge(X, z, w, RIDGE)
        theta = coef[: p.size] * scale
        theta -= theta.mean()
        if E:
            theta_e = coef[p.size: p.size + E] * scale
            theta_e -= theta_e.mean()
        beta_consec = float(coef[-2] * scale)
        beta_dates = float(coef[-1] * scale)
        # Out-of-sample check: fit on the first 80 %, predict the last 20 %.
        cut = int(len(z) * 0.8)
        r2 = None
        if cut >= 50 and len(z) - cut >= 15:
            c2, a2, _ = _wls_ridge(X[:cut], z[:cut], w[:cut], RIDGE)
            pred = a2 + X[cut:] @ c2
            ss_res = float(((z[cut:] - pred) ** 2 * w[cut:]).sum())
            ss_tot = float(((z[cut:] - np.average(z[cut:], weights=w[cut:])) ** 2 * w[cut:]).sum())
            r2 = 1 - ss_res / ss_tot if ss_tot > 0 else None
            diagnostics["oos_corr"] = round(float(np.corrcoef(pred, z[cut:])[0, 1]), 3)
        diagnostics.update({
            "oos_r2": None if r2 is None else round(r2, 3),
            "scale_factor": round(scale, 3),
            "ratio_spread": [round(float(np.exp(np.percentile(z, q))), 3) for q in (5, 50, 95)],
            "beta_consecutive": round(beta_consec, 3),
            "beta_all_le31": round(beta_dates, 3),
            "se_theta_mean": round(float(se[: p.size].mean() * scale), 3),
            "n_params": n_params,
        })
    model = PopularityModel(
        game_key=g.key, theta=theta, theta_extra=theta_e, beta_consec=beta_consec,
        beta_dates=beta_dates, last_draw=h.mains[-1] if len(h) else None,
        columns=g.slip_columns, high=p.high, k=k, diagnostics=diagnostics,
        n_combinations=g.n_combinations,
    )
    rng = np.random.default_rng(seed)
    ref_c = random_combinations(rng, p.size, k, ref_size) + p.low - 1
    ref_e = None
    if g.extra:
        ref_e = random_combinations(rng, g.extra.size, g.extra.picks, ref_size) + g.extra.low - 1
    lp = model.log_popularity(ref_c, ref_e)
    model.ref_logpop = np.sort(lp)
    model.mean_pop = float(np.exp(lp).mean())
    finite = h.boards[np.isfinite(h.boards)]
    model.boards_typical = float(np.median(finite[-104:])) if len(finite) else 0.0
    # EuroMillions is played in 9 countries: a jackpot is shared with all of them.
    # Scale Belgian boards by the (all countries / Belgium) winners ratio observed
    # on the low ranks, which have thousands of winners per draw.
    factor = _international_factor(h)
    if factor:
        model.boards_typical *= factor
        diagnostics["international_factor"] = round(factor, 2)
    diagnostics["boards_typical"] = round(model.boards_typical)
    return model


def _international_factor(h: History) -> float | None:
    if h.game.extra is None:
        return None
    ratios = []
    for did in h.ids[-208:]:
        tr = h.tiers.get(int(did)) or {}
        be = sum(v[0] for k, v in tr.items() if k in ("2+0", "2+1", "1+2", "3+0"))
        world = sum((v[2] or 0) for k, v in tr.items() if k in ("2+0", "2+1", "1+2", "3+0"))
        if be > 100 and world > be:
            ratios.append(world / be)
    return float(np.median(ratios)) if len(ratios) >= 10 else None


def random_combinations(rng: np.random.Generator, size: int, picks: int, m: int) -> np.ndarray:
    """m uniform random combinations of `picks` distinct values in 1..size, sorted."""
    return np.sort(np.argsort(rng.random((m, size)), axis=1)[:, :picks] + 1, axis=1).astype(np.int16)


def number_table(model: PopularityModel, low: int = 1) -> list[dict]:
    return [{"number": i + low, "multiplier": round(float(np.exp(t)), 3)} for i, t in enumerate(model.theta)]


def expected_share_curve(model: PopularityModel) -> list[dict]:
    """Expected jackpot share as a function of relative popularity (for the UI)."""
    out = []
    for rel in (0.25, 0.5, 0.75, 1, 1.5, 2, 4, 10, 100, 1000):
        lp = np.log(np.array([rel * model.mean_pop]))
        out.append({"relative_popularity": rel, "expected_share": round(float(model.expected_share(lp)[0]), 4)})
    return out


__all__ = ["PopularityModel", "fit", "random_combinations", "comb"]
