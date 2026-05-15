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
)
from config import DB_PATH

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
[data-testid="stAppViewContainer"],
[data-testid="stHeader"],
[data-testid="block-container"] { background: #0d1b2a !important; }
section[data-testid="stSidebar"] { background: #0a1628; }
.stTabs [data-baseweb="tab-list"] { background: #152233; border-radius: 8px; padding: 4px; }
.stTabs [data-baseweb="tab"] { color: #8fa8c8; border-radius: 6px; }
.stTabs [data-baseweb="tab"][aria-selected="true"] { background: #1e3a5f; color: #ffffff; }
h1,h2,h3,h4 { color: #ffffff !important; }
p, label, .stMarkdown { color: #c8d8e8 !important; }
hr { border-color: #1e3a5f; }
.stat-box {
    background: #152233; border-radius: 10px; padding: 14px 12px;
    text-align: center; margin: 4px 0;
}
.stat-value { font-size: 26px; font-weight: 700; color: #ffffff; line-height: 1.2; }
.stat-label { font-size: 11px; color: #8fa8c8; text-transform: uppercase; letter-spacing: 1px; }
.pick-card {
    background: #152233; border-radius: 10px; padding: 14px 18px;
    margin: 6px 0; border-left: 5px solid #3a5068;
}
.rec-card  { border-left-color: #27ae60; }
.lean-card { border-left-color: #f39c12; }
.player-name { font-size: 17px; font-weight: 700; color: #ffffff; }
.pick-meta   { font-size: 13px; color: #8fa8c8; }
.edge-rec  { font-size: 18px; font-weight: 700; color: #27ae60; }
.edge-lean { font-size: 18px; font-weight: 700; color: #f39c12; }
.edge-no   { font-size: 18px; font-weight: 700; color: #3a5068; }
.bet-placed { color: #27ae60; font-size: 13px; font-weight: 600; }
.bet-skipped { color: #8fa8c8; font-size: 13px; }
div[data-testid="stDataFrame"] { background: #152233 !important; }
</style>
"""


def _pt_date() -> str:
    pt = datetime.now(timezone.utc) - timedelta(hours=7)
    return pt.strftime("%Y-%m-%d")


def _mkt(key: str) -> str:
    return MARKET_LABELS.get(key, key)


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
        return "#3a5068"
    if score >= 65:
        return "#27ae60"
    if score >= 45:
        return "#f39c12"
    return "#8fa8c8"


def _render_stat(col, value: str, label: str, color: str = "#ffffff") -> None:
    col.markdown(
        f'<div class="stat-box">'
        f'<div class="stat-value" style="color:{color}">{value}</div>'
        f'<div class="stat-label">{label}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _render_today(conn, today: str) -> None:
    picks = get_today_picks(conn, today)
    if not picks:
        st.info("No picks for today. Run the pipeline first.")
        return

    _REC_ORDER = {"RECOMMENDED": 0, "LEAN": 1, "NO_BET": 2}
    picks = sorted(picks, key=lambda p: (
        _REC_ORDER.get(p["recommendation"], 2),
        -(p["signal_score"] or 0),
        -p["edge"],
    ))

    total    = len(picks)
    lean     = sum(1 for p in picks if p["recommendation"] == "LEAN")
    rec      = sum(1 for p in picks if p["recommendation"] == "RECOMMENDED")
    bet_cnt  = sum(1 for p in picks if p["bet_placed"] == 1)

    c1, c2, c3, c4 = st.columns(4)
    _render_stat(c1, str(total),   "Lines Evaluated")
    _render_stat(c2, str(lean),    "Lean Picks",        "#f39c12")
    _render_stat(c3, str(rec),     "Recommended",       "#27ae60")
    _render_stat(c4, str(bet_cnt), "Bets Placed Today", "#3498db")

    st.markdown("---")
    col_a, col_b = st.columns([2, 1])
    show_all = col_a.checkbox("Show all evaluated lines (not just LEAN+)", value=False)
    min_score = col_b.slider("Min signal score", 0, 90, 0, step=5, key="min_score",
                             label_visibility="collapsed")

    visible = [
        p for p in picks
        if (show_all or p["recommendation"] in ("LEAN", "RECOMMENDED"))
        and (p["signal_score"] or 0) >= min_score
    ]

    if not visible:
        st.info("No LEAN or RECOMMENDED picks today. Toggle 'Show all' to browse all lines.")
        return

    for p in visible:
        edge_cls  = _edge_class(p["recommendation"])
        card_cls  = _card_class(p["recommendation"])
        mkt       = _mkt(p["market_key"])
        p_name    = _html.escape(str(p["player_name"]))
        mkt_esc   = _html.escape(str(mkt))
        sel_esc   = _html.escape(str(p["selection"]))
        rec_esc   = _html.escape(str(p["recommendation"]))
        score_val  = p["signal_score"] or 0
        score_disp = _score_bar(score_val)
        score_clr  = _score_color(score_val)
        breakdown_raw = p["signal_breakdown"] or "[]"
        try:
            breakdown = json.loads(breakdown_raw)
        except Exception:
            breakdown = []

        st.markdown(f"""
<div class="{card_cls}">
  <span class="player-name">{p_name}</span>
  <span class="pick-meta"> &nbsp;·&nbsp; {mkt_esc} &nbsp;{sel_esc} {p['point']:g} &nbsp;@ &nbsp;{p['bovada_price']:+d}</span>
  <span class="{edge_cls}" style="float:right">EDGE {p['edge']:.1%}</span><br>
  <span class="pick-meta">
    BOV fair {p['bovada_fair_prob']:.1%} &nbsp;·&nbsp;
    Consensus {p['consensus_fair_prob']:.1%} &nbsp;·&nbsp;
    EV {p['ev']:+.1%} &nbsp;·&nbsp;
    {p['consensus_book_count']} books &nbsp;·&nbsp;
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
            "Tier":     b["recommendation"],
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
                 "#27ae60" if win_pct >= 52 else "#e74c3c")
    _render_stat(c4, f"{net:+.2f}",
                 "Net Units",
                 "#27ae60" if net >= 0 else "#e74c3c")
    _render_stat(c5, f"{roi:+.1f}%",
                 "ROI",
                 "#27ae60" if roi >= 0 else "#e74c3c")

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
            st.dataframe(
                df[["recommendation", "bets", "W-L-P", "Win%", "Net Units"]].rename(
                    columns={"recommendation": "Tier", "bets": "Bets"}
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
        color = "#27ae60" if cum[-1] >= 0 else "#e74c3c"
        fill  = "rgba(39,174,96,0.12)" if cum[-1] >= 0 else "rgba(231,76,60,0.12)"

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=dates, y=cum,
            mode="lines+markers",
            line=dict(color=color, width=2),
            marker=dict(size=5),
            fill="tozeroy", fillcolor=fill,
        ))
        fig.add_hline(y=0, line_dash="dash", line_color="#3a5068", line_width=1)
        fig.update_layout(
            paper_bgcolor="#0d1b2a",
            plot_bgcolor="#152233",
            font_color="#c8d8e8",
            margin=dict(l=0, r=0, t=20, b=0),
            xaxis=dict(gridcolor="#1e3a5f", showline=False),
            yaxis=dict(gridcolor="#1e3a5f", showline=False),
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
    st.set_page_config(page_title="MLB V2", page_icon="⚾", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)

    today = _pt_date()
    conn  = _db_conn(DB_PATH)
    init_db(conn)

    st.markdown(
        f"# ⚾ MLB V2 &nbsp;&nbsp;"
        f"<span style='font-size:16px;color:#8fa8c8;font-weight:400'>{today}</span>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<span style='color:#8fa8c8;font-size:12px'>"
        "Bovada vs market consensus &nbsp;·&nbsp; "
        "edge = no-vig Bovada vs consensus fair probability &nbsp;·&nbsp; "
        "auto-grades each morning"
        "</span>",
        unsafe_allow_html=True,
    )

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
