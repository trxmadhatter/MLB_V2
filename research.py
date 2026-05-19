#!/usr/bin/env python3
"""
MLB V2 — Market Calibration Research
Queries backtest.db across all predictive dimensions to find filters that
produce positive net_units on >=15 picks.

Usage: python research.py
"""
import sqlite3
from pathlib import Path

DB = Path(__file__).parent / "data" / "backtest.db"
MIN_PICKS = 15   # minimum picks required to flag a segment


def connect():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def _header(title: str) -> None:
    print(f"\n{'='*72}")
    print(f"  {title}")
    print(f"{'='*72}")


def _fmt(rows, cols: list, col_widths: list, flag_col: str = "") -> None:
    header = "  " + "  ".join(f"{c:<{w}}" for c, w in zip(cols, col_widths))
    print(header)
    print("  " + "-" * (sum(col_widths) + 2 * len(cols)))
    for r in rows:
        line = "  " + "  ".join(f"{str(r[c] or ''):<{w}}" for c, w in zip(cols, col_widths))
        marker = " *" if flag_col and r[flag_col] == "YES" else ""
        print(line + marker)


# ── 1. Market + Selection overview ────────────────────────────────────────────

def section_market_overview(conn):
    _header("1. MARKET + SELECTION OVERVIEW (all graded picks)")
    rows = conn.execute("""
        SELECT market_key || ' ' || selection AS segment,
               COUNT(*) AS n,
               SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) AS wins,
               ROUND(100.0 * SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END)
                     / COUNT(*), 1) AS win_pct,
               ROUND(AVG(bovada_fair_prob) * 100, 1) AS avg_bev_pct,
               ROUND(SUM(profit_units), 2) AS net_units,
               CASE WHEN COUNT(*) >= ? AND SUM(profit_units) > 0 THEN 'YES' ELSE '' END AS flag
        FROM backtest_picks WHERE result NOT IN ('PENDING')
        GROUP BY segment ORDER BY net_units DESC
    """, (MIN_PICKS,)).fetchall()
    _fmt(rows,
         ["segment", "n", "wins", "win_pct", "avg_bev_pct", "net_units", "flag"],
         [38, 5, 5, 8, 11, 10, 4], flag_col="flag")


# ── 2. Recommendation tier performance ────────────────────────────────────────

def section_tier_performance(conn):
    _header("2. RECOMMENDATION TIER PERFORMANCE")
    rows = conn.execute("""
        SELECT recommendation, market_key || ' ' || selection AS market,
               COUNT(*) AS n,
               SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) AS wins,
               ROUND(100.0 * SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END)
                     / COUNT(*), 1) AS win_pct,
               ROUND(AVG(bovada_fair_prob) * 100, 1) AS avg_bev_pct,
               ROUND(SUM(profit_units), 2) AS net_units
        FROM backtest_picks WHERE result NOT IN ('PENDING')
          AND recommendation IN ('LEAN', 'RECOMMENDED')
        GROUP BY recommendation, market
        HAVING COUNT(*) >= 5
        ORDER BY recommendation DESC, net_units DESC
    """).fetchall()
    _fmt(rows,
         ["recommendation", "market", "n", "wins", "win_pct", "avg_bev_pct", "net_units"],
         [13, 35, 5, 5, 8, 11, 10])


# ── 3. Edge bucket analysis ────────────────────────────────────────────────────

