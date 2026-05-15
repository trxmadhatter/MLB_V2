"""
MLB Stats API client (free, no key required).
Module-level caches prevent re-fetching within a single run.
Call _reset_caches() in tests only.
"""
import requests
from datetime import datetime

_BASE    = "https://statsapi.mlb.com/api/v1"
_TIMEOUT = 10

_player_cache:     dict[str, dict | None] = {}
_all_players:      list[dict] | None      = None
_team_stats_cache: dict[str, dict] | None = None


def _reset_caches() -> None:
    global _player_cache, _all_players, _team_stats_cache
    _player_cache.clear()
    _all_players      = None
    _team_stats_cache = None


def _load_all_players(season: int | None = None) -> list[dict]:
    if season is None:
        season = datetime.now().year
    global _all_players
    if _all_players is None:
        resp = requests.get(
            f"{_BASE}/sports/1/players",
            params={"season": season},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        _all_players = resp.json().get("people", [])
    return _all_players


def find_player_info(player_name: str, season: int | None = None) -> dict | None:
    """Return {id, team_name} for player_name, or None if not found."""
    if season is None:
        season = datetime.now().year
    if player_name in _player_cache:
        return _player_cache[player_name]

    try:
        players = _load_all_players(season)
    except Exception:
        return None

    name_lower = player_name.lower().strip()
    parts      = name_lower.split()

    for p in players:
        full = p.get("fullName", "").lower()
        if full == name_lower:
            result = {"id": p["id"], "team_name": p.get("currentTeam", {}).get("name", "")}
            _player_cache[player_name] = result
            return result

    if len(parts) >= 2:
        last, first_init = parts[-1], parts[0][0]
        for p in players:
            fp = p.get("fullName", "").lower().split()
            if len(fp) >= 2 and fp[-1] == last and fp[0][0] == first_init:
                result = {"id": p["id"], "team_name": p.get("currentTeam", {}).get("name", "")}
                _player_cache[player_name] = result
                return result

    _player_cache[player_name] = None
    return None


def fetch_pitcher_stats(player_id: int, season: int | None = None) -> dict | None:
    """
    Returns recent_k, recent_h, recent_er (avg last 5 starts),
    season_k9, season_era, season_whip. None on error.
    """
    if season is None:
        season = datetime.now().year
    try:
        r_log = requests.get(
            f"{_BASE}/people/{player_id}/stats",
            params={"stats": "gameLog", "season": season, "group": "pitching", "gameType": "R"},
            timeout=_TIMEOUT,
        )
        r_log.raise_for_status()
        splits = r_log.json().get("stats", [{}])[0].get("splits", [])

        started = [
            s["stat"] for s in splits
            if float(s["stat"].get("inningsPitched", "0") or "0") >= 1.0
        ]
        last5 = started[-5:] if len(started) >= 2 else []

        def _avg(key):
            return round(sum(int(s.get(key, 0)) for s in last5) / len(last5), 2) if last5 else None

        r_sea = requests.get(
            f"{_BASE}/people/{player_id}/stats",
            params={"stats": "season", "season": season, "group": "pitching", "gameType": "R"},
            timeout=_TIMEOUT,
        )
        r_sea.raise_for_status()
        sea_splits = r_sea.json().get("stats", [{}])[0].get("splits", [])
        sea = sea_splits[0]["stat"] if sea_splits else {}

        def _f(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        return {
            "recent_k":    _avg("strikeOuts"),
            "recent_h":    _avg("hits"),
            "recent_er":   _avg("earnedRuns"),
            "season_k9":   _f(sea.get("strikeoutsPer9Inn")),
            "season_era":  _f(sea.get("era")),
            "season_whip": _f(sea.get("whip")),
        }
    except Exception:
        return None


def fetch_batter_stats(player_id: int, season: int | None = None) -> dict | None:
    """
    Returns recent_h_per_game, recent_tb_per_game (avg last 10 games),
    season_avg, season_slg. None on error.
    """
    if season is None:
        season = datetime.now().year
    try:
        r_log = requests.get(
            f"{_BASE}/people/{player_id}/stats",
            params={"stats": "gameLog", "season": season, "group": "hitting", "gameType": "R"},
            timeout=_TIMEOUT,
        )
        r_log.raise_for_status()
        splits = r_log.json().get("stats", [{}])[0].get("splits", [])
        played = [
            s["stat"] for s in splits
            if int(s["stat"].get("plateAppearances", 0)) > 0
        ]
        last10 = played[-10:] if len(played) >= 3 else []

        def _avg(key):
            return round(sum(int(s.get(key, 0)) for s in last10) / len(last10), 3) if last10 else None

        r_sea = requests.get(
            f"{_BASE}/people/{player_id}/stats",
            params={"stats": "season", "season": season, "group": "hitting", "gameType": "R"},
            timeout=_TIMEOUT,
        )
        r_sea.raise_for_status()
        sea_splits = r_sea.json().get("stats", [{}])[0].get("splits", [])
        sea = sea_splits[0]["stat"] if sea_splits else {}

        def _f(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        return {
            "recent_h_per_game":  _avg("hits"),
            "recent_tb_per_game": _avg("totalBases"),
            "season_avg":         _f(sea.get("avg")),
            "season_slg":         _f(sea.get("slg")),
        }
    except Exception:
        return None


def fetch_team_hitting(team_name: str, season: int | None = None) -> dict | None:
    """Return {k_pct, avg, ops} for the named team, or None on failure."""
    if season is None:
        season = datetime.now().year
    cache = _load_team_stats(season)
    if cache is None:
        return None
    if team_name in cache:
        return cache[team_name]
    name_lower = team_name.lower()
    for k, v in cache.items():
        if name_lower in k.lower() or k.lower() in name_lower:
            return v
    return None


def _load_team_stats(season: int) -> dict[str, dict] | None:
    global _team_stats_cache
    if _team_stats_cache is not None:
        return _team_stats_cache
    try:
        resp = requests.get(
            f"{_BASE}/teams/stats",
            params={"stats": "season", "group": "hitting", "season": season, "sportId": 1},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        splits = resp.json().get("stats", [{}])[0].get("splits", [])
        _team_stats_cache = {}
        for s in splits:
            team = s.get("team", {}).get("name", "")
            st   = s.get("stat", {})
            try:
                pa    = int(st.get("plateAppearances", 0))
                k     = int(st.get("strikeOuts", 0))
                k_pct = k / pa if pa > 0 else None
            except (TypeError, ValueError):
                k_pct = None
            def _f(v):
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None
            _team_stats_cache[team] = {
                "k_pct": k_pct,
                "avg":   _f(st.get("avg")),
                "ops":   _f(st.get("ops")),
            }
        return _team_stats_cache
    except Exception:
        return None
