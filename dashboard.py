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
    get_today_picks,
    get_active_bets,
    get_roi_by_market,
    get_roi_by_tier,
    get_cumulative_pnl,
    get_today_game_picks,
)
from config import DB_PATH, BET_PRICE_MIN, BET_PRICE_MAX

MARKET_LABELS = {
    "pitcher_strikeouts":   "K (P)",
    "pitcher_hits_allowed": "Hits (P)",
    "pitcher_earned_runs":  "ER (P)",
    "pitcher_walks":        "BB (P)",
    "pitcher_outs":         "Outs (P)",
    "batter_hits":          "Hits (B)",
    "batter_total_bases":   "TB (B)",
    "batter_home_runs":     "HR (B)",
    "batter_rbis":          "RBI (B)",
    "batter_runs_scored":   "R (B)",
    "batter_stolen_bases":  "SB (B)",
    "batter_walks":         "BB (B)",
}

CSS = """
<style>
/* ── Base: night-game ballpark ─────────────────────────────────────────── */
@import url('https://fonts.googleapis.com/css2?family=Oswald:wght@400;600;700&display=swap');

[data-testid="stAppViewContainer"],
[data-testid="stHeader"] {
    background: #0a0f0a !important;
    background-image: repeating-linear-gradient(
        90deg,
        transparent 0px, transparent 34px,
        rgba(255,255,255,0.025) 34px, rgba(255,255,255,0.025) 35px
    ) !important;
}
[data-testid="block-container"] { background: transparent !important; }

/* ── Sidebar: dugout ───────────────────────────────────────────────────── */
section[data-testid="stSidebar"] {
    background: #070d07;
    border-right: 2px solid #1a3a1a;
}

/* ── Tabs: scoreboard nav ──────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {
    background: #0f1f0f; border-radius: 6px; padding: 4px;
    border: 1px solid #1e3e1e;
}
.stTabs [data-baseweb="tab"] {
    color: #5a7a5a; border-radius: 4px;
    font-family: 'Oswald', sans-serif; letter-spacing: 1px; text-transform: uppercase;
}
.stTabs [data-baseweb="tab"][aria-selected="true"] {
    background: #1a3a1a; color: #c8e8c8;
}

/* ── Typography ────────────────────────────────────────────────────────── */
h1,h2,h3,h4 { color: #e8f0e8 !important; font-family: 'Oswald', sans-serif !important; letter-spacing: 1px !important; }
p, label, .stMarkdown { color: #8aa88a !important; }
hr { border-color: #1a3a1a; }

/* ── Stat boxes: scoreboard panels ────────────────────────────────────── */
.stat-box {
    background: #0f1f0f;
    border: 1px solid #1e3e1e;
    border-radius: 6px;
    padding: 14px 12px;
    text-align: center;
    margin: 4px 0;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.04);
}
.stat-value {
    font-size: 28px; font-weight: 700; color: #e8f0e8;
    line-height: 1.2; font-family: 'Oswald', sans-serif;
}
.stat-label {
    font-size: 10px; color: #5a7a5a;
    text-transform: uppercase; letter-spacing: 2px; margin-top: 2px;
}

/* ── Pick cards: lineup card feel ─────────────────────────────────────── */
.pick-card {
    background: #0d1a0d;
    border-radius: 6px;
    padding: 14px 18px;
    margin: 8px 0;
    border-left: 5px solid #1e3a1e;
    border-bottom: 1px solid #152515;
    box-shadow: 0 2px 8px rgba(0,0,0,0.5);
}
.rec-card  { border-left-color: #c41230; box-shadow: 0 2px 12px rgba(196,18,48,0.2); }
.lean-card { border-left-color: #e8a020; box-shadow: 0 2px 12px rgba(232,160,32,0.15); }

.player-name {
    font-size: 17px; font-weight: 700; color: #e8f0e8;
    font-family: 'Oswald', sans-serif; letter-spacing: 0.5px;
}
.pick-meta { font-size: 13px; color: #5a7a5a; }

.edge-rec  { font-size: 16px; font-weight: 700; color: #c41230; font-family: 'Oswald', sans-serif; }
.edge-lean { font-size: 16px; font-weight: 700; color: #e8a020; font-family: 'Oswald', sans-serif; }
.edge-no   { font-size: 16px; font-weight: 700; color: #2a4a2a; font-family: 'Oswald', sans-serif; }

.bet-placed  { color: #3a9a50; font-size: 13px; font-weight: 600; }
.bet-skipped { color: #5a7a5a; font-size: 13px; }

div[data-testid="stDataFrame"] { background: #0d1a0d !important; }

/* ── Buttons ───────────────────────────────────────────────────────────── */
div.stButton > button {
    background: #1a3a1a; color: #c8e8c8;
    border: 1px solid #2a5a2a; border-radius: 4px;
    font-family: 'Oswald', sans-serif; letter-spacing: 1px;
}
div.stButton > button:hover { background: #243a24; border-color: #3a7a3a; }
</style>
"""


