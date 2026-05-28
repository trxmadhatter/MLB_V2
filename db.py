import os
import sqlite3
from pathlib import Path

from config import DB_PATH

BACKTEST_DB_PATH = Path(__file__).parent / "data" / "backtest.db"


# ── Postgres connection wrapper ───────────────────────────────────────────────

class _PgCursor:
    """Wraps a psycopg2 RealDictCursor to mimic sqlite3 cursor interface."""

    def __init__(self, cur):
        self._cur = cur

    @property
    def rowcount(self):
        return self._cur.rowcount

    def fetchall(self):
        try:
            return self._cur.fetchall()
        finally:
            self._cur.close()

    def fetchone(self):
        return self._cur.fetchone()

    def close(self):
        self._cur.close()

    def __del__(self):
        try:
            self._cur.close()
        except Exception:
            pass

    def __iter__(self):
        rows = self._cur.fetchall()
        self._cur.close()
        return iter(rows)


class PgConn:
    """Wraps psycopg2 connection to mimic sqlite3 Connection interface.
    Translates ? placeholders to %s automatically."""

    def __init__(self, dsn: str):
        import psycopg2
        import psycopg2.extras
        self._conn = psycopg2.connect(dsn, cursor_factory=psycopg2.extras.RealDictCursor)
        # Prevent any single statement from blocking indefinitely (e.g. due to a lock)
        with self._conn.cursor() as _c:
            _c.execute("SET statement_timeout = '30s'")
        self._conn.commit()

    def execute(self, sql: str, params=()):
        sql = sql.replace("?", "%s")
        cur = self._conn.cursor()
        try:
            cur.execute(sql, params)
        except Exception:
            cur.close()
            raise
        return _PgCursor(cur)

    def executemany(self, sql: str, params_list):
        sql = sql.replace("?", "%s")
        cur = self._conn.cursor()
        try:
            cur.executemany(sql, params_list)
        except Exception:
            cur.close()
            raise
        return _PgCursor(cur)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


# ── Connection factories ──────────────────────────────────────────────────────

