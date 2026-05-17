# Game Totals (Over/Under) — Design Spec
**Date:** 2026-05-17
**Market:** MLB game totals (`totals`)
**Scope:** v1 — totals only; schema future-proofed for RL/ML

---

## 1. Architecture

Totals run as a parallel lane inside the existing daily pipeline. All existing infrastructure (consensus, edge, classify, signals) is reused unchanged.

```
run_daily.py
  [1/4] Pre-fetch game data (MLB Stats API) — unchanged, adds team offense stats
  [2/4] Pull props + totals odds (Odds API) — add "totals" to market list
         → stored in props_snapshots (player_name="" for game totals)
  [3/4] Score props → daily_picks              (unchanged)
  [3b]  Score game totals → daily_game_picks   (new)
  [4/4] Grade props (MLB Stats API player stats) — unchanged
  [4b]  Grade game picks (MLB Stats API linescore) — new
```

**New files:**
- `scorer_game.py` — signal scorer for game totals
- Additions to `db.py` — `daily_game_picks` table + CRUD helpers
- Additions to `grade.py` — game score grading logic
- Additions to `run_daily.py` — steps [3b] and [4b]
- Additions to `dashboard.py` — game pick cards + summary bar counts

**Unchanged:** `consensus.py`, `edge.py`, `pull_props.py` (market list only), all `signals/` modules.

---

## 2. Data Pull

Add `"totals"` to `V1_MARKETS` in `config.py`. The existing `_get_event_odds()` and `parse_snapshots()` functions handle game totals with no code changes — `player_name` will be `""` for totals outcomes since the Odds API returns no `description` field for game markets.

Odds API totals outcome format:
```json
{"name": "Over", "price": -110, "point": 8.5}
{"name": "Under", "price": -115, "point": 8.5}
```

No extra API calls or quota beyond adding one market key per event.

---

## 3. DB Schema

```sql
CREATE TABLE IF NOT EXISTS daily_game_picks (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    pick_date              TEXT NOT NULL,
    pulled_at              TEXT NOT NULL,
    event_id               TEXT NOT NULL,
    commence_time          TEXT,
    home_team              TEXT NOT NULL,
    away_team              TEXT NOT NULL,
    market_key             TEXT NOT NULL,        -- 'totals' (RL/ML later)
    selection              TEXT NOT NULL,        -- 'Over' or 'Under'
    point                  REAL NOT NULL,        -- total line e.g. 8.5
    bovada_price           INTEGER NOT NULL,
    bovada_break_even_prob REAL,
    bovada_fair_prob       REAL,
    consensus_fair_prob    REAL,
    consensus_book_count   INTEGER,
    edge                   REAL,
    recommendation         TEXT NOT NULL,        -- RECOMMENDED / LEAN / NO_BET
    signal_score           INTEGER,
    signal_breakdown       TEXT,                 -- JSON
    result                 TEXT DEFAULT 'PENDING', -- WIN / LOSS / PUSH / PENDING
    home_runs              INTEGER,              -- graded: actual home runs
    away_runs              INTEGER,              -- graded: actual away runs
    actual_total           REAL,                 -- home_runs + away_runs
    profit_units           REAL,
    bet_placed             INTEGER DEFAULT 0,
    units_wagered          REAL,
    notes                  TEXT,
    UNIQUE(pick_date, event_id, selection)
);
```

**Future-proofing for RL/ML:** `home_runs` + `away_runs` cover all grading cases:
- Totals: `actual_total` vs `point`
- RL: `(home_runs - away_runs)` vs `point`
- ML: `home_runs > away_runs` → home team wins

---

## 4. Signal Model

Weights sum to 100. Higher score = stronger Over signal; lower score = stronger Under signal (same directional logic as `scorer.py`).

| Signal | Weight | Source | Direction |
|---|---|---|---|
| `home_sp_quality` | 18 | MLB Stats API (ERA, WHIP) + Statcast (whiff%, hard_hit%) | Low ERA/whiff% → Under |
| `away_sp_quality` | 18 | same | same |
| `home_team_offense` | 14 | MLB Stats API team season stats (R/G, OPS) | High → Over |
| `away_team_offense` | 14 | same | same |
| `park_run_factor` | 14 | `signals/parks.py` hr_factor + hits_factor composite | Coors → Over |
| `weather` | 12 | `signals/weather.py` tailwind_factor + cold_penalty | Tailwind → Over |
| `umpire_run_factor` | 5 | invert `signals/umpires.py` K-tendency | Wide zone → fewer runs → Under |
| `edge` | 5 | consensus edge | Positive → Over |

