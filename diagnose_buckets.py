#!/usr/bin/env python3
"""
diagnose_buckets.py — Bucket-level performance and classification diagnostic.

Reads ONLY from stored DB data (mlb_v2.db). No API calls.

Usage:
    python diagnose_buckets.py
    python diagnose_buckets.py --market batter_total_bases pitcher_strikeouts
"""
import argparse
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from config import (
    BET_WHITELIST, BET_PRICE_MIN, BET_PRICE_MAX,
    MARKET_EDGE_MIN, MARKET_EXCLUDE_PLUS_ODDS,
    EDGE_LEAN, EDGE_RECOMMENDED, EDGE_MIN_BET,
    SCORE_LEAN, SCORE_RECOMMENDED, SCORE_WATCH,
)
from edge import (
    classify, classify_by_score,
    _reload_cal, _CAL_SKIP, _edge_bucket,
    required_edge_for_price,
)
from market_learn import _edge_bucket as mkt_edge_bucket

DB_PATH = ROOT / "data" / "mlb_v2.db"

FOCUS_MARKETS = [
    "batter_total_bases",
    "batter_hits",
    "pitcher_strikeouts",
    "pitcher_outs",
    "totals",
]


def _bucket5(edge: float) -> str:
    """5-band bucketing that splits the EDGE_LEAN=0.015 zone explicitly."""
    if edge >= 0.06:  return "6%+    "
    if edge >= 0.04:  return "4-6%   "
    if edge >= 0.02:  return "2-4%   "
    if edge >= 0.015: return "1.5-2% "
    return "<1.5%  "


def _blocking_reason(market_key: str, selection: str, edge: float,
                     score, price: int) -> str:
    mkt = (market_key, selection)
    if mkt not in BET_WHITELIST:
        return "whitelist"
    if not (BET_PRICE_MIN <= price <= BET_PRICE_MAX):
        return "price_filter"
    if price >= 100 and mkt in MARKET_EXCLUDE_PLUS_ODDS:
        return "excl_plus_odds"
    min_edge = max(MARKET_EDGE_MIN.get(mkt, 0.0), required_edge_for_price(price))
    if edge < min_edge:
        return "edge_floor"
    bucket = mkt_edge_bucket(edge)
    if (market_key, selection, bucket) in _CAL_SKIP:
        return "cal_ban"
    if score is None:
        return "no_score"
    if score < SCORE_LEAN:
        return f"score_low({score})"
    return "qualifies"


def load_picks(conn: sqlite3.Connection) -> list[dict]:
    rows = [dict(r) for r in conn.execute("""
        SELECT market_key, selection, edge, bovada_price,
               bovada_break_even_prob, consensus_fair_prob,
               recommendation, signal_score, sim_prob,
               result, profit_units, ev
        FROM daily_picks
        WHERE result IN ('WIN','LOSS','PUSH')
    """).fetchall()]
    # also pull graded game picks
    game_rows = [dict(r) for r in conn.execute("""
        SELECT market_key, selection, edge, bovada_price,
               bovada_break_even_prob, consensus_fair_prob,
               recommendation, signal_score,
               NULL as sim_prob,
               result, profit_units,
               NULL as ev
        FROM daily_game_picks
        WHERE result IN ('WIN','LOSS','PUSH')
    """).fetchall()]
    return rows + game_rows