def get_backtest_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(BACKTEST_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_conn(db_path=None) -> PgConn:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        try:
            import streamlit as st
            dsn = st.secrets.get("DATABASE_URL")
            if not dsn:
                host = st.secrets.get("DB_HOST")
                user = st.secrets.get("DB_USER")
                pwd  = st.secrets.get("DB_PASS")
                name = st.secrets.get("DB_NAME", "neondb")
                if host and user and pwd:
                    dsn = f"postgresql://{user}:{pwd}@{host}/{name}?sslmode=require"
        except Exception:
            pass
    if not dsn:
        raise RuntimeError(
            "DATABASE_URL is not set. Add it to .env or export it as an environment variable."
        )
    # Append connect_timeout if not already specified so callers never hang forever
    if "connect_timeout" not in dsn:
        sep = "&" if "?" in dsn else "?"
        dsn = f"{dsn}{sep}connect_timeout=15"
    return PgConn(dsn)


# ── Schema ────────────────────────────────────────────────────────────────────

def init_db(conn: PgConn) -> None:
    statements = [
        """
        CREATE TABLE IF NOT EXISTS props_snapshots (
            id            SERIAL PRIMARY KEY,
            pulled_at     TEXT NOT NULL,
            event_id      TEXT NOT NULL,
            commence_time TEXT NOT NULL,
            home_team     TEXT NOT NULL,
            away_team     TEXT NOT NULL,
            bookmaker_key TEXT NOT NULL,
            last_update   TEXT,
            market_key    TEXT NOT NULL,
            player_name   TEXT NOT NULL,
            selection     TEXT NOT NULL,
            point         REAL NOT NULL,
            price         INTEGER NOT NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_snap_pull_event
            ON props_snapshots(pulled_at, event_id, market_key, player_name, point)
        """,
        """
        CREATE TABLE IF NOT EXISTS daily_picks (
            id                     SERIAL PRIMARY KEY,
            pick_date              TEXT NOT NULL,
            pulled_at              TEXT NOT NULL,
            event_id               TEXT NOT NULL,
            commence_time          TEXT NOT NULL,
            home_team              TEXT NOT NULL,
            away_team              TEXT NOT NULL,
            player_name            TEXT NOT NULL,
            market_key             TEXT NOT NULL,
            selection              TEXT NOT NULL,
            point                  REAL NOT NULL,
            bovada_price           INTEGER NOT NULL,
            bovada_break_even_prob REAL NOT NULL,
            bovada_fair_prob       REAL NOT NULL DEFAULT 0,
            consensus_fair_prob    REAL NOT NULL,
            consensus_book_count   INTEGER NOT NULL,
            edge                   REAL NOT NULL,
            ev                     REAL NOT NULL,
            recommendation         TEXT NOT NULL,
            result                 TEXT NOT NULL DEFAULT 'PENDING',
            actual_stat            REAL,
            profit_units           REAL,
            bet_placed             INTEGER NOT NULL DEFAULT 0,
            units_wagered          REAL,
            notes                  TEXT,
            confidence_score       INTEGER,
            confidence_factors     TEXT,
            signal_score           INTEGER,
            signal_breakdown       TEXT,
            sim_prob               REAL,
            team_abbr              TEXT,
            emailed                INTEGER NOT NULL DEFAULT 0,
            UNIQUE(event_id, player_name, market_key, selection, point, pick_date)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS no_bets_structural (
            id          SERIAL PRIMARY KEY,
            logged_at   TEXT NOT NULL,
            pick_date   TEXT NOT NULL,
            event_id    TEXT NOT NULL,
            player_name TEXT NOT NULL,
            market_key  TEXT NOT NULL,
            selection   TEXT NOT NULL,
            point       REAL NOT NULL,
            reason      TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS daily_game_picks (
            id                     SERIAL PRIMARY KEY,
            pick_date              TEXT NOT NULL,
            pulled_at              TEXT NOT NULL,
            event_id               TEXT NOT NULL,
            commence_time          TEXT,
            home_team              TEXT NOT NULL,
            away_team              TEXT NOT NULL,
            market_key             TEXT NOT NULL,
            selection              TEXT NOT NULL,
            point                  REAL NOT NULL,
            bovada_price           INTEGER NOT NULL,
            bovada_break_even_prob REAL,
            bovada_fair_prob       REAL,
            consensus_fair_prob    REAL,
            consensus_book_count   INTEGER,
            edge                   REAL,
            recommendation         TEXT NOT NULL,
            signal_score           INTEGER,
            signal_breakdown       TEXT,
            result                 TEXT NOT NULL DEFAULT 'PENDING',
            home_runs              INTEGER,
            away_runs              INTEGER,
            actual_total           REAL,
            profit_units           REAL,
            bet_placed             INTEGER NOT NULL DEFAULT 0,
            units_wagered          REAL,
            notes                  TEXT,
            emailed                INTEGER NOT NULL DEFAULT 0,
            UNIQUE(pick_date, event_id, market_key, selection)
        )
        """,
    ]
    for stmt in statements:
        conn.execute(stmt)
    conn.commit()

    # Add columns that may be absent from tables created before they were introduced
    _col_migrations = [
        ("daily_picks",      "emailed",             "INTEGER NOT NULL DEFAULT 0"),
        ("daily_picks",      "sim_prob",             "REAL"),
        ("daily_picks",      "team_abbr",            "TEXT"),
        ("daily_picks",      "signal_score",         "INTEGER"),
        ("daily_picks",      "signal_breakdown",     "TEXT"),
        ("daily_picks",      "confidence_score",     "INTEGER"),
        ("daily_picks",      "confidence_factors",   "TEXT"),
        ("daily_game_picks", "emailed",              "INTEGER NOT NULL DEFAULT 0"),
        ("daily_game_picks", "signal_score",         "INTEGER"),
        ("daily_game_picks", "signal_breakdown",     "TEXT"),
    ]
    for table, col, col_def in _col_migrations:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {col_def}")
    conn.commit()


# ── Writes ────────────────────────────────────────────────────────────────────

def insert_snapshots(conn: PgConn, rows: list[dict]) -> int:
    conn.executemany("""
        INSERT INTO props_snapshots
            (pulled_at, event_id, commence_time, home_team, away_team,
             bookmaker_key, last_update, market_key, player_name,
             selection, point, price)
        VALUES
            (%(pulled_at)s, %(event_id)s, %(commence_time)s, %(home_team)s, %(away_team)s,
             %(bookmaker_key)s, %(last_update)s, %(market_key)s, %(player_name)s,
             %(selection)s, %(point)s, %(price)s)
    """, rows)
    conn.commit()
    return len(rows)


def get_snapshots(conn: PgConn, pulled_at: str):
    return conn.execute(
        "SELECT * FROM props_snapshots WHERE pulled_at = %s", (pulled_at,)
    ).fetchall()


def upsert_pick(conn: PgConn, pick: dict) -> None:
    pick = {**pick}
    pick.setdefault("signal_score", None)
    pick.setdefault("signal_breakdown", None)
    pick.setdefault("sim_prob", None)
    pick.setdefault("team_abbr", None)
    conn.execute("""
        INSERT INTO daily_picks
            (pick_date, pulled_at, event_id, commence_time, home_team, away_team,
             player_name, market_key, selection, point, bovada_price,
             bovada_break_even_prob, bovada_fair_prob, consensus_fair_prob,
             consensus_book_count, edge, ev, recommendation,
             signal_score, signal_breakdown, sim_prob, team_abbr)
        VALUES
            (%(pick_date)s, %(pulled_at)s, %(event_id)s, %(commence_time)s,
             %(home_team)s, %(away_team)s, %(player_name)s, %(market_key)s,
             %(selection)s, %(point)s, %(bovada_price)s,
             %(bovada_break_even_prob)s, %(bovada_fair_prob)s, %(consensus_fair_prob)s,
             %(consensus_book_count)s, %(edge)s, %(ev)s, %(recommendation)s,
             %(signal_score)s, %(signal_breakdown)s, %(sim_prob)s, %(team_abbr)s)
        ON CONFLICT(event_id, player_name, market_key, selection, point, pick_date)
        DO UPDATE SET
            bovada_price=EXCLUDED.bovada_price,
            bovada_break_even_prob=EXCLUDED.bovada_break_even_prob,
            bovada_fair_prob=EXCLUDED.bovada_fair_prob,
            consensus_fair_prob=EXCLUDED.consensus_fair_prob,
            consensus_book_count=EXCLUDED.consensus_book_count,
            edge=EXCLUDED.edge,
            ev=EXCLUDED.ev,
            signal_score=EXCLUDED.signal_score,
            signal_breakdown=EXCLUDED.signal_breakdown,
            sim_prob=EXCLUDED.sim_prob,
            team_abbr=EXCLUDED.team_abbr,
            recommendation=CASE
                WHEN daily_picks.bet_placed=1
                    THEN daily_picks.recommendation
                WHEN daily_picks.emailed=1
                     AND daily_picks.recommendation IN ('A_BET','B_BET','RECOMMENDED','LEAN')
                    THEN daily_picks.recommendation
                ELSE EXCLUDED.recommendation
            END
    """, pick)
    conn.commit()


def get_pending_picks(conn: PgConn, pick_date: str):
    return conn.execute(
        "SELECT * FROM daily_picks WHERE pick_date = %s AND result = 'PENDING'",
        (pick_date,)
    ).fetchall()


def update_pick_result(conn: PgConn, pick_id: int, result: str,
                       actual_stat: float, profit_units: float) -> None:
    conn.execute(
        "UPDATE daily_picks SET result=%s, actual_stat=%s, profit_units=%s WHERE id=%s",
        (result, actual_stat, profit_units, pick_id),
    )
    conn.commit()


def log_no_bet(conn: PgConn, entry: dict) -> None:
    conn.execute("""
        INSERT INTO no_bets_structural
            (logged_at, pick_date, event_id, player_name,
             market_key, selection, point, reason)
        VALUES
            (%(logged_at)s, %(pick_date)s, %(event_id)s, %(player_name)s,
             %(market_key)s, %(selection)s, %(point)s, %(reason)s)
    """, entry)
    conn.commit()


def mark_bet_placed(conn: PgConn, pick_id: int, units: float) -> None:
    conn.execute(
        "UPDATE daily_picks SET bet_placed=1, units_wagered=%s WHERE id=%s",
        (units, pick_id),
    )
    conn.commit()


def mark_bet_skipped(conn: PgConn, pick_id: int) -> None:
    conn.execute("UPDATE daily_picks SET bet_placed=-1 WHERE id=%s", (pick_id,))
    conn.commit()


def mark_game_bet_placed(conn: PgConn, pick_id: int, units: float) -> None:
    conn.execute(
        "UPDATE daily_game_picks SET bet_placed=1, units_wagered=%s WHERE id=%s",
        (units, pick_id),
    )
    conn.commit()


def mark_game_bet_skipped(conn: PgConn, pick_id: int) -> None:
    conn.execute("UPDATE daily_game_picks SET bet_placed=-1 WHERE id=%s", (pick_id,))
    conn.commit()


def update_pick_confidence(conn: PgConn, pick_id: int, score: int,
                           factors: list[str]) -> None:
    import json
    conn.execute(
        "UPDATE daily_picks SET confidence_score=%s, confidence_factors=%s WHERE id=%s",
        (score, json.dumps(factors), pick_id),
    )
    conn.commit()


def get_today_picks(conn: PgConn, pick_date: str) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM daily_picks WHERE pick_date=%s ORDER BY edge DESC",
        (pick_date,),
    ).fetchall()]


