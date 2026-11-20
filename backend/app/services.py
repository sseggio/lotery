"""Application services: glue between storage, engine and HTTP API.

Engines are cached in memory per game and rebuilt automatically when a new
draw is stored (cache key = last draw id).
"""
from __future__ import annotations

import json
import logging
import secrets
import threading
from datetime import datetime, timezone
from typing import Any

import numpy as np

from .db import Database
from .engine import backtest as bt
from .engine import popularity, stats
from .engine.data import History, load_history
from .engine.generator import SLOTS, STRATEGIES, Engine, generate_grids
from .games import Game

log = logging.getLogger(__name__)


class AppError(Exception):
    """Business error whose message is safe to show to the client."""
    status = 400


class NotFound(AppError):
    status = 404


class Busy(AppError):
    status = 503


class BadRequest(AppError):
    status = 422


# Backtest parameters are whitelisted: bounded CPU cost and bounded cache size.
BACKTEST_DRAWS = (50, 100, 200, 300)
BACKTEST_GRIDS = (5, 10, 20)
BACKTEST_BALANCES = (0.0, 0.25, 0.5, 0.75, 1.0)
MAX_GENERATIONS_KEPT = 500

_engine_cache: dict[str, tuple[int, History, Engine]] = {}
_stats_cache: dict[tuple, Any] = {}
_cache_lock = threading.Lock()
_backtest_lock = threading.Lock()


def _last_id(db: Database, game: Game) -> int:
    last = db.last_draw(game.key)
    return int(last["draw_id"]) if last else -1


def engine_for(db: Database, game: Game) -> tuple[History, Engine]:
    lid = _last_id(db, game)
    with _cache_lock:
        cached = _engine_cache.get(game.key)
        if cached and cached[0] == lid:
            return cached[1], cached[2]
    h = load_history(db, game)
    if len(h) < 30:
        raise NotFound("Pas encore assez de tirages : lancez une actualisation.")
    eng = Engine(h)
    with _cache_lock:
        _engine_cache[game.key] = (lid, h, eng)
        for k in [k for k in _stats_cache if k[0] == game.key and k[1] != lid]:
            del _stats_cache[k]
    return h, eng


def _memo(db: Database, game: Game, name: str, fn) -> Any:
    key = (game.key, _last_id(db, game), name)
    with _cache_lock:
        if key in _stats_cache:
            return _stats_cache[key]
    val = fn()
    with _cache_lock:
        _stats_cache[key] = val
    return val


def _draw_dict(row) -> dict[str, Any]:
    return {
        "draw_id": row["draw_id"],
        "date": row["draw_date"],
        "numbers": json.loads(row["numbers"]),
        "extras": json.loads(row["extras"]) if row["extras"] else None,
        "bonus": row["bonus"],
        "verified": None if row["verified_xlsx"] is None else bool(row["verified_xlsx"]),
    }


def sync_status(db: Database, game: Game) -> dict[str, Any]:
    last_api = db.last_sync(game.key, "api")
    last_ok = db.last_sync(game.key, "api", ok_only=True)
    last_x = db.last_sync(game.key, "xlsx")
    return {
        "last_attempt": None if not last_api else {
            "at": last_api["finished_at"] or last_api["started_at"], "status": last_api["status"],
            "message": last_api["message"], "new_draws": last_api["new_draws"]},
        "last_success_at": last_ok["finished_at"] if last_ok else None,
        "xlsx_check": None if not last_x else {
            "at": last_x["finished_at"] or last_x["started_at"], "status": last_x["status"],
            "message": last_x["message"]},
    }