def section_edge_buckets(conn):
    _header("3. EDGE BUCKET ANALYSIS (all picks, profitable markets only)")
    profitable = [
        ("batter_total_bases", "Under"),
        ("pitcher_outs", "Over"),
        ("pitcher_hits_allowed", "Under"),
    ]
    for mkt, sel in profitable:
        rows = conn.execute("""
            SELECT
                CASE
                    WHEN edge < 0.01 THEN 'a.<1%'
                    WHEN edge < 0.02 THEN 'b.1-2%'
                    WHEN edge < 0.03 THEN 'c.2-3%'
                    WHEN edge < 0.04 THEN 'd.3-4%'
                    WHEN edge < 0.05 THEN 'e.4-5%'
                    WHEN edge < 0.06 THEN 'f.5-6%'
                    WHEN edge < 0.08 THEN 'g.6-8%'
                    ELSE 'h.8%+'
                END AS edge_bucket,
                COUNT(*) AS n,
                SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) AS wins,
                ROUND(100.0 * SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END)
                      / COUNT(*), 1) AS win_pct,
                ROUND(AVG(bovada_fair_prob) * 100, 1) AS avg_bev_pct,
                ROUND(SUM(profit_units), 2) AS net_units,
                CASE WHEN COUNT(*) >= ? AND SUM(profit_units) > 0 THEN 'YES' ELSE '' END AS flag
            FROM backtest_picks
            WHERE result NOT IN ('PENDING')
              AND market_key = ? AND selection = ?
            GROUP BY edge_bucket ORDER BY edge_bucket
        """, (MIN_PICKS, mkt, sel)).fetchall()
        print(f"\n  [{mkt} {sel}]")
        _fmt(rows,
             ["edge_bucket", "n", "wins", "win_pct", "avg_bev_pct", "net_units", "flag"],
             [12, 5, 5, 8, 11, 10, 4], flag_col="flag")


# ── 4. Consensus book count ────────────────────────────────────────────────────

def section_book_count(conn):
    _header("4. CONSENSUS BOOK COUNT (profitable markets)")
    profitable = [
        ("batter_total_bases", "Under"),
        ("pitcher_outs", "Over"),
        ("pitcher_hits_allowed", "Under"),
    ]
    for mkt, sel in profitable:
        rows = conn.execute("""
            SELECT consensus_book_count AS books,
                   COUNT(*) AS n,
                   SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) AS wins,
                   ROUND(100.0 * SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END)
                         / COUNT(*), 1) AS win_pct,
                   ROUND(SUM(profit_units), 2) AS net_units,
                   CASE WHEN COUNT(*) >= 5 AND SUM(profit_units) > 0 THEN 'YES' ELSE '' END AS flag
            FROM backtest_picks
            WHERE result NOT IN ('PENDING')
              AND market_key = ? AND selection = ?
            GROUP BY books ORDER BY books
        """, (mkt, sel)).fetchall()
        print(f"\n  [{mkt} {sel}]")
        _fmt(rows,
             ["books", "n", "wins", "win_pct", "net_units", "flag"],
             [6, 5, 5, 8, 10, 4], flag_col="flag")


# ── 5. Price range analysis ────────────────────────────────────────────────────

def section_price_range(conn):
    _header("5. PRICE RANGE ANALYSIS (profitable markets)")
    profitable = [
        ("batter_total_bases", "Under"),
        ("pitcher_outs", "Over"),
        ("pitcher_hits_allowed", "Under"),
    ]
    for mkt, sel in profitable:
        rows = conn.execute("""
            SELECT
                CASE
                    WHEN bovada_price <= -200 THEN 'a.<=-200'
                    WHEN bovada_price <= -145 THEN 'b.-200to-146'
                    WHEN bovada_price <= -110 THEN 'c.-145to-111'
                    WHEN bovada_price <= -101 THEN 'd.-110to-101'
                    WHEN bovada_price <  100  THEN 'e.-100to+99'
                    ELSE                           'f.+100+'
                END AS price_range,
                COUNT(*) AS n,
                SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) AS wins,
                ROUND(100.0 * SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END)
                      / COUNT(*), 1) AS win_pct,
                ROUND(AVG(bovada_fair_prob) * 100, 1) AS avg_bev_pct,
                ROUND(SUM(profit_units), 2) AS net_units,
                CASE WHEN COUNT(*) >= 5 AND SUM(profit_units) > 0 THEN 'YES' ELSE '' END AS flag
            FROM backtest_picks
            WHERE result NOT IN ('PENDING')
              AND market_key = ? AND selection = ?
            GROUP BY price_range ORDER BY price_range
        """, (mkt, sel)).fetchall()
        print(f"\n  [{mkt} {sel}]")
        _fmt(rows,
             ["price_range", "n", "wins", "win_pct", "avg_bev_pct", "net_units", "flag"],
             [14, 5, 5, 8, 11, 10, 4], flag_col="flag")


# ── 6. Line value analysis ─────────────────────────────────────────────────────

