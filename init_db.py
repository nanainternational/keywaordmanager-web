import sqlite3

conn = sqlite3.connect("keyword_manager.db")
cur = conn.cursor()

# ✅ history 테이블 (PC 컬럼 포함)
cur.execute("""
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT,
    channel TEXT,
    pc TEXT,
    created_at TEXT
)
""")

# ✅ memos 테이블import sqlite3

conn = sqlite3.connect("keyword_manager.db")
cur = conn.cursor()

# ✅ history 테이블 (PC 포함)
cur.execute("""
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT,
    channel TEXT,
    pc TEXT,
    created_at TEXT
)
""")

# ✅ memos 테이블
cur.execute("""
CREATE TABLE IF NOT EXISTS memos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT UNIQUE
)
""")

conn.commit()
conn.close()

print("✅ DB 구조 확인 완료 (데이터 유지)")

cur.execute("""
CREATE TABLE IF NOT EXISTS memos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT UNIQUE
)
""")

conn.commit()
conn.close()

print("✅ DB 구조 확인 완료 (데이터 유지)")
