# Full Signal Stack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the edge-only recommendation system with a 0-100 weighted signal score that incorporates player stats, platoon splits, park factors, weather, umpire tendencies, and lineup data.

**Architecture:** Six signal modules in a `signals/` package feed a central `scorer.py` which returns (score, breakdown). `edge.py`'s `classify()` is replaced by score thresholds. Score + breakdown are stored in both `daily_picks` and `backtest_picks` for validation.

**Tech Stack:** Python 3.11+, SQLite, MLB Stats API (free), Open-Meteo API (free, no key), requests, existing project stack.

---

## File Map

| Action | File | Purpose |
|---|---|---|
| Create | `signals/__init__.py` | Package marker |
| Create | `signals/parks.py` | Static park factors + stadium GPS for all 30 parks |
| Create | `signals/umpires.py` | Static HP umpire K-tendency table + lookup |
| Create | `signals/weather.py` | Open-Meteo wind/temp per game (cached) |
| Create | `signals/splits.py` | MLB Stats API platoon + home/away splits (cached) |
| Create | `signals/lineups.py` | MLB Stats API game data: SP, lineup, umpire |
| Create | `scorer.py` | Weighted 0-100 scoring engine |
| Create | `tests/test_parks.py` | Unit tests for park lookups |
| Create | `tests/test_scorer.py` | Unit tests for scoring math |
| Modify | `config.py` | Add SIGNAL_WEIGHTS, SCORE_RECOMMENDED, SCORE_LEAN |
| Modify | `db.py` | Add signal_score + signal_breakdown columns |
| Modify | `backtest.py` | Add columns to backtest_picks schema + INSERT |
| Modify | `edge.py` | Add `classify_by_score()`, keep old `classify()` |
| Modify | `run_daily.py` | Pre-fetch game data, call scorer, use score for rec |
| Modify | `market_learn.py` | Fix breakeven bug (use per-pick avg, not avg-price BEV) |
| Modify | `dashboard.py` | Replace star display with score bar + breakdown |
| Delete | `confidence.py` | Replaced by scorer.py |

---

## Task 1: DB schema — add signal columns

**Files:**
- Modify: `db.py`
- Modify: `backtest.py`

- [ ] **Step 1: Add columns to `db.py` init_db**

In `db.py`, inside `init_db`, add after the existing `confidence_factors` migration block:

```python
    for col_sql in [
        "ALTER TABLE daily_picks ADD COLUMN signal_score INTEGER",
        "ALTER TABLE daily_picks ADD COLUMN signal_breakdown TEXT",
    ]:
        try:
            conn.execute(col_sql)
            conn.commit()
        except sqlite3.OperationalError:
            pass
```

Also add `update_pick_signal` function at the bottom of `db.py`:

```python
def update_pick_signal(
    conn: sqlite3.Connection,
    pick_id: int,
    score: int,
    breakdown: list[dict],
) -> None:
    import json
    conn.execute(
        "UPDATE daily_picks SET signal_score=?, signal_breakdown=? WHERE id=?",
        (score, json.dumps(breakdown), pick_id),
    )
    conn.commit()
```

- [ ] **Step 2: Add columns to `backtest.py` schema**

In `backtest.py`, inside `init_backtest_db`, add to the `CREATE TABLE IF NOT EXISTS backtest_picks` statement after `profit_units REAL,`:

```sql
            signal_score       INTEGER,
            signal_breakdown   TEXT,
```

Also update `_store_picks` INSERT to include the new fields:

```python
    bt_conn.executemany("""
        INSERT OR IGNORE INTO backtest_picks
            (pick_date, player_name, market_key, selection, point,
             bovada_price, bovada_fair_prob, consensus_fair_prob,
             consensus_book_count, edge, ev, recommendation,
             result, actual_stat, profit_units,
             signal_score, signal_breakdown)
        VALUES
            (:pick_date, :player_name, :market_key, :selection, :point,
             :bovada_price, :bovada_fair_prob, :consensus_fair_prob,
             :consensus_book_count, :edge, :ev, :recommendation,
             :result, :actual_stat, :profit_units,
             :signal_score, :signal_breakdown)
    """, picks)
```

- [ ] **Step 3: Verify migration runs cleanly**

```bash
cd C:\Users\jesse\MLB_V2
python -c "from db import get_conn, init_db; c=get_conn(); init_db(c); print('OK')"
```

Expected output: `OK`

- [ ] **Step 4: Commit**

```bash
git add db.py backtest.py
git commit -m "feat: add signal_score + signal_breakdown columns to picks tables"
```

---

## Task 2: `signals/parks.py` — static park factors + stadium data

**Files:**
- Create: `signals/__init__.py`
- Create: `signals/parks.py`
- Create: `tests/test_parks.py`

- [ ] **Step 1: Create package marker**

Create `signals/__init__.py` as an empty file.

- [ ] **Step 2: Write failing test**

Create `tests/__init__.py` as empty file, then create `tests/test_parks.py`:

```python
from signals.parks import get_park, list_teams, NEUTRAL_PARK

def test_known_park():
    p = get_park("Colorado Rockies")
    assert p["k_factor"] < 100, "Coors should suppress Ks"
    assert p["hr_factor"] > 110, "Coors should boost HRs"
    assert p["is_dome"] is False
    assert "lat" in p and "lon" in p

def test_dome_park():
    p = get_park("Tampa Bay Rays")
    assert p["is_dome"] is True

def test_unknown_team_returns_neutral():
    p = get_park("Nonexistent Team")
    assert p == NEUTRAL_PARK

def test_all_teams_have_required_keys():
    for team in list_teams():
        p = get_park(team)
        for key in ("k_factor", "hits_factor", "tb_factor", "hr_factor",
                    "is_dome", "lat", "lon", "cf_bearing"):
            assert key in p, f"{team} missing {key}"
```

- [ ] **Step 3: Run test — expect failure**

```bash
cd C:\Users\jesse\MLB_V2
python -m pytest tests/test_parks.py -v
```

Expected: `ImportError` or `ModuleNotFoundError`

- [ ] **Step 4: Create `signals/parks.py`**

