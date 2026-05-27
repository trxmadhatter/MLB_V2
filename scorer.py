"""
Weighted signal scoring engine for MLB prop picks.
Returns (score 0-100, breakdown list) per pick.
"""
from __future__ import annotations
import json
from datetime import datetime

import logging

from config import SIGNAL_WEIGHTS, SCORE_RECOMMENDED, SCORE_LEAN
from signals.parks import get_park
from signals.weather import get_weather
from signals.statcast import fetch_pitcher_velo_trend

_log = logging.getLogger(__name__)


# ── helpers ───────────────────────────────────────────────────────────────────

def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def _edge_signal(edge: float) -> float:
    """0.0 at edge<=0%, 1.0 at edge>=8%."""
    return _clamp(edge / 0.08)


def _park_factor_signal(factor: int, selection: str) -> float:
    """
    For Over: high factor (>100) is good -> 1.0; low factor (<100) is bad -> 0.0.
    For Under: inverted.
    Neutral at 100 -> 0.5.
    """
    normalized = _clamp((factor - 85) / 30.0)   # 85->0, 100->0.5, 115->1.0
    return normalized if selection == "Over" else 1.0 - normalized


def _ump_signal(k_tendency: float, selection: str) -> float:
    """
    k_tendency in [-1, +1]. For K Over: positive tendency is good.
    For K Under: negative tendency is good.
    """
    normalized = _clamp((k_tendency + 1.0) / 2.0)  # -1->0, 0->0.5, +1->1
    return normalized if selection == "Over" else 1.0 - normalized


def _weather_signal(weather: dict, selection: str) -> float:
    """
    Combines tailwind_factor and cold_penalty into 0-1 for Over/Under.
    """
    if weather.get("is_dome"):
        return 0.5
    tf = weather.get("tailwind_factor", 0.5)
    cold = weather.get("cold_penalty", 0.0)
    wind_speed = weather.get("wind_speed_kph", 0.0)
    # Scale tailwind only when wind is meaningful (>10 kph)
    wind_weight = _clamp(wind_speed / 30.0)
    wind_effect = tf * wind_weight + 0.5 * (1.0 - wind_weight)
    # Cold reduces runs (good for Unders, bad for Overs)
    cold_effect = 0.5 - cold * 0.5   # cold=0 -> 0.5, cold=1 -> 0.0
    raw = (wind_effect * 0.7) + (cold_effect * 0.3)
    return raw if selection == "Over" else 1.0 - raw


def _game_total_signal(total: float | None, selection: str) -> float:
    """
    Game O/U total as implied run environment.
    High total (>8.5) = run-heavy → bad for pitcher Outs Over, pitcher K Under.
    Low total (<8.5) = pitcher's game → good for Outs Over.
    Benchmark: 8.5, spread ±1.5 run.
    """
    if total is None:
        return 0.5
    # Low total = good for pitcher Outs Over → raw near 1.0
    raw = _clamp(0.5 + (8.5 - total) / 3.0)   # 7.0->1.0, 8.5->0.5, 10.0->0.0
    return raw if selection == "Over" else 1.0 - raw


def _velo_trend_signal(velo: float | None, selection: str) -> float:
    """
    velo = season avg fastball speed (mph) from Baseball Savant leaderboard.
    93 mph = midpoint; ±2 mph = one unit of scale.
    95 mph → raw≈0.75 (hard thrower, good for K/outs Over).
    91 mph → raw≈0.25 (soft thrower, bad for K/outs Over).
    """
    return _season_rate_signal(velo, 93.0, selection, 2.0)


def _batting_order_signal(position: int | None, selection: str) -> float:
    """
    Batting order position -> 0-1 raw score for Over.
    Slots 3-5 (cleanup) are best for production; 7-9 are weakest.
    """
    if position is None:
        return 0.5
    _order_raw = {1: 0.52, 2: 0.55, 3: 0.72, 4: 0.75, 5: 0.68,
                  6: 0.48, 7: 0.38, 8: 0.32, 9: 0.28}
    raw = _order_raw.get(position, 0.5)
    return raw if selection == "Over" else 1.0 - raw


