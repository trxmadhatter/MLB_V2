from consensus import american_to_decimal
from config import EDGE_RECOMMENDED, EDGE_LEAN


def bovada_break_even(price: int) -> float:
    """Raw implied probability from Bovada price. Not vig-removed."""
    return 1.0 / american_to_decimal(price)


def compute_edge(consensus_fair_prob: float, break_even_prob: float) -> float:
    return consensus_fair_prob - break_even_prob


def compute_ev(bovada_price: int, consensus_fair_prob: float) -> float:
    decimal_odds = american_to_decimal(bovada_price)
    return consensus_fair_prob * decimal_odds - 1.0


def classify(edge: float, ev: float) -> str:
    if ev <= 0:
        return "NO_BET"
    if edge >= EDGE_RECOMMENDED:
        return "RECOMMENDED"
    if edge >= EDGE_LEAN:
        return "LEAN"
    return "NO_BET"
