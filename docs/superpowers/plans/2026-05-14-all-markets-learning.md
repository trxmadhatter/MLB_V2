# All-Markets Expansion + Miss Learning System

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the prop pipeline to all available MLB markets, fix grade.py's missing stat extractors, and build a persistent calibration/learning system that shows which markets and directions are genuinely profitable.

**Architecture:** Three independent layers — (1) data: fix and expand what grade.py extracts from MLB boxscores and what markets we fetch; (2) fetch pipeline: thread ALL_PROP_MARKETS through backtest_fetch.py with a --reset flag so we can re-run fresh; (3) learning: market_learn.py computes observed win% vs break-even per market×direction×edge bucket, persists to JSON, surfaces in the backtest report and dashboard.

**Tech Stack:** Python 3.11, SQLite (backtest.db), MLB Stats API (free), The Odds API historical endpoint, Streamlit dashboard, pytest.

---

## Critical bug discovered before writing this plan

`grade.py` currently extracts only 3 stats from MLB boxscores:
- `batter_hits` (batting.hits)
- `batter_total_bases` (batting.totalBases)
- `pitcher_strikeouts` (pitching.strikeOuts)

**Missing (in V1_MARKETS but never graded — 100% PENDING in backtest):**
- `pitcher_hits_allowed` — reads `pitching.hits`
- `pitcher_earned_runs` — reads `pitching.earnedRuns`
- `batter_hits` is extracted but had 0 picks in the 14-day run (thin consensus)

Task 1 fixes this and adds 7 more markets.

---

## File map

| File | Change |
|------|--------|
| `config.py` | Add `ALL_PROP_MARKETS` list (12 markets) |
| `grade.py` | Fix 2 missing extractors, add 7 new stat extractors |
| `pull_props.py` | `parse_snapshots` accepts optional `markets` filter param |
| `backtest_fetch.py` | Use `ALL_PROP_MARKETS` by default; pass through to `parse_snapshots` |
| `backtest.py` | Add `--reset` flag; add calibration section to `print_report` |
| `market_learn.py` | **New** — calibration computation, save/load, insight text |
| `dashboard.py` | Update `MARKET_LABELS`; add Market Calibration panel to Results tab |
| `tests/test_grade.py` | Add `TestGetGameResultsExtractors` class |
| `tests/test_market_learn.py` | **New** — 8 tests for calibration and persistence |

---

## Task 1: Fix grade.py missing extractors + expand all prop markets

**Files:**
- Modify: `config.py`
- Modify: `grade.py`
- Modify: `dashboard.py` (MARKET_LABELS only)
- Modify: `backtest.py` (MARKET_LABELS only)
- Modify: `tests/test_grade.py`

### Context

The `get_game_results(date_str)` function in grade.py is the single source of actual stats for grading. It fetches the schedule, then a boxscore per game, and extracts stat values per player. Right now it only emits 3 markets. We need 12.

The MLB Stats API boxscore per-player structure:
```json
{
  "stats": {
    "batting":  { "hits": 2, "totalBases": 5, "homeRuns": 1, "rbi": 2,
                  "runs": 1, "stolenBases": 0, "baseOnBalls": 1 },
    "pitching": { "strikeOuts": 7, "hits": 4, "earnedRuns": 2,
                  "baseOnBalls": 2, "outs": 21 }
  }
}
```

The Odds API market key → boxscore field mapping:

| market_key | source | field |
|---|---|---|
| batter_hits | batting | hits |
| batter_total_bases | batting | totalBases |
| batter_home_runs | batting | homeRuns |
| batter_rbis | batting | rbi |
| batter_runs_scored | batting | runs |
| batter_stolen_bases | batting | stolenBases |
| batter_walks | batting | baseOnBalls |
| pitcher_strikeouts | pitching | strikeOuts |
| pitcher_hits_allowed | pitching | hits |
| pitcher_earned_runs | pitching | earnedRuns |
| pitcher_walks | pitching | baseOnBalls |
| pitcher_outs | pitching | outs |

- [ ] **Step 1: Write the failing tests for new grade.py extractors**

Add `TestGetGameResultsExtractors` to `tests/test_grade.py`. The tests mock `requests.get` to return a synthetic schedule + boxscore, then assert the correct market_key and stat_value are present in the result.

