import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from scorer import (
    _edge_signal, _park_factor_signal, _ump_signal,
    _weather_signal, _clamp, score_pick,
)


def test_clamp():
    assert _clamp(1.5) == 1.0
    assert _clamp(-0.1) == 0.0
    assert _clamp(0.5) == 0.5


def test_edge_signal_positive():
    # 4% edge should be around 0.5
    assert 0.4 <= _edge_signal(0.04) <= 0.6


def test_edge_signal_negative():
    assert _edge_signal(-0.05) == 0.0


def test_edge_signal_max():
    assert _edge_signal(0.10) == 1.0


def test_park_k_over_high_k_park():
    # Coors has k_factor=92, should score low for K Over
    assert _park_factor_signal(92, "Over") < 0.4


def test_park_k_over_neutral():
    assert abs(_park_factor_signal(100, "Over") - 0.5) < 0.1


def test_park_k_under_high_k_park():
    # High K park (factor=108) should score low for K Under
    assert _park_factor_signal(108, "Under") < 0.4


def test_ump_signal_high_k_over():
    # High-K ump (+0.3) with K Over should score > 0.5
    assert _ump_signal(0.3, "Over") > 0.5


def test_ump_signal_low_k_under():
    # Low-K ump (-0.3) with K Under should score > 0.5
    assert _ump_signal(-0.3, "Under") > 0.5


def test_weather_neutral():
    w = {"tailwind_factor": 0.5, "cold_penalty": 0.0, "wind_speed_kph": 5}
    assert abs(_weather_signal(w, "Over") - 0.5) < 0.15


def test_score_pick_returns_tuple():
    result = score_pick(
        player_name="Test Player",
        market_key="pitcher_strikeouts",
        selection="Over",
        point=5.5,
        home_team="Colorado Rockies",
        away_team="Los Angeles Dodgers",
        edge=0.03,
        game_date="2026-05-15",
        game_data=None,
    )
    assert isinstance(result, tuple)
    score, breakdown = result
    assert 0 <= score <= 100
    assert isinstance(breakdown, list)
    assert all("signal" in b and "pts" in b for b in breakdown)