def get_active_bets(conn: PgConn) -> list[dict]:
    return [dict(r) for r in conn.execute("""
        SELECT pick_date, player_name, market_key, selection, point,
               bovada_price, edge, units_wagered, recommendation
        FROM daily_picks
        WHERE bet_placed=1 AND result='PENDING'
          AND recommendation IN ('A_BET','B_BET','LEAN','RECOMMENDED')
        UNION ALL
        SELECT pick_date,
               away_team || ' @ ' || home_team AS player_name,
               market_key, selection, point,
               bovada_price, edge, units_wagered, recommendation
        FROM daily_game_picks
        WHERE bet_placed=1 AND result='PENDING'
          AND recommendation IN ('A_BET','B_BET','LEAN','RECOMMENDED')
        ORDER BY pick_date DESC, edge DESC
    """).fetchall()]


def get_roi_by_market(conn: PgConn):
    return conn.execute("""
        SELECT market_key,
               COUNT(*) AS bets,
               SUM(CASE WHEN result='WIN'  THEN 1 ELSE 0 END) AS wins,
               SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) AS losses,
               SUM(CASE WHEN result='PUSH' THEN 1 ELSE 0 END) AS pushes,
               ROUND(100.0 * SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) /
                     NULLIF(SUM(CASE WHEN result IN ('WIN','LOSS') THEN 1 ELSE 0 END),0),1) AS win_pct,
               ROUND(SUM(COALESCE(profit_units,0))::numeric,2) AS net_units
        FROM (
            SELECT market_key, result, profit_units FROM daily_picks
            WHERE bet_placed=1 AND result != 'PENDING'
              AND recommendation IN ('A_BET','B_BET','LEAN','RECOMMENDED')
            UNION ALL
            SELECT market_key, result, profit_units FROM daily_game_picks
            WHERE bet_placed=1 AND result != 'PENDING'
              AND recommendation IN ('A_BET','B_BET','LEAN','RECOMMENDED')
        ) t
        GROUP BY market_key
        ORDER BY net_units DESC
    """).fetchall()


