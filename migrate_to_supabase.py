"""
One-time migration: copy picks.db → Supabase.
Run once: python migrate_to_supabase.py
"""
import sqlite3
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import psycopg2
import psycopg2.extras


def migrate():
    from config import DB_PATH
    src = sqlite3.connect(DB_PATH)
    src.row_factory = sqlite3.Row

    dsn = os.environ["DATABASE_URL"]
    dst = psycopg2.connect(dsn, cursor_factory=psycopg2.extras.RealDictCursor)

    # Init schema on Supabase
    from db import init_db, PgConn
    pg = PgConn(dsn)
    try:
        init_db(pg)
    finally:
        pg.close()
    print("Schema ready.")

    cur = dst.cursor()

    # Migrate daily_picks
    rows = src.execute("SELECT * FROM daily_picks").fetchall()
    count = 0
    try:
        for r in rows:
            d = dict(r)
            d.setdefault("emailed", 0)
            cur.execute("""
                INSERT INTO daily_picks
                    (pick_date, pulled_at, event_id, commence_time, home_team, away_team,
                     player_name, market_key, selection, point, bovada_price,
                     bovada_break_even_prob, bovada_fair_prob, consensus_fair_prob,
                     consensus_book_count, edge, ev, recommendation,
                     result, actual_stat, profit_units, bet_placed, units_wagered,
                     notes, confidence_score, confidence_factors,
                     signal_score, signal_breakdown, sim_prob, team_abbr, emailed)
                VALUES
                    (%(pick_date)s, %(pulled_at)s, %(event_id)s, %(commence_time)s,
                     %(home_team)s, %(away_team)s, %(player_name)s, %(market_key)s,
                     %(selection)s, %(point)s, %(bovada_price)s,
                     %(bovada_break_even_prob)s, %(bovada_fair_prob)s, %(consensus_fair_prob)s,
                     %(consensus_book_count)s, %(edge)s, %(ev)s, %(recommendation)s,
                     %(result)s, %(actual_stat)s, %(profit_units)s, %(bet_placed)s,
                     %(units_wagered)s, %(notes)s, %(confidence_score)s, %(confidence_factors)s,
                     %(signal_score)s, %(signal_breakdown)s, %(sim_prob)s, %(team_abbr)s,
                     %(emailed)s)
                ON CONFLICT(event_id, player_name, market_key, selection, point, pick_date)
                DO NOTHING
            """, d)
            count += 1
        dst.commit()
    except Exception as e:
        dst.rollback()
        raise RuntimeError(f"daily_picks migration failed after {count} rows: {e}") from e
    print(f"Migrated {count} daily_picks rows.")

    # Migrate daily_game_picks
    rows = src.execute("SELECT * FROM daily_game_picks").fetchall()
    count = 0
    try:
        for r in rows:
            d = dict(r)
            d.setdefault("emailed", 0)
            cur.execute("""
                INSERT INTO daily_game_picks
                    (pick_date, pulled_at, event_id, commence_time, home_team, away_team,
                     market_key, selection, point, bovada_price, bovada_break_even_prob,
                     bovada_fair_prob, consensus_fair_prob, consensus_book_count,
                     edge, recommendation, signal_score, signal_breakdown,
                     result, home_runs, away_runs, actual_total, profit_units,
                     bet_placed, units_wagered, notes, emailed)
                VALUES
                    (%(pick_date)s, %(pulled_at)s, %(event_id)s, %(commence_time)s,
                     %(home_team)s, %(away_team)s, %(market_key)s, %(selection)s,
                     %(point)s, %(bovada_price)s, %(bovada_break_even_prob)s,
                     %(bovada_fair_prob)s, %(consensus_fair_prob)s, %(consensus_book_count)s,
                     %(edge)s, %(recommendation)s, %(signal_score)s, %(signal_breakdown)s,
                     %(result)s, %(home_runs)s, %(away_runs)s, %(actual_total)s,
                     %(profit_units)s, %(bet_placed)s, %(units_wagered)s, %(notes)s,
                     %(emailed)s)
                ON CONFLICT(pick_date, event_id, market_key, selection)
                DO NOTHING
            """, d)
            count += 1
        dst.commit()
    except Exception as e:
        dst.rollback()
        raise RuntimeError(f"daily_game_picks migration failed after {count} rows: {e}") from e
    print(f"Migrated {count} daily_game_picks rows.")

    src.close()
    dst.close()
    print("Done.")


if __name__ == "__main__":
    migrate()
