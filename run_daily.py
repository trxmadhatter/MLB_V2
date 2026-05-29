#!/usr/bin/env python3
"""
MLB V2 — daily pipeline.
Run once per day before first pitch (recommended: 9 AM PT).
Run with --refresh to re-pull odds mid-day and detect Watchlist promotions.

Usage:
    python run_daily.py           # morning run
    python run_daily.py --refresh # mid-day refresh (skips grading)
"""
import argparse
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
from db import get_conn, init_db, upsert_pick, log_no_bet, get_snapshots, upsert_game_pick
from pull_props import pull_and_store
from consensus import compute_consensus, vig_remove_pair
from edge import bovada_break_even, compute_edge, compute_ev, classify_by_score, is_bet_recommendation
from grade import grade_pending_picks, grade_pending_game_picks
from market_learn import compute_live_calibration, save_calibration
from scorer import score_pick
from scorer_game import score_game_total
from simulate import simulate_pick
from stats import find_player_info as _find_player_info


from config import pt_date as _pt_date


def _commence_date_pt(commence_time: str) -> str:
    """Convert an ISO-8601 UTC commence_time to a PT calendar date string."""
    try:
        dt = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
        pt = dt.astimezone(timezone(timedelta(hours=-7)))
        return pt.strftime("%Y-%m-%d")
    except Exception:
        return ""


def _build_game_totals(all_rows: list[dict], today: str) -> dict[tuple, float]:
    """
    Build {(home_team_lower, away_team_lower): point} from Bovada totals lines.
    Accepts the already-fetched snapshot rows to avoid a second DB read.
    """
    result: dict[tuple, float] = {}
    for r in all_rows:
        if (r["market_key"] == "totals"
                and r["player_name"] == ""
                and r["bookmaker_key"] in BOVADA_KEYS
                and _commence_date_pt(r["commence_time"]) == today
                and r["selection"] == "Over"
                and r.get("point") is not None
                and float(r["point"]) >= 7.0):
            key = (r["home_team"].lower(), r["away_team"].lower())
            if key not in result:
                result[key] = float(r["point"])
    return result


