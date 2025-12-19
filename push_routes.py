# push_routes.py
import os
import json
import traceback
from flask import Blueprint, request, jsonify

from pywebpush import webpush, WebPushException

push_bp = Blueprint("push", __name__, url_prefix="/api/push")

# ✅ 임시: 서버 메모리에 저장 (Render 재시작되면 날아감)
_SUBS = {}  # endpoint -> subscription dict


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
    """
    - ok: HTTP 처리 성공 여부
    - saved: 현재 서버가 기억 중인 구독 개수
    - sent/failed: 실제 전송 성공/실패 카운트
    - errors: 실패 원인(최대 5개) -> Render 로그 없이도 원인 확인 가능
    """
    pub = (os.environ.get("VAPID_PUBLIC_KEY") or "").strip()
    priv = (os.environ.get("VAPID_PRIVATE_KEY") or "").strip()
    if not pub or not priv:
        return jsonify({"ok": False, "error": "VAPID keys missing"}), 500

    # ✅ vapid subject: 실제 이메일(권장). 환경변수로 바꿀 수 있게 함.
    vapid_sub = (os.environ.get("VAPID_SUB") or "mailto:push@nanainter.com").strip()
    if not vapid_sub.startswith("mailto:"):
        vapid_sub = "mailto:" + vapid_sub

    data = request.get_json(silent=True) or {}
    title = data.get("title") or "테스트 알림"
    body = data.get("body") or "푸시 테스트입니다."
    url = data.get("url") or "/"

    message = json.dumps({"title": title, "body": body, "url": url}, ensure_ascii=False)

    sent, failed = 0, 0
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
        except WebPushException as e:
            failed += 1
            err_msg = f"WebPushException: {repr(e)}"
            errors.append(err_msg)

            # ✅ Render 로그에도 남김
            print(err_msg)

            # 일부 예외는 response 객체에 자세한 이유가 들어옴
            try:
                if hasattr(e, "response") and e.response is not None:
                    print("WebPushException.response.status_code:", getattr(e.response, "status_code", None))
                    print("WebPushException.response.text:", getattr(e.response, "text", None))
            except Exception:
                pass
        except Exception as e:
            failed += 1
            tb = traceback.format_exc()
            err_msg = f"Exception: {repr(e)}"
            errors.append(err_msg)
            print(err_msg)
            print(tb)

    errors = errors[:5]
    return jsonify({"ok": True, "saved": len(_SUBS), "sent": sent, "failed": failed, "errors": errors})


def send_push(payload: dict):
    """
    서버 내부에서 호출용 (예: 새 채팅 메시지 발생 시 푸시)
    """
    priv = (os.environ.get("VAPID_PRIVATE_KEY") or "").strip()
    if not priv:
        return

    vapid_sub = (os.environ.get("VAPID_SUB") or "mailto:push@nanainter.com").strip()
    if not vapid_sub.startswith("mailto:"):
        vapid_sub = "mailto:" + vapid_sub

    message = json.dumps(payload, ensure_ascii=False)

    for endpoint, sub in list(_SUBS.items()):
        try:
            webpush(
                subscription_info=sub,
                data=message,
                vapid_private_key=priv,
                vapid_claims={"sub": vapid_sub},
            )
        except Exception:
            pass
