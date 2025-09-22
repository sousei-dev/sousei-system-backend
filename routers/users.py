from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session, joinedload
from typing import Optional, List
from database import SessionLocal
from models import User, DatabaseLog, Profiles
from schemas import UserCreate
from datetime import datetime
import uuid
import os
from supabase import create_client
import random
import string
from utils.dependencies import get_current_user
from database_log import create_database_log

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

def generate_random_filename(original_filename: str) -> str:
    """원본 파일명을 기반으로 랜덤한 영어 파일명 생성"""
    # 파일 확장자 추출
    file_extension = original_filename.split(".")[-1].lower()
    
    # 랜덤 문자열 생성 (16자리)
    random_string = ''.join(random.choices(string.ascii_lowercase + string.digits, k=16))
    
    # 새로운 파일명 생성: 랜덤문자열.확장자
    new_filename = f"{random_string}.{file_extension}"
    
    return new_filename

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
        user = db.query(Profiles).first()
        if not user:
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")
        
        # 프로필 업데이트
        if name is not None:
            user.name = name
        
        db.commit()
        db.refresh(user)
        
        return {
            "message": "프로필이 성공적으로 업데이트되었습니다",
            "user": {
                "id": str(user.id),
                "name": user.name,
                "role": user.role
            }
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"프로필 수정 중 오류가 발생했습니다: {str(e)}") 

@router.post("/changeAvatar")
async def upload_user_avatar(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """사용자 아바타 업로드"""
    try:
        # 로그인한 사용자 ID 사용
        user_id = current_user["id"]
        
        # 사용자 존재 여부 확인
        profiles = db.query(Profiles).filter(Profiles.id == user_id).first()
        if not profiles:
            raise HTTPException(
                status_code=404,
                detail="사용자를 찾을 수 없습니다."
            )

        # 파일 확장자 검사
        file_extension = file.filename.split(".")[-1].lower()
        if file_extension not in ["jpg", "jpeg", "png", "gif"]:
            raise HTTPException(
                status_code=400,
                detail="지원하지 않는 파일 형식입니다. jpg, jpeg, png, gif 파일만 업로드 가능합니다."
            )

        # 파일 크기 검사 (예: 5MB)
        file_size = 0
        chunk_size = 1024 * 1024  # 1MB
        while chunk := await file.read(chunk_size):
            file_size += len(chunk)
            if file_size > 5 * 1024 * 1024:  # 5MB
                raise HTTPException(
                    status_code=400,
                    detail="파일 크기는 5MB를 초과할 수 없습니다."
                )

        # 파일을 다시 처음으로 되돌림
        await file.seek(0)

        # 랜덤 파일명 생성
        random_filename = generate_random_filename(file.filename)
        
        # Supabase Storage에 파일 업로드
        file_path = f"user_avatars/{user_id}/{random_filename}"
        file_content = await file.read()
        
        try:
            print(f"file_path: {file_path}")
            print(f"file_content type: {type(file_content)}, size: {len(file_content)}")
            print(f"file content-type: {file.content_type}")
            
            # service role 클라이언트를 사용하여 Storage 업로드
            result = supabase_storage.storage.from_("avatars").upload(
                file_path,
                file_content,
                {"content-type": file.content_type}
            )
            print(f"Storage upload result: {result}")
            
            # 파일 URL 생성 (anon 클라이언트 사용)
            supabase_anon = create_client(SUPABASE_URL, os.getenv("SUPABASE_ANON_KEY"))
            file_url = supabase_anon.storage.from_("avatars").get_public_url(file_path)
            
            # 기존 아바타 URL 저장 (커밋 전에)
            old_avatar_url = profiles.avatar
            
            # 사용자의 avatar 필드 업데이트
            profiles.avatar = file_url
            db.commit()
            
            # 데이터베이스 로그 생성
            try:
                create_database_log(
                    db=db,
                    table_name="profiles",
                    record_id=str(profiles.id),
                    action="UPDATE",
                    user_id=current_user["id"] if current_user else None,
                    old_values={"avatar": old_avatar_url},  # 기존 아바타 정보
                    new_values={"avatar": file_url},
                    changed_fields=["avatar"],
                    note=f"사용자 아바타 업데이트 - {profiles.name}: {random_filename}"
                )
            except Exception as log_error:
                print(f"로그 생성 중 오류: {log_error}")
            
        except Exception as storage_error:
            print(f"Storage 업로드 에러: {storage_error}")
            raise HTTPException(
                status_code=500,
                detail=f"Storage 연결 오류: {str(storage_error)}"
            )
        return {
            "message": "사용자의 프로필 이미지가 성공적으로 업로드되었습니다.",
            "avatar_url": file_url,
            "original_filename": file.filename,
            "random_filename": random_filename,
            "file_path": file_path
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"파일 업로드 중 오류가 발생했습니다: {str(e)}"
        ) 