def _recent_rate_signal(recent: float | None, point: float,
                        selection: str, margin: float = 0.5) -> float:
    """
    How does recent average compare to the line?
    Over: recent >> line is good. Under: recent << line is good.
    """
    if recent is None:
        return 0.5
    diff = recent - point
    # diff = +2 -> clearly over the line -> 1.0 for Over
    # diff = -2 -> clearly under the line -> 0.0 for Over
    normalized = _clamp(0.5 + diff / (2.0 * (margin + 1.0)))
    return normalized if selection == "Over" else 1.0 - normalized


def _era_signal(era: float | None, selection: str) -> float:
    """High ERA = bad pitcher = good for batter Over, bad for batter Under."""
    if era is None:
        return 0.5
    # ERA 2.0 -> 0.0 (great pitcher, bad for Over)
    # ERA 4.5 -> 0.5 (neutral)
    # ERA 7.0+ -> 1.0 (bad pitcher, good for Over)
    normalized = _clamp((era - 2.0) / 5.0)
    return normalized if selection == "Over" else 1.0 - normalized


def _pitcher_rest_signal(rest_days: int | None, selection: str) -> float:
    """
    Fresher pitcher → better performance.
    Caller inverts selection for markets where fresh = fewer (e.g. hits_allowed Under).
    3 days: short rest (bad). 4: standard. 5: slight benefit. 6+: rust/injury return.
    """
    if rest_days is None:
        return 0.5
    if rest_days <= 3:
        raw = 0.2
    elif rest_days == 4:
        raw = 0.5
    elif rest_days == 5:
        raw = 0.65
    else:
        raw = 0.45  # 6+ days: possible rust or injury return
    return raw if selection == "Over" else 1.0 - raw


def _season_rate_signal(rate: float | None, benchmark: float,
                        selection: str, spread: float = 0.05) -> float:
    """Generic: how does season rate compare to a benchmark?"""
    if rate is None:
        return 0.5
    if spread == 0:
        raw = 1.0 if rate > benchmark else (0.0 if rate < benchmark else 0.5)
        return raw if selection == "Over" else 1.0 - raw
    normalized = _clamp(0.5 + (rate - benchmark) / (2 * spread))
    return normalized if selection == "Over" else 1.0 - normalized


def _platoon_signal(pitcher_hand: str | None,
                    batter_or_pitcher: str,
                    split_stat_same: float | None,
                    split_stat_opp: float | None,
                    selection: str) -> float:
    """
    Compare performance vs same-hand vs opp-hand.
    Better vs this batter type = higher score for corresponding direction.
    """
    if split_stat_same is None or split_stat_opp is None:
        return 0.5
    diff = split_stat_same - split_stat_opp
    # diff > 0: better vs this matchup -> good for Over (if it's an offensive stat)
    normalized = _clamp(0.5 + diff / 0.4)
    return normalized if selection == "Over" else 1.0 - normalized


# ── per-market scoring ─────────────────────────────────────────────────────────

