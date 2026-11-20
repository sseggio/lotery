"""Grid generation: Monte-Carlo candidates + two-objective selection.

For each grid slot:

1. **Monte-Carlo proposal** — a few thousand distinct candidate combinations
   are drawn: part tilted toward the slot's statistical objective, part
   tilted toward unpopular numbers, part uniform. Sampling is without
   replacement inside a combination (Gumbel top-k), so a grid never contains
   duplicates.
2. **Scoring** — each candidate gets
   * a *statistical score* (0-100): percentile of the slot's objective
     against uniform random combinations;
   * an *anti-sharing score* (0-100): share of random combinations estimated
     to be more popular (see popularity.py).
3. **Selection** — objective = a * stat + (1 - a) * anti - diversity penalty,
   where `a` depends on the slot and on the user's balance setting.
   Candidates sharing more than `max_overlap` numbers with an already chosen
   grid are rejected. The final pick is drawn among the top candidates
   (soft-max), so regenerating gives a *different* but equally good grid.

None of this changes the probability of winning, which is identical for
every combination. The scores describe agreement with past data and the
estimated risk of sharing a prize.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from ..games import Game
from . import popularity
from .data import History
from .features import consecutive_pairs, max_consecutive_run
from .strategies import Indicators, combo_scores, compute_indicators, number_vector


@dataclass(frozen=True)
class Strategy:
    key: str
    label: str
    objective: str | None   # None = uniform random
    alpha_base: float       # weight of the statistical score at balance 0.5
    description: str


STRATEGIES: dict[str, Strategy] = {s.key: s for s in (
    Strategy("frequence", "Fréquences historiques", "freq", 0.9,
             "Privilégie les numéros sortis plus souvent que la moyenne sur les 104 derniers tirages (≈ 1 an)."),
    Strategy("tendance", "Tendances récentes", "recent", 0.9,
             "Moyenne mobile exponentielle (demi-vie 12 tirages) : les tirages récents pèsent davantage."),
    Strategy("hybride", "Hybride statistiques + anti-partage", "composite", 0.5,
             "Indicateur combiné (fréquence, tendance, paires) équilibré avec le score anti-partage."),
    Strategy("anti_partage", "Anti-partage", "composite", 0.1,
             "Priorité aux combinaisons estimées peu jouées pour réduire le risque de partager un gain."),
    Strategy("retard", "Numéros en retard (contrôle)", "overdue", 1.0,
             "Numéros absents depuis longtemps. Sert de témoin : l'idée qu'ils « doivent » sortir est une illusion."),
    Strategy("aleatoire", "Aléatoire uniforme (référence)", None, 0.0,
             "Tirage parfaitement aléatoire, base de comparaison de toutes les stratégies."),
)}

SLOTS = ("frequence", "tendance", "hybride", "anti_partage")
BACKTEST_STRATEGIES = ("aleatoire", "frequence", "tendance", "hybride", "anti_partage", "retard")


def slot_alpha(strategy: Strategy, balance: float) -> float:
    """Weight of the statistical score for a strategy given the user's balance (0..1)."""
    return float(np.clip(strategy.alpha_base + (balance - 0.5) * 0.8, 0.0, 1.0))


def _gumbel_topk(rng: np.random.Generator, logits: np.ndarray, k: int, m: int) -> np.ndarray:
    """m combinations of k distinct indices, sampled with probability ~ softmax(logits)."""
    g = rng.gumbel(size=(m, len(logits))) + logits[None, :]
    idx = np.argpartition(-g, k - 1, axis=1)[:, :k]
    return np.sort(idx, axis=1)


