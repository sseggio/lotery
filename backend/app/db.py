"""SQLite persistence layer.

Every SQL statement in this module is parameterised. Draws are unique on
(game, draw_id): inserting an already-known draw is a no-op, so a
synchronisation can never create duplicates.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS draws (
    game            TEXT    NOT NULL,
    draw_id         INTEGER NOT NULL,           -- official draw number
    draw_time       INTEGER NOT NULL,           -- epoch milliseconds (UTC)
    draw_date       TEXT    NOT NULL,           -- local date (Europe/Brussels) YYYY-MM-DD
    numbers         TEXT    NOT NULL,           -- JSON array of main numbers (sorted)
    extras          TEXT,                       -- JSON array (EuroMillions stars)
    bonus           INTEGER,                    -- Lotto bonus number
    total_sales     INTEGER,                    -- cents, as published
    wagers_sold     INTEGER,
    base_price      INTEGER,                    -- cents per board
    source          TEXT    NOT NULL,           -- 'natlot-api'
    verified_xlsx   INTEGER,                    -- 1 match, 0 mismatch, NULL not checked
    fetched_at      TEXT    NOT NULL,
    raw             TEXT    NOT NULL,           -- raw JSON as received (audit trail)
    PRIMARY KEY (game, draw_id)
);
CREATE INDEX IF NOT EXISTS idx_draws_time ON draws(game, draw_time);

CREATE TABLE IF NOT EXISTS prize_tiers (
    game              TEXT    NOT NULL,
    draw_id           INTEGER NOT NULL,
    tier              TEXT    NOT NULL,         -- official rank name, e.g. '5+1'
    winners           INTEGER NOT NULL,         -- Belgian winners
    winners_global    INTEGER,                  -- all countries (EuroMillions)
    amount            INTEGER NOT NULL,         -- cents per winner
    PRIMARY KEY (game, draw_id, tier)
);

CREATE TABLE IF NOT EXISTS sync_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    game        TEXT NOT NULL,
    kind        TEXT NOT NULL,                  -- 'api' | 'xlsx'
    trigger     TEXT NOT NULL,                  -- 'manual' | 'scheduler' | 'startup'
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL,                  -- 'running' | 'ok' | 'error'
    new_draws   INTEGER DEFAULT 0,
    message     TEXT
);

CREATE TABLE IF NOT EXISTS generations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    game          TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    balance       REAL NOT NULL,               -- 0 = anti-sharing only .. 1 = statistics only
    last_draw_id  INTEGER,
    n_draws_used  INTEGER
);

CREATE TABLE IF NOT EXISTS grids (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    generation_id  INTEGER NOT NULL REFERENCES generations(id),
    slot           INTEGER NOT NULL,           -- 1..4
    active         INTEGER NOT NULL DEFAULT 1, -- 0 once replaced by a regeneration
    strategy       TEXT NOT NULL,
    numbers        TEXT NOT NULL,
    extras         TEXT,
    stat_score     REAL NOT NULL,
    anti_score     REAL NOT NULL,
    global_score   REAL NOT NULL,
    details        TEXT NOT NULL,              -- JSON: criteria & metrics
    favorite       INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_grids_gen ON grids(generation_id);

CREATE TABLE IF NOT EXISTS cache (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
"""

