import os
import re
import threading
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_cors import CORS

# ===============================
# ✅ Flask
# ===============================
app = Flask(__name__)
CORS(app)

# ===============================
# ✅ Push (Blueprint)
# ===============================
try:
    from push_routes import push_bp, send_push  # noqa: F401
    app.register_blueprint(push_bp)
except Exception as _e:
    # push_routes.py가 없거나(또는 의존성 미설치)일 때도 기존 앱은 동작하게 둠
    push_bp = None
    send_push = None


# ===============================
# ✅ TZ
# ===============================
try:
    import pytz
    TZ = pytz.timezone("Asia/Seoul")
except Exception:
    TZ = None

# ===============================
# ✅ DB
# ===============================
_DB_URL = (os.environ.get("DATABASE_URL") or "").strip()

def _now():
    if TZ:
        return datetime.now(TZ)
    return datetime.now()

# ===============================
# ✅ psycopg (optional)
# ===============================
try:
    import psycopg
except Exception:
    psycopg = None


def _get_conn():
    if not _DB_URL:
        raise RuntimeError("DATABASE_URL not set")
    if psycopg is None:
        raise RuntimeError("psycopg not installed")
    return psycopg.connect(_DB_URL, connect_timeout=10)


def _ensure_calendar_schema(cur):
    """DB migration for old calendar_events schema.
    Some deployments have calendar_events without 'date' column (e.g. 'event_date' or 'day').
    We normalize it to 'date' so the API queries work.
    """
    try:
        cur.execute("""
            select column_name
            from information_schema.columns
            where table_schema = 'public' and table_name = 'calendar_events'
        """)
        cols = {r[0] for r in cur.fetchall()}
        if "date" in cols:
            return

        # Rename common legacy columns to 'date'
        for legacy in ("event_date", "day", "dt"):
            if legacy in cols:
                cur.execute(f'alter table calendar_events rename column "{legacy}" to "date"')
                return

        # If no usable legacy column, add 'date'
        cur.execute('alter table calendar_events add column "date" date')

        # extra fields used by UI
        cur.execute('alter table calendar_events add column if not exists memo text')
        cur.execute('alter table calendar_events add column if not exists all_day boolean default false')
        cur.execute('alter table calendar_events add column if not exists start_time text')
        cur.execute('alter table calendar_events add column if not exists end_time text')
    except Exception as e:
        print("⚠️ calendar_events schema check failed:", repr(e))

