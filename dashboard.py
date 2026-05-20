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
.pick.elite { border-top: 2px solid #6366f1; }
.pick.good  { border-top: 2px solid #f59e0b; }
.pick.game  { background: #191c26; border-left: 3px solid #2a3044; }

/* Badges */
.badge {
    font-size: 11px; font-weight: 700; border-radius: 20px;
    padding: 3px 12px; letter-spacing: 0.8px; text-transform: uppercase;
    display: inline-block; white-space: nowrap;
}
.badge.elite { background: #1e1f3a; color: #818cf8; border: 1px solid #3730a3; }
.badge.good  { background: #1f1a0a; color: #fbbf24; border: 1px solid #78350f; }

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
    return {"RECOMMENDED": "Elite", "LEAN": "Good", "NO_BET": "No Bet"}.get(rec, rec)


def _full_team(abbr: str) -> str:
    return TEAM_NAMES.get(str(abbr).upper(), abbr or "")


def _tier(rec: str) -> str:
    return "elite" if rec == "RECOMMENDED" else "good"


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
        m = re.search(rf"{key}=([^\s]+)", clean(note))
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

        if signal == "sp_quality":
            # note: "sp=First Last ERA=X.XX"
            m = re.search(r"sp=(.+?)\s+ERA=([\d.]+)", note)
            if m:
                parts.insert(0, f"facing {m.group(1)} (ERA {m.group(2)})")
            else:
                sp = re.sub(r"^sp=", "", re.sub(r"\s+ERA.*", "", note)).strip()
                if sp:
                    parts.insert(0, f"facing {sp}")

        elif signal in ("recent_tb", "recent_hits", "recent_hr", "recent_rbi"):
            v = val(note, "recent")
            if v and v != "None":
                lbl = {"recent_tb": "TB", "recent_hits": "hits",
                       "recent_hr": "HR", "recent_rbi": "RBI"}.get(signal, "")
                parts.append(f"averaging {v} {lbl} over recent games".strip())

        elif signal == "recent_k":
            v = val(note, "recent_k")
            if v and v != "None":
                parts.append(f"averaging {v} Ks per start recently")

        elif signal == "season_slg":
            v = val(note, "season_slg")
            if v and v != "None":
                try:
                    parts.append(f"season SLG {float(v):.3f}")
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
                parts.append(f"{v}% barrel rate")

        elif signal == "hard_hit_pct":
            v = val(note, "hard_hit_pct")
            if v and v != "None":
                parts.append(f"{v}% hard-contact rate")

        elif signal == "season_k9":
            v = val(note, "k9")
            if v and v != "None":
                parts.append(f"{v} K/9 this season")

        elif signal == "season_whip":
            v = val(note, "whip")
            if v and v != "None":
                parts.append(f"WHIP {v}")

        elif signal == "opp_team_avg":
            v = val(note, "opp_avg")
            if v and v != "None":
                parts.append(f"opponent batting avg {v}")

        elif signal in ("park_tb_factor", "park_hits_factor", "park_run_factor"):
            v = val(note, "park_factor") or val(note, "hits_factor") or val(note, "hr_factor")
            if v and v != "None":
                try:
                    pf = int(v)
                    if pf != 100:
                        lbl = "hitter-friendly" if pf > 100 else "pitcher-friendly"
                        parts.append(f"park factor {pf} ({lbl})")
                except ValueError:
                    pass

        elif signal == "recent_ip":
            v = val(note, "recent_ip")
            if v and v != "None":
                parts.append(f"averaging {v} IP/start recently")

        if len(parts) >= 4:
            break

    if not parts:
        return f"Model signals favor {dir_word} {mkt_word} — score reflects edge strength."

    pitcher = [p for p in parts if p.startswith("facing")]
    stats   = [p for p in parts if not p.startswith("facing")]

    if pitcher and stats:
        return f"{player_name} is {pitcher[0]}, {', '.join(stats[:3])}. Model favors {dir_word} {mkt_word}."
    elif pitcher:
        return f"{player_name} is {pitcher[0]}. Model favors {dir_word} {mkt_word}."
    else:
        return f"{player_name}: {', '.join(stats[:4])}. Model favors {dir_word} {mkt_word}."


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


def _prop_card_html(p: dict) -> str:
    t        = _tier(p["recommendation"])
    lbl      = _rec_label(p["recommendation"])
    score    = p["signal_score"] or 0
    bar_pct  = min(score, 100)
    bar_grad = ("linear-gradient(90deg,#4f46e5,#818cf8)"
                if t == "elite" else "linear-gradient(90deg,#b45309,#fbbf24)")
    edge_col = "#818cf8" if t == "elite" else "#fbbf24"

    p_name   = _html.escape(str(p["player_name"]))
    team     = _html.escape(_full_team(p.get("team_abbr") or ""))
    mkt      = _html.escape(_mkt(p["market_key"]))
    sel      = _html.escape(str(p["selection"]))
    point_s  = f"{p['point']:g}" if p["point"] is not None else "?"
    price_s  = f"{p['bovada_price']:+d}" if p["bovada_price"] is not None else "—"
    edge_s   = f"{(p['edge'] or 0):.1%}"
    ev_s     = f"{(p['ev'] or 0):+.1%}"
    books_s  = str(p["consensus_book_count"] or "?")
    res_html = _result_html(p)

    return f"""
<div class="pick {t}">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px">
    <div>
      <div style="font-size:16px;font-weight:600;color:#f1f5f9">{p_name}</div>
      <div style="font-size:12px;color:#64748b;margin-top:2px">{team}</div>
    </div>
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;justify-content:flex-end">
      <span class="badge {t}">{lbl}</span>
      {res_html}
    </div>
  </div>
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;flex-wrap:wrap">
    <span style="background:#252a38;color:#94a3b8;font-size:12px;border-radius:4px;padding:3px 9px">{mkt}</span>
    <span style="font-size:15px;font-weight:600;color:#e2e8f0">{sel} {point_s}</span>
    <span style="background:#1e2330;color:#94a3b8;font-size:13px;border-radius:4px;padding:3px 9px;border:1px solid #2a3044">{price_s}</span>
  </div>
  <div style="display:flex;align-items:center;gap:12px;margin-bottom:10px">
    <div style="flex:1;background:#252a38;border-radius:99px;height:4px">
      <div style="background:{bar_grad};width:{bar_pct}%;height:4px;border-radius:99px"></div>
    </div>
    <span style="font-size:12px;color:#64748b;min-width:52px;white-space:nowrap">Score {score}</span>
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
</div>"""


def _game_card_html(p: dict) -> str:
    t        = _tier(p["recommendation"])
    lbl      = _rec_label(p["recommendation"])
    score    = p["signal_score"] or 0
    bar_pct  = min(score, 100)
    bar_grad = ("linear-gradient(90deg,#4f46e5,#818cf8)"
                if t == "elite" else "linear-gradient(90deg,#b45309,#fbbf24)")
    edge_col = "#818cf8" if t == "elite" else "#fbbf24"

    away     = _html.escape(str(p.get("away_team") or "?"))
    home     = _html.escape(str(p.get("home_team") or "?"))
    sel      = _html.escape(str(p["selection"]))
    point_s  = f"{p['point']:g}" if p["point"] is not None else "?"
    price_s  = f"{p['bovada_price']:+d}" if p["bovada_price"] is not None else "—"
    edge_s   = f"{(p['edge'] or 0):.1%}"
    books_s  = str(p.get("consensus_book_count") or "?")
    res_html = _result_html(p)

    actual      = p.get("actual_total")
    actual_html = ""
    if actual is not None and (p.get("result") or "PENDING") != "PENDING":
        actual_html = (
            f'<div style="font-size:11px;color:#64748b;margin-top:4px">'
            f'Actual: <span style="color:#94a3b8">{actual:g} runs</span></div>'
        )

    return f"""
<div class="pick {t} game">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px">
    <div>
      <div style="font-size:16px;font-weight:600;color:#f1f5f9">{away} @ {home}</div>
      <div style="font-size:12px;color:#64748b;margin-top:2px">Game Total</div>
    </div>
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;justify-content:flex-end">
      <span class="badge {t}">{lbl}</span>
      {res_html}
    </div>
  </div>
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;flex-wrap:wrap">
    <span style="background:#252a38;color:#94a3b8;font-size:12px;border-radius:4px;padding:3px 9px">Game Total</span>
    <span style="font-size:15px;font-weight:600;color:#e2e8f0">{sel} {point_s}</span>
    <span style="background:#1e2330;color:#94a3b8;font-size:13px;border-radius:4px;padding:3px 9px;border:1px solid #2a3044">{price_s}</span>
  </div>
  <div style="display:flex;align-items:center;gap:12px;margin-bottom:10px">
    <div style="flex:1;background:#252a38;border-radius:99px;height:4px">
      <div style="background:{bar_grad};width:{bar_pct}%;height:4px;border-radius:99px"></div>
    </div>
    <span style="font-size:12px;color:#64748b;min-width:52px;white-space:nowrap">Score {score}</span>
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
  {actual_html}
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

    max_units = 3 if score > 75 else 2
    u_col, b_col, s_col, _ = st.columns([1.2, 1.2, 0.9, 3])

    units = u_col.number_input(
        "Units",
        min_value=1.0,
        max_value=float(max_units),
        value=1.0,
        step=1.0,
        key=f"u_{pick_id}",
        label_visibility="collapsed",
        help=f"Max {max_units}u — score must be >75 for 3u",
    )
    if b_col.button("Track Bet", key=f"b_{pick_id}"):
        mark_bet_placed(conn, pick_id, units)
        conn.close()
        st.rerun()
    if s_col.button("Skip", key=f"s_{pick_id}"):
        mark_bet_skipped(conn, pick_id)
        conn.close()
        st.rerun()

    if max_units < 3:
        st.markdown(
            '<div style="font-size:10px;color:#3a4058;margin-top:2px">3u requires score &gt; 75</div>',
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

    max_units = 3 if score > 75 else 2
    u_col, b_col, s_col, _ = st.columns([1.2, 1.2, 0.9, 3])
    units = u_col.number_input(
        "Units", min_value=1.0, max_value=float(max_units), value=1.0, step=1.0,
        key=f"gu_{pick_id}", label_visibility="collapsed",
        help=f"Max {max_units}u — score must be >75 for 3u",
    )
    if b_col.button("Track Bet", key=f"gb_{pick_id}"):
        mark_game_bet_placed(conn, pick_id, units)
        conn.close()
        st.rerun()
    if s_col.button("Skip", key=f"gs_{pick_id}"):
        mark_game_bet_skipped(conn, pick_id)
        conn.close()
        st.rerun()
    if max_units < 3:
        st.markdown(
            '<div style="font-size:10px;color:#3a4058;margin-top:2px">3u requires score &gt; 75</div>',
            unsafe_allow_html=True,
        )


def _render_game_picks(conn, picks: list, show_all: bool, min_score: int,
                       matchup_filter: list | None = None) -> None:
    if not picks:
        st.info("No game total picks for this date. Run the pipeline first.")
        return

    def _passes(p):
        if not (show_all or p["recommendation"] in ("LEAN", "RECOMMENDED")):
            return False
        if p["bovada_price"] is None or not (BET_PRICE_MIN <= p["bovada_price"] <= BET_PRICE_MAX):
            return False
        if p["signal_score"] is not None and p["signal_score"] < min_score:
            return False
        if matchup_filter:
            label = f"{p.get('away_team','?')} @ {p.get('home_team','?')}"
            if label not in matchup_filter:
                return False
        return True

    visible = [p for p in picks if _passes(p)]
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

        _game_track_strip(conn, pick)


def _render_today(conn, today: str) -> None:
    picks = get_today_picks(conn, today)
    if not picks:
        st.info("No picks for today. Run the pipeline first.")
        return

    _REC_ORDER = {"RECOMMENDED": 0, "LEAN": 1, "NO_BET": 2}
    picks = sorted(picks, key=lambda p: (
        _REC_ORDER.get(p["recommendation"], 2),
        -(p["sim_prob"] or 0),
        -(p["signal_score"] or 0),
        -p["edge"],
    ))

    game_picks_all = get_today_game_picks(conn, today)

    # Day summary bar
    prop_bet  = sum(1 for p in picks if p["recommendation"] in ("LEAN", "RECOMMENDED"))
    game_bet  = sum(1 for p in game_picks_all if p["recommendation"] in ("LEAN", "RECOMMENDED"))
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
    <div class="dh-lbl">Totals</div>
    <div class="dh-val">{game_bet} picks</div>
  </div>
  <div class="dh-stat">
    <div class="dh-lbl">Live P&L</div>
    <div class="dh-val" style="color:{pnl_color}">{pnl_str}</div>
  </div>
</div>
""", unsafe_allow_html=True)

    # Filters
    col_a, col_b = st.columns([2, 1.5])
    sim_only  = col_a.checkbox("Sim confirmed only", value=True)
    show_all  = col_b.checkbox("Show all evaluated lines", value=False)
    min_score = st.slider("Min signal score", 0, 90, 0, step=5, key="min_score")

    def _passes(p):
        if not (show_all or p["recommendation"] in ("LEAN", "RECOMMENDED")):
            return False
        if p["bovada_price"] is None or not (BET_PRICE_MIN <= p["bovada_price"] <= BET_PRICE_MAX):
            return False
        if p["signal_score"] is not None and p["signal_score"] < min_score:
            return False
        if sim_only and p["recommendation"] in ("LEAN", "RECOMMENDED"):
            if p["sim_prob"] is None or p["sim_prob"] < p["bovada_break_even_prob"]:
                return False
        return True

    visible = [p for p in picks if _passes(p)]
    if not visible:
        st.info("No picks match current filters.")
        return

    # Group Elite then Good
    elite_picks = [p for p in visible if p["recommendation"] == "RECOMMENDED"]
    good_picks  = [p for p in visible if p["recommendation"] == "LEAN"]

    if elite_picks:
        st.markdown('<div class="section-label">Elite Picks</div>', unsafe_allow_html=True)
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
        st.markdown('<div class="section-label">Good Picks</div>', unsafe_allow_html=True)
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


def _render_active_bets(conn) -> None:
    bets = get_active_bets(conn)
    if not bets:
        st.info("No active pending bets. Place bets from Today's Picks.")
        return

    st.subheader(f"Active Bets  ({len(bets)} pending)")
    rows = []
    for b in bets:
        rows.append({
            "Date":   b["pick_date"],
            "Player": b["player_name"],
            "Market": _mkt(b["market_key"]),
            "Line":   (f"{b['selection']} {b['point']:g}" if b["point"] is not None else b["selection"]),
            "Price":  (f"{b['bovada_price']:+d}" if b["bovada_price"] is not None else "—"),
            "Edge":   f"{(b['edge'] or 0):.1%}",
            "Units":  b["units_wagered"],
            "Tier":   _rec_label(b["recommendation"]),
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _render_learning(conn) -> None:
    summary = conn.execute("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN result='WIN'  THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) AS losses,
            SUM(CASE WHEN result='PUSH' THEN 1 ELSE 0 END) AS pushes,
            ROUND(SUM(CASE WHEN result NOT IN ('PENDING')
                THEN COALESCE(profit_units,0) ELSE 0 END), 2) AS net_units
        FROM (
            SELECT result, profit_units FROM daily_picks WHERE bet_placed=1
            UNION ALL
            SELECT result, profit_units FROM daily_game_picks WHERE bet_placed=1
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

    tab1, tab2, tab3, tab4 = st.tabs(["Today's Picks", "Game Markets", "My Bets", "Results & Learning"])

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
        _render_learning(conn)

    conn.close()


if __name__ == "__main__":
    main()
