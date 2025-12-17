from flask import Flask, render_template, request, jsonify
from datetime import datetime
import pytz
import os
import re
import requests
from bs4 import BeautifulSoup
from flask_cors import CORS

# ✅ Postgres(Supabase) 연결용
import psycopg
import threading

app = Flask(__name__)
CORS(app)

tz = pytz.timezone("Asia/Seoul")

_DB_READY = False
_DB_LOCK = threading.Lock()

# ===============================
# ✅ DB URL (한 번만 로드/출력)
# ===============================
_CACHED_DATABASE_URL = None


def _get_database_url():
    global _CACHED_DATABASE_URL
    if _CACHED_DATABASE_URL:
        return _CACHED_DATABASE_URL

    url = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL")
    if not url:
        raise RuntimeError("DATABASE_URL (or SUPABASE_DB_URL) is required")

    # 안전 출력(비번 숨김)
    safe = url.split("@", 1)[-1] if "@" in url else url
    print(f"✅ Using DATABASE_URL: postgresql://***@{safe}")

    _CACHED_DATABASE_URL = url
    return url


def get_conn():
    return psycopg.connect(_get_database_url(), connect_timeout=10)


# ===============================
# ✅ DB 초기화 (한 번만)
# ===============================
def init_db():
    ddl = """
create table if not exists memos (
  id bigserial primary key,
  content text not null,
  created_at timestamptz not null default now()
);

-- ✅ 중복 메모 방지 (unique index)
create unique index if not exists memos_content_uq on memos (content);

-- ✅ 채팅
create table if not exists chat_messages (
  id bigserial primary key,
  room text not null,
  sender text not null,
  message text not null,
  created_at timestamptz not null default now()
);

-- ✅ (레거시) events: 예전 텍스트 기반 (남겨둠)
create table if not exists events (
  id bigserial primary key,
  title text not null,
  start_at text,
  end_at text,
  all_day int4 not null default 0,
  memo text,
  created_at timestamptz not null default now()
);

-- ✅ calendar_events: FullCalendar용 (timestamptz)
create table if not exists calendar_events (
  id bigserial primary key,
  title text not null,
  start_time timestamptz,
  end_time timestamptz,
  created_at timestamptz not null default now(),
  all_day int4 not null default 0,
  memo text
);
"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(ddl)
        conn.commit()


# ===============================
# ✅ Calendar helpers (KST 기준)
# ===============================
def _parse_dt(val):
    """val: 'YYYY-MM-DD' 또는 ISO 문자열. None 가능."""
    if val is None:
        return None
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return None

        # 날짜만 들어오면 KST 00:00
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            y, mo, d = map(int, s.split("-"))
            return datetime(y, mo, d, 0, 0, 0, tzinfo=tz)

        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=tz)
            return dt.astimezone(tz)
        except Exception:
            return None
    return None


def _dt_to_fullcalendar_start(dt, all_day):
    if not dt:
        return None
    dt_kst = dt.astimezone(tz) if dt.tzinfo else dt.replace(tzinfo=tz)
    if all_day:
        return dt_kst.date().isoformat()
    return dt_kst.isoformat()


def _ensure_calendar_events_columns(cur):
    """배포 중 스키마가 꼬였을 때를 대비해 컬럼을 보정."""
    cur.execute(
        """
        select 1
        from information_schema.columns
        where table_schema='public' and table_name='calendar_events' and column_name='all_day'
        """
    )
    if cur.fetchone() is None:
        cur.execute("alter table calendar_events add column all_day int4 not null default 0")

    cur.execute(
        """
        select 1
        from information_schema.columns
        where table_schema='public' and table_name='calendar_events' and column_name='memo'
        """
    )
    if cur.fetchone() is None:
        cur.execute("alter table calendar_events add column memo text")

    cur.execute(
        """
        select 1
        from information_schema.columns
        where table_schema='public' and table_name='calendar_events' and column_name='created_at'
        """
    )
    if cur.fetchone() is None:
        cur.execute("alter table calendar_events add column created_at timestamptz not null default now()")


def migrate_events_to_calendar_events_once():
    """레거시 events -> calendar_events (calendar_events가 비어있을 때만 1회)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            _ensure_calendar_events_columns(cur)

            cur.execute("select count(*) from calendar_events")
            cal_cnt = cur.fetchone()[0] or 0
            if cal_cnt > 0:
                conn.commit()
                return

            cur.execute("select id, title, start_at, end_at, all_day, memo, created_at from events order by id asc")
            rows = cur.fetchall()
            if not rows:
                conn.commit()
                return

            for (_id, title, start_at, end_at, all_day, memo, created_at) in rows:
                st = _parse_dt(start_at)
                et = _parse_dt(end_at) if end_at else None
                cur.execute(
                    """
                    insert into calendar_events (title, start_time, end_time, all_day, memo, created_at)
                    values (%s, %s, %s, %s, %s, %s)
                    """,
                    (title or "", st, et, int(all_day or 0), memo, created_at or datetime.now(tz)),
                )
        conn.commit()


def ensure_db():
    global _DB_READY
    if _DB_READY:
        return
    with _DB_LOCK:
        if _DB_READY:
            return
        init_db()
        # ✅ 스키마 보정 + (비었을 때만) 마이그레이션 1회
        migrate_events_to_calendar_events_once()
        _DB_READY = True


# ===============================
# ✅ 환율 (캐시)
# ===============================
cached_rate = {"value": None, "fetched_date": None}


def get_adjusted_exchange_rate():
    now = datetime.now(tz)
    REFRESH_HOUR = 9
    REFRESH_MINUTE = 5
    refresh_key = now.strftime(f"%Y-%m-%d-{REFRESH_HOUR:02d}-{REFRESH_MINUTE:02d}")

    if cached_rate["value"] and cached_rate["fetched_date"] == refresh_key:
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
                cached_rate["fetched_date"] = refresh_key
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
            cur.execute("select content from memos order by content")
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

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("insert into memos (content, created_at) values (%s, %s) on conflict do nothing returning id",
                        (content, datetime.now(tz)))
            row = cur.fetchone()
        conn.commit()

    # 중복이면 row가 None일 수 있음
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

    with get_conn() as conn:
        with conn.cursor() as cur:
            _ensure_calendar_events_columns(cur)
            cur.execute(
                """
                insert into calendar_events (title, start_time, end_time, all_day, memo, created_at)
                values (%s, %s, %s, %s, %s, %s)
                returning id
                """,
                (title, st, et, all_day, memo, datetime.now(tz)),
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

    now = datetime.now(tz)

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
