from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from typing import Optional, List
from database import SessionLocal
from models import Room, Student, RoomLog, ResidenceCardHistory
from schemas import AssignRoomRequest, NewResidenceRequest
from datetime import datetime
import uuid

router = APIRouter(prefix="/room-operations", tags=["방 운영 관리"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 이 API들은 rooms.py로 이동되었습니다
# @router.post("/rooms/{room_id}/check-in") - rooms.py에 있음
# @router.post("/rooms/{room_id}/check-out") - rooms.py에 있음

@router.put("/students/{student_id}/assign-room")
def assign_room_to_student(
    student_id: str,
    assign_data: AssignRoomRequest,
    db: Session = Depends(get_db)
):
    """학생에게 방 배정"""
    try:
        # 학생 존재 여부 확인
        student = db.query(Student).filter(Student.id == student_id).first()
        if not student:
            raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다")
        
        # 방 존재 여부 확인
        room = db.query(Room).filter(Room.id == assign_data.room_id).first()
        if not room:
            raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다")
        
        # 방 수용 가능 여부 확인
        current_residents_count = len(room.current_residents) if room.current_residents else 0
        if current_residents_count >= room.capacity:
            raise HTTPException(status_code=400, detail="방이 가득 찼습니다")
        
        # 기존 방 배정 해제
        old_room_id = student.current_room_id
        if old_room_id:
            # 기존 방 배정 해제 로그
            unassign_log = RoomLog(
                id=str(uuid.uuid4()),
                room_id=old_room_id,
                student_id=student_id,
                action="unassign",
                timestamp=datetime.utcnow(),
                note="새로운 방 배정으로 인한 기존 방 배정 해제"
            )
            db.add(unassign_log)
        
        # 새 방 배정
        student.current_room_id = assign_data.room_id
        student.status = "active"
        
        # 방 배정 로그 생성
        assign_log = RoomLog(
            id=str(uuid.uuid4()),
            room_id=assign_data.room_id,
            student_id=student_id,
            action="assign",
            timestamp=datetime.utcnow(),
            note=assign_data.note or "방 배정"
        )
        
        db.add(assign_log)
        db.commit()
        
        return {
            "message": "방 배정이 성공적으로 완료되었습니다",
            "student_id": str(student.id),
            "student_name": student.name,
            "room_id": str(room.id),
            "room_number": room.room_number,
            "old_room_id": str(old_room_id) if old_room_id else None,
            "assign_time": assign_log.timestamp
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"방 배정 중 오류가 발생했습니다: {str(e)}") 