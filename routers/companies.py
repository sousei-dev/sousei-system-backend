from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from typing import Optional, List
from database import SessionLocal
from models import Company, Student, Department
from datetime import datetime
from utils.dependencies import get_current_user
import uuid

router = APIRouter(prefix="/companies", tags=["회사 관리"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/")
def get_companies(
    name: Optional[str] = Query(None, description="회사 이름으로 검색"),
    page: int = Query(1, description="페이지 번호", ge=1),
    page_size: int = Query(100, description="페이지당 항목 수", ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """회사 목록 조회 (부서별로 분리)"""
    try:
        # Department와 Company를 조인하여 조회
        query = db.query(Department).options(joinedload(Department.company))
        
        # 이름으로 필터링 (회사 이름 또는 부서 이름)
        if name:
            query = query.filter(
                (Department.company.name.ilike(f"%{name}%")) | 
                (Department.name.ilike(f"%{name}%"))
            )
        
        # 전체 항목 수 계산
        total_count = query.count()
        
        # 페이지네이션 적용
        departments = query.offset((page - 1) * page_size).limit(page_size).all()
        
        # 전체 페이지 수 계산
        total_pages = (total_count + page_size - 1) // page_size
        
        # 응답 데이터 준비
        result = []
        for department in departments:
            # 각 부서의 학생 수 계산
            student_count = db.query(Student).filter(Student.company_id == str(department.company_id)).count()
            
            department_data = {
                "id": str(department.id),  # 부서의 ID 반환
                "name": f"{department.company.name} - {department.name}" if department.name != "-" else department.company.name,  # 부서 이름이 "-"가 아닐 때만 부서 이름 포함
                "company_name": department.company.name,
                "company_id": str(department.company_id),
                "billing_scope": department.company.billing_scope,
                "department_name": department.name,
                "company_address": department.company.address,
                "created_at": department.created_at,
                "student_count": student_count
            }
            result.append(department_data)
        
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
        raise HTTPException(status_code=500, detail=f"회사 목록 조회 중 오류가 발생했습니다: {str(e)}")

@router.get("/companies-only")
def get_companies_only(
    name: Optional[str] = Query(None, description="회사 이름으로 검색"),
    page: int = Query(1, description="페이지 번호", ge=1),
    page_size: int = Query(100, description="페이지당 항목 수", ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """회사 목록 조회 (부서별로 분리)"""
    try:
        # Department와 Company를 조인하여 조회
        query = db.query(Department).options(joinedload(Department.company))
        
        # 이름으로 필터링 (회사 이름 또는 부서 이름)
        if name:
            query = query.filter(
                (Department.company.name.ilike(f"%{name}%")) | 
                (Department.name.ilike(f"%{name}%"))
            )
        
        # 전체 항목 수 계산
        total_count = query.count()
        
        # 페이지네이션 적용
        departments = query.offset((page - 1) * page_size).limit(page_size).all()
        
        # 전체 페이지 수 계산
        total_pages = (total_count + page_size - 1) // page_size
        
        # 응답 데이터 준비
        result = []
        for department in departments:
            # 각 부서의 학생 수 계산
            student_count = db.query(Student).filter(Student.company_id == str(department.company_id)).count()
            
            department_data = {
                "id": str(department.id),  # 부서의 ID 반환
                "name": f"{department.company.name} - {department.name}" if department.name != "-" else department.company.name,  # 부서 이름이 "-"가 아닐 때만 부서 이름 포함
                "company_name": department.company.name,
                "company_id": str(department.company_id),
                "billing_scope": department.company.billing_scope,
                "department_name": department.name,
                "company_address": department.company.address,
                "created_at": department.created_at,
                "student_count": student_count
            }
            result.append(department_data)
        
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
        raise HTTPException(status_code=500, detail=f"회사 목록 조회 중 오류가 발생했습니다: {str(e)}")

@router.get("/{company_id}")
def get_company(company_id: str, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """특정 회사 상세 정보 조회"""
    try:
        company = db.query(Company).filter(Company.id == company_id).first()
        if not company:
            raise HTTPException(status_code=404, detail="회사를 찾을 수 없습니다")
        
        # 회사에 속한 학생들 조회
        students = db.query(Student).filter(Student.company_id == company_id).all()
        
        company_data = {
            "id": str(company.id),
            "name": company.name,
            "address": company.address,
            "created_at": company.created_at,
            "students": [
                {
                    "id": str(student.id),
                    "name": student.name,
                    "email": student.email,
                    "status": student.status
                } for student in students
            ]
        }
        
        return company_data
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"회사 정보 조회 중 오류가 발생했습니다: {str(e)}") 