```python
"""
Static MLB park factors and stadium metadata.
Park factors: 100 = league average. >100 = more of that outcome at this park.
Source: Statcast 3-year rolling park factors (2024-2026 approximation).
cf_bearing: compass bearing (degrees) from home plate to center field.
           Wind blowing IN this direction = tailwind for batters (helps Overs).
Update: once per season or when dramatically stale.
"""

NEUTRAL_PARK = {
    "name": "Unknown",
    "is_dome": False,
    "lat": 39.5, "lon": -98.35,   # geographic center of USA
    "cf_bearing": 0,
    "k_factor": 100, "hits_factor": 100, "tb_factor": 100, "hr_factor": 100,
}

_PARKS: dict[str, dict] = {
    "Arizona Diamondbacks": {
        "name": "Chase Field", "is_dome": True,
        "lat": 33.4453, "lon": -112.0667, "cf_bearing": 330,
        "k_factor": 98, "hits_factor": 105, "tb_factor": 107, "hr_factor": 110,
    },
    "Atlanta Braves": {
        "name": "Truist Park", "is_dome": False,
        "lat": 33.8905, "lon": -84.4677, "cf_bearing": 0,
        "k_factor": 98, "hits_factor": 102, "tb_factor": 103, "hr_factor": 102,
    },
    "Baltimore Orioles": {
        "name": "Camden Yards", "is_dome": False,
        "lat": 39.2838, "lon": -76.6218, "cf_bearing": 10,
        "k_factor": 98, "hits_factor": 106, "tb_factor": 108, "hr_factor": 116,
    },
    "Boston Red Sox": {
        "name": "Fenway Park", "is_dome": False,
        "lat": 42.3467, "lon": -71.0972, "cf_bearing": 85,
        "k_factor": 96, "hits_factor": 110, "tb_factor": 109, "hr_factor": 100,
    },
    "Chicago Cubs": {
        "name": "Wrigley Field", "is_dome": False,
        "lat": 41.9484, "lon": -87.6553, "cf_bearing": 60,
        "k_factor": 97, "hits_factor": 106, "tb_factor": 106, "hr_factor": 107,
    },
    "Chicago White Sox": {
        "name": "Guaranteed Rate Field", "is_dome": False,
        "lat": 41.8300, "lon": -87.6339, "cf_bearing": 350,
        "k_factor": 99, "hits_factor": 102, "tb_factor": 104, "hr_factor": 108,
    },
    "Cincinnati Reds": {
        "name": "Great American Ball Park", "is_dome": False,
        "lat": 39.0975, "lon": -84.5060, "cf_bearing": 10,
        "k_factor": 95, "hits_factor": 107, "tb_factor": 112, "hr_factor": 130,
    },
    "Cleveland Guardians": {
        "name": "Progressive Field", "is_dome": False,
        "lat": 41.4962, "lon": -81.6852, "cf_bearing": 10,
        "k_factor": 101, "hits_factor": 98, "tb_factor": 98, "hr_factor": 95,
    },
    "Colorado Rockies": {
        "name": "Coors Field", "is_dome": False,
        "lat": 39.7559, "lon": -104.9942, "cf_bearing": 50,
        "k_factor": 92, "hits_factor": 126, "tb_factor": 119, "hr_factor": 124,
    },
    "Detroit Tigers": {
        "name": "Comerica Park", "is_dome": False,
        "lat": 42.3390, "lon": -83.0485, "cf_bearing": 355,
        "k_factor": 100, "hits_factor": 99, "tb_factor": 98, "hr_factor": 90,
    },
    "Houston Astros": {
        "name": "Minute Maid Park", "is_dome": True,
        "lat": 29.7573, "lon": -95.3556, "cf_bearing": 340,
        "k_factor": 100, "hits_factor": 100, "tb_factor": 103, "hr_factor": 103,
    },
    "Kansas City Royals": {
        "name": "Kauffman Stadium", "is_dome": False,
        "lat": 39.0517, "lon": -94.4803, "cf_bearing": 15,
        "k_factor": 100, "hits_factor": 101, "tb_factor": 101, "hr_factor": 99,
    },
    "Los Angeles Angels": {
        "name": "Angel Stadium", "is_dome": False,
        "lat": 33.8003, "lon": -117.8827, "cf_bearing": 325,
        "k_factor": 102, "hits_factor": 97, "tb_factor": 97, "hr_factor": 92,
    },
    "Los Angeles Dodgers": {
        "name": "Dodger Stadium", "is_dome": False,
        "lat": 34.0739, "lon": -118.2400, "cf_bearing": 25,
        "k_factor": 103, "hits_factor": 95, "tb_factor": 97, "hr_factor": 95,
    },
    "Miami Marlins": {
        "name": "loanDepot Park", "is_dome": True,
        "lat": 25.7781, "lon": -80.2197, "cf_bearing": 350,
        "k_factor": 101, "hits_factor": 95, "tb_factor": 95, "hr_factor": 91,
    },
    "Milwaukee Brewers": {
        "name": "American Family Field", "is_dome": True,
        "lat": 43.0280, "lon": -87.9712, "cf_bearing": 310,
        "k_factor": 99, "hits_factor": 100, "tb_factor": 101, "hr_factor": 102,
    },
    "Minnesota Twins": {
        "name": "Target Field", "is_dome": False,
        "lat": 44.9817, "lon": -93.2783, "cf_bearing": 330,
        "k_factor": 101, "hits_factor": 99, "tb_factor": 100, "hr_factor": 99,
    },
    "New York Mets": {
        "name": "Citi Field", "is_dome": False,
        "lat": 40.7571, "lon": -73.8458, "cf_bearing": 350,
        "k_factor": 103, "hits_factor": 95, "tb_factor": 96, "hr_factor": 87,
    },
    "New York Yankees": {
        "name": "Yankee Stadium", "is_dome": False,
        "lat": 40.8296, "lon": -73.9262, "cf_bearing": 315,
        "k_factor": 100, "hits_factor": 99, "tb_factor": 109, "hr_factor": 126,
    },
    "Oakland Athletics": {
        "name": "Sutter Health Park", "is_dome": False,
        "lat": 38.5833, "lon": -121.5100, "cf_bearing": 0,
        "k_factor": 100, "hits_factor": 98, "tb_factor": 97, "hr_factor": 95,
    },
    "Philadelphia Phillies": {
        "name": "Citizens Bank Park", "is_dome": False,
        "lat": 39.9061, "lon": -75.1665, "cf_bearing": 355,
        "k_factor": 97, "hits_factor": 107, "tb_factor": 110, "hr_factor": 121,
    },
    "Pittsburgh Pirates": {
        "name": "PNC Park", "is_dome": False,
        "lat": 40.4469, "lon": -80.0057, "cf_bearing": 30,
        "k_factor": 101, "hits_factor": 99, "tb_factor": 98, "hr_factor": 96,
    },
    "San Diego Padres": {
        "name": "Petco Park", "is_dome": False,
        "lat": 32.7076, "lon": -117.1570, "cf_bearing": 325,
        "k_factor": 102, "hits_factor": 93, "tb_factor": 94, "hr_factor": 91,
    },
    "San Francisco Giants": {
        "name": "Oracle Park", "is_dome": False,
        "lat": 37.7786, "lon": -122.3893, "cf_bearing": 355,
        "k_factor": 104, "hits_factor": 88, "tb_factor": 91, "hr_factor": 78,
    },
    "Seattle Mariners": {
        "name": "T-Mobile Park", "is_dome": False,
        "lat": 47.5914, "lon": -122.3325, "cf_bearing": 0,
        "k_factor": 101, "hits_factor": 96, "tb_factor": 96, "hr_factor": 88,
    },
    "St. Louis Cardinals": {
        "name": "Busch Stadium", "is_dome": False,
        "lat": 38.6226, "lon": -90.1928, "cf_bearing": 0,
        "k_factor": 101, "hits_factor": 97, "tb_factor": 98, "hr_factor": 94,
    },
    "Tampa Bay Rays": {
        "name": "Tropicana Field", "is_dome": True,
        "lat": 27.7683, "lon": -82.6534, "cf_bearing": 0,
        "k_factor": 100, "hits_factor": 97, "tb_factor": 97, "hr_factor": 100,
    },
    "Texas Rangers": {
        "name": "Globe Life Field", "is_dome": True,
        "lat": 32.7512, "lon": -97.0826, "cf_bearing": 0,
        "k_factor": 100, "hits_factor": 99, "tb_factor": 100, "hr_factor": 100,
    },
    "Toronto Blue Jays": {
        "name": "Rogers Centre", "is_dome": True,
        "lat": 43.6414, "lon": -79.3892, "cf_bearing": 320,
        "k_factor": 99, "hits_factor": 101, "tb_factor": 104, "hr_factor": 107,
    },
    "Washington Nationals": {
        "name": "Nationals Park", "is_dome": False,
        "lat": 38.8730, "lon": -77.0074, "cf_bearing": 355,
        "k_factor": 100, "hits_factor": 99, "tb_factor": 100, "hr_factor": 100,
    },
}

# Alias map for alternate team name spellings from The Odds API
_ALIASES: dict[str, str] = {
    "Athletics":                  "Oakland Athletics",
    "Sacramento Athletics":       "Oakland Athletics",
    "Diamondbacks":               "Arizona Diamondbacks",
    "D-backs":                    "Arizona Diamondbacks",
}


def get_park(home_team: str) -> dict:
    """Return park data for the home team. Falls back to NEUTRAL_PARK."""
    team = _ALIASES.get(home_team, home_team)
    return _PARKS.get(team, NEUTRAL_PARK)


def list_teams() -> list[str]:
    return list(_PARKS.keys())
```

- [ ] **Step 5: Run tests — expect pass**

```bash
cd C:\Users\jesse\MLB_V2
python -m pytest tests/test_parks.py -v
```

Expected: 4 tests PASSED

- [ ] **Step 6: Commit**

```bash
git add signals/__init__.py signals/parks.py tests/__init__.py tests/test_parks.py
git commit -m "feat: add signals/parks.py with static park factors for all 30 MLB parks"
```

---

## Task 3: `signals/umpires.py` — static HP umpire K-tendency

**Files:**
- Create: `signals/umpires.py`

- [ ] **Step 1: Create `signals/umpires.py`**