```python
# tests/test_grade.py — add BELOW existing classes (do not remove anything)
from unittest import mock


class TestGetGameResultsExtractors:
    def _make_resp(self, data):
        m = mock.Mock()
        m.raise_for_status = mock.Mock()
        m.json.return_value = data
        return m

    def _schedule(self):
        return {
            "dates": [{
                "games": [{
                    "gamePk": 999,
                    "status": {"abstractGameState": "Final"},
                }]
            }]
        }

    def _boxscore(self, batting=None, pitching=None, name="Test Player"):
        return {
            "teams": {
                "home": {
                    "players": {
                        "ID1": {
                            "person": {"fullName": name},
                            "stats": {
                                "batting":  batting  or {},
                                "pitching": pitching or {},
                            },
                        }
                    }
                },
                "away": {"players": {}},
            }
        }

    def test_pitcher_hits_allowed_extracted(self):
        with mock.patch("requests.get") as mg:
            mg.side_effect = [
                self._make_resp(self._schedule()),
                self._make_resp(self._boxscore(pitching={"hits": 6})),
            ]
            from grade import get_game_results
            results = get_game_results("2026-05-01")
        found = [r for r in results if r["market_key"] == "pitcher_hits_allowed"]
        assert len(found) == 1
        assert found[0]["stat_value"] == 6

    def test_pitcher_earned_runs_extracted(self):
        with mock.patch("requests.get") as mg:
            mg.side_effect = [
                self._make_resp(self._schedule()),
                self._make_resp(self._boxscore(pitching={"earnedRuns": 3})),
            ]
            from grade import get_game_results
            results = get_game_results("2026-05-01")
        found = [r for r in results if r["market_key"] == "pitcher_earned_runs"]
        assert len(found) == 1
        assert found[0]["stat_value"] == 3

    def test_batter_home_runs_extracted(self):
        with mock.patch("requests.get") as mg:
            mg.side_effect = [
                self._make_resp(self._schedule()),
                self._make_resp(self._boxscore(batting={"homeRuns": 2})),
            ]
            from grade import get_game_results
            results = get_game_results("2026-05-01")
        found = [r for r in results if r["market_key"] == "batter_home_runs"]
        assert len(found) == 1
        assert found[0]["stat_value"] == 2

    def test_zero_value_still_extracted(self):
        """0 home runs is a valid outcome and must be graded (can't skip 0-value stats)."""
        with mock.patch("requests.get") as mg:
            mg.side_effect = [
                self._make_resp(self._schedule()),
                self._make_resp(self._boxscore(batting={"homeRuns": 0})),
            ]
            from grade import get_game_results
            results = get_game_results("2026-05-01")
        found = [r for r in results if r["market_key"] == "batter_home_runs"]
        assert len(found) == 1
        assert found[0]["stat_value"] == 0

    def test_all_12_markets_extracted_in_one_call(self):
        batting  = {"hits": 2, "totalBases": 5, "homeRuns": 1, "rbi": 2,
                    "runs": 1, "stolenBases": 1, "baseOnBalls": 1}
        pitching = {"strikeOuts": 7, "hits": 4, "earnedRuns": 2,
                    "baseOnBalls": 2, "outs": 21}
        with mock.patch("requests.get") as mg:
            mg.side_effect = [
                self._make_resp(self._schedule()),
                self._make_resp(self._boxscore(batting=batting, pitching=pitching)),
            ]
            from grade import get_game_results
            results = get_game_results("2026-05-01")
        found = {r["market_key"] for r in results}
        expected = {
            "batter_hits", "batter_total_bases", "batter_home_runs", "batter_rbis",
            "batter_runs_scored", "batter_stolen_bases", "batter_walks",
            "pitcher_strikeouts", "pitcher_hits_allowed", "pitcher_earned_runs",
            "pitcher_walks", "pitcher_outs",
        }
        assert expected == found

    def test_skips_non_final_games(self):
        schedule = {
            "dates": [{
                "games": [{
                    "gamePk": 999,
                    "status": {"abstractGameState": "Live"},
                }]
            }]
        }
        with mock.patch("requests.get") as mg:
            mg.side_effect = [self._make_resp(schedule)]
            from grade import get_game_results
            results = get_game_results("2026-05-01")
        assert results == []
```

- [ ] **Step 2: Run the new tests — verify they fail**

```
cd C:\Users\jesse\MLB_V2
pytest tests/test_grade.py::TestGetGameResultsExtractors -v
```

Expected: 6 failures (grade.py missing extractors).

- [ ] **Step 3: Rewrite the stat extraction block in grade.py**

In `grade.py`, replace the entire `bstats`/`pstats` extraction block inside the player loop with the refactored version. The rest of the function is untouched.

Find this block (lines 78-105):
```python
                    bstats = stats.get("batting", {})
                    h  = bstats.get("hits")
                    tb = bstats.get("totalBases")

                    pstats = stats.get("pitching", {})
                    k = pstats.get("strikeOuts")

                    if h is not None:
                        results.append({
                            "player_name":      full_name,
                            "player_name_norm": norm,
                            "market_key":       "batter_hits",
                            "stat_value":       int(h),
                        })
                    if tb is not None:
                        results.append({
                            "player_name":      full_name,
                            "player_name_norm": norm,
                            "market_key":       "batter_total_bases",
                            "stat_value":       int(tb),
                        })
                    if k is not None:
                        results.append({
                            "player_name":      full_name,
                            "player_name_norm": norm,
                            "market_key":       "pitcher_strikeouts",
                            "stat_value":       int(k),
                        })
```

