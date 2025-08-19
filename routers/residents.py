from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import SessionLocal
from models import Student


router = APIRouter(prefix="/residents", tags=["거주자 관리"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 이 API들은 rooms.py로 이동되었습니다
# @router.get("/rooms/{room_id}/residents") - rooms.py에 있음
# @router.get("/rooms/{room_id}/residence-history") - rooms.py에 있음

# 이 API들은 students.py로 이동되었습니다
# @router.get("/students/{student_id}/residence-history") - students.py에 있음
# @router.get("/students/{student_id}/residence-history/monthly") - students.py에 있음
# @router.post("/students/{student_id}/change-residence") - students.py에 있음

@router.get("/{resident_id}")
def get_resident_info(resident_id: str, db: Session = Depends(get_db)):
    """거주자 정보 조회 (학생 또는 고령자)"""
    try:
        # 학생으로 먼저 조회
        student = db.query(Student).filter(Student.id == resident_id).first()
        if student:
            return {
                "resident_id": str(student.id),
                "resident_name": student.name,
                "resident_type": "student",
                "email": student.email,
                "status": student.status,
                "current_room_id": str(student.current_room_id) if student.current_room_id else None
            }
        
        # 고령자로 조회 (Elderly 모델이 있다면)
        # elderly = db.query(Elderly).filter(Elderly.id == resident_id).first()
        # if elderly:
        #     return {
        #         "resident_id": str(elderly.id),
        #         "resident_name": elderly.name,
        #         "resident_type": "elderly",
        #         "status": elderly.status,
        #         "current_room_id": str(elderly.current_room_id) if elderly.current_room_id else None
        #     }
        
        raise HTTPException(status_code=404, detail="거주자를 찾을 수 없습니다")
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"거주자 정보 조회 중 오류가 발생했습니다: {str(e)}")