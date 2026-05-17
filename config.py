from pathlib import Path

ROOT = Path(__file__).parent

# The Odds API
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
SPORT = "baseball_mlb"
REGIONS = "us"
ODDS_FORMAT = "american"

# V1 player prop markets only
V1_MARKETS = [
    "pitcher_strikeouts",
    "pitcher_hits_allowed",
    "pitcher_earned_runs",
    "batter_hits",
    "batter_total_bases",
    "totals",
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
]

# Bovada is the target book — isolated from consensus
BOVADA_KEYS: set[str] = {"bovada"}

# Minimum valid non-Bovada books required at exact same line
MIN_CONSENSUS_BOOKS = 3

# Edge thresholds
EDGE_RECOMMENDED = 0.04   # >= 4%
EDGE_LEAN = 0.02          # >= 2%, < 4%
EDGE_MIN_BET = 0.01       # >= 1% required for whitelist markets

# Winning market/direction combinations — calibration filter handles bad edge buckets
BET_WHITELIST: set[tuple[str, str]] = {
    ("pitcher_outs",         "Over"),
    ("batter_total_bases",   "Under"),
    ("pitcher_hits_allowed", "Under"),
    ("pitcher_strikeouts",   "Under"),
    ("pitcher_strikeouts",   "Over"),    # <2% and 2-4% profitable; 6%+ blocked by calibration
    ("batter_hits",          "Over"),    # <2% profitable; 4-6% and 6%+ blocked by calibration
    ("batter_hits",          "Under"),   # <2% profitable
    ("totals",               "Over"),
    ("totals",               "Under"),
}

# Per-market minimum edge overrides (applied on top of global EDGE_MIN_BET)
MARKET_EDGE_MIN: dict[tuple[str, str], float] = {
    ("pitcher_strikeouts", "Under"): 0.06,   # 6%+ bucket is 54-37; lowered from 0.08
}

# Markets where +100 or better (underdog) price is unprofitable — exclude those lines
MARKET_EXCLUDE_PLUS_ODDS: set[tuple[str, str]] = {
    ("pitcher_outs", "Over"),   # +100 or better: 38.3% WR, -8.80u in backtest
}

# Price range filter: -151 to +150 (worse than -151 = too much juice; above +150 = suspect line)
BET_PRICE_MIN = -151
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

SCORE_RECOMMENDED = 65   # score >= this -> RECOMMENDED
SCORE_LEAN        = 45   # score >= this -> LEAN (else NO_BET)

# Per-market signal weights. Values are max points each signal can contribute.
# Sum of each dict should equal 100.
SIGNAL_WEIGHTS: dict[str, dict[str, int]] = {
    "pitcher_strikeouts": {
        "whiff_pct":         14,   # Statcast: whiff% -> direct K predictor
        "platoon_alignment": 15,
        "season_k_pct":      12,
        "stuff_plus":        10,   # FanGraphs: Stuff+ -> pitch quality
        "ump_k_tendency":    12,
        "park_k_factor":      8,
        "recent_k_rate":     10,
        "opp_team_k_pct":     8,
        "weather":            6,
        "edge":               5,
    },
    "pitcher_hits_allowed": {
        "recent_h9":         17,
        "opp_team_avg":      15,
        "hard_hit_pct":      12,   # Statcast: hard hit% allowed
        "barrel_pct":        10,   # Statcast: barrel% allowed
        "park_hits_factor":  13,
        "season_whip":       11,
        "platoon_alignment": 10,
        "weather":            7,
        "edge":               5,
    },
    "pitcher_outs": {
        "recent_ip":         20,
        "xfip":              12,   # FanGraphs: xFIP -> true pitching skill
        "opp_lineup_ops":    16,
        "season_ip":         14,
        "swstr_pct":         10,   # FanGraphs: SwStr% -> efficiency
        "park_run_factor":   12,
        "weather":            8,
        "edge":               8,
    },
    "batter_total_bases": {
        "xwoba":             13,   # Statcast: xwOBA -> contact quality
        "barrel_pct":        12,   # Statcast: barrel% -> extra-base power
        "sp_quality":        14,
        "platoon_alignment": 12,
        "hard_hit_pct":       8,   # Statcast: hard hit%
        "recent_tb":         10,
        "park_tb_factor":    10,
        "season_slg":         8,
        "weather_wind":       7,
        "edge":               6,
    },
    "batter_hits": {
        "xwoba":             14,   # Statcast: xwOBA -> contact quality
        "hard_hit_pct":      16,   # Statcast: hard hit% -> hits predictor
        "sp_quality":        16,
        "platoon_alignment": 12,
        "recent_h":          10,
        "park_hits_factor":  10,
        "season_avg":         9,
        "weather":            7,
        "edge":               6,
    },
}

# Default weights used when market has no specific entry
SIGNAL_WEIGHTS_DEFAULT: dict[str, int] = {
    "recent_form":  35,
    "park_factor":  25,
    "weather":      20,
    "edge":         20,
}
