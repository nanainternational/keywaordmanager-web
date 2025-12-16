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

# ✅ Render Disk(영구) 사용: 환경변수 DB_FILE 우선, 없으면 /var/data, 그마저 없으면 로컬
DEFAULT_DB_PATH = "/var/data/keyword_manager.db"
DB_FILE = os.environ.get("DB_FILE", DEFAULT_DB_PATH)

# ✅ 환율 캐시 저장소
cached_rate = {
    "value": None,
    "fetched_date": None
}

def ensure_db_dir():
    try:
        db_dir = os.path.dirname(DB_FILE)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
    except Exception as e:
        print("⚠️ DB dir create failed:", e)

def init_db():
    ensure_db_dir()
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

    conn.commit()
    conn.close()

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
                print(f"✅ [{refresh_time_key}] CNY 원본: {base_rate} → 조정 환율: {adjusted}")
                return adjusted

        print("❌ 중국 환율을 찾을 수 없습니다.")
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

@app.route("/api/rate")
def api_rate():
    return jsonify({"rate": get_adjusted_exchange_rate()})

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

    fields = []
    vals = []

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

    if not fields:
        conn.close()
        return jsonify({"ok": True})

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
    get_adjusted_exchange_rate()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
