# Confidence Scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 0–4 star confidence score to every pick by cross-referencing MLB Stats API data against the edge direction, so users can see whether underlying stats back up what the market is saying.

**Architecture:** Four independent layers. (1) `stats.py` — pure HTTP client for the free MLB Stats API (no key needed); caches all-players and team-stats in module-level dicts per process run. (2) `confidence.py` — scoring engine; calls `stats.py` and maps each signal to a factor string; never raises. (3) `db.py` + `run_daily.py` — add two nullable columns and call the scorer after `_analyze()`. (4) `dashboard.py` — read stars + factors from DB and render in pick cards with a confidence filter.

**Tech Stack:** Python 3.11+, `requests` (already in requirements), SQLite3 (existing), MLB Stats API (free, no key), Streamlit (existing), `unittest.mock` for tests.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `stats.py` | Create | MLB Stats API HTTP client, module-level caching, fuzzy name matching |
| `confidence.py` | Create | Per-market scoring logic, returns (score, factors) |
| `tests/test_stats.py` | Create | Unit tests for stats parsing (requests mocked) |
| `tests/test_confidence.py` | Create | Unit tests for scoring logic (stats functions mocked) |
| `db.py` | Modify | Add `confidence_score`, `confidence_factors` columns + `update_pick_confidence()` |
| `run_daily.py` | Modify | Add `_score_picks()`, call after `_analyze()` |
| `dashboard.py` | Modify | Stars display, confidence filter, sort by confidence within tier |

---

### Task 1: `stats.py` — MLB Stats API client

**Files:**
- Create: `stats.py`
- Create: `tests/test_stats.py`

All HTTP calls use the free MLB Stats API at `https://statsapi.mlb.com/api/v1`. No API key. Timeout 10 s on every call.

Three module-level caches prevent re-fetching within a single pipeline run:
- `_all_players` — list of all active MLB players loaded from `/sports/1/players`
- `_player_cache` — name → `{id, team_name}` already looked up
- `_team_stats_cache` — team name → `{k_pct, avg, ops}` from team batting stats

- [ ] **Step 1: Write failing tests**

Create `tests/test_stats.py`:

