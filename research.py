#!/usr/bin/env python3
"""
MLB V2 Market Research — find which pick characteristics predict profitability.

Queries backtest.db directly with per-pick break-even calculations.
No API calls. Read-only.

Usage:
    python research.py
    python research.py --section edge        # one section only
    python research.py --min-picks 10        # lower sample threshold
"""
import argparse
import sqlite3
from pathlib import Path

BACKTEST_DB = Path(__file__).parent / "data" / "backtest.db"
DEFAULT_MIN_PICKS = 15

SECTION_NAMES = ["overview", "edge", "price", "market", "books", "lines", "compound"]


# ── helpers ───────────────────────────────────────────────────────────────────

def bev_expr(col: str = "bovada_price") -> str:
    """SQL expression for per-pick break-even probability."""
    return (
        f"CASE WHEN {col} > 0 "
        f"THEN 100.0 / ({col} + 100) "
        f"ELSE ABS({col}) * 1.0 / (ABS({col}) + 100) END"
    )


def header(title: str) -> None:
    print(f"\n{'='*68}")
    print(f"  {title}")
    print(f"{'='*68}")


def print_table(rows: list, cols: list[tuple[str, int, str]], min_n: int = 0) -> None:
    """
    cols: list of (label, width, format_spec)
    Skips rows where first numeric column < min_n.
    """
    header_row = "  " + "  ".join(f"{c[0]:{c[1]}}" for c in cols)
    print(header_row)
    print("  " + "-" * (sum(c[1] for c in cols) + 2 * len(cols)))
    printed = 0
    for row in rows:
        vals = []
        for i, (_, width, fmt) in enumerate(cols):
            v = row[i]
            if v is None:
                vals.append(f"{'--':>{width}}")
            else:
                try:
                    vals.append(f"{v:{fmt}>{width}}" if fmt else f"{str(v):<{width}}")
                except (TypeError, ValueError):
                    vals.append(f"{str(v):<{width}}")
        print("  " + "  ".join(vals))
        printed += 1
    if printed == 0:
        print("  (no rows meeting threshold)")


# ── queries ───────────────────────────────────────────────────────────────────

def section_overview(conn: sqlite3.Connection) -> None:
    header("OVERVIEW — ALL GRADED PICKS BY TIER")
    bev = bev_expr()
    rows = conn.execute(f"""
        SELECT
            recommendation,
            COUNT(*) AS n,
            SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) AS losses,
            ROUND(100.0 * SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END)
                / NULLIF(SUM(CASE WHEN result IN ('WIN','LOSS') THEN 1 ELSE 0 END), 0), 1) AS win_pct,
            ROUND(AVG({bev}) * 100, 1) AS avg_bev_pct,
            ROUND(SUM(profit_units), 2) AS net_units,
            ROUND(100.0 * SUM(profit_units)
                / NULLIF(SUM(CASE WHEN result IN ('WIN','LOSS','PUSH') THEN 1 ELSE 0 END), 0), 1) AS roi_pct,
            SUM(CASE WHEN profit_units > ({bev} - 0.5) THEN 1 ELSE 0 END) AS above_bev_count
        FROM backtest_picks
        WHERE result IN ('WIN','LOSS','PUSH')
        GROUP BY recommendation
        ORDER BY CASE recommendation WHEN 'RECOMMENDED' THEN 0 WHEN 'LEAN' THEN 1 ELSE 2 END
    """).fetchall()
    cols = [
        ("TIER", 14, ""),
        ("N", 5, ".0f"),
        ("W", 5, ".0f"),
        ("L", 5, ".0f"),
        ("WIN%", 6, ".1f"),
        ("BEV%", 6, ".1f"),
        ("NET_U", 8, ".2f"),
        ("ROI%", 7, ".1f"),
    ]
    print_table([[r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7]] for r in rows], cols)

    print("\n  NOTE: BEV% = avg break-even prob needed (per-pick, not avg-price bucket)")
    print("        If WIN% < BEV% the market is structurally losing.\n")


