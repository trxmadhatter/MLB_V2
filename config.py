from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent


def pt_now() -> datetime:
    """Current datetime in US/Pacific, DST-aware."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Los_Angeles"))
    except ImportError:
        # fallback: approximate — DST runs Mar-Nov so UTC-7, else UTC-8
        month = datetime.now(timezone.utc).month
        offset = 7 if 3 <= month <= 11 else 8
        return datetime.now(timezone.utc) - timedelta(hours=offset)


def pt_date(offset_days: int = 0) -> str:
    """Today's date string in PT, with optional day offset."""
    return (pt_now() + timedelta(days=offset_days)).strftime("%Y-%m-%d")

# The Odds API
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
SPORT = "baseball_mlb"
REGIONS = "us"
ODDS_FORMAT = "american"

# V1 player prop markets only
V1_MARKETS = [
    "pitcher_strikeouts",
    "pitcher_outs",
    "pitcher_earned_runs",
    "batter_hits",
    "batter_total_bases",
    "totals",
    "h2h",
    "spreads",
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
    "totals",
    "h2h",
    "spreads",
]

# Bovada is the target book — isolated from consensus
BOVADA_KEYS: set[str] = {"bovada"}

# Minimum valid non-Bovada books required at exact same line
MIN_CONSENSUS_BOOKS = 3

# Edge thresholds
EDGE_RECOMMENDED = 0.04   # >= 4%
EDGE_LEAN = 0.02          # >= 2%, < 4%
EDGE_MIN_BET = 0.01       # >= 1% required for whitelist markets

# Winning market/direction combinations; calibration filter handles bad edge buckets.
# Removed 2026-05-24: pitcher_strikeouts Over (LEAN 25% WR/12 picks), pitcher_hits_allowed Under (LEAN 18.2%/11 picks)
# Removed 2026-05-26: pitcher_hits_allowed entirely (0W-4L live, dropped from V1_MARKETS; replaced by pitcher_outs)
# pitcher_strikeouts Under retained with 8% minimum; lower bands diluted performance in verification.
BET_WHITELIST: set[tuple[str, str]] = {
    ("pitcher_outs",         "Over"),
    ("batter_total_bases",   "Under"),
    ("pitcher_strikeouts",   "Under"),
    ("batter_hits",          "Over"),    # calibration blocks currently unprofitable buckets
    ("batter_hits",          "Under"),   # calibration blocks currently unprofitable buckets
    ("totals",               "Over"),
    ("totals",               "Under"),
    ("h2h",                  "Home"),
    ("h2h",                  "Away"),
    ("spreads",              "Home"),
    ("spreads",              "Away"),
}

# Per-market minimum edge overrides (applied on top of global EDGE_MIN_BET)
MARKET_EDGE_MIN: dict[tuple[str, str], float] = {
    ("pitcher_strikeouts", "Under"): 0.08,
}

# Markets where +100 or better (underdog) price is unprofitable — exclude those lines
MARKET_EXCLUDE_PLUS_ODDS: set[tuple[str, str]] = {
    ("pitcher_outs", "Over"),   # +100 or better: 38.3% WR, -8.80u in backtest
}

# Price range filter: -140 to +150 (worse than -140 = too much juice; above +150 = suspect line)
BET_PRICE_MIN = -140
BET_PRICE_MAX = 150

# Max recommended picks emitted per day
MAX_RECOMMENDED_PICKS = 5

# Stale data thresholds (minutes)
SNAPSHOT_STALE_MINUTES = 60
BOVADA_STALE_MINUTES = 30

# Paths
DB_PATH = ROOT / "data" / "mlb_v2.db"
PICKS_DIR = ROOT / "data" / "picks"

# ── Signal scoring ────────────────────────────────────────────────────────────

SCORE_RECOMMENDED = 65   # score >= this -> A_BET
SCORE_LEAN        = 55   # score >= this -> B_BET, 45+ can remain WATCH
SCORE_WATCH       = 45