```python
import pytest
from unittest.mock import MagicMock, patch
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import stats as stats_module
from stats import (
    find_player_info, fetch_pitcher_stats,
    fetch_batter_stats, fetch_team_hitting,
)

# --- fixture data ---

ALL_PLAYERS = {"people": [
    {"id": 669302, "fullName": "Jesus Luzardo",
     "currentTeam": {"name": "Miami Marlins"}},
    {"id": 99999,  "fullName": "Freddie Freeman",
     "currentTeam": {"name": "Los Angeles Dodgers"}},
]}

PITCHER_GAMELOG = {"stats": [{"splits": [
    {"stat": {"strikeOuts": 8, "hits": 3, "earnedRuns": 1, "inningsPitched": "6.0"}},
    {"stat": {"strikeOuts": 6, "hits": 5, "earnedRuns": 2, "inningsPitched": "5.2"}},
    {"stat": {"strikeOuts": 9, "hits": 4, "earnedRuns": 0, "inningsPitched": "7.0"}},
    {"stat": {"strikeOuts": 7, "hits": 6, "earnedRuns": 3, "inningsPitched": "5.0"}},
    {"stat": {"strikeOuts": 5, "hits": 4, "earnedRuns": 2, "inningsPitched": "6.1"}},
]}]}

PITCHER_SEASON = {"stats": [{"splits": [{"stat": {
    "strikeoutsPer9Inn": "10.2", "era": "3.25", "whip": "1.10",
}}]}]}

BATTER_GAMELOG = {"stats": [{"splits": [
    {"stat": {"hits": 2, "totalBases": 4}},
    {"stat": {"hits": 1, "totalBases": 1}},
    {"stat": {"hits": 0, "totalBases": 0}},
    {"stat": {"hits": 2, "totalBases": 3}},
    {"stat": {"hits": 1, "totalBases": 2}},
]}]}

BATTER_SEASON = {"stats": [{"splits": [{"stat": {"avg": ".285", "slg": ".450"}}]}]}

TEAM_STATS = {"stats": [{"splits": [
    {"team": {"name": "Miami Marlins"},
     "stat": {"strikeOuts": 310, "plateAppearances": 1350, "avg": ".228", "ops": ".690"}},
    {"team": {"name": "Philadelphia Phillies"},
     "stat": {"strikeOuts": 350, "plateAppearances": 1350, "avg": ".257", "ops": ".756"}},
]}]}


def _multi_get(*payloads):
    """Mock requests.get — each successive call returns the next payload."""
    it = iter(payloads)
    def _side(*a, **kw):
        m = MagicMock()
        m.raise_for_status = MagicMock()
        m.json.return_value = next(it)
        return m
    return MagicMock(side_effect=_side)


@pytest.fixture(autouse=True)
def reset():
    stats_module._reset_caches()
    yield
    stats_module._reset_caches()


def test_find_player_exact_match():
    with patch("stats.requests.get", _multi_get(ALL_PLAYERS)):
        r = find_player_info("Jesus Luzardo", season=2026)
    assert r["id"] == 669302
    assert r["team_name"] == "Miami Marlins"


def test_find_player_not_found():
    with patch("stats.requests.get", _multi_get(ALL_PLAYERS)):
        r = find_player_info("Nobody Fake", season=2026)
    assert r is None


def test_find_player_cached_no_extra_calls():
    mock = _multi_get(ALL_PLAYERS)
    with patch("stats.requests.get", mock):
        find_player_info("Jesus Luzardo", season=2026)
        find_player_info("Jesus Luzardo", season=2026)
    assert mock.call_count == 1   # all-players list fetched once


def test_fetch_pitcher_stats_averages():
    with patch("stats.requests.get", _multi_get(PITCHER_GAMELOG, PITCHER_SEASON)):
        r = fetch_pitcher_stats(669302, season=2026)
    # avg of [8,6,9,7,5] = 7.0
    assert r["recent_k"]    == pytest.approx(7.0,  abs=0.05)
    # avg of [3,5,4,6,4] = 4.4
    assert r["recent_h"]    == pytest.approx(4.4,  abs=0.05)
    # avg of [1,2,0,3,2] = 1.6
    assert r["recent_er"]   == pytest.approx(1.6,  abs=0.05)
    assert r["season_k9"]   == pytest.approx(10.2, abs=0.05)
    assert r["season_era"]  == pytest.approx(3.25, abs=0.01)
    assert r["season_whip"] == pytest.approx(1.10, abs=0.01)


def test_fetch_pitcher_stats_http_error_returns_none():
    m = MagicMock()
    m.return_value.raise_for_status.side_effect = Exception("500")
    with patch("stats.requests.get", m):
        assert fetch_pitcher_stats(1, season=2026) is None


def test_fetch_batter_stats():
    with patch("stats.requests.get", _multi_get(BATTER_GAMELOG, BATTER_SEASON)):
        r = fetch_batter_stats(99999, season=2026)
    # avg H of [2,1,0,2,1] = 1.2
    assert r["recent_h_per_game"]  == pytest.approx(1.2,  abs=0.05)
    # avg TB of [4,1,0,3,2] = 2.0
    assert r["recent_tb_per_game"] == pytest.approx(2.0,  abs=0.05)
    assert r["season_avg"] == pytest.approx(0.285, abs=0.001)
    assert r["season_slg"] == pytest.approx(0.450, abs=0.001)


def test_fetch_team_hitting():
    with patch("stats.requests.get", _multi_get(TEAM_STATS)):
        r = fetch_team_hitting("Philadelphia Phillies", season=2026)
    assert r["k_pct"] == pytest.approx(350/1350, abs=0.001)
    assert r["avg"]   == pytest.approx(0.257, abs=0.001)
    assert r["ops"]   == pytest.approx(0.756, abs=0.001)


def test_fetch_team_hitting_http_error_returns_none():
    m = MagicMock()
    m.return_value.raise_for_status.side_effect = Exception("500")
    with patch("stats.requests.get", m):
        assert fetch_team_hitting("Miami Marlins", season=2026) is None
```

- [ ] **Step 2: Run tests — confirm all fail**

```
cd C:\Users\jesse\MLB_V2
pytest tests/test_stats.py -v
```

Expected: ImportError (`No module named 'stats'`).

- [ ] **Step 3: Create `stats.py`**

```python
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


def _load_all_players(season: int) -> list[dict]:
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


def find_player_info(player_name: str, season: int = datetime.now().year) -> dict | None:
    """
    Return {id, team_name} for player_name, or None if not found.
    Tries exact name first, then last-name + first-initial fuzzy match.
    """
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


def fetch_pitcher_stats(player_id: int, season: int = datetime.now().year) -> dict | None:
    """
    Returns:
      recent_k, recent_h, recent_er  — avg over last 5 starts (None if < 2 starts)
      season_k9, season_era, season_whip  — season totals (None if missing)
    Returns None on any HTTP/parse error.
    """
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

        recent_k  = _avg("strikeOuts")
        recent_h  = _avg("hits")
        recent_er = _avg("earnedRuns")

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
            "recent_k":    recent_k,
            "recent_h":    recent_h,
            "recent_er":   recent_er,
            "season_k9":   _f(sea.get("strikeoutsPer9Inn")),
            "season_era":  _f(sea.get("era")),
            "season_whip": _f(sea.get("whip")),
        }
    except Exception:
        return None


def fetch_batter_stats(player_id: int, season: int = datetime.now().year) -> dict | None:
    """
    Returns:
      recent_h_per_game, recent_tb_per_game  — avg over last 10 games (None if < 3 games)
      season_avg, season_slg  — season totals (None if missing)
    Returns None on any HTTP/parse error.
    """
    try:
        r_log = requests.get(
            f"{_BASE}/people/{player_id}/stats",
            params={"stats": "gameLog", "season": season, "group": "hitting", "gameType": "R"},
            timeout=_TIMEOUT,
        )
        r_log.raise_for_status()
        splits = r_log.json().get("stats", [{}])[0].get("splits", [])
        last10 = [s["stat"] for s in splits[-10:]] if len(splits) >= 3 else []

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


def fetch_team_hitting(team_name: str, season: int = datetime.now().year) -> dict | None:
    """
    Return {k_pct, avg, ops} for the named team, or None on failure.
    Fetches all 30 teams in one call and caches the result.
    """
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
```

