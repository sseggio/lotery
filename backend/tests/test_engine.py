from math import comb

import numpy as np
import pytest

from app.engine import popularity, stats
from app.engine.backtest import run_backtest
from app.engine.data import load_history
from app.engine.features import consecutive_pairs, longest_equal_step, max_consecutive_run
from app.engine.generator import SLOTS, Engine, generate_grids
from conftest import load_into, synthetic_draws


# ---- official rules ---------------------------------------------------------
def test_lotto_rules(lotto):
    assert lotto.main.n_combinations == 8_145_060
    p = lotto.tier_probabilities()
    assert p["6"] == pytest.approx(1 / 8_145_060)
    assert p["5+1"] == pytest.approx(6 / 8_145_060)  # 6 ways to drop one number and hold the bonus
    assert set(p) == set(lotto.tier_names)
    assert lotto.tier_name(2, 0) is None and lotto.tier_name(1, 1) == "1+1"


def test_euromillions_rules(euromillions):
    assert euromillions.n_combinations == 139_838_160
    p = euromillions.tier_probabilities()
    assert p["5+2"] == pytest.approx(1 / 139_838_160)
    assert len(p) == 13


# ---- features & descriptive statistics --------------------------------------
def test_features():
    c = np.array([[1, 2, 3, 4, 5, 6], [3, 10, 17, 24, 31, 38], [1, 5, 9, 20, 33, 44]])
    assert max_consecutive_run(c).tolist() == [6, 1, 1]
    assert consecutive_pairs(c).tolist() == [5, 0, 0]
    assert longest_equal_step(c).tolist() == [6, 6, 3]


@pytest.fixture
def hist(db, lotto):
    load_into(db, lotto, synthetic_draws(lotto, 260, seed=3))
    return load_history(db, lotto)


def test_frequencies_and_gaps(hist):
    table = stats.frequency_table(hist, hist)
    assert sum(r["count"] for r in table) == len(hist) * 6
    n = 17
    idx = np.flatnonzero((hist.mains == n).any(1))
    assert table[n - 1]["gap"] == len(hist) - 1 - idx[-1]
    chi = stats.chi_square_uniformity(np.array([r["count"] for r in table]))
    assert 0 <= chi["p_value"] <= 1


def test_tuples_expected(hist):
    pairs = stats.top_tuples(hist, 2, 5)
    assert pairs[0]["expected"] == pytest.approx(len(hist) * comb(43, 4) / comb(45, 6), abs=0.01)
    assert pairs[0]["count"] >= pairs[-1]["count"]


def test_distributions_sum_to_100(hist):
    d = stats.distributions(hist)
    assert sum(x["theoretical_pct"] for x in d["odd_even"]) == pytest.approx(100, abs=0.5)
    assert sum(x["observed"] for x in d["odd_even"]) == len(hist)


# ---- grid generation: compliance with the official rules -------------------
@pytest.mark.parametrize("game_key", ["lotto", "euromillions"])
def test_generated_grids_respect_rules(db, game_key):
    from app.games import GAMES

    g = GAMES[game_key]
    load_into(db, g, synthetic_draws(g, 200, seed=5))
    eng = Engine(load_history(db, g), ref_size=3000)
    for seed in range(15):
        for balance in (0.0, 0.5, 1.0):
            grids = generate_grids(eng, balance, seed=seed)
            assert len(grids) == 4
            seen = set()
            for slot, gr in grids.items():
                nums = gr["numbers"]
                assert len(nums) == g.main.picks == len(set(nums))
                assert all(g.main.low <= n <= g.main.high for n in nums)
                assert nums == sorted(nums)
                if g.extra:
                    assert len(gr["extras"]) == g.extra.picks == len(set(gr["extras"]))
                    assert all(g.extra.low <= n <= g.extra.high for n in gr["extras"])
                else:
                    assert gr["extras"] is None
                assert 0 <= gr["stat_score"] <= 100 and 0 <= gr["anti_score"] <= 100
                assert gr["strategy"] == SLOTS[slot - 1]
                assert gr["details"]["reasons"]
                seen.add(tuple(nums))
            assert len(seen) == 4  # 4 different grids
            vals = [set(x["numbers"]) for x in grids.values()]
            for i in range(4):
                for j in range(i + 1, 4):
                    assert len(vals[i] & vals[j]) <= 2  # diversity constraint


