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
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from db import get_conn, init_db
from grade import grade_pending_picks, grade_pending_game_picks


def _pt_date(offset_days: int = 0) -> str:
    pt = datetime.now(timezone.utc) - timedelta(hours=7) + timedelta(days=offset_days)
    return pt.strftime("%Y-%m-%d")


def main() -> None:
    today     = _pt_date(0)
    yesterday = _pt_date(-1)

    print(f"\n{'='*50}")
    print(f"MLB V2 Nightly Grade - {today}")
    print(f"Grading picks for: {yesterday}")
    print(f"{'='*50}")

    conn = get_conn()
    init_db(conn)

    print(f"\nGrading player props for {yesterday}...")
    graded = grade_pending_picks(conn, yesterday)
    print(f"  Graded: {graded} picks")

    print(f"\nGrading game totals for {yesterday}...")
    game_graded = grade_pending_game_picks(conn, yesterday)
    print(f"  Graded: {game_graded} game picks")

    print(f"\nDone. Total graded: {graded + game_graded}")
    conn.close()


if __name__ == "__main__":
    main()