Replace with:
```python
                    bstats  = stats.get("batting",  {})
                    pstats  = stats.get("pitching", {})

                    _extracts = [
                        (bstats.get("hits"),          "batter_hits"),
                        (bstats.get("totalBases"),    "batter_total_bases"),
                        (bstats.get("homeRuns"),      "batter_home_runs"),
                        (bstats.get("rbi"),           "batter_rbis"),
                        (bstats.get("runs"),          "batter_runs_scored"),
                        (bstats.get("stolenBases"),   "batter_stolen_bases"),
                        (bstats.get("baseOnBalls"),   "batter_walks"),
                        (pstats.get("strikeOuts"),    "pitcher_strikeouts"),
                        (pstats.get("hits"),          "pitcher_hits_allowed"),
                        (pstats.get("earnedRuns"),    "pitcher_earned_runs"),
                        (pstats.get("baseOnBalls"),   "pitcher_walks"),
                        (pstats.get("outs"),          "pitcher_outs"),
                    ]
                    for val, mkt in _extracts:
                        if val is not None:
                            results.append({
                                "player_name":      full_name,
                                "player_name_norm": norm,
                                "market_key":       mkt,
                                "stat_value":       int(val),
                            })
```

- [ ] **Step 4: Run the tests — verify they pass**

```
pytest tests/test_grade.py -v
```

Expected: all tests pass including the 6 new ones.

- [ ] **Step 5: Add ALL_PROP_MARKETS to config.py**

In `config.py`, add after the existing `V1_MARKETS` block:

```python
# V1 player prop markets only
V1_MARKETS = [
    "pitcher_strikeouts",
    "pitcher_hits_allowed",
    "pitcher_earned_runs",
    "batter_hits",
    "batter_total_bases",
]

# All player prop markets to test and backtest
ALL_PROP_MARKETS = [
    "pitcher_strikeouts",
    "pitcher_hits_allowed",
    "pitcher_earned_runs",
    "pitcher_walks",
    "pitcher_outs",
    "batter_hits",
    "batter_total_bases",
    "batter_home_runs",
    "batter_rbis",
    "batter_runs_scored",
    "batter_stolen_bases",
    "batter_walks",
]
```

- [ ] **Step 6: Update MARKET_LABELS in backtest.py and dashboard.py**

In `backtest.py`, replace the `MARKET_LABELS` dict:
```python
MARKET_LABELS = {
    "pitcher_strikeouts":   "K (P)",
    "pitcher_hits_allowed": "Hits (P)",
    "pitcher_earned_runs":  "ER (P)",
    "pitcher_walks":        "BB (P)",
    "pitcher_outs":         "Outs (P)",
    "batter_hits":          "Hits (B)",
    "batter_total_bases":   "TB (B)",
    "batter_home_runs":     "HR (B)",
    "batter_rbis":          "RBI (B)",
    "batter_runs_scored":   "R (B)",
    "batter_stolen_bases":  "SB (B)",
    "batter_walks":         "BB (B)",
}
```

In `dashboard.py`, replace the `MARKET_LABELS` dict with the same dict above.

- [ ] **Step 7: Commit**

```
git add config.py grade.py backtest.py dashboard.py tests/test_grade.py
git commit -m "feat: expand grade.py to all 12 prop markets, fix missing pitcher_hits/ER extractors"
```

---

## Task 2: Thread ALL_PROP_MARKETS through backtest fetch + add --reset flag

**Files:**
- Modify: `pull_props.py` (`parse_snapshots` signature)
- Modify: `backtest_fetch.py` (use ALL_PROP_MARKETS)
- Modify: `backtest.py` (add --reset flag)
- Modify: `tests/test_backtest_fetch.py` (update for new signature)

### Context

Currently `parse_snapshots` hard-filters to `V1_MARKETS`. The live pipeline is safe — `pull_and_store` already restricts the API request to V1 markets, so API response only contains V1 data regardless. The backtest needs to fetch ALL_PROP_MARKETS.

`backtest_fetch.py` currently hard-codes `V1_MARKETS` in the API request params. After this task it will default to `ALL_PROP_MARKETS`.

The `--reset` flag deletes `data/backtest.db` before running, allowing a clean 14-day rerun with all 12 markets. Without `--reset`, the existing db picks are preserved and only new/unprocessed dates are fetched.

- [ ] **Step 1: Write the failing test for parse_snapshots markets param**

In `tests/test_backtest_fetch.py`, add one test to `TestParseSnapshots` (or wherever parse_snapshots is tested). If that class doesn't exist, add to the file:

