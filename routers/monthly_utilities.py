from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from typing import Optional, List
from database import SessionLocal
from models import Room, Student, RoomUtility
from datetime import datetime, date
import calendar
import uuid

router = APIRouter(prefix="/monthly-utilities", tags=["월별 유틸리티 상세 관리"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 이 API들은 rooms.py로 이동되었습니다
# @router.get("/rooms/{room_id}/utilities/monthly-allocation/{year}/{month}") - rooms.py에 있음
# @router.get("/rooms/{room_id}/utilities/monthly-summary/{year}/{month}") - rooms.py에 있음
# @router.get("/rooms/{room_id}/utilities/monthly-by-students/{year}/{month}") - rooms.py에 있음

@router.get("/validate/{year}/{month}")
def validate_monthly_utilities(year: int, month: int, db: Session = Depends(get_db)):
    """월간 유틸리티 데이터 검증"""
    try:
        # 년월 유효성 검사
        if not (1 <= month <= 12):
            raise HTTPException(status_code=400, detail="월은 1-12 사이여야 합니다")
        
        # 해당 월의 첫날과 마지막날 계산
        first_day = date(year, month, 1)
        last_day = date(year, month, calendar.monthrange(year, month)[1])
        
        # 모든 방의 유틸리티 데이터 검증
        rooms = db.query(Room).all()
        validation_results = []
        
        for room in rooms:
            # 해당 방의 유틸리티 조회
            utilities = db.query(RoomUtility).filter(
                RoomUtility.room_id == room.id,
                RoomUtility.start_date <= last_day,
                RoomUtility.end_date >= first_day
            ).all()
            
            # 해당 방에 거주 중인 학생 수
            student_count = db.query(Student).filter(
                Student.current_room_id == room.id
            ).count()
            
            room_validation = {
                "room_id": str(room.id),
                "room_number": room.room_number,
                "utility_count": len(utilities),
                "student_count": student_count,
                "is_valid": len(utilities) > 0 and student_count > 0,
                "issues": []
            }
            
            if len(utilities) == 0:
                room_validation["issues"].append("유틸리티 데이터가 없습니다")
            if student_count == 0:
                room_validation["issues"].append("거주 중인 학생이 없습니다")
            
            validation_results.append(room_validation)
        
        # 전체 검증 결과
        total_rooms = len(validation_results)
        valid_rooms = len([r for r in validation_results if r["is_valid"]])
        invalid_rooms = total_rooms - valid_rooms
        
        return {
            "validation_period": f"{year}년 {month}월",
            "total_rooms": total_rooms,
            "valid_rooms": valid_rooms,
            "invalid_rooms": invalid_rooms,
            "validation_rate": round((valid_rooms / total_rooms * 100), 2) if total_rooms > 0 else 0,
            "room_details": validation_results,
            "generated_at": datetime.utcnow()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"월간 유틸리티 검증 중 오류가 발생했습니다: {str(e)}") 