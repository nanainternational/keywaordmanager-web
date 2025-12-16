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

# ✅ 환율 캐시
cached_rate = {"value": None, "fetched_date": None}

def _is_writable_dir(path: str) -> bool:
    try:
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
        test_file = os.path.join(path, ".writetest")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(test_file)
        return True
    except Exception as e:
        print(f"⚠️ Dir not writable: {path} ({e})")
        return False

def get_db_file():
    # 1) env 우선
    env_db = os.environ.get("DB_FILE")
    if env_db:
        db_dir = os.path.dirname(env_db) or "."
        if _is_writable_dir(db_dir):
            return env_db
        print("⚠️ DB_FILE 경로에 쓸 수 없습니다. fallback 합니다.")

    # 2) Render Disk 기본 경로 시도
    render_dir = "/var/data"
    if _is_writable_dir(render_dir):
        return os.path.join(render_dir, "keyword_manager.db")

    # 3) 최후 fallback (영구 아님)
    local_dir = os.path.join(os.getcwd(), "data")
    if _is_writable_dir(local_dir):
        print("⚠️ Render Disk 미설정/권한 문제로 로컬 data/ 로 fallback (배포 시 초기화될 수 있음)")
        return os.path.join(local_dir, "keyword_manager.db")

    # 4) 진짜 최후
    print("❌ DB 저장 경로를 만들 수 없습니다. 현재 폴더에 생성 시도합니다.")
    return "keyword_manager.db"

DB_FILE = get_db_file()

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    # ✅ 메모
    cur.execute("CREATE TABLE IF NOT EXISTS memos (keyword TEXT UNIQUE)")

    # ✅ 캘린더 이벤트
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

    # ✅ 채팅 메시지
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
    print(f"✅ DB OK: {DB_FILE}")

@app.route("/health")
def health():
    return "ok", 200

def get_adjusted_exchange_rate():
    now = datetime.now(tz)

    REFRESH_HOUR = 9
    REFRESH_MINUTE = 5
    refresh_time_key = now.strftime(f"%Y-%m-%d-{REFRESH_HOUR:02d}-{REFRESH_MINUTE:02d}")

    if cached_rate["value"] and cached_rate["fetched_date"] == refresh_time_key:
        return cached_rate["value"]

    if (now.hour < REFRESH_HOUR) or (now.hour == REFRESH_HOUR and now.minute < REFRESH_MINUTE):
        if cached_rate["value"]:
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
                base_rate = float(value.text.strip().replace(",", ""))
                adjusted = round((base_rate + 2) * 1.1, 2)
                cached_rate["value"] = adjusted
                cached_rate["fetched_date"] = refresh_time_key
                return adjusted

        return cached_rate["value"]

    except Exception as e:
        print("❌ 환율 파싱 실패:", e)
        return cached_rate["value"]

@app.route("/", methods=["GET", "POST"])
def index():
    init_db()
    memo_list = load_memo_list()

    if request.method == "POST":
        action = request.form.get("action")
        memo_keyword = request.form.get("memo_keyword", "").strip()

        if action == "add_memo":
            add_memo(memo_keyword)
        elif action == "delete_memo":
            delete_memo(memo_keyword)

        memo_list = load_memo_list()

    return render_template(
        "index.html",
        memo_list=memo_list,
        exchange_rate=get_adjusted_exchange_rate()
    )

# -------------------
# 캘린더 API
# -------------------
@app.route("/api/events", methods=["GET"])
def api_get_events():
    init_db()
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT id, title, start, end, all_day, memo FROM events ORDER BY id DESC")
    rows = cur.fetchall()
    conn.close()

    events = []
    for r in rows:
        events.append({
            "id": r[0],
            "title": r[1],
            "start": r[2],
            "end": r[3],
            "allDay": bool(r[4]),
            "extendedProps": {"memo": r[5] or ""}
        })
    return jsonify(events)

