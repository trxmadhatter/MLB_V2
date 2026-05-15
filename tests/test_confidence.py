import pytest
from unittest.mock import patch
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from confidence import score_pick

_BASE_PICK = dict(
    player_name="Jesus Luzardo",
    home_team="Miami Marlins",
    away_team="Philadelphia Phillies",
    season=2026,
)

_PITCHER_STATS = {
    "recent_k": 7.0, "recent_h": 4.0, "recent_er": 1.5,
    "season_k9": 10.2, "season_era": 3.10, "season_whip": 1.08,
}

_BATTER_STATS = {
    "recent_h_per_game": 1.4, "recent_tb_per_game": 2.2,
    "season_avg": 0.290, "season_slg": 0.490,
}

_TEAM_HIGH_K = {"k_pct": 0.260, "avg": 0.230, "ops": 0.690}
_TEAM_LOW_K  = {"k_pct": 0.195, "avg": 0.257, "ops": 0.756}


def _p(player_info=None, pitcher=None, batter=None, team=None):
    """Return tuple of patch objects."""
    return (
        patch("confidence.find_player_info",
              return_value=player_info or {"id": 1, "team_name": "Miami Marlins"}),
        patch("confidence.fetch_pitcher_stats",
              return_value=pitcher or _PITCHER_STATS),
        patch("confidence.fetch_batter_stats",
              return_value=batter or _BATTER_STATS),
        patch("confidence.fetch_team_hitting",
              return_value=team or _TEAM_HIGH_K),
    )


def test_pitcher_strikeouts_all_4_signals():
    # recent_k 7.0 > 5.5+0.5, k9 10.2>9.0, opp k% 26%>25%, edge 5%>=4%
    p = _p()
    with p[0], p[1], p[2], p[3]:
        score, factors = score_pick(
            **_BASE_PICK, market_key="pitcher_strikeouts",
            selection="Over", point=5.5, edge=0.05,
        )
    assert score == 4
    assert len(factors) == 4


def test_pitcher_strikeouts_only_edge_signal():
    # recent K 5.5 = line, k9 8.0, opp k% 22.0% — none fire except edge
    p = _p(pitcher={**_PITCHER_STATS, "recent_k": 5.5, "season_k9": 8.0},
           team={**_TEAM_HIGH_K, "k_pct": 0.220})
    with p[0], p[1], p[2], p[3]:
        score, factors = score_pick(
            **_BASE_PICK, market_key="pitcher_strikeouts",
            selection="Over", point=5.5, edge=0.05,
        )
    assert score == 1
    assert len(factors) == 1
    assert "edge" in factors[0].lower()


def test_pitcher_strikeouts_no_signals_below_edge_threshold():
    p = _p(pitcher={**_PITCHER_STATS, "recent_k": 5.5, "season_k9": 8.0},
           team={**_TEAM_HIGH_K, "k_pct": 0.220})
    with p[0], p[1], p[2], p[3]:
        score, factors = score_pick(
            **_BASE_PICK, market_key="pitcher_strikeouts",
            selection="Over", point=5.5, edge=0.02,
        )
    assert score == 0
    assert factors == []


def test_player_not_found_returns_zero():
    with patch("confidence.find_player_info", return_value=None):
        score, factors = score_pick(
            **_BASE_PICK, market_key="pitcher_strikeouts",
            selection="Over", point=5.5, edge=0.05,
        )
    assert score == 0
    assert factors == []


def test_exception_returns_zero_never_raises():
    with patch("confidence.find_player_info", side_effect=RuntimeError("API down")):
        score, factors = score_pick(
            **_BASE_PICK, market_key="pitcher_strikeouts",
            selection="Over", point=5.5, edge=0.05,
        )
    assert score == 0
    assert factors == []


