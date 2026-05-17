"""
MLB Stats API — season-level team offense stats.
Fetches all 30 teams in one call; caches per season per process.
"""
from __future__ import annotations
import logging
import requests

_API_URL = "https://statsapi.mlb.com/api/v1/stats"
_TIMEOUT = 20
_log = logging.getLogger(__name__)

# season -> {team_name_lower -> {"runs_per_game": float|None, "ops": float|None}}
_cache: dict[int, dict[str, dict]] = {}

_EMPTY = {"runs_per_game": None, "ops": None}


def _f(v) -> float | None:
    try:
        return float(str(v).strip('"').strip())
    except (TypeError, ValueError):
        return None


def _load_season(season: int) -> dict[str, dict]:
    if season in _cache:
        return _cache[season]
    result: dict[str, dict] = {}
    try:
        resp = requests.get(
            _API_URL,
            params={
                "stats": "season",
                "group": "hitting",
                "gameType": "R",
                "season": season,
                "sportId": 1,
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        splits = data["stats"][0]["splits"]
        for split in splits:
            name = split["team"]["name"]
            stat = split.get("stat", {})
            result[name.lower()] = {
                "runs_per_game": _f(stat.get("runsPerGame")),
                "ops": _f(stat.get("ops")),
            }
        _cache[season] = result
    except Exception as exc:
        _log.warning("Failed to load team offense stats for season %s: %s", season, exc)
    return _cache.get(season, {})


def get_team_offense(team_name: str, season: int) -> dict:
    """Return {"runs_per_game": float|None, "ops": float|None} for a team."""
    data = _load_season(season)
    key = team_name.lower()

    # Exact match
    if key in data:
        return data[key]

    # Fuzzy: substring in either direction
    for cache_key, stats in data.items():
        if key in cache_key or cache_key in key:
            return stats

    return dict(_EMPTY)


def reset_cache() -> None:
    _cache.clear()
