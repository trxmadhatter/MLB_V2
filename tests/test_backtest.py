import sqlite3
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest import (
    init_backtest_db,
    _store_picks,
    _report_summary,
    _report_by_market,
    _report_by_edge_bucket,
)
from grade import grade_outcome, calc_profit


@pytest.fixture
def bt_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_backtest_db(conn)
    yield conn
    conn.close()


_SAMPLE_PICKS = [
    dict(pick_date="2026-04-20", player_name="Gerrit Cole",
         market_key="pitcher_strikeouts", selection="Over", point=7.5,
         bovada_price=-115, bovada_fair_prob=0.533, consensus_fair_prob=0.570,
         consensus_book_count=5, edge=0.037, ev=0.042, recommendation="LEAN",
         result="WIN", actual_stat=9.0, profit_units=0.870),
    dict(pick_date="2026-04-20", player_name="Aaron Judge",
         market_key="batter_hits", selection="Over", point=0.5,
         bovada_price=-130, bovada_fair_prob=0.565, consensus_fair_prob=0.615,
         consensus_book_count=4, edge=0.050, ev=0.058, recommendation="RECOMMENDED",
         result="LOSS", actual_stat=0.0, profit_units=-1.0),
    dict(pick_date="2026-04-21", player_name="Freddie Freeman",
         market_key="batter_total_bases", selection="Over", point=1.5,
         bovada_price=110, bovada_fair_prob=0.476, consensus_fair_prob=0.530,
         consensus_book_count=6, edge=0.054, ev=0.083, recommendation="RECOMMENDED",
         result="WIN", actual_stat=3.0, profit_units=1.10),
]


def test_init_backtest_db_creates_tables(bt_conn):
    tables = {row[0] for row in bt_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    assert "backtest_picks"  in tables
    assert "backtest_days"   in tables


def test_schema_has_required_columns(bt_conn):
    cols = {row[1] for row in bt_conn.execute("PRAGMA table_info(backtest_picks)")}
    for col in ["pick_date", "player_name", "market_key", "selection", "point",
                "bovada_price", "bovada_fair_prob", "consensus_fair_prob",
                "consensus_book_count", "edge", "ev", "recommendation",
                "result", "actual_stat", "profit_units"]:
        assert col in cols, f"Missing column: {col}"


def test_store_picks_inserts_rows(bt_conn):
    _store_picks(bt_conn, "2026-04-20", _SAMPLE_PICKS[:2])
    count = bt_conn.execute("SELECT COUNT(*) FROM backtest_picks").fetchone()[0]
    assert count == 2


def test_store_picks_idempotent(bt_conn):
    _store_picks(bt_conn, "2026-04-20", _SAMPLE_PICKS[:2])
    _store_picks(bt_conn, "2026-04-20", _SAMPLE_PICKS[:2])
    count = bt_conn.execute("SELECT COUNT(*) FROM backtest_picks").fetchone()[0]
    assert count == 2  # No duplicates


def test_report_summary_counts_wins_losses(bt_conn):
    for p in _SAMPLE_PICKS:
        _store_picks(bt_conn, p["pick_date"], [p])
    summary = _report_summary(bt_conn)
    rec = next(r for r in summary if r["recommendation"] == "RECOMMENDED")
    assert rec["wins"]      == 1
    assert rec["losses"]    == 1
    assert rec["pushes"]    == 0
    assert rec["total"]     == 2
    assert rec["win_pct"]   == pytest.approx(50.0, abs=0.1)
    # Aaron Judge LOSS: -1.0, Freddie Freeman WIN at +110: +1.10 → net = +0.10
    assert rec["net_units"] == pytest.approx(0.10, abs=0.01)
    lean = next(r for r in summary if r["recommendation"] == "LEAN")
    assert lean["wins"]     == 1
    assert lean["losses"]   == 0
    assert lean["total"]    == 1
    assert lean["win_pct"]  == pytest.approx(100.0, abs=0.1)
    # Gerrit Cole WIN at -115: profit = 100/115 ≈ 0.870
    assert lean["net_units"] == pytest.approx(0.870, abs=0.01)


def test_report_by_market_groups_correctly(bt_conn):
    for p in _SAMPLE_PICKS:
        _store_picks(bt_conn, p["pick_date"], [p])
    rows = _report_by_market(bt_conn)
    markets = {r["market_key"] for r in rows}
    assert "pitcher_strikeouts" in markets
    assert "batter_hits"        in markets
    assert "batter_total_bases" in markets


def test_report_by_edge_bucket_separates_lean_and_rec(bt_conn):
    # Add a 6%+ pick and a <2% pick to cover all 4 buckets
    extra_picks = [
        dict(pick_date="2026-04-22", player_name="Juan Soto",
             market_key="batter_hits", selection="Over", point=0.5,
             bovada_price=120, bovada_fair_prob=0.455, consensus_fair_prob=0.520,
             consensus_book_count=5, edge=0.065, ev=0.092, recommendation="RECOMMENDED",
             result="WIN", actual_stat=2.0, profit_units=1.20),
        dict(pick_date="2026-04-22", player_name="Pete Alonso",
             market_key="batter_hits", selection="Over", point=0.5,
             bovada_price=-110, bovada_fair_prob=0.524, consensus_fair_prob=0.533,
             consensus_book_count=4, edge=0.009, ev=0.012, recommendation="NO_BET",
             result="LOSS", actual_stat=0.0, profit_units=-1.0),
    ]
    for p in _SAMPLE_PICKS + extra_picks:
        _store_picks(bt_conn, p["pick_date"], [p])
    rows = _report_by_edge_bucket(bt_conn)
    buckets = [r["bucket"] for r in rows]
    # All 4 buckets present
    assert any("6%" in b for b in buckets),   f"Missing 6%+ bucket: {buckets}"
    assert any("4-6" in b for b in buckets),   f"Missing 4-6% bucket: {buckets}"
    assert any("2-4" in b for b in buckets),   f"Missing 2-4% bucket: {buckets}"
    assert any("2%" in b and "<" in b for b in buckets), f"Missing <2% bucket: {buckets}"
    # 6%+ bucket should come first (highest edge), <2% last
    assert "6%" in buckets[0]
    assert "<" in buckets[-1] and "2%" in buckets[-1]


def test_grade_outcome_and_calc_profit_roundtrip():
    assert grade_outcome("Over", 7.5, 9.0) == "WIN"
    assert abs(calc_profit("WIN", -115) - 100/115) < 1e-6
    assert calc_profit("LOSS", -115) == -1.0