def section_line_values(conn):
    _header("6. LINE VALUE ANALYSIS")

    for mkt, sel in [("batter_total_bases", "Under"), ("batter_total_bases", "Over")]:
        rows = conn.execute("""
            SELECT point AS line,
                   COUNT(*) AS n,
                   SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) AS wins,
                   ROUND(100.0 * SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END)
                         / COUNT(*), 1) AS win_pct,
                   ROUND(SUM(profit_units), 2) AS net_units,
                   CASE WHEN COUNT(*) >= 5 AND SUM(profit_units) > 0 THEN 'YES' ELSE '' END AS flag
            FROM backtest_picks
            WHERE result NOT IN ('PENDING')
              AND market_key = ? AND selection = ?
            GROUP BY line ORDER BY line
        """, (mkt, sel)).fetchall()
        print(f"\n  [{mkt} {sel}]")
        _fmt(rows,
             ["line", "n", "wins", "win_pct", "net_units", "flag"],
             [6, 5, 5, 8, 10, 4], flag_col="flag")

    for sel in ("Over", "Under"):
        rows = conn.execute("""
            SELECT point AS line,
                   COUNT(*) AS n,
                   SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) AS wins,
                   ROUND(100.0 * SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END)
                         / COUNT(*), 1) AS win_pct,
                   ROUND(SUM(profit_units), 2) AS net_units,
                   CASE WHEN COUNT(*) >= 5 AND SUM(profit_units) > 0 THEN 'YES' ELSE '' END AS flag
            FROM backtest_picks
            WHERE result NOT IN ('PENDING')
              AND market_key = 'pitcher_strikeouts' AND selection = ?
            GROUP BY line ORDER BY line
        """, (sel,)).fetchall()
        print(f"\n  [pitcher_strikeouts {sel}]")
        _fmt(rows,
             ["line", "n", "wins", "win_pct", "net_units", "flag"],
             [6, 5, 5, 8, 10, 4], flag_col="flag")

    rows = conn.execute("""
        SELECT point AS line,
               COUNT(*) AS n,
               SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) AS wins,
               ROUND(100.0 * SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END)
                     / COUNT(*), 1) AS win_pct,
               ROUND(SUM(profit_units), 2) AS net_units,
               CASE WHEN COUNT(*) >= 5 AND SUM(profit_units) > 0 THEN 'YES' ELSE '' END AS flag
        FROM backtest_picks
        WHERE result NOT IN ('PENDING')
          AND market_key = 'pitcher_outs' AND selection = 'Over'
        GROUP BY line ORDER BY line
    """).fetchall()
    print("\n  [pitcher_outs Over]")
    _fmt(rows,
         ["line", "n", "wins", "win_pct", "net_units", "flag"],
         [6, 5, 5, 8, 10, 4], flag_col="flag")


# ── 7. Compound filter ─────────────────────────────────────────────────────────

def section_compound_filter(conn):
    _header("7. COMPOUND FILTER — edge >= 2% + books >= 4")
    rows = conn.execute("""
        SELECT market_key || ' ' || selection AS segment,
               COUNT(*) AS n,
               SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) AS wins,
               ROUND(100.0 * SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END)
                     / COUNT(*), 1) AS win_pct,
               ROUND(AVG(bovada_fair_prob) * 100, 1) AS avg_bev_pct,
               ROUND(SUM(profit_units), 2) AS net_units,
               CASE WHEN COUNT(*) >= ? AND SUM(profit_units) > 0 THEN 'YES' ELSE '' END AS flag
        FROM backtest_picks
        WHERE result NOT IN ('PENDING')
          AND edge >= 0.02
          AND consensus_book_count >= 4
        GROUP BY segment
        HAVING COUNT(*) >= 5
        ORDER BY net_units DESC
    """, (MIN_PICKS,)).fetchall()
    _fmt(rows,
         ["segment", "n", "wins", "win_pct", "avg_bev_pct", "net_units", "flag"],
         [38, 5, 5, 8, 11, 10, 4], flag_col="flag")

    _header("7b. HELD-OUT — last 2 weeks (2026-05-01+), edge>=2%, books>=4")
    rows = conn.execute("""
        SELECT market_key || ' ' || selection AS segment,
               COUNT(*) AS n,
               SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) AS wins,
               ROUND(100.0 * SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END)
                     / COUNT(*), 1) AS win_pct,
               ROUND(SUM(profit_units), 2) AS net_units
        FROM backtest_picks
        WHERE result NOT IN ('PENDING')
          AND edge >= 0.02
          AND consensus_book_count >= 4
          AND pick_date >= '2026-05-01'
        GROUP BY segment
        HAVING COUNT(*) >= 3
        ORDER BY net_units DESC
    """).fetchall()
    _fmt(rows,
         ["segment", "n", "wins", "win_pct", "net_units"],
         [38, 5, 5, 8, 10])


