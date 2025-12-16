import os
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

def normalize_database_url(url: str) -> str:
    """
    Supabase Postgres는 보통 SSL이 필요.
    Render 환경변수 DATABASE_URL에 sslmode=require가 없으면 붙여준다.
    """
    if not url:
        return url

    # Render Postgres 스타일 postgres:// 를 postgresql:// 로 바꾸는 경우도 대비
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]

    # sslmode=require 보정
    if "sslmode=" not in url:
        joiner = "&" if "?" in url else "?"
        url = f"{url}{joiner}sslmode=require"

    return url

def get_database_uri() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        # 로컬 개발용(선택)
        return "sqlite:///local_dev.db"
    return normalize_database_url(url)