```python
"""
Home plate umpire K-tendency scores.
Scale: -1.0 = very tight zone (fewer Ks), 0.0 = league avg, +1.0 = wide zone (more Ks).
Source: UmpScorecards historical data (approximate, refresh periodically).
"""
from __future__ import annotations

_UMPIRES: dict[str, float] = {
    "jordan baker":        0.3,
    "vic carapazza":       0.3,
    "alan porter":         0.3,
    "pat hoberg":          0.2,
    "adam hamari":         0.2,
    "tripp gibson":        0.2,
    "tim timmons":         0.2,
    "hunter wendelstedt":  0.2,
    "bill miller":         0.1,
    "james hoye":          0.1,
    "cory blaser":         0.1,
    "scott barry":         0.1,
    "ron kulpa":           0.1,
    "todd tichenor":       0.1,
    "paul nauert":         0.2,
    "mike muchlinski":     0.2,
    "nic lentz":           0.1,
    "david rackley":       0.1,
    "shane livensparger":  0.1,
    "chris guccione":      0.0,
    "ted barrett":         0.0,
    "dan iassogna":        0.0,
    "manny gonzalez":      0.1,
    "mark ripperger":      0.0,
    "ryan blakney":        0.0,
    "nate tomlinson":      0.1,
    "john bacon":          0.0,
    "edwin moscoso":       0.0,
    "ben may":             0.0,
    "jeremie rehak":       0.0,
    "chris conroy":        0.0,
    "brennan miller":      0.1,
    "jeff nelson":         0.1,
    "sam holbrook":       -0.1,
    "phil cuzzi":         -0.1,
    "tom hallion":        -0.1,
    "gary cederstrom":    -0.2,
    "roberto ortiz":      -0.2,
    "dan bellino":        -0.2,
    "marty foster":       -0.2,
    "jerry meals":        -0.2,
    "cb bucknor":         -0.3,
    "laz diaz":           -0.3,
    "lance barksdale":    -0.3,
    "adrian johnson":     -0.1,
}


def get_ump_k_tendency(umpire_name: str | None) -> float:
    """Return K-tendency for umpire name. 0.0 if unknown."""
    if not umpire_name:
        return 0.0
    return _UMPIRES.get(umpire_name.lower().strip(), 0.0)
```

- [ ] **Step 2: Quick smoke test**

```bash
cd C:\Users\jesse\MLB_V2
python -c "from signals.umpires import get_ump_k_tendency; print(get_ump_k_tendency('Jordan Baker'), get_ump_k_tendency('Nobody'))"
```

Expected: `0.3 0.0`

- [ ] **Step 3: Commit**

```bash
git add signals/umpires.py
git commit -m "feat: add signals/umpires.py with HP umpire K-tendency table"
```

---

## Task 4: `signals/weather.py` — Open-Meteo wind + temp

**Files:**
- Create: `signals/weather.py`

- [ ] **Step 1: Create `signals/weather.py`**

```python
"""
Game weather via Open-Meteo archive/forecast API (free, no key required).
Returns wind tailwind factor relative to each park's cf_bearing.
Dome stadiums return neutral weather (zeros).
Results cached in-memory per (lat, lon, date).
"""
from __future__ import annotations
import math
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
    """
    diff = abs((wind_dir_deg - cf_bearing_deg + 180) % 360 - 180)
    # diff=0 → wind blows exactly toward CF (tailwind for batters) → 1.0
    # diff=180 → wind blows exactly from CF (headwind for batters) → 0.0
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
```

- [ ] **Step 2: Smoke test (live call)**

```bash
cd C:\Users\jesse\MLB_V2
python -c "
from signals.weather import get_weather
# Wrigley Field, 2026-05-15, CF bearing = 60 degrees
w = get_weather(41.9484, -87.6553, '2026-05-15', cf_bearing=60, is_dome=False)
print(w)
"
```

Expected: dict with `wind_speed_kph`, `tailwind_factor` between 0 and 1, no error.

- [ ] **Step 3: Dome returns neutral**

```bash
python -c "
from signals.weather import get_weather
w = get_weather(29.7573, -95.3556, '2026-05-15', cf_bearing=340, is_dome=True)
print(w['is_dome'], w['tailwind_factor'])
"
```

Expected: `True 0.5`

- [ ] **Step 4: Commit**

```bash
git add signals/weather.py
git commit -m "feat: add signals/weather.py using Open-Meteo free API"
```

---

## Task 5: `signals/splits.py` — MLB Stats API platoon + home/away splits

**Files:**
- Create: `signals/splits.py`

- [ ] **Step 1: Create `signals/splits.py`**

```python
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
    "k_pct_vs_lhh": None, "k_pct_vs_rhh": None,
    "h9_vs_lhh": None,    "h9_vs_rhh": None,
    "era_home": None,      "era_away": None,
    "slg_vs_lhp": None,   "slg_vs_rhp": None,
    "avg_vs_lhp": None,   "avg_vs_rhp": None,
    "tb_home": None,       "tb_away": None,
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
```

- [ ] **Step 2: Commit**

```bash
git add signals/splits.py
git commit -m "feat: add signals/splits.py for platoon and home/away splits"
```

---

## Task 6: `signals/lineups.py` — game data pre-fetch

**Files:**
- Create: `signals/lineups.py`

- [ ] **Step 1: Create `signals/lineups.py`**

```python
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
    from datetime import datetime
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
    # partial match fallback
    for (h, a), info in game_data.items():
        if home_team.lower() in h or h in home_team.lower():
            if away_team.lower() in a or a in away_team.lower():
                return info
    return None
```

- [ ] **Step 2: Smoke test**

```bash
cd C:\Users\jesse\MLB_V2
python -c "
from signals.lineups import get_game_data_for_date
games = get_game_data_for_date('2026-05-15')
print(f'{len(games)} games found')
for key, g in list(games.items())[:2]:
    print(key, g['umpire_name'], g['home_sp']['name'], g['home_sp']['era'])
"
```

Expected: prints game count and SP names without errors.

- [ ] **Step 3: Commit**

```bash
git add signals/lineups.py
git commit -m "feat: add signals/lineups.py for SP/umpire/lineup pre-fetch"
```

---

## Task 7: `scorer.py` + update `config.py`

**Files:**
- Create: `scorer.py`
- Modify: `config.py`
- Create: `tests/test_scorer.py`

- [ ] **Step 1: Add weights + thresholds to `config.py`**

Append to the end of `config.py`:

```python
# ── Signal scoring ────────────────────────────────────────────────────────────

SCORE_RECOMMENDED = 65   # score >= this → RECOMMENDED
SCORE_LEAN        = 45   # score >= this → LEAN (else NO_BET)

# Per-market signal weights. Values are max points each signal can contribute.
# Sum of each dict should equal 100.
SIGNAL_WEIGHTS: dict[str, dict[str, int]] = {
    "pitcher_strikeouts": {
        "platoon_alignment": 20,
        "season_k_pct":      18,
        "ump_k_tendency":    15,
        "park_k_factor":     12,
        "recent_k_rate":     12,
        "opp_team_k_pct":    10,
        "weather":            8,
        "edge":               5,
    },
    "pitcher_hits_allowed": {
        "recent_h9":         22,
        "opp_team_woba":     20,
        "park_hits_factor":  18,
        "season_whip":       15,
        "platoon_alignment": 12,
        "weather":            8,
        "edge":               5,
    },
    "pitcher_outs": {
        "recent_ip":         25,
        "opp_lineup_ops":    20,
        "season_ip":         18,
        "park_run_factor":   15,
        "weather":           12,
        "edge":              10,
    },
    "batter_total_bases": {
        "sp_quality":        22,
        "platoon_alignment": 18,
        "recent_tb":         15,
        "park_tb_factor":    15,
        "season_slg":        12,
        "weather_wind":      10,
        "edge":               8,
    },
    "batter_hits": {
        "sp_quality":        22,
        "platoon_alignment": 18,
        "recent_h":          15,
        "park_hits_factor":  15,
        "season_avg":        12,
        "weather":           10,
        "edge":               8,
    },
}

# Default weights used when market has no specific entry
SIGNAL_WEIGHTS_DEFAULT: dict[str, int] = {
    "recent_form":  35,
    "park_factor":  25,
    "weather":      20,
    "edge":         20,
}
```

- [ ] **Step 2: Write failing scorer tests**

Create `tests/test_scorer.py`:

