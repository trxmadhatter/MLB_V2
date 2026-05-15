# MLB V2 Dashboard, Scheduler & Bet Tracking — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Windows Task Scheduler setup, a baseball-themed Streamlit dashboard with bet tracking, and ROI learning stats.

**Architecture:** Three independent deliverables. (1) `setup_scheduler.ps1` registers a Windows Task Scheduler job that calls `run_daily.bat` daily at 5:30 AM — no Claude session required. (2) `db.py` gains three columns (`bet_placed`, `units_wagered`, `notes`) and six new query functions used by the dashboard. (3) `dashboard.py` is a Streamlit app with three tabs: Today's Picks (mark bets with unit input), My Bets (active pending bets), Results & Learning (ROI by market/tier + cumulative P&L chart).

**Tech Stack:** Python 3.11+, SQLite3 (existing), Streamlit ≥1.35, Plotly ≥5.0, Windows Task Scheduler (PowerShell cmdlets)

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `requirements.txt` | Modify | Add streamlit, plotly |
| `db.py` | Modify | Add bet columns, 6 query functions |
| `tests/test_db_bets.py` | Create | Tests for new DB functions |
| `setup_scheduler.ps1` | Create | Register Windows Task Scheduler job |
| `run_daily_logged.bat` | Create | Wrapper that captures output to `logs/daily.log` |
| `dashboard.py` | Create | Streamlit 3-tab dashboard |
| `logs/` | Create (dir) | Log output from scheduled runs |

---

### Task 1: DB schema + bet-tracking query functions

**Files:**
- Modify: `db.py`
- Modify: `requirements.txt`
- Create: `tests/test_db_bets.py`

- [ ] **Step 1: Add streamlit + plotly to requirements**

```
requests>=2.32
python-dotenv>=1.0
pytest>=8.0
streamlit>=1.35
plotly>=5.0
```

Run: `pip install streamlit plotly`
Expected: installs without error.

- [ ] **Step 2: Write failing tests**

Create `tests/test_db_bets.py`:

