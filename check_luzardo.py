import sqlite3
conn = sqlite3.connect('data/mlb_v2.db')
conn.row_factory = sqlite3.Row

pulled_at = conn.execute('SELECT pulled_at FROM props_snapshots ORDER BY id DESC LIMIT 1').fetchone()['pulled_at']
print(f"Snapshot: {pulled_at}\n")

rows = conn.execute("""
    SELECT bookmaker_key, market_key, selection, point, price
    FROM props_snapshots
    WHERE pulled_at=? AND lower(player_name) LIKE lower('%luzardo%')
    ORDER BY market_key, point, bookmaker_key
""", (pulled_at,)).fetchall()

if rows:
    for r in rows:
        print(f"  {r['bookmaker_key']:<18} {r['market_key']:<25} {r['selection']:<6} {r['point']:>5.1f}  {r['price']:>+6}")
else:
    print("  No Luzardo lines found in snapshot")

conn.close()
