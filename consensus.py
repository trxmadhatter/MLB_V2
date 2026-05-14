from collections import defaultdict


def american_to_decimal(price: int) -> float:
    if price > 0:
        return price / 100.0 + 1.0
    return 100.0 / abs(price) + 1.0


def american_to_implied(price: int) -> float:
    return 1.0 / american_to_decimal(price)


def vig_remove_pair(over_price: int, under_price: int) -> tuple[float, float]:
    """Multiplicative vig removal. Returns (no_vig_over_prob, no_vig_under_prob)."""
    over_imp  = american_to_implied(over_price)
    under_imp = american_to_implied(under_price)
    total     = over_imp + under_imp
    return over_imp / total, under_imp / total


def compute_consensus(
    rows: list[dict],
    min_books: int = 3,
    bovada_keys: set[str] | None = None,
) -> dict:
    """
    rows: each dict has keys bookmaker_key, selection ('Over'|'Under'), point, price.
    All rows must share the same event_id, player_name, market_key, and point.

    Returns one of:
      {'ok': True,  'fair_prob_over': float, 'fair_prob_under': float, 'book_count': int}
      {'ok': False, 'reason': str}
    """
    if bovada_keys is None:
        bovada_keys = {"bovada"}

    book_sides: dict[str, dict[str, int]] = defaultdict(dict)
    for row in rows:
        if row["bookmaker_key"] in bovada_keys:
            continue
        book_sides[row["bookmaker_key"]][row["selection"]] = row["price"]

    valid: dict[str, dict[str, int]] = {
        k: v for k, v in book_sides.items()
        if "Over" in v and "Under" in v
    }

    if len(valid) < min_books:
        return {"ok": False, "reason": "insufficient_consensus_books"}

    no_vig_overs = [
        vig_remove_pair(sides["Over"], sides["Under"])[0]
        for sides in valid.values()
    ]

    fair_prob_over  = sum(no_vig_overs) / len(no_vig_overs)
    fair_prob_under = 1.0 - fair_prob_over

    return {
        "ok":              True,
        "fair_prob_over":  fair_prob_over,
        "fair_prob_under": fair_prob_under,
        "book_count":      len(valid),
    }
