import sqlite3
from collections import defaultdict, Counter

conn = sqlite3.connect('data/mlb_v2.db')
conn.row_factory = sqlite3.Row

pulled_at = conn.execute(
    "SELECT pulled_at FROM props_snapshots ORDER BY id DESC LIMIT 1"
).fetchone()["pulled_at"]
print(f"Snapshot: {pulled_at}")

# 1. Bovada lines pulled per market
bovada = conn.execute("""
    SELECT market_key, COUNT(DISTINCT player_name||point||selection) as lines
    FROM props_snapshots WHERE pulled_at=? AND bookmaker_key='bovada'
    GROUP BY market_key
""", (pulled_at,)).fetchall()
print("\n=== Bovada lines pulled ===")
for r in bovada:
    print(f"  {r['market_key']}: {r['lines']} player/line/side combos")

# 2. All books in snapshot
books = conn.execute("""
    SELECT bookmaker_key, COUNT(*) as rows
    FROM props_snapshots WHERE pulled_at=?
    GROUP BY bookmaker_key ORDER BY rows DESC
""", (pulled_at,)).fetchall()
print("\n=== Books in snapshot ===")
for r in books:
    print(f"  {r['bookmaker_key']}: {r['rows']} rows")

# 3. Bovada line distribution by valid consensus book count
rows = conn.execute(
    "SELECT * FROM props_snapshots WHERE pulled_at=?", (pulled_at,)
).fetchall()
groups = defaultdict(list)
for r in rows:
    key = (r['event_id'], r['market_key'], r['player_name'], r['point'])
    groups[key].append(dict(r))

book_count_dist = Counter()
for grp in groups.values():
    bovada_rows = [r for r in grp if r['bookmaker_key'] == 'bovada']
    if not bovada_rows:
        continue
    book_sides = defaultdict(set)
    for r in grp:
        if r['bookmaker_key'] == 'bovada':
            continue
        book_sides[r['bookmaker_key']].add(r['selection'])
    valid = sum(1 for sides in book_sides.values() if 'Over' in sides and 'Under' in sides)
    book_count_dist[valid] += 1

print("\n=== Bovada lines by valid consensus book count ===")
for k in sorted(book_count_dist):
    note = "  <-- filtered out (need 3+)" if k < 3 else ""
    print(f"  {k} books: {book_count_dist[k]} Bovada lines{note}")

# 4. Edge distribution at min_books=1 (no book filter) to see true picture
from consensus import compute_consensus
from edge import bovada_break_even, compute_edge, compute_ev

edge_by_threshold = {1: Counter(), 2: Counter(), 3: Counter()}
would_be_picks = []

for grp in groups.values():
    bovada_rows = [r for r in grp if r['bookmaker_key'] == 'bovada']
    if not bovada_rows:
        continue
    bov_over  = next((r for r in bovada_rows if r['selection'] == 'Over'),  None)
    bov_under = next((r for r in bovada_rows if r['selection'] == 'Under'), None)
    if not (bov_over and bov_under):
        continue

    for min_b in (1, 2, 3):
        for bov, sel in [(bov_over, 'Over'), (bov_under, 'Under')]:
            c = compute_consensus(grp, min_books=min_b, bovada_keys={'bovada'})
            if not c['ok']:
                continue
            fp = c['fair_prob_over'] if sel == 'Over' else c['fair_prob_under']
            e  = compute_edge(fp, bovada_break_even(bov['price']))
            ev = compute_ev(bov['price'], fp)
            if e >= 0.04:
                edge_by_threshold[min_b]['>=4pct'] += 1
            elif e >= 0.02:
                edge_by_threshold[min_b]['2-4pct'] += 1
            elif e >= 0:
                edge_by_threshold[min_b]['0-2pct'] += 1
            else:
                edge_by_threshold[min_b]['negative'] += 1

            if min_b == 1 and e >= 0.04 and ev > 0:
                would_be_picks.append((
                    bov['player_name'], bov['market_key'], sel,
                    bov['point'], bov['price'], e, ev, c['book_count']
                ))

print("\n=== Edge distribution by min consensus book threshold ===")
for min_b in (1, 2, 3):
    d = edge_by_threshold[min_b]
    print(f"  min_books={min_b}: >=4% {d['>=4pct']}  2-4% {d['2-4pct']}  0-2% {d['0-2pct']}  negative {d['negative']}")

print("\n=== Would-be RECOMMENDED picks at min_books=1 ===")
for p in sorted(would_be_picks, key=lambda x: -x[5])[:15]:
    print(f"  {p[0]} | {p[1]} {p[2]} {p[3]} @ {p[4]} | edge {p[5]:.1%} ev {p[6]:.1%} | {p[7]} books")

conn.close()
