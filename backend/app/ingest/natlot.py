"""Client for the official Loterie Nationale draw-results API.

Source
------
`https://apim.prd.natlot.be/api/v4/draw-games/draws` is the JSON endpoint used
by the official website (www.loterie-nationale.be) to display results. It is
not publicly documented, so the parser is deliberately strict: any draw whose
content does not match the official game rules is rejected and reported,
never "fixed" or guessed.

Security: every URL is built from constants in this module; no user input ever
reaches an outbound request (no SSRF). Responses are size-bounded.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from ..games import Game

log = logging.getLogger(__name__)

API_URL = "https://apim.prd.natlot.be/api/v4/draw-games/draws"
USER_AGENT = "lotery-stats/1.0 (+personal statistics tool)"
TIMEOUT = httpx.Timeout(20.0, connect=10.0)
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
BRUSSELS = ZoneInfo("Europe/Brussels")


class SourceError(RuntimeError):
    """The official source is unreachable or returned unusable data."""


class InvalidDraw(ValueError):
    """A draw does not respect the official game rules."""


def _get_json(client: httpx.Client, params: dict[str, Any]) -> dict[str, Any]:
    try:
        with client.stream("GET", API_URL, params=params) as resp:
            if resp.status_code != 200:
                raise SourceError(f"API officielle: HTTP {resp.status_code}")
            chunks, size = [], 0
            for chunk in resp.iter_bytes():
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise SourceError("API officielle: réponse trop volumineuse")
                chunks.append(chunk)
        return json.loads(b"".join(chunks))
    except httpx.HTTPError as exc:
        raise SourceError(f"API officielle injoignable ({exc.__class__.__name__})") from exc
    except json.JSONDecodeError as exc:
        raise SourceError("API officielle: réponse JSON invalide") from exc


def fetch_draws(game: Game, date_from: datetime, date_to: datetime,
                client: httpx.Client | None = None) -> list[dict[str, Any]]:
    """Fetch raw PAYABLE draws (results final) between two datetimes.

    The range is split into ~1-year chunks: a chunk holds at most ~110 draws,
    well below the API page size of 250.
    """
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
    try:
        out: list[dict[str, Any]] = []
        start = date_from
        while start < date_to:
            end = min(date_to, start.replace(year=start.year + 1))
            data = _get_json(client, {
                "status": "PAYABLE",
                "game-names": game.api_name,
                "date-from": int(start.timestamp() * 1000),
                "date-to": int(end.timestamp() * 1000),
            })
            draws = data.get("draws")
            if not isinstance(draws, list):
                raise SourceError("API officielle: format inattendu (champ 'draws' absent)")
            if len(draws) >= 250:  # would mean pagination is needed: never silently truncate
                raise SourceError("API officielle: trop de tirages dans une seule page")
            out.extend(draws)
            start = end
        return out
    finally:
        if own:
            client.close()


def _ints(values: Any) -> list[int]:
    if not isinstance(values, list):
        raise InvalidDraw("liste de numéros absente")
    try:
        return [int(v) for v in values]
    except (TypeError, ValueError) as exc:
        raise InvalidDraw("numéro non entier") from exc


def _check_pool(nums: list[int], low: int, high: int, picks: int, label: str) -> None:
    if len(nums) != picks:
        raise InvalidDraw(f"{label}: {len(nums)} numéros au lieu de {picks}")
    if len(set(nums)) != picks:
        raise InvalidDraw(f"{label}: doublon")
    if any(n < low or n > high for n in nums):
        raise InvalidDraw(f"{label}: numéro hors de [{low}, {high}]")


def parse_tiers(raw: dict[str, Any], game: Game) -> list[dict[str, Any]]:
    """Prize ranks of the main game (add-ons such as Lucky Lotto are skipped).

    Note: the API sometimes pads `drawType` with spaces ("Regular "), hence strip().
    """
    tiers = []
    for t in raw.get("prizeTiers") or []:
        if str(t.get("drawType", "")).strip() != "Regular":
            continue
        name = str(t.get("name", "")).strip()
        if name not in game.tier_names:
            continue
        g = t.get("globalShareCount")
        tiers.append({
            "tier": name,
            "winners": int(t.get("shareCount") or 0),
            "winners_global": int(g) if g not in (None, "") else None,
            "amount": int(t.get("shareAmount") or 0),
        })
    return tiers


def parse_draw(raw: dict[str, Any], game: Game) -> dict[str, Any]:
    """Validate a raw API draw against the official rules and normalise it."""
    if raw.get("gameName") != game.api_name:
        raise InvalidDraw("jeu inattendu")
    if raw.get("status") != "PAYABLE":
        raise InvalidDraw("résultats non définitifs")
    try:
        draw_id = int(raw["id"])
        draw_time = int(raw["drawTime"])
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidDraw("identifiant ou date manquant") from exc

    rules = raw.get("gameRuleSet") or {}
    hi = rules.get("primarySelectionsHighNumber")
    if hi is not None and int(hi) != game.main.high:
        raise InvalidDraw(f"règle modifiée: numéros jusqu'à {hi}")

    results = raw.get("results") or []
    normal = next((r for r in results if r.get("drawType") == "normal"), None)
    if normal is None:
        raise InvalidDraw("résultat principal absent")
    numbers = sorted(_ints(normal.get("primary")))
    _check_pool(numbers, game.main.low, game.main.high, game.main.picks, "numéros")

    extras: list[int] | None = None
    bonus: int | None = None
    if game.extra:
        extras = sorted(_ints(normal.get("secondary")))
        _check_pool(extras, game.extra.low, game.extra.high, game.extra.picks, "étoiles")
    if game.has_bonus:
        b = next((r for r in results if r.get("drawType") == "bonus"), None)
        if b is None:
            raise InvalidDraw("numéro bonus absent")
        bl = _ints(b.get("primary"))
        if len(bl) != 1 or not (game.main.low <= bl[0] <= game.main.high) or bl[0] in numbers:
            raise InvalidDraw("numéro bonus invalide")
        bonus = bl[0]

    tiers = parse_tiers(raw, game)

    local_date = datetime.fromtimestamp(draw_time / 1000, timezone.utc).astimezone(BRUSSELS).date()
    return {
        "game": game.key,
        "draw_id": draw_id,
        "draw_time": draw_time,
        "draw_date": local_date.isoformat(),
        "numbers": numbers,
        "extras": extras,
        "bonus": bonus,
        "total_sales": int(raw.get("totalSales") or 0) or None,
        "wagers_sold": int(raw.get("totalWagersSold") or 0) or None,
        "base_price": int(rules.get("basePrice") or game.base_price_cents),
        "tiers": tiers,
        "source": "natlot-api",
        "raw": json.dumps(raw, separators=(",", ":")),
    }
