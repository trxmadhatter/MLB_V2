# MLB V2 — Full Signal Stack Design
**Date:** 2026-05-15  
**Status:** Pending user approval

---

## Problem

The current system produces picks using only three signals: market edge (Bovada vs consensus), a market whitelist, and a price range filter. A 0-star and 4-star pick with the same edge get identical recommendations. Player stats, matchups, ballpark, and weather data are either ignored (ballpark, weather) or computed but thrown away (player stats, team stats). This design replaces the edge-threshold tier system with a unified weighted score that uses all available signals.

---

## Goal

Every pick surfaces with a score from 0–100. That score — not edge alone — determines its recommendation tier. New signals are added from free sources. Weights are per-market, grounded in sports betting research, and configurable for tuning after backtest validation.

---

## Architecture

### New: `signals/` directory

Six focused modules. Each module has a single job and returns structured data. They do not call each other.

```
signals/
  __init__.py
  weather.py      — Open-Meteo API (free, no key required)
  parks.py        — Static park factors table (30 parks, Statcast-sourced)
  splits.py       — Platoon + home/away splits via MLB Stats API
  lineups.py      — Lineup confirmation + today's SP via MLB Stats API
  umpires.py      — HP umpire K tendency via static table
```

### New: `scorer.py`

Accepts a `SignalBundle` (dict of signal values) and a market key. Applies per-market weights. Returns a `PickScore` (numeric 0–100 + human-readable breakdown list).

### Modified files

| File | Change |
|---|---|
| `confidence.py` | Removed. Logic migrated into `scorer.py`. |
| `config.py` | Add score thresholds, per-market weight tables, stadium coords, weather toggle |
| `db.py` | Add `signal_score` (INT), `signal_breakdown` (TEXT JSON) to `daily_picks` |
| `backtest.py` | Add same columns to `backtest_picks` |
| `run_daily.py` | Replace confidence call with scorer call; use score for recommendation tier |
| `dashboard.py` | Show score bar + breakdown tooltip instead of stars |

---

## Signal Modules

### `signals/weather.py`

**Source:** Open-Meteo `https://api.open-meteo.com/v1/forecast`  
**Auth:** None required  
**Call:** One request per game venue per day (cached in-memory)

Returns per-game: `wind_speed_kph`, `wind_direction_deg`, `temp_c`, `precip_mm`, `is_dome` (from stadium table)

Derived signals for scoring:
- `tailwind_factor`: direction relative to home plate (0=neutral, +1=full tailwind, -1=full headwind). Tailwind favors Overs, headwind favors Unders for TB/HR.
- `cold_penalty`: temp < 10°C reduces scoring environment
- `precip_flag`: precipitation > 0.5mm (flag, may affect game)

Dome stadiums return zeros for all weather signals (no wind effect).

### `signals/parks.py`

**Source:** Static table embedded in module, based on Statcast 3-year park factors (2024–2026)  
**Update cadence:** Refresh once per season (opening day) or when dramatically stale

Provides per-team home park:
- `k_factor`: strikeout rate vs league avg (100 = neutral; >100 = more Ks)
- `hits_factor`: hit rate vs league avg
- `tb_factor`: total bases rate vs league avg  
- `hr_factor`: home run rate vs league avg

### `signals/splits.py`

**Source:** MLB Stats API — `statsType=vsLeft` / `vsRight` / `homeAndAway`  
**Auth:** None required

Returns per-player:
- Pitcher: `k_pct_vs_lhh`, `k_pct_vs_rhh`, `h9_vs_lhh`, `h9_vs_rhh`, `era_home`, `era_away`
- Batter: `slg_vs_lhp`, `slg_vs_rhp`, `avg_vs_lhp`, `avg_vs_rhp`, `tb_per_game_home`, `tb_per_game_away`

Used to compute `platoon_alignment`: does today's matchup favor the bet direction based on platoon tendencies?

### `signals/lineups.py`

**Source:** MLB Stats API `/schedule` → game `probablePitchers` + `/game/{pk}/boxscore`  
**Auth:** None required

Returns per-game:
- `starting_pitcher_id`: confirmed SP for the game (used for batter props)
- `lineup_confirmed`: bool — is the starting lineup posted?
- `batter_in_lineup`: bool — is the specific batter confirmed in today's order?
- `sp_era`: starter's current ERA
- `sp_k9`: starter's K/9
- `sp_hand`: L or R

If lineup not yet confirmed (pre-game), `batter_in_lineup = None` and pick gets a partial score.

### `signals/umpires.py`

**Source:** Static table built from UmpScorecards historical data  
**Update cadence:** Weekly (manual or scripted)

Today's umpire assignment pulled from MLB Stats API `/schedule?hydrate=officials`.

Returns per-game: `ump_k_tendency` — deviation from league avg K rate (-1 = low-K ump, 0 = neutral, +1 = high-K ump)

---

## Scoring Engine (`scorer.py`)

### Interface

```python
def score_pick(
    player_name: str,
    market_key: str,
    selection: str,
    point: float,
    home_team: str,
    away_team: str,
    edge: float,
    game_date: str,
    game_pk: int | None = None,
) -> tuple[int, list[str]]:
    """Returns (score 0-100, human-readable breakdown)."""
```

### Per-market weight tables

Stored in `config.py` as `SIGNAL_WEIGHTS`. Each entry maps signal name → points. Max sum = 100. Partial credit allowed (signal can contribute 0 to its full weight based on magnitude).

