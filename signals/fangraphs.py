"""
FanGraphs pitcher leaderboard data (free, no auth, requires Referer header).
Fetches season-level metrics keyed by MLBAM player_id (xMLBAMID field).
Cache is per-process and season-keyed; call reset_cache() in tests only.
"""
from __future__ import annotations
import logging
import requests

_BASE    = "https://www.fangraphs.com/api/leaders/major-league/data"
_REFERER = "https://www.fangraphs.com/leaders/major-league"
_TIMEOUT = 20
_log     = logging.getLogger(__name__)

# season -> {player_id -> metrics}
_pitcher_cache: dict[int, dict[int, dict]] = {}


def _f(v) -> float | None:
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def _load_pitchers(season: int) -> dict[int, dict]:
    if season in _pitcher_cache:
        return _pitcher_cache[season]
    result: dict[int, dict] = {}
    try:
        resp = requests.get(
            _BASE,
            params={
                "pos": "all", "stats": "pit", "lg": "all",
                "qual": 10,           # 10 IP minimum — includes all starters with 2+ starts
                "season": season, "type": 8,
                "startSeason": season, "endSeason": season,
                "month": 0, "pageitems": 2000, "pagenum": 1,
            },
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Referer": _REFERER,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Origin": "https://www.fangraphs.com",
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        if len(data) >= 2000:
            _log.warning(
                "FanGraphs returned %d rows for season %s — possible truncation.", len(data), season
            )
        for row in data:
            mlbam_id = row.get("xMLBAMID")
            if not mlbam_id:
                continue
            try:
                result[int(mlbam_id)] = {
                    "swstr_pct":  _f(row.get("SwStr%")),   # may be decimal (0.112) or pct (11.2)
                    "xfip":       _f(row.get("xFIP")),
                    "siera":      _f(row.get("SIERA")),
                    "stuff_plus": _f(row.get("sp_stuff")),  # 100 = avg
                }
            except (ValueError, TypeError):
                pass

        # Normalize swstr_pct: FanGraphs returns decimal (0.112) but some API versions
        # return percentage (11.2). Detect and correct automatically.
        sample = next(iter(result.values()), {})
        swstr_sample = sample.get("swstr_pct")
        if swstr_sample is not None and swstr_sample > 1.0:
            _log.warning(
                "FanGraphs SwStr%% appears to be in percentage form (%.3f). "
                "Normalizing all swstr_pct values by dividing by 100.", swstr_sample
            )
            for v in result.values():
                if v.get("swstr_pct") is not None:
                    v["swstr_pct"] = v["swstr_pct"] / 100.0

        _pitcher_cache[season] = result   # only cached on successful fetch
    except Exception as exc:
        _log.warning("Failed to load pitcher FanGraphs data for season %s: %s", season, exc)
    return _pitcher_cache.get(season, {})


def get_pitcher_fangraphs(player_id: int, season: int) -> dict:
    """Return FanGraphs metrics for a pitcher, or {} if unavailable."""
    return _load_pitchers(season).get(player_id, {})


def reset_cache() -> None:
    _pitcher_cache.clear()