```python
import pytest
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from db import (
    get_conn, init_db, upsert_pick,
    mark_bet_placed, mark_bet_skipped,
    get_today_picks, get_active_bets,
    get_roi_by_market, get_roi_by_tier, get_cumulative_pnl,
)

SAMPLE_PICK = {
    "pick_date":              "2026-05-14",
    "pulled_at":              "2026-05-14T12:00:00Z",
    "event_id":               "evt1",
    "commence_time":          "2026-05-14T20:00:00Z",
    "home_team":              "Red Sox",
    "away_team":              "Phillies",
    "player_name":            "J. Luzardo",
    "market_key":             "pitcher_strikeouts",
    "selection":              "Over",
    "point":                  6.5,
    "bovada_price":           -145,
    "bovada_break_even_prob": 0.5918,
    "bovada_fair_prob":       0.5540,
    "consensus_fair_prob":    0.5620,
    "consensus_book_count":   5,
    "edge":                   0.0080,
    "ev":                     -0.038,
    "recommendation":         "NO_BET",
}


@pytest.fixture
def conn():
    c = get_conn(":memory:")
    init_db(c)
    return c


def test_schema_has_bet_columns(conn):
    cols = {row[1] for row in conn.execute("PRAGMA table_info(daily_picks)")}
    assert "bet_placed" in cols
    assert "units_wagered" in cols
    assert "notes" in cols


def test_bet_placed_default_zero(conn):
    upsert_pick(conn, SAMPLE_PICK)
    row = conn.execute("SELECT bet_placed FROM daily_picks").fetchone()
    assert row[0] == 0


def test_mark_bet_placed(conn):
    upsert_pick(conn, SAMPLE_PICK)
    pick_id = conn.execute("SELECT id FROM daily_picks").fetchone()[0]
    mark_bet_placed(conn, pick_id, 2.5)
    row = conn.execute("SELECT bet_placed, units_wagered FROM daily_picks").fetchone()
    assert row[0] == 1
    assert row[1] == 2.5


def test_mark_bet_skipped(conn):
    upsert_pick(conn, SAMPLE_PICK)
    pick_id = conn.execute("SELECT id FROM daily_picks").fetchone()[0]
    mark_bet_skipped(conn, pick_id)
    row = conn.execute("SELECT bet_placed FROM daily_picks").fetchone()
    assert row[0] == -1


def test_get_today_picks(conn):
    upsert_pick(conn, SAMPLE_PICK)
    rows = get_today_picks(conn, "2026-05-14")
    assert len(rows) == 1
    assert rows[0]["player_name"] == "J. Luzardo"


def test_get_active_bets_only_returns_pending_bets(conn):
    upsert_pick(conn, SAMPLE_PICK)
    pick_id = conn.execute("SELECT id FROM daily_picks").fetchone()[0]
    # before bet: not active
    assert get_active_bets(conn) == []
    # after bet placed: active
    mark_bet_placed(conn, pick_id, 1.0)
    assert len(get_active_bets(conn)) == 1
    # after result set: no longer active
    conn.execute("UPDATE daily_picks SET result='WIN', profit_units=0.69 WHERE id=?", (pick_id,))
    conn.commit()
    assert get_active_bets(conn) == []


def test_get_roi_by_market_empty(conn):
    assert get_roi_by_market(conn) == []


def test_get_roi_by_tier_counts_graded_bets(conn):
    upsert_pick(conn, SAMPLE_PICK)
    pick_id = conn.execute("SELECT id FROM daily_picks").fetchone()[0]
    mark_bet_placed(conn, pick_id, 1.0)
    conn.execute("UPDATE daily_picks SET result='WIN', profit_units=0.69 WHERE id=?", (pick_id,))
    conn.commit()
    rows = get_roi_by_tier(conn)
    assert len(rows) == 1
    assert rows[0]["wins"] == 1
    assert rows[0]["net_units"] == pytest.approx(0.69, abs=0.01)


def test_get_cumulative_pnl(conn):
    upsert_pick(conn, SAMPLE_PICK)
    pick_id = conn.execute("SELECT id FROM daily_picks").fetchone()[0]
    mark_bet_placed(conn, pick_id, 1.0)
    conn.execute("UPDATE daily_picks SET result='WIN', profit_units=0.69 WHERE id=?", (pick_id,))
    conn.commit()
    rows = get_cumulative_pnl(conn)
    assert len(rows) == 1
    assert rows[0]["cumulative_units"] == pytest.approx(0.69, abs=0.01)
```

- [ ] **Step 3: Run tests — confirm they all fail**

```
cd C:\Users\jesse\MLB_V2
pytest tests/test_db_bets.py -v
```

