"""Shared fixtures.

The tests never touch the network. Draws used here are SYNTHETIC (seeded random
numbers) and only live in throw-away in-memory databases: they are never shown
by the application, which only displays official data.
"""
from __future__ import annotations

import json
import os
from math import comb

import numpy as np
import pytest

os.environ.setdefault("SCHEDULER_ENABLED", "0")
os.environ.setdefault("STATIC_DIR", "/nonexistent")

from app.db import Database, set_db  # noqa: E402
from app.games import GAMES, Game  # noqa: E402


def make_raw(game: Game, draw_id: int, t_ms: int, nums, extras=None, bonus=None, sales=300_000_000,
             tiers=None, pad_drawtype=False):
    results = [{"primary": [str(n) for n in nums], "drawType": "normal"}]
    if extras is not None:
        results[0]["secondary"] = [str(n) for n in extras]
    if bonus is not None:
        results.append({"primary": [str(bonus)], "drawType": "bonus"})
    dt = "Regular " if pad_drawtype else "Regular"
    return {
        "gameName": game.api_name, "id": str(draw_id), "status": "PAYABLE", "drawTime": t_ms,
        "totalSales": sales, "totalWagersSold": 1000,
        "gameRuleSet": {"basePrice": game.base_price_cents, "primarySelectionsHighNumber": game.main.high},
        "results": results,
        "prizeTiers": [{"name": f"  {k}" if len(k) == 1 else k, "shareCount": v, "shareAmount": 100,
                        "drawType": dt, "globalShareCount": v * 5 if game.extra else 0}
                       for k, v in (tiers or {}).items()],
    }


def synthetic_draws(game: Game, n: int, seed: int = 0, theta: np.ndarray | None = None):
    """n chronological synthetic raw draws. If `theta` is given, winners on the
    middle ranks are simulated from a planted per-number popularity."""
    rng = np.random.default_rng(seed)
    probs = game.tier_probabilities()
    t0 = 1_600_000_000_000
    out = []
    for i in range(n):
        nums = sorted(rng.choice(np.arange(1, game.main.high + 1), game.main.picks, replace=False).tolist())
        extras = bonus = None
        if game.extra:
            extras = sorted(rng.choice(np.arange(1, game.extra.high + 1), game.extra.picks, replace=False).tolist())
        if game.has_bonus:
            rest = [x for x in range(1, game.main.high + 1) if x not in nums]
            bonus = int(rng.choice(rest))
        boards = 2_000_000
        tiers = {}
        lift = 1.0
        if theta is not None:
            # rank-m winners carry ~ m/k of the drawn numbers' log-popularity
            lift_full = float(np.sum(theta[np.array(nums) - 1]))
        for name, p in probs.items():
            m = int(name[0])
            lam = boards * p
            if theta is not None:
                lam *= np.exp(lift_full * m / game.main.picks)
            tiers[name] = int(rng.poisson(lam * lift))
        out.append(make_raw(game, 1000 + i, t0 + i * 3 * 86_400_000, nums, extras, bonus,
                            sales=boards * game.base_price_cents, tiers=tiers))
    return out


@pytest.fixture
def db():
    d = Database(":memory:")
    set_db(d)
    return d


@pytest.fixture
def lotto():
    return GAMES["lotto"]


@pytest.fixture
def euromillions():
    return GAMES["euromillions"]


def load_into(db: Database, game: Game, raws) -> None:
    from app.ingest.natlot import parse_draw

    for r in raws:
        db.insert_draw(parse_draw(r, game))


__all__ = ["make_raw", "synthetic_draws", "load_into", "comb", "json"]
