import json
import sqlite3

import pytest

from backtest import init_backtest_db


@pytest.fixture
def bt_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_backtest_db(conn)
    return conn


def _insert(conn, picks):
    conn.executemany(
        """
        INSERT INTO backtest_picks
            (pick_date, player_name, market_key, selection, point,
             bovada_price, bovada_fair_prob, consensus_fair_prob,
             consensus_book_count, edge, ev, recommendation,
             result, actual_stat, profit_units)
        VALUES
            (:pick_date, :player_name, :market_key, :selection, :point,
             :bovada_price, :bovada_fair_prob, :consensus_fair_prob,
             :consensus_book_count, :edge, :ev, :recommendation,
             :result, :actual_stat, :profit_units)
        """,
        picks,
    )
    conn.commit()


_pick_counter = 0


def _p(**kw):
    global _pick_counter
    _pick_counter += 1
    base = dict(
        pick_date="2026-05-01", player_name=f"Player {_pick_counter}",
        market_key="pitcher_strikeouts", selection="Over", point=5.5,
        bovada_price=-115, bovada_fair_prob=0.535, consensus_fair_prob=0.575,
        consensus_book_count=4, edge=0.03, ev=0.02, recommendation="LEAN",
        result="WIN", actual_stat=7.0, profit_units=0.87,
    )
    base.update(kw)
    return base


class TestComputeCalibration:
    def test_empty_db_returns_empty(self, bt_conn):
        from market_learn import compute_calibration
        assert compute_calibration(bt_conn) == []

    def test_below_min_sample_excluded(self, bt_conn):
        from market_learn import compute_calibration
        _insert(bt_conn, [_p() for _ in range(19)])  # 19 < MIN_SAMPLE of 20
        assert compute_calibration(bt_conn) == []

    def test_at_min_sample_included(self, bt_conn):
        from market_learn import compute_calibration
        _insert(bt_conn, [_p() for _ in range(20)])
        assert len(compute_calibration(bt_conn)) == 1

    def test_profitable_when_win_rate_above_breakeven(self, bt_conn):
        # -115 breakeven = 115/215 = 53.5%
        # 15W / 5L = 75% win rate -> profitable
        from market_learn import compute_calibration
        picks = (
            [_p(result="WIN",  profit_units=0.87) for _ in range(15)]
            + [_p(result="LOSS", profit_units=-1.0) for _ in range(5)]
        )
        _insert(bt_conn, picks)
        cal = compute_calibration(bt_conn)
        assert cal[0]["profitable"] is True
        assert abs(cal[0]["win_rate"] - 0.75) < 0.001

    def test_unprofitable_when_win_rate_below_breakeven(self, bt_conn):
        # 10W / 10L = 50% < 53.5% breakeven
        from market_learn import compute_calibration
        picks = (
            [_p(result="WIN",  profit_units=0.87) for _ in range(10)]
            + [_p(result="LOSS", profit_units=-1.0) for _ in range(10)]
        )
        _insert(bt_conn, picks)
        cal = compute_calibration(bt_conn)
        assert cal[0]["profitable"] is False

    def test_sorted_best_first(self, bt_conn):
        from market_learn import compute_calibration
        ko = (
            [_p(market_key="pitcher_strikeouts", result="WIN",  profit_units=0.87) for _ in range(15)]
            + [_p(market_key="pitcher_strikeouts", result="LOSS", profit_units=-1.0) for _ in range(5)]
        )
        tb = (
            [_p(market_key="batter_total_bases", result="WIN",  profit_units=0.87) for _ in range(8)]
            + [_p(market_key="batter_total_bases", result="LOSS", profit_units=-1.0) for _ in range(12)]
        )
        _insert(bt_conn, ko + tb)
        cal = compute_calibration(bt_conn)
        assert cal[0]["market_key"] == "pitcher_strikeouts"
        assert cal[-1]["market_key"] == "batter_total_bases"

    def test_pushes_excluded_from_win_rate_calc(self, bt_conn):
        # 15W / 5L / 5P -> win rate = 15/20 = 75%, not 15/25 = 60%
        # 20 decided (W+L) satisfies MIN_SAMPLE
        from market_learn import compute_calibration
        picks = (
            [_p(result="WIN",  profit_units=0.87)  for _ in range(15)]
            + [_p(result="LOSS", profit_units=-1.0) for _ in range(5)]
            + [_p(result="PUSH", profit_units=0.0)  for _ in range(5)]
        )
        _insert(bt_conn, picks)
        cal = compute_calibration(bt_conn)
        assert abs(cal[0]["win_rate"] - 15 / 20) < 0.001


class TestSaveLoadCalibration:
    def test_roundtrip(self, tmp_path):
        from market_learn import save_calibration, load_calibration
        data = [{"market_key": "pitcher_strikeouts", "win_rate": 0.563, "profitable": True}]
        path = tmp_path / "cal.json"
        save_calibration(data, path)
        assert load_calibration(path) == data

    def test_load_missing_file_returns_empty(self, tmp_path):
        from market_learn import load_calibration
        assert load_calibration(tmp_path / "nofile.json") == []


class TestInsightText:
    def test_profitable_signal_contains_key_info(self):
        from market_learn import insight_text
        row = {
            "market_key": "pitcher_strikeouts", "selection": "Over",
            "edge_bucket": "2-4%", "wins": 22, "losses": 17,
            "win_rate": 0.564, "breakeven": 0.524, "edge_vs_breakeven": 0.040,
            "net_units": 4.69, "profitable": True,
        }
        text = insight_text(row)
        assert "pitcher_strikeouts" in text
        assert "Over" in text
        assert "56.4%" in text
