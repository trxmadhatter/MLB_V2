import sqlite3
conn = sqlite3.connect('data/mlb_v2.db')
conn.execute("DELETE FROM daily_picks WHERE pick_date='2026-05-14'")
conn.execute("DELETE FROM no_bets_structural WHERE pick_date='2026-05-14'")
conn.commit()
conn.close()
print('cleared')
