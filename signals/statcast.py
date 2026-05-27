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


def _f(v) -> float | None:
    try:
        return float(str(v).strip('"').strip())
    except (TypeError, ValueError):
        return None


def _i(v) -> int:
    try:
        return int(str(v).strip('"').strip())
    except (TypeError, ValueError):
        return 0


def _best_fastball_velo(ff_velo: float | None, n_ff: int,
                        si_velo: float | None, n_si: int) -> float | None:
    """Return the avg speed of whichever fastball type was thrown more.
    Falls back to the other type if the dominant type's speed is missing."""
    if n_ff == 0 and n_si == 0:
        return None
    if n_ff >= n_si:
        return ff_velo if ff_velo is not None else si_velo
    return si_velo if si_velo is not None else ff_velo


def _load_pitchers(season: int) -> dict[int, dict]:
    if season in _pitcher_cache:
        return _pitcher_cache[season]
    result: dict[int, dict] = {}
    try:
        resp = requests.get(
            f"{_BASE}/leaderboard/custom",
            params={
                "year": season, "type": "pitcher", "filter": "",
                "selections": "whiff_percent,barrel_batted_rate,hard_hit_percent,n_ff,ff_avg_speed,n_si,si_avg_speed",
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
                    "whiff_pct":     _f(row.get("whiff_percent")),
                    "barrel_pct":    _f(row.get("barrel_batted_rate")),
                    "hard_hit_pct":  _f(row.get("hard_hit_percent")),
                    "fastball_velo": _best_fastball_velo(
                        _f(row.get("ff_avg_speed")), _i(row.get("n_ff")),
                        _f(row.get("si_avg_speed")), _i(row.get("n_si")),
                    ),
                }
            except (ValueError, TypeError):
                pass
        _pitcher_cache[season] = result
    except Exception as exc:
        _log.warning("Failed to load pitcher Statcast data for season %s: %s", season, exc)
        _pitcher_cache[season] = {}   # cache empty result to suppress per-pick retries
    return _pitcher_cache[season]


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
    Return {"fastball_velo": float} from the season leaderboard, or {} if unavailable.
    Uses the cached pitcher leaderboard (no extra HTTP call).
    The Baseball Savant per-start chart endpoint returns 404 and cannot be used.
    """
    data = _load_pitchers(season).get(player_id, {})
    velo = data.get("fastball_velo")
    if velo is None:
        return {}
    return {"fastball_velo": velo}


def reset_cache() -> None:
    _pitcher_cache.clear()
    _batter_cache.clear()