**SP quality composite (per pitcher):**
1. ERA: normalize around league avg (~4.20). Lower ERA → more Under signal.
2. WHIP: normalize around league avg (~1.25). Lower WHIP → more Under signal.
3. Statcast whiff%: higher → more Ks → fewer baserunners → Under.
4. Statcast hard_hit%: higher → more damage when contact → Over.
5. xFIP when FanGraphs available (currently 403 — graceful degradation).

Composite is weighted average of available components. Missing data → neutral (0.5).

**Team offense data source:**
- Endpoint: `GET /api/v1/stats?stats=season&group=hitting&gameType=R&season={year}&sportId=1`
- Returns all 30 teams. Parse `runsPerGame` and `ops`.
- Cached in-process per season (same pattern as `signals/statcast.py`).
- New function: `signals/team_stats.py` → `get_team_offense(team_name, season)`

**Classification:** Reuse `classify_by_score(score, edge, market_key, selection, price)` unchanged. Game totals respect all existing price gates (`BET_PRICE_MIN=-151`, `BET_PRICE_MAX=150`) and the `EDGE_MIN_BET` floor for positive-odds picks.

**Whitelist:** Add `("totals", "Over")` and `("totals", "Under")` to `BET_WHITELIST` in `config.py`. No calibration filter at v1 launch (no historical data yet — add after ~4 weeks of results).

---

## 5. Grading

Runs after prop grading in step [4/4] of `run_daily.py`.

**Data source:** MLB Stats API `/schedule?date={yesterday}&sportId=1&hydrate=linescore`
- Same endpoint as game data fetch, adds `linescore` hydration.
- Returns `teams.home.score` and `teams.away.score` for completed games.

**Logic:**
```python
actual_total = home_runs + away_runs
if actual_total > point:  result = 'WIN' if selection == 'Over' else 'LOSS'
if actual_total < point:  result = 'WIN' if selection == 'Under' else 'LOSS'
if actual_total == point: result = 'PUSH'
```

**Profit:** Same unit model as props — `profit_units` derived from `bovada_price` and result.

**Postponements:** If game score unavailable or game not final, pick stays `PENDING`. Checked again on next run.

---

## 6. Dashboard Integration

Game picks appear on the **Today** tab below prop picks. Same RECOMMENDED/LEAN/NO_BET card style, matchup-formatted:

```
┌──────────────────────────────────────────────────────────────┐
│ NYY @ BOS  ·  Total Over  8.5  @  -110          EDGE 3.2%   │
│  RECOMMENDED                                                  │
│  Score: 72  ·  Sim: --  ·  BEV: 48%  ·  6 books            │
└──────────────────────────────────────────────────────────────┘
```

- No sim% for game picks in v1 (no historical distribution for simulation — add after backtest).
- Summary bar stat chips include game RECOMMENDED + LEAN counts.
- "Show all evaluated lines" checkbox applies to game picks too.
- ROI tab: `market_key = "totals"` appears as its own row in the by-market breakdown.

---

## 7. New File Summary

| File | Change |
|---|---|
| `config.py` | Add `"totals"` to `V1_MARKETS`; add totals to `BET_WHITELIST` |
| `signals/team_stats.py` | New — team offense fetch + cache |
| `scorer_game.py` | New — game totals signal scorer |
| `db.py` | Add `daily_game_picks` table, insert/query helpers |
| `grade.py` | Add game score grading function |
| `run_daily.py` | Add steps [3b] score game totals, [4b] grade game picks |
| `dashboard.py` | Game pick cards, summary bar counts, ROI row |

---

## 8. Out of Scope (v1)

- Simulation (no historical game total distribution yet)
- Calibration filter (needs ~4 weeks of results)
- Run Line and Moneyline (schema ready, build later)
- Bullpen quality signal (future enhancement)
- Recent team form / last-N-games splits (future enhancement)
