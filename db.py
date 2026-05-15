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
            bovada_fair_prob      REAL NOT NULL DEFAULT 0,
            consensus_fair_prob   REAL NOT NULL,
            consensus_book_count  INTEGER NOT NULL,
            edge                  REAL NOT NULL,
            ev                    REAL NOT NULL,
            recommendation        TEXT NOT NULL,
            result                TEXT NOT NULL DEFAULT 'PENDING',
            actual_stat           REAL,
            profit_units          REAL,
            bet_placed            INTEGER NOT NULL DEFAULT 0,
            units_wagered         REAL,
            notes                 TEXT,
            confidence_score      INTEGER,
            confidence_factors    TEXT,
            signal_score          INTEGER,
            signal_breakdown      TEXT,
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
    try:
        conn.execute("ALTER TABLE daily_picks ADD COLUMN bovada_fair_prob REAL NOT NULL DEFAULT 0")
        conn.commit()
    except Exception:
        pass
    for col_sql in [
        "ALTER TABLE daily_picks ADD COLUMN bet_placed INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE daily_picks ADD COLUMN units_wagered REAL",
        "ALTER TABLE daily_picks ADD COLUMN notes TEXT",
    ]:
        try:
            conn.execute(col_sql)
            conn.commit()
        except sqlite3.OperationalError:
            pass
    for col_sql in [
        "ALTER TABLE daily_picks ADD COLUMN confidence_score INTEGER",
        "ALTER TABLE daily_picks ADD COLUMN confidence_factors TEXT",
    ]:
        try:
            conn.execute(col_sql)
            conn.commit()
        except sqlite3.OperationalError:
            pass
    for col_sql in [
        "ALTER TABLE daily_picks ADD COLUMN signal_score INTEGER",
        "ALTER TABLE daily_picks ADD COLUMN signal_breakdown TEXT",
    ]:
        try:
            conn.execute(col_sql)
            conn.commit()
        except sqlite3.OperationalError:
            pass


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
    pick = {**pick}
    pick.setdefault("signal_score", None)
    pick.setdefault("signal_breakdown", None)
    conn.execute("""
        INSERT INTO daily_picks
            (pick_date, pulled_at, event_id, commence_time, home_team, away_team,
             player_name, market_key, selection, point, bovada_price,
             bovada_break_even_prob, bovada_fair_prob, consensus_fair_prob,
             consensus_book_count, edge, ev, recommendation,
             signal_score, signal_breakdown)
        VALUES
            (:pick_date, :pulled_at, :event_id, :commence_time, :home_team, :away_team,
             :player_name, :market_key, :selection, :point, :bovada_price,
             :bovada_break_even_prob, :bovada_fair_prob, :consensus_fair_prob,
             :consensus_book_count, :edge, :ev, :recommendation,
             :signal_score, :signal_breakdown)
        ON CONFLICT(event_id, player_name, market_key, selection, point, pick_date)
        DO UPDATE SET
            bovada_price=excluded.bovada_price,
            bovada_break_even_prob=excluded.bovada_break_even_prob,
            bovada_fair_prob=excluded.bovada_fair_prob,
            consensus_fair_prob=excluded.consensus_fair_prob,
            consensus_book_count=excluded.consensus_book_count,
            edge=excluded.edge,
            ev=excluded.ev,
            recommendation=excluded.recommendation,
            signal_score=excluded.signal_score,
            signal_breakdown=excluded.signal_breakdown
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


def mark_bet_placed(conn: sqlite3.Connection, pick_id: int, units: float) -> None:
    conn.execute(
        "UPDATE daily_picks SET bet_placed=1, units_wagered=? WHERE id=?",
        (units, pick_id),
    )
    conn.commit()


def mark_bet_skipped(conn: sqlite3.Connection, pick_id: int) -> None:
    conn.execute("UPDATE daily_picks SET bet_placed=-1 WHERE id=?", (pick_id,))
    conn.commit()


def update_pick_confidence(
    conn: sqlite3.Connection,
    pick_id: int,
    score: int,
    factors: list[str],
) -> None:
    import json
    conn.execute(
        "UPDATE daily_picks SET confidence_score=?, confidence_factors=? WHERE id=?",
        (score, json.dumps(factors), pick_id),
    )
    conn.commit()


def get_today_picks(conn: sqlite3.Connection, pick_date: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM daily_picks WHERE pick_date=? ORDER BY edge DESC",
        (pick_date,),
    ).fetchall()


def get_active_bets(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("""
        SELECT * FROM daily_picks
        WHERE bet_placed=1 AND result='PENDING'
        ORDER BY pick_date DESC, edge DESC
    """).fetchall()


def get_roi_by_market(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("""
        SELECT market_key,
               COUNT(*) AS bets,
               SUM(CASE WHEN result='WIN'  THEN 1 ELSE 0 END) AS wins,
               SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) AS losses,
               SUM(CASE WHEN result='PUSH' THEN 1 ELSE 0 END) AS pushes,
               ROUND(100.0 * SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) /
                     NULLIF(SUM(CASE WHEN result IN ('WIN','LOSS') THEN 1 ELSE 0 END),0),1) AS win_pct,
               ROUND(SUM(CASE WHEN result NOT IN ('PENDING') THEN COALESCE(profit_units,0) ELSE 0 END),2) AS net_units
        FROM daily_picks
        WHERE bet_placed=1 AND result != 'PENDING'
        GROUP BY market_key
        ORDER BY net_units DESC
    """).fetchall()


def get_roi_by_tier(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("""
        SELECT recommendation,
               COUNT(*) AS bets,
               SUM(CASE WHEN result='WIN'  THEN 1 ELSE 0 END) AS wins,
               SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) AS losses,
               SUM(CASE WHEN result='PUSH' THEN 1 ELSE 0 END) AS pushes,
               ROUND(100.0 * SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) /
                     NULLIF(SUM(CASE WHEN result IN ('WIN','LOSS') THEN 1 ELSE 0 END),0),1) AS win_pct,
               ROUND(SUM(CASE WHEN result NOT IN ('PENDING') THEN COALESCE(profit_units,0) ELSE 0 END),2) AS net_units
        FROM daily_picks
        WHERE bet_placed=1 AND result != 'PENDING'
        GROUP BY recommendation
        ORDER BY net_units DESC
    """).fetchall()


def update_pick_signal(
    conn: sqlite3.Connection,
    pick_id: int,
    score: int,
    breakdown: list[dict],
) -> None:
    import json
    conn.execute(
        "UPDATE daily_picks SET signal_score=?, signal_breakdown=? WHERE id=?",
        (score, json.dumps(breakdown), pick_id),
    )
    conn.commit()


def get_cumulative_pnl(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("""
        SELECT pick_date,
               SUM(COALESCE(profit_units,0)) AS daily_units,
               SUM(SUM(COALESCE(profit_units,0))) OVER (ORDER BY pick_date) AS cumulative_units
        FROM daily_picks
        WHERE bet_placed=1 AND result != 'PENDING'
        GROUP BY pick_date
        ORDER BY pick_date
    """).fetchall()
