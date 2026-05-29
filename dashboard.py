import html as _html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

import streamlit as st
import sqlite3
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta, timezone

from db import (
    get_conn as _db_conn,
    init_db,
    mark_bet_placed,
    mark_bet_skipped,
    mark_game_bet_placed,
    mark_game_bet_skipped,
    get_today_picks,
    get_active_bets,
    get_roi_by_market,
    get_roi_by_tier,
    get_cumulative_pnl,
    get_today_game_picks,
)
from config import DB_PATH, BET_PRICE_MIN, BET_PRICE_MAX
from config import pt_date as _pt_date
from edge import is_bet_recommendation, normalize_recommendation

MARKET_LABELS = {
    "pitcher_strikeouts":   "Strikeouts",
    "pitcher_hits_allowed": "Hits Allowed",
    "pitcher_earned_runs":  "Earned Runs",
    "pitcher_walks":        "Walks",
    "pitcher_outs":         "Outs Recorded",
    "batter_hits":          "Hits",
    "batter_total_bases":   "Total Bases",
    "batter_home_runs":     "Home Runs",
    "batter_rbis":          "RBIs",
    "batter_runs_scored":   "Runs Scored",
    "batter_stolen_bases":  "Stolen Bases",
    "batter_walks":         "Walks",
}

TEAM_NAMES = {
    "NYY": "New York Yankees",    "BOS": "Boston Red Sox",
    "TBR": "Tampa Bay Rays",      "BAL": "Baltimore Orioles",
    "TOR": "Toronto Blue Jays",   "CHW": "Chicago White Sox",
    "CLE": "Cleveland Guardians", "DET": "Detroit Tigers",
    "KCR": "Kansas City Royals",  "MIN": "Minnesota Twins",
    "HOU": "Houston Astros",      "LAA": "Los Angeles Angels",
    "OAK": "Oakland Athletics",   "SEA": "Seattle Mariners",
    "TEX": "Texas Rangers",       "ATL": "Atlanta Braves",
    "MIA": "Miami Marlins",       "NYM": "New York Mets",
    "PHI": "Philadelphia Phillies","WSN": "Washington Nationals",
    "CHC": "Chicago Cubs",        "CIN": "Cincinnati Reds",
    "MIL": "Milwaukee Brewers",   "PIT": "Pittsburgh Pirates",
    "STL": "St. Louis Cardinals", "ARI": "Arizona Diamondbacks",
    "COL": "Colorado Rockies",    "LAD": "Los Angeles Dodgers",
    "SDP": "San Diego Padres",    "SFG": "San Francisco Giants",
}

_SIG_GROUPS: dict[str, tuple[str, str]] = {
    "recent_tb":         ("Form",    "#f59e0b"),
    "recent_hits":       ("Form",    "#f59e0b"),
    "recent_h":          ("Form",    "#f59e0b"),
    "recent_hr":         ("Form",    "#f59e0b"),
    "recent_rbi":        ("Form",    "#f59e0b"),
    "recent_k":          ("Form",    "#f59e0b"),
    "recent_k_rate":     ("Form",    "#f59e0b"),
    "recent_ip":         ("Form",    "#f59e0b"),
    "sp_quality":        ("Matchup", "#34d399"),
    "home_sp_quality":   ("Matchup", "#34d399"),
    "away_sp_quality":   ("Matchup", "#34d399"),
    "opp_team_k_pct":    ("Matchup", "#34d399"),
    "opp_lineup_ops":    ("Matchup", "#34d399"),
    "opp_team_avg":      ("Matchup", "#34d399"),
    "home_team_offense": ("Offense", "#fb923c"),
    "away_team_offense": ("Offense", "#fb923c"),
    "ump_k_tendency":    ("Umpire",  "#a78bfa"),
    "umpire_run_factor": ("Umpire",  "#a78bfa"),
    "park_tb_factor":    ("Park",    "#94a3b8"),
    "park_hits_factor":  ("Park",    "#94a3b8"),
    "park_run_factor":   ("Park",    "#94a3b8"),
    "park_k_factor":     ("Park",    "#94a3b8"),
    "weather":           ("Weather", "#60a5fa"),
    "season_avg":        ("Stats",   "#818cf8"),
    "season_slg":        ("Stats",   "#818cf8"),
    "season_k_pct":      ("Stats",   "#818cf8"),
    "season_k9":         ("Stats",   "#818cf8"),
    "season_whip":       ("Stats",   "#818cf8"),
    "xwoba":             ("Stats",   "#818cf8"),
    "barrel_pct":        ("Stats",   "#818cf8"),
    "hard_hit_pct":      ("Stats",   "#818cf8"),
    "whiff_pct":         ("Stats",   "#818cf8"),
    "stuff_plus":        ("Stats",   "#818cf8"),
    "swstr_pct":         ("Stats",   "#818cf8"),
    "xfip":              ("Stats",   "#818cf8"),
}


def _breakdown_chips_html(breakdown: list) -> str:
    """Top signal-group chips from a breakdown list."""
    if not breakdown:
        return ""
    groups: dict[str, dict] = {}
    for sig in breakdown:
        signal = sig.get("signal", "")
        pts    = sig.get("pts", 0)
        if pts <= 0:
            continue
        cat, color = _SIG_GROUPS.get(signal, ("Other", "#64748b"))
        if cat not in groups:
            groups[cat] = {"pts": 0, "color": color}
        groups[cat]["pts"] += pts
    top = sorted(groups.items(), key=lambda x: -x[1]["pts"])[:3]
    if not top:
        return ""
    chips = "".join(
        f'<span style="background:#1a1d27;color:{info["color"]};border:1px solid #252a38;'
        f'border-radius:10px;font-size:10px;font-weight:600;padding:2px 7px;letter-spacing:0.3px">'
        f'{cat}</span>'
        for cat, info in top
    )
    return f'<div style="display:flex;gap:4px;flex-wrap:wrap;margin-top:6px">{chips}</div>'


# ── Four-lights system ────────────────────────────────────────────────────────

_PILL_COLORS: dict[str, tuple[str, str, str]] = {
    "green":  ("#0f2518", "#34d399", "#065f46"),
    "yellow": ("#1a1505", "#fbbf24", "#78350f"),
    "red":    ("#1f0e0e", "#f87171", "#7f1d1d"),
    "gray":   ("#161a24", "#64748b", "#334155"),
}
_DOT_COLORS: dict[str, str] = {
    "green": "#34d399", "yellow": "#fbbf24",
    "red":   "#f87171", "gray":   "#475569",
}
_SHADOW_BADGE_COLORS: dict[str, tuple[str, str, str]] = {
    "elite": ("#1e1f3a", "#818cf8", "#3730a3"),
    "good":  ("#1f1a0a", "#fbbf24", "#78350f"),
    "watch": ("#0c1a24", "#38bdf8", "#0369a1"),
    "pass":  ("#161a24", "#64748b", "#334155"),
}


def _build_cal_index() -> dict:
    from market_learn import load_calibration
    return {(r["market_key"], r["selection"], r["edge_bucket"]): r
            for r in load_calibration()}


def _light_setup(p: dict) -> tuple[str, str]:
    if p.get("market_key") in {"h2h", "spreads"}:
        return "gray", "Edge only"
    score = p.get("signal_score")
    if score is None:
        return "gray", "No score"
    if score >= 65: return "green",  f"Score {score}"
    if score >= 50: return "yellow", f"Score {score}"
    if score >= 45: return "yellow", f"Score {score} (weak)"
    return "red", f"Score {score} (weak)"


def _light_price(p: dict) -> tuple[str, str]:
    from edge import required_edge_for_price as _req_edge
    from config import BET_PRICE_MIN, BET_PRICE_MAX, MARKET_EDGE_MIN, EDGE_RECOMMENDED
    mkt, sel = p.get("market_key", ""), p.get("selection", "")
    price    = p.get("bovada_price")
    edge     = p.get("edge") or 0
    if price is None:
        return "gray", "No price"
    if not (BET_PRICE_MIN <= price <= BET_PRICE_MAX):
        return "red", f"Juice too high ({price:+d})"
    req = max(MARKET_EDGE_MIN.get((mkt, sel), 0.0), _req_edge(price))
    if edge < 0:
        return "red", f"Neg edge ({edge:.1%})"
    if edge < req:
        return "yellow", f"Edge short ({edge:.1%} < {req:.0%})"
    if edge >= EDGE_RECOMMENDED:
        return "green", f"Strong ({edge:.1%})"
    return "green", f"Clears ({edge:.1%})"


def _light_sim(p: dict) -> tuple[str, str]:
    bev = p.get("bovada_break_even_prob")
    sr  = p.get("_sim_result")
    if sr:
        source = sr.get("source", "")
        sim    = sr.get("sim_prob")
        if source in ("stored", "computed"):
            if sim is None or bev is None:
                return "gray", "Missing"
            diff = sim - bev
            tag  = "" if source == "stored" else "*"
            if diff >= 0.02:  return "green",  f"Sim{tag} {sim:.0%} vs {bev:.0%}"
            if diff >= -0.02: return "yellow", f"Sim{tag} close ({sim:.0%}/{bev:.0%})"
            return "red", f"Sim{tag} fails ({sim:.0%}<{bev:.0%})"
        reason = sr.get("reason") or source.replace("_", " ").capitalize()
        return "gray", reason or "Missing"
    # fallback when _sim_result not attached
    sim = p.get("sim_prob")
    if sim is None:
        return "gray", "Missing"
    if bev is None:
        return "gray", "No BEV"
    diff = sim - bev
    if diff >= 0.02:  return "green",  f"Sim {sim:.0%} vs {bev:.0%}"
    if diff >= -0.02: return "yellow", f"Close ({sim:.0%} vs {bev:.0%})"
    return "red", f"Fails ({sim:.0%} < {bev:.0%})"