def _init_db():
    if not _DB_URL or psycopg is None:
        return
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            create table if not exists chat_messages (
                id bigserial primary key,
                room text not null,
                sender text not null,
                message text not null,
                created_at timestamptz not null default now()
            )
            """)
            cur.execute("""
            create table if not exists memos (
                id bigserial primary key,
                text text not null,
                created_at timestamptz not null default now()
            )
            """)
            cur.execute("""
            create table if not exists calendar_events (
                id bigserial primary key,
                title text not null,
                date text not null,
                start_time text,
                end_time text,
                created_at timestamptz not null default now()
            )
            """)
            _ensure_calendar_schema(cur)
            conn.commit()
            cur.execute("""
            create table if not exists presence (
                id bigserial primary key,
                client_id text unique not null,
                sender text,
                animal text,
                last_seen timestamptz not null default now()
            )
            """)
            # ensure add column if not exists last_seen timestamptz not null default now()
        conn.commit()


_init_db()


# ===============================
# ✅ Static / Templates
# ===============================
@app.route("/", methods=["GET", "POST"])
def index():
    # 기존 index.html은 form POST를 "/"로 보내는 구조가 있어 405가 발생할 수 있음.
    # POST(action)를 서버에서 처리한 뒤 다시 "/"로 돌아오게 처리한다.
    if request.method == "POST":
        action = (request.form.get("action") or "").strip()

        # ✅ 메모 추가
        if action == "add_memo":
            text = (request.form.get("memo_text") or request.form.get("text") or "").strip()
            if text and _DB_URL and psycopg is not None:
                with _get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("insert into memos (text) values (%s)", (text,))
                    conn.commit()

        # ✅ 메모 삭제
        elif action == "delete_memo":
            memo_id = (request.form.get("memo_id") or request.form.get("id") or "").strip()
            try:
                memo_id_i = int(memo_id)
            except Exception:
                memo_id_i = None
            if memo_id_i and _DB_URL and psycopg is not None:
                with _get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("delete from memos where id=%s", (memo_id_i,))
                    conn.commit()

        # ✅ 일정 추가
        elif action == "add_event":
            title = (request.form.get("title") or "").strip()
            date = (request.form.get("date") or "").strip()
            start_time = (request.form.get("start") or request.form.get("start_time") or "").strip()
            end_time = (request.form.get("end") or request.form.get("end_time") or "").strip()
            if title and date and _DB_URL and psycopg is not None:
                with _get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "insert into calendar_events (title, date, start_time, end_time, memo, all_day) values (%s, %s, %s, %s, %s, %s)",
                            (title, date, start_time or None, end_time or None),
                        )
                    conn.commit()

        # ✅ 일정 삭제
        elif action == "delete_event":
            event_id = (request.form.get("event_id") or request.form.get("id") or "").strip()
            try:
                event_id_i = int(event_id)
            except Exception:
                event_id_i = None
            if event_id_i and _DB_URL and psycopg is not None:
                with _get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("delete from calendar_events where id=%s", (event_id_i,))
                    conn.commit()

        # POST 처리 후 새로고침(중복전송 방지)
        from flask import redirect
        return redirect("/")

    return render_template("index.html")
@app.route("/rate")
def rate_page():
    return render_template("rate.html")


# ===============================
# ✅ PWA (manifest / service worker)
# ===============================
@app.route("/service-worker.js")
def service_worker():
    return send_from_directory(
        ".",
        "service-worker.js",
        mimetype="application/javascript",
        max_age=0
    )


@app.route("/manifest.webmanifest")
def webmanifest():
    return send_from_directory(
        ".",
        "manifest.webmanifest",
        mimetype="application/manifest+json",
        max_age=0
    )


# ===============================
# ✅ Chat API
# ===============================
@app.route("/api/chat/messages", methods=["GET"])
def api_chat_messages():
    room = request.args.get("room", "main")
    after_id = request.args.get("after_id", "0")
    try:
        after_id = int(after_id)
    except Exception:
        after_id = 0

    if not _DB_URL or psycopg is None:
        return jsonify({"ok": True, "messages": []})

    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select id, room, sender, message, created_at from chat_messages where room=%s and id>%s order by id asc limit 200",
                (room, after_id),
            )
            rows = cur.fetchall()

    msgs = []
    for r in rows:
        msgs.append({
            "id": r[0],
            "room": r[1],
            "sender": r[2],
            "message": r[3],
            "created_at": r[4].isoformat() if r[4] else None,
        })
    return jsonify({"ok": True, "messages": msgs})


@app.route("/api/chat/send", methods=["POST"])
def api_chat_send():
    data = request.get_json(silent=True) or {}
    room = (data.get("room") or "main").strip()
    sender = (data.get("sender") or "익명").strip()
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"ok": False, "error": "empty message"}), 400

    if not _DB_URL or psycopg is None:
        return jsonify({"ok": True})
    except Exception as e:
        print('[events POST error]', repr(e))
        return jsonify({'ok': False, 'error': str(e)}), 500

    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into chat_messages (room, sender, message) values (%s, %s, %s) returning id",
                (room, sender, message),
            )
            new_id = cur.fetchone()[0]
        conn.commit()

    # (옵션) 새 메시지 발생 시 푸시 보내고 싶으면 여기서 send_push 호출 가능
    # if send_push:
    #     send_push({"title": "새 메시지", "body": f"{sender}: {message}", "url": "/"})

    return jsonify({"ok": True, "id": new_id})


# ===============================
# ✅ Memos API
# ===============================
@app.route("/api/memos", methods=["GET"])
def api_memos():
    if not _DB_URL or psycopg is None:
        return jsonify({"ok": True, "memos": []})

    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("select id, text, created_at from memos order by id desc limit 500")
            rows = cur.fetchall()

    memos = []
    for r in rows:
        memos.append({
            "id": r[0],
            "text": r[1],
            "created_at": r[2].isoformat() if r[2] else None,
        })
    return jsonify({"ok": True, "memos": memos})


@app.route("/api/memos/add", methods=["POST"])
def api_memos_add():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "empty"}), 400

    if not _DB_URL or psycopg is None:
        return jsonify({"ok": True})

    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("insert into memos (text) values (%s)", (text,))
        conn.commit()

    return jsonify({"ok": True})


@app.route("/api/memos/delete", methods=["POST"])
def api_memos_delete():
    data = request.get_json(silent=True) or {}
    memo_id = data.get("id")
    try:
        memo_id = int(memo_id)
    except Exception:
        return jsonify({"ok": False, "error": "invalid id"}), 400

    if not _DB_URL or psycopg is None:
        return jsonify({"ok": True})

    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from memos where id=%s", (memo_id,))
        conn.commit()

    return jsonify({"ok": True})


# ===============================
# ✅ Calendar API
# ===============================
@app.route("/api/events", methods=["GET","POST"])
def api_events():
    # ✅ 프론트가 POST /api/events로 저장을 보내는 경우를 지원 (기존 /api/events/add와 동일)
    if request.method == "POST":
        return api_events_add()
    if not _DB_URL or psycopg is None:
        return jsonify({"ok": True, "events": []})

    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("select id, title, date, start_time, end_time, coalesce(memo,'') as memo, coalesce(all_day,false) as all_day from calendar_events order by date asc, start_time asc limit 2000")
            rows = cur.fetchall()

    events = []
    for r in rows:
        events.append({
            "id": r[0],
            "title": r[1],
            "date": r[2],
            "start": r[3],
            "end": r[4],
            "memo": r[5],
            "allDay": bool(r[6]),
        })
    return jsonify({"ok": True, "events": events})


@app.route("/api/events/add", methods=["POST"])
def api_events_add():
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    memo = (data.get("memo") or "").strip()
    all_day = bool(data.get("allDay") or data.get("all_day") or False)

    # ✅ 프론트가 {start/end}로 보내는 경우도 지원
    date = (data.get("date") or "").strip()
    if not date:
        date = (data.get("start") or "").strip()
    # FullCalendar는 ISO datetime을 줄 수 있음 → 날짜만
    if 'T' in date:
        date = date.split('T', 1)[0]

    # ✅ 프론트에서 보내는 형식 통합 지원
    # - 기존: {date: 'YYYY-MM-DD', start: 'HH:MM', end: 'HH:MM'}
    # - 현재 UI/FullCalendar: {start: 'YYYY-MM-DD' or ISO, end: 'YYYY-MM-DD' or ISO}
    def _split_dt(v: str):
        v = (v or "").strip()
        if not v:
            return "", ""
        # ISO(YYYY-MM-DDTHH:MM...) 형태면 날짜/시각 분리
        if "T" in v:
            d, t = v.split("T", 1)
            t = t.split("+", 1)[0].split("Z", 1)[0]
            t = t[:5]  # HH:MM
            return d.strip(), t.strip()
        # YYYY-MM-DD만 오면 날짜로 취급
        if len(v) >= 10 and v[4] == "-" and v[7] == "-":
            return v[:10], ""
        # HH:MM만 오면 시각으로 취급
        return "", v

    start_raw = (data.get("start") or "").strip()
    end_raw = (data.get("end") or "").strip()

    d1, t1 = _split_dt(start_raw)
    d2, t2 = _split_dt(end_raw)

    if not date:
        # date가 없으면 start에서 날짜를 뽑아 사용
        date = d1 or d2

    start_time = t1
    end_time = t2

    if not title or not date:
        return jsonify({"ok": False, "error": "missing title/date"}), 400

    if not _DB_URL or psycopg is None:
        return jsonify({"ok": True})

    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into calendar_events (title, date, start_time, end_time, memo, all_day) values (%s, %s, %s, %s, %s, %s)",
                (title, date, start_time or None, end_time or None, memo or None, all_day),
            )
        conn.commit()

    return jsonify({"ok": True})


@app.route("/api/events/delete", methods=["POST"])
def api_events_delete():
    data = request.get_json(silent=True) or {}
    event_id = data.get("id")
    try:
        event_id = int(event_id)
    except Exception:
        return jsonify({"ok": False, "error": "invalid id"}), 400

    if not _DB_URL or psycopg is None:
        return jsonify({"ok": True})

    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from calendar_events where id=%s", (event_id,))
        conn.commit()

    return jsonify({"ok": True})


# ===============================
# ✅ Presence API
# ===============================
@app.route("/api/presence/ping", methods=["POST"])
def api_presence_ping():
    data = request.get_json(silent=True) or {}
    client_id = (data.get("client_id") or "").strip()
    sender = (data.get("sender") or "").strip()
    animal = (data.get("animal") or "").strip()

    if not client_id:
        return jsonify({"ok": False, "error": "missing client_id"}), 400

    if not _DB_URL or psycopg is None:
        return jsonify({"ok": True})

    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into presence (client_id, sender, animal, last_seen)
                values (%s, %s, %s, now())
                on conflict (client_id) do update
                set sender=excluded.sender,
                    animal=excluded.animal,
                    last_seen=now()
                """,
                (client_id, sender, animal),
            )
        conn.commit()

    return jsonify({"ok": True})


@app.route("/api/presence/list", methods=["GET"])
def api_presence_list():
    minutes = request.args.get("minutes", "3")
    try:
        minutes = int(minutes)
    except Exception:
        minutes = 3

    if not _DB_URL or psycopg is None:
        return jsonify({"ok": True, "list": []})

    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select client_id, sender, animal, last_seen from presence where last_seen > (now() - interval '%s minutes') order by last_seen desc limit 50",
                (minutes,),
            )
            rows = cur.fetchall()

    items = [
        {"client_id": r[0], "sender": (r[1] or ""), "animal": (r[2] or ""), "last_seen": r[3].isoformat() if r[3] else None}
        for r in rows
    ]
    return jsonify({"ok": True, "list": items})


# ===============================
# ✅ Run
# ===============================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
