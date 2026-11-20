"""In-memory, numpy-friendly view of the draw history.

`History` is immutable and always chronological. `History.before(i)` returns
the draws strictly preceding index `i`: the backtest only ever hands this
truncated view to the strategies, which is what prevents look-ahead leakage.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import numpy as np

from ..db import Database
from ..games import Game


@dataclass(frozen=True)
class History:
    game: Game
    ids: np.ndarray            # (N,) official draw ids
    times: np.ndarray          # (N,) epoch ms
    dates: tuple[str, ...]     # (N,) local dates
    mains: np.ndarray          # (N, k) sorted main numbers
    extras: np.ndarray | None  # (N, e) sorted stars (EuroMillions)
    bonus: np.ndarray | None   # (N,) Lotto bonus
    boards: np.ndarray         # (N,) estimated boards sold in Belgium (NaN if unknown)
    tiers: dict[int, dict[str, tuple[int, int, int | None]]] = field(default_factory=dict)  # id -> tier -> (winners BE, amount cents, winners all countries)

    def __len__(self) -> int:
        return len(self.ids)

    def before(self, i: int) -> "History":
        """Draws with index < i (strictly in the past of draw i)."""
        return History(
            self.game, self.ids[:i], self.times[:i], self.dates[:i], self.mains[:i],
            None if self.extras is None else self.extras[:i],
            None if self.bonus is None else self.bonus[:i],
            self.boards[:i], self.tiers,
        )

    def last(self, n: int) -> "History":
        start = max(0, len(self) - n)
        return History(
            self.game, self.ids[start:], self.times[start:], self.dates[start:], self.mains[start:],
            None if self.extras is None else self.extras[start:],
            None if self.bonus is None else self.bonus[start:],
            self.boards[start:], self.tiers,
        )

    def since_date(self, iso_date: str) -> "History":
        idx = next((i for i, d in enumerate(self.dates) if d >= iso_date), len(self))
        return self.last(len(self) - idx)

    def indicator(self, pool: str = "main") -> np.ndarray:
        """(N, H) 0/1 matrix: entry [d, n-1] = 1 if number n was drawn at draw d."""
        arr = self.mains if pool == "main" else self.extras
        p = self.game.main if pool == "main" else self.game.extra
        assert arr is not None and p is not None
        m = np.zeros((len(arr), p.size), dtype=np.int8)
        if len(arr):
            rows = np.repeat(np.arange(len(arr)), arr.shape[1])
            m[rows, arr.ravel() - p.low] = 1
        return m


def load_history(db: Database, game: Game) -> History:
    rows = db.all_draws(game.key)
    k = game.main.picks
    mains = np.array([json.loads(r["numbers"]) for r in rows], dtype=np.int16).reshape(-1, k)
    extras = None
    if game.extra:
        extras = np.array([json.loads(r["extras"]) for r in rows], dtype=np.int16).reshape(-1, game.extra.picks)
    bonus = np.array([r["bonus"] or 0 for r in rows], dtype=np.int16) if game.has_bonus else None
    boards = np.array(
        [(r["total_sales"] / r["base_price"]) if r["total_sales"] and r["base_price"] else np.nan for r in rows],
        dtype=float,
    )
    tiers: dict[int, dict[str, tuple[int, int, int | None]]] = {}
    for t in db.tiers_for_game(game.key):
        tiers.setdefault(t["draw_id"], {})[t["tier"]] = (t["winners"], t["amount"], t["winners_global"])
    return History(
        game=game,
        ids=np.array([r["draw_id"] for r in rows], dtype=np.int64),
        times=np.array([r["draw_time"] for r in rows], dtype=np.int64),
        dates=tuple(r["draw_date"] for r in rows),
        mains=mains, extras=extras, bonus=bonus, boards=boards, tiers=tiers,
    )
