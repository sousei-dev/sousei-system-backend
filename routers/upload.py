from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from typing import Optional
from database import SessionLocal
from models import Student
from datetime import datetime
import uuid
import os
from supabase import create_client

router = APIRouter(prefix="/upload", tags=["파일 업로드"])

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

@router.post("/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """아바타 이미지 업로드"""
    try:
        if not supabase_storage:
            raise HTTPException(status_code=500, detail="Supabase Storage가 설정되지 않았습니다")
        
        # 파일 타입 검증
        if not file.content_type.startswith('image/'):
            raise HTTPException(status_code=400, detail="이미지 파일만 업로드 가능합니다")
        
        # 파일 크기 검증 (5MB 제한)
        if file.size > 5 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="파일 크기는 5MB 이하여야 합니다")
        
        # 파일명 생성
        file_extension = os.path.splitext(file.filename)[1]
        file_name = f"avatars/{uuid.uuid4()}{file_extension}"
        
        # Supabase Storage에 업로드
        file_content = await file.read()
        result = supabase_storage.storage.from_("avatars").upload(
            path=file_name,
            file=file_content,
            file_options={"content-type": file.content_type}
        )
        
        if result.error:
            raise HTTPException(status_code=500, detail=f"파일 업로드 실패: {result.error}")
        
        # 공개 URL 생성
        public_url = supabase_storage.storage.from_("avatars").get_public_url(file_name)
        
        return {
            "message": "아바타가 성공적으로 업로드되었습니다",
            "file_name": file_name,
            "public_url": public_url,
            "file_size": len(file_content),
            "content_type": file.content_type
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"아바타 업로드 중 오류가 발생했습니다: {str(e)}")

@router.post("/students/{student_id}/changeAvatar")
async def change_student_avatar(
    student_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """학생 아바타 변경"""
    try:
        # 학생 존재 여부 확인
        student = db.query(Student).filter(Student.id == student_id).first()
        if not student:
            raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다")
        
        if not supabase_storage:
            raise HTTPException(status_code=500, detail="Supabase Storage가 설정되지 않았습니다")
        
        # 파일 타입 검증
        if not file.content_type.startswith('image/'):
            raise HTTPException(status_code=400, detail="이미지 파일만 업로드 가능합니다")
        
        # 파일 크기 검증 (5MB 제한)
        if file.size > 5 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="파일 크기는 5MB 이하여야 합니다")
        
        # 기존 아바타가 있다면 삭제
        if student.avatar and student.avatar != "/src/assets/images/avatars/avatar-1.png":
            try:
                old_avatar_path = student.avatar.replace("/storage/v1/object/public/avatars/", "")
                supabase_storage.storage.from_("avatars").remove([old_avatar_path])
            except:
                pass  # 기존 파일 삭제 실패는 무시
        
        # 새 파일명 생성
        file_extension = os.path.splitext(file.filename)[1]
        file_name = f"students/{student_id}/{uuid.uuid4()}{file_extension}"
        
        # Supabase Storage에 업로드
        file_content = await file.read()
        result = supabase_storage.storage.from_("avatars").upload(
            path=file_name,
            file=file_content,
            file_options={"content-type": file.content_type}
        )
        
        if result.error:
            raise HTTPException(status_code=500, detail=f"파일 업로드 실패: {result.error}")
        
        # 공개 URL 생성
        public_url = supabase_storage.storage.from_("avatars").get_public_url(file_name)
        
        # 학생 아바타 URL 업데이트
        student.avatar = public_url
        db.commit()
        
        return {
            "message": "학생 아바타가 성공적으로 변경되었습니다",
            "student_id": student_id,
            "student_name": student.name,
            "avatar_url": public_url,
            "file_size": len(file_content),
            "content_type": file.content_type
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"학생 아바타 변경 중 오류가 발생했습니다: {str(e)}") 