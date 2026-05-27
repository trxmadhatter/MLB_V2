"""
Baseball Savant / Statcast leaderboard data (free, no auth).
Fetches season-level metrics for pitchers and batters keyed by MLBAM player_id.
Cache is per-process and season-keyed; call reset_cache() in tests only.
"""
from __future__ import annotations
import csv
import io
import logging
import requests

_BASE    = "https://baseballsavant.mlb.com"
_TIMEOUT = 20
_log     = logging.getLogger(__name__)

# season -> {player_id -> metrics}
_pitcher_cache: dict[int, dict[int, dict]] = {}
_batter_cache:  dict[int, dict[int, dict]] = {}
# (player_id, season) -> {"season_avg_velo": float|None, "recent_avg_velo": float|None, "trend": float|None}
_velo_cache: dict[tuple, dict] = {}


def _f(v) -> float | None:
    try:
        return float(str(v).strip('"').strip())
    except (TypeError, ValueError):
        return None


def _load_pitchers(season: int) -> dict[int, dict]:
    if season in _pitcher_cache:
        return _pitcher_cache[season]
    result: dict[int, dict] = {}
    try:
        resp = requests.get(
            f"{_BASE}/leaderboard/custom",
            params={
                "year": season, "type": "pitcher", "filter": "",
                "selections": "whiff_percent,barrel_batted_rate,hard_hit_percent",
                "minResults": 0, "minGroupSwing": 0, "csv": "true",
            },
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        reader = csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig")))
        for row in reader:
            pid = row.get("player_id")
            if not pid:
                continue
            try:
                result[int(pid)] = {
                    "whiff_pct":    _f(row.get("whiff_percent")),
                    "barrel_pct":   _f(row.get("barrel_batted_rate")),
                    "hard_hit_pct": _f(row.get("hard_hit_percent")),
                }
            except (ValueError, TypeError):
                pass
        _pitcher_cache[season] = result   # only cached on successful fetch
    except Exception as exc:
        _log.warning("Failed to load pitcher Statcast data for season %s: %s", season, exc)
    return _pitcher_cache.get(season, {})


def _load_batters(season: int) -> dict[int, dict]:
    if season in _batter_cache:
        return _batter_cache[season]
    result: dict[int, dict] = {}
    try:
        resp = requests.get(
            f"{_BASE}/leaderboard/custom",
            params={
                "year": season, "type": "batter", "filter": "",
                "selections": "xwoba,barrel_batted_rate,hard_hit_percent",
                "minResults": 0, "minGroupSwing": 0, "csv": "true",
            },
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        reader = csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig")))
        for row in reader:
            pid = row.get("player_id")
            if not pid:
                continue
            try:
                result[int(pid)] = {
                    "xwoba":        _f(row.get("xwoba")),
                    "barrel_pct":   _f(row.get("barrel_batted_rate")),
                    "hard_hit_pct": _f(row.get("hard_hit_percent")),
                }
            except (ValueError, TypeError):
                pass
        _batter_cache[season] = result    # only cached on successful fetch
    except Exception as exc:
        _log.warning("Failed to load batter Statcast data for season %s: %s", season, exc)
    return _batter_cache.get(season, {})


def get_pitcher_statcast(player_id: int, season: int) -> dict:
    """Return Statcast metrics for a pitcher, or {} if unavailable."""
    return _load_pitchers(season).get(player_id, {})


def get_batter_statcast(player_id: int, season: int) -> dict:
    """Return Statcast metrics for a batter, or {} if unavailable."""
    return _load_batters(season).get(player_id, {})


def fetch_pitcher_velo_trend(player_id: int, season: int) -> dict:
    """
    Fetch per-start avg fastball velocity from Baseball Savant career game log chart.
    Returns {season_avg_velo, recent_avg_velo, trend} where trend = recent - season_avg.
    recent = avg of last 3 starts. Falls back to {} on error.
    Cached per (player_id, season).
    """
    key = (player_id, season)
    if key in _velo_cache:
        return _velo_cache[key]
    try:
        resp = requests.get(
            f"{_BASE}/player-services/career-game-log-chart",
            params={"player_id": player_id, "position": 1,
                    "chartType": "velocity", "season": season},
            headers={"User-Agent": "Mozilla/5.0",
                     "Referer": f"{_BASE}/savant-player/{player_id}"},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        # Expected: {"chart_data": [{"game_date": "YYYY-MM-DD", "y": float}, ...]}
        chart = data.get("chart_data", []) if isinstance(data, dict) else []
        if not chart:
            _velo_cache[key] = {}
            return {}
        velos = [v for pt in chart for v in (_f(pt.get("y")),) if v is not None]
        if len(velos) < 3:
            _velo_cache[key] = {}
            return {}
        season_avg = round(sum(velos) / len(velos), 1)
        recent_avg = round(sum(velos[-3:]) / 3, 1)
        result = {
            "season_avg_velo": season_avg,
            "recent_avg_velo": recent_avg,
            "trend":           round(recent_avg - season_avg, 1),
        }
        _velo_cache[key] = result
        return result
    except Exception as exc:
        _log.debug("Velocity trend fetch failed for player %s season %s: %s",
                   player_id, season, exc)
        _velo_cache[key] = {}
        return {}


def reset_cache() -> None:
    _pitcher_cache.clear()
    _batter_cache.clear()
    _velo_cache.clear()
