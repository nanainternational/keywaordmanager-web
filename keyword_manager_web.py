from flask import Flask, render_template, request, jsonify
from datetime import datetime
import pytz
import os
import requests
from bs4 import BeautifulSoup
from flask_cors import CORS

from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
import threading

import psycopg

# ✅ psycopg3 pool (없을 수도 있으니 try)
try:
    from psycopg_pool import ConnectionPool
except Exception:
    ConnectionPool = None


app = Flask(__name__)
CORS(app)

tz = pytz.timezone("Asia/Seoul")

_DB_READY = False
_DB_LOCK = threading.Lock()

_POOL = None


# ===============================
# ✅ DB URL (Supabase Postgres)
# ===============================
def _get_database_url():
    url = (os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_URLSupabase") or "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL(또는 DATABASE_URLSupabase) 환경변수가 없습니다. Render Environment에 설정하세요.")

    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]

    u = urlparse(url)
    q = dict(parse_qsl(u.query))
    if "sslmode" not in q:
        q["sslmode"] = "require"
        u = u._replace(query=urlencode(q))
        url = urlunparse(u)

    # ✅ 로그(비번 마스킹)
    try:
        masked = url
        if "://" in masked and "@" in masked:
            head, tail = masked.split("://", 1)
            cred, rest = tail.split("@", 1)
            if ":" in cred:
                user, _pw = cred.split(":", 1)
                masked = f"{head}://{user}:***@{rest}"
        print(f"✅ Using DATABASE_URL: {masked}")
    except Exception:
        pass

    return url


# ===============================
# ✅ DB Connection (Pool 우선)
# ===============================
def _init_pool_once():
    global _POOL
    if _POOL is not None:
        return

    if ConnectionPool is None:
        # psycopg_pool이 없으면 풀 없이 진행
        _POOL = False
        return

    dsn = _get_database_url()

    # Render free + Supabase pooler 특성상 너무 큰 풀은 오히려 역효과
    _POOL = ConnectionPool(
        conninfo=dsn,
        min_size=1,
        max_size=4,
        timeout=10,
        max_lifetime=60 * 10,
        max_idle=60 * 2,
    )


def db_conn():
    """
    사용법:
      with db_conn() as conn:
          with conn.cursor() as cur:
              ...
    """
    _init_pool_once()
    if _POOL is False:
        return psycopg.connect(_get_database_url(), connect_timeout=10)
    return _POOL.connection()


# ===============================
# ✅ DB 초기화 / 마이그레이션
# ===============================
def init_db():
    ddl = """
    create table if not exists memos (
        id bigserial primary key,
        content text not null,
        created_at timestamptz default now()
    );
    create unique index if not exists memos_content_uq on memos(content);

    -- 레거시 events
    create table if not exists events (
        id bigserial primary key,
        title text not null,
        start_at text not null,
        end_at text,
        all_day integer default 0,
        memo text,
        created_at timestamptz default now()
    );

    -- ✅ 캘린더 메인
    create table if not exists calendar_events (
        id bigserial primary key,
        title text not null,
        start_time timestamptz not null,
        end_time timestamptz,
        all_day integer default 0,
        memo text,
        created_at timestamptz default now()
    );

    create table if not exists chat_messages (
        id bigserial primary key,
        room text default 'main',
        sender text,
        message text not null,
        created_at timestamptz default now()
    );
    create index if not exists chat_room_id_idx on chat_messages(room, id);
    """
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(ddl)
        conn.commit()