```python
# In tests/test_backtest_fetch.py — add this test to an appropriate class or at module level
def test_parse_snapshots_accepts_markets_filter():
    """parse_snapshots(events, pulled_at, markets=[...]) should only emit rows for listed markets."""
    from pull_props import parse_snapshots
    event = {
        "id": "abc", "commence_time": "2026-05-01T18:00:00Z",
        "home_team": "Cubs", "away_team": "Cardinals",
        "bookmakers": [{
            "key": "draftkings", "last_update": None,
            "markets": [
                {
                    "key": "pitcher_strikeouts",
                    "outcomes": [{"name": "Over", "description": "G. Cole", "point": 7.5, "price": -115}],
                },
                {
                    "key": "batter_home_runs",
                    "outcomes": [{"name": "Over", "description": "A. Judge", "point": 0.5, "price": -130}],
                },
            ],
        }],
    }
    rows = parse_snapshots([event], "2026-05-01T12:00:00Z", markets=["pitcher_strikeouts"])
    assert len(rows) == 1
    assert rows[0]["market_key"] == "pitcher_strikeouts"


def test_parse_snapshots_no_filter_accepts_all():
    """parse_snapshots with markets=None accepts everything."""
    from pull_props import parse_snapshots
    event = {
        "id": "abc", "commence_time": "2026-05-01T18:00:00Z",
        "home_team": "Cubs", "away_team": "Cardinals",
        "bookmakers": [{
            "key": "draftkings", "last_update": None,
            "markets": [
                {
                    "key": "pitcher_strikeouts",
                    "outcomes": [{"name": "Over", "description": "G. Cole", "point": 7.5, "price": -115}],
                },
                {
                    "key": "batter_home_runs",
                    "outcomes": [{"name": "Over", "description": "A. Judge", "point": 0.5, "price": -130}],
                },
            ],
        }],
    }
    rows = parse_snapshots([event], "2026-05-01T12:00:00Z", markets=None)
    assert len(rows) == 2
```

- [ ] **Step 2: Run the new tests — verify they fail**

```
pytest tests/test_backtest_fetch.py::test_parse_snapshots_accepts_markets_filter tests/test_backtest_fetch.py::test_parse_snapshots_no_filter_accepts_all -v
```

Expected: both fail (parse_snapshots does not yet accept markets param).

- [ ] **Step 3: Update parse_snapshots in pull_props.py**

In `pull_props.py`, change the `parse_snapshots` signature and the market filter:

Old:
```python
def parse_snapshots(events: list[dict], pulled_at: str) -> list[dict]:
    rows: list[dict] = []
    for event in events:
        event_id      = event["id"]
        commence_time = event["commence_time"]
        home_team     = event["home_team"]
        away_team     = event["away_team"]
        for book in event.get("bookmakers", []):
            bookmaker_key = book["key"]
            last_update   = book.get("last_update")
            for market in book.get("markets", []):
                if market["key"] not in V1_MARKETS:
                    continue
```

New:
```python
def parse_snapshots(
    events: list[dict],
    pulled_at: str,
    markets: list[str] | None = None,
) -> list[dict]:
    rows: list[dict] = []
    for event in events:
        event_id      = event["id"]
        commence_time = event["commence_time"]
        home_team     = event["home_team"]
        away_team     = event["away_team"]
        for book in event.get("bookmakers", []):
            bookmaker_key = book["key"]
            last_update   = book.get("last_update")
            for market in book.get("markets", []):
                if markets is not None and market["key"] not in markets:
                    continue
```

Remove the `from config import ... V1_MARKETS` import if V1_MARKETS is no longer used in pull_props.py (check first — `_get_event_odds` still uses it).

- [ ] **Step 4: Run the tests — verify they pass**

```
pytest tests/test_backtest_fetch.py -v
```

Expected: all pass.

- [ ] **Step 5: Update backtest_fetch.py to use ALL_PROP_MARKETS**

In `backtest_fetch.py`, change the import and both functions:

Old import:
```python
from config import SPORT, REGIONS, ODDS_FORMAT, V1_MARKETS
```

New import:
```python
from config import SPORT, REGIONS, ODDS_FORMAT, ALL_PROP_MARKETS
```

Old `fetch_historical_event_odds`:
```python
def fetch_historical_event_odds(
    api_key: str,
    event_id: str,
    date_iso: str,
) -> dict:
    url = f"{_HIST_BASE}/sports/{SPORT}/events/{event_id}/odds"
    resp = requests.get(
        url,
        params={
            "apiKey":     api_key,
            "date":       date_iso,
            "regions":    REGIONS,
            "markets":    ",".join(V1_MARKETS),
            "oddsFormat": ODDS_FORMAT,
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    _log_quota(resp)
    return resp.json()["data"]
```

