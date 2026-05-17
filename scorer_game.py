"""
scorer_game.py — Game Over/Under totals signal scorer.

Public interface:
    score_game_total(home_team, away_team, selection, point, edge, game_date, game_data=None)
    -> (score: int, breakdown: list[dict])
"""

from __future__ import annotations

# ── weights ──────────────────────────────────────────────────────────────────

GAME_TOTAL_WEIGHTS = {
    "home_sp_quality":   18,
    "away_sp_quality":   18,
    "home_team_offense": 14,
    "away_team_offense": 14,
    "park_run_factor":   14,
    "weather":           12,
    "umpire_run_factor":  5,
    "edge":               5,
}

assert sum(GAME_TOTAL_WEIGHTS.values()) == 100, "Weights must sum to 100"

# ── helpers ───────────────────────────────────────────────────────────────────


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def _edge_signal(edge: float) -> float:
    """0.0 at edge<=0%, 1.0 at edge>=8%."""
    return _clamp(edge / 0.08)


def _park_run_signal(park: dict, selection: str) -> float:
    """
    Composite of hr_factor and hits_factor.
    Hitter-friendly park (composite > 100) -> Over signal.
    """
    hr_f = park.get("hr_factor", 100)
    hits_f = park.get("hits_factor", 100)
    composite = hr_f * 0.6 + hits_f * 0.4
    raw = _clamp((composite - 85.0) / 30.0)  # 85->0, 100->0.5, 115->1.0
    return raw if selection == "Over" else 1.0 - raw


def _ump_run_signal(k_tendency: float, selection: str) -> float:
    """
    Wide zone (positive k_tendency) -> more Ks -> fewer runs -> Under signal.
    k_tendency in [-1, +1].
    """
    normalized = _clamp((k_tendency + 1.0) / 2.0)  # -1->0, 0->0.5, +1->1
    # high normalized = wide zone = fewer runs = Under signal
    return (1.0 - normalized) if selection == "Over" else normalized


def _weather_signal(weather: dict, selection: str) -> float:
    """Combines tailwind_factor and cold_penalty into 0-1 for Over/Under."""
    if weather.get("is_dome"):
        return 0.5
    tf = weather.get("tailwind_factor", 0.5)
    cold = weather.get("cold_penalty", 0.0)
    wind_speed = weather.get("wind_speed_kph", 0.0)
    wind_weight = _clamp(wind_speed / 30.0)
    wind_effect = tf * wind_weight + 0.5 * (1.0 - wind_weight)
    cold_effect = 0.5 - cold * 0.5
    raw = (wind_effect * 0.7) + (cold_effect * 0.3)
    return raw if selection == "Over" else 1.0 - raw


def _sp_quality_signal(sp: dict, season: int, selection: str) -> tuple[float, str]:
    """
    Composite SP quality from ERA, WHIP, whiff_pct, hard_hit_pct.
    Good SP (low ERA/WHIP, high whiff) -> Under signal.
    raw near 1.0 = bad pitcher = runs likely = Over signal.
    """
    from signals.statcast import get_pitcher_statcast

    era = sp.get("era")
    whip = sp.get("whip")
    pid = sp.get("id")
    sc = get_pitcher_statcast(pid, season) if pid else {}
    whiff_pct = sc.get("whiff_pct")
    hard_hit_pct = sc.get("hard_hit_pct")

    components = []
    if era is not None:
        era_raw = _clamp((era - 2.0) / 5.0)  # 2.0->0(great), 4.5->0.5, 7.0->1.0(bad)
        components.append((era_raw, 0.35))
    if whip is not None:
        whip_raw = _clamp((whip - 0.80) / 0.90)  # 0.80->0(great), 1.25->0.5, 1.70->1.0(bad)
        components.append((whip_raw, 0.25))
    if whiff_pct is not None:
        # high whiff = lots of Ks = fewer baserunners = good for Under (low for Over)
        whiff_raw = 1.0 - _clamp((whiff_pct - 15.0) / 20.0)  # 15%->1.0(bad), 35%->0.0(great)
        components.append((whiff_raw, 0.25))
    if hard_hit_pct is not None:
        hh_raw = _clamp((hard_hit_pct - 30.0) / 20.0)  # 30%->0.0, 40%->0.5, 50%->1.0
        components.append((hh_raw, 0.15))

    if not components:
        return 0.5, "no_data"

    total_weight = sum(w for _, w in components)
    raw = sum(v * w for v, w in components) / total_weight
    # raw near 1.0 = bad pitcher/favorable for scoring = Over signal
    result = raw if selection == "Over" else 1.0 - raw
    name = sp.get("name", "?")
    return _clamp(result), f"{name} era={era} whip={whip} whiff={whiff_pct} hh={hard_hit_pct}"