def migrate_calendar_events_table():
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select column_name
                from information_schema.columns
                where table_schema='public' and table_name='calendar_events'
                """
            )
            cols = {r[0] for r in cur.fetchall()}
            if not cols:
                conn.commit()
                return

            # ✅ 이번 에러 원인 방지: 없으면 즉시 추가
            if "all_day" not in cols:
                cur.execute("alter table calendar_events add column if not exists all_day integer default 0")
            if "memo" not in cols:
                cur.execute("alter table calendar_events add column if not exists memo text")
            if "created_at" not in cols:
                cur.execute("alter table calendar_events add column if not exists created_at timestamptz default now()")
        conn.commit()


def _parse_legacy_text_dt(s: str):
    if not s:
        return None
    s = str(s).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    if len(s) == 10 and s.count("-") == 2:
        dt = datetime.fromisoformat(s + "T00:00:00")
        return tz.localize(dt)
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            return tz.localize(dt)
        return dt
    except Exception:
        return None


def migrate_events_to_calendar_events_once():
    """
    ✅ 레거시 events -> calendar_events 이관 (1회)
    - 이관 실패는 서비스 전체를 죽이면 안됨 (로그만 찍고 무시)
    """
    try:
        with db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("select count(*) from calendar_events")
                cal_cnt = cur.fetchone()[0]
                cur.execute("select count(*) from events")
                old_cnt = cur.fetchone()[0]
                if cal_cnt > 0 or old_cnt == 0:
                    conn.commit()
                    return

                cur.execute("select title, start_at, end_at, all_day, memo, created_at from events order by id asc")
                rows = cur.fetchall()

                inserted = 0
                for title, start_at, end_at, all_day, memo, created_at in rows:
                    st = _parse_legacy_text_dt(start_at)
                    et = _parse_legacy_text_dt(end_at) if end_at else None
                    if not title or not st:
                        continue

                    cur.execute(
                        """
                        insert into calendar_events (title, start_time, end_time, all_day, memo, created_at)
                        values (%s, %s, %s, %s, %s, %s)
                        """,
                        (title, st, et, int(all_day or 0), memo, created_at),
                    )
                    inserted += 1

            conn.commit()
            if inserted:
                print(f"✅ migrated legacy events -> calendar_events: {inserted} rows")
    except Exception as e:
        print("⚠️ migrate_events_to_calendar_events_once failed:", e)


def ensure_db():
    """
    ✅ 중요:
    - 여기서 실패하면 polling 때문에 매 요청마다 다시 실행되어 서버가 점점 느려짐
    - 그래서 '필수 init_db'만 실패하면 죽고,
      '옵션 migrate'는 실패해도 _DB_READY는 True로 만들어서 서비스는 정상 동작하게 함
    """
    global _DB_READY
    if _DB_READY:
        return

    with _DB_LOCK:
        if _DB_READY:
            return

        # 1) 필수: 테이블 생성
        init_db()

        # 2) 옵션: 컬럼 보정 / 이관 (실패해도 서비스는 살아야 함)
        try:
            migrate_calendar_events_table()
        except Exception as e:
            print("⚠️ migrate_calendar_events_table failed:", e)

        try:
            migrate_events_to_calendar_events_once()
        except Exception as e:
            print("⚠️ migrate_events_to_calendar_events_once failed:", e)

        # ✅ 여기서 True로 고정 (다시 안 돌게)
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
# ✅ ROUTES
# ===============================
@app.route("/health", methods=["GET", "HEAD"])
def health():
    return ("", 200)


@app.route("/", methods=["GET", "POST", "HEAD"])
def index():
    if request.method == "HEAD":
        return ("", 200)

    ensure_db()

    if request.method == "POST":
        action = request.form.get("action")
        memo_keyword = request.form.get("memo_keyword", "").strip()

        if action == "add_memo" and memo_keyword:
            with db_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "insert into memos (content) values (%s) on conflict (content) do nothing",
                        (memo_keyword,),
                    )
                conn.commit()

        if action == "delete_memo" and memo_keyword:
            with db_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("delete from memos where content=%s", (memo_keyword,))
                conn.commit()

    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("select content from memos order by content")
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
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("select content from memos order by content")
            memo_list = [r[0] for r in cur.fetchall()]
    return jsonify({"ok": True, "memos": memo_list})


@app.route("/api/memos", methods=["POST"])
def api_add_memo():
    ensure_db()
    try:
        data = request.get_json() or {}
        content = (data.get("content") or "").strip()
        if not content:
            return jsonify({"ok": False, "error": "empty_content"}), 400

        with db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "insert into memos (content) values (%s) on conflict (content) do nothing",
                    (content,),
                )
            conn.commit()

        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/memos", methods=["DELETE"])
def api_delete_memo():
    ensure_db()
    try:
        data = request.get_json() or {}
        content = (data.get("content") or "").strip()
        if not content:
            return jsonify({"ok": False, "error": "empty_content"}), 400

        with db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("delete from memos where content=%s", (content,))
            conn.commit()

        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ===============================
# ✅ 캘린더 API (calendar_events)
# ===============================
@app.route("/api/events", methods=["GET"])
def get_events():
    ensure_db()
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select id, title, start_time, end_time, coalesce(all_day,0), memo from calendar_events order by id asc"
            )
            rows = cur.fetchall()

    return jsonify(
        [
            {
                "id": r[0],
                "title": r[1],
                "start": r[2].isoformat() if r[2] else None,
                "end": r[3].isoformat() if r[3] else None,
                "allDay": bool(r[4]),
                "extendedProps": {"memo": r[5] or ""},
            }
            for r in rows
        ]
    )


def _parse_incoming_dt(s: str):
    if not s:
        return None
    s = str(s).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    if len(s) == 10 and s.count("-") == 2:
        dt = datetime.fromisoformat(s + "T00:00:00")
        return tz.localize(dt)
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        return tz.localize(dt)
    return dt


@app.route("/api/events", methods=["POST"])
def add_event():
    ensure_db()
    try:
        data = request.get_json() or {}
        title = (data.get("title") or "").strip()
        start_raw = (data.get("start") or "").strip()
        if not title or not start_raw:
            return jsonify({"ok": False, "error": "title/start required"}), 400

        st = _parse_incoming_dt(start_raw)
        et = _parse_incoming_dt(data.get("end")) if data.get("end") else None
        memo = (data.get("memo") or "").strip()
        all_day = 1 if data.get("allDay") else 0

        with db_conn() as conn:
            with conn.cursor() as cur:
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
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/events/<int:event_id>", methods=["PUT"])
def update_event(event_id):
    ensure_db()
    try:
        data = request.get_json() or {}

        fields = []
        values = []

        if "title" in data:
            fields.append("title=%s")
            values.append((data.get("title") or "").strip())

        if "start" in data:
            fields.append("start_time=%s")
            values.append(_parse_incoming_dt(data.get("start")))

        if "end" in data:
            endv = data.get("end")
            fields.append("end_time=%s")
            values.append(_parse_incoming_dt(endv) if endv else None)

        if "memo" in data:
            fields.append("memo=%s")
            values.append((data.get("memo") or "").strip())

        if "allDay" in data:
            fields.append("all_day=%s")
            values.append(1 if data.get("allDay") else 0)

        if not fields:
            return jsonify({"ok": True})

        values.append(event_id)

        with db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"update calendar_events set {', '.join(fields)} where id=%s", values)
            conn.commit()

        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/events/<int:event_id>", methods=["DELETE"])
def delete_event(event_id):
    ensure_db()
    try:
        with db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("delete from calendar_events where id=%s", (event_id,))
            conn.commit()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ===============================
# ✅ 채팅 API
# ===============================
@app.route("/api/chat/messages", methods=["GET"])
def chat_messages():
    ensure_db()
    after_id = int(request.args.get("after_id", 0))
    room = (request.args.get("room") or "main").strip() or "main"

    with db_conn() as conn:
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
                {
                    "id": r[0],
                    "sender": r[1],
                    "message": r[2],
                    "created_at": r[3].isoformat() if r[3] else None,
                }
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

    with db_conn() as conn:
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