```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from scorer import (
    _edge_signal, _park_factor_signal, _ump_signal,
    _weather_signal, _clamp, score_pick,
)


def test_clamp():
    assert _clamp(1.5) == 1.0
    assert _clamp(-0.1) == 0.0
    assert _clamp(0.5) == 0.5


def test_edge_signal_positive():
    # 4% edge should be around 0.5
    assert 0.4 <= _edge_signal(0.04) <= 0.6


def test_edge_signal_negative():
    assert _edge_signal(-0.05) == 0.0


def test_edge_signal_max():
    assert _edge_signal(0.10) == 1.0


def test_park_k_over_high_k_park():
    # Coors has k_factor=92, should score low for K Over
    assert _park_factor_signal(92, "Over") < 0.4


def test_park_k_over_neutral():
    assert abs(_park_factor_signal(100, "Over") - 0.5) < 0.1


def test_park_k_under_high_k_park():
    # High K park (factor=108) should score low for K Under
    assert _park_factor_signal(108, "Under") < 0.4


def test_ump_signal_high_k_over():
    # High-K ump (+0.3) with K Over should score > 0.5
    assert _ump_signal(0.3, "Over") > 0.5


def test_ump_signal_low_k_under():
    # Low-K ump (-0.3) with K Under should score > 0.5
    assert _ump_signal(-0.3, "Under") > 0.5


def test_weather_neutral():
    w = {"tailwind_factor": 0.5, "cold_penalty": 0.0, "wind_speed_kph": 5}
    assert abs(_weather_signal(w, "Over") - 0.5) < 0.15


def test_score_pick_returns_tuple():
    result = score_pick(
        player_name="Test Player",
        market_key="pitcher_strikeouts",
        selection="Over",
        point=5.5,
        home_team="Colorado Rockies",
        away_team="Los Angeles Dodgers",
        edge=0.03,
        game_date="2026-05-15",
        game_data=None,
    )
    assert isinstance(result, tuple)
    score, breakdown = result
    assert 0 <= score <= 100
    assert isinstance(breakdown, list)
    assert all("signal" in b and "pts" in b for b in breakdown)
```

- [ ] **Step 3: Run tests — expect failure**

```bash
cd C:\Users\jesse\MLB_V2
python -m pytest tests/test_scorer.py -v
```

Expected: `ImportError` — scorer.py doesn't exist yet

- [ ] **Step 4: Create `scorer.py`**

