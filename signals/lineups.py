"""
Pre-fetch all game data for a given date from MLB Stats API:
  - Probable starting pitchers (hand, ERA, K/9)
  - Home plate umpire name
  - Lineup confirmation status

Returns a dict keyed by (home_team_name_lower, away_team_name_lower) for
fast lookup during pick scoring.
"""
from __future__ import annotations
import requests
from signals.umpires import get_ump_k_tendency

_BASE = "https://statsapi.mlb.com/api/v1"
_TIMEOUT = 15

_HAND_MAP = {"L": "L", "R": "R", "S": "S", "B": "S"}  # B = switch


def _f(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _get_pitcher_meta(pitcher_id: int, season: int) -> dict:
    try:
        r = requests.get(
            f"{_BASE}/people/{pitcher_id}/stats",
            params={"stats": "season", "group": "pitching",
                    "season": season, "gameType": "R"},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        splits = r.json().get("stats", [{}])[0].get("splits", [])
        s = splits[0]["stat"] if splits else {}
        return {
            "era":  _f(s.get("era")),
            "k9":   _f(s.get("strikeoutsPer9Inn")),
            "whip": _f(s.get("whip")),
        }
    except Exception:
        return {"era": None, "k9": None, "whip": None}


def get_game_data_for_date(date_str: str, season: int | None = None) -> dict:
    """
    Returns {(home_name_lower, away_name_lower): game_info_dict} for all
    games on date_str.

    game_info_dict keys:
        game_pk, home_team, away_team,
        home_sp: {id, name, hand, era, k9, whip},
        away_sp: {id, name, hand, era, k9, whip},
        umpire_name: str | None,
        ump_k_tendency: float,
        lineup_confirmed: bool,
    """
    if season is None:
        season = int(date_str[:4])

    result = {}
    try:
        r = requests.get(
            f"{_BASE}/schedule",
            params={
                "date": date_str,
                "sportId": 1,
                "hydrate": "probablePitcher,officials,lineups",
            },
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
    except Exception:
        return result

    for date_entry in r.json().get("dates", []):
        for game in date_entry.get("games", []):
            game_pk    = game.get("gamePk")
            home_info  = game.get("teams", {}).get("home", {})
            away_info  = game.get("teams", {}).get("away", {})
            home_name  = home_info.get("team", {}).get("name", "")
            away_name  = away_info.get("team", {}).get("name", "")

            def _sp(team_info: dict) -> dict:
                pp = team_info.get("probablePitcher", {})
                if not pp:
                    return {"id": None, "name": None, "hand": None,
                            "era": None, "k9": None, "whip": None}
                pid  = pp.get("id")
                hand = pp.get("pitchHand", {}).get("code") if pid else None
                meta = _get_pitcher_meta(pid, season) if pid else {}
                return {"id": pid, "name": pp.get("fullName"),
                        "hand": _HAND_MAP.get(hand, hand), **meta}

            officials = game.get("officials", [])
            ump_name  = None
            for off in officials:
                if off.get("officialType") == "Home Plate":
                    ump_name = off.get("official", {}).get("fullName")
                    break

            lineups = game.get("lineups", {})
            lineup_confirmed = bool(
                lineups.get("homePlayers") or lineups.get("awayPlayers")
            )

            key = (home_name.lower(), away_name.lower())
            result[key] = {
                "game_pk":          game_pk,
                "home_team":        home_name,
                "away_team":        away_name,
                "home_sp":          _sp(home_info),
                "away_sp":          _sp(away_info),
                "umpire_name":      ump_name,
                "ump_k_tendency":   get_ump_k_tendency(ump_name),
                "lineup_confirmed": lineup_confirmed,
            }

    return result


def find_game(game_data: dict, home_team: str, away_team: str) -> dict | None:
    """Fuzzy match home/away team names to game_data keys."""
    key = (home_team.lower(), away_team.lower())
    if key in game_data:
        return game_data[key]
    for (h, a), info in game_data.items():
        if home_team.lower() in h or h in home_team.lower():
            if away_team.lower() in a or a in away_team.lower():
                return info
    return None
