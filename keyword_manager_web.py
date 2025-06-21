from flask import Flask, render_template, request, send_file
import sqlite3
import pandas as pd
from datetime import datetime
import pytz
import os

app = Flask(__name__)

DB_FILE = "keyword_manager.db"

# KST 타임존
tz = pytz.timezone("Asia/Seoul")

@app.route("/", methods=["GET", "POST"])
def index():
    keyword = ""
    log = []
    selected_channel = request.form.get("selected_channel", "")
    selected_pc = request.form.get("selected_pc", "")

    memo_list = load_memo_list()

    if request.method == "POST":
        action = request.form.get("action")
        keyword = request.form.get("keyword", "").strip()
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

    channels = ["지마켓", "쿠팡", "지그재그", "도매꾹", "에이블리", "4910"]
    pcs = ["Lenovo", "HP", "Razer"]

    return render_template("index.html",
                           keyword=keyword,
                           log=log,
                           memo_list=memo_list,
                           channels=channels,
                           pcs=pcs,
                           selected_channel=selected_channel,
                           selected_pc=selected_pc)

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

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM history WHERE keyword=? AND channel=?
    """, (keyword, channel))
    duplicate = cur.fetchone()

    if duplicate:
        logs.append(f"⚠️ 이미 기록됨")
    else:
        now = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("""
            INSERT INTO history (keyword, channel, pc, created_at) VALUES (?, ?, ?, ?)
        """, (keyword, channel, pc, now))
        conn.commit()
        logs.append(f"✅ 기록 완료: {keyword} - {channel} - {pc}")

    conn.close()
    export_history_csv()
    return logs

def check_history(keyword):
    logs = []
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM history", conn)
    conn.close()

    if keyword:
        df = df[df['keyword'] == keyword]

    if not df.empty:
        logs.append(f"🔍 이력 {len(df)}건:")
        for _, row in df.iterrows():
            logs.append(f"  📌 {row['keyword']} | {row['channel']} | {row['pc']} | {row['created_at']}")
    else:
        logs.append("ℹ️ 이력이 없습니다.")
    return logs

def export_history_csv():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM history", conn)
    conn.close()
    df.to_csv("history.csv", index=False)

def load_memo_list():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT keyword FROM memos")
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

@app.route("/download")
def download_history():
    if os.path.exists("history.csv"):
        return send_file("history.csv", as_attachment=True)
    else:
        return "CSV 파일이 아직 생성되지 않았습니다."

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
