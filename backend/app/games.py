"""Official game rules for the supported Loterie Nationale draw games.

The rules are cross-checked at runtime against the `gameRuleSet` returned by the
official API (see `ingest/natlot.py`): if the operator changes a rule
(e.g. number range), the parser rejects the draw instead of silently storing
inconsistent data.

Lotto (Belgium)
    Player picks 6 distinct numbers in 1..45. The draw picks 6 numbers plus one
    bonus number from the *same* drum (so the bonus is distinct from the 6).
    The bonus is never chosen by the player: it only upgrades prize ranks.
    Ranks: 6, 5+1, 5, 4+1, 4, 3+1, 3, 2+1, 1+1 ("+1" = player holds the bonus).
    Draws: Wednesday and Saturday evening. Board price: EUR 1.50.

EuroMillions
    Player picks 5 distinct numbers in 1..50 and 2 distinct "stars" in 1..12.
    13 prize ranks from 5+2 down to 2+0. Draws: Tuesday and Friday evening.
    Board price: EUR 2.50.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import comb


@dataclass(frozen=True)
class Pool:
    """A drum of numbers from which the player picks `picks` distinct values."""

    name: str
    low: int
    high: int
    picks: int

    @property
    def size(self) -> int:
        return self.high - self.low + 1

    @property
    def n_combinations(self) -> int:
        return comb(self.size, self.picks)


@dataclass(frozen=True)
class Game:
    key: str  # URL-safe identifier used by our API
    label: str
    api_name: str  # value of `game-names` on the official API
    main: Pool
    extra: Pool | None  # second pool chosen by the player (EuroMillions stars)
    has_bonus: bool  # bonus drawn from the main drum, not chosen by the player
    base_price_cents: int
    draw_weekdays: tuple[int, ...]  # Monday=0
    # Columns of the official paper slip, used by the visual-pattern feature of
    # the popularity model. Several layouts are evaluated (see popularity.py).
    slip_columns: tuple[int, ...]
    xlsx_slug: str | None = None  # name used in the official statistics xlsx

    @property
    def n_combinations(self) -> int:
        n = self.main.n_combinations
        if self.extra:
            n *= self.extra.n_combinations
        return n

    # ---- prize ranks ---------------------------------------------------
    def tier_name(self, main_hits: int, extra_hits: int) -> str | None:
        """Return the official rank name for a result, or None if no prize.

        For Lotto, `extra_hits` is 1 if the player's grid contains the bonus.
        """
        if self.key == "lotto":
            if main_hits == 6:
                return "6"
            if main_hits == 5:
                return "5+1" if extra_hits else "5"
            if main_hits in (4, 3):
                return f"{main_hits}+1" if extra_hits else str(main_hits)
            if main_hits in (2, 1) and extra_hits:
                return f"{main_hits}+1"
            return None
        name = f"{main_hits}+{extra_hits}"
        return name if name in self.tier_names else None

    @property
    def tier_names(self) -> tuple[str, ...]:
        if self.key == "lotto":
            return ("6", "5+1", "5", "4+1", "4", "3+1", "3", "2+1", "1+1")
        return ("5+2", "5+1", "5+0", "4+2", "4+1", "3+2", "4+0", "2+2", "3+1", "3+0", "1+2", "2+1", "2+0")

    def tier_probabilities(self) -> dict[str, float]:
        """Exact probability of each rank for one board (uniform random draw)."""
        probs: dict[str, float] = {}
        m = self.main
        total_main = comb(m.size, m.picks)
        if self.key == "lotto":
            others = m.size - m.picks  # numbers not drawn among the 6 (39)
            for hits in range(m.picks + 1):
                p_hits = comb(m.picks, hits) * comb(others, m.picks - hits) / total_main
                # The bonus is uniform among the 39 non-drawn numbers; the player
                # holds (6 - hits) of them.
                p_bonus = (m.picks - hits) / others
                for b, pb in ((1, p_bonus), (0, 1 - p_bonus)):
                    name = self.tier_name(hits, b)
                    if name:
                        probs[name] = probs.get(name, 0.0) + p_hits * pb
            return probs
        assert self.extra is not None
        e = self.extra
        for hits in range(m.picks + 1):
            p_m = comb(m.picks, hits) * comb(m.size - m.picks, m.picks - hits) / total_main
            for s in range(e.picks + 1):
                p_s = comb(e.picks, s) * comb(e.size - e.picks, e.picks - s) / comb(e.size, e.picks)
                name = self.tier_name(hits, s)
                if name:
                    probs[name] = p_m * p_s
        return probs


LOTTO = Game(
    key="lotto",
    label="Lotto",
    api_name="Lotto",
    main=Pool("Numéros", 1, 45, 6),
    extra=None,
    has_bonus=True,
    base_price_cents=150,
    draw_weekdays=(2, 5),
    slip_columns=(5, 7, 9),
    xlsx_slug="lotto",
)

EUROMILLIONS = Game(
    key="euromillions",
    label="EuroMillions",
    api_name="Euro Millions",
    main=Pool("Numéros", 1, 50, 5),
    extra=Pool("Étoiles", 1, 12, 2),
    has_bonus=False,
    base_price_cents=250,
    draw_weekdays=(1, 4),
    slip_columns=(5, 10),
)

GAMES: dict[str, Game] = {g.key: g for g in (LOTTO, EUROMILLIONS)}


def get_game(key: str) -> Game:
    try:
        return GAMES[key]
    except KeyError as exc:  # pragma: no cover - guarded by API validation
        raise ValueError(f"Unknown game {key!r}") from exc
