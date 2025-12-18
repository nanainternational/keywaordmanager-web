import os
import time
import json
import threading
from datetime import datetime
from urllib.parse import quote_plus

import psycopg2
import psycopg2.extras
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify, render_template

app = Flask(__name__)

# ===============================
# ✅ TZ
# ===============================
try:
    import pytz
    tz = pytz.timezone("Asia/Seoul")
except Exception:
    tz = None

# ===============================
# ✅ DB
# ===============================
def get_conn():
    db_url = os.environ.get("DATABASE_URL", "").strip()
    if not db_url:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg2.connect(db_url)

def ensure_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            # memos
            cur.execute(
                """
                create table if not exists memos(
                    id serial primary key,
                    content text unique,
                    created_at timestamptz default now()
                )
                """
            )

            # chat_messages
            cur.execute(
                """
                create table if not exists chat_messages(
                    id serial primary key,
                    room text not null default 'main',
                    sender text,
                    message text,
                    created_at timestamptz default now()
                )
                """
            )

            # calendar_events (기존 테이블 호환)
            cur.execute(
                """
                create table if not exists calendar_events(
                    id serial primary key,
                    title text,
                    start_time timestamptz,
                    end_time timestamptz,
                    all_day int default 0,
                    memo text,
                    created_at timestamptz default now()
                )
                """
            )

        conn.commit()

def _ensure_calendar_events_columns(cur):
    # 기존 테이블이 있더라도 컬럼 누락되면 추가
    cur.execute("select column_name from information_schema.columns where table_name='calendar_events'")
    cols = {r[0] for r in cur.fetchall()}

    def add_col(sql):
        cur.execute(sql)

    if "memo" not in cols:
        add_col("alter table calendar_events add column memo text")
    if "created_at" not in cols:
        add_col("alter table calendar_events add column created_at timestamptz default now()")
    if "all_day" not in cols:
        add_col("alter table calendar_events add column all_day int default 0")

def _parse_dt(s):
    if not s:
        return None
    try:
        # datetime-local 형식 "YYYY-MM-DDTHH:MM"
        return datetime.fromisoformat(s)
    except Exception:
        try:
            return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        except Exception:
            return None

def _dt_to_fullcalendar_start(dt, is_all_day):
    if not dt:
        return None
    try:
        if is_all_day:
            return dt.strftime("%Y-%m-%d")
        return dt.strftime("%Y-%m-%dT%H:%M")
    except Exception:
        return None

# ===============================
# ✅ 환율 (시티은행)
# ===============================
cached_rate = {"value": None, "fetched_date": None}

def get_adjusted_exchange_rate():
    today = datetime.now().strftime("%Y-%m-%d")
    if cached_rate["value"] and cached_rate["fetched_date"] == today:
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
                cached_rate["fetched_date"] = today
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
# ✅ 메인 페이지 (GET/POST/HEAD)
# ===============================
@app.route("/", methods=["GET", "POST", "HEAD"])
def index():
    if request.method == "HEAD":
        return ("", 200)

    ensure_db()

    if request.method == "POST":
        action = request.form.get("action")
        memo_keyword = (request.form.get("memo_keyword") or "").strip()

        if action == "add_memo" and memo_keyword:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    # ✅ unique index 덕분에 중복 방지
                    cur.execute("insert into memos (content) values (%s) on conflict do nothing", (memo_keyword,))
                conn.commit()

        if action == "delete_memo" and memo_keyword:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("delete from memos where content=%s", (memo_keyword,))
                conn.commit()

    with get_conn() as conn:
        with conn.cursor() as cur:
            # ✅ 최신 메모가 위로(=id desc)
            cur.execute("select content from memos order by id desc")
            memo_list = [r[0] for r in cur.fetchall()]

    return render_template(
        "index.html",
        memo_list=memo_list,
        exchange_rate=get_adjusted_exchange_rate(),
    )

# ===============================
# ✅ 메모 API (실시간 동기화용)
# ===============================
@app.route("/api/memos", methods=["GET"])
def api_get_memos():
    ensure_db()
    after_id = request.args.get("after_id")

    with get_conn() as conn:
        with conn.cursor() as cur:
            if after_id and str(after_id).isdigit():
                cur.execute(
                    "select id, content, created_at from memos where id > %s order by id asc",
                    (int(after_id),),
                )
            else:
                cur.execute("select id, content, created_at from memos order by id asc")
            rows = cur.fetchall()

    out = [{"id": r[0], "content": r[1], "created_at": r[2].isoformat() if r[2] else None} for r in rows]
    return jsonify(out)

@app.route("/api/memos", methods=["POST"])
def api_create_memo():
    ensure_db()
    data = request.get_json() or {}
    content = (data.get("content") or "").strip()
    if not content:
        return jsonify({"ok": False, "error": "empty"}), 400

    now = datetime.now(tz) if tz else datetime.now()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into memos (content, created_at) values (%s, %s) on conflict do nothing returning id",
                (content, now),
            )
            row = cur.fetchone()
        conn.commit()

    return jsonify({"ok": True, "id": row[0] if row else None})

