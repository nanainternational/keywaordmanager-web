import os
import re
import json
import threading
from datetime import datetime

from flask import Flask, request, jsonify, render_template, send_from_directory

# ✅ psycopg (v3)
import psycopg

# ✅ Web Push
from pywebpush import webpush, WebPushException

app = Flask(__name__)

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
                # ✅ client_id 컬럼 없으면 추가
                cur.execute(
                    """
                    select 1
                    from information_schema.columns
                    where table_schema='public' and table_name='chat_messages' and column_name='client_id'
                    """
                )
                if cur.fetchone() is None:
                    cur.execute("alter table chat_messages add column client_id text")

                # calendar_events
                cur.execute(
                    """
                    create table if not exists calendar_events(
                        id bigserial primary key,
                        title text,
                        start_at timestamptz,
                        end_at timestamptz,
                        memo text,
                        all_day int4 not null default 0,
                        created_at timestamptz not null default now()
                    )
                    """
                )

                # presence
                cur.execute(
                    """
                    create table if not exists presence(
                        client_id text primary key,
                        sender text,
                        animal text,
                        last_seen timestamptz not null default now(),
                        user_agent text
                    )
                    """
                )
                cur.execute("alter table presence add column if not exists sender text")
                cur.execute("alter table presence add column if not exists animal text")
                cur.execute("alter table presence add column if not exists last_seen timestamptz not null default now()")
                cur.execute("alter table presence add column if not exists user_agent text")

                # ✅ push_subscriptions (PWA 푸시 구독 저장)
                cur.execute(
                    """
                    create table if not exists push_subscriptions(
                        id bigserial primary key,
                        client_id text,
                        platform text,
                        endpoint text unique,
                        subscription jsonb not null,
                        created_at timestamptz not null default now(),
                        updated_at timestamptz not null default now()
                    )
                    """
                )

            conn.commit()

        _DB_READY = True


def _ensure_calendar_events_columns(cur):
    cur.execute(
        """
        select column_name
        from information_schema.columns
        where table_schema='public' and table_name='calendar_events'
        """
    )
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
        return dt.isoformat()
    except Exception:
        return None


# ===============================
# ✅ PWA (manifest / service worker)
# ===============================
@app.route("/service-worker.js")
def service_worker():
    return send_from_directory(
        "static",
        "service-worker.js",
        mimetype="application/javascript",
        max_age=0
    )

@app.route("/manifest.webmanifest")
def webmanifest():
    return send_from_directory(
        "static",
        "manifest.webmanifest",
        mimetype="application/manifest+json",
        max_age=0
    )


# ===============================
# ✅ VAPID / Admin Key
# ===============================
VAPID_PUBLIC_KEY = (os.environ.get("VAPID_PUBLIC_KEY") or "").strip()
VAPID_PRIVATE_KEY = (os.environ.get("VAPID_PRIVATE_KEY") or "").strip()
VAPID_SUBJECT = (os.environ.get("VAPID_SUBJECT") or "mailto:secsiboy1@gmail.com").strip()

ADMIN_PUSH_KEY = (os.environ.get("ADMIN_PUSH_KEY") or os.environ.get("ADMIN_PUSH_KEY".replace("PUSH_", "PUSH_")) or "").strip()
# 사용자 환경변수명이 ADMIN_PUSH_KEY로 되어있으면 그걸 쓰고, (혹시) ADMIN_KEY 같은 걸 쓰는 경우를 위해 아래도 허용
if not ADMIN_PUSH_KEY:
    ADMIN_PUSH_KEY = (os.environ.get("ADMIN_KEY") or os.environ.get("ADMIN_PUSH_KEY") or "").strip()


def _is_valid_subscription(sub):
    try:
        if not isinstance(sub, dict):
            return False
        if not sub.get("endpoint"):
            return False
        keys = sub.get("keys") or {}
        if not keys.get("p256dh") or not keys.get("auth"):
            return False
        return True
    except Exception:
        return False


