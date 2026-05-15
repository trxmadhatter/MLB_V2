import pytest
from edge import bovada_break_even, compute_edge, compute_ev, classify


class TestBovadaBreakEven:
    def test_even_money(self):
        assert bovada_break_even(100) == 0.5

    def test_minus_110(self):
        assert abs(bovada_break_even(-110) - 110/210) < 1e-6

    def test_plus_150(self):
        assert abs(bovada_break_even(150) - 0.4) < 1e-6


class TestComputeEdge:
    def test_positive_edge(self):
        edge = compute_edge(0.55, 0.52)
        assert abs(edge - 0.03) < 1e-9

    def test_zero_edge(self):
        assert compute_edge(0.50, 0.50) == 0.0

    def test_negative_edge(self):
        assert compute_edge(0.48, 0.52) == pytest.approx(-0.04)


class TestComputeEV:
    def test_positive_ev(self):
        # +100 (decimal 2.0), consensus prob 0.55 → EV = 0.55*2.0-1 = 0.10
        assert abs(compute_ev(100, 0.55) - 0.10) < 1e-6

    def test_negative_ev(self):
        # -150 (decimal 1.667), consensus prob 0.55 → negative
        assert compute_ev(-150, 0.55) < 0

    def test_zero_ev(self):
        # +100, consensus exactly 50% → EV = 0.5*2.0-1 = 0.0
        assert abs(compute_ev(100, 0.50)) < 1e-9


GOOD_ARGS = dict(market_key="pitcher_outs", selection="Over", price=-115)


class TestClassify:
    def test_recommended(self):
        assert classify(0.05, 0.03, **GOOD_ARGS) == "RECOMMENDED"

    def test_recommended_at_exactly_4pct(self):
        assert classify(0.04, 0.01, **GOOD_ARGS) == "RECOMMENDED"

    def test_lean(self):
        assert classify(0.03, 0.01, **GOOD_ARGS) == "LEAN"

    def test_lean_at_1pct(self):
        assert classify(0.01, 0.005, **GOOD_ARGS) == "LEAN"

    def test_no_bet_below_1pct(self):
        assert classify(0.009, 0.01, **GOOD_ARGS) == "NO_BET"

    def test_no_bet_wrong_market(self):
        assert classify(0.05, 0.03, market_key="pitcher_strikeouts", selection="Over", price=-115) == "NO_BET"

    def test_no_bet_wrong_direction(self):
        assert classify(0.05, 0.03, market_key="pitcher_outs", selection="Under", price=-115) == "NO_BET"

    def test_no_bet_price_too_heavy(self):
        assert classify(0.05, 0.03, market_key="pitcher_outs", selection="Over", price=-160) == "NO_BET"

    def test_no_bet_positive_odds(self):
        assert classify(0.05, 0.03, market_key="pitcher_outs", selection="Over", price=110) == "NO_BET"

    def test_no_bet_price_at_boundary_min(self):
        assert classify(0.05, 0.03, market_key="pitcher_outs", selection="Over", price=-145) == "RECOMMENDED"

    def test_no_bet_price_at_boundary_max(self):
        assert classify(0.05, 0.03, market_key="pitcher_outs", selection="Over", price=-101) == "RECOMMENDED"

    def test_ev_ignored_does_not_block_recommended(self):
        assert classify(0.05, -0.01, **GOOD_ARGS) == "RECOMMENDED"
