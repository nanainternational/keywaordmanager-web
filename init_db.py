import sqlite3

conn = sqlite3.connect("keyword_manager.db")
cur = conn.cursor()

# ✅ 이미 있으면 테이블 DROP
cur.execute("DROP TABLE IF EXISTS history")
cur.execute("DROP TABLE IF EXISTS memos")

# ✅ 새로 만들기
cur.execute("""
CREATE TABLE history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT,
    channel TEXT,
    pc TEXT,
    created_at TEXT
)
""")

cur.execute("""
CREATE TABLE memos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT UNIQUE
)
""")

conn.commit()
conn.close()

print("✅ DB 재생성 완료!")