- [ ] **Step 4: Run tests — all should pass**

```
pytest tests/test_stats.py -v
```

Expected: 9/9 PASSED.

- [ ] **Step 5: Commit**

```
git add stats.py tests/test_stats.py
git commit -m "feat: add MLB Stats API client (stats.py)"
```

---

### Task 2: `confidence.py` — scoring engine

**Files:**
- Create: `confidence.py`
- Create: `tests/test_confidence.py`

Four signals per pitcher market, three per batter market (batters have less available data). Signal 4 for all markets is edge strength (>= 4% counts as a market-alignment signal). Score is `min(len(factors), 4)`.

**Scoring thresholds:**

| Signal | Over trigger | Under trigger |
|--------|-------------|---------------|
| pitcher K recent avg | recent_k >= line + 0.5 | recent_k <= line − 0.5 |
| pitcher K/9 season | k9 >= 9.0 | k9 <= 7.0 |
| opp team K% | k_pct >= 25.0% | k_pct <= 20.5% |
| pitcher hits recent | recent_h >= line + 0.5 | recent_h <= line − 0.5 |
| pitcher WHIP season | whip >= 1.40 | whip <= 1.15 |
| opp team BA | avg >= .255 | avg <= .234 |
| pitcher ER recent | recent_er >= line + 0.5 | recent_er <= line − 0.5 |
| pitcher ERA season | era >= line + 0.5 | era <= line − 0.5 |
| opp team OPS | ops >= .740 | ops <= .685 |
| batter recent H/game | recent_h_per_game >= line + 0.2 | recent_h_per_game <= line − 0.2 |
| batter season BA*4 proj | avg*4 >= line + 0.2 | avg*4 <= line − 0.2 |
| batter recent TB/game | recent_tb_per_game >= line + 0.2 | recent_tb_per_game <= line − 0.2 |
| batter season SLG*4 proj | slg*4 >= line + 0.2 | slg*4 <= line − 0.2 |
| edge strength (all markets) | edge >= 0.04 | edge >= 0.04 |

- [ ] **Step 1: Write failing tests**

Create `tests/test_confidence.py`:

```python
import pytest
from unittest.mock import patch
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from confidence import score_pick

_BASE_PICK = dict(
    player_name="Jesus Luzardo",
    home_team="Miami Marlins",
    away_team="Philadelphia Phillies",
    season=2026,
)

_PITCHER_STATS = {
    "recent_k": 7.0, "recent_h": 4.0, "recent_er": 1.5,
    "season_k9": 10.2, "season_era": 3.10, "season_whip": 1.08,
}

_BATTER_STATS = {
    "recent_h_per_game": 1.4, "recent_tb_per_game": 2.2,
    "season_avg": 0.290, "season_slg": 0.490,
}

_TEAM_HIGH_K = {"k_pct": 0.260, "avg": 0.230, "ops": 0.690}
_TEAM_LOW_K  = {"k_pct": 0.195, "avg": 0.257, "ops": 0.756}


def _p(player_info=None, pitcher=None, batter=None, team=None):
    """Return tuple of patch objects."""
    return (
        patch("confidence.find_player_info",
              return_value=player_info or {"id": 1, "team_name": "Miami Marlins"}),
        patch("confidence.fetch_pitcher_stats",
              return_value=pitcher or _PITCHER_STATS),
        patch("confidence.fetch_batter_stats",
              return_value=batter or _BATTER_STATS),
        patch("confidence.fetch_team_hitting",
              return_value=team or _TEAM_HIGH_K),
    )


def test_pitcher_strikeouts_all_4_signals():
    # recent_k 7.0 > 5.5+0.5, k9 10.2>9.0, opp k% 26%>25%, edge 5%>=4%
    p = _p()
    with p[0], p[1], p[2], p[3]:
        score, factors = score_pick(
            **_BASE_PICK, market_key="pitcher_strikeouts",
            selection="Over", point=5.5, edge=0.05,
        )
    assert score == 4
    assert len(factors) == 4


def test_pitcher_strikeouts_only_edge_signal():
    # recent K 5.5 = line, k9 8.0, opp k% 22.0% — none fire except edge
    p = _p(pitcher={**_PITCHER_STATS, "recent_k": 5.5, "season_k9": 8.0},
           team={**_TEAM_HIGH_K, "k_pct": 0.220})
    with p[0], p[1], p[2], p[3]:
        score, factors = score_pick(
            **_BASE_PICK, market_key="pitcher_strikeouts",
            selection="Over", point=5.5, edge=0.05,
        )
    assert score == 1
    assert len(factors) == 1
    assert "edge" in factors[0].lower()


def test_pitcher_strikeouts_no_signals_below_edge_threshold():
    p = _p(pitcher={**_PITCHER_STATS, "recent_k": 5.5, "season_k9": 8.0},
           team={**_TEAM_HIGH_K, "k_pct": 0.220})
    with p[0], p[1], p[2], p[3]:
        score, factors = score_pick(
            **_BASE_PICK, market_key="pitcher_strikeouts",
            selection="Over", point=5.5, edge=0.02,
        )
    assert score == 0
    assert factors == []


def test_player_not_found_returns_zero():
    with patch("confidence.find_player_info", return_value=None):
        score, factors = score_pick(
            **_BASE_PICK, market_key="pitcher_strikeouts",
            selection="Over", point=5.5, edge=0.05,
        )
    assert score == 0
    assert factors == []


def test_exception_returns_zero_never_raises():
    with patch("confidence.find_player_info", side_effect=RuntimeError("API down")):
        score, factors = score_pick(
            **_BASE_PICK, market_key="pitcher_strikeouts",
            selection="Over", point=5.5, edge=0.05,
        )
    assert score == 0


def test_pitcher_hits_under_all_signals():
    # recent_h 4.0 < 5.5-0.5, whip 1.08 <= 1.15, opp avg 0.230 <= 0.234, edge 4%
    p = _p()
    with p[0], p[1], p[2], p[3]:
        score, factors = score_pick(
            **_BASE_PICK, market_key="pitcher_hits_allowed",
            selection="Under", point=5.5, edge=0.04,
        )
    assert score == 4


def test_pitcher_earned_runs_under():
    # recent_er 1.5 < 3.5-0.5, ERA 3.10 < 3.5-0.5, opp ops 0.690 <= 0.685? no
    # only 2 signals fire + edge
    p = _p()
    with p[0], p[1], p[2], p[3]:
        score, factors = score_pick(
            **_BASE_PICK, market_key="pitcher_earned_runs",
            selection="Under", point=3.5, edge=0.04,
        )
    assert score >= 2


def test_batter_hits_over():
    # recent_h_per_game 1.4 > 0.5+0.2, BA*4 = 1.16 > 0.5+0.2, edge 4%
    p = _p()
    with p[0], p[1], p[2], p[3]:
        score, factors = score_pick(
            player_name="Freddie Freeman",
            market_key="batter_hits",
            selection="Over", point=0.5,
            home_team="Los Angeles Dodgers",
            away_team="Miami Marlins",
            edge=0.04, season=2026,
        )
    assert score >= 2


def test_batter_total_bases_over():
    # recent_tb 2.2 > 1.5+0.2, SLG*4 = 1.96 > 1.5+0.2, edge 4%
    p = _p()
    with p[0], p[1], p[2], p[3]:
        score, factors = score_pick(
            player_name="Freddie Freeman",
            market_key="batter_total_bases",
            selection="Over", point=1.5,
            home_team="Los Angeles Dodgers",
            away_team="Miami Marlins",
            edge=0.04, season=2026,
        )
    assert score >= 2


def test_unknown_market_returns_zero():
    p = _p()
    with p[0], p[1], p[2], p[3]:
        score, factors = score_pick(
            **_BASE_PICK, market_key="unknown_market",
            selection="Over", point=1.5, edge=0.05,
        )
    assert score == 0
    assert factors == []


def test_score_capped_at_4():
    # Verify score never exceeds 4 even for 5-signal markets (shouldn't exist but defensive)
    p = _p()
    with p[0], p[1], p[2], p[3]:
        score, _ = score_pick(
            **_BASE_PICK, market_key="pitcher_strikeouts",
            selection="Over", point=5.5, edge=0.05,
        )
    assert score <= 4
```

- [ ] **Step 2: Run tests — confirm all fail**

```
pytest tests/test_confidence.py -v
```

Expected: ImportError (`No module named 'confidence'`).

- [ ] **Step 3: Create `confidence.py`**