```python
"""
Weighted signal scoring engine for MLB prop picks.
Returns (score 0-100, breakdown list) per pick.
"""
from __future__ import annotations
import json
from datetime import datetime

from config import SIGNAL_WEIGHTS, SIGNAL_WEIGHTS_DEFAULT, SCORE_RECOMMENDED, SCORE_LEAN
from signals.parks import get_park
from signals.weather import get_weather
from signals.umpires import get_ump_k_tendency


# ── helpers ───────────────────────────────────────────────────────────────────

def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def _edge_signal(edge: float) -> float:
    """0.0 at edge≤0%, 1.0 at edge≥8%."""
    return _clamp(edge / 0.08)


def _park_factor_signal(factor: int, selection: str) -> float:
    """
    For Over: high factor (>100) is good → 1.0; low factor (<100) is bad → 0.0.
    For Under: inverted.
    Neutral at 100 → 0.5.
    """
    normalized = _clamp((factor - 85) / 30.0)   # 85→0, 100→0.5, 115→1.0
    return normalized if selection == "Over" else 1.0 - normalized


def _ump_signal(k_tendency: float, selection: str) -> float:
    """
    k_tendency in [-1, +1]. For K Over: positive tendency is good.
    For K Under: negative tendency is good.
    """
    normalized = _clamp((k_tendency + 1.0) / 2.0)  # -1→0, 0→0.5, +1→1
    return normalized if selection == "Over" else 1.0 - normalized


def _weather_signal(weather: dict, selection: str) -> float:
    """
    Combines tailwind_factor and cold_penalty into 0-1 for Over/Under.
    """
    if weather.get("is_dome"):
        return 0.5
    tf = weather.get("tailwind_factor", 0.5)
    cold = weather.get("cold_penalty", 0.0)
    wind_speed = weather.get("wind_speed_kph", 0.0)
    # Scale tailwind only when wind is meaningful (>10 kph)
    wind_weight = _clamp(wind_speed / 30.0)
    wind_effect = tf * wind_weight + 0.5 * (1.0 - wind_weight)
    # Cold reduces runs (good for Unders, bad for Overs)
    cold_effect = 0.5 - cold * 0.5   # cold=0 → 0.5, cold=1 → 0.0
    raw = (wind_effect * 0.7) + (cold_effect * 0.3)
    return raw if selection == "Over" else 1.0 - raw


def _recent_rate_signal(recent: float | None, point: float,
                        selection: str, margin: float = 0.5) -> float:
    """
    How does recent average compare to the line?
    Over: recent >> line is good. Under: recent << line is good.
    """
    if recent is None:
        return 0.5
    diff = recent - point
    # diff = +2 → clearly over the line → 1.0 for Over
    # diff = -2 → clearly under the line → 0.0 for Over
    normalized = _clamp(0.5 + diff / (2.0 * (margin + 1.0)))
    return normalized if selection == "Over" else 1.0 - normalized


def _era_signal(era: float | None, selection: str) -> float:
    """High ERA = bad pitcher = good for batter Over, bad for batter Under."""
    if era is None:
        return 0.5
    # ERA 2.0 → 0.0 (great pitcher, bad for Over)
    # ERA 4.5 → 0.5 (neutral)
    # ERA 7.0+ → 1.0 (bad pitcher, good for Over)
    normalized = _clamp((era - 2.0) / 5.0)
    return normalized if selection == "Over" else 1.0 - normalized


def _season_rate_signal(rate: float | None, benchmark: float,
                        selection: str, spread: float = 0.05) -> float:
    """Generic: how does season rate compare to a benchmark?"""
    if rate is None:
        return 0.5
    normalized = _clamp(0.5 + (rate - benchmark) / (2 * spread))
    return normalized if selection == "Over" else 1.0 - normalized


def _platoon_signal(pitcher_hand: str | None,
                    batter_or_pitcher: str,
                    split_stat_same: float | None,
                    split_stat_opp: float | None,
                    selection: str) -> float:
    """
    Compare performance vs same-hand vs opp-hand.
    Better vs this batter type = higher score for corresponding direction.
    """
    if split_stat_same is None or split_stat_opp is None:
        return 0.5
    diff = split_stat_same - split_stat_opp
    # diff > 0: better vs this matchup → good for Over (if it's an offensive stat)
    normalized = _clamp(0.5 + diff / 0.4)
    return normalized if selection == "Over" else 1.0 - normalized


# ── per-market scoring ─────────────────────────────────────────────────────────

def _score_pitcher_strikeouts(
    player_id: int | None,
    selection: str,
    point: float,
    edge: float,
    park: dict,
    weather: dict,
    game_info: dict | None,
    season: int,
) -> list[dict]:
    from stats import fetch_pitcher_stats, fetch_team_hitting
    from signals.splits import get_pitcher_splits

    weights = SIGNAL_WEIGHTS["pitcher_strikeouts"]
    breakdown = []

    def add(signal: str, raw: float, note: str = ""):
        pts = round(raw * weights.get(signal, 0))
        breakdown.append({"signal": signal, "raw": round(raw, 3),
                          "pts": pts, "max": weights.get(signal, 0), "note": note})

    # edge
    add("edge", _edge_signal(edge), f"edge={edge:.1%}")

    # park K factor
    kf = park.get("k_factor", 100)
    add("park_k_factor", _park_factor_signal(kf, selection), f"k_factor={kf}")

    # umpire
    ump_k = game_info.get("ump_k_tendency", 0.0) if game_info else 0.0
    ump_name = game_info.get("umpire_name", "unknown") if game_info else "unknown"
    add("ump_k_tendency", _ump_signal(ump_k, selection), f"ump={ump_name} ({ump_k:+.1f})")

    # weather
    add("weather", _weather_signal(weather, selection),
        f"wind={weather.get('wind_speed_kph', 0):.0f}kph tf={weather.get('tailwind_factor', 0.5):.2f}")

    # player stats
    if player_id:
        stats = fetch_pitcher_stats(player_id, season) or {}
        recent_k = stats.get("recent_k")
        add("recent_k_rate", _recent_rate_signal(recent_k, point, selection, 0.5),
            f"recent_k={recent_k}")

        k9 = stats.get("season_k9")
        # For K Over: K/9 >= 9 is good → benchmark 8.0
        add("season_k_pct", _season_rate_signal(k9, 8.0, selection, spread=1.5),
            f"k9={k9}")

        # opp team K% from team hitting stats
        opp_team = (game_info.get("away_team") if game_info else None)
        if opp_team:
            team = fetch_team_hitting(opp_team, season) or {}
            k_pct = team.get("k_pct")
            # league avg ~22.8%, spread of 5%
            add("opp_team_k_pct", _season_rate_signal(k_pct, 0.228, selection, 0.05),
                f"opp_k_pct={k_pct:.1%}" if k_pct else "opp_k_pct=None")

        # platoon
        splits = get_pitcher_splits(player_id, season)
        k9_vl = splits.get("k9_vs_lhh")
        k9_vr = splits.get("k9_vs_rhh")
        if game_info:
            sp_hand = (game_info.get("home_sp", {}).get("hand") or
                       game_info.get("away_sp", {}).get("hand"))
        else:
            sp_hand = None
        if k9_vl and k9_vr:
            # For K Over: want high K rate vs this lineup
            # If pitcher is RHP, he faces mostly the lineup's handedness
            # Use whichever split is better/worse for the direction
            avg_k9 = (k9_vl + k9_vr) / 2
            add("platoon_alignment",
                _season_rate_signal(avg_k9, 8.0, selection, 1.5),
                f"k9_vL={k9_vl} k9_vR={k9_vr}")
        else:
            add("platoon_alignment", 0.5, "splits unavailable")
    else:
        for sig in ("recent_k_rate", "season_k_pct", "opp_team_k_pct", "platoon_alignment"):
            add(sig, 0.5, "player_id unavailable")

    return breakdown


def _score_pitcher_hits_allowed(
    player_id: int | None,
    selection: str,
    point: float,
    edge: float,
    park: dict,
    weather: dict,
    game_info: dict | None,
    season: int,
) -> list[dict]:
    from stats import fetch_pitcher_stats, fetch_team_hitting
    from signals.splits import get_pitcher_splits

    weights = SIGNAL_WEIGHTS["pitcher_hits_allowed"]
    breakdown = []

    def add(signal, raw, note=""):
        pts = round(raw * weights.get(signal, 0))
        breakdown.append({"signal": signal, "raw": round(raw, 3),
                          "pts": pts, "max": weights.get(signal, 0), "note": note})

    add("edge", _edge_signal(edge), f"edge={edge:.1%}")

    hf = park.get("hits_factor", 100)
    add("park_hits_factor", _park_factor_signal(hf, selection), f"hits_factor={hf}")

    add("weather", _weather_signal(weather, selection),
        f"wind={weather.get('wind_speed_kph', 0):.0f}kph")

    if player_id:
        stats = fetch_pitcher_stats(player_id, season) or {}
        recent_h = stats.get("recent_h")
        add("recent_h9", _recent_rate_signal(recent_h, point, selection, 0.5),
            f"recent_h={recent_h}")

        whip = stats.get("season_whip")
        # WHIP: 1.0 is excellent (fewer hits), 1.5 is poor. For Under: low WHIP is good.
        add("season_whip", _season_rate_signal(whip, 1.25, "Under" if selection == "Under" else "Over", 0.15),
            f"whip={whip}")

        opp_team = (game_info.get("away_team") if game_info else None)
        if opp_team:
            team = fetch_team_hitting(opp_team, season) or {}
            team_avg = team.get("avg")
            # League avg ~.244. Higher BA = more hits against pitcher.
            add("opp_team_woba", _season_rate_signal(team_avg, 0.244, selection, 0.015),
                f"opp_avg={team_avg:.3f}" if team_avg else "opp_avg=None")
        else:
            add("opp_team_woba", 0.5, "opp_team unavailable")

        splits = get_pitcher_splits(player_id, season)
        h9_vl = splits.get("h9_vs_lhh")
        h9_vr = splits.get("h9_vs_rhh")
        if h9_vl and h9_vr:
            avg_h9 = (h9_vl + h9_vr) / 2
            add("platoon_alignment",
                _season_rate_signal(avg_h9, 9.0, selection, 1.5),
                f"h9_vL={h9_vl} h9_vR={h9_vr}")
        else:
            add("platoon_alignment", 0.5, "splits unavailable")
    else:
        for sig in ("recent_h9", "season_whip", "opp_team_woba", "platoon_alignment"):
            add(sig, 0.5, "player_id unavailable")

    return breakdown


def _score_pitcher_outs(
    player_id: int | None,
    selection: str,
    point: float,
    edge: float,
    park: dict,
    weather: dict,
    game_info: dict | None,
    season: int,
) -> list[dict]:
    from stats import fetch_pitcher_stats, fetch_team_hitting

    weights = SIGNAL_WEIGHTS["pitcher_outs"]
    breakdown = []

    def add(signal, raw, note=""):
        pts = round(raw * weights.get(signal, 0))
        breakdown.append({"signal": signal, "raw": round(raw, 3),
                          "pts": pts, "max": weights.get(signal, 0), "note": note})

    add("edge", _edge_signal(edge), f"edge={edge:.1%}")

    rf = park.get("hr_factor", 100)  # high HR park = shorter outings (closer games, more bullpen)
    add("park_run_factor", _park_factor_signal(rf, "Under" if selection == "Over" else "Over"),
        f"hr_factor={rf}")

    add("weather", _weather_signal(weather, selection),
        f"wind={weather.get('wind_speed_kph', 0):.0f}kph")

    if player_id:
        stats = fetch_pitcher_stats(player_id, season) or {}
        # Use recent_er as a proxy for how deep pitchers go (more ER = shorter outing)
        # Better: use IP per start. Proxy: outs = IP * 3, line typically 15-18
        recent_k = stats.get("recent_k")  # more Ks = longer outings (pitcher in control)
        add("recent_ip", _recent_rate_signal(recent_k, point / 3.0, selection, 1.0),
            f"recent_k={recent_k} (proxy for IP)")

        k9 = stats.get("season_k9")
        add("season_ip", _season_rate_signal(k9, 8.0, selection, 1.5),
            f"season_k9={k9}")

        opp_team = (game_info.get("away_team") if game_info else None)
        if opp_team:
            team = fetch_team_hitting(opp_team, season) or {}
            ops = team.get("ops")
            # High OPS = dangerous lineup = shorter pitcher outing = bad for Outs Over
            add("opp_lineup_ops", _season_rate_signal(ops, 0.720, "Under" if selection == "Over" else "Over", 0.04),
                f"opp_ops={ops:.3f}" if ops else "opp_ops=None")
        else:
            add("opp_lineup_ops", 0.5, "opp_team unavailable")
    else:
        for sig in ("recent_ip", "season_ip", "opp_lineup_ops"):
            add(sig, 0.5, "player_id unavailable")

    return breakdown


def _score_batter(
    player_id: int | None,
    market_key: str,
    selection: str,
    point: float,
    edge: float,
    park: dict,
    weather: dict,
    game_info: dict | None,
    home_team: str,
    away_team: str,
    season: int,
) -> list[dict]:
    from stats import fetch_batter_stats
    from signals.splits import get_batter_splits

    is_tb = market_key == "batter_total_bases"
    weights = SIGNAL_WEIGHTS.get(market_key, SIGNAL_WEIGHTS_DEFAULT)
    breakdown = []

    def add(signal, raw, note=""):
        pts = round(raw * weights.get(signal, 0))
        breakdown.append({"signal": signal, "raw": round(raw, 3),
                          "pts": pts, "max": weights.get(signal, 0), "note": note})

    add("edge", _edge_signal(edge), f"edge={edge:.1%}")

    # park factor
    pf = park.get("tb_factor" if is_tb else "hits_factor", 100)
    add("park_tb_factor" if is_tb else "park_hits_factor",
        _park_factor_signal(pf, selection), f"park_factor={pf}")

    # weather
    add("weather_wind" if is_tb else "weather",
        _weather_signal(weather, selection),
        f"tailwind={weather.get('tailwind_factor', 0.5):.2f}")

    # SP quality — find the opposing SP
    sp = None
    if game_info:
        # Determine which team the batter is on (home or away)
        # If player is on the home team, they face the away SP
        sp = game_info.get("away_sp") or game_info.get("home_sp")
    if sp and sp.get("era") is not None:
        add("sp_quality", _era_signal(sp["era"], selection),
            f"sp={sp.get('name','?')} ERA={sp['era']:.2f}")
    else:
        add("sp_quality", 0.5, "SP ERA unavailable")

    if player_id:
        stats = fetch_batter_stats(player_id, season) or {}
        recent_key = "recent_tb_per_game" if is_tb else "recent_h_per_game"
        recent = stats.get(recent_key)
        add("recent_tb" if is_tb else "recent_h",
            _recent_rate_signal(recent, point, selection, 0.3),
            f"recent={recent}")

        season_key = "season_slg" if is_tb else "season_avg"
        rate = stats.get(season_key)
        benchmark = 0.420 if is_tb else 0.255  # approx league avg SLG / BA
        add("season_slg" if is_tb else "season_avg",
            _season_rate_signal(rate, benchmark, selection, 0.06 if is_tb else 0.03),
            f"{season_key}={rate}")

        # platoon splits
        splits = get_batter_splits(player_id, season)
        sp_hand = sp.get("hand") if sp else None
        if sp_hand in ("L", "R"):
            slg_key = f"slg_vs_{'lhp' if sp_hand == 'L' else 'rhp'}"
            slg_opp = f"slg_vs_{'rhp' if sp_hand == 'L' else 'lhp'}"
            s1, s2 = splits.get(slg_key), splits.get(slg_opp)
            add("platoon_alignment",
                _platoon_signal(sp_hand, "batter", s1, s2, selection),
                f"slg_vs_{sp_hand}={s1} vs_opp={s2}")
        else:
            add("platoon_alignment", 0.5, "SP hand unknown")
    else:
        for sig in ("recent_tb", "recent_h", "season_slg", "season_avg", "platoon_alignment"):
            if sig in weights:
                add(sig, 0.5, "player_id unavailable")

    return breakdown


# ── main entry point ──────────────────────────────────────────────────────────

def score_pick(
    player_name: str,
    market_key: str,
    selection: str,
    point: float,
    home_team: str,
    away_team: str,
    edge: float,
    game_date: str,
    game_data: dict | None = None,
) -> tuple[int, list[dict]]:
    """
    Returns (score 0-100, breakdown list).
    breakdown items: {signal, raw, pts, max, note}
    game_data: pre-fetched from lineups.get_game_data_for_date(). None = partial score.
    """
    from datetime import datetime
    from stats import find_player_info

    season = int(game_date[:4])

    park = get_park(home_team)

    weather_data = get_weather(
        park["lat"], park["lon"], game_date,
        park["cf_bearing"], park["is_dome"]
    )

    game_info = None
    if game_data is not None:
        from signals.lineups import find_game
        game_info = find_game(game_data, home_team, away_team)

    # Resolve player_id
    player_id = None
    try:
        info = find_player_info(player_name, season)
        if info:
            player_id = info["id"]
    except Exception:
        pass

    try:
        if market_key == "pitcher_strikeouts":
            breakdown = _score_pitcher_strikeouts(
                player_id, selection, point, edge, park, weather_data, game_info, season)
        elif market_key == "pitcher_hits_allowed":
            breakdown = _score_pitcher_hits_allowed(
                player_id, selection, point, edge, park, weather_data, game_info, season)
        elif market_key == "pitcher_outs":
            breakdown = _score_pitcher_outs(
                player_id, selection, point, edge, park, weather_data, game_info, season)
        elif market_key in ("batter_total_bases", "batter_hits"):
            breakdown = _score_batter(
                player_id, market_key, selection, point, edge,
                park, weather_data, game_info, home_team, away_team, season)
        else:
            # Minimal score for unsupported markets
            breakdown = [{"signal": "edge", "raw": _edge_signal(edge),
                          "pts": round(_edge_signal(edge) * 50), "max": 50, "note": "unsupported market"}]
    except Exception as exc:
        breakdown = [{"signal": "error", "raw": 0.5, "pts": 0, "max": 0, "note": str(exc)}]

    total = sum(b["pts"] for b in breakdown)
    return int(min(100, max(0, total))), breakdown


def tier_from_score(score: int) -> str:
    """RECOMMENDED / LEAN / NO_BET based on score thresholds."""
    if score >= SCORE_RECOMMENDED:
        return "RECOMMENDED"
    if score >= SCORE_LEAN:
        return "LEAN"
    return "NO_BET"
```