def _require_admin_key():
    # 헤더 우선
    got = (request.headers.get("X-Admin-Key") or "").strip()
    if got and ADMIN_PUSH_KEY and got == ADMIN_PUSH_KEY:
        return True

    # (옵션) JSON body로도 받을 수 있게
    data = request.get_json(silent=True) or {}
    got2 = (data.get("admin_key") or "").strip()
    if got2 and ADMIN_PUSH_KEY and got2 == ADMIN_PUSH_KEY:
        return True

    return False


# ===============================
# ✅ Routes
# ===============================
@app.route("/")
def index():
    ensure_db()
    return render_template("index.html")


@app.route("/health")
def health():
    return "ok", 200


# -------------------------------
# ✅ Memo APIs
# -------------------------------
@app.route("/api/memos", methods=["GET"])
def api_memos_list():
    ensure_db()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("select id, content, created_at from memos order by id desc limit 200")
            rows = cur.fetchall()
    return jsonify([
        {"id": r[0], "content": r[1], "created_at": (r[2].isoformat() if r[2] else None)}
        for r in rows
    ])


@app.route("/api/memos", methods=["POST"])
def api_memos_add():
    ensure_db()
    data = request.get_json(force=True, silent=True) or {}
    content = (data.get("content") or "").strip()
    if not content:
        return jsonify({"ok": False, "error": "empty"}), 400

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into memos(content) values(%s) on conflict (content) do nothing",
                (content,)
            )
        conn.commit()

    return jsonify({"ok": True})


@app.route("/api/memos/<int:memo_id>", methods=["DELETE"])
def api_memos_del(memo_id):
    ensure_db()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from memos where id=%s", (memo_id,))
        conn.commit()
    return jsonify({"ok": True})


