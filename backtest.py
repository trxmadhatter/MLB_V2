#!/usr/bin/env python3
"""
MLB V2 Backtester — replay the edge pipeline on historical odds.

Usage:
    python backtest.py                  # last 14 days
    python backtest.py --days 30
    python backtest.py --from 2026-04-01 --to 2026-04-30
    python backtest.py --report-only    # show report without fetching
"""
import argparse
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from db import init_db, insert_snapshots

BACKTEST_DB = ROOT / "data" / "backtest.db"

MARKET_LABELS = {
    "pitcher_strikeouts":   "K (P)",
    "pitcher_hits_allowed": "Hits (P)",
    "pitcher_earned_runs":  "ER (P)",
    "pitcher_walks":        "BB (P)",
    "pitcher_outs":         "Outs (P)",
    "batter_hits":          "Hits (B)",
    "batter_total_bases":   "TB (B)",
    "batter_home_runs":     "HR (B)",
    "batter_rbis":          "RBI (B)",
    "batter_runs_scored":   "R (B)",
    "batter_stolen_bases":  "SB (B)",
    "batter_walks":         "BB (B)",
}


# ── DB ────────────────────────────────────────────────────────────────────────

def init_backtest_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS backtest_picks (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            pick_date             TEXT    NOT NULL,
            player_name           TEXT    NOT NULL,
            market_key            TEXT    NOT NULL,
            selection             TEXT    NOT NULL,
            point                 REAL    NOT NULL,
            bovada_price          INTEGER NOT NULL,
            bovada_fair_prob      REAL    NOT NULL,
            consensus_fair_prob   REAL    NOT NULL,
            consensus_book_count  INTEGER NOT NULL,
            edge                  REAL    NOT NULL,
            ev                    REAL    NOT NULL,
            recommendation        TEXT    NOT NULL,
            result                TEXT    NOT NULL DEFAULT 'PENDING',
            actual_stat           REAL,
            profit_units          REAL,
            UNIQUE(pick_date, player_name, market_key, selection, point)
        );

        CREATE TABLE IF NOT EXISTS backtest_days (
            pick_date      TEXT PRIMARY KEY,
            processed_at   TEXT NOT NULL,
            picks_analyzed INTEGER NOT NULL
        );
    """)
    conn.commit()


def _store_picks(
    bt_conn: sqlite3.Connection,
    pick_date: str,
    picks: list,
) -> None:
    bt_conn.executemany("""
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
    """, picks)
    bt_conn.commit()


# ── Per-day analysis ──────────────────────────────────────────────────────────

def _analyze_day(snapshot_rows: list, pulled_at: str, date_str: str) -> list:
    """Run edge analysis on snapshot_rows using in-memory SQLite. Returns list of pick dicts."""
    from run_daily import _analyze

    mem = sqlite3.connect(":memory:")
    mem.row_factory = sqlite3.Row
    init_db(mem)
    insert_snapshots(mem, snapshot_rows)
    _analyze(mem, pulled_at, date_str)
    picks = [dict(r) for r in mem.execute(
        "SELECT * FROM daily_picks WHERE pick_date=?", (date_str,)
    ).fetchall()]
    mem.close()
    return picks


def _grade_picks(picks: list, date_str: str) -> list:
    """Grade picks against MLB Stats API boxscores for date_str."""
    from grade import get_game_results, grade_outcome, calc_profit, normalize_name

    results = get_game_results(date_str)
    index = {
        (normalize_name(r["player_name"]), r["market_key"]): r["stat_value"]
        for r in results
    }

    for p in picks:
        key    = (normalize_name(p["player_name"]), p["market_key"])
        actual = index.get(key)
        if actual is not None:
            p["result"]       = grade_outcome(p["selection"], p["point"], actual)
            p["actual_stat"]  = actual
            p["profit_units"] = calc_profit(p["result"], p["bovada_price"])
    return picks


def run_backtest_day(
    api_key: str,
    date_str: str,
    bt_conn: sqlite3.Connection,
) -> int:
    """
    Process one day: fetch -> analyze -> grade -> store.
    Skips if already in backtest_days. Returns picks analyzed.
    """
    from backtest_fetch import pull_historical_snapshots

    if bt_conn.execute(
        "SELECT 1 FROM backtest_days WHERE pick_date=?", (date_str,)
    ).fetchone():
        print(f"  {date_str}: already processed, skipping")
        return 0

    print(f"\n  [{date_str}] Fetching historical odds...")
    pulled_at, snapshot_rows = pull_historical_snapshots(api_key, date_str)

    if not snapshot_rows:
        print(f"  {date_str}: no snapshot rows — skipping")
        return 0

    print(f"  {date_str}: {len(snapshot_rows)} snapshot rows - analyzing...")
    picks = _analyze_day(snapshot_rows, pulled_at, date_str)
    print(f"  {date_str}: {len(picks)} picks evaluated - grading...")

    picks = _grade_picks(picks, date_str)
    graded_count = sum(1 for p in picks if p.get("result", "PENDING") != "PENDING")
    print(f"  {date_str}: {graded_count}/{len(picks)} picks graded")

    _store_picks(bt_conn, date_str, picks)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    bt_conn.execute(
        "INSERT OR REPLACE INTO backtest_days VALUES (?, ?, ?)",
        (date_str, now, len(picks)),
    )
    bt_conn.commit()
    return len(picks)


def run_backtest(
    api_key: str,
    start_date: str,
    end_date: str,
    bt_conn: sqlite3.Connection,
) -> None:
    """Loop from start_date to end_date (inclusive, YYYY-MM-DD), skipping today and future."""
    today = (datetime.now(timezone.utc) - timedelta(hours=7)).strftime("%Y-%m-%d")
    d   = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date,   "%Y-%m-%d")
    while d <= end:
        date_str = d.strftime("%Y-%m-%d")
        if date_str < today:
            try:
                run_backtest_day(api_key, date_str, bt_conn)
            except Exception as exc:
                print(f"  {date_str}: ERROR — {exc} — skipping day")
        else:
            print(f"  {date_str}: skipping (today or future)")
        d += timedelta(days=1)


# ── Report ────────────────────────────────────────────────────────────────────

def _report_summary(bt_conn: sqlite3.Connection) -> list:
    return bt_conn.execute("""
        SELECT recommendation,
               COUNT(*) AS total,
               SUM(CASE WHEN result='WIN'  THEN 1 ELSE 0 END) AS wins,
               SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) AS losses,
               SUM(CASE WHEN result='PUSH' THEN 1 ELSE 0 END) AS pushes,
               ROUND(100.0 * SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END)
                     / NULLIF(SUM(CASE WHEN result IN ('WIN','LOSS') THEN 1 ELSE 0 END), 0), 1) AS win_pct,
               ROUND(SUM(CASE WHEN result != 'PENDING' THEN COALESCE(profit_units,0) ELSE 0 END), 2) AS net_units,
               ROUND(100.0 * SUM(CASE WHEN result != 'PENDING' THEN COALESCE(profit_units,0) ELSE 0 END)
                     / NULLIF(SUM(CASE WHEN result IN ('WIN','LOSS','PUSH') THEN 1 ELSE 0 END), 0), 1) AS roi_pct
        FROM backtest_picks
        WHERE result != 'PENDING'
        GROUP BY recommendation
        ORDER BY CASE recommendation WHEN 'RECOMMENDED' THEN 0 WHEN 'LEAN' THEN 1 ELSE 2 END
    """).fetchall()


def _report_by_market(bt_conn: sqlite3.Connection) -> list:
    return bt_conn.execute("""
        SELECT market_key, recommendation,
               COUNT(*) AS total,
               SUM(CASE WHEN result='WIN'  THEN 1 ELSE 0 END) AS wins,
               SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) AS losses,
               SUM(CASE WHEN result='PUSH' THEN 1 ELSE 0 END) AS pushes,
               ROUND(100.0 * SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END)
                     / NULLIF(SUM(CASE WHEN result IN ('WIN','LOSS') THEN 1 ELSE 0 END), 0), 1) AS win_pct,
               ROUND(SUM(CASE WHEN result != 'PENDING' THEN COALESCE(profit_units,0) ELSE 0 END), 2) AS net_units
        FROM backtest_picks
        WHERE result != 'PENDING'
          AND recommendation IN ('RECOMMENDED', 'LEAN')
        GROUP BY market_key, recommendation
        ORDER BY net_units DESC
    """).fetchall()


def _report_by_edge_bucket(bt_conn: sqlite3.Connection) -> list:
    return bt_conn.execute("""
        SELECT
            CASE
                WHEN edge >= 0.06 THEN '6%+    (REC)'
                WHEN edge >= 0.04 THEN '4-6%   (REC)'
                WHEN edge >= 0.02 THEN '2-4%   (LEAN)'
                ELSE '< 2%   (NO_BET)'
            END AS bucket,
            COUNT(*) AS total,
            SUM(CASE WHEN result='WIN'  THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) AS losses,
            SUM(CASE WHEN result='PUSH' THEN 1 ELSE 0 END) AS pushes,
            ROUND(100.0 * SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END)
                  / NULLIF(SUM(CASE WHEN result IN ('WIN','LOSS') THEN 1 ELSE 0 END), 0), 1) AS win_pct,
            ROUND(SUM(CASE WHEN result != 'PENDING' THEN COALESCE(profit_units,0) ELSE 0 END), 2) AS net_units,
            ROUND(100.0 * SUM(CASE WHEN result != 'PENDING' THEN COALESCE(profit_units,0) ELSE 0 END)
                  / NULLIF(SUM(CASE WHEN result IN ('WIN','LOSS','PUSH') THEN 1 ELSE 0 END), 0), 1) AS roi_pct
        FROM backtest_picks
        WHERE result != 'PENDING'
        GROUP BY bucket
        ORDER BY MIN(edge) DESC
    """).fetchall()


def print_report(
    bt_conn: sqlite3.Connection,
    start_date: str,
    end_date: str,
) -> None:
    days = bt_conn.execute("SELECT COUNT(*) FROM backtest_days").fetchone()[0]
    total_picks = bt_conn.execute(
        "SELECT COUNT(*) FROM backtest_picks WHERE result != 'PENDING'"
    ).fetchone()[0]

    print(f"\n{'='*60}")
    print(f"  BACKTEST: {start_date} to {end_date}  ({days} days processed)")
    print(f"  Graded picks: {total_picks}")
    print(f"{'='*60}")

    print("\n-- BY TIER -------------------------------------------------")
    print(f"  {'TIER':<14} {'TOTAL':>5}  {'W-L-P':>11}  {'WIN%':>6}  {'NET':>7}  {'ROI':>6}")
    print("  " + "-" * 56)
    for r in _report_summary(bt_conn):
        wlp = f"{r['wins']}-{r['losses']}-{r['pushes']}"
        wp  = f"{r['win_pct']:.1f}%" if r['win_pct'] is not None else "  --"
        roi = f"{r['roi_pct']:+.1f}%" if r['roi_pct'] is not None else "  --"
        print(f"  {r['recommendation']:<14} {r['total']:>5}  {wlp:>11}  {wp:>6}  {r['net_units']:>+7.2f}  {roi:>6}")

    print("\n-- BY MARKET (LEAN+) ---------------------------------------")
    print(f"  {'MARKET':<16} {'TIER':<14} {'TOT':>4}  {'W-L-P':>11}  {'WIN%':>6}  {'NET':>7}")
    print("  " + "-" * 62)
    for r in _report_by_market(bt_conn):
        label = MARKET_LABELS.get(r['market_key'], r['market_key'])
        wlp   = f"{r['wins']}-{r['losses']}-{r['pushes']}"
        wp    = f"{r['win_pct']:.1f}%" if r['win_pct'] is not None else "  --"
        print(f"  {label:<16} {r['recommendation']:<14} {r['total']:>4}  {wlp:>11}  {wp:>6}  {r['net_units']:>+7.2f}")

    print("\n-- BY EDGE BUCKET ------------------------------------------")
    print(f"  {'BUCKET':<16} {'TOT':>4}  {'W-L-P':>11}  {'WIN%':>6}  {'NET':>7}  {'ROI':>6}")
    print("  " + "-" * 58)
    for r in _report_by_edge_bucket(bt_conn):
        wlp = f"{r['wins']}-{r['losses']}-{r['pushes']}"
        wp  = f"{r['win_pct']:.1f}%" if r['win_pct'] is not None else "  --"
        roi = f"{r['roi_pct']:+.1f}%" if r['roi_pct'] is not None else "  --"
        print(f"  {r['bucket']:<16} {r['total']:>4}  {wlp:>11}  {wp:>6}  {r['net_units']:>+7.2f}  {roi:>6}")

    print()


# ── CLI ───────────────────────────────────────────────────────────────────────

def _get_bt_conn() -> sqlite3.Connection:
    BACKTEST_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(BACKTEST_DB)
    conn.row_factory = sqlite3.Row
    init_backtest_db(conn)
    return conn


def main() -> None:
    today = (datetime.now(timezone.utc) - timedelta(hours=7)).strftime("%Y-%m-%d")

    parser = argparse.ArgumentParser(description="MLB V2 Backtester")
    parser.add_argument("--days",        type=int, default=14,
                        help="Number of past days to backtest (default: 14)")
    parser.add_argument("--from", dest="start_date", default=None,
                        help="Start date YYYY-MM-DD (overrides --days)")
    parser.add_argument("--to",   dest="end_date",   default=None,
                        help="End date YYYY-MM-DD (default: yesterday)")
    parser.add_argument("--report-only", action="store_true",
                        help="Print report from existing data without fetching")
    parser.add_argument("--reset", action="store_true",
                        help="Delete backtest DB before running (fresh start with all markets)")
    args = parser.parse_args()

    if args.reset and not args.report_only:
        if BACKTEST_DB.exists():
            BACKTEST_DB.unlink()
            print("  Backtest DB reset. Starting fresh.")

    bt_conn = _get_bt_conn()

    if args.end_date:
        end_date = args.end_date
    else:
        end_date = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")

    if args.start_date:
        start_date = args.start_date
    else:
        start_date = (
            datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=args.days - 1)
        ).strftime("%Y-%m-%d")

    if not args.report_only:
        api_key = os.environ.get("ODDS_API_KEY")
        if not api_key:
            print("ERROR: ODDS_API_KEY not set in .env")
            sys.exit(1)
        print(f"\nBacktesting {start_date} to {end_date}...")
        print(f"NOTE: Each day costs ~15-20 API requests. A 14-day run uses ~220 requests.\n")
        run_backtest(api_key, start_date, end_date, bt_conn)

    print_report(bt_conn, start_date, end_date)
    bt_conn.close()


if __name__ == "__main__":
    main()