- [ ] **Step 5: Run scorer tests**

```bash
cd C:\Users\jesse\MLB_V2
python -m pytest tests/test_scorer.py -v
```

Expected: all tests PASS

- [ ] **Step 6: Commit**

```bash
git add scorer.py config.py tests/test_scorer.py
git commit -m "feat: add scorer.py weighted signal engine + SIGNAL_WEIGHTS to config"
```

---

## Task 8: Update `edge.py` — add score-based classify

**Files:**
- Modify: `edge.py`

- [ ] **Step 1: Add `classify_by_score()` to `edge.py`**

Replace the contents of `edge.py` with:

```python
from consensus import american_to_decimal
from config import (
    EDGE_RECOMMENDED, EDGE_MIN_BET, BET_WHITELIST,
    BET_PRICE_MIN, BET_PRICE_MAX,
    SCORE_RECOMMENDED, SCORE_LEAN,
)


def bovada_break_even(price: int) -> float:
    """Raw implied probability from Bovada price. Not vig-removed."""
    return 1.0 / american_to_decimal(price)


def compute_edge(consensus_fair_prob: float, break_even_prob: float) -> float:
    return consensus_fair_prob - break_even_prob


def compute_ev(bovada_price: int, consensus_fair_prob: float) -> float:
    decimal_odds = american_to_decimal(bovada_price)
    return consensus_fair_prob * decimal_odds - 1.0


def classify(edge: float, ev: float, *, market_key: str = "", selection: str = "", price: int = 0) -> str:
    """Legacy edge-only classifier. Kept for backtest replay compatibility."""
    if (market_key, selection) not in BET_WHITELIST:
        return "NO_BET"
    if not (BET_PRICE_MIN <= price <= BET_PRICE_MAX):
        return "NO_BET"
    if edge >= EDGE_RECOMMENDED:
        return "RECOMMENDED"
    if edge >= EDGE_MIN_BET:
        return "LEAN"
    return "NO_BET"


def classify_by_score(score: int, edge: float, market_key: str, selection: str) -> str:
    """
    Score-based classifier (new system).
    Hard gates: market+direction must be whitelisted, edge must be > 0%.
    Score determines tier.
    """
    if (market_key, selection) not in BET_WHITELIST:
        return "NO_BET"
    if edge <= 0.0:
        return "NO_BET"
    if score >= SCORE_RECOMMENDED:
        return "RECOMMENDED"
    if score >= SCORE_LEAN:
        return "LEAN"
    return "NO_BET"
```

- [ ] **Step 2: Quick smoke test**

```bash
cd C:\Users\jesse\MLB_V2
python -c "
from edge import classify_by_score
print(classify_by_score(70, 0.03, 'pitcher_outs', 'Over'))    # RECOMMENDED
print(classify_by_score(50, 0.01, 'pitcher_outs', 'Over'))    # LEAN
print(classify_by_score(30, 0.03, 'pitcher_outs', 'Over'))    # NO_BET
print(classify_by_score(70, -0.01, 'pitcher_outs', 'Over'))   # NO_BET (neg edge)
print(classify_by_score(70, 0.03, 'batter_total_bases', 'Over'))  # NO_BET (not whitelisted)
"
```

Expected:
```
RECOMMENDED
LEAN
NO_BET
NO_BET
NO_BET
```

- [ ] **Step 3: Commit**

```bash
git add edge.py
git commit -m "feat: add classify_by_score() to edge.py — score-driven recommendation tiers"
```

---

## Task 9: Wire scorer into `run_daily.py`

**Files:**
- Modify: `run_daily.py`

- [ ] **Step 1: Replace `_score_picks` and update `_analyze` in `run_daily.py`**

Replace the existing `_score_picks` function and update the imports + `_analyze` function. The full updated `run_daily.py`:

```python
#!/usr/bin/env python3
"""
MLB V2 — daily pipeline.
Run once per day before first pitch (recommended: 9 AM PT).

Usage:
    python run_daily.py
"""
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from config import PICKS_DIR, BOVADA_KEYS, MIN_CONSENSUS_BOOKS
from db import get_conn, init_db, upsert_pick, log_no_bet, get_snapshots, update_pick_signal
from pull_props import pull_and_store
from consensus import compute_consensus, vig_remove_pair
from edge import bovada_break_even, compute_edge, compute_ev, classify_by_score
from grade import grade_pending_picks
from scorer import score_pick


def _pt_date(offset_days: int = 0) -> str:
    pt = datetime.now(timezone.utc) - timedelta(hours=7) + timedelta(days=offset_days)
    return pt.strftime("%Y-%m-%d")


def _analyze(conn, pulled_at: str, today: str,
             game_data: dict | None = None) -> tuple[int, int]:
    """
    Compute consensus + edge + signal score for all Bovada lines.
    game_data: pre-fetched from lineups.get_game_data_for_date().
    Returns (picks_evaluated, no_bets_logged).
    """
    rows = [dict(r) for r in get_snapshots(conn, pulled_at)]

    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        key = (row["event_id"], row["market_key"], row["player_name"], row["point"])
        groups[key].append(row)

    picks_evaluated = 0
    no_bets_logged  = 0

    for (event_id, market_key, player_name, point), group_rows in groups.items():
        bovada_rows = [r for r in group_rows if r["bookmaker_key"] in BOVADA_KEYS]
        if not bovada_rows:
            continue

        meta = bovada_rows[0]
        base = {
            "pick_date":     today,
            "pulled_at":     pulled_at,
            "event_id":      event_id,
            "commence_time": meta["commence_time"],
            "home_team":     meta["home_team"],
            "away_team":     meta["away_team"],
            "player_name":   player_name,
            "market_key":    market_key,
            "point":         point,
        }
        no_bet_base = {
            "logged_at":   pulled_at,
            "pick_date":   today,
            "event_id":    event_id,
            "player_name": player_name,
            "market_key":  market_key,
            "point":       point,
        }

        bov_over  = next((r for r in bovada_rows if r["selection"] == "Over"),  None)
        bov_under = next((r for r in bovada_rows if r["selection"] == "Under"), None)

        if bov_over is None or bov_under is None or bov_over["point"] != bov_under["point"]:
            for sel in ("Over", "Under"):
                log_no_bet(conn, {**no_bet_base, "selection": sel,
                                  "reason": "missing_valid_two_way_market"})
                no_bets_logged += 1
            continue

        bov_fair_over, bov_fair_under = vig_remove_pair(bov_over["price"], bov_under["price"])

        consensus = compute_consensus(
            group_rows,
            min_books=MIN_CONSENSUS_BOOKS,
            bovada_keys=BOVADA_KEYS,
        )

        for selection in ("Over", "Under"):
            bov = bov_over if selection == "Over" else bov_under
            bov_fair = bov_fair_over if selection == "Over" else bov_fair_under

            if not consensus["ok"]:
                log_no_bet(conn, {**no_bet_base, "selection": selection,
                                  "reason": consensus["reason"]})
                no_bets_logged += 1
                continue

            fair_prob = (
                consensus["fair_prob_over"] if selection == "Over"
                else consensus["fair_prob_under"]
            )
            bev  = bovada_break_even(bov["price"])
            edge = compute_edge(fair_prob, bov_fair)
            ev   = compute_ev(bov["price"], fair_prob)

            # Score pick with all signals
            score, breakdown = score_pick(
                player_name=player_name,
                market_key=market_key,
                selection=selection,
                point=point,
                home_team=meta["home_team"],
                away_team=meta["away_team"],
                edge=edge,
                game_date=today,
                game_data=game_data,
            )

            rec = classify_by_score(score, edge, market_key, selection)

            upsert_pick(conn, {
                **base,
                "selection":              selection,
                "bovada_price":           bov["price"],
                "bovada_break_even_prob": round(bev,      6),
                "bovada_fair_prob":       round(bov_fair, 6),
                "consensus_fair_prob":    round(fair_prob, 6),
                "consensus_book_count":   consensus["book_count"],
                "edge":                   round(edge, 6),
                "ev":                     round(ev,   6),
                "recommendation":         rec,
                "signal_score":           score,
                "signal_breakdown":       json.dumps(breakdown),
                # keep legacy confidence columns null (scorer replaces them)
                "confidence_score":       None,
                "confidence_factors":     None,
            })
            picks_evaluated += 1

    return picks_evaluated, no_bets_logged


def _export_csv(conn, pick_date: str) -> Path:
    PICKS_DIR.mkdir(parents=True, exist_ok=True)
    path = PICKS_DIR / f"picks_{pick_date}.csv"
    rows = conn.execute("""
        SELECT pick_date, player_name, market_key, selection, point,
               bovada_price, bovada_fair_prob, consensus_fair_prob,
               edge, ev, recommendation, consensus_book_count,
               signal_score, signal_breakdown,
               home_team, away_team, commence_time, result
        FROM daily_picks
        WHERE pick_date = ?
        ORDER BY signal_score DESC
    """, (pick_date,)).fetchall()
    if rows:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows([dict(r) for r in rows])
    return path


def _print_summary(conn, pick_date: str, pulled_at: str) -> None:
    counts = conn.execute("""
        SELECT recommendation, COUNT(*) AS cnt
        FROM daily_picks WHERE pick_date = ?
        GROUP BY recommendation ORDER BY cnt DESC
    """, (pick_date,)).fetchall()
    for row in counts:
        print(f"  {row['recommendation']}: {row['cnt']}")

    rows = conn.execute("""
        SELECT player_name, market_key, selection, point,
               bovada_price, edge, recommendation,
               consensus_book_count, signal_score, signal_breakdown
        FROM daily_picks
        WHERE pick_date = ?
        ORDER BY signal_score DESC NULLS LAST LIMIT 25
    """, (pick_date,)).fetchall()
    if rows:
        print(f"\n  {'PLAYER':<22} {'MARKET':<22} {'S':<5} {'PT':>4}  {'PRICE':>6}  {'EDGE':>6}  {'SCORE':>5}  REC")
        print("  " + "-" * 95)
        for p in rows:
            tag = "**" if p["recommendation"] == "RECOMMENDED" else (" >" if p["recommendation"] == "LEAN" else "  ")
            print(
                f"{tag} {p['player_name']:<22} {p['market_key']:<22} {p['selection']:<5} {p['point']:>4.1f}"
                f"  {p['bovada_price']:>+6d}  {p['edge']:>+6.1%}  {p['signal_score'] or 0:>5}  {p['recommendation']}"
            )


def main() -> None:
    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        print("ERROR: ODDS_API_KEY not set in .env")
        sys.exit(1)

    conn  = get_conn()
    init_db(conn)

    today     = _pt_date(0)
    yesterday = _pt_date(-1)
    print(f"\n{'='*50}")
    print(f"MLB V2 Daily Run - {today}")
    print(f"{'='*50}")

    # Pre-fetch game data (lineups, SPs, umpires) — one MLB Stats API call
    print("\n[1/4] Pre-fetching game data from MLB Stats API...")
    try:
        from signals.lineups import get_game_data_for_date
        game_data = get_game_data_for_date(today)
        print(f"  {len(game_data)} games found for today")
    except Exception as exc:
        print(f"  WARNING: game data fetch failed ({exc}) — scoring without lineup/umpire data")
        game_data = None

    print("\n[2/4] Pulling props from The Odds API...")
    pulled_at, row_count = pull_and_store(api_key, conn)
    print(f"  Stored {row_count} snapshot rows  (pulled_at={pulled_at})")

    print("\n[3/4] Computing consensus, edge, and signal scores...")
    evaluated, no_bets = _analyze(conn, pulled_at, today, game_data=game_data)
    print(f"  Evaluated: {evaluated}  |  Structural no-bets logged: {no_bets}")

    csv_path = _export_csv(conn, today)
    print(f"  CSV: {csv_path}")

    print(f"\n[4/4] Grading picks for {yesterday}...")
    graded = grade_pending_picks(conn, yesterday)
    print(f"  Graded: {graded} picks")

    print(f"\n{'-'*50}")
    print(f"  Today's picks ({today}):")
    _print_summary(conn, today, pulled_at)
    print()

    conn.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Also update `upsert_pick` in `db.py` to accept signal_score + signal_breakdown**

In `db.py`, update `upsert_pick` to include the new fields:

```python
def upsert_pick(conn: sqlite3.Connection, pick: dict) -> None:
    conn.execute("""
        INSERT INTO daily_picks
            (pick_date, pulled_at, event_id, commence_time, home_team, away_team,
             player_name, market_key, selection, point, bovada_price,
             bovada_break_even_prob, bovada_fair_prob, consensus_fair_prob,
             consensus_book_count, edge, ev, recommendation,
             signal_score, signal_breakdown)
        VALUES
            (:pick_date, :pulled_at, :event_id, :commence_time, :home_team, :away_team,
             :player_name, :market_key, :selection, :point, :bovada_price,
             :bovada_break_even_prob, :bovada_fair_prob, :consensus_fair_prob,
             :consensus_book_count, :edge, :ev, :recommendation,
             :signal_score, :signal_breakdown)
        ON CONFLICT(event_id, player_name, market_key, selection, point, pick_date)
        DO UPDATE SET
            bovada_price=excluded.bovada_price,
            bovada_break_even_prob=excluded.bovada_break_even_prob,
            bovada_fair_prob=excluded.bovada_fair_prob,
            consensus_fair_prob=excluded.consensus_fair_prob,
            consensus_book_count=excluded.consensus_book_count,
            edge=excluded.edge,
            ev=excluded.ev,
            recommendation=excluded.recommendation,
            signal_score=excluded.signal_score,
            signal_breakdown=excluded.signal_breakdown
    """, pick)
    conn.commit()
```

- [ ] **Step 3: Smoke test pipeline without API call**

```bash
cd C:\Users\jesse\MLB_V2
python -c "
from scorer import score_pick
s, bd = score_pick('Corbin Burnes', 'pitcher_strikeouts', 'Over', 6.5,
    'Arizona Diamondbacks', 'San Francisco Giants', 0.03, '2026-05-15', game_data=None)
