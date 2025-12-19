# push_routes.py
import os
import json
from datetime import datetime

from flask import Blueprint, request, jsonify

try:
    import psycopg
except Exception:
    psycopg = None

from pywebpush import webpush, WebPushException

push_bp = Blueprint("push", __name__, url_prefix="/api/push")

def _get_conn():
    db_url = (os.environ.get("DATABASE_URL") or "").strip()
    if not db_url:
        raise RuntimeError("DATABASE_URL not set")
    if psycopg is None:
        raise RuntimeError("psycopg not available")
    return psycopg.connect(db_url, connect_timeout=10)

def _ensure_table():
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                create table if not exists push_subscriptions (
                    endpoint text primary key,
                    sub_json text not null,
                    created_at timestamptz not null default now()
                )
                """
            )
        conn.commit()

def _normalize_subscription(payload):
    """
    허용 형태:
      1) payload == subscription dict
      2) payload == {"subscription": subscription dict}
      3) payload == {"sub": subscription dict}
    """
    if not isinstance(payload, dict):
        return None, "payload_not_object"

    sub = payload.get("subscription") or payload.get("sub") or payload

    if not isinstance(sub, dict):
        return None, "subscription_not_object"

    endpoint = sub.get("endpoint")
    keys = sub.get("keys") or {}
    p256dh = keys.get("p256dh")
    auth = keys.get("auth")

    if not endpoint:
        return None, "missing_endpoint"
    if not p256dh or not auth:
        return None, "missing_keys"

    # expirationTime은 없어도 됨
    return sub, None

@push_bp.route("/vapidPublicKey", methods=["GET"])
def vapid_public_key():
    pub = (os.environ.get("VAPID_PUBLIC_KEY") or "").strip()
    if not pub:
        return jsonify({"ok": False, "error": "VAPID_PUBLIC_KEY missing"}), 500
    return jsonify({"ok": True, "publicKey": pub})

@push_bp.route("/subscribe", methods=["POST"])
def subscribe():
    _ensure_table()
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({"ok": False, "error": "invalid_json"}), 400

    sub, err = _normalize_subscription(payload)
    if err:
        return jsonify({"ok": False, "error": err, "received_keys": list(payload.keys())}), 400

    endpoint = sub["endpoint"]
    sub_json = json.dumps(sub, ensure_ascii=False)

    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into push_subscriptions (endpoint, sub_json, created_at)
                values (%s, %s, now())
                on conflict (endpoint) do update
                set sub_json = excluded.sub_json,
                    created_at = now()
                """,
                (endpoint, sub_json),
            )
        conn.commit()

    return jsonify({"ok": True, "endpoint": endpoint})

@push_bp.route("/send-test", methods=["POST"])
def send_test():
    _ensure_table()

    pub = (os.environ.get("VAPID_PUBLIC_KEY") or "").strip()
    priv = (os.environ.get("VAPID_PRIVATE_KEY") or "").strip()
    if not pub or not priv:
        return jsonify({"ok": False, "error": "VAPID keys missing"}), 500

    data = request.get_json(silent=True) or {}
    title = data.get("title") or "테스트 알림"
    body = data.get("body") or "푸시 테스트입니다."
    url = data.get("url") or "/"

    message = json.dumps({"title": title, "body": body, "url": url}, ensure_ascii=False)

    sent = 0
    failed = 0

    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("select endpoint, sub_json from push_subscriptions")
            rows = cur.fetchall()

    for endpoint, sub_json in rows:
        try:
            sub = json.loads(sub_json)
            webpush(
                subscription_info=sub,
                data=message,
                vapid_private_key=priv,
                vapid_claims={"sub": "mailto:admin@example.com"},
            )
            sent += 1
        except WebPushException:
            failed += 1
        except Exception:
            failed += 1

    return jsonify({"ok": True, "sent": sent, "failed": failed})

def send_push(payload: dict):
    """
    서버 내부에서 호출용 (채팅 메시지 알림 등)
    """
    _ensure_table()

    pub = (os.environ.get("VAPID_PUBLIC_KEY") or "").strip()
    priv = (os.environ.get("VAPID_PRIVATE_KEY") or "").strip()
    if not pub or not priv:
        return

    message = json.dumps(payload, ensure_ascii=False)

    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("select sub_json from push_subscriptions")
            rows = cur.fetchall()

    for (sub_json,) in rows:
        try:
            sub = json.loads(sub_json)
            webpush(
                subscription_info=sub,
                data=message,
                vapid_private_key=priv,
                vapid_claims={"sub": "mailto:admin@example.com"},
            )
        except Exception:
            pass
