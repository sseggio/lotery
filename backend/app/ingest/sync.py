"""Synchronisation service: incremental, idempotent, logged.

* Initial run: backfill from `HISTORY_START_YEAR` to now.
* Later runs: only fetch from the last stored draw (minus a 2-day safety
  margin); duplicates are ignored by the primary key, so nothing already
  stored is re-inserted.
* Every run is recorded in `sync_log` (status, new draws, error message), which
  feeds the "last synchronisation" indicator and error banners in the UI.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import date, datetime, timedelta, timezone

from ..config import settings
from ..db import Database
from ..games import Game
from . import natlot, xlsx_verify

log = logging.getLogger(__name__)

_locks: dict[str, threading.Lock] = {}
_last_manual: dict[str, float] = {}
_guard = threading.Lock()


class SyncThrottled(RuntimeError):
    def __init__(self, retry_after: int) -> None:
        super().__init__(f"Synchronisation récente, réessayez dans {retry_after} s")
        self.retry_after = retry_after


class SyncBusy(RuntimeError):
    pass


def _lock_for(game: str) -> threading.Lock:
    with _guard:
        return _locks.setdefault(game, threading.Lock())


def sync_game(db: Database, game: Game, trigger: str = "manual", client=None) -> dict:
    """Fetch new draws for a game. Raises SyncThrottled / SyncBusy for manual abuse."""
    if trigger == "manual":
        with _guard:
            elapsed = time.monotonic() - _last_manual.get(game.key, -1e9)
            if elapsed < settings.sync_min_interval_s:
                raise SyncThrottled(int(settings.sync_min_interval_s - elapsed) + 1)
            _last_manual[game.key] = time.monotonic()

    lock = _lock_for(game.key)
    if not lock.acquire(blocking=False):
        raise SyncBusy("Synchronisation déjà en cours")
    sync_id = db.start_sync(game.key, "api", trigger)
    try:
        last = db.last_draw(game.key)
        now = datetime.now(timezone.utc)
        if last is None:
            start = datetime(settings.history_start_year, 1, 1, tzinfo=timezone.utc)
        else:
            start = datetime.fromtimestamp(last["draw_time"] / 1000, timezone.utc) - timedelta(days=2)
        raws = natlot.fetch_draws(game, start, now + timedelta(days=1), client=client)
        new, rejected = 0, []
        for raw in raws:
            try:
                parsed = natlot.parse_draw(raw, game)
            except natlot.InvalidDraw as exc:
                rejected.append(f"{raw.get('id')}: {exc}")
                continue
            new += db.insert_draw(parsed)
        msg = f"{new} nouveau(x) tirage(s)"
        if rejected:
            msg += f"; {len(rejected)} rejeté(s): " + "; ".join(rejected[:5])
            log.warning("Rejected draws for %s: %s", game.key, rejected)
        db.finish_sync(sync_id, "ok", new, msg)
        if new:
            db.cache_clear_prefix(f"{game.key}:")
        result = {"status": "ok", "new_draws": new, "rejected": len(rejected), "message": msg}
    except natlot.SourceError as exc:
        db.finish_sync(sync_id, "error", 0, str(exc))
        result = {"status": "error", "new_draws": 0, "message": str(exc)}
    except Exception as exc:  # never leak internals to the client, but keep a trace in logs
        log.exception("Unexpected sync failure for %s", game.key)
        db.finish_sync(sync_id, "error", 0, "Erreur interne pendant la synchronisation")
        result = {"status": "error", "new_draws": 0, "message": "Erreur interne pendant la synchronisation"}
    finally:
        lock.release()

    if game.xlsx_slug and result["status"] == "ok":
        maybe_verify_xlsx(db, game)
    return result


def repair_tiers_from_raw(db: Database, game: Game) -> int:
    """Re-parse prize tiers from the stored raw JSON (no network call).

    Useful when the parser is improved: the audit copy of each API response
    lets us rebuild derived data without fetching anything again.
    """
    n = 0
    for row in db.draws_without_tiers(game.key):
        tiers = natlot.parse_tiers(json.loads(row["raw"]), game)
        if tiers:
            db.replace_tiers(game.key, row["draw_id"], tiers)
            n += 1
    if n:
        db.cache_clear_prefix(f"{game.key}:")
    return n


def maybe_verify_xlsx(db: Database, game: Game, force: bool = False, client=None) -> dict | None:
    """Cross-check draws against the official xlsx, at most once a day."""
    last = db.last_sync(game.key, "xlsx", ok_only=True)
    if last and not force:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(last["started_at"])
        unverified = db.query(
            "SELECT COUNT(*) AS n FROM draws WHERE game=? AND verified_xlsx IS NULL", (game.key,)
        )[0]["n"]
        if age < timedelta(hours=20) or unverified == 0:
            return None
    sync_id = db.start_sync(game.key, "xlsx", "auto")
    try:
        url, official = xlsx_verify.fetch_official_results(client=client)
        results: dict[int, int] = {}
        mismatches = []
        for row in db.all_draws(game.key):
            d = date.fromisoformat(row["draw_date"])
            if d not in official:
                continue  # file not yet updated for this draw (monthly publication)
            nums, bonus = official[d]
            ok = nums == sorted(json.loads(row["numbers"])) and bonus == row["bonus"]
            results[row["draw_id"]] = 1 if ok else 0
            if not ok:
                mismatches.append(row["draw_id"])
        db.set_verification(game.key, results)
        msg = f"{sum(results.values())} tirage(s) confirmé(s) par {url.rsplit('/', 1)[-1]}"
        if mismatches:
            msg += f"; DIVERGENCES: {mismatches[:10]}"
        db.finish_sync(sync_id, "ok", 0, msg)
        return {"verified": sum(results.values()), "mismatches": mismatches}
    except natlot.SourceError as exc:
        db.finish_sync(sync_id, "error", 0, str(exc))
    except Exception:
        log.exception("xlsx verification failed")
        db.finish_sync(sync_id, "error", 0, "Erreur interne pendant la vérification")
    return None