@app.route("/api/memos/<int:memo_id>", methods=["DELETE"])
def api_delete_memo(memo_id):
    ensure_db()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from memos where id=%s", (memo_id,))
        conn.commit()
    return jsonify({"ok": True})

# ===============================
# ✅ 캘린더 API (calendar_events만 사용)
# ===============================
@app.route("/api/events", methods=["GET"])
def get_events():
    ensure_db()
    with get_conn() as conn:
        with conn.cursor() as cur:
            _ensure_calendar_events_columns(cur)
            cur.execute(
                """
                select id, title, start_time, end_time, all_day, memo
                from calendar_events
                order by id asc
                """
            )
            rows = cur.fetchall()

    out = []
    for (eid, title, st, et, all_day, memo) in rows:
        out.append(
            {
                "id": eid,
                "title": title or "",
                "start": _dt_to_fullcalendar_start(st, bool(all_day)),
                "end": _dt_to_fullcalendar_start(et, bool(all_day)) if et else None,
                "allDay": bool(all_day),
                "memo": memo or "",
            }
        )
    return jsonify(out)

@app.route("/api/events", methods=["POST"])
def create_event():
    ensure_db()
    data = request.get_json() or {}

    title = (data.get("title") or "").strip()
    st = _parse_dt(data.get("start"))
    et = _parse_dt(data.get("end")) if data.get("end") else None
    all_day = 1 if data.get("allDay") else 0
    memo = data.get("memo", "")

    if not title or not st:
        return jsonify({"ok": False, "error": "title/start required"}), 400

    now = datetime.now(tz) if tz else datetime.now()
    with get_conn() as conn:
        with conn.cursor() as cur:
            _ensure_calendar_events_columns(cur)
            cur.execute(
                """
                insert into calendar_events (title, start_time, end_time, all_day, memo, created_at)
                values (%s, %s, %s, %s, %s, %s)
                returning id
                """,
                (title, st, et, all_day, memo, now),
            )
            event_id = cur.fetchone()[0]
        conn.commit()

    return jsonify({"ok": True, "id": event_id})

@app.route("/api/events/<int:event_id>", methods=["PUT"])
def update_event(event_id):
    ensure_db()
    data = request.get_json() or {}

    fields = []
    values = []

    if "title" in data:
        fields.append("title=%s")
        values.append((data.get("title") or "").strip())

    if "start" in data:
        fields.append("start_time=%s")
        values.append(_parse_dt(data.get("start")))

    if "end" in data:
        fields.append("end_time=%s")
        values.append(_parse_dt(data.get("end")) if data.get("end") else None)

    if "allDay" in data:
        fields.append("all_day=%s")
        values.append(1 if data.get("allDay") else 0)

    if "memo" in data:
        fields.append("memo=%s")
        values.append(data.get("memo") or "")

    if not fields:
        return jsonify({"ok": True})

    values.append(event_id)

    with get_conn() as conn:
        with conn.cursor() as cur:
            _ensure_calendar_events_columns(cur)
            cur.execute(f"update calendar_events set {', '.join(fields)} where id=%s", values)
        conn.commit()

    return jsonify({"ok": True})

@app.route("/api/events/<int:event_id>", methods=["DELETE"])
def delete_event(event_id):
    ensure_db()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from calendar_events where id=%s", (event_id,))
        conn.commit()
    return jsonify({"ok": True})

# ===============================
# ✅ 채팅 API
# ===============================
@app.route("/api/chat/messages", methods=["GET"])
def chat_messages():
    ensure_db()
    after_id = int(request.args.get("after_id", 0))
    room = (request.args.get("room") or "main").strip() or "main"

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select id, sender, message, created_at
                from chat_messages
                where room = %s and id > %s
                order by id asc
                """,
                (room, after_id),
            )
            rows = cur.fetchall()

    return jsonify(
        {
            "ok": True,
            "messages": [
                {"id": r[0], "sender": r[1], "message": r[2], "created_at": r[3].isoformat() if r[3] else None}
                for r in rows
            ],
        }
    )

@app.route("/api/chat/send", methods=["POST"])
def send_chat():
    ensure_db()
    data = request.get_json() or {}

    room = (data.get("room") or "main").strip() or "main"
    sender = (data.get("sender") or "익명").strip()
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"ok": False, "error": "empty_message"}), 400

    now = datetime.now(tz) if tz else datetime.now()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into chat_messages (room, sender, message, created_at)
                values (%s, %s, %s, %s)
                returning id
                """,
                (room, sender, message, now),
            )
            msg_id = cur.fetchone()[0]
        conn.commit()

    return jsonify({"ok": True, "id": msg_id, "created_at": now.isoformat()})

if __name__ == "__main__":
    ensure_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