def _light_track(p: dict, cal_index: dict) -> tuple[str, str]:
    from market_learn import _edge_bucket
    mkt, sel = p.get("market_key", ""), p.get("selection", "")
    bucket   = _edge_bucket(p.get("edge") or 0)
    cal      = cal_index.get((mkt, sel, bucket))
    if cal is None:
        return "gray", "No data"
    n = cal["total"]
    if n < 20:
        return "yellow", f"Small sample ({n})"
    diff = cal["edge_vs_breakeven"]
    if cal["profitable"]:
        return "green", f"{cal['win_rate']:.0%} WR +{diff:.1%} ({n}g)"
    return "red", f"{cal['win_rate']:.0%} WR {diff:.1%} ({n}g)"


def _shadow_rec(sc: str, pc: str, mc: str, tc: str) -> tuple[str, str]:
    """(shadow_label, tier_css_class) from four light colors."""
    if pc == "red":
        return "PASS", "pass"
    if mc == "red" and tc == "red":
        return "PASS", "pass"
    greens    = [sc, pc, mc, tc].count("green")
    hard_reds = sum(1 for c in [pc, mc, tc] if c == "red")
    if greens >= 3 and hard_reds == 0:
        return "ELITE", "elite"
    if greens >= 3 and hard_reds <= 1 and mc != "red":
        return "GOOD", "good"
    if greens >= 2:
        return "WATCH", "watch"
    if greens == 1 and pc != "red":
        return "WATCH", "watch"
    return "PASS", "pass"


def _lights_html_render(lights: dict) -> str:
    rows = [
        ("SETUP",        lights["setup"]),
        ("PRICE",        lights["price"]),
        ("SIMULATION",   lights["sim"]),
        ("TRACK RECORD", lights["track"]),
    ]
    pills = []
    for label, (color, reason) in rows:
        bg, txt, bdr = _PILL_COLORS[color]
        dot = _DOT_COLORS[color]
        pills.append(
            f'<div class="light-box" style="background:{bg};border:1px solid {bdr}">'
            f'<div class="light-top">'
            f'<span class="light-dot" style="background:{dot}"></span>'
            f'<span class="light-label">{label}</span>'
            f'</div>'
            f'<div class="light-reason" style="color:{txt}">'
            f'{_html.escape(reason)}</div>'
            f'</div>'
        )
    return '<div class="lights-grid">' + "".join(pills) + "</div>"


def _attach_lights(p: dict, cal_index: dict) -> None:
    """Compute and attach all four-light keys to a pick dict in place."""
    setup = _light_setup(p)
    price = _light_price(p)
    sim   = _light_sim(p)
    track = _light_track(p, cal_index)
    label, tier = _shadow_rec(setup[0], price[0], sim[0], track[0])
    p["_lights_html"]  = _lights_html_render({
        "setup": setup, "price": price, "sim": sim, "track": track,
        "shadow_label": label, "shadow_tier": tier,
    })
    p["_shadow_tier"]  = tier
    p["_shadow_label"] = label
    p["_setup_color"]  = setup[0]
    p["_price_color"]  = price[0]
    p["_sim_color"]    = sim[0]
    p["_track_color"]  = track[0]
    p["_setup_reason"] = setup[1]
    p["_price_reason"] = price[1]
    p["_sim_reason"]   = sim[1]
    p["_track_reason"] = track[1]


def _decision_badge_html(p: dict) -> str:
    tier = p.get("_shadow_tier") or _tier(p.get("recommendation", ""))
    label = p.get("_shadow_label") or _rec_label(p.get("recommendation", ""))
    bg, txt, bdr = _SHADOW_BADGE_COLORS.get(tier, _SHADOW_BADGE_COLORS["pass"])
    return (
        f'<span style="background:{bg};color:{txt};border:1px solid {bdr};'
        f'border-radius:20px;font-size:11px;font-weight:800;padding:4px 11px;'
        f'letter-spacing:0.8px;text-transform:uppercase;white-space:nowrap">'
        f'{_html.escape(str(label))}</span>'
    )


def _decision_why(p: dict) -> str:
    tier = str(p.get("_shadow_label") or _rec_label(p.get("recommendation", ""))).upper()
    setup = p.get("_setup_color")
    price = p.get("_price_color")
    sim = p.get("_sim_color")
    track = p.get("_track_color")

    if tier == "PASS":
        if price == "red":
            return f"Pass because price/value failed: {p.get('_price_reason', 'not enough value')}."
        if sim == "red":
            return f"Pass because simulation did not clear break-even: {p.get('_sim_reason', 'failed sim')}."
        if setup == "red":
            return f"Pass because the baseball setup is weak: {p.get('_setup_reason', 'weak setup')}."
        return "Pass because one major gate failed."

    if tier == "ELITE":
        return "Elite because setup, price, simulation, and track record are all aligned."
    if tier == "GOOD":
        return "Good because most lights are positive and no major gate is red."
    if tier == "WATCH":
        if price == "yellow":
            return f"Watchlist because the setup is interesting, but price is close: {p.get('_price_reason', 'edge short')}."
        if sim == "gray":
            return "Watchlist because simulation is missing or unavailable."
        if track == "gray":
            return "Watchlist because the track record sample is not strong enough yet."
        return "Watchlist because the pick has promise but is missing one green light."
    return "Decision is based on setup, price, simulation, and track record."


def _compute_pick_sim(p: dict, season: int) -> dict:
    """
    Run local bootstrap simulation. Uses MLB Stats API only — no Odds API calls.
    Returns {source, sim_prob, reason}.
    source: 'stored' | 'computed' | 'unsupported' | 'no_stats' | 'error'
    """
    from simulate import simulate_pick, MARKET_TO_STAT

    # Use stored value if present
    stored = p.get("sim_prob")
    if stored is not None:
        return {"source": "stored", "sim_prob": stored, "reason": ""}

    mkt = p.get("market_key", "")
    sel = p.get("selection", "")

    # Game markets have no simulator
    if mkt in {"h2h", "spreads", "totals"}:
        return {"source": "unsupported", "sim_prob": None,
                "reason": "No sim — game market"}

    # Prop market not covered by simulator
    if mkt not in MARKET_TO_STAT:
        return {"source": "unsupported", "sim_prob": None,
                "reason": f"No sim — {mkt}"}

    player = p.get("player_name") or ""
    point  = p.get("point")
    if not player or point is None:
        return {"source": "error", "sim_prob": None, "reason": "Missing player/line"}

    try:
        result = simulate_pick(player, mkt, sel, float(point), season)
    except Exception as exc:
        return {"source": "error", "sim_prob": None, "reason": str(exc)[:50]}

    if result is None:
        return {"source": "no_stats", "sim_prob": None,
                "reason": f"No stats — {player}"}

    return {
        "source":   "computed",
        "sim_prob": result["sim_prob"],
        "reason":   f"{result['n_games']}g sampled",
    }


def _get_sim(p: dict, season: int) -> dict:
    """Session-cached simulation: computed once per (player, market, line) per session."""
    stored = p.get("sim_prob")
    if stored is not None:
        return {"source": "stored", "sim_prob": stored, "reason": ""}

    cache: dict = st.session_state.setdefault("_sim_cache", {})
    key = (
        str(p.get("player_name", "")),
        str(p.get("market_key", "")),
        str(p.get("selection", "")),
        float(p.get("point") or 0),
        season,
    )
    if key not in cache:
        cache[key] = _compute_pick_sim(p, season)
    return cache[key]


def _daily_summary_html(prop_picks: list, game_picks: list) -> str:
    """Compact grouped summary for the top of the Props tab."""
    all_picks = prop_picks + game_picks
    if not all_picks:
        return ""

    def _pline(p: dict) -> str:
        name = (p.get("player_name")
                or f"{p.get('away_team','?')} @ {p.get('home_team','?')}")
        mkt  = MARKET_LABELS.get(p.get("market_key", ""), p.get("market_key", ""))
        sel  = p.get("selection", "")
        pt   = p.get("point")
        pt_s = f" {pt:g}" if pt is not None else ""
        edge = p.get("edge") or 0
        sc   = p.get("signal_score")
        sc_s = str(sc) if sc is not None else "—"
        tier = p.get("_shadow_tier", "pass")
        _, tc, _ = _SHADOW_BADGE_COLORS.get(tier, ("", "#64748b", ""))
        return (
            f'<div style="display:flex;gap:10px;padding:3px 0;'
            f'border-bottom:1px solid #1a1d27;font-size:12px;'
            f'align-items:baseline;flex-wrap:wrap">'
            f'<span style="color:#f1f5f9;font-weight:600;min-width:140px">'
            f'{_html.escape(str(name))}</span>'
            f'<span style="color:#64748b;flex:1">'
            f'{_html.escape(mkt)} {_html.escape(sel)}{pt_s}</span>'
            f'<span style="color:{tc};font-weight:600;min-width:55px">'
            f'Edge {edge:.1%}</span>'
            f'<span style="color:#475569;min-width:55px">Setup {sc_s}</span>'
            f'</div>'
        )

    near_miss = [
        p for p in all_picks
        if p.get("_price_color") == "yellow"
        and p.get("_setup_color") in ("green", "yellow")
        and p.get("_shadow_tier") not in ("elite", "good")
    ]
    bad_price = [
        p for p in all_picks
        if p.get("_price_color") == "red"
        and normalize_recommendation(p.get("recommendation", "")) in ("A_BET", "B_BET", "WATCH")
    ]
    missing_sim = [
        p for p in all_picks
        if p.get("_sim_color") == "gray"
        and normalize_recommendation(p.get("recommendation", "")) in ("A_BET", "B_BET", "WATCH")
    ]

    parts = ['<div style="font-family:Inter,-apple-system,sans-serif">']
    for tier, label, color in [
        ("elite", "Best Bets", "#818cf8"),
        ("good",  "Good",      "#fbbf24"),
        ("watch", "Watchlist", "#38bdf8"),
    ]:
        tier_picks = [p for p in all_picks if p.get("_shadow_tier") == tier]
        parts.append(
            f'<div style="font-size:11px;color:{color};font-weight:700;'
            f'text-transform:uppercase;letter-spacing:0.8px;margin:6px 0 3px">'
            f'{label} ({len(tier_picks)})</div>'
        )
        for p in tier_picks[:6]:
            parts.append(_pline(p))
        if not tier_picks:
            parts.append('<div style="font-size:12px;color:#2a3044;padding:2px 0">None</div>')

    for label, bucket, color in [
        ("Near Misses",        near_miss,   "#94a3b8"),
        ("Bad Price / Trap",   bad_price,   "#f87171"),
        ("Missing Simulation", missing_sim, "#64748b"),
    ]:
        parts.append(
            f'<div style="font-size:11px;color:{color};font-weight:700;'
            f'text-transform:uppercase;letter-spacing:0.8px;margin:6px 0 3px">'
            f'{label} ({len(bucket)})</div>'
        )
        for p in bucket[:4]:
            parts.append(_pline(p))
        if not bucket:
            parts.append('<div style="font-size:12px;color:#2a3044;padding:2px 0">None</div>')

    parts.append('</div>')
    return "".join(parts)


CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

* { box-sizing: border-box; }

[data-testid="stAppViewContainer"],
[data-testid="stHeader"] {
    background: #13151a !important;
}
[data-testid="block-container"] { background: transparent !important; }

section[data-testid="stSidebar"] {
    background: #0e1117;
    border-right: 1px solid #252a38;
}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {
    background: #1a1d27; border-radius: 6px; padding: 4px;
    border: 1px solid #252a38; gap: 2px;
}
.stTabs [data-baseweb="tab"] {
    color: #64748b; border-radius: 4px;
    font-family: 'Inter', -apple-system, sans-serif;
    font-size: 13px; font-weight: 500; letter-spacing: 0.3px;
    padding: 6px 18px;
}
.stTabs [data-baseweb="tab"][aria-selected="true"] {
    background: #252a38 !important; color: #e2e8f0 !important;
}

/* Typography */
h1, h2, h3, h4 {
    color: #f1f5f9 !important;
    font-family: 'Inter', -apple-system, sans-serif !important;
    font-weight: 600 !important;
}
p, label, .stMarkdown { color: #94a3b8 !important; }
hr { border-color: #252a38 !important; }

/* Stat boxes */
.stat-box {
    background: #1e2330;
    border: 1px solid #2a3044;
    border-radius: 8px;
    padding: 14px 12px;
    text-align: center;
    margin: 4px 0;
}
.stat-value {
    font-size: 22px; font-weight: 700; color: #f1f5f9;
    line-height: 1.2;
    font-family: 'Inter', -apple-system, sans-serif;
}
.stat-label {
    font-size: 10px; color: #64748b;
    text-transform: uppercase; letter-spacing: 1.5px; margin-top: 3px;
}

/* Day header */
.day-header {
    display: flex; justify-content: space-between; align-items: center;
    background: #1e2330; border-radius: 8px;
    padding: 12px 18px; margin-bottom: 14px;
    border: 1px solid #2a3044;
}
.day-header .dh-lbl { font-size: 10px; color: #64748b; text-transform: uppercase; letter-spacing: 1.5px; }
.day-header .dh-val { font-size: 15px; font-weight: 600; color: #f1f5f9; margin-top: 2px; }
.day-header .dh-stat { text-align: right; }

/* Section labels */
.section-label {
    font-size: 10px; color: #475569; text-transform: uppercase; letter-spacing: 2px;
    margin: 16px 0 8px; padding-bottom: 6px;
    border-bottom: 1px solid #1e2330;
}

/* Pick cards */
.pick {
    background: linear-gradient(180deg, #1b1f2a 0%, #171a23 100%);
    border: 1px solid #283044;
    border-radius: 10px;
    padding: 14px;
    margin: 0 0 10px 0;
    min-height: 230px;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.03);
}
.pick.elite  { border-top: 2px solid #6366f1; }
.pick.good   { border-top: 2px solid #f59e0b; }
.pick.watch  { border-top: 2px solid #0ea5e9; }
.pick.pass   { border-top: 2px solid #475569; }
.pick.game  { background: linear-gradient(180deg, #1a1e29 0%, #161922 100%); border-left: 3px solid #2a3044; }
.pick-head {
    display:flex; justify-content:space-between; align-items:flex-start;
    gap:12px; margin-bottom:10px;
}
.pick-name {
    font-size:17px; font-weight:700; color:#f1f5f9; line-height:1.2;
}
.pick-team {
    font-size:12px; color:#94a3b8; margin-top:3px;
}
.pick-meta {
    display:flex; align-items:center; gap:10px; margin-bottom:10px; flex-wrap:wrap;
}
.pick-pill {
    background:#252a38; color:#94a3b8; font-size:12px;
    border-radius:4px; padding:3px 9px;
}
.pick-line {
    font-size:15px; font-weight:700; color:#e2e8f0;
}
.pick-price {
    background:#10141d; color:#cbd5e1; font-size:13px;
    border-radius:4px; padding:3px 9px; border:1px solid #2a3044;
}
.pick-stats {
    display:flex; gap:20px; flex-wrap:wrap; margin-bottom:8px;
}
.pick-stat-label {
    font-size:10px; color:#475569; text-transform:uppercase; letter-spacing:0.8px;
}
.pick-stat-value {
    font-size:13px; color:#cbd5e1; font-weight:600;
}
.lights-grid {
    display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:6px; margin-top:10px;
}
.light-box {
    border-radius:7px; padding:7px 8px; min-height:58px;
    display:flex; flex-direction:column; justify-content:center;
}
.light-top {
    display:flex; align-items:center; gap:5px; margin-bottom:3px; min-width:0;
}
.light-dot {
    width:8px; height:8px; border-radius:50%; flex-shrink:0;
}
.light-label {
    font-size:9px; color:#64748b; text-transform:uppercase;
    letter-spacing:0.7px; font-weight:700; white-space:nowrap;
}
.light-reason {
    font-size:11px; font-weight:600; line-height:1.25;
    overflow:hidden; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical;
}
.decision-row {
    display:flex; gap:8px; align-items:center; flex-wrap:wrap;
    border-top:1px solid #252a38; margin-top:10px; padding-top:9px;
}
.decision-why {
    color:#94a3b8; font-size:12px; line-height:1.4; flex:1; min-width:180px;
}
@media (max-width: 700px) {
    .lights-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
    .pick { min-height: 0; }
}

/* Badges */
.badge {
    font-size: 11px; font-weight: 700; border-radius: 20px;
    padding: 3px 12px; letter-spacing: 0.8px; text-transform: uppercase;
    display: inline-block; white-space: nowrap;
}
.badge.elite { background: #1e1f3a; color: #818cf8; border: 1px solid #3730a3; }
.badge.good  { background: #1f1a0a; color: #fbbf24; border: 1px solid #78350f; }
.badge.watch { background: #0c1a24; color: #38bdf8; border: 1px solid #0369a1; }
.badge.pass  { background: #161a24; color: #64748b; border: 1px solid #334155; }

/* Result pills */
.r-win  { background:#0f2518;color:#34d399;border:1px solid #065f46;border-radius:20px;font-size:11px;font-weight:700;padding:3px 10px;display:inline-block; }
.r-loss { background:#1f0e0e;color:#f87171;border:1px solid #7f1d1d;border-radius:20px;font-size:11px;font-weight:700;padding:3px 10px;display:inline-block; }
.r-push { background:#1a1a3a;color:#a5b4fc;border:1px solid #3730a3;border-radius:20px;font-size:11px;font-weight:700;padding:3px 10px;display:inline-block; }

/* Buttons */
div.stButton > button {
    background: #1e2330; color: #94a3b8;
    border: 1px solid #2a3044; border-radius: 6px;
    font-family: 'Inter', -apple-system, sans-serif;
    font-size: 13px; font-weight: 600;
}
div.stButton > button:hover {
    border-color: #6366f1 !important; color: #818cf8 !important;
    background: #1e1f3a !important;
}

/* Expanders */
[data-testid="stExpander"] {
    background: #191c26 !important;
    border: 1px solid #1e2330 !important;
    border-radius: 6px !important;
    margin-bottom: 4px !important;
}
[data-testid="stExpander"] summary {
    color: #475569 !important;
    font-size: 12px !important;
    font-weight: 500 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.8px !important;
}

/* Number input */
[data-testid="stNumberInput"] input {
    background: #1e2330 !important;
    border: 1px solid #2a3044 !important;
    color: #e2e8f0 !important;
    border-radius: 6px !important;
    font-size: 13px !important;
    font-weight: 600 !important;
}

/* DataFrame */
[data-testid="stDataFrame"] { background: #1a1d27 !important; }
</style>
"""


def _mkt(key: str) -> str:
    return MARKET_LABELS.get(key, key)


def _rec_label(rec: str) -> str:
    rec = normalize_recommendation(rec)
    return {
        "A_BET": "Elite",
        "B_BET": "Good",
        "WATCH": "Watchlist",
        "PASS": "Pass",
    }.get(rec, rec)


def _full_team(abbr: str) -> str:
    return TEAM_NAMES.get(str(abbr).upper(), abbr or "")


def _tier(rec: str) -> str:
    rec = normalize_recommendation(rec)
    if rec == "A_BET":
        return "elite"
    if rec == "WATCH":
        return "watch"
    if rec == "PASS":
        return "pass"
    return "good"


def _render_stat(col, value: str, label: str, color: str = "#f1f5f9") -> None:
    col.markdown(
        f'<div class="stat-box">'
        f'<div class="stat-value" style="color:{color}">{value}</div>'
        f'<div class="stat-label">{label}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _result_html(p: dict) -> str:
    result = p.get("result") or "PENDING"
    pu = p.get("profit_units")
    if result == "WIN":
        pu_str = f" +{pu:.2f}u" if pu is not None else ""
        return f'<span class="r-win">WIN{_html.escape(pu_str)}</span>'
    if result == "LOSS":
        pu_str = f" {pu:.2f}u" if pu is not None else ""
        return f'<span class="r-loss">LOSS{_html.escape(pu_str)}</span>'
    if result == "PUSH":
        return '<span class="r-push">PUSH</span>'
    return ""


def _parse_why(player_name: str, market_key: str, selection: str, breakdown: list) -> str:
    """Translate signal breakdown into a readable sentence."""
    import re

    MKT_WORD = {
        "batter_total_bases":   "total bases",
        "batter_hits":          "hits",
        "pitcher_strikeouts":   "strikeouts",
        "pitcher_hits_allowed": "hits allowed",
        "pitcher_earned_runs":  "earned runs",
        "batter_home_runs":     "home runs",
        "batter_rbis":          "RBIs",
        "batter_runs_scored":   "runs scored",
        "batter_stolen_bases":  "stolen bases",
        "batter_walks":         "walks",
        "pitcher_walks":        "walks",
        "pitcher_outs":         "outs",
    }
    mkt_word = MKT_WORD.get(market_key, market_key.replace("_", " "))
    dir_word = selection.lower()

    def clean(note):
        return re.sub(r"[^\x20-\x7e]", " ", note or "").strip()

    def val(note, key):
        m = re.search(rf"{re.escape(key)}=([^\s]+)", clean(note))
        return m.group(1) if m else None

    top = sorted(breakdown, key=lambda b: b.get("pts", 0), reverse=True)
    parts = []
    seen = set()

    for sig in top:
        signal = sig.get("signal", "")
        note   = clean(sig.get("note", ""))
        pts    = sig.get("pts", 0)
        if signal in seen or pts <= 0:
            continue
        seen.add(signal)

        # ── batter signals ────────────────────────────────────────────
        if signal == "sp_quality":
            m = re.search(r"sp=(.+?)\s+ERA=([\d.]+)", note)
            if m:
                parts.insert(0, f"facing {m.group(1)} (ERA {m.group(2)})")
            else:
                sp = re.sub(r"^sp=", "", re.sub(r"\s+ERA.*", "", note)).strip()
                if sp:
                    parts.insert(0, f"facing {sp}")

        elif signal in ("recent_tb", "recent_hits", "recent_h", "recent_hr", "recent_rbi"):
            v = val(note, "recent")
            if v and v != "None":
                lbl = {"recent_tb": "TB", "recent_hits": "hits", "recent_h": "hits",
                       "recent_hr": "HR", "recent_rbi": "RBI"}.get(signal, "")
                parts.append(f"averaging {v} {lbl}/game recently".strip())

        elif signal in ("season_slg", "season_avg"):
            key = "season_slg" if signal == "season_slg" else "season_avg"
            v = val(note, key)
            if v and v != "None":
                try:
                    lbl = "SLG" if signal == "season_slg" else "avg"
                    parts.append(f"season {lbl} {float(v):.3f}")
                except ValueError:
                    pass

        elif signal == "xwoba":
            v = val(note, "xwoba")
            if v and v not in ("None", "0.0", "0"):
                try:
                    parts.append(f"xwOBA {float(v):.3f}")
                except ValueError:
                    pass

        elif signal == "barrel_pct":
            v = val(note, "barrel_pct")
            if v and v != "None":
                try:
                    parts.append(f"{float(v):.1f}% barrel rate")
                except ValueError:
                    pass

        elif signal == "hard_hit_pct":
            v = val(note, "hard_hit_pct")
            if v and v != "None":
                try:
                    parts.append(f"{float(v):.1f}% hard-contact rate")
                except ValueError:
                    pass

        # ── pitcher strikeout signals ─────────────────────────────────
        elif signal == "ump_k_tendency":
            m = re.search(r"ump=(.+?)\s+\(([+-][\d.]+)\)", note)
            if m:
                ump_name = m.group(1)
                ump_val  = float(m.group(2))
                zone_desc = "wide zone" if ump_val >= 0.2 else ("tight zone" if ump_val <= -0.2 else "average zone")
                parts.append(f"umpire {ump_name} ({zone_desc}, {ump_val:+.1f})")

        elif signal == "opp_team_k_pct":
            v = val(note, "opp_k_pct")
            if v and v != "None":
                try:
                    pct = float(v.rstrip("%")) if "%" in v else float(v) * 100
                    tendency = "high" if pct > 23.5 else "low"
                    parts.append(f"opponent K rate {pct:.1f}% ({tendency})")
                except ValueError:
                    pass

        elif signal in ("recent_k_rate", "recent_k"):
            v = val(note, "recent_k")
            if v and v != "None":
                try:
                    parts.append(f"averaging {float(v):.1f} Ks/start recently")
                except ValueError:
                    pass

        elif signal in ("season_k_pct", "season_k9"):
            v = val(note, "k9")
            if v and v != "None":
                try:
                    parts.append(f"{float(v):.1f} K/9 this season")
                except ValueError:
                    pass

        elif signal == "whiff_pct":
            v = val(note, "whiff_pct")
            if v and v != "None":
                try:
                    parts.append(f"{float(v):.1f}% whiff rate")
                except ValueError:
                    pass

        elif signal == "stuff_plus":
            v = val(note, "stuff_plus")
            if v and v != "None":
                try:
                    sp_val = float(v)
                    desc = "elite" if sp_val >= 115 else ("above avg" if sp_val >= 100 else "below avg")
                    parts.append(f"Stuff+ {sp_val:.0f} ({desc})")
                except ValueError:
                    pass

        # ── pitcher hits/outs signals ─────────────────────────────────
        elif signal == "season_whip":
            v = val(note, "whip")
            if v and v != "None":
                parts.append(f"WHIP {v}")

        elif signal == "opp_team_avg":
            v = val(note, "opp_avg")
            if v and v != "None":
                parts.append(f"opponent avg {v}")

        elif signal == "recent_ip":
            v = val(note, "recent_ip")
            if v and v != "None":
                parts.append(f"averaging {v} IP/start recently")

        elif signal == "opp_lineup_ops":
            v = val(note, "opp_ops")
            if v and v != "None":
                try:
                    parts.append(f"opponent OPS {float(v):.3f}")
                except ValueError:
                    pass

        elif signal == "xfip":
            v = val(note, "xfip")
            if v and v != "None":
                try:
                    parts.append(f"xFIP {float(v):.2f}")
                except ValueError:
                    pass

        elif signal == "swstr_pct":
            v = val(note, "swstr_pct")
            if v and v != "None":
                try:
                    parts.append(f"{float(v)*100:.1f}% swinging-strike rate")
                except ValueError:
                    pass

        # ── park signal ───────────────────────────────────────────────
        elif signal in ("park_tb_factor", "park_hits_factor", "park_run_factor", "park_k_factor"):
            v = (val(note, "park_factor") or val(note, "hits_factor")
                 or val(note, "hr_factor") or val(note, "k_factor"))
            if v and v != "None":
                try:
                    pf = int(v)
                    if pf != 100:
                        lbl = "hitter-friendly" if pf > 100 else "pitcher-friendly"
                        parts.append(f"park factor {pf} ({lbl})")
                except ValueError:
                    pass

        if len(parts) >= 4:
            break

    # ── game total signals (different structure) ──────────────────────
    if market_key == "totals":
        sp_parts  = []
        off_parts = []
        env_parts = []

        for sig in sorted(breakdown, key=lambda b: b.get("pts", 0), reverse=True):
            signal = sig.get("signal", "")
            note   = clean(sig.get("note", ""))
            pts    = sig.get("pts", 0)
            if pts <= 0 or note in ("no_data", ""):
                continue

            if signal in ("home_sp_quality", "away_sp_quality"):
                m = re.match(r"^(.+?)\s+era=", note)
                sp_name = m.group(1) if m else None
                era_v   = val(note, "era")
                whiff_v = val(note, "whiff")
                if sp_name and sp_name != "?":
                    side = "Home" if signal == "home_sp_quality" else "Away"
                    details = []
                    if era_v and era_v != "None":
                        try:
                            details.append(f"ERA {float(era_v):.2f}")
                        except ValueError:
                            pass
                    if whiff_v and whiff_v != "None":
                        try:
                            details.append(f"{float(whiff_v):.0f}% whiff")
                        except ValueError:
                            pass
                    desc = f"{side}: {sp_name}"
                    if details:
                        desc += f" ({', '.join(details)})"
                    if len(sp_parts) < 2:
                        sp_parts.append(desc)

            elif signal in ("home_team_offense", "away_team_offense"):
                m = re.match(r"^(.+?)\s+rpg=", note)
                team_name = m.group(1) if m else None
                rpg_v = val(note, "rpg")
                ops_v = val(note, "ops")
                if team_name and rpg_v and rpg_v != "None":
                    try:
                        rpg_f = float(rpg_v)
                        desc = f"{team_name} {rpg_f:.1f} R/G"
                        if ops_v and ops_v != "None":
                            desc += f" (OPS {float(ops_v):.3f})"
                        if len(off_parts) < 2:
                            off_parts.append(desc)
                    except ValueError:
                        pass

            elif signal == "umpire_run_factor":
                m = re.search(r"ump=(.+?)\s+\(([+-][\d.]+)\)", note)
                if m:
                    ump_name = m.group(1)
                    ump_val  = float(m.group(2))
                    zone_desc = "wide zone" if ump_val >= 0.2 else ("tight zone" if ump_val <= -0.2 else "average zone")
                    run_impact = "suppresses runs" if ump_val >= 0.2 else ("inflates runs" if ump_val <= -0.2 else "neutral")
                    env_parts.append(f"umpire {ump_name} ({zone_desc}, {run_impact})")

            elif signal == "park_run_factor":
                hr_v   = val(note, "hr_factor")
                hits_v = val(note, "hits_factor")
                if hr_v and hr_v != "None":
                    try:
                        if hits_v and hits_v != "None":
                            composite = int(hr_v) * 0.6 + int(hits_v) * 0.4
                            park_note = f"HR {hr_v}, hits {hits_v}"
                        else:
                            composite = int(hr_v)
                            park_note = f"HR {hr_v}"
                        if composite != 100:
                            lbl = "hitter-friendly park" if composite > 100 else "pitcher-friendly park"
                            env_parts.append(f"{lbl} ({park_note})")
                    except ValueError:
                        pass

            elif signal == "weather":
                wind_v = val(note, "wind")
                tf_v   = val(note, "tf")
                if wind_v and tf_v:
                    try:
                        m_wind = re.match(r"[\d.]+", wind_v)
                        if not m_wind:
                            continue
                        wind_kph = float(m_wind.group())
                        tf       = float(tf_v)
                        if wind_kph > 10:
                            wind_dir = "blowing out" if tf > 0.6 else ("blowing in" if tf < 0.4 else "crosswind")
                            env_parts.append(f"wind {wind_kph:.0f} kph ({wind_dir})")
                    except ValueError:
                        pass

        sections = []
        if sp_parts:
            sections.append(" · ".join(sp_parts))
        if off_parts:
            sections.append(", ".join(off_parts))
        if env_parts:
            sections.append(", ".join(env_parts[:2]))

        if not sections:
            return f"Model signals favor {dir_word} total — score reflects edge strength."
        return f"{'; '.join(sections)}. Model favors {dir_word} total."

    # ── prop picks ────────────────────────────────────────────────────
    if not parts:
        return f"Model signals favor {dir_word} {mkt_word} — score reflects edge strength."

    pitcher = [p for p in parts if p.startswith("facing")]
    stats   = [p for p in parts if not p.startswith("facing")]

    if pitcher and stats:
        return f"{player_name} is {pitcher[0]}, {', '.join(stats[:3])}. Model favors {dir_word} {mkt_word}."
    elif pitcher:
        return f"{player_name} is {pitcher[0]}. Model favors {dir_word} {mkt_word}."
    else:
        return f"{player_name}: {', '.join(parts[:4])}. Model favors {dir_word} {mkt_word}."


def _why_content(p: dict, breakdown: list, sim_prob, bev) -> None:
    player  = str(p.get("player_name") or p.get("away_team", "") + " @ " + p.get("home_team", ""))
    market  = p.get("market_key", "")
    sel     = p.get("selection", "")

    text = _parse_why(player, market, sel, breakdown)
    st.markdown(
        f'<div style="font-size:13px;color:#94a3b8;line-height:1.65;padding:2px 0">'
        f'{_html.escape(text)}</div>',
        unsafe_allow_html=True,
    )

    if sim_prob is not None and bev is not None:
        sim_pct = round(sim_prob * 100, 1)
        bev_pct = round(bev * 100, 1)
        color   = "#34d399" if sim_prob >= bev else "#f87171"
        st.markdown(
            f'<span style="font-size:12px;color:{color};font-weight:600">Sim {sim_pct}%</span>'
            f'<span style="font-size:12px;color:#64748b"> vs {bev_pct}% break-even</span>',
            unsafe_allow_html=True,
        )


def _bet_badge_html(p: dict) -> str:
    if p.get("bet_placed") == 1:
        u = p.get("units_wagered") or "?"
        u_str = f"{u:g}u" if isinstance(u, (int, float)) else f"{u}u"
        return (f'<span style="background:#0f2518;color:#34d399;border:1px solid #065f46;'
                f'border-radius:20px;font-size:11px;font-weight:700;padding:3px 10px;'
                f'display:inline-block;letter-spacing:0.8px">BET {u_str}</span>')
    return ""


def _is_edge_only_game_market(p: dict) -> bool:
    return p.get("market_key") in {"h2h", "spreads"}


def _game_market_label(p: dict) -> str:
    market = p.get("market_key")
    if market == "h2h":
        return "Moneyline"
    if market == "spreads":
        return "Run Line"
    return "Game Total"


def _game_selection_label(p: dict) -> str:
    selection = str(p.get("selection") or "")
    if p.get("market_key") == "h2h":
        team = p.get("home_team") if selection == "Home" else p.get("away_team")
        return _html.escape(str(team or selection))
    if p.get("market_key") == "spreads":
        team = p.get("home_team") if selection == "Home" else p.get("away_team")
        point = p.get("point")
        point_s = f"{point:+g}" if point is not None else ""
        return _html.escape(f"{team or selection} {point_s}".strip())
    point = p.get("point")
    point_s = f"{point:g}" if point is not None else "?"
    return _html.escape(f"{selection} {point_s}")


def _time_sort_key(p: dict) -> tuple:
    commence = str(p.get("commence_time") or "")
    return (commence, str(p.get("player_name") or ""), str(p.get("market_key") or ""))


def _prop_card_html(p: dict) -> str:
    t     = _tier(p["recommendation"])
    lbl   = _rec_label(p["recommendation"])
    edge  = p.get("edge") or 0

    try:
        breakdown = json.loads(p.get("signal_breakdown") or "[]")
    except Exception:
        breakdown = []
    chips_html = _breakdown_chips_html(breakdown)

    edge_col = {"elite": "#818cf8", "pass": "#64748b"}.get(t, "#fbbf24")

    p_name    = _html.escape(str(p["player_name"]))
    team      = _html.escape(_full_team(p.get("team_abbr") or ""))
    mkt       = _html.escape(_mkt(p["market_key"]))
    sel       = _html.escape(str(p["selection"]))
    point_s   = f"{p['point']:g}" if p["point"] is not None else "?"
    price_s   = f"{p['bovada_price']:+d}" if p["bovada_price"] is not None else "—"
    edge_s    = f"{edge:.1%}"
    ev_s      = f"{(p.get('ev') or 0):+.1%}"
    books_s   = str(p.get("consensus_book_count") or "?")
    res_html  = _result_html(p)
    bet_badge = _bet_badge_html(p)
    decision_badge = _decision_badge_html(p)
    decision_why = _html.escape(_decision_why(p))
    tracked_style = "border-left:3px solid #34d399;background:#0d1812;" if p.get("bet_placed") == 1 else ""

    return f"""
<div class="pick {t}" style="{tracked_style}">
  <div>
      <div class="pick-head">
        <div>
          <div class="pick-name">{p_name}</div>
          <div class="pick-team">{team}</div>
        </div>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;justify-content:flex-end">{bet_badge}{res_html}</div>
      </div>
      <div class="pick-meta">
        <span class="pick-pill">{mkt}</span>
        <span class="pick-line">{sel} {point_s}</span>
        <span class="pick-price">{price_s}</span>
      </div>
      <div class="pick-stats">
        <div>
          <div class="pick-stat-label">Edge</div>
          <div class="pick-stat-value" style="color:{edge_col}">{edge_s}</div>
        </div>
        <div>
          <div class="pick-stat-label">EV</div>
          <div class="pick-stat-value">{ev_s}</div>
        </div>
        <div>
          <div class="pick-stat-label">Books</div>
          <div class="pick-stat-value">{books_s}</div>
        </div>
      </div>
      {chips_html}
      {p.get("_lights_html", "")}
      <div class="decision-row">{decision_badge}<div class="decision-why">{decision_why}</div></div>
  </div>
</div>"""


def _game_card_html(p: dict) -> str:
    t         = _tier(p["recommendation"])
    lbl       = _rec_label(p["recommendation"])
    edge_only = _is_edge_only_game_market(p)
    edge      = p.get("edge") or 0

    if edge_only:
        chips_html  = ""
    else:
        try:
            breakdown = json.loads(p.get("signal_breakdown") or "[]")
        except Exception:
            breakdown = []
        chips_html = _breakdown_chips_html(breakdown)

    edge_col   = {"elite": "#818cf8", "pass": "#64748b"}.get(t, "#fbbf24")

    away      = _html.escape(str(p.get("away_team") or "?"))
    home      = _html.escape(str(p.get("home_team") or "?"))
    market_s  = _html.escape(_game_market_label(p))
    pick_s    = _game_selection_label(p)
    price_s   = f"{p['bovada_price']:+d}" if p["bovada_price"] is not None else "—"
    edge_s    = f"{edge:.1%}"
    books_s   = str(p.get("consensus_book_count") or "?")
    res_html  = _result_html(p)
    bet_badge = _bet_badge_html(p)
    decision_badge = _decision_badge_html(p)
    decision_why = _html.escape(_decision_why(p))
    tracked_style = "border-left:3px solid #34d399;background:#0d1812;" if p.get("bet_placed") == 1 else ""

    actual      = p.get("actual_total")
    actual_html = ""
    if actual is not None and (p.get("result") or "PENDING") != "PENDING":
        actual_html = (
            f'<div style="font-size:11px;color:#64748b;margin-top:4px">'
            f'Actual: <span style="color:#94a3b8">{actual:g} runs</span></div>'
        )

    return f"""
<div class="pick {t} game" style="{tracked_style}">
  <div>
      <div class="pick-head">
        <div>
          <div class="pick-name">{away} @ {home}</div>
          <div class="pick-team">{market_s}</div>
        </div>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;justify-content:flex-end">{bet_badge}{res_html}</div>
      </div>
      <div class="pick-meta">
        <span class="pick-pill">{market_s}</span>
        <span class="pick-line">{pick_s}</span>
        <span class="pick-price">{price_s}</span>
      </div>
      <div class="pick-stats">
        <div>
          <div class="pick-stat-label">Edge</div>
          <div class="pick-stat-value" style="color:{edge_col}">{edge_s}</div>
        </div>
        <div>
          <div class="pick-stat-label">Books</div>
          <div class="pick-stat-value">{books_s}</div>
        </div>
      </div>
      {chips_html}{actual_html}
      {p.get("_lights_html", "")}
      <div class="decision-row">{decision_badge}<div class="decision-why">{decision_why}</div></div>
  </div>
</div>"""


def _track_strip(conn, p: dict, id_field: str = "id") -> None:
    """Render unit selector + Track/Skip buttons below a card."""
    pick_id = p[id_field]
    score   = p.get("signal_score") or 0
    result  = p.get("result") or "PENDING"

    if p["bet_placed"] == 1:
        units_esc = _html.escape(str(p["units_wagered"] or "?"))
        st.markdown(
            f'<div style="padding:6px 0 2px;font-size:12px;color:#34d399;font-weight:600">'
            f'Tracked &nbsp;·&nbsp; {units_esc}u placed</div>',
            unsafe_allow_html=True,
        )
        return
    if p["bet_placed"] == -1:
        st.markdown(
            '<div style="padding:6px 0 2px;font-size:12px;color:#475569">Skipped</div>',
            unsafe_allow_html=True,
        )
        return

    # Still pending — show track controls
    if result != "PENDING":
        # Already graded but never tracked
        st.markdown(
            '<div style="padding:6px 0 2px;font-size:11px;color:#475569;font-style:italic">Not tracked</div>',
            unsafe_allow_html=True,
        )
        return

    rec = normalize_recommendation(p.get("recommendation", ""))
    max_units = 1.5 if rec == "A_BET" else 1.0
    default_units = 1.0 if rec == "A_BET" else 0.5
    step_units = 0.5 if rec == "A_BET" else 0.25
    u_col, b_col, s_col, _ = st.columns([1.2, 1.2, 0.9, 3])

    units = u_col.number_input(
        "Units",
        min_value=0.25,
        max_value=float(max_units),
        value=default_units,
        step=step_units,
        key=f"u_{pick_id}",
        label_visibility="collapsed",
        help=f"Max {max_units:g}u for {_rec_label(p.get('recommendation', ''))}",
    )
    if b_col.button("Track Bet", key=f"b_{pick_id}"):
        mark_bet_placed(conn, pick_id, units)
        conn.close()
        st.rerun()
    if s_col.button("Skip", key=f"s_{pick_id}"):
        mark_bet_skipped(conn, pick_id)
        conn.close()
        st.rerun()

    st.markdown(
        '<div style="font-size:10px;color:#3a4058;margin-top:2px">Elite: max 1.5u default 1u; Good: max 1u default 0.5u</div>',
        unsafe_allow_html=True,
    )


def _game_track_strip(conn, p: dict) -> None:
    """Track strip for daily_game_picks rows."""
    pick_id = p["id"]
    score   = p.get("signal_score") or 0
    result  = p.get("result") or "PENDING"

    if p["bet_placed"] == 1:
        units_esc = _html.escape(str(p.get("units_wagered") or "?"))
        st.markdown(
            f'<div style="padding:6px 0 2px;font-size:12px;color:#34d399;font-weight:600">'
            f'Tracked &nbsp;·&nbsp; {units_esc}u placed</div>',
            unsafe_allow_html=True,
        )
        return
    if p["bet_placed"] == -1:
        st.markdown(
            '<div style="padding:6px 0 2px;font-size:12px;color:#475569">Skipped</div>',
            unsafe_allow_html=True,
        )
        return

    if result != "PENDING":
        st.markdown(
            '<div style="padding:6px 0 2px;font-size:11px;color:#475569;font-style:italic">Not tracked</div>',
            unsafe_allow_html=True,
        )
        return

    rec = normalize_recommendation(p.get("recommendation", ""))
    max_units = 1.5 if rec == "A_BET" else 1.0
    default_units = 1.0 if rec == "A_BET" else 0.5
    step_units = 0.5 if rec == "A_BET" else 0.25
    u_col, b_col, s_col, _ = st.columns([1.2, 1.2, 0.9, 3])
    units = u_col.number_input(
        "Units", min_value=0.25, max_value=float(max_units), value=default_units, step=step_units,
        key=f"gu_{pick_id}", label_visibility="collapsed",
        help=f"Max {max_units:g}u for {_rec_label(p.get('recommendation', ''))}",
    )
    if b_col.button("Track Bet", key=f"gb_{pick_id}"):
        mark_game_bet_placed(conn, pick_id, units)
        conn.close()
        st.rerun()
    if s_col.button("Skip", key=f"gs_{pick_id}"):
        mark_game_bet_skipped(conn, pick_id)
        conn.close()
        st.rerun()
    st.markdown(
        '<div style="font-size:10px;color:#3a4058;margin-top:2px">Elite: max 1.5u default 1u; Good: max 1u default 0.5u</div>',
        unsafe_allow_html=True,
    )


def _render_game_picks(conn, picks: list, show_all: bool, min_score: int,
                       matchup_filter: list | None = None) -> None:
    if not picks:
        st.info("No game market picks for this date. Run the pipeline first.")
        return

    _gcal    = _build_cal_index()
    _gseason = int((picks[0].get("pick_date") or str(datetime.now().year))[:4]) if picks else datetime.now().year
    for _gp in picks:
        if "_lights_html" not in _gp:
            _gp["_sim_result"] = _get_sim(_gp, _gseason)
            _attach_lights(_gp, _gcal)

    def _passes(p):
        if p.get("bet_placed") == 1:
            return True
        rec = normalize_recommendation(p["recommendation"])
        if not (show_all or is_bet_recommendation(p["recommendation"]) or rec == "WATCH"):
            return False
        if p["bovada_price"] is None or not (BET_PRICE_MIN <= p["bovada_price"] <= BET_PRICE_MAX):
            return False
        if (
            not _is_edge_only_game_market(p)
            and p["signal_score"] is not None
            and p["signal_score"] < min_score
        ):
            return False
        if matchup_filter:
            label = f"{p.get('away_team','?')} @ {p.get('home_team','?')}"
            if label not in matchup_filter:
                return False
        return True

    visible = [p for p in picks if _passes(p)]

    # Keep only best side per game — but always keep bet_placed picks even if lower edge
    _seen_game: dict = {}
    _deduped_game = []
    for p in visible:  # first pass: protect tracked bets
        if p.get("bet_placed") == 1:
            _seen_game[p["event_id"]] = True
            _deduped_game.append(p)
    for p in visible:  # second pass: fill best non-bet side per remaining event
        if p.get("bet_placed") != 1:
            k = p["event_id"]
            if k not in _seen_game:
                _seen_game[k] = True
                _deduped_game.append(p)
    visible = sorted(_deduped_game, key=_time_sort_key)

    if not visible:
        st.info("No game picks match current filters.")
        return

    for pick in visible:
        st.markdown(_game_card_html(pick), unsafe_allow_html=True)

        tier_lbl = _rec_label(pick["recommendation"])
        breakdown_raw = pick.get("signal_breakdown") or "[]"
        try:
            breakdown = json.loads(breakdown_raw)
        except Exception:
            breakdown = []

        if breakdown:
            with st.expander(f"Why {tier_lbl}?"):
                _why_content(pick, breakdown, None, None)

        if is_bet_recommendation(pick["recommendation"]):
            _game_track_strip(conn, pick)
        elif (pick.get("result") or "PENDING") == "PENDING":
            st.markdown(
                '<div style="padding:6px 0 2px;font-size:12px;color:#64748b">Watch only</div>',
                unsafe_allow_html=True,
            )


def _render_today(conn, today: str) -> None:
    picks = get_today_picks(conn, today)
    if not picks:
        st.info("No picks for today. Run the pipeline first.")
        return

    _REC_ORDER = {"A_BET": 0, "RECOMMENDED": 0, "B_BET": 1, "LEAN": 1, "WATCH": 2, "NO_BET": 2, "PASS": 3}
    picks = sorted(picks, key=lambda p: (
        _REC_ORDER.get(p["recommendation"], 2),
        -(p["sim_prob"] or 0),
        -(p["signal_score"] or 0),
        -p["edge"],
    ))

    game_picks_all = get_today_game_picks(conn, today)

    _cal    = _build_cal_index()
    _season = int(today[:4])
    _sim_recs = {"A_BET", "B_BET", "RECOMMENDED", "LEAN", "WATCH"}
    for _p in picks:
        if normalize_recommendation(_p.get("recommendation", "")) in _sim_recs:
            _p["_sim_result"] = _get_sim(_p, _season)
        _attach_lights(_p, _cal)
    for _p in game_picks_all:
        _p["_sim_result"] = _get_sim(_p, _season)
        _attach_lights(_p, _cal)

    # Filters — defined before the header so counts can reflect filtered state
    col_a, col_b = st.columns([2, 1.5])
    sim_only  = col_a.checkbox("Sim confirmed only", value=False)
    show_all  = col_b.checkbox("Show all evaluated lines", value=False)
    min_score = st.slider("Min signal score", 0, 90, 0, step=5, key="min_score")

    def _passes(p):
        if p.get("bet_placed") == 1:
            return True
        rec = normalize_recommendation(p["recommendation"])
        if not (show_all or is_bet_recommendation(p["recommendation"]) or rec == "WATCH"):
            return False
        if p["bovada_price"] is None or not (BET_PRICE_MIN <= p["bovada_price"] <= BET_PRICE_MAX):
            return False
        if p["signal_score"] is not None and p["signal_score"] < min_score:
            return False
        if sim_only and is_bet_recommendation(p["recommendation"]):
            if p["sim_prob"] is None or p["sim_prob"] < p["bovada_break_even_prob"]:
                return False
        return True

    # Day summary bar — counts based on current filter state
    prop_bet  = sum(1 for p in picks if _passes(p) and is_bet_recommendation(p["recommendation"]))
    game_bet  = sum(1 for p in game_picks_all if is_bet_recommendation(p["recommendation"]))
    live_pnl  = sum(
        (p.get("profit_units") or 0)
        for lst in (picks, game_picks_all)
        for p in lst
        if (p.get("result") or "PENDING") in ("WIN", "LOSS", "PUSH") and p.get("bet_placed") == 1
    )
    pnl_color = "#34d399" if live_pnl >= 0 else "#f87171"
    pnl_str   = f"{live_pnl:+.2f}u"

    dt_obj = datetime.strptime(today, "%Y-%m-%d")
    date_str = f"{dt_obj.strftime('%b')} {dt_obj.day}, {dt_obj.year}"

    st.markdown(f"""
<div class="day-header">
  <div>
    <div class="dh-lbl">Date</div>
    <div class="dh-val">{date_str}</div>
  </div>
  <div class="dh-stat">
    <div class="dh-lbl">Props</div>
    <div class="dh-val">{prop_bet} picks</div>
  </div>
  <div class="dh-stat">
    <div class="dh-lbl">Game Mkts</div>
    <div class="dh-val">{game_bet} picks</div>
  </div>
  <div class="dh-stat">
    <div class="dh-lbl">Live P&L</div>
    <div class="dh-val" style="color:{pnl_color}">{pnl_str}</div>
  </div>
</div>
""", unsafe_allow_html=True)

    with st.expander("Daily Summary", expanded=False):
        st.markdown(_daily_summary_html(picks, game_picks_all), unsafe_allow_html=True)

    visible = [p for p in picks if _passes(p)]

    # Keep only best side per (player, market, line) — prevents Over+Under both showing
    _seen: dict = {}
    _deduped = []
    for p in visible:  # already sorted best-first
        k = (p["player_name"], p["market_key"], p["point"])
        if k not in _seen:
            _seen[k] = True
            _deduped.append(p)
    visible = _deduped

    if not visible:
        st.info("No picks match current filters.")
        return

    visible = sorted(visible, key=_time_sort_key)
    st.markdown('<div class="section-label">Props by Start Time</div>', unsafe_allow_html=True)
    for p in visible:
        st.markdown(_prop_card_html(p), unsafe_allow_html=True)
        tier_lbl = _rec_label(p["recommendation"])
        breakdown_raw = p.get("signal_breakdown") or "[]"
        try:
            breakdown = json.loads(breakdown_raw)
        except Exception:
            breakdown = []
        with st.expander(f"Why {tier_lbl}?"):
            _why_content(p, breakdown, p.get("sim_prob"), p.get("bovada_break_even_prob"))
        if is_bet_recommendation(p["recommendation"]):
            _track_strip(conn, p)


def _render_active_bets(conn) -> None:
    bets = get_active_bets(conn)
    if not bets:
        st.info("No active pending bets. Place bets from Props or Game Markets.")
        return

    st.subheader(f"Active Bets  ({len(bets)} pending)")
    rows = []
    for b in bets:
        rows.append({
            "Date":          b["pick_date"],
            "Player/Game":   b["player_name"],
            "Market":        _mkt(b["market_key"]),
            "Line":          (f"{b['selection']} {b['point']:g}" if b["point"] is not None else b["selection"]),
            "Price":         (f"{b['bovada_price']:+d}" if b["bovada_price"] is not None else "—"),
            "Edge":          f"{(b['edge'] or 0):.1%}",
            "Units":         b["units_wagered"],
            "Tier":          _rec_label(b["recommendation"]),
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _render_history(conn) -> None:
    from datetime import datetime as _dt

    tier_filter = st.selectbox(
        "Tier", ["Elite + Good", "Elite only", "Good only", "Watchlist"],
        key="hist_tier",
    )
    tiers = (
        ("A_BET", "B_BET", "RECOMMENDED", "LEAN") if tier_filter == "Elite + Good"
        else ("A_BET", "RECOMMENDED") if tier_filter == "Elite only"
        else ("B_BET", "LEAN") if tier_filter == "Good only"
        else ("WATCH",)
    )
    placeholders = ",".join("?" * len(tiers))

    rows_props = conn.execute(f"""
        SELECT pick_date, recommendation, player_name AS label, market_key,
               selection, point, result, profit_units, edge
        FROM daily_picks
        WHERE recommendation IN ({placeholders}) AND result NOT IN ('PENDING','VOID')
        ORDER BY pick_date DESC, edge DESC
    """, tiers).fetchall()

    rows_games = conn.execute(f"""
        SELECT pick_date, recommendation,
               away_team || ' @ ' || home_team AS label, market_key,
               selection, point, result, profit_units, edge
        FROM daily_game_picks
        WHERE recommendation IN ({placeholders}) AND result NOT IN ('PENDING','VOID')
        ORDER BY pick_date DESC, edge DESC
    """, tiers).fetchall()

    all_rows = sorted(
        [dict(r) for r in rows_props] + [dict(r) for r in rows_games],
        key=lambda r: (r["pick_date"], -(r["edge"] or 0)),
        reverse=True,
    )

    if not all_rows:
        st.info("No graded picks at this tier yet.")
        return

    # Overall summary
    wins   = sum(1 for r in all_rows if r["result"] == "WIN")
    losses = sum(1 for r in all_rows if r["result"] == "LOSS")
    pushes = sum(1 for r in all_rows if r["result"] == "PUSH")
    graded = wins + losses
    net    = sum(r["profit_units"] or 0 for r in all_rows)
    winpct = wins / graded * 100 if graded else 0.0
    roi    = net / graded * 100 if graded else 0.0

    c1, c2, c3, c4, c5 = st.columns(5)
    _render_stat(c1, f"{wins+losses+pushes}", "Total Picks")
    _render_stat(c2, f"{wins}-{losses}-{pushes}", "W – L – P")
    _render_stat(c3, f"{winpct:.1f}%", "Win Rate", "#34d399" if winpct >= 52 else "#f87171")
    _render_stat(c4, f"{net:+.2f}u", "Net Units", "#34d399" if net >= 0 else "#f87171")
    _render_stat(c5, f"{roi:+.1f}%", "ROI/Pick", "#34d399" if roi >= 0 else "#f87171")

    st.markdown("---")

    # Group by date
    grouped = {}
    for r in all_rows:
        grouped.setdefault(r["pick_date"], []).append(r)

    for date in sorted(grouped.keys(), reverse=True):
        day_rows = grouped[date]
        dw = sum(1 for r in day_rows if r["result"] == "WIN")
        dl = sum(1 for r in day_rows if r["result"] == "LOSS")
        dp = sum(1 for r in day_rows if r["result"] == "PUSH")
        dnet = sum(r["profit_units"] or 0 for r in day_rows)
        dg = dw + dl
        dwpct = dw / dg * 100 if dg else 0.0

        label = _dt.strptime(date, "%Y-%m-%d").strftime("%a %b %#d")
        with st.expander(f"{label}   {dw}-{dl}-{dp}   {dnet:+.2f}u   ({dwpct:.0f}% win)", expanded=False):
            table = []
            for r in day_rows:
                res_icon = {"WIN": "✅", "LOSS": "❌", "PUSH": "➖"}.get(r["result"], "?")
                mkt = MARKET_LABELS.get(r["market_key"], r["market_key"])
                table.append({
                    "Tier": _rec_label(r["recommendation"]),
                    "Pick": r["label"],
                    "Market": mkt,
                    "Side": f"{r['selection']} {r['point']}",
                    "Edge": f"{r['edge']*100:.1f}%" if r["edge"] else "--",
                    "Result": res_icon,
                    "Units": f"{r['profit_units']:+.2f}" if r["profit_units"] is not None else "--",
                })
            st.dataframe(pd.DataFrame(table), use_container_width=True, hide_index=True)


def _render_learning(conn) -> None:
    summary = conn.execute("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN result='WIN'  THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) AS losses,
            SUM(CASE WHEN result='PUSH' THEN 1 ELSE 0 END) AS pushes,
            ROUND(SUM(CASE WHEN result NOT IN ('PENDING')
                THEN COALESCE(profit_units,0) ELSE 0 END)::numeric, 2) AS net_units
        FROM (
            SELECT result, profit_units FROM daily_picks
            WHERE bet_placed=1 AND recommendation IN ('A_BET','B_BET','LEAN','RECOMMENDED')
            UNION ALL
            SELECT result, profit_units FROM daily_game_picks
            WHERE bet_placed=1 AND recommendation IN ('A_BET','B_BET','LEAN','RECOMMENDED')
        )
    """).fetchone()

    if not summary or summary["total"] == 0:
        st.info("No bet history yet. Mark your first bets in Props or Game Markets — results auto-grade each morning.")
        return

    graded  = (summary["wins"] or 0) + (summary["losses"] or 0)
    win_pct = (summary["wins"] or 0) / graded * 100 if graded else 0.0
    net     = summary["net_units"] or 0.0
    roi     = net / graded * 100 if graded else 0.0

    c1, c2, c3, c4, c5 = st.columns(5)
    _render_stat(c1, str(summary["total"]), "Total Bets")
    _render_stat(c2, f"{summary['wins'] or 0}-{summary['losses'] or 0}-{summary['pushes'] or 0}", "W – L – P")
    _render_stat(c3, f"{win_pct:.1f}%",  "Win Rate",  "#34d399" if win_pct >= 52 else "#f87171")
    _render_stat(c4, f"{net:+.2f}",      "Net Units", "#34d399" if net >= 0 else "#f87171")
    _render_stat(c5, f"{roi:+.1f}%",     "ROI",       "#34d399" if roi >= 0 else "#f87171")

    st.markdown("---")
    left, right = st.columns(2)

    with left:
        st.subheader("By Market")
        mkt_rows = get_roi_by_market(conn)
        if mkt_rows:
            df = pd.DataFrame([dict(r) for r in mkt_rows])
            df["Market"]    = df["market_key"].map(MARKET_LABELS).fillna(df["market_key"])
            df["W-L-P"]     = df.apply(lambda r: f"{r['wins']}-{r['losses']}-{r['pushes']}", axis=1)
            df["Win%"]      = df["win_pct"].map(lambda v: f"{v:.1f}%" if v is not None else "--")
            df["Net Units"] = df["net_units"].map(lambda v: f"{v:+.2f}" if v is not None else "--")
            st.dataframe(
                df[["Market", "bets", "W-L-P", "Win%", "Net Units"]].rename(columns={"bets": "Bets"}),
                use_container_width=True, hide_index=True,
            )
        else:
            st.info("No graded bets yet.")

    with right:
        st.subheader("By Tier")
        tier_rows = get_roi_by_tier(conn)
        if tier_rows:
            df = pd.DataFrame([dict(r) for r in tier_rows])
            df["W-L-P"]     = df.apply(lambda r: f"{r['wins']}-{r['losses']}-{r['pushes']}", axis=1)
            df["Win%"]      = df["win_pct"].map(lambda v: f"{v:.1f}%" if v is not None else "--")
            df["Net Units"] = df["net_units"].map(lambda v: f"{v:+.2f}" if v is not None else "--")
            df["Tier"]      = df["recommendation"].map(_rec_label)
            st.dataframe(
                df[["Tier", "bets", "W-L-P", "Win%", "Net Units"]].rename(columns={"bets": "Bets"}),
                use_container_width=True, hide_index=True,
            )
        else:
            st.info("No graded bets yet.")

    pnl = get_cumulative_pnl(conn)
    if len(pnl) >= 2:
        st.markdown("---")
        st.subheader("Cumulative P&L (units)")
        raw_dates = [r["pick_date"] for r in pnl]
        cum       = [r["cumulative_units"] for r in pnl]
        labels    = [
            f"{datetime.strptime(d, '%Y-%m-%d').strftime('%b')} {datetime.strptime(d, '%Y-%m-%d').day}"
            for d in raw_dates
        ]

        pos = [v if v >= 0 else 0 for v in cum]
        neg = [v if v <= 0 else 0 for v in cum]

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=labels, y=pos, mode="none",
            fill="tozeroy", fillcolor="rgba(52,211,153,0.15)",
            showlegend=False, hoverinfo="skip",
        ))
        fig.add_trace(go.Scatter(
            x=labels, y=neg, mode="none",
            fill="tozeroy", fillcolor="rgba(248,113,113,0.15)",
            showlegend=False, hoverinfo="skip",
        ))
        fig.add_trace(go.Scatter(
            x=labels, y=cum, mode="lines+markers",
            line=dict(color="#64748b", width=2),
            marker=dict(
                size=6,
                color=["#34d399" if v >= 0 else "#f87171" for v in cum],
                line=dict(width=0),
            ),
            hovertemplate="%{x}: %{y:+.2f}u<extra></extra>",
            showlegend=False,
        ))
        fig.add_hline(y=0, line_dash="dash", line_color="#2a3044", line_width=1)
        fig.update_layout(
            paper_bgcolor="#13151a",
            plot_bgcolor="#1a1d27",
            font_color="#64748b",
            margin=dict(l=0, r=0, t=20, b=0),
            xaxis=dict(gridcolor="#252a38", showline=False, tickfont=dict(size=12)),
            yaxis=dict(gridcolor="#252a38", showline=False, zeroline=False),
            hovermode="x unified",
        )
        st.plotly_chart(fig, use_container_width=True)

    from market_learn import load_calibration
    cal = load_calibration()
    if cal:
        st.markdown("---")
        st.subheader("Market Calibration (from backtest)")
        st.caption(
            "Observed win rate vs break-even. BET = profitable, SKIP = below break-even. "
            "Min 20 graded picks per row."
        )
        rows = []
        for r in cal:
            rows.append({
                "Signal":  "BET" if r["profitable"] else "SKIP",
                "Market":  r["market_key"],
                "Side":    r["selection"],
                "Edge":    r["edge_bucket"],
                "W-L":     f"{r['wins']}-{r['losses']}",
                "Win%":    f"{r['win_rate']:.1%}",
                "Need":    f"{r['breakeven']:.1%}",
                "Diff":    f"{r['edge_vs_breakeven']:+.1%}",
                "Net":     f"{r['net_units']:+.2f}u",
            })
        df = pd.DataFrame(rows)

        def _hl(row):
            c = "background-color:#0f2518;color:#94a3b8" if row["Signal"] == "BET" else "background-color:#1f0e0e;color:#94a3b8"
            return [c] * len(row)

        st.dataframe(df.style.apply(_hl, axis=1), use_container_width=True, hide_index=True)


def main() -> None:
    st.set_page_config(page_title="MLB Prop Scout", page_icon="⚾", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)

    today = _pt_date()
    conn  = _db_conn(DB_PATH)
    init_db(conn)

    # Header
    dt_obj   = datetime.strptime(today, "%Y-%m-%d")
    date_str = f"{dt_obj.strftime('%b')} {dt_obj.day}, {dt_obj.year}"
    st.markdown(f"""
<div style="
    background: #1a1d27;
    border: 1px solid #252a38;
    border-radius: 10px;
    padding: 18px 24px;
    margin-bottom: 16px;
    display: flex;
    align-items: center;
    justify-content: space-between;
">
  <div>
    <div style="font-size:26px;font-weight:700;color:#f1f5f9;letter-spacing:1px;line-height:1.1">
      ⚾ &nbsp;MLB Prop Scout
    </div>
    <div style="font-size:11px;color:#475569;letter-spacing:2px;text-transform:uppercase;margin-top:4px">
      Bovada vs consensus &nbsp;·&nbsp; auto-graded &nbsp;·&nbsp; signal-scored
    </div>
  </div>
  <div style="text-align:right">
    <div style="font-size:20px;font-weight:600;color:#818cf8">{date_str}</div>
    <div style="font-size:10px;color:#475569;letter-spacing:2px;text-transform:uppercase;margin-top:2px">Game Day</div>
  </div>
</div>
""", unsafe_allow_html=True)

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Props", "Game Markets", "My Bets", "Pick History", "Results & Learning"])

    with tab1:
        from datetime import date as _date
        t_date = st.date_input(
            "Date", value=_date.fromisoformat(today),
            min_value=_date(2025, 1, 1), key="t_date",
            label_visibility="collapsed",
        )
        _render_today(conn, str(t_date))

    with tab2:
        from datetime import date as _date
        gd_col, ga_col, gb_col = st.columns([1.5, 2, 1.5])
        g_date      = gd_col.date_input("Game date", value=_date.fromisoformat(today),
                                        min_value=_date(2025, 1, 1), key="g_date")
        g_show_all  = ga_col.checkbox("Show all evaluated game lines", value=False, key="g_show_all")
        g_min_score = gb_col.slider("Min signal score", 0, 90, 0, step=5, key="g_min_score")

        g_picks_all = get_today_game_picks(conn, str(g_date))
        matchup_options = sorted({
            f"{p.get('away_team','?')} @ {p.get('home_team','?')}"
            for p in g_picks_all
        })
        g_matchup = st.multiselect(
            "Filter by game (leave blank for all)",
            options=matchup_options, default=[], key="g_matchup",
        )
        _render_game_picks(
            conn,
            g_picks_all,
            show_all=g_show_all,
            min_score=g_min_score,
            matchup_filter=g_matchup if g_matchup else None,
        )

    with tab3:
        _render_active_bets(conn)

    with tab4:
        _render_history(conn)

    with tab5:
        _render_learning(conn)

    conn.close()


if __name__ == "__main__":
    main()
