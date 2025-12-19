import os
import json
from datetime import datetime

import psycopg
from flask import Blueprint, request, jsonify
from pywebpush import webpush, WebPushException


push_bp = Blueprint("push", __name__)


# ===============================
# ✅ VAPID (Render 환경변수로 관리)
# ===============================
VAPID_PUBLIC_KEY = (os.environ.get("VAPID_PUBLIC_KEY") or "").strip()
VAPID_PRIVATE_KEY = (os.environ.get("VAPID_PRIVATE_KEY") or "").strip()

# 메일은 아무거나여도 동작하지만, 운영에선 본인 이메일로 바꾸는걸 권장
VAPID_CLAIMS = {"sub": os.environ.get("VAPID_SUBJECT") or "mailto:admin@example.com"}


# ===============================
# ✅ DB 연결 (keyword_manager_web.py와 독립 동작)
# ===============================
def get_conn():
    db_url = (os.environ.get("DATABASE_URL") or "").strip()
    if not db_url:
        raise RuntimeError("DATABASE_URL is missing")
    # Supabase pooler/sslmode=require 그대로 사용
    return psycopg.connect(db_url)


def ensure_push_table():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                create table if not exists push_subscriptions(
                    id bigserial primary key,
                    endpoint text unique,
                    p256dh text,
                    auth text,
                    created_at timestamptz not null default now()
                )
                """
            )
        conn.commit()


def _upsert_subscription(sub: dict):
    endpoint = (sub.get("endpoint") or "").strip()
    keys = sub.get("keys") or {}
    p256dh = (keys.get("p256dh") or "").strip()
    auth = (keys.get("auth") or "").strip()

    if not endpoint or not p256dh or not auth:
        raise ValueError("invalid subscription (missing endpoint/keys)")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into push_subscriptions(endpoint, p256dh, auth)
                values (%s, %s, %s)
                on conflict(endpoint) do update
                set p256dh=excluded.p256dh, auth=excluded.auth
                """,
                (endpoint, p256dh, auth),
            )
        conn.commit()


def _load_subscriptions():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("select endpoint, p256dh, auth from push_subscriptions order by id desc")
            rows = cur.fetchall()

    subs = []
    for r in rows:
        subs.append(
            {
                "endpoint": r[0],
                "keys": {"p256dh": r[1], "auth": r[2]},
            }
        )
    return subs


# ===============================
# ✅ API
# ===============================
@push_bp.route("/api/push/vapidPublicKey", methods=["GET"])
def api_vapid_key():
    # 프론트에서 base64url 형태의 publicKey만 필요
    return jsonify({"ok": True, "publicKey": VAPID_PUBLIC_KEY})


@push_bp.route("/api/push/subscribe", methods=["POST"])
def api_subscribe():
    ensure_push_table()
    sub = request.get_json(silent=True) or {}
    try:
        _upsert_subscription(sub)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


def send_push(payload: dict):
    """
    keyword_manager_web.py에서 import 해서 호출:
      send_push({"title":"...", "body":"...", "url":"/"})
    """
    if not VAPID_PRIVATE_KEY or not VAPID_PUBLIC_KEY:
        raise RuntimeError("VAPID keys are missing")

    ensure_push_table()
    subs = _load_subscriptions()

    data = json.dumps(payload, ensure_ascii=False)

    for sub in subs:
        try:
            webpush(
                subscription_info=sub,
                data=data,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS,
            )
        except WebPushException as e:
            # 만료/삭제된 구독은 나중에 정리하는 방식으로 두고, 우선 로그만 찍음
            print("[push] WebPushException:", e)
        except Exception as e:
            print("[push] send error:", e)


@push_bp.route("/api/push/send-test", methods=["POST"])
def api_send_test():
    try:
        send_push(
            {
                "title": "푸시 테스트",
                "body": "정상적으로 푸시가 도착했습니다 🎉",
                "url": "/",
                "ts": datetime.utcnow().isoformat(),
            }
        )
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