def _score_pitcher_strikeouts(
    player_id: int | None,
    selection: str,
    point: float,
    edge: float,
    park: dict,
    weather: dict,
    game_info: dict | None,
    season: int,
    opp_team: str | None = None,
) -> list[dict]:
    from stats import fetch_pitcher_stats, fetch_team_hitting
    from signals.splits import get_pitcher_splits
    from signals.statcast import get_pitcher_statcast
    from signals.fangraphs import get_pitcher_fangraphs

    weights = SIGNAL_WEIGHTS["pitcher_strikeouts"]
    breakdown = []

    def add(signal: str, raw: float, note: str = ""):
        pts = round(raw * weights.get(signal, 0))
        breakdown.append({"signal": signal, "raw": round(raw, 3),
                          "pts": pts, "max": weights.get(signal, 0), "note": note})

    add("edge", _edge_signal(edge), f"edge={edge:.1%}")

    kf = park.get("k_factor", 100)
    add("park_k_factor", _park_factor_signal(kf, selection), f"k_factor={kf}")

    ump_k = game_info.get("ump_k_tendency", 0.0) if game_info else 0.0
    ump_name = game_info.get("umpire_name", "unknown") if game_info else "unknown"
    add("ump_k_tendency", _ump_signal(ump_k, selection), f"ump={ump_name} ({ump_k:+.1f})")

    add("weather", _weather_signal(weather, selection),
        f"wind={weather.get('wind_speed_kph', 0):.0f}kph tf={weather.get('tailwind_factor', 0.5):.2f}")

    if player_id:
        stats = fetch_pitcher_stats(player_id, season) or {}
        recent_k = stats.get("recent_k")
        add("recent_k_rate", _recent_rate_signal(recent_k, point, selection, 0.5),
            f"recent_k={recent_k}")

        k9 = stats.get("season_k9")
        add("season_k_pct", _season_rate_signal(k9, 8.0, selection, spread=1.5),
            f"k9={k9}")

        if opp_team:
            team = fetch_team_hitting(opp_team, season) or {}
            k_pct = team.get("k_pct")
            add("opp_team_k_pct", _season_rate_signal(k_pct, 0.228, selection, 0.05),
                f"opp_k_pct={k_pct:.1%}" if k_pct else "opp_k_pct=None")
        else:
            add("opp_team_k_pct", 0.5, "opp_team unavailable")

        splits = get_pitcher_splits(player_id, season)
        k9_vl = splits.get("k9_vs_lhh")
        k9_vr = splits.get("k9_vs_rhh")
        if k9_vl and k9_vr:
            k9_used = max(k9_vl, k9_vr) if selection == "Over" else min(k9_vl, k9_vr)
            add("platoon_alignment",
                _season_rate_signal(k9_used, 8.0, selection, 1.5),
                f"k9_vL={k9_vl} k9_vR={k9_vr} used={k9_used:.1f}")
        else:
            add("platoon_alignment", 0.5, "splits unavailable")

        # Statcast: whiff% — benchmark 25%, spread 5 pct-points (CSV delivers as float e.g. 28.5)
        sc = get_pitcher_statcast(player_id, season)
        whiff = sc.get("whiff_pct")
        add("whiff_pct", _season_rate_signal(whiff, 25.0, selection, 5.0),
            f"whiff_pct={whiff}")

        # FanGraphs: Stuff+ — 100 is avg, spread 15
        fg = get_pitcher_fangraphs(player_id, season)
        stuff = fg.get("stuff_plus")
        add("stuff_plus", _season_rate_signal(stuff, 100.0, selection, 15.0),
            f"stuff_plus={stuff}")

        # Fastball velocity quality: hard throwers → good for K Over.
        # 93 mph = midpoint; uses season leaderboard avg (no separate HTTP call).
        vt = fetch_pitcher_velo_trend(player_id, season)
        velo = vt.get("fastball_velo")
        add("velo_trend", _velo_trend_signal(velo, selection),
            f"fastball_velo={velo:.1f}mph" if velo is not None else "fastball_velo=unavailable")
    else:
        for sig in ("recent_k_rate", "season_k_pct", "opp_team_k_pct",
                    "platoon_alignment", "whiff_pct", "stuff_plus", "velo_trend"):
            add(sig, 0.5, "player_id unavailable")

    return breakdown


