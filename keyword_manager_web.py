from flask import Flask, render_template, request, jsonify
import sqlite3
from datetime import datetime
import pytz
import os
import requests
from bs4 import BeautifulSoup
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

tz = pytz.timezone("Asia/Seoul")

def _safe_mkdir(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        testfile = os.path.join(path, ".write_test")
        with open(testfile, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(testfile)
        return True
    except Exception as e:
        print(f"⚠️ Dir not writable: {path} ({e})")
        return False

# ===============================
# ✅ DB 경로 결정 (핵심)
# 1) DB_FILE 환경변수 있으면 그걸 사용
# 2) 없으면 DISK_PATH/keyword_manager.db
# 3) 실패하면 ./data/keyword_manager.db
# ===============================
_env_db_file = (os.environ.get("DB_FILE") or "").strip()
_env_disk_path = (os.environ.get("DISK_PATH") or "").strip()

if _env_db_file:
    DB_FILE = _env_db_file
else:
    if not _env_disk_path:
        _env_disk_path = "data"
    DB_FILE = os.path.join(_env_disk_path, "keyword_manager.db")

# DB_FILE의 디렉토리가 writable 아니면 fallback
_db_dir = os.path.dirname(DB_FILE) or "."
if not _safe_mkdir(_db_dir):
    fallback_dir = "data"
    _safe_mkdir(fallback_dir)
    DB_FILE = os.path.join(fallback_dir, "keyword_manager.db")

print("✅ DB_FILE:", DB_FILE)

# ===============================
# ✅ DB 초기화
# ===============================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS memos (
            keyword TEXT UNIQUE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            start TEXT NOT NULL,
            end TEXT,
            all_day INTEGER DEFAULT 0,
            memo TEXT,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room TEXT DEFAULT 'main',
            sender TEXT,
            message TEXT NOT NULL,
            created_at TEXT
        )
    """)

    conn.commit()
    conn.close()

# ===============================
# ✅ 환율 (캐시)
# ===============================
cached_rate = {"value": None, "fetched_date": None}

def get_adjusted_exchange_rate():
    now = datetime.now(tz)
    REFRESH_HOUR = 9
    REFRESH_MINUTE = 5
    refresh_key = now.strftime(f"%Y-%m-%d-{REFRESH_HOUR:02d}-{REFRESH_MINUTE:02d}")

    if cached_rate["value"] and cached_rate["fetched_date"] == refresh_key:
        return cached_rate["value"]

    try:
        url = "https://www.citibank.co.kr/FxdExrt0100.act"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, "html.parser")

        for li in soup.select("ul.exchangeList > li"):
            label = li.select_one("span.flagCn")
            value = li.select_one("span.green")
            if label and "중국" in label.text and value:
                base = float(value.text.strip().replace(",", ""))
                adjusted = round((base + 2) * 1.1, 2)
                cached_rate["value"] = adjusted
                cached_rate["fetched_date"] = refresh_key
                return adjusted
    except Exception as e:
        print("환율 오류:", e)

    return cached_rate["value"]

# ===============================
# ✅ Health (UptimeRobot)
# ===============================
@app.route("/health", methods=["GET", "HEAD"])
def health():
    return ("", 200)

# ===============================
# ✅ 메인
# ===============================
@app.route("/", methods=["GET", "POST", "HEAD"])
def index():
    init_db()

    if request.method == "POST":
        action = request.form.get("action")
        memo_keyword = request.form.get("memo_keyword", "").strip()

        if action == "add_memo" and memo_keyword:
            conn = sqlite3.connect(DB_FILE)
            cur = conn.cursor()
            cur.execute("INSERT OR IGNORE INTO memos (keyword) VALUES (?)", (memo_keyword,))
            conn.commit()
            conn.close()

        if action == "delete_memo" and memo_keyword:
            conn = sqlite3.connect(DB_FILE)
            cur = conn.cursor()
            cur.execute("DELETE FROM memos WHERE keyword=?", (memo_keyword,))
            conn.commit()
            conn.close()

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT keyword FROM memos ORDER BY keyword")
    memo_list = [r[0] for r in cur.fetchall()]
    conn.close()

    return render_template(
        "index.html",
        memo_list=memo_list,
        exchange_rate=get_adjusted_exchange_rate()
    )

# ===============================
# ✅ 캘린더 API
# ===============================
@app.route("/api/events", methods=["GET"])
def get_events():
    init_db()
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT id, title, start, end, all_day, memo FROM events")
    rows = cur.fetchall()
    conn.close()

    return jsonify([
        {
            "id": r[0],
            "title": r[1],
            "start": r[2],
            "end": r[3],
            "allDay": bool(r[4]),
            "extendedProps": {"memo": r[5] or ""}
        } for r in rows
    ])

@app.route("/api/events", methods=["POST"])
def add_event():
    init_db()
    data = request.get_json() or {}

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO events (title, start, end, all_day, memo, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        data.get("title", ""),
        data.get("start", ""),
        data.get("end"),
        1 if data.get("allDay") else 0,
        data.get("memo", ""),
        datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    ))
    conn.commit()
    event_id = cur.lastrowid
    conn.close()

    return jsonify({"ok": True, "id": event_id})

@app.route("/api/events/<int:event_id>", methods=["PUT"])
def update_event(event_id):
    init_db()
    data = request.get_json() or {}

    fields = []
    values = []

    for key, col in [("title","title"), ("start","start"), ("end","end"), ("memo","memo")]:
        if key in data:
            fields.append(f"{col}=?")
            values.append(data[key])

    if "allDay" in data:
        fields.append("all_day=?")
        values.append(1 if data["allDay"] else 0)

    if not fields:
        return jsonify({"ok": True})

    values.append(event_id)

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(f"UPDATE events SET {', '.join(fields)} WHERE id=?", values)
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/events/<int:event_id>", methods=["DELETE"])
def delete_event(event_id):
    init_db()
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("DELETE FROM events WHERE id=?", (event_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

# ===============================
# ✅ 채팅 API
# ===============================
@app.route("/api/chat/messages", methods=["GET"])
def chat_messages():
    init_db()
    after_id = int(request.args.get("after_id", 0))

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, sender, message, created_at
        FROM chat_messages
        WHERE id > ?
        ORDER BY id ASC
    """, (after_id,))
    rows = cur.fetchall()
    conn.close()

    return jsonify({
        "ok": True,
        "messages": [
            {"id": r[0], "sender": r[1], "message": r[2], "created_at": r[3]}
            for r in rows
        ]
    })

@app.route("/api/chat/send", methods=["POST"])
def send_chat():
    init_db()
    data = request.get_json() or {}

    sender = (data.get("sender") or "익명").strip()
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"ok": False, "error": "empty_message"}), 400

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO chat_messages (room, sender, message, created_at)
        VALUES (?, ?, ?, ?)
    """, (
        "main",
        sender,
        message,
        datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    ))
    conn.commit()
    msg_id = cur.lastrowid
    conn.close()

    return jsonify({"ok": True, "id": msg_id})

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
