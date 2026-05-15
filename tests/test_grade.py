import pytest
from unittest import mock
from grade import normalize_name, grade_outcome, calc_profit


class TestNormalizeName:
    def test_lowercase(self):
        result = normalize_name("Gerrit Cole")
        assert result == "gerritcole"

    def test_strips_accents(self):
        assert normalize_name("José Ramírez") == "joseramirez"

    def test_strips_punctuation(self):
        assert normalize_name("Bo Bichette") == "bobichette"

    def test_already_clean(self):
        assert normalize_name("aaron judge") == "aaronjudge"


class TestGradeOutcome:
    def test_over_win(self):
        assert grade_outcome("Over", 7.5, 8.0) == "WIN"

    def test_over_loss(self):
        assert grade_outcome("Over", 7.5, 7.0) == "LOSS"

    def test_over_push(self):
        assert grade_outcome("Over", 8.0, 8.0) == "PUSH"

    def test_under_win(self):
        assert grade_outcome("Under", 7.5, 7.0) == "WIN"

    def test_under_loss(self):
        assert grade_outcome("Under", 7.5, 8.0) == "LOSS"

    def test_under_push(self):
        assert grade_outcome("Under", 8.0, 8.0) == "PUSH"

    def test_over_half_line_win(self):
        assert grade_outcome("Over", 1.5, 2) == "WIN"

    def test_over_half_line_loss(self):
        assert grade_outcome("Over", 1.5, 1) == "LOSS"


class TestCalcProfit:
    def test_win_positive_odds(self):
        assert abs(calc_profit("WIN", 150) - 1.5) < 1e-9

    def test_win_even_money(self):
        assert abs(calc_profit("WIN", 100) - 1.0) < 1e-9

    def test_win_negative_odds(self):
        assert abs(calc_profit("WIN", -110) - 100/110) < 1e-6

    def test_loss(self):
        assert calc_profit("LOSS", -110) == -1.0
        assert calc_profit("LOSS", 150)  == -1.0

    def test_push(self):
        assert calc_profit("PUSH", -110) == 0.0
        assert calc_profit("PUSH", 150)  == 0.0


class TestGetGameResultsExtractors:
    def _make_resp(self, data):
        m = mock.Mock()
        m.raise_for_status = mock.Mock()
        m.json.return_value = data
        return m

    def _schedule(self):
        return {
            "dates": [{
                "games": [{
                    "gamePk": 999,
                    "status": {"abstractGameState": "Final"},
                }]
            }]
        }

    def _boxscore(self, batting=None, pitching=None, name="Test Player"):
        return {
            "teams": {
                "home": {
                    "players": {
                        "ID1": {
                            "person": {"fullName": name},
                            "stats": {
                                "batting":  batting  or {},
                                "pitching": pitching or {},
                            },
                        }
                    }
                },
                "away": {"players": {}},
            }
        }

    def test_pitcher_hits_allowed_extracted(self):
        with mock.patch("requests.get") as mg:
            mg.side_effect = [
                self._make_resp(self._schedule()),
                self._make_resp(self._boxscore(pitching={"hits": 6})),
            ]
            from grade import get_game_results
            results = get_game_results("2026-05-01")
        found = [r for r in results if r["market_key"] == "pitcher_hits_allowed"]
        assert len(found) == 1
        assert found[0]["stat_value"] == 6

    def test_pitcher_earned_runs_extracted(self):
        with mock.patch("requests.get") as mg:
            mg.side_effect = [
                self._make_resp(self._schedule()),
                self._make_resp(self._boxscore(pitching={"earnedRuns": 3})),
            ]
            from grade import get_game_results
            results = get_game_results("2026-05-01")
        found = [r for r in results if r["market_key"] == "pitcher_earned_runs"]
        assert len(found) == 1
        assert found[0]["stat_value"] == 3

    def test_batter_home_runs_extracted(self):
        with mock.patch("requests.get") as mg:
            mg.side_effect = [
                self._make_resp(self._schedule()),
                self._make_resp(self._boxscore(batting={"homeRuns": 2})),
            ]
            from grade import get_game_results
            results = get_game_results("2026-05-01")
        found = [r for r in results if r["market_key"] == "batter_home_runs"]
        assert len(found) == 1
        assert found[0]["stat_value"] == 2

    def test_zero_value_still_extracted(self):
        """0 home runs is a valid outcome — must be graded, not skipped."""
        with mock.patch("requests.get") as mg:
            mg.side_effect = [
                self._make_resp(self._schedule()),
                self._make_resp(self._boxscore(batting={"homeRuns": 0})),
            ]
            from grade import get_game_results
            results = get_game_results("2026-05-01")
        found = [r for r in results if r["market_key"] == "batter_home_runs"]
        assert len(found) == 1
        assert found[0]["stat_value"] == 0

    def test_all_12_markets_extracted_in_one_call(self):
        batting  = {"hits": 2, "totalBases": 5, "homeRuns": 1, "rbi": 2,
                    "runs": 1, "stolenBases": 1, "baseOnBalls": 1}
        pitching = {"strikeOuts": 7, "hits": 4, "earnedRuns": 2,
                    "baseOnBalls": 2, "outs": 21}
        with mock.patch("requests.get") as mg:
            mg.side_effect = [
                self._make_resp(self._schedule()),
                self._make_resp(self._boxscore(batting=batting, pitching=pitching)),
            ]
            from grade import get_game_results
            results = get_game_results("2026-05-01")
        found = {r["market_key"] for r in results}
        expected = {
            "batter_hits", "batter_total_bases", "batter_home_runs", "batter_rbis",
            "batter_runs_scored", "batter_stolen_bases", "batter_walks",
            "pitcher_strikeouts", "pitcher_hits_allowed", "pitcher_earned_runs",
            "pitcher_walks", "pitcher_outs",
        }
        assert expected == found

    def test_skips_non_final_games(self):
        schedule = {
            "dates": [{
                "games": [{
                    "gamePk": 999,
                    "status": {"abstractGameState": "Live"},
                }]
            }]
        }
        with mock.patch("requests.get") as mg:
            mg.side_effect = [self._make_resp(schedule)]
            from grade import get_game_results
            results = get_game_results("2026-05-01")
        assert results == []