def _score_pitcher_hits_allowed(
    player_id: int | None,
    selection: str,
    point: float,
    edge: float,
    park: dict,
    weather: dict,
    game_info: dict | None,
    season: int,
    opp_team: str | None = None,
) -> list[dict]:
    from stats import fetch_pitcher_stats, fetch_team_hitting
    from signals.splits import get_pitcher_splits
    from signals.statcast import get_pitcher_statcast

    weights = SIGNAL_WEIGHTS["pitcher_hits_allowed"]
    breakdown = []

    def add(signal, raw, note=""):
        pts = round(raw * weights.get(signal, 0))
        breakdown.append({"signal": signal, "raw": round(raw, 3),
                          "pts": pts, "max": weights.get(signal, 0), "note": note})

    add("edge", _edge_signal(edge), f"edge={edge:.1%}")

    hf = park.get("hits_factor", 100)
    add("park_hits_factor", _park_factor_signal(hf, selection), f"hits_factor={hf}")

    add("weather", _weather_signal(weather, selection),
        f"wind={weather.get('wind_speed_kph', 0):.0f}kph")

    if player_id:
        stats = fetch_pitcher_stats(player_id, season) or {}
        recent_h = stats.get("recent_h")
        add("recent_h9", _recent_rate_signal(recent_h, point, selection, 0.5),
            f"recent_h={recent_h}")

        whip = stats.get("season_whip")
        add("season_whip", _season_rate_signal(whip, 1.25, selection, 0.15),
            f"whip={whip}")

        if opp_team:
            team = fetch_team_hitting(opp_team, season) or {}
            team_avg = team.get("avg")
            add("opp_team_avg", _season_rate_signal(team_avg, 0.244, selection, 0.015),
                f"opp_avg={team_avg:.3f}" if team_avg else "opp_avg=None")
        else:
            add("opp_team_avg", 0.5, "opp_team unavailable")

        splits = get_pitcher_splits(player_id, season)
        h9_vl = splits.get("h9_vs_lhh")
        h9_vr = splits.get("h9_vs_rhh")
        if h9_vl and h9_vr:
            h9_used = min(h9_vl, h9_vr) if selection == "Under" else max(h9_vl, h9_vr)
            add("platoon_alignment",
                _season_rate_signal(h9_used, 9.0, selection, 1.5),
                f"h9_vL={h9_vl} h9_vR={h9_vr} used={h9_used:.1f}")
        else:
            add("platoon_alignment", 0.5, "splits unavailable")

        # Statcast: hard_hit% allowed (benchmark 37%, spread 4 pct-points; higher = more hits)
        sc = get_pitcher_statcast(player_id, season)
        hard_hit = sc.get("hard_hit_pct")
        add("hard_hit_pct", _season_rate_signal(hard_hit, 37.0, selection, 4.0),
            f"hard_hit_pct={hard_hit}")

        # Statcast: barrel% allowed (benchmark 8%, spread 2 pct-points; higher = more XBH)
        barrel = sc.get("barrel_pct")
        add("barrel_pct", _season_rate_signal(barrel, 8.0, selection, 2.0),
            f"barrel_pct={barrel}")

        # Rest days: fresh pitcher → fewer hits → good for Under. Invert selection.
        rest = stats.get("rest_days")
        flip_sel = "Under" if selection == "Over" else "Over"
        add("rest_days", _pitcher_rest_signal(rest, flip_sel), f"rest_days={rest}")
    else:
        for sig in ("recent_h9", "season_whip", "opp_team_avg",
                    "platoon_alignment", "hard_hit_pct", "barrel_pct", "rest_days"):
            add(sig, 0.5, "player_id unavailable")

    return breakdown


