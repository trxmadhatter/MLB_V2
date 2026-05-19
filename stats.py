"""
MLB Stats API client (free, no key required).
Module-level caches prevent re-fetching within a single run.
Call _reset_caches() in tests only.
"""
import requests
from datetime import datetime

_BASE    = "https://statsapi.mlb.com/api/v1"
_TIMEOUT = 10

_player_cache:          dict[str, dict | None]  = {}
_all_players:           list[dict] | None       = None
_team_stats_cache:      dict[str, dict] | None  = None
_pitcher_gamelog_cache: dict[tuple, list[dict]] = {}
_batter_gamelog_cache:  dict[tuple, list[dict]] = {}


def _reset_caches() -> None:
    global _player_cache, _all_players, _team_stats_cache
    global _pitcher_gamelog_cache, _batter_gamelog_cache
    _player_cache.clear()
    _all_players           = None
    _team_stats_cache      = None
    _pitcher_gamelog_cache.clear()
    _batter_gamelog_cache.clear()


def _fetch_pitcher_gamelog(player_id: int, season: int) -> list[dict]:
    key = (player_id, season)
    if key not in _pitcher_gamelog_cache:
        try:
            r = requests.get(
                f"{_BASE}/people/{player_id}/stats",
                params={"stats": "gameLog", "season": season,
                        "group": "pitching", "gameType": "R"},
                timeout=_TIMEOUT,
            )
            r.raise_for_status()
            splits = r.json().get("stats", [{}])[0].get("splits", [])
            _pitcher_gamelog_cache[key] = [
                s["stat"] for s in splits
                if float(s["stat"].get("inningsPitched", "0") or "0") >= 1.0
            ]
        except Exception:
            _pitcher_gamelog_cache[key] = []
    return _pitcher_gamelog_cache[key]


def _fetch_batter_gamelog(player_id: int, season: int) -> list[dict]:
    key = (player_id, season)
    if key not in _batter_gamelog_cache:
        try:
            r = requests.get(
                f"{_BASE}/people/{player_id}/stats",
                params={"stats": "gameLog", "season": season,
                        "group": "hitting", "gameType": "R"},
                timeout=_TIMEOUT,
            )
            r.raise_for_status()
            splits = r.json().get("stats", [{}])[0].get("splits", [])
            _batter_gamelog_cache[key] = [
                s["stat"] for s in splits
                if int(s["stat"].get("plateAppearances", 0)) > 0
            ]
        except Exception:
            _batter_gamelog_cache[key] = []
    return _batter_gamelog_cache[key]


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
            result = {"id": p["id"],
                      "team_id": p.get("currentTeam", {}).get("id"),
                      "team_name": p.get("currentTeam", {}).get("name", "")}
            _player_cache[player_name] = result
            return result

    if len(parts) >= 2:
        last, first_init = parts[-1], parts[0][0]
        for p in players:
            fp = p.get("fullName", "").lower().split()
            if len(fp) >= 2 and fp[-1] == last and fp[0][0] == first_init:
                result = {"id": p["id"],
                          "team_id": p.get("currentTeam", {}).get("id"),
                          "team_name": p.get("currentTeam", {}).get("name", "")}
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
        started = _fetch_pitcher_gamelog(player_id, season)
        last5 = started[-5:] if len(started) >= 2 else []

        def _avg(key):
            return round(sum(int(s.get(key, 0)) for s in last5) / len(last5), 2) if last5 else None

        def _ip_to_dec(ip_str) -> float:
            # MLB API: "6.2" = 6 innings + 2 outs = 6.667 innings
            try:
                s = str(ip_str or "0")
                if "." in s:
                    full, frac = s.split(".", 1)
                    return int(full) + int(frac) / 3.0
                return float(s)
            except (ValueError, TypeError):
                return 0.0

        recent_ip = round(
            sum(_ip_to_dec(s.get("inningsPitched", "0")) for s in last5) / len(last5), 2
        ) if last5 else None

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

        gs = _f(sea.get("gamesStarted")) or _f(sea.get("gamesPitched"))
        sea_ip_total = _ip_to_dec(sea.get("inningsPitched", "0"))
        season_ip_per_start = round(sea_ip_total / gs, 2) if sea_ip_total and gs and gs > 0 else None

        return {
            "recent_k":             _avg("strikeOuts"),
            "recent_h":             _avg("hits"),
            "recent_er":            _avg("earnedRuns"),
            "recent_ip":            recent_ip,
            "season_k9":            _f(sea.get("strikeoutsPer9Inn")),
            "season_era":           _f(sea.get("era")),
            "season_whip":          _f(sea.get("whip")),
            "season_ip_per_start":  season_ip_per_start,
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
        played = _fetch_batter_gamelog(player_id, season)
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


def fetch_batter_game_values(player_id: int, season: int, stat_key: str,
                             n: int = 20) -> list[float]:
    """Return last n per-game values of stat_key from the batter's game log."""
    games = _fetch_batter_gamelog(player_id, season)
    return [float(g.get(stat_key, 0)) for g in games][-n:]


def fetch_pitcher_game_values(player_id: int, season: int, stat_key: str,
                              n: int = 10) -> list[float]:
    """Return last n per-start values of stat_key from the pitcher's game log.
    stat_key='outs' converts inningsPitched to outs recorded."""
    games = _fetch_pitcher_gamelog(player_id, season)
    if stat_key == "outs":
        def _ip_to_outs(ip_str) -> float:
            try:
                s = str(ip_str or "0")
                if "." in s:
                    full, frac = s.split(".", 1)
                    return int(full) * 3 + int(frac)
                return float(s) * 3
            except (ValueError, TypeError):
                return 0.0
        values = [_ip_to_outs(g.get("inningsPitched", "0")) for g in games]
    else:
        values = [float(g.get(stat_key, 0)) for g in games]
    return values[-n:]


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