_lock = threading.RLock()


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with _lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def query(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        with _lock:
            return self._conn.execute(sql, params).fetchall()

    # ---- draws ---------------------------------------------------------
    def insert_draw(self, d: dict[str, Any]) -> bool:
        """Insert a parsed draw and its prize tiers. Returns True if new."""
        with self.tx() as c:
            cur = c.execute(
                """INSERT OR IGNORE INTO draws
                (game, draw_id, draw_time, draw_date, numbers, extras, bonus, total_sales,
                 wagers_sold, base_price, source, fetched_at, raw)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    d["game"], d["draw_id"], d["draw_time"], d["draw_date"],
                    json.dumps(d["numbers"]), json.dumps(d["extras"]) if d["extras"] else None,
                    d["bonus"], d["total_sales"], d["wagers_sold"], d["base_price"],
                    d["source"], utcnow_iso(), d["raw"],
                ),
            )
            is_new = cur.rowcount == 1
            if is_new:
                c.executemany(
                    """INSERT OR REPLACE INTO prize_tiers
                    (game, draw_id, tier, winners, winners_global, amount) VALUES (?,?,?,?,?,?)""",
                    [
                        (d["game"], d["draw_id"], t["tier"], t["winners"], t["winners_global"], t["amount"])
                        for t in d["tiers"]
                    ],
                )
            return is_new

    def last_draw(self, game: str) -> sqlite3.Row | None:
        rows = self.query(
            "SELECT * FROM draws WHERE game=? ORDER BY draw_time DESC LIMIT 1", (game,)
        )
        return rows[0] if rows else None

    def count_draws(self, game: str) -> int:
        return self.query("SELECT COUNT(*) AS n FROM draws WHERE game=?", (game,))[0]["n"]

    def all_draws(self, game: str) -> list[sqlite3.Row]:
        """All draws in chronological order (oldest first)."""
        return self.query(
            "SELECT draw_id, draw_time, draw_date, numbers, extras, bonus, total_sales, base_price,"
            " verified_xlsx FROM draws WHERE game=? ORDER BY draw_time ASC",
            (game,),
        )

    def list_draws(self, game: str, limit: int, offset: int) -> list[sqlite3.Row]:
        return self.query(
            "SELECT draw_id, draw_time, draw_date, numbers, extras, bonus, verified_xlsx, total_sales"
            " FROM draws WHERE game=? ORDER BY draw_time DESC LIMIT ? OFFSET ?",
            (game, limit, offset),
        )

    def tiers_for_game(self, game: str) -> list[sqlite3.Row]:
        return self.query(
            "SELECT draw_id, tier, winners, winners_global, amount FROM prize_tiers WHERE game=?",
            (game,),
        )

    def draws_without_tiers(self, game: str) -> list[sqlite3.Row]:
        return self.query(
            "SELECT d.draw_id, d.raw FROM draws d WHERE d.game=? AND NOT EXISTS"
            " (SELECT 1 FROM prize_tiers t WHERE t.game=d.game AND t.draw_id=d.draw_id)",
            (game,),
        )

    def replace_tiers(self, game: str, draw_id: int, tiers: list[dict[str, Any]]) -> None:
        with self.tx() as c:
            c.executemany(
                """INSERT OR REPLACE INTO prize_tiers
                (game, draw_id, tier, winners, winners_global, amount) VALUES (?,?,?,?,?,?)""",
                [(game, draw_id, t["tier"], t["winners"], t["winners_global"], t["amount"]) for t in tiers],
            )

    def set_verification(self, game: str, results: dict[int, int]) -> None:
        with self.tx() as c:
            c.executemany(
                "UPDATE draws SET verified_xlsx=? WHERE game=? AND draw_id=?",
                [(v, game, k) for k, v in results.items()],
            )

    # ---- sync log ------------------------------------------------------
    def start_sync(self, game: str, kind: str, trigger: str) -> int:
        with self.tx() as c:
            cur = c.execute(
                "INSERT INTO sync_log (game, kind, trigger, started_at, status) VALUES (?,?,?,?,?)",
                (game, kind, trigger, utcnow_iso(), "running"),
            )
            return int(cur.lastrowid)

    def finish_sync(self, sync_id: int, status: str, new_draws: int = 0, message: str = "") -> None:
        with self.tx() as c:
            c.execute(
                "UPDATE sync_log SET finished_at=?, status=?, new_draws=?, message=? WHERE id=?",
                (utcnow_iso(), status, new_draws, message[:500], sync_id),
            )

    def last_sync(self, game: str, kind: str = "api", ok_only: bool = False) -> sqlite3.Row | None:
        sql = "SELECT * FROM sync_log WHERE game=? AND kind=?"
        if ok_only:
            sql += " AND status='ok'"
        rows = self.query(sql + " ORDER BY id DESC LIMIT 1", (game, kind))
        return rows[0] if rows else None

    # ---- generations & grids ------------------------------------------
    def create_generation(self, game: str, balance: float, last_draw_id: int | None, n_draws: int) -> int:
        with self.tx() as c:
            cur = c.execute(
                "INSERT INTO generations (game, created_at, balance, last_draw_id, n_draws_used)"
                " VALUES (?,?,?,?,?)",
                (game, utcnow_iso(), balance, last_draw_id, n_draws),
            )
            return int(cur.lastrowid)

    def insert_grid(self, generation_id: int, slot: int, g: dict[str, Any]) -> int:
        with self.tx() as c:
            c.execute(
                "UPDATE grids SET active=0 WHERE generation_id=? AND slot=?", (generation_id, slot)
            )
            cur = c.execute(
                """INSERT INTO grids (generation_id, slot, strategy, numbers, extras, stat_score,
                anti_score, global_score, details, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    generation_id, slot, g["strategy"], json.dumps(g["numbers"]),
                    json.dumps(g["extras"]) if g.get("extras") else None,
                    g["stat_score"], g["anti_score"], g["global_score"],
                    json.dumps(g["details"]), utcnow_iso(),
                ),
            )
            return int(cur.lastrowid)

    def get_generation(self, generation_id: int) -> sqlite3.Row | None:
        rows = self.query("SELECT * FROM generations WHERE id=?", (generation_id,))
        return rows[0] if rows else None

    def generations(self, game: str, limit: int, offset: int = 0) -> list[sqlite3.Row]:
        return self.query(
            "SELECT * FROM generations WHERE game=? ORDER BY id DESC LIMIT ? OFFSET ?",
            (game, limit, offset),
        )

    def grids_for_generation(self, generation_id: int, active_only: bool = True) -> list[sqlite3.Row]:
        sql = "SELECT * FROM grids WHERE generation_id=?"
        if active_only:
            sql += " AND active=1"
        return self.query(sql + " ORDER BY slot, id", (generation_id,))

    def prune_generations(self, game: str, keep: int) -> None:
        """Delete old generations beyond `keep`, except those holding a favourite."""
        with self.tx() as c:
            old = [r[0] for r in c.execute(
                "SELECT id FROM generations WHERE game=? ORDER BY id DESC LIMIT -1 OFFSET ?", (game, keep))]
            for gid in old:
                if c.execute("SELECT 1 FROM grids WHERE generation_id=? AND favorite=1", (gid,)).fetchone():
                    continue
                c.execute("DELETE FROM grids WHERE generation_id=?", (gid,))
                c.execute("DELETE FROM generations WHERE id=?", (gid,))

    def grid(self, grid_id: int) -> sqlite3.Row | None:
        rows = self.query("SELECT * FROM grids WHERE id=?", (grid_id,))
        return rows[0] if rows else None

    def set_favorite(self, grid_id: int, favorite: bool) -> bool:
        with self.tx() as c:
            cur = c.execute("UPDATE grids SET favorite=? WHERE id=?", (1 if favorite else 0, grid_id))
            return cur.rowcount == 1

    def favorites(self, game: str) -> list[sqlite3.Row]:
        return self.query(
            "SELECT g.*, gen.game, gen.last_draw_id FROM grids g JOIN generations gen"
            " ON gen.id = g.generation_id WHERE gen.game=? AND g.favorite=1 ORDER BY g.id DESC",
            (game,),
        )

    # ---- cache ---------------------------------------------------------
    def cache_get(self, key: str) -> Any | None:
        rows = self.query("SELECT value FROM cache WHERE key=?", (key,))
        return json.loads(rows[0]["value"]) if rows else None

    def cache_set(self, key: str, value: Any) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT OR REPLACE INTO cache (key, value, created_at) VALUES (?,?,?)",
                (key, json.dumps(value), utcnow_iso()),
            )

    def cache_clear_prefix(self, prefix: str) -> None:
        with self.tx() as c:
            c.execute("DELETE FROM cache WHERE key LIKE ?", (prefix.replace("%", "") + "%",))


_db: Database | None = None


def get_db() -> Database:
    global _db
    if _db is None:
        _db = Database(settings.db_path)
    return _db


def set_db(db: Database) -> None:
    """Used by tests to inject an in-memory database."""
    global _db
    _db = db
