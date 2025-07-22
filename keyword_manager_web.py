from flask import Flask, render_template, request, send_file, jsonify
import sqlite3
import pandas as pd
from datetime import datetime
import pytz
import os
import chardet
import requests

from flask_cors import CORS  # ✅ CORS 추가

app = Flask(__name__)
CORS(app)  # ✅ CORS 활성화 (한 번만 선언)

DB_FILE = "keyword_manager.db"
tz = pytz.timezone("Asia/Seoul")

# ✅ 중국환율 계산 함수
def get_adjusted_exchange_rate():
    try:
        base_rate = 190.15  # 예시 기준 환율
        adjusted_rate = round((base_rate + 2) * 1.1, 2)
        return adjusted_rate
    except Exception:
        return "N/A"


@app.route("/", methods=["GET", "POST"])
def index():
    keyword = ""
    log = []
    selected_channel = request.form.get("selected_channel", "")
    selected_pc = request.form.get("selected_pc", "")

    memo_list = load_memo_list()
    history_list = load_history_list()
    show_history = False

    if request.method == "POST":
        action = request.form.get("action")
        keyword = request.form.get("keyword", "").strip()
        memo_keyword = request.form.get("memo_keyword", "").strip()

        if action == "record":
            log = record_keyword(keyword, selected_channel, selected_pc)
        elif action == "check":
            if keyword.lower() == "all":
                log = []
                show_history = True
            else:
                log = check_history(keyword)
        elif action == "add_memo":
            add_memo(memo_keyword)
            memo_list = load_memo_list()
        elif action == "delete_memo":
            delete_memo(memo_keyword)
            memo_list = load_memo_list()

    channels = ["지마켓", "쿠팡", "지그재그", "도매꾹", "에이블리", "4910"]
    pcs = ["Lenovo", "HP", "Razer"]

    return render_template(
        "index.html",
        keyword=keyword,
        log=log,
        memo_list=memo_list,
        history_list=history_list,
        channels=channels,
        pcs=pcs,
        selected_channel=selected_channel,
        selected_pc=selected_pc,
        show_history=show_history,
        exchange_rate=get_adjusted_exchange_rate()
    )


@app.route("/rate")
def rate_page():
    return render_template("rate.html", exchange_rate=get_adjusted_exchange_rate())


@app.route("/api/rate")
def api_rate():
    return jsonify({
        "rate": get_adjusted_exchange_rate()
    })


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
        CREATE TABLE IF NOT EXISTS history (
            keyword TEXT, channel TEXT, pc TEXT, created_at TEXT
        )
    """)
    cur.execute("SELECT * FROM history WHERE keyword=? AND channel=?", (keyword, channel))
    duplicate = cur.fetchone()

    if duplicate:
        logs.append("⚠️ 이미 기록됨")
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
    df = pd.read_sql_query("SELECT rowid AS id, * FROM history", conn)
    conn.close()

    if keyword and keyword.lower() != "all":
        df = df[df['keyword'] == keyword]

    if not df.empty:
        logs.append(f"🔍 이력 {len(df)}건:")
        for _, row in df.iterrows():
            logs.append(f"  📌 {row['keyword']} | {row['channel']} | {row['pc']} | {row['created_at']}")
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
    cur.execute("CREATE TABLE IF NOT EXISTS memos (keyword TEXT UNIQUE)")
    cur.execute("SELECT keyword FROM memos")
    memos = [row[0] for row in cur.fetchall()]
    conn.close()
    return memos


def load_history_list():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT rowid AS id, * FROM history")
    rows = [{"id": row[0], "keyword": row[1], "channel": row[2], "pc": row[3], "created_at": row[4]}
            for row in cur.fetchall()]
    conn.close()
    return rows


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


@app.route("/delete_history", methods=["POST"])
def delete_history():
    data = request.get_json()
    row_id = data.get("id")
    if row_id:
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("DELETE FROM history WHERE rowid=?", (row_id,))
        conn.commit()
        conn.close()
        export_combined_csv()
        return {"status": "ok"}
    else:
        return {"status": "error"}


@app.route("/download_all")
def download_all():
    export_combined_csv()
    return send_file("backup.csv", as_attachment=True)


@app.route("/upload_all", methods=["GET", "POST"])
def upload_all():
    if request.method == "POST":
        f = request.files["file"]
        if f and f.filename.endswith(".csv"):
            f.save("uploaded_backup.csv")
            with open("uploaded_backup.csv", "rb") as rawdata:
                result = chardet.detect(rawdata.read())
                detected_encoding = result['encoding']
            try:
                df_all = pd.read_csv("uploaded_backup.csv", encoding=detected_encoding)
            except Exception:
                df_all = pd.read_csv("uploaded_backup.csv", encoding="utf-8-sig")

            if "table" not in df_all.columns:
                return "❌ Error: This CSV does not have a 'table' column. Use the combined backup only."

            df_history = df_all[df_all["table"] == "history"].drop(columns=["table"])
            df_memos = df_all[df_all["table"] == "memos"][["keyword"]].drop_duplicates()

            conn = sqlite3.connect(DB_FILE)
            df_history.to_sql("history", conn, if_exists="replace", index=False)
            df_memos.to_sql("memos", conn, if_exists="replace", index=False)
            conn.close()

            export_combined_csv()
            return f"✅ 통합 CSV 복원 완료! (인코딩: {detected_encoding})"
    return '''
        <h3 style="color:lime;">📤 통합 CSV 업로드</h3>
        <form method="POST" enctype="multipart/form-data">
            <input type="file" name="file" accept=".csv">
            <input type="submit" value="Upload">
        </form>
    '''


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