Expected: ImportError or AttributeError on `mark_bet_placed` etc. (functions don't exist yet).

- [ ] **Step 4: Add columns to `db.py` CREATE TABLE**

In `db.py`, inside the `CREATE TABLE IF NOT EXISTS daily_picks` block, add three columns after `result TEXT NOT NULL DEFAULT 'PENDING'`:

```sql
            result                TEXT NOT NULL DEFAULT 'PENDING',
            actual_stat           REAL,
            profit_units          REAL,
            bet_placed            INTEGER NOT NULL DEFAULT 0,
            units_wagered         REAL,
            notes                 TEXT,
```

- [ ] **Step 5: Add three migrations to `init_db` in `db.py`**

After the existing `try/except` block for `bovada_fair_prob`, add:

```python
    for col_sql in [
        "ALTER TABLE daily_picks ADD COLUMN bet_placed INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE daily_picks ADD COLUMN units_wagered REAL",
        "ALTER TABLE daily_picks ADD COLUMN notes TEXT",
    ]:
        try:
            conn.execute(col_sql)
            conn.commit()
        except Exception:
            pass
```

- [ ] **Step 6: Add the six query functions to `db.py`**

Add after `log_no_bet`:

```python
def mark_bet_placed(conn: sqlite3.Connection, pick_id: int, units: float) -> None:
    conn.execute(
        "UPDATE daily_picks SET bet_placed=1, units_wagered=? WHERE id=?",
        (units, pick_id),
    )
    conn.commit()


def mark_bet_skipped(conn: sqlite3.Connection, pick_id: int) -> None:
    conn.execute("UPDATE daily_picks SET bet_placed=-1 WHERE id=?", (pick_id,))
    conn.commit()


def get_today_picks(conn: sqlite3.Connection, pick_date: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM daily_picks WHERE pick_date=? ORDER BY edge DESC",
        (pick_date,),
    ).fetchall()


def get_active_bets(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("""
        SELECT * FROM daily_picks
        WHERE bet_placed=1 AND result='PENDING'
        ORDER BY pick_date DESC, edge DESC
    """).fetchall()


def get_roi_by_market(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("""
        SELECT market_key,
               COUNT(*) AS bets,
               SUM(CASE WHEN result='WIN'  THEN 1 ELSE 0 END) AS wins,
               SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) AS losses,
               SUM(CASE WHEN result='PUSH' THEN 1 ELSE 0 END) AS pushes,
               ROUND(100.0 * SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) /
                     NULLIF(SUM(CASE WHEN result IN ('WIN','LOSS') THEN 1 ELSE 0 END),0),1) AS win_pct,
               ROUND(SUM(CASE WHEN result NOT IN ('PENDING') THEN COALESCE(profit_units,0) ELSE 0 END),2) AS net_units
        FROM daily_picks
        WHERE bet_placed=1
        GROUP BY market_key
        ORDER BY net_units DESC
    """).fetchall()


def get_roi_by_tier(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("""
        SELECT recommendation,
               COUNT(*) AS bets,
               SUM(CASE WHEN result='WIN'  THEN 1 ELSE 0 END) AS wins,
               SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) AS losses,
               SUM(CASE WHEN result='PUSH' THEN 1 ELSE 0 END) AS pushes,
               ROUND(100.0 * SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) /
                     NULLIF(SUM(CASE WHEN result IN ('WIN','LOSS') THEN 1 ELSE 0 END),0),1) AS win_pct,
               ROUND(SUM(CASE WHEN result NOT IN ('PENDING') THEN COALESCE(profit_units,0) ELSE 0 END),2) AS net_units
        FROM daily_picks
        WHERE bet_placed=1
        GROUP BY recommendation
        ORDER BY net_units DESC
    """).fetchall()


def get_cumulative_pnl(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("""
        SELECT pick_date,
               SUM(COALESCE(profit_units,0)) AS daily_units,
               SUM(SUM(COALESCE(profit_units,0))) OVER (ORDER BY pick_date) AS cumulative_units
        FROM daily_picks
        WHERE bet_placed=1 AND result != 'PENDING'
        GROUP BY pick_date
        ORDER BY pick_date
    """).fetchall()
```

- [ ] **Step 7: Run tests — all should pass**

```
pytest tests/test_db_bets.py -v
```

Expected: 10/10 PASSED.

- [ ] **Step 8: Commit**

```
git add db.py requirements.txt tests/test_db_bets.py
git commit -m "feat: add bet tracking columns and query functions to db"
```

---

### Task 2: Windows Task Scheduler setup

**Files:**
- Create: `setup_scheduler.ps1`
- Create: `run_daily_logged.bat`
- Create: `logs/.gitkeep`

- [ ] **Step 1: Create `run_daily_logged.bat`**

```bat
@echo off
cd /d C:\Users\jesse\MLB_V2
if not exist logs mkdir logs
echo. >> logs\daily.log
echo ===== %DATE% %TIME% ===== >> logs\daily.log
python run_daily.py >> logs\daily.log 2>&1
```

- [ ] **Step 2: Create `logs/.gitkeep`**

Create an empty file at `logs/.gitkeep` so the directory is tracked if the project is in git. The log file itself should be gitignored.

- [ ] **Step 3: Create `setup_scheduler.ps1`**

```powershell
# setup_scheduler.ps1
# Run once in PowerShell (Admin not required for current user tasks).
# Re-running is safe — -Force overwrites the existing task.

$scriptDir = "C:\Users\jesse\MLB_V2"
$batPath   = Join-Path $scriptDir "run_daily_logged.bat"

$action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$batPath`"" `
    -WorkingDirectory $scriptDir

$trigger = New-ScheduledTaskTrigger -Daily -At "05:30AM"

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit  (New-TimeSpan -Minutes 30) `
    -RestartCount        2 `
    -RestartInterval     (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable              # fires if PC was asleep at trigger time

Register-ScheduledTask `
    -TaskName    "MLB_V2_Daily" `
    -Action      $action `
    -Trigger     $trigger `
    -Settings    $settings `
    -RunLevel    Limited `
    -Force | Out-Null

$task = Get-ScheduledTask -TaskName "MLB_V2_Daily"
$nextRun = ($task | Get-ScheduledTaskInfo).NextRunTime
Write-Host "MLB_V2_Daily registered. Next run: $nextRun"
Write-Host "Logs will appear in: $scriptDir\logs\daily.log"
Write-Host ""
Write-Host "To run manually:   Start-ScheduledTask -TaskName MLB_V2_Daily"
Write-Host "To disable:        Disable-ScheduledTask -TaskName MLB_V2_Daily"
Write-Host "To unregister:     Unregister-ScheduledTask -TaskName MLB_V2_Daily -Confirm:`$false"
```

- [ ] **Step 4: Run setup_scheduler.ps1 to register the task**

```powershell
cd C:\Users\jesse\MLB_V2
.\setup_scheduler.ps1
```

Expected output:
```
MLB_V2_Daily registered. Next run: 5/15/2026 5:30:00 AM
Logs will appear in: C:\Users\jesse\MLB_V2\logs\daily.log
```

- [ ] **Step 5: Verify in Task Scheduler**

```powershell
Get-ScheduledTask -TaskName "MLB_V2_Daily" | Select TaskName, State
```

Expected: `MLB_V2_Daily   Ready`

- [ ] **Step 6: Commit**

```
git add setup_scheduler.ps1 run_daily_logged.bat logs/.gitkeep
git commit -m "feat: add Windows Task Scheduler setup for 5:30am daily run"
```

---

### Task 3: Streamlit dashboard

**Files:**
- Create: `dashboard.py`

- [ ] **Step 1: Create `dashboard.py` with full content**

```python
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
    "pitcher_strikeouts":   "Strikeouts",
    "pitcher_hits_allowed": "Hits Allowed",
    "pitcher_earned_runs":  "Earned Runs",
    "batter_hits":          "Hits",
    "batter_total_bases":   "Total Bases",
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
    show_all = st.checkbox("Show all evaluated lines (not just LEAN+)", value=False)
    visible = picks if show_all else [p for p in picks if p["recommendation"] in ("LEAN", "RECOMMENDED")]

    if not visible:
        st.info("No LEAN or RECOMMENDED picks today. Toggle 'Show all' to browse all lines.")
        return

    for p in visible:
        edge_cls = _edge_class(p["recommendation"])
        card_cls = _card_class(p["recommendation"])
        mkt      = _mkt(p["market_key"])

        st.markdown(f"""
<div class="{card_cls}">
  <span class="player-name">{p['player_name']}</span>
  <span class="pick-meta"> &nbsp;·&nbsp; {mkt} &nbsp;{p['selection']} {p['point']:g} &nbsp;@ &nbsp;{p['bovada_price']:+d}</span>
  <span class="{edge_cls}" style="float:right">EDGE {p['edge']:.1%}</span><br>
  <span class="pick-meta">
    BOV fair {p['bovada_fair_prob']:.1%} &nbsp;·&nbsp;
    Consensus {p['consensus_fair_prob']:.1%} &nbsp;·&nbsp;
    EV {p['ev']:+.1%} &nbsp;·&nbsp;
    {p['consensus_book_count']} books &nbsp;·&nbsp;
    <b>{p['recommendation']}</b>
  </span>
</div>
""", unsafe_allow_html=True)

        if p["bet_placed"] == 0:
            uc, bc, sc, _ = st.columns([1.4, 0.9, 0.9, 4])
            units = uc.number_input(
                "Units", min_value=0.5, max_value=20.0, value=1.0, step=0.5,
                key=f"u_{p['id']}", label_visibility="collapsed",
            )
            if bc.button("✅ Bet", key=f"b_{p['id']}"):
                mark_bet_placed(conn, p["id"], units)
                st.rerun()
            if sc.button("❌ Skip", key=f"s_{p['id']}"):
                mark_bet_skipped(conn, p["id"])
                st.rerun()
        elif p["bet_placed"] == 1:
            st.markdown(f'<span class="bet-placed">✅ BET PLACED &nbsp;·&nbsp; {p["units_wagered"]} units</span>', unsafe_allow_html=True)
        else:
            st.markdown('<span class="bet-skipped">— Skipped</span>', unsafe_allow_html=True)

        st.markdown("")


def _render_active_bets(conn) -> None:
    bets = get_active_bets(conn)
    if not bets:
        st.info("No active pending bets. Place bets from Today's Picks.")
        return

    st.subheader(f"⏳ Active Bets  ({len(bets)} pending)")
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
        st.info("No bet history yet. Mark your first bets in Today's Picks — results auto-grade each morning.")
        return

    graded  = (summary["wins"] or 0) + (summary["losses"] or 0)
    win_pct = (summary["wins"] or 0) / graded * 100 if graded else 0.0
    net     = summary["net_units"] or 0.0
    roi     = net / summary["total"] * 100

    c1, c2, c3, c4, c5 = st.columns(5)
    _render_stat(c1, str(summary["total"]),
                 "Total Bets")
    _render_stat(c2, f"{summary['wins'] or 0}-{summary['losses'] or 0}-{summary['pushes'] or 0}",
                 "W — L — P")
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
            df["Win%"]      = df["win_pct"].map(lambda v: f"{v:.1f}%" if v is not None else "—")
            df["Net Units"] = df["net_units"].map("{:+.2f}".format)
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
            df["Win%"]      = df["win_pct"].map(lambda v: f"{v:.1f}%" if v is not None else "—")
            df["Net Units"] = df["net_units"].map("{:+.2f}".format)
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
        st.subheader("📈 Cumulative P&L (units)")
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


def main() -> None:
    st.set_page_config(page_title="⚾ MLB V2", page_icon="⚾", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)

    today = _pt_date()
    conn  = _db_conn(DB_PATH)

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

    tab1, tab2, tab3 = st.tabs(["📋  Today's Picks", "💰  My Bets", "📊  Results & Learning"])

    with tab1:
        _render_today(conn, today)
    with tab2:
        _render_active_bets(conn)
    with tab3:
        _render_learning(conn)

    conn.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the dashboard and verify in browser**

```
cd C:\Users\jesse\MLB_V2
streamlit run dashboard.py
```

Expected: browser opens at `http://localhost:8501` showing the ⚾ MLB V2 header and three tabs.

- [ ] **Step 3: Verify Today's Picks tab**

Check:
- Summary stat boxes show correct counts
- Picks display with correct edge color (green = RECOMMENDED, amber = LEAN, dark = NO_BET)
- "Show all lines" checkbox works
- Each pick shows player, market, selection, line, price, BOV fair, consensus, EV, books, tier
- Bet / Skip buttons appear on undecided picks

- [ ] **Step 4: Mark a pick as Bet and verify state persists**

- Click ✅ Bet on any pick
- Verify the row changes to "✅ BET PLACED · N units"
- Navigate to My Bets tab — pick should appear in the table
- Refresh page (F5) — bet should still be marked (it's in SQLite, not session state)

- [ ] **Step 5: Verify Results & Learning tab**

- With no graded bets: shows "No bet history yet." message
- After placing and manually grading a bet in the DB (or waiting for tomorrow's grade run), stats appear with W-L-P, win rate, net units, ROI, and tables

- [ ] **Step 6: Commit**

```
git add dashboard.py
git commit -m "feat: Streamlit dashboard with bet tracking and ROI learning"
```

---

## Self-Review

**Spec coverage:**
- ✅ Durable scheduling without Claude open → `setup_scheduler.ps1` + `run_daily_logged.bat`
- ✅ Nice dashboard → Streamlit with baseball dark theme, stat boxes, colored cards
- ✅ Bet tracking → `bet_placed` / `units_wagered` columns + Bet/Skip buttons
- ✅ Track which bets you placed → My Bets tab
- ✅ Learn from results → Results & Learning tab with ROI by market/tier + cumulative P&L

**Placeholder scan:** None found — all code blocks are complete.

**Type consistency:** `mark_bet_placed(conn, pick_id: int, units: float)` matches all call sites. `get_today_picks` returns `list[sqlite3.Row]` with `bet_placed`, `units_wagered` columns available — all accesses in `dashboard.py` use the correct key names.

**One note for the implementer:** `dashboard.py` imports from `db.py` using `from db import ...`. This works when `streamlit run dashboard.py` is launched from `C:\Users\jesse\MLB_V2`. Do not run it from a different working directory.
