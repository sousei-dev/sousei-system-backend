from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from typing import Optional, List
from database import SessionLocal
from models import RoomUtility, Student, Room, Resident
from schemas import RoomUtilityCreate, RoomUtilityUpdate
from datetime import datetime, date, timedelta
from database_log import create_database_log
from utils.dependencies import get_current_user
import uuid

router = APIRouter(prefix="/room-utilities", tags=["방 유틸리티 관리"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/", response_model=dict)
def create_room_utility(
    utility: RoomUtilityCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """방 공과금 등록"""
    # 방 존재 여부 확인
    room = db.query(Room).filter(Room.id == utility.room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다")

    # 날짜 형식 검증
    try:
        period_start = datetime.strptime(utility.period_start, "%Y-%m-%d").date()
        period_end = datetime.strptime(utility.period_end, "%Y-%m-%d").date()
        charge_month = datetime.strptime(utility.charge_month, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="날짜 형식이 올바르지 않습니다 (YYYY-MM-DD)")

    # 기간 유효성 검사
    if period_end <= period_start:
        raise HTTPException(status_code=400, detail="검침 종료일은 시작일보다 늦어야 합니다")

    # 해당 방의 같은 유형, 같은 청구 월에 이미 등록되어 있는지 확인하고 덮어쓰기
    existing_utility = db.query(RoomUtility).filter(
        RoomUtility.room_id == utility.room_id,
        RoomUtility.utility_type == utility.utility_type,
        RoomUtility.charge_month == charge_month
    ).first()
    
    if existing_utility:
        # 기존 데이터 업데이트
        existing_utility.period_start = period_start
        existing_utility.period_end = period_end
        existing_utility.usage = utility.usage
        existing_utility.unit_price = utility.unit_price
        existing_utility.total_amount = utility.total_amount
        existing_utility.memo = utility.memo
        
        db.commit()
        db.refresh(existing_utility)

        # 응답 데이터 준비
        response_data = {
          "id": str(existing_utility.id),
          "room_id": str(existing_utility.room_id),
          "utility_type": existing_utility.utility_type,
          "period_start": existing_utility.period_start,
          "period_end": existing_utility.period_end,
          "usage": float(existing_utility.usage) if existing_utility.usage else None,
          "unit_price": float(existing_utility.unit_price) if existing_utility.unit_price else None,
          "total_amount": float(existing_utility.total_amount) if existing_utility.total_amount else None,
          "charge_month": existing_utility.charge_month,
          "memo": existing_utility.memo,
          "created_at": existing_utility.created_at,
          "room": {
              "id": str(room.id),
              "room_number": room.room_number,
              "building_name": room.building.name if room.building else None
          }
        }
        
        return response_data

    try:
        # 공과금 등록
        new_utility = RoomUtility(
            id=str(uuid.uuid4()),
            room_id=utility.room_id,
            utility_type=utility.utility_type,
            period_start=period_start,
            period_end=period_end,
            usage=utility.usage,
            unit_price=utility.unit_price,
            total_amount=utility.total_amount,
            charge_month=charge_month,
            memo=utility.memo
        )
        db.add(new_utility)
        db.commit()
        db.refresh(new_utility)
        
        # 로그 생성
        create_database_log(
            db=db,
            table_name="room_utilities",
            record_id=str(new_utility.id),
            action="CREATE",
            user_id=current_user["id"] if current_user else None,
            new_values={
                "room_id": str(new_utility.room_id),
                "utility_type": new_utility.utility_type,
                "period_start": str(new_utility.period_start),
                "period_end": str(new_utility.period_end),
                "usage": float(new_utility.usage) if new_utility.usage else None,
                "unit_price": float(new_utility.unit_price) if new_utility.unit_price else None,
                "total_amount": float(new_utility.total_amount) if new_utility.total_amount else None,
                "charge_month": str(new_utility.charge_month),
                "memo": new_utility.memo
            },
            note="部屋光熱費登録"
        )

        # 응답 데이터 준비
        response_data = {
            "id": str(new_utility.id),
            "room_id": str(new_utility.room_id),
            "utility_type": new_utility.utility_type,
            "period_start": new_utility.period_start,
            "period_end": new_utility.period_end,
            "usage": float(new_utility.usage) if new_utility.usage else None,
            "unit_price": float(new_utility.unit_price) if new_utility.unit_price else None,
            "total_amount": float(new_utility.total_amount) if new_utility.total_amount else None,
            "charge_month": new_utility.charge_month,
            "memo": new_utility.memo,
            "created_at": new_utility.created_at,
            "room": {
                "id": str(room.id),
                "room_number": room.room_number,
                "building_name": room.building.name if room.building else None
            }
        }

        return response_data

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"공과금 등록 중 오류가 발생했습니다: {str(e)}"
        )


@router.get("/")
def get_room_utilities(
    room_id: Optional[str] = Query(None, description="방 ID로 필터링"),
    utility_type: Optional[str] = Query(None, description="공과금 유형으로 필터링"),
    charge_month: Optional[str] = Query(None, description="청구 월로 필터링 (YYYY-MM)"),
    page: int = Query(1, description="페이지 번호", ge=1),
    size: int = Query(10, description="페이지당 항목 수", ge=1, le=100),
    db: Session = Depends(get_db),
):
    """방 공과금 목록 조회"""
    # 기본 쿼리 생성
    query = db.query(RoomUtility).options(
        joinedload(RoomUtility.room).joinedload(Room.building)
    )

    # 필터 조건 추가
    if room_id:
        query = query.filter(RoomUtility.room_id == room_id)
    if utility_type:
        query = query.filter(RoomUtility.utility_type == utility_type)
    if charge_month:
        try:
            # YYYY-MM 형식으로 받아서 해당 월의 첫날로 변환
            year, month = charge_month.split("-")
            start_date = datetime(int(year), int(month), 1).date()
            if int(month) == 12:
                end_date = datetime(int(year) + 1, 1, 1).date() - timedelta(days=1)
            else:
                end_date = datetime(int(year), int(month) + 1, 1).date() - timedelta(days=1)
            
            query = query.filter(
                RoomUtility.charge_month >= start_date,
                RoomUtility.charge_month <= end_date
            )
        except ValueError:
            raise HTTPException(status_code=400, detail="청구 월 형식이 올바르지 않습니다 (YYYY-MM)")

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
            "room_id": str(utility.room_id),
            "utility_type": utility.utility_type,
            "period_start": utility.period_start.strftime("%Y-%m-%d"),
            "period_end": utility.period_end.strftime("%Y-%m-%d"),
            "usage": float(utility.usage) if utility.usage else None,
            "unit_price": float(utility.unit_price) if utility.unit_price else None,
            "total_amount": float(utility.total_amount) if utility.total_amount else None,
            "charge_month": utility.charge_month.strftime("%Y-%m-%d"),
            "memo": utility.memo,
            "created_at": utility.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "room": {
                "id": str(utility.room.id),
                "room_number": utility.room.room_number,
                "building_name": utility.room.building.name if utility.room.building else None
            }
        }
        result.append(utility_data)

    return {
        "items": result,
        "total": total_count,
        "total_pages": total_pages,
        "current_page": page
    }

@router.get("/{utility_id}")
def get_room_utility(utility_id: str, db: Session = Depends(get_db)):
    """특정 방 유틸리티 상세 정보 조회"""
    try:
        utility = db.query(RoomUtility).options(
            joinedload(RoomUtility.room)
        ).filter(RoomUtility.id == utility_id).first()
        
        if not utility:
            raise HTTPException(status_code=404, detail="방 유틸리티를 찾을 수 없습니다")
        
        utility_data = {
            "id": str(utility.id),
            "room_id": str(utility.room_id),
            "room_number": utility.room.room_number if utility.room else None,
            "utility_type": utility.utility_type,
            "start_date": utility.start_date,
            "end_date": utility.end_date,
            "total_amount": utility.total_amount,
            "description": utility.description,
            "status": utility.status,
            "created_at": utility.created_at
        }
        
        return utility_data
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"방 유틸리티 상세 정보 조회 중 오류가 발생했습니다: {str(e)}")

@router.put("/{utility_id}")
def update_room_utility(
    utility_id: str,
    utility_update: RoomUtilityUpdate,
    db: Session = Depends(get_db)
):
    """방 유틸리티 수정"""
    try:
        utility = db.query(RoomUtility).filter(RoomUtility.id == utility_id).first()
        if not utility:
            raise HTTPException(status_code=404, detail="방 유틸리티를 찾을 수 없습니다")
        
        # 업데이트할 필드들
        update_data = utility_update.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(utility, field, value)
        
        db.commit()
        db.refresh(utility)
        
        return {
            "message": "방 유틸리티가 성공적으로 수정되었습니다",
            "utility": {
                "id": str(utility.id),
                "room_id": str(utility.room_id),
                "utility_type": utility.utility_type,
                "start_date": utility.start_date,
                "end_date": utility.end_date,
                "total_amount": utility.total_amount,
                "description": utility.description,
                "status": utility.status
            }
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"방 유틸리티 수정 중 오류가 발생했습니다: {str(e)}")

# 이 API들은 rooms.py로 이동되었습니다
# @router.delete("/rooms/{room_id}/utilities/{utility_id}") - rooms.py에 있음
# @router.get("/rooms/{room_id}/utilities") - rooms.py에 있음

@router.get("/{utility_id}/residents-during-period")
def get_residents_during_utility_period(utility_id: str, db: Session = Depends(get_db)):
    """유틸리티 기간 동안의 거주자 조회"""
    try:
        utility = db.query(RoomUtility).filter(RoomUtility.id == utility_id).first()
        if not utility:
            raise HTTPException(status_code=404, detail="방 유틸리티를 찾을 수 없습니다")
        
        # 해당 기간 동안 방에 거주했던 학생들 조회
        residents = db.query(Student).filter(
            Student.current_room_id == utility.room_id
        ).all()
        
        result = []
        for resident in residents:
            resident_data = {
                "id": str(resident.id),
                "name": resident.name,
                "email": resident.email,
                "status": resident.status,
                "check_in_date": resident.entry_date,
                "current_room_id": str(resident.current_room_id) if resident.current_room_id else None
            }
            result.append(resident_data)
        
        return {
            "utility_id": utility_id,
            "utility_type": utility.utility_type,
            "start_date": utility.start_date,
            "end_date": utility.end_date,
            "total_amount": utility.total_amount,
            "residents": result,
            "total_residents": len(result)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"거주자 조회 중 오류가 발생했습니다: {str(e)}")

@router.post("/{utility_id}/calculate-allocation")
def calculate_utility_allocation(utility_id: str, db: Session = Depends(get_db)):
    """유틸리티 요금 배분 계산"""
    try:
        utility = db.query(RoomUtility).filter(RoomUtility.id == utility_id).first()
        if not utility:
            raise HTTPException(status_code=404, detail="방 유틸리티를 찾을 수 없습니다")
        
        # 해당 방에 거주 중인 학생들 조회
        residents = db.query(Student).filter(
            Student.current_room_id == utility.room_id,
            Student.status == "active"
        ).all()
        
        if not residents:
            return {
                "utility_id": utility_id,
                "message": "해당 방에 거주 중인 학생이 없습니다",
                "allocation": []
            }
        
        # 요금을 학생 수로 균등 배분
        total_amount = utility.total_amount
        resident_count = len(residents)
        amount_per_person = total_amount / resident_count
        
        allocation_result = []
        for resident in residents:
            allocation_data = {
                "student_id": str(resident.id),
                "student_name": resident.name,
                "allocated_amount": round(amount_per_person, 2),
                "utility_type": utility.utility_type,
                "period": f"{utility.start_date} ~ {utility.end_date}"
            }
            allocation_result.append(allocation_data)
        
        return {
            "utility_id": utility_id,
            "utility_type": utility.utility_type,
            "total_amount": total_amount,
            "resident_count": resident_count,
            "amount_per_person": round(amount_per_person, 2),
            "allocation": allocation_result
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"요금 배분 계산 중 오류가 발생했습니다: {str(e)}") 
    