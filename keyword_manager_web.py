from flask import Flask, render_template, request, send_file, jsonify
import sqlite3
import pandas as pd
from datetime import datetime
import pytz
import os
import chardet
import requests
from bs4 import BeautifulSoup
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DB_FILE = "keyword_manager.db"
tz = pytz.timezone("Asia/Seoul")

# ✅ 환율 캐시 저장소
cached_rate = {
    "value": None,
    "fetched_date": None  # YYYY-MM-DD-HH-MM
}

# ✅ 시티은행 기준 - 두 번째 <li> = 중국(CNY) 환율

def get_adjusted_exchange_rate():
    now = datetime.now(tz)
    now_key = now.strftime("%Y-%m-%d-%H-%M")

    # ✅ 테스트용 갱신 기준 시간 설정 (여기만 수정해서 원하는 시간으로 테스트 가능)
    REFRESH_HOUR = 10
    REFRESH_MINUTE = 00

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
    keyword = ""
    log = []
    selected_channel = request.form.get("selected_channel", "")

    memo_list = load_memo_list()
    history_list = load_history_list()
    show_history = False

    if request.method == "POST":
        action = request.form.get("action")
        keyword = request.form.get("keyword", "").strip()
        memo_keyword = request.form.get("memo_keyword", "").strip()

        if action == "record":
            log = record_keyword(keyword, selected_channel)
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

    return render_template(
        "index.html",
        keyword=keyword,
        log=log,
        memo_list=memo_list,
        history_list=history_list,
        channels=channels,
        selected_channel=selected_channel,
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

def record_keyword(keyword, channel):
    logs = []
    if not keyword:
        logs.append("❌ 키워드를 입력하세요.")
        return logs
    if not channel:
        logs.append("❌ 채널을 선택하세요.")
        return logs

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS history (
            keyword TEXT, channel TEXT, created_at TEXT
        )
    """)
    cur.execute("SELECT * FROM history WHERE keyword=? AND channel=?", (keyword, channel))
    duplicate = cur.fetchone()

    if duplicate:
        logs.append("⚠️ 이미 기록됨")
    else:
        now = datetime.now(tz).strftime("%Y-%m-%d")
        cur.execute("""
            INSERT INTO history (keyword, channel, created_at) VALUES (?, ?, ?)
        """, (keyword, channel, now))
        conn.commit()
        logs.append(f"✅ 기록 완료: {keyword} - {channel}")

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
            logs.append(f"  📌 {row['keyword']} | {row['channel']} | {row['created_at']}")
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
    df_memos["created_at"] = None
    df_memos = df_memos[["table", "keyword", "channel", "created_at"]]

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
    rows = [{"id": row[0], "keyword": row[1], "channel": row[2], "created_at": row[3]}
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
            df_memos = df_all[df_all["table"] == "memos"]["keyword"].drop_duplicates().to_frame()

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
    get_adjusted_exchange_rate()  # 앱 시작 시 1회 강제 호출
    app.run(host="0.0.0.0", port=5000, debug=True)
