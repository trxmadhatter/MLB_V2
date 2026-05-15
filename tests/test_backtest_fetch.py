import pytest
from unittest.mock import MagicMock, patch
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest_fetch import (
    fetch_historical_events,
    fetch_historical_event_odds,
    pull_historical_snapshots,
)

_EVENTS_RESPONSE = {
    "timestamp": "2026-05-01T12:00:00Z",
    "data": [
        {"id": "abc123", "sport_key": "baseball_mlb", "commence_time": "2026-05-01T17:10:00Z",
         "home_team": "New York Yankees", "away_team": "Boston Red Sox"},
        {"id": "def456", "sport_key": "baseball_mlb", "commence_time": "2026-05-01T20:10:00Z",
         "home_team": "Los Angeles Dodgers", "away_team": "San Francisco Giants"},
    ],
}

_ODDS_RESPONSE_abc123 = {
    "timestamp": "2026-05-01T12:00:00Z",
    "data": {
        "id": "abc123",
        "commence_time": "2026-05-01T17:10:00Z",
        "home_team": "New York Yankees",
        "away_team": "Boston Red Sox",
        "bookmakers": [
            {
                "key": "bovada", "last_update": "2026-05-01T11:55:00Z",
                "markets": [{"key": "pitcher_strikeouts", "outcomes": [
                    {"name": "Over",  "description": "Gerrit Cole", "point": 7.5, "price": -115},
                    {"name": "Under", "description": "Gerrit Cole", "point": 7.5, "price": -105},
                ]}],
            },
            {
                "key": "draftkings", "last_update": "2026-05-01T11:58:00Z",
                "markets": [{"key": "pitcher_strikeouts", "outcomes": [
                    {"name": "Over",  "description": "Gerrit Cole", "point": 7.5, "price": -120},
                    {"name": "Under", "description": "Gerrit Cole", "point": 7.5, "price": 100},
                ]}],
            },
        ],
    },
}


def _mock_get(*responses):
    it = iter(responses)
    def _side(*a, **kw):
        m = MagicMock()
        m.raise_for_status = MagicMock()
        m.json.return_value = next(it)
        m.headers = {"x-requests-remaining": "499", "x-requests-used": "1"}
        return m
    return MagicMock(side_effect=_side)


def test_fetch_historical_events_returns_event_list():
    with patch("backtest_fetch.requests.get", _mock_get(_EVENTS_RESPONSE)):
        events = fetch_historical_events("FAKE_KEY", "2026-05-01")
    assert len(events) == 2
    assert events[0]["id"] == "abc123"
    assert events[1]["home_team"] == "Los Angeles Dodgers"


def test_fetch_historical_events_passes_correct_params():
    mock = _mock_get(_EVENTS_RESPONSE)
    with patch("backtest_fetch.requests.get", mock):
        fetch_historical_events("FAKE_KEY", "2026-05-01", odds_time="09:00:00")
    params = mock.call_args.kwargs["params"]
    assert "2026-05-01" in str(params.get("date", ""))
    assert "09:00:00" in str(params.get("date", ""))


def test_fetch_historical_event_odds_returns_event_with_bookmakers():
    with patch("backtest_fetch.requests.get", _mock_get(_ODDS_RESPONSE_abc123)):
        event = fetch_historical_event_odds("FAKE_KEY", "abc123", "2026-05-01T12:00:00Z")
    assert event["id"] == "abc123"
    assert len(event["bookmakers"]) == 2
    assert event["bookmakers"][0]["key"] == "bovada"


def test_fetch_historical_event_odds_passes_correct_params():
    mock = _mock_get(_ODDS_RESPONSE_abc123)
    with patch("backtest_fetch.requests.get", mock):
        fetch_historical_event_odds("FAKE_KEY", "abc123", "2026-05-01T12:00:00Z")
    params = mock.call_args.kwargs["params"]
    assert params["date"]       == "2026-05-01T12:00:00Z"
    assert params["apiKey"]     == "FAKE_KEY"
    assert params["regions"]    == "us"
    assert params["oddsFormat"] == "american"
    # All V1 markets included
    from config import V1_MARKETS
    for mkt in V1_MARKETS:
        assert mkt in params["markets"]


