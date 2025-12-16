from datetime import datetime
from db import db

class ChatMessage(db.Model):
    __tablename__ = "chat_messages"
    id = db.Column(db.Integer, primary_key=True)
    room = db.Column(db.String(64), default="default", nullable=False)
    sender = db.Column(db.String(64), default="user", nullable=False)  # "user" / "bot" 등
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "room": self.room,
            "sender": self.sender,
            "message": self.message,
            "created_at": self.created_at.isoformat() + "Z",
        }

class Memo(db.Model):
    __tablename__ = "memos"
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    pinned = db.Column(db.Boolean, default=False, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "content": self.content,
            "pinned": self.pinned,
            "updated_at": self.updated_at.isoformat() + "Z",
            "created_at": self.created_at.isoformat() + "Z",
        }

class CalendarEvent(db.Model):
    __tablename__ = "calendar_events"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    note = db.Column(db.Text, default="", nullable=False)

    # start/end를 문자열로 보내는 프론트가 많아서, 서버는 UTC datetime으로 저장
    start_at = db.Column(db.DateTime, nullable=False)
    end_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "note": self.note,
            "start_at": self.start_at.isoformat() + "Z",
            "end_at": self.end_at.isoformat() + "Z" if self.end_at else None,
            "created_at": self.created_at.isoformat() + "Z",
        }
