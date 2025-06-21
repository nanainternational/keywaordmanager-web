from flask import Flask, render_template, request
import sqlite3
from datetime import datetime
import pytz

app = Flask(__name__)

DB_FILE = "keyword_manager.db"

CHANNELS = ["지마켓", "쿠팡", "지그재그", "도매꾹", "에이블리", "4910"]
PCS = ["Lenovo", "HP", "Razer"]

def get_db():
    return sqlite3.connect(DB_FILE)

# === 기록 ===
def record_keyword(keyword, channel, pc):
    logs = []
    if not keyword:
        logs.append("❌ 키워드를 입력하세요.")
        return logs
    if not channel:
        logs.append("❌ 채널을 선택하세요.")
        return logs
    if not pc:
        logs.append("❌ PC를 선택하세요.")
        return logs

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM history WHERE keyword=? AND channel=?", (keyword, channel))
    if cur.fetchone():
        logs.append("⚠️ 이미 기록됨!")
    else:
        # ✅ pytz로 한국시간
        KST = pytz.timezone('Asia/Seoul')
        now = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
        cur.execute(
            "INSERT INTO history (keyword, channel, pc, created_at) VALUES (?, ?, ?, ?)",
            (keyword, channel, pc, now)
        )
        conn.commit()
        logs.append(f"✅ 기록 완료: {keyword} - {channel} - {pc}")

    conn.close()
    return logs

# === 이력 조회 ===
def check_history(keyword):
    logs = []
    if not keyword:
        logs.append("❌ 키워드를 입력하세요.")
        return logs

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT channel, pc, created_at FROM history WHERE keyword=?", (keyword,))
    rows = cur.fetchall()
    if rows:
        logs.append(f"🔍 이력 {len(rows)}건:")
        for r in rows:
            logs.append(f"  📌 {r[0]} | {r[1]} | {r[2]}")
    else:
        logs.append("ℹ️ 이력이 없습니다.")
    conn.close()
    return logs

# === 메모 ===
def load_memo_list():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT keyword FROM memos")
    memos = [row[0] for row in cur.fetchall()]
    conn.close()
    return memos

def add_memo(keyword):
    if keyword:
        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute("INSERT INTO memos (keyword) VALUES (?)", (keyword,))
            conn.commit()
        except sqlite3.IntegrityError:
            pass
        conn.close()

def delete_memo(keyword):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM memos WHERE keyword=?", (keyword,))
    conn.commit()
    conn.close()

# === 기본 페이지 ===
@app.route("/", methods=["GET", "POST"])
def index():
    keyword = ""
    log = []
    memo_list = load_memo_list()

    selected_channel = ""
    selected_pc = ""

    if request.method == "POST":
        action = request.form.get("action")
        keyword = request.form.get("keyword", "").strip()
        selected_channel = request.form.get("selected_channel", "").strip()
        selected_pc = request.form.get("selected_pc", "").strip()
        memo_keyword = request.form.get("memo_keyword", "").strip()

        if action == "record":
            log = record_keyword(keyword, selected_channel, selected_pc)
        elif action == "check":
            log = check_history(keyword)
        elif action == "add_memo":
            add_memo(memo_keyword)
            memo_list = load_memo_list()
            log.append(f"➕ 메모 추가: {memo_keyword}")
        elif action == "delete_memo":
            delete_memo(memo_keyword)
            memo_list = load_memo_list()
            log.append(f"❌ 메모 삭제: {memo_keyword}")

    return render_template("index.html",
                           keyword=keyword,
                           log=log,
                           memo_list=memo_list,
                           channels=CHANNELS,
                           pcs=PCS)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
