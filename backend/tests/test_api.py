import pytest
from fastapi.testclient import TestClient

from app.main import app
from conftest import load_into, synthetic_draws


@pytest.fixture
def client(db, lotto, euromillions):
    load_into(db, lotto, synthetic_draws(lotto, 220, seed=21))
    load_into(db, euromillions, synthetic_draws(euromillions, 220, seed=22))
    return TestClient(app)


def test_health_and_games(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    games = client.get("/api/games").json()
    assert {g["key"] for g in games["games"]} == {"lotto", "euromillions"}


def test_security_headers(client):
    r = client.get("/api/health")
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"


def test_summary_and_stats(client):
    s = client.get("/api/lotto/summary").json()
    assert s["total_draws"] == 220 and s["last_draw"]["numbers"]
    for w in ("year", "30", "all"):
        r = client.get(f"/api/lotto/stats?window={w}")
        assert r.status_code == 200
        assert len(r.json()["frequencies"]) == 45
    assert client.get("/api/lotto/stats?window=7").status_code == 422
    assert client.get("/api/keno/summary").status_code == 422


def test_generate_regenerate_favorite(client):
    gen = client.post("/api/lotto/generate", json={"balance": 0.3}).json()
    assert len(gen["grids"]) == 4
    first = {g["slot"]: g for g in gen["grids"]}
    r = client.post("/api/lotto/generate", json={"balance": 0.3, "generation_id": gen["id"], "slot": 3}).json()
    after = {g["slot"]: g for g in r["grids"]}
    assert len(after) == 4
    assert after[1]["id"] == first[1]["id"] and after[3]["id"] != first[3]["id"]
    gid = after[2]["id"]
    assert client.post(f"/api/grids/{gid}/favorite", json={"favorite": True}).status_code == 200
    favs = client.get("/api/lotto/favorites").json()
    assert [f["id"] for f in favs] == [gid]
    hist = client.get("/api/lotto/generations").json()
    assert hist[0]["id"] == gen["id"]
    assert client.get("/api/lotto/generations/latest").json()["id"] == gen["id"]


def test_generate_validation(client):
    assert client.post("/api/lotto/generate", json={"balance": 2}).status_code == 422
    assert client.post("/api/lotto/generate", json={"slot": 9, "generation_id": 1}).status_code == 422
    assert client.post("/api/lotto/generate", json={"slot": 1}).status_code == 422
    assert client.post("/api/lotto/generate", json={"slot": 1, "generation_id": 999}).status_code == 404
    assert client.post("/api/grids/999/favorite", json={"favorite": True}).status_code == 404


def test_score_user_grid(client):
    r = client.post("/api/lotto/score", json={"numbers": [1, 2, 3, 4, 5, 6]})
    assert r.status_code == 200 and r.json()["anti_score"] < 5
    assert client.post("/api/lotto/score", json={"numbers": [1, 2, 3, 4, 5, 5]}).status_code == 422
    assert client.post("/api/lotto/score", json={"numbers": [1, 2, 3, 4, 5, 46]}).status_code == 422
    assert client.post("/api/euromillions/score", json={"numbers": [1, 2, 3, 4, 5]}).status_code == 422
    ok = client.post("/api/euromillions/score", json={"numbers": [1, 2, 3, 4, 5], "extras": [1, 2]})
    assert ok.status_code == 200


def test_backtest_bounds(client):
    assert client.get("/api/lotto/backtest?n_draws=5000").status_code == 422
    assert client.get("/api/lotto/backtest?grids_per_draw=500").status_code == 422
    assert client.get("/api/lotto/backtest?n_draws=73&grids_per_draw=5").status_code == 422  # not whitelisted
    r = client.get("/api/lotto/backtest?n_draws=50&grids_per_draw=5")
    assert r.status_code == 200
    assert {x["strategy"] for x in r.json()["results"]} >= {"aleatoire", "anti_partage"}


def test_popularity_endpoint(client):
    r = client.get("/api/lotto/popularity").json()
    assert len(r["numbers"]) == 45 and r["examples"]


def test_basic_auth(client, monkeypatch):
    from app import main

    try:
        object.__setattr__(main.settings, "basic_auth_user", "u")
        object.__setattr__(main.settings, "basic_auth_password", "p")
        assert client.get("/api/games").status_code == 401
        assert client.get("/api/games", auth=("u", "bad")).status_code == 401
        assert client.get("/api/games", auth=("u", "p")).status_code == 200
        assert client.get("/api/health").status_code == 200
        # Regression: a forged Host header must not bypass authentication.
        assert client.get("/api/games", headers={"Host": "x/api/health?"}).status_code in (400, 401)
        r401 = client.get("/api/games")
        assert "frame-ancestors" in r401.headers.get("content-security-policy", "")
    finally:
        object.__setattr__(main.settings, "basic_auth_user", "")
        object.__setattr__(main.settings, "basic_auth_password", "")


def test_post_rate_limit(client, monkeypatch):
    from app import main

    main._hits.clear()
    object.__setattr__(main.settings, "post_rate_per_min", 3)
    try:
        codes = [client.post("/api/grids/999/favorite", json={"favorite": True}).status_code for _ in range(5)]
        assert codes[:3] == [404, 404, 404] and codes[3:] == [429, 429]
    finally:
        object.__setattr__(main.settings, "post_rate_per_min", 40)
        main._hits.clear()


def test_history_is_pruned(db, lotto):
    from app import services
    from conftest import load_into, synthetic_draws

    load_into(db, lotto, synthetic_draws(lotto, 120, seed=3))
    for _ in range(4):
        services.new_generation(db, lotto, 0.5)
    db.prune_generations(lotto.key, 2)
    assert len(db.generations(lotto.key, 50)) == 2
