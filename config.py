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

# Max recommended picks emitted per day
MAX_RECOMMENDED_PICKS = 5

# Stale data thresholds (minutes)
SNAPSHOT_STALE_MINUTES = 60
BOVADA_STALE_MINUTES = 30

# Paths
DB_PATH = ROOT / "data" / "mlb_v2.db"
PICKS_DIR = ROOT / "data" / "picks"
