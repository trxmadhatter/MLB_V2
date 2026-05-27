"""
tests/test_run_daily_games.py — unit tests for _analyze_games and _print_game_summary
in run_daily.py.
"""
import io
import json
import sqlite3
import sys
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_totals_row(
    event_id="evt1",
    bookmaker_key="bovada",
    selection="Over",
    point=8.5,
    price=-110,
    player_name="",
    market_key="totals",
    home_team="New York Yankees",
    away_team="Boston Red Sox",
    commence_time="2026-05-17T18:00:00Z",
    pulled_at="2026-05-17T10:00:00",
):
    return {
        "event_id":      event_id,
        "bookmaker_key": bookmaker_key,
        "selection":     selection,
        "point":         point,
        "price":         price,
        "player_name":   player_name,
        "market_key":    market_key,
        "home_team":     home_team,
        "away_team":     away_team,
        "commence_time": commence_time,
        "pulled_at":     pulled_at,
    }


# ---------------------------------------------------------------------------
# Test 1: happy path — both Over and Under present, upsert called for each
# ---------------------------------------------------------------------------

def test_analyze_games_upserts_game_pick():
    rows = [
        _make_totals_row(bookmaker_key="bovada",   selection="Over",  price=-110),
        _make_totals_row(bookmaker_key="bovada",   selection="Under", price=-110),
        _make_totals_row(bookmaker_key="draftkings", selection="Over",  price=-108),
        _make_totals_row(bookmaker_key="draftkings", selection="Under", price=-112),
    ]

    conn = MagicMock()
    breakdown = [{"signal": "edge", "score": 5}]

    with patch("run_daily.get_snapshots", return_value=rows), \
         patch("run_daily.compute_consensus", return_value={
             "ok": True,
             "book_count": 2,
             "fair_prob_over": 0.50,
             "fair_prob_under": 0.50,
             "reason": None,
         }), \
         patch("run_daily.vig_remove_pair", return_value=(0.50, 0.50)), \
         patch("run_daily.bovada_break_even", return_value=0.5238), \
         patch("run_daily.compute_edge", return_value=0.023), \
         patch("run_daily.score_game_total", return_value=(70, breakdown)), \
         patch("run_daily.classify_by_score", return_value="RECOMMENDED"), \
         patch("run_daily.upsert_game_pick") as mock_upsert:

        from run_daily import _analyze_games
        games_eval, _ = _analyze_games(conn, "2026-05-17T10:00:00", "2026-05-17")

    assert games_eval == 2
    assert mock_upsert.call_count == 2

    calls = mock_upsert.call_args_list
    selections = {c[0][1]["selection"] for c in calls}
    assert selections == {"Over", "Under"}

    # Spot-check a field on the Over call
    over_pick = next(c[0][1] for c in calls if c[0][1]["selection"] == "Over")
    assert over_pick["recommendation"] == "RECOMMENDED"
    assert over_pick["signal_score"] == 70
    assert json.loads(over_pick["signal_breakdown"]) == breakdown


# ---------------------------------------------------------------------------
# Test 2: missing bovada Under — skip both sides, games_evaluated == 0
# ---------------------------------------------------------------------------

def test_analyze_games_skips_missing_bovada_side():
    rows = [
        # Only Over for bovada; no Under
        _make_totals_row(bookmaker_key="bovada",    selection="Over",  price=-110),
        _make_totals_row(bookmaker_key="draftkings", selection="Over",  price=-108),
        _make_totals_row(bookmaker_key="draftkings", selection="Under", price=-112),
    ]

    conn = MagicMock()

    with patch("run_daily.get_snapshots", return_value=rows), \
         patch("run_daily.upsert_game_pick") as mock_upsert:

        from run_daily import _analyze_games
        games_eval, _ = _analyze_games(conn, "2026-05-17T10:00:00", "2026-05-17")

    assert games_eval == 0
    mock_upsert.assert_not_called()


# ---------------------------------------------------------------------------
# Test 3: _print_game_summary with no LEAN/RECOMMENDED picks
# ---------------------------------------------------------------------------

def test_print_game_summary_no_picks(capsys):
    from run_daily import _print_game_summary

    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = []

    _print_game_summary(conn, "2026-05-17")

    captured = capsys.readouterr()
    assert "No game total picks today." in captured.out
