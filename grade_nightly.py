#!/usr/bin/env python3
"""
MLB V2 — nightly grading script.
Run after games are final (recommended: 10 PM PT).

Grades pending player prop picks and game total picks for yesterday.
Does NOT pull new odds or score new picks.

Usage:
    python grade_nightly.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from config import pt_date as _pt_date
from db import get_conn, init_db, get_backtest_conn
from grade import grade_pending_picks, grade_pending_game_picks
from market_learn import compute_calibration, save_calibration


def main() -> None:
    today     = _pt_date(0)
    yesterday = _pt_date(-1)

    print(f"\n{'='*50}")
    print(f"MLB V2 Nightly Grade - {today}")
    print(f"Grading picks for: {yesterday}")
    print(f"{'='*50}")

    conn = get_conn()
    init_db(conn)

    total = 0
    for date in (today, yesterday):
        print(f"\nGrading player props for {date}...")
        graded = grade_pending_picks(conn, date)
        print(f"  Graded: {graded} picks")

        print(f"Grading game totals for {date}...")
        game_graded = grade_pending_game_picks(conn, date)
        print(f"  Graded: {game_graded} game picks")
        total += graded + game_graded

    print(f"\nDone. Total graded: {total}")

    print("\nUpdating calibration from backtest DB...")
    bt_conn = get_backtest_conn()
    cal = compute_calibration(bt_conn)
    bt_conn.close()
    save_calibration(cal)
    print(f"  Saved {len(cal)} calibration buckets")

    conn.close()


if __name__ == "__main__":
    main()