# Per-market signal weights. Values are max points each signal can contribute.
# Sum of each dict should equal 100.
# Weights tuned 2026-05-24 via logistic regression on graded live picks.
# BTB Under: AUC=0.483 (signals near-random vs structural baseline) — conservative adjustments only.
#   hard_hit_pct and edge boosted (positive coefs); xwoba/park_tb_factor/season_slg trimmed (negative coefs).
# K Under: AUC=0.533 — whiff_pct/ump_k_tendency/season_k_pct are real predictors;
#   edge and weather have negative coefs (high edge on K Under = Bovada knows something); platoon_alignment neutral.
SIGNAL_WEIGHTS: dict[str, dict[str, int]] = {
    "pitcher_strikeouts": {
        "whiff_pct":         23,   # Statcast: whiff% — strongest K predictor (coef +0.214)
        "ump_k_tendency":    20,   # ump K tendency — strong predictor (coef +0.193)
        "season_k_pct":      18,   # season K% — strong predictor (coef +0.171)
        "park_k_factor":     10,   # slightly positive (coef +0.038)
        "platoon_alignment":  9,   # near-zero coef (-0.026) at n=195 — not enough to cut hard
        "stuff_plus":         7,   # FanGraphs: Stuff+ — neutral (coef 0.000)
        "recent_k_rate":      7,   # near-zero coef (-0.008) at n=195 — modest trim only
        "opp_team_k_pct":     1,   # slightly negative (coef -0.002); trimmed to fund velo_quality
        "edge":               0,   # harmful coef (-0.367); zeroed to fund velo_quality
        "weather":            0,   # harmful (coef -0.261); removed entirely
        "velo_quality":       5,   # season avg fastball speed vs 93 mph baseline
    },
    "pitcher_hits_allowed": {
        "recent_h9":         17,
        "opp_team_avg":      15,
        "hard_hit_pct":      12,   # Statcast: hard hit% allowed
        "barrel_pct":        10,   # Statcast: barrel% allowed
        "park_hits_factor":  13,
        "season_whip":       11,
        "platoon_alignment": 10,
        "rest_days":          6,   # days since last start; fresh pitcher → fewer hits
        "weather":            4,
        "edge":               2,
    },
    "pitcher_outs": {
        "recent_ip":         20,
        "xfip":              12,   # FanGraphs xFIP (falls back to computed FIP)
        "opp_lineup_ops":    14,   # trimmed to fund game_total
        "season_ip":         14,
        "swstr_pct":         10,   # FanGraphs SwStr% (falls back to Statcast whiff_pct)
        "park_run_factor":   12,
        "rest_days":          8,   # days since last start; fresh pitcher → more outs
        "weather":            0,   # trimmed; minimal value after park/total context
        "edge":               0,   # trimmed; minimal value in outs market
        "velo_quality":       5,   # season avg fastball speed vs 93 mph baseline
        "game_total":         5,   # implied game O/U; high total = run-heavy = fewer outs
    },
    "batter_total_bases": {
        "sp_quality":        14,   # neutral (coef +0.061) — kept, theoretically sound
        "xwoba":             11,   # slightly negative (coef -0.033) — trimmed from 13, kept (Statcast)
        "barrel_pct":        12,   # Statcast: barrel% — slightly positive (coef +0.054)
        "platoon_alignment": 11,   # neutral (coef 0.000)
        "hard_hit_pct":      11,   # Statcast: hard hit% — top positive signal (coef +0.119)
        "recent_tb":          6,   # near-zero (coef +0.002); trimmed to fund batting_order
        "edge":               5,   # slightly positive + confirmed by bucket analysis
        "park_tb_factor":     8,   # slightly negative (coef -0.046) — trimmed from 10
        "weather_wind":       5,   # slightly positive (coef +0.034)
        "season_slg":         6,   # coef -0.002 ≈ zero; trimmed to fund batting_order
        "h2h":                6,   # career H2H avg vs this pitcher (min 5 AB)
        "batting_order":      5,   # team-confirmed lineup slot (3-5=power, 7-9=weak)
    },
    "batter_hits": {
        "xwoba":             14,   # Statcast: xwOBA -> contact quality
        "hard_hit_pct":      16,   # Statcast: hard hit% -> hits predictor
        "sp_quality":        16,
        "platoon_alignment": 12,
        "recent_h":           7,   # trimmed to fund batting_order
        "park_hits_factor":  10,
        "season_avg":         7,   # trimmed to fund batting_order
        "weather":            4,   # trimmed to fund h2h signal
        "edge":               3,   # trimmed to fund h2h signal
        "h2h":                6,   # career H2H avg vs this pitcher (min 5 AB)
        "batting_order":      5,   # team-confirmed lineup slot (3-5=power, 7-9=weak)
    },
}

# Default weights used when market has no specific entry
SIGNAL_WEIGHTS_DEFAULT: dict[str, int] = {
    "recent_form":  35,
    "park_factor":  25,
    "weather":      20,
    "edge":         20,
}
