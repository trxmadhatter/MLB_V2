"""
Send today's MLB V2 picks via email — full summary, no dashboard needed.
Includes: today's picks, yesterday's results, running record + ROI.
"""
import os
import json
import smtplib
import sys
from datetime import date, datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from db import get_conn
from edge import normalize_recommendation


def _fmt_odds(price: int) -> str:
    return f"+{price}" if price > 0 else str(price)


def _rec_color(rec: str) -> str:
    rec = normalize_recommendation(rec)
    return "#ff6b35" if rec == "A_BET" else "#00b894"


def _rec_label(rec: str) -> str:
    return {"A_BET": "ELITE", "B_BET": "GOOD", "WATCH": "WATCHLIST"}.get(
        normalize_recommendation(rec), rec
    )


def send_promotion_alert(promoted: list[dict], today: str) -> None:
    """Compact alert email when Watchlist picks upgrade to Elite or Good."""
    import html as _html
    email_from = os.getenv("EMAIL_FROM", "")
    email_pass = os.getenv("EMAIL_PASSWORD", "")
    email_to   = os.getenv("EMAIL_TO", email_from)
    if not email_from or not email_pass:
        print("  EMAIL_FROM / EMAIL_PASSWORD not set — skipping promotion alert")
        return

    today_label = date.fromisoformat(today).strftime("%B %d")
    n = len(promoted)
    subject = f"MLB Promotion Alert — {n} pick{'s' if n > 1 else ''} upgraded ({today_label})"

    plain_lines = [f"WATCHLIST UPGRADED — {today_label}", ""]
    for p in promoted:
        tier = "ELITE" if normalize_recommendation(p["recommendation"]) == "A_BET" else "GOOD"
        plain_lines.append(
            f"[{tier}] {p['player_name']} | {p['market_key']} | "
            f"{p['selection']} {p['point']} | {_fmt_odds(p['bovada_price'])} | "
            f"{p['edge']*100:+.1f}% edge"
        )

    cards = ""
    for p in promoted:
        rec  = normalize_recommendation(p["recommendation"])
        tier = "ELITE" if rec == "A_BET" else "GOOD"
        col  = "#818cf8" if rec == "A_BET" else "#fbbf24"
        bdr  = "#6366f1" if rec == "A_BET" else "#f59e0b"
        cards += (
            f'<div style="border-left:3px solid {bdr};padding:8px 14px;margin:8px 0;background:#161b22">'
            f'<span style="color:{col};font-weight:700">{tier}</span>&nbsp;&nbsp;'
            f'{_html.escape(str(p["player_name"]))} &mdash; '
            f'{_html.escape(str(p["market_key"]))} {_html.escape(str(p["selection"]))} {p["point"]}'
            f'&nbsp;&nbsp;<span style="color:#8b949e">{_fmt_odds(p["bovada_price"])} &nbsp; '
            f'{p["edge"]*100:+.1f}% edge</span></div>'
        )

    html_body = f"""<html><body style="font-family:monospace;background:#0d1117;color:#e6edf3;padding:20px">
<h2 style="color:#38bdf8">Watchlist Promotion &mdash; {today_label}</h2>
<p style="color:#8b949e">{n} pick{'s' if n > 1 else ''} upgraded from Watchlist to actionable</p>
{cards}
</body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = email_from
    msg["To"]      = email_to
    msg.attach(MIMEText("\n".join(plain_lines), "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(email_from, email_pass)
        server.sendmail(email_from, email_to, msg.as_string())
    print(f"  Promotion alert sent to {email_to} ({n} picks)")


def _result_color(result: str) -> tuple[str, str]:
    if result == "WIN":   return "#00b894", "WIN"
    if result == "LOSS":  return "#e74c3c", "LOSS"
    if result == "PUSH":  return "#888",    "PUSH"
    return "#555", result or "PENDING"


def send_degradation_alert(degraded: list[dict], today: str) -> None:
    """Alert when a bet game pick's edge drops below its tier minimum — consider cashing out."""
    import html as _html
    email_from = os.getenv("EMAIL_FROM", "")
    email_pass = os.getenv("EMAIL_PASSWORD", "")
    email_to   = os.getenv("EMAIL_TO", email_from)
    if not email_from or not email_pass:
        print("  EMAIL_FROM / EMAIL_PASSWORD not set — skipping degradation alert")
        return

    today_label = date.fromisoformat(today).strftime("%B %d")
    n = len(degraded)
    subject = f"MLB Line Alert — {n} bet{'s' if n > 1 else ''} degraded ({today_label})"

    plain_lines = [f"LINE DEGRADATION — {today_label}", "Edge has moved — review position on Bovada", ""]
    for p in degraded:
        plain_lines.append(
            f"{p.get('away_team','?')} @ {p.get('home_team','?')} | "
            f"{p['selection']} {p['point']} | {_fmt_odds(p['bovada_price'])} | "
            f"edge now {p['edge']*100:+.1f}%"
        )

    cards = ""
    for p in degraded:
        edge_pct = p["edge"] * 100
        col = "#e74c3c" if edge_pct < 0 else "#f59e0b"
        cards += (
            f'<div style="border-left:3px solid {col};padding:8px 14px;margin:8px 0;background:#161b22">'
            f'<span style="color:#e6edf3;font-weight:700">'
            f'{_html.escape(str(p.get("away_team","?")))} @ {_html.escape(str(p.get("home_team","?")))}</span>'
            f'&nbsp;&nbsp;{_html.escape(str(p["selection"]))} {p["point"]}'
            f'&nbsp;&nbsp;<span style="color:#8b949e">{_fmt_odds(p["bovada_price"])}</span>'
            f'&nbsp;&nbsp;<span style="color:{col};font-weight:700">edge {edge_pct:+.1f}%</span>'
            f'</div>'
        )

    html_body = f"""<html><body style="font-family:monospace;background:#0d1117;color:#e6edf3;padding:20px">
<h2 style="color:#e74c3c">Line Degradation Alert &mdash; {today_label}</h2>
<p style="color:#8b949e">{n} bet{'s' if n > 1 else ''} no longer meeting edge threshold &mdash; review position on Bovada</p>
{cards}
</body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = email_from
    msg["To"]      = email_to
    msg.attach(MIMEText("\n".join(plain_lines), "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(email_from, email_pass)
        server.sendmail(email_from, email_to, msg.as_string())
    print(f"  Degradation alert sent to {email_to} ({n} picks)")


def _profit(price: int) -> float:
    return -100 / price if price < 0 else price / 100


def get_today_game_picks(conn, today: str) -> list[dict]:
    return [dict(r) for r in conn.execute("""
        SELECT home_team, away_team, market_key, selection, point,
               bovada_price, edge, recommendation, signal_score
        FROM daily_game_picks
        WHERE pick_date = ?
          AND recommendation IN ('A_BET','B_BET','RECOMMENDED','LEAN')
          AND emailed = 0
        ORDER BY recommendation DESC, signal_score DESC
    """, (today,)).fetchall()]


def get_yesterday_game_results(conn, yesterday: str) -> list[dict]:
    return [dict(r) for r in conn.execute("""
        SELECT home_team, away_team, selection, point,
               bovada_price, edge, result, recommendation
        FROM daily_game_picks
        WHERE pick_date = ?
          AND recommendation IN ('A_BET','B_BET','RECOMMENDED','LEAN')
        ORDER BY result, edge DESC
    """, (yesterday,)).fetchall()]


def get_today_picks(conn, today: str) -> list[dict]:
    rows = [dict(r) for r in conn.execute("""
        SELECT event_id, player_name, market_key, selection, point,
               bovada_price, consensus_fair_prob, edge, recommendation,
               home_team, away_team
        FROM daily_picks
        WHERE pick_date = ?
          AND recommendation IN ('A_BET','B_BET','RECOMMENDED','LEAN')
          AND sim_prob IS NOT NULL
          AND sim_prob >= bovada_break_even_prob
          AND emailed = 0
        ORDER BY recommendation DESC, sim_prob DESC, edge DESC
    """, (today,)).fetchall()]
    if not rows:
        # sim_prob not yet populated — fall back to edge-only so email isn't empty
        rows = [dict(r) for r in conn.execute("""
            SELECT event_id, player_name, market_key, selection, point,
                   bovada_price, consensus_fair_prob, edge, recommendation,
                   home_team, away_team
            FROM daily_picks
            WHERE pick_date = ?
              AND recommendation IN ('A_BET','B_BET','RECOMMENDED','LEAN')
              AND emailed = 0
            ORDER BY recommendation DESC, edge DESC
        """, (today,)).fetchall()]
        if rows:
            print(f"  [email] WARNING: sim_prob not populated — falling back to {len(rows)} edge-only picks")
    return rows


def get_yesterday_results(conn, yesterday: str) -> list[dict]:
    return [dict(r) for r in conn.execute("""
        SELECT player_name, market_key, selection, point,
               bovada_price, edge, result, recommendation
        FROM daily_picks
        WHERE pick_date = ?
          AND recommendation IN ('A_BET','B_BET','RECOMMENDED','LEAN')
        ORDER BY result, edge DESC
    """, (yesterday,)).fetchall()]


def get_running_record(conn) -> dict:
    row = conn.execute("""
        SELECT
            COUNT(*)                                                   AS total,
            SUM(CASE WHEN result='WIN'  THEN 1 ELSE 0 END)            AS wins,
            SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END)            AS losses,
            SUM(CASE WHEN result='PUSH' THEN 1 ELSE 0 END)            AS pushes
        FROM daily_picks
        WHERE recommendation IN ('A_BET','B_BET','RECOMMENDED','LEAN')
          AND result IN ('WIN','LOSS','PUSH')
    """).fetchone()
    if not row or row["total"] == 0:
        return {"wins": 0, "losses": 0, "pushes": 0, "win_pct": 0.0, "net": 0.0, "roi": 0.0}

    picks = conn.execute("""
        SELECT bovada_price, result FROM daily_picks
        WHERE recommendation IN ('A_BET','B_BET','RECOMMENDED','LEAN')
          AND result IN ('WIN','LOSS','PUSH')
    """).fetchall()

    net = sum(_profit(p["bovada_price"]) if p["result"] == "WIN" else
              (0 if p["result"] == "PUSH" else -1.0)
              for p in picks)
    wl  = row["wins"] + row["losses"]
    return {
        "wins":    row["wins"],
        "losses":  row["losses"],
        "pushes":  row["pushes"],
        "win_pct": row["wins"] / wl * 100 if wl else 0.0,
        "net":     net,
        "roi":     net / wl * 100 if wl else 0.0,
    }


def section(title: str, content: str) -> str:
    return f"""
    <div style="margin-bottom:32px;">
      <h2 style="font-size:14px;font-weight:700;color:#8fa8c8;text-transform:uppercase;
                 letter-spacing:1.5px;margin:0 0 12px;padding-bottom:8px;
                 border-bottom:1px solid #1e3a5f;">{title}</h2>
      {content}
    </div>"""


def picks_table(picks: list[dict]) -> str:
    if not picks:
        return "<p style='color:#555;font-size:14px;margin:0;'>No qualifying picks today.</p>"

    rows = ""
    for p in picks:
        color = _rec_color(p["recommendation"])
        matchup = f"{p.get('away_team','?')} @ {p.get('home_team','?')}"
        rows += f"""
        <tr>
          <td style="padding:11px 14px;border-bottom:1px solid #1a2a3a;">
            <div style="font-weight:700;color:#fff;font-size:14px;">{p['player_name']}</div>
            <div style="color:#556;font-size:11px;margin-top:2px;">{matchup}</div>
          </td>
          <td style="padding:11px 14px;border-bottom:1px solid #1a2a3a;color:#aaa;font-size:13px;">
            {p['market_key'].replace('_',' ').title()}
          </td>
          <td style="padding:11px 14px;border-bottom:1px solid #1a2a3a;color:#fff;font-size:14px;font-weight:600;">
            {p['selection']} {p['point']}
          </td>
          <td style="padding:11px 14px;border-bottom:1px solid #1a2a3a;color:#aaa;font-size:13px;">
            {_fmt_odds(p['bovada_price'])}
          </td>
          <td style="padding:11px 14px;border-bottom:1px solid #1a2a3a;font-weight:700;
                     color:{color};font-size:13px;">
            {p['edge']*100:+.1f}%
          </td>
          <td style="padding:11px 14px;border-bottom:1px solid #1a2a3a;">
            <span style="background:{color};color:#fff;padding:3px 9px;border-radius:4px;
                         font-size:11px;font-weight:700;">{_rec_label(p['recommendation'])}</span>
          </td>
        </tr>"""

    return f"""
    <table width="100%" cellpadding="0" cellspacing="0"
           style="border-collapse:collapse;background:#0f1e2e;border-radius:8px;overflow:hidden;">
      <thead>
        <tr style="background:#0a1628;">
          <th style="padding:9px 14px;text-align:left;color:#556;font-size:11px;text-transform:uppercase;">Player</th>
          <th style="padding:9px 14px;text-align:left;color:#556;font-size:11px;text-transform:uppercase;">Market</th>
          <th style="padding:9px 14px;text-align:left;color:#556;font-size:11px;text-transform:uppercase;">Pick</th>
          <th style="padding:9px 14px;text-align:left;color:#556;font-size:11px;text-transform:uppercase;">Odds</th>
          <th style="padding:9px 14px;text-align:left;color:#556;font-size:11px;text-transform:uppercase;">Edge</th>
          <th style="padding:9px 14px;text-align:left;color:#556;font-size:11px;text-transform:uppercase;">Rating</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>"""


def results_table(picks: list[dict]) -> str:
    if not picks:
        return "<p style='color:#555;font-size:14px;margin:0;'>No graded picks from yesterday.</p>"

    rows = ""
    for p in picks:
        color, label = _result_color(p["result"])
        rows += f"""
        <tr>
          <td style="padding:10px 14px;border-bottom:1px solid #1a2a3a;font-weight:600;color:#fff;font-size:14px;">
            {p['player_name']}
          </td>
          <td style="padding:10px 14px;border-bottom:1px solid #1a2a3a;color:#aaa;font-size:13px;">
            {p['market_key'].replace('_',' ').title()}
          </td>
          <td style="padding:10px 14px;border-bottom:1px solid #1a2a3a;color:#fff;font-size:13px;">
            {p['selection']} {p['point']}
          </td>
          <td style="padding:10px 14px;border-bottom:1px solid #1a2a3a;color:#aaa;font-size:13px;">
            {_fmt_odds(p['bovada_price'])}
          </td>
          <td style="padding:10px 14px;border-bottom:1px solid #1a2a3a;">
            <span style="background:{color};color:#fff;padding:3px 10px;border-radius:4px;
                         font-size:12px;font-weight:700;">{label}</span>
          </td>
        </tr>"""

    return f"""
    <table width="100%" cellpadding="0" cellspacing="0"
           style="border-collapse:collapse;background:#0f1e2e;border-radius:8px;overflow:hidden;">
      <thead>
        <tr style="background:#0a1628;">
          <th style="padding:9px 14px;text-align:left;color:#556;font-size:11px;text-transform:uppercase;">Player</th>
          <th style="padding:9px 14px;text-align:left;color:#556;font-size:11px;text-transform:uppercase;">Market</th>
          <th style="padding:9px 14px;text-align:left;color:#556;font-size:11px;text-transform:uppercase;">Pick</th>
          <th style="padding:9px 14px;text-align:left;color:#556;font-size:11px;text-transform:uppercase;">Odds</th>
          <th style="padding:9px 14px;text-align:left;color:#556;font-size:11px;text-transform:uppercase;">Result</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>"""


def game_picks_table(picks: list[dict]) -> str:
    if not picks:
        return "<p style='color:#555;font-size:14px;margin:0;'>No qualifying game total picks today.</p>"

    rows = ""
    for p in picks:
        color = _rec_color(p["recommendation"])
        direction = "Over" if p["selection"].lower() == "over" else "Under"
        rows += f"""
        <tr>
          <td style="padding:11px 14px;border-bottom:1px solid #1a2a3a;">
            <div style="font-weight:700;color:#fff;font-size:14px;">
              {p.get('away_team','?')} @ {p.get('home_team','?')}
            </div>
            <div style="color:#556;font-size:11px;margin-top:2px;">Game Total</div>
          </td>
          <td style="padding:11px 14px;border-bottom:1px solid #1a2a3a;color:#fff;font-size:14px;font-weight:600;">
            {direction} {p['point']}
          </td>
          <td style="padding:11px 14px;border-bottom:1px solid #1a2a3a;color:#aaa;font-size:13px;">
            {_fmt_odds(p['bovada_price'])}
          </td>
          <td style="padding:11px 14px;border-bottom:1px solid #1a2a3a;font-weight:700;
                     color:{color};font-size:13px;">
            {p['edge']*100:+.1f}%
          </td>
          <td style="padding:11px 14px;border-bottom:1px solid #1a2a3a;">
            <span style="background:{color};color:#fff;padding:3px 9px;border-radius:4px;
                         font-size:11px;font-weight:700;">{_rec_label(p['recommendation'])}</span>
          </td>
        </tr>"""

    return f"""
    <table width="100%" cellpadding="0" cellspacing="0"
           style="border-collapse:collapse;background:#0f1e2e;border-radius:8px;overflow:hidden;">
      <thead>
        <tr style="background:#0a1628;">
          <th style="padding:9px 14px;text-align:left;color:#556;font-size:11px;text-transform:uppercase;">Matchup</th>
          <th style="padding:9px 14px;text-align:left;color:#556;font-size:11px;text-transform:uppercase;">Pick</th>
          <th style="padding:9px 14px;text-align:left;color:#556;font-size:11px;text-transform:uppercase;">Odds</th>
          <th style="padding:9px 14px;text-align:left;color:#556;font-size:11px;text-transform:uppercase;">Edge</th>
          <th style="padding:9px 14px;text-align:left;color:#556;font-size:11px;text-transform:uppercase;">Rating</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>"""


def game_results_table(picks: list[dict]) -> str:
    if not picks:
        return "<p style='color:#555;font-size:14px;margin:0;'>No graded game total picks from yesterday.</p>"

    rows = ""
    for p in picks:
        color, label = _result_color(p["result"])
        direction = "Over" if p["selection"].lower() == "over" else "Under"
        rows += f"""
        <tr>
          <td style="padding:10px 14px;border-bottom:1px solid #1a2a3a;font-weight:600;color:#fff;font-size:14px;">
            {p.get('away_team','?')} @ {p.get('home_team','?')}
          </td>
          <td style="padding:10px 14px;border-bottom:1px solid #1a2a3a;color:#fff;font-size:13px;">
            {direction} {p['point']}
          </td>
          <td style="padding:10px 14px;border-bottom:1px solid #1a2a3a;color:#aaa;font-size:13px;">
            {_fmt_odds(p['bovada_price'])}
          </td>
          <td style="padding:10px 14px;border-bottom:1px solid #1a2a3a;">
            <span style="background:{color};color:#fff;padding:3px 10px;border-radius:4px;
                         font-size:12px;font-weight:700;">{label}</span>
          </td>
        </tr>"""

    return f"""
    <table width="100%" cellpadding="0" cellspacing="0"
           style="border-collapse:collapse;background:#0f1e2e;border-radius:8px;overflow:hidden;">
      <thead>
        <tr style="background:#0a1628;">
          <th style="padding:9px 14px;text-align:left;color:#556;font-size:11px;text-transform:uppercase;">Matchup</th>
          <th style="padding:9px 14px;text-align:left;color:#556;font-size:11px;text-transform:uppercase;">Pick</th>
          <th style="padding:9px 14px;text-align:left;color:#556;font-size:11px;text-transform:uppercase;">Odds</th>
          <th style="padding:9px 14px;text-align:left;color:#556;font-size:11px;text-transform:uppercase;">Result</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>"""


def record_bar(rec: dict) -> str:
    net_color  = "#00b894" if rec["net"] >= 0 else "#e74c3c"
    roi_color  = "#00b894" if rec["roi"] >= 0 else "#e74c3c"
    wl = rec["wins"] + rec["losses"]
    return f"""
    <div style="display:flex;gap:12px;flex-wrap:wrap;">
      <div style="background:#0f1e2e;border-radius:8px;padding:14px 20px;text-align:center;min-width:80px;">
        <div style="font-size:22px;font-weight:700;color:#fff;">{rec['wins']}-{rec['losses']}</div>
        <div style="font-size:11px;color:#556;text-transform:uppercase;margin-top:3px;">Record</div>
      </div>
      <div style="background:#0f1e2e;border-radius:8px;padding:14px 20px;text-align:center;min-width:80px;">
        <div style="font-size:22px;font-weight:700;color:#fff;">{rec['win_pct']:.1f}%</div>
        <div style="font-size:11px;color:#556;text-transform:uppercase;margin-top:3px;">Win Rate</div>
      </div>
      <div style="background:#0f1e2e;border-radius:8px;padding:14px 20px;text-align:center;min-width:80px;">
        <div style="font-size:22px;font-weight:700;color:{net_color};">{rec['net']:+.1f}u</div>
        <div style="font-size:11px;color:#556;text-transform:uppercase;margin-top:3px;">Net Units</div>
      </div>
      <div style="background:#0f1e2e;border-radius:8px;padding:14px 20px;text-align:center;min-width:80px;">
        <div style="font-size:22px;font-weight:700;color:{roi_color};">{rec['roi']:+.1f}%</div>
        <div style="font-size:11px;color:#556;text-transform:uppercase;margin-top:3px;">ROI</div>
      </div>
      <div style="background:#0f1e2e;border-radius:8px;padding:14px 20px;text-align:center;min-width:80px;">
        <div style="font-size:22px;font-weight:700;color:#fff;">{wl}</div>
        <div style="font-size:11px;color:#556;text-transform:uppercase;margin-top:3px;">Graded</div>
      </div>
    </div>"""


def build_html(today_picks, yesterday_picks, record, today, yesterday,
               today_game_picks=None, yesterday_game_results=None) -> str:
    today_label     = date.fromisoformat(today).strftime("%A, %B %d")
    yesterday_label = date.fromisoformat(yesterday).strftime("%A, %B %d")
    today_game_picks        = today_game_picks or []
    yesterday_game_results  = yesterday_game_results or []
    total_today = len(today_picks) + len(today_game_picks)

    return f"""
    <html>
    <body style="background:#0a1628;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
                 padding:28px 24px;color:#fff;max-width:780px;margin:0 auto;">

      <div style="margin-bottom:28px;">
        <h1 style="font-size:24px;font-weight:800;margin:0 0 4px;color:#fff;">
          MLB V2 &mdash; {today_label}
        </h1>
        <p style="color:#556;font-size:13px;margin:0;">
          {total_today} pick{'s' if total_today!=1 else ''} today
          &nbsp;·&nbsp; Pitcher Outs O / TB Under / P Hits Allowed U
          &nbsp;·&nbsp; -145 to -101 &nbsp;·&nbsp; Edge &ge;1%
        </p>
      </div>

      {section(f"Today's Player Props — {today_label}", picks_table(today_picks))}
      {section(f"Today's Game Totals — {today_label}", game_picks_table(today_game_picks))}
      {section(f"Yesterday's Prop Results — {yesterday_label}", results_table(yesterday_picks))}
      {section(f"Yesterday's Game Total Results — {yesterday_label}", game_results_table(yesterday_game_results))}
      {section("Running Record (Live Picks Only)", record_bar(record))}

      <p style="color:#2a3a4a;font-size:11px;margin-top:24px;text-align:center;">
        MLB V2 &nbsp;·&nbsp; Auto-generated at 5:30 AM PT
      </p>
    </body>
    </html>"""


def send(today_picks, yesterday_picks, record, today, yesterday,
         today_game_picks=None, yesterday_game_results=None) -> None:
    email_from = os.getenv("EMAIL_FROM", "")
    email_pass = os.getenv("EMAIL_PASSWORD", "")
    email_to   = os.getenv("EMAIL_TO", email_from)

    if not email_from or not email_pass:
        print("  EMAIL_FROM / EMAIL_PASSWORD not set — skipping email")
        return

    today_game_picks       = today_game_picks or []
    yesterday_game_results = yesterday_game_results or []
    today_label = date.fromisoformat(today).strftime("%A, %B %d")
    total_today = len(today_picks) + len(today_game_picks)
    subject     = f"MLB Picks — {today_label} ({total_today} picks)"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = email_from
    msg["To"]      = email_to

    plain_lines = ["=== TODAY'S PLAYER PROPS ==="]
    for p in today_picks:
        plain_lines.append(
            f"{p['player_name']} | {p['market_key']} | {p['selection']} {p['point']} | "
            f"{_fmt_odds(p['bovada_price'])} | {p['edge']*100:+.1f}% edge | {_rec_label(p['recommendation'])}"
        )
    plain_lines += ["", "=== TODAY'S GAME TOTALS ==="]
    for p in today_game_picks:
        direction = "Over" if p["selection"].lower() == "over" else "Under"
        plain_lines.append(
            f"{p.get('away_team','?')} @ {p.get('home_team','?')} | {direction} {p['point']} | "
            f"{_fmt_odds(p['bovada_price'])} | {p['edge']*100:+.1f}% edge | {_rec_label(p['recommendation'])}"
        )
    plain_lines += ["", "=== YESTERDAY'S PROP RESULTS ==="]
    for p in yesterday_picks:
        plain_lines.append(
            f"{p['player_name']} | {p['selection']} {p['point']} | "
            f"{_fmt_odds(p['bovada_price'])} | {p.get('result','PENDING')}"
        )
    plain_lines += ["", "=== YESTERDAY'S GAME TOTAL RESULTS ==="]
    for p in yesterday_game_results:
        direction = "Over" if p["selection"].lower() == "over" else "Under"
        plain_lines.append(
            f"{p.get('away_team','?')} @ {p.get('home_team','?')} | {direction} {p['point']} | "
            f"{_fmt_odds(p['bovada_price'])} | {p.get('result','PENDING')}"
        )
    plain_lines += [
        "", "=== RUNNING RECORD ===",
        f"{record['wins']}W - {record['losses']}L  |  {record['win_pct']:.1f}% win rate  |  "
        f"{record['net']:+.1f} units  |  {record['roi']:+.1f}% ROI",
    ]

    msg.attach(MIMEText("\n".join(plain_lines), "plain"))
    msg.attach(MIMEText(
        build_html(today_picks, yesterday_picks, record, today, yesterday,
                   today_game_picks, yesterday_game_results), "html"
    ))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(email_from, email_pass)
        server.sendmail(email_from, email_to, msg.as_string())

    print(f"  Email sent to {email_to}")

    try:
        status_path = ROOT / "data" / "status.json"
        if status_path.exists():
            import json as _json
            status = _json.loads(status_path.read_text())
            status["email_sent"] = True
            status_path.write_text(_json.dumps(status, indent=2))
    except Exception as _e:
        print(f"  WARNING: could not update status.json ({_e})")


def _stamp_emailed(conn, today: str, today_picks: list[dict],
                   today_game_picks: list[dict]) -> None:
    for p in today_picks:
        conn.execute("""
            UPDATE daily_picks SET emailed=1
            WHERE pick_date=? AND event_id=? AND player_name=?
              AND market_key=? AND selection=? AND point=?
        """, (today, p.get("event_id",""), p["player_name"],
              p["market_key"], p["selection"], p["point"]))
    for p in today_game_picks:
        conn.execute("""
            UPDATE daily_game_picks SET emailed=1
            WHERE pick_date=? AND home_team=? AND away_team=?
              AND market_key=? AND selection=? AND point=?
        """, (today, p["home_team"], p["away_team"],
              p["market_key"], p["selection"], p["point"]))
    conn.commit()


def _email_already_sent(today: str) -> bool:
    status_path = ROOT / "data" / "status.json"
    if not status_path.exists():
        return False
    try:
        status = json.loads(status_path.read_text())
        return status.get("date") == today and status.get("email_sent") is True
    except Exception as exc:
        print(f"  WARNING: could not read status.json ({exc})")
        return False


def main() -> None:
    now       = __import__('config').pt_now()
    today     = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    conn = get_conn()
    today_picks            = get_today_picks(conn, today)
    yesterday_picks        = get_yesterday_results(conn, yesterday)
    today_game_picks       = get_today_game_picks(conn, today)
    yesterday_game_results = get_yesterday_game_results(conn, yesterday)
    record                 = get_running_record(conn)

    total_today = len(today_picks) + len(today_game_picks)
    print(f"\n[Email] {total_today} picks today ({len(today_game_picks)} game totals), "
          f"{len(yesterday_picks) + len(yesterday_game_results)} graded yesterday")
    if total_today == 0 and _email_already_sent(today):
        print("  No unemailed picks and today's email was already sent — skipping")
        conn.close()
        return
    try:
        send(today_picks, yesterday_picks, record, today, yesterday,
             today_game_picks, yesterday_game_results)
        _stamp_emailed(conn, today, today_picks, today_game_picks)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
