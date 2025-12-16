from flask import Flask, render_template, request, jsonify
from datetime import datetime
import pytz
import os
import requests
from bs4 import BeautifulSoup
from flask_cors import CORS

# ✅ Postgres(Supabase) 연결용
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
import psycopg

app = Flask(__name__)
CORS(app)

tz = pytz.timezone("Asia/Seoul")


def _safe_mkdir(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        testfile = os.path.join(path, ".write_test")
        with open(testfile, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(testfile)
        return True
    except Exception as e:
        print(f"⚠️ Dir not writable: {path} ({e})")
        return False


# ===============================
# ✅ DB URL (Supabase Postgres)
# - Render에 DATABASE_URL을 권장
# - 이미 DATABASE_URLSupabase로 넣었다면 그것도 허용
# ===============================
def _get_database_url():
    url = (os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_URLSupabase") or "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL(또는 DATABASE_URLSupabase) 환경변수가 없습니다. Render Environment에 설정하세요.")

    # postgres:// -> postgresql:// 정규화
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]

    # sslmode=require 강제(없으면 추가)
    u = urlparse(url)
    q = dict(parse_qsl(u.query))
    if "sslmode" not in q:
        q["sslmode"] = "require"
        u = u._replace(query=urlencode(q))
        url = urlunparse(u)

    return url


def get_conn():
    return psycopg.connect(_get_database_url())


# ===============================
# ✅ DB 초기화 (Supabase에 테이블/인덱스 보장)
# ===============================
def init_db():
    ddl = """
    -- ✅ 메모(키워드) : 기존 Supabase에서 memos(id, content, created_at)로 만든 상태도 그대로 사용
    create table if not exists memos (
        id bigserial primary key,
        content text not null,
        created_at timestamptz default now()
    );
    create unique index if not exists memos_content_uq on memos(content);

    -- ✅ 캘린더 이벤트(프론트 호환 위해 events 테이블 유지)
    create table if not exists events (
        id bigserial primary key,
        title text not null,
        start text not null,
        end text,
        all_day integer default 0,
        memo text,
        created_at timestamptz default now()
    );

    -- ✅ 채팅
    create table if not exists chat_messages (
        id bigserial primary key,
        room text default 'main',
        sender text,
        message text not null,
        created_at timestamptz default now()
    );
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(ddl)
        conn.commit()


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
# ✅ 메인
# ===============================
@app.route("/", methods=["GET", "POST", "HEAD"])
def index():
    init_db()

    if request.method == "POST":
        action = request.form.get("action")
        memo_keyword = request.form.get("memo_keyword", "").strip()

        if action == "add_memo" and memo_keyword:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "insert into memos (content) values (%s) on conflict (content) do nothing",
                        (memo_keyword,),
                    )
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
# ✅ 캘린더 API
# ===============================
@app.route("/api/events", methods=["GET"])
def get_events():
    init_db()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("select id, title, start, end, all_day, memo from events")
            rows = cur.fetchall()

    return jsonify(
        [
            {
                "id": r[0],
                "title": r[1],
                "start": r[2],
                "end": r[3],
                "allDay": bool(r[4]),
                "extendedProps": {"memo": r[5] or ""},
            }
            for r in rows
        ]
    )


@app.route("/api/events", methods=["POST"])
def add_event():
    init_db()
    data = request.get_json() or {}

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into events (title, start, end, all_day, memo, created_at)
                values (%s, %s, %s, %s, %s, %s)
                returning id
                """,
                (
                    data.get("title", ""),
                    data.get("start", ""),
                    data.get("end"),
                    1 if data.get("allDay") else 0,
                    data.get("memo", ""),
                    datetime.now(tz),
                ),
            )
            event_id = cur.fetchone()[0]
        conn.commit()

    return jsonify({"ok": True, "id": event_id})


@app.route("/api/events/<int:event_id>", methods=["PUT"])
def update_event(event_id):
    init_db()
    data = request.get_json() or {}

    fields = []
    values = []

    for key, col in [("title", "title"), ("start", "start"), ("end", "end"), ("memo", "memo")]:
        if key in data:
            fields.append(f"{col}=%s")
            values.append(data[key])

    if "allDay" in data:
        fields.append("all_day=%s")
        values.append(1 if data["allDay"] else 0)

    if not fields:
        return jsonify({"ok": True})

    values.append(event_id)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"update events set {', '.join(fields)} where id=%s", values)
        conn.commit()

    return jsonify({"ok": True})


@app.route("/api/events/<int:event_id>", methods=["DELETE"])
def delete_event(event_id):
    init_db()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from events where id=%s", (event_id,))
        conn.commit()
    return jsonify({"ok": True})


# ===============================
# ✅ 채팅 API
# ===============================
@app.route("/api/chat/messages", methods=["GET"])
def chat_messages():
    init_db()
    after_id = int(request.args.get("after_id", 0))

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select id, sender, message, created_at
                from chat_messages
                where id > %s
                order by id asc
                """,
                (after_id,),
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
    init_db()
    data = request.get_json() or {}

    sender = (data.get("sender") or "익명").strip()
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"ok": False, "error": "empty_message"}), 400

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into chat_messages (room, sender, message, created_at)
                values (%s, %s, %s, %s)
                returning id
                """,
                ("main", sender, message, datetime.now(tz)),
            )
            msg_id = cur.fetchone()[0]
        conn.commit()

    return jsonify({"ok": True, "id": msg_id})


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
