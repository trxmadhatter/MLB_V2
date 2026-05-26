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


VOID_AFTER_DAYS = 3  # mark PENDING picks older than this as VOID


def _get_pending_dates(conn) -> list[str]:
    """All distinct pick dates that still have PENDING rows, oldest first."""
    rows = conn.execute("""
        SELECT DISTINCT pick_date FROM daily_picks WHERE result='PENDING'
        UNION
        SELECT DISTINCT pick_date FROM daily_game_picks WHERE result='PENDING'
        ORDER BY pick_date
    """).fetchall()
    return [r["pick_date"] for r in rows]


def _void_stale_pending(conn, today: str) -> int:
    """Mark PENDING picks older than VOID_AFTER_DAYS days as VOID."""
    from datetime import date, timedelta
    cutoff = (date.fromisoformat(today) - timedelta(days=VOID_AFTER_DAYS)).isoformat()
    try:
        cur = conn.execute(
            "UPDATE daily_picks SET result='VOID' WHERE result='PENDING' AND pick_date < ?",
            (cutoff,),
        )
        n1 = cur.rowcount
        cur = conn.execute(
            "UPDATE daily_game_picks SET result='VOID' WHERE result='PENDING' AND pick_date < ?",
            (cutoff,),
        )
        n2 = cur.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return n1 + n2


def main() -> None:
    today     = _pt_date(0)
    yesterday = _pt_date(-1)

    print(f"\n{'='*50}")
    print(f"MLB V2 Nightly Grade - {today}")
    print(f"{'='*50}")

    conn = get_conn()
    init_db(conn)

    # Void stale picks first so the grading loop never touches them
    voided = _void_stale_pending(conn, today)
    if voided:
        print(f"\nVOIDed {voided} picks still PENDING after {VOID_AFTER_DAYS}+ days (DNP/postponed).")

    pending_dates = _get_pending_dates(conn)
    # Exclude today — games aren't final yet
    dates_to_grade = [d for d in pending_dates if d != today]

    if not dates_to_grade:
        print("\nNo pending picks to grade.")
    else:
        print(f"\nPending dates to grade: {dates_to_grade}")

    total = 0
    for date in dates_to_grade:
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