def _score_pitcher_outs(
    player_id: int | None,
    selection: str,
    point: float,
    edge: float,
    park: dict,
    weather: dict,
    game_info: dict | None,
    season: int,
    opp_team: str | None = None,
    game_total: float | None = None,
) -> list[dict]:
    from stats import fetch_pitcher_stats, fetch_team_hitting
    from signals.fangraphs import get_pitcher_fangraphs
    from signals.statcast import get_pitcher_statcast

    weights = SIGNAL_WEIGHTS["pitcher_outs"]
    breakdown = []

    def add(signal, raw, note=""):
        pts = round(raw * weights.get(signal, 0))
        breakdown.append({"signal": signal, "raw": round(raw, 3),
                          "pts": pts, "max": weights.get(signal, 0), "note": note})

    add("edge", _edge_signal(edge), f"edge={edge:.1%}")

    # HR-friendly parks (high hr_factor) mean fewer pitcher outs.
    # We invert the selection so that high hr_factor scores low for Outs Over.
    rf = park.get("hr_factor", 100)
    flip_sel = "Under" if selection == "Over" else "Over"
    add("park_run_factor", _park_factor_signal(rf, flip_sel), f"hr_factor={rf}")

    add("weather", _weather_signal(weather, selection),
        f"wind={weather.get('wind_speed_kph', 0):.0f}kph")

    if player_id:
        stats = fetch_pitcher_stats(player_id, season) or {}
        recent_ip = stats.get("recent_ip")
        add("recent_ip", _recent_rate_signal(recent_ip, point / 3.0, selection, 0.5),
            f"recent_ip={recent_ip} IP/start (line={point/3.0:.1f}IP)")

        season_ip = stats.get("season_ip_per_start")
        add("season_ip", _recent_rate_signal(season_ip, point / 3.0, selection, 0.5),
            f"season_ip_per_start={season_ip}")

        if opp_team:
            team = fetch_team_hitting(opp_team, season) or {}
            ops = team.get("ops")
            add("opp_lineup_ops", _season_rate_signal(ops, 0.720, "Under" if selection == "Over" else "Over", 0.04),
                f"opp_ops={ops:.3f}" if ops else "opp_ops=None")
        else:
            add("opp_lineup_ops", 0.5, "opp_team unavailable")

        # xFIP: prefer FanGraphs; fall back to computed FIP from MLB Stats API.
        # Both invert: low value = better pitcher = more outs → use "Under" direction.
        fg = get_pitcher_fangraphs(player_id, season)
        xfip = fg.get("xfip")
        flip_sel = "Under" if selection == "Over" else "Over"
        if xfip is not None:
            add("xfip", _season_rate_signal(xfip, 4.2, flip_sel, 0.6), f"xfip={xfip} (FG)")
        else:
            fip = stats.get("season_fip")
            add("xfip", _season_rate_signal(fip, 4.2, flip_sel, 0.6),
                f"xfip={fip} (FIP fallback)" if fip is not None else "xfip=unavailable")

        # SwStr%: prefer FanGraphs (decimal, e.g. 0.112); fall back to Statcast whiff_pct
        # (same concept, different denominator — pct scale, e.g. 28.5)
        swstr = fg.get("swstr_pct")
        if swstr is not None:
            add("swstr_pct", _season_rate_signal(swstr, 0.112, selection, 0.02),
                f"swstr_pct={swstr} (FG)")
        else:
            sc = get_pitcher_statcast(player_id, season)
            whiff = sc.get("whiff_pct")
            add("swstr_pct", _season_rate_signal(whiff, 25.0, selection, 5.0),
                f"swstr_pct={whiff} (Statcast whiff fallback)" if whiff is not None else "swstr_pct=unavailable")

        # Rest days: fresh pitcher → goes deeper → good for Over outs.
        rest = stats.get("rest_days")
        add("rest_days", _pitcher_rest_signal(rest, selection), f"rest_days={rest}")

        # Fastball velocity quality: hard throwers → good for outs Over (deeper starts).
        vt = fetch_pitcher_velo_trend(player_id, season)
        velo = vt.get("fastball_velo")
        add("velo_trend", _velo_trend_signal(velo, selection),
            f"fastball_velo={velo:.1f}mph" if velo is not None else "fastball_velo=unavailable")
    else:
        for sig in ("recent_ip", "season_ip", "opp_lineup_ops", "xfip", "swstr_pct",
                    "rest_days", "velo_trend"):
            add(sig, 0.5, "player_id unavailable")

    # Game total: high total = run-heavy environment → fewer outs for pitcher.
    # Applied regardless of player_id (game-level context).
    add("game_total", _game_total_signal(game_total, selection),
        f"game_total={game_total}" if game_total is not None else "game_total=unavailable")

    return breakdown