def _pt_date() -> str:
    pt = datetime.now(timezone.utc) - timedelta(hours=7)
    return pt.strftime("%Y-%m-%d")


def _mkt(key: str) -> str:
    return MARKET_LABELS.get(key, key)


def _rec_label(rec: str) -> str:
    return {"RECOMMENDED": "ELITE", "LEAN": "GOOD", "NO_BET": "NO BET"}.get(rec, rec)


def _edge_class(rec: str) -> str:
    return {"RECOMMENDED": "edge-rec", "LEAN": "edge-lean"}.get(rec, "edge-no")


def _card_class(rec: str) -> str:
    return {"RECOMMENDED": "rec-card pick-card", "LEAN": "lean-card pick-card"}.get(rec, "pick-card")


def _score_bar(score) -> str:
    if score is None:
        return ""
    filled = int((score or 0) / 10)
    bar = "█" * filled + "░" * (10 - filled)
    return f"{score:>3}/100 [{bar}]"


def _score_color(score) -> str:
    if score is None or score == 0:
        return "#2a4a2a"
    if score >= 65:
        return "#3a9a50"
    if score >= 45:
        return "#e8a020"
    return "#5a7a5a"


def _render_stat(col, value: str, label: str, color: str = "#ffffff") -> None:
    col.markdown(
        f'<div class="stat-box">'
        f'<div class="stat-value" style="color:{color}">{value}</div>'
        f'<div class="stat-label">{label}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _sim_badge(sim_prob, bev) -> str:
    if sim_prob is None:
        return '<span style="color:#3a5068;font-size:12px">SIM —</span>'
    pct = round(sim_prob * 100)
    bev_pct = round(bev * 100)
    color = "#3a9a50" if sim_prob >= bev else "#c41230"
    return (
        f'<span style="color:{color};font-weight:700;font-size:13px">'
        f'SIM {pct}%</span>'
        f'<span style="color:#5a7a5a;font-size:12px"> vs {bev_pct}% BEV</span>'
    )


def _render_game_picks(conn, today: str, show_all: bool, min_score: int) -> None:
    picks = get_today_game_picks(conn, today)
    if not picks:
        return

    def _passes_game(p):
        if not (show_all or p["recommendation"] in ("LEAN", "RECOMMENDED")):
            return False
        if not (BET_PRICE_MIN <= p["bovada_price"] <= BET_PRICE_MAX):
            return False
        if p["signal_score"] is not None and p["signal_score"] < min_score:
            return False
        return True

    visible = [p for p in picks if _passes_game(p)]
    if not visible:
        return

    st.markdown("---")
    st.subheader("Game Totals")

    for pick in visible:
        card_cls  = _card_class(pick["recommendation"])
        edge_cls  = _edge_class(pick["recommendation"])
        rec_label = _html.escape(_rec_label(pick["recommendation"]))
        away      = _html.escape(str(pick["away_team"]))
        home      = _html.escape(str(pick["home_team"]))
        sel_esc   = _html.escape(str(pick["selection"]))
        score_disp = _score_bar(pick["signal_score"])
        score_clr  = _score_color(pick["signal_score"])

        breakdown_raw = pick["signal_breakdown"] or "[]"
        try:
            breakdown = json.loads(breakdown_raw)
        except Exception:
            breakdown = []

        st.markdown(f"""
<div class="{card_cls}">
  <span class="player-name">{away} @ {home}</span>
  <span class="pick-meta"> &nbsp;·&nbsp; Total {sel_esc} {pick['point']:g} &nbsp;@ &nbsp;{pick['bovada_price']:+d}</span>
  <span class="{edge_cls}" style="float:right">EDGE {pick['edge']:.1%}</span><br>
  <span class="pick-meta">
    <b>{rec_label}</b> &nbsp;·&nbsp;
    Score: {pick['signal_score'] or 0} &nbsp;·&nbsp;
    {pick['consensus_book_count']} books
  </span>
  <span style="float:right;color:{score_clr};font-family:monospace;font-size:13px">{score_disp}</span>
</div>
""", unsafe_allow_html=True)

        if breakdown:
            with st.expander("Signal breakdown"):
                breakdown_text = "\n".join(
                    f"  {b['signal']:<22} {b['pts']:>3}/{b['max']:<3} — {b['note']}"
                    for b in breakdown
                )
                st.code(breakdown_text)

        st.markdown("")


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

    total    = len(picks)
    lean     = sum(1 for p in picks if p["recommendation"] == "LEAN")
    rec      = sum(1 for p in picks if p["recommendation"] == "RECOMMENDED")
    sim_conf = sum(1 for p in picks
                   if p["recommendation"] in ("LEAN", "RECOMMENDED")
                   and p["sim_prob"] is not None
                   and p["sim_prob"] >= p["bovada_break_even_prob"])
    bet_cnt  = sum(1 for p in picks if p["bet_placed"] == 1)

    game_picks_all = get_today_game_picks(conn, today)
    game_lean = sum(1 for p in game_picks_all if p["recommendation"] == "LEAN")
    game_rec  = sum(1 for p in game_picks_all if p["recommendation"] == "RECOMMENDED")

    c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
    _render_stat(c1, str(total),     "Lines Evaluated")
    _render_stat(c2, str(lean),      "Good",            "#f39c12")
    _render_stat(c3, str(rec),       "Elite",           "#27ae60")
    _render_stat(c4, str(sim_conf),  "Sim Confirmed",   "#3498db")
    _render_stat(c5, str(bet_cnt),   "Bets Placed",     "#9b59b6")
    _render_stat(c6, str(game_lean), "Games Good",      "#f39c12")
    _render_stat(c7, str(game_rec),  "Games Elite",     "#27ae60")

    st.markdown("---")
    col_a, col_b = st.columns([2, 1.5])
    sim_only = col_a.checkbox("Sim confirmed only (recommended)", value=True)
    show_all = col_b.checkbox("Show all evaluated lines", value=False)
    min_score = st.slider("Min signal score filter", 0, 90, 0, step=5, key="min_score")

    def _passes(p):
        if not (show_all or p["recommendation"] in ("LEAN", "RECOMMENDED")):
            return False
        if not (BET_PRICE_MIN <= p["bovada_price"] <= BET_PRICE_MAX):
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

    for p in visible:
        edge_cls  = _edge_class(p["recommendation"])
        card_cls  = _card_class(p["recommendation"])
        mkt       = _mkt(p["market_key"])
        p_name    = _html.escape(str(p["player_name"]))
        team      = _html.escape(str(p["team_abbr"] or ""))
        mkt_esc   = _html.escape(str(mkt))
        sel_esc   = _html.escape(str(p["selection"]))
        rec_esc   = _html.escape(_rec_label(p["recommendation"]))
        score_val  = p["signal_score"] or 0
        score_disp = _score_bar(score_val)
        score_clr  = _score_color(score_val)
        sim_html   = _sim_badge(p["sim_prob"], p["bovada_break_even_prob"])
        team_html  = (f'<span style="background:#0f2a0f;color:#5a9a5a;font-size:11px;'
                      f'border-radius:3px;padding:1px 7px;margin-left:6px;'
                      f'font-family:monospace;letter-spacing:1px;border:1px solid #1e4a1e">{team}</span>'
                      if team else "")
        breakdown_raw = p["signal_breakdown"] or "[]"
        try:
            breakdown = json.loads(breakdown_raw)
        except Exception:
            breakdown = []

        st.markdown(f"""
<div class="{card_cls}">
  <span class="player-name">{p_name}</span>{team_html}
  <span class="pick-meta"> &nbsp;·&nbsp; {mkt_esc} &nbsp;{sel_esc} {p['point']:g} &nbsp;@ &nbsp;{p['bovada_price']:+d}</span>
  <span class="{edge_cls}" style="float:right">EDGE {p['edge']:.1%}</span><br>
  <span class="pick-meta">
    {sim_html} &nbsp;·&nbsp;
    {p['consensus_book_count']} books &nbsp;·&nbsp;
    EV {p['ev']:+.1%} &nbsp;·&nbsp;
    <b>{rec_esc}</b>
  </span>
  <span style="float:right;color:{score_clr};font-family:monospace;font-size:13px">{score_disp}</span>
</div>
""", unsafe_allow_html=True)
        if breakdown:
            with st.expander("Signal breakdown"):
                breakdown_text = "\n".join(
                    f"  {b['signal']:<22} {b['pts']:>3}/{b['max']:<3} — {b['note']}"
                    for b in breakdown
                )
                st.code(breakdown_text)

        if p["bet_placed"] == 0:
            uc, bc, sc, _ = st.columns([1.4, 0.9, 0.9, 4])
            units = uc.number_input(
                "Units", min_value=0.5, max_value=20.0, value=1.0, step=0.5,
                key=f"u_{p['id']}", label_visibility="collapsed",
            )
            if bc.button("Bet", key=f"b_{p['id']}"):
                mark_bet_placed(conn, p["id"], units)
                conn.close()
                st.rerun()
            if sc.button("Skip", key=f"s_{p['id']}"):
                mark_bet_skipped(conn, p["id"])
                conn.close()
                st.rerun()
        elif p["bet_placed"] == 1:
            units_esc = _html.escape(str(p["units_wagered"]))
            st.markdown(f'<span class="bet-placed">BET PLACED &nbsp;·&nbsp; {units_esc} units</span>', unsafe_allow_html=True)
        else:
            st.markdown('<span class="bet-skipped">-- Skipped</span>', unsafe_allow_html=True)

        st.markdown("")

    # Game totals section
    _render_game_picks(conn, today, show_all, min_score)


def _render_active_bets(conn) -> None:
    bets = get_active_bets(conn)
    if not bets:
        st.info("No active pending bets. Place bets from Today's Picks.")
        return

    st.subheader(f"Active Bets  ({len(bets)} pending)")
    rows = []
    for b in bets:
        rows.append({
            "Date":     b["pick_date"],
            "Player":   b["player_name"],
            "Market":   _mkt(b["market_key"]),
            "Line":     f"{b['selection']} {b['point']:g}",
            "Price":    f"{b['bovada_price']:+d}",
            "Edge":     f"{b['edge']:.1%}",
            "Units":    b["units_wagered"],
            "Tier":     _rec_label(b["recommendation"]),
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
        FROM daily_picks WHERE bet_placed=1
    """).fetchone()

    if not summary or summary["total"] == 0:
        st.info("No bet history yet. Mark your first bets in Today's Picks -- results auto-grade each morning.")
        return

    graded  = (summary["wins"] or 0) + (summary["losses"] or 0)
    win_pct = (summary["wins"] or 0) / graded * 100 if graded else 0.0
    net     = summary["net_units"] or 0.0
    roi     = net / summary["total"] * 100

    c1, c2, c3, c4, c5 = st.columns(5)
    _render_stat(c1, str(summary["total"]),
                 "Total Bets")
    _render_stat(c2, f"{summary['wins'] or 0}-{summary['losses'] or 0}-{summary['pushes'] or 0}",
                 "W -- L -- P")
    _render_stat(c3, f"{win_pct:.1f}%",
                 "Win Rate",
                 "#3a9a50" if win_pct >= 52 else "#c41230")
    _render_stat(c4, f"{net:+.2f}",
                 "Net Units",
                 "#3a9a50" if net >= 0 else "#c41230")
    _render_stat(c5, f"{roi:+.1f}%",
                 "ROI",
                 "#3a9a50" if roi >= 0 else "#c41230")

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
                df[["Tier", "bets", "W-L-P", "Win%", "Net Units"]].rename(
                    columns={"bets": "Bets"}
                ),
                use_container_width=True, hide_index=True,
            )
        else:
            st.info("No graded bets yet.")

    pnl = get_cumulative_pnl(conn)
    if len(pnl) >= 2:
        st.markdown("---")
        st.subheader("Cumulative P&L (units)")
        dates = [r["pick_date"] for r in pnl]
        cum   = [r["cumulative_units"] for r in pnl]
        color = "#3a9a50" if cum[-1] >= 0 else "#c41230"
        fill  = "rgba(58,154,80,0.12)" if cum[-1] >= 0 else "rgba(196,18,48,0.12)"

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=dates, y=cum,
            mode="lines+markers",
            line=dict(color=color, width=2),
            marker=dict(size=5),
            fill="tozeroy", fillcolor=fill,
        ))
        fig.add_hline(y=0, line_dash="dash", line_color="#1e3e1e", line_width=1)
        fig.update_layout(
            paper_bgcolor="#0a0f0a",
            plot_bgcolor="#0d1a0d",
            font_color="#8aa88a",
            margin=dict(l=0, r=0, t=20, b=0),
            xaxis=dict(gridcolor="#1a3a1a", showline=False),
            yaxis=dict(gridcolor="#1a3a1a", showline=False),
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
            "Min 20 graded picks per row. Refresh: python backtest.py --report-only"
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
            c = "background-color: #1a3a1a" if row["Signal"] == "BET" else "background-color: #3a1a1a"
            return [c] * len(row)

        st.dataframe(df.style.apply(_hl, axis=1), use_container_width=True, hide_index=True)


def main() -> None:
    st.set_page_config(page_title="MLB Prop Scout", page_icon="⚾", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)

    today = _pt_date()
    conn  = _db_conn(DB_PATH)
    init_db(conn)

    st.markdown(f"""
<div style="
    background: linear-gradient(135deg, #0f1f0f 0%, #0a0f0a 100%);
    border: 1px solid #1e3e1e;
    border-radius: 8px;
    padding: 18px 24px;
    margin-bottom: 16px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    box-shadow: 0 4px 16px rgba(0,0,0,0.6);
">
  <div>
    <div style="font-family:'Oswald',sans-serif;font-size:32px;font-weight:700;
                color:#e8f0e8;letter-spacing:3px;line-height:1.1">
      ⚾ &nbsp;MLB PROP SCOUT
    </div>
    <div style="font-size:11px;color:#5a7a5a;letter-spacing:3px;
                text-transform:uppercase;margin-top:4px;font-family:monospace">
      Bovada vs consensus &nbsp;·&nbsp; auto-graded &nbsp;·&nbsp; signal-scored
    </div>
  </div>
  <div style="text-align:right">
    <div style="font-family:'Oswald',sans-serif;font-size:22px;
                color:#c41230;font-weight:700;letter-spacing:2px">{today}</div>
    <div style="font-size:10px;color:#5a7a5a;letter-spacing:2px;text-transform:uppercase">Game Day</div>
  </div>
</div>
""", unsafe_allow_html=True)

    tab1, tab2, tab3 = st.tabs(["Today's Picks", "My Bets", "Results & Learning"])

    with tab1:
        _render_today(conn, today)
    with tab2:
        _render_active_bets(conn)
    with tab3:
        _render_learning(conn)

    conn.close()


if __name__ == "__main__":
    main()
