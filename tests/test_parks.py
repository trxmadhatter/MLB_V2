from signals.parks import get_park, list_teams, NEUTRAL_PARK

def test_known_park():
    p = get_park("Colorado Rockies")
    assert p["k_factor"] < 100, "Coors should suppress Ks"
    assert p["hr_factor"] > 110, "Coors should boost HRs"
    assert p["is_dome"] is False
    assert "lat" in p and "lon" in p

def test_dome_park():
    p = get_park("Tampa Bay Rays")
    assert p["is_dome"] is True

def test_unknown_team_returns_neutral():
    p = get_park("Nonexistent Team")
    assert p == NEUTRAL_PARK

def test_all_teams_have_required_keys():
    for team in list_teams():
        p = get_park(team)
        for key in ("k_factor", "hits_factor", "tb_factor", "hr_factor",
                    "is_dome", "lat", "lon", "cf_bearing"):
            assert key in p, f"{team} missing {key}"
