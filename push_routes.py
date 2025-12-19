
from flask import Blueprint, jsonify, request
from pywebpush import webpush, WebPushException
import os, json

push_bp = Blueprint("push", __name__, url_prefix="/api/push")

VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY")
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY")
VAPID_CLAIMS = {"sub": "mailto:admin@example.com"}

SUBSCRIPTIONS = []

@push_bp.route("/vapidPublicKey")
def vapid_key():
    return jsonify({"ok": True, "publicKey": VAPID_PUBLIC_KEY})

@push_bp.route("/subscribe", methods=["POST"])
def subscribe():
    data = request.get_json()
    SUBSCRIPTIONS.append(data)
    return jsonify({"ok": True})

@push_bp.route("/test", methods=["POST"])
def test_push():
    payload = json.dumps({
        "title": "푸시 테스트",
        "body": "정상적으로 푸시가 도착했습니다"
    })

    for sub in SUBSCRIPTIONS:
        try:
            webpush(
                subscription_info=sub,
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS,
            )
        except WebPushException as e:
            print("Push failed:", e)

    return jsonify({"ok": True})
