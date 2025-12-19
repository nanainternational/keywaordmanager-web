# push_routes.py
from flask import Blueprint, request, jsonify
from pywebpush import webpush, WebPushException
import json
import os

push_bp = Blueprint("push", __name__)

VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY")
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY")
VAPID_CLAIMS = {
    "sub": "mailto:admin@example.com"
}

SUBSCRIPTIONS = []


@push_bp.route("/api/push/vapidPublicKey")
def vapid_public_key():
    return jsonify({"ok": True, "publicKey": VAPID_PUBLIC_KEY})


@push_bp.route("/api/push/subscribe", methods=["POST"])
def subscribe():
    sub = request.get_json()
    SUBSCRIPTIONS.append(sub)
    return jsonify({"ok": True})


def send_push(payload):
    for sub in SUBSCRIPTIONS:
        try:
            webpush(
                subscription_info=sub,
                data=json.dumps(payload),
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS,
            )
        except WebPushException as e:
            print("Push error:", e)


@push_bp.route("/api/push/send-test", methods=["POST"])
def send_test():
    send_push({
        "title": "푸시 테스트",
        "body": "정상적으로 푸시가 도착했습니다 🎉"
    })
    return jsonify({"ok": True})