New:
```python
def fetch_historical_event_odds(
    api_key: str,
    event_id: str,
    date_iso: str,
    markets: list[str] | None = None,
) -> dict:
    if markets is None:
        markets = ALL_PROP_MARKETS
    url = f"{_HIST_BASE}/sports/{SPORT}/events/{event_id}/odds"
    resp = requests.get(
        url,
        params={
            "apiKey":     api_key,
            "date":       date_iso,
            "regions":    REGIONS,
            "markets":    ",".join(markets),
            "oddsFormat": ODDS_FORMAT,
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    _log_quota(resp)
    return resp.json()["data"]
```

Old `pull_historical_snapshots`:
```python
def pull_historical_snapshots(
    api_key: str,
    date_str: str,
    odds_time: str = "12:00:00",
) -> tuple[str, list[dict]]:
    date_iso = f"{date_str}T{odds_time}Z"
    events = fetch_historical_events(api_key, date_str, odds_time)
    print(f"  {date_str}: {len(events)} events found")

    all_rows: list[dict] = []
    for event in events:
        event_id = event["id"]
        home     = event.get("home_team", "")
        away     = event.get("away_team", "")
        print(f"    {away} @ {home}")
        odds_event = fetch_historical_event_odds(api_key, event_id, date_iso)
        rows = parse_snapshots([odds_event], date_iso)
        all_rows.extend(rows)

    return date_iso, all_rows
```

New:
```python
def pull_historical_snapshots(
    api_key: str,
    date_str: str,
    odds_time: str = "12:00:00",
    markets: list[str] | None = None,
) -> tuple[str, list[dict]]:
    if markets is None:
        markets = ALL_PROP_MARKETS
    date_iso = f"{date_str}T{odds_time}Z"
    events = fetch_historical_events(api_key, date_str, odds_time)
    print(f"  {date_str}: {len(events)} events found")

    all_rows: list[dict] = []
    for event in events:
        event_id = event["id"]
        home     = event.get("home_team", "")
        away     = event.get("away_team", "")
        print(f"    {away} @ {home}")
        odds_event = fetch_historical_event_odds(api_key, event_id, date_iso, markets=markets)
        rows = parse_snapshots([odds_event], date_iso)
        all_rows.extend(rows)

    return date_iso, all_rows
```

- [ ] **Step 6: Add --reset flag to backtest.py**

In `backtest.py`, add to the argparse block:
```python
    parser.add_argument("--reset", action="store_true",
                        help="Delete backtest DB before running (fresh start with all markets)")
```

In `main()`, add after `bt_conn = _get_bt_conn()`:
```python
    # Put this BEFORE _get_bt_conn(), not after:
```

Actually restructure the main() reset logic to happen before opening the connection:

```python
def main() -> None:
    today = (datetime.now(timezone.utc) - timedelta(hours=7)).strftime("%Y-%m-%d")

    parser = argparse.ArgumentParser(description="MLB V2 Backtester")
    parser.add_argument("--days",        type=int, default=14, ...)
    parser.add_argument("--from",  dest="start_date", default=None, ...)
    parser.add_argument("--to",    dest="end_date",   default=None, ...)
    parser.add_argument("--report-only", action="store_true", ...)
    parser.add_argument("--reset",       action="store_true",
                        help="Delete backtest DB before running (fresh start with all markets)")
    args = parser.parse_args()

    if args.reset and not args.report_only:
        if BACKTEST_DB.exists():
            BACKTEST_DB.unlink()
            print("  Backtest DB reset. Starting fresh.")

    bt_conn = _get_bt_conn()
    ...
```

- [ ] **Step 7: Run all tests**

```
pytest tests/ -v
```

Expected: all pass.

- [ ] **Step 8: Commit**

```
git add pull_props.py backtest_fetch.py backtest.py tests/test_backtest_fetch.py
git commit -m "feat: thread ALL_PROP_MARKETS through backtest fetch pipeline, add --reset flag"
```

---

## Task 3: Market calibration / miss learning system

**Files:**
- Create: `market_learn.py`
- Modify: `backtest.py` (calibration section in `print_report`, save after report)
- Modify: `dashboard.py` (Market Calibration panel in Results & Learning tab)
- Create: `tests/test_market_learn.py`

### Context

The calibration system answers: "For each (market_key, selection, edge_bucket), is our model's edge call actually profitable?"

- `compute_calibration(bt_conn)` reads all graded picks, groups by (market, side, bucket), computes `win_rate` and compares to `breakeven` implied by the avg Bovada price.
- If `win_rate >= breakeven`, the market/direction is genuinely profitable.
- Results saved to `data/market_calibration.json` after every `print_report` call so the dashboard can load it without touching backtest.db.
- `MIN_SAMPLE = 20` — buckets with fewer graded picks are excluded (too noisy to trust).

Break-even probability from American odds: if price > 0, `bev = 100 / (price + 100)`. If price < 0, `bev = |price| / (|price| + 100)`.