# -------------------------------
# ✅ Chat APIs
# -------------------------------
@app.route("/api/chat/messages", methods=["GET"])
def api_chat_messages():
    ensure_db()
    room = (request.args.get("room") or "main").strip()
    after_id = request.args.get("after_id")
    try:
        after_id = int(after_id) if after_id else 0
    except Exception:
        after_id = 0

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select id, room, sender, message, created_at, client_id
                from chat_messages
                where room=%s and id>%s
                order by id asc
                limit 200
                """,
                (room, after_id),
            )
            rows = cur.fetchall()

    return jsonify([
        {
            "id": r[0],
            "room": r[1],
            "sender": (r[2] or ""),
            "message": (r[3] or ""),
            "created_at": (r[4].isoformat() if r[4] else None),
            "client_id": (r[5] or ""),
        }
        for r in rows
    ])


@app.route("/api/chat/send", methods=["POST"])
def api_chat_send():
    ensure_db()
    data = request.get_json(force=True, silent=True) or {}
    room = (data.get("room") or "main").strip()
    sender = (data.get("sender") or "").strip()
    message = (data.get("message") or "").strip()
    client_id = (data.get("client_id") or "").strip()
    if not message:
        return jsonify({"ok": False, "error": "empty"}), 400

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into chat_messages(room, sender, message, client_id) values(%s,%s,%s,%s)",
                (room, sender, message, client_id),
            )
        conn.commit()

    return jsonify({"ok": True})


# -------------------------------
# ✅ Calendar APIs
# -------------------------------
@app.route("/api/events", methods=["GET"])
def api_events():
    ensure_db()
    with get_conn() as conn:
        with conn.cursor() as cur:
            _ensure_calendar_events_columns(cur)
            cur.execute(
                "select id, title, start_at, end_at, memo, all_day from calendar_events order by id desc limit 500"
            )
            rows = cur.fetchall()

    out = []
    for r in rows:
        all_day = (r[5] == 1)
        out.append(
            {
                "id": r[0],
                "title": (r[1] or ""),
                "start": _dt_to_fullcalendar(r[2], all_day),
                "end": _dt_to_fullcalendar(r[3], all_day),
                "memo": (r[4] or ""),
                "allDay": all_day,
            }
        )
    return jsonify(out)


@app.route("/api/events", methods=["POST"])
def api_events_add():
    ensure_db()
    data = request.get_json(force=True, silent=True) or {}
    title = (data.get("title") or "").strip()
    start = _parse_dt(data.get("start"))
    end = _parse_dt(data.get("end"))
    memo = (data.get("memo") or "").strip()
    all_day = 1 if bool(data.get("allDay")) else 0

    with get_conn() as conn:
        with conn.cursor() as cur:
            _ensure_calendar_events_columns(cur)
            cur.execute(
                "insert into calendar_events(title, start_at, end_at, memo, all_day) values(%s,%s,%s,%s,%s)",
                (title, start, end, memo, all_day),
            )
        conn.commit()
    return jsonify({"ok": True})


@app.route("/api/events/<int:event_id>", methods=["PUT"])
def api_events_update(event_id):
    ensure_db()
    data = request.get_json(force=True, silent=True) or {}
    title = (data.get("title") or "").strip()
    start = _parse_dt(data.get("start"))
    end = _parse_dt(data.get("end"))
    memo = (data.get("memo") or "").strip()
    all_day = 1 if bool(data.get("allDay")) else 0

    with get_conn() as conn:
        with conn.cursor() as cur:
            _ensure_calendar_events_columns(cur)
            cur.execute(
                "update calendar_events set title=%s, start_at=%s, end_at=%s, memo=%s, all_day=%s where id=%s",
                (title, start, end, memo, all_day, event_id),
            )
        conn.commit()
    return jsonify({"ok": True})


@app.route("/api/events/<int:event_id>", methods=["DELETE"])
def api_events_delete(event_id):
    ensure_db()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from calendar_events where id=%s", (event_id,))
        conn.commit()
    return jsonify({"ok": True})


# -------------------------------
# ✅ Presence APIs
# -------------------------------
@app.route("/api/presence/ping", methods=["POST"])
def api_presence_ping():
    ensure_db()
    data = request.get_json(force=True, silent=True) or {}
    client_id = (data.get("client_id") or "").strip()
    sender = (data.get("sender") or "").strip()
    animal = (data.get("animal") or "").strip()
    user_agent = (request.headers.get("User-Agent") or "").strip()

    if not client_id:
        return jsonify({"ok": False, "error": "no client_id"}), 400

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into presence(client_id, sender, animal, last_seen, user_agent)
                values(%s,%s,%s,now(),%s)
                on conflict (client_id)
                do update set sender=excluded.sender, animal=excluded.animal, last_seen=now(), user_agent=excluded.user_agent
                """,
                (client_id, sender, animal, user_agent),
            )
        conn.commit()
    return jsonify({"ok": True})


@app.route("/api/presence/list", methods=["GET"])
def api_presence_list():
    ensure_db()
    minutes = request.args.get("minutes")
    try:
        minutes = int(minutes) if minutes else 10
    except Exception:
        minutes = 10

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select client_id, sender, animal, last_seen
                from presence
                where last_seen > now() - (%s || ' minutes')::interval
                order by last_seen desc
                limit 200
                """,
                (minutes,),
            )
            rows = cur.fetchall()

    return jsonify(
        [
            {
                "client_id": r[0],
                "sender": (r[1] or ""),
                "animal": (r[2] or ""),
                "last_seen": r[3].isoformat() if r[3] else None
            }
            for r in rows
        ]
    )


# -------------------------------
# ✅ Push Subscription APIs
# -------------------------------
@app.route("/api/push/subscribe", methods=["POST"])
def api_push_subscribe():
    ensure_db()
    data = request.get_json(force=True, silent=True) or {}
    client_id = (data.get("client_id") or "").strip()
    platform = (data.get("platform") or "").strip()
    sub = data.get("subscription")

    if not _is_valid_subscription(sub):
        return jsonify({"ok": False, "error": "invalid subscription"}), 400

    endpoint = sub.get("endpoint")

    # psycopg jsonb: dict -> json string
    sub_json = json.dumps(sub, ensure_ascii=False)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into push_subscriptions (client_id, platform, endpoint, subscription, updated_at)
                values (%s,%s,%s,%s::jsonb, now())
                on conflict (endpoint)
                do update set client_id=excluded.client_id,
                              platform=excluded.platform,
                              subscription=excluded.subscription,
                              updated_at=now()
                """,
                (client_id, platform, endpoint, sub_json),
            )
        conn.commit()

    return jsonify({"ok": True})


