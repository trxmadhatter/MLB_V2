"""
Bootstrap Monte Carlo simulation for MLB prop picks.

For each pick, samples 100 outcomes from the player's recent game log
(with replacement) and computes P(selection wins) against the line.
Uses the same cached game log data already fetched by the scorer.
"""
import random
from stats import (
    find_player_info,
    fetch_batter_game_values,
    fetch_pitcher_game_values,
)

# Maps market_key -> (stat_group, stat_key_for_game_values)
MARKET_TO_STAT: dict[str, tuple[str, str]] = {
    "batter_total_bases":   ("hitting",  "totalBases"),
    "batter_hits":          ("hitting",  "hits"),
    "pitcher_strikeouts":   ("pitching", "strikeOuts"),
    "pitcher_hits_allowed": ("pitching", "hits"),
    "pitcher_outs":         ("pitching", "outs"),   # IP -> outs conversion handled in stats.py
}

# Minimum recent games needed to run a meaningful simulation
MIN_GAMES = 5


def simulate_pick(
    player_name: str,
    market_key: str,
    selection: str,
    point: float,
    season: int,
    n_sim: int = 1000,
) -> dict | None:
    """
    Bootstrap simulate n_sim game outcomes for this prop.

    Returns {sim_prob, n_games, mean} or None when simulation is not possible
    (unknown player, unsupported market, or insufficient game history).

    sim_prob: estimated P(selection wins) based on recent game results.
    """
    if market_key not in MARKET_TO_STAT:
        return None

    info = find_player_info(player_name, season)
    if not info:
        return None

    group, stat_key = MARKET_TO_STAT[market_key]
    player_id = info["id"]

    values = (
        fetch_batter_game_values(player_id, season, stat_key)
        if group == "hitting"
        else fetch_pitcher_game_values(player_id, season, stat_key)
    )

    if len(values) < MIN_GAMES:
        return None

    is_under = selection == "Under"
    wins = sum(
        1 for _ in range(n_sim)
        if (random.choice(values) < point) == is_under
    )
    return {
        "sim_prob": round(wins / n_sim, 3),
        "n_games":  len(values),
        "mean":     round(sum(values) / len(values), 2),
    }
