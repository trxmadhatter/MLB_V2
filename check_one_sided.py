import sqlite3
conn = sqlite3.connect('data/mlb_v2.db')
conn.row_factory = sqlite3.Row

pulled_at = conn.execute('SELECT pulled_at FROM props_snapshots ORDER BY id DESC LIMIT 1').fetchone()['pulled_at']
print(f"Snapshot: {pulled_at}\n")

# Check Luzardo specifically
luzardo = conn.execute("""
    SELECT bookmaker_key, market_key, selection, point, price
    FROM props_snapshots WHERE pulled_at=? AND lower(player_name) LIKE '%luzardo%'
    ORDER BY market_key, point, bookmaker_key
""", (pulled_at,)).fetchall()
print("=== Luzardo lines ===")
for r in luzardo:
    print(f"  {r['bookmaker_key']:<18} {r['market_key']:<25} {r['selection']:<6} {r['point']:>5.1f}  {r['price']:>+6}")

# One-sided Bovada lines
rows = conn.execute("""
    SELECT b.player_name, b.market_key, b.selection, b.point, b.price,
           COUNT(DISTINCT nb.bookmaker_key) AS other_books
    FROM props_snapshots b
    LEFT JOIN props_snapshots nb
        ON  nb.pulled_at     = b.pulled_at
        AND nb.event_id      = b.event_id
        AND nb.market_key    = b.market_key
        AND nb.player_name   = b.player_name
        AND nb.point         = b.point
        AND nb.bookmaker_key != b.bookmaker_key
    WHERE b.pulled_at = ? AND b.bookmaker_key = 'bovada'
    GROUP BY b.event_id, b.market_key, b.player_name, b.point
    HAVING COUNT(DISTINCT b.selection) = 1
    ORDER BY other_books DESC, b.market_key, b.player_name
""", (pulled_at,)).fetchall()
print(f"\n=== One-sided Bovada lines ({len(rows)}) ===")
for r in rows:
    print(f"  {r['player_name']:<22} {r['market_key']:<25} {r['selection']:<6} {r['point']:>4.1f}  {r['price']:>+6}  other_books={r['other_books']}")

conn.close()