def section_edge(conn: sqlite3.Connection, min_n: int) -> None:
    header("EDGE BUCKET ANALYSIS — does more edge predict more wins?")
    bev = bev_expr()
    rows = conn.execute(f"""
        SELECT
            CASE
                WHEN edge < 0     THEN '< 0%  '
                WHEN edge < 0.01  THEN '0-1%  '
                WHEN edge < 0.02  THEN '1-2%  '
                WHEN edge < 0.03  THEN '2-3%  '
                WHEN edge < 0.04  THEN '3-4%  '
                WHEN edge < 0.05  THEN '4-5%  '
                WHEN edge < 0.06  THEN '5-6%  '
                WHEN edge < 0.08  THEN '6-8%  '
                ELSE              '8%+   '
            END AS bucket,
            COUNT(*) AS n,
            ROUND(AVG(edge)*100,1) AS avg_edge_pct,
            SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) AS losses,
            ROUND(100.0 * SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END)
                / NULLIF(SUM(CASE WHEN result IN ('WIN','LOSS') THEN 1 ELSE 0 END),0), 1) AS win_pct,
            ROUND(AVG({bev})*100,1) AS avg_bev_pct,
            ROUND(SUM(profit_units),2) AS net_units,
            ROUND(100.0 * SUM(profit_units)
                / NULLIF(SUM(CASE WHEN result IN ('WIN','LOSS','PUSH') THEN 1 ELSE 0 END),0), 1) AS roi_pct
        FROM backtest_picks
        WHERE result IN ('WIN','LOSS','PUSH')
        GROUP BY bucket
        HAVING n >= {min_n}
        ORDER BY MIN(edge)
    """).fetchall()
    cols = [
        ("EDGE_BUCKET", 10, ""),
        ("N", 5, ".0f"),
        ("AVG_EDGE%", 9, ".1f"),
        ("W", 5, ".0f"),
        ("L", 5, ".0f"),
        ("WIN%", 6, ".1f"),
        ("BEV%", 6, ".1f"),
        ("NET_U", 8, ".2f"),
        ("ROI%", 7, ".1f"),
    ]
    print_table([[r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8]] for r in rows], cols, min_n)
    print("\n  KEY: If WIN% doesn't rise with edge, the consensus edge signal is noise.\n")


def section_price(conn: sqlite3.Connection, min_n: int) -> None:
    header("PRICE RANGE ANALYSIS — which odds ranges are profitable?")
    bev = bev_expr()
    rows = conn.execute(f"""
        SELECT
            CASE
                WHEN bovada_price <= -200 THEN '<=-200 heavy_fav '
                WHEN bovada_price <= -150 THEN '-150 to -200    '
                WHEN bovada_price <= -120 THEN '-120 to -150    '
                WHEN bovada_price <= -101 THEN '-101 to -120    '
                WHEN bovada_price < 0     THEN '-100 to -1      '
                WHEN bovada_price <= 100  THEN 'even to +100    '
                WHEN bovada_price <= 150  THEN '+101 to +150    '
                ELSE                          '+151 and up     '
            END AS price_range,
            COUNT(*) AS n,
            ROUND(AVG(bovada_price),0) AS avg_price,
            ROUND(AVG({bev})*100,1) AS avg_bev_pct,
            SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) AS losses,
            ROUND(100.0 * SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END)
                / NULLIF(SUM(CASE WHEN result IN ('WIN','LOSS') THEN 1 ELSE 0 END),0), 1) AS win_pct,
            ROUND(SUM(profit_units),2) AS net_units,
            ROUND(100.0 * SUM(profit_units)
                / NULLIF(SUM(CASE WHEN result IN ('WIN','LOSS','PUSH') THEN 1 ELSE 0 END),0), 1) AS roi_pct
        FROM backtest_picks
        WHERE result IN ('WIN','LOSS','PUSH')
        GROUP BY price_range
        HAVING n >= {min_n}
        ORDER BY avg_price
    """).fetchall()
    cols = [
        ("PRICE_RANGE", 18, ""),
        ("N", 5, ".0f"),
        ("AVG_PRC", 7, ".0f"),
        ("BEV%", 6, ".1f"),
        ("W", 5, ".0f"),
        ("L", 5, ".0f"),
        ("WIN%", 6, ".1f"),
        ("NET_U", 8, ".2f"),
        ("ROI%", 7, ".1f"),
    ]
    print_table([[r[0],r[1],r[2],r[3],r[4],r[5],r[6],r[7],r[8]] for r in rows], cols, min_n)