def test_regenerate_single_slot_avoids_others(db, lotto):
    load_into(db, lotto, synthetic_draws(lotto, 200, seed=6))
    eng = Engine(load_history(db, lotto), ref_size=3000)
    grids = generate_grids(eng, 0.5, seed=1)
    existing = {s: g["numbers"] for s, g in grids.items()}
    for seed in range(10):
        new = generate_grids(eng, 0.5, seed=100 + seed, existing=existing, only_slot=2)
        assert list(new) == [2]
        for s in (1, 3, 4):
            assert len(set(new[2]["numbers"]) & set(existing[s])) <= 2


def test_balance_moves_scores(db, lotto):
    load_into(db, lotto, synthetic_draws(lotto, 200, seed=8))
    eng = Engine(load_history(db, lotto), ref_size=3000)
    stat_heavy = np.mean([g["stat_score"] for s in range(8) for g in generate_grids(eng, 1.0, seed=s).values()])
    anti_heavy = np.mean([g["anti_score"] for s in range(8) for g in generate_grids(eng, 0.0, seed=s).values()])
    anti_of_stat = np.mean([g["anti_score"] for s in range(8) for g in generate_grids(eng, 1.0, seed=s).values()])
    assert anti_heavy > anti_of_stat
    assert stat_heavy > 60


# ---- popularity model ----------------------------------------------------------
def test_popularity_patterns_and_share(db, lotto):
    load_into(db, lotto, synthetic_draws(lotto, 120, seed=9))
    m = popularity.fit(load_history(db, lotto), ref_size=5000)
    c = np.array([[1, 2, 3, 4, 5, 6], [5, 17, 26, 34, 41, 44]])
    lp = m.log_popularity(c)
    assert lp[0] > lp[1] + 5  # the famous sequence is far more popular
    a = m.anti_score(lp)
    assert a[0] < 1 and 0 <= a[1] <= 100
    share = m.expected_share(lp)
    assert share[0] < share[1] <= 1  # more popular -> smaller expected jackpot share


def test_popularity_recovers_planted_preferences(db, lotto):
    theta = np.zeros(45)
    theta[6] = 0.6      # number 7 strongly overplayed
    theta[44] = -0.5    # number 45 underplayed
    load_into(db, lotto, synthetic_draws(lotto, 500, seed=11, theta=theta))
    m = popularity.fit(load_history(db, lotto), ref_size=3000)
    assert m.diagnostics["estimated"]
    assert np.argmax(m.theta) == 6
    assert np.argmin(m.theta) == 44
    assert m.theta[6] > 0.3 and m.theta[44] < -0.25


# ---- backtest: no look-ahead ---------------------------------------------------
def test_backtest_has_no_lookahead(db, lotto):
    """Changing FUTURE draws must not change what was generated for earlier dates."""
    raws = synthetic_draws(lotto, 200, seed=12)
    load_into(db, lotto, raws)
    h = load_history(db, lotto)
    r1 = run_backtest(h, n_test=20, grids_per_draw=3, min_history=150, seed=1,
                      strategies=("aleatoire", "frequence"))
    # Tamper with the last 5 draws only.
    tampered = h.mains.copy()
    tampered[-5:] = np.array([[1, 2, 3, 4, 5, 6]] * 5)
    from dataclasses import replace
    h2 = replace(h, mains=tampered)
    r2 = run_backtest(h2, n_test=20, grids_per_draw=3, min_history=150, seed=1,
                      strategies=("aleatoire", "frequence"))
    for a, b in zip(r1["results"], r2["results"]):
        # cumulative mean over the first 15 test draws is identical
        assert a["cumulative_mean"][:15] == b["cumulative_mean"][:15]


def test_backtest_random_matches_theory(db, lotto):
    load_into(db, lotto, synthetic_draws(lotto, 300, seed=13))
    r = run_backtest(load_history(db, lotto), n_test=120, grids_per_draw=10, min_history=150,
                     strategies=("aleatoire", "frequence"))
    assert r["theoretical_mean_hits"] == pytest.approx(0.8)
    for x in r["results"]:
        assert abs(x["mean_hits"] - 0.8) < 0.15
        assert x["ci95"][0] < x["mean_hits"] < x["ci95"][1]