@app.route("/api/events", methods=["POST"])
def api_create_event():
    init_db()
    data = request.get_json(force=True)

    title = (data.get("title") or "").strip()
    start = (data.get("start") or "").strip()
    end = (data.get("end") or "").strip() if data.get("end") else None
    all_day = 1 if data.get("allDay") else 0
    memo = (data.get("memo") or "").strip()

    if not title or not start:
        return jsonify({"ok": False, "error": "title/start required"}), 400

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO events (title, start, end, all_day, memo, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (title, start, end, all_day, memo, datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S"))
    )
    conn.commit()
    event_id = cur.lastrowid
    conn.close()

    return jsonify({"ok": True, "id": event_id})

@app.route("/api/events/<int:event_id>", methods=["PUT"])
def api_update_event(event_id):
    init_db()
    data = request.get_json(force=True)

    title = data.get("title")
    start = data.get("start")
    end = data.get("end")
    all_day = 1 if data.get("allDay") else 0 if data.get("allDay") is not None else None
    memo = data.get("memo")

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("SELECT id FROM events WHERE id=?", (event_id,))
    if not cur.fetchone():
        conn.close()
        return jsonify({"ok": False, "error": "not found"}), 404

    fields, vals = [], []

    if title is not None:
        fields.append("title=?")
        vals.append((title or "").strip())
    if start is not None:
        fields.append("start=?")
        vals.append((start or "").strip())
    if end is not None:
        fields.append("end=?")
        vals.append((end or "").strip() if end else None)
    if all_day is not None:
        fields.append("all_day=?")
        vals.append(all_day)
    if memo is not None:
        fields.append("memo=?")
        vals.append((memo or "").strip())

    if fields:
        vals.append(event_id)
        sql = f"UPDATE events SET {', '.join(fields)} WHERE id=?"
        cur.execute(sql, tuple(vals))
        conn.commit()

    conn.close()
    return jsonify({"ok": True})

@app.route("/api/events/<int:event_id>", methods=["DELETE"])
def api_delete_event(event_id):
    init_db()
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("DELETE FROM events WHERE id=?", (event_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

# -------------------
# 채팅 API
# -------------------
@app.route("/api/chat/messages", methods=["GET"])
def api_chat_messages():
    init_db()
    room = (request.args.get("room") or "main").strip() or "main"
    after_id = request.args.get("after_id", "0")
    try:
        after_id = int(after_id)
    except Exception:
        after_id = 0

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, sender, message, created_at
        FROM chat_messages
        WHERE room=? AND id>?
        ORDER BY id ASC
        LIMIT 200
    """, (room, after_id))
    rows = cur.fetchall()
    conn.close()

    msgs = []
    for r in rows:
        msgs.append({
            "id": r[0],
            "sender": r[1] or "익명",
            "message": r[2],
            "created_at": r[3] or ""
        })
    return jsonify({"ok": True, "messages": msgs})

@app.route("/api/chat/send", methods=["POST"])
def api_chat_send():
    init_db()
    data = request.get_json(force=True)

    room = ((data.get("room") or "main").strip() or "main")
    sender = (data.get("sender") or "").strip()
    message = (data.get("message") or "").strip()

    if not message:
        return jsonify({"ok": False, "error": "empty"}), 400

    if not sender:
        sender = "익명"

    now_str = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO chat_messages (room, sender, message, created_at) VALUES (?, ?, ?, ?)",
        (room, sender, message, now_str)
    )
    conn.commit()
    msg_id = cur.lastrowid
    conn.close()

    return jsonify({"ok": True, "id": msg_id})

# -------------------
# Memo helpers
# -------------------
def load_memo_list():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT keyword FROM memos ORDER BY keyword ASC")
    memos = [row[0] for row in cur.fetchall()]
    conn.close()
    return memos

def add_memo(keyword):
    if keyword:
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO memos (keyword) VALUES (?)", (keyword,))
        conn.commit()
        conn.close()

def delete_memo(keyword):
    if keyword:
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("DELETE FROM memos WHERE keyword=?", (keyword,))
        conn.commit()
        conn.close()

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
