import pytest
from unittest.mock import MagicMock, patch
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import stats as stats_module
from stats import (
    find_player_info, fetch_pitcher_stats,
    fetch_batter_stats, fetch_team_hitting,
)

ALL_PLAYERS = {"people": [
    {"id": 669302, "fullName": "Jesus Luzardo",
     "currentTeam": {"name": "Miami Marlins"}},
    {"id": 99999,  "fullName": "Freddie Freeman",
     "currentTeam": {"name": "Los Angeles Dodgers"}},
]}

PITCHER_GAMELOG = {"stats": [{"splits": [
    {"date": "2026-04-10", "stat": {"gamesStarted": 1, "strikeOuts": 8, "hits": 3, "earnedRuns": 1, "inningsPitched": "6.0"}},
    {"date": "2026-04-15", "stat": {"gamesStarted": 1, "strikeOuts": 6, "hits": 5, "earnedRuns": 2, "inningsPitched": "5.2"}},
    {"date": "2026-04-20", "stat": {"gamesStarted": 1, "strikeOuts": 9, "hits": 4, "earnedRuns": 0, "inningsPitched": "7.0"}},
    {"date": "2026-04-25", "stat": {"gamesStarted": 1, "strikeOuts": 7, "hits": 6, "earnedRuns": 3, "inningsPitched": "5.0"}},
    {"date": "2026-04-30", "stat": {"gamesStarted": 1, "strikeOuts": 5, "hits": 4, "earnedRuns": 2, "inningsPitched": "6.1"}},
]}]}

PITCHER_SEASON = {"stats": [{"splits": [{"stat": {
    "strikeoutsPer9Inn": "10.2", "era": "3.25", "whip": "1.10",
}}]}]}

BATTER_GAMELOG = {"stats": [{"splits": [
    {"stat": {"hits": 2, "totalBases": 4, "plateAppearances": 4}},
    {"stat": {"hits": 1, "totalBases": 1, "plateAppearances": 4}},
    {"stat": {"hits": 0, "totalBases": 0, "plateAppearances": 4}},
    {"stat": {"hits": 2, "totalBases": 3, "plateAppearances": 4}},
    {"stat": {"hits": 1, "totalBases": 2, "plateAppearances": 4}},
]}]}

BATTER_SEASON = {"stats": [{"splits": [{"stat": {"avg": ".285", "slg": ".450"}}]}]}

TEAM_STATS = {"stats": [{"splits": [
    {"team": {"name": "Miami Marlins"},
     "stat": {"strikeOuts": 310, "plateAppearances": 1350, "avg": ".228", "ops": ".690"}},
    {"team": {"name": "Philadelphia Phillies"},
     "stat": {"strikeOuts": 350, "plateAppearances": 1350, "avg": ".257", "ops": ".756"}},
]}]}


def _multi_get(*payloads):
    it = iter(payloads)
    def _side(*a, **kw):
        m = MagicMock()
        m.raise_for_status = MagicMock()
        m.json.return_value = next(it)
        return m
    return MagicMock(side_effect=_side)


@pytest.fixture(autouse=True)
def reset():
    stats_module._reset_caches()
    yield
    stats_module._reset_caches()


def test_find_player_exact_match():
    with patch("stats.requests.get", _multi_get(ALL_PLAYERS)):
        r = find_player_info("Jesus Luzardo", season=2026)
    assert r["id"] == 669302
    assert r["team_name"] == "Miami Marlins"


def test_find_player_not_found():
    with patch("stats.requests.get", _multi_get(ALL_PLAYERS)):
        r = find_player_info("Nobody Fake", season=2026)
    assert r is None


def test_find_player_cached_no_extra_calls():
    mock = _multi_get(ALL_PLAYERS)
    with patch("stats.requests.get", mock):
        find_player_info("Jesus Luzardo", season=2026)
        find_player_info("Jesus Luzardo", season=2026)
    assert mock.call_count == 1


def test_fetch_pitcher_stats_averages():
    with patch("stats.requests.get", _multi_get(PITCHER_GAMELOG, PITCHER_SEASON)):
        r = fetch_pitcher_stats(669302, season=2026)
    assert r["recent_k"]    == pytest.approx(7.0,  abs=0.05)
    assert r["recent_h"]    == pytest.approx(4.4,  abs=0.05)
    assert r["recent_er"]   == pytest.approx(1.6,  abs=0.05)
    assert r["season_k9"]   == pytest.approx(10.2, abs=0.05)
    assert r["season_era"]  == pytest.approx(3.25, abs=0.01)
    assert r["season_whip"] == pytest.approx(1.10, abs=0.01)


def test_fetch_pitcher_stats_http_error_returns_none():
    m = MagicMock()
    m.return_value.raise_for_status.side_effect = Exception("500")
    with patch("stats.requests.get", m):
        assert fetch_pitcher_stats(1, season=2026) is None


def test_fetch_batter_stats():
    with patch("stats.requests.get", _multi_get(BATTER_GAMELOG, BATTER_SEASON)):
        r = fetch_batter_stats(99999, season=2026)
    assert r["recent_h_per_game"]  == pytest.approx(1.2,  abs=0.05)
    assert r["recent_tb_per_game"] == pytest.approx(2.0,  abs=0.05)
    assert r["season_avg"] == pytest.approx(0.285, abs=0.001)
    assert r["season_slg"] == pytest.approx(0.450, abs=0.001)


def test_fetch_team_hitting():
    with patch("stats.requests.get", _multi_get(TEAM_STATS)):
        r = fetch_team_hitting("Philadelphia Phillies", season=2026)
    assert r["k_pct"] == pytest.approx(350/1350, abs=0.001)
    assert r["avg"]   == pytest.approx(0.257, abs=0.001)
    assert r["ops"]   == pytest.approx(0.756, abs=0.001)


def test_fetch_team_hitting_http_error_returns_none():
    m = MagicMock()
    m.return_value.raise_for_status.side_effect = Exception("500")
    with patch("stats.requests.get", m):
        assert fetch_team_hitting("Miami Marlins", season=2026) is None


def test_fetch_batter_stats_http_error_returns_none():
    m = MagicMock()
    m.return_value.raise_for_status.side_effect = Exception("500")
    with patch("stats.requests.get", m):
        assert fetch_batter_stats(1, season=2026) is None