def _team_offense_signal(team_name: str, season: int, selection: str) -> tuple[float, str]:
    """
    Composite team offense from runs_per_game and OPS.
    Strong offense (high rpg/OPS) -> Over signal.
    """
    from signals.team_stats import get_team_offense

    stats = get_team_offense(team_name, season)
    rpg = stats.get("runs_per_game")
    ops = stats.get("ops")

    components = []
    if rpg is not None:
        rpg_raw = _clamp((rpg - 3.0) / 3.0)  # 3.0->0(weak), 4.5->0.5, 6.0->1.0(strong)
        components.append((rpg_raw, 0.60))
    if ops is not None:
        ops_raw = _clamp((ops - 0.600) / 0.240)  # .600->0, .720->0.5, .840->1.0
        components.append((ops_raw, 0.40))

    if not components:
        return 0.5, "no_data"

    total_weight = sum(w for _, w in components)
    raw = sum(v * w for v, w in components) / total_weight
    # raw near 1.0 = strong offense = Over signal
    result = raw if selection == "Over" else 1.0 - raw
    return _clamp(result), f"{team_name} rpg={rpg} ops={ops}"


# ── main scorer ───────────────────────────────────────────────────────────────


def score_game_total(
    home_team: str,
    away_team: str,
    selection: str,       # "Over" or "Under"
    point: float,         # the total line e.g. 8.5
    edge: float,
    game_date: str,       # "YYYY-MM-DD"
    game_data: dict | None = None,  # from signals.lineups.get_game_data_for_date()
) -> tuple[int, list[dict]]:
    """Returns (score 0-100, breakdown list)."""
    from signals.lineups import find_game
    from signals.parks import get_park
    from signals.weather import get_weather

    season = int(game_date[:4])
    breakdown = []

    def add(signal: str, raw: float, note: str = "") -> None:
        pts = round(raw * GAME_TOTAL_WEIGHTS.get(signal, 0))
        breakdown.append({
            "signal": signal,
            "raw": round(raw, 3),
            "pts": pts,
            "max": GAME_TOTAL_WEIGHTS.get(signal, 0),
            "note": note,
        })

    # edge
    add("edge", _edge_signal(edge), f"edge={edge:.1%}")

    # park
    park = get_park(home_team)
    add("park_run_factor", _park_run_signal(park, selection),
        f"hr_factor={park.get('hr_factor')} hits_factor={park.get('hits_factor')}")

    # weather
    weather = get_weather(
        park.get("lat", 39.5),
        park.get("lon", -98.35),
        game_date,
        park.get("cf_bearing", 0),
        park.get("is_dome", False),
    )
    add("weather", _weather_signal(weather, selection),
        f"wind={weather.get('wind_speed_kph', 0):.0f}kph tf={weather.get('tailwind_factor', 0.5):.2f}")

    # game_info (umpire + SPs)
    game_info = find_game(game_data, home_team, away_team) if game_data else None

    # umpire
    ump_k = game_info.get("ump_k_tendency", 0.0) if game_info else 0.0
    ump_name = game_info.get("umpire_name", "unknown") if game_info else "unknown"
    add("umpire_run_factor", _ump_run_signal(ump_k, selection), f"ump={ump_name} ({ump_k:+.1f})")

    # SP quality
    home_sp = (game_info or {}).get("home_sp", {})
    away_sp = (game_info or {}).get("away_sp", {})
    home_sp_raw, home_sp_note = _sp_quality_signal(home_sp, season, selection)
    away_sp_raw, away_sp_note = _sp_quality_signal(away_sp, season, selection)
    add("home_sp_quality", home_sp_raw, home_sp_note)
    add("away_sp_quality", away_sp_raw, away_sp_note)

    # team offense
    home_off_raw, home_off_note = _team_offense_signal(home_team, season, selection)
    away_off_raw, away_off_note = _team_offense_signal(away_team, season, selection)
    add("home_team_offense", home_off_raw, home_off_note)
    add("away_team_offense", away_off_raw, away_off_note)

    score = sum(item["pts"] for item in breakdown)
    return max(0, min(100, score)), breakdown
