import sqlite3
from pathlib import Path

from config import DB_PATH


def get_conn(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS props_snapshots (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
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
        );

        CREATE INDEX IF NOT EXISTS idx_snap_pull_event
            ON props_snapshots(pulled_at, event_id, market_key, player_name, point);

        CREATE TABLE IF NOT EXISTS daily_picks (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            pick_date             TEXT NOT NULL,
            pulled_at             TEXT NOT NULL,
            event_id              TEXT NOT NULL,
            commence_time         TEXT NOT NULL,
            home_team             TEXT NOT NULL,
            away_team             TEXT NOT NULL,
            player_name           TEXT NOT NULL,
            market_key            TEXT NOT NULL,
            selection             TEXT NOT NULL,
            point                 REAL NOT NULL,
            bovada_price          INTEGER NOT NULL,
            bovada_break_even_prob REAL NOT NULL,
            consensus_fair_prob   REAL NOT NULL,
            consensus_book_count  INTEGER NOT NULL,
            edge                  REAL NOT NULL,
            ev                    REAL NOT NULL,
            recommendation        TEXT NOT NULL,
            result                TEXT NOT NULL DEFAULT 'PENDING',
            actual_stat           REAL,
            profit_units          REAL,
            UNIQUE(event_id, player_name, market_key, selection, point, pick_date)
        );

        CREATE TABLE IF NOT EXISTS no_bets_structural (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            logged_at   TEXT NOT NULL,
            pick_date   TEXT NOT NULL,
            event_id    TEXT NOT NULL,
            player_name TEXT NOT NULL,
            market_key  TEXT NOT NULL,
            selection   TEXT NOT NULL,
            point       REAL NOT NULL,
            reason      TEXT NOT NULL
        );
    """)
    conn.commit()


def insert_snapshots(conn: sqlite3.Connection, rows: list[dict]) -> int:
    conn.executemany("""
        INSERT INTO props_snapshots
            (pulled_at, event_id, commence_time, home_team, away_team,
             bookmaker_key, last_update, market_key, player_name,
             selection, point, price)
        VALUES
            (:pulled_at, :event_id, :commence_time, :home_team, :away_team,
             :bookmaker_key, :last_update, :market_key, :player_name,
             :selection, :point, :price)
    """, rows)
    conn.commit()
    return len(rows)


def get_snapshots(conn: sqlite3.Connection, pulled_at: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM props_snapshots WHERE pulled_at = ?", (pulled_at,)
    ).fetchall()


def upsert_pick(conn: sqlite3.Connection, pick: dict) -> None:
    conn.execute("""
        INSERT INTO daily_picks
            (pick_date, pulled_at, event_id, commence_time, home_team, away_team,
             player_name, market_key, selection, point, bovada_price,
             bovada_break_even_prob, consensus_fair_prob, consensus_book_count,
             edge, ev, recommendation)
        VALUES
            (:pick_date, :pulled_at, :event_id, :commence_time, :home_team, :away_team,
             :player_name, :market_key, :selection, :point, :bovada_price,
             :bovada_break_even_prob, :consensus_fair_prob, :consensus_book_count,
             :edge, :ev, :recommendation)
        ON CONFLICT(event_id, player_name, market_key, selection, point, pick_date)
        DO UPDATE SET
            bovada_price=excluded.bovada_price,
            bovada_break_even_prob=excluded.bovada_break_even_prob,
            consensus_fair_prob=excluded.consensus_fair_prob,
            consensus_book_count=excluded.consensus_book_count,
            edge=excluded.edge,
            ev=excluded.ev,
            recommendation=excluded.recommendation
    """, pick)
    conn.commit()


def get_pending_picks(conn: sqlite3.Connection, pick_date: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM daily_picks WHERE pick_date = ? AND result = 'PENDING'",
        (pick_date,)
    ).fetchall()


def update_pick_result(
    conn: sqlite3.Connection,
    pick_id: int,
    result: str,
    actual_stat: float,
    profit_units: float,
) -> None:
    conn.execute(
        "UPDATE daily_picks SET result=?, actual_stat=?, profit_units=? WHERE id=?",
        (result, actual_stat, profit_units, pick_id),
    )
    conn.commit()


def log_no_bet(conn: sqlite3.Connection, entry: dict) -> None:
    conn.execute("""
        INSERT INTO no_bets_structural
            (logged_at, pick_date, event_id, player_name,
             market_key, selection, point, reason)
        VALUES
            (:logged_at, :pick_date, :event_id, :player_name,
             :market_key, :selection, :point, :reason)
    """, entry)
    conn.commit()
