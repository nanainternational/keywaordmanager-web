from flask import Blueprint, request, jsonify
from pywebpush import webpush
import os, json

push_bp = Blueprint("push", __name__)

VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY")
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY")

SUBS = []

@push_bp.route("/api/push/vapidPublicKey")
def key():
    return jsonify({"ok": True, "publicKey": VAPID_PUBLIC_KEY})

@push_bp.route("/api/push/subscribe", methods=["POST"])
def sub():
    SUBS.append(request.get_json())
    return jsonify({"ok": True})

@push_bp.route("/api/push/send-test", methods=["POST"])
def test():
    for s in SUBS:
        webpush(
            subscription_info=s,
            data=json.dumps({"title":"테스트","body":"푸시 도착"}),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub":"mailto:test@test.com"},
        )
    return jsonify({"ok": True})