```python
"""
Confidence scorer.
Returns (score 0-4, list of human-readable factor strings).
Score = number of signals that align with the pick direction, capped at 4.
Never raises — returns (0, []) on any data failure.
"""
from stats import find_player_info, fetch_pitcher_stats, fetch_batter_stats, fetch_team_hitting
from config import EDGE_RECOMMENDED

_LEAGUE_K_PCT = 0.228
_LEAGUE_AVG   = 0.244
_HIGH_K9      = 9.0
_LOW_K9       = 7.0
_LOW_WHIP     = 1.15
_HIGH_WHIP    = 1.40
_ERA_DELTA    = 0.5


def score_pick(
    player_name: str,
    market_key: str,
    selection: str,
    point: float,
    home_team: str,
    away_team: str,
    edge: float,
    season: int = 2026,
) -> tuple[int, list[str]]:
    """Return (confidence_score 0-4, factor descriptions). Never raises."""
    try:
        info = find_player_info(player_name, season)
        if info is None:
            return 0, []

        player_team = info["team_name"].lower()
        opp_team = away_team if player_team in home_team.lower() else home_team

        if market_key == "pitcher_strikeouts":
            factors = _pitcher_k(info["id"], selection, point, opp_team, edge, season)
        elif market_key == "pitcher_hits_allowed":
            factors = _pitcher_hits(info["id"], selection, point, opp_team, edge, season)
        elif market_key == "pitcher_earned_runs":
            factors = _pitcher_er(info["id"], selection, point, opp_team, edge, season)
        elif market_key in ("batter_hits", "batter_total_bases"):
            factors = _batter(info["id"], market_key, selection, point, edge, season)
        else:
            return 0, []

        return min(len(factors), 4), factors
    except Exception:
        return 0, []


def _edge_signal(edge: float) -> str | None:
    if edge >= EDGE_RECOMMENDED:
        return f"Market edge {edge:.1%} — consensus strongly disagrees with Bovada"
    return None


def _pitcher_k(player_id, selection, point, opp_team, edge, season) -> list[str]:
    factors = []
    stats = fetch_pitcher_stats(player_id, season)

    if stats:
        if stats.get("recent_k") is not None:
            avg = stats["recent_k"]
            if selection == "Over"  and avg >= point + 0.5:
                factors.append(f"Recent avg K {avg:.1f} exceeds line {point}")
            elif selection == "Under" and avg <= point - 0.5:
                factors.append(f"Recent avg K {avg:.1f} below line {point}")

        if stats.get("season_k9") is not None:
            k9 = stats["season_k9"]
            if selection == "Over"  and k9 >= _HIGH_K9:
                factors.append(f"High strikeout rate this season (K/9 {k9:.1f})")
            elif selection == "Under" and k9 <= _LOW_K9:
                factors.append(f"Low strikeout rate this season (K/9 {k9:.1f})")

    team = fetch_team_hitting(opp_team, season)
    if team and team.get("k_pct") is not None:
        kpct = team["k_pct"]
        if selection == "Over"  and kpct >= _LEAGUE_K_PCT + 0.022:
            factors.append(f"Opposing team K% {kpct:.1%} (above league avg)")
        elif selection == "Under" and kpct <= _LEAGUE_K_PCT - 0.023:
            factors.append(f"Opposing team K% {kpct:.1%} (below league avg)")

    sig = _edge_signal(edge)
    if sig:
        factors.append(sig)
    return factors


def _pitcher_hits(player_id, selection, point, opp_team, edge, season) -> list[str]:
    factors = []
    stats = fetch_pitcher_stats(player_id, season)

    if stats:
        if stats.get("recent_h") is not None:
            avg = stats["recent_h"]
            if selection == "Over"  and avg >= point + 0.5:
                factors.append(f"Recent avg H allowed {avg:.1f} exceeds line {point}")
            elif selection == "Under" and avg <= point - 0.5:
                factors.append(f"Recent avg H allowed {avg:.1f} below line {point}")

        if stats.get("season_whip") is not None:
            whip = stats["season_whip"]
            if selection == "Under" and whip <= _LOW_WHIP:
                factors.append(f"Low season WHIP {whip:.2f} — dominant pitcher")
            elif selection == "Over"  and whip >= _HIGH_WHIP:
                factors.append(f"High season WHIP {whip:.2f} — hittable pitcher")

    team = fetch_team_hitting(opp_team, season)
    if team and team.get("avg") is not None:
        avg_opp = team["avg"]
        if selection == "Over"  and avg_opp >= _LEAGUE_AVG + 0.011:
            factors.append(f"Opposing team BA {avg_opp:.3f} (above league avg)")
        elif selection == "Under" and avg_opp <= _LEAGUE_AVG - 0.010:
            factors.append(f"Opposing team BA {avg_opp:.3f} (below league avg)")

    sig = _edge_signal(edge)
    if sig:
        factors.append(sig)
    return factors


def _pitcher_er(player_id, selection, point, opp_team, edge, season) -> list[str]:
    factors = []
    stats = fetch_pitcher_stats(player_id, season)

    if stats:
        if stats.get("recent_er") is not None:
            avg = stats["recent_er"]
            if selection == "Over"  and avg >= point + 0.5:
                factors.append(f"Recent avg ER {avg:.1f} exceeds line {point}")
            elif selection == "Under" and avg <= point - 0.5:
                factors.append(f"Recent avg ER {avg:.1f} below line {point}")

        if stats.get("season_era") is not None:
            era = stats["season_era"]
            if selection == "Under" and era <= point - _ERA_DELTA:
                factors.append(f"Season ERA {era:.2f} well below line {point}")
            elif selection == "Over"  and era >= point + _ERA_DELTA:
                factors.append(f"Season ERA {era:.2f} well above line {point}")

    team = fetch_team_hitting(opp_team, season)
    if team and team.get("ops") is not None:
        ops = team["ops"]
        if selection == "Over"  and ops >= 0.740:
            factors.append(f"Opposing team OPS {ops:.3f} (potent offense)")
        elif selection == "Under" and ops <= 0.685:
            factors.append(f"Opposing team OPS {ops:.3f} (weak offense)")

    sig = _edge_signal(edge)
    if sig:
        factors.append(sig)
    return factors


def _batter(player_id, market_key, selection, point, edge, season) -> list[str]:
    factors = []
    stats = fetch_batter_stats(player_id, season)
    is_hits = market_key == "batter_hits"

    recent_key  = "recent_h_per_game"  if is_hits else "recent_tb_per_game"
    season_key  = "season_avg"         if is_hits else "season_slg"
    label_r     = "H/game"             if is_hits else "TB/game"
    label_s     = "BA"                 if is_hits else "SLG"

    if stats:
        if stats.get(recent_key) is not None:
            avg = stats[recent_key]
            if selection == "Over"  and avg >= point + 0.2:
                factors.append(f"Recent avg {label_r} {avg:.2f} exceeds line {point}")
            elif selection == "Under" and avg <= point - 0.2:
                factors.append(f"Recent avg {label_r} {avg:.2f} below line {point}")

        if stats.get(season_key) is not None:
            rate = stats[season_key]
            proj = rate * 4
            if selection == "Over"  and proj >= point + 0.2:
                factors.append(f"Season {label_s} projects {proj:.2f} per game vs line {point}")
            elif selection == "Under" and proj <= point - 0.2:
                factors.append(f"Season {label_s} projects {proj:.2f} per game vs line {point}")

    sig = _edge_signal(edge)
    if sig:
        factors.append(sig)
    return factors
```