def summary(db: Database, game: Game) -> dict[str, Any]:
    total = db.count_draws(game.key)
    last = db.last_draw(game.key)
    base: dict[str, Any] = {
        "game": game.key,
        "total_draws": total,
        "last_draw": None,
        "sync": sync_status(db, game),
    }
    if total < 30:
        return base

    def compute():
        h, eng = engine_for(db, game)
        year = stats.window_slice(h, "year")
        table = stats.frequency_table(year, h)
        by_count = sorted(table, key=lambda r: (-r["count"], r["number"]))
        by_gap = sorted(table, key=lambda r: (-r["gap"], r["number"]))
        counts = np.array([r["count"] for r in table])
        dist = stats.distributions(year)
        verified = db.query(
            "SELECT SUM(verified_xlsx=1) AS ok, SUM(verified_xlsx=0) AS ko FROM draws WHERE game=?", (game.key,)
        )[0]
        return {
            "year_draws": len(year),
            "year_from": year.dates[0] if len(year) else None,
            "most_frequent": by_count[:8],
            "least_frequent": list(reversed(by_count[-8:])),
            "overdue": by_gap[:8],
            "recent_draws": [
                {"date": h.dates[i], "numbers": h.mains[i].tolist(),
                 "extras": None if h.extras is None else h.extras[i].tolist(),
                 "bonus": None if h.bonus is None else int(h.bonus[i])}
                for i in range(len(h) - 1, max(-1, len(h) - 6), -1)
            ],
            "chi_square": stats.chi_square_uniformity(counts),
            "sum_mean": dist["sum_mean_observed"],
            "sum_mean_theoretical": dist["sum_mean_theoretical"],
            "odd_mean": round(float((year.mains % 2 == 1).sum(1).mean()), 2),
            "verified_draws": int(verified["ok"] or 0),
            "mismatched_draws": int(verified["ko"] or 0),
            "history_draws": len(h),
            "history_from": h.dates[0],
        }

    base.update(_memo(db, game, "summary", compute))
    base["last_draw"] = _draw_dict(last) if last else None
    return base


def detailed_stats(db: Database, game: Game, window: str) -> dict[str, Any]:
    def compute():
        h, _ = engine_for(db, game)
        w = stats.window_slice(h, window)
        out = {
            "window": window,
            "n_draws": len(w),
            "from": w.dates[0] if len(w) else None,
            "to": w.dates[-1] if len(w) else None,
            "frequencies": stats.frequency_table(w, h),
            "chi_square": stats.chi_square_uniformity(w.indicator("main").sum(0)),
            "evolution": stats.evolution(w, h),
            "heatmap": stats.monthly_heatmap(w),
            "pairs": stats.top_tuples(w, 2, 15),
            "triplets": stats.top_tuples(w, 3, 10),
            "distributions": stats.distributions(w),
            "recurring": stats.recurring_combinations(w),
        }
        if game.extra:
            out["extra_frequencies"] = stats.frequency_table(w, h, "extra")
            out["extra_chi_square"] = stats.chi_square_uniformity(w.indicator("extra").sum(0))
        return out

    return _memo(db, game, f"stats:{window}", compute)


def popularity_info(db: Database, game: Game) -> dict[str, Any]:
    def compute():
        _, eng = engine_for(db, game)
        m = eng.model
        examples = {
            "lotto": [[1, 2, 3, 4, 5, 6], [7, 14, 21, 28, 35, 42], [3, 7, 12, 19, 23, 28], [5, 17, 26, 34, 41, 44]],
            "euromillions": [[1, 2, 3, 4, 5], [7, 14, 21, 28, 35], [3, 7, 12, 19, 23], [29, 36, 41, 44, 48]],
        }[game.key]
        ex = []
        for c in examples:
            arr = np.array(c)
            e = np.array([3, 7]) if game.extra else None
            ex.append({"numbers": c, "extras": None if e is None else e.tolist(), **m.explain(arr, e)})
        return {
            "diagnostics": m.diagnostics,
            "numbers": popularity.number_table(m, game.main.low),
            "extras": None if m.theta_extra is None else [
                {"number": i + 1, "multiplier": round(float(np.exp(t)), 3)} for i, t in enumerate(m.theta_extra)],
            "priors": [{"key": k, "label": popularity.PRIOR_LABELS[k],
                        "log_lift": v if not isinstance(v, dict) else max(v.values())}
                       for k, v in popularity.PRIORS.items()],
            "share_curve": popularity.expected_share_curve(m),
            "examples": ex,
            "boards_typical": round(m.boards_typical),
            "n_combinations": m.n_combinations,
        }

    return _memo(db, game, "popularity", compute)


# ---- generations ------------------------------------------------------
def _grid_dict(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "slot": row["slot"],
        "strategy": row["strategy"],
        "numbers": json.loads(row["numbers"]),
        "extras": json.loads(row["extras"]) if row["extras"] else None,
        "stat_score": row["stat_score"],
        "anti_score": row["anti_score"],
        "global_score": row["global_score"],
        "details": json.loads(row["details"]),
        "favorite": bool(row["favorite"]),
        "created_at": row["created_at"],
    }


