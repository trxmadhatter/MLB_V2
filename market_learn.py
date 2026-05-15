"""
Market calibration: tracks observed win rates vs break-even by
(market_key, selection, edge_bucket). Persists to data/market_calibration.json.
"""
import json
import sqlite3
from pathlib import Path

CALIBRATION_PATH = Path(__file__).parent / "data" / "market_calibration.json"
MIN_SAMPLE = 20


def _edge_bucket(edge: float) -> str:
    if edge >= 0.06: return "6%+"
    if edge >= 0.04: return "4-6%"
    if edge >= 0.02: return "2-4%"
    return "<2%"


def _breakeven(price: int) -> float:
    if price > 0:
        return 100.0 / (price + 100)
    return abs(price) / (abs(price) + 100)


def compute_calibration(bt_conn: sqlite3.Connection) -> list[dict]:
    """
    Returns calibration stats per (market_key, selection, edge_bucket),
    sorted best-to-worst by (observed win_rate - breakeven).
    Only includes buckets with >= MIN_SAMPLE decided (WIN or LOSS) picks.
    """
    rows = bt_conn.execute("""
        SELECT market_key, selection, edge, bovada_price, result, profit_units
        FROM backtest_picks
        WHERE result IN ('WIN', 'LOSS', 'PUSH')
    """).fetchall()

    buckets: dict[tuple, dict] = {}
    for r in rows:
        key = (r["market_key"], r["selection"], _edge_bucket(r["edge"]))
        if key not in buckets:
            buckets[key] = {"wins": 0, "losses": 0, "pushes": 0,
                            "prices": [], "profit": 0.0}
        b = buckets[key]
        if r["result"] == "WIN":    b["wins"]   += 1
        elif r["result"] == "LOSS": b["losses"] += 1
        else:                       b["pushes"] += 1
        b["prices"].append(r["bovada_price"])
        b["profit"] += r["profit_units"] or 0.0

    results = []
    for (mkt, sel, bucket), b in buckets.items():
        decided = b["wins"] + b["losses"]
        if decided < MIN_SAMPLE:
            continue
        win_rate  = b["wins"] / decided
        avg_price = sum(b["prices"]) / len(b["prices"])
        bev       = _breakeven(int(round(avg_price)))
        results.append({
            "market_key":        mkt,
            "selection":         sel,
            "edge_bucket":       bucket,
            "wins":              b["wins"],
            "losses":            b["losses"],
            "pushes":            b["pushes"],
            "total":             decided,
            "win_rate":          round(win_rate, 4),
            "breakeven":         round(bev, 4),
            "edge_vs_breakeven": round(win_rate - bev, 4),
            "net_units":         round(b["profit"], 2),
            "profitable":        win_rate >= bev,
        })

    results.sort(key=lambda x: x["edge_vs_breakeven"], reverse=True)
    return results


def save_calibration(calibration: list[dict],
                     path: Path = CALIBRATION_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(calibration, indent=2))


def load_calibration(path: Path = CALIBRATION_PATH) -> list[dict]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except Exception:
        return []


def insight_text(row: dict) -> str:
    sign = "+" if row["profitable"] else "-"
    return (
        f"{row['market_key']} {row['selection']} ({row['edge_bucket']} edge): "
        f"{row['win_rate']:.1%} actual vs {row['breakeven']:.1%} needed "
        f"({sign}{abs(row['edge_vs_breakeven']):.1%}), "
        f"{row['wins']}-{row['losses']} graded, {row['net_units']:+.2f}u"
    )
