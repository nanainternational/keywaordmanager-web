import sqlite3

conn = sqlite3.connect("keyword_manager.db")
cur = conn.cursor()

# 기록 테이블
cur.execute("""
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT,
    channel TEXT,
    created_at TEXT
)
""")

# 메모 테이블
cur.execute("""
CREATE TABLE IF NOT EXISTS memos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT UNIQUE
)
""")

conn.commit()
conn.close()

print("✅ DB 초기화 완료!")
