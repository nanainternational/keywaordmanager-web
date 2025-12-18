import os
import re
import threading
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify, render_template

# ✅ Python 3.13 호환: psycopg(v3)
import psycopg

app = Flask(__name__)

# ===============================
# ✅ TZ
# ===============================
try:
    import pytz
    TZ = pytz.timezone("Asia/Seoul")
except Exception:
    TZ = None

def _now():
    return datetime.now(TZ) if TZ else datetime.now()

# ===============================
# ✅ DB
# ===============================
_DB_READY = False
_DB_LOCK = threading.Lock()

def get_conn():
    db_url = (os.environ.get("DATABASE_URL") or "").strip()
    if not db_url:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg.connect(db_url, connect_timeout=10)

def _ensure_columns(cur):
    # chat_messages: client_id 컬럼
    cur.execute("""
        select 1
        from information_schema.columns
        where table_schema='public' and table_name='chat_messages' and column_name='client_id'
    """)
    if cur.fetchone() is None:
        cur.execute("alter table chat_messages add column client_id text")

    # presence 테이블
    cur.execute("""
        create table if not exists presence(
            client_id text primary key,
            sender text,
            last_seen timestamptz not null default now(),
            user_agent text
        )
    """)

def ensure_db():
    global _DB_READY
    if _DB_READY:
        return
    with _DB_LOCK:
        if _DB_READY:
            return
        with get_conn() as conn:
            with conn.cursor() as cur:
                # memos
                cur.execute(
                    """
                    create table if not exists memos(
                        id bigserial primary key,
                        content text unique,
                        created_at timestamptz not null default now()
                    )
                    """
                )

                # chat_messages
                cur.execute(
                    """
                    create table if not exists chat_messages(
                        id bigserial primary key,
                        room text not null default 'main',
                        sender text,
                        message text,
                        created_at timestamptz not null default now()
                    )
                    """
                )

                # calendar_events
                cur.execute(
                    """
                    create table if not exists calendar_events(
                        id bigserial primary key,
                        title text,
                        start_time timestamptz,
                        end_time timestamptz,
                        all_day int4 not null default 0,
                        memo text,
                        created_at timestamptz not null default now()
                    )
                    """
                )

                _ensure_columns(cur)

            conn.commit()
        _DB_READY = True

def _ensure_calendar_events_columns(cur):
    cur.execute("select column_name from information_schema.columns where table_schema='public' and table_name='calendar_events'")
    cols = {r[0] for r in cur.fetchall()}
    if "memo" not in cols:
        cur.execute("alter table calendar_events add column memo text")
    if "created_at" not in cols:
        cur.execute("alter table calendar_events add column created_at timestamptz not null default now()")
    if "all_day" not in cols:
        cur.execute("alter table calendar_events add column all_day int4 not null default 0")

def _parse_dt(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None

def _dt_to_fullcalendar(dt, is_all_day):
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
_cached_rate = {"value": None, "date": None}

def get_adjusted_exchange_rate():
    today = datetime.now().strftime("%Y-%m-%d")
    if _cached_rate["value"] is not None and _cached_rate["date"] == today:
        return _cached_rate["value"]

    try:
        url = "https://www.citibank.co.kr/FxdExrt0100.act"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=6)
        soup = BeautifulSoup(res.text, "html.parser")

        for li in soup.select("ul.exchangeList > li"):
            label = li.select_one("span.flagCn")
            value = li.select_one("span.green")
            if label and value and "중국" in label.get_text(strip=True):
                base = float(value.get_text(strip=True).replace(",", ""))
                adjusted = round((base + 2) * 1.1, 2)
                _cached_rate["value"] = adjusted
                _cached_rate["date"] = today
                return adjusted
    except Exception as e:
        print("환율 오류:", e)

    return _cached_rate["value"]

# ===============================
# ✅ Health
# ===============================
@app.route("/health", methods=["GET", "HEAD"])
def health():
    return ("", 200)

# ===============================
# ✅ 메인
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
                    cur.execute("insert into memos (content) values (%s) on conflict do nothing", (memo_keyword,))
                conn.commit()

        if action == "delete_memo" and memo_keyword:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("delete from memos where content=%s", (memo_keyword,))
                conn.commit()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("select content from memos order by id desc")
            memo_list = [r[0] for r in cur.fetchall()]

    return render_template(
        "index.html",
        memo_list=memo_list,
        exchange_rate=get_adjusted_exchange_rate(),
    )

