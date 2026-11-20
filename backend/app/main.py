"""HTTP API (FastAPI) + static frontend.

Layers: ingest/ (data retrieval) -> db.py (storage) -> engine/ (statistics)
-> services.py (use cases) -> main.py (HTTP). The frontend only talks to /api.
"""
from __future__ import annotations

import base64
import logging
import secrets
import threading
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import Body, FastAPI, HTTPException, Path, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import services
from .config import settings
from .db import get_db
from .games import GAMES
from .ingest import sync as sync_mod

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("lotery")

GameKey = Literal["lotto", "euromillions"]
Window = Literal["year", "30", "60", "90", "all"]


def _startup_tasks() -> None:
    db = get_db()
    for game in GAMES.values():
        try:
            sync_mod.repair_tiers_from_raw(db, game)
            sync_mod.sync_game(db, game, trigger="startup")
        except Exception:  # never prevent the app from starting
            log.exception("startup sync failed for %s", game.key)
    # Warm the default backtest so the comparison page is instant.
    for game in GAMES.values():
        try:
            services.backtest(db, game, 100, 10, 0.5)
        except Exception:
            log.exception("backtest warm-up failed for %s", game.key)


def _start_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    sched = BackgroundScheduler(timezone=settings.timezone)

    def job(game_key: str) -> None:
        try:
            res = sync_mod.sync_game(get_db(), GAMES[game_key], trigger="scheduler")
            if res.get("new_draws"):
                services.backtest(get_db(), GAMES[game_key], 100, 10, 0.5)
        except Exception:
            log.exception("scheduled sync failed")

    # Results are published within about an hour of the draw (Lotto ~20:00, EuroMillions ~21:00).
    sched.add_job(job, CronTrigger(day_of_week="wed,sat", hour="21,23", minute=5), args=["lotto"])
    sched.add_job(job, CronTrigger(day_of_week="tue,fri", hour="22,23", minute=35), args=["euromillions"])
    for key in GAMES:  # daily catch-up
        sched.add_job(job, CronTrigger(hour=9, minute=10), args=[key])
    sched.start()
    return sched


@asynccontextmanager
async def lifespan(app: FastAPI):
    sched = None
    if settings.scheduler_enabled:
        threading.Thread(target=_startup_tasks, daemon=True, name="startup-sync").start()
        sched = _start_scheduler()
    yield
    if sched:
        sched.shutdown(wait=False)


app = FastAPI(title="Lotery — analyse statistique Loterie Nationale", lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)


# ---- middleware: auth + security headers --------------------------------
CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
       "font-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
       "base-uri 'self'; form-action 'self'")


@app.middleware("http")
async def security(request: Request, call_next):
    if settings.basic_auth_user and settings.basic_auth_password and request.url.path != "/api/health":
        ok = False
        header = request.headers.get("authorization", "")
        if header.lower().startswith("basic "):
            try:
                user, _, pwd = base64.b64decode(header[6:]).decode("utf-8").partition(":")
                ok = secrets.compare_digest(user.encode(), settings.basic_auth_user.encode()) & \
                    secrets.compare_digest(pwd.encode(), settings.basic_auth_password.encode())
            except (ValueError, UnicodeDecodeError):
                ok = False
        if not ok:
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="lotery"'})
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Erreur interne"})


def _game(key: str):
    return GAMES[key]


async def _call(fn, *args):
    try:
        return await run_in_threadpool(fn, *args)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---- API ------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/games")
def games():
    out = []
    for g in GAMES.values():
        out.append({
            "key": g.key, "label": g.label,
            "main": {"name": g.main.name, "low": g.main.low, "high": g.main.high, "picks": g.main.picks},
            "extra": None if not g.extra else {"name": g.extra.name, "low": g.extra.low, "high": g.extra.high,
                                               "picks": g.extra.picks},
            "has_bonus": g.has_bonus,
            "price_eur": g.base_price_cents / 100,
            "draw_weekdays": list(g.draw_weekdays),
            "tiers": list(g.tier_names),
            "n_combinations": g.n_combinations,
            "jackpot_probability": 1 / g.n_combinations,
        })
    return {"games": out, "strategies": services.strategies_info()}


@app.get("/api/{game}/summary")
async def summary(game: Annotated[GameKey, Path()]):
    return await _call(services.summary, get_db(), _game(game))


@app.get("/api/{game}/stats")
async def stats(game: Annotated[GameKey, Path()], window: Window = "year"):
    return await _call(services.detailed_stats, get_db(), _game(game), window)


@app.get("/api/{game}/draws")
def draws(game: Annotated[GameKey, Path()], limit: Annotated[int, Query(ge=1, le=200)] = 50,
          offset: Annotated[int, Query(ge=0, le=100000)] = 0):
    db = get_db()
    rows = db.list_draws(game, limit, offset)
    return {"total": db.count_draws(game), "draws": [services._draw_dict(r) for r in rows]}


