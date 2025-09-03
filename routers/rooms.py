from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from typing import Optional, List
from database import SessionLocal
from models import Room, Building, Student, RoomUtility, Resident
from schemas import RoomResponse, RoomUpdate, RoomCreate
from database_log import create_database_log
from utils.dependencies import get_current_user
from datetime import datetime, timedelta
import uuid

router = APIRouter(prefix="/rooms", tags=["방 관리"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/")
def get_rooms(
    building_id: Optional[str] = Query(None, description="건물 ID로 필터링"),
    room_number: Optional[str] = Query(None, description="방 번호로 검색"),
    status: Optional[str] = Query(None, description="방 상태로 필터링"),
    page: int = Query(1, description="페이지 번호", ge=1),
    page_size: int = Query(10, description="페이지당 항목 수", ge=1, le=100),
    db: Session = Depends(get_db)
):
    """방 목록 조회"""
    try:
        query = db.query(Room).options(joinedload(Room.building))
        
        # 필터링 적용
        if building_id:
            query = query.filter(Room.building_id == building_id)
        if room_number:
            query = query.filter(Room.room_number.ilike(f"%{room_number}%"))
        if status:
            query = query.filter(Room.status == status)
        
        # 전체 항목 수 계산
        total_count = query.count()
        
        # 페이지네이션 적용
        rooms = query.offset((page - 1) * page_size).limit(page_size).all()
        
        # 전체 페이지 수 계산
        total_pages = (total_count + page_size - 1) // page_size
        
        # 응답 데이터 준비
        result = []
        for room in rooms:
            # 현재 거주자 수 계산
            current_residents_count = len(room.current_residents) if room.current_residents else 0
            
            room_data = {
                "id": str(room.id),
                "room_number": room.room_number,
                "floor": room.floor,
                "capacity": room.capacity,
                "status": room.status,
                "building": {
                    "id": str(room.building.id),
                    "name": room.building.name
                } if room.building else None,
                "current_residents_count": current_residents_count,
                "is_available": current_residents_count < room.capacity if room.capacity else True
            }
            result.append(room_data)
        
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
        raise HTTPException(status_code=500, detail=f"방 목록 조회 중 오류가 발생했습니다: {str(e)}")

@router.get("/available")
def get_available_rooms(
    building_id: Optional[str] = Query(None, description="건물 ID로 필터링"),
    db: Session = Depends(get_db)
):
    """사용 가능한 방 조회"""
    try:
        query = db.query(Room).options(joinedload(Room.building))
        
        if building_id:
            query = query.filter(Room.building_id == building_id)
        
        rooms = query.all()
        
        available_rooms = []
        for room in rooms:
            current_residents_count = len(room.current_residents) if room.current_residents else 0
            
            if current_residents_count < room.capacity:
                available_rooms.append({
                    "id": str(room.id),
                    "room_number": room.room_number,
                    "floor": room.floor,
                    "capacity": room.capacity,
                    "current_residents_count": current_residents_count,
                    "available_spots": room.capacity - current_residents_count,
                    "building": {
                        "id": str(room.building.id),
                        "name": room.building.name
                    } if room.building else None
                })
        
        return {
            "available_rooms": available_rooms,
            "total_available": len(available_rooms)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"사용 가능한 방 조회 중 오류가 발생했습니다: {str(e)}")

@router.get("/{room_id}")
def get_room(
    room_id: str,
    db: Session = Depends(get_db)
):
    room = db.query(Room).options(
        joinedload(Room.building)
    ).filter(Room.id == room_id).first()
    
    if not room:
        raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다")
    
    # 방 정보와 함께 빌딩의 resident_type 포함
    room_data = {
        "id": str(room.id),
        "building_id": str(room.building_id),
        "room_number": room.room_number,
        "rent": room.rent,
        "maintenance": room.maintenance,
        "service": room.service,
        "floor": room.floor,
        "capacity": room.capacity,
        "is_available": room.is_available,
        "note": room.note,
        "building": {
            "id": str(room.building.id),
            "name": room.building.name,
            "address": room.building.address,
            "total_rooms": room.building.total_rooms,
            "note": room.building.note,
            "resident_type": room.building.resident_type
        }
    }
    
    return room_data


@router.get("/{room_id}/capacity-status")
def get_room_capacity_status(room_id: str, db: Session = Depends(get_db)):
    """방의 수용 가능 상태 조회"""
    try:
        room = db.query(Room).options(joinedload(Room.current_residents)).filter(Room.id == room_id).first()
        
        if not room:
            raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다")
        
        current_residents_count = len(room.current_residents) if room.current_residents else 0
        available_spots = room.capacity - current_residents_count if room.capacity else 0
        
        return {
            "room_id": str(room.id),
            "room_number": room.room_number,
            "capacity": room.capacity,
            "current_residents_count": current_residents_count,
            "available_spots": available_spots,
            "is_full": current_residents_count >= room.capacity if room.capacity else False,
            "occupancy_rate": (current_residents_count / room.capacity * 100) if room.capacity else 0
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"방 수용 가능 상태 조회 중 오류가 발생했습니다: {str(e)}")

@router.get("/{room_id}/residents")
def get_room_residents(
    room_id: str,
    db: Session = Depends(get_db)
):
    """방 거주자 목록 조회"""
    try:
        # 방 존재 여부 확인
        room = db.query(Room).options(
            joinedload(Room.current_residents).joinedload(Student.grade)
        ).filter(Room.id == room_id).first()
        
        if not room:
            raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다")
        
        residents_data = []
        for resident in room.current_residents:
            resident_info = {
                "id": str(resident.id),
                "name": resident.name,
                "email": resident.email,
                "grade_name": resident.grade.name if resident.grade else None,
                "entry_date": resident.entry_date,
                "status": resident.status,
                "avatar": resident.avatar
            }
            residents_data.append(resident_info)
        
        return {
            "room_id": str(room.id),
            "room_number": room.room_number,
            "floor": room.floor,
            "capacity": room.capacity,
            "current_residents_count": len(residents_data),
            "residents": residents_data
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"방 거주자 조회 중 오류가 발생했습니다: {str(e)}")

@router.get("/{room_id}/residence-history")
def get_room_residence_history(
    room_id: str,
    resident_type: Optional[str] = Query(None, description="거주자 타입으로 필터링 (student 또는 elderly)"),
    page: int = Query(1, description="페이지 번호", ge=1),
    size: int = Query(10, description="페이지당 항목 수", ge=1, le=100),
    is_active: Optional[bool] = Query(None, description="활성 상태로 필터링"),
    db: Session = Depends(get_db),
):
    # 방 존재 여부 확인
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다")

    # 해당 방의 모든 입주 기록 조회
    query = db.query(Resident)
    
    # 거주자 타입에 따라 조인 설정
    if resident_type == "elderly":
        query = query.options(joinedload(Resident.elderly))
    else:  # student 또는 기본값
        query = query.options(joinedload(Resident.student))
    
    query = query.filter(Resident.room_id == room_id)

    # 활성 상태 필터링 (선택사항)
    if is_active is not None:
        query = query.filter(Resident.is_active == is_active)

    # 전체 항목 수 계산
    total_count = query.count()

    # 페이지네이션 적용 (최신 기록부터)
    residents = query.order_by(Resident.created_at.desc()).offset((page - 1) * size).limit(size).all()

    # 전체 페이지 수 계산
    total_pages = (total_count + size - 1) // size

    # 응답 데이터 준비
    result = []
    for resident in residents:
        resident_data = {
            "id": str(resident.id),
            "room_id": str(resident.room_id),
            "resident_id": str(resident.resident_id),
            "check_in_date": resident.check_in_date.strftime("%Y-%m-%d"),
            "check_out_date": resident.check_out_date.strftime("%Y-%m-%d") if resident.check_out_date else None,
            "is_active": resident.is_active,
            "note": resident.note,
            "created_at": resident.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": resident.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
            "room": {
                "id": str(room.id),
                "room_number": room.room_number,
                "building_id": str(room.building_id)
            },
            "resident_type": resident.resident_type
        }
        
        # 거주자 타입에 따라 다른 데이터 추가
        if resident_type == "elderly" and resident.elderly:
            resident_data["elderly"] = {
                "id": str(resident.elderly.id),
                "name": resident.elderly.name,
                "name_katakana": resident.elderly.name_katakana,
                "gender": resident.elderly.gender,
                "birth_date": resident.elderly.birth_date.strftime("%Y-%m-%d") if resident.elderly.birth_date else None,
                "phone": resident.elderly.phone,
                "care_level": resident.elderly.care_level,
                "status": resident.elderly.status,
                "avatar": resident.elderly.avatar,
            }
        elif (resident_type == "student" or resident_type is None) and resident.student:
            resident_data["student"] = {
                "id": str(resident.student.id),
                "name": resident.student.name,
                "name_katakana": resident.student.name_katakana,
                "nationality": resident.student.nationality,
                "phone": resident.student.phone,
                "email": resident.student.email if resident.student.email else "",
                "avatar": resident.student.avatar,
                "gender": resident.student.gender,
                "birth_date": resident.student.birth_date.strftime("%Y-%m-%d") if resident.student.birth_date else None,
                "japanese_level": resident.student.japanese_level,
                "local_address": resident.student.local_address
            }
        
        result.append(resident_data)

    return {
        "items": result,
        "total": total_count,
        "total_pages": total_pages,
        "current_page": page
    }

@router.post("/", response_model=RoomResponse)
def create_room(
    room: RoomCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    # 빌딩 존재 여부 확인
    building = db.query(Building).filter(Building.id == room.building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="빌딩을 찾을 수 없습니다")

    # 같은 빌딩 내에서 방 번호 중복 확인
    existing_room = db.query(Room).filter(
        Room.building_id == room.building_id,
        Room.room_number == room.room_number
    ).first()
    
    if existing_room:
        raise HTTPException(status_code=400, detail="해당 빌딩에 같은 방 번호가 이미 존재합니다")

    # 정원 유효성 검사
    if room.capacity is not None and room.capacity <= 0:
        raise HTTPException(status_code=400, detail="정원은 1명 이상이어야 합니다")

    new_room = Room(
        building_id=room.building_id,
        room_number=room.room_number,
        rent=room.rent,
        floor=room.floor,
        capacity=room.capacity,
        is_available=room.is_available,
        note=room.note
    )
    db.add(new_room)
    
    try:
        db.commit()
        db.refresh(new_room)
        
        # 로그 생성
        create_database_log(
            db=db,
            table_name="rooms",
            record_id=str(new_room.id),
            action="CREATE",
            user_id=current_user["id"] if current_user else None,
            new_values={
                "building_id": str(new_room.building_id),
                "room_number": new_room.room_number,
                "rent": new_room.rent,
                "floor": new_room.floor,
                "capacity": new_room.capacity,
                "is_available": new_room.is_available,
                "note": new_room.note
            },
            note="部屋新規登録"
        )
        
        return new_room
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"방 생성 중 오류가 발생했습니다: {str(e)}"
        )

@router.put("/{room_id}", response_model=RoomResponse)
def update_room(
    room_id: str,
    room_update: RoomUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    # 방 존재 여부 확인
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다")

    # 방 번호가 변경되는 경우 중복 확인
    if room_update.room_number and room_update.room_number != room.room_number:
        existing_room = db.query(Room).filter(
            Room.building_id == room.building_id,
            Room.room_number == room_update.room_number,
            Room.id != room_id
        ).first()
        
        if existing_room:
            raise HTTPException(status_code=400, detail="해당 빌딩에 같은 방 번호가 이미 존재합니다")

    # 정원 유효성 검사
    if room_update.capacity is not None and room_update.capacity <= 0:
        raise HTTPException(status_code=400, detail="정원은 1명 이상이어야 합니다")

    # 기존 값 저장 (로그용)
    old_values = {
        "building_id": str(room.building_id),
        "room_number": room.room_number,
        "rent": room.rent,
        "floor": room.floor,
        "capacity": room.capacity,
        "is_available": room.is_available,
        "note": room.note
    }
    
    # 방 정보 업데이트
    update_data = room_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(room, field, value)

    try:
        db.commit()
        db.refresh(room)
        
        # 로그 생성
        create_database_log(
            db=db,
            table_name="rooms",
            record_id=str(room.id),
            action="UPDATE",
            user_id=current_user["id"] if current_user else None,
            old_values=old_values,
            new_values={
                "building_id": str(room.building_id),
                "room_number": room.room_number,
                "rent": room.rent,
                "floor": room.floor,
                "capacity": room.capacity,
                "is_available": room.is_available,
                "note": room.note
            },
            changed_fields=list(update_data.keys()),
            note="部屋情報更新"
        )
        
        return room
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"방 정보 수정 중 오류가 발생했습니다: {str(e)}"
        )

@router.delete("/{room_id}")
def delete_room(
    room_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    # 방 존재 여부 확인
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다")

    # 삭제 전 값 저장 (로그용)
    old_values = {
        "building_id": str(room.building_id),
        "room_number": room.room_number,
        "rent": room.rent,
        "floor": room.floor,
        "capacity": room.capacity,
        "is_available": room.is_available,
        "note": room.note
    }
    
    try:
        db.delete(room)
        db.commit()
        
        # 로그 생성
        create_database_log(
            db=db,
            table_name="rooms",
            record_id=str(room.id),
            action="DELETE",
            user_id=current_user["id"] if current_user else None,
            old_values=old_values,
            note="部屋削除"
        )
        
        return {"message": "部屋が正常に削除されました"}
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"방 삭제 중 오류가 발생했습니다: {str(e)}"
        )

@router.post("/{room_id}/check-in")
def check_in_student(
    room_id: str,
    check_in_data: dict,  # CheckInRequest 스키마 대신 dict 사용
    db: Session = Depends(get_db)
):
    """학생 체크인"""
    try:
        # 방 존재 여부 확인
        room = db.query(Room).filter(Room.id == room_id).first()
        if not room:
            raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다")
        
        # 학생 존재 여부 확인
        student = db.query(Student).filter(Student.id == check_in_data.get("student_id")).first()
        if not student:
            raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다")
        
        # 방 수용 가능 여부 확인
        current_residents_count = len(room.current_residents) if room.current_residents else 0
        if current_residents_count >= room.capacity:
            raise HTTPException(status_code=400, detail="방이 가득 찼습니다")
        
        # 학생이 이미 다른 방에 있는지 확인
        if student.current_room_id:
            raise HTTPException(status_code=400, detail="학생이 이미 다른 방에 배정되어 있습니다")
        
        # 체크인 처리
        student.current_room_id = room_id
        student.status = "active"
        
        db.commit()
        
        return {
            "message": "체크인이 성공적으로 완료되었습니다",
            "student_id": str(student.id),
            "student_name": student.name,
            "room_id": str(room.id),
            "room_number": room.room_number
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"체크인 중 오류가 발생했습니다: {str(e)}")

@router.post("/{room_id}/check-out")
def check_out_student(
    room_id: str,
    check_out_data: dict,  # CheckOutRequest 스키마 대신 dict 사용
    db: Session = Depends(get_db)
):
    """학생 체크아웃"""
    try:
        # 방 존재 여부 확인
        room = db.query(Room).filter(Room.id == room_id).first()
        if not room:
            raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다")
        
        # 학생 존재 여부 확인
        student = db.query(Student).filter(Student.id == check_out_data.get("student_id")).first()
        if not student:
            raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다")
        
        # 학생이 해당 방에 있는지 확인
        if student.current_room_id != room_id:
            raise HTTPException(status_code=400, detail="학생이 해당 방에 배정되어 있지 않습니다")
        
        # 체크아웃 처리
        student.current_room_id = None
        student.status = "inactive"
        
        db.commit()
        
        return {
            "message": "체크아웃이 성공적으로 완료되었습니다",
            "student_id": str(student.id),
            "student_name": student.name,
            "room_id": str(room.id),
            "room_number": room.room_number
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"체크아웃 중 오류가 발생했습니다: {str(e)}")

@router.delete("/{room_id}/utilities/{utility_id}")
def delete_room_utility(room_id: str, utility_id: str, db: Session = Depends(get_db)):
    """특정 방의 공과금 삭제"""
    try:
        # 방 존재 여부 확인
        room = db.query(Room).filter(Room.id == room_id).first()
        if not room:
            raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다")

        # 공과금 존재 여부 및 해당 방의 공과금인지 확인
        utility = db.query(RoomUtility).filter(
            RoomUtility.id == utility_id,
            RoomUtility.room_id == room_id
        ).first()
        
        if not utility:
            raise HTTPException(status_code=404, detail="해당 방의 공과금을 찾을 수 없습니다")

        # 삭제 전 값 저장 (로그용)
        old_values = {
            "room_id": str(utility.room_id),
            "utility_type": utility.utility_type,
            "period_start": str(utility.period_start),
            "period_end": str(utility.period_end),
            "usage": float(utility.usage) if utility.usage else None,
            "unit_price": float(utility.unit_price) if utility.unit_price else None,
            "total_amount": float(utility.total_amount) if utility.total_amount else None,
            "charge_month": str(utility.charge_month),
            "memo": utility.memo
        }
        
        db.delete(utility)
        db.commit()
        
        return {"message": "공과금이 정상적으로 삭제되었습니다"}
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"공과금 삭제 중 오류가 발생했습니다: {str(e)}"
        )

@router.get("/{room_id}/utilities")
def get_room_utilities_by_room(
    room_id: str,
    utility_type: Optional[str] = Query(None, description="공과금 타입으로 필터링"),
    page: int = Query(1, description="페이지 번호", ge=1),
    size: int = Query(10, description="페이지당 항목 수", ge=1, le=100),
    db: Session = Depends(get_db)
):
    """특정 방의 공과금 목록 조회"""
    try:
        # 방 존재 여부 확인
        room = db.query(Room).filter(Room.id == room_id).first()
        if not room:
            raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다")
        
        # 해당 방의 공과금을 가져오기
        query = db.query(RoomUtility).filter(RoomUtility.room_id == room_id)

        # 공과금 타입으로 필터링
        if utility_type:
            query = query.filter(RoomUtility.utility_type == utility_type)

        # 전체 항목 수 계산
        total_count = query.count()

        # 페이지네이션 적용 (최신순)
        utilities = query.order_by(RoomUtility.charge_month.desc(), RoomUtility.created_at.desc()).offset((page - 1) * size).limit(size).all()

        # 전체 페이지 수 계산
        total_pages = (total_count + size - 1) // size

        # 응답 데이터 준비
        result = []
        for utility in utilities:
            utility_data = {
                "id": str(utility.id),
                "utility_type": utility.utility_type,
                "period_start": utility.period_start.strftime("%Y-%m-%d") if utility.period_start else None,
                "period_end": utility.period_end.strftime("%Y-%m-%d") if utility.period_end else None,
                "usage": float(utility.usage) if utility.usage else None,
                "unit_price": float(utility.unit_price) if utility.unit_price else None,
                "total_amount": float(utility.total_amount) if utility.total_amount else None,
                "charge_month": utility.charge_month.strftime("%Y-%m-%d") if utility.charge_month else None,
                "memo": utility.memo,
                "created_at": utility.created_at.strftime("%Y-%m-%d %H:%M:%S") if utility.created_at else None,
                "updated_at": utility.updated_at.strftime("%Y-%m-%d %H:%M:%S") if utility.updated_at else None
            }
            result.append(utility_data)
        
        return {
            "room_id": str(room.id),
            "room_number": room.room_number,
            "utilities": result,
            "total_count": total_count,
            "total_pages": total_pages,
            "current_page": page,
            "has_next": page < total_pages,
            "has_previous": page > 1
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"방 공과금 조회 중 오류가 발생했습니다: {str(e)}")

@router.get("/{room_id}/utilities/monthly-allocation/{year}/{month}")
def get_room_monthly_utility_allocation(
    room_id: str,
    year: int,
    month: int,
    db: Session = Depends(get_db)
):
    """특정 방의 월별 공과금 배분 계산"""
    try:
        # 방 존재 여부 확인
        room = db.query(Room).options(
            joinedload(Room.building)
        ).filter(Room.id == room_id).first()
        if not room:
            raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다")

        # 월 유효성 검사
        if month < 1 or month > 12:
            raise HTTPException(status_code=400, detail="월은 1-12 사이의 값이어야 합니다")

        # 해당 월의 시작일과 종료일 계산
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)

        # 해당 월의 모든 공과금 조회
        utilities = db.query(RoomUtility).filter(
            RoomUtility.room_id == room_id,
            RoomUtility.charge_month >= start_date,
            RoomUtility.charge_month <= end_date
        ).order_by(RoomUtility.utility_type, RoomUtility.period_start).all()

        if not utilities:
            return {
                "room": {
                    "id": str(room.id),
                    "room_number": room.room_number,
                    "building_name": room.building.name if room.building else None
                },
                "year": year,
                "month": month,
                "utilities": [],
                "summary": {
                    "total_utilities": 0,
                    "total_amount": 0,
                    "total_residents": 0
                }
            }

        # 해당 방의 모든 거주 기록 조회
        residents = db.query(Resident).options(
            joinedload(Resident.student)
        ).filter(Resident.room_id == room_id).all()

        # 각 공과금별 배분 계산
        utility_allocations = []
        total_monthly_amount = 0

        for utility in utilities:
            # 공과금 기간 동안의 거주자 정보 계산
            allocations = []
            total_days_in_period = (utility.period_end - utility.period_start).days + 1
            total_overlap_days = 0

            # 각 거주자의 겹치는 일수 계산
            resident_overlaps = []
            for resident in residents:
                resident_start = resident.check_in_date
                resident_end = resident.check_out_date if resident.check_out_date else utility.period_end

                overlap_start = max(resident_start, utility.period_start)
                overlap_end = min(resident_end, utility.period_end)

                if overlap_start <= overlap_end:
                    overlap_days = (overlap_end - overlap_start).days + 1
                    total_overlap_days += overlap_days
                    
                    resident_overlaps.append({
                        "resident": resident,
                        "overlap_days": overlap_days,
                        "overlap_start": overlap_start,
                        "overlap_end": overlap_end
                    })

            # 배분 계산 (일수 기준)
            for overlap_info in resident_overlaps:
                resident = overlap_info["resident"]
                overlap_days = overlap_info["overlap_days"]
                
                # 비율 계산
                ratio = overlap_days / total_overlap_days if total_overlap_days > 0 else 0
                
                # 부담금액 계산
                amount = float(utility.total_amount) * ratio if utility.total_amount else 0

                allocation = {
                    "student_id": str(resident.resident_id),
                    "student_name": resident.student.name if resident.student else "Unknown",
                    "overlap_days": overlap_days,
                    "overlap_start": overlap_info["overlap_start"].strftime("%Y-%m-%d"),
                    "overlap_end": overlap_info["overlap_end"].strftime("%Y-%m-%d"),
                    "ratio": round(ratio, 4),
                    "amount": round(amount, 2)
                }
                allocations.append(allocation)

            utility_allocation = {
                "utility_id": str(utility.id),
                "utility_type": utility.utility_type,
                "period_start": utility.period_start.strftime("%Y-%m-%d") if utility.period_start else None,
                "period_end": utility.period_end.strftime("%Y-%m-%d") if utility.period_end else None,
                "total_amount": float(utility.total_amount) if utility.total_amount else 0,
                "allocations": allocations
            }
            utility_allocations.append(utility_allocation)
            total_monthly_amount += float(utility.total_amount) if utility.total_amount else 0

        return {
            "room": {
                "id": str(room.id),
                "room_number": room.room_number,
                "building_name": room.building.name if room.building else None
            },
            "year": year,
            "month": month,
            "utilities": utility_allocations,
            "summary": {
                "total_utilities": len(utilities),
                "total_amount": round(total_monthly_amount, 2),
                "total_residents": len(residents)
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"월간 공과금 배분 조회 중 오류가 발생했습니다: {str(e)}")

@router.get("/{room_id}/utilities/monthly-summary/{year}/{month}")
def get_room_monthly_utility_summary(
    room_id: str,
    year: int,
    month: int,
    db: Session = Depends(get_db)
):
    """특정 방의 월별 공과금 요약 정보"""
    try:
        # 방 존재 여부 확인
        room = db.query(Room).options(
            joinedload(Room.building)
        ).filter(Room.id == room_id).first()
        if not room:
            raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다")

        # 월 유효성 검사
        if month < 1 or month > 12:
            raise HTTPException(status_code=400, detail="월은 1-12 사이의 값이어야 합니다")

        # 해당 월의 시작일과 종료일 계산
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)

        # 해당 월의 모든 공과금 조회
        utilities = db.query(RoomUtility).filter(
            RoomUtility.room_id == room_id,
            RoomUtility.charge_month >= start_date,
            RoomUtility.charge_month <= end_date
        ).all()

        # 해당 방의 모든 거주 기록 조회
        residents = db.query(Resident).options(
            joinedload(Resident.student)
        ).filter(Resident.room_id == room_id).all()

        # 공과금별 요약 정보
        utility_summaries = []
        total_monthly_amount = 0

        for utility in utilities:
            # 공과금 기간 동안의 거주자 수와 일수 계산
            total_days_in_period = (utility.period_end - utility.period_start).days + 1
            total_overlap_days = 0
            resident_count = 0

            for resident in residents:
                resident_start = resident.check_in_date
                resident_end = resident.check_out_date if resident.check_out_date else utility.period_end

                overlap_start = max(resident_start, utility.period_start)
                overlap_end = min(resident_end, utility.period_end)

                if overlap_start <= overlap_end:
                    overlap_days = (overlap_end - overlap_start).days + 1
                    total_overlap_days += overlap_days
                    resident_count += 1

            # 평균 일수 계산
            avg_days_per_resident = total_overlap_days / resident_count if resident_count > 0 else 0

            utility_summary = {
                "utility_id": str(utility.id),
                "utility_type": utility.utility_type,
                "period_start": utility.period_start.strftime("%Y-%m-%d") if utility.period_start else None,
                "period_end": utility.period_end.strftime("%Y-%m-%d") if utility.period_end else None,
                "total_amount": float(utility.total_amount) if utility.total_amount else 0,
                "total_days": total_days_in_period,
                "resident_count": resident_count,
                "total_resident_days": total_overlap_days,
                "avg_days_per_resident": round(avg_days_per_resident, 1),
                "amount_per_day": round(float(utility.total_amount) / total_overlap_days, 2) if total_overlap_days > 0 else 0,
                "amount_per_resident": round(float(utility.total_amount) / resident_count, 2) if resident_count > 0 else 0,
                "memo": utility.memo
            }
            
            utility_summaries.append(utility_summary)
            total_monthly_amount += float(utility.total_amount) if utility.total_amount else 0

        return {
            "room": {
                "id": str(room.id),
                "room_number": room.room_number,
                "building_name": room.building.name if room.building else None
            },
            "year": year,
            "month": month,
            "utilities": utility_summaries,
            "summary": {
                "total_utilities": len(utility_summaries),
                "total_amount": total_monthly_amount,
                "utility_types": list(set(u["utility_type"] for u in utility_summaries))
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"월간 공과금 요약 조회 중 오류가 발생했습니다: {str(e)}")

@router.get("/{room_id}/utilities/monthly-by-students/{year}/{month}")
def get_room_monthly_utilities_by_students(
    room_id: str,
    year: int,
    month: int,
    db: Session = Depends(get_db)
):
    """방별 월간 학생별 유틸리티 조회"""
    try:
        # 년월 유효성 검사
        if not (1 <= month <= 12):
            raise HTTPException(status_code=400, detail="월은 1-12 사이여야 합니다")
        
        # 방 존재 여부 확인
        room = db.query(Room).options(joinedload(Room.building)).filter(Room.id == room_id).first()
        if not room:
            raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다")

        # 해당 월의 시작일과 종료일 계산
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)

        # 해당 월의 모든 공과금 조회
        utilities = db.query(RoomUtility).filter(
            RoomUtility.room_id == room_id,
            RoomUtility.charge_month >= start_date,
            RoomUtility.charge_month <= end_date
        ).all()

        # 해당 방의 모든 거주 기록 조회
        residents = db.query(Resident).options(
            joinedload(Resident.student)
        ).filter(Resident.room_id == room_id).all()

        # 학생별 유틸리티 배분 계산
        student_allocations = []
        
        for resident in residents:
            if not resident.student:
                continue
                
            student_total = 0
            utility_details = []
            
            for utility in utilities:
                # 해당 학생의 거주 기간과 공과금 기간이 겹치는지 확인
                resident_start = resident.check_in_date
                resident_end = resident.check_out_date if resident.check_out_date else utility.period_end

                overlap_start = max(resident_start, utility.period_start)
                overlap_end = min(resident_end, utility.period_end)

                if overlap_start <= overlap_end:
                    overlap_days = (overlap_end - overlap_start).days + 1
                    
                    # 해당 공과금 기간 내 전체 거주자 일수 계산
                    total_resident_days = 0
                    for other_resident in residents:
                        other_start = other_resident.check_in_date
                        other_end = other_resident.check_out_date if other_resident.check_out_date else utility.period_end
                        
                        other_overlap_start = max(other_start, utility.period_start)
                        other_overlap_end = min(other_end, utility.period_end)
                        
                        if other_overlap_start <= other_overlap_end:
                            total_resident_days += (other_overlap_end - other_overlap_start).days + 1
                    
                    # 비율 계산 및 금액 배분
                    ratio = overlap_days / total_resident_days if total_resident_days > 0 else 0
                    amount = float(utility.total_amount) * ratio if utility.total_amount else 0
                    student_total += amount
                    
                    utility_details.append({
                        "utility_id": str(utility.id),
                        "utility_type": utility.utility_type,
                        "overlap_days": overlap_days,
                        "total_resident_days": total_resident_days,
                        "ratio": round(ratio, 4),
                        "amount": round(amount, 2)
                    })
            
            student_allocation = {
                "student_id": str(resident.resident_id),
                "student_name": resident.student.name,
                "check_in_date": resident.check_in_date.strftime("%Y-%m-%d") if resident.check_in_date else None,
                "check_out_date": resident.check_out_date.strftime("%Y-%m-%d") if resident.check_out_date else None,
                "is_active": resident.is_active,
                "utility_details": utility_details,
                "total_amount": round(student_total, 2)
            }
            student_allocations.append(student_allocation)

        return {
            "room": {
                "id": str(room.id),
                "room_number": room.room_number,
                "building_name": room.building.name if room.building else None
            },
            "year": year,
            "month": month,
            "students": student_allocations,
            "summary": {
                "total_students": len(student_allocations),
                "total_utilities": len(utilities),
                "total_amount": sum(s["total_amount"] for s in student_allocations)
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"월간 학생별 유틸리티 조회 중 오류가 발생했습니다: {str(e)}") 
    
@router.put("/{room_id}", response_model=RoomResponse)
def update_room(
    room_id: str,
    room_update: RoomUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    # 방 존재 여부 확인
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다")

    # 방 번호가 변경되는 경우 중복 확인
    if room_update.room_number and room_update.room_number != room.room_number:
        existing_room = db.query(Room).filter(
            Room.building_id == room.building_id,
            Room.room_number == room_update.room_number,
            Room.id != room_id
        ).first()
        
        if existing_room:
            raise HTTPException(status_code=400, detail="해당 빌딩에 같은 방 번호가 이미 존재합니다")

    # 정원 유효성 검사
    if room_update.capacity is not None and room_update.capacity <= 0:
        raise HTTPException(status_code=400, detail="정원은 1명 이상이어야 합니다")

    # 기존 값 저장 (로그용)
    old_values = {
        "building_id": str(room.building_id),
        "room_number": room.room_number,
        "rent": room.rent,
        "floor": room.floor,
        "capacity": room.capacity,
        "is_available": room.is_available,
        "note": room.note
    }
    
    # 방 정보 업데이트
    update_data = room_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(room, field, value)

    try:
        db.commit()
        db.refresh(room)
        
        # 로그 생성
        create_database_log(
            db=db,
            table_name="rooms",
            record_id=str(room.id),
            action="UPDATE",
            user_id=current_user["id"] if current_user else None,
            old_values=old_values,
            new_values={
                "building_id": str(room.building_id),
                "room_number": room.room_number,
                "rent": room.rent,
                "floor": room.floor,
                "capacity": room.capacity,
                "is_available": room.is_available,
                "note": room.note
            },
            changed_fields=list(update_data.keys()),
            note="部屋情報更新"
        )
        
        return room
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"방 정보 수정 중 오류가 발생했습니다: {str(e)}"
        )