def section_market(conn: sqlite3.Connection, min_n: int) -> None:
    header("MARKET + SELECTION — which combos beat break-even? (ALL tiers)")
    bev = bev_expr()
    rows = conn.execute(f"""
        SELECT
            market_key,
            selection,
            COUNT(*) AS n,
            ROUND(AVG({bev})*100,1) AS avg_bev_pct,
            SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) AS losses,
            ROUND(100.0 * SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END)
                / NULLIF(SUM(CASE WHEN result IN ('WIN','LOSS') THEN 1 ELSE 0 END),0), 1) AS win_pct,
            ROUND(SUM(profit_units),2) AS net_units,
            ROUND(100.0 * SUM(profit_units)
                / NULLIF(SUM(CASE WHEN result IN ('WIN','LOSS','PUSH') THEN 1 ELSE 0 END),0), 1) AS roi_pct,
            CASE WHEN SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) * 1.0
                      / NULLIF(SUM(CASE WHEN result IN ('WIN','LOSS') THEN 1 ELSE 0 END),0)
                      > AVG({bev})
                 THEN 'YES' ELSE 'NO' END AS beats_bev
        FROM backtest_picks
        WHERE result IN ('WIN','LOSS','PUSH')
        GROUP BY market_key, selection
        HAVING n >= {min_n}
        ORDER BY roi_pct DESC
    """).fetchall()
    cols = [
        ("MARKET", 22, ""),
        ("SEL", 6, ""),
        ("N", 5, ".0f"),
        ("BEV%", 6, ".1f"),
        ("W", 5, ".0f"),
        ("L", 5, ".0f"),
        ("WIN%", 6, ".1f"),
        ("NET_U", 8, ".2f"),
        ("ROI%", 7, ".1f"),
        ("BEATS_BEV", 9, ""),
    ]
    print_table([[r[0],r[1],r[2],r[3],r[4],r[5],r[6],r[7],r[8],r[9]] for r in rows], cols, min_n)


def section_books(conn: sqlite3.Connection, min_n: int) -> None:
    header("CONSENSUS BOOK COUNT — does more books = better signal?")
    bev = bev_expr()
    rows = conn.execute(f"""
        SELECT
            CASE
                WHEN consensus_book_count = 3 THEN '3 books  '
                WHEN consensus_book_count = 4 THEN '4 books  '
                WHEN consensus_book_count = 5 THEN '5 books  '
                WHEN consensus_book_count = 6 THEN '6 books  '
                ELSE                               '7+ books '
            END AS book_bucket,
            consensus_book_count,
            COUNT(*) AS n,
            ROUND(AVG({bev})*100,1) AS avg_bev_pct,
            SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) AS losses,
            ROUND(100.0 * SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END)
                / NULLIF(SUM(CASE WHEN result IN ('WIN','LOSS') THEN 1 ELSE 0 END),0), 1) AS win_pct,
            ROUND(SUM(profit_units),2) AS net_units,
            ROUND(100.0 * SUM(profit_units)
                / NULLIF(SUM(CASE WHEN result IN ('WIN','LOSS','PUSH') THEN 1 ELSE 0 END),0), 1) AS roi_pct
        FROM backtest_picks
        WHERE result IN ('WIN','LOSS','PUSH')
        GROUP BY book_bucket
        HAVING n >= {min_n}
        ORDER BY consensus_book_count
    """).fetchall()
    cols = [
        ("BOOKS", 10, ""),
        ("EXACT_N", 7, ".0f"),
        ("PICKS", 5, ".0f"),
        ("BEV%", 6, ".1f"),
        ("W", 5, ".0f"),
        ("L", 5, ".0f"),
        ("WIN%", 6, ".1f"),
        ("NET_U", 8, ".2f"),
        ("ROI%", 7, ".1f"),
    ]
    print_table([[r[0],r[1],r[2],r[3],r[4],r[5],r[6],r[7],r[8]] for r in rows], cols, min_n)