@app.post("/api/{game}/sync")
async def sync(game: Annotated[GameKey, Path()]):
    db = get_db()
    try:
        res = await run_in_threadpool(sync_mod.sync_game, db, _game(game), "manual")
    except sync_mod.SyncThrottled as exc:
        raise HTTPException(status_code=429, detail=str(exc), headers={"Retry-After": str(exc.retry_after)})
    except sync_mod.SyncBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    res["sync"] = services.sync_status(db, _game(game))
    if res["status"] == "error":
        return JSONResponse(status_code=502, content={"detail": res["message"], **res})
    return res


@app.get("/api/{game}/sync")
def sync_status(game: Annotated[GameKey, Path()]):
    return services.sync_status(get_db(), _game(game))


class GenerateRequest(BaseModel):
    balance: float = Field(0.5, ge=0.0, le=1.0)
    generation_id: int | None = Field(None, ge=1)
    slot: int | None = Field(None, ge=1, le=4)


@app.post("/api/{game}/generate")
async def generate(game: Annotated[GameKey, Path()], req: GenerateRequest = Body(default_factory=GenerateRequest)):
    g = _game(game)
    if req.slot is not None:
        if req.generation_id is None:
            raise HTTPException(status_code=422, detail="generation_id requis pour régénérer une grille")
        return await _call(services.regenerate_slot, get_db(), g, req.generation_id, req.slot, req.balance)
    return await _call(services.new_generation, get_db(), g, req.balance)


@app.get("/api/{game}/generations/latest")
async def latest(game: Annotated[GameKey, Path()]):
    return await _call(services.latest_generation, get_db(), _game(game))


@app.get("/api/{game}/generations")
async def generations(game: Annotated[GameKey, Path()], limit: Annotated[int, Query(ge=1, le=50)] = 20,
                      offset: Annotated[int, Query(ge=0, le=100000)] = 0):
    return await _call(services.history, get_db(), _game(game), limit, offset)


class FavoriteRequest(BaseModel):
    favorite: bool


@app.post("/api/grids/{grid_id}/favorite")
def favorite(grid_id: Annotated[int, Path(ge=1)], req: FavoriteRequest):
    if not get_db().set_favorite(grid_id, req.favorite):
        raise HTTPException(status_code=404, detail="Grille introuvable")
    return {"id": grid_id, "favorite": req.favorite}


@app.get("/api/{game}/favorites")
def favorites(game: Annotated[GameKey, Path()]):
    return [services._grid_dict(r) | {"last_draw_id": r["last_draw_id"]} for r in get_db().favorites(game)]


class ScoreRequest(BaseModel):
    numbers: list[int] = Field(min_length=1, max_length=10)
    extras: list[int] | None = Field(None, max_length=4)
    balance: float = Field(0.5, ge=0.0, le=1.0)

    @field_validator("numbers", "extras")
    @classmethod
    def distinct(cls, v):
        if v is not None and len(set(v)) != len(v):
            raise ValueError("numéros en double")
        return v


@app.post("/api/{game}/score")
async def score(game: Annotated[GameKey, Path()], req: ScoreRequest):
    g = _game(game)
    if len(req.numbers) != g.main.picks or any(not g.main.low <= n <= g.main.high for n in req.numbers):
        raise HTTPException(422, f"{g.main.picks} numéros distincts entre {g.main.low} et {g.main.high} requis")
    if g.extra:
        if not req.extras or len(req.extras) != g.extra.picks or any(
                not g.extra.low <= n <= g.extra.high for n in req.extras):
            raise HTTPException(422, f"{g.extra.picks} étoiles distinctes entre 1 et {g.extra.high} requises")
    elif req.extras:
        raise HTTPException(422, "Ce jeu n'a pas d'étoiles")
    return await _call(services.score_user_grid, get_db(), g, req.numbers, req.extras, req.balance)


@app.get("/api/{game}/popularity")
async def popularity(game: Annotated[GameKey, Path()]):
    return await _call(services.popularity_info, get_db(), _game(game))


@app.get("/api/{game}/backtest")
async def backtest(game: Annotated[GameKey, Path()],
                   n_draws: Annotated[int, Query(ge=20, le=300)] = 100,
                   grids_per_draw: Annotated[int, Query(ge=1, le=20)] = 10,
                   balance: Annotated[float, Query(ge=0.0, le=1.0)] = 0.5):
    balance = round(balance * 4) / 4  # 5 cache-friendly levels
    return await _call(services.backtest, get_db(), _game(game), n_draws, grids_per_draw, balance)


# ---- static frontend (SPA) ----------------------------------------------------
_static = settings.static_dir.resolve()
if (_static / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=_static / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404)
        candidate = (_static / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(_static):
            return FileResponse(candidate)
        return FileResponse(_static / "index.html")
