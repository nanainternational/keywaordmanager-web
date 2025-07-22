import sqlite3

conn = sqlite3.connect("keyword_manager.db")
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS history (
    keyword TEXT, channel TEXT, pc TEXT, created_at TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS memos (
    keyword TEXT UNIQUE
)
""")

conn.commit()
conn.close()

print("✅ DB 초기화 완료")
