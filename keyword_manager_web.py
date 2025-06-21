from flask import Flask, render_template, request, redirect, url_for
import pandas as pd
import os
from datetime import datetime

app = Flask(__name__)

HISTORY_FILE = "keyword_history.xlsx"
MEMO_FILE = "memo_keywords.txt"

# === 기본 페이지 ===
@app.route("/", methods=["GET", "POST"])
def index():
    keyword = ""
    channel = ""
    log = []
    memo_list = load_memo_list()

    if request.method == "POST":
        action = request.form.get("action")
        keyword = request.form.get("keyword", "").strip()
        channel = request.form.get("channel", "").strip()

        if action == "record":
            log = record_keyword(keyword, channel)
        elif action == "check":
            log = check_history(keyword)
        elif action == "add_memo":
            add_memo(keyword)
            memo_list = load_memo_list()
            log.append(f"➕ 메모 추가: {keyword}")
        elif action == "delete_memo":
            delete_memo(keyword)
            memo_list = load_memo_list()
            log.append(f"❌ 메모 삭제: {keyword}")

    return render_template("index.html",
                           keyword=keyword,
                           log=log,
                           memo_list=memo_list)

# === 기록 함수 ===
def record_keyword(keyword, channel):
    logs = []
    if not keyword:
        logs.append("❌ 키워드를 입력하세요.")
        return logs
    if not channel:
        logs.append("❌ 채널을 선택하세요.")
        return logs

    if os.path.exists(HISTORY_FILE):
        df = pd.read_excel(HISTORY_FILE)
    else:
        df = pd.DataFrame(columns=['키워드', '채널', '수집일자'])

    duplicate = df[(df['키워드'] == keyword) & (df['채널'] == channel)]

    if not duplicate.empty:
        last = duplicate.iloc[-1]
        logs.append(f"⚠️ 이미 기록됨: {last['수집일자']}")
    else:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        new_row = pd.DataFrame([[keyword, channel, now]], columns=df.columns)
        df = pd.concat([df, new_row], ignore_index=True)
        df.to_excel(HISTORY_FILE, index=False)
        logs.append(f"✅ 기록 완료: {keyword} - {channel}")

    return logs

# === 이력 조회 함수 ===
def check_history(keyword):
    logs = []
    if not keyword:
        logs.append("❌ 키워드를 입력하세요.")
        return logs

    if os.path.exists(HISTORY_FILE):
        df = pd.read_excel(HISTORY_FILE)
        matches = df[df['키워드'] == keyword]
        if not matches.empty:
            logs.append(f"🔍 이력 {len(matches)}건:")
            for _, row in matches.iterrows():
                logs.append(f"  📌 {row['채널']} | {row['수집일자']}")
        else:
            logs.append("ℹ️ 이력이 없습니다.")
    else:
        logs.append("ℹ️ 기록 파일이 없습니다.")
    return logs

# === 메모 관리 ===
def load_memo_list():
    if os.path.exists(MEMO_FILE):
        with open(MEMO_FILE, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    return []

def add_memo(keyword):
    if keyword:
        with open(MEMO_FILE, "a", encoding="utf-8") as f:
            f.write(f"{keyword}\n")

def delete_memo(keyword):
    memos = load_memo_list()
    if keyword in memos:
        memos.remove(keyword)
        with open(MEMO_FILE, "w", encoding="utf-8") as f:
            for memo in memos:
                f.write(f"{memo}\n")

# === 서버 실행 ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
