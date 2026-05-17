"""Tests for signals/team_stats.py"""
import pytest
from unittest.mock import patch, MagicMock

import signals.team_stats as ts


MOCK_RESPONSE = {
    "stats": [{
        "splits": [
            {
                "team": {"name": "New York Yankees"},
                "stat": {"runsPerGame": "5.2", "ops": ".780"}
            },
            {
                "team": {"name": "Boston Red Sox"},
                "stat": {"runsPerGame": "4.8", "ops": ".750"}
            },
        ]
    }]
}


def _mock_get(url, **kwargs):
    mock = MagicMock()
    mock.raise_for_status.return_value = None
    mock.json.return_value = MOCK_RESPONSE
    return mock


@pytest.fixture(autouse=True)
def clear_cache():
    ts.reset_cache()
    yield
    ts.reset_cache()


def test_exact_match():
    with patch("signals.team_stats.requests.get", side_effect=_mock_get):
        result = ts.get_team_offense("New York Yankees", 2024)
    assert result["runs_per_game"] == pytest.approx(5.2)
    assert result["ops"] == pytest.approx(0.780)


def test_fuzzy_match():
    with patch("signals.team_stats.requests.get", side_effect=_mock_get):
        result = ts.get_team_offense("Yankees", 2024)
    assert result["runs_per_game"] == pytest.approx(5.2)
    assert result["ops"] == pytest.approx(0.780)


def test_unknown_team_returns_none():
    with patch("signals.team_stats.requests.get", side_effect=_mock_get):
        result = ts.get_team_offense("Nonexistent Team", 2024)
    assert result["runs_per_game"] is None
    assert result["ops"] is None


def test_api_failure_returns_none():
    with patch("signals.team_stats.requests.get", side_effect=Exception("network error")):
        result = ts.get_team_offense("New York Yankees", 2024)
    assert result["runs_per_game"] is None
    assert result["ops"] is None