Edge vs break-even: `win_rate - breakeven`. Positive = profitable, negative = avoid.

The backtest `--report-only` flag must also save calibration (so the dashboard stays fresh without re-fetching).

- [ ] **Step 1: Write tests for market_learn.py**

Create `tests/test_market_learn.py`:

```python
import json
import sqlite3

import pytest

from backtest import init_backtest_db


@pytest.fixture
def bt_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_backtest_db(conn)
    return conn


def _insert(conn, picks):
    conn.executemany(
        """
        INSERT INTO backtest_picks
            (pick_date, player_name, market_key, selection, point,
             bovada_price, bovada_fair_prob, consensus_fair_prob,
             consensus_book_count, edge, ev, recommendation,
             result, actual_stat, profit_units)
        VALUES
            (:pick_date, :player_name, :market_key, :selection, :point,
             :bovada_price, :bovada_fair_prob, :consensus_fair_prob,
             :consensus_book_count, :edge, :ev, :recommendation,
             :result, :actual_stat, :profit_units)
        """,
        picks,
    )
    conn.commit()


def _p(**kw):
    base = dict(
        pick_date="2026-05-01", player_name="Test Player",
        market_key="pitcher_strikeouts", selection="Over", point=5.5,
        bovada_price=-115, bovada_fair_prob=0.535, consensus_fair_prob=0.575,
        consensus_book_count=4, edge=0.03, ev=0.02, recommendation="LEAN",
        result="WIN", actual_stat=7.0, profit_units=0.87,
    )
    base.update(kw)
    return base


class TestComputeCalibration:
    def test_empty_db_returns_empty(self, bt_conn):
        from market_learn import compute_calibration
        assert compute_calibration(bt_conn) == []

    def test_below_min_sample_excluded(self, bt_conn):
        from market_learn import compute_calibration
        _insert(bt_conn, [_p() for _ in range(19)])  # 19 < MIN_SAMPLE of 20
        assert compute_calibration(bt_conn) == []

    def test_at_min_sample_included(self, bt_conn):
        from market_learn import compute_calibration
        _insert(bt_conn, [_p() for _ in range(20)])
        assert len(compute_calibration(bt_conn)) == 1

    def test_profitable_when_win_rate_above_breakeven(self, bt_conn):
        # -115 breakeven = 115/215 = 53.5%
        # 15W / 5L = 75% win rate → profitable
        from market_learn import compute_calibration
        picks = (
            [_p(result="WIN",  profit_units=0.87) for _ in range(15)]
            + [_p(result="LOSS", profit_units=-1.0) for _ in range(5)]
        )
        _insert(bt_conn, picks)
        cal = compute_calibration(bt_conn)
        assert cal[0]["profitable"] is True
        assert abs(cal[0]["win_rate"] - 0.75) < 0.001

    def test_unprofitable_when_win_rate_below_breakeven(self, bt_conn):
        # 10W / 10L = 50% < 53.5% breakeven
        from market_learn import compute_calibration
        picks = (
            [_p(result="WIN",  profit_units=0.87) for _ in range(10)]
            + [_p(result="LOSS", profit_units=-1.0) for _ in range(10)]
        )
        _insert(bt_conn, picks)
        cal = compute_calibration(bt_conn)
        assert cal[0]["profitable"] is False

    def test_sorted_best_first(self, bt_conn):
        # pitcher_strikeouts: 15W/5L (profitable)
        # batter_total_bases: 8W/12L (unprofitable)
        from market_learn import compute_calibration
        ko = (
            [_p(market_key="pitcher_strikeouts", result="WIN",  profit_units=0.87) for _ in range(15)]
            + [_p(market_key="pitcher_strikeouts", result="LOSS", profit_units=-1.0) for _ in range(5)]
        )
        tb = (
            [_p(market_key="batter_total_bases", result="WIN",  profit_units=0.87) for _ in range(8)]
            + [_p(market_key="batter_total_bases", result="LOSS", profit_units=-1.0) for _ in range(12)]
        )
        _insert(bt_conn, ko + tb)
        cal = compute_calibration(bt_conn)
        assert cal[0]["market_key"] == "pitcher_strikeouts"
        assert cal[-1]["market_key"] == "batter_total_bases"

    def test_pushes_excluded_from_win_rate_calc(self, bt_conn):
        # 10W / 5L / 5P = win rate is 10/15 = 66.7%, not 10/20 = 50%
        from market_learn import compute_calibration
        picks = (
            [_p(result="WIN",  profit_units=0.87)  for _ in range(10)]
            + [_p(result="LOSS", profit_units=-1.0) for _ in range(5)]
            + [_p(result="PUSH", profit_units=0.0)  for _ in range(5)]
        )
        _insert(bt_conn, picks)
        cal = compute_calibration(bt_conn)
        assert abs(cal[0]["win_rate"] - 10 / 15) < 0.001


class TestSaveLoadCalibration:
    def test_roundtrip(self, tmp_path):
        from market_learn import save_calibration, load_calibration
        data = [{"market_key": "pitcher_strikeouts", "win_rate": 0.563, "profitable": True}]
        path = tmp_path / "cal.json"
        save_calibration(data, path)
        assert load_calibration(path) == data

    def test_load_missing_file_returns_empty(self, tmp_path):
        from market_learn import load_calibration
        assert load_calibration(tmp_path / "nofile.json") == []


class TestInsightText:
    def test_profitable_signal_contains_key_info(self):
        from market_learn import insight_text
        row = {
            "market_key": "pitcher_strikeouts", "selection": "Over",
            "edge_bucket": "2-4%", "wins": 22, "losses": 17,
            "win_rate": 0.564, "breakeven": 0.524, "edge_vs_breakeven": 0.040,
            "net_units": 4.69, "profitable": True,
        }
        text = insight_text(row)
        assert "pitcher_strikeouts" in text
        assert "Over" in text
        assert "56.4%" in text or "0.564" in text
```