def get_roi_by_tier(conn: PgConn):
    return conn.execute("""
        SELECT recommendation,
               COUNT(*) AS bets,
               SUM(CASE WHEN result='WIN'  THEN 1 ELSE 0 END) AS wins,
               SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) AS losses,
               SUM(CASE WHEN result='PUSH' THEN 1 ELSE 0 END) AS pushes,
               ROUND(100.0 * SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) /
                     NULLIF(SUM(CASE WHEN result IN ('WIN','LOSS') THEN 1 ELSE 0 END),0),1) AS win_pct,
               ROUND(SUM(COALESCE(profit_units,0))::numeric,2) AS net_units
        FROM (
            SELECT CASE
                     WHEN recommendation='RECOMMENDED' THEN 'A_BET'
                     WHEN recommendation='LEAN' THEN 'B_BET'
                     ELSE recommendation
                   END AS recommendation,
                   result, profit_units
            FROM daily_picks
            WHERE bet_placed=1 AND result != 'PENDING'
              AND recommendation IN ('A_BET','B_BET','LEAN','RECOMMENDED')
            UNION ALL
            SELECT CASE
                     WHEN recommendation='RECOMMENDED' THEN 'A_BET'
                     WHEN recommendation='LEAN' THEN 'B_BET'
                     ELSE recommendation
                   END AS recommendation,
                   result, profit_units
            FROM daily_game_picks
            WHERE bet_placed=1 AND result != 'PENDING'
              AND recommendation IN ('A_BET','B_BET','LEAN','RECOMMENDED')
        ) t
        GROUP BY recommendation
        ORDER BY net_units DESC
    """).fetchall()


def update_pick_signal(conn: PgConn, pick_id: int, score: int,
                       breakdown: list[dict]) -> None:
    import json
    conn.execute(
        "UPDATE daily_picks SET signal_score=%s, signal_breakdown=%s WHERE id=%s",
        (score, json.dumps(breakdown), pick_id),
    )
    conn.commit()