# ── 8. Edge x books compound grid ─────────────────────────────────────────────

def section_best_compound(conn):
    _header("8. EDGE x BOOKS GRID (top-3 profitable markets)")
    for mkt, sel in [("batter_total_bases", "Under"), ("pitcher_outs", "Over"),
                     ("pitcher_hits_allowed", "Under")]:
        rows = conn.execute("""
            SELECT
                CASE
                    WHEN edge < 0.02 THEN '<2%'
                    WHEN edge < 0.04 THEN '2-4%'
                    WHEN edge < 0.06 THEN '4-6%'
                    ELSE '6%+'
                END AS edge_band,
                CASE WHEN consensus_book_count >= 6 THEN '6+'
                     WHEN consensus_book_count = 5   THEN '5'
                     WHEN consensus_book_count = 4   THEN '4'
                     ELSE '3'
                END AS books,
                COUNT(*) AS n,
                SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) AS wins,
                ROUND(100.0 * SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END)
                      / COUNT(*), 1) AS win_pct,
                ROUND(AVG(bovada_fair_prob)*100, 1) AS avg_bev,
                ROUND(SUM(profit_units), 2) AS net_units,
                CASE WHEN COUNT(*) >= 8 AND SUM(profit_units) > 0 THEN 'YES' ELSE '' END AS flag
            FROM backtest_picks
            WHERE result NOT IN ('PENDING')
              AND market_key = ? AND selection = ?
            GROUP BY edge_band, books
            ORDER BY edge_band, books
        """, (mkt, sel)).fetchall()
        print(f"\n  [{mkt} {sel}]")
        _fmt(rows,
             ["edge_band", "books", "n", "wins", "win_pct", "avg_bev", "net_units", "flag"],
             [8, 6, 5, 5, 8, 8, 10, 4], flag_col="flag")


# ── 9. Summary ─────────────────────────────────────────────────────────────────

def section_summary(conn):
    _header("9. SUMMARY — All segments >=15 picks with positive net_units")
    rows = conn.execute("""
        SELECT market_key || ' ' || selection AS segment,
               COUNT(*) AS n,
               ROUND(100.0 * SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END)
                     / COUNT(*), 1) AS win_pct,
               ROUND(AVG(bovada_fair_prob)*100, 1) AS avg_bev_pct,
               ROUND(AVG(edge)*100, 2) AS avg_edge_pct,
               ROUND(SUM(profit_units), 2) AS net_units,
               ROUND(SUM(profit_units) / COUNT(*), 4) AS units_per_pick
        FROM backtest_picks
        WHERE result NOT IN ('PENDING')
        GROUP BY segment
        HAVING COUNT(*) >= ?
          AND SUM(profit_units) > 0
        ORDER BY units_per_pick DESC
    """, (MIN_PICKS,)).fetchall()
    _fmt(rows,
         ["segment", "n", "win_pct", "avg_bev_pct", "avg_edge_pct", "net_units", "units_per_pick"],
         [38, 5, 8, 11, 12, 10, 14])


def main():
    conn = connect()
    n_total = conn.execute(
        "SELECT COUNT(*) FROM backtest_picks WHERE result NOT IN ('PENDING')"
    ).fetchone()[0]
    dates = conn.execute(
        "SELECT MIN(pick_date), MAX(pick_date) FROM backtest_picks WHERE result NOT IN ('PENDING')"
    ).fetchone()
    print(f"\nMLB V2 Market Calibration Research")
    print(f"  Graded picks: {n_total}  |  Date range: {dates[0]} to {dates[1]}")

    section_market_overview(conn)
    section_tier_performance(conn)
    section_edge_buckets(conn)
    section_book_count(conn)
    section_price_range(conn)
    section_line_values(conn)
    section_compound_filter(conn)
    section_best_compound(conn)
    section_summary(conn)

    conn.close()
    print()


if __name__ == "__main__":
    main()
