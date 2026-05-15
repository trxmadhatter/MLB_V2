import pytest
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from db import (
    get_conn, init_db, upsert_pick,
    mark_bet_placed, mark_bet_skipped,
    get_today_picks, get_active_bets,
    get_roi_by_market, get_roi_by_tier, get_cumulative_pnl,
)

SAMPLE_PICK = {
    "pick_date":              "2026-05-14",
    "pulled_at":              "2026-05-14T12:00:00Z",
    "event_id":               "evt1",
    "commence_time":          "2026-05-14T20:00:00Z",
    "home_team":              "Red Sox",
    "away_team":              "Phillies",
    "player_name":            "J. Luzardo",
    "market_key":             "pitcher_strikeouts",
    "selection":              "Over",
    "point":                  6.5,
    "bovada_price":           -145,
    "bovada_break_even_prob": 0.5918,
    "bovada_fair_prob":       0.5540,
    "consensus_fair_prob":    0.5620,
    "consensus_book_count":   5,
    "edge":                   0.0080,
    "ev":                     -0.038,
    "recommendation":         "NO_BET",
}


@pytest.fixture
def conn():
    c = get_conn(":memory:")
    init_db(c)
    return c


def test_schema_has_bet_columns(conn):
    cols = {row[1] for row in conn.execute("PRAGMA table_info(daily_picks)")}
    assert "bet_placed" in cols
    assert "units_wagered" in cols
    assert "notes" in cols


def test_bet_placed_default_zero(conn):
    upsert_pick(conn, SAMPLE_PICK)
    row = conn.execute("SELECT bet_placed FROM daily_picks").fetchone()
    assert row[0] == 0


def test_mark_bet_placed(conn):
    upsert_pick(conn, SAMPLE_PICK)
    pick_id = conn.execute("SELECT id FROM daily_picks").fetchone()[0]
    mark_bet_placed(conn, pick_id, 2.5)
    row = conn.execute("SELECT bet_placed, units_wagered FROM daily_picks").fetchone()
    assert row[0] == 1
    assert row[1] == 2.5


def test_mark_bet_skipped(conn):
    upsert_pick(conn, SAMPLE_PICK)
    pick_id = conn.execute("SELECT id FROM daily_picks").fetchone()[0]
    mark_bet_skipped(conn, pick_id)
    row = conn.execute("SELECT bet_placed FROM daily_picks").fetchone()
    assert row[0] == -1


def test_get_today_picks(conn):
    upsert_pick(conn, SAMPLE_PICK)
    rows = get_today_picks(conn, "2026-05-14")
    assert len(rows) == 1
    assert rows[0]["player_name"] == "J. Luzardo"


def test_get_active_bets_only_returns_pending_bets(conn):
    upsert_pick(conn, SAMPLE_PICK)
    pick_id = conn.execute("SELECT id FROM daily_picks").fetchone()[0]
    assert get_active_bets(conn) == []
    mark_bet_placed(conn, pick_id, 1.0)
    assert len(get_active_bets(conn)) == 1
    conn.execute("UPDATE daily_picks SET result='WIN', profit_units=0.69 WHERE id=?", (pick_id,))
    conn.commit()
    assert get_active_bets(conn) == []


def test_get_roi_by_market_empty(conn):
    assert get_roi_by_market(conn) == []


def test_get_roi_by_tier_counts_graded_bets(conn):
    upsert_pick(conn, SAMPLE_PICK)
    pick_id = conn.execute("SELECT id FROM daily_picks").fetchone()[0]
    mark_bet_placed(conn, pick_id, 1.0)
    conn.execute("UPDATE daily_picks SET result='WIN', profit_units=0.69 WHERE id=?", (pick_id,))
    conn.commit()
    rows = get_roi_by_tier(conn)
    assert len(rows) == 1
    assert rows[0]["wins"] == 1
    assert rows[0]["net_units"] == pytest.approx(0.69, abs=0.01)


