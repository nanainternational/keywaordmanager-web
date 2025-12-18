# push_routes.py
# Flask에 "그대로 붙여넣기" 가능한 라우트 모음
# 의존성: pywebpush, py-vapid
#
# iOS는 홈 화면에 추가된 PWA(standalone)에서 Web Push 가능
# Push API는 Service Worker가 필요
# VAPID 키는 py-vapid로 생성 가능

import os
import json
from flask import Blueprint, request, jsonify
from pywebpush import webpush, WebPushException

bp_push = Blueprint("bp_push", __name__)

VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "").strip()
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "mailto:admin@example.com").strip()

_SUBS = {}  # sender -> subscription dict

@bp_push.get("/api/push/vapidPublicKey")
def vapid_public_key():
    if not VAPID_PUBLIC_KEY:
        return jsonify(ok=False, error="VAPID_PUBLIC_KEY not set"), 500
    return jsonify(ok=True, publicKey=VAPID_PUBLIC_KEY)

@bp_push.post("/api/push/subscribe")
def push_subscribe():
    data = request.get_json(force=True, silent=True) or {}
    sender = (data.get("sender") or "").strip()
    sub = data.get("subscription")

    if not sender:
        return jsonify(ok=False, error="sender required"), 400
    if not isinstance(sub, dict) or not sub.get("endpoint"):
        return jsonify(ok=False, error="subscription required"), 400

    _SUBS[sender] = sub
    return jsonify(ok=True)

@bp_push.post("/api/push/test")
def push_test():
    data = request.get_json(force=True, silent=True) or {}
    sender = (data.get("sender") or "").strip()
    if not sender:
        return jsonify(ok=False, error="sender required"), 400

    sub = _SUBS.get(sender)
    if not sub:
        return jsonify(ok=False, error="no subscription for sender"), 404

    if not VAPID_PRIVATE_KEY:
        return jsonify(ok=False, error="VAPID_PRIVATE_KEY not set"), 500

    payload = {
        "title": "테스트 알림",
        "body": f"{sender}님, iOS PWA Web Push 테스트 성공!",
        "url": "/",
    }

    try:
        webpush(
            subscription_info=sub,
            data=json.dumps(payload),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": VAPID_SUBJECT},
        )
        return jsonify(ok=True)
    except WebPushException as e:
        return jsonify(ok=False, error=str(e)), 500
