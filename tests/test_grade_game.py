from unittest.mock import patch, MagicMock
import pytest
from grade import get_game_scores, grade_pending_game_picks
from db import get_conn, init_db, upsert_game_pick, get_today_game_picks

_MOCK_SCHEDULE = {
    "dates": [{
        "games": [{
            "status": {"abstractGameState": "Final"},
            "teams": {
                "home": {"team": {"name": "New York Yankees"}},
                "away": {"team": {"name": "Boston Red Sox"}},
            },
            "linescore": {
                "teams": {
                    "home": {"runs": 5},
                    "away": {"runs": 3},
                }
            }
        }]
    }]
}


def _mock_get(data):
    m = MagicMock()
    m.json.return_value = data
    m.raise_for_status = MagicMock()
    return m


class TestGetGameScores:
    def test_final_game_returned(self):
        with patch("grade.requests.get", return_value=_mock_get(_MOCK_SCHEDULE)):
            results = get_game_scores("2026-05-17")
        assert len(results) == 1
        assert results[0]["home_runs"] == 5
        assert results[0]["away_runs"] == 3
        assert results[0]["home_team"] == "New York Yankees"
        assert results[0]["away_team"] == "Boston Red Sox"

    def test_non_final_excluded(self):
        data = {"dates": [{"games": [{
            "status": {"abstractGameState": "Live"},
            "teams": {"home": {"team": {"name": "Yankees"}}, "away": {"team": {"name": "Red Sox"}}},
            "linescore": {"teams": {"home": {"runs": 2}, "away": {"runs": 1}}}
        }]}]}
        with patch("grade.requests.get", return_value=_mock_get(data)):
            results = get_game_scores("2026-05-17")
        assert results == []

    def test_api_failure_returns_empty(self):
        with patch("grade.requests.get", side_effect=Exception("timeout")):
            results = get_game_scores("2026-05-17")
        assert results == []

    def test_missing_runs_excluded(self):
        data = {"dates": [{"games": [{
            "status": {"abstractGameState": "Final"},
            "teams": {"home": {"team": {"name": "Yankees"}}, "away": {"team": {"name": "Red Sox"}}},
            "linescore": {"teams": {"home": {}, "away": {}}}
        }]}]}
        with patch("grade.requests.get", return_value=_mock_get(data)):
            results = get_game_scores("2026-05-17")
        assert results == []


@pytest.fixture
def conn(tmp_path):
    db = tmp_path / "test.db"
    c = get_conn(db)
    init_db(c)
    yield c
    c.close()


_PICK = {
    "pick_date": "2026-05-16",
    "pulled_at": "2026-05-16T15:00:00Z",
    "event_id": "evt1",
    "commence_time": "2026-05-16T18:00:00Z",
    "home_team": "New York Yankees",
    "away_team": "Boston Red Sox",
    "market_key": "totals",
    "selection": "Over",
    "point": 8.5,
    "bovada_price": -110,
    "bovada_break_even_prob": 0.5238,
    "bovada_fair_prob": 0.5,
    "consensus_fair_prob": 0.55,
    "consensus_book_count": 5,
    "edge": 0.03,
    "recommendation": "LEAN",
    "signal_score": 55,
    "signal_breakdown": "[]",
}


class TestGradePendingGamePicks:
    def test_over_loss_graded(self, conn):
        upsert_game_pick(conn, _PICK)
        with patch("grade.requests.get", return_value=_mock_get(_MOCK_SCHEDULE)):
            graded = grade_pending_game_picks(conn, "2026-05-16")
        assert graded == 1
        row = get_today_game_picks(conn, "2026-05-16")[0]
        assert row["result"] == "LOSS"    # 5+3=8 < 8.5 → Over loses
        assert row["actual_total"] == 8.0

    def test_no_match_stays_pending(self, conn):
        pick = {**_PICK, "home_team": "Houston Astros", "away_team": "Texas Rangers"}
        upsert_game_pick(conn, pick)
        with patch("grade.requests.get", return_value=_mock_get(_MOCK_SCHEDULE)):
            graded = grade_pending_game_picks(conn, "2026-05-16")
        assert graded == 0
        row = get_today_game_picks(conn, "2026-05-16")[0]
        assert row["result"] == "PENDING"

    def test_api_failure_leaves_pending(self, conn):
        upsert_game_pick(conn, _PICK)
        with patch("grade.requests.get", side_effect=Exception("timeout")):
            graded = grade_pending_game_picks(conn, "2026-05-16")
        assert graded == 0
