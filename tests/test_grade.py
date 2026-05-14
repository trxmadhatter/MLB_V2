import pytest
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