- [ ] **Step 4: Run tests — all should pass**

```
pytest tests/test_confidence.py -v
```

Expected: 11/11 PASSED.

- [ ] **Step 5: Run all tests to confirm no regressions**

```
pytest -v
```

Expected: all existing tests still pass plus the new ones.

- [ ] **Step 6: Commit**

```
git add confidence.py tests/test_confidence.py
git commit -m "feat: add confidence scoring engine (confidence.py)"
```

---

### Task 3: DB + pipeline integration

**Files:**
- Modify: `db.py` (lines 36–92: CREATE TABLE block + migration block)
- Modify: `run_daily.py` (lines 210–249: main() + new _score_picks function)

Add two nullable columns to `daily_picks`, a new `update_pick_confidence()` function, and wire the scorer into the daily pipeline.

- [ ] **Step 1: Write failing tests for new DB function**

Add to `tests/test_db_bets.py` (append after the existing last test):

```python
import json

def test_update_pick_confidence(conn):
    upsert_pick(conn, SAMPLE_PICK)
    pick_id = conn.execute("SELECT id FROM daily_picks").fetchone()[0]
    from db import update_pick_confidence
    update_pick_confidence(conn, pick_id, 3, ["Signal A", "Signal B", "Signal C"])
    row = conn.execute(
        "SELECT confidence_score, confidence_factors FROM daily_picks WHERE id=?", (pick_id,)
    ).fetchone()
    assert row[0] == 3
    assert json.loads(row[1]) == ["Signal A", "Signal B", "Signal C"]


def test_schema_has_confidence_columns(conn):
    cols = {row[1] for row in conn.execute("PRAGMA table_info(daily_picks)")}
    assert "confidence_score"   in cols
    assert "confidence_factors" in cols
```

- [ ] **Step 2: Run new tests — confirm they fail**

```
pytest tests/test_db_bets.py::test_update_pick_confidence tests/test_db_bets.py::test_schema_has_confidence_columns -v
```

