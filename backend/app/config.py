"""Application configuration, read from environment variables.

All values have safe defaults so the application runs out of the box
(`docker compose up`). See `.env.example` at the repository root.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # Persistent SQLite database (mounted as a Docker volume).
    db_path: Path = field(default_factory=lambda: Path(os.environ.get("DB_PATH", "./data/lotery.db")))
    # First year fetched on the initial backfill. Several years are kept so that
    # the backtest and the popularity model have enough independent data; the
    # dashboard itself focuses on the current year by default.
    history_start_year: int = field(default_factory=lambda: _int("HISTORY_START_YEAR", 2016))
    # Minimum delay between two manual synchronisations (protects the official server).
    sync_min_interval_s: int = field(default_factory=lambda: _int("SYNC_MIN_INTERVAL_S", 60))
    # Optional HTTP Basic auth for the whole site (recommended on a public VPS).
    basic_auth_user: str = field(default_factory=lambda: os.environ.get("BASIC_AUTH_USER", ""))
    basic_auth_password: str = field(default_factory=lambda: os.environ.get("BASIC_AUTH_PASSWORD", ""))
    # Comma-separated host names accepted in the Host header (e.g. "lotery.example.com").
    # Empty = any host (fine behind a reverse proxy that only forwards your domain).
    allowed_hosts: str = field(default_factory=lambda: os.environ.get("ALLOWED_HOSTS", ""))
    # Max POST requests per client IP per minute (generation, favourites, sync, score).
    post_rate_per_min: int = field(default_factory=lambda: _int("POST_RATE_PER_MIN", 40))
    # Enable the automatic sync scheduler (disabled in tests).
    scheduler_enabled: bool = field(default_factory=lambda: os.environ.get("SCHEDULER_ENABLED", "1") == "1")
    # Static frontend build directory served by FastAPI.
    static_dir: Path = field(default_factory=lambda: Path(os.environ.get("STATIC_DIR", "../frontend/dist")))
    timezone: str = "Europe/Brussels"


settings = Settings()