def test_fetch_historical_event_odds_missing_data_key_raises():
    bad_response = {"timestamp": "...", "something_else": {}}
    with patch("backtest_fetch.requests.get", _mock_get(bad_response)):
        with pytest.raises(KeyError):
            fetch_historical_event_odds("FAKE_KEY", "abc123", "2026-05-01T12:00:00Z")


def test_pull_historical_snapshots_returns_flat_rows():
    empty_odds = {"timestamp": "...", "data": {
        "id": "def456", "commence_time": "2026-05-01T20:10:00Z",
        "home_team": "Los Angeles Dodgers", "away_team": "San Francisco Giants",
        "bookmakers": [],
    }}
    mock = _mock_get(_EVENTS_RESPONSE, _ODDS_RESPONSE_abc123, empty_odds)
    with patch("backtest_fetch.requests.get", mock):
        pulled_at, rows = pull_historical_snapshots("FAKE_KEY", "2026-05-01")
    assert len(rows) == 4
    assert all(r["event_id"] == "abc123" for r in rows)
    assert all(r["player_name"] == "Gerrit Cole" for r in rows)
    assert {r["bookmaker_key"] for r in rows} == {"bovada", "draftkings"}
    assert "2026-05-01" in pulled_at


def test_pull_historical_snapshots_http_error_raises():
    m = MagicMock()
    m.return_value.raise_for_status.side_effect = Exception("403 Forbidden")
    with patch("backtest_fetch.requests.get", m):
        with pytest.raises(Exception, match="403"):
            pull_historical_snapshots("BAD_KEY", "2026-05-01")


def test_pull_historical_snapshots_empty_events_returns_no_rows():
    empty_events = {"timestamp": "2026-01-15T12:00:00Z", "data": []}
    mock = _mock_get(empty_events)
    with patch("backtest_fetch.requests.get", mock):
        pulled_at, rows = pull_historical_snapshots("FAKE_KEY", "2026-01-15")
    assert rows == []
    assert "2026-01-15" in pulled_at


def test_parse_snapshots_accepts_markets_filter():
    """parse_snapshots with markets=[...] only emits rows for listed markets."""
    from pull_props import parse_snapshots
    event = {
        "id": "abc", "commence_time": "2026-05-01T18:00:00Z",
        "home_team": "Cubs", "away_team": "Cardinals",
        "bookmakers": [{
            "key": "draftkings", "last_update": None,
            "markets": [
                {
                    "key": "pitcher_strikeouts",
                    "outcomes": [{"name": "Over", "description": "G. Cole", "point": 7.5, "price": -115}],
                },
                {
                    "key": "batter_home_runs",
                    "outcomes": [{"name": "Over", "description": "A. Judge", "point": 0.5, "price": -130}],
                },
            ],
        }],
    }
    rows = parse_snapshots([event], "2026-05-01T12:00:00Z", markets=["pitcher_strikeouts"])
    assert len(rows) == 1
    assert rows[0]["market_key"] == "pitcher_strikeouts"


def test_parse_snapshots_none_filter_accepts_all():
    """parse_snapshots with markets=None accepts all markets in the response."""
    from pull_props import parse_snapshots
    event = {
        "id": "abc", "commence_time": "2026-05-01T18:00:00Z",
        "home_team": "Cubs", "away_team": "Cardinals",
        "bookmakers": [{
            "key": "draftkings", "last_update": None,
            "markets": [
                {
                    "key": "pitcher_strikeouts",
                    "outcomes": [{"name": "Over", "description": "G. Cole", "point": 7.5, "price": -115}],
                },
                {
                    "key": "batter_home_runs",
                    "outcomes": [{"name": "Over", "description": "A. Judge", "point": 0.5, "price": -130}],
                },
            ],
        }],
    }
    rows = parse_snapshots([event], "2026-05-01T12:00:00Z", markets=None)
    assert len(rows) == 2
