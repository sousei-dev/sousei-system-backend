from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from typing import Optional, List
from database import SessionLocal
from models import Grade, Student
from datetime import datetime
import uuid

router = APIRouter(prefix="/grades", tags=["등급 관리"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/")
def get_grades(
    name: Optional[str] = Query(None, description="등급 이름으로 검색"),
    page: int = Query(1, description="페이지 번호", ge=1),
    page_size: int = Query(10, description="페이지당 항목 수", ge=1, le=100),
    db: Session = Depends(get_db)
):
    """등급 목록 조회"""
    try:
        query = db.query(Grade)
        
        # 이름으로 필터링
        if name:
            query = query.filter(Grade.name.ilike(f"%{name}%"))
        
        # 전체 항목 수 계산
        total_count = query.count()
        
        # 페이지네이션 적용
        grades = query.offset((page - 1) * page_size).limit(page_size).all()
        
        # 전체 페이지 수 계산
        total_pages = (total_count + page_size - 1) // page_size
        
        # 응답 데이터 준비
        result = []
        for grade in grades:
            # 각 등급의 학생 수 계산
            student_count = db.query(Student).filter(Student.grade_id == grade.id).count()
            
            grade_data = {
                "id": str(grade.id),
                "name": grade.name,
                "created_at": grade.created_at,
                "student_count": student_count
            }
            result.append(grade_data)
        
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
        raise HTTPException(status_code=500, detail=f"등급 목록 조회 중 오류가 발생했습니다: {str(e)}")

@router.get("/{grade_id}")
def get_grade(grade_id: str, db: Session = Depends(get_db)):
    """특정 등급 상세 정보 조회"""
    try:
        grade = db.query(Grade).filter(Grade.id == grade_id).first()
        if not grade:
            raise HTTPException(status_code=404, detail="등급을 찾을 수 없습니다")
        
        # 등급에 속한 학생들 조회
        students = db.query(Student).filter(Student.grade_id == grade_id).all()
        
        grade_data = {
            "id": str(grade.id),
            "name": grade.name,
            "created_at": grade.created_at,
            "students": [
                {
                    "id": str(student.id),
                    "name": student.name,
                    "email": student.email,
                    "status": student.status
                } for student in students
            ]
        }
        
        return grade_data
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"등급 정보 조회 중 오류가 발생했습니다: {str(e)}") 