class Engine:
    """Everything needed to score combinations at a given point in time."""

    def __init__(self, h: History, model: popularity.PopularityModel | None = None,
                 ref_size: int = 20000, seed: int = 0) -> None:
        self.h = h
        self.game: Game = h.game
        self.ind: Indicators = compute_indicators(h)
        self.model = model or popularity.fit(h)
        rng = np.random.default_rng(seed)
        g = self.game
        self.ref_c = popularity.random_combinations(rng, g.main.size, g.main.picks, ref_size) + g.main.low - 1
        self.ref_e = None
        if g.extra:
            self.ref_e = popularity.random_combinations(rng, g.extra.size, g.extra.picks, ref_size) + g.extra.low - 1
        ref = combo_scores(self.ind, self.ref_c, self.ref_e)
        self.ref_sorted = {k: np.sort(v) for k, v in ref.items()}

    # ---- scoring ------------------------------------------------------
    def percentile(self, objective: str, raw: np.ndarray) -> np.ndarray:
        ref = self.ref_sorted[objective]
        return 100.0 * np.searchsorted(ref, raw, side="right") / len(ref)

    def score(self, c: np.ndarray, e: np.ndarray | None) -> dict[str, np.ndarray]:
        raw = combo_scores(self.ind, c, e)
        out = {f"pct_{k}": self.percentile(k, v) for k, v in raw.items()}
        lp = self.model.log_popularity(c, e)
        out["logpop"] = lp
        out["anti"] = self.model.anti_score(lp)
        return out

    # ---- candidates ---------------------------------------------------
    def candidates(self, rng: np.random.Generator, strategy: Strategy, m: int = 4000
                   ) -> tuple[np.ndarray, np.ndarray | None]:
        g = self.game
        k, H = g.main.picks, g.main.size
        parts = []
        n_obj = int(m * 0.45) if strategy.objective else 0
        n_anti = int(m * 0.35)
        n_uni = m - n_obj - n_anti
        if n_obj:
            parts.append(_gumbel_topk(rng, 0.6 * number_vector(self.ind.main, strategy.objective), k, n_obj))
        parts.append(_gumbel_topk(rng, -6.0 * self.model.theta, k, n_anti))
        parts.append(_gumbel_topk(rng, np.zeros(H), k, n_uni))
        c = np.vstack(parts) + g.main.low
        e = None
        if g.extra and self.ind.extra is not None:
            E, ke = g.extra.size, g.extra.picks
            tilt = number_vector(self.ind.extra, strategy.objective) if strategy.objective else np.zeros(E)
            theta_e = self.model.theta_extra if self.model.theta_extra is not None else np.zeros(E)
            ep = [
                _gumbel_topk(rng, 0.6 * tilt, ke, n_obj) if n_obj else np.zeros((0, ke), int),
                _gumbel_topk(rng, -6.0 * theta_e, ke, n_anti),
                _gumbel_topk(rng, np.zeros(E), ke, n_uni),
            ]
            e = np.vstack(ep) + g.extra.low
            both = np.hstack([c, e])
            _, uniq = np.unique(both, axis=0, return_index=True)
            return c[uniq].astype(np.int16), e[uniq].astype(np.int16)
        c = np.unique(c, axis=0)
        return c.astype(np.int16), None

    # ---- selection ----------------------------------------------------
    def pick(self, rng: np.random.Generator, strategy: Strategy, balance: float,
             chosen: list[np.ndarray], m: int = 4000, max_overlap: int = 2) -> dict[str, Any]:
        g = self.game
        if strategy.objective is None:
            c = popularity.random_combinations(rng, g.main.size, g.main.picks, 1) + g.main.low - 1
            e = None
            if g.extra:
                e = popularity.random_combinations(rng, g.extra.size, g.extra.picks, 1) + g.extra.low - 1
            s = self.score(c, e)
            return self._result(strategy, balance, c[0], None if e is None else e[0], s, 0, 0.0)

        c, e = self.candidates(rng, strategy, m)
        s = self.score(c, e)
        alpha = slot_alpha(strategy, balance)
        obj = alpha * s[f"pct_{strategy.objective}"] + (1 - alpha) * s["anti"]
        overlap = np.zeros(len(c), dtype=int)
        for prev in chosen:
            ov = np.isin(c, prev).sum(1)
            overlap = np.maximum(overlap, ov)
            obj = obj - 6.0 * ov
        obj = np.where(overlap > max_overlap, -np.inf, obj)
        if not np.isfinite(obj).any():  # extremely unlikely; relax the constraint
            obj = alpha * s[f"pct_{strategy.objective}"] + (1 - alpha) * s["anti"]
        top_n = max(20, len(c) // 100)
        top = np.argsort(-obj)[:top_n]
        w = np.exp((obj[top] - obj[top].max()) / 2.0)
        i = int(rng.choice(top, p=w / w.sum()))
        sub = {key: v[i:i + 1] for key, v in s.items()}
        return self._result(strategy, balance, c[i], None if e is None else e[i], sub,
                            int(overlap[i]), float(obj[i]))

    def pick_many(self, rng: np.random.Generator, strategy: Strategy, balance: float, n: int,
                  m: int = 2000) -> list[dict[str, Any]]:
        """n grids from one candidate pool (used by the backtest, no diversity constraint)."""
        g = self.game
        if strategy.objective is None:
            c = popularity.random_combinations(rng, g.main.size, g.main.picks, n) + g.main.low - 1
            e = None
            if g.extra:
                e = popularity.random_combinations(rng, g.extra.size, g.extra.picks, n) + g.extra.low - 1
            s = self.score(c, e)
            idx = np.arange(n)
        else:
            c, e = self.candidates(rng, strategy, m)
            s = self.score(c, e)
            alpha = slot_alpha(strategy, balance)
            obj = alpha * s[f"pct_{strategy.objective}"] + (1 - alpha) * s["anti"]
            top = np.argsort(-obj)[: max(20, len(c) // 100)]
            w = np.exp((obj[top] - obj[top].max()) / 2.0)
            idx = rng.choice(top, size=n, replace=len(top) < n, p=w / w.sum())
        lp = s["logpop"][idx]
        share = self.model.expected_share(lp)
        return [{
            "numbers": [int(x) for x in c[i]],
            "extras": None if e is None else [int(x) for x in e[i]],
            "anti_score": float(s["anti"][i]),
            "expected_share": float(sh),
        } for i, sh in zip(idx, share)]

    def _result(self, strategy: Strategy, balance: float, c: np.ndarray, e: np.ndarray | None,
                s: dict[str, np.ndarray], overlap: int, objective_value: float) -> dict[str, Any]:
        stat = float(s["pct_composite"][0])
        anti = float(s["anti"][0])
        return {
            "strategy": strategy.key,
            "numbers": [int(x) for x in c],
            "extras": None if e is None else [int(x) for x in e],
            "stat_score": round(stat, 1),
            "anti_score": round(anti, 1),
            "global_score": round(balance * stat + (1 - balance) * anti, 1),
            "details": self.explain(strategy, balance, c, e, s, overlap),
        }

    # ---- explanation --------------------------------------------------
    def explain(self, strategy: Strategy, balance: float, c: np.ndarray, e: np.ndarray | None,
                s: dict[str, np.ndarray], overlap: int) -> dict[str, Any]:
        g = self.game
        m = self.ind.main
        H, k = g.main.size, g.main.picks
        rank_freq = (-m.counts).argsort().argsort() + 1  # 1 = most frequent
        rank_recent = (-m.recent).argsort().argsort() + 1
        ci = c - g.main.low
        c2 = c.reshape(1, -1)
        pop = self.model.explain(c, e)
        nums = [{
            "number": int(n),
            "count": int(m.counts[i]),
            "freq_rank": int(rank_freq[i]),
            "recent_rank": int(rank_recent[i]),
            "gap": int(m.gap[i]),
            "popularity": pop["number_effects"].get(int(n)),
        } for n, i in zip(c, ci)]
        odd = int((c % 2 == 1).sum())
        low = int((c <= H // 2).sum())
        decades: dict[str, int] = {}
        for n in c:
            lo = (int(n) // 10) * 10
            label = f"{max(lo, 1)}-{min(lo + 9, H)}"
            decades[label] = decades.get(label, 0) + 1
        top_q = max(5, H // 3)

        def pl(n: int, word: str) -> str:
            return f"{n} {word}{'s' if n > 1 else ''}"

        def fr(x: float) -> str:
            return f"{x:.2f}".replace(".", ",")

        reasons = []
        if strategy.objective == "freq":
            nb = int((rank_freq[ci] <= top_q).sum())
            reasons.append(f"{nb} sur {k} parmi les {top_q} numéros les plus fréquents des {m.window} derniers tirages")
        elif strategy.objective == "recent":
            nb = int((rank_recent[ci] <= top_q).sum())
            reasons.append(f"{nb} sur {k} parmi les {top_q} numéros les plus présents récemment (moyenne mobile pondérée)")
        elif strategy.objective in ("composite",):
            reasons.append(
                f"Indicateur combiné : fréquence {s['pct_freq'][0]:.0f}/100, tendance {s['pct_recent'][0]:.0f}/100, "
                f"paires {s['pct_pairs'][0]:.0f}/100")
        high31 = int((c > 31).sum())
        if high31:
            reasons.append(f"{pl(high31, 'numéro')} > 31, hors de la plage des dates de naissance")
        else:
            reasons.append("Tous les numéros ≤ 31 : combinaison de type « dates », souvent jouée")
        run = int(max_consecutive_run(c2)[0])
        reasons.append("Aucun numéro consécutif" if run == 1 else f"Plus longue suite : {run} numéros consécutifs")
        rel = pop["relative_popularity"]
        reasons.append(f"Popularité estimée ×{fr(rel)} par rapport à une grille moyenne (estimation)")
        if pop["patterns"]:
            reasons.append("Motifs repérés : " + ", ".join(pop["patterns"]))
        if overlap:
            reasons.append(f"Partage au plus {pl(overlap, 'numéro')} avec les grilles précédentes")
        return {
            "strategy_label": strategy.label,
            "strategy_description": strategy.description,
            "alpha": round(slot_alpha(strategy, balance), 2),
            "scores": {
                "frequence": round(float(s["pct_freq"][0]), 1),
                "tendance": round(float(s["pct_recent"][0]), 1),
                "paires": round(float(s["pct_pairs"][0]), 1),
                "retard": round(float(s["pct_overdue"][0]), 1),
                "composite": round(float(s["pct_composite"][0]), 1),
            },
            "numbers": nums,
            "extras": None if e is None else [{"number": int(x)} for x in e],
            "structure": {
                "sum": int(c.sum()), "odd": odd, "even": k - odd, "low": low, "high": k - low,
                "decades": decades, "max_run": run, "consecutive_pairs": int(consecutive_pairs(c2)[0]),
                "le31": int((c <= 31).sum()),
            },
            "popularity": pop,
            "reasons": reasons,
        }


def generate_grids(engine: Engine, balance: float, seed: int | None = None,
                   slots: tuple[str, ...] = SLOTS, existing: dict[int, list[int]] | None = None,
                   only_slot: int | None = None) -> dict[int, dict[str, Any]]:
    """Generate the 4 complementary grids (or a single slot, avoiding the others)."""
    rng = np.random.default_rng(seed)
    out: dict[int, dict[str, Any]] = {}
    chosen: list[np.ndarray] = []
    if only_slot is not None:
        chosen = [np.array(v) for s, v in (existing or {}).items() if s != only_slot]
        strat = STRATEGIES[slots[only_slot - 1]]
        out[only_slot] = engine.pick(rng, strat, balance, chosen)
        return out
    for i, key in enumerate(slots, start=1):
        res = engine.pick(rng, STRATEGIES[key], balance, chosen)
        out[i] = res
        chosen.append(np.array(res["numbers"]))
    return out
