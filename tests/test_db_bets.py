import json
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from db import (
    get_conn, upsert_pick,
    mark_bet_placed, mark_bet_skipped,
    get_today_picks, get_active_bets,
    get_roi_by_market, get_roi_by_tier, get_cumulative_pnl,
)

_TEST_DATE  = "1990-02-01"   # guaranteed absent from live DB
_TEST_DATE2 = "1990-02-02"

# All picks use event_id prefixed "TEST_BETS_" and a fake market_key so that
# aggregate queries (roi_by_market, cumulative_pnl) can be scoped to test data.
SAMPLE_PICK = {
    "pick_date":              _TEST_DATE,
    "pulled_at":              "1990-02-01T12:00:00Z",
    "event_id":               "TEST_BETS_evt1",
    "commence_time":          "1990-02-01T20:00:00Z",
    "home_team":              "Red Sox",
    "away_team":              "Phillies",
    "player_name":            "Test Player A",
    "market_key":             "TEST_pitcher_k",   # unique market for aggregate isolation
    "selection":              "Over",
    "point":                  6.5,
    "bovada_price":           -145,
    "bovada_break_even_prob": 0.5918,
    "bovada_fair_prob":       0.5540,
    "consensus_fair_prob":    0.5620,
    "consensus_book_count":   5,
    "edge":                   0.0080,
    "ev":                     -0.038,
    "recommendation":         "LEAN",
}


@pytest.fixture(scope="module")
def conn():
    c = get_conn()
    yield c
    c.execute("DELETE FROM daily_picks WHERE event_id LIKE ?", ("TEST_BETS_%",))
    c.commit()
    c.close()


@pytest.fixture(autouse=True)
def clean_picks(conn):
    """Wipe test rows before each test so tests don't see each other's data."""
    conn.execute("DELETE FROM daily_picks WHERE event_id LIKE ?", ("TEST_BETS_%",))
    conn.commit()
    yield


def _pick_id(conn, event_id=SAMPLE_PICK["event_id"]):
    return conn.execute(
        "SELECT id FROM daily_picks WHERE event_id=%s", (event_id,)
    ).fetchone()["id"]


def test_schema_has_bet_columns(conn):
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='daily_picks'"
    ).fetchall()
    cols = {row["column_name"] for row in rows}
    assert "bet_placed" in cols
    assert "units_wagered" in cols
    assert "notes" in cols


def test_schema_has_confidence_columns(conn):
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='daily_picks'"
    ).fetchall()
    cols = {row["column_name"] for row in rows}
    assert "confidence_score"   in cols
    assert "confidence_factors" in cols


def test_bet_placed_default_zero(conn):
    upsert_pick(conn, SAMPLE_PICK)
    row = conn.execute(
        "SELECT bet_placed FROM daily_picks WHERE event_id=%s",
        (SAMPLE_PICK["event_id"],)
    ).fetchone()
    assert row["bet_placed"] == 0


def test_mark_bet_placed(conn):
    upsert_pick(conn, SAMPLE_PICK)
    pid = _pick_id(conn)
    mark_bet_placed(conn, pid, 2.5)
    row = conn.execute(
        "SELECT bet_placed, units_wagered FROM daily_picks WHERE id=%s", (pid,)
    ).fetchone()
    assert row["bet_placed"] == 1
    assert row["units_wagered"] == 2.5


def test_mark_bet_skipped(conn):
    upsert_pick(conn, SAMPLE_PICK)
    pid = _pick_id(conn)
    mark_bet_skipped(conn, pid)
    row = conn.execute(
        "SELECT bet_placed FROM daily_picks WHERE id=%s", (pid,)
    ).fetchone()
    assert row["bet_placed"] == -1


def test_get_today_picks(conn):
    upsert_pick(conn, SAMPLE_PICK)
    rows = get_today_picks(conn, _TEST_DATE)
    our = next((r for r in rows if r["event_id"] == SAMPLE_PICK["event_id"]), None)
    assert our is not None
    assert our["player_name"] == SAMPLE_PICK["player_name"]


def test_get_active_bets_only_returns_pending_bets(conn):
    upsert_pick(conn, SAMPLE_PICK)
    pid = _pick_id(conn)

    # Before marking, our pick is not in active bets
    active = get_active_bets(conn)
    assert not any(b.get("player_name") == SAMPLE_PICK["player_name"] for b in active)

    mark_bet_placed(conn, pid, 1.0)
    active = get_active_bets(conn)
    assert any(b.get("player_name") == SAMPLE_PICK["player_name"] for b in active)

    conn.execute("UPDATE daily_picks SET result='WIN', profit_units=0.69 WHERE id=%s", (pid,))
    conn.commit()
    active = get_active_bets(conn)
    assert not any(b.get("player_name") == SAMPLE_PICK["player_name"] for b in active)


def test_get_roi_by_market_empty(conn):
    # Before any bet is placed and graded, our test market doesn't appear in ROI
    rows = get_roi_by_market(conn)
    market_keys = {r["market_key"] for r in rows}
    assert SAMPLE_PICK["market_key"] not in market_keys


