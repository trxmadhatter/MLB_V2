import sqlite3
import pytest
from db import get_conn, init_db, upsert_game_pick, get_pending_game_picks, update_game_pick_result, get_today_game_picks

@pytest.fixture
def conn(tmp_path):
    db = tmp_path / "test.db"
    c = get_conn(db)
    init_db(c)
    yield c
    c.close()

_PICK = {
    "pick_date": "2026-05-17",
    "pulled_at": "2026-05-17T15:00:00Z",
    "event_id": "evt1",
    "commence_time": "2026-05-17T18:00:00Z",
    "home_team": "New York Yankees",
    "away_team": "Boston Red Sox",
    "market_key": "totals",
    "selection": "Over",
    "point": 8.5,
    "bovada_price": -110,
    "bovada_break_even_prob": 0.5238,
    "bovada_fair_prob": 0.5,
    "consensus_fair_prob": 0.55,
    "consensus_book_count": 5,
    "edge": 0.03,
    "recommendation": "LEAN",
    "signal_score": 55,
    "signal_breakdown": "[]",
}

def test_upsert_and_retrieve(conn):
    upsert_game_pick(conn, _PICK)
    rows = get_today_game_picks(conn, "2026-05-17")
    assert len(rows) == 1
    assert rows[0]["selection"] == "Over"
    assert rows[0]["result"] == "PENDING"

def test_upsert_updates_on_conflict(conn):
    upsert_game_pick(conn, _PICK)
    updated = {**_PICK, "edge": 0.05, "recommendation": "RECOMMENDED"}
    upsert_game_pick(conn, updated)
    rows = get_today_game_picks(conn, "2026-05-17")
    assert len(rows) == 1
    assert rows[0]["recommendation"] == "RECOMMENDED"

def test_get_pending_game_picks(conn):
    upsert_game_pick(conn, _PICK)
    pending = get_pending_game_picks(conn, "2026-05-17")
    assert len(pending) == 1

def test_update_game_pick_result(conn):
    upsert_game_pick(conn, _PICK)
    pick_id = get_today_game_picks(conn, "2026-05-17")[0]["id"]
    update_game_pick_result(conn, pick_id, "WIN", 5, 4, 9.0, 0.909)
    rows = get_today_game_picks(conn, "2026-05-17")
    assert rows[0]["result"] == "WIN"
    assert rows[0]["home_runs"] == 5
    assert rows[0]["away_runs"] == 4
    assert abs(rows[0]["actual_total"] - 9.0) < 0.01

def test_pending_excludes_graded(conn):
    upsert_game_pick(conn, _PICK)
    pick_id = get_today_game_picks(conn, "2026-05-17")[0]["id"]
    update_game_pick_result(conn, pick_id, "WIN", 5, 4, 9.0, 0.909)
    pending = get_pending_game_picks(conn, "2026-05-17")
    assert len(pending) == 0
