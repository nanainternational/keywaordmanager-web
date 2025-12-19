# push_routes.py
# - /api/push/vapidPublicKey : VAPID 공개키 제공
# - /api/push/subscribe      : 구독 정보 저장(Upsert)
# - /api/push/test           : 저장된 구독자에게 테스트 푸시 전송
#
# ✅ 중요:
# - iOS/Safari는 applicationServerKey가 Uint8Array여야 함 (프론트에서 변환 필요)
# - 구독 정보는 메모리가 아니라 DB에 저장(재시작/멀티워커 대비)

import os
import json
import psycopg
from flask import Blueprint, jsonify, request
from pywebpush import webpush, WebPushException

push_bp = Blueprint("push", __name__, url_prefix="/api/push")

VAPID_PUBLIC_KEY = (os.environ.get("VAPID_PUBLIC_KEY") or "").strip()
VAPID_PRIVATE_KEY = (os.environ.get("VAPID_PRIVATE_KEY") or "").strip()

# 원하면 메일 주소를 바꿔도 됨
VAPID_CLAIMS = {"sub": "mailto:admin@example.com"}


def _get_conn():
    db_url = (os.environ.get("DATABASE_URL") or "").strip()
    if not db_url:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg.connect(db_url)


def _ensure_push_table():
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                create table if not exists push_subscriptions (
                    id bigserial primary key,
                    endpoint text unique,
                    sub jsonb not null,
                    created_at timestamptz default now()
                );
                """
            )
        conn.commit()


def _list_subscriptions():
    _ensure_push_table()
    subs = []
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("select sub from push_subscriptions order by id desc")
            for (sub,) in cur.fetchall():
                subs.append(sub)
    return subs


def _delete_subscription(endpoint: str):
    if not endpoint:
        return
    _ensure_push_table()
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from push_subscriptions where endpoint=%s", (endpoint,))
        conn.commit()


@push_bp.route("/vapidPublicKey", methods=["GET"])
def vapid_public_key():
    # 프론트에서 이 값이 없으면 구독 불가
    return jsonify({"ok": True, "publicKey": VAPID_PUBLIC_KEY})


@push_bp.route("/subscribe", methods=["POST"])
def subscribe():
    _ensure_push_table()
    data = request.get_json(silent=True) or {}

    endpoint = (data.get("endpoint") or "").strip()
    if not endpoint:
        return jsonify({"ok": False, "error": "missing_endpoint"}), 400

    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into push_subscriptions (endpoint, sub)
                values (%s, %s::jsonb)
                on conflict (endpoint) do update set sub=excluded.sub
                """,
                (endpoint, json.dumps(data)),
            )
        conn.commit()

    return jsonify({"ok": True})


def notify_all(title: str, body: str, url: str = "/"):
    """keyword_manager_web.py에서 import 해서 사용.
    - 실패해도 예외 던지지 않도록 내부에서 최대한 정리
    """
    if not VAPID_PUBLIC_KEY or not VAPID_PRIVATE_KEY:
        raise RuntimeError("VAPID keys are not set")

    payload = json.dumps(
        {
            "title": title or "알림",
            "body": body or "",
            "url": url or "/",
            "icon": "/static/icons/icon-192.png",
            "badge": "/static/icons/icon-192.png",
        },
        ensure_ascii=False,
    )

    subs = _list_subscriptions()

    for sub in subs:
        endpoint = (sub.get("endpoint") or "").strip()
        try:
            webpush(
                subscription_info=sub,
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS,
            )
        except WebPushException as e:
            # 구독 만료/삭제 필요 케이스가 많음: 404/410
            try:
                status = getattr(e.response, "status_code", None)
            except Exception:
                status = None

            print("[push] WebPushException:", e, "status:", status)

            if status in (404, 410):
                _delete_subscription(endpoint)
        except Exception as e:
            print("[push] send failed:", e)


@push_bp.route("/test", methods=["POST"])
def test_push():
    # 테스트용 푸시
    try:
        notify_all(title="푸시 테스트", body="정상적으로 푸시가 도착했습니다 ✅", url="/")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