def _analyze(conn, pulled_at: str, today: str,
             game_data: dict | None = None) -> tuple[int, int]:
    """
    Compute consensus + edge + signal score for all Bovada lines.
    game_data: pre-fetched from lineups.get_game_data_for_date().
    Returns (picks_evaluated, no_bets_logged).
    """
    rows = [dict(r) for r in get_snapshots(conn, pulled_at)]
    game_totals = _build_game_totals(rows, today)
    rows = [r for r in rows if r["player_name"] != ""]
    rows = [r for r in rows if _commence_date_pt(r["commence_time"]) == today]

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
            gt_key = (meta["home_team"].lower(), meta["away_team"].lower())
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
                game_total=game_totals.get(gt_key),
            )

            rec = classify_by_score(sig_score, edge, market_key, selection,
                                    price=bov["price"])

            sim_prob = None
            if is_bet_recommendation(rec):
                sim = simulate_pick(player_name, market_key, selection, point,
                                    int(today[:4]))
                if sim:
                    sim_prob = sim["sim_prob"]

            _pinfo = _find_player_info(player_name, int(today[:4]))
            _tid   = (_pinfo or {}).get("team_id")
            team_abbr = _TEAM_ID_ABBR.get(_tid, "") if _tid else ""

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
                "sim_prob":               sim_prob,
                "team_abbr":              team_abbr,
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
          AND NOT EXISTS (
              SELECT 1 FROM props_snapshots opp
              WHERE opp.pulled_at     = b.pulled_at
                AND opp.event_id      = b.event_id
                AND opp.market_key    = b.market_key
                AND opp.player_name   = b.player_name
                AND opp.point         = b.point
                AND opp.bookmaker_key = 'bovada'
                AND opp.selection    != b.selection
          )
        GROUP BY b.event_id, b.market_key, b.player_name, b.point, b.selection, b.price
        ORDER BY other_books DESC, b.market_key, b.player_name
    """, (pulled_at,)).fetchall()

    if not rows:
        return
    print(f"\n  --- One-sided Bovada lines (no two-way posted) ---")
    print(f"  {'PLAYER':<22} {'MARKET':<22} {'S':<6} {'PT':>4}  {'PRICE':>6}  {'OTHER_BKS':>9}")
    print("  " + "-" * 80)
    for r in rows:
        print(f"  {r['player_name']:<22} {r['market_key']:<22} {r['selection']:<6} {r['point']:>4.1f}  {r['price']:>+6d}  {r['other_books']:>9}")


_MARKET_SHORT = {
    "batter_total_bases":   "BTB",
    "batter_hits":          "BHT",
    "pitcher_strikeouts":   "PKO",
    "pitcher_hits_allowed": "PHA",
    "pitcher_outs":         "PTS",
}

# MLB team IDs are stable across seasons
_TEAM_ID_ABBR: dict[int, str] = {
    108: "LAA", 109: "ARI", 110: "BAL", 111: "BOS", 112: "CHC",
    113: "CIN", 114: "CLE", 115: "COL", 116: "DET", 117: "HOU",
    118: "KC",  119: "LAD", 120: "WSH", 121: "NYM", 133: "OAK",
    134: "PIT", 135: "SD",  136: "SEA", 137: "SF",  138: "STL",
    139: "TB",  140: "TEX", 141: "TOR", 142: "MIN", 143: "PHI",
    144: "ATL", 145: "CWS", 146: "MIA", 147: "NYY", 158: "MIL",
}


def _team_abbr(player_name: str, season: int) -> str:
    from stats import find_player_info
    try:
        info = find_player_info(player_name, season)
        if info:
            tid = info.get("team_id")
            if tid and tid in _TEAM_ID_ABBR:
                return _TEAM_ID_ABBR[tid]
    except Exception:
        pass
    return "???"


def _print_summary(conn, pick_date: str, pulled_at: str) -> None:
    season = int(pick_date[:4])

    # --- overall counts (internal reference) ---
    counts = conn.execute("""
        SELECT recommendation, COUNT(*) AS cnt
        FROM daily_picks WHERE pick_date = ?
        GROUP BY recommendation ORDER BY cnt DESC
    """, (pick_date,)).fetchall()
    total_by_rec = {r["recommendation"]: r["cnt"] for r in counts}
    total_eval = sum(total_by_rec.values())
    print(f"  Evaluated: {total_eval}  |  "
          + "  ".join(f"{k}: {v}" for k, v in total_by_rec.items()))

    # --- sim-confirmed Bovada bets ---
    bets = conn.execute("""
        SELECT player_name, market_key, selection, point,
               bovada_price, bovada_break_even_prob, edge,
               recommendation, signal_score, sim_prob, commence_time
        FROM daily_picks
        WHERE pick_date = ?
          AND recommendation IN ('A_BET', 'B_BET', 'RECOMMENDED', 'LEAN')
          AND sim_prob IS NOT NULL
          AND sim_prob >= bovada_break_even_prob
        ORDER BY commence_time ASC, recommendation DESC, sim_prob DESC, edge DESC
    """, (pick_date,)).fetchall()

    print(f"\n{'='*78}")
    print(f"  BOVADA BETS — {pick_date}  ({len(bets)} sim-confirmed)")
    print(f"{'='*78}")

    if not bets:
        print("  No picks passed simulation filter today.")
    else:
        print(f"  {'PLAYER':<22} {'TEAM':<4} {'MKT':<4} {'S':<5} {'LINE':>4}  "
              f"{'BOVADA':>7}  {'EDGE':>6}  {'SIM%':>5}  {'BEV%':>5}  TIER")
        print("  " + "-" * 84)
        for p in bets:
            tag = "**" if p["recommendation"] in ("A_BET", "RECOMMENDED") else " >"
            mkt  = _MARKET_SHORT.get(p["market_key"], p["market_key"][:4])
            team = _team_abbr(p["player_name"], season)
            bev_pct = p["bovada_break_even_prob"] * 100
            sim_pct = p["sim_prob"] * 100
            print(
                f"{tag} {p['player_name']:<22} {team:<4} {mkt:<4} {p['selection']:<5} "
                f"{p['point']:>4.1f}  {p['bovada_price']:>+7d}  "
                f"{p['edge']:>+6.1%}  {sim_pct:>4.0f}%  {bev_pct:>4.0f}%  "
                f"{p['recommendation']}"
            )

    # --- picks that had an edge but simulation rejected ---
    rejected = conn.execute("""
        SELECT COUNT(*) AS cnt FROM daily_picks
        WHERE pick_date = ?
          AND recommendation IN ('A_BET', 'B_BET', 'RECOMMENDED', 'LEAN')
          AND (sim_prob IS NULL OR sim_prob < bovada_break_even_prob)
    """, (pick_date,)).fetchone()["cnt"]
    if rejected:
        print(f"\n  ({rejected} A/B bet candidates rejected by simulation or no data)")

    _print_one_sided(conn, pulled_at)


def _analyze_games(conn, pulled_at: str, today: str,
                   game_data: dict | None = None) -> tuple[int, int]:
    """
    Score game totals (Over/Under), moneyline (h2h), and run line (spreads).
    Selections stored as 'Over'/'Under' for totals, 'Home'/'Away' for h2h/spreads.
    Returns (games_evaluated, no_bets_logged).
    """
    GAME_MARKETS = {"totals", "h2h", "spreads"}
    rows = [dict(r) for r in get_snapshots(conn, pulled_at)]
    rows = [r for r in rows if r["market_key"] in GAME_MARKETS and r["player_name"] == ""]
    rows = [r for r in rows if _commence_date_pt(r["commence_time"]) == today]

    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        key = (row["event_id"], row["market_key"])
        groups[key].append(row)

    games_evaluated = 0

    for (event_id, market_key), group_rows in groups.items():
        bovada_rows = [r for r in group_rows if r["bookmaker_key"] in BOVADA_KEYS]
        if not bovada_rows:
            continue

        meta = bovada_rows[0]

        if market_key == "totals":
            bov_a = next((r for r in bovada_rows if r["selection"] == "Over"),  None)
            bov_b = next((r for r in bovada_rows if r["selection"] == "Under"), None)
            sel_a, sel_b = "Over", "Under"
        else:
            # h2h/spreads: selections are team names — normalize to Home/Away
            bov_a = next((r for r in bovada_rows
                          if r["selection"].lower() == meta["home_team"].lower()), None)
            bov_b = next((r for r in bovada_rows
                          if r["selection"].lower() == meta["away_team"].lower()), None)
            sel_a, sel_b = "Home", "Away"

        if bov_a is None or bov_b is None:
            continue

        if market_key == "totals":
            if bov_a["point"] != bov_b["point"]:
                continue
            if bov_a["point"] < 7.0:
                continue  # skip F5 / alternate totals

        bov_fair_a, bov_fair_b = vig_remove_pair(bov_a["price"], bov_b["price"])

        # consensus requires 'Over'/'Under' selections — map team names for h2h/spreads
        # For spreads, also filter to the same point as Bovada to avoid mixing lines
        if market_key == "spreads":
            consensus_rows = []
            for r in group_rows:
                r2 = dict(r)
                if r2["selection"].lower() == meta["home_team"].lower():
                    if r2["point"] != bov_a["point"]:
                        continue
                    r2["selection"] = "Over"
                elif r2["selection"].lower() == meta["away_team"].lower():
                    if r2["point"] != bov_b["point"]:
                        continue
                    r2["selection"] = "Under"
                else:
                    continue
                consensus_rows.append(r2)
        elif market_key == "h2h":
            consensus_rows = []
            for r in group_rows:
                r2 = dict(r)
                if r2["selection"].lower() == meta["home_team"].lower():
                    r2["selection"] = "Over"
                elif r2["selection"].lower() == meta["away_team"].lower():
                    r2["selection"] = "Under"
                else:
                    continue
                consensus_rows.append(r2)
        else:
            consensus_rows = group_rows

        consensus = compute_consensus(
            consensus_rows,
            min_books=MIN_CONSENSUS_BOOKS,
            bovada_keys=BOVADA_KEYS,
        )

        for selection, bov, bov_fair in (
            (sel_a, bov_a, bov_fair_a),
            (sel_b, bov_b, bov_fair_b),
        ):
            if not consensus["ok"]:
                continue

            is_a_side = selection in ("Over", "Home")
            fair_prob = (
                consensus["fair_prob_over"] if is_a_side
                else consensus["fair_prob_under"]
            )
            bev  = bovada_break_even(bov["price"])
            edge = compute_edge(fair_prob, bov_fair)

            if market_key == "totals":
                total_sel = "Over" if is_a_side else "Under"
                sig_score, breakdown = score_game_total(
                    home_team=meta["home_team"],
                    away_team=meta["away_team"],
                    selection=total_sel,
                    point=bov_a["point"],
                    edge=edge,
                    game_date=today,
                    game_data=game_data,
                )
            else:
                # h2h/spreads: no signal scoring. Use a temporary score above
                # thresholds for classification, but store NULL so displays do
                # not show a fake 100.
                sig_score, breakdown = 100, []

            rec = classify_by_score(sig_score, edge, market_key, selection,
                                    price=bov["price"])
            stored_score = None if market_key in {"h2h", "spreads"} else sig_score

            upsert_game_pick(conn, {
                "pick_date":              today,
                "pulled_at":              pulled_at,
                "event_id":               event_id,
                "commence_time":          meta["commence_time"],
                "home_team":              meta["home_team"],
                "away_team":              meta["away_team"],
                "market_key":             market_key,
                "selection":              selection,
                "point":                  bov["point"],
                "bovada_price":           bov["price"],
                "bovada_break_even_prob": round(bev,       6),
                "bovada_fair_prob":       round(bov_fair,  6),
                "consensus_fair_prob":    round(fair_prob, 6),
                "consensus_book_count":   consensus["book_count"],
                "edge":                   round(edge, 6),
                "recommendation":         rec,
                "signal_score":           stored_score,
                "signal_breakdown":       json.dumps(breakdown),
            })
            games_evaluated += 1

    return games_evaluated, 0


def _print_game_summary(conn, pick_date: str) -> None:
    rows = conn.execute("""
        SELECT home_team, away_team, market_key, selection, point, bovada_price,
               edge, signal_score, recommendation, commence_time
        FROM daily_game_picks
        WHERE pick_date = ?
          AND recommendation IN ('A_BET', 'B_BET', 'RECOMMENDED', 'LEAN')
        ORDER BY commence_time ASC, recommendation DESC, signal_score DESC
    """, (pick_date,)).fetchall()

    print(f"\n  GAME MARKETS — {pick_date}")
    if not rows:
        print("  No game market picks today.")
        return

    print(f"  {'HOME':<20} {'AWAY':<20} {'MKT':<7} {'SEL':<6} {'LINE':>4}  {'BOVADA':>6}  {'EDGE':>6}  {'SCORE':>9}  TIER")
    print("  " + "-" * 80)
    for r in rows:
        tag = "**" if r["recommendation"] in ("A_BET", "RECOMMENDED") else " >"
        score_s = f"{r['signal_score']:>9d}" if r["signal_score"] is not None else "edge-only"
        print(
            f"{tag} {r['home_team']:<20} {r['away_team']:<20} {r['market_key']:<7} {r['selection']:<6} "
            f"{r['point']:>4.1f}  {r['bovada_price']:>+6d}  "
            f"{r['edge']:>+5.1%}  {score_s}  {r['recommendation']}"
        )


def _snapshot_watch_picks(conn, today: str) -> dict:
    """Return {pick_key: recommendation} for all WATCH picks today."""
    rows = conn.execute("""
        SELECT event_id, player_name, market_key, selection, point
        FROM daily_picks
        WHERE pick_date = ? AND recommendation = 'WATCH'
    """, [today]).fetchall()
    return {(r["event_id"], r["player_name"], r["market_key"], r["selection"], r["point"]): "WATCH"
            for r in rows}


def _detect_promotions(conn, today: str, prev_watch: dict) -> list[dict]:
    """Return picks that were WATCH and are now A_BET or B_BET."""
    promoted = []
    for (event_id, player_name, market_key, selection, point) in prev_watch:
        row = conn.execute("""
            SELECT * FROM daily_picks
            WHERE pick_date=? AND event_id=? AND player_name=?
              AND market_key=? AND selection=? AND point=?
        """, [today, event_id, player_name, market_key, selection, point]).fetchone()
        if row and row["recommendation"] in ("A_BET", "B_BET"):
            promoted.append(dict(row))
    return promoted


def _snapshot_game_bets(conn, today: str) -> dict:
    """Return {(event_id, market_key, selection, point): (recommendation, edge)} for bet game picks."""
    rows = conn.execute("""
        SELECT event_id, market_key, selection, point, recommendation, edge
        FROM daily_game_picks
        WHERE pick_date = ? AND bet_placed = 1
          AND recommendation IN ('A_BET','B_BET','RECOMMENDED','LEAN')
    """, [today]).fetchall()
    return {(r["event_id"], r["market_key"], r["selection"], r["point"]): (r["recommendation"], r["edge"])
            for r in rows}


def _detect_game_degradations(conn, today: str, prev_bets: dict) -> list[dict]:
    """Return bet game picks whose edge has dropped below their tier minimum."""
    from config import EDGE_RECOMMENDED, EDGE_LEAN
    from edge import normalize_recommendation
    degraded = []
    for (event_id, market_key, selection, point), (rec, _) in prev_bets.items():
        row = conn.execute("""
            SELECT * FROM daily_game_picks
            WHERE pick_date=? AND event_id=? AND market_key=? AND selection=? AND point=?
        """, [today, event_id, market_key, selection, point]).fetchone()
        if not row:
            continue
        new_edge = row["edge"] or 0.0
        norm = normalize_recommendation(rec)
        floor = EDGE_RECOMMENDED if norm == "A_BET" else EDGE_LEAN
        if new_edge < floor:
            d = dict(row)
            d["edge"] = new_edge
            degraded.append(d)
    return degraded


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true",
                        help="Re-pull odds mid-day, detect Watchlist promotions, skip grading")
    args = parser.parse_args()

    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        print("ERROR: ODDS_API_KEY not set in .env")
        sys.exit(1)

    conn  = get_conn()
    init_db(conn)

    today     = _pt_date(0)
    yesterday = _pt_date(-1)
    mode = "REFRESH" if args.refresh else "DAILY"
    print(f"\n{'='*50}")
    print(f"MLB V2 {mode} Run - {today}")
    print(f"{'='*50}")

    # Snapshot state before re-pulling (refresh mode only)
    prev_watch     = _snapshot_watch_picks(conn, today) if args.refresh else {}
    prev_game_bets = _snapshot_game_bets(conn, today)   if args.refresh else {}

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

    from db import void_missing_bovada_lines
    voided_lines = void_missing_bovada_lines(conn, today, pulled_at)
    if voided_lines:
        print(f"  Voided {voided_lines} picks — Bovada line no longer posted")

    csv_path = _export_csv(conn, today)
    print(f"  CSV: {csv_path}")

    print("\n[3b] Scoring game markets...")
    games_eval, _ = _analyze_games(conn, pulled_at, today, game_data=game_data)
    print(f"  Game lines evaluated: {games_eval}")

    # Detect promotions and degradations (refresh mode only)
    if args.refresh:
        try:
            from send_picks_email import send_promotion_alert, send_degradation_alert

            promoted = _detect_promotions(conn, today, prev_watch)
            if promoted:
                print(f"\n  *** {len(promoted)} Watchlist pick(s) promoted — sending alert ***")
                send_promotion_alert(promoted, today)
            else:
                print("\n  No Watchlist promotions this refresh")

            degraded = _detect_game_degradations(conn, today, prev_game_bets)
            if degraded:
                print(f"  *** {len(degraded)} game bet(s) degraded — sending alert ***")
                send_degradation_alert(degraded, today)
            else:
                print("  No game bet degradations this refresh")
        finally:
            conn.close()
        return

    print(f"\n[4/4] Grading picks for {yesterday}...")
    graded = grade_pending_picks(conn, yesterday)
    print(f"  Graded: {graded} picks")

    print(f"\n[4b] Grading game picks for {yesterday}...")
    game_graded = grade_pending_game_picks(conn, yesterday)
    print(f"  Graded: {game_graded} game picks")

    print(f"\n[4c] Updating market calibration...")
    calibration = compute_live_calibration(conn)
    if calibration:
        save_calibration(calibration)
        print(f"  Calibration updated: {len(calibration)} buckets")
    else:
        print(f"  No graded picks — calibration unchanged")

    print(f"\n{'-'*50}")
    print(f"  Today's picks ({today}):")
    _print_summary(conn, today, pulled_at)
    _print_game_summary(conn, today)
    print()

    # Write status file for remote health checks
    try:
        player_bets = conn.execute("""
            SELECT COUNT(*) AS cnt FROM daily_picks
            WHERE pick_date = ?
              AND recommendation IN ('A_BET','B_BET','RECOMMENDED','LEAN')
        """, (today,)).fetchone()["cnt"]
        game_bets = conn.execute("""
            SELECT COUNT(*) AS cnt FROM daily_game_picks
            WHERE pick_date = ?
              AND recommendation IN ('A_BET','B_BET','RECOMMENDED','LEAN')
        """, (today,)).fetchone()["cnt"]
        status = {
            "date": today,
            "ran_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "picks_evaluated": evaluated,
            "bets_found": player_bets + game_bets,
            "email_sent": False,
            "pipeline_success": True,
        }
        (ROOT / "data" / "status.json").write_text(json.dumps(status, indent=2))
    except Exception as _e:
        print(f"  WARNING: could not write status.json ({_e})")

    conn.close()


if __name__ == "__main__":
    main()