# ===============================
# ✅ 메모 API
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
    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()
    if not content:
        return jsonify({"ok": False, "error": "empty"}), 400

    now = _now()
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
# ✅ 캘린더 API
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
                "start": _dt_to_fullcalendar(st, bool(all_day)),
                "end": _dt_to_fullcalendar(et, bool(all_day)) if et else None,
                "allDay": bool(all_day),
                "memo": memo or "",
            }
        )
    return jsonify(out)

@app.route("/api/events", methods=["POST"])
def create_event():
    ensure_db()
    data = request.get_json(silent=True) or {}

    title = (data.get("title") or "").strip()
    st = _parse_dt(data.get("start"))
    et = _parse_dt(data.get("end")) if data.get("end") else None
    all_day = 1 if data.get("allDay") else 0
    memo = data.get("memo") or ""

    if not title or not st:
        return jsonify({"ok": False, "error": "title/start required"}), 400

    now = _now()
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
    data = request.get_json(silent=True) or {}

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
# ✅ Presence API
# ===============================
@app.route("/api/presence/ping", methods=["POST"])
def presence_ping():
    ensure_db()
    data = request.get_json(silent=True) or {}
    client_id = (data.get("client_id") or "").strip()
    sender = (data.get("sender") or "").strip()
    ua = request.headers.get("User-Agent", "")[:300]

    if not client_id:
        return jsonify({"ok": False, "error": "client_id required"}), 400

    now = _now()
    with get_conn() as conn:
        with conn.cursor() as cur:
            _ensure_columns(cur)
            cur.execute(
                """
                insert into presence (client_id, sender, last_seen, user_agent)
                values (%s, %s, %s, %s)
                on conflict (client_id)
                do update set sender = excluded.sender, last_seen = excluded.last_seen, user_agent = excluded.user_agent
                """,
                (client_id, sender, now, ua),
            )
        conn.commit()

    return jsonify({"ok": True})

@app.route("/api/presence/list", methods=["GET"])
def presence_list():
    ensure_db()
    try:
        minutes = int(request.args.get("minutes", 5))
    except Exception:
        minutes = 5
    minutes = max(1, min(minutes, 60))

    with get_conn() as conn:
        with conn.cursor() as cur:
            _ensure_columns(cur)
            # ✅ 이름이 비어있는 경우는 최근접속자에서 제외
            cur.execute(
                """
                select client_id, sender, last_seen
                from presence
                where sender is not null and sender <> ''
                  and last_seen >= (now() - (%s || ' minutes')::interval)
                order by last_seen desc
                limit 30
                """,
                (minutes,),
            )
            rows = cur.fetchall()

    out = [{"client_id": r[0], "sender": r[1], "last_seen": r[2].isoformat() if r[2] else None} for r in rows]
    return jsonify({"ok": True, "users": out})

# ===============================
# ✅ 채팅 API
# ===============================
@app.route("/api/chat/messages", methods=["GET"])
def chat_messages():
    ensure_db()
    try:
        after_id = int(request.args.get("after_id", 0))
    except Exception:
        after_id = 0
    room = (request.args.get("room") or "main").strip() or "main"

    with get_conn() as conn:
        with conn.cursor() as cur:
            _ensure_columns(cur)
            cur.execute(
                """
                select id, sender, message, created_at, client_id
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
                {
                    "id": r[0],
                    "sender": r[1],
                    "message": r[2],
                    "created_at": r[3].isoformat() if r[3] else None,
                    "client_id": r[4] or "",
                }
                for r in rows
            ],
        }
    )

@app.route("/api/chat/send", methods=["POST"])
def send_chat():
    ensure_db()
    data = request.get_json(silent=True) or {}

    room = (data.get("room") or "main").strip() or "main"
    sender = (data.get("sender") or "").strip()
    message = (data.get("message") or "").strip()
    client_id = (data.get("client_id") or "").strip()

    if not client_id:
        return jsonify({"ok": False, "error": "client_id required"}), 400
    if not sender:
        return jsonify({"ok": False, "error": "sender_required"}), 400
    if not message:
        return jsonify({"ok": False, "error": "empty_message"}), 400

    now = _now()

    with get_conn() as conn:
        with conn.cursor() as cur:
            _ensure_columns(cur)
            cur.execute(
                """
                insert into chat_messages (room, sender, message, created_at, client_id)
                values (%s, %s, %s, %s, %s)
                returning id
                """,
                (room, sender, message, now, client_id),
            )
            msg_id = cur.fetchone()[0]
        conn.commit()

    return jsonify({"ok": True, "id": msg_id, "created_at": now.isoformat()})

if __name__ == "__main__":
    ensure_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