print(f'Score: {s}/100')
for b in bd:
    print(f'  {b[\"signal\"]:<22} {b[\"pts\"]:>3}/{b[\"max\"]:<3} ({b[\"raw\"]:.2f})  {b[\"note\"]}')
"
```

Expected: prints score and breakdown without errors.

- [ ] **Step 4: Commit**

```bash
git add run_daily.py db.py
git commit -m "feat: wire scorer into run_daily pipeline — score determines recommendation tier"
```

---

## Task 10: Update `backtest.py` for scorer

**Files:**
- Modify: `backtest.py`

- [ ] **Step 1: Pass `game_data=None` to `_analyze` in backtest**

In `backtest.py`, the `_analyze_day` function calls `_analyze`. Update it so that `daily_picks` rows now include the signal columns:

```python
def _analyze_day(snapshot_rows: list, pulled_at: str, date_str: str) -> list:
    """Run edge analysis on snapshot_rows using in-memory SQLite. Returns list of pick dicts."""
    from run_daily import _analyze

    mem = sqlite3.connect(":memory:")
    mem.row_factory = sqlite3.Row
    init_db(mem)
    insert_snapshots(mem, snapshot_rows)
    # game_data=None in backtest — scorer uses stats-only signals (no live lineup/umpire)
    _analyze(mem, pulled_at, date_str, game_data=None)
    picks = [dict(r) for r in mem.execute(
        "SELECT * FROM daily_picks WHERE pick_date=?", (date_str,)
    ).fetchall()]
    mem.close()
    return picks
```

Also update `_store_picks` to pass through `signal_score` and `signal_breakdown` from the picks:

The INSERT in `_store_picks` was already updated in Task 1. Verify the picks dict keys match:

```bash
cd C:\Users\jesse\MLB_V2
python -c "
import sqlite3
from db import init_db, insert_snapshots
from run_daily import _analyze
mem = sqlite3.connect(':memory:')
mem.row_factory = sqlite3.Row
init_db(mem)
_analyze(mem, 'test', '2026-05-15', game_data=None)
rows = mem.execute('SELECT signal_score FROM daily_picks').fetchall()
print('Rows with signal_score:', len(rows))
"
```

Expected: `Rows with signal_score: 0` (no snapshot data in test) — no error.

- [ ] **Step 2: Commit**

```bash
git add backtest.py
git commit -m "feat: backtest stores signal_score + signal_breakdown via updated _analyze_day"
```

---

## Task 11: Fix `market_learn.py` breakeven bug

**Files:**
- Modify: `market_learn.py`

The current `compute_calibration` uses `avg_price` to compute a single `bev` for the whole bucket. This produces wrong results (e.g., pitcher_strikeouts Over shows BEV=28% when true BEV is 53%). Fix: compute per-pick BEV and average those.

- [ ] **Step 1: Fix breakeven in `market_learn.py`**

Replace lines 52-72 in `market_learn.py` (the `results` construction loop):

```python
    results = []
    for (mkt, sel, bucket), b in buckets.items():
        decided = b["wins"] + b["losses"]
        if decided < MIN_SAMPLE:
            continue
        win_rate = b["wins"] / decided
        # Correct: average per-pick BEV, not BEV of avg price
        avg_bev = sum(_breakeven(p) for p in b["prices"]) / len(b["prices"])
        results.append({
            "market_key":        mkt,
            "selection":         sel,
            "edge_bucket":       bucket,
            "wins":              b["wins"],
            "losses":            b["losses"],
            "pushes":            b["pushes"],
            "total":             decided,
            "win_rate":          round(win_rate, 4),
            "breakeven":         round(avg_bev, 4),
            "edge_vs_breakeven": round(win_rate - avg_bev, 4),
            "net_units":         round(b["profit"], 2),
            "profitable":        win_rate >= avg_bev,
        })
```

- [ ] **Step 2: Verify fix**

```bash
cd C:\Users\jesse\MLB_V2
python -c "
import sqlite3
conn = sqlite3.connect('data/backtest.db')
conn.row_factory = sqlite3.Row
from market_learn import compute_calibration
cal = compute_calibration(conn)
for r in cal[:5]:
    print(r['market_key'], r['selection'], f\"win={r['win_rate']:.1%} bev={r['breakeven']:.1%} net={r['net_units']:+.1f}u\")
"
```

Expected: `bev` values near 53% for pitcher markets (not 28%).

- [ ] **Step 3: Commit**

```bash
git add market_learn.py
git commit -m "fix: market_learn.py breakeven now uses per-pick BEV avg instead of avg-price BEV"
```

---

## Task 12: Dashboard — replace stars with score bar

**Files:**
- Modify: `dashboard.py`

- [ ] **Step 1: Read current dashboard pick display section**

Find the section of `dashboard.py` that renders confidence stars. Search for `confidence_score` to locate it.

```bash
cd C:\Users\jesse\MLB_V2
grep -n "confidence_score\|confidence_factors\|star" dashboard.py | head -30
```

- [ ] **Step 2: Replace star rendering with score bar**

For each pick row display, replace the star block with a score bar. Find the block that renders stars (typically looks like `"★" * score + "☆" * (4 - score)`) and replace with:

```python
# Score bar display
score = pick.get("signal_score") or 0
breakdown_raw = pick.get("signal_breakdown") or "[]"
try:
    import json as _json
    breakdown = _json.loads(breakdown_raw)
except Exception:
    breakdown = []

bar_filled = int(score / 10)
bar = "█" * bar_filled + "░" * (10 - bar_filled)
score_display = f"{score:>3}/100 [{bar}]"
breakdown_text = "\n".join(
    f"  {b['signal']:<22} {b['pts']:>3}/{b['max']:<3} — {b['note']}"
    for b in breakdown
)
```

Then use `st.metric` or `st.text` to show `score_display`, and `st.expander` for the breakdown:

```python
col_score, col_breakdown = st.columns([2, 3])
with col_score:
    color = "green" if score >= 65 else ("orange" if score >= 45 else "red")
    st.markdown(f"<span style='color:{color}; font-family:monospace'>{score_display}</span>",
                unsafe_allow_html=True)
with col_breakdown:
    if breakdown:
        with st.expander("Signal breakdown"):
            st.code(breakdown_text)
```

Also update the sidebar filter: replace "Min confidence (stars)" with a score slider:

```python
min_score = st.sidebar.slider("Min signal score", 0, 90, 0, step=5)
```

And filter picks:

```python
picks = [p for p in picks if (p.get("signal_score") or 0) >= min_score]
```

- [ ] **Step 3: Remove old confidence imports/calls from `dashboard.py`**

Search for any `update_pick_confidence` calls or `confidence_score`/`confidence_factors` column references in the dashboard SQL queries and replace with `signal_score`/`signal_breakdown`.

- [ ] **Step 4: Smoke test dashboard**

```bash
cd C:\Users\jesse\MLB_V2
streamlit run dashboard.py
```

Open browser, verify picks show score bar instead of stars. No console errors.

- [ ] **Step 5: Commit**

```bash
git add dashboard.py
git commit -m "feat: dashboard replaces star rating with signal score bar + breakdown expander"
```

---

## Task 13: Delete `confidence.py`

- [ ] **Step 1: Verify nothing imports confidence.py**

```bash
cd C:\Users\jesse\MLB_V2
grep -rn "from confidence\|import confidence" *.py
```

Expected: no results (run_daily.py no longer imports it after Task 9).

- [ ] **Step 2: Delete**

```bash
del "C:\Users\jesse\MLB_V2\confidence.py"
```

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "chore: remove confidence.py — replaced by scorer.py"
```

---

## Verification

After all tasks complete:

```bash
cd C:\Users\jesse\MLB_V2

# 1. All tests pass
python -m pytest tests/ -v

# 2. Scorer works standalone
python -c "
from scorer import score_pick, tier_from_score
s, bd = score_pick('Zack Wheeler', 'pitcher_strikeouts', 'Over', 7.5,
    'Philadelphia Phillies', 'New York Mets', 0.035, '2026-05-15', game_data=None)
print(f'Score: {s}/100  Tier: {tier_from_score(s)}')
"

# 3. Backtest report still works
python backtest.py --report-only

# 4. Market calibration BEV is fixed
python -c "
import sqlite3, json
conn = sqlite3.connect('data/backtest.db')
conn.row_factory = sqlite3.Row
from market_learn import compute_calibration
for r in compute_calibration(conn):
    print(r['market_key'], r['selection'], f\"{r['breakeven']:.1%}\")
"
```

Expected: all pitcher markets show BEV ~53%, not ~29%.

**Do NOT run `python backtest.py` (with --reset or date range) without user approval** — it consumes Odds API tokens.