Expected: FAIL (columns don't exist yet).

- [ ] **Step 3: Add columns to `db.py` CREATE TABLE**

In `db.py`, inside the `CREATE TABLE IF NOT EXISTS daily_picks` block, add two columns after `notes TEXT`:

```sql
            notes                 TEXT,
            confidence_score      INTEGER,
            confidence_factors    TEXT,
```

The full end of the table block should look like:

```sql
            bet_placed            INTEGER NOT NULL DEFAULT 0,
            units_wagered         REAL,
            notes                 TEXT,
            confidence_score      INTEGER,
            confidence_factors    TEXT,
            UNIQUE(event_id, player_name, market_key, selection, point, pick_date)
```

- [ ] **Step 4: Add migrations to `init_db` in `db.py`**

After the existing bet-tracking migration loop, add:

```python
    for col_sql in [
        "ALTER TABLE daily_picks ADD COLUMN confidence_score INTEGER",
        "ALTER TABLE daily_picks ADD COLUMN confidence_factors TEXT",
    ]:
        try:
            conn.execute(col_sql)
            conn.commit()
        except sqlite3.OperationalError:
            pass
```

- [ ] **Step 5: Add `update_pick_confidence` to `db.py`**

Append after `log_no_bet`:

```python
def update_pick_confidence(
    conn: sqlite3.Connection,
    pick_id: int,
    score: int,
    factors: list[str],
) -> None:
    import json
    conn.execute(
        "UPDATE daily_picks SET confidence_score=?, confidence_factors=? WHERE id=?",
        (score, json.dumps(factors), pick_id),
    )
    conn.commit()
```

- [ ] **Step 6: Run tests — should pass**

```
pytest tests/test_db_bets.py -v
```

Expected: all 13 PASSED.

- [ ] **Step 7: Add `_score_picks` to `run_daily.py`**

Add this function to `run_daily.py` after `_print_one_sided`:

```python
def _score_picks(conn, today: str) -> int:
    """
    Score confidence for all picks for today. Returns count scored.
    Import is local to avoid circular dependency at module load time.
    """
    from confidence import score_pick
    from db import update_pick_confidence

    picks = conn.execute(
        "SELECT id, player_name, market_key, selection, point, "
        "home_team, away_team, edge FROM daily_picks WHERE pick_date=?",
        (today,),
    ).fetchall()

    scored = 0
    for p in picks:
        try:
            s, factors = score_pick(
                player_name=p["player_name"],
                market_key=p["market_key"],
                selection=p["selection"],
                point=p["point"],
                home_team=p["home_team"],
                away_team=p["away_team"],
                edge=p["edge"],
            )
            update_pick_confidence(conn, p["id"], s, factors)
            scored += 1
        except Exception:
            pass
    return scored
```

- [ ] **Step 8: Call `_score_picks` in `main()` of `run_daily.py`**

In `run_daily.py`, after the `_analyze` block (around line 232), add:

```python
    print("\n[2b] Scoring confidence from MLB Stats API...")
    scored = _score_picks(conn, today)
    print(f"  Confidence scored: {scored} picks  (0 = player not found or API unavailable)")
```

The full section in `main()` should look like:

```python
    print("\n[2/3] Computing consensus and edge...")
    evaluated, no_bets = _analyze(conn, pulled_at, today)
    print(f"  Evaluated: {evaluated}  |  Structural no-bets logged: {no_bets}")

    print("\n[2b] Scoring confidence from MLB Stats API...")
    scored = _score_picks(conn, today)
    print(f"  Confidence scored: {scored} picks  (0 = player not found or API unavailable)")

    csv_path = _export_csv(conn, today)
    print(f"  CSV: {csv_path}")
```

- [ ] **Step 9: Add `confidence_score` to `_export_csv` SELECT in `run_daily.py`**

In `_export_csv`, update the SELECT to include the new columns:

```python
    rows = conn.execute("""
        SELECT pick_date, player_name, market_key, selection, point,
               bovada_price, bovada_fair_prob, consensus_fair_prob,
               edge, ev, recommendation, consensus_book_count,
               confidence_score, confidence_factors,
               home_team, away_team, commence_time, result
        FROM daily_picks
        WHERE pick_date = ?
        ORDER BY edge DESC
    """, (pick_date,)).fetchall()
```

- [ ] **Step 10: Run all tests**

```
pytest -v
```

Expected: all tests pass.

- [ ] **Step 11: Commit**

```
git add db.py run_daily.py
git commit -m "feat: wire confidence scoring into daily pipeline"
```

---

### Task 4: Dashboard stars display

**Files:**
- Modify: `dashboard.py`

Read `confidence_score` and `confidence_factors` from the DB rows already returned by `get_today_picks`. Add a stars helper, render stars in pick cards, add a confidence filter, and sort picks by (tier, confidence DESC, edge DESC).

- [ ] **Step 1: Add `_stars` helper and update imports in `dashboard.py`**

After the existing `_card_class` function, add:

```python
def _stars(score) -> str:
    """Return filled/empty star string for score 0-4. Empty string if None."""
    if score is None:
        return ""
    return "★" * int(score) + "☆" * (4 - int(score))


def _star_color(score) -> str:
    if score is None or score == 0:
        return "#3a5068"
    if score >= 3:
        return "#f1c40f"
    if score >= 2:
        return "#f39c12"
    return "#8fa8c8"
```

Also add at the top of `dashboard.py` after the existing imports:

```python
import json
```

- [ ] **Step 2: Add confidence sort + filter to `_render_today`**

In `_render_today`, after the `picks = get_today_picks(conn, today)` line and before the stat boxes, add a sort:

```python
    _REC_ORDER = {"RECOMMENDED": 0, "LEAN": 1, "NO_BET": 2}
    picks = sorted(picks, key=lambda p: (
        _REC_ORDER.get(p["recommendation"], 2),
        -(p["confidence_score"] or 0),
        -p["edge"],
    ))
```

Then, after the `show_all` checkbox, add a confidence filter selectbox. Replace:

```python
    show_all = st.checkbox("Show all evaluated lines (not just LEAN+)", value=False)
    visible = picks if show_all else [p for p in picks if p["recommendation"] in ("LEAN", "RECOMMENDED")]
```

With:

```python
    col_a, col_b = st.columns([2, 1])
    show_all = col_a.checkbox("Show all evaluated lines (not just LEAN+)", value=False)
    min_conf = col_b.selectbox(
        "Min confidence",
        options=[0, 1, 2, 3, 4],
        format_func=lambda x: "All stars" if x == 0 else f"{x}+ stars",
        index=0,
        key="min_conf",
        label_visibility="collapsed",
    )

    visible = [
        p for p in picks
        if (show_all or p["recommendation"] in ("LEAN", "RECOMMENDED"))
        and (min_conf == 0 or (p["confidence_score"] is not None and p["confidence_score"] >= min_conf))
    ]
```

- [ ] **Step 3: Add stars to pick card HTML in `_render_today`**

In the `for p in visible:` loop, after computing `edge_cls`, `card_cls`, `mkt`, add:

```python
        stars      = _stars(p["confidence_score"])
        star_color = _star_color(p["confidence_score"])
        factors    = json.loads(p["confidence_factors"] or "[]")
        factors_title = " | ".join(factors) if factors else "No data"
```

Then update the `st.markdown(f"""...""")` block. Replace the existing card HTML with:

```python
        st.markdown(f"""
<div class="{card_cls}">
  <span class="player-name">{p_name}</span>
  <span class="pick-meta"> &nbsp;·&nbsp; {mkt_esc} &nbsp;{sel_esc} {p['point']:g} &nbsp;@ &nbsp;{p['bovada_price']:+d}</span>
  <span class="{edge_cls}" style="float:right">EDGE {p['edge']:.1%}</span><br>
  <span class="pick-meta">
    BOV fair {p['bovada_fair_prob']:.1%} &nbsp;·&nbsp;
    Consensus {p['consensus_fair_prob']:.1%} &nbsp;·&nbsp;
    EV {p['ev']:+.1%} &nbsp;·&nbsp;
    {p['consensus_book_count']} books &nbsp;·&nbsp;
    <b>{rec_esc}</b>
  </span>
  <span title="{_html.escape(factors_title)}"
        style="float:right;color:{star_color};font-size:15px;cursor:help">{stars}</span>
</div>
""", unsafe_allow_html=True)
```

- [ ] **Step 4: Verify syntax**

```
python -c "import ast; ast.parse(open('dashboard.py').read()); print('syntax OK')"
```

Expected: `syntax OK`

- [ ] **Step 5: Verify dashboard loads in browser**

```
streamlit run dashboard.py
```

Open `http://localhost:8501`. Check:
- Today's Picks shows star filter selectbox next to "Show all" checkbox
- Each pick card shows stars on the right side (★★★☆ etc.)
- Hovering over stars shows the factor tooltip
- Changing min confidence filter to "2+ stars" hides picks with 0-1 stars and unscored picks
- Picks with 0 stars and no data show no stars (empty string)

- [ ] **Step 6: Commit**

```
git add dashboard.py
git commit -m "feat: show confidence stars on pick cards with filter"
```

---

## Self-Review

**Spec coverage:**
- ✅ MLB Stats API data — `stats.py` fetches pitcher/batter recent stats + season rates + opposing team stats
- ✅ Confidence scoring — `confidence.py` maps signals to factor strings; score = count of aligned signals, capped at 4
- ✅ All 5 markets covered — pitcher_strikeouts, pitcher_hits_allowed, pitcher_earned_runs, batter_hits, batter_total_bases
- ✅ Never breaks the pipeline — `score_pick` catches all exceptions; scoring failure leaves `confidence_score=NULL`
- ✅ Stars visible in dashboard — pick cards show ★★★☆, tooltip shows factor list
- ✅ Filter by minimum stars — selectbox in Today's Picks
- ✅ Sorted by confidence within tier — highest confidence picks float to the top

**Placeholder scan:** No TBDs, no "similar to above," all code blocks complete.

**Type consistency:**
- `update_pick_confidence(conn, pick_id: int, score: int, factors: list[str])` matches every call site
- `score_pick(...)` returns `tuple[int, list[str]]` — matches `_score_picks` unpacking `s, factors`
- `p["confidence_score"]` and `p["confidence_factors"]` are valid column names in all DB reads
