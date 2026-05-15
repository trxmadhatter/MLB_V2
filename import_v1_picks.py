"""
Import and grade NBA V1 MLB picks into the MLB_V2 backtest database.

Reads data/mlb/history/graded_picks_mlb.csv from NBA V1, maps stat names
to our market_key format, grades via MLB Stats API, stores in backtest.db.
"""
import sqlite3
import csv
import sys
from pathlib import Path
from collections import defaultdict

ROOT    = Path(__file__).parent
V1_DIR  = Path(r"C:\Users\jesse\NBA V1")
V1_CSV  = V1_DIR / "data/mlb/history/graded_picks_mlb.csv"

sys.path.insert(0, str(ROOT))
from backtest import _get_bt_conn, init_backtest_db
from grade import get_game_results, grade_outcome, calc_profit, normalize_name
from edge import classify, compute_edge, bovada_break_even
from consensus import vig_remove_pair

STAT_MAP = {
    "k":          "pitcher_strikeouts",
    "tb":         "batter_total_bases",
    "hits":       "batter_hits",
    "outs":       "pitcher_outs",
    "h_allowed":  "pitcher_hits_allowed",
    "er":         "pitcher_earned_runs",
    "runs":       "batter_runs_scored",
    "rbi":        "batter_rbis",
    "bb_allowed": "pitcher_walks",
    "sb":         "batter_stolen_bases",
    "hrb":        None,  # combo stat, skip
}


def _vig_remove(over_price: float, under_price: float) -> tuple[float, float]:
    return vig_remove_pair(int(over_price), int(under_price))


def load_v1_picks() -> list[dict]:
    with open(V1_CSV, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def convert_row(row: dict) -> dict | None:
    """Convert a V1 row to our backtest_picks format. Returns None if unusable."""
    market_key = STAT_MAP.get(row["stat"])
    if not market_key:
        return None

    selection = row["side"].capitalize()
    if selection not in ("Over", "Under"):
        return None

    try:
        bov_over  = float(row["bovada_over"])
        bov_under = float(row["bovada_under"])
    except (ValueError, TypeError):
        return None

    bov_price = int(bov_over if selection == "Over" else bov_under)

    try:
        point = float(row["line"])
    except (ValueError, TypeError):
        return None

    try:
        book_count = int(float(row["book_count"])) if row["book_count"] else 0
    except (ValueError, TypeError):
        book_count = 0

    # Vig-remove Bovada pair to get fair probs
    try:
        fair_over, fair_under = _vig_remove(bov_over, bov_under)
    except Exception:
        return None

    bov_fair = fair_over if selection == "Over" else fair_under

    # Use V1's fair_prob as consensus_fair_prob
    try:
        consensus_fair_prob = float(row["fair_prob"])
    except (ValueError, TypeError):
        return None

    edge = compute_edge(consensus_fair_prob, bov_fair)
    bev  = bovada_break_even(bov_price)

    try:
        ev = consensus_fair_prob * (100 / abs(bov_price) + 1 if bov_price < 0 else bov_price / 100 + 1) - 1
    except Exception:
        ev = 0.0

    rec = classify(edge, ev, market_key=market_key, selection=selection, price=bov_price)

    return {
        "pick_date":              row["game_date"],
        "player_name":            row["player_name"],
        "market_key":             market_key,
        "selection":              selection,
        "point":                  point,
        "bovada_price":           bov_price,
        "bovada_fair_prob":       round(bov_fair, 6),
        "consensus_fair_prob":    round(consensus_fair_prob, 6),
        "consensus_book_count":   book_count,
        "edge":                   round(edge, 6),
        "ev":                     round(ev, 6),
        "recommendation":         rec,
        "result":                 "PENDING",
        "actual_stat":            None,
        "profit_units":           None,
        "source":                 "v1_import",
    }


def grade_picks(picks: list[dict]) -> list[dict]:
    by_date = defaultdict(list)
    for p in picks:
        by_date[p["pick_date"]].append(p)

    for date, day_picks in sorted(by_date.items()):
        print(f"  Grading {date}: {len(day_picks)} picks...", end=" ")
        try:
            results = get_game_results(date)
            index = {
                (normalize_name(r["player_name"]), r["market_key"]): r["stat_value"]
                for r in results
            }
            graded = 0
            for p in day_picks:
                key    = (normalize_name(p["player_name"]), p["market_key"])
                actual = index.get(key)
                if actual is not None:
                    p["result"]       = grade_outcome(p["selection"], p["point"], actual)
                    p["actual_stat"]  = actual
                    p["profit_units"] = calc_profit(p["result"], p["bovada_price"])
                    graded += 1
            print(f"{graded}/{len(day_picks)} graded")
        except Exception as e:
            print(f"ERROR: {e}")

    return picks


def store_picks(conn: sqlite3.Connection, picks: list[dict]) -> int:
    stored = 0
    for p in picks:
        try:
            conn.execute("""
                INSERT OR IGNORE INTO backtest_picks
                  (pick_date, player_name, market_key, selection, point,
                   bovada_price, bovada_fair_prob, consensus_fair_prob,
                   consensus_book_count, edge, ev, recommendation,
                   result, actual_stat, profit_units)
                VALUES
                  (:pick_date, :player_name, :market_key, :selection, :point,
                   :bovada_price, :bovada_fair_prob, :consensus_fair_prob,
                   :consensus_book_count, :edge, :ev, :recommendation,
                   :result, :actual_stat, :profit_units)
            """, p)
            stored += conn.execute("SELECT changes()").fetchone()[0]
        except Exception as e:
            print(f"  SKIP {p['player_name']} {p['market_key']}: {e}")
    conn.commit()
    return stored


def main():
    print("Loading V1 picks...")
    raw = load_v1_picks()
    print(f"  {len(raw)} raw rows")

    print("Converting...")
    picks = [c for r in raw if (c := convert_row(r)) is not None]
    print(f"  {len(picks)} convertible picks")

    print("Grading via MLB Stats API...")
    picks = grade_picks(picks)

    graded = sum(1 for p in picks if p["result"] != "PENDING")
    print(f"  {graded}/{len(picks)} graded")

    print("Storing in backtest.db...")
    conn = _get_bt_conn()
    init_backtest_db(conn)
    stored = store_picks(conn, picks)
    print(f"  {stored} new rows inserted (duplicates skipped)")
    conn.close()

    print("\nDone. Re-run backtest report to see expanded results:")
    print("  python backtest.py --report")


if __name__ == "__main__":
    main()
