from flask import Flask, render_template, request, send_file, jsonify
import sqlite3
import pandas as pd
from datetime import datetime
import pytz
import os
import chardet

app = Flask(__name__)

DB_FILE = "keyword_manager.db"
tz = pytz.timezone("Asia/Seoul")


@app.route("/", methods=["GET", "POST"])
def index():
    keyword = ""
    log = []
    selected_channel = request.form.get("selected_channel", "")
    selected_pc = request.form.get("selected_pc", "")

    memo_list = load_memo_list()
    history_list = load_history_list()

    if request.method == "POST":
        action = request.form.get("action")
        keyword = request.form.get("keyword", "").strip()
        memo_keyword = request.form.get("memo_keyword", "").strip()

        if action == "record":
            log = record_keyword(keyword, selected_channel, selected_pc)
        elif action == "check":
            log = check_history(keyword)
            history_list = load_history_list(keyword)
        elif action == "add_memo":
            add_memo(memo_keyword)
            memo_list = load_memo_list()
        elif action == "delete_memo":
            delete_memo(memo_keyword)
            memo_list = load_memo_list()

    channels = ["지마켓", "쿠팡", "지그재그", "도매꾹", "에이블리", "4910"]
    pcs = ["Lenovo", "HP", "Razer"]

    return render_template("index.html",
                           keyword=keyword,
                           log=log,
                           memo_list=memo_list,
                           history_list=history_list,
                           channels=channels,
                           pcs=pcs,
                           selected_channel=selected_channel,
                           selected_pc=selected_pc)


@app.route("/delete_history", methods=["POST"])
def delete_history():
    history_id = request.json.get("id")
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("DELETE FROM history WHERE id=?", (history_id,))
    conn.commit()
    conn.close()
    export_combined_csv()
    return jsonify({"status": "ok"})


def load_history_list(keyword=None):
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM history ORDER BY id DESC", conn)
    conn.close()
    if keyword:
        df = df[df['keyword'] == keyword]
    return df.to_dict(orient="records")


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
        now = datetime.now(tz).strftime("%Y-%m-%d")
        cur.execute("""
            INSERT INTO history (keyword, channel, pc, created_at) VALUES (?, ?, ?, ?)
        """, (keyword, channel, pc, now))
        conn.commit()
        logs.append(f"✅ 기록 완료: {keyword} - {channel} - {pc}")

    conn.close()
    export_combined_csv()
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
            logs.append(f"📌 {row['keyword']} | {row['channel']} | {row['pc']} | {row['created_at']}")
    else:
        logs.append("ℹ️ 이력이 없습니다.")
    return logs


def export_combined_csv():
    conn = sqlite3.connect(DB_FILE)
    df_history = pd.read_sql_query("SELECT * FROM history", conn)
    df_history.insert(0, "table", "history")

    df_memos = pd.read_sql_query("SELECT keyword FROM memos", conn)
    df_memos["table"] = "memos"
    df_memos["channel"] = None
    df_memos["pc"] = None
    df_memos["created_at"] = None
    df_memos = df_memos[["table", "keyword", "channel", "pc", "created_at"]]

    df_all = pd.concat([df_history, df_memos], ignore_index=True)
    conn.close()

    df_all.to_csv("backup.csv", index=False)


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
        export_combined_csv()


def delete_memo(keyword):
    if keyword:
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("DELETE FROM memos WHERE keyword=?", (keyword,))
        conn.commit()
        conn.close()
        export_combined_csv()


@app.route("/download_all")
def download_all():
    export_combined_csv()
    return send_file("backup.csv", as_attachment=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
