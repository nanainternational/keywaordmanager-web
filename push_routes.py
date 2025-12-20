# push_routes.py
# DB-backed Web Push subscription routes (stable)

import os
import json
from flask import Blueprint, request, jsonify
from pywebpush import webpush, WebPushException

from db import get_conn

push_bp = Blueprint("push_bp", __name__)

VAPID_PUBLIC_KEY = (os.environ.get("VAPID_PUBLIC_KEY") or "").strip()
VAPID_PRIVATE_KEY = (os.environ.get("VAPID_PRIVATE_KEY") or "").strip()
VAPID_SUBJECT = (os.environ.get("VAPID_SUBJECT") or "mailto:secsiboy1@gmail.com").strip()


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


@push_bp.route("/api/push/subscribe", methods=["POST"])
def subscribe():
    data = request.get_json(force=True, silent=True) or {}
    sub = data.get("subscription")
    client_id = (data.get("client_id") or "").strip()
    platform = (data.get("platform") or "").strip()

    if not _is_valid_subscription(sub):
        return jsonify({"ok": False, "error": "invalid subscription"}), 400

    endpoint = sub.get("endpoint")
    sub_json = json.dumps(sub, ensure_ascii=False)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                insert into push_subscriptions (endpoint, subscription, client_id, platform, updated_at)
                values (%s, %s::jsonb, %s, %s, now())
                on conflict (endpoint)
                do update set
                    subscription=excluded.subscription,
                    client_id=excluded.client_id,
                    platform=excluded.platform,
                    updated_at=now()
                ''',
                (endpoint, sub_json, client_id, platform),
            )
        conn.commit()

    return jsonify({"ok": True})


@push_bp.route("/api/push/unsubscribe", methods=["POST"])
def unsubscribe():
    data = request.get_json(force=True, silent=True) or {}
    endpoint = (data.get("endpoint") or "").strip()
    if not endpoint:
        return jsonify({"ok": False, "error": "no endpoint"}), 400

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from push_subscriptions where endpoint=%s", (endpoint,))
        conn.commit()

    return jsonify({"ok": True})


@push_bp.route("/api/push/send-test", methods=["POST"])
def send_test():
    if not VAPID_PUBLIC_KEY or not VAPID_PRIVATE_KEY:
        return jsonify({"ok": False, "error": "missing VAPID keys"}), 500

    data = request.get_json(force=True, silent=True) or {}
    title = (data.get("title") or "Test").strip()
    body = (data.get("body") or "Hello").strip()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select endpoint, subscription from push_subscriptions order by updated_at desc limit 50"
            )
            rows = cur.fetchall()

    payload = json.dumps({"title": title, "body": body}, ensure_ascii=False).encode("utf-8")
    claims = {"sub": VAPID_SUBJECT}

    sent, failed = 0, 0
    for endpoint, sub_obj in rows:
        try:
            sub = json.loads(sub_obj) if isinstance(sub_obj, str) else sub_obj
            webpush(
                subscription_info=sub,
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=claims,
            )
            sent += 1
        except WebPushException:
            failed += 1
        except Exception:
            failed += 1

    return jsonify({"ok": True, "sent": sent, "failed": failed})
