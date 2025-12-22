# push_routes.py
import os
import json
import traceback
from flask import Blueprint, request, jsonify

import psycopg
from pywebpush import webpush

push_bp = Blueprint("push", __name__, url_prefix="/api/push")

# ✅ 구독 정보는 DB에 저장(서버 재시작에도 유지). 전송 시 메모리 캐시를 사용.
_SUBS = {}  # endpoint -> subscription dict (cache)

def _get_conn():
    db_url = (os.environ.get("DATABASE_URL") or "").strip()
    if not db_url:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg.connect(db_url, connect_timeout=10)

def _ensure_push_table():
    # keyword_manager_web.ensure_db()에서 만들지만, push 단독 호출 대비로 여기서도 보정
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    create table if not exists push_subscriptions(
                        endpoint text primary key,
                        subscription_json text not null,
                        created_at timestamptz not null default now()
                    )
                    """
                )
    except Exception:
        pass

def _save_sub_to_db(sub: dict):
    _ensure_push_table()
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into push_subscriptions(endpoint, subscription_json)
                    values(%s, %s)
                    on conflict (endpoint) do update
                    set subscription_json = excluded.subscription_json
                    """,
                    (sub.get("endpoint"), json.dumps(sub, ensure_ascii=False)),
                )
    except Exception:
        pass

def _load_subs_from_db():
    _ensure_push_table()
    subs = {}
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("select endpoint, subscription_json from push_subscriptions")
                rows = cur.fetchall()
        for endpoint, sub_json in rows:
            try:
                subs[endpoint] = json.loads(sub_json)
            except Exception:
                continue
    except Exception:
        return {}
    return subs

def _normalize_subscription(payload):
    """
    허용 형태:
      1) payload == subscription dict
      2) payload == { subscription: {...} }
    """
    if isinstance(payload, dict) and "endpoint" in payload and "keys" in payload:
        sub = payload
    elif isinstance(payload, dict) and "subscription" in payload and isinstance(payload["subscription"], dict):
        sub = payload["subscription"]
    else:
        return None, "invalid_payload"

    if not sub.get("endpoint"):
        return None, "missing_endpoint"
    if not isinstance(sub.get("keys"), dict):
        return None, "missing_keys"

    # keys: p256dh/auth 필수
    if not sub["keys"].get("p256dh") or not sub["keys"].get("auth"):
        return None, "missing_keys"
    return sub, None

@push_bp.route("/vapidPublicKey", methods=["GET"])
def vapid_public_key():
    pub = (os.environ.get("VAPID_PUBLIC_KEY") or "").strip()
    if not pub:
        return jsonify({"ok": False, "error": "VAPID_PUBLIC_KEY missing"}), 500
    return jsonify({"ok": True, "publicKey": pub})

@push_bp.route("/subscribe", methods=["POST"])
def subscribe():
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({"ok": False, "error": "invalid_json"}), 400

    sub, err = _normalize_subscription(payload)
    if err:
        return jsonify({"ok": False, "error": err, "received_keys": list(payload.keys())}), 400

    _SUBS[sub["endpoint"]] = sub
    _save_sub_to_db(sub)

    return jsonify({"ok": True, "saved": len(_SUBS), "endpoint": sub["endpoint"]})

def _send_payload_to_subs(payload: dict):
    pub = (os.environ.get("VAPID_PUBLIC_KEY") or "").strip()
    priv = (os.environ.get("VAPID_PRIVATE_KEY") or "").strip()
    if not pub or not priv:
        return {"ok": False, "error": "VAPID keys missing"}, 500

    vapid_sub = (os.environ.get("VAPID_SUB") or "mailto:secsiboy1@gmail.com").strip()
    if not vapid_sub.startswith("mailto:"):
        vapid_sub = "mailto:" + vapid_sub

    # ✅ 캐시가 비었으면 DB에서 로드
    if not _SUBS:
        _SUBS.update(_load_subs_from_db())

    message = json.dumps(payload, ensure_ascii=False)

    sent = 0
    failed = 0
    errors = []
    for endpoint, sub in list(_SUBS.items()):
        try:
            webpush(
                subscription_info=sub,
                data=message,
                vapid_private_key=priv,
                vapid_claims={"sub": vapid_sub},
            )
            sent += 1
        except Exception as e:
            failed += 1
            if len(errors) < 5:
                errors.append(str(e)[:300])

    return {"ok": True, "saved": len(_SUBS), "sent": sent, "failed": failed, "errors": errors}, 200

@push_bp.route("/send-test", methods=["POST"])
def send_test():
    payload = request.get_json(silent=True) or {}
    title = payload.get("title") or "푸시 테스트"
    body = payload.get("body") or "테스트 메시지"
    url = payload.get("url") or "/"
    return _send_payload_to_subs({"title": title, "body": body, "url": url, "type": "test"})

def notify_all(title: str, body: str, url: str = "/", extra: dict | None = None):
    payload = {"title": title, "body": body, "url": url, "type": "notify"}
    if extra and isinstance(extra, dict):
        payload.update(extra)
    # Flask route가 아니라도 전송 시도 (실패해도 앱 기능엔 영향 없게 조용히 처리)
    try:
        return _send_payload_to_subs(payload)[0]
    except Exception:
        return None