def analyze(picks: list[dict], focus: list[str] | None = None) -> None:
    _reload_cal()

    # Group by (market_key, selection, bucket5)
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for p in picks:
        mkt = p["market_key"]
        if focus and mkt not in focus:
            continue
        key = (mkt, p["selection"], _bucket5(p["edge"] or 0))
        groups[key].append(p)

    # Collect unique (market_key, selection) pairs in order
    seen: list[tuple] = []
    for mkt, sel, _ in groups:
        if (mkt, sel) not in seen:
            seen.append((mkt, sel))

    for mkt, sel in sorted(seen, key=lambda x: (FOCUS_MARKETS.index(x[0]) if x[0] in FOCUS_MARKETS else 99, x[0], x[1])):
        print(f"\n{'='*80}")
        print(f"  {mkt}  {sel}")
        print(f"{'='*80}")
        hdr = (f"  {'BUCKET':<9} {'CNT':>4}  {'W-L-P':>11}  {'WR%':>6}  "
               f"{'BEV%':>6}  {'WR-BEV':>7}  {'NET':>7}  {'ROI':>6}  "
               f"{'A_BET':>5}  {'B_BET':>5}  {'WATCH':>5}  {'PASS':>5}")
        print(hdr)
        print("  " + "-" * 90)

        bucket_order = ["6%+    ", "4-6%   ", "2-4%   ", "1.5-2% ", "<1.5%  "]
        for bucket in bucket_order:
            key = (mkt, sel, bucket)
            if key not in groups:
                continue
            rows = groups[key]
            wins   = sum(1 for r in rows if r["result"] == "WIN")
            losses = sum(1 for r in rows if r["result"] == "LOSS")
            pushes = sum(1 for r in rows if r["result"] == "PUSH")
            decided = wins + losses
            wr   = wins / decided if decided else 0
            net  = sum(r["profit_units"] or 0 for r in rows)
            roi  = net / len(rows) * 100
            bevs = [r["bovada_break_even_prob"] for r in rows if r["bovada_break_even_prob"]]
            avg_bev = sum(bevs) / len(bevs) if bevs else 0

            # current label distribution (as stored)
            lab: dict[str, int] = defaultdict(int)
            for r in rows:
                rec = r["recommendation"] or "PASS"
                # normalize old labels
                rec = {"RECOMMENDED": "A_BET", "LEAN": "B_BET",
                       "NO_BET": "PASS"}.get(rec, rec)
                lab[rec] += 1

            wlp  = f"{wins}-{losses}-{pushes}"
            wr_s = f"{wr*100:.1f}%"
            bev_s = f"{avg_bev*100:.1f}%"
            diff  = f"{(wr-avg_bev)*100:+.1f}%"
            net_s = f"{net:+.2f}"
            roi_s = f"{roi:+.1f}%"

            print(f"  {bucket:<9} {len(rows):>4}  {wlp:>11}  {wr_s:>6}  "
                  f"{bev_s:>6}  {diff:>7}  {net_s:>7}  {roi_s:>6}  "
                  f"{lab['A_BET']:>5}  {lab['B_BET']:>5}  "
                  f"{lab['WATCH']:>5}  {lab['PASS']:>5}")

        # Blocking reason breakdown for 2%+ edge picks not currently A/B_BET
        cand = [p for p in groups.get((mkt, sel, "2-4%   "), [])
                + groups.get((mkt, sel, "4-6%   "), [])
                + groups.get((mkt, sel, "6%+    "), [])
                if p["recommendation"] not in ("A_BET", "B_BET", "RECOMMENDED", "LEAN")]
        if cand:
            reason_counts: dict[str, int] = defaultdict(int)
            for p in cand:
                r = _blocking_reason(mkt, sel, p["edge"] or 0,
                                     p["signal_score"], p["bovada_price"])
                reason_counts[r] += 1
            print(f"\n  Blocking reasons for {len(cand)} non-bet picks at 2%+ edge:")
            for reason, cnt in sorted(reason_counts.items(), key=lambda x: -x[1]):
                print(f"    {reason}: {cnt}")

        # Legacy vs current for 2%+ edge picks
        eligible = [p for p in groups.get((mkt, sel, "2-4%   "), [])
                    + groups.get((mkt, sel, "4-6%   "), [])
                    + groups.get((mkt, sel, "6%+    "), [])]
        if eligible:
            legacy_bet = sum(
                1 for p in eligible
                if classify(p["edge"] or 0, p["ev"] or 0,
                            market_key=mkt, selection=sel,
                            price=p["bovada_price"]) in ("RECOMMENDED", "LEAN")
            )
            current_bet = sum(
                1 for p in eligible
                if p["recommendation"] in ("A_BET", "B_BET", "RECOMMENDED", "LEAN")
            )
            print(f"\n  2%+ edge picks ({len(eligible)} total):")
            print(f"    Legacy  (edge-only classify):    {legacy_bet:>4} bet  "
                  f"({legacy_bet/len(eligible)*100:.0f}%)")
            print(f"    Current (balanced classify_by_score): {current_bet:>4} bet  "
                  f"({current_bet/len(eligible)*100:.0f}%)")

        # Price band breakdown (follow-up item: 13 price_filter blocks on BTB Under)
        if mkt == "batter_total_bases" and sel == "Under":
            btb_picks = [p for p in picks
                         if p["market_key"] == mkt and p["selection"] == sel
                         and p["result"] in ("WIN", "LOSS", "PUSH")]
            if btb_picks:
                bands = [
                    ("-140 to -121", lambda p: -140 <= p["bovada_price"] <= -121),
                    ("-120 to -101", lambda p: -120 <= p["bovada_price"] <= -101),
                    ("-100 to -80",  lambda p: -100 <= p["bovada_price"] <= -80),
                    ("+100 to +150", lambda p: 100  <= p["bovada_price"] <= 150),
                    ("out of range", lambda p: not (-140 <= p["bovada_price"] <= 150)),
                ]
                print(f"\n  BTB Under — price band breakdown (all graded):")
                print(f"    {'BAND':<18} {'CNT':>4}  {'W-L':>9}  {'WR%':>6}  {'NET':>7}  {'ROI':>6}")
                print("    " + "-" * 56)
                for label, pred in bands:
                    band = [p for p in btb_picks if pred(p)]
                    if not band:
                        continue
                    w = sum(1 for p in band if p["result"] == "WIN")
                    l = sum(1 for p in band if p["result"] == "LOSS")
                    wr = w / (w + l) if (w + l) else 0
                    net = sum(p["profit_units"] or 0 for p in band)
                    roi = net / len(band) * 100
                    print(f"    {label:<18} {len(band):>4}  {w}-{l:>3}  "
                          f"  {wr*100:>5.1f}%  {net:>+7.2f}  {roi:>+6.1f}%")


def main() -> None:
    parser = argparse.ArgumentParser(description="Bucket diagnostic — no API calls")
    parser.add_argument("--market", nargs="*", default=None,
                        help="Filter to specific market keys")
    args = parser.parse_args()

    focus = args.market or FOCUS_MARKETS

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    picks = load_picks(conn)
    conn.close()

    graded = [p for p in picks if p["result"] in ("WIN", "LOSS", "PUSH")]
    print(f"\nDiagnostic source: {DB_PATH}")
    print(f"Total graded picks loaded: {len(graded)}")
    print(f"Markets in scope: {focus}")
    print(f"Current thresholds: EDGE_LEAN={EDGE_LEAN}, SCORE_LEAN={SCORE_LEAN}, "
          f"CAL_SKIP={len(_CAL_SKIP)} buckets")

    analyze(graded, focus)
    print()


if __name__ == "__main__":
    main()
