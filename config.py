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

# Bovada is the target book — isolated from consensus
BOVADA_KEYS: set[str] = {"bovada"}

# Minimum valid non-Bovada books required at exact same line
MIN_CONSENSUS_BOOKS = 3

# Edge thresholds
EDGE_RECOMMENDED = 0.04   # >= 4%
EDGE_LEAN = 0.02          # >= 2%, < 4%
EDGE_MIN_BET = 0.01       # >= 1% required for whitelist markets

# Winning market/direction combinations identified from backtest analysis
BET_WHITELIST: set[tuple[str, str]] = {
    ("pitcher_outs",         "Over"),
    ("batter_total_bases",   "Under"),
    ("pitcher_hits_allowed", "Under"),
    ("pitcher_strikeouts",   "Under"),   # profitable only at >=8% edge per backtest
}

# Per-market minimum edge overrides (applied on top of global EDGE_MIN_BET)
MARKET_EDGE_MIN: dict[tuple[str, str], float] = {
    ("pitcher_strikeouts", "Under"): 0.08,
}

# Markets where +100 or better (underdog) price is unprofitable — exclude those lines
MARKET_EXCLUDE_PLUS_ODDS: set[tuple[str, str]] = {
    ("pitcher_outs", "Over"),   # +100 or better: 38.3% WR, -8.80u in backtest
}

# Price range filter: negative-odds favorites only (-145 to -101)
BET_PRICE_MIN = -145
BET_PRICE_MAX = -101

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
