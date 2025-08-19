from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from typing import Optional, List
from database import SessionLocal
from models import Student, Room, BillingMonthlyItem
from datetime import datetime, date
import calendar
import uuid

router = APIRouter(prefix="/monthly-billing", tags=["월별 청구서"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 이 API들은 buildings.py로 이동되었습니다
# @router.get("/buildings/monthly-invoice-preview/students/{year}/{month}") - buildings.py에 있음
# @router.get("/buildings/download-monthly-invoice/{year}/{month}") - buildings.py에 있음
# @router.get("/buildings/monthly-invoice-preview/rooms/{year}/{month}") - buildings.py에 있음

@router.get("/validate/{year}/{month}")
def validate_monthly_billing(year: int, month: int, db: Session = Depends(get_db)):
    """월간 청구서 데이터 검증"""
    try:
        # 년월 유효성 검사
        if not (1 <= month <= 12):
            raise HTTPException(status_code=400, detail="월은 1-12 사이여야 합니다")
        
        # 해당 월의 첫날과 마지막날 계산
        first_day = date(year, month, 1)
        last_day = date(year, month, calendar.monthrange(year, month)[1])
        
        # 학생별 월간 청구서 데이터 검증
        students = db.query(Student).filter(Student.status == "active").all()
        validation_results = []
        
        for student in students:
            # 해당 월의 월별 항목들 조회
            monthly_items = db.query(BillingMonthlyItem).filter(
                BillingMonthlyItem.student_id == student.id,
                BillingMonthlyItem.year == year,
                BillingMonthlyItem.month == month
            ).all()
            
            student_validation = {
                "student_id": str(student.id),
                "student_name": student.name,
                "item_count": len(monthly_items),
                "total_amount": sum(item.amount for item in monthly_items),
                "is_valid": len(monthly_items) > 0,
                "issues": []
            }
            
            if len(monthly_items) == 0:
                student_validation["issues"].append("월간 청구서 항목이 없습니다")
            
            validation_results.append(student_validation)
        
        # 전체 검증 결과
        total_students = len(validation_results)
        valid_students = len([s for s in validation_results if s["is_valid"]])
        invalid_students = total_students - valid_students
        
        return {
            "validation_period": f"{year}년 {month}월",
            "total_students": total_students,
            "valid_students": valid_students,
            "invalid_students": invalid_students,
            "validation_rate": round((valid_students / total_students * 100), 2) if total_students > 0 else 0,
            "student_details": validation_results,
            "generated_at": datetime.utcnow()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"월간 청구서 검증 중 오류가 발생했습니다: {str(e)}") 