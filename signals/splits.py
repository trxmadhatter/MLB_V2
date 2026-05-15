"""
Platoon (vs LHP / vs RHP) and home/away splits from MLB Stats API.
Results cached in-memory per (player_id, season, group).
"""
from __future__ import annotations
import requests

_BASE = "https://statsapi.mlb.com/api/v1"
_TIMEOUT = 10
_cache: dict[tuple, dict] = {}

NEUTRAL_SPLITS = {
    "k9_vs_lhh": None, "k9_vs_rhh": None,
    "h9_vs_lhh": None,  "h9_vs_rhh": None,
    "era_home": None,   "era_away": None,
    "slg_vs_lhp": None, "slg_vs_rhp": None,
    "avg_vs_lhp": None, "avg_vs_rhp": None,
    "avg_home": None,   "avg_away": None,
}


def _f(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fetch_splits(player_id: int, season: int, group: str) -> list[dict]:
    cache_key = (player_id, season, group)
    if cache_key in _cache:
        return _cache[cache_key]
    try:
        resp = requests.get(
            f"{_BASE}/people/{player_id}/stats",
            params={
                "stats": "statSplits",
                "group": group,
                "season": season,
                "sitCodes": "vl,vr,h,a",
                "gameType": "R",
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        splits = resp.json().get("stats", [{}])[0].get("splits", [])
        _cache[cache_key] = splits
        return splits
    except Exception:
        _cache[cache_key] = []
        return []


def _split_stat(splits: list[dict], sit_code: str, key: str) -> float | None:
    for s in splits:
        if s.get("split", {}).get("code") == sit_code:
            return _f(s.get("stat", {}).get(key))
    return None


def get_pitcher_splits(player_id: int, season: int) -> dict:
    splits = _fetch_splits(player_id, season, "pitching")
    if not splits:
        return NEUTRAL_SPLITS.copy()

    def k9(sit):
        ip = _split_stat(splits, sit, "inningsPitched")
        k  = _split_stat(splits, sit, "strikeOuts")
        if ip and k and float(ip) > 0:
            return round(k / float(ip) * 9, 2)
        return None

    def h9(sit):
        ip = _split_stat(splits, sit, "inningsPitched")
        h  = _split_stat(splits, sit, "hits")
        if ip and h and float(ip) > 0:
            return round(h / float(ip) * 9, 2)
        return None

    return {
        "k9_vs_lhh":  k9("vl"),
        "k9_vs_rhh":  k9("vr"),
        "h9_vs_lhh":  h9("vl"),
        "h9_vs_rhh":  h9("vr"),
        "era_home":   _split_stat(splits, "h", "era"),
        "era_away":   _split_stat(splits, "a", "era"),
    }


def get_batter_splits(player_id: int, season: int) -> dict:
    splits = _fetch_splits(player_id, season, "hitting")
    if not splits:
        return NEUTRAL_SPLITS.copy()
    return {
        "slg_vs_lhp": _split_stat(splits, "vl", "slg"),
        "slg_vs_rhp": _split_stat(splits, "vr", "slg"),
        "avg_vs_lhp": _split_stat(splits, "vl", "avg"),
        "avg_vs_rhp": _split_stat(splits, "vr", "avg"),
        "avg_home":   _split_stat(splits, "h",  "avg"),
        "avg_away":   _split_stat(splits, "a",  "avg"),
    }


def reset_cache() -> None:
    _cache.clear()
