# Calibration Auto-Ban — Design Spec
**Date:** 2026-05-28  
**Status:** Approved

## Problem

`market_calibration.json` is computed nightly and already identifies which `(market_key, selection, edge_bucket)` combos are profitable vs unprofitable. But this data is never fed back into the pipeline — picks in losing buckets still get recommended as bets.

## Goal

Suppress bet recommendations for buckets with a proven losing record. Unsuppress them automatically when the record recovers. No manual intervention required.

## Scope

- Applies only to picks that crossed the bet threshold (`A_BET`, `B_BET`, `RECOMMENDED`, `LEAN`)
- Does NOT apply to `WATCH` picks
- Granularity: `(market_key, selection, edge_bucket)` — same as existing calibration
- Minimum sample: 20 graded picks before a bucket can trigger a ban (existing `MIN_SAMPLE`)

## Design

### Data flow

```
nightly grade → compute_live_calibration() → market_calibration.json
                                                      ↓
10am run → _analyze() loads calibration → classify_by_score() → auto-ban check → upsert_pick()
```

### Auto-ban check (added to `_analyze()` in `run_daily.py`)

1. Load `market_calibration.json` once at the top of `_analyze()`
2. Build lookup: `{(market_key, selection, edge_bucket): cal_entry}`
3. After `classify_by_score()` returns a bet recommendation:
   ```
   if is_bet_recommendation(rec):
       bucket = _edge_bucket(edge)
       entry = cal_lookup.get((market_key, selection, bucket))
       if entry and not entry["profitable"] and entry["total"] >= MIN_SAMPLE:
           rec = "NO_BET"
           banned_count += 1
   ```
4. Print at end of analysis: `Calibration-banned: N picks`

### Self-correcting behaviour

- Calibration rebuilds every night from all graded picks
- If a banned bucket's win rate recovers above break-even → `profitable` flips to `true` → picks flow through again automatically
- No manual intervention, no static ban list

### Storage

Banned picks are stored in `daily_picks` with `recommendation = "NO_BET"` — same as any other no-bet pick. Fully queryable, visible in the dashboard with "Show all evaluated lines" checked. No schema changes needed.

## Files changed

| File | Change |
|------|--------|
| `market_learn.py` | Make `_edge_bucket()` public (`edge_bucket()`) so `run_daily.py` can import it |
| `run_daily.py` | Load calibration in `_analyze()`, add auto-ban check after `classify_by_score()`, print suppression count |

## Files NOT changed

`edge.py`, `db.py`, `consensus.py`, `scorer.py`, `simulate.py`, `dashboard.py`, `send_picks_email.py`

## Edge cases

- **No calibration data yet** (empty file or bucket not in calibration): pick passes through normally — ban only fires when there is enough evidence
- **Bucket has sample but profitable=true**: pick passes through normally
- **Refresh mode (`--refresh`)**: same check applies — a banned pick won't get promoted from WATCH to bet tier if its bucket is banned