def section_lines(conn: sqlite3.Connection, min_n: int) -> None:
    header("LINE VALUE BY MARKET — which specific lines win?")
    bev = bev_expr()

    markets = conn.execute("""
        SELECT DISTINCT market_key
        FROM backtest_picks
        WHERE result IN ('WIN','LOSS','PUSH')
        GROUP BY market_key
        HAVING COUNT(*) >= 50
        ORDER BY market_key
    """).fetchall()

    cols = [
        ("POINT", 7, ".1f"),
        ("N", 5, ".0f"),
        ("BEV%", 6, ".1f"),
        ("W", 5, ".0f"),
        ("L", 5, ".0f"),
        ("WIN%", 6, ".1f"),
        ("NET_U", 8, ".2f"),
        ("ROI%", 7, ".1f"),
    ]

    for (mkt,) in markets:
        rows = conn.execute(f"""
            SELECT
                point,
                COUNT(*) AS n,
                ROUND(AVG({bev})*100,1) AS avg_bev_pct,
                SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) AS losses,
                ROUND(100.0 * SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END)
                    / NULLIF(SUM(CASE WHEN result IN ('WIN','LOSS') THEN 1 ELSE 0 END),0), 1) AS win_pct,
                ROUND(SUM(profit_units),2) AS net_units,
                ROUND(100.0 * SUM(profit_units)
                    / NULLIF(SUM(CASE WHEN result IN ('WIN','LOSS','PUSH') THEN 1 ELSE 0 END),0), 1) AS roi_pct
            FROM backtest_picks
            WHERE result IN ('WIN','LOSS','PUSH')
              AND market_key = ?
            GROUP BY point
            HAVING n >= {min_n}
            ORDER BY net_units DESC
        """, (mkt,)).fetchall()

        if rows:
            print(f"\n  {mkt}:")
            print_table([[r[0],r[1],r[2],r[3],r[4],r[5],r[6],r[7]] for r in rows], cols, min_n)


