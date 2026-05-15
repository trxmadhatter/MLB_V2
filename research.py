"""
Market segment analysis on existing backtest data.
Slices backtest_picks across edge, book count, line value, price, and
market+direction to find which filters produce positive ROI.

Usage: python research.py
"""
import sqlite3
from pathlib import Path

DB = Path(__file__).parent / "data" / "backtest.db"
MIN_PICKS = 15


def _edge_bucket(edge: float) -> str:
    if edge >= 0.08: return "8%+"
    if edge >= 0.06: return "6-8%"
    if edge >= 0.04: return "4-6%"
    if edge >= 0.02: return "2-4%"
    if edge >= 0.01: return "1-2%"
    return "<1%"


def _price_bucket(price: int) -> str:
    if price >= 100:   return "+100 or better"
    if price >= -105:  return "-105 to -101"
    if price >= -115:  return "-115 to -106"
    if price >= -130:  return "-130 to -116"
    if price >= -150:  return "-150 to -131"
    return "worse than -150"


def _line_bucket(point: float) -> str:
    return str(round(point * 2) / 2)


def _seg(rows: list[sqlite3.Row], label: str, key_fn) -> list[dict]:
    from collections import defaultdict
    buckets: dict = defaultdict(lambda: {"wins": 0, "losses": 0, "pushes": 0,
                                          "profit": 0.0, "bevs": []})
    for r in rows:
        k = key_fn(r)
        b = buckets[k]
        res = r["result"]
        if res == "WIN":
            b["wins"] += 1
        elif res == "LOSS":
            b["losses"] += 1
        elif res == "PUSH":
            b["pushes"] += 1
        else:
            continue
        b["profit"] += r["profit_units"] or 0.0
        b["bevs"].append(r["bovada_fair_prob"] or 0.53)

    results = []
    for k, b in buckets.items():
        decided = b["wins"] + b["losses"]
        if decided < MIN_PICKS:
            continue
        avg_bev = sum(b["bevs"]) / len(b["bevs"]) if b["bevs"] else 0.53
        win_rate = b["wins"] / decided
        results.append({
            "segment":     f"{label}={k}",
            "n":           decided,
            "wins":        b["wins"],
            "losses":      b["losses"],
            "pushes":      b["pushes"],
            "win_rate":    round(win_rate, 4),
            "bev":         round(avg_bev, 4),
            "edge_vs_bev": round(win_rate - avg_bev, 4),
            "net_units":   round(b["profit"], 2),
        })
    results.sort(key=lambda x: x["net_units"], reverse=True)
    return results


def _print_table(title: str, rows: list[dict], min_n: int = MIN_PICKS) -> None:
    rows = [r for r in rows if r["n"] >= min_n]
    print(f"\n{'='*76}")
    print(f"  {title}")
    print(f"{'='*76}")
    if not rows:
        print("  (no segments with enough data)")
        return
    print(f"  {'Segment':<38} {'N':>5} {'W-L':>10} {'WR%':>6} {'BEV%':>6} {'Edge':>7} {'Net':>9}")
    print("  " + "-" * 74)
    for r in rows:
        wl = f"{r['wins']}-{r['losses']}"
        flag = " *" if r["edge_vs_bev"] > 0 else ""
        print(f"  {r['segment']:<38} {r['n']:>5} {wl:>10} "
              f"{r['win_rate']*100:>5.1f}% {r['bev']*100:>5.1f}% "
              f"{r['edge_vs_bev']*100:>+6.1f}% {r['net_units']:>+8.2f}u{flag}")


