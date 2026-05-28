from consensus import american_to_decimal
from config import (
    EDGE_RECOMMENDED, EDGE_MIN_BET, BET_WHITELIST,
    BET_PRICE_MIN, BET_PRICE_MAX,
    MARKET_EDGE_MIN, MARKET_EXCLUDE_PLUS_ODDS,
    SCORE_RECOMMENDED, SCORE_LEAN, SCORE_WATCH,
)
from market_learn import load_calibration, _edge_bucket

# Loaded once at import time; call _reload_cal() in tests or after backtest runs
_CAL_SKIP: set[tuple] = set()


def _reload_cal() -> None:
    global _CAL_SKIP
    _CAL_SKIP = {
        (r["market_key"], r["selection"], r["edge_bucket"])
        for r in load_calibration()
        if not r["profitable"]
    }


_reload_cal()


def bovada_break_even(price: int) -> float:
    """Raw implied probability from Bovada price. Not vig-removed."""
    return 1.0 / american_to_decimal(price)


def compute_edge(consensus_fair_prob: float, break_even_prob: float) -> float:
    return consensus_fair_prob - break_even_prob


def compute_ev(bovada_price: int, consensus_fair_prob: float) -> float:
    decimal_odds = american_to_decimal(bovada_price)
    return consensus_fair_prob * decimal_odds - 1.0


def required_edge_for_price(price: int | None) -> float:
    """Minimum Bovada-vs-consensus edge required before a pick is bettable."""
    if price is None:
        return EDGE_MIN_BET
    if price <= -121:
        return 0.03
    if price <= -100:
        return 0.015
    return EDGE_MIN_BET


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
    Score-based classifier.
    A/B bet tiers require playable Bovada price, Bovada-vs-consensus edge,
    a non-blocked market bucket, and enough baseball context score.
    """
    mkt = (market_key, selection)
    if mkt not in BET_WHITELIST:
        return "PASS"
    if price is not None and not (BET_PRICE_MIN <= price <= BET_PRICE_MAX):
        return "PASS"
    if price is not None and price >= 100 and mkt in MARKET_EXCLUDE_PLUS_ODDS:
        return "PASS"

    min_edge = max(MARKET_EDGE_MIN.get(mkt, 0.0), required_edge_for_price(price))
    bettable_edge = edge >= min_edge
    cal_blocked = (market_key, selection, _edge_bucket(edge)) in _CAL_SKIP

    if bettable_edge and not cal_blocked:
        if score >= SCORE_RECOMMENDED:
            return "A_BET"
        if score >= SCORE_LEAN:
            return "B_BET"

    if score >= SCORE_WATCH or edge >= EDGE_MIN_BET:
        return "WATCH"
    return "PASS"


def is_bet_recommendation(rec: str) -> bool:
    """True for current and legacy actionable recommendation labels."""
    return rec in {"A_BET", "B_BET", "RECOMMENDED", "LEAN"}


def normalize_recommendation(rec: str) -> str:
    """Map old recommendation names to the current dashboard language."""
    return {
        "RECOMMENDED": "A_BET",
        "LEAN": "B_BET",
        "NO_BET": "PASS",
    }.get(rec, rec)
