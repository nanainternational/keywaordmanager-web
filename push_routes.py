# push_routes.py
import os
import json
from flask import Blueprint, request, jsonify
from pywebpush import webpush, WebPushException

push_bp = Blueprint("push", __name__, url_prefix="/api/push")

# ✅ 임시: 서버 메모리에 저장 (Render 재시작되면 날아감)
# 일단 500 없애고 푸시 성공부터 확인하는 용도
_SUBS = {}  # endpoint -> subscription dict

def _normalize_subscription(payload):
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
    return jsonify({"ok": True, "saved": len(_SUBS), "endpoint": sub["endpoint"]})

@push_bp.route("/send-test", methods=["POST"])
def send_test():
    pub = (os.environ.get("VAPID_PUBLIC_KEY") or "").strip()
    priv = (os.environ.get("VAPID_PRIVATE_KEY") or "").strip()
    if not pub or not priv:
        return jsonify({"ok": False, "error": "VAPID keys missing"}), 500

    data = request.get_json(silent=True) or {}
    title = data.get("title") or "테스트 알림"
    body = data.get("body") or "푸시 테스트입니다."
    url = data.get("url") or "/"

    message = json.dumps({"title": title, "body": body, "url": url}, ensure_ascii=False)

    sent, failed = 0, 0
    for endpoint, sub in list(_SUBS.items()):
        try:
            webpush(
                subscription_info=sub,
                data=message,
                vapid_private_key=priv,
                vapid_claims={"sub": "mailto:secsiboy1@gmail.com"},
            )
            sent += 1
        except WebPushException:
            failed += 1
        except Exception:
            failed += 1

    return jsonify({"ok": True, "saved": len(_SUBS), "sent": sent, "failed": failed})

def send_push(payload: dict):
    # 서버 내부 호출용 (옵션)
    pub = (os.environ.get("VAPID_PUBLIC_KEY") or "").strip()
    priv = (os.environ.get("VAPID_PRIVATE_KEY") or "").strip()
    if not pub or not priv:
        return

    message = json.dumps(payload, ensure_ascii=False)

    for endpoint, sub in list(_SUBS.items()):
        try:
            webpush(
                subscription_info=sub,
                data=message,
                vapid_private_key=priv,
                vapid_claims={"sub": "mailto:admin@example.com"},
            )
        except Exception:
            pass