**`pitcher_strikeouts`**
```python
{
    "platoon_alignment":    20,   # pitcher hand vs lineup L/R composition
    "season_k_pct":         18,   # pitcher's K% this season
    "ump_k_tendency":       15,   # umpire historical K rate
    "park_k_factor":        12,   # park K factor vs league avg
    "recent_k_rate":        12,   # avg Ks last 5 starts
    "opp_team_k_pct":       10,   # opposing team K%
    "weather":               8,   # wind + temp effect
    "edge":                  5,   # Bovada vs consensus mispricing
}
```

**`batter_total_bases`**
```python
{
    "sp_quality":           22,   # starting pitcher ERA + K rate
    "platoon_alignment":    18,   # batter vs SP hand
    "recent_tb_per_game":   15,   # avg TB last 10 games
    "park_tb_factor":       15,   # park TB/HR factor
    "season_slg":           12,   # batter season SLG
    "weather_wind":         10,   # tailwind/headwind factor
    "edge":                  8,   # Bovada vs consensus mispricing
}
```

**`pitcher_outs`**
```python
{
    "recent_ip_per_start":  25,   # avg IP last 5 starts (key: is he going deep?)
    "opp_lineup_quality":   20,   # opposing lineup wOBA/OPS
    "season_ip_per_start":  18,   # season IP/GS
    "park_run_factor":      15,   # run environment (affects bullpen usage)
    "weather":              12,   # wind + dome factor
    "edge":                 10,   # Bovada vs consensus mispricing
}
```

**`pitcher_hits_allowed`**
```python
{
    "recent_h9":            22,   # avg H allowed last 5 starts
    "opp_team_woba":        20,   # opposing team wOBA
    "park_hits_factor":     18,   # park hits factor
    "season_whip":          15,   # season WHIP
    "platoon_alignment":    12,   # pitcher hand vs lineup composition
    "weather":              8,    # precipitation / wind
    "edge":                 5,    # Bovada vs consensus mispricing
}
```

### Partial credit rules

Each signal computes a `signal_score` between 0.0 and 1.0, then multiplied by its max weight. Examples:

- **edge** (0–1 proportional): edge=0.01 → 0.25, edge=0.04 → 0.75, edge≥0.08 → 1.0
- **park_k_factor** (symmetric): factor=110 for Over → 1.0; factor=90 → 0.0; factor=100 → 0.5
- **platoon_alignment**: full alignment → 1.0; neutral → 0.5; disadvantage → 0.0
- **weather/wind** (for Over): tailwind factor +1.0 → 1.0; neutral → 0.5; headwind → 0.0
- **ump_k_tendency**: high-K ump for K Over → 1.0; neutral → 0.5; low-K → 0.0

---

## Recommendation Tiers (new logic)

| Score | Tier |
|---|---|
| ≥ 65 | RECOMMENDED |
| 45–64 | LEAN |
| < 45 | NO_BET |

**Hard gates (score doesn't override these):**
- Market + direction must be on the whitelist
- Edge must be > 0% (consensus must agree with our direction at all)

No price filter hard gate (it was distorting results — price becomes a signal component instead).

---

## Database Changes

### `daily_picks` additions
```sql
signal_score       INTEGER,    -- 0-100 composite score
signal_breakdown   TEXT,       -- JSON array of {signal, points_earned, max_points, note}
```

### `backtest_picks` additions
```sql
signal_score       INTEGER,
signal_breakdown   TEXT,
```

Storing breakdown in backtest enables future regression analysis: which signals actually predicted wins.

---

## Dashboard Changes

- Replace ★★★☆ stars with a numeric score bar (e.g., `82/100 ██████████░░`)
- Score breakdown shown as tooltip/expandable (same data as `signal_breakdown`)
- Add score filter slider to dashboard sidebar (min score: 0–80)
- Remove the old "min confidence" dropdown

---

## Data that is NOT included (and why)

| Signal | Why excluded |
|---|---|
| Sharp line movement | Requires Odds API calls — user preference, avoid tokens |
| Pitcher velocity trends | Requires Statcast scraping (JS-rendered) — complex, skip v1 |
| Pitcher spin rate | Same as above |
| Batter plate discipline (O-Swing%) | Statcast-only — skip v1 |
| Injury reports | Requires paid feed or fragile scraping — skip v1 |
| Lineup batting order position | Available but minor signal vs complexity — skip v1 |

All exclusions are scope decisions for v1. Architecture allows adding them later.

---

## Implementation Phases

1. **Core scaffold** — create `signals/` directory, stub all modules with correct interfaces
2. **Free MLB Stats API signals** — splits.py + lineups.py (no new data sources)
3. **Static data** — parks.py (embed table), umpires.py (embed table)
4. **Weather** — weather.py (Open-Meteo, no key needed)
5. **Scorer** — scorer.py with full weight tables
6. **DB + backtest** — add score columns, store breakdown
7. **Run pipeline** — wire scorer into run_daily.py, replace confidence.py
8. **Dashboard** — replace stars with score bar + breakdown

---

## Validation Plan

After implementation:
1. Run `python backtest.py --reset --days 45` (uses Odds API — needs user approval before running)
2. Run `python research.py` — compare RECOMMENDED win% before vs after score filter
3. Examine `signal_breakdown` in DB to identify which signals are firing most
4. Adjust weights in `config.py` based on which signals correlate with wins
