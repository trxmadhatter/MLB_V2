# MLB_V2 — Project Context

## Stack
- Language: Python
- Data source: The Odds API (all non-Bovada US books for consensus)
- Target book: Bovada (mispricing target only)
- Timezone: America/Los_Angeles

## Env vars
- `ODDS_API_KEY` — The Odds API key

## Locked strategy — do not revisit these
- Target book is Bovada only. BetOnline is a consensus book, never grouped with Bovada.
- Markets: `pitcher_strikeouts`, `batter_hits`, `batter_total_bases`
- Strategy: Bovada vs market consensus mispricing. NOT a predictive model.
- Line matching: strict — event_id + player + market + selection + line must all match exactly.
- Vig removal: multiplicative. Requires a valid two-way market per book.
- Consensus: minimum 3 non-Bovada books at the exact same line.
- Edge thresholds: ≥4% → bet, ≥2% → lean, <2% → no bet.
- Stale data: consensus snapshot >60 min old OR Bovada last_update >30 min before game time → skip.

## Hard constraints
- Never write to or read from `C:\Users\jesse\NBA V1`. That project is separate and must stay untouched.
- Do not copy code from NBA V1.
