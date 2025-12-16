import os
from datetime import datetime
from flask import Flask, jsonify, request
from flask_cors import CORS
import requests

from db import db, get_database_uri
from models import ChatMessage, Memo, CalendarEvent

def create_app():
    app = Flask(__name__)
    CORS(app, supports_credentials=True)

    app.config["SQLALCHEMY_DATABASE_URI"] = get_database_uri()
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Supabase/Render에서 커넥션 튐 줄이기용(가벼운 기본값)
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
        "pool_recycle": 280,   # 너무 길게 잡지 말기
    }

    db.init_app(app)

    with app.app_context():
        db.create_all()  # 초기 테이블 자동 생성(운영에서는 migrate 권장)

    # -------------------------
    # Health / Ping
    # -------------------------
    @app.get("/health")
    def health():
        return jsonify({"ok": True})

    # -------------------------
    # Rate (CNY) - 예시
    # 너가 기존에 시티은행 파싱 로직을 따로 갖고 있다면 여기만 교체하면 됨
    # -------------------------
    @app.get("/api/rate")
    def api_rate():
        """
        프론트 상단에 작은 텍스트로 보여줄 용도.
        여기서는 "예시"로만 둔다.
        (실제 시티은행 파싱 로직은 너 기존 코드로 옮겨 붙이면 됨)
        """
        try:
            # TODO: 너가 쓰는 시티은행 파싱 함수로 교체
            return jsonify({"currency": "CNY", "krw_per_cny": None, "source": "citibank", "note": "TODO: parser"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # -------------------------
    # Chat API
    # -------------------------
    @app.get("/api/chat/messages")
    def get_chat_messages():
        room = request.args.get("room", "default")
        limit = int(request.args.get("limit", "100"))
        limit = max(1, min(limit, 500))

        rows = (
            ChatMessage.query
            .filter_by(room=room)
            .order_by(ChatMessage.id.desc())
            .limit(limit)
            .all()
        )
        rows.reverse()
        return jsonify([r.to_dict() for r in rows])

    @app.post("/api/chat/messages")
    def post_chat_message():
        data = request.get_json(force=True) or {}
        room = (data.get("room") or "default").strip()
        sender = (data.get("sender") or "user").strip()
        message = (data.get("message") or "").strip()

        if not message:
            return jsonify({"error": "message is required"}), 400

        row = ChatMessage(room=room, sender=sender, message=message)
        db.session.add(row)
        db.session.commit()
        return jsonify(row.to_dict()), 201

    @app.delete("/api/chat/messages")
    def clear_chat_messages():
        room = request.args.get("room", "default")
        ChatMessage.query.filter_by(room=room).delete()
        db.session.commit()
        return jsonify({"ok": True})

    # -------------------------
    # Memo API
    # -------------------------
    @app.get("/api/memos")
    def list_memos():
        rows = Memo.query.order_by(Memo.pinned.desc(), Memo.updated_at.desc()).limit(500).all()
        return jsonify([r.to_dict() for r in rows])

    @app.post("/api/memos")
    def create_memo():
        data = request.get_json(force=True) or {}
        content = (data.get("content") or "").strip()
        pinned = bool(data.get("pinned", False))

        if not content:
            return jsonify({"error": "content is required"}), 400

        row = Memo(content=content, pinned=pinned)
        db.session.add(row)
        db.session.commit()
        return jsonify(row.to_dict()), 201

    @app.patch("/api/memos/<int:memo_id>")
    def update_memo(memo_id: int):
        data = request.get_json(force=True) or {}
        row = Memo.query.get_or_404(memo_id)

        if "content" in data:
            row.content = (data.get("content") or "").strip()
        if "pinned" in data:
            row.pinned = bool(data.get("pinned"))

        if not row.content:
            return jsonify({"error": "content is required"}), 400

        db.session.commit()
        return jsonify(row.to_dict())

    @app.delete("/api/memos/<int:memo_id>")
    def delete_memo(memo_id: int):
        row = Memo.query.get_or_404(memo_id)
        db.session.delete(row)
        db.session.commit()
        return jsonify({"ok": True})

    # -------------------------
    # Calendar API
    # -------------------------
    def _parse_dt(s: str) -> datetime:
        """
        프론트에서 ISO 문자열을 보내는 걸 가정.
        예: 2025-12-16T10:30:00 or 2025-12-16T10:30:00Z
        """
        s = (s or "").strip()
        if not s:
            raise ValueError("datetime string is required")

        # Z 제거
        if s.endswith("Z"):
            s = s[:-1]

        # fromisoformat은 "YYYY-MM-DDTHH:MM:SS" 지원
        return datetime.fromisoformat(s)

    @app.get("/api/calendar/events")
    def list_events():
        # 필요하면 기간 필터 추가 가능
        rows = CalendarEvent.query.order_by(CalendarEvent.start_at.asc()).limit(1000).all()
        return jsonify([r.to_dict() for r in rows])

    @app.post("/api/calendar/events")
    def create_event():
        data = request.get_json(force=True) or {}
        title = (data.get("title") or "").strip()
        note = (data.get("note") or "").strip()
        start_at = data.get("start_at")
        end_at = data.get("end_at")

        if not title:
            return jsonify({"error": "title is required"}), 400
        try:
            start_dt = _parse_dt(start_at)
            end_dt = _parse_dt(end_at) if end_at else None
        except Exception as e:
            return jsonify({"error": f"invalid datetime: {str(e)}"}), 400

        row = CalendarEvent(title=title, note=note, start_at=start_dt, end_at=end_dt)
        db.session.add(row)
        db.session.commit()
        return jsonify(row.to_dict()), 201

    @app.patch("/api/calendar/events/<int:event_id>")
    def update_event(event_id: int):
        data = request.get_json(force=True) or {}
        row = CalendarEvent.query.get_or_404(event_id)

        if "title" in data:
            row.title = (data.get("title") or "").strip()
        if "note" in data:
            row.note = (data.get("note") or "").strip()
        if "start_at" in data:
            try:
                row.start_at = _parse_dt(data.get("start_at"))
            except Exception as e:
                return jsonify({"error": f"invalid start_at: {str(e)}"}), 400
        if "end_at" in data:
            try:
                row.end_at = _parse_dt(data.get("end_at")) if data.get("end_at") else None
            except Exception as e:
                return jsonify({"error": f"invalid end_at: {str(e)}"}), 400

        if not row.title:
            return jsonify({"error": "title is required"}), 400

        db.session.commit()
        return jsonify(row.to_dict())

    @app.delete("/api/calendar/events/<int:event_id>")
    def delete_event(event_id: int):
        row = CalendarEvent.query.get_or_404(event_id)
        db.session.delete(row)
        db.session.commit()
        return jsonify({"ok": True})

    return app

app = create_app()

if __name__ == "__main__":
    # 로컬 실행용
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
