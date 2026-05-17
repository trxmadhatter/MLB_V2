"""Tests for scorer_game.py — game Over/Under totals scorer."""

import pytest
from unittest.mock import patch, MagicMock
from scorer_game import (
    score_game_total,
    _sp_quality_signal,
    _team_offense_signal,
    _ump_run_signal,
    _park_run_signal,
)

_NEUTRAL_OFFENSE = {"runs_per_game": 4.5, "ops": 0.720}
_NEUTRAL_WEATHER = {
    "wind_speed_kph": 0.0,
    "wind_direction_deg": 0,
    "temp_c": 20.0,
    "precip_mm": 0.0,
    "tailwind_factor": 0.5,
    "cold_penalty": 0.0,
    "is_dome": False,
}


class TestUmpRunSignal:
    def test_wide_zone_good_for_under(self):
        assert _ump_run_signal(0.5, "Under") > 0.5

    def test_wide_zone_bad_for_over(self):
        assert _ump_run_signal(0.5, "Over") < 0.5

    def test_neutral(self):
        assert abs(_ump_run_signal(0.0, "Over") - 0.5) < 0.01

    def test_symmetry(self):
        assert abs(_ump_run_signal(0.3, "Over") + _ump_run_signal(0.3, "Under") - 1.0) < 0.001


class TestParkRunSignal:
    def test_hitter_park_over(self):
        park = {"hr_factor": 115, "hits_factor": 110}
        assert _park_run_signal(park, "Over") > 0.5

    def test_pitcher_park_under(self):
        park = {"hr_factor": 85, "hits_factor": 90}
        assert _park_run_signal(park, "Under") > 0.5

    def test_neutral_park(self):
        park = {"hr_factor": 100, "hits_factor": 100}
        assert abs(_park_run_signal(park, "Over") - 0.5) < 0.05


class TestSpQualitySignal:
    def test_great_pitcher_under(self):
        sp = {"era": 2.5, "whip": 0.90, "id": None}
        raw, _ = _sp_quality_signal(sp, 2026, "Under")
        assert raw > 0.5

    def test_bad_pitcher_over(self):
        sp = {"era": 6.5, "whip": 1.70, "id": None}
        raw, _ = _sp_quality_signal(sp, 2026, "Over")
        assert raw > 0.5

    def test_no_data_neutral(self):
        raw, note = _sp_quality_signal({}, 2026, "Over")
        assert abs(raw - 0.5) < 0.01
        assert note == "no_data"

    def test_symmetry(self):
        sp = {"era": 4.5, "whip": 1.25, "id": None}
        over, _ = _sp_quality_signal(sp, 2026, "Over")
        under, _ = _sp_quality_signal(sp, 2026, "Under")
        assert abs(over + under - 1.0) < 0.001


@pytest.fixture(autouse=False)
def mock_network():
    """Patch all live network calls used by score_game_total."""
    with patch("signals.team_stats.get_team_offense", return_value=_NEUTRAL_OFFENSE), \
         patch("signals.weather.get_weather", return_value=_NEUTRAL_WEATHER), \
         patch("signals.statcast._load_pitchers", return_value={}):
        yield


class TestScoreGameTotal:
    def test_returns_score_and_breakdown(self, mock_network):
        score, breakdown = score_game_total(
            "New York Yankees", "Boston Red Sox",
            "Over", 8.5, 0.03, "2026-05-17", None
        )
        assert 0 <= score <= 100
        assert len(breakdown) == 8
        assert all("signal" in item and "pts" in item for item in breakdown)

    def test_score_equals_sum_of_pts(self, mock_network):
        score, breakdown = score_game_total(
            "Boston Red Sox", "New York Yankees",
            "Under", 8.5, 0.02, "2026-05-17", None
        )
        assert score == sum(item["pts"] for item in breakdown)

    def test_score_clamped(self, mock_network):
        score, _ = score_game_total(
            "Colorado Rockies", "Arizona Diamondbacks",
            "Over", 10.5, 0.10, "2026-05-17", None
        )
        assert 0 <= score <= 100

    def test_no_game_data_still_scores(self, mock_network):
        score, breakdown = score_game_total(
            "Houston Astros", "Texas Rangers",
            "Under", 7.5, 0.02, "2026-05-17", game_data=None
        )
        assert isinstance(score, int)
        assert len(breakdown) == 8
