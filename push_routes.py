# push_routes.py
from flask import Blueprint, jsonify, request
from pywebpush import webpush, WebPushException
import os
import json

push_bp = Blueprint("push", __name__)

# 🔑 Render 환경변수에서 불러옴 (반드시 Base64URL 형식)
VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY")
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY")
VAPID_SUBJECT = "mailto:admin@example.com"

# ⚠️ 테스트용 메모리 저장 (서버 재시작 시 초기화됨)
SUBSCRIPTIONS = []


@push_bp.route("/api/push/vapidPublicKey")
def vapid_public_key():
    if not VAPID_PUBLIC_KEY:
        return jsonify({"ok": False, "error": "VAPID_PUBLIC_KEY not set"}), 500

    return jsonify({
        "ok": True,
        "publicKey": VAPID_PUBLIC_KEY
    })


@push_bp.route("/api/push/subscribe", methods=["POST"])
def push_subscribe():
    data = request.get_json()
    subscription = data.get("subscription")

    if not subscription:
        return jsonify({"ok": False, "error": "no subscription"}), 400

    SUBSCRIPTIONS.append(subscription)
    return jsonify({"ok": True})


@push_bp.route("/api/push/test", methods=["POST"])
def push_test():
    payload = json.dumps({
        "title": "푸시 테스트 성공 🎉",
        "body": "iOS PWA 푸시가 정상 작동합니다",
        "url": "/"
    })

    for sub in SUBSCRIPTIONS:
        try:
            webpush(
                subscription_info=sub,
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": VAPID_SUBJECT},
            )
        except WebPushException as ex:
            print("WebPush error:", ex)

    return jsonify({"ok": True})
