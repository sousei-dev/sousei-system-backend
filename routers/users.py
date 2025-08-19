from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session, joinedload
from typing import Optional, List
from database import SessionLocal
from models import User, DatabaseLog
from schemas import UserCreate
from datetime import datetime
import uuid
import os
from supabase import create_client

router = APIRouter(prefix="/users", tags=["사용자 관리"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Supabase 설정
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase_storage = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY) if SUPABASE_SERVICE_KEY else None

@router.get("/")
def get_users(
    page: int = Query(1, description="페이지 번호", ge=1),
    page_size: int = Query(10, description="페이지당 항목 수", ge=1, le=100),
    db: Session = Depends(get_db)
):
    """사용자 목록 조회"""
    try:
        query = db.query(User)
        
        # 전체 항목 수 계산
        total_count = query.count()
        
        # 페이지네이션 적용
        users = query.offset((page - 1) * page_size).limit(page_size).all()
        
        # 전체 페이지 수 계산
        total_pages = (total_count + page_size - 1) // page_size
        
        # 응답 데이터 준비
        result = []
        for user in users:
            user_data = {
                "id": str(user.id),
                "name": user.name,
                "email": user.email,
                "role": user.role,
                "created_at": user.created_at
            }
            result.append(user_data)
        
        return {
            "items": result,
            "total": total_count,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_previous": page > 1
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"사용자 목록 조회 중 오류가 발생했습니다: {str(e)}")

@router.post("/")
def create_user(user: UserCreate, db: Session = Depends(get_db)):
    """새로운 사용자 생성"""
    try:
        # 이메일 중복 확인
        existing_user = db.query(User).filter(User.email == user.email).first()
        if existing_user:
            raise HTTPException(status_code=400, detail="이미 존재하는 이메일입니다")
        
        # 새 사용자 생성
        new_user = User(
            id=str(uuid.uuid4()),
            name=user.name,
            email=user.email,
            password=user.password,  # 실제로는 해시화해야 함
            role=user.role or "manager"
        )
        
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        
        return {
            "message": "사용자가 성공적으로 생성되었습니다",
            "user": {
                "id": str(new_user.id),
                "name": new_user.name,
                "email": new_user.email,
                "role": new_user.role
            }
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"사용자 생성 중 오류가 발생했습니다: {str(e)}")

@router.get("/profile")
def get_profile(db: Session = Depends(get_db)):
    """현재 사용자 프로필 조회"""
    try:
        # 실제로는 JWT 토큰에서 사용자 ID를 가져와야 함
        # 여기서는 임시로 첫 번째 사용자를 반환
        user = db.query(User).first()
        if not user:
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")
        
        return {
            "id": str(user.id),
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "created_at": user.created_at
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"프로필 조회 중 오류가 발생했습니다: {str(e)}")

@router.put("/profile")
def update_profile(
    name: Optional[str] = None,
    email: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """사용자 프로필 수정"""
    try:
        # 실제로는 JWT 토큰에서 사용자 ID를 가져와야 함
        user = db.query(User).first()
        if not user:
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")
        
        # 프로필 업데이트
        if name is not None:
            user.name = name
        if email is not None:
            # 이메일 중복 확인
            existing_user = db.query(User).filter(User.email == email, User.id != user.id).first()
            if existing_user:
                raise HTTPException(status_code=400, detail="이미 존재하는 이메일입니다")
            user.email = email
        
        db.commit()
        db.refresh(user)
        
        return {
            "message": "프로필이 성공적으로 업데이트되었습니다",
            "user": {
                "id": str(user.id),
                "name": user.name,
                "email": user.email,
                "role": user.role
            }
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"프로필 수정 중 오류가 발생했습니다: {str(e)}") 