def _score_batter(
    player_id: int | None,
    market_key: str,
    selection: str,
    point: float,
    edge: float,
    park: dict,
    weather: dict,
    game_info: dict | None,
    home_team: str,
    away_team: str,
    season: int,
    player_team: str | None = None,
) -> list[dict]:
    from stats import fetch_batter_stats
    from signals.splits import get_batter_splits
    from signals.statcast import get_batter_statcast

    is_tb = market_key == "batter_total_bases"
    weights = SIGNAL_WEIGHTS.get(market_key)
    if weights is None:
        raise ValueError(f"No SIGNAL_WEIGHTS entry for market {market_key!r}")
    breakdown = []

    def add(signal, raw, note=""):
        pts = round(raw * weights.get(signal, 0))
        breakdown.append({"signal": signal, "raw": round(raw, 3),
                          "pts": pts, "max": weights.get(signal, 0), "note": note})

    add("edge", _edge_signal(edge), f"edge={edge:.1%}")

    pf = park.get("tb_factor" if is_tb else "hits_factor", 100)
    add("park_tb_factor" if is_tb else "park_hits_factor",
        _park_factor_signal(pf, selection), f"park_factor={pf}")

    add("weather_wind" if is_tb else "weather",
        _weather_signal(weather, selection),
        f"tailwind={weather.get('tailwind_factor', 0.5):.2f}")

    sp = None
    if game_info:
        pt = (player_team or "").lower()
        ht = home_team.lower()
        if pt and (pt in ht or ht in pt):
            sp = game_info.get("away_sp")   # batter on home team faces away SP
        else:
            sp = game_info.get("home_sp")   # batter on away team faces home SP
    if sp and sp.get("era") is not None:
        add("sp_quality", _era_signal(sp["era"], selection),
            f"sp={sp.get('name','?')} ERA={sp['era']:.2f}")
    else:
        add("sp_quality", 0.5, "SP ERA unavailable")

    if player_id:
        stats = fetch_batter_stats(player_id, season) or {}
        recent_key = "recent_tb_per_game" if is_tb else "recent_h_per_game"
        recent = stats.get(recent_key)
        add("recent_tb" if is_tb else "recent_h",
            _recent_rate_signal(recent, point, selection, 0.3),
            f"recent={recent}")

        season_key = "season_slg" if is_tb else "season_avg"
        rate = stats.get(season_key)
        benchmark = 0.420 if is_tb else 0.255
        add("season_slg" if is_tb else "season_avg",
            _season_rate_signal(rate, benchmark, selection, 0.06 if is_tb else 0.03),
            f"{season_key}={rate}")

        splits = get_batter_splits(player_id, season)
        sp_hand = sp.get("hand") if sp else None
        if sp_hand in ("L", "R"):
            slg_key = f"slg_vs_{'lhp' if sp_hand == 'L' else 'rhp'}"
            slg_opp = f"slg_vs_{'rhp' if sp_hand == 'L' else 'lhp'}"
            s1, s2 = splits.get(slg_key), splits.get(slg_opp)
            add("platoon_alignment",
                _platoon_signal(sp_hand, "batter", s1, s2, selection),
                f"slg_vs_{sp_hand}={s1} vs_opp={s2}")
        else:
            add("platoon_alignment", 0.5, "SP hand unknown")

        # Statcast contact quality signals
        sc = get_batter_statcast(player_id, season)

        # xwOBA: benchmark .320 (league avg), spread 0.040
        xwoba = sc.get("xwoba")
        add("xwoba", _season_rate_signal(xwoba, 0.320, selection, 0.040),
            f"xwoba={xwoba}")

        if is_tb:
            # Barrel% strongly predicts extra-base hits (benchmark 7.5%, spread 3 pct-points)
            barrel = sc.get("barrel_pct")
            add("barrel_pct", _season_rate_signal(barrel, 7.5, selection, 3.0),
                f"barrel_pct={barrel}")

        # Hard hit% (benchmark 38%, spread 5 pct-points)
        hard_hit = sc.get("hard_hit_pct")
        add("hard_hit_pct", _season_rate_signal(hard_hit, 38.0, selection, 5.0),
            f"hard_hit_pct={hard_hit}")

        # Batter vs pitcher H2H (career, min 5 AB). Benchmark .255 avg, spread 0.060.
        pitcher_id = sp.get("id") if sp else None
        if pitcher_id:
            from stats import fetch_batter_vs_pitcher
            h2h = fetch_batter_vs_pitcher(player_id, pitcher_id, season)
            if h2h:
                avg = h2h["avg"]
                add("h2h", _season_rate_signal(avg, 0.255, selection, 0.060),
                    f"h2h={h2h['hits']}/{h2h['ab']} ({avg:.3f})" if avg is not None else
                    f"h2h={h2h['hits']}/{h2h['ab']} (avg=None)")
            else:
                add("h2h", 0.5, "h2h=<5 AB or unavailable")
        else:
            add("h2h", 0.5, "h2h=pitcher_id unknown")

        # Batting order position (1-9). Positions 3-5 are power slots (good for Over);
        # positions 7-9 are weak (good for Under). Falls back to 0.5 if lineup not confirmed.
        bat_pos = None
        if game_info and player_id:
            pt = (player_team or "").lower()
            ht = home_team.lower()
            if pt and (pt in ht or ht in pt):
                bat_pos = game_info.get("home_lineup", {}).get(player_id)
            else:
                bat_pos = game_info.get("away_lineup", {}).get(player_id)
        add("batting_order", _batting_order_signal(bat_pos, selection),
            f"batting_order={bat_pos}")
    else:
        # Emit market-specific fallbacks explicitly to avoid weight gaps (H-01)
        base_sigs = [
            "recent_tb" if is_tb else "recent_h",
            "season_slg" if is_tb else "season_avg",
            "platoon_alignment",
        ]
        statcast_sigs = ["xwoba", "hard_hit_pct"] + (["barrel_pct"] if is_tb else [])
        for sig in base_sigs + statcast_sigs + ["h2h", "batting_order"]:
            add(sig, 0.5, "player_id unavailable")

    return breakdown