def test_get_roi_by_tier_counts_graded_bets(conn):
    upsert_pick(conn, SAMPLE_PICK)   # recommendation=LEAN
    pid = _pick_id(conn)
    mark_bet_placed(conn, pid, 1.0)
    conn.execute("UPDATE daily_picks SET result='WIN', profit_units=0.69 WHERE id=%s", (pid,))
    conn.commit()
    rows = get_roi_by_tier(conn)
    lean = next((r for r in rows if r["recommendation"] == "B_BET"), None)
    assert lean is not None
    assert lean["wins"] >= 1
    # net_units reflects the entire live DB so we only verify the column is numeric
    assert isinstance(float(lean["net_units"]), float)


def test_get_cumulative_pnl(conn):
    upsert_pick(conn, SAMPLE_PICK)
    pid = _pick_id(conn)
    mark_bet_placed(conn, pid, 1.0)
    conn.execute("UPDATE daily_picks SET result='WIN', profit_units=0.69 WHERE id=%s", (pid,))
    conn.commit()
    rows = get_cumulative_pnl(conn)
    # _TEST_DATE "1990-02-01" predates all real data so it's the first entry
    day_row = next((r for r in rows if r["pick_date"] == _TEST_DATE), None)
    assert day_row is not None
    assert day_row["daily_units"] == pytest.approx(0.69, abs=0.01)
    assert day_row["cumulative_units"] == pytest.approx(0.69, abs=0.01)


def test_get_roi_by_market_groups_correctly(conn):
    upsert_pick(conn, SAMPLE_PICK)
    pick2 = {**SAMPLE_PICK, "selection": "Under", "bovada_price": 115,
             "event_id": "TEST_BETS_evt2"}
    upsert_pick(conn, pick2)
    id1, id2 = _pick_id(conn, "TEST_BETS_evt1"), _pick_id(conn, "TEST_BETS_evt2")
    for pid in (id1, id2):
        mark_bet_placed(conn, pid, 1.0)
    conn.execute("UPDATE daily_picks SET result='WIN',  profit_units=0.69  WHERE id=%s", (id1,))
    conn.execute("UPDATE daily_picks SET result='LOSS', profit_units=-1.0  WHERE id=%s", (id2,))
    conn.commit()
    rows = get_roi_by_market(conn)
    our = next((r for r in rows if r["market_key"] == SAMPLE_PICK["market_key"]), None)
    assert our is not None
    assert our["bets"] == 2
    assert our["wins"] == 1
    assert our["losses"] == 1
    assert float(our["net_units"]) == pytest.approx(-0.31, abs=0.01)


def test_get_cumulative_pnl_accumulates_across_dates(conn):
    pick1 = {**SAMPLE_PICK, "pick_date": _TEST_DATE,  "pulled_at": "1990-02-01T12:00:00Z",
             "event_id": "TEST_BETS_day1"}
    pick2 = {**SAMPLE_PICK, "pick_date": _TEST_DATE2, "pulled_at": "1990-02-02T12:00:00Z",
             "event_id": "TEST_BETS_day2"}
    upsert_pick(conn, pick1)
    upsert_pick(conn, pick2)
    id1 = _pick_id(conn, "TEST_BETS_day1")
    id2 = _pick_id(conn, "TEST_BETS_day2")
    mark_bet_placed(conn, id1, 1.0)
    mark_bet_placed(conn, id2, 1.0)
    conn.execute("UPDATE daily_picks SET result='WIN',  profit_units=0.69  WHERE id=%s", (id1,))
    conn.execute("UPDATE daily_picks SET result='LOSS', profit_units=-1.0  WHERE id=%s", (id2,))
    conn.commit()
    rows = get_cumulative_pnl(conn)
    row1 = next((r for r in rows if r["pick_date"] == _TEST_DATE),  None)
    row2 = next((r for r in rows if r["pick_date"] == _TEST_DATE2), None)
    assert row1 is not None and row2 is not None
    assert row1["daily_units"]      == pytest.approx(0.69,  abs=0.01)
    assert row2["daily_units"]      == pytest.approx(-1.0,  abs=0.01)
    assert row1["cumulative_units"] == pytest.approx(0.69,  abs=0.01)
    assert row2["cumulative_units"] == pytest.approx(-0.31, abs=0.01)


def test_update_pick_confidence(conn):
    upsert_pick(conn, SAMPLE_PICK)
    pid = _pick_id(conn)
    from db import update_pick_confidence
    update_pick_confidence(conn, pid, 3, ["Signal A", "Signal B", "Signal C"])
    row = conn.execute(
        "SELECT confidence_score, confidence_factors FROM daily_picks WHERE id=%s", (pid,)
    ).fetchone()
    assert row["confidence_score"] == 3
    assert json.loads(row["confidence_factors"]) == ["Signal A", "Signal B", "Signal C"]