def section_compound(conn: sqlite3.Connection, min_n: int) -> None:
    header("COMPOUND FILTERS — market + selection + edge + books + price")

    bev = bev_expr()
    rows = conn.execute(f"""
        SELECT
            market_key,
            selection,
            CASE
                WHEN edge < 0.02 THEN '<2%'
                WHEN edge < 0.04 THEN '2-4%'
                WHEN edge < 0.06 THEN '4-6%'
                ELSE '6%+'
            END AS edge_bucket,
            CASE
                WHEN consensus_book_count >= 6 THEN '6+'
                WHEN consensus_book_count >= 5 THEN '5'
                WHEN consensus_book_count >= 4 THEN '4'
                ELSE '3'
            END AS book_tier,
            CASE
                WHEN bovada_price <= -150 THEN 'heavy_fav'
                WHEN bovada_price <= -101 THEN 'fav'
                WHEN bovada_price < 0     THEN 'slight_fav'
                ELSE 'dog'
            END AS price_tier,
            COUNT(*) AS n,
            ROUND(AVG({bev})*100,1) AS avg_bev_pct,
            SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) AS losses,
            ROUND(100.0 * SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END)
                / NULLIF(SUM(CASE WHEN result IN ('WIN','LOSS') THEN 1 ELSE 0 END),0), 1) AS win_pct,
            ROUND(SUM(profit_units),2) AS net_units,
            ROUND(100.0 * SUM(profit_units)
                / NULLIF(SUM(CASE WHEN result IN ('WIN','LOSS','PUSH') THEN 1 ELSE 0 END),0), 1) AS roi_pct
        FROM backtest_picks
        WHERE result IN ('WIN','LOSS','PUSH')
        GROUP BY market_key, selection, edge_bucket, book_tier, price_tier
        HAVING n >= {min_n}
          AND roi_pct > 0
        ORDER BY roi_pct DESC
        LIMIT 30
    """).fetchall()

    print("  Top 30 profitable compound segments (ROI% > 0, min picks threshold):\n")
    cols = [
        ("MARKET", 22, ""),
        ("SEL", 6, ""),
        ("EDGE", 5, ""),
        ("BKS", 4, ""),
        ("PRC_TIER", 10, ""),
        ("N", 5, ".0f"),
        ("BEV%", 6, ".1f"),
        ("W", 5, ".0f"),
        ("L", 5, ".0f"),
        ("WIN%", 6, ".1f"),
        ("NET_U", 8, ".2f"),
        ("ROI%", 7, ".1f"),
    ]
    print_table([[r[0],r[1],r[2],r[3],r[4],r[5],r[6],r[7],r[8],r[9],r[10],r[11]] for r in rows], cols, min_n)

    print("\n  WORST 10 losing compound segments:\n")
    worst = conn.execute(f"""
        SELECT
            market_key,
            selection,
            CASE
                WHEN edge < 0.02 THEN '<2%'
                WHEN edge < 0.04 THEN '2-4%'
                WHEN edge < 0.06 THEN '4-6%'
                ELSE '6%+'
            END AS edge_bucket,
            CASE
                WHEN consensus_book_count >= 6 THEN '6+'
                WHEN consensus_book_count >= 5 THEN '5'
                WHEN consensus_book_count >= 4 THEN '4'
                ELSE '3'
            END AS book_tier,
            CASE
                WHEN bovada_price <= -150 THEN 'heavy_fav'
                WHEN bovada_price <= -101 THEN 'fav'
                WHEN bovada_price < 0     THEN 'slight_fav'
                ELSE 'dog'
            END AS price_tier,
            COUNT(*) AS n,
            ROUND(AVG({bev})*100,1) AS avg_bev_pct,
            SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) AS losses,
            ROUND(100.0 * SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END)
                / NULLIF(SUM(CASE WHEN result IN ('WIN','LOSS') THEN 1 ELSE 0 END),0), 1) AS win_pct,
            ROUND(SUM(profit_units),2) AS net_units,
            ROUND(100.0 * SUM(profit_units)
                / NULLIF(SUM(CASE WHEN result IN ('WIN','LOSS','PUSH') THEN 1 ELSE 0 END),0), 1) AS roi_pct
        FROM backtest_picks
        WHERE result IN ('WIN','LOSS','PUSH')
        GROUP BY market_key, selection, edge_bucket, book_tier, price_tier
        HAVING n >= {min_n}
        ORDER BY roi_pct ASC
        LIMIT 10
    """).fetchall()
    print_table([[r[0],r[1],r[2],r[3],r[4],r[5],r[6],r[7],r[8],r[9],r[10],r[11]] for r in worst], cols, min_n)


