from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from database import SessionLocal, engine
from models import User, DatabaseLog
from schemas import UserCreate, UserLogin, ChangePasswordRequest, AdminResetPasswordRequest
from datetime import timedelta
import os
from supabase import create_client
from passlib.hash import bcrypt
from utils.dependencies import get_current_user
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["인증"])

# .env 파일에서 Supabase 설정 로드
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

# Supabase 설정 확인
if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    logger.error(f"Supabase 설정 오류 - URL: {SUPABASE_URL}, KEY: {'설정됨' if SUPABASE_ANON_KEY else '설정되지 않음'}")
    raise Exception("Supabase 설정이 올바르지 않습니다.")

logger.info(f"Supabase 설정 확인 - URL: {SUPABASE_URL}")

supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

# JWT 설정
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 7


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/login")
async def login(user: UserLogin):
    try:
        logger.info(f"로그인 시도 - 이메일: {user.email}")
        
        # Supabase Auth를 사용한 로그인
        auth_response = supabase.auth.sign_in_with_password({
            "email": user.email,
            "password": user.password
        })
        
        logger.info(f"Supabase 인증 성공 - 사용자 ID: {auth_response.user.id if auth_response.user else 'None'}")
        
        # 로그인 성공 시 사용자 정보 반환
        user_data = auth_response.user
        session = auth_response.session
        
        # 데이터베이스 로그 조회
        db = SessionLocal()
        try:
            # 모든 데이터베이스 로그 조회 (최신 100개)
            database_logs = db.query(DatabaseLog).order_by(DatabaseLog.created_at.desc()).limit(100).all()
            
            # 로그 데이터 포맷팅
            logs_data = []
            for log in database_logs:
                log_data = {
                    "id": str(log.id),
                    "table_name": log.table_name,
                    "record_id": log.record_id,
                    "action": log.action,
                    "user_id": log.user_id,
                    "old_values": log.old_values,
                    "new_values": log.new_values,
                    "changed_fields": log.changed_fields,
                    "ip_address": log.ip_address,
                    "user_agent": log.user_agent,
                    "note": log.note,
                    "created_at": log.created_at.isoformat() if log.created_at else None
                }
                logs_data.append(log_data)
        except Exception as log_error:
            logger.error(f"데이터베이스 로그 조회 중 오류: {str(log_error)}")
            logs_data = []
        finally:
            db.close()
        
        # 사용자 권한 정보 조회
        try:
            profile_response = supabase.table("profiles").select("name, role, department, position, avatar").eq("id", user_data.id).execute()
            profile_data = profile_response.data[0] if profile_response.data else {}
            
            return {
                "message": "ログインに成功しました",
                "user_id": user_data.id,
                "email": user_data.email,
                "name": profile_data.get("name"),
                "avatar": profile_data.get("avatar"),
                "department": profile_data.get("department"),
                "position": profile_data.get("position"),
                "role": profile_data.get("role", "manager"),
                "access_token": session.access_token,
                "refresh_token": session.refresh_token,
                "token_type": "bearer",
                "database_logs": logs_data,
                "total_logs": len(logs_data)
            }
        except Exception as profile_error:
            # 프로필 조회 실패 시 기본 정보만 반환
            return {
                "message": "ログインに成功しました",
                "user_id": user_data.id,
                "email": user_data.email,
                "name": None,
                "department": None,
                "position": None,
                "role": "manager",
                "access_token": session.access_token,
                "refresh_token": session.refresh_token,
                "token_type": "bearer",
                "database_logs": logs_data,
                "total_logs": len(logs_data)
            }
        
    except Exception as e:
        # Supabase Auth 에러 처리
        error_message = str(e)
        logger.error(f"로그인 실패 - 이메일: {user.email}, 오류: {error_message}")
        
        if "Invalid login credentials" in error_message:
            logger.warning(f"잘못된 로그인 자격증명 - 이메일: {user.email}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="이메일 또는 비밀번호가 올바르지 않습니다."
            )
        elif "Email not confirmed" in error_message:
            logger.warning(f"이메일 미인증 - 이메일: {user.email}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="이메일 인증이 필요합니다. 해결 방법: 1) Supabase 대시보드 → Authentication → Settings → 'Enable email confirmations' 체크 해제, 2) 또는 Authentication → Users에서 해당 사용자의 'Email confirmed'를 true로 변경"
            )
        else:
            logger.error(f"알 수 없는 로그인 오류 - 이메일: {user.email}, 오류: {error_message}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"로그인 중 오류가 발생했습니다: {error_message}"
            )

@router.post("/logout")
async def logout():
    try:
        # Supabase Auth를 사용한 로그아웃
        supabase.auth.sign_out()
        return {"message": "ログアウトに成功しました"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"로그아웃 중 오류가 발생했습니다: {str(e)}"
        )