# ── main entry point ──────────────────────────────────────────────────────────

def score_pick(
    player_name: str,
    market_key: str,
    selection: str,
    point: float,
    home_team: str,
    away_team: str,
    edge: float,
    game_date: str,
    game_data: dict | None = None,
    game_total: float | None = None,
) -> tuple[int, list[dict]]:
    """
    Returns (score 0-100, breakdown list).
    breakdown items: {signal, raw, pts, max, note}
    game_data: pre-fetched from lineups.get_game_data_for_date(). None = partial score.
    """
    from stats import find_player_info

    season = int(game_date[:4])

    park = get_park(home_team)

    weather_data = get_weather(
        park["lat"], park["lon"], game_date,
        park["cf_bearing"], park["is_dome"]
    )

    game_info = None
    if game_data is not None:
        from signals.lineups import find_game
        game_info = find_game(game_data, home_team, away_team)

    # Resolve player_id and team
    player_id = None
    player_team = None
    try:
        info = find_player_info(player_name, season)
        if info:
            player_id = info["id"]
            player_team = info.get("team_name", "")
    except Exception as exc:
        _log.warning("player lookup failed for %r (season=%s): %s", player_name, season, exc)

    # Determine opposing team for pitcher signals (pitcher's opponents, not their own team)
    opp_team: str | None = None
    if game_info:
        pt = (player_team or "").lower()
        ht = home_team.lower()
        if pt and (pt in ht or ht in pt):
            opp_team = game_info.get("away_team")   # pitcher on home team, faces away lineup
        else:
            opp_team = game_info.get("home_team")   # pitcher on away team, faces home lineup

    # Guard: batter markets must have a SIGNAL_WEIGHTS entry — fail loud before entering the try block
    if market_key in ("batter_total_bases", "batter_hits") and SIGNAL_WEIGHTS.get(market_key) is None:
        raise ValueError(f"No SIGNAL_WEIGHTS entry for market {market_key!r}")

    try:
        if market_key == "pitcher_strikeouts":
            breakdown = _score_pitcher_strikeouts(
                player_id, selection, point, edge, park, weather_data, game_info, season,
                opp_team=opp_team)
        elif market_key == "pitcher_hits_allowed":
            breakdown = _score_pitcher_hits_allowed(
                player_id, selection, point, edge, park, weather_data, game_info, season,
                opp_team=opp_team)
        elif market_key == "pitcher_outs":
            breakdown = _score_pitcher_outs(
                player_id, selection, point, edge, park, weather_data, game_info, season,
                opp_team=opp_team, game_total=game_total)
        elif market_key in ("batter_total_bases", "batter_hits"):
            breakdown = _score_batter(
                player_id, market_key, selection, point, edge,
                park, weather_data, game_info, home_team, away_team, season,
                player_team=player_team)
        else:
            # Minimal score for unsupported markets
            breakdown = [{"signal": "edge", "raw": _edge_signal(edge),
                          "pts": round(_edge_signal(edge) * 50), "max": 50, "note": "unsupported market"}]
    except Exception as exc:
        breakdown = [{"signal": "error", "raw": 0.5, "pts": 0, "max": 0, "note": str(exc)}]

    total = sum(b["pts"] for b in breakdown)
    return int(min(100, max(0, total))), breakdown


def tier_from_score(score: int) -> str:
    """RECOMMENDED / LEAN / NO_BET based on score thresholds."""
    if score >= SCORE_RECOMMENDED:
        return "RECOMMENDED"
    if score >= SCORE_LEAN:
        return "LEAN"
    return "NO_BET"