@app.route("/api/push/unsubscribe", methods=["POST"])
def api_push_unsubscribe():
    ensure_db()
    data = request.get_json(force=True, silent=True) or {}
    endpoint = (data.get("endpoint") or "").strip()
    if not endpoint:
        return jsonify({"ok": False, "error": "no endpoint"}), 400

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from push_subscriptions where endpoint=%s", (endpoint,))
        conn.commit()

    return jsonify({"ok": True})


# -------------------------------
# ✅ Admin Push Send API (완성본)
# -------------------------------
@app.route("/api/admin/push/send", methods=["POST"])
def api_admin_push_send():
    ensure_db()

    # 1) 관리자 키 체크
    if not _require_admin_key():
        return jsonify({"ok": False, "error": "forbidden"}), 403

    # 2) 입력 파라미터
    data = request.get_json(force=True, silent=True) or {}
    title = (data.get("title") or "").strip()
    body = (data.get("body") or "").strip()
    platform = (data.get("platform") or "").strip().lower()     # "ios" | "android" | ""
    client_id = (data.get("client_id") or "").strip()

    if not title and not body:
        return jsonify({"ok": False, "error": "empty payload"}), 400

    # 3) VAPID 키 체크
    if not VAPID_PUBLIC_KEY or not VAPID_PRIVATE_KEY:
        return jsonify({"ok": False, "error": "missing VAPID keys"}), 500

    # 4) 대상 구독 조회
    where = []
    params = []

    if platform:
        where.append("platform=%s")
        params.append(platform)

    if client_id:
        where.append("client_id=%s")
        params.append(client_id)

    sql = "select endpoint, subscription, client_id, platform from push_subscriptions"
    if where:
        sql += " where " + " and ".join(where)
    sql += " order by updated_at desc limit 1000"

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()

    # 5) 구독이 0개면 500 내지 말고 정상 응답
    if not rows:
        return jsonify({"ok": True, "sent": 0, "failed": 0, "detail": [], "note": "no subscriptions"}), 200

    payload = {
        "title": title,
        "body": body,
    }
    payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    vapid_claims = {"sub": VAPID_SUBJECT}

    sent = 0
    failed = 0
    detail = []

    # 6) 발송: 한 건 실패해도 전체 500 터지지 않게 try/except
    for endpoint, sub_obj, cid, plat in rows:
        try:
            # psycopg jsonb -> dict 로 오는 경우/str로 오는 경우 모두 처리
            if isinstance(sub_obj, str):
                sub = json.loads(sub_obj)
            else:
                sub = sub_obj  # dict 기대

            # 최소 유효성 확인
            if not _is_valid_subscription(sub):
                failed += 1
                detail.append({"endpoint": endpoint, "client_id": cid, "platform": plat, "ok": False, "error": "invalid subscription"})
                continue

            webpush(
                subscription_info=sub,
                data=payload_bytes,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=vapid_claims,
            )
            sent += 1
            detail.append({"endpoint": endpoint, "client_id": cid, "platform": plat, "ok": True})

        except WebPushException as e:
            failed += 1
            msg = str(e)
            # 너무 길면 잘라서 저장
            if len(msg) > 300:
                msg = msg[:300] + "..."
            detail.append({"endpoint": endpoint, "client_id": cid, "platform": plat, "ok": False, "error": msg})

        except Exception as e:
            failed += 1
            msg = f"{type(e).__name__}: {e}"
            if len(msg) > 300:
                msg = msg[:300] + "..."
            detail.append({"endpoint": endpoint, "client_id": cid, "platform": plat, "ok": False, "error": msg})

    return jsonify({"ok": True, "sent": sent, "failed": failed, "detail": detail}), 200


if __name__ == "__main__":
    # 로컬 실행용
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