def test_pitcher_hits_under_all_signals():
    # recent_h 4.0 < 5.5-0.5=5.0 fires, whip 1.08 <= 1.15 fires, opp avg 0.230 <= 0.234 fires, edge 4% fires
    p = _p()
    with p[0], p[1], p[2], p[3]:
        score, factors = score_pick(
            **_BASE_PICK, market_key="pitcher_hits_allowed",
            selection="Under", point=5.5, edge=0.04,
        )
    assert score == 4
    assert len(factors) == 4
    assert any("H allowed" in f for f in factors)
    assert any("WHIP" in f for f in factors)
    assert any("BA" in f for f in factors)
    assert any("edge" in f.lower() for f in factors)


def test_pitcher_earned_runs_under():
    # recent_er 1.5 < 3.0 (3.5-0.5) fires; ERA 3.10 > 3.0 does NOT fire; ops 0.690 > 0.685 does NOT fire; edge fires
    # 2 signals: recent_er + edge
    p = _p()
    with p[0], p[1], p[2], p[3]:
        score, factors = score_pick(
            **_BASE_PICK, market_key="pitcher_earned_runs",
            selection="Under", point=3.5, edge=0.04,
        )
    assert score == 2
    assert len(factors) == 2
    assert any("ER" in f for f in factors)
    assert any("edge" in f.lower() for f in factors)


def test_batter_hits_over():
    # recent_h_per_game 1.4 >= 0.7 (0.5+0.2) fires; BA*4=1.16 >= 0.7 fires; edge 4% fires → score 3
    p = _p()
    with p[0], p[1], p[2], p[3]:
        score, factors = score_pick(
            player_name="Freddie Freeman",
            market_key="batter_hits",
            selection="Over", point=0.5,
            home_team="Los Angeles Dodgers",
            away_team="Miami Marlins",
            edge=0.04, season=2026,
        )
    assert score == 3
    assert len(factors) == 3
    assert any("H/game" in f for f in factors)
    assert any("BA" in f for f in factors)
    assert any("edge" in f.lower() for f in factors)


def test_batter_total_bases_over():
    # recent_tb_per_game 2.2 >= 1.7 (1.5+0.2) fires; SLG*4=1.96 >= 1.7 fires; edge 4% fires → score 3
    p = _p()
    with p[0], p[1], p[2], p[3]:
        score, factors = score_pick(
            player_name="Freddie Freeman",
            market_key="batter_total_bases",
            selection="Over", point=1.5,
            home_team="Los Angeles Dodgers",
            away_team="Miami Marlins",
            edge=0.04, season=2026,
        )
    assert score == 3
    assert len(factors) == 3
    assert any("TB/game" in f for f in factors)
    assert any("SLG" in f for f in factors)
    assert any("edge" in f.lower() for f in factors)


def test_unknown_market_returns_zero():
    p = _p()
    with p[0], p[1], p[2], p[3]:
        score, factors = score_pick(
            **_BASE_PICK, market_key="unknown_market",
            selection="Over", point=1.5, edge=0.05,
        )
    assert score == 0
    assert factors == []


def test_score_capped_at_4():
    # Verify score never exceeds 4
    p = _p()
    with p[0], p[1], p[2], p[3]:
        score, _ = score_pick(
            **_BASE_PICK, market_key="pitcher_strikeouts",
            selection="Over", point=5.5, edge=0.05,
        )
    assert score <= 4


def test_pitcher_stats_with_none_values_skips_signals():
    # Stats dict is truthy but has None values — should not crash or add spurious signals
    none_pitcher = {"recent_k": None, "season_k9": None, "recent_h": None,
                    "season_whip": None, "recent_er": None, "season_era": None}
    p = _p(pitcher=none_pitcher)
    with p[0], p[1], p[2], p[3]:
        score, factors = score_pick(
            **_BASE_PICK, market_key="pitcher_strikeouts",
            selection="Over", point=5.5, edge=0.05,
        )
    # Only edge signal fires (team k_pct from _TEAM_HIGH_K=0.260 also fires)
    assert score >= 1
    assert any("edge" in f.lower() for f in factors)
    # recent_k None → no recent-K factor
    assert not any("Recent avg K" in f for f in factors)
    # season_k9 None → no K/9 factor
    assert not any("K/9" in f for f in factors)