def get_cumulative_pnl(conn: PgConn):
    return conn.execute("""
        SELECT pick_date,
               SUM(COALESCE(profit_units,0)) AS daily_units,
               SUM(SUM(COALESCE(profit_units,0))) OVER (ORDER BY pick_date) AS cumulative_units
        FROM (
            SELECT pick_date, profit_units FROM daily_picks
            WHERE bet_placed=1 AND result != 'PENDING'
              AND recommendation IN ('A_BET','B_BET','LEAN','RECOMMENDED')
            UNION ALL
            SELECT pick_date, profit_units FROM daily_game_picks
            WHERE bet_placed=1 AND result != 'PENDING'
              AND recommendation IN ('A_BET','B_BET','LEAN','RECOMMENDED')
        ) t
        GROUP BY pick_date
        ORDER BY pick_date
    """).fetchall()


def upsert_game_pick(conn: PgConn, pick: dict) -> None:
    pick = {**pick}
    pick.setdefault("signal_score", None)
    pick.setdefault("signal_breakdown", None)
    pick.setdefault("commence_time", None)
    pick.setdefault("bovada_break_even_prob", None)
    pick.setdefault("bovada_fair_prob", None)
    pick.setdefault("consensus_fair_prob", None)
    pick.setdefault("consensus_book_count", None)
    conn.execute("""
        INSERT INTO daily_game_picks
            (pick_date, pulled_at, event_id, commence_time, home_team, away_team,
             market_key, selection, point, bovada_price, bovada_break_even_prob,
             bovada_fair_prob, consensus_fair_prob, consensus_book_count,
             edge, recommendation, signal_score, signal_breakdown)
        VALUES
            (%(pick_date)s, %(pulled_at)s, %(event_id)s, %(commence_time)s,
             %(home_team)s, %(away_team)s, %(market_key)s, %(selection)s,
             %(point)s, %(bovada_price)s, %(bovada_break_even_prob)s,
             %(bovada_fair_prob)s, %(consensus_fair_prob)s, %(consensus_book_count)s,
             %(edge)s, %(recommendation)s, %(signal_score)s, %(signal_breakdown)s)
        ON CONFLICT(pick_date, event_id, market_key, selection) DO UPDATE SET
            bovada_price=EXCLUDED.bovada_price,
            bovada_break_even_prob=EXCLUDED.bovada_break_even_prob,
            bovada_fair_prob=EXCLUDED.bovada_fair_prob,
            consensus_fair_prob=EXCLUDED.consensus_fair_prob,
            consensus_book_count=EXCLUDED.consensus_book_count,
            edge=EXCLUDED.edge,
            signal_score=EXCLUDED.signal_score,
            signal_breakdown=EXCLUDED.signal_breakdown,
            recommendation=CASE
                WHEN daily_game_picks.emailed=1 OR daily_game_picks.bet_placed=1
                THEN daily_game_picks.recommendation
                ELSE EXCLUDED.recommendation
            END
    """, pick)
    conn.commit()


def get_pending_game_picks(conn: PgConn, pick_date: str):
    return conn.execute(
        "SELECT * FROM daily_game_picks WHERE pick_date=%s AND result='PENDING'",
        (pick_date,),
    ).fetchall()


def update_game_pick_result(conn: PgConn, pick_id: int, result: str,
                             home_runs: int, away_runs: int, actual_total: float,
                             profit_units: float) -> None:
    conn.execute("""
        UPDATE daily_game_picks
        SET result=%s, home_runs=%s, away_runs=%s, actual_total=%s, profit_units=%s
        WHERE id=%s
    """, (result, home_runs, away_runs, actual_total, profit_units, pick_id))
    conn.commit()


def void_missing_bovada_lines(conn: PgConn, pick_date: str, pulled_at: str) -> int:
    """Downgrade to NO_BET any unbet pick whose Bovada line is absent from the latest snapshot."""
    cur = conn.execute("""
        UPDATE daily_picks
        SET recommendation = 'NO_BET'
        WHERE pick_date = %s
          AND bet_placed = 0
          AND result = 'PENDING'
          AND recommendation != 'NO_BET'
          AND NOT EXISTS (
              SELECT 1 FROM props_snapshots ps
              WHERE ps.pulled_at    = %s
                AND ps.bookmaker_key = 'bovada'
                AND ps.event_id     = daily_picks.event_id
                AND ps.market_key   = daily_picks.market_key
                AND ps.player_name  = daily_picks.player_name
                AND ps.point        = daily_picks.point
          )
    """, (pick_date, pulled_at))
    n = cur.rowcount
    conn.commit()
    return n


def get_today_game_picks(conn: PgConn, pick_date: str) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM daily_game_picks WHERE pick_date=%s ORDER BY edge DESC",
        (pick_date,),
    ).fetchall()]
