#!/usr/bin/env python3
"""
MLB V2 — daily pipeline.
Run once per day before first pitch (recommended: 9 AM PT).

Usage:
    python run_daily.py
"""
import csv
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from config import PICKS_DIR, BOVADA_KEYS, MIN_CONSENSUS_BOOKS
from db import get_conn, init_db, upsert_pick, log_no_bet, get_snapshots
from pull_props import pull_and_store
from consensus import compute_consensus
from edge import bovada_break_even, compute_edge, compute_ev, classify
from grade import grade_pending_picks


def _pt_date(offset_days: int = 0) -> str:
    """Return date in America/Los_Angeles (approximated as UTC-7)."""
    pt = datetime.now(timezone.utc) - timedelta(hours=7) + timedelta(days=offset_days)
    return pt.strftime("%Y-%m-%d")


def _analyze(conn, pulled_at: str, today: str) -> tuple[int, int]:
    """
    Compute consensus + edge for all Bovada lines in this snapshot.
    Returns (picks_evaluated, no_bets_logged).
    """
    rows = [dict(r) for r in get_snapshots(conn, pulled_at)]

    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        key = (row["event_id"], row["market_key"], row["player_name"], row["point"])
        groups[key].append(row)

    picks_evaluated = 0
    no_bets_logged  = 0

    for (event_id, market_key, player_name, point), group_rows in groups.items():
        bovada_rows = [r for r in group_rows if r["bookmaker_key"] in BOVADA_KEYS]
        if not bovada_rows:
            continue

        meta = bovada_rows[0]
        base = {
            "pick_date":     today,
            "pulled_at":     pulled_at,
            "event_id":      event_id,
            "commence_time": meta["commence_time"],
            "home_team":     meta["home_team"],
            "away_team":     meta["away_team"],
            "player_name":   player_name,
            "market_key":    market_key,
            "point":         point,
        }
        no_bet_base = {
            "logged_at":   pulled_at,
            "pick_date":   today,
            "event_id":    event_id,
            "player_name": player_name,
            "market_key":  market_key,
            "point":       point,
        }

        for selection in ("Over", "Under"):
            bov = next((r for r in bovada_rows if r["selection"] == selection), None)
            if bov is None:
                log_no_bet(conn, {**no_bet_base, "selection": selection,
                                  "reason": "missing_bovada_line"})
                no_bets_logged += 1
                continue

            other_side = "Under" if selection == "Over" else "Over"
            bov_other = next(
                (r for r in bovada_rows
                 if r["selection"] == other_side and r["point"] == point),
                None,
            )
            if bov_other is None:
                log_no_bet(conn, {**no_bet_base, "selection": selection,
                                  "reason": "missing_valid_two_way_market"})
                no_bets_logged += 1
                continue

            consensus = compute_consensus(
                group_rows,
                min_books=MIN_CONSENSUS_BOOKS,
                bovada_keys=BOVADA_KEYS,
            )
            if not consensus["ok"]:
                log_no_bet(conn, {**no_bet_base, "selection": selection,
                                  "reason": consensus["reason"]})
                no_bets_logged += 1
                continue

            fair_prob = (
                consensus["fair_prob_over"] if selection == "Over"
                else consensus["fair_prob_under"]
            )
            bev  = bovada_break_even(bov["price"])
            edge = compute_edge(fair_prob, bev)
            ev   = compute_ev(bov["price"], fair_prob)
            rec  = classify(edge, ev)

            upsert_pick(conn, {
                **base,
                "selection":              selection,
                "bovada_price":           bov["price"],
                "bovada_break_even_prob": round(bev,       6),
                "consensus_fair_prob":    round(fair_prob, 6),
                "consensus_book_count":   consensus["book_count"],
                "edge":                   round(edge, 6),
                "ev":                     round(ev,   6),
                "recommendation":         rec,
            })
            picks_evaluated += 1

    return picks_evaluated, no_bets_logged


def _export_csv(conn, pick_date: str) -> Path:
    PICKS_DIR.mkdir(parents=True, exist_ok=True)
    path = PICKS_DIR / f"picks_{pick_date}.csv"
    rows = conn.execute("""
        SELECT pick_date, player_name, market_key, selection, point,
               bovada_price, edge, ev, recommendation,
               consensus_fair_prob, consensus_book_count,
               home_team, away_team, commence_time, result
        FROM daily_picks
        WHERE pick_date = ?
        ORDER BY edge DESC
    """, (pick_date,)).fetchall()
    if rows:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows([dict(r) for r in rows])
    return path


def _print_summary(conn, pick_date: str) -> None:
    counts = conn.execute("""
        SELECT recommendation, COUNT(*) AS cnt
        FROM daily_picks WHERE pick_date = ?
        GROUP BY recommendation ORDER BY cnt DESC
    """, (pick_date,)).fetchall()
    for row in counts:
        print(f"  {row['recommendation']}: {row['cnt']}")

    top = conn.execute("""
        SELECT player_name, market_key, selection, point,
               bovada_price, edge, ev, recommendation
        FROM daily_picks
        WHERE pick_date = ? AND recommendation IN ('RECOMMENDED', 'LEAN')
        ORDER BY edge DESC LIMIT 5
    """, (pick_date,)).fetchall()
    if top:
        print("\n  Top picks:")
        for p in top:
            tag = "*" if p["recommendation"] == "RECOMMENDED" else "·"
            print(
                f"  {tag} {p['player_name']} | {p['market_key']} "
                f"{p['selection']} {p['point']} @ {p['bovada_price']:+d} | "
                f"edge={p['edge']:.1%}  ev={p['ev']:.1%}"
            )


def main() -> None:
    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        print("ERROR: ODDS_API_KEY not set in .env")
        sys.exit(1)

    conn  = get_conn()
    init_db(conn)

    today     = _pt_date(0)
    yesterday = _pt_date(-1)
    print(f"\n{'='*50}")
    print(f"MLB V2 Daily Run — {today}")
    print(f"{'='*50}")

    print("\n[1/3] Pulling props from The Odds API...")
    pulled_at, row_count = pull_and_store(api_key, conn)
    print(f"  Stored {row_count} snapshot rows  (pulled_at={pulled_at})")

    print("\n[2/3] Computing consensus and edge...")
    evaluated, no_bets = _analyze(conn, pulled_at, today)
    print(f"  Evaluated: {evaluated}  |  Structural no-bets logged: {no_bets}")

    csv_path = _export_csv(conn, today)
    print(f"  CSV: {csv_path}")

    print(f"\n[3/3] Grading picks for {yesterday}...")
    graded = grade_pending_picks(conn, yesterday)
    print(f"  Graded: {graded} picks")

    print(f"\n{'─'*50}")
    print(f"  Today's picks ({today}):")
    _print_summary(conn, today)
    print()

    conn.close()


if __name__ == "__main__":
    main()