def generation_dict(db: Database, gen_row, include_inactive: bool = False) -> dict[str, Any]:
    grids = db.grids_for_generation(gen_row["id"], active_only=not include_inactive)
    last = db.query("SELECT draw_date FROM draws WHERE game=? AND draw_id=?",
                    (gen_row["game"], gen_row["last_draw_id"]))
    return {
        "id": gen_row["id"],
        "game": gen_row["game"],
        "created_at": gen_row["created_at"],
        "balance": gen_row["balance"],
        "last_draw_id": gen_row["last_draw_id"],
        "last_draw_date": last[0]["draw_date"] if last else None,
        "n_draws_used": gen_row["n_draws_used"],
        "grids": [_grid_dict(g) for g in grids],
    }


def new_generation(db: Database, game: Game, balance: float) -> dict[str, Any]:
    h, eng = engine_for(db, game)
    grids = generate_grids(eng, balance, seed=secrets.randbits(63))
    gid = db.create_generation(game.key, balance, int(h.ids[-1]), len(h))
    for slot, g in grids.items():
        db.insert_grid(gid, slot, g)
    db.prune_generations(game.key, MAX_GENERATIONS_KEPT)
    return generation_dict(db, db.get_generation(gid))


def regenerate_slot(db: Database, game: Game, generation_id: int, slot: int, balance: float) -> dict[str, Any]:
    gen = db.get_generation(generation_id)
    if gen is None or gen["game"] != game.key:
        raise NotFound("Génération introuvable")
    h, eng = engine_for(db, game)
    existing = {r["slot"]: json.loads(r["numbers"]) for r in db.grids_for_generation(generation_id)}
    res = generate_grids(eng, balance, seed=secrets.randbits(63), existing=existing, only_slot=slot)
    db.insert_grid(generation_id, slot, res[slot])
    return generation_dict(db, db.get_generation(generation_id))


def latest_generation(db: Database, game: Game) -> dict[str, Any] | None:
    rows = db.generations(game.key, 1)
    return generation_dict(db, rows[0]) if rows else None


def history(db: Database, game: Game, limit: int, offset: int) -> list[dict[str, Any]]:
    return [generation_dict(db, r) for r in db.generations(game.key, limit, offset)]


def score_user_grid(db: Database, game: Game, numbers: list[int], extras: list[int] | None,
                    balance: float) -> dict[str, Any]:
    _, eng = engine_for(db, game)
    c = np.array(sorted(numbers)).reshape(1, -1)
    e = None if extras is None else np.array(sorted(extras)).reshape(1, -1)
    s = eng.score(c, e)
    strat = STRATEGIES["hybride"]
    return eng._result(strat, balance, c[0], None if e is None else e[0], s, 0, 0.0)


# ---- backtest -----------------------------------------------------------
def backtest(db: Database, game: Game, n_test: int, grids_per_draw: int, balance: float,
             wait: bool = False) -> dict[str, Any]:
    if n_test not in BACKTEST_DRAWS or grids_per_draw not in BACKTEST_GRIDS or balance not in BACKTEST_BALANCES:
        raise BadRequest("Paramètres de backtest non autorisés")
    key = f"{game.key}:backtest:{_last_id(db, game)}:{n_test}:{grids_per_draw}:{balance:.2f}"
    cached = db.cache_get(key)
    if cached:
        return cached
    # Never queue requests (each would hold a worker thread): answer "busy" at once.
    if not _backtest_lock.acquire(blocking=wait, timeout=600 if wait else -1):
        raise Busy("Un backtest est déjà en cours de calcul, réessayez dans quelques secondes.")
    try:
        cached = db.cache_get(key)
        if cached:
            return cached
        h = load_history(db, game)
        try:
            res = bt.run_backtest(h, n_test=n_test, grids_per_draw=grids_per_draw, balance=balance)
        except ValueError as exc:
            raise BadRequest("Historique insuffisant pour ce backtest") from exc
        res["computed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        db.cache_set(key, res)
        return res
    finally:
        _backtest_lock.release()


def strategies_info() -> list[dict[str, Any]]:
    return [{"key": s.key, "label": s.label, "description": s.description, "alpha_base": s.alpha_base,
             "slot": SLOTS.index(s.key) + 1 if s.key in SLOTS else None} for s in STRATEGIES.values()]