def main() -> None:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    all_rows = conn.execute("""
        SELECT * FROM backtest_picks WHERE result IN ('WIN','LOSS','PUSH')
    """).fetchall()
    print(f"\nLoaded {len(all_rows)} graded picks  |  DB: {DB}")

    # 1. Edge bucket — does edge predict wins?
    _print_table(
        "1. BY EDGE BUCKET (all markets)",
        _seg(all_rows, "edge", lambda r: _edge_bucket(r["edge"]))
    )

    # 2. Recommendation tier
    _print_table(
        "2. BY RECOMMENDATION TIER",
        _seg(all_rows, "tier", lambda r: r["recommendation"])
    )

    # 3. Book count — more books = more reliable consensus?
    _print_table(
        "3. BY CONSENSUS BOOK COUNT",
        _seg(all_rows, "books", lambda r: str(r["consensus_book_count"]))
    )

    # 4. Price range
    _print_table(
        "4. BY BOVADA PRICE RANGE",
        _seg(all_rows, "price", lambda r: _price_bucket(r["bovada_price"]))
    )

    # 5. Market + direction
    _print_table(
        "5. BY MARKET + DIRECTION",
        _seg(all_rows, "mkt", lambda r: f"{r['market_key']} {r['selection']}")
    )

    # Whitelist only — keep in sync with config.BET_WHITELIST
    from config import BET_WHITELIST
    wl_rows = [r for r in all_rows
               if (r["market_key"], r["selection"]) in BET_WHITELIST]

    # 6. Whitelist by edge bucket
    _print_table(
        "6. WHITELIST — BY EDGE BUCKET",
        _seg(wl_rows, "seg",
             lambda r: f"{r['market_key']} {r['selection']} | {_edge_bucket(r['edge'])}")
    )

    # 7. Whitelist by line value
    _print_table(
        "7. WHITELIST — BY LINE VALUE",
        _seg(wl_rows, "seg",
             lambda r: f"{r['market_key']} {r['selection']} @ {_line_bucket(r['point'])}")
    )

    # 8. Whitelist by book count
    _print_table(
        "8. WHITELIST — BY BOOK COUNT",
        _seg(wl_rows, "seg",
             lambda r: f"{r['market_key']} {r['selection']} | {r['consensus_book_count']}bk")
    )

    # 9. Whitelist by price range
    _print_table(
        "9. WHITELIST — BY PRICE RANGE",
        _seg(wl_rows, "seg",
             lambda r: f"{r['market_key']} {r['selection']} | {_price_bucket(r['bovada_price'])}")
    )

    # 10. Compound: market + edge + books
    _print_table(
        "10. COMPOUND: market + edge + book count",
        _seg(wl_rows, "seg",
             lambda r: (f"{r['market_key'][:8]} {r['selection'][:1]}"
                        f" | {_edge_bucket(r['edge'])} | {r['consensus_book_count']}bk")),
        min_n=20,
    )

    # 11. All market+edge combos, any market
    all_mkt_edge = _seg(
        all_rows, "seg",
        lambda r: f"{r['market_key']} {r['selection']} | {_edge_bucket(r['edge'])}"
    )
    profitable = sorted(
        [s for s in all_mkt_edge if s["net_units"] > 0],
        key=lambda x: x["net_units"], reverse=True
    )
    _print_table("11. ALL PROFITABLE market+edge SEGMENTS (net > 0)", profitable)

    # Summary: best filters
    print(f"\n{'='*76}")
    print("  SUMMARY — positive edge_vs_bev AND n >= 20")
    print(f"{'='*76}")
    candidates = sorted(
        [s for s in all_mkt_edge if s["edge_vs_bev"] > 0 and s["n"] >= 20],
        key=lambda x: x["edge_vs_bev"], reverse=True
    )
    for s in candidates:
        print(f"  {s['segment']:<55}  WR={s['win_rate']*100:.1f}%  net={s['net_units']:+.2f}u  n={s['n']}")

    # ── NEW FILTER VALIDATION ────────────────────────────────────────────────
    # Simulate new whitelist rules on backtest data and compare old vs new
    from config import BET_WHITELIST as _NEW_WL, MARKET_EDGE_MIN as _MEM, MARKET_EXCLUDE_PLUS_ODDS as _MEP

    _OLD_WL = {
        ("pitcher_outs", "Over"),
        ("batter_total_bases", "Under"),
        ("pitcher_hits_allowed", "Under"),
    }

    def new_filter(r) -> bool:
        mkt = (r["market_key"], r["selection"])
        if mkt not in _NEW_WL:
            return False
        edge = r["edge"] or 0.0
        if edge <= 0.0:
            return False
        if edge < _MEM.get(mkt, 0.0):
            return False
        price = r["bovada_price"]
        if price is not None and price >= 100 and mkt in _MEP:
            return False
        return True

    def old_filter(r) -> bool:
        return (r["market_key"], r["selection"]) in _OLD_WL and (r["edge"] or 0) > 0

    # Fixed split date (75/25 of Mar 29–May 14 2026 dataset; hardcoded for reproducibility)
    split_date = "2026-05-04"

    def summarize(rows, label):
        wins = sum(1 for r in rows if r["result"] == "WIN")
        losses = sum(1 for r in rows if r["result"] == "LOSS")
        n = wins + losses
        profit = sum(r["profit_units"] or 0 for r in rows)
        wr = 100 * wins / n if n else 0
        print(f"  {label:<30} n={n:4d}  {wins}W-{losses}L  WR={wr:.1f}%  net={profit:+.2f}u")

    print(f"\n{'='*76}")
    print(f"  NEW FILTER VALIDATION  (train: before {split_date} | held-out: from {split_date})")
    print(f"{'='*76}")
    print("  -- TRAINING SET --")
    train = [r for r in all_rows if r["pick_date"] < split_date]
    summarize([r for r in train if old_filter(r)], "Old whitelist")
    summarize([r for r in train if new_filter(r)], "New whitelist")

    print("  -- HELD-OUT SET --")
    held = [r for r in all_rows if r["pick_date"] >= split_date]
    summarize([r for r in held if old_filter(r)], "Old whitelist")
    summarize([r for r in held if new_filter(r)], "New whitelist")

    print()


if __name__ == "__main__":
    main()