def section_bev_bug(conn: sqlite3.Connection) -> None:
    """Show the calibration bug: avg-price BEV vs per-pick BEV comparison."""
    header("CALIBRATION BUG CHECK — avg-price BEV vs correct per-pick BEV")
    bev = bev_expr()
    rows = conn.execute(f"""
        SELECT
            market_key,
            selection,
            COUNT(*) AS n,
            ROUND(AVG(bovada_price),0) AS avg_price,
            ROUND(AVG({bev})*100,2) AS per_pick_bev_pct,
            -- what market_learn.py computes (wrong):
            ROUND(
                CASE WHEN ROUND(AVG(bovada_price)) > 0
                     THEN 100.0 / (ROUND(AVG(bovada_price)) + 100)
                     ELSE ABS(ROUND(AVG(bovada_price))) * 1.0 / (ABS(ROUND(AVG(bovada_price))) + 100)
                END * 100, 2
            ) AS avg_price_bev_pct,
            ROUND(100.0 * SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END)
                / NULLIF(SUM(CASE WHEN result IN ('WIN','LOSS') THEN 1 ELSE 0 END),0), 2) AS win_pct,
            ROUND(SUM(profit_units),2) AS net_units
        FROM backtest_picks
        WHERE result IN ('WIN','LOSS','PUSH')
        GROUP BY market_key, selection
        HAVING n >= 20
        ORDER BY ABS(per_pick_bev_pct - avg_price_bev_pct) DESC
    """).fetchall()

    cols = [
        ("MARKET", 22, ""),
        ("SEL", 6, ""),
        ("N", 5, ".0f"),
        ("AVG_PRC", 7, ".0f"),
        ("PER_PICK_BEV%", 13, ".2f"),
        ("AVG_PRC_BEV%", 12, ".2f"),
        ("WIN%", 7, ".2f"),
        ("NET_U", 8, ".2f"),
    ]
    print_table([[r[0],r[1],r[2],r[3],r[4],r[5],r[6],r[7]] for r in rows], cols)
    print("\n  PER_PICK_BEV% is correct. AVG_PRC_BEV% is what market_learn.py stores.")
    print("  Large differences = miscategorized as profitable/unprofitable in the JSON.\n")


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="MLB V2 Market Research")
    parser.add_argument("--section", choices=SECTION_NAMES + ["bug"], default=None,
                        help="Run only this section (default: all)")
    parser.add_argument("--min-picks", type=int, default=DEFAULT_MIN_PICKS,
                        help=f"Minimum picks per segment (default: {DEFAULT_MIN_PICKS})")
    args = parser.parse_args()

    if not BACKTEST_DB.exists():
        print(f"ERROR: backtest.db not found at {BACKTEST_DB}")
        print("Run 'python backtest.py --report-only' first to confirm the path.")
        return

    conn = sqlite3.connect(BACKTEST_DB)
    conn.row_factory = sqlite3.Row

    total = conn.execute(
        "SELECT COUNT(*) FROM backtest_picks WHERE result IN ('WIN','LOSS','PUSH')"
    ).fetchone()[0]
    dates = conn.execute(
        "SELECT MIN(pick_date), MAX(pick_date) FROM backtest_picks WHERE result != 'PENDING'"
    ).fetchone()

    print(f"\n  MLB V2 Research — backtest.db")
    print(f"  Graded picks: {total:,}   |   Date range: {dates[0]} to {dates[1]}")
    print(f"  Min segment size: {args.min_picks}")

    s = args.section
    run_all = s is None

    if run_all or s == "bug":
        section_bev_bug(conn)
    if run_all or s == "overview":
        section_overview(conn)
    if run_all or s == "edge":
        section_edge(conn, args.min_picks)
    if run_all or s == "price":
        section_price(conn, args.min_picks)
    if run_all or s == "market":
        section_market(conn, args.min_picks)
    if run_all or s == "books":
        section_books(conn, args.min_picks)
    if run_all or s == "lines":
        section_lines(conn, args.min_picks)
    if run_all or s == "compound":
        section_compound(conn, args.min_picks)

    conn.close()
    print("\n  Done.\n")


if __name__ == "__main__":
    main()
