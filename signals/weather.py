"""
Game weather via Open-Meteo archive/forecast API (free, no key required).
Returns wind tailwind factor relative to each park's cf_bearing.
Dome stadiums return neutral weather (zeros).
Results cached in-memory per (lat, lon, date).
"""
from __future__ import annotations
import requests

_TIMEOUT = 10
_cache: dict[tuple, dict] = {}

NEUTRAL_WEATHER = {
    "wind_speed_kph": 0.0,
    "wind_direction_deg": 0,
    "temp_c": 20.0,
    "precip_mm": 0.0,
    "tailwind_factor": 0.5,   # 0=headwind, 0.5=crosswind/neutral, 1=tailwind
    "cold_penalty": 0.0,       # 0-1, higher = colder = fewer runs
    "is_dome": False,
}


def _tailwind_factor(wind_dir_deg: float, cf_bearing_deg: float) -> float:
    """
    Returns 0.0 (full headwind) to 1.0 (full tailwind) based on
    how much wind blows toward CF (helps Overs) vs from CF (helps Unders).

    wind_dir_deg: meteorological convention — direction wind is blowing FROM.
    cf_bearing_deg: compass bearing from home plate TO center field.
    Tailwind = wind blowing FROM the direction OPPOSITE to CF (i.e., pushing ball toward CF).
    """
    # Convert "wind from" direction to "wind toward" direction
    wind_toward_deg = (wind_dir_deg + 180) % 360
    diff = abs((wind_toward_deg - cf_bearing_deg + 180) % 360 - 180)
    # diff=0  -> wind blows exactly toward CF (tailwind) -> 1.0
    # diff=180 -> wind blows exactly away from CF (headwind) -> 0.0
    return 1.0 - (diff / 180.0)


def get_weather(lat: float, lon: float, date_str: str,
                cf_bearing: int, is_dome: bool) -> dict:
    """
    Fetch weather for a stadium location on a given date.
    date_str: 'YYYY-MM-DD'
    cf_bearing: compass bearing from home plate to center field
    """
    if is_dome:
        return {**NEUTRAL_WEATHER, "is_dome": True}

    cache_key = (round(lat, 3), round(lon, 3), date_str)
    if cache_key in _cache:
        return _cache[cache_key]

    try:
        url = "https://api.open-meteo.com/v1/forecast"
        resp = requests.get(url, params={
            "latitude": lat,
            "longitude": lon,
            "daily": "wind_speed_10m_max,wind_direction_10m_dominant,precipitation_sum,temperature_2m_max",
            "start_date": date_str,
            "end_date": date_str,
            "wind_speed_unit": "kmh",
            "temperature_unit": "celsius",
            "timezone": "auto",
        }, timeout=_TIMEOUT)
        resp.raise_for_status()
        d = resp.json().get("daily", {})

        wind_speed  = (d.get("wind_speed_10m_max")          or [0.0])[0] or 0.0
        wind_dir    = (d.get("wind_direction_10m_dominant")  or [0])[0]   or 0
        precip      = (d.get("precipitation_sum")            or [0.0])[0] or 0.0
        temp        = (d.get("temperature_2m_max")           or [20.0])[0] or 20.0

        tf = _tailwind_factor(float(wind_dir), float(cf_bearing))
        cold = max(0.0, min(1.0, (10.0 - temp) / 20.0)) if temp < 10 else 0.0

        result = {
            "wind_speed_kph":    round(wind_speed, 1),
            "wind_direction_deg": int(wind_dir),
            "temp_c":            round(temp, 1),
            "precip_mm":         round(precip, 2),
            "tailwind_factor":   round(tf, 3),
            "cold_penalty":      round(cold, 3),
            "is_dome":           False,
        }
    except Exception:
        result = {**NEUTRAL_WEATHER}

    _cache[cache_key] = result
    return result


def reset_cache() -> None:
    _cache.clear()