def test_get_cumulative_pnl(conn):
    upsert_pick(conn, SAMPLE_PICK)
    pick_id = conn.execute("SELECT id FROM daily_picks").fetchone()[0]
    mark_bet_placed(conn, pick_id, 1.0)
    conn.execute("UPDATE daily_picks SET result='WIN', profit_units=0.69 WHERE id=?", (pick_id,))
    conn.commit()
    rows = get_cumulative_pnl(conn)
    assert len(rows) == 1
    assert rows[0]["cumulative_units"] == pytest.approx(0.69, abs=0.01)


def test_get_roi_by_market_groups_correctly(conn):
    # Two picks, same market, different results
    upsert_pick(conn, SAMPLE_PICK)
    pick2 = {**SAMPLE_PICK, "selection": "Under", "bovada_price": 115}
    upsert_pick(conn, pick2)
    ids = [r[0] for r in conn.execute("SELECT id FROM daily_picks").fetchall()]
    for pid in ids:
        mark_bet_placed(conn, pid, 1.0)
    conn.execute("UPDATE daily_picks SET result='WIN', profit_units=0.69 WHERE id=?", (ids[0],))
    conn.execute("UPDATE daily_picks SET result='LOSS', profit_units=-1.0 WHERE id=?", (ids[1],))
    conn.commit()
    rows = get_roi_by_market(conn)
    assert len(rows) == 1
    assert rows[0]["bets"] == 2
    assert rows[0]["wins"] == 1
    assert rows[0]["losses"] == 1
    assert rows[0]["net_units"] == pytest.approx(-0.31, abs=0.01)


def test_get_cumulative_pnl_accumulates_across_dates(conn):
    # Day 1 bet: WIN +0.69
    pick_day1 = {**SAMPLE_PICK, "pick_date": "2026-05-13", "pulled_at": "2026-05-13T12:00:00Z"}
    upsert_pick(conn, pick_day1)
    id1 = conn.execute("SELECT id FROM daily_picks WHERE pick_date='2026-05-13'").fetchone()[0]
    mark_bet_placed(conn, id1, 1.0)
    conn.execute("UPDATE daily_picks SET result='WIN', profit_units=0.69 WHERE id=?", (id1,))
    # Day 2 bet: LOSS -1.0
    pick_day2 = {**SAMPLE_PICK, "pick_date": "2026-05-14", "pulled_at": "2026-05-14T12:00:00Z"}
    upsert_pick(conn, pick_day2)
    id2 = conn.execute("SELECT id FROM daily_picks WHERE pick_date='2026-05-14'").fetchone()[0]
    mark_bet_placed(conn, id2, 1.0)
    conn.execute("UPDATE daily_picks SET result='LOSS', profit_units=-1.0 WHERE id=?", (id2,))
    conn.commit()
    rows = get_cumulative_pnl(conn)
    assert len(rows) == 2
    assert rows[0]["cumulative_units"] == pytest.approx(0.69, abs=0.01)
    assert rows[1]["cumulative_units"] == pytest.approx(-0.31, abs=0.01)


import json


def test_update_pick_confidence(conn):
    upsert_pick(conn, SAMPLE_PICK)
    pick_id = conn.execute("SELECT id FROM daily_picks").fetchone()[0]
    from db import update_pick_confidence
    update_pick_confidence(conn, pick_id, 3, ["Signal A", "Signal B", "Signal C"])
    row = conn.execute(
        "SELECT confidence_score, confidence_factors FROM daily_picks WHERE id=?", (pick_id,)
    ).fetchone()
    assert row[0] == 3
    assert json.loads(row[1]) == ["Signal A", "Signal B", "Signal C"]


def test_schema_has_confidence_columns(conn):
    cols = {row[1] for row in conn.execute("PRAGMA table_info(daily_picks)")}
    assert "confidence_score"   in cols
    assert "confidence_factors" in cols
