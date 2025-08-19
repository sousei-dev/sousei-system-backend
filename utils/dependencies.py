from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from database import SessionLocal, engine
import os
from supabase import create_client

# Supabase 설정
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY) if SUPABASE_URL and SUPABASE_ANON_KEY else None

# JWT 토큰 검증을 위한 security
security = HTTPBearer()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """현재 인증된 사용자 정보 반환"""
    try:
        if not supabase:
            # Supabase 설정이 없는 경우 테스트용 더미 사용자 반환
            return {
                "id": "test-user-id",
                "email": "test@example.com",
                "role": "manager"
            }
        
        # JWT 토큰 검증
        token = credentials.credentials
        user = supabase.auth.get_user(token)
        
        if not user.user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="無効なトークンです"
            )
        
        # 사용자 프로필 정보 조회
        try:
            profile_response = supabase.table("profiles").select("name, role").eq("id", user.user.id).execute()
            profile_data = profile_response.data[0] if profile_response.data else {}
            
            return {
                "id": user.user.id,
                "email": user.user.email,
                "name": profile_data.get("name"),
                "role": profile_data.get("role", "manager")
            }
        except Exception:
            # 프로필 조회 실패 시 기본 정보만 반환
            return {
                "id": user.user.id,
                "email": user.user.email,
                "name": None,
                "role": "manager"
            }
            
    except Exception as e:
        if "Invalid JWT" in str(e) or "JWT expired" in str(e):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="トークンが期限切れまたは無効です"
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"認証エラー: {str(e)}"
            )

def get_db_session():
    """데이터베이스 세션 의존성"""
    return Depends(get_db) 