@router.post("/refresh-token")
async def refresh_token(refresh_token: str):
    try:
        # Supabase Auth를 사용한 토큰 갱신
        auth_response = supabase.auth.refresh_session(refresh_token)
        session = auth_response.session
        
        # 새로운 사용자 정보 조회
        try:
            profile_response = supabase.table("profiles").select("name, role, department, position, avatar").eq("id", session.user.id).execute()
            profile_data = profile_response.data[0] if profile_response.data else {}
            
            return {
                "message": "토큰이 성공적으로 갱신되었습니다.",
                "user_id": session.user.id,
                "email": session.user.email,
                "name": profile_data.get("name"),
                "avatar": profile_data.get("avatar"),
                "department": profile_data.get("department"),
                "position": profile_data.get("position"),
                "role": profile_data.get("role", "manager"),
                "access_token": session.access_token,
                "refresh_token": session.refresh_token,
                "token_type": "bearer"
            }
        except Exception as profile_error:
            # 프로필 조회 실패 시 기본 정보만 반환
            return {
                "message": "토큰이 성공적으로 갱신되었습니다.",
                "user_id": session.user.id,
                "email": session.user.email,
                "name": None,
                "department": None,
                "position": None,
                "role": "manager",
                "access_token": session.access_token,
                "refresh_token": session.refresh_token,
                "token_type": "bearer"
            }
        
    except Exception as e:
        error_message = str(e)
        print(f"[DEBUG] Refresh token error: {error_message}")  # 디버깅용 로그 추가
        
        # Supabase의 실제 에러 메시지들을 더 정확하게 체크
        if any(keyword in error_message.lower() for keyword in [
            "invalid refresh token", 
            "already used", 
            "expired", 
            "invalid_grant",
            "refresh_token_not_found",
            "token_expired"
        ]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="리프레시 토큰이 만료되었거나 이미 사용되었습니다. 다시 로그인해주세요."
            )
        elif "invalid_request" in error_message.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="잘못된 요청입니다. 리프레시 토큰을 확인해주세요."
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"토큰 갱신 중 오류가 발생했습니다: {error_message}"
            )

@router.post("/signup")
async def signup(user: UserCreate):
    try:
        # Supabase Auth를 사용한 회원가입
        auth_response = supabase.auth.sign_up({
            "email": user.email,
            "password": user.password
        })
        
        user_data = auth_response.user
        
        # 사용자 프로필 정보 저장
        try:
            supabase.table("profiles").insert({
                "id": user_data.id,
                "name": user.name if hasattr(user, 'name') else None,
                "role": "manager"
            }).execute()
        except Exception as profile_error:
            print(f"프로필 생성 중 오류: {profile_error}")
        
        return {
            "message": "회원가입이 성공적으로 완료되었습니다.",
            "user_id": user_data.id,
            "email": user_data.email
        }
        
    except Exception as e:
        error_message = str(e)
        
        if "User already registered" in error_message:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="이미 등록된 이메일입니다."
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"회원가입 중 오류가 발생했습니다: {error_message}"
            )

@router.post("/change-password")
async def change_password(
    password_data: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    현재 로그인한 사용자의 비밀번호 변경
    - 현재 비밀번호 확인 필요
    - 새 비밀번호로 변경
    """
    try:
        # 현재 비밀번호로 재인증 (보안 강화)
        try:
            supabase.auth.sign_in_with_password({
                "email": current_user.get("email"),
                "password": password_data.current_password
            })
        except Exception as verify_error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="現在のパスワードが正しくありません"
            )
        
        # Supabase를 통해 비밀번호 변경
        try:
            # 새 비밀번호로 업데이트
            update_response = supabase.auth.update_user({
                "password": password_data.new_password
            })
            
            logger.info(f"비밀번호 변경 성공 - 사용자: {current_user.get('id')}")
            
            return {
                "message": "パスワードが正常に変更されました",
                "user_id": current_user.get("id"),
                "email": current_user.get("email")
            }
            
        except Exception as update_error:
            logger.error(f"비밀번호 변경 실패: {str(update_error)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"パスワード変更中にエラーが発生しました: {str(update_error)}"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"비밀번호 변경 중 오류: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"パスワード変更中にエラーが発生しました: {str(e)}"
        )

@router.post("/admin/reset-password")
async def admin_reset_password(
    reset_data: AdminResetPasswordRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    관리자가 다른 사용자의 비밀번호 재설정
    - 관리자 권한 필수 (admin만 가능)
    - 대상 사용자의 현재 비밀번호 불필요
    """
    try:
        # 관리자 권한 확인 (admin만 가능, manager는 불가)
        if current_user.get("role") != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="管理者権限が必要です"
            )
        
        # Supabase Admin API를 사용하여 비밀번호 재설정
        # Service Role Key가 필요합니다
        admin_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        
        if not admin_key:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="管理者APIキーが設定されていません"
            )
        
        # Admin 클라이언트 생성
        admin_supabase = create_client(SUPABASE_URL, admin_key)
        
        try:
            # Admin API를 사용하여 비밀번호 재설정
            admin_supabase.auth.admin.update_user_by_id(
                reset_data.user_id,
                {"password": reset_data.new_password}
            )
            
            logger.info(f"비밀번호 재설정 성공 - 대상 사용자: {reset_data.user_id}, 관리자: {current_user.get('id')}")
            
            return {
                "message": "パスワードが正常にリセットされました",
                "user_id": reset_data.user_id,
                "reset_by": current_user.get("id")
            }
            
        except Exception as reset_error:
            logger.error(f"비밀번호 재설정 실패: {str(reset_error)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"パスワードリセット中にエラーが発生しました: {str(reset_error)}"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"비밀번호 재설정 중 오류: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"パスワードリセット中にエラーが発生しました: {str(e)}"
        ) 