- [ ] **Step 2: Run tests — verify they fail**

```
pytest tests/test_market_learn.py -v
```

Expected: ModuleNotFoundError for market_learn (file doesn't exist yet).

- [ ] **Step 3: Create market_learn.py**

Create `C:\Users\jesse\MLB_V2\market_learn.py`:

```python
"""
Market calibration: tracks observed win rates vs break-even by
(market_key, selection, edge_bucket). Persists to data/market_calibration.json.
Call compute_calibration(bt_conn) after any backtest run to refresh insights.
"""
import json
import sqlite3
from pathlib import Path

CALIBRATION_PATH = Path(__file__).parent / "data" / "market_calibration.json"
MIN_SAMPLE = 20


def _edge_bucket(edge: float) -> str:
    if edge >= 0.06: return "6%+"
    if edge >= 0.04: return "4-6%"
    if edge >= 0.02: return "2-4%"
    return "<2%"


def _breakeven(price: int) -> float:
    if price > 0:
        return 100.0 / (price + 100)
    return abs(price) / (abs(price) + 100)


def compute_calibration(bt_conn: sqlite3.Connection) -> list[dict]:
    """
    Returns calibration stats per (market_key, selection, edge_bucket),
    sorted best-to-worst by (observed win_rate - breakeven).
    Only includes buckets with >= MIN_SAMPLE decided picks.
    """
    rows = bt_conn.execute("""
        SELECT market_key, selection, edge, bovada_price, result, profit_units
        FROM backtest_picks
        WHERE result IN ('WIN', 'LOSS', 'PUSH')
    """).fetchall()

    buckets: dict[tuple, dict] = {}
    for r in rows:
        key = (r["market_key"], r["selection"], _edge_bucket(r["edge"]))
        if key not in buckets:
            buckets[key] = {"wins": 0, "losses": 0, "pushes": 0,
                            "prices": [], "profit": 0.0}
        b = buckets[key]
        if r["result"] == "WIN":    b["wins"]   += 1
        elif r["result"] == "LOSS": b["losses"] += 1
        else:                       b["pushes"] += 1
        b["prices"].append(r["bovada_price"])
        b["profit"] += r["profit_units"] or 0.0

    results = []
    for (mkt, sel, bucket), b in buckets.items():
        decided = b["wins"] + b["losses"]
        if decided < MIN_SAMPLE:
            continue
        win_rate  = b["wins"] / decided
        avg_price = sum(b["prices"]) / len(b["prices"])
        bev       = _breakeven(int(round(avg_price)))
        results.append({
            "market_key":        mkt,
            "selection":         sel,
            "edge_bucket":       bucket,
            "wins":              b["wins"],
            "losses":            b["losses"],
            "pushes":            b["pushes"],
            "total":             decided,
            "win_rate":          round(win_rate, 4),
            "breakeven":         round(bev, 4),
            "edge_vs_breakeven": round(win_rate - bev, 4),
            "net_units":         round(b["profit"], 2),
            "profitable":        win_rate >= bev,
        })

    results.sort(key=lambda x: x["edge_vs_breakeven"], reverse=True)
    return results


def save_calibration(calibration: list[dict],
                     path: Path = CALIBRATION_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(calibration, indent=2))


def load_calibration(path: Path = CALIBRATION_PATH) -> list[dict]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except Exception:
        return []


def insight_text(row: dict) -> str:
    sign = "+" if row["profitable"] else "-"
    return (
        f"{row['market_key']} {row['selection']} ({row['edge_bucket']} edge): "
        f"{row['win_rate']:.1%} actual vs {row['breakeven']:.1%} needed "
        f"({sign}{abs(row['edge_vs_breakeven']):.1%}), "
        f"{row['wins']}-{row['losses']} graded, {row['net_units']:+.2f}u"
    )
```

- [ ] **Step 4: Run tests — verify they pass**

```
pytest tests/test_market_learn.py -v
```

Expected: all 10 tests pass.

- [ ] **Step 5: Add calibration section to backtest.py print_report**

In `backtest.py`, add this function after `_report_by_edge_bucket`:

```python
def _report_calibration(bt_conn: sqlite3.Connection) -> list:
    from market_learn import compute_calibration
    return compute_calibration(bt_conn)
```

In `print_report`, add after the edge bucket section (after the last `for r in ...` loop, before `print()`):

```python
    cal = _report_calibration(bt_conn)
    if cal:
        print("\n-- MARKET CALIBRATION (actual vs break-even, min 20 graded) ----")
        print(f"  {'MARKET':<22} {'SEL':<6} {'BUCKET':<9} {'W-L':>7}  {'WIN%':>6}  {'BEV':>6}  {'DIFF':>7}  {'NET':>7}")
        print("  " + "-" * 76)
        for r in cal:
            wl   = f"{r['wins']}-{r['losses']}"
            diff = f"{r['edge_vs_breakeven']:+.1%}"
            flag = "BET " if r["profitable"] else "SKIP"
            print(
                f"  [{flag}] {r['market_key']:<20} {r['selection']:<6} "
                f"{r['edge_bucket']:<9} {wl:>7}  {r['win_rate']:.1%}  "
                f"{r['breakeven']:.1%}  {diff:>7}  {r['net_units']:>+7.2f}"
            )

        from market_learn import save_calibration
        save_calibration(cal)
        print(f"\n  Calibration saved to data/market_calibration.json")
```

- [ ] **Step 6: Add Market Calibration panel to dashboard.py**

In `dashboard.py`, at the end of `_render_learning` (after the cumulative P&L chart block), add:

```python
    from market_learn import load_calibration
    cal = load_calibration()
    if cal:
        st.markdown("---")
        st.subheader("Market Calibration (from backtest)")
        st.caption(
            "Observed win rate vs break-even probability. BET = profitable, SKIP = below break-even. "
            "Min 20 graded picks per row. Refresh by running: python backtest.py --report-only"
        )
        rows = []
        for r in cal:
            rows.append({
                "Signal":  "BET" if r["profitable"] else "SKIP",
                "Market":  r["market_key"],
                "Side":    r["selection"],
                "Edge":    r["edge_bucket"],
                "W-L":     f"{r['wins']}-{r['losses']}",
                "Win%":    f"{r['win_rate']:.1%}",
                "Need":    f"{r['breakeven']:.1%}",
                "Diff":    f"{r['edge_vs_breakeven']:+.1%}",
                "Net":     f"{r['net_units']:+.2f}u",
            })
        df = pd.DataFrame(rows)

        def _hl(row):
            c = "background-color: #1a3a1a" if row["Signal"] == "BET" else "background-color: #3a1a1a"
            return [c] * len(row)

        st.dataframe(df.style.apply(_hl, axis=1), use_container_width=True, hide_index=True)
```

- [ ] **Step 7: Run the full test suite**

```
pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```
git add market_learn.py backtest.py dashboard.py tests/test_market_learn.py
git commit -m "feat: market calibration learning system — tracks observed vs expected win rates per market"
```

---

## After implementation: re-run the backtest with all markets

Once all 3 tasks are complete, reset and rerun to get fresh data for all 12 markets:

```
python backtest.py --reset --days 14
```

This will:
1. Delete the existing `data/backtest.db`
2. Re-fetch 14 days of historical odds with ALL_PROP_MARKETS (same API cost — 1 request per event regardless of market count)
3. Grade all picks using the expanded grade.py
4. Print the report with the new Calibration section
5. Save `data/market_calibration.json` for the dashboard

Then view results:
```
python backtest.py --report-only
```

And launch the dashboard:
```
streamlit run dashboard.py
```

The "Results & Learning" tab will now show the Market Calibration panel with BET/SKIP signals per market.

---

## Self-review

**Spec coverage check:**
- Test every betting stat: Task 1 adds 7 new markets + fixes 2 missing; Task 2 threads them through the fetch pipeline ✓
- Find most profitable: calibration table in backtest report and dashboard ✓
- Learn from misses: market_learn.py computes observed vs expected per bucket ✓
- Track and build: save_calibration persists to JSON, loads into dashboard each time ✓
- --reset flag: Task 2 Step 6 ✓

**Placeholder scan:** No TBD, no "handle edge cases", no "similar to above." All code is complete.

**Type consistency:** `compute_calibration` returns `list[dict]`, consumed by `save_calibration(list[dict])` and `_report_calibration(bt_conn) -> list` — consistent. `load_calibration() -> list[dict]` used in dashboard — consistent.
