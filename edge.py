from consensus import american_to_decimal
from config import (
    EDGE_RECOMMENDED, EDGE_MIN_BET, BET_WHITELIST,
    BET_PRICE_MIN, BET_PRICE_MAX,
    MARKET_EDGE_MIN, MARKET_EXCLUDE_PLUS_ODDS,
    SCORE_RECOMMENDED, SCORE_LEAN,
)


def bovada_break_even(price: int) -> float:
    """Raw implied probability from Bovada price. Not vig-removed."""
    return 1.0 / american_to_decimal(price)


def compute_edge(consensus_fair_prob: float, break_even_prob: float) -> float:
    return consensus_fair_prob - break_even_prob


def compute_ev(bovada_price: int, consensus_fair_prob: float) -> float:
    decimal_odds = american_to_decimal(bovada_price)
    return consensus_fair_prob * decimal_odds - 1.0


def classify(edge: float, ev: float, *, market_key: str = "", selection: str = "", price: int = 0) -> str:
    """Legacy edge-only classifier. Kept for backtest replay compatibility."""
    mkt = (market_key, selection)
    if mkt not in BET_WHITELIST:
        return "NO_BET"
    if not (BET_PRICE_MIN <= price <= BET_PRICE_MAX):
        return "NO_BET"
    if edge < MARKET_EDGE_MIN.get(mkt, 0.0):
        return "NO_BET"
    if edge >= EDGE_RECOMMENDED:
        return "RECOMMENDED"
    if edge >= EDGE_MIN_BET:
        return "LEAN"
    return "NO_BET"


def classify_by_score(score: int, edge: float, market_key: str, selection: str,
                      price: int | None = None) -> str:
    """
    Score-based classifier (new system).
    Hard gates: whitelist, per-market min edge, price exclusions, then score tier.
    """
    mkt = (market_key, selection)
    if mkt not in BET_WHITELIST:
        return "NO_BET"
    if edge <= 0.0:
        return "NO_BET"
    if edge < MARKET_EDGE_MIN.get(mkt, 0.0):
        return "NO_BET"
    if price is not None and price >= 100 and mkt in MARKET_EXCLUDE_PLUS_ODDS:
        return "NO_BET"
    if score >= SCORE_RECOMMENDED:
        return "RECOMMENDED"
    if score >= SCORE_LEAN:
        return "LEAN"
    return "NO_BET"
