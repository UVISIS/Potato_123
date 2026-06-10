"""
functions/db.py — Supabase 싱글턴 클라이언트

모든 fn 함수가 get_client() 로 동일 인스턴스를 공유한다.
환경변수(.env):
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY

※ 이 파일은 업로드 스크립트가 '리포에 db.py 가 없을 때만' 복사한다(cp -n).
  기존 db.py 가 있으면 덮어쓰지 않는다.
"""

from __future__ import annotations
import os
from functools import lru_cache

from supabase import create_client, Client

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


@lru_cache(maxsize=1)
def get_client() -> "Client":
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 환경변수가 필요합니다. "
            ".env 파일을 확인하세요."
        )
    return create_client(url, key)
