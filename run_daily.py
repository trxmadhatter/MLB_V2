#!/usr/bin/env python3
"""
MLB V2 — daily pipeline.
Run once per day before first pitch (recommended: 9 AM PT).

Usage:
    python run_daily.py
"""
import csv
import json
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
from consensus import compute_consensus, vig_remove_pair
from edge import bovada_break_even, compute_edge, compute_ev, classify_by_score
from grade import grade_pending_picks
from scorer import score_pick


def _pt_date(offset_days: int = 0) -> str:
    pt = datetime.now(timezone.utc) - timedelta(hours=7) + timedelta(days=offset_days)
    return pt.strftime("%Y-%m-%d")


def _analyze(conn, pulled_at: str, today: str,
             game_data: dict | None = None) -> tuple[int, int]:
    """
    Compute consensus + edge + signal score for all Bovada lines.
    game_data: pre-fetched from lineups.get_game_data_for_date().
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

        bov_over  = next((r for r in bovada_rows if r["selection"] == "Over"),  None)
        bov_under = next((r for r in bovada_rows if r["selection"] == "Under"), None)

        if bov_over is None or bov_under is None or bov_over["point"] != bov_under["point"]:
            for sel in ("Over", "Under"):
                log_no_bet(conn, {**no_bet_base, "selection": sel,
                                  "reason": "missing_valid_two_way_market"})
                no_bets_logged += 1
            continue

        bov_fair_over, bov_fair_under = vig_remove_pair(bov_over["price"], bov_under["price"])

        consensus = compute_consensus(
            group_rows,
            min_books=MIN_CONSENSUS_BOOKS,
            bovada_keys=BOVADA_KEYS,
        )

        for selection in ("Over", "Under"):
            bov = bov_over if selection == "Over" else bov_under
            bov_fair = bov_fair_over if selection == "Over" else bov_fair_under

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
            edge = compute_edge(fair_prob, bov_fair)
            ev   = compute_ev(bov["price"], fair_prob)

            # Score pick with all signals
            sig_score, breakdown = score_pick(
                player_name=player_name,
                market_key=market_key,
                selection=selection,
                point=point,
                home_team=meta["home_team"],
                away_team=meta["away_team"],
                edge=edge,
                game_date=today,
                game_data=game_data,
            )

            rec = classify_by_score(sig_score, edge, market_key, selection,
                                    price=bov["price"])

            upsert_pick(conn, {
                **base,
                "selection":              selection,
                "bovada_price":           bov["price"],
                "bovada_break_even_prob": round(bev,      6),
                "bovada_fair_prob":       round(bov_fair, 6),
                "consensus_fair_prob":    round(fair_prob, 6),
                "consensus_book_count":   consensus["book_count"],
                "edge":                   round(edge, 6),
                "ev":                     round(ev,   6),
                "recommendation":         rec,
                "signal_score":           sig_score,
                "signal_breakdown":       json.dumps(breakdown),
            })
            picks_evaluated += 1

    return picks_evaluated, no_bets_logged


def _export_csv(conn, pick_date: str) -> Path:
    PICKS_DIR.mkdir(parents=True, exist_ok=True)
    path = PICKS_DIR / f"picks_{pick_date}.csv"
    rows = conn.execute("""
        SELECT pick_date, player_name, market_key, selection, point,
               bovada_price, bovada_fair_prob, consensus_fair_prob,
               edge, ev, recommendation, consensus_book_count,
               signal_score, signal_breakdown,
               home_team, away_team, commence_time, result
        FROM daily_picks
        WHERE pick_date = ?
        ORDER BY signal_score DESC
    """, (pick_date,)).fetchall()
    if rows:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows([dict(r) for r in rows])
    return path


def _print_one_sided(conn, pulled_at: str) -> None:
    """Show Bovada lines where only one side was posted (can't vig-remove)."""
    rows = conn.execute("""
        SELECT b.player_name, b.market_key, b.selection, b.point, b.price,
               COUNT(DISTINCT nb.bookmaker_key) AS other_books
        FROM props_snapshots b
        LEFT JOIN props_snapshots nb
            ON  nb.pulled_at     = b.pulled_at
            AND nb.event_id      = b.event_id
            AND nb.market_key    = b.market_key
            AND nb.player_name   = b.player_name
            AND nb.point         = b.point
            AND nb.bookmaker_key != b.bookmaker_key
        WHERE b.pulled_at = ? AND b.bookmaker_key = 'bovada'
        GROUP BY b.event_id, b.market_key, b.player_name, b.point
        HAVING COUNT(DISTINCT b.selection) = 1
        ORDER BY other_books DESC, b.market_key, b.player_name
    """, (pulled_at,)).fetchall()

    if not rows:
        return
    print(f"\n  --- One-sided Bovada lines (no two-way posted) ---")
    print(f"  {'PLAYER':<22} {'MARKET':<22} {'S':<6} {'PT':>4}  {'PRICE':>6}  {'OTHER_BKS':>9}")
    print("  " + "-" * 80)
    for r in rows:
        print(f"  {r['player_name']:<22} {r['market_key']:<22} {r['selection']:<6} {r['point']:>4.1f}  {r['price']:>+6d}  {r['other_books']:>9}")


def _print_summary(conn, pick_date: str, pulled_at: str) -> None:
    counts = conn.execute("""
        SELECT recommendation, COUNT(*) AS cnt
        FROM daily_picks WHERE pick_date = ?
        GROUP BY recommendation ORDER BY cnt DESC
    """, (pick_date,)).fetchall()
    for row in counts:
        print(f"  {row['recommendation']}: {row['cnt']}")

    rows = conn.execute("""
        SELECT player_name, market_key, selection, point,
               bovada_price, edge, recommendation,
               consensus_book_count, signal_score, signal_breakdown
        FROM daily_picks
        WHERE pick_date = ?
        ORDER BY signal_score DESC NULLS LAST LIMIT 25
    """, (pick_date,)).fetchall()
    if rows:
        print(f"\n  {'PLAYER':<22} {'MARKET':<22} {'S':<5} {'PT':>4}  {'PRICE':>6}  {'EDGE':>6}  {'SCORE':>5}  REC")
        print("  " + "-" * 95)
        for p in rows:
            tag = "**" if p["recommendation"] == "RECOMMENDED" else (" >" if p["recommendation"] == "LEAN" else "  ")
            print(
                f"{tag} {p['player_name']:<22} {p['market_key']:<22} {p['selection']:<5} {p['point']:>4.1f}"
                f"  {p['bovada_price']:>+6d}  {p['edge']:>+6.1%}  {p['signal_score'] or 0:>5}  {p['recommendation']}"
            )

    _print_one_sided(conn, pulled_at)


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
    print(f"MLB V2 Daily Run - {today}")
    print(f"{'='*50}")

    # Pre-fetch game data (lineups, SPs, umpires) — one MLB Stats API call
    print("\n[1/4] Pre-fetching game data from MLB Stats API...")
    try:
        from signals.lineups import get_game_data_for_date
        game_data = get_game_data_for_date(today)
        print(f"  {len(game_data)} games found for today")
    except Exception as exc:
        print(f"  WARNING: game data fetch failed ({exc}) — scoring without lineup/umpire data")
        game_data = None

    print("\n[2/4] Pulling props from The Odds API...")
    pulled_at, row_count = pull_and_store(api_key, conn)
    print(f"  Stored {row_count} snapshot rows  (pulled_at={pulled_at})")

    print("\n[3/4] Computing consensus, edge, and signal scores...")
    evaluated, no_bets = _analyze(conn, pulled_at, today, game_data=game_data)
    print(f"  Evaluated: {evaluated}  |  Structural no-bets logged: {no_bets}")

    csv_path = _export_csv(conn, today)
    print(f"  CSV: {csv_path}")

    print(f"\n[4/4] Grading picks for {yesterday}...")
    graded = grade_pending_picks(conn, yesterday)
    print(f"  Graded: {graded} picks")

    print(f"\n{'-'*50}")
    print(f"  Today's picks ({today}):")
    _print_summary(conn, today, pulled_at)
    print()

    conn.close()


if __name__ == "__main__":
    main()
