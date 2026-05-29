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


def _score_color(score: int | None) -> str:
    if score is None:
        return "#475569"
    if score >= 65:
        return "#818cf8"
    if score >= 50:
        return "#fbbf24"
    if score >= 45:
        return "#38bdf8"
    return "#64748b"


def _meter_svg(center_text: str, fill_pct: float, color: str, sub_label: str = "") -> str:
    """SVG circular meter. fill_pct 0-100."""
    size, r = 68, 26
    cx = cy = size / 2
    circ = 2 * 3.14159265 * r
    dash = max(0.0, min(fill_pct / 100.0, 1.0)) * circ
    gap  = circ - dash
    fs, sf = 14.0, 9.5
    if sub_label:
        cy_main = cx - sf * 0.75
        cy_sub  = cx + fs * 0.65
        sub_el = (
            f'<text x="{cx:.1f}" y="{cy_sub:.1f}" text-anchor="middle" '
            f'dominant-baseline="middle" font-size="{sf:.1f}" fill="#475569" '
            f'font-family="Inter,-apple-system,sans-serif">{sub_label}</text>'
        )
    else:
        cy_main = cx
        sub_el  = ""
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" '
        f'xmlns="http://www.w3.org/2000/svg">'
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r}" fill="none" stroke="#252a38" stroke-width="4.5"/>'
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r}" fill="none" stroke="{color}" stroke-width="4.5"'
        f' stroke-dasharray="{dash:.2f} {gap:.2f}" stroke-linecap="round"'
        f' transform="rotate(-90 {cx:.1f} {cy:.1f})"/>'
        f'<text x="{cx:.1f}" y="{cy_main:.1f}" text-anchor="middle" dominant-baseline="middle"'
        f' font-size="{fs:.1f}" font-weight="700" fill="{color}"'
        f' font-family="Inter,-apple-system,sans-serif">{center_text}</text>'
        f'{sub_el}</svg>'
    )


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
    background: #1a1d27;
    border: 1px solid #252a38;
    border-radius: 10px;
    padding: 16px;
    margin: 0 0 8px 0;
}
.pick.elite  { border-top: 2px solid #6366f1; }
.pick.good   { border-top: 2px solid #f59e0b; }
.pick.watch  { border-top: 2px solid #0ea5e9; }
.pick.pass   { border-top: 2px solid #475569; }
.pick.game  { background: #191c26; border-left: 3px solid #2a3044; }

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


def _prop_card_html(p: dict) -> str:
    t     = _tier(p["recommendation"])
    lbl   = _rec_label(p["recommendation"])
    score = p.get("signal_score")
    edge  = p.get("edge") or 0

    meter_color = _score_color(score)
    meter_fill  = min(float(score), 100.0) if score is not None else 0.0
    meter_text  = str(int(score)) if score is not None else "—"
    meter_html  = _meter_svg(meter_text, meter_fill, meter_color)

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
    tracked_style = "border-left:3px solid #34d399;background:#0d1812;" if p.get("bet_placed") == 1 else ""

    return f"""
<div class="pick {t}" style="{tracked_style}">
  <div style="display:flex;gap:12px;align-items:flex-start">
    <div style="flex:1;min-width:0">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px">
        <div>
          <div style="font-size:16px;font-weight:600;color:#f1f5f9">{p_name}</div>
          <div style="font-size:12px;color:#64748b;margin-top:2px">{team}</div>
        </div>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;justify-content:flex-end">
          <span class="badge {t}">{lbl}</span>{bet_badge}{res_html}
        </div>
      </div>
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;flex-wrap:wrap">
        <span style="background:#252a38;color:#94a3b8;font-size:12px;border-radius:4px;padding:3px 9px">{mkt}</span>
        <span style="font-size:15px;font-weight:600;color:#e2e8f0">{sel} {point_s}</span>
        <span style="background:#1e2330;color:#94a3b8;font-size:13px;border-radius:4px;padding:3px 9px;border:1px solid #2a3044">{price_s}</span>
      </div>
      <div style="display:flex;gap:20px;flex-wrap:wrap">
        <div>
          <div style="font-size:10px;color:#475569;text-transform:uppercase;letter-spacing:0.8px">Edge</div>
          <div style="font-size:13px;color:{edge_col};font-weight:500">{edge_s}</div>
        </div>
        <div>
          <div style="font-size:10px;color:#475569;text-transform:uppercase;letter-spacing:0.8px">EV</div>
          <div style="font-size:13px;color:#cbd5e1;font-weight:500">{ev_s}</div>
        </div>
        <div>
          <div style="font-size:10px;color:#475569;text-transform:uppercase;letter-spacing:0.8px">Books</div>
          <div style="font-size:13px;color:#cbd5e1;font-weight:500">{books_s}</div>
        </div>
      </div>
      {chips_html}
    </div>
    <div style="flex:0 0 auto;padding-top:2px">{meter_html}</div>
  </div>
</div>"""


def _game_card_html(p: dict) -> str:
    t         = _tier(p["recommendation"])
    lbl       = _rec_label(p["recommendation"])
    edge_only = _is_edge_only_game_market(p)
    edge      = p.get("edge") or 0
    score     = p.get("signal_score")

    if edge_only:
        meter_color = {"elite": "#818cf8", "good": "#fbbf24", "watch": "#38bdf8"}.get(t, "#64748b")
        meter_fill  = min(abs(edge) / 0.04, 1.0) * 100
        edge_pct    = abs(edge) * 100
        meter_text  = f"{edge_pct:.1f}%"
        meter_sub   = "EDGE"
        chips_html  = ""
    else:
        meter_color = _score_color(score)
        meter_fill  = min(float(score), 100.0) if score is not None else 0.0
        meter_text  = str(int(score)) if score is not None else "—"
        meter_sub   = ""
        try:
            breakdown = json.loads(p.get("signal_breakdown") or "[]")
        except Exception:
            breakdown = []
        chips_html = _breakdown_chips_html(breakdown)

    meter_html = _meter_svg(meter_text, meter_fill, meter_color, meter_sub)
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
  <div style="display:flex;gap:12px;align-items:flex-start">
    <div style="flex:1;min-width:0">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px">
        <div>
          <div style="font-size:16px;font-weight:600;color:#f1f5f9">{away} @ {home}</div>
          <div style="font-size:12px;color:#64748b;margin-top:2px">{market_s}</div>
        </div>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;justify-content:flex-end">
          <span class="badge {t}">{lbl}</span>{bet_badge}{res_html}
        </div>
      </div>
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;flex-wrap:wrap">
        <span style="background:#252a38;color:#94a3b8;font-size:12px;border-radius:4px;padding:3px 9px">{market_s}</span>
        <span style="font-size:15px;font-weight:600;color:#e2e8f0">{pick_s}</span>
        <span style="background:#1e2330;color:#94a3b8;font-size:13px;border-radius:4px;padding:3px 9px;border:1px solid #2a3044">{price_s}</span>
      </div>
      <div style="display:flex;gap:20px;flex-wrap:wrap">
        <div>
          <div style="font-size:10px;color:#475569;text-transform:uppercase;letter-spacing:0.8px">Edge</div>
          <div style="font-size:13px;color:{edge_col};font-weight:500">{edge_s}</div>
        </div>
        <div>
          <div style="font-size:10px;color:#475569;text-transform:uppercase;letter-spacing:0.8px">Books</div>
          <div style="font-size:13px;color:#cbd5e1;font-weight:500">{books_s}</div>
        </div>
      </div>
      {chips_html}{actual_html}
    </div>
    <div style="flex:0 0 auto;padding-top:2px">{meter_html}</div>
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
    visible = _deduped_game

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

    # Group A/B bets first, then watchlist candidates.
    elite_picks = [p for p in visible if normalize_recommendation(p["recommendation"]) == "A_BET"]
    good_picks  = [p for p in visible if normalize_recommendation(p["recommendation"]) == "B_BET"]
    watch_picks = [p for p in visible if normalize_recommendation(p["recommendation"]) == "WATCH"]

    if elite_picks:
        st.markdown('<div class="section-label">Elite</div>', unsafe_allow_html=True)
        for p in elite_picks:
            st.markdown(_prop_card_html(p), unsafe_allow_html=True)
            tier_lbl = _rec_label(p["recommendation"])
            breakdown_raw = p.get("signal_breakdown") or "[]"
            try:
                breakdown = json.loads(breakdown_raw)
            except Exception:
                breakdown = []
            with st.expander(f"Why {tier_lbl}?"):
                _why_content(p, breakdown, p.get("sim_prob"), p.get("bovada_break_even_prob"))
            _track_strip(conn, p)

    if good_picks:
        st.markdown('<div class="section-label">Good</div>', unsafe_allow_html=True)
        for p in good_picks:
            st.markdown(_prop_card_html(p), unsafe_allow_html=True)
            tier_lbl = _rec_label(p["recommendation"])
            breakdown_raw = p.get("signal_breakdown") or "[]"
            try:
                breakdown = json.loads(breakdown_raw)
            except Exception:
                breakdown = []
            with st.expander(f"Why {tier_lbl}?"):
                _why_content(p, breakdown, p.get("sim_prob"), p.get("bovada_break_even_prob"))
            _track_strip(conn, p)

    if watch_picks:
        st.markdown('<div class="section-label">Watchlist</div>', unsafe_allow_html=True)
        for p in watch_picks:
            st.markdown(_prop_card_html(p), unsafe_allow_html=True)
            tier_lbl = _rec_label(p["recommendation"])
            breakdown_raw = p.get("signal_breakdown") or "[]"
            try:
                breakdown = json.loads(breakdown_raw)
            except Exception:
                breakdown = []
            with st.expander(f"Why {tier_lbl}?"):
                _why_content(p, breakdown, p.get("sim_prob"), p.get("bovada_break_even_prob"))


def _render_active_bets(conn) -> None:
    bets = get_active_bets(conn)
    if not bets:
        st.info("No active pending bets. Place bets from Today's Picks.")
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
        st.info("No bet history yet. Mark your first bets in Today's Picks — results auto-grade each morning.")
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

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Today's Picks", "Game Markets", "My Bets", "Pick History", "Results & Learning"])

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
